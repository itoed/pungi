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


import errno
import os
import time
import pipes
import tempfile
import shutil
import re
import errno

from kobo.threads import ThreadPool, WorkerThread
from kobo.shortcuts import run, read_checksum_file, relative_path
from productmd.imagemanifest import Image

from pypungi.util import get_buildroot_rpms, get_volid
from pypungi.wrappers.lorax import LoraxWrapper
from pypungi.wrappers.kojiwrapper import KojiWrapper
from pypungi.wrappers.iso import IsoWrapper
from pypungi.wrappers.scm import get_file_from_scm
from pypungi.phases.base import PhaseBase


class BuildinstallPhase(PhaseBase):
    name = "buildinstall"

    config_options = (
        {
            "name": "bootable",
            "expected_types": [bool],
            "expected_values": [True],
        },
        {
            "name": "buildinstall_method",
            "extected_types": [str],
            "expected_values": ["lorax", "buildinstall"],
            "requires": (
                (lambda x: bool(x) is True, ["bootable"]),
            ),
        },
        {
            "name": "buildinstall_upgrade_image",
            "expected_types": [bool],
            "optional": True,
        },
        {
            "name": "buildinstall_kickstart",
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
        if not self.compose.conf.get("bootable"):
            msg = "Not a bootable product. Skipping buildinstall."
            self.compose.log_debug(msg)
            return True
        return False

    def run(self):
        lorax = LoraxWrapper()
        product = self.compose.conf["product_name"]
        version = self.compose.conf["product_version"]
        release = self.compose.conf["product_version"]
        noupgrade = not self.compose.conf.get("buildinstall_upgrade_image", False)
        buildinstall_method = self.compose.conf["buildinstall_method"]

        for arch in self.compose.get_arches():
            repo_baseurl = self.compose.paths.work.arch_repo(arch)
            output_dir = self.compose.paths.work.buildinstall_dir(arch)
            volid = get_volid(self.compose, arch)

            if buildinstall_method == "lorax":
                cmd = lorax.get_lorax_cmd(product, version, release, repo_baseurl, output_dir, is_final=self.compose.supported, buildarch=arch, volid=volid, nomacboot=True, noupgrade=noupgrade)
            elif buildinstall_method == "buildinstall":
                cmd = lorax.get_buildinstall_cmd(product, version, release, repo_baseurl, output_dir, is_final=self.compose.supported, buildarch=arch, volid=volid)
            else:
                raise ValueError("Unsupported buildinstall method: %s" % buildinstall_method)
            self.pool.add(BuildinstallThread(self.pool))
            self.pool.queue_put((self.compose, arch, cmd))

        self.pool.start()

    def copy_files(self):
        # copy buildinstall files to the 'os' dir
        kickstart_file = get_kickstart_file(self.compose)
        for arch in self.compose.get_arches():
            for variant in self.compose.get_variants(arch=arch, types=["self", "variant"]):
                buildinstall_dir = self.compose.paths.work.buildinstall_dir(arch)
                if not os.path.isdir(buildinstall_dir) or not os.listdir(buildinstall_dir):
                    continue

                os_tree = self.compose.paths.compose.os_tree(arch, variant)
                # TODO: label is not used
                label = ""
                volid = get_volid(self.compose, arch, variant, escape_spaces=False)
                tweak_buildinstall(buildinstall_dir, os_tree, arch, variant.uid, label, volid, kickstart_file)
                symlink_boot_iso(self.compose, arch, variant)


def get_kickstart_file(compose):
    scm_dict = compose.conf.get("buildinstall_kickstart", None)
    if not scm_dict:
        compose.log_debug("Path to ks.cfg (buildinstall_kickstart) not specified.")
        return

    msg = "Getting ks.cfg"
    kickstart_path = os.path.join(compose.paths.work.topdir(arch="global"), "ks.cfg")
    if os.path.exists(kickstart_path):
        compose.log_warn("[SKIP ] %s" % msg)
        return kickstart_path

    compose.log_info("[BEGIN] %s" % msg)
    if isinstance(scm_dict, dict):
        kickstart_name = os.path.basename(scm_dict["file"])
        if scm_dict["scm"] == "file":
            scm_dict["file"] = os.path.join(compose.config_dir, scm_dict["file"])
    else:
        kickstart_name = os.path.basename(scm_dict)
        scm_dict = os.path.join(compose.config_dir, scm_dict)

    tmp_dir = tempfile.mkdtemp(prefix="buildinstall_kickstart_")
    get_file_from_scm(scm_dict, tmp_dir, logger=compose._logger)
    src = os.path.join(tmp_dir, kickstart_name)
    shutil.copy2(src, kickstart_path)
    compose.log_info("[DONE ] %s" % msg)
    return kickstart_path


# HACK: this is a hack!
# * it's quite trivial to replace volids
# * it's not easy to replace menu titles
# * we probably need to get this into lorax
def tweak_buildinstall(src, dst, arch, variant, label, volid, kickstart_file=None):
    volid_escaped = volid.replace(" ", r"\x20").replace("\\", "\\\\")
    volid_escaped_2 = volid_escaped.replace("\\", "\\\\")
    tmp_dir = tempfile.mkdtemp(prefix="tweak_buildinstall_")

    # verify src
    if not os.path.isdir(src):
        raise OSError(errno.ENOENT, "Directory does not exist: %s" % src)

    # create dst
    try:
        os.makedirs(dst)
    except OSError as ex:
        if ex.errno != errno.EEXIST:
            raise

    # copy src to temp
    # TODO: place temp on the same device as buildinstall dir so we can hardlink
    cmd = "cp -av --remove-destination %s/* %s/" % (pipes.quote(src), pipes.quote(tmp_dir))
    run(cmd)

    # tweak configs
    configs = [
        "isolinux/isolinux.cfg",
        "etc/yaboot.conf",
        "ppc/ppc64/yaboot.conf",
        "EFI/BOOT/BOOTX64.conf",
        "EFI/BOOT/grub.cfg",
    ]
    for config in configs:
        config_path = os.path.join(tmp_dir, config)
        if not os.path.exists(config_path):
            continue

        data = open(config_path, "r").read()
        os.unlink(config_path)  # break hadlink by removing file writing a new one

        new_volid = volid_escaped
        if "yaboot" in config:
            # double-escape volid in yaboot.conf
            new_volid = volid_escaped_2

        ks = ""
        if kickstart_file:
            shutil.copy2(kickstart_file, os.path.join(dst, "ks.cfg"))
            ks = " ks=hd:LABEL=%s:/ks.cfg" % new_volid

        # pre-f18
        data = re.sub(r":CDLABEL=[^ \n]*", r":CDLABEL=%s%s" % (new_volid, ks), data)
        # f18+
        data = re.sub(r":LABEL=[^ \n]*", r":LABEL=%s%s" % (new_volid, ks), data)
        data = re.sub(r"(search .* -l) '[^'\n]*'", r"\1 '%s'" % volid, data)

        open(config_path, "w").write(data)

    images = [
        os.path.join(tmp_dir, "images", "efiboot.img"),
    ]
    for image in images:
        if not os.path.isfile(image):
            continue
        mount_tmp_dir = tempfile.mkdtemp(prefix="tweak_buildinstall")
        cmd = ["mount", "-o", "loop", image, mount_tmp_dir]
        run(cmd)

        for config in configs:
            config_path = os.path.join(tmp_dir, config)
            config_in_image = os.path.join(mount_tmp_dir, config)

            if os.path.isfile(config_in_image):
                cmd = ["cp", "-v", "--remove-destination", config_path, config_in_image]
                run(cmd)

        cmd = ["umount", mount_tmp_dir]
        run(cmd)
        shutil.rmtree(mount_tmp_dir)

    # HACK: make buildinstall files world readable
    run("chmod -R a+rX %s" % pipes.quote(tmp_dir))

    # copy temp to dst
    cmd = "cp -av --remove-destination %s/* %s/" % (pipes.quote(tmp_dir), pipes.quote(dst))
    run(cmd)

    shutil.rmtree(tmp_dir)


def symlink_boot_iso(compose, arch, variant):
    if arch == "src":
        return

    symlink_isos_to = compose.conf.get("symlink_isos_to", None)
    os_tree = compose.paths.compose.os_tree(arch, variant)
    # TODO: find in treeinfo?
    boot_iso_path = os.path.join(os_tree, "images", "boot.iso")
    if not os.path.isfile(boot_iso_path):
        return

    msg = "Symlinking boot.iso (arch: %s, variant: %s)" % (arch, variant)
    new_boot_iso_path = compose.paths.compose.iso_path(arch, variant, disc_type="boot", disc_num=None, suffix=".iso", symlink_to=symlink_isos_to)
    new_boot_iso_relative_path = compose.paths.compose.iso_path(arch, variant, disc_type="boot", disc_num=None, suffix=".iso", relative=True)
    if os.path.exists(new_boot_iso_path):
        # TODO: log
        compose.log_warning("[SKIP ] %s" % msg)
        return

    compose.log_info("[BEGIN] %s" % msg)
    # can't make a hardlink - possible cross-device link due to 'symlink_to' argument
    symlink_target = relative_path(boot_iso_path, new_boot_iso_path)
    os.symlink(symlink_target, new_boot_iso_path)

    iso = IsoWrapper()
    implant_md5 = iso.get_implanted_md5(new_boot_iso_path)
    # compute md5sum, sha1sum, sha256sum
    iso_name = os.path.basename(new_boot_iso_path)
    iso_dir = os.path.dirname(new_boot_iso_path)
    for cmd in iso.get_checksum_cmds(iso_name):
        run(cmd, workdir=iso_dir)

    # create iso manifest
    run(iso.get_manifest_cmd(iso_name), workdir=iso_dir)

    img = Image(compose.im)
    img.implant_md5 = iso.get_implanted_md5(new_boot_iso_path)
    img.path = new_boot_iso_relative_path
    img.mtime = int(os.stat(new_boot_iso_path).st_mtime)
    img.size = os.path.getsize(new_boot_iso_path)
    img.arch = arch
    img.type = "boot"
    img.format = "iso"
    img.disc_number = 1
    img.disc_count = 1
    for checksum_type in ("md5", "sha1", "sha256"):
        checksum_path = new_boot_iso_path + ".%sSUM" % checksum_type.upper()
        checksum_value = None
        if os.path.isfile(checksum_path):
            checksum_value, iso_name = read_checksum_file(checksum_path)[0]
            if iso_name != os.path.basename(img.path):
                # a bit paranoind check - this should never happen
                raise ValueError("Image name doesn't match checksum: %s" % checksum_path)
        img.add_checksum(compose.paths.compose.topdir(), checksum_type=checksum_type, checksum_value=checksum_value)
    img.bootable = True
    img.implant_md5 = implant_md5
    try:
        img.volume_id = iso.get_volume_id(new_boot_iso_path)
    except RuntimeError:
        pass
    compose.im.add(arch, variant.uid, img)
    compose.log_info("[DONE ] %s" % msg)


class BuildinstallThread(WorkerThread):
    def process(self, item, num):
        compose, arch, cmd = item
        runroot = compose.conf.get("runroot", False)
        buildinstall_method = compose.conf["buildinstall_method"]
        log_file = compose.paths.log.log_file(arch, "buildinstall")

        msg = "Runnging buildinstall for arch %s" % arch

        output_dir = compose.paths.work.buildinstall_dir(arch)
        if os.path.isdir(output_dir):
            if os.listdir(output_dir):
                # output dir is *not* empty -> SKIP
                self.pool.log_warning("[SKIP ] %s" % msg)
                return
            else:
                # output dir is empty -> remove it and run buildinstall
                self.pool.log_debug("Removing existing (but empty) buildinstall dir: %s" % output_dir)
                os.rmdir(output_dir)

        self.pool.log_info("[BEGIN] %s" % msg)

        task_id = None
        if runroot:
            # run in a koji build root
            # glibc32 is needed by yaboot on ppc64
            packages = ["glibc32", "strace"]
            if buildinstall_method == "lorax":
                packages += ["lorax"]
            elif buildinstall_method == "buildinstall":
                packages += ["anaconda"]
            runroot_channel = compose.conf.get("runroot_channel", None)
            runroot_tag = compose.conf["runroot_tag"]

            koji_wrapper = KojiWrapper(compose.conf["koji_profile"])
            koji_cmd = koji_wrapper.get_runroot_cmd(runroot_tag, arch, cmd, channel=runroot_channel, use_shell=True, task_id=True, packages=packages, mounts=[compose.topdir])

            # avoid race conditions?
            # Kerberos authentication failed: Permission denied in replay cache code (-1765328215)
            time.sleep(num * 3)

            output = koji_wrapper.run_runroot_cmd(koji_cmd, log_file=log_file)
            task_id = int(output["task_id"])
            if output["retcode"] != 0:
                raise RuntimeError("Runroot task failed: %s. See %s for more details." % (output["task_id"], log_file))

        else:
            # run locally
            run(cmd, show_cmd=True, logfile=log_file)

        log_file = compose.paths.log.log_file(arch, "buildinstall-RPMs")
        rpms = get_buildroot_rpms(compose, task_id)
        open(log_file, "w").write("\n".join(rpms))

        self.pool.log_info("[DONE ] %s" % msg)
