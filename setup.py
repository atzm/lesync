#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from setuptools import setup

setup(
    name='llesync',
    version='0.1',
    description='simple programs to copy or digest files '
                'without copying buffers to userspace',
    author='Atzm WATANABE',
    author_email='atzm@atzm.org',
    license='BSD-2',
    entry_points={'console_scripts': [
        'llesync = llesync:main',
        'llehash = llehash:main',
    ]},
    py_modules=['llesync', 'llehash'],
    install_requires=[],
    classifiers=[
        'Development Status :: 3 - Alpha',
        'License :: OSI Approved :: BSD License',
    ],
)
