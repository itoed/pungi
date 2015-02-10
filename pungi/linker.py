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


import errno
import os
import shutil

import kobo.log
from kobo.shortcuts import relative_path
from kobo.threads import WorkerThread, ThreadPool

from pypungi.util import makedirs


class LinkerPool(ThreadPool):
    def __init__(self, link_type="hardlink-or-copy", logger=None):
        ThreadPool.__init__(self, logger)
        self.link_type = link_type
        self.linker = Linker()


class LinkerThread(WorkerThread):
    def process(self, item, num):
        src, dst = item

        if (num % 100 == 0) or (num == self.pool.queue_total):
            self.pool.log_debug("Linked %s out of %s packages" % (num, self.pool.queue_total))

        self.pool.linker.link(src, dst, link_type=self.pool.link_type)


class Linker(kobo.log.LoggingBase):
    def __init__(self, ignore_existing=False, always_copy=None, test=False, logger=None):
        kobo.log.LoggingBase.__init__(self, logger=logger)
        self.ignore_existing = ignore_existing
        self.always_copy = always_copy or []
        self.test = test
        self._precache = {}
        self._inode_map = {}

    def _is_same_type(self, path1, path2):
        if not os.path.islink(path1) == os.path.islink(path2):
            return False
        if not os.path.isdir(path1) == os.path.isdir(path2):
            return False
        if not os.path.isfile(path1) == os.path.isfile(path2):
            return False
        return True

    def _is_same(self, path1, path2):
        if self.ignore_existing:
            return True
        if path1 == path2:
            return True
        if os.path.islink(path2) and not os.path.exists(path2):
            return True
        if os.path.getsize(path1) != os.path.getsize(path2):
            return False
        if int(os.path.getmtime(path1)) != int(os.path.getmtime(path2)):
            return False
        return True

    def symlink(self, src, dst, relative=True):
        if src == dst:
            return

        old_src = src
        if relative:
            src = relative_path(src, dst)

        msg = "Symlinking %s -> %s" % (dst, src)
        if self.test:
            self.log_info("TEST: %s" % msg)
            return
        self.log_info(msg)

        try:
            os.symlink(src, dst)
        except OSError as ex:
            if ex.errno != errno.EEXIST:
                raise
            if os.path.islink(dst) and self._is_same(old_src, dst):
                if os.readlink(dst) != src:
                    raise
                self.log_debug("The same file already exists, skipping symlink %s -> %s" % (dst, src))
            else:
                raise

    def hardlink_on_dest(self, src, dst):
        if src == dst:
            return

        if os.path.exists(src):
            st = os.stat(src)
            file_name = os.path.basename(src)
            precache_key = (file_name, int(st.st_mtime), st.st_size)
            if precache_key in self._precache:
                self.log_warning("HIT %s" % str(precache_key))
                cached_path = self._precache[precache_key]["path"]
                self.hardlink(cached_path, dst)
                return True
        return False

    def hardlink(self, src, dst):
        if src == dst:
            return

        msg = "Hardlinking %s to %s" % (src, dst)
        if self.test:
            self.log_info("TEST: %s" % msg)
            return
        self.log_info(msg)

        try:
            os.link(src, dst)
        except OSError as ex:
            if ex.errno != errno.EEXIST:
                raise
            if self._is_same(src, dst):
                if not self._is_same_type(src, dst):
                    self.log_error("File %s already exists but has different type than %s" % (dst, src))
                    raise
                self.log_debug("The same file already exists, skipping hardlink %s to %s" % (src, dst))
            else:
                raise

    def copy(self, src, dst):
        if src == dst:
            return True

        if os.path.islink(src):
            msg = "Copying symlink %s to %s" % (src, dst)
        else:
            msg = "Copying file %s to %s" % (src, dst)

        if self.test:
            self.log_info("TEST: %s" % msg)
            return
        self.log_info(msg)

        if os.path.exists(dst):
            if self._is_same(src, dst):
                if not self._is_same_type(src, dst):
                    self.log_error("File %s already exists but has different type than %s" % (dst, src))
                    raise OSError(errno.EEXIST, "File exists")
                self.log_debug("The same file already exists, skipping copy %s to %s" % (src, dst))
                return
            else:
                raise OSError(errno.EEXIST, "File exists")

        if os.path.islink(src):
            if not os.path.islink(dst):
                os.symlink(os.readlink(src), dst)
                return
            return

        src_stat = os.stat(src)
        src_key = (src_stat.st_dev, src_stat.st_ino)
        if src_key in self._inode_map:
            # (st_dev, st_ino) found in the mapping
            self.log_debug("Harlink detected, hardlinking in destination %s to %s" % (self._inode_map[src_key], dst))
            os.link(self._inode_map[src_key], dst)
            return

        # BEWARE: shutil.copy2 automatically *rewrites* existing files
        shutil.copy2(src, dst)
        self._inode_map[src_key] = dst

        if not self._is_same(src, dst):
            self.log_error("File %s doesn't match the copied file %s" % (src, dst))
            # XXX:
            raise OSError(errno.EEXIST, "File exists")

    def _put_into_cache(self, path):
        def get_stats(item):
            return [item[i] for i in ("st_dev", "st_ino", "st_mtime", "st_size")]

        filename = os.path.basename(path)
        st = os.stat(path)
        item = {
            "st_dev": st.st_dev,
            "st_ino": st.st_ino,
            "st_mtime": int(st.st_mtime),
            "st_size": st.st_size,
            "path": path,
        }
        precache_key = (filename, int(st.st_mtime), st.st_size)
        if precache_key in self._precache:
            if get_stats(self._precache[precache_key]) != get_stats(item):
                # Files have same mtime and size but device
                # or/and inode is/are different.
                self.log_debug("Caching failed, files are different: %s, %s"
                               % (path, self._precache[precache_key]["path"]))
            return False
        self._precache[precache_key] = item
        return True

    def scan(self, path):
        """Recursively scan a directory and populate the cache."""
        msg = "Scanning directory: %s" % path
        self.log_debug("[BEGIN] %s" % msg)
        for dirpath, _, filenames in os.walk(path):
            for filename in filenames:
                path = os.path.join(dirpath, filename)
                self._put_into_cache(path)
        self.log_debug("[DONE ] %s" % msg)

    def _link_file(self, src, dst, link_type):
        if link_type == "hardlink":
            if not self.hardlink_on_dest(src, dst):
                self.hardlink(src, dst)
        elif link_type == "copy":
            self.copy(src, dst)
        elif link_type in ("symlink", "abspath-symlink"):
            if os.path.islink(src):
                self.copy(src, dst)
            else:
                relative = link_type != "abspath-symlink"
                self.symlink(src, dst, relative)
        elif link_type == "hardlink-or-copy":
            if not self.hardlink_on_dest(src, dst):
                src_stat = os.stat(src)
                dst_stat = os.stat(os.path.dirname(dst))
                if src_stat.st_dev == dst_stat.st_dev:
                    self.hardlink(src, dst)
                else:
                    self.copy(src, dst)
        else:
            raise ValueError("Unknown link_type: %s" % link_type)

    def link(self, src, dst, link_type="hardlink-or-copy", scan=True):
        """Link directories recursively."""
        if os.path.isfile(src) or os.path.islink(src):
            self._link_file(src, dst, link_type)
            return

        if os.path.isfile(dst):
            raise OSError(errno.EEXIST, "File exists")

        if not self.test:
            if not os.path.exists(dst):
                makedirs(dst)
            shutil.copystat(src, dst)

        for i in os.listdir(src):
            src_path = os.path.join(src, i)
            dst_path = os.path.join(dst, i)
            self.link(src_path, dst_path, link_type)

        return

        if scan:
            self.scan(dst)

        self.log_debug("Start linking")

        src = os.path.abspath(src)
        for dirpath, dirnames, filenames in os.walk(src):
            rel_path = dirpath[len(src):].lstrip("/")
            dst_path = os.path.join(dst, rel_path)

            # Dir check and creation
            if not os.path.isdir(dst_path):
                if os.path.exists(dst_path):
                    # At destination there is a file with same name but
                    # it is not a directory.
                    self.log_error("Cannot create directory %s" % dst_path)
                    dirnames = []  # noqa
                    continue
                os.mkdir(dst_path)

            # Process all files in directory
            for filename in filenames:
                path = os.path.join(dirpath, filename)
                st = os.stat(path)
                # Check cache
                # Same file already exists at a destination dir =>
                # Create the new file by hardlink to the cached one.
                precache_key = (filename, int(st.st_mtime), st.st_size)
                full_dst_path = os.path.join(dst_path, filename)
                if precache_key in self._precache:
                    # Cache hit
                    cached_path = self._precache[precache_key]["path"]
                    self.log_debug("Cache HIT for %s [%s]" % (path, cached_path))
                    if cached_path != full_dst_path:
                        self.hardlink(cached_path, full_dst_path)
                    else:
                        self.log_debug("Files are same, skip hardlinking")
                    continue
                # Cache miss
                # Copy the new file and put it to the cache.
                try:
                    self.copy(path, full_dst_path)
                except Exception as ex:
                    print(ex)
                    print(path, open(path, "r").read())
                    print(full_dst_path, open(full_dst_path, "r").read())
                    print(os.stat(path))
                    print(os.stat(full_dst_path))
                    os.utime(full_dst_path, (st.st_atime, int(st.st_mtime)))
                    self._put_into_cache(full_dst_path)
