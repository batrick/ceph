#!/usr/bin/env bash
set -ex

echo "getting iogen"
wget http://download.ceph.com/qa/iogen_3.1p0.tar
tar -xvzf iogen_3.1p0.tar
cd iogen_3.1p0
echo "patching Makefile for distro compatibility"
# This removes the conflicting -Dstrlcpy and -Darc4random macros
sed -i 's/-Dstrlcpy=strncpy//g' Makefile
sed -i 's/-Darc4random=rand//g' Makefile
echo "making iogen"
make
echo "running iogen"
./iogen -n 5 -s 2g
echo "sleep for 10 min"
sleep 600
echo "stopping iogen"
./iogen -k

echo "OK"
