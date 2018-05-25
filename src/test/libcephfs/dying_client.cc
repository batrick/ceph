// -*- mode:C++; tab-width:8; c-basic-offset:2; indent-tabs-mode:t -*-
// vim: ts=8 sw=2 smarttab
/*
 * Mount, create a file, and then die leaving the session out there. When
 *
 * (c) 2017, Jeff Layton <jlayton@redhat.com>
 */

#include "gtest/gtest.h"
#include "include/cephfs/libcephfs.h"
#include "include/stat.h"
#include <errno.h>
#include <fcntl.h>
#include <unistd.h>
#include <sys/types.h>
#include <sys/stat.h>
#include <dirent.h>
#include <sys/xattr.h>
#include <sys/uio.h>

#ifdef __linux__
#include <limits.h>
#endif

#include <map>
#include <vector>
#include <thread>
#include <atomic>

#define	CEPHFS_RECLAIM_TIMEOUT		60

int main(int argc, char **argv)
{
  struct ceph_mount_info *cmount;

  /* Caller must pass in the uuid */
  assert(argc >= 1);

  assert(ceph_create(&cmount, NULL) == 0);
  assert(ceph_conf_read_file(cmount, NULL) == 0);
  assert(ceph_conf_parse_env(cmount, NULL) == 0);
  assert(ceph_init(cmount) == 0);
  ceph_set_session_timeout(cmount, CEPHFS_RECLAIM_TIMEOUT);
  assert(ceph_start_reclaim(cmount, argv[1], CEPH_RECLAIM_RESET) == -ENOENT);
  ceph_set_uuid(cmount, argv[1]);
  assert(ceph_mount(cmount, "/") == 0);

  Inode *root, *file;
  assert(ceph_ll_lookup_root(cmount, &root) == 0);

  Fh *fh;
  struct ceph_statx stx;
  UserPerm *perms = ceph_mount_perms(cmount);

  assert(ceph_ll_create(cmount, root, argv[1], 0666,
	    O_RDWR|O_CREAT|O_EXCL, &file, &fh, &stx, 0, 0, perms) == 0);
  return 0;
}
