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
import pipes
import re

import koji
import rpmUtils.arch
from kobo.shortcuts import run


class KojiWrapper(object):
    def __init__(self, profile):
        self.profile = profile
        # assumption: profile name equals executable name (it's a symlink -> koji)
        self.executable = self.profile.replace("_", "-")
        self.koji_module = __import__(self.profile)

    def get_runroot_cmd(self, target, arch, command, quiet=False, use_shell=True, channel=None, packages=None, mounts=None, weight=None, task_id=True):
        cmd = [self.executable, "runroot"]

        if quiet:
            cmd.append("--quiet")

        if use_shell:
            cmd.append("--use-shell")

        if task_id:
            cmd.append("--task-id")

        if channel:
            cmd.append("--channel-override=%s" % channel)
        else:
            cmd.append("--channel-override=runroot-local")

        if weight:
            cmd.append("--weight=%s" % int(weight))

        if packages:
            for package in packages:
                cmd.append("--package=%s" % package)

        if mounts:
            for mount in mounts:
                # directories are *not* created here
                cmd.append("--mount=%s" % mount)

        # IMPORTANT: all --opts have to be provided *before* args

        cmd.append(target)

        # i686 -> i386 etc.
        arch = rpmUtils.arch.getBaseArch(arch)
        cmd.append(arch)

        if isinstance(command, list):
            command = " ".join([pipes.quote(i) for i in command])

        # HACK: remove rpmdb and yum cache
        command = "rm -f /var/lib/rpm/__db*; rm -rf /var/cache/yum/*; set -x; " + command
        cmd.append(command)

        return cmd

    def run_runroot_cmd(self, command, log_file=None):
        # runroot is blocking -> you probably want to run it in a thread

        task_id = None
        retcode, output = run(command, can_fail=True, logfile=log_file)
        if "--task-id" in command:
            task_id = int(output.splitlines()[0])
            output_ends_with_eol = output.endswith("\n")
            output = "\n".join(output.splitlines()[1:])
            if output_ends_with_eol:
                output += "\n"

        result = {
            "retcode": retcode,
            "output": output,
            "task_id": task_id,
        }
        return result

    def get_create_image_cmd(self, name, version, target, arch, ks_file, repos, image_type="live", image_format=None, release=None, wait=True, archive=False):
        # Usage: koji spin-livecd [options] <name> <version> <target> <arch> <kickstart-file>
        # Usage: koji spin-appliance [options] <name> <version> <target> <arch> <kickstart-file>
        # Examples:
        #  * name: RHEL-7.0
        #  * name: Satellite-6.0.1-RHEL-6
        #  ** -<type>.<arch>
        #  * version: YYYYMMDD[.n|.t].X
        #  * release: 1

        cmd = [self.executable]

        if image_type == "live":
            cmd.append("spin-livecd")
        elif image_type == "appliance":
            cmd.append("spin-appliance")
        else:
            raise ValueError("Invalid image type: %s" % image_type)

        if not archive:
            cmd.append("--scratch")

        cmd.append("--noprogress")

        if wait:
            cmd.append("--wait")
        else:
            cmd.append("--nowait")

        if isinstance(repos, list):
            for repo in repos:
                cmd.append("--repo=%s" % repo)
        else:
            cmd.append("--repo=%s" % repos)

        if image_format:
            if image_type != "appliance":
                raise ValueError("Format can be specified only for appliance images'")
            supported_formats = ["raw", "qcow", "qcow2", "vmx"]
            if image_format not in supported_formats:
                raise ValueError("Format is not supported: %s. Supported formats: %s" % (image_format, " ".join(sorted(supported_formats))))
            cmd.append("--format=%s" % image_format)

        if release is not None:
            cmd.append("--release=%s" % release)

        # IMPORTANT: all --opts have to be provided *before* args
        # Usage: koji spin-livecd [options] <name> <version> <target> <arch> <kickstart-file>

        cmd.append(name)
        cmd.append(version)
        cmd.append(target)

        # i686 -> i386 etc.
        arch = rpmUtils.arch.getBaseArch(arch)
        cmd.append(arch)

        cmd.append(ks_file)

        return cmd

    def run_create_image_cmd(self, command, log_file=None):
        # spin-{livecd,appliance} is blocking by default -> you probably want to run it in a thread

        retcode, output = run(command, can_fail=True, logfile=log_file)

        match = re.search(r"Created task: (\d+)", output)
        if not match:
            raise RuntimeError("Could not find task ID in output")

        result = {
            "retcode": retcode,
            "output": output,
            "task_id": int(match.groups()[0]),
        }
        return result

    def get_image_path(self, task_id):
        result = []
        # XXX: hardcoded URL
        koji_proxy = self.koji_module.ClientSession(self.koji_module.config.server)
        task_info_list = []
        task_info_list.append(koji_proxy.getTaskInfo(task_id, request=True))
        task_info_list.extend(koji_proxy.getTaskChildren(task_id, request=True))

        # scan parent and child tasks for certain methods
        task_info = None
        for i in task_info_list:
            if i["method"] in ("createAppliance", "createLiveCD"):
                task_info = i
                break

        scratch = task_info["request"][-1].get("scratch", False)
        task_result = koji_proxy.getTaskResult(task_info["id"])
        task_result.pop("rpmlist", None)

        if scratch:
            topdir = os.path.join(self.koji_module.pathinfo.work(), self.koji_module.pathinfo.taskrelpath(task_info["id"]))
        else:
            build = koji_proxy.getImageBuild("%(name)s-%(version)s-%(release)s" % task_result)
            build["name"] = task_result["name"]
            build["version"] = task_result["version"]
            build["release"] = task_result["release"]
            build["arch"] = task_result["arch"]
            topdir = self.koji_module.pathinfo.imagebuild(build)
        for i in task_result["files"]:
            result.append(os.path.join(topdir, i))
        return result
