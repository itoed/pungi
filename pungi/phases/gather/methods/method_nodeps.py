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


import pypungi.arch
from pypungi.util import pkg_is_rpm, pkg_is_srpm, pkg_is_debug

import pypungi.phases.gather.method


class GatherMethodNodeps(pypungi.phases.gather.method.GatherMethodBase):
    enabled = True
    config_options = (
        {
            "name": "gather_method",
            "expected_types": [str],
            "expected_values": ["nodeps"],
        },
    )

    def __call__(self, arch, variant, packages, groups, filter_packages, multilib_whitelist, multilib_blacklist, package_sets, path_prefix=None, fulltree_excludes=None, prepopulate=None):
        global_pkgset = package_sets["global"]
        result = {
            "rpm": [],
            "srpm": [],
            "debuginfo": [],
        }

        seen_rpms = {}
        seen_srpms = {}

        valid_arches = pypungi.arch.get_valid_arches(arch, multilib=True)
        compatible_arches = {}
        for i in valid_arches:
            compatible_arches[i] = pypungi.arch.get_compatible_arches(i)

        for i in global_pkgset:
            pkg = global_pkgset[i]
            if not pkg_is_rpm(pkg):
                continue
            for pkg_name, pkg_arch in packages:
                if pkg.arch not in valid_arches:
                    continue
                if pkg.name != pkg_name:
                    continue
                if pkg_arch is not None and pkg.arch != pkg_arch:
                    continue
                result["rpm"].append({
                    "path": pkg.file_path,
                    "flags": ["input"],
                })
                seen_rpms.setdefault(pkg.name, set()).add(pkg.arch)
                seen_srpms.setdefault(pkg.sourcerpm, set()).add(pkg.arch)

        for i in global_pkgset:
            pkg = global_pkgset[i]
            if not pkg_is_srpm(pkg):
                continue
            if pkg.file_name in seen_srpms:
                result["srpm"].append({
                    "path": pkg.file_path,
                    "flags": ["input"],
                })

        for i in global_pkgset:
            pkg = global_pkgset[i]
            if pkg.arch not in valid_arches:
                continue
            if not pkg_is_debug(pkg):
                continue
            if pkg.sourcerpm not in seen_srpms:
                continue
            if not set(compatible_arches[pkg.arch]) & set(seen_srpms[pkg.sourcerpm]):
                # this handles stuff like i386 debuginfo in a i686 package
                continue
            result["debuginfo"].append({
                "path": pkg.file_path,
                "flags": ["input"],
            })

        return result
