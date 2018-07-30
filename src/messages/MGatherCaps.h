#ifndef CEPH_MGATHERCAPS_H
#define CEPH_MGATHERCAPS_H

#include "msg/Message.h"


class MGatherCaps : public Message {
public:
  typedef boost::intrusive_ptr<MGatherCaps> ref;
  typedef boost::intrusive_ptr<MGatherCaps const> const_ref;
  using factory = MessageFactory<MGatherCaps>;
  friend factory;


  inodeno_t ino;

protected:
  MGatherCaps() :
    Message(MSG_MDS_GATHERCAPS) {}
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
    auto p = payload.cbegin();
    decode(ino, p);
  }

};

#endif
