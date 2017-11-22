
// -*- mode:C++; tab-width:8; c-basic-offset:2; indent-tabs-mode:t -*-
// vim: ts=8 sw=2 smarttab
/*
 * Ceph - scalable distributed file system
 *
 * Copyright (C) 2017 Red Hat Inc
 *
 * This is free software; you can redistribute it and/or
 * modify it under the terms of the GNU Lesser General Public
 * License version 2.1, as published by the Free Software
 * Foundation.  See file COPYING.
 *
 */


#include "Inode.h"

#include "Fh.h"

Fh::Fh(Inode *in, int flags, int cmode, const UserPerm &perms) :
    inode(in), mode(cmode), flags(flags),
    actor_perms(perms), readahead(), xlist_inode_item(this)
{
  in->fhs.push_back(&xlist_inode_item);
}

Fh::~Fh()
{
  xlist_inode_item.remove_myself();
}

