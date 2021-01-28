// -*- mode:C++; tab-width:8; c-basic-offset:2; indent-tabs-mode:t -*-
// vim: ts=8 sw=2 smarttab

/*
 * Ceph - scalable distributed file system
 *
 * Copyright (C) 2021 Red Hat, Inc.
 *
 * This is free software; you can redistribute it and/or modify it under the
 * terms of the GNU Lesser General Public License version 2.1, as published by
 * the Free Software Foundation.  See file COPYING.
 *
 */

#include <boost/smart_ptr/intrusive_ptr.hpp>
#include <fmt/format.h>

#include <fcntl.h>
#include <stdio.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <unistd.h>

#include <iomanip>
#include <iostream>
#include <regex>
#include <sstream>
#include <string_view>

#include <limits.h>
#include <string.h>

#include <sqlite3ext.h>
SQLITE_EXTENSION_INIT1

#include "include/ceph_assert.h"
#include "include/rados/librados.hpp"

#include "common/Clock.h"
#include "common/ceph_argparse.h"
#include "common/ceph_mutex.h"
#include "common/common_init.h"
#include "common/config.h"
#include "common/debug.h"
#include "common/errno.h"
#include "common/version.h"

#include "include/libcephsqlite.h"
#include "SimpleRADOSStriper.h"

#define dout_subsys ceph_subsys_client
#undef dout_prefix
#define dout_prefix *_dout << "libcephsqlite: " << __func__ << ": "
#define d(vfs,lvl) ldout(getcct(vfs), (lvl)) << "(client." << getdata(vfs).cluster.get_instance_id() << ") "
#define dv(lvl) d(vfs,(lvl))
#define df(lvl) d(f->vfs,(lvl)) << f->loc << " "

using ceph::bufferlist;
using aiocompletionptr = std::unique_ptr<librados::AioCompletion>;

struct cephsqlite_appdata {
  boost::intrusive_ptr<CephContext> cct;
  librados::Rados cluster;
  struct sqlite3_vfs vfs{};
};

struct cephsqlite_fileloc {
  std::string pool;
  std::string radosns;
  std::string name;
};

struct cephsqlite_fileio {
  librados::IoCtx ioctx;
  SimpleRADOSStriper rs;
};

std::ostream& operator<<(std::ostream &out, const cephsqlite_fileloc& fileloc) {
  return out
    << "["
    << fileloc.pool
    << ":"
    << fileloc.radosns
    << "/"
    << fileloc.name
    << "]"
    ;
}

struct cephsqlite_file {
  sqlite3_file base;
  struct sqlite3_vfs* vfs = nullptr;
  int flags = 0;
  // There are 5 lock states: https://sqlite.org/c3ref/c_lock_exclusive.html
  int lock = 0;
  struct cephsqlite_fileloc loc{};
  struct cephsqlite_fileio io{};
};


#define getdata(vfs) (*((cephsqlite_appdata*)((vfs)->pAppData)))

static int initcluster(cephsqlite_appdata& appd)
{
  auto& cct = appd.cct;
  auto& cluster = appd.cluster;

  ldout(cct, 1) << "initializing RADOS handle" << dendl;
  if (int rc = cluster.init_with_context(cct.get()); rc < 0) {
    lderr(cct) << "cannot initialize RADOS: " << cpp_strerror(rc) << dendl;
    return rc;
  }
  if (int rc = cluster.connect(); rc < 0) {
    lderr(cct) << "cannot connect: " << cpp_strerror(rc) << dendl;
    return rc;
  }
  return 0;
}

static CephContext* getcct(sqlite3_vfs* vfs)
{
  auto&& appd = getdata(vfs);
  auto& cct = appd.cct;
  if (cct) {
    return cct.get();
  }

  /* bootstrap cct */
  CephInitParameters iparams(CEPH_ENTITY_TYPE_CLIENT);
  cct = boost::intrusive_ptr<CephContext>(common_preinit(iparams, CODE_ENVIRONMENT_LIBRARY, 0), false);
  cct->_conf.parse_config_files(nullptr, &std::cerr, 0);
  cct->_conf.parse_env(cct->get_module_type()); // environment variables override
  cct->_conf.apply_changes(nullptr);
  common_init_finish(cct.get());
  ldout(cct, 1) << "initialized with library context" << dendl;

  if (int rc = initcluster(appd); rc < 0) {
    ceph_abort(0);
  }

  return cct.get();
}

static int Lock(sqlite3_file *pFile, int eLock)
{
  auto f = (cephsqlite_file*)pFile;
  df(5) << std::hex << eLock << dendl;

  auto& lock = f->lock;
  ceph_assert(!f->io.rs.is_locked() || lock > SQLITE_LOCK_NONE);
  ceph_assert(lock <= eLock);
  if (!f->io.rs.is_locked() && eLock > SQLITE_LOCK_NONE) {
    if (int rc = f->io.rs.lock(0); rc < 0) {
      df(5) << "failed: " << rc << dendl;
      return SQLITE_IOERR;
    }
  }

  lock = eLock;
  return SQLITE_OK;
}

static int Unlock(sqlite3_file *pFile, int eLock)
{
  auto f = (cephsqlite_file*)pFile;
  df(5) << std::hex << eLock << dendl;

  auto& lock = f->lock;
  ceph_assert(lock == SQLITE_LOCK_NONE || (lock > SQLITE_LOCK_NONE && f->io.rs.is_locked()));
  ceph_assert(lock >= eLock);
  if (eLock <= SQLITE_LOCK_NONE && SQLITE_LOCK_NONE < lock) {
    if (int rc = f->io.rs.unlock(); rc < 0) {
      df(5) << "failed: " << rc << dendl;
      return SQLITE_IOERR;
    }
  }

  lock = eLock;
  return SQLITE_OK;
}

static int CheckReservedLock(sqlite3_file *pFile, int *pResOut)
{
  auto f = (cephsqlite_file*)pFile;
  df(5) << dendl;

  auto& lock = f->lock;
  if (lock > SQLITE_LOCK_SHARED) {
    *pResOut = 1;
  }

  df(10);
  f->io.rs.printlockers(*_dout);
  *_dout << dendl;

  *pResOut = 0;
  return SQLITE_OK;
}

static int Close(sqlite3_file *pFile)
{
  auto f = (cephsqlite_file*)pFile;
  df(5) << dendl;
  f->~cephsqlite_file();
  return SQLITE_OK;
}

static int Read(sqlite3_file *pFile, void *zBuf, int iAmt, sqlite_int64 iOfst)
{
  auto f = (cephsqlite_file*)pFile;
  df(5) << zBuf << " " << iOfst << "~" << iAmt << dendl;

  bufferlist bl;
  bufferptr bp = ceph::buffer::create_static(iAmt, (char*)zBuf);
  bl.push_back(std::move(bp));
  if (int rc = f->io.rs.read(zBuf, iAmt, iOfst); rc < 0) {
    df(5) << "read failed: " << cpp_strerror(rc) << dendl;
    return SQLITE_IOERR_READ;
  } else {
    df(5) << "= " << rc << dendl;
    if (rc < iAmt) {
      memset(zBuf, 0, iAmt-rc);
      return SQLITE_IOERR_SHORT_READ;
    } else {
      return SQLITE_OK;
    }
  }
}

static int Write(sqlite3_file *pFile, const void *zBuf, int iAmt, sqlite_int64 iOfst)
{
  auto f = (cephsqlite_file*)pFile;
  df(5) << iOfst << "~" << iAmt << dendl;

  auto aiocp = aiocompletionptr(librados::Rados::aio_create_completion());
  ceph::bufferlist bl;
  bl.append((const char*)zBuf, iAmt);
  if (int rc = f->io.rs.write(zBuf, iAmt, iOfst); rc < 0) {
    df(5) << "write failed: " << cpp_strerror(rc) << dendl;
    return SQLITE_IOERR_WRITE;
  } else {
    df(5) << "= " << rc << dendl;
    return SQLITE_OK;
  }

}

static int Truncate(sqlite3_file *pFile, sqlite_int64 size)
{
  auto f = (cephsqlite_file*)pFile;
  df(5) << size << dendl;

  if (int rc = f->io.rs.truncate(size); rc < 0) {
    df(5) << "truncate failed: " << cpp_strerror(rc) << dendl;
    return SQLITE_IOERR;
  }

  return SQLITE_OK;
}

static int Sync(sqlite3_file *pFile, int flags)
{
  auto f = (cephsqlite_file*)pFile;
  df(5) << flags << dendl;

  if (int rc = f->io.rs.flush(); rc < 0) {
    df(5) << "failed: " << cpp_strerror(rc) << dendl;
    return SQLITE_IOERR;
  }

  df(5) << " = 0" << dendl;

  return SQLITE_OK;
}


static int FileSize(sqlite3_file *pFile, sqlite_int64 *pSize)
{
  auto f = (cephsqlite_file*)pFile;
  df(5) << dendl;

  uint64_t size = 0;
  if (int rc = f->io.rs.stat(&size); rc < 0) {
    df(5) << "stat failed: " << cpp_strerror(rc) << dendl;
    return SQLITE_NOTFOUND;
  }

  *pSize = (sqlite_int64)size;

  df(5) << "= " << size << dendl;

  return SQLITE_OK;
}


static bool parsepath(std::string_view path, struct cephsqlite_fileloc* fileloc)
{
  static const std::regex re1{"^/*(\\*[[:digit:]]+):([[:alnum:]-_.]*)/([[:alnum:]-._]+)$"};
  static const std::regex re2{"^/*([[:alnum:]-_.]+):([[:alnum:]-_.]*)/([[:alnum:]-._]+)$"};

  std::cmatch cm;
  if (!std::regex_match(path.data(), cm, re1)) {
    if (!std::regex_match(path.data(), cm, re2)) {
      return false;
    }
  }
  fileloc->pool = cm[1];
  fileloc->radosns = cm[2];
  fileloc->name = cm[3];

  return true;
}

static int makestriper(sqlite3_vfs* vfs, const cephsqlite_fileloc& loc, cephsqlite_fileio* io)
{
  auto& cluster = getdata(vfs).cluster;
  bool gotmap = false;

  dv(10) << loc << dendl;

enoent_retry:
  if (loc.pool[0] == '*') {
    std::string err;
    int64_t id = strict_strtoll(loc.pool.c_str()+1, 10, &err);
    ceph_assert(err.empty());
    if (int rc = cluster.ioctx_create2(id, io->ioctx); rc < 0) {
      if (rc == -ENOENT && !gotmap) {
        cluster.wait_for_latest_osdmap();
        gotmap = true;
        goto enoent_retry;
      }
      dv(10) << "cannot create ioctx: " << cpp_strerror(rc) << dendl;
      return rc;
    }
  } else {
    if (int rc = cluster.ioctx_create(loc.pool.c_str(), io->ioctx); rc < 0) {
      if (rc == -ENOENT && !gotmap) {
        cluster.wait_for_latest_osdmap();
        gotmap = true;
        goto enoent_retry;
      }
      dv(10) << "cannot create ioctx: " << cpp_strerror(rc) << dendl;
      return rc;
    }
  }

  if (!loc.radosns.empty())
    io->ioctx.set_namespace(loc.radosns);

  io->rs = SimpleRADOSStriper(io->ioctx, loc.name);

  return 0;
}

static int SectorSize(sqlite3_file* sf)
{
  static const int size = 65536;
  auto f = (cephsqlite_file*)sf;
  df(5) << " = " << size << dendl;
  return size;
}

static int FileControl(sqlite3_file* sf, int op, void *pArg)
{
  auto f = (cephsqlite_file*)sf;
  df(5) << op << ", " << pArg << dendl;
  return SQLITE_NOTFOUND;
}

static int DeviceCharacteristics(sqlite3_file* sf)
{
  auto f = (cephsqlite_file*)sf;
  df(5) << dendl;
  static const int c = 0
      |SQLITE_IOCAP_ATOMIC
      |SQLITE_IOCAP_POWERSAFE_OVERWRITE
      |SQLITE_IOCAP_UNDELETABLE_WHEN_OPEN
      |SQLITE_IOCAP_SAFE_APPEND
      ;
  return c;
}

static bool ends_with(std::string_view s, std::string_view suffix)
{
  return s.size() >= suffix.size() &&
      s.compare(s.size()-suffix.size(), suffix.size(), suffix) == 0;
}


static int Open(
  sqlite3_vfs *vfs,              /* VFS */
  const char *zName,              /* File to open, or 0 for a temp file */
  sqlite3_file *pFile,            /* Pointer to DemoFile struct to populate */
  int flags,                      /* Input SQLITE_OPEN_XXX flags */
  int *pOutFlags                  /* Output SQLITE_OPEN_XXX flags (or NULL) */
)
{
  static const sqlite3_io_methods io = {
    1,                        /* iVersion */
    Close,                    /* xClose */
    Read,                     /* xRead */
    Write,                    /* xWrite */
    Truncate,                 /* xTruncate */
    Sync,                     /* xSync */
    FileSize,                 /* xFileSize */
    Lock,                     /* xLock */
    Unlock,                   /* xUnlock */
    CheckReservedLock,        /* xCheckReservedLock */
    FileControl,              /* xFileControl */
    SectorSize,               /* xSectorSize */
    DeviceCharacteristics     /* xDeviceCharacteristics */
  };

  bool gotmap = false;
  auto& cluster = getdata(vfs).cluster;

  /* we are not going to create temporary files */
  if (zName == NULL) {
    dv(5) << " cannot open memory file" << dendl;
    return SQLITE_CANTOPEN;
  }
  auto path = std::string_view(zName);
  if (path == ":memory:"sv) {
    dv(5) << " cannot open memory file" << dendl;
    return SQLITE_IOERR;
  } else if (ends_with(path, "-wal"sv)) {
    dv(5) << " wal journals are always ignored" << dendl;
    return SQLITE_CANTOPEN;
  }

  dv(5) << path << " flags=" << std::hex << flags << dendl;

  auto f = new (pFile)cephsqlite_file();
  f->vfs = vfs;
  if (!parsepath(path, &f->loc)) {
    ceph_assert(0); /* xFullPathname validates! */
  }
  f->flags = flags;

enoent_retry:
  if (int rc = makestriper(vfs, f->loc, &f->io); rc < 0) {
    f->~cephsqlite_file();
    dv(5) << "cannot open striper" << dendl;
    return SQLITE_IOERR;
  }

  if (flags & SQLITE_OPEN_CREATE) {
    dv(10) << "OPEN_CREATE" << dendl;
    if (int rc = f->io.rs.create(); rc < 0 && rc != -EEXIST) {
      if (rc == -ENOENT && !gotmap) {
        /* we may have an out of date OSDMap which cancels the op in the
         * Objecter. Try to get a new one and retry. This is mostly noticable
         * in testing when pools are getting created/deleted left and right.
         */
        dv(5) << "retrying create after getting latest OSDMap" << dendl;
        cluster.wait_for_latest_osdmap();
        gotmap = true;
        goto enoent_retry;
      }
      dv(5) << "file cannot be created: " << cpp_strerror(rc) << dendl;
      return SQLITE_IOERR;
    }
  }

  if (int rc = f->io.rs.open(); rc < 0) {
    if (rc == -ENOENT && !gotmap) {
      /* See comment above for create case. */
      dv(5) << "retrying open after getting latest OSDMap" << dendl;
      cluster.wait_for_latest_osdmap();
      gotmap = true;
      goto enoent_retry;
    }
    dv(10) << "cannot open striper: " << cpp_strerror(rc) << dendl;
    return rc;
  }

  if (pOutFlags) {
    *pOutFlags = flags;
  }
  f->base.pMethods = &io;
  return SQLITE_OK;
}

/*
** Delete the file identified by argument zPath. If the dirSync parameter
** is non-zero, then ensure the file-system modification to delete the
** file has been synced to disk before returning.
*/
static int Delete(sqlite3_vfs* vfs, const char* zPath, int dirSync)
{
  dv(5) << "'" << zPath << "', " << dirSync << dendl;

  cephsqlite_fileloc fileloc;
  if (!parsepath(zPath, &fileloc)) {
    dv(5) << "path does not parse!" << dendl;
    return SQLITE_NOTFOUND;
  }

  cephsqlite_fileio io;
  if (int rc = makestriper(vfs, fileloc, &io); rc < 0) {
    dv(5) << "cannot open striper" << dendl;
    return SQLITE_IOERR;
  }

  if (int rc = io.rs.lock(0); rc < 0) {
    return SQLITE_IOERR;
  }

  if (int rc = io.rs.open(); rc < 0) {
    dv(10) << "cannot open striper: " << cpp_strerror(rc) << dendl;
    return SQLITE_IOERR;
  }

  if (int rc = io.rs.remove(); rc < 0) {
    dv(5) << "= " << rc << dendl;
    return SQLITE_IOERR_DELETE;
  }
  dv(5) << "= 0" << dendl;

  return SQLITE_OK;
}

/*
** Query the file-system to see if the named file exists, is readable or
** is both readable and writable.
*/
static int Access(sqlite3_vfs* vfs, const char* zPath, int flags, int* pResOut)
{
  dv(5) << zPath << " " << std::hex << flags << dendl;

  cephsqlite_fileloc fileloc;
  if (!parsepath(zPath, &fileloc)) {
    dv(5) << "path does not parse!" << dendl;
    return SQLITE_NOTFOUND;
  }

  if (ends_with(fileloc.name, "-wal"sv)) {
    dv(5) << " wal journals are always ignored" << dendl;
    *pResOut = 0;
    return SQLITE_OK;
  }

  cephsqlite_fileio io;
  if (int rc = makestriper(vfs, fileloc, &io); rc < 0) {
    dv(5) << "cannot open striper" << dendl;
    return SQLITE_IOERR;
  }

  if (int rc = io.rs.open(); rc < 0) {
    if (rc == -ENOENT) {
      *pResOut = 0;
      return SQLITE_OK;
    } else {
      dv(10) << "cannot open striper: " << cpp_strerror(rc) << dendl;
      *pResOut = 0;
      return SQLITE_IOERR;
    }
  }

  uint64_t size = 0;
  if (int rc = io.rs.stat(&size); rc < 0) {
    dv(5) << "= " << rc << " (" << cpp_strerror(rc) << ")" << dendl;
    *pResOut = 0;
  } else {
    dv(5) << "= 0" << dendl;
    *pResOut = 1;
  }

  return SQLITE_OK;
}

/* This method is only called once for each database. It provides a chance to
 * reformat the path into a canonical format.
 */
static int FullPathname(sqlite3_vfs* vfs, const char* zPath, int nPathOut, char* zPathOut)
{
  auto path = std::string_view(zPath);

  dv(5) << "1: " <<  path << dendl;

  cephsqlite_fileloc fileloc;
  if (!parsepath(path, &fileloc)) {
    dv(5) << "path does not parse!" << dendl;
    return SQLITE_NOTFOUND;
  }
  dv(5) << " parsed " << fileloc << dendl;

  auto p = fmt::format("{}:{}/{}", fileloc.pool, fileloc.radosns, fileloc.name);
  if (p.size() >= (size_t)nPathOut) {
    dv(5) << "path too long!" << dendl;
    return SQLITE_CANTOPEN;
  }
  strcpy(zPathOut, p.c_str());
  dv(5) << " output " << p << dendl;

  return SQLITE_OK;
}

static int CurrentTime(sqlite3_vfs* vfs, sqlite3_int64* pTime)
{
  dv(5) << pTime << dendl;

  auto t = ceph_clock_now();
  *pTime = t.to_msec() + 2440587.5;
  return SQLITE_OK;
}

LIBCEPHSQLITE_API int cephsqlite_setcct(CephContext* cct, char** ident)
{
  ldout(cct, 1) << cct << dendl;

  if (sqlite3_api == nullptr) {
    lderr(cct) << "API violation: must have sqlite3 init libcephsqlite" << dendl;
    return -EINVAL;
  }

  auto vfs = sqlite3_vfs_find("ceph");
  if (!vfs) {
    lderr(cct) << "API violation: must have sqlite3 init libcephsqlite" << dendl;
    return -EINVAL;
  }

  auto &appd = getdata(vfs);
  appd.cct = cct;
  if (int rc = initcluster(appd); rc < 0) {
    appd.cct = nullptr;
    return rc;
  }

  auto s = appd.cluster.get_addrs();
  ldout(cct, 5) << "my addr is " << s << dendl;
  if (ident) {
    *ident = strdup(s.c_str());
  }

  ldout(cct, 1) << "complete" << dendl;

  return 0;
}

LIBCEPHSQLITE_API int sqlite3_cephsqlite_init(sqlite3* db, char** err, const sqlite3_api_routines* api)
{
  SQLITE_EXTENSION_INIT2(api);

  if (sqlite3_vfs_find("ceph")) {
    return SQLITE_OK_LOAD_PERMANENTLY;
  }

  auto appd = new cephsqlite_appdata;

  auto vfs = &appd->vfs;
  vfs->iVersion = 2;
  vfs->szOsFile = sizeof(struct cephsqlite_file);
  vfs->mxPathname = 4096;
  vfs->zName = "ceph";
  vfs->pAppData = appd;
  vfs->xOpen = Open;
  vfs->xDelete = Delete;
  vfs->xAccess = Access;
  vfs->xFullPathname = FullPathname;
  vfs->xCurrentTimeInt64 = CurrentTime;

  appd->cct = nullptr;
  sqlite3_vfs_register(vfs, 0);

  return SQLITE_OK_LOAD_PERMANENTLY;
}
