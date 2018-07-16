"""
Task for running foo
"""
from cStringIO import StringIO
import logging

from teuthology import misc
from teuthology.exceptions import ConfigError
from teuthology.task import Task
from teuthology.orchestra import run
from teuthology.orchestra.remote import Remote

log = logging.getLogger(__name__)


class CephFSShellTest(Task):
    """
    Install and mount foo
    This will require foo.
    For example:
    tasks:
    - foo:
        biz:
        bar:
    Possible options for this task are:
        biz:
        bar:
        baz:
    """
    def __init__(self, ctx, config):
        super(CephFSShellTest, self).__init__(ctx, config)
        self.log = log
        log.info('In __init__ step, hello world')

    def setup(self):
        super(CephFSShellTest, self).setup()
        config = self.config
        log.info('In setup step, hello world')
        log.debug('config is: %r', config)

    def begin(self):
        super(CephFSShellTest, self).begin()
        log.info('In begin step, hello world')
        ctx = self.ctx
        log.debug('ctx is: %r', ctx)
        remote = Remote('rpavani1998@teuthology.front.sepia.ceph.com')
        remote.run(args=['echo','"hello world: console output 15"'], stdout=StringIO())
        remote.run(args=['sleep', '15'], stdout=StringIO())

    def teardown(self):
        log.info('Teardown step')

task = CephFSShellTest

