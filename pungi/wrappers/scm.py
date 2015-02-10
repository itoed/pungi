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
import tempfile
import shutil
import pipes
import glob
import time

import kobo.log
from kobo.shortcuts import run, force_list
from pypungi.util import explode_rpm_package, makedirs


class ScmBase(kobo.log.LoggingBase):
    def __init__(self, logger=None):
        kobo.log.LoggingBase.__init__(self, logger=logger)

    def _create_temp_dir(self, tmp_dir=None):
        if tmp_dir is not None:
            makedirs(tmp_dir)
        return tempfile.mkdtemp(prefix="cvswrapper_", dir=tmp_dir)

    def _delete_temp_dir(self, tmp_dir):
        self.log_debug("Removing %s" % tmp_dir)
        try:
            shutil.rmtree(tmp_dir)
        except OSError as ex:
            self.log_warning("Error removing %s: %s" % (tmp_dir, ex))

    def export_file(self, scm_root, scm_file, target_dir, scm_branch=None, tmp_dir=None, log_file=None):
        raise NotImplemented

    def retry_run(self, cmd, retries=5, timeout=60, **kwargs):
        """
        @param cmd - cmd passed to kobo.shortcuts.run()
        @param retries=5 - attempt to execute n times
        @param timeout=60 - seconds before next try
        @param **kwargs - args passed to kobo.shortcuts.run()
        """

        for n in range(1, retries + 1):
            try:
                self.log_debug("Retrying execution %s/%s of '%s'" % (n, retries, cmd))
                return run(cmd, **kwargs)
            except RuntimeError as ex:
                if n == retries:
                    raise ex
                self.log_debug("Waiting %s seconds to retry execution of '%s'" % (timeout, cmd))
                time.sleep(timeout)

        raise RuntimeError("Something went wrong during execution of '%s'" % cmd)


class FileWrapper(ScmBase):
    def export_dir(self, scm_root, scm_dir, target_dir, scm_branch=None, tmp_dir=None, log_file=None):
        if scm_root:
            raise ValueError("FileWrapper: 'scm_root' should be empty.")
        dirs = glob.glob(scm_dir)
        for i in dirs:
            run("cp -a %s/* %s/" % (pipes.quote(i), pipes.quote(target_dir)))

    def export_file(self, scm_root, scm_file, target_dir, scm_branch=None, tmp_dir=None, log_file=None):
        if scm_root:
            raise ValueError("FileWrapper: 'scm_root' should be empty.")
        files = glob.glob(scm_file)
        for i in files:
            target_path = os.path.join(target_dir, os.path.basename(i))
            shutil.copy2(i, target_path)


class CvsWrapper(ScmBase):
    def export_dir(self, scm_root, scm_dir, target_dir, scm_branch=None, tmp_dir=None, log_file=None):
        scm_dir = scm_dir.lstrip("/")
        scm_branch = scm_branch or "HEAD"
        tmp_dir = self._create_temp_dir(tmp_dir=tmp_dir)

        self.log_debug("Exporting directory %s from CVS %s (branch %s)..." % (scm_dir, scm_root, scm_branch))
        self.retry_run(["/usr/bin/cvs", "-q", "-d", scm_root, "export", "-r", scm_branch, scm_dir], workdir=tmp_dir, show_cmd=True, logfile=log_file)
        # TODO: hidden files
        run("cp -a %s/* %s/" % (pipes.quote(os.path.join(tmp_dir, scm_dir)), pipes.quote(target_dir)))
        self._delete_temp_dir(tmp_dir)

    def export_file(self, scm_root, scm_file, target_dir, scm_branch=None, tmp_dir=None, log_file=None):
        scm_file = scm_file.lstrip("/")
        scm_branch = scm_branch or "HEAD"
        tmp_dir = self._create_temp_dir(tmp_dir=tmp_dir)

        target_path = os.path.join(target_dir, os.path.basename(scm_file))
        self.log_debug("Exporting file %s from CVS %s (branch %s)..." % (scm_file, scm_root, scm_branch))
        self.retry_run(["/usr/bin/cvs", "-q", "-d", scm_root, "export", "-r", scm_branch, scm_file], workdir=tmp_dir, show_cmd=True, logfile=log_file)

        makedirs(target_dir)
        shutil.copy2(os.path.join(tmp_dir, scm_file), target_path)
        self._delete_temp_dir(tmp_dir)


class GitWrapper(ScmBase):
    def export_dir(self, scm_root, scm_dir, target_dir, scm_branch=None, tmp_dir=None, log_file=None):
        scm_dir = scm_dir.lstrip("/")
        scm_branch = scm_branch or "master"
        tmp_dir = self._create_temp_dir(tmp_dir=tmp_dir)

        if "://" not in scm_root:
            scm_root = "file://%s" % scm_root

        self.log_debug("Exporting directory %s from git %s (branch %s)..." % (scm_dir, scm_root, scm_branch))
        cmd = "/usr/bin/git archive --remote=%s %s %s | tar xf -" % (pipes.quote(scm_root), pipes.quote(scm_branch), pipes.quote(scm_dir))
        self.retry_run(cmd, workdir=tmp_dir, show_cmd=True, logfile=log_file)

        run("cp -a %s/* %s/" % (pipes.quote(os.path.join(tmp_dir, scm_dir)), pipes.quote(target_dir)))
        self._delete_temp_dir(tmp_dir)

    def export_file(self, scm_root, scm_file, target_dir, scm_branch=None, tmp_dir=None, log_file=None):
        scm_file = scm_file.lstrip("/")
        scm_branch = scm_branch or "master"
        tmp_dir = self._create_temp_dir(tmp_dir=tmp_dir)

        target_path = os.path.join(target_dir, os.path.basename(scm_file))

        if "://" not in scm_root:
            scm_root = "file://%s" % scm_root

        self.log_debug("Exporting file %s from git %s (branch %s)..." % (scm_file, scm_root, scm_branch))
        cmd = "/usr/bin/git archive --remote=%s %s %s | tar xf -" % (pipes.quote(scm_root), pipes.quote(scm_branch), pipes.quote(scm_file))
        self.retry_run(cmd, workdir=tmp_dir, show_cmd=True, logfile=log_file)

        makedirs(target_dir)
        shutil.copy2(os.path.join(tmp_dir, scm_file), target_path)
        self._delete_temp_dir(tmp_dir)


class RpmScmWrapper(ScmBase):
    def export_dir(self, scm_root, scm_dir, target_dir, scm_branch=None, tmp_dir=None, log_file=None):
        # if scm_root is a list, recursively process all RPMs
        if isinstance(scm_root, list):
            for i in scm_root:
                self.export_dir(i, scm_dir, target_dir, scm_branch, tmp_dir, log_file)
            return

        # if scm_root is a glob, recursively process all RPMs
        rpms = glob.glob(scm_root)
        if len(rpms) > 1 or (rpms and rpms[0] != scm_root):
            for i in rpms:
                self.export_dir(i, scm_dir, target_dir, scm_branch, tmp_dir, log_file)
            return

        scm_dir = scm_dir.lstrip("/")
        tmp_dir = self._create_temp_dir(tmp_dir=tmp_dir)
        self.log_debug("Extracting directory %s from RPM package %s..." % (scm_dir, scm_root))
        explode_rpm_package(scm_root, tmp_dir)

        makedirs(target_dir)
        # "dir" includes the whole directory while "dir/" includes it's content
        if scm_dir.endswith("/"):
            run("cp -a %s/* %s/" % (pipes.quote(os.path.join(tmp_dir, scm_dir)), pipes.quote(target_dir)))
        else:
            run("cp -a %s %s/" % (pipes.quote(os.path.join(tmp_dir, scm_dir)), pipes.quote(target_dir)))
        self._delete_temp_dir(tmp_dir)

    def export_file(self, scm_root, scm_file, target_dir, scm_branch=None, tmp_dir=None, log_file=None):
        # if scm_root is a list, recursively process all RPMs
        if isinstance(scm_root, list):
            for i in scm_root:
                self.export_file(i, scm_file, target_dir, scm_branch, tmp_dir, log_file)
            return

        # if scm_root is a glob, recursively process all RPMs
        rpms = glob.glob(scm_root)
        if len(rpms) > 1 or (rpms and rpms[0] != scm_root):
            for i in rpms:
                self.export_file(i, scm_file, target_dir, scm_branch, tmp_dir, log_file)
            return

        scm_file = scm_file.lstrip("/")
        tmp_dir = self._create_temp_dir(tmp_dir=tmp_dir)

        self.log_debug("Exporting file %s from RPM file %s..." % (scm_file, scm_root))
        explode_rpm_package(scm_root, tmp_dir)

        makedirs(target_dir)
        for src in glob.glob(os.path.join(tmp_dir, scm_file)):
            dst = os.path.join(target_dir, os.path.basename(src))
            shutil.copy2(src, dst)
        self._delete_temp_dir(tmp_dir)


def get_file_from_scm(scm_dict, target_path, logger=None):
    if isinstance(scm_dict, str):
        scm_type = "file"
        scm_repo = None
        scm_file = os.path.abspath(scm_dict)
        scm_branch = None
    else:
        scm_type = scm_dict["scm"]
        scm_repo = scm_dict["repo"]
        scm_file = scm_dict["file"]
        scm_branch = scm_dict.get("branch", None)

    if scm_type == "file":
        scm = FileWrapper(logger=logger)
    elif scm_type == "cvs":
        scm = CvsWrapper(logger=logger)
    elif scm_type == "git":
        scm = GitWrapper(logger=logger)
    elif scm_type == "rpm":
        scm = RpmScmWrapper(logger=logger)
    else:
        raise ValueError("Unknown SCM type: %s" % scm_type)

    for i in force_list(scm_file):
        tmp_dir = tempfile.mkdtemp(prefix="scm_checkout_")
        scm.export_file(scm_repo, i, scm_branch=scm_branch, target_dir=tmp_dir)
        makedirs(target_path)
        run("cp -a %s/* %s/" % (pipes.quote(tmp_dir), pipes.quote(target_path)))
        shutil.rmtree(tmp_dir)


def get_dir_from_scm(scm_dict, target_path, logger=None):
    if isinstance(scm_dict, str):
        scm_type = "file"
        scm_repo = None
        scm_dir = os.path.abspath(scm_dict)
        scm_branch = None
    else:
        scm_type = scm_dict["scm"]
        scm_repo = scm_dict.get("repo", None)
        scm_dir = scm_dict["dir"]
        scm_branch = scm_dict.get("branch", None)

    if scm_type == "file":
        scm = FileWrapper(logger=logger)
    elif scm_type == "cvs":
        scm = CvsWrapper(logger=logger)
    elif scm_type == "git":
        scm = GitWrapper(logger=logger)
    elif scm_type == "rpm":
        scm = RpmScmWrapper(logger=logger)
    else:
        raise ValueError("Unknown SCM type: %s" % scm_type)

    tmp_dir = tempfile.mkdtemp(prefix="scm_checkout_")
    scm.export_dir(scm_repo, scm_dir, scm_branch=scm_branch, target_dir=tmp_dir)
    # TODO: hidden files
    makedirs(target_path)
    run("cp -a %s/* %s/" % (pipes.quote(tmp_dir), pipes.quote(target_path)))
    shutil.rmtree(tmp_dir)
