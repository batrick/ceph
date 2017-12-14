#ifndef CEPH_CLIENT_DIR_H
#define CEPH_CLIENT_DIR_H

#include "InodeRef.h"

class Dir {
 public:
  InodeRef parent_inode;  // my inode
  ceph::unordered_map<string, Dentry*> dentries;
  vector<Dentry*> readdir_cache;

  Dir() = delete;
  explicit Dir(Inode *in) : parent_inode(in) {
    assert(parent_inode->dentries.size() < 2); // dirs can't be hard-linked
    if (!parent_inode->dentries.empty())
      parent_inode->get_first_parent()->get(); // pin dentry
  }
  ~Dir() {
    assert(is_empty());
    assert(parent_inode->dentries.size() < 2); // dirs can't be hard-linked
    if (!parent_inode->dentries.empty())
      parent_inode->get_first_parent()->put(); // unpin dentry
  }

  bool is_empty() const {
    return dentries.empty();
  }
};

#endif
