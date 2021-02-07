#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# for python 3.5 or earlier

import os
import fcntl
import string
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

    # max page size is 16 in the kernel (<4.11)
    SPLICE_S_MAX = os.sysconf(os.sysconf_names['SC_PAGESIZE']) * 16

    def __init__(self, fileno, digestsize):
        self.fileno = fileno
        self.digestsize = digestsize

    def splice(self, fileno, size):
        @contextlib.contextmanager
        def _pipe():
            try:
                rfd, wfd = -1, -1
                rfd, wfd = os.pipe()
                yield rfd, wfd
            finally:
                if rfd >= 0:
                    os.close(rfd)
                if wfd >= 0:
                    os.close(wfd)

        def _splice(fd_in, off_in, fd_out, off_out, len_, flags):
            size = _libc.splice(fd_in, off_in, fd_out, off_out, len_, flags)
            if size < 0:
                n = ctypes.get_errno()
                raise OSError(n, os.strerror(n))
            return size

        with _pipe() as (rfd, wfd):
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
        def _read(fileno, size):
            while size > 0:
                byte = os.read(fileno, size)
                size -= len(byte)
                yield byte

        if size:
            self.splice(fileno, size)
        else:
            os.write(self.fileno, b'')

        return b''.join(_read(self.fileno, self.digestsize))


class Hash:
    AF_ALG = 38
    SOL_ALG = 279

    ALG_SET_KEY = 1
    ALG_SET_IV = 2
    ALG_SET_OP = 3
    ALG_SET_AEAD_ASSOCLEN = 4
    ALG_SET_AEAD_AUTHSIZE = 5

    ALG_OP_DECRYPT = 0
    ALG_OP_ENCRYPT = 1

    ALG_TYPE = b'hash'
    ALG_NAME = None
    ALG_BYTE = None

    def __init__(self, key):
        sock = socket.socket(self.AF_ALG, socket.SOCK_SEQPACKET, 0)
        algo = _sockaddr_alg(self.AF_ALG, self.ALG_TYPE, 0, 0, self.ALG_NAME)

        r = _libc.bind(sock.fileno(), ctypes.byref(algo), ctypes.sizeof(algo))
        if r < 0:
            n = ctypes.get_errno()
            sock.close()
            raise OSError(n, os.strerror(n))

        self.key = key
        self.sock = self.prepare(sock)
        self.algo = algo

    def __del__(self):
        if getattr(self, 'sock', None):
            self.sock.close()

    def prepare(self, sock):
        if self.key is not None:
            r = _libc.setsockopt(sock.fileno(), self.SOL_ALG, self.ALG_SET_KEY,
                                 self.key, self.ALG_BYTE)
            if r < 0:
                n = ctypes.get_errno()
                sock.close()
                raise OSError(n, os.strerror(n))

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
    def instance(cls, name, key=None):
        return cls.algorithm()[name](key)

    @classmethod
    def algorithm(cls):
        d = {}
        for c in cls.__subclasses__():
            d.update(c.algorithm())
            d[c.__name__] = c
        return d


class dummy(Hash):
    ALG_NAME = b'dummy'
    ALG_BYTE = 0

    class descriptor(HashDescriptor):
        def splice(self, fileno, size):
            pass

        def digest(self, fileno, size):
            return b''

    def __init__(self, key):
        pass

    @contextlib.contextmanager
    def open(self):
        yield self.descriptor(0, 0)


def iteralgo(filter_=lambda x: True):
    with open('/proc/crypto') as fp:
        algo = {}

        for line in fp:
            line = line.strip()

            if not line:
                if filter_(algo):
                    yield algo

                algo = {}
                continue

            key, val = line.split(':', 1)
            algo[key.strip()] = val.strip()


def defalgo():
    table = str.maketrans(string.punctuation, '_' * len(string.punctuation))

    for algo in iteralgo(lambda x: x.get('type') == 'shash'):
        name = algo['driver'].translate(table).strip('_')

        if name.endswith('_generic'):
            name = name[:-8]

        globals()[name] = type(name, (Hash,), {
            'ALG_NAME': algo['driver'].encode(),
            'ALG_BYTE': int(algo['digestsize']),
        })


def main():
    digs = sorted(Hash.algorithm().keys())
    argp = argparse.ArgumentParser()
    argp.add_argument('-a', '--digest-algo', choices=digs, default='dummy')
    argp.add_argument('-k', '--digest-key', type=os.fsencode)
    argp.add_argument('-t', '--threads', type=int, default=os.cpu_count())
    argp.add_argument('files', nargs=argparse.REMAINDER)

    args = argp.parse_args()
    hasher = Hash.instance(args.digest_algo, args.digest_key)

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


defalgo()

if __name__ == '__main__':
    main()
