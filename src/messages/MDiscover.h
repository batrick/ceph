// -*- mode:C++; tab-width:8; c-basic-offset:2; indent-tabs-mode:t -*- 
// vim: ts=8 sw=2 smarttab
/*
 * Ceph - scalable distributed file system
 *
 * Copyright (C) 2004-2006 Sage Weil <sage@newdream.net>
 *
 * This is free software; you can redistribute it and/or
 * modify it under the terms of the GNU Lesser General Public
 * License version 2.1, as published by the Free Software 
 * Foundation.  See file COPYING.
 * 
 */


#ifndef CEPH_MDISCOVER_H
#define CEPH_MDISCOVER_H

#include "msg/Message.h"
#include "include/filepath.h"

#include <string>


class MDiscover : public Message {
  static const int HEAD_VERSION = 1;
  static const int COMPAT_VERSION = 1;

  inodeno_t       base_ino;          // 1 -> root
  frag_t          base_dir_frag;

  snapid_t        snapid;
  filepath        want;   // ... [/]need/this/stuff

  bool want_base_dir = true;
  bool want_xlocked = false;

 public:
  inodeno_t get_base_ino() { return base_ino; }
  frag_t    get_base_dir_frag() { return base_dir_frag; }
  snapid_t  get_snapid() { return snapid; }

  filepath& get_want() { return want; }
  const std::string& get_dentry(int n) { return want[n]; }

  bool wants_base_dir() { return want_base_dir; }
  bool wants_xlocked() { return want_xlocked; }
  
  void set_base_dir_frag(frag_t f) { base_dir_frag = f; }

  MDiscover() : Message(MSG_MDS_DISCOVER, HEAD_VERSION, COMPAT_VERSION) { }
  MDiscover(inodeno_t base_ino_,
	    frag_t base_frag_,
	    snapid_t s,
            filepath& want_path_,
            bool want_base_dir_ = true,
	    bool discover_xlocks_ = false) :
    Message(MSG_MDS_DISCOVER),
    base_ino(base_ino_),
    base_dir_frag(base_frag_),
    snapid(s),
    want(want_path_),
    want_base_dir(want_base_dir_),
    want_xlocked(discover_xlocks_) { }
private:
  ~MDiscover() override {}

public:
  const char *get_type_name() const override { return "Dis"; }
  void print(ostream &out) const override {
    out << "discover(" << header.tid << " " << base_ino << "." << base_dir_frag
	<< " " << want << ")";
  }

  void decode_payload() override {
    bufferlist::iterator p = payload.begin();
    decode(base_ino, p);
    decode(base_dir_frag, p);
    decode(snapid, p);
    decode(want, p);
    decode(want_base_dir, p);
    decode(want_xlocked, p);
  }
  void encode_payload(uint64_t features) override {
    using ceph::encode;
    encode(base_ino, payload);
    encode(base_dir_frag, payload);
    encode(snapid, payload);
    encode(want, payload);
    encode(want_base_dir, payload);
    encode(want_xlocked, payload);
  }

};

#endif
