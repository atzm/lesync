# llesync
llesync is a simple program to copy/synchronize files and directory trees
without copying buffers to userspace using `sendfile(2)`.

# llehash
llehash is a simple program to digest files using the Linux Kernel Crypto API.
The digest is done without copying buffers to userspace too, using `pipe(2)`
and `splice(2)`.
