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
import copy
import fnmatch
import pipes

from kobo.shortcuts import run

from pypungi.util import get_arch_variant_data, pkg_is_rpm
from pypungi.arch import split_name_arch
from pypungi.wrappers.scm import get_file_from_scm, get_dir_from_scm
from pypungi.phases.base import PhaseBase


class ExtraFilesPhase(PhaseBase):
    """EXTRA_FILES"""
    name = "extra_files"

    config_options = (
        {
            "name": "extra_files",
            "expected_types": [list],
            "optional": True
        },
    )

    def __init__(self, compose, pkgset_phase):
        PhaseBase.__init__(self, compose)
        # pkgset_phase provides package_sets and path_prefix
        self.pkgset_phase = pkgset_phase

    def run(self):
        for arch in self.compose.get_arches() + ["src"]:
            for variant in self.compose.get_variants(arch=arch):
                copy_extra_files(self.compose, arch, variant, self.pkgset_phase.package_sets)


def copy_extra_files(compose, arch, variant, package_sets):
    if "extra_files" not in compose.conf:
        return

    var_dict = {
        "arch": arch,
        "variant_id": variant.id,
        "variant_id_lower": variant.id.lower(),
        "variant_uid": variant.uid,
        "variant_uid_lower": variant.uid.lower(),
    }

    msg = "Getting extra files (arch: %s, variant: %s)" % (arch, variant)
    # no skip (yet?)
    compose.log_info("[BEGIN] %s" % msg)

    os_tree = compose.paths.compose.os_tree(arch, variant)
    extra_files_dir = compose.paths.work.extra_files_dir(arch, variant)

    for scm_dict in get_arch_variant_data(compose.conf, "extra_files", arch, variant):
        scm_dict = copy.deepcopy(scm_dict)
        # if scm is "rpm" and repo contains a package name, find the package(s) in package set
        if scm_dict["scm"] == "rpm" and not (scm_dict["repo"].startswith("/") or "://" in scm_dict["repo"]):
            rpms = []
            for pkgset_file in package_sets[arch]:
                pkg_obj = package_sets[arch][pkgset_file]
                if not pkg_is_rpm(pkg_obj):
                    continue
                pkg_name, pkg_arch = split_name_arch(scm_dict["repo"] % var_dict)
                if fnmatch.fnmatch(pkg_obj.name, pkg_name) and pkg_arch is None or pkg_arch == pkg_obj.arch:
                    rpms.append(pkg_obj.file_path)
            scm_dict["repo"] = rpms

        if "file" in scm_dict:
            get_file_from_scm(scm_dict, os.path.join(extra_files_dir, scm_dict.get("target", "").lstrip("/")), logger=compose._logger)
        else:
            get_dir_from_scm(scm_dict, os.path.join(extra_files_dir, scm_dict.get("target", "").lstrip("/")), logger=compose._logger)

    if os.listdir(extra_files_dir):
        cmd = "cp -av --remove-destination %s/* %s/" % (pipes.quote(extra_files_dir), pipes.quote(os_tree))
        run(cmd)

    compose.log_info("[DONE ] %s" % msg)
