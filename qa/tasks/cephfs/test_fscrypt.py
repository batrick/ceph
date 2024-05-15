from io import StringIO
import random
import string

from logging import getLogger

from tasks.cephfs.cephfs_test_case import CephFSTestCase
from tasks.cephfs.xfstests_dev import XFSTestsDev

log = getLogger(__name__)

class TestFSCrypt(CephFSTestCase):
    CLIENTS_REQUIRED = 1

    def setUp(self):
        self.protector = ''.join(random.choice(string.ascii_letters) for _ in range(8))
        self.key_file = "/tmp/key"
        self.path = "dir/"

        self.mount_a.run_shell_payload(f"sudo fscrypt setup --quiet")
        self.mount_a.run_shell_payload(f"sudo fscrypt status")
        self.mount_a.run_shell_payload(f"sudo fscrypt setup --quiet {self.mount_a.hostfs_mntpt}")
        self.mount_a.run_shell_payload(f"sudo fscrypt status")
        self.mount_a.run_shell_payload(f"sudo dd if=/dev/urandom of={self.key_file} bs=32 count=1")
        self.mount_a.run_shell_payload(f"mkdir -p {self.path}")
        self.mount_a.run_shell_payload(f"sudo fscrypt encrypt --quiet --source=raw_key --name={self.protector} --no-recovery --skip-unlock --key={self.key_file} {self.path}")
        self.mount_a.run_shell_payload(f"sudo fscrypt unlock --quiet --key=/tmp/key {self.path}")

    def tearDown(self):
        self.mount_a.run_shell_payload(f"sudo fscrypt lock --quiet {self.path}")

    def test_fscrypt_basic_mount(self):
        """
        That fscrypt can be setup and ingest files.
        """

        self.mount_a.run_shell_payload(f"cp -av /usr/bin {self.path}")

class TestFSCryptRecovery(TestFSCrypt):

    def test_fscrypt_journal_recovery(self):
        """
        That alternate_name can be recovered from the journal.
        """

        file = ''.join(random.choice(string.ascii_letters) for _ in range(255))

        self.mount_a.run_shell_payload(f"cd {path} && dd if=/dev/urandom of={file} bs=512 count=1 && stat {file}")

        # TODO: verify alternate_name is set
        self.fs.read_cache("/dir", depth=0)

        self.fs.fail()

        self.fs.journal_tool(['event', 'recover_dentries', 'list'], 0)
        self.fs.journal_tool(['journal', 'reset'], 0)

        self.fs.set_joinable()
        self.fs.wait_for_daemons()

        self.mount_a.run_shell_payload(f"cd {path} && stat {file}")


class TestFSCryptXFS(XFSTestsDev):

    def setup_xfsprogs_devs(self):
        self.install_xfsprogs = True

    def test_fscrypt_encrypt(self):
        # XXX: check_status is set to False so that we can check for command's
        # failure on our own (since this command doesn't set right error code
        # and error message in some cases) and print custom log messages
        # accordingly.
        proc = self.mount_a.client_remote.run(args=['sudo', 'env', 'DIFF_LENGTH=0',
            './check', '-g', 'encrypt'], cwd=self.xfstests_repo_path, stdout=StringIO(),
            stderr=StringIO(), timeout=900, check_status=False, omit_sudo=False,
            label='running tests for encrypt from xfstests-dev')

        if proc.returncode != 0:
            log.info('Command failed.')
        log.info(f'Command return value: {proc.returncode}')
        stdout, stderr = proc.stdout.getvalue(), proc.stderr.getvalue()
        log.info(f'Command stdout -\n{stdout}')
        log.info(f'Command stderr -\n{stderr}')

        # Currently only the 395,396,397,421,429,435,440,580,593,595 and 598
        # of the 26 test cases will be actually ran, all the others will be
        # skipped for now because of not supporting features in kernel or kceph.
        self.assertEqual(proc.returncode, 0)
        self.assertIn('Passed all 26 tests', stdout)

    def test_fscrypt_dummy_encryption_with_quick_group(self):
        self.write_local_config('test_dummy_encryption')

        # XXX: check_status is set to False so that we can check for command's
        # failure on our own (since this command doesn't set right error code
        # and error message in some cases) and print custom log messages
        # accordingly. This will take a long time and set the timeout to 3 hours.
        proc = self.mount_a.client_remote.run(args=['sudo', 'env', 'DIFF_LENGTH=0',
            './check', '-g', 'quick', '-E', './ceph.exclude'], cwd=self.xfstests_repo_path,
            stdout=StringIO(), stderr=StringIO(), timeout=10800, check_status=False,
            omit_sudo=False, label='running tests for dummy_encryption from xfstests-dev')

        if proc.returncode != 0:
            log.info('Command failed.')
        log.info(f'Command return value: {proc.returncode}')
        stdout, stderr = proc.stdout.getvalue(), proc.stderr.getvalue()
        log.info(f'Command stdout -\n{stdout}')
        log.info(f'Command stderr -\n{stderr}')

        # Currently, many test cases will be skipped due to unsupported features,
        # but still will be marked as successful.
        self.assertEqual(proc.returncode, 0)
        self.assertIn('Passed all ', stdout)
