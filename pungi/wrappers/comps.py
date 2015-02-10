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


import sys
import fnmatch
import xml.dom.minidom
import yum.comps


if sys.version_info[:2] < (2, 7):
    # HACK: remove spaces from text elements on py < 2.7
    OldElement = xml.dom.minidom.Element

    class Element(OldElement):
        def writexml(self, writer, indent="", addindent="", newl=""):
            if len(self.childNodes) == 1 and self.firstChild.nodeType == 3:
                writer.write(indent)
                OldElement.writexml(self, writer)
                writer.write(newl)
            else:
                OldElement.writexml(self, writer, indent, addindent, newl)

    xml.dom.minidom.Element = Element


class CompsWrapper(object):
    """Class for reading and retreiving information from comps XML files"""

    def __init__(self, comps_file):
        self.comps = yum.comps.Comps()
        self.comps.add(comps_file)
        self.comps_file = comps_file

    def get_comps_packages(self):
        """Returns a dictionary containing all packages in comps"""

        packages = set()
        for group in self.comps.get_groups():
            packages.update(group.packages)
        return list(packages)

    def get_comps_groups(self):
        return self.comps.get_groups()

    def write_comps(self, comps_obj=None, target_file=None):
        if not comps_obj:
            comps_obj = self.generate_comps()
        if not target_file:
            target_file = self.comps_file
        stream = open(target_file, "w")
        # comps_obj.writexml(stream, addindent="  ", newl="\n") # no encoding -> use toprettyxml()
        stream.write(comps_obj.toprettyxml(indent="  ", encoding="UTF-8"))
        stream.close()

    def generate_comps(self):
        impl = xml.dom.minidom.getDOMImplementation()
        doctype = impl.createDocumentType("comps", "-//Red Hat, Inc.//DTD Comps info//EN", "comps.dtd")
        doc = impl.createDocument(None, "comps", doctype)
        msg_elem = doc.documentElement

        groups = {}
        for group_obj in self.comps.get_groups():
            groupid = group_obj.groupid
            groups[groupid] = {"group_obj": group_obj}

        group_names = groups.keys()
        group_names.sort()
        for group_key in group_names:
            group = groups[group_key]["group_obj"]
            group_node = doc.createElement("group")
            msg_elem.appendChild(group_node)

            id_node = doc.createElement("id")
            id_node.appendChild(doc.createTextNode(group.groupid))
            group_node.appendChild(id_node)

            name_node = doc.createElement("name")
            name_node.appendChild(doc.createTextNode(group.name))
            group_node.appendChild(name_node)

            langs = group.translated_name.keys()
            langs.sort()

            for lang in langs:
                text = group.translated_name[lang].decode("UTF-8")
                node = doc.createElement("name")
                node.setAttribute("xml:lang", lang)
                node.appendChild(doc.createTextNode(text))
                group_node.appendChild(node)

            node = doc.createElement("description")
            group_node.appendChild(node)
            if group.description and group.description != "":
                node.appendChild(doc.createTextNode(group.description))
                langs = group.translated_description.keys()
                langs.sort()

                for lang in langs:
                    text = group.translated_description[lang].decode("UTF-8")
                    node = doc.createElement("description")
                    node.setAttribute("xml:lang", lang)
                    node.appendChild(doc.createTextNode(text))
                    group_node.appendChild(node)

            node = doc.createElement("default")

            if group.default:
                node.appendChild(doc.createTextNode("true"))
            else:
                node.appendChild(doc.createTextNode("false"))
            group_node.appendChild(node)

            node = doc.createElement("uservisible")

            if group.user_visible:
                node.appendChild(doc.createTextNode("true"))
            else:
                node.appendChild(doc.createTextNode("false"))

            group_node.appendChild(node)

            if group.langonly:
                node = doc.createElement("langonly")
                node.appendChild(doc.createTextNode(group.langonly))
                group_node.appendChild(node)

            packagelist = doc.createElement("packagelist")

            for package_type in ("mandatory", "default", "optional", "conditional"):
                packages = getattr(group, package_type + "_packages").keys()
                packages.sort()
                for package in packages:
                    node = doc.createElement("packagereq")
                    node.appendChild(doc.createTextNode(package))
                    node.setAttribute("type", package_type)
                    packagelist.appendChild(node)
                    if package_type == "conditional":
                        node.setAttribute("requires", group.conditional_packages[package])

            group_node.appendChild(packagelist)

        categories = self.comps.get_categories()
        for category in categories:
            groups = set(category.groups) & set([i.groupid for i in self.comps.get_groups()])
            if not groups:
                continue
            cat_node = doc.createElement("category")
            msg_elem.appendChild(cat_node)

            id_node = doc.createElement("id")
            id_node.appendChild(doc.createTextNode(category.categoryid))
            cat_node.appendChild(id_node)

            name_node = doc.createElement("name")
            name_node.appendChild(doc.createTextNode(category.name))
            cat_node.appendChild(name_node)

            langs = category.translated_name.keys()
            langs.sort()

            for lang in langs:
                text = category.translated_name[lang].decode("UTF-8")
                node = doc.createElement("name")
                node.setAttribute("xml:lang", lang)
                node.appendChild(doc.createTextNode(text))
                cat_node.appendChild(node)

            if category.description and category.description != "":
                node = doc.createElement("description")
                node.appendChild(doc.createTextNode(category.description))
                cat_node.appendChild(node)
                langs = category.translated_description.keys()
                langs.sort()

                for lang in langs:
                    text = category.translated_description[lang].decode("UTF-8")
                    node = doc.createElement("description")
                    node.setAttribute("xml:lang", lang)
                    node.appendChild(doc.createTextNode(text))
                    cat_node.appendChild(node)

            if category.display_order is not None:
                display_node = doc.createElement("display_order")
                display_node.appendChild(doc.createTextNode("%s" % category.display_order))
                cat_node.appendChild(display_node)

            grouplist_node = doc.createElement("grouplist")
            groupids = sorted(groups)

            for groupid in groupids:
                node = doc.createElement("groupid")
                node.appendChild(doc.createTextNode(groupid))
                grouplist_node.appendChild(node)

            cat_node.appendChild(grouplist_node)

        # XXX
        environments = self.comps.get_environments()
        if environments:
            for environment in environments:
                groups = set(environment.groups) & set([i.groupid for i in self.comps.get_groups()])
                if not groups:
                    continue
                env_node = doc.createElement("environment")
                msg_elem.appendChild(env_node)

                id_node = doc.createElement("id")
                id_node.appendChild(doc.createTextNode(environment.environmentid))
                env_node.appendChild(id_node)

                name_node = doc.createElement("name")
                name_node.appendChild(doc.createTextNode(environment.name))
                env_node.appendChild(name_node)

                langs = environment.translated_name.keys()
                langs.sort()

                for lang in langs:
                    text = environment.translated_name[lang].decode("UTF-8")
                    node = doc.createElement("name")
                    node.setAttribute("xml:lang", lang)
                    node.appendChild(doc.createTextNode(text))
                    env_node.appendChild(node)

                if environment.description:
                    node = doc.createElement("description")
                    node.appendChild(doc.createTextNode(environment.description))
                    env_node.appendChild(node)

                    langs = environment.translated_description.keys()
                    langs.sort()

                    for lang in langs:
                        text = environment.translated_description[lang].decode("UTF-8")
                        node = doc.createElement("description")
                        node.setAttribute("xml:lang", lang)
                        node.appendChild(doc.createTextNode(text))
                        env_node.appendChild(node)

                if environment.display_order is not None:
                    display_node = doc.createElement("display_order")
                    display_node.appendChild(doc.createTextNode("%s" % environment.display_order))
                    env_node.appendChild(display_node)

                grouplist_node = doc.createElement("grouplist")
                groupids = sorted(groups)
                for groupid in groupids:
                    node = doc.createElement("groupid")
                    node.appendChild(doc.createTextNode(groupid))
                    grouplist_node.appendChild(node)
                env_node.appendChild(grouplist_node)

                optionids = sorted(environment.options)
                if optionids:
                    optionlist_node = doc.createElement("optionlist")
                    for optionid in optionids:
                        node = doc.createElement("groupid")
                        node.appendChild(doc.createTextNode(optionid))
                        optionlist_node.appendChild(node)
                    env_node.appendChild(optionlist_node)

        # XXX
        langpacks = self.comps.get_langpacks()
        if langpacks:
            lang_node = doc.createElement("langpacks")
            msg_elem.appendChild(lang_node)

        for langpack in langpacks:
            match_node = doc.createElement("match")
            match_node.setAttribute("name", langpack["name"])
            match_node.setAttribute("install", langpack["install"])
            lang_node.appendChild(match_node)

        return doc

    def _tweak_group(self, group_obj, group_dict):
        if group_dict["default"] is not None:
            group_obj.default = group_dict["default"]
        if group_dict["uservisible"] is not None:
            group_obj.uservisible = group_dict["uservisible"]

    def _tweak_env(self, env_obj, env_dict):
        if env_dict["display_order"] is not None:
            env_obj.display_order = env_dict["display_order"]
        else:
            # write actual display order back to env_dict
            env_dict["display_order"] = env_obj.display_order
        # write group list back to env_dict
        env_dict["groups"] = env_obj.groups[:]

    def filter_groups(self, group_dicts):
        """Filter groups according to group definitions in group_dicts.
        group_dicts = [{
            "name": group ID,
            "glob": True/False -- is "name" a glob?
            "default: True/False/None -- if not None, set "default" accordingly
            "uservisible": True/False/None -- if not None, set "uservisible" accordingly
        }]
        """
        to_remove = []
        for group_obj in self.comps.groups:
            found = False
            for group_dict in group_dicts:
                if group_dict["glob"]:
                    if fnmatch.fnmatch(group_obj.groupid, group_dict["name"]):
                        found = True
                        self._tweak_group(group_obj, group_dict)
                        break
                else:
                    if group_obj.groupid == group_dict["name"]:
                        self._tweak_group(group_obj, group_dict)
                        found = True
                        break

            if not found:
                to_remove.append(group_obj.groupid)

        if to_remove:
            for key, value in self.comps._groups.items():
                if key in to_remove:
                    del self.comps._groups[key]

    def filter_packages(self, pkglist):
        rv = []
        for group_obj in self.comps.get_groups():
            for package_type in ("mandatory", "default", "optional", "conditional"):
                group_pkgs = getattr(group_obj, "%s_packages" % package_type)
                pkg_names = group_pkgs.keys()
                pkg_names.sort()
                for pkg in pkg_names:
                    if pkg not in pkglist:
                        rv.append((pkg, group_obj.name))
                        del group_pkgs[pkg]
        rv.sort()
        return rv

    def filter_categories(self, catlist=None, include_empty=False):
        rv = []
        if catlist is not None:
            for categoryobj in self.comps.get_categories():
                if categoryobj.categoryid not in catlist:
                    rv.append(categoryobj.categoryid)
                    del self.comps._categories[categoryobj.categoryid]
        if not include_empty:
            comps_groups = [group.groupid for group in self.comps.get_groups()]
            for categoryobj in self.comps.get_categories():
                matched = False
                groupids = categoryobj.groups
                groupids.sort()
                for groupid in groupids:
                    if groupid not in comps_groups:
                        del categoryobj._groups[groupid]
                    else:
                        matched = True
                if not matched:
                    rv.append(categoryobj.categoryid)
                    del self.comps._categories[categoryobj.categoryid]
        rv.sort()
        return rv

    def filter_environments(self, env_dicts):
        """Filter environments according to group definitions in group_dicts.
        env_dicts = [{
            "name": environment ID,
            "display_order: <int>/None -- if not None, set "display_order" accordingly
        }]
        """
        to_remove = []
        for env_obj in self.comps.environments:
            found = False
            for env_dict in env_dicts:
                if env_obj.environmentid == env_dict["name"]:
                    self._tweak_env(env_obj, env_dict)
                    found = True
                    break

            if not found:
                to_remove.append(env_obj.environmentid)

        if to_remove:
            for key, value in self.comps._environments.items():
                if key in to_remove:
                    del self.comps._environments[key]

    def injectpackages(self, pkglist):
        def getgroup(pkgname):
            if pkgname.endswith("-devel"):
                return "compat-arch-development"
            elif pkgname.endswith("libs"):
                return "compat-arch-libs"
            else:
                return "compat-arch-support"

        groups_dict = {}
        for group_obj in self.comps.get_groups():
            groupid = group_obj.groupid
            groups_dict[groupid] = {"group_obj": group_obj}

        pkggroup_dict = {
            "compat-arch-development": [],
            "compat-arch-libs": [],
            "compat-arch-support": [],
        }

        for pkgname in pkglist:
            group = getgroup(pkgname)
            pkggroup_dict[group].append(pkgname)

        for group_obj in self.comps.get_groups():
            groupid = group_obj.groupid
            for pkg in pkggroup_dict[groupid]:
                if pkg not in group_obj.packages:
                    group_obj.default_packages[pkg] = 1
