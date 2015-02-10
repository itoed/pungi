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


import kobo.plugins

from pypungi.checks import validate_options


class GatherMethodBase(kobo.plugins.Plugin):
    config_options = ()

    def __init__(self, compose):
        self.compose = compose

    def validate(self):
        errors = validate_options(self.compose.conf, self.config_options)
        if errors:
            raise ValueError("\n".join(errors))


class GatherMethodContainer(kobo.plugins.PluginContainer):
    @classmethod
    def normalize_name(cls, name):
        return name.lower()
