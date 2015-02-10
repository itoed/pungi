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


import os.path


tools = [
    ("isomd5sum", "/usr/bin/implantisomd5"),
    ("isomd5sum", "/usr/bin/checkisomd5"),
    ("jigdo", "/usr/bin/jigdo-lite"),
    ("genisoimage", "/usr/bin/genisoimage"),
    ("gettext", "/usr/bin/msgfmt"),
    ("syslinux", "/usr/bin/isohybrid"),
    ("yum-utils", "/usr/bin/createrepo"),
    ("yum-utils", "/usr/bin/mergerepo"),
    ("yum-utils", "/usr/bin/repoquery"),
    ("git", "/usr/bin/git"),
    ("cvs", "/usr/bin/cvs"),
    ("gettext", "/usr/bin/msgfmt"),
]

imports = [
    ("kobo", "kobo"),
    ("kobo-rpmlib", "kobo.rpmlib"),
    ("python-lxml", "lxml"),
    ("koji", "koji"),
    ("productmd", "productmd"),
]


def check():
    fail = False

    # Check python modules
    for package, module in imports:
        try:
            __import__(module)
        except ImportError:
            print("Module '%s' doesn't exist. Install package '%s'." % (module, package))
            fail = True

    # Check tools
    for package, path in tools:
        if not os.path.exists(path):
            print("Program '%s' doesn't exist. Install package '%s'." % (path, package))
            fail = True

    return not fail


def validate_options(conf, valid_options):
    errors = []
    for i in valid_options:
        name = i["name"]
        value = conf.get(name)

        if i.get("deprecated", False):
            if name in conf:
                errors.append("Deprecated config option: %s; %s" % (name, i["comment"]))
            continue

        if name not in conf:
            if not i.get("optional", False):
                errors.append("Config option not set: %s" % name)
            continue

        # verify type
        if "expected_types" in i:
            etypes = i["expected_types"]
            if not isinstance(etypes, list) and not isinstance(etypes, tuple):
                raise TypeError("The 'expected_types' value must be wrapped in a list: %s" % i)
            found = False
            for etype in etypes:
                if isinstance(value, etype):
                    found = True
                    break
            if not found:
                errors.append("Config option '%s' has invalid type: %s. Expected: %s." % (name, str(type(value)), etypes))
                continue

        # verify value
        if "expected_values" in i:
            evalues = i["expected_values"]
            if not isinstance(evalues, list) and not isinstance(evalues, tuple):
                raise TypeError("The 'expected_values' value must be wrapped in a list: %s" % i)
            found = False
            for evalue in evalues:
                if value == evalue:
                    found = True
                    break
            if not found:
                errors.append("Config option '%s' has invalid value: %s. Expected: %s." % (name, value, evalues))
                continue

        if "requires" in i:
            for func, requires in i["requires"]:
                if func(value):
                    for req in requires:
                        if req not in conf:
                            errors.append("Config option %s=%s requires %s which is not set" % (name, value, req))

        if "conflicts" in i:
            for func, conflicts in i["conflicts"]:
                if func(value):
                    for con in conflicts:
                        if con in conf:
                            errors.append("Config option %s=%s conflicts with option %s" % (name, value, con))

    return errors
