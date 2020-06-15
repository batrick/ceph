import os
import errno

import cephfs

from ..exception import VolumeException
from distutils.util import strtobool

_pin_value = {
    "export": lambda x: int(strtobool(x)),
    "distributed": lambda x: int(strtobool(x)),
    "random": float,
}
_pin_xattr = {
    "export": "ceph.dir.pin",
    "distributed": "ceph.dir.pin.distributed",
    "random": "ceph.dir.pin.random",
}

def pin(fs, path, pin_type, pin_setting):
    """
    Set a pin on a directory.
    """
    assert pin_type in _pin_xattr

    try:
        pin_setting = _pin_value[pin_type](pin_setting)
    except Exception as e:
        raise VolumeException(-errno.EINVAL, f"pin value wrong type: {e}")

    try:
        fs.setxattr(path, _pin_xattr[pin_type], str(pin_setting).encode('utf-8'), 0)
    except cephfs.Error as e:
        raise VolumeException(-e.args[0], e.args[1])

        raise VolumeException(-e.args[0], e.args[1])
