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
# parser = argparse.ArgumentParser(description='CephFS Shell.')

def setup_cephfs():
    """ Mouting a cephfs """
    global cephfs
    cephfs = libcephfs.LibCephFS(conffile='/home/admin1/Documents/ceph/build/ceph.conf')
    cephfs.mount()

def get_file(file_name):
    fd = -1
    if not isinstance(file_name, bytes):
      file_name = bytes(file_name, encoding="ascii")
    cephfs.chdir(b'/')
    d = cephfs.opendir(b"/")
    dent = cephfs.readdir(d)
    try :
       fd = cephfs.open(file_name,'r', 0o755) 
       return fd 
    except : #handling file exception
       print( "\nFile not found\n") 
       return -1

def get_data(file_name):
    fd = get_file(file_name)
    data = ""
    if fd == -1 :
        return data
    BUF_SIZE = 65536
    while True:
      data = data + "" + cephfs.read(fd, BUF_SIZE, 1024)
      if not data:
        break
    return data 

def write_file(file_name, data):
    if not isinstance(file_name, bytes):
      file_name = bytes(file_name, encoding="ascii")
    fd = cephfs.open(file_name, 'w', 0o755)   
    data = bytes(data, encoding="ascii")
    cephfs.write(fd, data, 0)

class CephfsShell(cmd.Cmd):
   
    def __init__(self):
        super().__init__()
        self._set_prompt()
        self.intro = 'Ceph File System Shell'
        self.parser = argparse.ArgumentParser(description='CephFS Shell.')
        
    def _set_prompt(self):
        self.cwd = os.getcwd()
        self.prompt = '\033[01;33mCephFS >>>\033[00m ' 

    def postcmd(self, stop, line):
        self._set_prompt()
        return stop

    def do_mkdir(self,arglist):
        """Create directory.
        Usage: mkdir <new_dir> <permission> """    
        # parser = argparse.ArgumentParser(description='Create Directory.')
        self.parser.add_argument('dir_name', type = str, help = ' Name of new_directory.')
        self.parser.add_argument('-m', '--mode', action='store_const', help='Sets the access mode for the new directory.',const=int)
        args = self.parser.parse_args(shlex.split(arglist))
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
        # parser = argparse.ArgumentParser(description='Copy a file to Ceph File System from Local Directory.')
        self.parser.add_argument('local_path', type = str, help = 'Path of the file in the local system')
        self.parser.add_argument('remote_path', type = str,help = 'Path of the file in the remote system')
        args = self.parser.parse_args(shlex.split(arglist))
        print(cephfs.getcwd())
        shutil.copy(args.local_path,cephfs.getcwd()+args.remote_path)
        return 0

    def do_copyToLocal(self, arglist):
        """ Copy a file from Ceph File System to Local Directory.
        Usage : copyToLocal  <path_uri> """
        # parser = argparse.ArgumentParser(description='Copy a file from Ceph File System from Local Directory.')
        self.parser.add_argument('local_path', type = str, help = 'Path of the file in the local system')
        self.parser.add_argument('remote_path', type = str, help = 'Path of the file in the remote system')
        args = self.parser.parse_args(shlex.split(arglist))
        print(cephfs.getcwd())
        shutil.copy(cephfs.getcwd()+bytes(args.remote_path, encoding="ascii") ,args.local_path)
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
        
    def do_cd(self,arglist):
        """ Open a specific directory.
        Usage : opendir <dir_name>"""
        # parser = argparse.ArgumentParser(description='Create Directory.')
        self.parser.add_argument('dir_name', type = str, help = ' Name of the directory.')
        args = self.parser.parse_args(shlex.split(arglist))
        if args.dir_name == '..':
            d = cephfs.opendir(cephfs.getcwd())
            cephfs.closedir(d)
        else :
            cephfs.opendir(bytes(args.dir_name, encoding="ascii"))
            cephfs.chdir(bytes(args.dir_name, encoding="ascii"))

    def do_cwd(self, arglist):
        """Get current working directory.
        Usage : cwd"""
        print(cephfs.getcwd())

    def do_EOF(self, arglist):
        """Close the shell.
           Usage: Ctrl + D or EOF """
        # parser = argparse.ArgumentParser(description='Close Shell.')
        print("\nExiting CephFS Shell.......")
        sys.exit(0)

    def do_cat(self, arglist):
        # parser = argparse.ArgumentParser(description='')
        self.parser.add_argument('file_name', type = str, help = ' Name of File')
        args = self.parser.parse_args(shlex.split(arglist))
        print(get_data(args.file_name))

    def do_write(self, arglist):
        self.parser.add_argument('file_name', type = str, help = ' Name of File')
        self.parser.add_argument('data',type = str, help = 'Data to be written in the file.')
        args = self.parser.parse_args(shlex.split(arglist))
        write_file(args.file_name,args.data)
   
if __name__ == '__main__':
    setup_cephfs()
    c = CephfsShell()
    c.cmdloop()