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
import re


PACKAGES_RE = {
    "rpm": re.compile(r"^RPM(\((?P<flags>[^\)]+)\))?: (?:file://)?(?P<path>/?[^ ]+)$"),
    "srpm": re.compile(r"^SRPM(\((?P<flags>[^\)]+)\))?: (?:file://)?(?P<path>/?[^ ]+)$"),
    "debuginfo": re.compile(r"^DEBUGINFO(\((?P<flags>[^\)]+)\))?: (?:file://)?(?P<path>/?[^ ]+)$"),
}


UNRESOLVED_DEPENDENCY_RE = re.compile(r"^.*Unresolvable dependency (.+) in ([^ ]+).*$")


class PungiWrapper(object):

    def write_kickstart(self, ks_path, repos, groups, packages, exclude_packages=None, comps_repo=None, lookaside_repos=None, fulltree_excludes=None, multilib_blacklist=None, multilib_whitelist=None, prepopulate=None):
        groups = groups or []
        exclude_packages = exclude_packages or {}
        lookaside_repos = lookaside_repos or {}
        # repos = {name: url}
        fulltree_excludes = fulltree_excludes or set()
        multilib_blacklist = multilib_blacklist or set()
        multilib_whitelist = multilib_whitelist or set()
        ks_path = os.path.abspath(ks_path)

        ks_dir = os.path.dirname(ks_path)
        try:
            os.makedirs(ks_dir)
        except OSError as ex:
            if ex.errno != errno.EEXIST:
                raise

        kickstart = open(ks_path, "w")

        # repos
        for repo_name, repo_url in repos.items() + lookaside_repos.items():
            if "://" not in repo_url:
                repo_url = "file://" + os.path.abspath(repo_url)
            repo_str = "repo --name=%s --baseurl=%s" % (repo_name, repo_url)
            # TODO: make sure pungi works when there are no comps in repodata
            # XXX: if groups are ignored, langpacks are ignored too
            if comps_repo and repo_name != comps_repo:
                repo_str += " --ignoregroups=true"
            kickstart.write(repo_str + "\n")

        # %packages
        kickstart.write("\n")
        kickstart.write("%packages\n")

        for group in sorted(groups):
            kickstart.write("@%s --optional\n" % group)

        for package in sorted(packages):
            kickstart.write("%s\n" % package)

        for package in sorted(exclude_packages):
            kickstart.write("-%s\n" % package)

        kickstart.write("%end\n")

        # %fulltree-excludes
        if fulltree_excludes:
            kickstart.write("\n")
            kickstart.write("%fulltree-excludes\n")
            for i in sorted(fulltree_excludes):
                kickstart.write("%s\n" % i)
            kickstart.write("%end\n")

        # %multilib-blacklist
        if multilib_blacklist:
            kickstart.write("\n")
            kickstart.write("%multilib-blacklist\n")
            for i in sorted(multilib_blacklist):
                kickstart.write("%s\n" % i)
            kickstart.write("%end\n")

        # %multilib-whitelist
        if multilib_whitelist:
            kickstart.write("\n")
            kickstart.write("%multilib-whitelist\n")
            for i in sorted(multilib_whitelist):
                kickstart.write("%s\n" % i)
            kickstart.write("%end\n")

        # %prepopulate
        if prepopulate:
            kickstart.write("\n")
            kickstart.write("%prepopulate\n")
            for i in sorted(prepopulate):
                kickstart.write("%s\n" % i)
            kickstart.write("%end\n")

        kickstart.close()

    def get_pungi_cmd(self, config, destdir, name, version=None, flavor=None, selfhosting=False, fulltree=False, greedy=None, nodeps=False, nodownload=True, full_archlist=False, arch=None, cache_dir=None, lookaside_repos=None, multilib_methods=None):
        cmd = ["pungi-gather"]

        # Gather stage
        cmd.append("-G")

        # path to a kickstart file
        cmd.append("--config=%s" % config)

        # destdir is optional in Pungi (defaults to current dir), but want it mandatory here
        cmd.append("--destdir=%s" % destdir)

        # name
        cmd.append("--name=%s" % name)

        # version; optional, defaults to datestamp
        if version:
            cmd.append("--ver=%s" % version)

        # rhel variant; optional
        if flavor:
            cmd.append("--flavor=%s" % flavor)

        # turn selfhosting on
        if selfhosting:
            cmd.append("--selfhosting")

        # NPLB
        if fulltree:
            cmd.append("--fulltree")

        greedy = greedy or "none"
        cmd.append("--greedy=%s" % greedy)

        if nodeps:
            cmd.append("--nodeps")

        # don't download packages, just print paths
        if nodownload:
            cmd.append("--nodownload")

        if full_archlist:
            cmd.append("--full-archlist")

        if arch:
            cmd.append("--arch=%s" % arch)

        if multilib_methods:
            for i in multilib_methods:
                cmd.append("--multilib=%s" % i)

        if cache_dir:
            cmd.append("--cachedir=%s" % cache_dir)

        if lookaside_repos:
            for i in lookaside_repos:
                cmd.append("--lookaside-repo=%s" % i)

        return cmd

    def get_packages(self, output):
        global PACKAGES_RE
        result = dict(((i, []) for i in PACKAGES_RE))

        for line in output.splitlines():
            for file_type, pattern in PACKAGES_RE.iteritems():
                match = pattern.match(line)
                if match:
                    item = {}
                    item["path"] = match.groupdict()["path"]
                    flags = match.groupdict()["flags"] or ""
                    flags = sorted([i.strip() for i in flags.split(",") if i.strip()])
                    item["flags"] = flags
                    result[file_type].append(item)
                    break

        # no packages are filtered

        return result

    def get_missing_deps(self, output):
        global UNRESOLVED_DEPENDENCY_RE
        result = {}

        for line in output.splitlines():
            match = UNRESOLVED_DEPENDENCY_RE.match(line)
            if match:
                result.setdefault(match.group(2), set()).add(match.group(1))

        return result
