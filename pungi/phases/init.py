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
import tempfile
import shutil

from kobo.shortcuts import run

from pypungi.phases.base import PhaseBase
from pypungi.phases.gather import write_prepopulate_file
from pypungi.wrappers.createrepo import CreaterepoWrapper
from pypungi.wrappers.comps import CompsWrapper
from pypungi.wrappers.scm import get_file_from_scm


class InitPhase(PhaseBase):
    """INIT is a mandatory phase"""
    name = "init"

    config_options = (
        # PRODUCT INFO
        {
            "name": "product_name",
            "expected_types": [str],
        },
        {
            "name": "product_short",
            "expected_types": [str],
        },
        {
            "name": "product_version",
            "expected_types": [str],
        },
        {
            # override description in .discinfo; accepts %(variant_name)s and %(arch)s variables
            "name": "product_discinfo_description",
            "expected_types": [str],
            "optional": True,
        },
        {
            "name": "product_is_layered",
            "expected_types": [bool],
            "requires": (
                (lambda x: bool(x), ["base_product_name", "base_product_short", "base_product_version"]),
            ),
            "conflicts": (
                (lambda x: not bool(x), ["base_product_name", "base_product_short", "base_product_version"]),
            ),
        },

        # BASE PRODUCT INFO (FOR A LAYERED PRODUCT ONLY)
        {
            "name": "base_product_name",
            "expected_types": [str],
            "optional": True,
        },
        {
            "name": "base_product_short",
            "expected_types": [str],
            "optional": True,
        },
        {
            "name": "base_product_version",
            "expected_types": [str],
            "optional": True,
        },

        {
            "name": "comps_file",
            "expected_types": [str, dict],
            "optional": True,
        },
        {
            "name": "comps_filter_environments",  # !!! default is True !!!
            "expected_types": [bool],
            "optional": True,
        },
        {
            "name": "variants_file",
            "expected_types": [str, dict],
        },
        {
            "name": "sigkeys",
            "expected_types": [list],
        },

        {
            "name": "tree_arches",
            "expected_types": [list],
            "optional": True,
        },
        {
            "name": "tree_variants",
            "expected_types": [list],
            "optional": True,
        },
        {
            "name": "multilib_arches",
            "expected_types": [list],
            "optional": True,
        },

        # CREATEREPO SETTINGS
        {
            "name": "createrepo_c",
            "expected_types": [bool],
            "optional": True,
        },
        {
            "name": "createrepo_checksum",
            "expected_types": [str],
            "expected_values": ["sha256", "sha"],
            "optional": True,
        },

        # RUNROOT SETTINGS
        {
            "name": "runroot",
            "expected_types": [bool],
            "requires": (
                (lambda x: bool(x), ["runroot_tag", "runroot_channel"]),
            ),
            "conflicts": (
                (lambda x: not bool(x), ["runroot_tag", "runroot_channel"]),
            ),
        },
        {
            "name": "runroot_tag",
            "expected_types": [str],
            "optional": True,
        },
        {
            "name": "runroot_channel",
            "expected_types": [str],
            "optional": True,
        },


    )

    def skip(self):
        # INIT must never be skipped,
        # because it generates data for LIVEIMAGES
        return False

    def run(self):
        # write global comps and arch comps
        write_global_comps(self.compose)
        for arch in self.compose.get_arches():
            write_arch_comps(self.compose, arch)

        # create comps repos
        for arch in self.compose.get_arches():
            create_comps_repo(self.compose, arch)

        # write variant comps
        for variant in self.compose.get_variants():
            for arch in variant.arches:
                write_variant_comps(self.compose, arch, variant)

        # download variants.xml / product.xml?

        # write prepopulate file
        write_prepopulate_file(self.compose)


def write_global_comps(compose):
    if not compose.has_comps:
        return

    comps_file_global = compose.paths.work.comps(arch="global")
    msg = "Writing global comps file: %s" % comps_file_global

    if compose.DEBUG and os.path.isfile(comps_file_global):
        compose.log_warning("[SKIP ] %s" % msg)
    else:
        scm_dict = compose.conf["comps_file"]
        if isinstance(scm_dict, dict):
            comps_name = os.path.basename(scm_dict["file"])
            if scm_dict["scm"] == "file":
                scm_dict["file"] = os.path.join(compose.config_dir, scm_dict["file"])
        else:
            comps_name = os.path.basename(scm_dict)
            scm_dict = os.path.join(compose.config_dir, scm_dict)

        compose.log_debug(msg)
        tmp_dir = tempfile.mkdtemp(prefix="comps_")
        get_file_from_scm(scm_dict, tmp_dir, logger=compose._logger)
        shutil.copy2(os.path.join(tmp_dir, comps_name), comps_file_global)
        shutil.rmtree(tmp_dir)


def write_arch_comps(compose, arch):
    if not compose.has_comps:
        return

    comps_file_arch = compose.paths.work.comps(arch=arch)
    msg = "Writing comps file for arch '%s': %s" % (arch, comps_file_arch)

    if compose.DEBUG and os.path.isfile(comps_file_arch):
        compose.log_warning("[SKIP ] %s" % msg)
        return

    compose.log_debug(msg)
    run(["comps_filter", "--arch=%s" % arch, "--no-cleanup", "--output=%s" % comps_file_arch, compose.paths.work.comps(arch="global")])


def write_variant_comps(compose, arch, variant):
    if not compose.has_comps:
        return

    comps_file = compose.paths.work.comps(arch=arch, variant=variant)
    msg = "Writing comps file (arch: %s, variant: %s): %s" % (arch, variant, comps_file)

    if compose.DEBUG and os.path.isfile(comps_file):
        # read display_order and groups for environments (needed for live images)
        comps = CompsWrapper(comps_file)
        # groups = variant.groups
        comps.filter_groups(variant.groups)
        if compose.conf.get("comps_filter_environments", True):
            comps.filter_environments(variant.environments)

        compose.log_warning("[SKIP ] %s" % msg)
        return

    compose.log_debug(msg)
    run(["comps_filter", "--arch=%s" % arch, "--keep-empty-group=conflicts", "--keep-empty-group=conflicts-%s" % variant.uid.lower(), "--output=%s" % comps_file, compose.paths.work.comps(arch="global")])

    comps = CompsWrapper(comps_file)
    comps.filter_groups(variant.groups)
    if compose.conf.get("comps_filter_environments", True):
        comps.filter_environments(variant.environments)
    comps.write_comps()


def create_comps_repo(compose, arch):
    if not compose.has_comps:
        return

    createrepo_c = compose.conf.get("createrepo_c", False)
    createrepo_checksum = compose.conf.get("createrepo_checksum", None)
    repo = CreaterepoWrapper(createrepo_c=createrepo_c)
    comps_repo = compose.paths.work.comps_repo(arch=arch)
    comps_path = compose.paths.work.comps(arch=arch)
    msg = "Creating comps repo for arch '%s'" % arch
    if compose.DEBUG and os.path.isdir(os.path.join(comps_repo, "repodata")):
        compose.log_warning("[SKIP ] %s" % msg)
    else:
        compose.log_info("[BEGIN] %s" % msg)
        cmd = repo.get_createrepo_cmd(comps_repo, update=True, database=True, skip_stat=True, outputdir=comps_repo, groupfile=comps_path, checksum=createrepo_checksum)
        run(cmd, logfile=compose.paths.log.log_file("global", "arch_repo"), show_cmd=True)
        compose.log_info("[DONE ] %s" % msg)
