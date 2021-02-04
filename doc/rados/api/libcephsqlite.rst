.. _libcephsqlite:

================
 Ceph SQLite VFS
================

This sqlite3 VFS may be used for storing and accessing a SQLite database backed by
RADOS.

Usage
^^^^^

Normal unmodified applications (including the sqlite command-line toolset
binary) may load libcephsqlite using the SQLite extension loading command.

.. code:: sql

    .LOAD libcephsqlite

or during the invocation of ``sqlite3``

.. code:: sh

   sqlite3 -cmd '.load libcephsqlite'

A database file is formatted as a SQLite URI::

    file:///<"*"poolid|poolname>:[namespace]/<dbname>?vfs=ceph

The ``namespace`` is optional. Note the triple ``///`` in the path. The URI
authority must be empty or localhost in SQLite. Only the path part of the URI
is parsed. For this reason, the URI will not parse properly if you only use two
``//``.

A complete example of (optionally) creating a database and opening:

.. code:: sh

   sqlite3 -cmd '.load libcephsqlite' -cmd '.open file:///foo:bar/baz.db?vfs=ceph'

Note you cannot specify the database file as the normal positional argument to
``sqlite3``. This is because the ``.load libcephsqlite`` command is applied
after opening the database, but opening the database depends on the extension
being loaded first.

An example passing the pool integer id:

.. code:: sh

   sqlite3 -cmd '.load libcephsqlite' -cmd '.open file:///*2:bar/baz.db?vfs=ceph'


Page Size
^^^^^^^^^

SQL allows configuring the page size prior to creating a new database. It is
advisable to increase this config to 65536 (64K) when using RADOS backed
databases to reduce the number of OSD reads/writes and thereby improve
throughput and latency.

.. code:: sql

   PRAGMA page_size = 65536

You may also try other values according to your application needs but note that
64K is the max imposed by SQLite.


Cache
^^^^^

The ceph VFS does not do any caching of reads or buffering of writes. Instead,
and more appropriately, the SQLite page cache is used. You may find it is too small
for most workloads and should therefore increase it significantly:


.. code:: sql

   PRAGMA cache_size = 4096

Which will cache 4096 pages or 256MB (with 64K ``page_cache``).


Journal Persistence
^^^^^^^^^^^^^^^^^^^

By default, SQLite deletes the journal for every transaction. This can be
expensive as libcephsqlite must delete every object backing the journal for
each transaction. For this reason, it is much faster and simpler to ask SQLite
to **persist** the journal and invalidate it with a write to its header. This
is done via:

.. code:: sql

   PRAGMA journal_mode = PERSIST

The cost of this may be increased unused space according to the high-water size
of the journal (based on transaction sizes).


Exclusive Lock Mode
^^^^^^^^^^^^^^^^^^^

SQLite operates in a ``NORMAL`` locking mode where each transaction requires
locking the backing database file. This can add unnecessary overhead to
transactions when you know there's only ever one user of the database at a
given time. You can have SQLite lock the database once for the duration of the
connection using:

.. code:: sql

   PRAGMA locking_mode = EXCLUSIVE

This can more than **halve** the time perform a transaction. Keep in mind this
prevents other clients from accessing the database and increases the likelihood
you'll need to break database locks (see :ref:`libcephsqlite-breaking-locks`).

In this locking mode, each write transaction to the database requires 3
synchronization events: once to write to the journal, another to write to the
database file, and a final write to invalidate the journal header (in
``PERSIST`` journaling mode).


WAL Journal
^^^^^^^^^^^

The `WAL Journal Mode`_ is only available when SQLite is operating in exclusive
lock mode. This is because it requires shared memory communication with other
readers and writers when in the ``NORMAL`` locking mode.

As with local disk databases, WAL mode may significantly reduce small
transaction latency. Testing has shown it can provide more than 50% speedup
over persisted rollback journals in exclusive locking mode. You can expect
around 150 transactions per second.


Performance Notes
^^^^^^^^^^^^^^^^^

The filing backend for the database on RADOS is asynchronous as much as
possible.  Still, performance can be anywhere from 3x-10x slower than a local
database on SSD. Latency can be a major factor. It is advisable to be familiar
with SQLite transactions and other strategies for efficient database updates.
Depending on the performance of the underlying pool, you can expect small
transactions to take up to 30 milliseconds to complete. If you use the
``EXCLUSIVE`` locking mode, it can be reduced further to 15 milliseconds per
transaction.

There is no limit to the size of a SQLite database on RADOS but this should not
be taken as an indication that a database hundreds of gigabytes in size is
advisable. For an appropriate and thoughtful schema, it may be however.


Recommended Use-Cases
^^^^^^^^^^^^^^^^^^^^^

The original purpose of this module was to support saving relational or large
data in RADOS which needs to span multiple objects. Many current applications
with trivial state try to use RADOS omap storage on a single object but this
cannot scale. It is also non-trivial to design a store spanning multiple
objects which is consistent and also simple to use.


Parallel Access
^^^^^^^^^^^^^^^

The VFS does not yet support concurrent readers. All database access is protected
by a single exclusive lock.


Export or Extract Database out of RADOS
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

The database is striped on RADOS and can be extracted using the RADOS cli toolset.

.. code:: sh

    rados --pool=foo --striper get bar.db local-bar.db
    sqlite3 local-bar.db ...

Keep in mind the journal is also striped and may need extracted as well if the
database was in the middle of a transaction. Its name would be something like
``bar.db-journal``.


Temporary Tables
^^^^^^^^^^^^^^^^

Temporary tables backed by the ceph VFS are not supported. The main reason for
this is that the VFS lacks context about where it should put the database, i.e.
which RADOS pool. The persistent database associated with the temporary
database is not communicated via the SQLite VFS API.

Instead, it's suggested to attach a secondary local or `In-Memory Database`_
and put the temporary tables there.

.. _libcephsqlite-breaking-locks:

Breaking Locks
^^^^^^^^^^^^^^

Access to the database file is protected by an exclusive lock on the first
object stripe of the database. If the application fails without unlocking the
database (e.g. a segmentation fault), the lock is not automatically unlocked,
even if the client connection is blocklisted afterward. It may be necessary to
manually rescue the database in this situation by breaking the lock::

    $ rados --pool=foo --namespace bar lock info baz.db.0000000000000000 striper.lock
    {"name":"striper.lock","type":"exclusive","tag":"","lockers":[{"name":"client.4463","cookie":"555c7208-db39-48e8-a4d7-3ba92433a41a","description":"SimpleRADOSStriper","expiration":"0.000000","addr":"127.0.0.1:0/1831418345"}]}

    $ rados --pool=foo --namespace bar lock break baz.db.0000000000000000 striper.lock client.4463 --lock-cookie 555c7208-db39-48e8-a4d7-3ba92433a41a

Making this process automatic if the locker is later blocklisted is planned.

.. _In-Memory Database: https://www.sqlite.org/inmemorydb.html
.. _WAL Journal Mode: https://sqlite.org/wal.html
