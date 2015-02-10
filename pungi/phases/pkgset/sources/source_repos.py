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
import cPickle as pickle

from kobo.shortcuts import run

import pypungi.phases.pkgset.pkgsets
from pypungi.arch import get_valid_arches
from pypungi.util import makedirs
from pypungi.wrappers.pungi import PungiWrapper

from pypungi.phases.pkgset.common import create_global_repo, create_arch_repos, populate_arch_pkgsets
from pypungi.phases.gather import get_prepopulate_packages
from pypungi.linker import LinkerThread, LinkerPool


import pypungi.phases.pkgset.source


class PkgsetSourceRepos(pypungi.phases.pkgset.source.PkgsetSourceBase):
    enabled = True
    config_options = (
        {
            "name": "pkgset_source",
            "expected_types": [str],
            "expected_values": "repos",
        },
        {
            "name": "pkgset_repos",
            "expected_types": [dict],
        },
    )

    def __call__(self):
        package_sets, path_prefix = get_pkgset_from_repos(self.compose)
        return (package_sets, path_prefix)


def get_pkgset_from_repos(compose):
    # populate pkgset from yum repos
    # TODO: noarch hack - secondary arches, use x86_64 noarch where possible
    flist = []

    link_type = compose.conf.get("link_type", "hardlink-or-copy")
    pool = LinkerPool(link_type, logger=compose._logger)
    for i in range(10):
        pool.add(LinkerThread(pool))

    seen_packages = set()
    for arch in compose.get_arches():
        # write a pungi config for remote repos and a local comps repo
        repos = {}
        for num, repo in enumerate(compose.conf["pkgset_repos"][arch]):
            repo_path = repo
            if "://" not in repo_path:
                repo_path = os.path.join(compose.config_dir, repo)
            repos["repo-%s" % num] = repo_path

        comps_repo = None
        if compose.has_comps:
            repos["comps"] = compose.paths.work.comps_repo(arch=arch)
            comps_repo = "comps"
        write_pungi_config(compose, arch, None, repos=repos, comps_repo=comps_repo)

        pungi = PungiWrapper()
        pungi_conf = compose.paths.work.pungi_conf(arch=arch)
        pungi_log = compose.paths.log.log_file(arch, "fooo")
        pungi_dir = compose.paths.work.pungi_download_dir(arch)
        cmd = pungi.get_pungi_cmd(pungi_conf, destdir=pungi_dir, name="FOO", selfhosting=True, fulltree=True, multilib_methods=["all"], nodownload=False, full_archlist=True, arch=arch, cache_dir=compose.paths.work.pungi_cache_dir(arch=arch))
        cmd.append("--force")

        # TODO: runroot
        run(cmd, logfile=pungi_log, show_cmd=True, stdout=False)

        path_prefix = os.path.join(compose.paths.work.topdir(arch="global"), "download") + "/"
        makedirs(path_prefix)
        for root, dirs, files in os.walk(pungi_dir):
            for fn in files:
                if not fn.endswith(".rpm"):
                    continue
                if fn in seen_packages:
                    continue
                seen_packages.add(fn)
                src = os.path.join(root, fn)
                dst = os.path.join(path_prefix, os.path.basename(src))
                flist.append(dst)
                pool.queue_put((src, dst))

    msg = "Linking downloaded pkgset packages"
    compose.log_info("[BEGIN] %s" % msg)
    pool.start()
    pool.stop()
    compose.log_info("[DONE ] %s" % msg)

    flist = sorted(set(flist))
    pkgset_global = populate_global_pkgset(compose, flist, path_prefix)
#    get_extra_packages(compose, pkgset_global)
    package_sets = populate_arch_pkgsets(compose, path_prefix, pkgset_global)

    create_global_repo(compose, path_prefix)
    for arch in compose.get_arches():
        # TODO: threads? runroot?
        create_arch_repos(compose, arch, path_prefix)

    package_sets["global"] = pkgset_global
    return package_sets, path_prefix


def populate_global_pkgset(compose, file_list, path_prefix):
    ALL_ARCHES = set(["src"])
    for arch in compose.get_arches():
        is_multilib = arch in compose.conf["multilib_arches"]
        arches = get_valid_arches(arch, is_multilib)
        ALL_ARCHES.update(arches)

    msg = "Populating the global package set from a file list"
    global_pkgset_path = os.path.join(compose.paths.work.topdir(arch="global"), "packages.pickle")
    if compose.DEBUG and os.path.isfile(global_pkgset_path):
        compose.log_warning("[SKIP ] %s" % msg)
        pkgset = pickle.load(open(global_pkgset_path, "r"))
    else:
        compose.log_info(msg)
        pkgset = pypungi.phases.pkgset.pkgsets.FilelistPackageSet(compose.conf["sigkeys"], logger=compose._logger, arches=ALL_ARCHES)
        pkgset.populate(file_list)
        f = open(global_pkgset_path, "w")
        data = pickle.dumps(pkgset)
        f.write(data)
        f.close()

    # write global package list
    pkgset.save_file_list(compose.paths.work.package_list(arch="global"), remove_path_prefix=path_prefix)
    return pkgset


def write_pungi_config(compose, arch, variant, repos=None, comps_repo=None, package_set=None):
    """write pungi config (kickstart) for arch/variant"""
    pungi = PungiWrapper()
    pungi_cfg = compose.paths.work.pungi_conf(variant=variant, arch=arch)
    msg = "Writing pungi config (arch: %s, variant: %s): %s" % (arch, variant, pungi_cfg)

    if compose.DEBUG and os.path.isfile(pungi_cfg):
        compose.log_warning("[SKIP ] %s" % msg)
        return

    compose.log_info(msg)

    # TODO move to a function
    gather_source = "GatherSource%s" % compose.conf["gather_source"]
    from pypungi.phases.gather.source import GatherSourceContainer
    import pypungi.phases.gather.sources
    GatherSourceContainer.register_module(pypungi.phases.gather.sources)
    container = GatherSourceContainer()
    SourceClass = container[gather_source]
    src = SourceClass(compose)

    packages = []
    pkgs, grps = src(arch, variant)
    for pkg_name, pkg_arch in pkgs:
        if pkg_arch is None:
            packages.append(pkg_name)
        else:
            packages.append("%s.%s" % (pkg_name, pkg_arch))

    # include *all* packages providing system-release
    if "system-release" not in packages:
        packages.append("system-release")

    prepopulate = get_prepopulate_packages(compose, arch, None)
    pungi.write_kickstart(ks_path=pungi_cfg, repos=repos, groups=grps, packages=packages, exclude_packages=[], comps_repo=None, prepopulate=prepopulate)
