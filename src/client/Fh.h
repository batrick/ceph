#ifndef CEPH_CLIENT_FH_H
#define CEPH_CLIENT_FH_H

#include "common/Readahead.h"
#include "common/RefCountedObj.h"

#include "include/types.h"

#include "mds/flock.h"

#include "FhRef.h"
#include "InodeRef.h"
#include "UserPerm.h"

class Cond;
class Inode;

// file handle for any open file state

class Fh : public RefCountedObject {
public:
  static FhRef create(Inode *in, int flags, int cmode, const UserPerm &perms) {
    return FhRef(new Fh(in, flags, cmode, perms), false);
  }

  // IO error encountered by any writeback on this Inode while
  // this Fh existed (i.e. an fsync on another Fh will still show
  // up as an async_err here because it could have been the same
  // bytes we wrote via this Fh).
  int async_err = 0;

  int take_async_err()
  {
      int e = async_err;
      async_err = 0;
      return e;
  }

  InodeRef  inode;
  loff_t    pos = 0;
  int       mds = 0; // have to talk to mds we opened with (for now)
  int       mode; // the mode i opened the file with

  int flags;
  bool pos_locked = false;           // pos is currently in use
  std::list<Cond*> pos_waiters;   // waiters for pos

  UserPerm actor_perms; // perms I opened the file with

  Readahead readahead;

  // file lock
  std::unique_ptr<ceph_lock_state_t> fcntl_locks;
  std::unique_ptr<ceph_lock_state_t> flock_locks;

private:
  /* ctors/dtors hidden to enforce intrusive_ptr style allocation/free */
  Fh() = delete;
  explicit Fh(Inode *in, int flags, int cmode, const UserPerm &perms);
  ~Fh();

  xlist<Fh *>::item xlist_inode_item;
};

#endif
