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


class File(metaclass=abc.ABCMeta):
    @property
    @abc.abstractmethod
    def openflag(self):
        pass

    @property
    @abc.abstractmethod
    def lockmode(self):
        pass

    def __init__(self, path, encoding):
        self.path = os.path.realpath(path)
        self.encoding = encoding
        self.fileno = -1
        self.statcache = self.stat0

    def __eq__(self, other):
        if self.stat.st_size == other.stat.st_size:
            return self.basename == other.basename
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
    def opened(self):
        return self.fileno >= 0

    @property
    def stat(self):
        if self.opened and self.statcache == self.stat0:
            self.statcache = os.fstat(self.fileno)
        return self.statcache

    @property
    def stat0(self):
        return os.stat_result((0,) * 10)

    @property
    def isdir(self):
        return os.path.isdir(self.encoded)

    def iterdir(self, include=['*/', '*'], exclude=[]):
        def xfnmatch(filename, patterns):
            return any(fnmatch.fnmatch(filename, p) for p in patterns)

        for f in os.listdir(self.encoded):
            f = self.join(f.decode(self.encoding, 'surrogateescape'))
            m = str(f) + os.sep if f.isdir else str(f)

            if not xfnmatch(m, include):
                continue
            if xfnmatch(m, exclude):
                continue

            yield f

    def join(self, f):
        return type(self)(os.path.join(str(self), f), self.encoding)

    @contextlib.contextmanager
    def open(self, mode=0o0644):
        try:
            self.fileno = os.open(self.encoded, self.openflag, mode)
            yield self

        except OSError as e:
            if e.errno != errno.ENOENT:
                raise
            yield self

        finally:
            if self.opened:
                os.close(self.fileno)
                self.fileno = -1

    def lock(self):
        try:
            if self.opened:
                fcntl.flock(self.fileno, self.lockmode | fcntl.LOCK_NB)
            return True

        except OSError as e:
            if e.errno != errno.EAGAIN:
                raise

        return False

    def seek(self, *args, **kwargs):
        if self.opened:
            os.lseek(self.fileno, *args, **kwargs)

    def truncate(self, *args, **kwargs):
        pass

    def copy(self, dst):
        pass

    def mkdir(self, mode=0o0755):
        pass


class FileRD(File):
    @property
    def openflag(self):
        return os.O_LARGEFILE | os.O_RDONLY

    @property
    def lockmode(self):
        return fcntl.LOCK_SH

    def copy(self, dst):
        if not (self.opened and dst.opened):
            return
        if not isinstance(dst, FileRDWR):
            return
        os.sendfile(dst.fileno, self.fileno, None, self.stat.st_size)


class FileRDWR(File):
    @property
    def openflag(self):
        return os.O_LARGEFILE | os.O_RDWR | os.O_CREAT

    @property
    def lockmode(self):
        return fcntl.LOCK_EX

    def truncate(self, *args, **kwargs):
        if self.opened:
            os.ftruncate(self.fileno, *args, **kwargs)

    def mkdir(self, mode=0o0755):
        try:
            os.mkdir(self.encoded, mode)
        except OSError as e:
            if e.errno != errno.EEXIST:
                raise


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
    with src.open():
        if not src.lock():
            return logging.warning('could not be locked: %s', src)

        with dst.open(src.stat.st_mode & 0o0777):
            if not dst.lock():
                return logging.warning('could not be locked: %s', dst)

            if args.sync and src == dst:
                return logging.debug('skipped: %s', src)

            dst.seek(0, 0)
            dst.truncate(0)
            src.copy(dst)

            logging.info('copied: %s', src)


def walk(args, src, dst):
    if dst.isdir:
        dst = dst.join(src.basename)

    if not src.isdir:
        return copy(args, src, dst)

    with src.open():
        if not src.lock():  # XXX
            return logging.warning('could not be locked: %s', src)

        dst.mkdir(src.stat.st_mode & 0o0777)

        for s in src.iterdir(args.include, args.exclude):
            walk(args, s, dst)


def run(args):
    nfiles = len(args.files)

    if nfiles < 2:
        return logging.error('two files required at least')

    if nfiles > 2 and not args.reader(args.files[-1], args.dst_enc).isdir:
        return logging.error('last file must be a directory')

    dst = args.writer(args.files.pop(), args.dst_enc)

    while args.files:
        src = args.reader(args.files.pop(0), args.src_enc)
        walk(args, src, dst)


def prepare(args):
    args.reader = FileRD
    args.writer = FileRD if args.dry_run else FileRDWR

    if args.verbose > 1:
        loglevel = logging.DEBUG
    elif args.verbose > 0 or args.dry_run:
        loglevel = logging.INFO
    else:
        loglevel = logging.WARN

    logging.basicConfig(level=loglevel, format='[%(levelname)s] %(message)s')


def main():
    argp = argparse.ArgumentParser()
    argp.add_argument('-v', '--verbose', action='count', default=0)
    argp.add_argument('-n', '--dry-run', action='store_true', default=False)
    argp.add_argument('-S', '--sync', action='store_true', default=False)
    argp.add_argument('-I', '--include', nargs='+', default=['*/', '*'])
    argp.add_argument('-X', '--exclude', nargs='+', default=[])
    argp.add_argument('-s', '--src-enc', default=sys.getfilesystemencoding())
    argp.add_argument('-d', '--dst-enc', default='utf-8')
    argp.add_argument('files', nargs=argparse.REMAINDER)

    args = argp.parse_args()
    prepare(args)

    with umask(0):
        run(args)


if __name__ == '__main__':
    main()
