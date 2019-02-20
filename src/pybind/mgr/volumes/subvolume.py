from threading import Event
import errno
import json
try:
    import queue as Queue
except ImportError:
    import Queue


class SubVolume():
    def __init__(name, fsmap, size=None):
        self.name = name
        self.id = fsmap['id']
        self.fsmap = fsmap
        # TODO: apply quotas to the filesystem root
        v.init_subvolumes()

class VolumeIndex():
    def __init__(self):
        self.volumes = map()
        # options:
        # - pinning; max number of pins
        # - standby-replay

        # default sub-volume

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
