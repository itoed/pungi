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
import cPickle as pickle
import json

import koji

import pypungi.phases.pkgset.pkgsets
from pypungi.arch import get_valid_arches

from pypungi.phases.pkgset.common import create_arch_repos, create_global_repo, populate_arch_pkgsets


import pypungi.phases.pkgset.source


class PkgsetSourceKoji(pypungi.phases.pkgset.source.PkgsetSourceBase):
    enabled = True
    config_options = (
        {
            "name": "pkgset_source",
            "expected_types": [str],
            "expected_values": "koji",
        },
        {
            "name": "pkgset_koji_url",
            "expected_types": [str],
        },
        {
            "name": "pkgset_koji_tag",
            "expected_types": [str],
        },
        {
            "name": "pkgset_koji_inherit",
            "expected_types": [bool],
            "optional": True,
        },
        {
            "name": "pkgset_koji_path_prefix",
            "expected_types": [str],
        },
    )

    def __call__(self):
        compose = self.compose
        koji_url = compose.conf["pkgset_koji_url"]
        # koji_tag = compose.conf["pkgset_koji_tag"]
        path_prefix = compose.conf["pkgset_koji_path_prefix"].rstrip("/") + "/"  # must contain trailing '/'

        koji_proxy = koji.ClientSession(koji_url)
        package_sets = get_pkgset_from_koji(self.compose, koji_proxy, path_prefix)
        return (package_sets, path_prefix)


'''
class PkgsetKojiPhase(PhaseBase):
    """PKGSET"""
    name = "pkgset"

    def __init__(self, compose):
        PhaseBase.__init__(self, compose)
        self.package_sets = None
        self.path_prefix = None

    def run(self):
        path_prefix = self.compose.conf["koji_path_prefix"]
        path_prefix = path_prefix.rstrip("/") + "/" # must contain trailing '/'
        koji_url = self.compose.conf["koji_url"]
        koji_proxy = koji.ClientSession(koji_url)
        self.package_sets = get_pkgset_from_koji(self.compose, koji_proxy, path_prefix)
        self.path_prefix = path_prefix
'''


def get_pkgset_from_koji(compose, koji_proxy, path_prefix):
    event_info = get_koji_event_info(compose, koji_proxy)
    tag_info = get_koji_tag_info(compose, koji_proxy)

    pkgset_global = populate_global_pkgset(compose, koji_proxy, path_prefix, tag_info, event_info)
#    get_extra_packages(compose, pkgset_global)
    package_sets = populate_arch_pkgsets(compose, path_prefix, pkgset_global)
    package_sets["global"] = pkgset_global

    create_global_repo(compose, path_prefix)
    for arch in compose.get_arches():
        # TODO: threads? runroot?
        create_arch_repos(compose, arch, path_prefix)

    return package_sets


def populate_global_pkgset(compose, koji_proxy, path_prefix, compose_tag, event_id):
    ALL_ARCHES = set(["src"])
    for arch in compose.get_arches():
        is_multilib = arch in compose.conf["multilib_arches"]
        arches = get_valid_arches(arch, is_multilib)
        ALL_ARCHES.update(arches)

    compose_tag = compose.conf["pkgset_koji_tag"]
    inherit = compose.conf.get("pkgset_koji_inherit", True)
    msg = "Populating the global package set from tag '%s'" % compose_tag
    global_pkgset_path = os.path.join(compose.paths.work.topdir(arch="global"), "pkgset_global.pickle")
    if compose.DEBUG and os.path.isfile(global_pkgset_path):
        compose.log_warning("[SKIP ] %s" % msg)
        pkgset = pickle.load(open(global_pkgset_path, "r"))
    else:
        compose.log_info(msg)
        pkgset = pypungi.phases.pkgset.pkgsets.KojiPackageSet(koji_proxy, compose.conf["sigkeys"], logger=compose._logger, arches=ALL_ARCHES)
        pkgset.populate(compose_tag, event_id, inherit=inherit)
        f = open(global_pkgset_path, "w")
        data = pickle.dumps(pkgset)
        f.write(data)
        f.close()

    # write global package list
    pkgset.save_file_list(compose.paths.work.package_list(arch="global"), remove_path_prefix=path_prefix)
    return pkgset


def get_koji_event_info(compose, koji_proxy):
    event_file = os.path.join(compose.paths.work.topdir(arch="global"), "koji-event")

    if compose.koji_event:
        koji_event = koji_proxy.getEvent(compose.koji_event)
        compose.log_info("Setting koji event to a custom value: %s" % compose.koji_event)
        json.dump(koji_event, open(event_file, "w"))

    msg = "Getting koji event"
    if compose.DEBUG and os.path.exists(event_file):
        compose.log_warning("[SKIP ] %s" % msg)
        result = json.load(open(event_file, "r"))
    else:
        compose.log_info(msg)
        result = koji_proxy.getLastEvent()
        json.dump(result, open(event_file, "w"))
    compose.log_info("Koji event: %s" % result["id"])
    return result


def get_koji_tag_info(compose, koji_proxy):
    tag_file = os.path.join(compose.paths.work.topdir(arch="global"), "koji-tag")
    msg = "Getting a koji tag info"
    if compose.DEBUG and os.path.exists(tag_file):
        compose.log_warning("[SKIP ] %s" % msg)
        result = json.load(open(tag_file, "r"))
    else:
        compose.log_info(msg)
        tag_name = compose.conf["pkgset_koji_tag"]
        result = koji_proxy.getTag(tag_name)
        if result is None:
            raise ValueError("Unknown koji tag: %s" % tag_name)
        result["name"] = tag_name
        json.dump(result, open(tag_file, "w"))
    compose.log_info("Koji compose tag: %(name)s (ID: %(id)s)" % result)
    return result
