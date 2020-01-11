#pragma once

#include "msg/Message.h"

class MMDSOp: public SafeMessage {
public:
  template<typename... Types>
  MMDSOp(Types&&... args)
    : SafeMessage(std::forward<Types>(args)...) {}
};
