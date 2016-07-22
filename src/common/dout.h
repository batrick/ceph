// -*- mode:C++; tab-width:8; c-basic-offset:2; indent-tabs-mode:t -*-
// vim: ts=8 sw=2 smarttab
/*
 * Ceph - scalable distributed file system
 *
 * Copyright (C) 2004-2010 Sage Weil <sage@newdream.net>
 * Copyright (C) 2010 Dreamhost
 *
 * This is free software; you can redistribute it and/or
 * modify it under the terms of the GNU Lesser General Public
 * License version 2.1, as published by the Free Software
 * Foundation.  See file COPYING.
 *
 */

#ifndef CEPH_DOUT_H
#define CEPH_DOUT_H

#include "global/global_context.h"
#include "common/config.h"
#include "common/likely.h"
#include "common/Clock.h"
#include "log/Entry.h"
#include "log/Log.h"
#include "include/assert.h"

#include <ostream>
#include <iostream>
#include <pthread.h>
#include <streambuf>
#include <sstream>

extern void dout_emergency(const char * const str);
extern void dout_emergency(const std::string &str);

// intentionally conflict with endl
class _bad_endl_use_dendl_t { public: _bad_endl_use_dendl_t(int) {} };
static const _bad_endl_use_dendl_t endl = 0;
inline std::ostream& operator<<(std::ostream& out, _bad_endl_use_dendl_t) {
  assert(0 && "you are using the wrong endl.. use std::endl or dendl");
  return out;
}

class DoutPrefixProvider {
public:
  virtual string gen_prefix() const = 0;
  virtual CephContext *get_cct() const = 0;
  virtual unsigned get_subsys() const = 0;
  virtual ~DoutPrefixProvider() {}
};

// NOTE: depend on magic value in _ASSERT_H so that we detect when
// /usr/include/assert.h clobbers our fancier version.
#define _dout_cct create_entry

#define lsubdout(cct, sub, v)  (cct)->_log->_ASSERT_H((v), ceph_subsys_##sub)
#define ldout(cct, v)  (cct)->_log->_ASSERT_H((v), dout_subsys)
#define lderr(cct) (cct)->_log->_ASSERT_H(-1, ceph_subsys_)

#define ldpp_dout(dpp, v) (dpp ? (dpp)->get_cct()->_log->_ASSERT_H(v, dpp->get_subsys()) : NullEntry())
// FIXME (*_dout << dpp->gen_prefix())

#define lgeneric_subdout(cct, sub, v) lsubdout(cct, sub, v)
#define lgeneric_dout(cct, v) (cct)->_log->_ASSERT_H((v), ceph_subsys_)
#define lgeneric_derr(cct) (cct)->_log->_ASSERT_H(-1, ceph_subsys_)

#define ldlog_p1(cct, sub, lvl)                 \
  (cct->_conf->subsys.should_gather((sub), (lvl)))

#define dendl std::flush

#endif
