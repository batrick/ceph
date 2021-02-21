#!/bin/bash -ex

# The main point of these tests beyond ceph_test_libcephsqlite is to:
#
# - Ensure you can load the Ceph VFS via the dynamic load extension mechanism
#   in SQLite.
# - Check the behavior of a dead application, that it does not hold locks
#   indefinitely.

ceph osd pool rm foo foo --yes-i-really-really-mean-it || true

ceph osd pool create foo

function sqlite {
  tee /dev/stderr | sqlite3 -cmd '.load libcephsqlite.so' -cmd 'pragma journal_mode = PERSIST' -cmd '.open file:///foo:bar/baz.db?vfs=ceph'
}

function striper {
  rados --pool=foo --namespace=bar --striper "$@"
}

function repeat {
  n=$1
  shift
  for ((i = 0; i < "$n"; ++i)); do
    echo "$*"
  done
}

time sqlite <<EOF
create table if not exists foo (a INT);
insert into foo (a) values (RANDOM());
drop table foo;
EOF

striper stat baz.db
striper rm baz.db

time sqlite <<EOF
CREATE TABLE IF NOT EXISTS rand(text BLOB NOT NULL);
$(repeat 10 'INSERT INTO rand (text) VALUES (RANDOMBLOB(4096));')
SELECT LENGTH(text) FROM rand;
DROP TABLE rand;
EOF

time sqlite <<EOF
BEGIN TRANSACTION;
CREATE TABLE IF NOT EXISTS rand(text BLOB NOT NULL);
$(repeat 100 'INSERT INTO rand (text) VALUES (RANDOMBLOB(4096));')
COMMIT;
SELECT LENGTH(text) FROM rand;
DROP TABLE rand;
EOF

striper rm baz.db

time sqlite <<EOF &
CREATE TABLE foo (a BLOB);
INSERT INTO foo VALUES ("start");
WITH RECURSIVE c(x) AS
  (
   VALUES(1)
  UNION ALL
   SELECT x+1
   FROM c
  )
INSERT INTO foo (a)
  SELECT RANDOMBLOB(1<<20)
  FROM c
  LIMIT (1<<20);
EOF

sleep 10

jobs
kill -9 %1
wait

n=$(sqlite <<<"SELECT COUNT(*) FROM foo;")
[[ n -eq 1 ]]
