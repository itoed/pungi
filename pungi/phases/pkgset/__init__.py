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

from kobo.shortcuts import force_list

import pypungi.phases.pkgset.pkgsets
from pypungi.arch import get_valid_arches
from pypungi.phases.base import PhaseBase


class PkgsetPhase(PhaseBase):
    """PKGSET"""
    name = "pkgset"

    config_options = (
        {
            "name": "pkgset_source",
            "expected_types": [str],
        },
        {
            "name": "multilib_arches",
            "expected_types": [list],
        },
    )

    def run(self):
        pkgset_source = "PkgsetSource%s" % self.compose.conf["pkgset_source"]
        from source import PkgsetSourceContainer
        import sources
        PkgsetSourceContainer.register_module(sources)
        container = PkgsetSourceContainer()
        SourceClass = container[pkgset_source]
        self.package_sets, self.path_prefix = SourceClass(self.compose)()


# TODO: per arch?
def populate_arch_pkgsets(compose, path_prefix, global_pkgset):
    result = {}
    for arch in compose.get_arches():
        compose.log_info("Populating package set for arch: %s" % arch)
        is_multilib = arch in compose.conf["multilib_arches"]
        arches = get_valid_arches(arch, is_multilib, add_src=True)
        pkgset = pypungi.phases.pkgset.pkgsets.PackageSetBase(compose.conf["sigkeys"], logger=compose._logger, arches=arches)
        pkgset.merge(global_pkgset, arch, arches)
        pkgset.save_file_list(compose.paths.work.package_list(arch=arch), remove_path_prefix=path_prefix)
        result[arch] = pkgset
    return result


def find_old_compose(old_compose_dirs, shortname=None, version=None):
    composes = []

    for compose_dir in force_list(old_compose_dirs):
        if not os.path.isdir(compose_dir):
            continue

        # get all finished composes
        for i in os.listdir(compose_dir):
            # TODO: read .composeinfo
            if shortname and not i.startswith(shortname):
                continue

            if shortname and version and not i.startswith("%s-%s" % (shortname, version)):
                continue

            path = os.path.join(compose_dir, i)
            if not os.path.isdir(path):
                continue

            if os.path.islink(path):
                continue

            status_path = os.path.join(path, "STATUS")
            if not os.path.isfile(status_path):
                continue

            try:
                if open(status_path, "r").read().strip() in ("FINISHED", "DOOMED"):
                    composes.append((i, os.path.abspath(path)))
            except:
                continue

    if not composes:
        return None

    return sorted(composes)[-1][1]
