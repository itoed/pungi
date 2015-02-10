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
import sys
import pipes
from fnmatch import fnmatch

import kobo.log
from kobo.shortcuts import force_list, relative_path, run


# HACK: define cmp in python3
if sys.version_info[0] == 3:
    def cmp(a, b):
        return (a > b) - (a < b)


class IsoWrapper(kobo.log.LoggingBase):

    def get_boot_options(self, arch, createfrom, efi=True):
        """Checks to see what we need as the -b option for mkisofs"""

        if arch in ("aarch64", ):
            result = [
                '-eltorito-alt-boot',
                '-e', 'images/efiboot.img',
                '-no-emul-boot',
            ]
            return result

        if arch in ("i386", "i686", "x86_64"):
            result = [
                '-b', 'isolinux/isolinux.bin',
                '-c', 'isolinux/boot.cat',
                '-no-emul-boot',
                '-boot-load-size', '4',
                '-boot-info-table',
            ]

            # EFI args
            if arch == "x86_64":
                result.extend([
                    '-eltorito-alt-boot',
                    '-e', 'images/efiboot.img',
                    '-no-emul-boot',
                ])
            return result

        if arch == "ia64":
            result = [
                '-b', 'images/boot.img',
                '-no-emul-boot',
            ]
            return result

        if arch in ("ppc", "ppc64", "ppc64le"):
            result = [
                '-part',
                '-hfs',
                '-r',
                '-l',
                '-sysid', 'PPC',
                '-no-desktop',
                '-allow-multidot',
                '-chrp-boot',
                "-map", os.path.join(createfrom, 'mapping'),  # -map %s/ppc/mapping
                "-magic", os.path.join(createfrom, 'magic'),  # -magic %s/ppc/magic
                '-hfs-bless', "/ppc/mac",  # must be the last
            ]
            return result

        if arch == "sparc":
            result = [
                '-G', '/boot/isofs.b',
                '-B', '...',
                '-s', '/boot/silo.conf',
                '-sparc-label', '"sparc"',
            ]
            return result

        if arch in ("s390", "s390x"):
            result = [
                # "-no-emul-boot",
                # "-b", "images/cdboot.img",
                # "-c", "boot.cat",
            ]
            return result

        raise ValueError("Unknown arch: %s" % arch)

    def _truncate_volid(self, volid):
        if len(volid) > 32:
            old_volid = volid
            volid = volid.replace("-", "")
            self.log_warning("Truncating volume ID from '%s' to '%s'" % (old_volid, volid))

        if len(volid) > 32:
            old_volid = volid
            volid = volid.replace(" ", "")
            self.log_warning("Truncating volume ID from '%s' to '%s'" % (old_volid, volid))

        if len(volid) > 32:
            old_volid = volid
            volid = volid.replace("Supplementary", "Supp")
            self.log_warning("Truncating volume ID from '%s' to '%s'" % (old_volid, volid))

        if len(volid) > 32:
            raise ValueError("Volume ID must be less than 32 character: %s" % volid)

        return volid

    def get_mkisofs_cmd(self, iso, paths, appid=None, volid=None, volset=None, exclude=None, verbose=False, boot_args=None, input_charset="utf-8", graft_points=None):
        # following options are always enabled
        untranslated_filenames = True
        translation_table = True
        joliet = True
        joliet_long = True
        rock = True

        cmd = ["/usr/bin/genisoimage"]
        if appid:
            cmd.extend(["-appid", appid])

        if untranslated_filenames:
            cmd.append("-untranslated-filenames")

        if volid:
            cmd.extend(["-volid", self._truncate_volid(volid)])

        if joliet:
            cmd.append("-J")

        if joliet_long:
            cmd.append("-joliet-long")

        if volset:
            cmd.extend(["-volset", volset])

        if rock:
            cmd.append("-rational-rock")

        if verbose:
            cmd.append("-verbose")

        if translation_table:
            cmd.append("-translation-table")

        if input_charset:
            cmd.extend(["-input-charset", input_charset])

        if exclude:
            for i in force_list(exclude):
                cmd.extend(["-x", i])

        if boot_args:
            cmd.extend(boot_args)

        cmd.extend(["-o", iso])

        if graft_points:
            cmd.append("-graft-points")
            cmd.extend(["-path-list", graft_points])
        else:
            # we're either using graft points or file lists, not both
            cmd.extend(force_list(paths))

        return cmd

    def get_implantisomd5_cmd(self, iso_path, supported=False):
        cmd = ["/usr/bin/implantisomd5"]
        if supported:
            cmd.append("--supported-iso")
        cmd.append(iso_path)
        return cmd

    def get_checkisomd5_cmd(self, iso_path, just_print=False):
        cmd = ["/usr/bin/checkisomd5"]
        if just_print:
            cmd.append("--md5sumonly")
        cmd.append(iso_path)
        return cmd

    def get_implanted_md5(self, iso_path):
        cmd = self.get_checkisomd5_cmd(iso_path, just_print=True)
        retcode, output = run(cmd)
        line = output.splitlines()[0]
        result = line.rsplit(":")[-1].strip()
        return result

    def get_checksum_cmds(self, iso_name, checksum_types=None):
        checksum_types = checksum_types or ["md5", "sha1", "sha256"]
        result = []
        for checksum_type in checksum_types:
            cmd = "%ssum -b %s > %s.%sSUM" % (checksum_type.lower(), pipes.quote(iso_name), pipes.quote(iso_name), checksum_type.upper())
            result.append(cmd)
        return result

    def get_manifest_cmd(self, iso_name):
        return "isoinfo -R -f -i %s | grep -v '/TRANS.TBL$' | sort >> %s.manifest" % (pipes.quote(iso_name), pipes.quote(iso_name))

    def get_volume_id(self, path):
        cmd = ["isoinfo", "-d", "-i", path]
        retcode, output = run(cmd)

        for line in output.splitlines():
            line = line.strip()
            if line.startswith("Volume id:"):
                return line[11:].strip()

        raise RuntimeError("Could not read Volume ID")

    def get_graft_points(self, paths, exclusive_paths=None, exclude=None):
        # path priority in ascending order (1st = lowest prio)
        # paths merge according to priority
        # exclusive paths override whole dirs

        result = {}
        exclude = exclude or []
        exclusive_paths = exclusive_paths or []

        for i in paths:
            if isinstance(i, dict):
                tree = i
            else:
                tree = self._scan_tree(i)
            result = self._merge_trees(result, tree)

        for i in exclusive_paths:
            tree = self._scan_tree(i)
            result = self._merge_trees(result, tree, exclusive=True)

        # TODO: exclude
        return result

    def _paths_from_list(self, root, paths):
        root = os.path.abspath(root).rstrip("/") + "/"
        result = {}
        for i in paths:
            i = os.path.normpath(os.path.join(root, i))
            key = i[len(root):]
            result[key] = i
        return result

    def _scan_tree(self, path):
        path = os.path.abspath(path)
        result = {}
        for root, dirs, files in os.walk(path):
            for f in files:
                abspath = os.path.join(root, f)
                relpath = relative_path(abspath, path.rstrip("/") + "/")
                result[relpath] = abspath

            # include empty dirs
            if root != path:
                abspath = os.path.join(root, "")
                relpath = relative_path(abspath, path.rstrip("/") + "/")
                result[relpath] = abspath

        return result

    def _merge_trees(self, tree1, tree2, exclusive=False):
        # tree2 has higher priority
        result = tree2.copy()
        all_dirs = set([os.path.dirname(i).rstrip("/") for i in result if os.path.dirname(i) != ""])

        for i in tree1:
            dn = os.path.dirname(i)
            if exclusive:
                match = False
                for a in all_dirs:
                    if dn == a or dn.startswith("%s/" % a):
                        match = True
                        break
                if match:
                    continue

            if i in result:
                continue

            result[i] = tree1[i]
        return result

    def write_graft_points(self, file_name, h, exclude=None):
        exclude = exclude or []
        result = {}
        seen_dirs = set()
        for i in sorted(h, reverse=True):
            dn = os.path.dirname(i)

            if not i.endswith("/"):
                result[i] = h[i]
                seen_dirs.add(dn)
                continue

            found = False
            for j in seen_dirs:
                if j.startswith(dn):
                    found = True
                    break
            if not found:
                result[i] = h[i]
            seen_dirs.add(dn)

        f = open(file_name, "w")
        for i in sorted(result, cmp=cmp_graft_points):
            # make sure all files required for boot come first,
            # otherwise there may be problems with booting (large LBA address, etc.)
            found = False
            for excl in exclude:
                if fnmatch(i, excl):
                    found = True
                    break
            if found:
                continue
            f.write("%s=%s\n" % (i, h[i]))
        f.close()


def _is_rpm(path):
    if path.endswith(".rpm"):
        return True
    return False


def _is_image(path):
    if path.startswith("images/"):
        return True
    if path.startswith("isolinux/"):
        return True
    if path.startswith("EFI/"):
        return True
    if path.startswith("etc/"):
        return True
    if path.startswith("ppc/"):
        return True
    if path.endswith(".img"):
        return True
    if path.endswith(".ins"):
        return True
    return False


def cmp_graft_points(x, y):
    x_is_rpm = _is_rpm(x)
    y_is_rpm = _is_rpm(y)
    x_is_image = _is_image(x)
    y_is_image = _is_image(y)

    if x_is_rpm and y_is_rpm:
        return cmp(x, y)
    if x_is_rpm:
        return 1
    if y_is_rpm:
        return -1

    if x_is_image and y_is_image:
        return cmp(x, y)
    if x_is_image:
        return -1
    if y_is_image:
        return 1

    return cmp(x, y)
