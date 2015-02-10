# -*- coding: utf-8 -*-


# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; version 2 of the License.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Library General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place - Suite 330, Boston, MA 02111-1307, USA.


import os


SIZE_UNITS = {
    "b": 1,
    "k": 1024,
    "M": 1024 ** 2,
    "G": 1024 ** 3,
}


def convert_media_size(size):
    if isinstance(size, str):
        if size[-1] in SIZE_UNITS:
            num = int(size[:-1])
            units = size[-1]
        else:
            num = int(size)
            units = "b"
        result = num * SIZE_UNITS[units]
    else:
        result = int(size)

    if result <= 0:
        raise ValueError("Media size must be a positive number: %s" % size)

    return result


def convert_file_size(size, block_size=2048):
    """round file size to block"""
    blocks = int(size / block_size)
    if size % block_size:
        blocks += 1
    return blocks * block_size


class MediaSplitter(object):
    def __init__(self, media_size):
        self.media_size = convert_media_size(media_size)
        self.files = []  # to preserve order
        self.file_sizes = {}
        self.sticky_files = set()

    def add_file(self, name, size, sticky=False):
        name = os.path.normpath(name)
        size = int(size)
        old_size = self.file_sizes.get(name, None)
        if old_size is None:
            self.files.append(name)
            self.file_sizes[name] = size
        elif old_size != size:
            raise ValueError("File size mismatch; file: %s; sizes: %s vs %s" % (name, old_size, size))
        elif size > self.media_size:
            raise ValueError("File is larger than media size: %s" % name)
        if sticky:
            self.sticky_files.add(name)

    '''
    def load(self, file_name):
        f = open(file_name, "r")
        for line in f:
            line = line.strip()
            if not line:
                continue
            name, size = line.split(" ")
            self.add_file(name, size)
        f.close()

    def scan(self, pattern):
        for i in glob.glob(pattern):
            self.add_file(i, os.path.getsize(i))

    def dump(self, file_name):
        f = open(file_name, "w")
        for name in self.files:
            f.write("%s %s\n" % (os.path.basename(name), self.file_sizes[name]))
        f.close()
    '''

    @property
    def total_size(self):
        return sum(self.file_sizes.values())

    @property
    def total_size_in_blocks(self):
        return sum([convert_file_size(i) for i in list(self.file_sizes.values())])

    def split(self, first_disk=0, all_disks=0):
        all_files = []
        sticky_files = []
        sticky_files_size = 0

        for name in self.files:
            if name in self.sticky_files:
                sticky_files.append(name)
                sticky_files_size += convert_file_size(self.file_sizes[name])
            else:
                all_files.append(name)

        disks = []
        disk = {}
        while all_files:
            name = all_files.pop(0)
            size = convert_file_size(self.file_sizes[name])

            if not disks or disk["size"] + size > self.media_size:
                disk = {"size": 0, "files": []}
                disks.append(disk)
                disk["files"].extend(sticky_files)
                disk["size"] += sticky_files_size

            disk["files"].append(name)
            disk["size"] += convert_file_size(self.file_sizes[name])

        return disks
