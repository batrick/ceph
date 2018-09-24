// -*- mode:C++; tab-width:8; c-basic-offset:2; indent-tabs-mode:t -*-
// vim: ts=8 sw=2 smarttab
/*
 * Mount, create a file, and then die leaving the session out there. When
 *
 * (c) 2017, Jeff Layton <jlayton@redhat.com>
 */

#include "include/cephfs/libcephfs.h"
#include <errno.h>

#define	CEPHFS_RECLAIM_TIMEOUT		60

int main(int argc, char **argv)
{
  struct ceph_mount_info *cmount;

  /* Caller must pass in the uuid */
  if (argc < 2)
    return 1;

  if (ceph_create(&cmount, nullptr) != 0)
    return 1;

  if (ceph_conf_read_file(cmount, nullptr) != 0)
    return 1;

  if (ceph_conf_parse_env(cmount, nullptr) != 0)
    return 1;

  if (ceph_init(cmount) != 0)
    return 1;

  ceph_set_session_timeout(cmount, CEPHFS_RECLAIM_TIMEOUT);

  if (ceph_start_reclaim(cmount, argv[1], CEPH_RECLAIM_RESET) != -ENOENT)
    return 1;

  ceph_set_uuid(cmount, argv[1]);

  if (ceph_mount(cmount, "/") != 0)
    return 1;

  Inode *root, *file;
  if (ceph_ll_lookup_root(cmount, &root) != 0)
    return 1;

  Fh *fh;
  struct ceph_statx stx;
  UserPerm *perms = ceph_mount_perms(cmount);

  if (ceph_ll_create(cmount, root, argv[1], 0666, O_RDWR|O_CREAT|O_EXCL,
		      &file, &fh, &stx, 0, 0, perms) != 0)
    return 1;

  return 0;
}
