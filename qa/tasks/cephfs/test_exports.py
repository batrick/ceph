import logging
import time
from tasks.cephfs.fuse_mount import FuseMount
from tasks.cephfs.cephfs_test_case import CephFSTestCase

log = logging.getLogger(__name__)

class TestExports(CephFSTestCase):
    def _wait_subtrees(self, status, rank, test):
        timeout = 30
        pause = 2
        test = sorted(test)
        for i in range(timeout/pause):
            subtrees = self.fs.mds_asok(["get", "subtrees"], mds_id=status.get_rank(self.fs.id, rank)['name'])
            subtrees = filter(lambda s: s['dir']['path'].startswith('/'), subtrees)
            filtered = sorted([(s['dir']['path'], s['auth_first']) for s in subtrees])
            log.info("%s =?= %s", filtered, test)
            if filtered == test:
                return subtrees
            time.sleep(pause)
        raise RuntimeError("rank {0} failed to reach desired subtree state", rank)

    def test_export_pin(self):
        self.fs.set_allow_multimds(True)
        self.fs.set_max_mds(2)

        status = self.fs.status()

        self.mount_a.run_shell(["mkdir", "-p", "1/2/3"])
        self._wait_subtrees(status, 0, [])

        # NOP
        self.mount_a.run_shell(["setfattr", "-n", "ceph.dir.pin", "-v", "-1", "1"])
        self._wait_subtrees(status, 0, [])

        # NOP (rank < -1)
        self.mount_a.run_shell(["setfattr", "-n", "ceph.dir.pin", "-v", "-2341", "1"])
        self._wait_subtrees(status, 0, [])

        # pin /1 to rank 1
        self.mount_a.run_shell(["setfattr", "-n", "ceph.dir.pin", "-v", "1", "1"])
        self._wait_subtrees(status, 1, [('/1', 1)])

        # Check export_targets is set properly
        status = self.fs.status()
        log.info(status)
        r0 = status.get_rank(self.fs.id, 0)
        self.assertTrue(sorted(r0['export_targets']) == [1])

        # redundant pin /1/2 to rank 1
        self.mount_a.run_shell(["setfattr", "-n", "ceph.dir.pin", "-v", "1", "1/2"])
        self._wait_subtrees(status, 1, [('/1', 1), ('/1/2', 1)])

        # change pin /1/2 to rank 0
        self.mount_a.run_shell(["setfattr", "-n", "ceph.dir.pin", "-v", "0", "1/2"])
        self._wait_subtrees(status, 1, [('/1', 1), ('/1/2', 0)])
        self._wait_subtrees(status, 0, [('/1', 1), ('/1/2', 0)])

        # change pin /1/2/3 to (presently) non-existent rank 2
        self.mount_a.run_shell(["setfattr", "-n", "ceph.dir.pin", "-v", "2", "1/2/3"])
        self._wait_subtrees(status, 0, [('/1', 1), ('/1/2', 0)])
        self._wait_subtrees(status, 1, [('/1', 1), ('/1/2', 0)])

        # change pin /1/2 back to rank 1
        self.mount_a.run_shell(["setfattr", "-n", "ceph.dir.pin", "-v", "1", "1/2"])
        self._wait_subtrees(status, 1, [('/1', 1), ('/1/2', 1)])

        # add another directory pinned to 1
        self.mount_a.run_shell(["mkdir", "-p", "1/4/5"])
        self.mount_a.run_shell(["setfattr", "-n", "ceph.dir.pin", "-v", "1", "1/4/5"])
        self._wait_subtrees(status, 1, [('/1', 1), ('/1/2', 1), ('/1/4/5', 1)])

        # change pin /1 to 0
        self.mount_a.run_shell(["setfattr", "-n", "ceph.dir.pin", "-v", "0", "1"])
        self._wait_subtrees(status, 0, [('/1', 0), ('/1/2', 1), ('/1/4/5', 1)])

        # change pin /1/2 to default (-1); does the subtree root properly respect it's parent pin?
        self.mount_a.run_shell(["setfattr", "-n", "ceph.dir.pin", "-v", "-1", "1/2"])
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
        self.mount_a.run_shell(["setfattr", "-n", "ceph.dir.pin", "-v", "1", "a"])
        self.mount_a.run_shell(["setfattr", "-n", "ceph.dir.pin", "-v", "0", "aa/bb"])
        self._wait_subtrees(status, 0, [('/1', 0), ('/1/4/5', 1), ('/1/2/3', 2), ('/a', 1), ('/aa/bb', 0)])
        self.mount_a.run_shell(["mv", "aa", "a/b/"])
        self._wait_subtrees(status, 0, [('/1', 0), ('/1/4/5', 1), ('/1/2/3', 2), ('/a', 1), ('/a/b/aa/bb', 0)])

class TestKillPoints(CephFSTestCase):
    """
    Test to exercise killpoints available during directory export code path
    After hitting a killpoint, MDS crashes and cluster must find a standby MDS
    to become active. Exported data must be available after mds replacement.
    """

    # Two active MDS
    MDSS_REQUIRED = 2

    def setup_cluster(self):
        # Set Multi-MDS cluster
        self.fs.set_allow_multimds(True)
        self.fs.set_max_mds(2)

        self.fs.wait_for_daemons()

        num_active_mds = len(self.fs.get_active_names())
        if num_active_mds != 2:
            log.error("Incorrect number of MDS active: %d" %num_active_mds)
            return False

        self.mount_a.create_n_files("dir/file_", 8)
        self.org_files = set(self.mount_a.ls("dir"))

    def verify_data(self):
        s1 = set(self.mount_a.ls())
        s2 = set(self.org_files)

        if s1.isdisjoint(s2):
            log.error("Directory contents org: %s" %str(org_files))
            log.error("Directory contents new: %s" %str(out))
            return False

        log.info("Directory contents matches")
        return True

    def run_export_dir(self, importv, exportv):
        # Wait till all MDS becomes active
        self.fs.wait_for_daemons()

        # Get all active ranks
        ranks = self.fs.get_all_mds_rank()

        original_active = self.fs.get_active_names()

        if len(ranks) != 2:
            log.error("Incorrect number of MDS ranks, exiting the test")
            return False

        rank_0_id = original_active[0]
        rank_1_id = original_active[1]

        killpoint = {}
        killpoint[rank_0_id] = ('export', exportv)
        killpoint[rank_1_id] = ('import', importv)

        command = ["config", "set", "mds_kill_export_at", str(exportv)]
        result = self.fs.mds_asok(command, rank_0_id)
        assert(result["success"])

        command = ["config", "set", "mds_kill_import_at", str(importv)]
        result = self.fs.mds_asok(command, rank_1_id)
        assert(result["success"])

        # This should kill either or both MDS process
        self.mount_a.setfattr("dir", "ceph.dir.pin", "1")

        def log_crashed_mds():
            crashed_mds = self.fs.get_crashed_mds()
            for k in crashed_mds:
                name = crashed_mds[k]
                log.info("MDS %s crashed at type %s killpoint %d"
                        %(name, killpoint[name][0], killpoint[name][1]))

        def log_active_mds():
            active_mds = self.fs.get_up_and_active_mds()
            for k in active_mds:
                name = active_mds[k]
                log.info("MDS %s active at type %s killpoint %d"
                        %(name, killpoint[name][0], killpoint[name][1]))

        # Waiting time for monitor to promote replacement for dead MDS
        grace = int(self.fs.get_config("mds_beacon_grace", service_type="mon"))

        #log_active_mds()
        #log_crashed_mds()

        time.sleep(grace * 2)

        log_active_mds()
        log_crashed_mds()

        # Restart the crashed MDS daemon.
        crashed_mds = self.fs.get_crashed_mds()
        for k in crashed_mds:
            log.info("Restarting rank %d" % k)
            self.fs.mds_fail(crashed_mds[k])
            self.fs.mds_restart(crashed_mds[k])

        # After the restarted, the other MDS can fail on a killpoint.
        # Wait for another grace period to let monitor notice the failure
        # and update MDSMap.

        log_active_mds()
        log_crashed_mds()

        time.sleep(grace * 2)

        log_active_mds()
        log_crashed_mds()

        # Restart the killed daemon.
        for k in crashed_mds:
            log.info("Restarting rank %d" % k)
            self.fs.mds_fail(crashed_mds[k])
            self.fs.mds_restart(crashed_mds[k])

        time.sleep(grace * 2)

        active_mds = self.fs.get_up_and_active_mds()
        if len(active_mds) != 2:
            "One or more MDS did not come up"
            return False

        if not self.verify_data():
            return False;

        return True


    def run_export(self, importv, exportv):
        success_count = 0

        for v in range(1, importv + 1):
            for w in range(1, exportv + 1):
                if self.run_export_dir(v, w):
                    success_count = success_count + 1
                else:
                    log.error("Error for killpoint %d:%d" %(v, w))

        for v in range(1, exportv + 1):
            for w in range(1, importv + 1):
                if self.run_export_dir(v, w):
                    success_count = success_count + 1
                else:
                    log.error("Error for killpoint %d:%d" %(v, w))

        return success_count

    def test_export_killpoints(self):
        self.init = False
        self.setup_cluster()
        success_count = 0

        import_killpoint = 13
        export_killpoint = 13

        killpoints_count = 2 * import_killpoint * export_killpoint

        success_count = self.run_export(import_killpoint, export_killpoint)
        assert(success_count == killpoints_count)

        log.info("All %d scenarios passed" %killpoints_count)
