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
import time
import pipes
import random
import shutil

import koji
import productmd.treeinfo
from productmd.imagemanifest import Image
from kobo.threads import ThreadPool, WorkerThread
from kobo.shortcuts import run, read_checksum_file, relative_path

from pypungi.wrappers.iso import IsoWrapper
from pypungi.wrappers.createrepo import CreaterepoWrapper
from pypungi.wrappers.kojiwrapper import KojiWrapper
from pypungi.wrappers.jigdo import JigdoWrapper
from pypungi.phases.base import PhaseBase
from pypungi.util import makedirs, get_volid
from pypungi.media_split import MediaSplitter
from pypungi.compose_metadata.discinfo import read_discinfo, write_discinfo


class CreateisoPhase(PhaseBase):
    name = "createiso"

    def __init__(self, compose):
        PhaseBase.__init__(self, compose)
        self.pool = ThreadPool(logger=self.compose._logger)

    def run(self):
        iso = IsoWrapper(logger=self.compose._logger)
        symlink_isos_to = self.compose.conf.get("symlink_isos_to", None)

        commands = []
        for variant in self.compose.get_variants(types=["variant", "layered-product", "optional"], recursive=True):
            for arch in variant.arches + ["src"]:
                volid = get_volid(self.compose, arch, variant)
                os_tree = self.compose.paths.compose.os_tree(arch, variant)

                iso_dir = self.compose.paths.compose.iso_dir(arch, variant, symlink_to=symlink_isos_to)
                if not iso_dir:
                    continue

                found = False
                for root, dirs, files in os.walk(os_tree):
                    if found:
                        break
                    for fn in files:
                        if fn.endswith(".rpm"):
                            found = True
                            break

                if not found:
                    self.compose.log_warning("No RPMs found for %s.%s, skipping ISO" % (variant, arch))
                    continue

                split_iso_data = split_iso(self.compose, arch, variant)
                disc_count = len(split_iso_data)

                for disc_num, iso_data in enumerate(split_iso_data):
                    disc_num += 1

                    # XXX: hardcoded disc_type
                    iso_path = self.compose.paths.compose.iso_path(arch, variant, disc_type="dvd", disc_num=disc_num, symlink_to=symlink_isos_to)
                    relative_iso_path = self.compose.paths.compose.iso_path(arch, variant, disc_type="dvd", disc_num=disc_num, create_dir=False, relative=True)
                    if os.path.isfile(iso_path):
                        self.compose.log_warning("Skipping mkisofs, image already exists: %s" % iso_path)
                        continue
                    iso_name = os.path.basename(iso_path)

                    graft_points = prepare_iso(self.compose, arch, variant, disc_num=disc_num, disc_count=disc_count, split_iso_data=iso_data)

                    bootable = self.compose.conf.get("bootable", False)
                    if arch == "src":
                        bootable = False
                    if variant.type != "variant":
                        bootable = False

                    cmd = {
                        "arch": arch,
                        "variant": variant,
                        "iso_path": iso_path,
                        "relative_iso_path": relative_iso_path,
                        "build_arch": arch,
                        "bootable": bootable,
                        "cmd": [],
                        "label": "",  # currently not used
                        "disc_num": disc_num,
                        "disc_count": disc_count,
                    }

                    if os.path.islink(iso_dir):
                        cmd["mount"] = os.path.abspath(os.path.join(os.path.dirname(iso_dir), os.readlink(iso_dir)))

                    chdir_cmd = "cd %s" % pipes.quote(iso_dir)
                    cmd["cmd"].append(chdir_cmd)

                    mkisofs_kwargs = {}

                    if bootable:
                        buildinstall_method = self.compose.conf["buildinstall_method"]
                        if buildinstall_method == "lorax":
                            # TODO: $arch instead of ppc
                            mkisofs_kwargs["boot_args"] = iso.get_boot_options(arch, "/usr/share/lorax/config_files/ppc")
                        elif buildinstall_method == "buildinstall":
                            mkisofs_kwargs["boot_args"] = iso.get_boot_options(arch, "/usr/lib/anaconda-runtime/boot")

                    # ppc(64) doesn't seem to support utf-8
                    if arch in ("ppc", "ppc64", "ppc64le"):
                        mkisofs_kwargs["input_charset"] = None

                    mkisofs_cmd = iso.get_mkisofs_cmd(iso_name, None, volid=volid, exclude=["./lost+found"], graft_points=graft_points, **mkisofs_kwargs)
                    mkisofs_cmd = " ".join([pipes.quote(i) for i in mkisofs_cmd])
                    cmd["cmd"].append(mkisofs_cmd)

                    if bootable and arch == "x86_64":
                        isohybrid_cmd = "isohybrid --uefi %s" % pipes.quote(iso_name)
                        cmd["cmd"].append(isohybrid_cmd)
                    elif bootable and arch == "i386":
                        isohybrid_cmd = "isohybrid %s" % pipes.quote(iso_name)
                        cmd["cmd"].append(isohybrid_cmd)

                    # implant MD5SUM to iso
                    isomd5sum_cmd = iso.get_implantisomd5_cmd(iso_name, self.compose.supported)
                    isomd5sum_cmd = " ".join([pipes.quote(i) for i in isomd5sum_cmd])
                    cmd["cmd"].append(isomd5sum_cmd)

                    # compute md5sum, sha1sum, sha256sum
                    cmd["cmd"].extend(iso.get_checksum_cmds(iso_name))

                    # create iso manifest
                    cmd["cmd"].append(iso.get_manifest_cmd(iso_name))

                    # create jigdo
                    jigdo = JigdoWrapper(logger=self.compose._logger)
                    jigdo_dir = self.compose.paths.compose.jigdo_dir(arch, variant)
                    files = [
                        {
                            "path": os_tree,
                            "label": None,
                            "uri": None,
                        }
                    ]
                    jigdo_cmd = jigdo.get_jigdo_cmd(iso_path, files, output_dir=jigdo_dir, no_servers=True, report="noprogress")
                    jigdo_cmd = " ".join([pipes.quote(i) for i in jigdo_cmd])
                    cmd["cmd"].append(jigdo_cmd)

                    cmd["cmd"] = " && ".join(cmd["cmd"])
                    commands.append(cmd)

        for cmd in commands:
            self.pool.add(CreateIsoThread(self.pool))
            self.pool.queue_put((self.compose, cmd))

        self.pool.start()

    def stop(self, *args, **kwargs):
        PhaseBase.stop(self, *args, **kwargs)
        if self.skip():
            return


class CreateIsoThread(WorkerThread):
    def fail(self, compose, cmd):
        compose.log_error("CreateISO failed, removing ISO: %s" % cmd["iso_path"])
        try:
            # remove incomplete ISO
            os.unlink(cmd["iso_path"])
            # TODO: remove jigdo & template & checksums
        except OSError:
            pass

    def process(self, item, num):
        compose, cmd = item

        mounts = [compose.topdir]
        if "mount" in cmd:
            mounts.append(cmd["mount"])

        runroot = compose.conf.get("runroot", False)
        bootable = compose.conf.get("bootable", False)
        log_file = compose.paths.log.log_file(cmd["arch"], "createiso-%s" % os.path.basename(cmd["iso_path"]))

        msg = "Creating ISO (arch: %s, variant: %s): %s" % (cmd["arch"], cmd["variant"], os.path.basename(cmd["iso_path"]))
        self.pool.log_info("[BEGIN] %s" % msg)

        if runroot:
            # run in a koji build root
            packages = ["coreutils", "genisoimage", "isomd5sum", "jigdo", "strace", "lsof"]
            if bootable:
                buildinstall_method = compose.conf["buildinstall_method"]
                if buildinstall_method == "lorax":
                    packages += ["lorax"]
                elif buildinstall_method == "buildinstall":
                    packages += ["anaconda"]

            runroot_channel = compose.conf.get("runroot_channel", None)
            runroot_tag = compose.conf["runroot_tag"]

            # get info about build arches in buildroot_tag
            koji_url = compose.conf["pkgset_koji_url"]
            koji_proxy = koji.ClientSession(koji_url)
            tag_info = koji_proxy.getTag(runroot_tag)
            tag_arches = tag_info["arches"].split(" ")

            if not cmd["bootable"]:
                if "x86_64" in tag_arches:
                    # assign non-bootable images to x86_64 if possible
                    cmd["build_arch"] = "x86_64"
                elif cmd["build_arch"] == "src":
                    # pick random arch from available runroot tag arches
                    cmd["build_arch"] = random.choice(tag_arches)

            koji_wrapper = KojiWrapper(compose.conf["koji_profile"])
            koji_cmd = koji_wrapper.get_runroot_cmd(runroot_tag, cmd["build_arch"], cmd["cmd"], channel=runroot_channel, use_shell=True, task_id=True, packages=packages, mounts=mounts)

            # avoid race conditions?
            # Kerberos authentication failed: Permission denied in replay cache code (-1765328215)
            time.sleep(num * 3)

            output = koji_wrapper.run_runroot_cmd(koji_cmd, log_file=log_file)
            if output["retcode"] != 0:
                self.fail(compose, cmd)
                raise RuntimeError("Runroot task failed: %s. See %s for more details." % (output["task_id"], log_file))

        else:
            # run locally
            try:
                run(cmd["cmd"], show_cmd=True, logfile=log_file)
            except:
                self.fail(compose, cmd)
                raise

        iso = IsoWrapper()

        img = Image(compose.im)
        img.path = cmd["relative_iso_path"]
        img.mtime = int(os.stat(cmd["iso_path"]).st_mtime)
        img.size = os.path.getsize(cmd["iso_path"])
        img.arch = cmd["arch"]
        # XXX: HARDCODED
        img.type = "dvd"
        img.format = "iso"
        img.disc_number = cmd["disc_num"]
        img.disc_count = cmd["disc_count"]
        for checksum_type in ("md5", "sha1", "sha256"):
            checksum_path = cmd["iso_path"] + ".%sSUM" % checksum_type.upper()
            checksum_value = None
            if os.path.isfile(checksum_path):
                checksum_value, iso_name = read_checksum_file(checksum_path)[0]
                if iso_name != os.path.basename(img.path):
                    # a bit paranoind check - this should never happen
                    raise ValueError("Image name doesn't match checksum: %s" % checksum_path)
            img.add_checksum(compose.paths.compose.topdir(), checksum_type=checksum_type, checksum_value=checksum_value)
        img.bootable = cmd["bootable"]
        img.implant_md5 = iso.get_implanted_md5(cmd["iso_path"])
        try:
            img.volume_id = iso.get_volume_id(cmd["iso_path"])
        except RuntimeError:
            pass
        compose.im.add(cmd["arch"], cmd["variant"].uid, img)
        # TODO: supported_iso_bit
        # add: boot.iso

        self.pool.log_info("[DONE ] %s" % msg)


def split_iso(compose, arch, variant):
    # XXX: hardcoded
    media_size = 4700000000
    media_reserve = 10 * 1024 * 1024

    ms = MediaSplitter(str(media_size - media_reserve))

    os_tree = compose.paths.compose.os_tree(arch, variant)
    extra_files_dir = compose.paths.work.extra_files_dir(arch, variant)

#    ti_path = os.path.join(os_tree, ".treeinfo")
#    ti = productmd.treeinfo.TreeInfo()
#    ti.load(ti_path)

    # scan extra files to mark them "sticky" -> they'll be on all media after split
    extra_files = set()
    for root, dirs, files in os.walk(extra_files_dir):
        for fn in files:
            path = os.path.join(root, fn)
            rel_path = relative_path(path, extra_files_dir.rstrip("/") + "/")
            extra_files.add(rel_path)

    packages = []
    all_files = []
    all_files_ignore = []

    ti = productmd.treeinfo.TreeInfo()
    ti.load(os.path.join(os_tree, ".treeinfo"))
    boot_iso_rpath = ti.images.images.get(arch, {}).get("boot.iso", None)
    if boot_iso_rpath:
        all_files_ignore.append(boot_iso_rpath)
    compose.log_debug("split_iso all_files_ignore = %s" % ", ".join(all_files_ignore))

    for root, dirs, files in os.walk(os_tree):
        for dn in dirs[:]:
            repo_dir = os.path.join(root, dn)
            if repo_dir == os.path.join(compose.paths.compose.repository(arch, variant), "repodata"):
                dirs.remove(dn)

        for fn in files:
            path = os.path.join(root, fn)
            rel_path = relative_path(path, os_tree.rstrip("/") + "/")
            sticky = rel_path in extra_files
            if rel_path in all_files_ignore:
                compose.log_info("split_iso: Skipping %s" % rel_path)
                continue
            if root == compose.paths.compose.packages(arch, variant):
                packages.append((path, os.path.getsize(path), sticky))
            else:
                all_files.append((path, os.path.getsize(path), sticky))

    for path, size, sticky in all_files + packages:
        ms.add_file(path, size, sticky)

    return ms.split()


def prepare_iso(compose, arch, variant, disc_num=1, disc_count=None, split_iso_data=None):
    tree_dir = compose.paths.compose.os_tree(arch, variant)
    iso_dir = compose.paths.work.iso_dir(arch, variant, disc_num=disc_num)

    # modify treeinfo
    ti_path = os.path.join(tree_dir, ".treeinfo")
    ti = productmd.treeinfo.TreeInfo()
    ti.load(ti_path)
    ti.media.totaldiscs = disc_count or 1
    ti.media.discnum = disc_num

    # remove boot.iso from all sections
    paths = set()
    for platform in ti.images.images:
        if "boot.iso" in ti.images.images[platform]:
            paths.add(ti.images.images[platform].pop("boot.iso"))

    # remove boot.iso from checksums
    for i in paths:
        if i in ti.checksums.checksums.keys():
            del ti.checksums.checksums[i]

    # make a copy of isolinux/isolinux.bin, images/boot.img - they get modified when mkisofs is called
    for i in ("isolinux/isolinux.bin", "images/boot.img"):
        src_path = os.path.join(tree_dir, i)
        dst_path = os.path.join(iso_dir, i)
        if os.path.exists(src_path):
            makedirs(os.path.dirname(dst_path))
            shutil.copy2(src_path, dst_path)

    if disc_count > 1:
        # remove repodata/repomd.xml from checksums, create a new one later
        if "repodata/repomd.xml" in ti.checksums.checksums:
            del ti.checksums.checksums["repodata/repomd.xml"]

        # rebuild repodata
        createrepo_c = compose.conf.get("createrepo_c", False)
        createrepo_checksum = compose.conf.get("createrepo_checksum", None)
        repo = CreaterepoWrapper(createrepo_c=createrepo_c)

        file_list = "%s-file-list" % iso_dir
        packages_dir = compose.paths.compose.packages(arch, variant)
        file_list_content = []
        for i in split_iso_data["files"]:
            if not i.endswith(".rpm"):
                continue
            if not i.startswith(packages_dir):
                continue
            rel_path = relative_path(i, tree_dir.rstrip("/") + "/")
            file_list_content.append(rel_path)

        if file_list_content:
            # write modified repodata only if there are packages available
            run("cp -a %s/repodata %s/" % (pipes.quote(tree_dir), pipes.quote(iso_dir)))
            open(file_list, "w").write("\n".join(file_list_content))
            cmd = repo.get_createrepo_cmd(tree_dir, update=True, database=True, skip_stat=True, pkglist=file_list, outputdir=iso_dir, workers=3, checksum=createrepo_checksum)
            run(cmd)
            # add repodata/repomd.xml back to checksums
            ti.checksums.add(iso_dir, "repodata/repomd.xml")

    new_ti_path = os.path.join(iso_dir, ".treeinfo")
    ti.dump(new_ti_path)

    # modify discinfo
    di_path = os.path.join(tree_dir, ".discinfo")
    data = read_discinfo(di_path)
    data["disc_numbers"] = [disc_num]
    new_di_path = os.path.join(iso_dir, ".discinfo")
    write_discinfo(new_di_path, **data)

    i = IsoWrapper()
    if not disc_count or disc_count == 1:
        data = i.get_graft_points([tree_dir, iso_dir])
    else:
        data = i.get_graft_points([i._paths_from_list(tree_dir, split_iso_data["files"]), iso_dir])

    # TODO: /content /graft-points
    gp = "%s-graft-points" % iso_dir
    i.write_graft_points(gp, data, exclude=["*/lost+found", "*/boot.iso"])
    return gp
