#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# lesync -- a simple program to copy files and directory trees with converting
#           filename encoding like 'rsync --iconv' but its logic is simplified
#           for some filesystems, e.g. exFAT on fuse.
#

import os
import sys
import abc
import errno
import fcntl
import fnmatch
import logging
import argparse
import contextlib
from concurrent import futures

import lehash


class File(metaclass=abc.ABCMeta):
    @property
    @abc.abstractmethod
    def openflag(self):
        pass

    @property
    @abc.abstractmethod
    def lockmode(self):
        pass

    def __init__(self, path, encoding, hasher):
        self.path = os.path.realpath(path)
        self.encoding = encoding
        self.hasher = hasher
        self.fileno = -1
        self.statc = self.stat0

    def __eq__(self, other):
        if self.stat.st_size == other.stat.st_size:
            if self.stat.st_mtime == other.stat.st_mtime:
                if self.basename == other.basename:
                    return self.digest == other.digest
        return False

    def __ne__(self, other):
        return not self.__eq__(other)

    def __str__(self):
        return self.path

    @property
    def encoded(self):
        return str(self).encode(self.encoding, 'surrogateescape')

    @property
    def basename(self):
        return os.path.basename(str(self))

    @property
    def digest(self):
        if self.opened:
            with self.hasher.open() as desc:
                return desc.digest(self.fileno, self.stat.st_size)

    @property
    def opened(self):
        return self.fileno >= 0

    @property
    def stat(self):
        if self.opened and self.statc == self.stat0:
            self.statc = os.stat_result(int(s) for s in os.fstat(self.fileno))
        return self.statc

    @property
    def stat0(self):
        return os.stat_result((-1,) * 10)

    @property
    def errnoignore(self):
        return []

    @property
    def isdir(self):
        return os.path.isdir(self.encoded)

    def iterdir(self):
        for f in os.listdir(self.encoded):
            yield self.join(f.decode(self.encoding, 'surrogateescape'))

    def join(self, f):
        path = os.path.join(str(self), f)
        return type(self)(path, self.encoding, self.hasher)

    @contextlib.contextmanager
    def open(self, mode=0o0644):
        try:
            try:
                self.fileno = os.open(self.encoded, self.openflag, mode)
                fcntl.flock(self.fileno, self.lockmode | fcntl.LOCK_NB)

            except OSError as e:
                if e.errno not in self.errnoignore:
                    raise

            yield self

        finally:
            if self.opened:
                os.close(self.fileno)
                self.fileno = -1

    @contextlib.contextmanager
    def mkdir(self, src):
        yield

    def seek(self, *args, **kwargs):
        if self.opened:
            os.lseek(self.fileno, *args, **kwargs)

    def truncate(self, *args, **kwargs):
        pass

    def copy(self, src):
        pass


class FileRD(File):
    @property
    def openflag(self):
        return os.O_LARGEFILE | os.O_RDONLY

    @property
    def lockmode(self):
        return fcntl.LOCK_SH


class FileRDWR(File):
    @property
    def openflag(self):
        return os.O_LARGEFILE | os.O_RDWR | os.O_CREAT

    @property
    def lockmode(self):
        return fcntl.LOCK_EX

    @contextlib.contextmanager
    def mkdir(self, src):
        try:
            os.mkdir(self.encoded, src.stat.st_mode & 0o0777)
        except OSError as e:
            if e.errno != errno.EEXIST:
                raise
        yield
        os.utime(self.encoded, (src.stat.st_atime, src.stat.st_mtime))

    def truncate(self, *args, **kwargs):
        if self.opened:
            os.ftruncate(self.fileno, *args, **kwargs)

    def copy(self, src):
        if not (self.opened and src.opened):
            return

        size = src.stat.st_size
        while size > 0:
            size -= os.sendfile(self.fileno, src.fileno, None, size)

        os.utime(self.fileno, (src.stat.st_atime, src.stat.st_mtime))


class FileStat(FileRD):
    @property
    def errnoignore(self):
        return [errno.ENOENT]


@contextlib.contextmanager
def umask(mask):
    try:
        oldmask = -1
        oldmask = os.umask(mask)
        yield
    finally:
        if oldmask > 0:
            os.umask(oldmask)


def copy(args, src, dst):
    with src.open(), dst.open(src.stat.st_mode & 0o0777):
        if args.sync and src == dst:
            return logging.debug('skipped: %s', src)

        dst.seek(0, os.SEEK_SET)
        dst.truncate(0)
        dst.copy(src)

    logging.info('copied: %s', src)


def xfnmatch(path, patterns):
    return any(fnmatch.fnmatch(path, p) for p in patterns)


def walk(args, src, dst):
    match = str(src) + os.sep if src.isdir else str(src)

    if not xfnmatch(match, args.include) or xfnmatch(match, args.exclude):
        return logging.debug('skipped: %s', src)

    if dst.isdir:
        dst = dst.join(src.basename)

    if not src.isdir:
        return args.executor.submit(copy, args, src, dst)

    with src.open(), dst.mkdir(src):
        for s in src.iterdir():
            walk(args, s, dst)


def run(args):
    nfiles = len(args.files)

    if nfiles < 2:
        return logging.error('two files required at least')

    if nfiles > 2:
        dst = args.reader(args.files[-1], args.dst_enc, args.hasher)
        if not dst.isdir:
            return logging.error('last file must be a directory')

    dst = args.writer(args.files.pop(), args.dst_enc, args.hasher)

    while args.files:
        src = args.reader(args.files.pop(0), args.src_enc, args.hasher)
        walk(args, src, dst)


def prepare(args):
    args.reader = FileRD
    args.writer = FileStat if args.dry_run else FileRDWR
    args.hasher = lehash.Hash.instance(args.digest)
    args.executor = futures.ThreadPoolExecutor(max_workers=args.threads)

    if args.verbose > 1:
        loglevel = logging.DEBUG
    elif args.verbose > 0 or args.dry_run:
        loglevel = logging.INFO
    else:
        loglevel = logging.WARN

    logging.basicConfig(level=loglevel, format='[%(levelname)s] %(message)s')


def main():
    digs = sorted(lehash.Hash.algorithm().keys())
    argp = argparse.ArgumentParser()
    argp.add_argument('-v', '--verbose', action='count', default=0)
    argp.add_argument('-n', '--dry-run', action='store_true', default=False)
    argp.add_argument('-t', '--threads', type=int, default=1)
    argp.add_argument('-S', '--sync', action='store_true', default=False)
    argp.add_argument('-D', '--digest', choices=digs, default='dummy')
    argp.add_argument('-I', '--include', nargs='+', default=['*/', '*'])
    argp.add_argument('-X', '--exclude', nargs='+', default=[])
    argp.add_argument('-s', '--src-enc', default=sys.getfilesystemencoding())
    argp.add_argument('-d', '--dst-enc', default='utf-8')
    argp.add_argument('files', nargs=argparse.REMAINDER)

    args = argp.parse_args()
    prepare(args)

    with umask(0), args.executor:
        run(args)


if __name__ == '__main__':
    main()
