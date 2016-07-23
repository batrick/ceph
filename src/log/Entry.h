// -*- mode:C++; tab-width:8; c-basic-offset:2; indent-tabs-mode:t -*-
// vim: ts=8 sw=2 smarttab

#ifndef __CEPH_LOG_ENTRY_H
#define __CEPH_LOG_ENTRY_H

#include "include/utime.h"
#include "common/PrebufferedStreambuf.h"
#include <pthread.h>
#include <string>


namespace ceph {
namespace log {

class Entry {
  Log &log;

public:
  utime_t m_stamp;
  pthread_t m_thread;
  short m_prio, m_subsys;

  Entry(Log &l, utime_t s, pthread_t t, short pr, short sub) :
    log(l),
    m_stamp(s),
    m_thread(t),
    m_prio(pr),
    m_subsys(sub)
  {}
  Entry(Entry &&e) :
    log(e.log),
    m_stamp(e.m_stamp),
    m_thread(e.m_thread),
    m_prio(e.m_prio),
    m_subsys(e.m_subsys)
  {}
  Entry(const Entry &) = delete;
  Entry& operator=(const Entry &) = delete;
  virtual ~Entry() {}

  //virtual Entry& operator<<(Entry &e, std::string s) = 0;
  virtual const std::string &get_str() const = 0;
  virtual size_t size() const = 0;
};

class MutableEntry : public Entry, public std::ostream {
  MutableEntry(std::streambuf *b, Log &l, utime_t s, pthread_t t, short pr, short sub) : Entry(l, s, t, pr, sub), ostream(b) {}
  virtual ~MutableEntry() {}
  //virtual std::ostream& operator<<(MutableEntry &e, const std::string &s) = 0;
};

class IncompleteEntry : public PrebufferedStreambuf, public MutableEntry /* after PrebufferedStreambuf! */ {
  char m_buf[4096];

public:
  IncompleteEntry(Log &l, utime_t s, pthread_t t, short pr, short sub) :
      PrebufferedStreambuf(m_buf, sizeof m_buf),
      MutableEntry(this, l, s, t, pr, sub)
  {
  }

  IncompleteEntry(IncompleteEntry &&e) :
    Entry(std::move(e)),
    PrebufferedStreambuf(m_buf, sizeof m_buf)
  {
    this << e.get_str();
  }

  ~IncompleteEntry() {
    if (m_streambuf.size())
      log.submit_entry(ConcreteEntry(std::move(this)));
  }

  //std::ostream& operator<<(MutableEntry &e, std::string s) {
  //  m_streambuf << s;
  //  return e;
  //}

  const std::string &get_str() const {
    return m_streambuf.get_str();
  }

  // returns current size of content
  size_t size() const {
    return m_streambuf.size();
  }

  // extracts up to avail chars of content
  //int snprintf(char* dst, size_t avail) const {
    //return m_streambuf.snprintf(dst, avail);
  //}
};

class NullEntry : public std::streambuf, public MutableEntry /* after std::streambuf! */ {
  static const std::string s;
  char b[4096];

protected:
  int overflow(int c) {
    setp(b, b + sizeof b);
    return std::char_traits<char>::not_eof(c);
  }

public:
  NullEntry(Log &l, utime_t s, pthread_t t, short pr, short sub) : Entry(l, s, t, pr, sub) {
    //setstate(std::ios_base::failbit);
    setp(b, b+(sizeof b));
  }
  NullEntry(NullEntry &&e) : Entry(std::move(e)) {}

  const std::string &get_str const { return s; }
  size_t size() const { return 0; }
};

class ConcreteEntry : public Entry {
  std::string s;

public:
  ConcreteEntry(Entry &&e) : Entry(e), s(e.get_str()) {}
  ConcreteEntry(ConcreteEntry &&e) : Entry(std::move(e)), s(std::move(e.s)) {}

  const std::string &get_str() const {
    return s;
  }

  size_t size() const {
    return s.len();
  }
};

}
}

#endif
