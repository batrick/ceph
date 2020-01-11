import os
import errno
import logging

try:
    import configparser
except ImportError:
    import ConfigParser as configparser

try:
    from StringIO import StringIO
except ImportError:
    from io import StringIO

import cephfs

from ...exception import MetadataMgrException

log = logging.getLogger(__name__)

class MetadataManager(object):
    GLOBAL_SECTION = "GLOBAL"
    GLOBAL_META_KEY_VERSION = "version"
    GLOBAL_META_KEY_TYPE    = "type"
    GLOBAL_META_KEY_PATH    = "path"
    GLOBAL_META_KEY_STATE   = "state"

    MAX_IO_BYTES = 8 * 1024

    def __init__(self, fs, config_path, mode):
        self.fs = fs
        self.mode = mode
        self.config_path = config_path
        self.config = configparser.ConfigParser()

    def refresh(self):
        fd = None
        conf_data = StringIO()
        try:
            log.debug("opening config {0}".format(self.config_path))
            fd = self.fs.open(self.config_path, os.O_RDONLY)
            while True:
                data = self.fs.read(fd, -1, MetadataManager.MAX_IO_BYTES)
                if not len(data):
                    break
                conf_data.write(data.decode('utf-8'))
            conf_data.seek(0)
            self.config.readfp(conf_data)
        except cephfs.ObjectNotFound:
            raise MetadataMgrException(-errno.ENOENT, "metadata config '{0}' not found".format(self.config_path))
        except cephfs.Error as e:
            raise MetadataMgrException(-e.args[0], e.args[1])
        finally:
            if fd is not None:
                self.fs.close(fd)

    def flush(self):
        conf_data = StringIO()
        self.config.write(conf_data)
        conf_data.seek(0)

        fd = None
        try:
            fd = self.fs.open(self.config_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, self.mode)
            wrote = 0
            while True:
                data = conf_data.read()
                if not len(data):
                    break
                wrote += self.fs.write(fd, data.encode('utf-8'), -1)
            self.fs.fsync(fd, 0)
            log.info("wrote {0} bytes to config {1}".format(wrote, self.config_path))
        except cephfs.Error as e:
            raise MetadataMgrException(-e.args[0], e.args[1])
        finally:
            if fd is not None:
                self.fs.close(fd)

    def init(self, version, typ, path, state):
        # you may init just once before refresh (helps to overwrite conf)
        if self.config.has_section(MetadataManager.GLOBAL_SECTION):
            raise MetadataMgrException(-errno.EINVAL, "init called on an existing config")

        self.add_section(MetadataManager.GLOBAL_SECTION)
        self.update_section_multi(
            MetadataManager.GLOBAL_SECTION, {MetadataManager.GLOBAL_META_KEY_VERSION : str(version),
                                             MetadataManager.GLOBAL_META_KEY_TYPE    : str(typ),
                                             MetadataManager.GLOBAL_META_KEY_PATH    : str(path),
                                             MetadataManager.GLOBAL_META_KEY_STATE   : str(state)
            })

    def add_section(self, section):
        try:
            self.config.add_section(section)
        except configparser.DuplicateSectionError:
            return
        except:
            raise MetadataMgrException(-errno.EINVAL, "error adding section to config")

    def remove_option(self, section, key):
        if not self.config.has_section(section):
            raise MetadataMgrException(-errno.ENOENT, "section '{0}' does not exist".format(section))
        self.config.remove_option(section, key)

    def remove_section(self, section):
        self.config.remove_section(section)

    def update_section(self, section, key, value):
        if not self.config.has_section(section):
            raise MetadataMgrException(-errno.ENOENT, "section '{0}' does not exist".format(section))
        self.config.set(section, key, str(value))

    def update_section_multi(self, section, dct):
        if not self.config.has_section(section):
            raise MetadataMgrException(-errno.ENOENT, "section '{0}' does not exist".format(section))
        for key,value in dct.items():
            self.config.set(section, key, str(value))

    def get_option(self, section, key):
        if not self.config.has_section(section):
            raise MetadataMgrException(-errno.ENOENT, "section '{0}' does not exist".format(section))
        if not self.config.has_option(section, key):
            raise MetadataMgrException(-errno.ENOENT, "no config '{0}' in section '{1}'".format(key, section))
        return self.config.get(section, key)

    def get_global_option(self, key):
        return self.get_option(MetadataManager.GLOBAL_SECTION, key)
