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

#include "include/ceph_assert.h"
#include "include/rados/librados.hpp"

#include "common/ceph_argparse.h"
#include "common/ceph_mutex.h"
#include "common/common_init.h"
#include "common/config.h"
#include "common/debug.h"
#include "common/errno.h"
#include "common/version.h"

#include "SimpleRADOSStriper.h"

using ceph::bufferlist;

#define dout_subsys ceph_subsys_client
#undef dout_prefix
#define dout_prefix *_dout << "client." << ioctx.get_instance_id() << ": SimpleRADOSStriper: " << __func__ << ": " << oid << ": "
#define d(lvl) ldout((CephContext*)ioctx.cct(), (lvl))

SimpleRADOSStriper::~SimpleRADOSStriper()
{
  if (ioctx.is_valid()) {
    d(5) << dendl;

    if (is_locked()) {
      unlock();
    }
  }
}

SimpleRADOSStriper::extent SimpleRADOSStriper::getnextextent(size_t len, uint64_t off) const
{
  extent e;
  {
    uint64_t stripe = (off>>object_size);
    CachedStackStringStream css;
    *css << oid;
    *css << ".";
    *css << std::setw(16) << std::setfill('0') << std::hex << stripe;
    e.soid = css->str();
  }
  e.off = off & ((1<<object_size)-1);
  e.len = std::min<size_t>(len, (1<<object_size)-e.off);
  return e;
}

int SimpleRADOSStriper::remove()
{
  d(5) << dendl;

  if (auto rc = ioctx.aio_flush(); rc) {
    d(5) << " aio_flush failed: " << cpp_strerror(rc) << dendl;
    return rc;
  }

  if (int rc = setmeta(0, true); rc < 0) {
    return rc;
  }

  auto ext = getfirstextent();
  if (int rc = ioctx.remove(ext.soid); rc < 0) {
    d(5) << " remove failed: " << cpp_strerror(rc) << dendl;
    return rc;
  }

  locked = false;

  return 0;
}

int SimpleRADOSStriper::truncate(uint64_t size)
{
  d(5) << size << dendl;

  /* TODO: (not currently used by SQLite) handle growth + sparse */
  if (int rc = setmeta(size, true); rc < 0) {
    return rc;
  }

  return 0;
}

int SimpleRADOSStriper::flush()
{
  d(5) << dendl;

  if (size_dirty) {
    if (int rc = setmeta(size, true); rc < 0) {
      return rc;
    }
  }

  for (auto& aiocp : updates) {
    if (int rc = aiocp->wait_for_complete(); rc < 0) {
      d(5) << " update failed: " << cpp_strerror(rc) << dendl;
      return rc;
    }
  }
  updates.clear();

  if (auto rc = ioctx.aio_flush(); rc) {
    d(5) << " aio_flush failed: " << cpp_strerror(rc) << dendl;
    return rc;
  }
  return 0;
}

int SimpleRADOSStriper::stat(uint64_t* s)
{
  d(5) << dendl;

  *s = size;
  return 0;
}

int SimpleRADOSStriper::create()
{
  d(5) << dendl;

  auto ext = getfirstextent();
  auto op = librados::ObjectWriteOperation();
  /* exclusive create ensures we do none of these setxattrs happen if it fails */
  op.create(1);
  op.setxattr(XATTR_VERSION, uint2bl(0));
  op.setxattr(XATTR_SIZE, uint2bl(0));
  op.setxattr(XATTR_ALLOCATED, uint2bl(0));
  op.setxattr(XATTR_LAYOUT_STRIPE_UNIT, uint2bl(1));
  op.setxattr(XATTR_LAYOUT_STRIPE_COUNT, uint2bl(1));
  op.setxattr(XATTR_LAYOUT_OBJECT_SIZE, uint2bl(1<<object_size));
  if (int rc = ioctx.operate(ext.soid, &op); rc < 0) {
    return rc; /* including EEXIST */
  }
  return 0;
}

int SimpleRADOSStriper::open()
{
  d(5) << oid << dendl;

  auto ext = getfirstextent();
  auto op = librados::ObjectReadOperation();
  bufferlist bl_size, bl_alloc, bl_version, pbl;
  int prval_size, prval_alloc, prval_version;
  op.getxattr(XATTR_SIZE, &bl_size, &prval_size);
  op.getxattr(XATTR_ALLOCATED, &bl_alloc, &prval_alloc);
  op.getxattr(XATTR_VERSION, &bl_version, &prval_version);
  if (int rc = ioctx.operate(ext.soid, &op, &pbl); rc < 0) {
    d(5) << " getxattr failed: " << cpp_strerror(rc) << dendl;
    return rc;
  }
  {
    auto sstr = bl_size.to_str();
    std::string err;
    size = strict_strtoll(sstr.c_str(), 10, &err);
    ceph_assert(err.empty());
  }
  {
    auto sstr = bl_alloc.to_str();
    std::string err;
    allocated = strict_strtoll(sstr.c_str(), 10, &err);
    ceph_assert(err.empty());
  }
  {
    auto sstr = bl_version.to_str();
    std::string err;
    version = strict_strtoll(sstr.c_str(), 10, &err);
    ceph_assert(err.empty());
  }
  d(15) << " size: " << size << " allocated: " << allocated << " version: " << version << dendl;
  return 0;
}

int SimpleRADOSStriper::allocshrink(uint64_t a)
{
  d(5) << dendl;
  std::vector<aiocompletionptr> removes;

  ceph_assert(a <= allocated);
  uint64_t prune = std::max<uint64_t>(a, (1<<object_size)); /* never delete first extent here */
  uint64_t n = allocated-prune;
  uint64_t o = prune;
  while (n > 0) {
    auto ext = getnextextent(n, o);
    auto aiocp = aiocompletionptr(librados::Rados::aio_create_completion());
    if (int rc = ioctx.aio_remove(ext.soid, aiocp.get()); rc < 0) {
      d(5) << " aio_remove failed: " << cpp_strerror(rc) << dendl;
      return rc;
    }
    removes.emplace_back(std::move(aiocp));
    n -= ext.len;
    o += ext.len;
  }

  for (auto& aiocp : removes) {
    if (int rc = aiocp->wait_for_complete(); rc < 0 && rc != -ENOENT) {
      d(5) << " aio_remove failed: " << cpp_strerror(rc) << dendl;
      return rc;
    }
  }

  auto ext = getfirstextent();
  auto op = librados::ObjectWriteOperation();
  auto aiocp = aiocompletionptr(librados::Rados::aio_create_completion());
  op.setxattr(XATTR_ALLOCATED, uint2bl(a));
  d(15) << " updating allocated to " << a << dendl;
  op.setxattr(XATTR_VERSION, uint2bl(version+1));
  d(15) << " updating version to " << (version+1) << dendl;
  if (int rc = ioctx.aio_operate(ext.soid, aiocp.get(), &op); rc < 0) {
    d(5) << " update failed: " << cpp_strerror(rc) << dendl;
    return rc;
  }
  /* we need to wait so we don't have dangling extents */
  d(10) << " waiting for allocated update" << dendl;
  if (int rc = aiocp->wait_for_complete(); rc < 0) {
    d(1) << " update failure: " << cpp_strerror(rc) << dendl;
    return rc;
  }
  version += 1;
  allocated = a;
  return 0;
}

int SimpleRADOSStriper::maybeallocshrink()
{
  d(15) << dendl;

  if (size == 0) {
    if (allocated > 0) {
      d(10) << "allocation shrink to 0" << dendl;
      return allocshrink(0);
    } else {
      return 0;
    }
  }

  uint64_t mask = (1<<object_size)-1;
  uint64_t new_allocated = min_growth + ((size + mask) & ~mask); /* round up base 2 */
  if (allocated > new_allocated && ((allocated-new_allocated) > min_growth)) {
    d(10) << "allocation shrink to " << new_allocated << dendl;
    return allocshrink(new_allocated);
  }

  return 0;
}

bufferlist SimpleRADOSStriper::uint2bl(uint64_t v)
{
  CachedStackStringStream css;
  *css << std::dec << std::setw(16) << std::setfill('0') << v;
  bufferlist bl;
  bl.append(css->strv());
  return bl;
}

int SimpleRADOSStriper::setmeta(uint64_t new_size, bool update_size)
{
  d(10) << " new_size: " << new_size
        << " update_size: " << update_size
        << " allocated: " << allocated
        << " size: " << size
        << " version: " << version
        << dendl;

  bool do_op = false;
  auto new_allocated = allocated;
  auto ext = getfirstextent();
  auto op = librados::ObjectWriteOperation();
  if (new_size > allocated) {
    uint64_t mask = (1<<object_size)-1;
    new_allocated = min_growth + ((size + mask) & ~mask); /* round up base 2 */
    op.setxattr(XATTR_ALLOCATED, uint2bl(new_allocated));
    do_op = true;
    d(15) << " updating allocated to " << new_allocated << dendl;
  }
  if (update_size) {
    op.setxattr(XATTR_SIZE, uint2bl(new_size));
    do_op = true;
    d(15) << " updating size to " << new_size << dendl;
  }
  if (do_op) {
    op.setxattr(XATTR_VERSION, uint2bl(version+1));
    d(15) << " updating version to " << (version+1) << dendl;
    auto aiocp = aiocompletionptr(librados::Rados::aio_create_completion());
    if (int rc = ioctx.aio_operate(ext.soid, aiocp.get(), &op); rc < 0) {
      d(1) << " update failure: " << cpp_strerror(rc) << dendl;
      return rc;
    }
    version += 1;
    if (allocated != new_allocated) {
      /* we need to wait so we don't have dangling extents */
      d(10) << "waiting for allocated update" << dendl;
      if (int rc = aiocp->wait_for_complete(); rc < 0) {
        d(1) << " update failure: " << cpp_strerror(rc) << dendl;
        return rc;
      }
      aiocp.reset();
      allocated = new_allocated;
    }
    if (aiocp) {
      updates.emplace_back(std::move(aiocp));
    }
    if (update_size) {
      size = new_size;
      size_dirty = false;
      return maybeallocshrink();
    }
  }
  return 0;
}

ssize_t SimpleRADOSStriper::write(const void* data, size_t len, uint64_t off)
{
  d(5) << off << "~" << len << dendl;

  if (allocated < (len+off)) {
    if (int rc = setmeta(len+off, false); rc < 0) {
      return rc;
    }
  }
    
  size_t w = 0;
  while ((len-w) > 0) {
    auto ext = getnextextent(len-w, off+w);
    auto aiocp = aiocompletionptr(librados::Rados::aio_create_completion());
    bufferlist bl;
    bl.append((const char*)data+w, ext.len);
    if (int rc = ioctx.aio_write(ext.soid, aiocp.get(), bl, ext.len, ext.off); rc < 0) {
      break;
    }
    updates.emplace_back(std::move(aiocp));
    w += ext.len;
  }

  if (size < (len+off)) {
    size = len+off;
    size_dirty = true;
    d(10) << " dirty size: " << size << dendl;
  }

  return (ssize_t)w;
}

ssize_t SimpleRADOSStriper::read(void* data, size_t len, uint64_t off)
{
  d(5) << off << "~" << len << dendl;

  size_t r = 0;
  std::vector<std::pair<bufferlist, aiocompletionptr>> reads;
  while ((len-r) > 0) {
    auto ext = getnextextent(len-r, off+r);
    auto& [bl, aiocp] = reads.emplace_back();
    aiocp = aiocompletionptr(librados::Rados::aio_create_completion());
    if (int rc = ioctx.aio_read(ext.soid, aiocp.get(), &bl, ext.len, ext.off); rc < 0) {
      d(1) << " read failure: " << cpp_strerror(rc) << dendl;
      return rc;
    }
    r += ext.len;
  }

  r = 0;
  for (auto& [bl, aiocp] : reads) {
    if (int rc = aiocp->wait_for_complete(); rc < 0) {
      d(1) << " read failure: " << cpp_strerror(rc) << dendl;
      return rc;
    }
    bl.begin().copy(bl.length(), ((char*)data)+r);
    r += bl.length();
  }
  ceph_assert(r <= len);

  return r;
}

int SimpleRADOSStriper::printlockers(std::ostream& out)
{
  int exclusive;
  std::string tag;
  std::list<librados::locker_t> lockers;
  auto ext = getfirstextent();
  if (int rc = ioctx.list_lockers(ext.soid, biglock, &exclusive, &tag, &lockers); rc < 0) {
    d(1) << " list_lockers failure: " << cpp_strerror(rc) << dendl;
    return rc;
  }
  if (lockers.empty()) {
    out << " lockers none";
  } else {
    out << " lockers exclusive=" << exclusive  << " tag=" << tag << " lockers=[";
    bool first = true;
    for (const auto& l : lockers) {
      if (!first) out << ",";
      out << l.client << ":" << l.cookie << ":" << l.address;
    }
    out << "]";
  }
  return 0;
}

int SimpleRADOSStriper::lock(uint64_t timeoutms)
{
  d(5) << "timeout=" << timeoutms << dendl;

  /* We're going to be very lazy here in implementation: only exclusive locks
   * are allowed. That even ensures a single reader.
   */
  uint64_t slept = 0;

  auto ext = getfirstextent();
  while (true) {
    int rc = ioctx.lock_exclusive(ext.soid, biglock, cookie.to_string(), lockdesc, nullptr, 0);
    if (rc == 0) {
      locked = true;
      break;
    } else if (rc == -EBUSY) {
      if ((slept % 500000) == 0) {
        d(10);
        printlockers(*_dout);
        *_dout << dendl;
      }
      usleep(5000);
      slept += 5000;
      continue;
    } else {
      d(5) << " lock failed: " << cpp_strerror(rc) << dendl;
      return rc;
    }
  }

  if (int rc = open(); rc < 0) {
    d(5) << " open failed: " << cpp_strerror(rc) << dendl;
    return rc;
  }

  d(5) << " = 0" << dendl;

  return 0;
}

int SimpleRADOSStriper::unlock()
{
  d(5) << dendl;

  ceph_assert(is_locked());

  /* wait for flush of metadata */
  if (int rc = flush(); rc < 0) {
    return rc;
  }

  auto ext = getfirstextent();
  if (int rc = ioctx.unlock(ext.soid, biglock, cookie.to_string()); rc < 0) {
    d(5) << " unlock failed: " << cpp_strerror(rc) << dendl;
    return rc;
  }
  locked = false;

  d(5) << " = 0" << dendl;

  return 0;
}
