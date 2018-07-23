#!/usr/bin/env python3
# coding = utf-8

import argparse
import os
import sys
from cmd2 import Cmd, with_argparser
import cephfs as libcephfs
import shutil
import traceback
import colorama
import readline
import fnmatch
import math
cephfs = None

def setup_cephfs():
    """ 
    Mouting a cephfs 
    """
    global cephfs
    cephfs = libcephfs.LibCephFS(conffile = '/home/admin1/Documents/ceph/build/ceph.conf')
    cephfs.mount()

def mode_notation(mode):
    """
    """
    permission_bits = {'0':'---', '1':'--x', '2':'-w-', '3': '-wx', '4':'r--', '5':'r-x', '6':'rw-', '7':'rwx'}
    mode = str(oct(mode))
    notation = '-'
    if mode[2] == '4':
        notation = 'd'
    for i in mode[-3:]:
        notation += permission_bits[i]
    return notation

def get_chunks(file_size):
    chunk_start = 0
    chunk_size = 0x20000  # 131072 bytes, default max ssl buffer size
    while chunk_start + chunk_size < file_size:
        yield(chunk_start, chunk_size)
        chunk_start += chunk_size
    final_chunk_size = file_size - chunk_start
    yield(chunk_start, final_chunk_size)

def to_bytes(string):
    return bytes(string, encoding = 'utf-8')

def list_items(dir_name = ''):
    if not isinstance(dir_name, bytes):
        dir_name = to_bytes(dir_name)
    if dir_name == '':
        d = cephfs.opendir(cephfs.getcwd())
    else :
        d = cephfs.opendir(dir_name)
    dent = cephfs.readdir(d)
    items = []
    while dent:
        items.append(dent)
        dent = cephfs.readdir(d)
    cephfs.closedir(d)
    return items

def glob(dir_name, pattern):
    if isinstance(dir_name, bytes):
        dir_name = dir_name.decode('utf-8')
    paths = []
    parent_dir = dir_name.rsplit('/', 1)[0]
    if parent_dir == '':
        parent_dir = '/'
    if dir_name == '/' or is_dir_exists(dir_name.rsplit('/', 1)[1], parent_dir) :
        for i in list_items(dir_name)[2:]:
            if fnmatch.fnmatch(i.d_name.decode('utf-8'), pattern):
                paths.append((dir_name + '/' + i.d_name.decode('utf-8')).replace('//', '/'))
    return paths

def get_all_possible_paths(pattern):
    paths = []
    dir_ = cephfs.getcwd()
    is_rel_path = True
    if pattern[0] == '/':
        dir_ = '/'
        pattern = pattern[1:]
        is_rel_path = False
    patterns = pattern.split('/')
    paths.extend(glob(dir_, patterns[0]))
    patterns.pop(0) 
    for index in range(len(patterns)) :
        for path in paths :
            paths.extend(glob(path, patterns[index]))
    return [path for path in paths if fnmatch.fnmatch(path, '/'*is_rel_path + pattern)]

suffixes = ['B', 'K', 'M', 'G', 'T', 'P']
def humansize(nbytes):
    i = 0
    while nbytes >= 1024 and i < len(suffixes)-1:
        nbytes /= 1024.
        i += 1
    nbytes = math.ceil(nbytes)
    f = ('%d' % nbytes).rstrip('.')
    return '%s%s' % (f, suffixes[i])

def print_long(file_name, flag, human_readable):
    if not isinstance(file_name, bytes):
      file_name = to_bytes(file_name)
    info = cephfs.stat(file_name)
    if flag :
        file_name = colorama.Fore.BLUE + file_name.decode('utf-8').rsplit('/', 1)[1] + '/'+ colorama.Style.RESET_ALL
    else :
        file_name = file_name.decode('utf-8').rsplit('/', 1)[1] 
    if human_readable :
        print('{}\t{:10s} {} {} {} {}'.format(mode_notation(info.st_mode), humansize(info.st_size), info.st_uid, info.st_gid, info.st_mtime, file_name, sep = '\t'))
    else :
        print('{} {:12d} {} {} {} {}'.format(mode_notation(info.st_mode), info.st_size, info.st_uid, info.st_gid, info.st_mtime, file_name, sep = '\t'))

def word_len(word):
    """
    Returns the word lenght, minus any color codes.
    """
    if word[0] == '\x1b':
        return len(word) - 9  
    return len(word)

def is_dir_exists(dir_name, dir_ = ''):
    if dir_ == '': 
        dir_ = cephfs.getcwd()
    elif not isinstance(dir_, bytes):
        dir_ = to_bytes(dir_)
    if not isinstance(dir_name, bytes):
        dir_name = to_bytes(dir_name)
    return len([i for i in set(list_items(dir_)) if i.d_name == dir_name and i.is_dir()]) > 0

def is_file_exists(file_name, dir = ''):
    if dir == '':
        dir = cephfs.getcwd()
    elif not isinstance(dir, bytes):
        dir = to_bytes(dir)
    if not isinstance(file_name, bytes):
        file_name = to_bytes(file_name)
    return len([i for i in set(list_items(dir)) if i.d_name == file_name and not i.is_dir()]) > 0

def print_list(words, termwidth = 79):
    if not words :
        return
    width = max([word_len(word) for word in words]) + 2
    nwords = len(words)
    ncols = max(1, (termwidth + 1) // (width + 1))
    nrows = (nwords + ncols - 1) // ncols
    for row in range(nrows):
        for i in range(row, nwords, nrows):
            word = words[i]
            if word[0] == '\x1b':
                print('%-*s'% (width + 9, words[i]), end = '\n'if i + nrows >= nwords else '')
            else:
                print('%-*s'% (width, words[i]), end = '\n'if i + nrows >= nwords else '')

def copy_from_local(local_path, remote_path):
    stdin = -1
    if local_path == '-':
        data = ''.join([line for line in sys.stdin])
        file_size = len(data)
    else :
        file_ = open(local_path, 'rb')
        stdin = 1
        file_size = os.path.getsize(local_path)
        print('File {}: {}'.format(local_path, file_size))
    if is_file_exists(remote_path):
        return
    fd = cephfs.open(to_bytes(remote_path), 'w', 0o666) 
    if file_size == 0:
        return  
    progress = 0
    while True:
        data = file_.read(65536)
        if not data:
            break
        wrote = cephfs.write(fd, data, progress) 
        if wrote < 0:
            break
        progress += wrote
        print('{} of {} bytes read ({}%)'.format(progress, file_size, int(progress / file_size * 100)), end = '\r')
    cephfs.close(fd)
    if stdin > 0 : 
        file_.close()
    print()

def copy_to_local(remote_path, local_path):
    print('lp', local_path)
    if not os.path.exists(local_path.rsplit('/', 1)[0]) :
          os.makedirs(local_path.rsplit('/', 1)[0], exist_ok = True)
    fd = None
    if len(remote_path.rsplit('/', 1)) > 2 and remote_path.rsplit('/', 1)[1] == '':
        return
    if local_path != '-':
        fd = open(local_path, 'wb+')
    file_ = cephfs.open(to_bytes(remote_path), 'r')
    file_size = cephfs.stat(remote_path).st_size
    if file_size <= 0 :
        return
    print('File {}: {}'.format(remote_path, file_size))
    progress = 0
    for chunk_start, chunk_size in get_chunks(file_size):
        file_chunk = cephfs.read(file_, chunk_start, chunk_size)
        progress += len(file_chunk)
        if fd :
            fd.write(file_chunk)
            print('{} of {} bytes read ({}%)'.format(progress, file_size, int(progress / file_size * 100)), end = '\r') 
        else :
            print(file_chunk.decode('utf-8'))  
    print() 
    cephfs.close(file_)
    if fd : 
        fd.close()   

def dirwalk(dir_name, giveDirs=0):
    """
    walk a directory tree, using a generator
    """
    dir_name = dir_name.replace('//', '/') 
    for item in list_items(dir_name)[2:]:
        fullpath = dir_name + '/'+ item.d_name.decode('utf-8')
        yield fullpath.rsplit('/', 1)[0] + '/'
        if is_dir_exists(item.d_name, fullpath.rsplit('/', 1)[0]) :
            if not len(list_items(fullpath)[2:]):
                yield fullpath.replace('//', '/')
            else:
                for x in dirwalk(fullpath): 
                    if giveDirs:
                        yield x 
                    else:
                        yield x 
        else:
            yield fullpath.replace('//', '/')

class CephfsShell(Cmd):

    def __init__(self):
        super().__init__()
        self.working_dir = cephfs.getcwd().decode('utf-8')
        self.set_prompt()
        self.intro = 'Ceph File System Shell'
        self.interactive = False
        self.umask = '2'
        
    def default(self, line):
        print('Unrecognized command:', line)

    def set_prompt(self):
        self.prompt = '\033[01;33mCephFS:~' + colorama.Fore.LIGHTCYAN_EX + self.working_dir +  colorama.Style.RESET_ALL + '\033[01;33m>>>\033[00m '

    def create_argparser(self, command):
        try:
            argparse_args = getattr(self, 'argparse_'+ command)
        except AttributeError:
            return None
        doc_lines = getattr(self, 'do_'+ command).__doc__.expandtabs().splitlines()
        if ''in doc_lines:
            blank_idx = doc_lines.index('')
            usage = doc_lines[:blank_idx]
            description = doc_lines[blank_idx + 1:]
        else:
            usage = doc_lines
            description = []
        parser = argparse.ArgumentParser(
            prog = command, 
            usage = '\n'.join(usage), 
            description = '\n'.join(description), 
            formatter_class = argparse.ArgumentDefaultsHelpFormatter
        )
        for args, kwargs in argparse_args:
            parser.add_argument(*args, **kwargs)
        return parser

    def complete_filenames(self, text, line, begidx, endidx):
        if not text:
            completions = [x.d_name.decode('utf-8') + '/' * int(x.is_dir()) for x in list_items(cephfs.getcwd())[2:]]
        else:
            if text.count('/') > 0:
                completions = [text.rsplit('/', 1)[0] + '/' + x.d_name.decode('utf-8') + '/'*int(x.is_dir())  for x in list_items('/'+ text.rsplit('/', 1)[0])[2:] if x.d_name.decode('utf-8').startswith(text.rsplit('/', 1)[1])]
            else :
                completions = [x.d_name.decode('utf-8') + '/' * int(x.is_dir()) for x in list_items()[2:] if x.d_name.decode('utf-8').startswith(text)]
            if len(completions) == 1 and completions[0][-1] == '/':
                dir_, file_ = completions[0].rsplit('/', 1)
                completions.extend([dir_ + '/' + x.d_name.decode('utf-8') + '/' * int(x.is_dir())  for x in list_items('/'+ dir_)[2:] if x.d_name.decode('utf-8').startswith(file_)])
            return self.delimiter_complete(text, line, begidx, endidx, completions, '/')
        return completions
    
    def onecmd(self, line):
        """
        Global error catcher
        """
        try:
            res = Cmd.onecmd(self, line)
            if self.interactive: 
                self.set_prompt()
            return res
        except ConnectionError as e:
            print('***', e)
        except KeyboardInterrupt:
            print('Command aborted')
        except Exception as e:
            print(e)
            traceback.print_exc(file = sys.stdout)

    def complete_mkdir(self, text, line, begidx, endidx):
        """ 
        auto complete of file name.
        """    
        return self.complete_filenames(text, line, begidx, endidx)

    mkdir_parser = argparse.ArgumentParser(description = 'Create Directory.')
    mkdir_parser.add_argument('dir_name', type = str, metavar = 'DIR_NAME', help = 'Name of new_directory.')
    mkdir_parser.add_argument('-m', '--mode', action = 'store', help = 'Sets the access mode for the new directory.', type = str)
    mkdir_parser.add_argument('-p', '--parent', action = 'store_true', help = 'Create parent directories as necessary. When this option is specified, no error is reported if a directory already exists.')
    
    @with_argparser(mkdir_parser)
    def do_mkdir(self, args):
        """
        Create directory.
           Usage: mkdir [-m MODE] <dir_name> 
        """    
        try:
            path = to_bytes('/'+ args.dir_name)
            if args.mode :
                permission = int(args.mode, 8)
            else :
                permission = 0o777
            if args.parent :
                cephfs.mkdirs(path, permission)
            else :
                cephfs.mkdir(path, permission)
        except:
             traceback.print_exc(file = sys.stdout)

    def complete_put(self, text, line, begidx, endidx):
        """ 
        auto complete of file name.
        """    
        index_dict = {1: self.path_complete}
        return self.index_based_complete(text, line, begidx, endidx, index_dict)

    put_parser = argparse.ArgumentParser(description = 'Copy a file to Ceph File System from Local Directory.')
    put_parser.add_argument('local_path', type = str, help = 'Path of the file in the local system')
    put_parser.add_argument('remote_path', type = str, help = 'Path of the file in the remote system')
    put_parser.add_argument('-f', '--force', action = 'store_true', help = 'Overwrites the destination if it already exists.')

    @with_argparser(put_parser)
    def do_put(self, args):
        """ 
        Copy a file to Ceph File System from Local Directory.
            Usage : put <local_path> <remote_path> 
        """
        try:       
            root_src_dir = args.local_path 
            root_dst_dir = args.remote_path 
            if args.local_path == '.':
                root_src_dir = os.getcwd()
            if args.remote_path == '.':
                root_dst_dir = cephfs.getcwd().decode('utf-8') 
            elif root_dst_dir[-1] != '/':
                root_dst_dir += '/'
            if args.local_path == '-'or os.path.isfile(root_src_dir):
                copy_from_local(root_src_dir, root_dst_dir)
            else :
                for src_dir, dirs, files in os.walk(root_src_dir):
                    dst_dir = src_dir.replace(root_src_dir, root_dst_dir, 1)
                    if not args.force and dst_dir != '/':
                        cephfs.mkdirs(to_bytes(dst_dir), 0o777)
                    elif args.force and not is_dir_exists(dst_dir):
                        cephfs.mkdirs(to_bytes(dst_dir), 0o777)
                    for file_ in files:
                        src_file = os.path.join(src_dir, file_)
                        dst_file = '/'+ dst_dir + '/'+ file_
                        if args.force and is_file_exists(dst_file):
                            cephfs.unlink(to_bytes(dst_file))
                        copy_from_local(src_file, dst_file.replace('//', '/'))
        except :
             traceback.print_exc(file = sys.stdout)
    
    def complete_get(self, text, line, begidx, endidx):
        """ 
        auto complete of file name.
        """    
        return self.complete_filenames(text, line, begidx, endidx)

    get_parser = argparse.ArgumentParser(description = 'Copy a file from Ceph File System from Local Directory.')
    get_parser.add_argument('remote_path', type = str, help = 'Path of the file in the remote system')
    get_parser.add_argument('local_path', type = str, help = 'Path of the file in the local system')

    @with_argparser(get_parser)
    def do_get(self, args):
        """ 
        Copy a file/directory  from Ceph File System to Local Directory.
            Usage : get <remote_path> <local_path>
        """
        try:
            root_src_dir = args.remote_path
            root_dst_dir = args.local_path 
            if args.local_path == '.':
                root_dst_dir = os.getcwd()
            if args.remote_path == '.':
                root_src_dir = cephfs.getcwd().decode('utf-8')
            if args.local_path == '-':
                copy_to_local(root_src_dir, '-')
            elif is_file_exists(args.remote_path) :# any([i for i in list_items() if i.d_name.decode('utf-8') == args.remote_path and not i.is_dir()]) :
                copy_to_local(root_src_dir, root_dst_dir + '/'+ root_src_dir)
            elif '/'in root_src_dir and  is_file_exists(root_src_dir.rsplit('/', 1)[1], root_src_dir.rsplit('/', 1)[0]) : #any([i for i in list_items() if i.d_name.decode('utf-8') == and not i.is_dir()]) :
                copy_to_local(root_src_dir, root_dst_dir)
            else :
                files = list(reversed(sorted(dirwalk(root_src_dir))))
                if len(files) == 0 :
                    os.makedirs(root_dst_dir + '/' + root_src_dir)
                for file_ in files:
                    dst_dirpath, dst_file = file_.rsplit('/', 1)
                    if dst_dirpath in files :
                        files.remove(dst_dirpath)
                    if not is_dir_exists(file_) and not os.path.exists(root_dst_dir + '/' +file_):
                        copy_to_local(file_, (root_dst_dir + '/'+ dst_dirpath + '/'+ dst_file).replace('//', '/'))
                    elif is_dir_exists(file_) and not os.path.exists((root_dst_dir + '/'+ dst_dirpath + '/'+ dst_file).replace('//', '/')) :
                        os.makedirs((root_dst_dir + '/'+ dst_dirpath + '/'+ dst_file).replace('//', '/'))
            return 0
        except :
              traceback.print_exc(file = sys.stdout)


    def complete_ls(self, text, line, begidx, endidx):
        """
        auto complete of file name.
        """    
        return self.complete_filenames(text, line, begidx, endidx)
        
    ls_parser = argparse.ArgumentParser(description = 'Copy a file from Ceph File System from Local Directory.')
    ls_parser.add_argument('-l', '--long', action = 'store_true', help = 'Detailed list of items in the directory.')
    ls_parser.add_argument('-r', '--reverse', action = 'store_true', help = 'Reverse order of listing items in the directory.')
    ls_parser.add_argument('-H', action = 'store_true', help = 'Human Readable')
    ls_parser.add_argument('-S', action = 'store_true', help = 'Sort by file_size')
    ls_parser.add_argument('dir_names', help = 'Name of Directories', nargs = '*', default = [''])     
    
    @with_argparser(ls_parser)
    def do_ls(self, args):
        """ 
        List all the files and directories in the current working directory
            Usage : ls
        """
        try:
            directories = args.dir_names
            print(directories)
            for dir_name in directories :
                values = []
                items = []
                if dir_name.count('*') > 0 :
                    all_items = get_all_possible_paths(dir_name)
                    if len(all_items) == 0 :
                        continue
                    dir_name = all_items[0].rsplit('/',1)[0]
                    if dir_name == '':
                        dir_name = '/'
                    items = [item for item in list_items(dir_name) for i in all_items if i.rsplit('/', 1)[1] == item.d_name.decode('utf-8') and not item.is_dir()]
                    dirs = [(dir_name + '/' + item.d_name.decode('utf-8')).replace('//', '/') for item in list_items(dir_name) for i in all_items if i.rsplit('/', 1)[1] == item.d_name.decode('utf-8') and item.is_dir()]
                    directories.extend(dirs)
                    if len(dirs) == 0 :
                        print(dir_name, ':')
                    items = sorted(items, key = lambda item : item.d_name)
                else :
                    if dir_name != '' and dir_name != cephfs.getcwd().decode('utf-8'):
                        print(dir_name, ':')
                    items = sorted(list_items(dir_name), key = lambda item : item.d_name)
                if len(items) > 2 and items[0].d_name.decode('utf-8') == '.':
                    items = items[2:]
                flag = 0
                if args.S :
                    items = sorted(items, key = lambda item : cephfs.stat(to_bytes(dir_name + '/' + item.d_name.decode('utf-8'))).st_size)    
                if args.reverse :
                    items = reversed(items)
                for item in items:
                    path = item
                    if not isinstance(item, str) :
                        path = item.d_name.decode('utf-8') 
                        if item.is_dir() :
                            flag = 1
                        else :
                            flag = 0
                    if args.long and args.H  :
                        print_long(cephfs.getcwd().decode('utf-8') + dir_name + '/' + path, flag, True)
                    elif args.long :
                        print_long(cephfs.getcwd().decode('utf-8') + dir_name + '/' + path, flag, False)
                    else :
                        values.append(colorama.Fore.BLUE * flag + path + '/'* flag + colorama.Style.RESET_ALL  * flag)
                if not args.long :
                    print_list(values, shutil.get_terminal_size().columns)
                    if dir_name != directories[-1]:
                        print()
        except :
            traceback.print_exc(file = sys.stdout)
   
    def complete_rmdir(self, text, line, begidx, endidx):
        """ 
        auto complete of file name.
        """    
        return self.complete_filenames(text, line, begidx, endidx)

    rmdir_parser = argparse.ArgumentParser(description = 'Remove Directory.')
    rmdir_parser.add_argument('dir_paths', help = 'Directory Path.',nargs = '*', default = [''])
    rmdir_parser.add_argument('-p', '--parent', action = 'store_true', help = 'Remove parent directories as necessary. When this option is specified, no error is reported if a directory has any sub-directories, files')
    
    @with_argparser(rmdir_parser)
    def do_rmdir(self, args):
        """ 
        Remove a specific Directory
            Usage : rmdir <dir_path>
        """
        try:
            is_pattern = False
            directories = args.dir_paths
            for i, dir_path in enumerate(directories):
                if dir_path.count('*') > 0 :
                    is_pattern = True
                    all_items = get_all_possible_paths(dir_path)
                    if len(all_items) > 0 :
                        dir_path = all_items[0].rsplit('/',1)[0]
                    if dir_path == '':
                        dir_path = '/'
                    dirs = [(dir_path + '/' + item.d_name.decode('utf-8')).replace('//', '/') for item in list_items(dir_path) for i in all_items if i.rsplit('/', 1)[1] == item.d_name.decode('utf-8') and item.is_dir()]
                    directories.extend(dirs)
                    continue
                else :
                    is_pattern = False
                path = ''
                if args.parent :
                    files = reversed(sorted(set(dirwalk(cephfs.getcwd().decode('utf-8') + dir_path))))     
                    for i, path in enumerate(files):
                        if path[1:] != dir_path : 
                            print('Removed : ', path)
                            try :
                                cephfs.rmdir(to_bytes(path))
                            except :
                                cephfs.unlink(to_bytes(path)) 
                if not is_pattern and dir_path != path:                      
                    cephfs.rmdir(to_bytes(dir_path))
        except :
            traceback.print_exc(file = sys.stdout)
    
    def complete_rm(self, text, line, begidx, endidx):
        """ 
        auto complete of file name.
        """ 
        return self.complete_filenames(text, line, begidx, endidx)

    rm_parser = argparse.ArgumentParser(description = 'Remove File.')
    rm_parser.add_argument('file_paths', help = 'File Path.', nargs = '+')

    @with_argparser(rm_parser)
    def do_rm(self, args):
        """
        Remove a specific file
            Usage : rm <file_path>
        """
        try:
            files = args.file_paths
            print(args.file_paths)
            for file_path in files :
                if file_path.count('*') > 0 :
                    files.extend(get_all_possible_paths(file_path))
                else :
                    cephfs.unlink(to_bytes(file_path))
        except :
            traceback.print_exc(file = sys.stdout)
   
    def complete_mv(self, text, line, begidx, endidx):
        """
         auto complete of file name.
        """    
        return self.complete_filenames(text, line, begidx, endidx)

    mv_parser = argparse.ArgumentParser(description = 'Move File.')
    mv_parser.add_argument('src_path', type = str, help = 'Source File Path.')
    mv_parser.add_argument('dest_path', type = str, help = 'Destination File Path.')

    @with_argparser(mv_parser)
    def do_mv(self, args):
        """
        Rename a file or Move a file from source path to the destination
            Usage : mv <src_path> <dest_path>
        """
        try:           
            cephfs.rename(to_bytes(args.src_path), to_bytes(args.dest_path))
        except :
            traceback.print_exc(file = sys.stdout)
   
    def complete_cd(self, text, line, begidx, endidx):
        """ 
        auto complete of file name.
        """    
        return self.complete_filenames(text, line, begidx, endidx)

    cd_parser = argparse.ArgumentParser(description = 'Create Directory.')
    cd_parser.add_argument('dir_name', type = str, help = 'Name of the directory.', nargs = '*', default = [''])

    @with_argparser(cd_parser)
    def do_cd(self, args):
        """ 
        Open a specific directory.
            Usage : cd <dir_name>
        """
        try:            
            if args.dir_name[0] == '' :
                cephfs.chdir(b'/')
            if args.dir_name[0] == '..':
                dir_name = cephfs.getcwd().decode('utf-8').rsplit('/', 1)[0]
                if dir_name != '':
                    cephfs.chdir(to_bytes(dir_name))
                else :
                    cephfs.chdir(b'/')
            else :
                cephfs.chdir(to_bytes(args.dir_name[0]))
            self.working_dir = cephfs.getcwd().decode('utf-8')
            self.set_prompt()
        except :
            traceback.print_exc(file = sys.stdout)
   
    def do_cwd(self, arglist):
        """
        Get current working directory.
           Usage : cwd
        """
        print(cephfs.getcwd())

    def complete_chmod(self, text, line, begidx, endidx):
        """
        auto complete of file name.
        """    
        return self.complete_filenames(text, line, begidx, endidx)

    chmod_parser = argparse.ArgumentParser(description = 'Create Directory.')
    chmod_parser.add_argument('file_name', type = str, help = 'Name of the file')
    chmod_parser.add_argument('mode', type = int, help = 'Mode')

    @with_argparser(chmod_parser)
    def do_chmod(self, args):
        """
        Change permission of a file
        """
        try:           
            cephfs.chmod(args.file_name, args.mode)
        except :
             traceback.print_exc(file = sys.stdout)
  
    def complete_cat(self, text, line, begidx, endidx):
        """ 
        auto complete of file name.
        """    
        return self.complete_filenames(text, line, begidx, endidx)

    cat_parser = argparse.ArgumentParser(description = '')
    cat_parser.add_argument('file_names', help = 'Name of Files', nargs = '+')
            
    @with_argparser(cat_parser)
    def do_cat(self, args):
        """
        Print contents of a file
            Usage cat <file_name>
        """
        try:
            for file_name in args.file_names :
                print(file_name)
                copy_to_local(file_name, '-')
        except :
            traceback.print_exc(file = sys.stdout)
   
    umask_parser = argparse.ArgumentParser(description = '')
    umask_parser.add_argument('mode', help = 'Mode', action  = 'store', nargs = '*', default = [''])

    @with_argparser(umask_parser)
    def do_umask(self, args):
        try:
            if args.mode[0] == '' :
                print(self.umask.zfill(4)) 
            else :         
                mode = int(args.mode[0], 8)
                self.umask = str(oct(cephfs.umask(mode))[2:])
        except :
            traceback.print_exc(file = sys.stdout)

    def complete_write(self, text, line, begidx, endidx):
        """ 
        auto complete of file name.
        """    
        return self.complete_filenames(text, line, begidx, endidx)

    write_parser = argparse.ArgumentParser(description = '')
    write_parser.add_argument('file_name', type = str, help = 'Name of File')

    @with_argparser(write_parser)
    def do_write(self, args):
        """ 
        Write data into a file.
            Usage : write <file_name>
        """
        try:
            copy_from_local('-', args.file_name)
        except :
            traceback.print_exc(file = sys.stdout)

    def complete_lcd(self, text, line, begidx, endidx):
        """ 
        auto complete of file name.
        """    
        index_dict = {1: self.path_complete}
        return self.index_based_complete(text, line, begidx, endidx, index_dict)

    lcd_parser = argparse.ArgumentParser(description = '')
    lcd_parser.add_argument('path', type = str, help = 'Path')

    @with_argparser(lcd_parser)
    def do_lcd(self, args):
        """
        Moves into the given local directory
        """
        try :
            path = os.path.expanduser(args.path)
            if os.path.isdir(path):
                os.chdir(path)
            # print(get_all_possible_paths(args.path))
        except :
            traceback.print_exc(file = sys.stdout)

    def complete_lls(self, text, line, begidx, endidx):
        """ 
        auto complete of file name.
        """    
        index_dict = {1: self.path_complete}
        return self.index_based_complete(text, line, begidx, endidx, index_dict)

    lls_parser = argparse.ArgumentParser(description = 'List files in local system.')
    lls_parser.add_argument('paths', help = 'Paths', nargs = '*', default = [''])

    @with_argparser(lls_parser)
    def do_lls(self, args):
        """
        Lists all files and folders in the current local directory
        """
        try:
            if len(args.paths) == 1 and args.paths[0] == '':
                args.paths.pop(0)
                args.paths.append(os.getcwd())
            for path in args.paths :
                print(path)
                if not path.startswith(os.getcwd()) and not path.startswith('/'):
                    path = os.getcwd() + '/'+ path
                items = os.listdir(path)
                print_list(items)    
        except :
            traceback.print_exc(file = sys.stdout)
       
    def do_lpwd(self, arglist):
        """
        Prints the absolute path of the current local directory
        """
        print(os.getcwd())

    def do_df(self, arglist):
        """

        """
        print('{:10s}\t{:5s}\t{:15s}{:10s}{}'.format("1K-blocks", "Used", "Available", "Use%", "Stored on"))
        for i in list_items(cephfs.getcwd())[2:]:
            statfs = cephfs.statfs(i.d_name)
            stat = cephfs.stat(i.d_name)
            block_size = statfs['f_blocks']*statfs['f_bsize'] // 1024
            available = block_size - stat.st_size
            use = 0
            if block_size > 0 :
                use = (stat.st_size*100 // block_size)
            print('{:10d}\t{:5d}\t{:10d}\t{:5s} {}'.format(statfs['f_fsid'], stat.st_size, available, str(int(use)) + '%', i.d_name.decode('utf-8')))


    locate_parser = argparse.ArgumentParser(description = 'Find file within file system')
    locate_parser.add_argument('name', help = 'name', type = str)
    locate_parser.add_argument('-c', '--count', action = 'store_true', help = 'Count list of items located.')
    locate_parser.add_argument('-i', '--ignorecase', action = 'store_true', help = 'Ignore case')

    @with_argparser(locate_parser)
    def do_locate(self, args):
        """
        Find a file within the File System
        """
        if args.name.count('*') == 1 :
            if args.name[0] == '*':
                args.name += '/'
            elif args.name[-1] == '*':
                args.name = '/'+ args.name
        args.name = args.name.replace('*', '')
        if args.ignorecase :
            locations = [i for i in sorted(set(dirwalk(cephfs.getcwd().decode('utf-8')))) if args.name.lower() in i.lower()]
        else :
            locations = [i for i in sorted(set(dirwalk(cephfs.getcwd().decode('utf-8')))) if args.name in i]
        if args.count :
            print(len(locations))
        else:
            print('\n'.join(locations))

    def complete_du(self, text, line, begidx, endidx):
        """ 
        auto complete of file name.
        """    
        return self.complete_filenames(text, line, begidx, endidx)

    du_parser = argparse.ArgumentParser(description = 'Disk Usage of a Directory')
    du_parser.add_argument('dirs', type = str, help = 'Name of the directory.', nargs = '*', default = [''])

    @with_argparser(du_parser)
    def do_du(self, args):
        if args.dirs[0] == '':
            args.dirs[0] = cephfs.getcwd().decode('utf-8')
        for dir_ in args.dirs :
            for i in reversed(sorted(set(dirwalk(dir_)))):
                try :
                    print('{:10s} {}'.format(humansize(int(cephfs.getxattr(to_bytes(i), 'ceph.dir.rbytes').decode('utf-8'))), '.' + i))
                except :
                    continue
      
    def do_help(self, line):
        """
        Get details about a command.
            Usage : help <cmd> - for a specific command
                    help all - for all the commands
        """
        try:
            if line == 'all':
                for k in dir(self):
                    if k.startswith('do_'):
                        print('-'*80)
                        super().do_help(k[3:])
                return
            parser = self.create_argparser(line)
            if parser:
                parser.print_help()
            else:
                super().do_help(line)
        except :
            traceback.print_exc(file = sys.stdout)
 
if __name__ == '__main__':
    setup_cephfs()
    c = CephfsShell()
    c.cmdloop()

    