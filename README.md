# lesync
lesync is a simple program to copy/synchronize files and directory trees
without copying buffers to userspace using `sendfile(2)`.

# lehash
lehash is a simple program to digest files using the Linux Kernel Crypto API.
The digest is done without copying buffers to userspace using `pipe(2)` and
`splice(2)` too.
