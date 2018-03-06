#!/usr/bin/env bash

function run {
  printf '%s\n' "$*" >&2
  "$@"
}

BIN_PATH=${TESTDIR}/fsstress/ltp-full-20091231/testcases/kernel/fs/fsstress/fsstress

trap "rm -rf ${TESTDIR}/fsstress" EXIT
run mkdir -p ${TESTDIR}/fsstress
run pushd "${TESTDIR}/fsstress"
run wget -q -O fsstress/ltp-full.tgz http://download.ceph.com/qa/ltp-full-20091231.tgz
run tar xzf fsstress/ltp-full.tgz
run rm fsstress/ltp-full.tgz
run cd fsstress/ltp-full-20091231/testcases/kernel/fs/fsstress
run make
run popd

printf "Starting fsstress...\n" >&2
DIR="fsstress-$(hostname)-$$"
run mkdir -- "$DIR"
run "${BIN_PATH}" -d "$DIR" -l 1 -n 1000 -p 10 -v
