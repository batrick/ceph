// -*- mode:C++; tab-width:8; c-basic-offset:2; indent-tabs-mode:t -*-
// vim: ts=8 sw=2 smarttab

#ifndef CEPH_JOURNAL_FUTURE_H
#define CEPH_JOURNAL_FUTURE_H

#include "include/int_types.h"
#include <string>
#include <iosfwd>
#include <boost/intrusive_ptr.hpp>
#include "include/ceph_assert.h"

class Context;

namespace journal {

using FutureImplPtr = boost::intrusive_ptr<class FutureImpl>;

class Future {
public:
  Future();
  Future(const FutureImplPtr& future_impl);
  ~Future();

  inline bool is_valid() const {
    return m_future_impl.get() != nullptr;
  }

  void flush(Context *on_safe);
  void wait(Context *on_safe);

  bool is_complete() const;
  int get_return_value() const;

private:
  friend class Journaler;
  friend std::ostream& operator<<(std::ostream&, const Future&);

  inline const FutureImplPtr& get_future_impl() const {
    return m_future_impl;
  }

  FutureImplPtr m_future_impl;
};

std::ostream &operator<<(std::ostream &os, const Future &future);

} // namespace journal

using journal::operator<<;

#endif // CEPH_JOURNAL_FUTURE_H
