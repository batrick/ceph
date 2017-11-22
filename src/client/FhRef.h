// -*- mode:C++; tab-width:8; c-basic-offset:2; indent-tabs-mode:t -*-
// vim: ts=8 sw=2 smarttab

#ifndef CEPH_CLIENT_FHREF_H
#define CEPH_CLIENT_FHREF_H

#include <boost/intrusive_ptr.hpp>
class Fh;
typedef boost::intrusive_ptr<Fh> FhRef;
#endif
