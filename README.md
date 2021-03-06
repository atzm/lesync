# llesync
llesync is a simple program to copy/synchronize files and directory trees
without copying buffers to userspace using `sendfile(2)`.

Here is a simple benchmark of llesync vs. rsync vs. cp:
```
$ uname -srvmpio
Linux 5.4.92-gentoo #4 SMP Wed Feb 3 15:40:26 JST 2021 x86_64 Intel(R) Core(TM) i9-9900 CPU @ 3.10GHz GenuineIntel GNU/Linux

$ ls -l data1.dat data2.dat data3.dat
-rw-r--r-- 1 user users 1555821443 Aug 20  2018 data1.dat
-rw-r--r-- 1 user users 1979275517 Aug 20  2018 data2.dat
-rw-r--r-- 1 user users 2486493060 Aug 20  2018 data3.dat

$ rm dst/*
$ sudo bash -c 'echo 1 > /proc/sys/vm/drop_caches'
$ time llesync -S data1.dat data2.dat data3.dat dst/.

real    0m4.023s
user    0m0.040s
sys     0m3.030s

$ rm dst/*
$ sudo bash -c 'echo 1 > /proc/sys/vm/drop_caches'
$ time rsync -a data1.dat data2.dat data3.dat dst/.

real    0m12.249s
user    0m13.692s
sys     0m4.070s

$ rm dst/*
$ sudo bash -c 'echo 1 > /proc/sys/vm/drop_caches'
$ time cp -a data1.dat data2.dat data3.dat dst/.

real    0m2.385s
user    0m0.011s
sys     0m2.340s
```

Note: of course llesync and rsync skips same files but cp does not.

# llehash
llehash is a simple program to digest files using the Linux Kernel Crypto API.
The digest is done without copying buffers to userspace too, using `pipe(2)`
and `splice(2)`.

Here is a simple benchmark of kernel sha256-avx2 vs. userspace sha256sum:
```
$ uname -srvmpio
Linux 5.4.92-gentoo #4 SMP Wed Feb 3 15:40:26 JST 2021 x86_64 Intel(R) Core(TM) i9-9900 CPU @ 3.10GHz GenuineIntel GNU/Linux

$ ls -l data1.dat data2.dat data3.dat
-rw-r--r-- 1 user users 1555821443 Aug 20  2018 data1.dat
-rw-r--r-- 1 user users 1979275517 Aug 20  2018 data2.dat
-rw-r--r-- 1 user users 2486493060 Aug 20  2018 data3.dat

$ sudo bash -c 'echo 1 > /proc/sys/vm/drop_caches'
$ time llehash -a sha256_avx2 data1.dat data2.dat data3.dat
8618d438c2102421173bf5b85628d2d17263ea8184bacbd0f2a229c3e6e1743e  data1.dat
260947eb8c5234356f1f0a6d57072da47d840df3a6a94b451f89ea26dd984e82  data2.dat
b33c84b9638beb91a5436fe3e6e04c0688af5e1120fee1330dd51b42ba1c79b3  data3.dat

real    0m4.985s
user    0m0.234s
sys     0m11.758s

$ sudo bash -c 'echo 1 > /proc/sys/vm/drop_caches'
$ time bash -c 'sha256sum data1.dat & sha256sum data2.dat & sha256sum data3.dat & wait'
8618d438c2102421173bf5b85628d2d17263ea8184bacbd0f2a229c3e6e1743e  data1.dat
260947eb8c5234356f1f0a6d57072da47d840df3a6a94b451f89ea26dd984e82  data2.dat
b33c84b9638beb91a5436fe3e6e04c0688af5e1120fee1330dd51b42ba1c79b3  data3.dat

real    0m6.916s
user    0m16.006s
sys     0m0.809s
```
