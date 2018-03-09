#ifndef CEPH_MGATHERCAPS_H
#define CEPH_MGATHERCAPS_H

#include "msg/Message.h"


class MGatherCaps : public Message {
  static const int HEAD_VERSION = 1;
  static const int COMPAT_VERSION = 1;

 public:
  inodeno_t ino;

  MGatherCaps() :
    Message(MSG_MDS_GATHERCAPS, HEAD_VERSION, COMPAT_VERSION) {}
private:
  ~MGatherCaps() override {}

public:
  const char *get_type_name() const override { return "gather_caps"; }
  void print(ostream& o) const override {
    o << "gather_caps(" << ino << ")";
  }

  void encode_payload(uint64_t features) override {
    using ceph::encode;
    encode(ino, payload);
  }
  void decode_payload() override {
    using ceph::decode;
    bufferlist::iterator p = payload.begin();
    decode(ino, p);
  }

};

#endif
