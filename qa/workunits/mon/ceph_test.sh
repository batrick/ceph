#!/bin/bash

set -ex

for t in ceph_test_mon_*; do
    "$t"
done
