#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from setuptools import setup

setup(
    name='lesync',
    version='0.1',
    description='simple programs to copy or digest files '
                'without copying buffers to userspace',
    author='Atzm WATANABE',
    author_email='atzm@atzm.org',
    license='BSD-2',
    entry_points={'console_scripts': [
        'lesync = lesync:main',
        'lehash = lehash:main',
    ]},
    py_modules=['lesync', 'lehash'],
    install_requires=[],
    classifiers=[
        'Development Status :: 3 - Alpha',
        'License :: OSI Approved :: BSD License',
    ],
)
