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


"""
Get a package list based on a JSON mapping.

Input format:
{
    variant: {
        tree_arch: {
            rpm_name: [rpm_arch, rpm_arch, ... (or None for any/best arch)],
        }
    }
}

Output:
set([(rpm_name, rpm_arch or None)])
"""


import json

import pypungi.phases.gather.source


class GatherSourceJson(pypungi.phases.gather.source.GatherSourceBase):
    enabled = True
    config_options = (
        {
            "name": "gather_source",
            "expected_types": [str],
            "expected_values": ["json"],
        },
        {
            "name": "gather_source_mapping",
            "expected_types": [str],
        },
    )

    def __call__(self, arch, variant):
        json_path = self.compose.conf["gather_source_mapping"]
        data = open(json_path, "r").read()
        mapping = json.loads(data)

        packages = set()
        if variant is None:
            # get all packages for all variants
            for variant_uid in mapping:
                for pkg_name, pkg_arches in mapping[variant_uid][arch].iteritems():
                    for pkg_arch in pkg_arches:
                        packages.add((pkg_name, pkg_arch))
        else:
            # get packages for a particular variant
            for pkg_name, pkg_arches in mapping[variant.uid][arch].iteritems():
                for pkg_arch in pkg_arches:
                    packages.add((pkg_name, pkg_arch))
        return packages, set()
