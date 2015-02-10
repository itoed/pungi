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

from kobo.shortcuts import force_list


class RepoclosureWrapper(object):

    def __init__(self):
        self.actual_id = 0

    def get_repoclosure_cmd(self, config=None, arch=None, basearch=None, builddeps=False,
                            repos=None, lookaside=None, tempcache=False, quiet=False, newest=False, pkg=None, group=None):

        cmd = ["/usr/bin/repoclosure"]

        if config:
            cmd.append("--config=%s" % config)

        if arch:
            for i in force_list(arch):
                cmd.append("--arch=%s" % i)

        if basearch:
            cmd.append("--basearch=%s" % basearch)

        if builddeps:
            cmd.append("--builddeps")

        if tempcache:
            cmd.append("--tempcache")

        if quiet:
            cmd.append("--quiet")

        if newest:
            cmd.append("--newest")

        repos = repos or {}
        for repo_id, repo_path in repos.iteritems():
            if "://" not in repo_path:
                repo_path = "file://%s" % os.path.abspath(repo_path)
            cmd.append("--repofrompath=%s,%s" % (repo_id, repo_path))
            cmd.append("--repoid=%s" % repo_id)

        lookaside = lookaside or {}
        for repo_id, repo_path in lookaside.iteritems():
            if "://" not in repo_path:
                repo_path = "file://%s" % os.path.abspath(repo_path)
            cmd.append("--repofrompath=%s,%s" % (repo_id, repo_path))
            cmd.append("--lookaside=%s" % repo_id)

        if pkg:
            cmd.append("--pkg=%s" % pkg)

        if group:
            cmd.append("--group=%s" % group)

        return cmd
