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

#ifndef CEPH_TABLE_H
#define CEPH_TABLE_H

#include "common/LogClient.h"
#include "common/Mutex.h"
#include "common/Timer.h"
#include "include/Context.h"
#include "include/types.h"
#include "mgr/MgrClient.h"
#include "msg/Dispatcher.h"

#define CEPH_TABLE_PROTOCOL 1

class AuthAuthorizeHandlerRegistry;
class Message;
class Messenger;
class MonClient;

class TableDaemon : public Dispatcher, protected MonClient, protected MgrClient, public md_config_obs_t {
public:
  TableDaemon(const std::string &name, std::unique_ptr<Messenger> m);
  ~TableDaemon() override;

  void exec(void);

  void handle_signal(int signum);

  // config observer bits
  const char** get_tracked_conf_keys() const override;
  void handle_conf_change(const struct md_config_t *conf,
				  const std::set <std::string> &changed) override;

  /**
   * Terminate this daemon process.
   *
   * This function will return, but once it does so the calling thread
   * must do no more work as all subsystems will have been shut down.
   */
  void suicide();

  /**
   * Start a new daemon process with the same command line parameters that
   * this process was run with, then terminate this process
   */
  void respawn();

protected:
  void reset_tick();
  void wait_for_omap_osds();

  // TODO Beacon  beacon;
  Context *tick_event = nullptr;

  bool ms_dispatch(Message *m) override;
  bool ms_get_authorizer(int dest_type, AuthAuthorizer **authorizer, bool force_new) override;
  bool ms_verify_authorizer(Connection *con, int peer_type,
			       int protocol, bufferlist& authorizer_data, bufferlist& authorizer_reply,
			       bool& isvalid, CryptoKey& session_key) override;
  void ms_handle_accept(Connection *con) override;
  void ms_handle_connect(Connection *con) override;
  bool ms_handle_reset(Connection *con) override;
  void ms_handle_remote_reset(Connection *con) override;
  bool ms_handle_refused(Connection *con) override;

private:
  std::string name;
  std::unique_ptr<Messenger> m;
  MgrClient     mgrc;
  LogClient    log_client;
  LogChannelRef clog;
  int orig_argc;
  const char **orig_argv;
}

#if 0
  // messages
  bool _dispatch(Message *m, bool new_msg);

protected:
  bool handle_core_message(Message *m);
  
  // special message types
  friend class C_MDS_Send_Command_Reply;
  static void send_command_reply(MCommand *m, MDSRank* mds_rank, int r,
				 bufferlist outbl, const std::string& outs);
  int _handle_command(
      const cmdmap_t &cmdmap,
      MCommand *m,
      bufferlist *outbl,
      std::string *outs,
      Context **run_later,
      bool *need_reply);
  void handle_command(class MCommand *m);
  void handle_mds_map(class MMDSMap *m);
  void _handle_mds_map(MDSMap *oldmap);
};
#endif

#endif
