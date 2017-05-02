// -*- mode:C++; tab-width:8; c-basic-offset:2; indent-tabs-mode:t -*-
// vim: ts=8 sw=2 smarttab
/*
 * Ceph - scalable distributed file system
 *
 * Copyright (C) 2017 Red Hat, Inc.
 *
 * This is free software; you can redistribute it and/or
 * modify it under the terms of the GNU Lesser General Public
 * License version 2.1, as published by the Free Software
 * Foundation.  See file COPYING.
 *
 */

#ifndef CEPH_FLAGS_H
#define CEPH_FLAGS_H

template <typename T>
class Flag {
public:
  Flag(const std::string& name, const T& value) : name(name), value(value) {}

  static std::ostream& operator<<(std::ostream& out, const Flag<T>& flag)
  {
    out << name;
  }

  const std::string name;
  const T value;
};

template <typename T>
class Flags {
//class Flags : BitmaskType {
public:
  static std::ostream& operator<<(std::ostream& out, const Flags<T>& flags)
  {
    auto it = flags.begin();
    while (it != flags.end()) {
      out << *it;
      if (++it != flags.end()) {
        out << "|";
      }
    }
  }

  Flags<T>& operator&(const Flags<T>& lhs, const Flags<T>& rhs);


private:
  
  
};

#endif
