import logging
from StringIO import StringIO

from xfstests_dev import XFSTestsDev

log = logging.getLogger(__name__)

class TestACLs(XFSTestsDev):

    def test_acls(self):
        from tasks.cephfs.fuse_mount import FuseMount
        from tasks.cephfs.kernel_mount import KernelMount

        if isinstance(self.mount_a, FuseMount):
            log.info('client is fuse mounted')
        elif isinstance(self.mount_a, KernelMount):
            log.info('client is kernel mounted')

        self.mount_a.client_remote.run(args=['sudo', './check',
            'generic/099'], cwd=self.repo_path, stdout=StringIO(),
            stderr=StringIO(), timeout=30, check_status=True,
            label='running tests for ACLs from xfstests-dev')
