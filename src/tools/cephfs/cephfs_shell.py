#!/usr/bin/env python3
# coding=utf-8

import argparse
import os
import sys
import cmd
import cephfs as libcephfs
import shlex
import shutil

cephfs =  None

def setup_cephfs():
    """ Mouting a cephfs """
    global cephfs
    cephfs = libcephfs.LibCephFS(conffile='/home/admin1/Documents/ceph/build/ceph.conf')
    cephfs.mount()

class CephfsShell(cmd.Cmd):
    def __init__(self):
        super().__init__()
        self._set_prompt()
        self.intro = 'Ceph File System Shell'

    def _set_prompt(self):
        self.cwd = os.getcwd()
        self.prompt = '\033[01;33mCephFS >>>\033[00m ' #self.colorize('{!r} $ '.format(self.cwd), 'cyan')

    def postcmd(self, stop, line):
        self._set_prompt()
        return stop

    def do_mkdir(self,arglist):
        """Create directory.
            Usage: mkdir <new_dir> <permission> """    
        parser = argparse.ArgumentParser(description='Create Directory.')
        parser.add_argument('dir_name', type = str, help = ' Name of new_directory.')
        parser.add_argument('-m', '--mode', action='store_const', help='Sets the access mode for the new directory.',const=int)
        args = parser.parse_args(shlex.split(arglist))
        path = cephfs.getcwd() +  bytes(args.dir_name, encoding="ascii")
        if args.mode :
            permission = args.mode
        else :
            permission = 777
        print(path,permission)
        cephfs.mkdir(path, permission)

    def do_copyFromLocal(self, arglist):
        """ Copy a file to Ceph File System from Local Directory.
            Usage : copyFromLocal  <path_uri> """
        parser = argparse.ArgumentParser(description='Copy a file to Ceph File System from Local Directory.')
        parser.add_argument('local_path', type = str, help = 'Path of the file in the local system')
        parser.add_argument('remote_path', type = str,help = 'Path of the file in the remote system')
        args = parser.parse_args(shlex.split(arglist))
        print(cephfs.getcwd())
        shutil.copy(args.local_path,cephfs.getcwd()+args.remote_path)
        return 0

    def do_copyToLocal(self, arglist):
        """ Copy a file from Ceph File System to Local Directory.
            Usage : copyToLocal  <path_uri> """
        parser = argparse.ArgumentParser(description='Copy a file from Ceph File System from Local Directory.')
        parser.add_argument('local_path', type = str, help = 'Path of the file in the local system')
        parser.add_argument('remote_path', type = str, help = 'Path of the file in the remote system')
        args = parser.parse_args(shlex.split(arglist))
        print(cephfs.getcwd())
        shutil.copy(cephfs.getcwd()+args.remote_path,args.local_path)
        return 0

    def do_ls(self,arglist):
        """ List all the files and directories in the current working directory
            Usage : ls"""
        d = cephfs.opendir(cephfs.getcwd())
        dent = cephfs.readdir(d)
        while dent:
            if (dent.d_name not in [b".", b".."]):
                print(dent.d_name)
            dent = cephfs.readdir(d)
        cephfs.closedir(d)
        
    def do_opendir(self,arglist):
        """ Open a specific directory.
            Usage : opendir <dir_name>"""
        parser = argparse.ArgumentParser(description='Create Directory.')
        parser.add_argument('dir_name', type = str, help = ' Name of the directory.')
        args = parser.parse_args(shlex.split(arglist))
        cephfs.opendir(bytes(args.dir_name, encoding="ascii"))
        cephfs.chdir(bytes(args.dir_name, encoding="ascii"))

    def do_closedir(self, arglist):
        """ Close the present working directory 
            Usage : closedir """
        d = cephfs.opendir(cephfs.getcwd())
        cephfs.closedir(d)
        cephfs.chdir(cephfs.getcwd())

    def do_cwd(self, arglist):
        """Get current working directory.
           Usage : cwd"""
        cephfs.getcwd()

    def do_EOF(self, arglist):
        """Close the shell.
           Usage: Ctrl + D or EOF """
        parser = argparse.ArgumentParser(description='Close Shell.')
        print("\nExiting CephFS Shell.......")
        sys.exit(0)
   
if __name__ == '__main__':
    setup_cephfs()
    c = CephfsShell()
    c.cmdloop()