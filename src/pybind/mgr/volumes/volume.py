from threading import Event
import errno
import json
try:
    import queue as Queue
except ImportError:
    import Queue

from . import SubVolume

class VolumeName():
    VOLUME_PREFIX = "vol:"
    VOLUME_POOL_PREFIX = "cephfs-vol."

    def __init__(name):
        self.name = name
        self.fs_name = "vol:"+name
        # XXX can mgr persist auth db?

    @static
    def is_volume(name):
        return name.startswith(VOLUME_PREFIX)

    def get_metadata_pool_name():
        return VOLUME_POOL_PREFIX+self.name+".meta"

    def get_data_pool_name():
        return VOLUME_POOL_PREFIX+self.name+".data"

class Volume():
    def __init__(fscid, vmgr, size=None):
        self.name = name
        self.id = fscid
        self.mgr = mgr
        # TODO: apply quotas to the filesystem root
        v.init_subvolumes()
        # options:
        # - pinning; max number of pins
        # - standby-replay
        # - quota (default)

        # default sub-volume

    def log(self, *args, **kwargs):
        self.vmgr.log(*args, **kwargs)

    def connect(self, premount_evict = None):
        """

        :param premount_evict: Optional auth_id to evict before mounting the filesystem: callers
                               may want to use this to specify their own auth ID if they expect
                               to be a unique instance and don't want to wait for caps to time
                               out after failure of another instance of themselves.
        """

        self.log.debug("Connecting to cephfs...")
        self.fs = cephfs.LibCephFS(rados_inst=self.vmgr.rados)
        self.log.debug("CephFS initializing...")
        self.fs.init()
        if premount_evict is not None:
            self.log.debug("Premount eviction of {0} starting".format(premount_evict))
            self.evict(premount_evict)
            self.log.debug("Premount eviction of {0} completes".format(premount_evict))
        self.log.debug("CephFS mounting...")
        self.fs.mount(filesystem_name=self.fs_name)
        self.log.debug("Connection to cephfs complete")

        # Recover from partial auth updates due to a previous
        # crash.
        self.recover()

    def get_mon_addrs(self):
        self.log.info("get_mon_addrs")
        result = []
        mon_map = self._rados_command("mon dump")
        for mon in mon_map['mons']:
            ip_port = mon['addr'].split("/")[0]
            result.append(ip_port)

        return result

    def disconnect(self):
        self.log.info("disconnect")
        if self.fs:
            self.log.debug("Disconnecting cephfs...")
            self.fs.shutdown()
            self.fs = None
            self.log.debug("Disconnecting cephfs complete")

        if self.rados and self.own_rados:
            self.log.debug("Disconnecting rados...")
            self.rados.shutdown()
            self.rados = None
            self.log.debug("Disconnecting rados complete")


    def evict(self, auth_id, timeout, volume_path):
        """
        Evict all clients based on the authorization ID and optionally based on
        the volume path mounted.  Assumes that the authorization key has been
        revoked prior to calling this function.

        This operation can throw an exception if the mon cluster is unresponsive, or
        any individual MDS daemon is unresponsive for longer than the timeout passed in.
        """

        client_spec = ["auth_name={0}".format(auth_id)]
        if volume_path:
            client_spec.append("client_metadata.root={0}".
                               format(self._get_path(volume_path)))

        log.info("evict clients with {0}".format(', '.join(client_spec)))

        mds_map = self.get_mds_map()
        assert 0 in mds_map['in']

        # It is sufficient to talk to rank 0 for this volume to evict the
        # client, the MDS will send an osd blacklist command that will cause
        # the other ranks to also kill the client's session.
        # XXX Do we need this if it's not done in parallel?
        thread = RankEvicter(self, client_spec, 0, mds_map, timeout)
        thread.start()
        thread.join()

        mds_map = self.get_mds_map()
        up = {}
        for name, gid in mds_map['up'].items():
            # Quirk of the MDSMap JSON dump: keys in the up dict are like "mds_0"
            assert name.startswith("mds_")
            up[int(name[4:])] = gid

        # For all MDS ranks held by a daemon
        # Do the parallelism in python instead of using "tell mds.*", because
        # the latter doesn't give us per-mds output
        threads = []
        for rank, gid in up.items():
            thread = RankEvicter(self, client_spec, rank, gid, mds_map,
                                 timeout)
            thread.start()
            threads.append(thread)

        for t in threads:
            t.join()

        log.info("evict: joined all")

        for t in threads:
            if not t.success:
                msg = ("Failed to evict client with {0} from mds {1}/{2}: {3}".
                       format(', '.join(client_spec), t.rank, t.gid, t.exception)
                      )
                log.error(msg)
                raise EvictionError(msg)


class VolumeIndex():
    def __init__(self):
        self.volumes = map()

    def _get_volume(self, vn):
        v = self.volumes.get(vn)
        if v:
            return v
        else:
            fs_map = self.get('fs_map')
            for fs in fs_map['filesystems']:
                if fs['mdsmap']['fs_name'] == vn.fs_name:
                    v = Volume(vn)
                    self.volumes[vn.name] = v
                    return v
            return None

    def _get_volumes(self):
        fs_map = self.get('fs_map')
        for fs in fs_map['filesystems']:
            if fs['mdsmap']['fs_name'] == vol_name: #???? XXX
                yield Volume(fs)

    def create(self, name, size=None):
        name = VolumeName(name)

        metadata_pool_name = name.get_metadata_pool_name()
        r, outb, outs = self.mon_command({
            'prefix': 'osd pool create',
            'pool': metadata_pool_name,
            'pg_num': 1
        })
        if r != 0:
            # TODO handle EEXIST
            return r, outb, outs

        data_pool_name = name.get_data_pool_name()
        r, outb, outs = self.mon_command({
            'prefix': 'osd pool create',
            'pool': data_pool_name,
            'pg_num': 1
        })
        if r != 0:
            # TODO handle EEXIST
            return r, outb, outs

        r, outb, outs = self.mon_command({
            'prefix': 'fs new',
            'fs_name': name.fs_name,
            'metadata': metadata_pool_name,
            'data': data_pool_name,
        })
        if r != 0:
            # TODO handle EEXIST
            pass

        return Volume(name, size=size)

    def set_conf(self):
        # e.g. standby-replay; ??? 
        # standby-replay should be a setting on a FS
        # set default sub-volume data pool?
        pass

    def describe(self, name):
        pass

    def ls(self):
        result = []
        for volume in self._get_volumes():
            result.append({'name': volume.name})

        return json.dumps(result, indent=2)

    def importfs(self, fs_name):
		# rename fs?
        pass

    def rm(self, name):
        name = VolumeName(name)

        volume = self.get_volume(name)
        if volume is None:
            self.log.warning("Filesystem already gone for volume '{0}'".format(vol_name))
        else:
            cmd = {
                'prefix': 'fs fail',
                'fs_name': name.fs_name,
            }
            r, out, err = self.mon_command(cmd)
            if r != 0:
                pass
            cmd = {
                'prefix': 'fs rm',
                'fs_name': name.fs_name,
                'yes_i_really_mean_it': True,
            }
            r, out, err = self.mon_command(cmd)
            if r != 0:
                pass
