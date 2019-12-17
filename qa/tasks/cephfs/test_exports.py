import logging
import time
from StringIO import StringIO
from tasks.cephfs.fuse_mount import FuseMount
from tasks.cephfs.cephfs_test_case import CephFSTestCase

log = logging.getLogger(__name__)

class TestExports(CephFSTestCase):
    MDSS_REQUIRED = 2
    CLIENTS_REQUIRED = 2

    def test_export_pin(self):
        self.fs.set_max_mds(2)
        self.fs.wait_for_daemons()

        status = self.fs.status()

        self.mount_a.run_shell(["mkdir", "-p", "1/2/3"])
        self._wait_subtrees(status, 0, [])

        # NOP
        self.mount_a.setfattr("1", "ceph.dir.pin", "-1")
        self._wait_subtrees(status, 0, [])

        # NOP (rank < -1)
        self.mount_a.setfattr("1", "ceph.dir.pin", "-2341")
        self._wait_subtrees(status, 0, [])

        # pin /1 to rank 1
        self.mount_a.setfattr("1", "ceph.dir.pin", "1")
        self._wait_subtrees(status, 1, [('/1', 1)])

        # Check export_targets is set properly
        status = self.fs.status()
        log.info(status)
        r0 = status.get_rank(self.fs.id, 0)
        self.assertTrue(sorted(r0['export_targets']) == [1])

        # redundant pin /1/2 to rank 1
        self.mount_a.setfattr("1/2", "ceph.dir.pin", "1")
        self._wait_subtrees(status, 1, [('/1', 1), ('/1/2', 1)])

        # change pin /1/2 to rank 0
        self.mount_a.setfattr("1/2", "ceph.dir.pin", "0")
        self._wait_subtrees(status, 1, [('/1', 1), ('/1/2', 0)])
        self._wait_subtrees(status, 0, [('/1', 1), ('/1/2', 0)])

        # change pin /1/2/3 to (presently) non-existent rank 2
        self.mount_a.setfattr("1/2/3", "ceph.dir.pin", "2")
        self._wait_subtrees(status, 0, [('/1', 1), ('/1/2', 0)])
        self._wait_subtrees(status, 1, [('/1', 1), ('/1/2', 0)])

        # change pin /1/2 back to rank 1
        self.mount_a.setfattr("1/2", "ceph.dir.pin", "1")
        self._wait_subtrees(status, 1, [('/1', 1), ('/1/2', 1)])

        # add another directory pinned to 1
        self.mount_a.run_shell(["mkdir", "-p", "1/4/5"])
        self.mount_a.setfattr("1/4/5", "ceph.dir.pin", "1")
        self._wait_subtrees(status, 1, [('/1', 1), ('/1/2', 1), ('/1/4/5', 1)])

        # change pin /1 to 0
        self.mount_a.setfattr("1", "ceph.dir.pin", "0")
        self._wait_subtrees(status, 0, [('/1', 0), ('/1/2', 1), ('/1/4/5', 1)])

        # change pin /1/2 to default (-1); does the subtree root properly respect it's parent pin?
        self.mount_a.setfattr("1/2", "ceph.dir.pin", "-1")
        self._wait_subtrees(status, 0, [('/1', 0), ('/1/4/5', 1)])

        if len(list(status.get_standbys())):
            self.fs.set_max_mds(3)
            self.fs.wait_for_state('up:active', rank=2)
            self._wait_subtrees(status, 0, [('/1', 0), ('/1/4/5', 1), ('/1/2/3', 2)])

            # Check export_targets is set properly
            status = self.fs.status()
            log.info(status)
            r0 = status.get_rank(self.fs.id, 0)
            self.assertTrue(sorted(r0['export_targets']) == [1,2])
            r1 = status.get_rank(self.fs.id, 1)
            self.assertTrue(sorted(r1['export_targets']) == [0])
            r2 = status.get_rank(self.fs.id, 2)
            self.assertTrue(sorted(r2['export_targets']) == [])

        # Test rename
        self.mount_a.run_shell(["mkdir", "-p", "a/b", "aa/bb"])
        self.mount_a.setfattr("a", "ceph.dir.pin", "1")
        self.mount_a.setfattr("aa/bb", "ceph.dir.pin", "0")
        if (len(self.fs.get_active_names()) > 2):
            self._wait_subtrees(status, 0, [('/1', 0), ('/1/4/5', 1), ('/1/2/3', 2), ('/a', 1), ('/aa/bb', 0)])
        else:
            self._wait_subtrees(status, 0, [('/1', 0), ('/1/4/5', 1), ('/a', 1), ('/aa/bb', 0)])
        self.mount_a.run_shell(["mv", "aa", "a/b/"])
        if (len(self.fs.get_active_names()) > 2):
            self._wait_subtrees(status, 0, [('/1', 0), ('/1/4/5', 1), ('/1/2/3', 2), ('/a', 1), ('/a/b/aa/bb', 0)])
        else:
            self._wait_subtrees(status, 0, [('/1', 0), ('/1/4/5', 1), ('/a', 1), ('/a/b/aa/bb', 0)])

    def test_export_pin_getfattr(self):
        self.fs.set_max_mds(2)
        self.fs.wait_for_daemons()

        status = self.fs.status()

        self.mount_a.run_shell(["mkdir", "-p", "1/2/3"])
        self._wait_subtrees(status, 0, [])

        # pin /1 to rank 0
        self.mount_a.setfattr("1", "ceph.dir.pin", "1")
        self._wait_subtrees(status, 1, [('/1', 1)])

        # pin /1/2 to rank 1
        self.mount_a.setfattr("1/2", "ceph.dir.pin", "1")
        self._wait_subtrees(status, 1, [('/1', 1), ('/1/2', 1)])

        # change pin /1/2 to rank 0
        self.mount_a.setfattr("1/2", "ceph.dir.pin", "0")
        self._wait_subtrees(status, 1, [('/1', 1), ('/1/2', 0)])
        self._wait_subtrees(status, 0, [('/1', 1), ('/1/2', 0)])

         # change pin /1/2/3 to (presently) non-existent rank 2
        self.mount_a.setfattr("1/2/3", "ceph.dir.pin", "2")
        self._wait_subtrees(status, 0, [('/1', 1), ('/1/2', 0)])

        if len(list(status.get_standbys())):
            self.fs.set_max_mds(3)
            self.fs.wait_for_state('up:active', rank=2)
            self._wait_subtrees(status, 0, [('/1', 1), ('/1/2', 0), ('/1/2/3', 2)])

        if not isinstance(self.mount_a, FuseMount):
            p = self.mount_a.client_remote.run(args=['uname', '-r'], stdout=StringIO(), wait=True)
            dir_pin = self.mount_a.getfattr("1", "ceph.dir.pin")
            log.debug("mount.getfattr('1','ceph.dir.pin'): %s " % dir_pin)
	    if str(p.stdout.getvalue()) < "5" and not(dir_pin):
	        self.skipTest("Kernel does not support getting the extended attribute ceph.dir.pin")
        self.assertTrue(self.mount_a.getfattr("1", "ceph.dir.pin") == "1")
        self.assertTrue(self.mount_a.getfattr("1/2", "ceph.dir.pin") == "0")
        if (len(self.fs.get_active_names()) > 2):
            self.assertTrue(self.mount_a.getfattr("1/2/3", "ceph.dir.pin") == "2")

    def test_session_race(self):
        """
        Test session creation race.

        See: https://tracker.ceph.com/issues/24072#change-113056
        """

        self.fs.set_max_mds(2)
        status = self.fs.wait_for_daemons()

        rank1 = self.fs.get_rank(rank=1, status=status)

        # Create a directory that is pre-exported to rank 1
        self.mount_a.run_shell(["mkdir", "-p", "a/aa"])
        self.mount_a.setfattr("a", "ceph.dir.pin", "1")
        self._wait_subtrees(status, 1, [('/a', 1)])

        # Now set the mds config to allow the race
        self.fs.rank_asok(["config", "set", "mds_inject_migrator_session_race", "true"], rank=1)

        # Now create another directory and try to export it
        self.mount_b.run_shell(["mkdir", "-p", "b/bb"])
        self.mount_b.setfattr("b", "ceph.dir.pin", "1")

        time.sleep(5)

        # Now turn off the race so that it doesn't wait again
        self.fs.rank_asok(["config", "set", "mds_inject_migrator_session_race", "false"], rank=1)

        # Now try to create a session with rank 1 by accessing a dir known to
        # be there, if buggy, this should cause the rank 1 to crash:
        self.mount_b.run_shell(["ls", "a"])

        # Check if rank1 changed (standby tookover?)
        new_rank1 = self.fs.get_rank(rank=1)
        self.assertEqual(rank1['gid'], new_rank1['gid'])

class TestKillPoints(CephFSTestCase):
    # Two active MDS
    MDSS_REQUIRED = 2

    init = False

    def _setup_cluster(self):
        # Set Multi-MDS cluster
        self.fs.set_max_mds(2)

        self.fs.wait_for_daemons()
        
        all_daemons = self.fs.get_daemon_names()

        # Create test data
        if self.init is False:
            self._populate_data(8)
            self.init = True

        return True

    def _populate_data(self, nfiles):
            size_mb = 8
            dname = "abc"
            self.mount_a.run_shell(["mkdir", dname])
            for i in range(nfiles):
                fname =dname.join("/").join(str(i)).join(".txt")
                self.mount_a.write_n_mb(fname, size_mb)

            # Get the list of file to confirm the count of files
            self.org_files = self.mount_a.ls()

    def _verify_data(self):
        s1 = set(self.mount_a.ls())
        s2 = set(self.org_files)

        if s1.isdisjoint(s2):
            log.error("Directory contents org: %s" %str(org_files))
            log.error("Directory contents new: %s" %str(out))
            return False

        log.info("Directory contents matches")
        return True

    def _run_export_dir(self, importv, exportv):
        # Wait till all MDS becomes active
        self.fs.wait_for_daemons()

        # Get all active ranks
        ranks = self.fs.get_all_mds_rank()

        rank_0 = self.fs.get_rank(rank=0)
        rank_0_name = rank_0['name']

        killpoint = {}
        killpoint[0] = ('export', exportv)
        killpoint[1] = ('import', importv)

        command = ["config", "set", "mds_kill_export_at", str(exportv)]
        result = self.fs.mds_asok(command, rank_0_name)
        assert(result["success"])

        command = ["config", "set", "mds_kill_import_at", str(importv)]
        result = self.fs.mds_asok(command, rank_1_name)
        assert(result["success"])

        # This should kill either or both MDS process
        command = ["export", "dir", "/abc", "1"]
        try:
            result = self.fs.mds_asok(command, rank_0_name)
        except Exception as e:
            log.error(e.__str__())

        active_mds = self.fs.get_active_names()
        if rank_0_name in active_mds:
            log.info("MDS %s crashed at type %s killpoint %d"
                    %(rank_0_name, killpoint[0][0], killpoint[0][1]))

        # Waiting time for monitor to promote replacement for dead MDS
        grace = int(float(self.fs.get_config("mds_beacon_grace", service_type="mon")))

        #log_active_mds()
        #log_crashed_mds()

        status = self.fs.wait_for_daemons(timeout=grace*2)

        # Check if rank0 changed (standby tookover?)
        new_rank_0 = self.fs.get_rank(rank=0)
        self.assertEqual(rank_0['gid'], new_rank_0['gid'])
        new_rank_0_name = new_rank_0['name']
        active_mds = self.fs.get_active_names()
        if new_rank_0_name in active_mds:
            log.info("MDS %s active at type %s killpoint %d"
                    %(new_rank_0_name, killpoint[0][0], killpoint[0][1]))

        status = self.fs.wait_for_daemons(timeout=grace*2)

        active_mds = self.fs.get_active_names()
        if len(active_mds) != 2:
            "One or more MDS did not come up"
            return False

        if not self._verify_data():
            return False;

        return True


    def _run_export(self, importv, exportv):
        if !(self._run_export_dir(importv, exportv)):
            log.error("Error for killpoint %d:%d" %(importv, exportv))
        else:
            return True


def make_test_killpoints(importv, exportv):
    def test_export_killpoints(self)
        self.init = False
        self._setup_cluster()
        assert(self._run_export(importv, exportv))
        log.info("Test passed for killpoint (%d, %d)" %importv, %exportv))
    return test_export_killpoints

for i in range(1, 14):
    for j in range(1, 14):
        test_export_killpoints = make_test_killpoints(i, j)
        setattr(TestKillPoints, "test_export_killpoints_%d_%d" % (i,j), test_export_killpoints)

