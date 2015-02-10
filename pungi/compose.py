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
    "Compose",
)


import errno
import os
import time
import tempfile
import shutil

import kobo.log
from productmd import ComposeInfo, ImageManifest

from pypungi.wrappers.variants import VariantsXmlParser
from pypungi.paths import Paths
from pypungi.wrappers.scm import get_file_from_scm
from pypungi.util import makedirs
from pypungi.metadata import compose_to_composeinfo


def get_compose_dir(topdir, conf, compose_type="production", compose_date=None, compose_respin=None, compose_label=None, already_exists_callbacks=None):
    topdir = os.path.abspath(topdir)
    already_exists_callbacks = already_exists_callbacks or []

    # create an incomplete ComposeInfo to generate compose ID
    ci = ComposeInfo()
    ci.product.name = conf["product_name"]
    ci.product.short = conf["product_short"]
    ci.product.version = conf["product_version"]
    ci.product.is_layered = bool(conf.get("product_is_layered", False))
    if ci.product.is_layered:
        ci.base_product.name = conf["base_product_name"]
        ci.base_product.short = conf["base_product_short"]
        ci.base_product.version = conf["base_product_version"]

    ci.compose.label = compose_label
    ci.compose.type = compose_type
    ci.compose.date = compose_date or time.strftime("%Y%m%d", time.localtime())
    ci.compose.respin = compose_respin or 0

    # HACK - add topdir for callbacks
    ci.topdir = topdir

    while 1:
        ci.compose.id = ci.create_compose_id()

        compose_dir = os.path.join(topdir, ci.compose.id)

        exists = False
        # TODO: callbacks to determine if a composeid was already used
        # for callback in already_exists_callbacks:
        #     if callback(data):
        #         exists = True
        #         break

        # already_exists_callbacks fallback: does target compose_dir exist?
        if not exists:
            try:
                os.makedirs(compose_dir)
            except OSError as ex:
                if ex.errno == errno.EEXIST:
                    exists = True
                else:
                    raise

        if exists:
            ci.compose.respin += 1
            continue
        break

    open(os.path.join(compose_dir, "COMPOSE_ID"), "w").write(ci.compose.id)
    work_dir = os.path.join(compose_dir, "work", "global")
    makedirs(work_dir)
    ci.dump(os.path.join(work_dir, "composeinfo-base.json"))
    return compose_dir


class Compose(kobo.log.LoggingBase):
    def __init__(self, conf, topdir, debug=False, skip_phases=None, just_phases=None, old_composes=None, koji_event=None, supported=False, logger=None):
        kobo.log.LoggingBase.__init__(self, logger)
        # TODO: check if minimal conf values are set
        self.conf = conf
        self.variants = {}
        self.topdir = os.path.abspath(topdir)
        self.skip_phases = skip_phases or []
        self.just_phases = just_phases or []
        self.old_composes = old_composes or []
        self.koji_event = koji_event

        # intentionally upper-case (visible in the code)
        self.DEBUG = debug

        # path definitions
        self.paths = Paths(self)

        # to provide compose_id, compose_date and compose_respin
        self.ci_base = ComposeInfo()
        self.ci_base.load(os.path.join(self.paths.work.topdir(arch="global"), "composeinfo-base.json"))

        self.supported = supported
        if self.compose_label and self.compose_label.split("-")[0] == "RC":
            self.log_info("Automatically setting 'supported' flag for a Release Candidate (%s) compose." % self.compose_label)
            self.supported = True

        self.im = ImageManifest()
        if self.DEBUG:
            try:
                self.im.load(self.paths.compose.metadata("images.json"))
            except RuntimeError:
                pass
        self.im.compose.id = self.compose_id
        self.im.compose.type = self.compose_type
        self.im.compose.date = self.compose_date
        self.im.compose.respin = self.compose_respin
        self.im.metadata_path = self.paths.compose.metadata()

    get_compose_dir = staticmethod(get_compose_dir)

    def __getitem__(self, name):
        return self.variants[name]

    @property
    def compose_id(self):
        return self.ci_base.compose.id

    @property
    def compose_date(self):
        return self.ci_base.compose.date

    @property
    def compose_respin(self):
        return self.ci_base.compose.respin

    @property
    def compose_type(self):
        return self.ci_base.compose.type

    @property
    def compose_type_suffix(self):
        return self.ci_base.compose.type_suffix

    @property
    def compose_label(self):
        return self.ci_base.compose.label

    @property
    def has_comps(self):
        return bool(self.conf.get("comps_file", False))

    @property
    def config_dir(self):
        return os.path.dirname(self.conf._open_file or "")

    def read_variants(self):
        # TODO: move to phases/init ?
        variants_file = self.paths.work.variants_file(arch="global")
        msg = "Writing variants file: %s" % variants_file

        if self.DEBUG and os.path.isfile(variants_file):
            self.log_warning("[SKIP ] %s" % msg)
        else:
            scm_dict = self.conf["variants_file"]
            if isinstance(scm_dict, dict):
                file_name = os.path.basename(scm_dict["file"])
                if scm_dict["scm"] == "file":
                    scm_dict["file"] = os.path.join(self.config_dir, os.path.basename(scm_dict["file"]))
            else:
                file_name = os.path.basename(scm_dict)
                scm_dict = os.path.join(self.config_dir, os.path.basename(scm_dict))

            self.log_debug(msg)
            tmp_dir = tempfile.mkdtemp(prefix="variants_file_")
            get_file_from_scm(scm_dict, tmp_dir, logger=self._logger)
            shutil.copy2(os.path.join(tmp_dir, file_name), variants_file)
            shutil.rmtree(tmp_dir)

        file_obj = open(variants_file, "r")
        tree_arches = self.conf.get("tree_arches", None)
        self.variants = VariantsXmlParser(file_obj, tree_arches).parse()

        # populate ci_base with variants - needed for layered-products (compose_id)
        self.ci_base = compose_to_composeinfo(self)

    def get_variants(self, types=None, arch=None, recursive=False):
        result = []
        types = types or ["variant", "optional", "addon", "layered-product"]
        for i in self.variants.values():
            if i.type in types:
                if arch and arch not in i.arches:
                    continue
                result.append(i)
            result.extend(i.get_variants(types=types, arch=arch, recursive=recursive))
        return sorted(set(result))

    def get_arches(self):
        result = set()
        tree_arches = self.conf.get("tree_arches", None)
        for variant in self.get_variants():
            for arch in variant.arches:
                if tree_arches:
                    if arch in tree_arches:
                        result.add(arch)
                else:
                    result.add(arch)
        return sorted(result)

    def write_status(self, stat_msg):
        if stat_msg not in ("STARTED", "FINISHED", "DOOMED"):
            self.log_warning("Writing nonstandard compose status: %s" % stat_msg)
        old_status = self.get_status()
        if stat_msg == old_status:
            return
        if old_status == "FINISHED":
            msg = "Could not modify a FINISHED compose: %s" % self.topdir
            self.log_error(msg)
            raise RuntimeError(msg)
        open(os.path.join(self.topdir, "STATUS"), "w").write(stat_msg + "\n")

    def get_status(self):
        path = os.path.join(self.topdir, "STATUS")
        if not os.path.isfile(path):
            return
        return open(path, "r").read().strip()
