Ceph FS Shell
=============

The File System (FS) shell includes various shell-like commands that directly interact with the Ceph File System.

Commands
========

mkdir
-----

Create the directory(ies), if they do not already exist.

Usage: mkdir [-option]...<path_uri>...

Takes path uri's as argument and creates directories.

Options :

 -m mode   Sets the access mode for the new directory.
 -p        Creates parent directories if doesn't exist.

 
copyFromLocal
-------------

 Copy a file to Ceph File System from Local Directory.

 Usage : copyFromLocal [-option] <path_uri>

 Options:

 -f        Overwrites the destination if it already exists.

 ls
 --

 List all the files and directories in the current working directory.

 Usage : ls [-option]

 Options:

 -s 	   List file size
 -S 	   Sort by file size


opendir
-------

Open a specific named directory.

Usage : opendir <directory_name>


closedir
--------

Close the current working directory.

Usage : closedir 

cwd
---

Get current working directory.

Usage : cwd


EOF/ Ctrl + D
-------------

Close the shell.




