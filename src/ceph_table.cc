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

#include "auth/KeyRing.h"
#include "common/Timer.h"
#include "common/ceph_argparse.h"
#include "common/config.h"
#include "common/pick_address.h"
#include "common/strtol.h"
#include "global/global_init.h"
#include "global/pidfile.h"
#include "global/signal_handler.h"
#include "include/assert.h"
#include "include/ceph_features.h"
#include "include/compat.h"
#include "msg/Messenger.h"
#include "perfglue/heap_profiler.h"
#include "table/TableDaemon.h"

#include <iostream>
#include <string>

#include <fcntl.h>
#include <pthread.h>
#include <sys/stat.h>
#include <sys/types.h>

#include <ctype.h>

#define dout_context g_ceph_context
#define dout_subsys ceph_subsys_table

static void usage()
{
  cout << "usage: ceph-table -i <ID> [flags]\n"
       << "  -m monitorip:port\n"
       << "        connect to monitor at given address\n"
       << "  --debug_table n\n"
       << "        debug Table level (e.g. 10)\n"
       << std::endl;
  generic_server_usage();
}

std::unique_ptr<TableDaemon> table;

static void handle_table_signal(int signum)
{
  if (table)
    table->handle_signal(signum);
}

#ifdef BUILDING_FOR_EMBEDDED
extern "C" int cephd_table(int argc, const char **argv)
#else
int main(int argc, const char **argv)
#endif
{
  ceph_pthread_setname(pthread_self(), "ceph-table");

  vector<const char*> args;
  argv_to_vec(argc, argv, args);
  env_to_vec(args);

  auto cct = global_init(NULL, args,
			 CEPH_ENTITY_TYPE_TABLE, CODE_ENVIRONMENT_DAEMON,
			 0, "table_data");
  ceph_heap_profiler_init();

  std::string val, action;
  for (std::vector<const char*>::iterator i = args.begin(); i != args.end(); ) {
    if (ceph_argparse_double_dash(args, i)) {
      break;
    } else if (ceph_argparse_flag(args, i, "--help", "-h", (char*)NULL)) {
      // exit(1) will be called in the usage()
      usage();
    } else {
      derr << "Error: can't understand argument: " << *i << "\n" << dendl;
      usage();
    }
  }

  pick_addresses(g_ceph_context, CEPH_PICK_ADDRESS_PUBLIC);

  // Normal startup
  if (g_conf->name.has_default_id()) {
    derr << "must specify '-i name' with the ceph-table instance name" << dendl;
    usage();
  }

  if (g_conf->name.get_id().empty() || isdigit(g_conf->name.get_id()[0])) {
    derr << "id is invalid: must not be empty or begin with a digit" << dendl;
    usage();
  }

  uint64_t nonce = 0;
  get_random_bytes((char*)&nonce, sizeof(nonce));

  std::string public_msgr_type = g_conf->ms_public_type.empty() ? g_conf->get_val<std::string>("ms_type") : g_conf->ms_public_type;
  std::unique_ptr<Messenger> m(Messenger::create(g_ceph_context, public_msgr_type,
      entity_name_t::TABLE(-1), "table", nonce, Messenger::HAS_MANY_CONNECTIONS));
  if (!msgr)
    exit(EXIT_FAILURE);
  msgr->set_cluster_protocol(CEPH_TABLE_PROTOCOL);

  cout << "starting " << g_conf->name << " at " << msgr->get_myaddr()
       << std::endl;
  uint64_t required = CEPH_FEATURE_OSDREPLYMUX;

  msgr->set_default_policy(Messenger::Policy::lossy_client(required));
  msgr->set_policy(entity_name_t::TYPE_MON,
                   Messenger::Policy::lossy_client(CEPH_FEATURE_UID |
                                                   CEPH_FEATURE_PGID64));
  msgr->set_policy(entity_name_t::TYPE_TABLE,
                   Messenger::Policy::lossless_peer(CEPH_FEATURE_UID));
  msgr->set_policy(entity_name_t::TYPE_CLIENT,
                   Messenger::Policy::stateful_server(0));

  int r = msgr->bind(g_conf->public_addr);
  if (r < 0)
    exit(EXIT_FAILURE);

  global_init_daemonize(g_ceph_context);
  common_init_finish(g_ceph_context);
  global_init_chdir(g_ceph_context);

  // set up signal handlers, now that we've daemonized/forked.
  init_async_signal_handler();
  register_async_signal_handler(SIGHUP, sighup_handler);
  register_async_signal_handler_oneshot(SIGINT, handle_table_signal);
  register_async_signal_handler_oneshot(SIGTERM, handle_table_signal);

  msgr->start();

  // start table
  int r = 0;
  try {
    table = new TableDaemon(g_conf->name.get_id().c_str(), std::move(msgr), argc, argv);

    if (g_conf->inject_early_sigterm)
      raise(SIGTERM);

    table->exec();
  } catch (int e) {
    r = e;
    msgr->wait();
    goto shutdown;
  }

  unregister_async_signal_handler(SIGHUP, sighup_handler);
  unregister_async_signal_handler(SIGINT, handle_table_signal);
  unregister_async_signal_handler(SIGTERM, handle_table_signal);
  shutdown_async_signal_handler();

shutdown:
  // TODO verify pidfile_remove() unnecessary

  if (r < 0) {
    // leak deliberately to aid memory leak detection
    table.release();
    msgr.release();
  }

  // cd on exit, so that gmon.out (if any) goes into a separate directory for each node.
  char s[20];
  snprintf(s, sizeof(s), "gmon/%d", getpid());
  if ((mkdir(s, 0755) == 0) && (chdir(s) == 0)) {
    cerr << "ceph-table: gmon.out should be in " << s << std::endl;
  }

  return 0;
}

