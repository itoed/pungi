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


__all__ = (
    "Paths",
)


import errno
import os

from pypungi.util import makedirs


class Paths(object):
    def __init__(self, compose):
        paths_module_name = compose.conf.get("paths_module", None)
        if paths_module_name:
            # custom paths
            compose.log_info("Using custom paths from module %s" % paths_module_name)
            paths_module = __import__(paths_module_name, globals(), locals(), ["LogPaths", "WorkPaths", "ComposePaths"])
            self.compose = paths_module.ComposePaths(compose)
            self.log = paths_module.LogPaths(compose)
            self.work = paths_module.WorkPaths(compose)
        else:
            # default paths
            self.compose = ComposePaths(compose)
            self.log = LogPaths(compose)
            self.work = WorkPaths(compose)
        # self.metadata ?


class LogPaths(object):
    def __init__(self, compose):
        self.compose = compose

    def topdir(self, arch=None, create_dir=True):
        """
        Examples:
            log/global
            log/x86_64
        """
        arch = arch or "global"
        path = os.path.join(self.compose.topdir, "logs", arch)
        if create_dir:
            makedirs(path)
        return path

    def log_file(self, arch, log_name, create_dir=True):
        arch = arch or "global"
        if log_name.endswith(".log"):
            log_name = log_name[:-4]
        return os.path.join(self.topdir(arch, create_dir=create_dir), "%s.%s.log" % (log_name, arch))


class WorkPaths(object):
    def __init__(self, compose):
        self.compose = compose

    def topdir(self, arch=None, create_dir=True):
        """
        Examples:
            work/global
            work/x86_64
        """
        arch = arch or "global"
        path = os.path.join(self.compose.topdir, "work", arch)
        if create_dir:
            makedirs(path)
        return path

    def variants_file(self, arch=None, create_dir=True):
        """
        Examples:
            work/global/variants.xml
        """
        arch = "global"
        path = os.path.join(self.topdir(arch, create_dir=create_dir), "variants.xml")
        return path

    def comps(self, arch=None, variant=None, create_dir=True):
        """
        Examples:
            work/x86_64/comps/comps-86_64.xml
            work/x86_64/comps/comps-Server.x86_64.xml
        """
        arch = arch or "global"
        if variant is None:
            file_name = "comps-%s.xml" % arch
        else:
            file_name = "comps-%s.%s.xml" % (variant.uid, arch)
        path = os.path.join(self.topdir(arch, create_dir=create_dir), "comps")
        if create_dir:
            makedirs(path)
        path = os.path.join(path, file_name)
        return path

    def pungi_conf(self, arch=None, variant=None, create_dir=True):
        """
        Examples:
            work/x86_64/pungi/x86_64.conf
            work/x86_64/pungi/Server.x86_64.conf
        """
        arch = arch or "global"
        if variant is None:
            file_name = "%s.conf" % arch
        else:
            file_name = "%s.%s.conf" % (variant.uid, arch)
        path = os.path.join(self.topdir(arch, create_dir=create_dir), "pungi")
        if create_dir:
            makedirs(path)
        path = os.path.join(path, file_name)
        return path

    def pungi_log(self, arch=None, variant=None, create_dir=True):
        """
        Examples:
            work/x86_64/pungi/x86_64.log
            work/x86_64/pungi/Server.x86_64.log
        """
        path = self.pungi_conf(arch, variant, create_dir=create_dir)
        path = path[:-5] + ".log"
        return path

    def pungi_cache_dir(self, arch, variant=None, create_dir=True):
        """
        Examples:
            work/global/pungi-cache
        """
        # WARNING: Using the same cache dir with repos of the same names may lead to a race condition
        # We should use per arch variant cache dirs to workaround this.
        path = os.path.join(self.topdir(arch, create_dir=create_dir), "pungi-cache")
        if variant:
            path = os.path.join(path, variant.uid)
        if create_dir:
            makedirs(path)
        return path

    def comps_repo(self, arch=None, create_dir=True):
        """
        Examples:
            work/x86_64/comps-repo
            work/global/comps-repo
        """
        arch = arch or "global"
        path = os.path.join(self.topdir(arch, create_dir=create_dir), "comps_repo")
        if create_dir:
            makedirs(path)
        return path

    def arch_repo(self, arch=None, create_dir=True):
        """
        Examples:
            work/x86_64/repo
            work/global/repo
        """
        arch = arch or "global"
        path = os.path.join(self.topdir(arch, create_dir=create_dir), "repo")
        if create_dir:
            makedirs(path)
        return path

    def package_list(self, arch=None, variant=None, pkg_type=None, create_dir=True):
        """
        Examples:
            work/x86_64/package_list/x86_64.conf
            work/x86_64/package_list/Server.x86_64.conf
            work/x86_64/package_list/Server.x86_64.rpm.conf
        """
        arch = arch or "global"
        if variant is not None:
            file_name = "%s.%s" % (variant, arch)
        else:
            file_name = "%s" % arch
        if pkg_type is not None:
            file_name += ".%s" % pkg_type
        file_name += ".conf"
        path = os.path.join(self.topdir(arch, create_dir=create_dir), "package_list")
        if create_dir:
            makedirs(path)
        path = os.path.join(path, file_name)
        return path

    def pungi_download_dir(self, arch, create_dir=True):
        """
        Examples:
            work/x86_64/pungi_download
        """
        path = os.path.join(self.topdir(arch, create_dir=create_dir), "pungi_download")
        if create_dir:
            makedirs(path)
        return path

    def buildinstall_dir(self, arch, create_dir=True):
        """
        Examples:
            work/x86_64/buildinstall
        """
        if arch == "global":
            raise RuntimeError("Global buildinstall dir makes no sense.")
        path = os.path.join(self.topdir(arch, create_dir=create_dir), "buildinstall")
        return path

    def extra_files_dir(self, arch, variant, create_dir=True):
        """
        Examples:
            work/x86_64/Server/extra-files
        """
        if arch == "global":
            raise RuntimeError("Global extra files dir makes no sense.")
        path = os.path.join(self.topdir(arch, create_dir=create_dir), variant.uid, "extra-files")
        if create_dir:
            makedirs(path)
        return path

    def repo_package_list(self, arch, variant, pkg_type=None, create_dir=True):
        """
        Examples:
            work/x86_64/repo_package_list/Server.x86_64.rpm.conf
        """
        file_name = "%s.%s" % (variant, arch)
        if pkg_type is not None:
            file_name += ".%s" % pkg_type
        file_name += ".conf"
        path = os.path.join(self.topdir(arch, create_dir=create_dir), "repo_package_list")
        if create_dir:
            makedirs(path)
        path = os.path.join(path, file_name)
        return path

    def product_img(self, variant, create_dir=True):
        """
        Examples:
            work/global/product-Server.img
        """
        file_name = "product-%s.img" % variant
        path = self.topdir(arch="global", create_dir=create_dir)
        path = os.path.join(path, file_name)
        return path

    def iso_dir(self, arch, variant, disc_type="dvd", disc_num=1, create_dir=True):
        """
        Examples:
            work/x86_64/iso/rhel-7.0-20120127.0-Server-x86_64-dvd1.iso
        """
        dir_name = self.compose.paths.compose.iso_path(arch, variant, disc_type, disc_num, create_dir=False)
        dir_name = os.path.basename(dir_name)
        path = os.path.join(self.topdir(arch, create_dir=create_dir), "iso", dir_name)
        if create_dir:
            makedirs(path)
        return path

    def tmp_dir(self, arch, variant=None, create_dir=True):
        """
        Examples:
            work/x86_64/tmp
            work/x86_64/tmp-Server
        """
        dir_name = "tmp"
        if variant:
            dir_name += "-%s" % variant.uid
        path = os.path.join(self.topdir(arch, create_dir=create_dir), dir_name)
        if create_dir:
            makedirs(path)
        return path

    def product_id(self, arch, variant, create_dir=True):
        """
        Examples:
            work/x86_64/product_id/productid-Server.x86_64.pem/productid
        """
        # file_name = "%s.%s.pem" % (variant, arch)
        # HACK: modifyrepo doesn't handle renames -> $dir/productid
        file_name = "productid"
        path = os.path.join(self.topdir(arch, create_dir=create_dir), "product_id", "%s.%s.pem" % (variant, arch))
        if create_dir:
            makedirs(path)
        path = os.path.join(path, file_name)
        return path


class ComposePaths(object):
    def __init__(self, compose):
        self.compose = compose
        # TODO: TREES?

    def topdir(self, arch=None, variant=None, create_dir=True, relative=False):
        """
        Examples:
            compose
            compose/Server/x86_64
        """
        if bool(arch) != bool(variant):
            raise TypeError("topdir(): either none or 2 arguments are expected")

        path = ""
        if not relative:
            path = os.path.join(self.compose.topdir, "compose")

        if arch or variant:
            if variant.type == "addon":
                return self.topdir(arch, variant.parent, create_dir=create_dir, relative=relative)
            path = os.path.join(path, variant.uid, arch)
        if create_dir and not relative:
            makedirs(path)
        return path

    def tree_dir(self, arch, variant, create_dir=True, relative=False):
        """
        Examples:
            compose/Server/x86_64/os
            compose/Server-optional/x86_64/os
        """
        if arch == "src":
            arch = "source"

        if arch == "source":
            tree_dir = "tree"
        else:
            # use 'os' dir due to historical reasons
            tree_dir = "os"

        path = os.path.join(self.topdir(arch, variant, create_dir=create_dir, relative=relative), tree_dir)
        if create_dir and not relative:
            makedirs(path)
        return path

    def os_tree(self, arch, variant, create_dir=True, relative=False):
        return self.tree_dir(arch, variant, create_dir=create_dir, relative=relative)

    def repository(self, arch, variant, create_dir=True, relative=False):
        """
        Examples:
            compose/Server/x86_64/os
            compose/Server/x86_64/addons/LoadBalancer
        """
        if variant.type == "addon":
            path = self.packages(arch, variant, create_dir=create_dir, relative=relative)
        else:
            path = self.tree_dir(arch, variant, create_dir=create_dir, relative=relative)
        if create_dir and not relative:
            makedirs(path)
        return path

    def packages(self, arch, variant, create_dir=True, relative=False):
        """
        Examples:
            compose/Server/x86_64/os/Packages
            compose/Server/x86_64/os/addons/LoadBalancer
            compose/Server-optional/x86_64/os/Packages
        """
        if variant.type == "addon":
            path = os.path.join(self.tree_dir(arch, variant, create_dir=create_dir, relative=relative), "addons", variant.id)
        else:
            path = os.path.join(self.tree_dir(arch, variant, create_dir=create_dir, relative=relative), "Packages")
        if create_dir and not relative:
            makedirs(path)
        return path

    def debug_topdir(self, arch, variant, create_dir=True, relative=False):
        """
        Examples:
            compose/Server/x86_64/debug
            compose/Server-optional/x86_64/debug
        """
        path = os.path.join(self.topdir(arch, variant, create_dir=create_dir, relative=relative), "debug")
        if create_dir and not relative:
            makedirs(path)
        return path

    def debug_tree(self, arch, variant, create_dir=True, relative=False):
        """
        Examples:
            compose/Server/x86_64/debug/tree
            compose/Server-optional/x86_64/debug/tree
        """
        path = os.path.join(self.debug_topdir(arch, variant, create_dir=create_dir, relative=relative), "tree")
        if create_dir and not relative:
            makedirs(path)
        return path

    def debug_packages(self, arch, variant, create_dir=True, relative=False):
        """
        Examples:
            compose/Server/x86_64/debug/tree/Packages
            compose/Server/x86_64/debug/tree/addons/LoadBalancer
            compose/Server-optional/x86_64/debug/tree/Packages
        """
        if arch in ("source", "src"):
            return None
        if variant.type == "addon":
            path = os.path.join(self.debug_tree(arch, variant, create_dir=create_dir, relative=relative), "addons", variant.id)
        else:
            path = os.path.join(self.debug_tree(arch, variant, create_dir=create_dir, relative=relative), "Packages")
        if create_dir and not relative:
            makedirs(path)
        return path

    def debug_repository(self, arch, variant, create_dir=True, relative=False):
        """
        Examples:
            compose/Server/x86_64/debug/tree
            compose/Server/x86_64/debug/tree/addons/LoadBalancer
            compose/Server-optional/x86_64/debug/tree
        """
        if arch in ("source", "src"):
            return None
        if variant.type == "addon":
            path = os.path.join(self.debug_tree(arch, variant, create_dir=create_dir, relative=relative), "addons", variant.id)
        else:
            path = self.debug_tree(arch, variant, create_dir=create_dir, relative=relative)
        if create_dir and not relative:
            makedirs(path)
        return path

    def iso_dir(self, arch, variant, symlink_to=None, create_dir=True, relative=False):
        """
        Examples:
            compose/Server/x86_64/iso
            None
        """
        if variant.type == "addon":
            return None
        if variant.type == "optional":
            if not self.compose.conf["create_optional_isos"]:
                return None
        if arch == "src":
            arch = "source"
        path = os.path.join(self.topdir(arch, variant, create_dir=create_dir, relative=relative), "iso")

        if symlink_to:
            # TODO: create_dir
            topdir = self.compose.topdir.rstrip("/") + "/"
            relative_dir = path[len(topdir):]
            target_dir = os.path.join(symlink_to, self.compose.compose_id, relative_dir)
            if create_dir and not relative:
                makedirs(target_dir)
            try:
                os.symlink(target_dir, path)
            except OSError as ex:
                if ex.errno != errno.EEXIST:
                    raise
                msg = "Symlink pointing to '%s' expected: %s" % (target_dir, path)
                if not os.path.islink(path):
                    raise RuntimeError(msg)
                if os.path.abspath(os.readlink(path)) != target_dir:
                    raise RuntimeError(msg)
        else:
            if create_dir and not relative:
                makedirs(path)
        return path

    def iso_path(self, arch, variant, disc_type="dvd", disc_num=1, suffix=".iso", symlink_to=None, create_dir=True, relative=False):
        """
        Examples:
            compose/Server/x86_64/iso/rhel-7.0-20120127.0-Server-x86_64-dvd1.iso
            None
        """
        if arch == "src":
            arch = "source"

        if disc_type not in ("cd", "dvd", "ec2", "live", "boot"):
            raise RuntimeError("Unsupported disc type: %s" % disc_type)
        if disc_num:
            disc_num = int(disc_num)
        else:
            disc_num = ""

        path = self.iso_dir(arch, variant, symlink_to=symlink_to, create_dir=create_dir, relative=relative)
        if path is None:
            return None

        compose_id = self.compose.ci_base[variant.uid].compose_id
        if variant.type == "layered-product":
            variant_uid = variant.parent.uid
        else:
            variant_uid = variant.uid
        file_name = "%s-%s-%s-%s%s%s" % (compose_id, variant_uid, arch, disc_type, disc_num, suffix)
        result = os.path.join(path, file_name)
        return result

    def jigdo_dir(self, arch, variant, create_dir=True, relative=False):
        """
        Examples:
            compose/Server/x86_64/jigdo
            None
        """
        if variant.type == "addon":
            return None
        if variant.type == "optional":
            if not self.compose.conf["create_optional_isos"]:
                return None
        if arch == "src":
            arch = "source"
        path = os.path.join(self.topdir(arch, variant, create_dir=create_dir, relative=relative), "jigdo")

        if create_dir and not relative:
            makedirs(path)
        return path

    def metadata(self, file_name=None, create_dir=True, relative=False):
        """
        Examples:
            compose/metadata
            compose/metadata/rpms.json
        """
        path = os.path.join(self.topdir(create_dir=create_dir, relative=relative), "metadata")
        if create_dir and not relative:
            makedirs(path)
        if file_name:
            path = os.path.join(path, file_name)
        return path
