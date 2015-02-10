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
import copy
import time
import pipes
import shutil
import re
import tempfile

from kobo.threads import ThreadPool, WorkerThread
from kobo.shortcuts import run

from pypungi.wrappers.kojiwrapper import KojiWrapper
from pypungi.wrappers.iso import IsoWrapper
from pypungi.wrappers.scm import get_file_from_scm
from pypungi.phases.base import PhaseBase
from pypungi.util import get_arch_variant_data


# HACK: define cmp in python3
if sys.version_info[0] == 3:
    def cmp(a, b):
        return (a > b) - (a < b)


class LiveImagesPhase(PhaseBase):
    name = "liveimages"

    config_options = (
        {
            "name": "live_target",
            "expected_types": [str],
            "optional": True,
        },
    )

    def __init__(self, compose):
        PhaseBase.__init__(self, compose)
        self.pool = ThreadPool(logger=self.compose._logger)

    def skip(self):
        if PhaseBase.skip(self):
            return True
        if not self.compose.conf.get("live_images"):
            return True
        return False

    def run(self):
        symlink_isos_to = self.compose.conf.get("symlink_isos_to", None)
        iso = IsoWrapper()
        commands = []

        for variant in self.compose.variants.values():
            for arch in variant.arches + ["src"]:
                ks_in = get_ks_in(self.compose, arch, variant)
                if not ks_in:
                    continue

                ks_file = tweak_ks(self.compose, arch, variant, ks_in)

                iso_dir = self.compose.paths.compose.iso_dir(arch, variant, symlink_to=symlink_isos_to)
                if not iso_dir:
                    continue

                # XXX: hardcoded disc_type and disc_num
                iso_path = self.compose.paths.compose.iso_path(arch, variant, disc_type="live", disc_num=None, symlink_to=symlink_isos_to)
                if os.path.isfile(iso_path):
                    self.compose.log_warning("Skipping creating live image, it already exists: %s" % iso_path)
                    continue

                iso_name = os.path.basename(iso_path)

                cmd = {
                    "arch": arch,
                    "variant": variant,
                    "iso_path": iso_path,
                    "build_arch": arch,
                    "ks_file": ks_file,
                    "cmd": [],
                    "label": "",  # currently not used
                }
                repo = self.compose.paths.compose.repository(arch, variant)
                # HACK:
                repo = re.sub(r"^/mnt/koji/", "https://kojipkgs.fedoraproject.org/", repo)
                cmd["repos"] = [repo]

                # additional repos
                data = get_arch_variant_data(self.compose.conf, "live_images", arch, variant)
                cmd["repos"].extend(data[0].get("additional_repos", []))

                chdir_cmd = "cd %s" % pipes.quote(iso_dir)
                cmd["cmd"].append(chdir_cmd)

                # compute md5sum, sha1sum, sha256sum
                cmd["cmd"].extend(iso.get_checksum_cmds(iso_name))

                # create iso manifest
                cmd["cmd"].append(iso.get_manifest_cmd(iso_name))

                cmd["cmd"] = " && ".join(cmd["cmd"])
                commands.append(cmd)

        for cmd in commands:
            self.pool.add(CreateLiveImageThread(self.pool))
            self.pool.queue_put((self.compose, cmd))

        self.pool.start()

    def stop(self, *args, **kwargs):
        PhaseBase.stop(self, *args, **kwargs)
        if self.skip():
            return


class CreateLiveImageThread(WorkerThread):
    def fail(self, compose, cmd):
        compose.log_error("LiveImage failed, removing ISO: %s" % cmd["iso_path"])
        try:
            # remove (possibly?) incomplete ISO
            os.unlink(cmd["iso_path"])
            # TODO: remove checksums
        except OSError:
            pass

    def process(self, item, num):
        compose, cmd = item

        runroot = compose.conf.get("runroot", False)
        log_file = compose.paths.log.log_file(cmd["arch"], "createiso-%s" % os.path.basename(cmd["iso_path"]))

        msg = "Creating ISO (arch: %s, variant: %s): %s" % (cmd["arch"], cmd["variant"], os.path.basename(cmd["iso_path"]))
        self.pool.log_info("[BEGIN] %s" % msg)

        if runroot:
            # run in a koji build root

            koji_wrapper = KojiWrapper(compose.conf["koji_profile"])
            name, version = compose.compose_id.rsplit("-", 1)
            target = compose.conf["live_target"]
            koji_cmd = koji_wrapper.get_create_image_cmd(name, version, target, cmd["build_arch"], cmd["ks_file"], cmd["repos"], image_type="live", wait=True, archive=False)

            # avoid race conditions?
            # Kerberos authentication failed: Permission denied in replay cache code (-1765328215)
            time.sleep(num * 3)

            output = koji_wrapper.run_create_image_cmd(koji_cmd, log_file=log_file)
            if output["retcode"] != 0:
                self.fail(compose, cmd)
                raise RuntimeError("LiveImage task failed: %s. See %s for more details." % (output["task_id"], log_file))

            # copy finished image to isos/
            image_path = koji_wrapper.get_image_path(output["task_id"])
            # TODO: assert len == 1
            image_path = image_path[0]
            shutil.copy2(image_path, cmd["iso_path"])

            # write checksum and manifest
            run(cmd["cmd"])

        else:
            raise RuntimeError("NOT IMPLEMENTED")

        self.pool.log_info("[DONE ] %s" % msg)


def get_ks_in(compose, arch, variant):
    data = get_arch_variant_data(compose.conf, "live_images", arch, variant)
    if not data:
        return
    scm_dict = data[0]["kickstart"]

    if isinstance(scm_dict, dict):
        if scm_dict["scm"] == "file":
            file_name = os.path.basename(os.path.basename(scm_dict["file"]))
            scm_dict["file"] = os.path.join(compose.config_dir, os.path.basename(scm_dict["file"]))
    else:
        file_name = os.path.basename(os.path.basename(scm_dict))
        scm_dict = os.path.join(compose.config_dir, os.path.basename(scm_dict))

    tmp_dir = tempfile.mkdtemp(prefix="ks_in_")
    get_file_from_scm(scm_dict, tmp_dir, logger=compose._logger)
    ks_in = os.path.join(compose.paths.work.topdir(arch), "liveimage-%s.%s.ks.in" % (variant.uid, arch))
    shutil.copy2(os.path.join(tmp_dir, file_name), ks_in)
    shutil.rmtree(tmp_dir)
    return ks_in


def tweak_ks(compose, arch, variant, ks_in):
    if variant.environments:
        # get groups from default environment (with lowest display_order)
        envs = copy.deepcopy(variant.environments)
        envs.sort(lambda x, y: cmp(x["display_order"], y["display_order"]))
        env = envs[0]
        groups = sorted(env["groups"])
    else:
        # no environments -> get default groups
        groups = []
        for i in variant.groups:
            if i["default"]:
                groups.append(i["name"])
        groups.sort()

    ks_file = os.path.join(compose.paths.work.topdir(arch), "liveimage-%s.%s.ks" % (variant.uid, arch))
    contents = open(ks_in, "r").read()
    contents = contents.replace("__GROUPS__", "\n".join(["@%s" % i for i in groups]))
    open(ks_file, "w").write(contents)
    return ks_file
