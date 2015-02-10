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
Pungi adds several new sections to kickstarts.


FULLTREE EXCLUDES
-----------------
Fulltree excludes allow us to define SRPM names
we don't want to be part of fulltree processing.

Syntax:
%fulltree-excludes
<srpm_name>
<srpm_name>
...
%end


MULTILIB BLACKLIST
------------------
List of RPMs which are prevented from becoming multilib.

Syntax:
%multilib-blacklist
<rpm_name>
<rpm_name>
...
%end


MULTILIB WHITELIST
------------------
List of RPMs which will become multilib (but only if native package is pulled in).

Syntax:
%multilib-whitelist
<rpm_name>
<rpm_name>
...
%end


PREPOPULATE
-----------
To make sure no package is left behind between 2 composes,
we can explicitly add <name>.<arch> records to the %prepopulate section.
These will be added to the input list and marked with 'prepopulate' flag.

Syntax:
%prepopulate
<rpm_name>.<rpm_arch>
<rpm_name>.<rpm_arch>
...
%end
"""


import pykickstart.parser
import pykickstart.sections


class FulltreeExcludesSection(pykickstart.sections.Section):
    sectionOpen = "%fulltree-excludes"

    def handleLine(self, line):
        if not self.handler:
            return

        (h, s, t) = line.partition('#')
        line = h.rstrip()

        self.handler.fulltree_excludes.add(line)


class MultilibBlacklistSection(pykickstart.sections.Section):
    sectionOpen = "%multilib-blacklist"

    def handleLine(self, line):
        if not self.handler:
            return

        (h, s, t) = line.partition('#')
        line = h.rstrip()

        self.handler.multilib_blacklist.add(line)


class MultilibWhitelistSection(pykickstart.sections.Section):
    sectionOpen = "%multilib-whitelist"

    def handleLine(self, line):
        if not self.handler:
            return

        (h, s, t) = line.partition('#')
        line = h.rstrip()

        self.handler.multilib_whitelist.add(line)


class PrepopulateSection(pykickstart.sections.Section):
    sectionOpen = "%prepopulate"

    def handleLine(self, line):
        if not self.handler:
            return

        (h, s, t) = line.partition('#')
        line = h.rstrip()

        self.handler.prepopulate.add(line)


class KickstartParser(pykickstart.parser.KickstartParser):
    def setupSections(self):
        pykickstart.parser.KickstartParser.setupSections(self)
        self.registerSection(FulltreeExcludesSection(self.handler))
        self.registerSection(MultilibBlacklistSection(self.handler))
        self.registerSection(MultilibWhitelistSection(self.handler))
        self.registerSection(PrepopulateSection(self.handler))


HandlerClass = pykickstart.version.returnClassForVersion()
class PungiHandler(HandlerClass):
    def __init__(self, *args, **kwargs):
        HandlerClass.__init__(self, *args, **kwargs)
        self.fulltree_excludes = set()
        self.multilib_blacklist = set()
        self.multilib_whitelist = set()
        self.prepopulate = set()


def get_ksparser(ks_path=None):
    """
    Return a kickstart parser instance.
    Read kickstart if ks_path provided.
    """
    ksparser = KickstartParser(PungiHandler())
    if ks_path:
        ksparser.readKickstart(ks_path)
    return ksparser
