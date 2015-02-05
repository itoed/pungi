#!/usr/bin/python
# -*- coding: utf-8 -*-


import os
import glob

import distutils.command.sdist
from setuptools import setup


# override default tarball format with bzip2
distutils.command.sdist.sdist.default_format = {"posix": "bztar"}


# recursively scan for python modules to be included
package_root_dirs = ["pungi"]
packages = set()
for package_root_dir in package_root_dirs:
    for root, dirs, files in os.walk(package_root_dir):
        if "__init__.py" in files:
            packages.add(root.replace("/", "."))
packages = sorted(packages)


setup(
    name            = "pungi",
    version         = "4.0",  # make sure it matches with pungi.__version__
    description     = "Distribution compose tool",
    url             = "http://fedorahosted.org/pungi",
    author          = "Dennis Gilmore",
    author_email    = "dgilmore@fedoraproject.org",
    license         = "GPLv2",

    packages        = packages,
    scripts         = [
        'bin/pungi-gather',
    ],
    data_files      = [
        ('/usr/share/pungi', glob.glob('share/*.xsl')),
        ('/usr/share/pungi', glob.glob('share/*.ks')),
        ('/usr/share/pungi/multilib', glob.glob('share/multilib/*')),
    ]
)
