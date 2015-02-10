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
Get a package list based on comps.xml.

Input format:
see comps.dtd

Output:
set([(rpm_name, rpm_arch or None)])
"""


from pypungi.wrappers.comps import CompsWrapper
import pypungi.phases.gather.source


class GatherSourceComps(pypungi.phases.gather.source.GatherSourceBase):
    enabled = True
    config_options = (
        {
            "name": "gather_source",
            "expected_types": [str],
            "expected_values": ["comps"],
        },
        {
            "name": "comps_file",
            "expected_types": [str, dict],
        },
    )

    def __call__(self, arch, variant):
        groups = set()
        comps = CompsWrapper(self.compose.paths.work.comps(arch=arch))

        if variant is not None:
            # get packages for a particular variant
            comps.filter_groups(variant.groups)

        for i in comps.get_comps_groups():
            groups.add(i.groupid)
        return set(), groups
