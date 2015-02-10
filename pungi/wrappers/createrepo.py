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


from kobo.shortcuts import force_list


class CreaterepoWrapper(object):
    def __init__(self, createrepo_c=False):
        if createrepo_c:
            self.createrepo = "createrepo_c"
            self.mergerepo = "mergerepo_c"
        else:
            self.createrepo = "createrepo"
            self.mergerepo = "mergerepo"
        self.modifyrepo = "modifyrepo"

    def get_createrepo_cmd(self, directory, baseurl=None, outputdir=None, excludes=None, pkglist=None, groupfile=None, cachedir=None,
                           update=True, update_md_path=None, skip_stat=False, checkts=False, split=False, pretty=True, database=True, checksum=None,
                           unique_md_filenames=True, distro=None, content=None, repo=None, revision=None, deltas=False, oldpackagedirs=None,
                           num_deltas=None, workers=None):
        # groupfile = /path/to/comps.xml

        cmd = [self.createrepo]

        cmd.append(directory)

        if baseurl:
            cmd.append("--baseurl=%s" % baseurl)

        if outputdir:
            cmd.append("--outputdir=%s" % outputdir)

        if excludes:
            for i in force_list(excludes):
                cmd.append("--excludes=%s" % i)

        if pkglist:
            cmd.append("--pkglist=%s" % pkglist)

        if groupfile:
            cmd.append("--groupfile=%s" % groupfile)

        if cachedir:
            cmd.append("--cachedir=%s" % cachedir)

        if update:
            cmd.append("--update")

        if update_md_path:
            cmd.append("--update-md-path=%s" % update_md_path)

        if skip_stat:
            cmd.append("--skip-stat")

        if checkts:
            cmd.append("--checkts")

        if split:
            cmd.append("--split")

        # HACK:
        if "createrepo_c" in self.createrepo:
            pretty = False
        if pretty:
            cmd.append("--pretty")

        if database:
            cmd.append("--database")
        else:
            cmd.append("--no-database")

        if checksum:
            cmd.append("--checksum=%s" % checksum)

        if unique_md_filenames:
            cmd.append("--unique-md-filenames")
        else:
            cmd.append("--simple-md-filenames")

        if distro:
            for i in force_list(distro):
                cmd.append("--distro=%s" % i)

        if content:
            for i in force_list(content):
                cmd.append("--content=%s" % i)

        if repo:
            for i in force_list(repo):
                cmd.append("--repo=%s" % i)

        if revision:
            cmd.append("--revision=%s" % revision)

        if deltas:
            cmd.append("--deltas=%s" % deltas)

        if oldpackagedirs:
            for i in force_list(oldpackagedirs):
                cmd.append("--oldpackagedirs=%s" % i)

        if num_deltas:
            cmd.append("--num-deltas=%d" % int(num_deltas))

        if workers:
            cmd.append("--workers=%d" % int(workers))

        return cmd

    def get_mergerepo_cmd(self, outputdir, repos, database=True, pkglist=None, nogroups=False, noupdateinfo=None):
        cmd = [self.mergerepo]

        cmd.append("--outputdir=%s" % outputdir)

        for repo in repos:
            if "://" not in repo:
                repo = "file://" + repo
            cmd.append("--repo=%s" % repo)

        if database:
            cmd.append("--database")
        else:
            cmd.append("--nodatabase")

        # XXX: a custom mergerepo hack, not in upstream git repo
        if pkglist:
            cmd.append("--pkglist=%s" % pkglist)

        if nogroups:
            cmd.append("--nogroups")

        if noupdateinfo:
            cmd.append("--noupdateinfo")

        return cmd

    def get_modifyrepo_cmd(self, repo_path, file_path, mdtype=None, compress_type=None, remove=False):
        cmd = [self.modifyrepo]

        cmd.append(file_path)
        cmd.append(repo_path)

        if mdtype:
            cmd.append("--mdtype=%s" % mdtype)

        if remove:
            cmd.append("--remove")

        if compress_type:
            cmd.append("--compress")
            cmd.append("--compress-type=%s" % compress_type)

        return cmd

    def get_repoquery_cmd(self, repos, whatrequires=False, alldeps=False, packages=None, tempcache=True):
        cmd = ["/usr/bin/repoquery"]

        if tempcache:
            cmd.append("--tempcache")

        # a dict is expected: {repo_name: repo_path}
        for repo_name in sorted(repos):
            repo_path = repos[repo_name]
            if "://" not in repo_path:
                repo_path = "file://" + repo_path
            cmd.append("--repofrompath=%s,%s" % (repo_name, repo_path))
            cmd.append("--enablerepo=%s" % repo_name)

        if whatrequires:
            cmd.append("--whatrequires")

        if alldeps:
            cmd.append("--alldeps")

        if packages:
            for pkg in packages:
                cmd.append(pkg)

        return cmd
