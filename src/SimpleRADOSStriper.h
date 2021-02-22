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

#ifndef _SIMPLERADOSSTRIPER_H
#define _SIMPLERADOSSTRIPER_H

#include <string_view>
#include <thread>

#include "include/buffer.h"
#include "include/rados/librados.hpp"
#include "include/uuid.h"
#include "include/types.h"

#include "common/ceph_time.h"
#include "common/perf_counters.h"

class SimpleRADOSStriper
{
public:
  using aiocompletionptr = std::unique_ptr<librados::AioCompletion>;
  using clock = ceph::coarse_mono_clock;
  using time = ceph::coarse_mono_time;

  struct extent {
    std::string soid;
    size_t len;
    size_t off;
  };

  static inline const uint64_t object_size = 22; /* power of 2 */
  static inline const uint64_t min_growth = (1<<27); /* 128 MB */
  static inline const char XATTR_SIZE[] = "striper.size";
  static inline const char XATTR_ALLOCATED[] = "striper.allocated";
  static inline const char XATTR_VERSION[] = "striper.version";
  static inline const char XATTR_LAYOUT_STRIPE_UNIT[] = "striper.layout.stripe_unit";
  static inline const char XATTR_LAYOUT_STRIPE_COUNT[] = "striper.layout.stripe_count";
  static inline const char XATTR_LAYOUT_OBJECT_SIZE[] = "striper.layout.object_size";
  static inline const std::string biglock = "striper.lock";
  static inline const std::string lockdesc = "SimpleRADOSStriper";

  static int config_logger(CephContext* cct, std::string_view name, std::shared_ptr<PerfCounters>* l);

  SimpleRADOSStriper() = default;
  SimpleRADOSStriper(librados::IoCtx ioctx, std::string oid)
    : ioctx(std::move(ioctx))
    , oid(std::move(oid))
  {
    cookie.generate_random();
  }
  SimpleRADOSStriper(const SimpleRADOSStriper&) = delete;
  SimpleRADOSStriper& operator=(const SimpleRADOSStriper&) = delete;
  SimpleRADOSStriper& operator=(SimpleRADOSStriper&&) = delete;
  SimpleRADOSStriper(SimpleRADOSStriper&&) = delete;
  ~SimpleRADOSStriper();

  int create();
  int open();
  int remove();
  int stat(uint64_t* size);
  ssize_t write(const void* data, size_t len, uint64_t off);
  ssize_t read(void* data, size_t len, uint64_t off);
  int truncate(size_t size);
  int flush();
  int lock(uint64_t timeoutms);
  int unlock();
  int is_locked() const {
    return locked;
  }
  int printlockers(std::ostream& out);
  void set_logger(std::shared_ptr<PerfCounters> l) {
    logger = std::move(l);
  }
  void set_lock_interval(std::chrono::milliseconds t) {
    lock_keeper_interval = t;
  }
  void set_lock_timeout(std::chrono::milliseconds t) {
    lock_keeper_timeout = t;
  }

protected:
  ceph::bufferlist uint2bl(uint64_t v);
  int setmeta(uint64_t new_size, bool update_size);
  int allocshrink(uint64_t a);
  int maybeallocshrink();
  int wait_for_updates();
  extent getnextextent(size_t len, uint64_t off) const;
  extent getfirstextent() const {
    return getnextextent(0, 0);
  }

private:
  void lock_keeper_main(void);

  librados::IoCtx ioctx;
  std::shared_ptr<PerfCounters> logger;
  std::string oid;
  std::thread lock_keeper;
  std::condition_variable lock_keeper_cvar;
  std::mutex lock_keeper_mutex;
  time last_renewal = time::min();
  std::chrono::milliseconds lock_keeper_interval = 2000ms;
  std::chrono::milliseconds lock_keeper_timeout = 30000ms;
  std::atomic<bool> blocklisted = false;
  bool shutdown = false;
  version_t version = 0;
  uint64_t size = 0;
  uint64_t allocated = 0;
  uuid_d cookie{};
  bool locked = false;
  bool size_dirty = false;
  std::vector<aiocompletionptr> updates;
};

#endif /* _SIMPLERADOSSTRIPER_H */
