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

from kobo.shortcuts import run, force_list, relative_path

import pypungi.phases.pkgset.pkgsets
from pypungi.arch import get_valid_arches
from pypungi.wrappers.createrepo import CreaterepoWrapper


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


def create_global_repo(compose, path_prefix):
    createrepo_c = compose.conf.get("createrepo_c", False)
    createrepo_checksum = compose.conf.get("createrepo_checksum", None)
    repo = CreaterepoWrapper(createrepo_c=createrepo_c)
    repo_dir_global = compose.paths.work.arch_repo(arch="global")
    msg = "Running createrepo for the global package set"

    if compose.DEBUG and os.path.isdir(os.path.join(repo_dir_global, "repodata")):
        compose.log_warning("[SKIP ] %s" % msg)
        return

    compose.log_info("[BEGIN] %s" % msg)

    # find an old compose suitable for repodata reuse
    old_compose_path = None
    update_md_path = None
    if compose.old_composes:
        old_compose_path = find_old_compose(compose.old_composes, compose.conf["product_short"], compose.conf["product_version"], compose.conf.get("base_product_short", None), compose.conf.get("base_product_version", None))
        if old_compose_path is None:
            compose.log_info("No suitable old compose found in: %s" % compose.old_composes)
        else:
            repo_dir = compose.paths.work.arch_repo(arch="global")
            rel_path = relative_path(repo_dir, os.path.abspath(compose.topdir).rstrip("/") + "/")
            old_repo_dir = os.path.join(old_compose_path, rel_path)
            if os.path.isdir(old_repo_dir):
                compose.log_info("Using old repodata from: %s" % old_repo_dir)
                update_md_path = old_repo_dir

    # IMPORTANT: must not use --skip-stat here -- to make sure that correctly signed files are pulled in
    cmd = repo.get_createrepo_cmd(path_prefix, update=True, database=True, skip_stat=False, pkglist=compose.paths.work.package_list(arch="global"), outputdir=repo_dir_global, baseurl="file://%s" % path_prefix, workers=5, update_md_path=update_md_path, checksum=createrepo_checksum)
    run(cmd, logfile=compose.paths.log.log_file("global", "arch_repo"), show_cmd=True)
    compose.log_info("[DONE ] %s" % msg)


def create_arch_repos(compose, arch, path_prefix):
    createrepo_c = compose.conf.get("createrepo_c", False)
    createrepo_checksum = compose.conf.get("createrepo_checksum", None)
    repo = CreaterepoWrapper(createrepo_c=createrepo_c)
    repo_dir_global = compose.paths.work.arch_repo(arch="global")
    repo_dir = compose.paths.work.arch_repo(arch=arch)
    msg = "Running createrepo for arch '%s'" % arch

    if compose.DEBUG and os.path.isdir(os.path.join(repo_dir, "repodata")):
        compose.log_warning("[SKIP ] %s" % msg)
        return

    compose.log_info("[BEGIN] %s" % msg)
    comps_path = None
    if compose.has_comps:
        comps_path = compose.paths.work.comps(arch=arch)
    cmd = repo.get_createrepo_cmd(path_prefix, update=True, database=True, skip_stat=True, pkglist=compose.paths.work.package_list(arch=arch), outputdir=repo_dir, baseurl="file://%s" % path_prefix, workers=5, groupfile=comps_path, update_md_path=repo_dir_global, checksum=createrepo_checksum)
    run(cmd, logfile=compose.paths.log.log_file(arch, "arch_repo"), show_cmd=True)
    compose.log_info("[DONE ] %s" % msg)


def find_old_compose(old_compose_dirs, product_short, product_version, base_product_short=None, base_product_version=None):
    composes = []

    for compose_dir in force_list(old_compose_dirs):
        if not os.path.isdir(compose_dir):
            continue

        # get all finished composes
        for i in os.listdir(compose_dir):
            # TODO: read .composeinfo

            pattern = "%s-%s" % (product_short, product_version)
            if base_product_short:
                pattern += "-%s" % base_product_short
            if base_product_version:
                pattern += "-%s" % base_product_version

            if not i.startswith(pattern):
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
