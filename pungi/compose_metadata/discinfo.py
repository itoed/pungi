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


"""
The .discinfo file contains metadata about media.
Following fields are part of the .discinfo file,
one record per line:
- timestamp
- release
- architecture
- disc number (optional)
"""


__all__ = (
    "read_discinfo",
    "write_discinfo",
    "write_media_repo",
)


import time


def write_discinfo(file_path, description, arch, disc_numbers=None, timestamp=None):
    """
    Write a .discinfo file:
    """
    disc_numbers = disc_numbers or ["ALL"]
    if not isinstance(disc_numbers, list):
        raise TypeError("Invalid type: disc_numbers type is %s; expected: <list>" % type(disc_numbers))
    if not timestamp:
        timestamp = "%f" % time.time()
    f = open(file_path, "w")
    f.write("%s\n" % timestamp)
    f.write("%s\n" % description)
    f.write("%s\n" % arch)
    if disc_numbers:
        f.write("%s\n" % ",".join([str(i) for i in disc_numbers]))
    f.close()
    return timestamp


def read_discinfo(file_path):
    result = {}
    f = open(file_path, "r")
    result["timestamp"] = f.readline().strip()
    result["description"] = f.readline().strip()
    result["arch"] = f.readline().strip()
    disc_numbers = f.readline().strip()
    if not disc_numbers:
        result["disc_numbers"] = None
    elif disc_numbers == "ALL":
        result["disc_numbers"] = ["ALL"]
    else:
        result["disc_numbers"] = [int(i) for i in disc_numbers.split(",")]
    return result


def write_media_repo(file_path, description, timestamp=None):
    """
    Write media.repo file for the disc to be used on installed system.
    PackageKit uses this.
    """

    if not timestamp:
        raise
        timestamp = "%f" % time.time()

    data = [
        "[InstallMedia]",
        "name=%s" % description,
        "mediaid=%s" % timestamp,
        "metadata_expire=-1",
        "gpgcheck=0",
        "cost=500",
        "",
    ]

    repo_file = open(file_path, "w")
    repo_file.write("\n".join(data))
    repo_file.close()
    return timestamp
