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

#ifndef CEPH_EEXPORT_H
#define CEPH_EEXPORT_H

#include "common/config.h"
#include "include/types.h"

#include "../MDSRank.h"

#include "EMetaBlob.h"
#include "../LogEvent.h"

class EExport : public LogEvent {
public:
  EMetaBlob metablob; // exported dir
protected:
  dirfrag_t      base;
  vector<dirfrag_t> bounds;
  mds_rank_t target;
  uint64_t tid;
  
public:
  EExport() :
    LogEvent(EVENT_EXPORT), target(MDS_RANK_NONE) { }
  EExport(dirfrag_t b, const vector<dirfrag_t>& bds, mds_rank_t t, uint64_t _tid) :
    LogEvent(EVENT_EXPORT),
    base(b), bounds(bds), target(t), tid(_tid) { }
  
  const vector<dirfrag_t>& get_bounds() const { return bounds; }
  
  void print(ostream& out) const override {
    out << "EExport " << base << " to mds." << target << " " << metablob;
  }

  EMetaBlob *get_metablob() override { return &metablob; }

  void encode(bufferlist& bl, uint64_t features) const override;
  void decode(bufferlist::const_iterator &bl) override;
  void dump(Formatter *f) const override;
  static void generate_test_instances(std::list<EExport*>& ls);
  void replay(MDSRank *mds) override;

};
WRITE_CLASS_ENCODER_FEATURES(EExport)

#endif
