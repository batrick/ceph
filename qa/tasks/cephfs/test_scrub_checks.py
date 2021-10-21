"""
MDS admin socket scrubbing-related tests.
"""
import json
import logging
import errno
import time
from teuthology.exceptions import CommandFailedError
from teuthology.contextutil import safe_while
import os
from tasks.cephfs.cephfs_test_case import CephFSTestCase

log = logging.getLogger(__name__)

class TestScrubControls(CephFSTestCase):
    """
    Test basic scrub control operations such as abort, pause and resume.
    """

    MDSS_REQUIRED = 2
    CLIENTS_REQUIRED = 1

    def _abort_scrub(self, expected):
        res = self.fs.run_scrub(["abort"])
        self.assertEqual(res['return_code'], expected)
    def _pause_scrub(self, expected):
        res = self.fs.run_scrub(["pause"])
        self.assertEqual(res['return_code'], expected)
    def _resume_scrub(self, expected):
        res = self.fs.run_scrub(["resume"])
        self.assertEqual(res['return_code'], expected)
    def _check_task_status(self, expected_status, timo=120):
        """ check scrub status for current active mds in ceph status """
        with safe_while(sleep=1, tries=120, action='wait for task status') as proceed:
            while proceed():
                active = self.fs.get_active_names()
                log.debug("current active={0}".format(active))
                task_status = self.fs.get_task_status("scrub status")
                try:
                    if task_status[active[0]].startswith(expected_status):
                        return True
                except KeyError:
                    pass

    def _check_task_status_na(self, timo=120):
        """ check absence of scrub status in ceph status """
        with safe_while(sleep=1, tries=120, action='wait for task status') as proceed:
            while proceed():
                active = self.fs.get_active_names()
                log.debug("current active={0}".format(active))
                task_status = self.fs.get_task_status("scrub status")
                if not active[0] in task_status:
                    return True

    def create_scrub_data(self, test_dir):
        for i in range(32):
            dirname = "dir.{0}".format(i)
            dirpath = os.path.join(test_dir, dirname)
            self.mount_a.run_shell_payload(f"""
set -e
mkdir -p {dirpath}
for ((i = 0; i < 32; i++)); do
    dd if=/dev/urandom of={dirpath}/filename.$i bs=1M conv=fdatasync count=1
done
""")

    def test_scrub_abort(self):
        test_dir = "scrub_control_test_path"
        abs_test_path = "/{0}".format(test_dir)

        self.create_scrub_data(test_dir)

        out_json = self.fs.run_scrub(["start", abs_test_path, "recursive"])
        self.assertNotEqual(out_json, None)

        # abort and verify
        self._abort_scrub(0)
        self.fs.wait_until_scrub_complete(sleep=5, timeout=30)

        # sleep enough to fetch updated task status
        checked = self._check_task_status_na()
        self.assertTrue(checked)

    def test_scrub_pause_and_resume(self):
        test_dir = "scrub_control_test_path"
        abs_test_path = "/{0}".format(test_dir)

        log.info("mountpoint: {0}".format(self.mount_a.mountpoint))
        client_path = os.path.join(self.mount_a.mountpoint, test_dir)
        log.info("client_path: {0}".format(client_path))

        self.create_scrub_data(test_dir)

        out_json = self.fs.run_scrub(["start", abs_test_path, "recursive"])
        self.assertNotEqual(out_json, None)

        # pause and verify
        self._pause_scrub(0)
        out_json = self.fs.get_scrub_status()
        self.assertTrue("PAUSED" in out_json['status'])

        checked = self._check_task_status("paused")
        self.assertTrue(checked)

        # resume and verify
        self._resume_scrub(0)
        out_json = self.fs.get_scrub_status()
        self.assertFalse("PAUSED" in out_json['status'])

        checked = self._check_task_status_na()
        self.assertTrue(checked)

    def test_scrub_pause_and_resume_with_abort(self):
        test_dir = "scrub_control_test_path"
        abs_test_path = "/{0}".format(test_dir)

        self.create_scrub_data(test_dir)

        out_json = self.fs.run_scrub(["start", abs_test_path, "recursive"])
        self.assertNotEqual(out_json, None)

        # pause and verify
        self._pause_scrub(0)
        out_json = self.fs.get_scrub_status()
        self.assertTrue("PAUSED" in out_json['status'])

        checked = self._check_task_status("paused")
        self.assertTrue(checked)

        # abort and verify
        self._abort_scrub(0)
        out_json = self.fs.get_scrub_status()
        self.assertTrue("PAUSED" in out_json['status'])
        self.assertTrue("0 inodes" in out_json['status'])

        # scrub status should still be paused...
        checked = self._check_task_status("paused")
        self.assertTrue(checked)

        # resume and verify
        self._resume_scrub(0)
        out_json = self.fs.get_scrub_status()
        self.assertTrue("no active" in out_json['status'])

        checked = self._check_task_status_na()
        self.assertTrue(checked)

    def test_scrub_task_status_on_mds_failover(self):
        (original_active, ) = self.fs.get_active_names()
        original_standbys = self.mds_cluster.get_standby_daemons()

        test_dir = "scrub_control_test_path"
        abs_test_path = "/{0}".format(test_dir)

        self.create_scrub_data(test_dir)

        out_json = self.fs.run_scrub(["start", abs_test_path, "recursive"])
        self.assertNotEqual(out_json, None)

        # pause and verify
        self._pause_scrub(0)
        out_json = self.fs.get_scrub_status()
        self.assertTrue("PAUSED" in out_json['status'])

        checked = self._check_task_status("paused")
        self.assertTrue(checked)

        # Kill the rank 0
        self.fs.mds_stop(original_active)

        grace = float(self.fs.get_config("mds_beacon_grace", service_type="mon"))

        def promoted():
            active = self.fs.get_active_names()
            return active and active[0] in original_standbys

        log.info("Waiting for promotion of one of the original standbys {0}".format(
            original_standbys))
        self.wait_until_true(promoted, timeout=grace*2+15)

        self._check_task_status_na()

class TestScrubChecks(CephFSTestCase):
    """
    Run flush and scrub commands on the specified files in the filesystem. This
    task will run through a sequence of operations, but it is not comprehensive
    on its own -- it doesn't manipulate the mds cache state to test on both
    in- and out-of-memory parts of the hierarchy. So it's designed to be run
    multiple times within a single test run, so that the test can manipulate
    memory state.

    Usage:
    mds_scrub_checks:
      mds_rank: 0
      path: path/to/test/dir
      client: 0
      run_seq: [0-9]+

    Increment the run_seq on subsequent invocations within a single test run;
    it uses that value to generate unique folder and file names.
    """

    MDSS_REQUIRED = 1
    CLIENTS_REQUIRED = 1

    def test_scrub_checks(self):
        self._checks(0)
        self._checks(1)

    def _checks(self, run_seq):
        mds_rank = 0
        test_dir = "scrub_test_path"

        abs_test_path = "/{0}".format(test_dir)

        log.info("mountpoint: {0}".format(self.mount_a.mountpoint))
        client_path = os.path.join(self.mount_a.mountpoint, test_dir)
        log.info("client_path: {0}".format(client_path))

        log.info("Cloning repo into place")
        repo_path = TestScrubChecks.clone_repo(self.mount_a, client_path)

        log.info("Initiating mds_scrub_checks on mds.{id_} test_path {path}, run_seq {seq}".format(
            id_=mds_rank, path=abs_test_path, seq=run_seq)
        )


        success_validator = lambda j, r: self.json_validator(j, r, "return_code", 0)

        nep = "{test_path}/i/dont/exist".format(test_path=abs_test_path)
        self.asok_command(mds_rank, "flush_path {nep}".format(nep=nep),
                          lambda j, r: self.json_validator(j, r, "return_code", -errno.ENOENT))
        self.tell_command(mds_rank, "scrub start {nep}".format(nep=nep),
                          lambda j, r: self.json_validator(j, r, "return_code", -errno.ENOENT))

        test_repo_path = "{test_path}/ceph-qa-suite".format(test_path=abs_test_path)
        dirpath = "{repo_path}/suites".format(repo_path=test_repo_path)

        if run_seq == 0:
            log.info("First run: flushing {dirpath}".format(dirpath=dirpath))
            command = "flush_path {dirpath}".format(dirpath=dirpath)
            self.asok_command(mds_rank, command, success_validator)
        command = "scrub start {dirpath}".format(dirpath=dirpath)
        self.tell_command(mds_rank, command, success_validator)

        filepath = "{repo_path}/suites/fs/verify/validater/valgrind.yaml".format(
            repo_path=test_repo_path)
        if run_seq == 0:
            log.info("First run: flushing {filepath}".format(filepath=filepath))
            command = "flush_path {filepath}".format(filepath=filepath)
            self.asok_command(mds_rank, command, success_validator)
        command = "scrub start {filepath}".format(filepath=filepath)
        self.tell_command(mds_rank, command, success_validator)

        if run_seq == 0:
            log.info("First run: flushing base dir /")
            command = "flush_path /"
            self.asok_command(mds_rank, command, success_validator)
        command = "scrub start /"
        self.tell_command(mds_rank, command, success_validator)

        new_dir = "{repo_path}/new_dir_{i}".format(repo_path=repo_path, i=run_seq)
        test_new_dir = "{repo_path}/new_dir_{i}".format(repo_path=test_repo_path,
                                                        i=run_seq)
        self.mount_a.run_shell(["mkdir", new_dir])
        command = "flush_path {dir}".format(dir=test_new_dir)
        self.asok_command(mds_rank, command, success_validator)

        new_file = "{repo_path}/new_file_{i}".format(repo_path=repo_path,
                                                     i=run_seq)
        test_new_file = "{repo_path}/new_file_{i}".format(repo_path=test_repo_path,
                                                          i=run_seq)
        self.mount_a.write_n_mb(new_file, 1)

        command = "flush_path {file}".format(file=test_new_file)
        self.asok_command(mds_rank, command, success_validator)

        # check that scrub fails on errors
        ino = self.mount_a.path_to_ino(new_file)
        rados_obj_name = "{ino:x}.00000000".format(ino=ino)
        command = "scrub start {file}".format(file=test_new_file)

        def _check_and_clear_damage(ino, dtype):
            all_damage = self.fs.rank_tell(["damage", "ls"], mds_rank)
            damage = [d for d in all_damage if d['ino'] == ino and d['damage_type'] == dtype]
            for d in damage:
                self.fs.mon_manager.raw_cluster_cmd(
                    'tell', 'mds.{0}'.format(self.fs.get_active_names()[mds_rank]),
                    "damage", "rm", str(d['id']))
            return len(damage) > 0

        # Missing parent xattr
        self.assertFalse(_check_and_clear_damage(ino, "backtrace"));
        self.fs.rados(["rmxattr", rados_obj_name, "parent"], pool=self.fs.get_data_pool_name())
        self.tell_command(mds_rank, command, success_validator)
        self.fs.wait_until_scrub_complete(sleep=5, timeout=30)
        self.assertTrue(_check_and_clear_damage(ino, "backtrace"));

        command = "flush_path /"
        self.asok_command(mds_rank, command, success_validator)

    def test_scrub_repair(self):
        mds_rank = 0
        test_dir = "scrub_repair_path"

        self.mount_a.run_shell(["mkdir", test_dir])
        self.mount_a.run_shell(["touch", "{0}/file".format(test_dir)])
        dir_objname = "{:x}.00000000".format(self.mount_a.path_to_ino(test_dir))

        self.mount_a.umount_wait()

        # flush journal entries to dirfrag objects, and expire journal
        self.fs.mds_asok(['flush', 'journal'])
        self.fs.mds_stop()

        # remove the dentry from dirfrag, cause incorrect fragstat/rstat
        self.fs.radosm(["rmomapkey", dir_objname, "file_head"])

        self.fs.mds_fail_restart()
        self.fs.wait_for_daemons()

        self.mount_a.mount_wait()

        # fragstat indicates the directory is not empty, rmdir should fail
        with self.assertRaises(CommandFailedError) as ar:
            self.mount_a.run_shell(["rmdir", test_dir])
        self.assertEqual(ar.exception.exitstatus, 1)

        self.tell_command(mds_rank, "scrub start /{0} repair".format(test_dir),
                          lambda j, r: self.json_validator(j, r, "return_code", 0))

        # wait a few second for background repair
        time.sleep(10)

        # fragstat should be fixed
        self.mount_a.run_shell(["rmdir", test_dir])

    @staticmethod
    def json_validator(json_out, rc, element, expected_value):
        if rc != 0:
            return False, "asok command returned error {rc}".format(rc=rc)
        element_value = json_out.get(element)
        if element_value != expected_value:
            return False, "unexpectedly got {jv} instead of {ev}!".format(
                jv=element_value, ev=expected_value)
        return True, "Succeeded"

    def tell_command(self, mds_rank, command, validator):
        log.info("Running command '{command}'".format(command=command))

        command_list = command.split()
        jout = self.fs.rank_tell(command_list, mds_rank)

        log.info("command '{command}' returned '{jout}'".format(
                     command=command, jout=jout))

        success, errstring = validator(jout, 0)
        if not success:
            raise AsokCommandFailedError(command, 0, jout, errstring)
        return jout

    def asok_command(self, mds_rank, command, validator):
        log.info("Running command '{command}'".format(command=command))

        command_list = command.split()

        # we just assume there's an active mds for every rank
        mds_id = self.fs.get_active_names()[mds_rank]
        proc = self.fs.mon_manager.admin_socket('mds', mds_id,
                                                command_list, check_status=False)
        rout = proc.exitstatus
        sout = proc.stdout.getvalue()

        if sout.strip():
            jout = json.loads(sout)
        else:
            jout = None

        log.info("command '{command}' got response code '{rout}' and stdout '{sout}'".format(
            command=command, rout=rout, sout=sout))

        success, errstring = validator(jout, rout)

        if not success:
            raise AsokCommandFailedError(command, rout, jout, errstring)

        return jout

    @staticmethod
    def clone_repo(client_mount, path):
        repo = "ceph-qa-suite"
        repo_path = os.path.join(path, repo)
        client_mount.run_shell(["mkdir", "-p", path])

        try:
            client_mount.stat(repo_path)
        except CommandFailedError:
            client_mount.run_shell([
                "git", "clone", '--branch', 'giant',
                "http://github.com/ceph/{repo}".format(repo=repo),
                "{path}/{repo}".format(path=path, repo=repo)
            ])

        return repo_path


class AsokCommandFailedError(Exception):
    """
    Exception thrown when we get an unexpected response
    on an admin socket command
    """

    def __init__(self, command, rc, json_out, errstring):
        self.command = command
        self.rc = rc
        self.json = json_out
        self.errstring = errstring

    def __str__(self):
        return "Admin socket: {command} failed with rc={rc} json output={json}, because '{es}'".format(
            command=self.command, rc=self.rc, json=self.json, es=self.errstring)
