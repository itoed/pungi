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


import tempfile

from kobo.shortcuts import run

from pypungi.wrappers.repoclosure import RepoclosureWrapper
from pypungi.arch import get_valid_arches
from pypungi.phases.base import PhaseBase
from pypungi.phases.gather import get_lookaside_repos
from pypungi.util import rmtree


class TestPhase(PhaseBase):
    name = "test"

    def run(self):
        run_repoclosure(self.compose)


def run_repoclosure(compose):
    repoclosure = RepoclosureWrapper()

    # TODO: Special handling for src packages (use repoclosure param builddeps)

    msg = "Running repoclosure"
    compose.log_info("[BEGIN] %s" % msg)

    # Arch repos
    for arch in compose.get_arches():
        is_multilib = arch in compose.conf["multilib_arches"]
        arches = get_valid_arches(arch, is_multilib)
        repo_id = "repoclosure-%s" % arch
        repo_dir = compose.paths.work.arch_repo(arch=arch)

        lookaside = {}
        if compose.conf.get("product_is_layered", False):
            for i, lookaside_url in enumerate(get_lookaside_repos(compose, arch, None)):
                lookaside["lookaside-%s-%s" % (arch, i)] = lookaside_url

        cmd = repoclosure.get_repoclosure_cmd(repos={repo_id: repo_dir}, lookaside=lookaside, arch=arches)
        # Use temp working directory directory as workaround for
        # https://bugzilla.redhat.com/show_bug.cgi?id=795137
        tmp_dir = tempfile.mkdtemp(prefix="repoclosure_")
        try:
            run(cmd, logfile=compose.paths.log.log_file(arch, "repoclosure"), show_cmd=True, can_fail=True, workdir=tmp_dir)
        finally:
            rmtree(tmp_dir)

    # Variant repos
    all_repos = {}  # to be used as lookaside for the self-hosting check
    all_arches = set()
    for arch in compose.get_arches():
        is_multilib = arch in compose.conf["multilib_arches"]
        arches = get_valid_arches(arch, is_multilib)
        all_arches.update(arches)
        for variant in compose.get_variants(arch=arch):
            lookaside = {}
            if variant.parent:
                repo_id = "repoclosure-%s.%s" % (variant.parent.uid, arch)
                repo_dir = compose.paths.compose.repository(arch=arch, variant=variant.parent)
                lookaside[repo_id] = repo_dir

            repos = {}
            repo_id = "repoclosure-%s.%s" % (variant.uid, arch)
            repo_dir = compose.paths.compose.repository(arch=arch, variant=variant)
            repos[repo_id] = repo_dir

            if compose.conf.get("product_is_layered", False):
                for i, lookaside_url in enumerate(get_lookaside_repos(compose, arch, variant)):
                    lookaside["lookaside-%s.%s-%s" % (variant.uid, arch, i)] = lookaside_url

            cmd = repoclosure.get_repoclosure_cmd(repos=repos, lookaside=lookaside, arch=arches)
            # Use temp working directory directory as workaround for
            # https://bugzilla.redhat.com/show_bug.cgi?id=795137
            tmp_dir = tempfile.mkdtemp(prefix="repoclosure_")
            try:
                run(cmd, logfile=compose.paths.log.log_file(arch, "repoclosure-%s" % variant), show_cmd=True, can_fail=True, workdir=tmp_dir)
            finally:
                rmtree(tmp_dir)

            all_repos.update(repos)
            all_repos.update(lookaside)
            repo_id = "repoclosure-%s.%s" % (variant.uid, "src")
            repo_dir = compose.paths.compose.repository(arch="src", variant=variant)
            all_repos[repo_id] = repo_dir

    # A SRPM can be built on any arch and is always rebuilt before building on the target arch.
    # This means the deps can't be always satisfied within one tree arch.
    # As a workaround, let's run the self-hosting check across all repos.

    # XXX: This doesn't solve a situation, when a noarch package is excluded due to ExcludeArch/ExclusiveArch and it's still required on that arch.
    # In this case, it's an obvious bug in the test.

    # check BuildRequires (self-hosting)
    cmd = repoclosure.get_repoclosure_cmd(repos=all_repos, arch=all_arches, builddeps=True)
    # Use temp working directory directory as workaround for
    # https://bugzilla.redhat.com/show_bug.cgi?id=795137
    tmp_dir = tempfile.mkdtemp(prefix="repoclosure_")
    try:
        run(cmd, logfile=compose.paths.log.log_file("global", "repoclosure-builddeps"), show_cmd=True, can_fail=True, workdir=tmp_dir)
    finally:
        rmtree(tmp_dir)

    compose.log_info("[DONE ] %s" % msg)
