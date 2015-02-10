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
    "create_variant_repo",
)


import os
import glob
import shutil
import tempfile
import threading

from kobo.threads import ThreadPool, WorkerThread
from kobo.shortcuts import run, relative_path

from pypungi.wrappers.scm import get_dir_from_scm
from pypungi.wrappers.createrepo import CreaterepoWrapper
from pypungi.phases.base import PhaseBase


createrepo_lock = threading.Lock()
createrepo_dirs = set()


class CreaterepoPhase(PhaseBase):
    name = "createrepo"

    config_options = (
        {
            "name": "createrepo_c",
            "expected_types": [bool],
            "optional": True,
        },
        {
            "name": "createrepo_checksum",
            "expected_types": [bool],
            "optional": True,
        },
        {
            "name": "product_id",
            "expected_types": [dict],
            "optional": True,
        },
        {
            "name": "product_id_allow_missing",
            "expected_types": [bool],
            "optional": True,
        },
    )

    def __init__(self, compose):
        PhaseBase.__init__(self, compose)
        self.pool = ThreadPool(logger=self.compose._logger)

    def run(self):
        get_productids_from_scm(self.compose)
        for i in range(3):
            self.pool.add(CreaterepoThread(self.pool))

        for arch in self.compose.get_arches():
            for variant in self.compose.get_variants(arch=arch):
                self.pool.queue_put((self.compose, arch, variant, "rpm"))
                self.pool.queue_put((self.compose, arch, variant, "debuginfo"))

        for variant in self.compose.get_variants():
            self.pool.queue_put((self.compose, None, variant, "srpm"))

        self.pool.start()


def create_variant_repo(compose, arch, variant, pkg_type):
    createrepo_c = compose.conf.get("createrepo_c", False)
    createrepo_checksum = compose.conf.get("createrepo_checksum", None)
    repo = CreaterepoWrapper(createrepo_c=createrepo_c)
    if pkg_type == "srpm":
        repo_dir_arch = compose.paths.work.arch_repo(arch="global")
    else:
        repo_dir_arch = compose.paths.work.arch_repo(arch=arch)

    if pkg_type == "rpm":
        repo_dir = compose.paths.compose.repository(arch=arch, variant=variant)
        package_dir = compose.paths.compose.packages(arch, variant)
    elif pkg_type == "srpm":
        repo_dir = compose.paths.compose.repository(arch="src", variant=variant)
        package_dir = compose.paths.compose.packages("src", variant)
    elif pkg_type == "debuginfo":
        repo_dir = compose.paths.compose.debug_repository(arch=arch, variant=variant)
        package_dir = compose.paths.compose.debug_packages(arch, variant)
    else:
        raise ValueError("Unknown package type: %s" % pkg_type)

    if not repo_dir:
        return

    msg = "Creating repo (arch: %s, variant: %s): %s" % (arch, variant, repo_dir)

    # HACK: using global lock
    createrepo_lock.acquire()
    if repo_dir in createrepo_dirs:
        compose.log_warning("[SKIP ] Already in progress: %s" % msg)
        createrepo_lock.release()
        return
    createrepo_dirs.add(repo_dir)
    createrepo_lock.release()

    if compose.DEBUG and os.path.isdir(os.path.join(repo_dir, "repodata")):
        compose.log_warning("[SKIP ] %s" % msg)
        return

    compose.log_info("[BEGIN] %s" % msg)

    file_list = None
    if repo_dir != package_dir:
        rel_dir = relative_path(package_dir.rstrip("/") + "/", repo_dir.rstrip("/") + "/")
        file_list = compose.paths.work.repo_package_list(arch, variant, pkg_type)
        f = open(file_list, "w")
        for i in os.listdir(package_dir):
            if i.endswith(".rpm"):
                f.write("%s\n" % os.path.join(rel_dir, i))
        f.close()

    comps_path = None
    if compose.has_comps and pkg_type == "rpm":
        comps_path = compose.paths.work.comps(arch=arch, variant=variant)
    cmd = repo.get_createrepo_cmd(repo_dir, update=True, database=True, skip_stat=True, pkglist=file_list, outputdir=repo_dir, workers=3, groupfile=comps_path, update_md_path=repo_dir_arch, checksum=createrepo_checksum)
#    cmd.append("-vvv")
    log_file = compose.paths.log.log_file(arch, "createrepo-%s" % variant)
    run(cmd, logfile=log_file, show_cmd=True)

    # call modifyrepo to inject productid
    product_id = compose.conf.get("product_id")
    if product_id and pkg_type == "rpm":
        # add product certificate to base (rpm) repo; skip source and debug
        product_id_path = compose.paths.work.product_id(arch, variant)
        if os.path.isfile(product_id_path):
            cmd = repo.get_modifyrepo_cmd(os.path.join(repo_dir, "repodata"), product_id_path, compress_type="gz")
            log_file = compose.paths.log.log_file(arch, "modifyrepo-%s" % variant)
            run(cmd, logfile=log_file, show_cmd=True)
            # productinfo is not supported by modifyrepo in any way
            # this is a HACK to make CDN happy (dmach: at least I think, need to confirm with dgregor)
            shutil.copy2(product_id_path, os.path.join(repo_dir, "repodata", "productid"))

    compose.log_info("[DONE ] %s" % msg)


class CreaterepoThread(WorkerThread):
    def process(self, item, num):
        compose, arch, variant, pkg_type = item
        create_variant_repo(compose, arch, variant, pkg_type=pkg_type)


def get_productids_from_scm(compose):
    # product_id is a scm_dict: {scm, repo, branch, dir}
    # expected file name format: $variant_uid-$arch-*.pem
    product_id = compose.conf.get("product_id")
    if not product_id:
        compose.log_info("No product certificates specified")
        return

    product_id_allow_missing = compose.conf.get("product_id_allow_missing", False)

    msg = "Getting product certificates from SCM..."
    compose.log_info("[BEGIN] %s" % msg)

    tmp_dir = tempfile.mkdtemp(prefix="pungi_")
    get_dir_from_scm(product_id, tmp_dir)

    for arch in compose.get_arches():
        for variant in compose.get_variants(arch=arch):
            # some layered products may use base product name before variant
            pem_files = glob.glob("%s/*%s-%s-*.pem" % (tmp_dir, variant.uid, arch))
            # use for development:
            # pem_files = glob.glob("%s/*.pem" % tmp_dir)[-1:]
            if not pem_files:
                msg = "No product certificate found (arch: %s, variant: %s)" % (arch, variant.uid)
                if product_id_allow_missing:
                    compose.log_warning(msg)
                    continue
                else:
                    shutil.rmtree(tmp_dir)
                    raise RuntimeError(msg)
            if len(pem_files) > 1:
                shutil.rmtree(tmp_dir)
                raise RuntimeError("Multiple product certificates found (arch: %s, variant: %s): %s" % (arch, variant.uid, ", ".join(sorted([os.path.basename(i) for i in pem_files]))))
            product_id_path = compose.paths.work.product_id(arch, variant)
            shutil.copy2(pem_files[0], product_id_path)

    shutil.rmtree(tmp_dir)
    compose.log_info("[DONE ] %s" % msg)
