#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# for python 3.5 or earlier

import os
import fcntl
import codecs
import socket
import ctypes
import argparse
import contextlib
from concurrent import futures

_libc = ctypes.CDLL('libc.so.6', use_errno=True)


class _sockaddr_alg(ctypes.Structure):
    _fields_ = [
        ('salg_family', ctypes.c_uint16),
        ('salg_type',   ctypes.c_char * 14),
        ('salg_feat',   ctypes.c_uint32),
        ('salg_mask',   ctypes.c_uint32),
        ('salg_name',   ctypes.c_char * 64),
    ]


class HashDescriptor:
    SPLICE_F_MOVE = 1
    SPLICE_F_NONBLOCK = 2
    SPLICE_F_MORE = 4
    SPLICE_F_GIFT = 8
    SPLICE_S_MAX = 4096 * 16

    def __init__(self, fileno, digestsize):
        self.fileno = fileno
        self.digestsize = digestsize

    @staticmethod
    @contextlib.contextmanager
    def pipe():
        try:
            rfd, wfd = -1, -1
            rfd, wfd = os.pipe()
            yield rfd, wfd
        finally:
            if rfd >= 0:
                os.close(rfd)
            if wfd >= 0:
                os.close(wfd)

    def splice(self, fileno, size):
        def _splice(fd_in, off_in, fd_out, off_out, len_, flags):
            size = _libc.splice(fd_in, off_in, fd_out, off_out, len_, flags)
            if size < 0:
                n = ctypes.get_errno()
                raise OSError(n, os.strerror(n))
            return size

        with self.pipe() as (rfd, wfd):
            while size > 0:
                if size <= self.SPLICE_S_MAX:
                    mvlen = size
                    flags = self.SPLICE_F_MOVE
                else:
                    mvlen = self.SPLICE_S_MAX
                    flags = self.SPLICE_F_MOVE | self.SPLICE_F_MORE

                nr = _splice(fileno, None, wfd, None, mvlen, flags)
                nw = _splice(rfd, None, self.fileno, None, mvlen, flags)
                assert nr == nw

                size -= nr

        os.lseek(fileno, 0, os.SEEK_SET)

    def digest(self, fileno, size):
        if size:
            self.splice(fileno, size)
        else:
            os.write(self.fileno, b'')

        buff = b''
        size = 0
        while size < self.digestsize:
            b = os.read(self.fileno, self.digestsize - size)
            size += len(b)
            buff += b
        return buff


class HashDescriptorDummy(HashDescriptor):
    def __init__(self, fileno, digestsize):
        pass

    def digest(self, fileno, size):
        return b''


class Hash:
    AF_ALG = 38
    SOL_ALG = 279
    ALG_SET_KEY = 1

    ALG_TYPE = b'hash'
    ALG_NAME = None
    ALG_BYTE = None

    def __init__(self):
        sock = socket.socket(self.AF_ALG, socket.SOCK_SEQPACKET, 0)
        algo = _sockaddr_alg(self.AF_ALG, self.ALG_TYPE, 0, 0, self.ALG_NAME)

        r = _libc.bind(sock.fileno(), ctypes.byref(algo), ctypes.sizeof(algo))
        if r < 0:
            n = ctypes.get_errno()
            sock.close()
            raise OSError(n, os.strerror(n))

        self.sock = self.prepare(sock)
        self.algo = algo

    def __del__(self):
        if getattr(self, 'sock', None):
            self.sock.close()

    @classmethod
    def prepare(cls, sock):
        return sock

    @contextlib.contextmanager
    def open(self):
        try:
            fileno = _libc.accept(self.sock.fileno(), None, None)
            if fileno < 0:
                n = ctypes.get_errno()
                raise OSError(n, os.strerror(n))
            yield HashDescriptor(fileno, self.ALG_BYTE)
        finally:
            if fileno >= 0:
                os.close(fileno)

    @classmethod
    def instance(cls, name):
        return cls.algorithm()[name]()

    @classmethod
    def algorithm(cls):
        d = {}
        for c in cls.__subclasses__():
            d.update(c.algorithm())
            d[c.ALG_NAME.decode()] = c
        return d


class HashDummy(Hash):
    ALG_NAME = b'dummy'
    ALG_BYTE = 0

    def __init__(self):
        pass

    @contextlib.contextmanager
    def open(self):
        yield HashDescriptorDummy(0, 0)


class HashCRC32C(Hash):
    ALG_NAME = b'crc32c'
    ALG_BYTE = 4

    @classmethod
    def prepare(cls, sock):
        r = _libc.setsockopt(sock.fileno(), cls.SOL_ALG, cls.ALG_SET_KEY,
                             b'\xff' * cls.ALG_BYTE, cls.ALG_BYTE)
        if r < 0:
            n = ctypes.get_errno()
            sock.close()
            raise OSError(n, os.strerror(n))

        return sock


class HashMD5(Hash):
    ALG_NAME = b'md5'
    ALG_BYTE = 16


class HashSHA1(Hash):
    ALG_NAME = b'sha1'
    ALG_BYTE = 20


class HashSHA224(Hash):
    ALG_NAME = b'sha224'
    ALG_BYTE = 28


class HashSHA256(Hash):
    ALG_NAME = b'sha256'
    ALG_BYTE = 32


def main():
    digs = sorted(Hash.algorithm().keys())
    argp = argparse.ArgumentParser()
    argp.add_argument('-a', '--algorithm', choices=digs, default='dummy')
    argp.add_argument('-t', '--threads', type=int, default=os.cpu_count())
    argp.add_argument('files', nargs=argparse.REMAINDER)
    args = argp.parse_args()
    hasher = Hash.instance(args.algorithm)

    def run(path):
        with hasher.open() as desc, open(path) as fp:
            fileno = fp.fileno()
            fcntl.flock(fileno, fcntl.LOCK_SH)
            return desc.digest(fileno, os.fstat(fileno).st_size)

    with futures.ThreadPoolExecutor(max_workers=args.threads) as executor:
        futuredict = {executor.submit(run, path): path for path in args.files}

        for future in futures.as_completed(futuredict):
            path = futuredict[future]
            digest = future.result()
            print(codecs.encode(digest, 'hex').decode(), '', path)


if __name__ == '__main__':
    main()
