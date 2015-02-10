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
import json

from kobo.rpmlib import parse_nvra
from productmd import RpmManifest

from pypungi.wrappers.scm import get_file_from_scm
from link import link_files

from pypungi.util import get_arch_variant_data, get_arch_data
from pypungi.phases.base import PhaseBase
from pypungi.arch import split_name_arch, get_compatible_arches


def get_gather_source(name):
    import pypungi.phases.gather.sources
    from source import GatherSourceContainer
    GatherSourceContainer.register_module(pypungi.phases.gather.sources)
    container = GatherSourceContainer()
    return container["GatherSource%s" % name]


def get_gather_method(name):
    import pypungi.phases.gather.methods
    from method import GatherMethodContainer
    GatherMethodContainer.register_module(pypungi.phases.gather.methods)
    container = GatherMethodContainer()
    return container["GatherMethod%s" % name]


class GatherPhase(PhaseBase):
    """GATHER"""
    name = "gather"

    config_options = (
        {
            "name": "multilib_arches",
            "expected_types": [list],
            "optional": True,
        },
        {
            "name": "gather_lookaside_repos",
            "expected_types": [list],
            "optional": True,
        },
        {
            "name": "multilib_methods",
            "expected_types": [list],
        },
        {
            "name": "greedy_method",
            "expected_values": ["none", "all", "build"],
            "optional": True,
        },
        {
            "name": "gather_fulltree",
            "expected_types": [bool],
            "optional": True,
        },
        {
            "name": "gather_prepopulate",
            "expected_types": [str, dict],
            "optional": True,
        },
        # DEPRECATED OPTIONS
        {
            "name": "additional_packages_multiarch",
            "deprecated": True,
            "comment": "Use multilib_whitelist instead",
        },
        {
            "name": "filter_packages_multiarch",
            "deprecated": True,
            "comment": "Use multilib_blacklist instead",
        },
    )

    def __init__(self, compose, pkgset_phase):
        PhaseBase.__init__(self, compose)
        # pkgset_phase provides package_sets and path_prefix
        self.pkgset_phase = pkgset_phase

    @staticmethod
    def check_deps():
        pass

    def check_config(self):
        errors = []
        for i in ["product_name", "product_short", "product_version"]:
            errors.append(self.conf_assert_str(i))

    def run(self):
        pkg_map = gather_wrapper(self.compose, self.pkgset_phase.package_sets, self.pkgset_phase.path_prefix)

        manifest_file = self.compose.paths.compose.metadata("rpms.json")
        manifest = RpmManifest()
        manifest.compose.id = self.compose.compose_id
        manifest.compose.type = self.compose.compose_type
        manifest.compose.date = self.compose.compose_date
        manifest.compose.respin = self.compose.compose_respin

        for arch in self.compose.get_arches():
            for variant in self.compose.get_variants(arch=arch):
                link_files(self.compose, arch, variant, pkg_map[arch][variant.uid], self.pkgset_phase.package_sets, manifest=manifest)

        self.compose.log_info("Writing RPM manifest: %s" % manifest_file)
        manifest.dump(manifest_file)


def get_parent_pkgs(arch, variant, result_dict):
    result = {
        "rpm": set(),
        "srpm": set(),
        "debuginfo": set(),
    }
    if variant.parent is None:
        return result
    for pkg_type, pkgs in result_dict.get(arch, {}).get(variant.parent.uid, {}).iteritems():
        for pkg in pkgs:
            nvra = parse_nvra(pkg["path"])
            result[pkg_type].add((nvra["name"], nvra["arch"]))
    return result


def gather_packages(compose, arch, variant, package_sets, fulltree_excludes=None):
    # multilib is per-arch, common for all variants
    multilib_whitelist = get_multilib_whitelist(compose, arch)
    multilib_blacklist = get_multilib_blacklist(compose, arch)
    GatherMethod = get_gather_method(compose.conf["gather_method"])

    msg = "Gathering packages (arch: %s, variant: %s)" % (arch, variant)
    compose.log_info("[BEGIN] %s" % msg)

    packages, groups, filter_packages = get_variant_packages(compose, arch, variant, package_sets)
    prepopulate = get_prepopulate_packages(compose, arch, variant)
    fulltree_excludes = fulltree_excludes or set()

    method = GatherMethod(compose)
    pkg_map = method(arch, variant, packages, groups, filter_packages, multilib_whitelist, multilib_blacklist, package_sets, fulltree_excludes=fulltree_excludes, prepopulate=prepopulate)

    compose.log_info("[DONE ] %s" % msg)
    return pkg_map


def write_packages(compose, arch, variant, pkg_map, path_prefix):
    msg = "Writing package list (arch: %s, variant: %s)" % (arch, variant)
    compose.log_info("[BEGIN] %s" % msg)

    for pkg_type, pkgs in pkg_map.iteritems():
        file_name = compose.paths.work.package_list(arch=arch, variant=variant, pkg_type=pkg_type)
        pkg_list = open(file_name, "w")
        for pkg in pkgs:
            # TODO: flags?
            pkg_path = pkg["path"]
            if pkg_path.startswith(path_prefix):
                pkg_path = pkg_path[len(path_prefix):]
            pkg_list.write("%s\n" % pkg_path)
        pkg_list.close()

    compose.log_info("[DONE ] %s" % msg)


def trim_packages(compose, arch, variant, pkg_map, parent_pkgs=None, remove_pkgs=None):
    """Remove parent variant's packages from pkg_map <-- it gets modified in this function"""
    # TODO: remove debuginfo and srpm leftovers

    if not variant.parent:
        return

    msg = "Trimming package list (arch: %s, variant: %s)" % (arch, variant)
    compose.log_info("[BEGIN] %s" % msg)

    remove_pkgs = remove_pkgs or {}
    parent_pkgs = parent_pkgs or {}

    addon_pkgs = {}
    move_to_parent_pkgs = {}
    removed_pkgs = {}
    for pkg_type, pkgs in pkg_map.iteritems():
        addon_pkgs.setdefault(pkg_type, set())
        move_to_parent_pkgs.setdefault(pkg_type, [])
        removed_pkgs.setdefault(pkg_type, [])

        new_pkgs = []
        for pkg in pkgs:
            pkg_path = pkg["path"]
            if not pkg_path:
                continue
            nvra = parse_nvra(pkg_path)
            key = ((nvra["name"], nvra["arch"]))

            if nvra["name"] in remove_pkgs.get(pkg_type, set()):
                # TODO: make an option to turn this off
                if variant.type == "layered-product" and pkg_type in ("srpm", "debuginfo"):
                    new_pkgs.append(pkg)
                    # User may not have addons available, therefore we need to
                    # keep addon SRPMs in layered products in order not to violate GPL.
                    # The same applies on debuginfo availability.
                    continue
                compose.log_warning("Removed addon package (arch: %s, variant: %s): %s: %s" % (arch, variant, pkg_type, pkg_path))
                removed_pkgs[pkg_type].append(pkg)
            elif key not in parent_pkgs.get(pkg_type, set()):
                if "input" in pkg["flags"]:
                    new_pkgs.append(pkg)
                    addon_pkgs[pkg_type].add(nvra["name"])
                elif "fulltree-exclude" in pkg["flags"]:
                    # if a package wasn't explicitly included ('input') in an addon,
                    # move it to parent variant (cannot move it to optional, because addons can't depend on optional)
                    # this is a workaround for not having $addon-optional
                    move_to_parent_pkgs[pkg_type].append(pkg)
                else:
                    new_pkgs.append(pkg)
                    addon_pkgs[pkg_type].add(nvra["name"])
            else:
                removed_pkgs[pkg_type].append(pkg)

        pkgs[:] = new_pkgs
        compose.log_info("Removed packages (arch: %s, variant: %s): %s: %s" % (arch, variant, pkg_type, len(removed_pkgs[pkg_type])))
        compose.log_info("Moved to parent (arch: %s, variant: %s): %s: %s" % (arch, variant, pkg_type, len(move_to_parent_pkgs[pkg_type])))

    compose.log_info("[DONE ] %s" % msg)
    return addon_pkgs, move_to_parent_pkgs, removed_pkgs


def gather_wrapper(compose, package_sets, path_prefix):
    result = {}

    # gather packages: variants
    for arch in compose.get_arches():
        for variant in compose.get_variants(arch=arch, types=["variant"]):
            fulltree_excludes = set()
            pkg_map = gather_packages(compose, arch, variant, package_sets, fulltree_excludes=fulltree_excludes)
            result.setdefault(arch, {})[variant.uid] = pkg_map

    # gather packages: addons
    for arch in compose.get_arches():
        for variant in compose.get_variants(arch=arch, types=["addon"]):
            fulltree_excludes = set()
            for pkg_name, pkg_arch in get_parent_pkgs(arch, variant, result)["srpm"]:
                fulltree_excludes.add(pkg_name)
            pkg_map = gather_packages(compose, arch, variant, package_sets, fulltree_excludes=fulltree_excludes)
            result.setdefault(arch, {})[variant.uid] = pkg_map

    # gather packages: layered-products
    # NOTE: the same code as for addons
    for arch in compose.get_arches():
        for variant in compose.get_variants(arch=arch, types=["layered-product"]):
            fulltree_excludes = set()
            for pkg_name, pkg_arch in get_parent_pkgs(arch, variant, result)["srpm"]:
                fulltree_excludes.add(pkg_name)
            pkg_map = gather_packages(compose, arch, variant, package_sets, fulltree_excludes=fulltree_excludes)
            result.setdefault(arch, {})[variant.uid] = pkg_map

    # gather packages: optional
    # NOTE: the same code as for variants
    for arch in compose.get_arches():
        for variant in compose.get_variants(arch=arch, types=["optional"]):
            fulltree_excludes = set()
            pkg_map = gather_packages(compose, arch, variant, package_sets, fulltree_excludes=fulltree_excludes)
            result.setdefault(arch, {})[variant.uid] = pkg_map

    # trim packages: addons
    all_addon_pkgs = {}
    for arch in compose.get_arches():
        for variant in compose.get_variants(arch=arch, types=["addon"]):
            pkg_map = result[arch][variant.uid]
            parent_pkgs = get_parent_pkgs(arch, variant, result)
            addon_pkgs, move_to_parent_pkgs, removed_pkgs = trim_packages(compose, arch, variant, pkg_map, parent_pkgs)

            # update all_addon_pkgs
            for pkg_type, pkgs in addon_pkgs.iteritems():
                all_addon_pkgs.setdefault(pkg_type, set()).update(pkgs)

            # move packages to parent
            parent_pkg_map = result[arch][variant.parent.uid]
            for pkg_type, pkgs in move_to_parent_pkgs.iteritems():
                for pkg in pkgs:
                    compose.log_debug("Moving package to parent (arch: %s, variant: %s, pkg_type: %s): %s" % (arch, variant.uid, pkg_type, os.path.basename(pkg["path"])))
                    if pkg not in parent_pkg_map[pkg_type]:
                        parent_pkg_map[pkg_type].append(pkg)

    # trim packages: layered-products
    all_lp_pkgs = {}
    for arch in compose.get_arches():
        for variant in compose.get_variants(arch=arch, types=["layered-product"]):
            pkg_map = result[arch][variant.uid]
            parent_pkgs = get_parent_pkgs(arch, variant, result)
            lp_pkgs, move_to_parent_pkgs, removed_pkgs = trim_packages(compose, arch, variant, pkg_map, parent_pkgs, remove_pkgs=all_addon_pkgs)

            # update all_addon_pkgs
            for pkg_type, pkgs in lp_pkgs.iteritems():
                all_lp_pkgs.setdefault(pkg_type, set()).update(pkgs)

            # move packages to parent
            # XXX: do we really want this?
            parent_pkg_map = result[arch][variant.parent.uid]
            for pkg_type, pkgs in move_to_parent_pkgs.iteritems():
                for pkg in pkgs:
                    compose.log_debug("Moving package to parent (arch: %s, variant: %s, pkg_type: %s): %s" % (arch, variant.uid, pkg_type, os.path.basename(pkg["path"])))
                    if pkg not in parent_pkg_map[pkg_type]:
                        parent_pkg_map[pkg_type].append(pkg)

    # merge all_addon_pkgs with all_lp_pkgs
    for pkg_type in set(all_addon_pkgs.keys()) | set(all_lp_pkgs.keys()):
        all_addon_pkgs.setdefault(pkg_type, set()).update(all_lp_pkgs.get(pkg_type, set()))

    # trim packages: variants
    for arch in compose.get_arches():
        for variant in compose.get_variants(arch=arch, types=["optional"]):
            pkg_map = result[arch][variant.uid]
            addon_pkgs, move_to_parent_pkgs, removed_pkgs = trim_packages(compose, arch, variant, pkg_map, remove_pkgs=all_addon_pkgs)

    # trim packages: optional
    for arch in compose.get_arches():
        for variant in compose.get_variants(arch=arch, types=["optional"]):
            pkg_map = result[arch][variant.uid]
            parent_pkgs = get_parent_pkgs(arch, variant, result)
            addon_pkgs, move_to_parent_pkgs, removed_pkgs = trim_packages(compose, arch, variant, pkg_map, parent_pkgs, remove_pkgs=all_addon_pkgs)

    # write packages (package lists) for all variants
    for arch in compose.get_arches():
        for variant in compose.get_variants(arch=arch, recursive=True):
            pkg_map = result[arch][variant.uid]
            write_packages(compose, arch, variant, pkg_map, path_prefix=path_prefix)

    return result


def write_prepopulate_file(compose):
    if not compose.conf.get("gather_prepopulate", None):
        return

    prepopulate_file = os.path.join(compose.paths.work.topdir(arch="global"), "prepopulate.json")
    msg = "Writing prepopulate file: %s" % prepopulate_file

    if compose.DEBUG and os.path.isfile(prepopulate_file):
        compose.log_warning("[SKIP ] %s" % msg)
    else:
        scm_dict = compose.conf["gather_prepopulate"]
        if isinstance(scm_dict, dict):
            file_name = os.path.basename(scm_dict["file"])
            if scm_dict["scm"] == "file":
                scm_dict["file"] = os.path.join(compose.config_dir, os.path.basename(scm_dict["file"]))
        else:
            file_name = os.path.basename(scm_dict)
            scm_dict = os.path.join(compose.config_dir, os.path.basename(scm_dict))

        compose.log_debug(msg)
        tmp_dir = tempfile.mkdtemp(prefix="prepopulate_file_")
        get_file_from_scm(scm_dict, tmp_dir, logger=compose._logger)
        shutil.copy2(os.path.join(tmp_dir, file_name), prepopulate_file)
        shutil.rmtree(tmp_dir)


def get_prepopulate_packages(compose, arch, variant):
    result = set()

    prepopulate_file = os.path.join(compose.paths.work.topdir(arch="global"), "prepopulate.json")
    if not os.path.isfile(prepopulate_file):
        return result

    prepopulate_data = json.load(open(prepopulate_file, "r"))

    if variant:
        variants = [variant.uid]
    else:
        # ALL variants
        variants = prepopulate_data.keys()

    for var in variants:
        for build, packages in prepopulate_data.get(var, {}).get(arch, {}).iteritems():
            for i in packages:
                pkg_name, pkg_arch = split_name_arch(i)
                if pkg_arch not in get_compatible_arches(arch, multilib=True):
                    raise ValueError("Incompatible package arch '%s' for tree arch '%s'" % (pkg_arch, arch))
                result.add(i)
    return result


def get_additional_packages(compose, arch, variant):
    result = set()
    for i in get_arch_variant_data(compose.conf, "additional_packages", arch, variant):
        pkg_name, pkg_arch = split_name_arch(i)
        if pkg_arch is not None and pkg_arch not in get_compatible_arches(arch, multilib=True):
            raise ValueError("Incompatible package arch '%s' for tree arch '%s'" % (pkg_arch, arch))
        result.add((pkg_name, pkg_arch))
    return result


def get_filter_packages(compose, arch, variant):
    result = set()
    for i in get_arch_variant_data(compose.conf, "filter_packages", arch, variant):
        result.add(split_name_arch(i))
    return result


def get_multilib_whitelist(compose, arch):
    return set(get_arch_data(compose.conf, "multilib_whitelist", arch))


def get_multilib_blacklist(compose, arch):
    return set(get_arch_data(compose.conf, "multilib_blacklist", arch))


def get_lookaside_repos(compose, arch, variant):
    return get_arch_variant_data(compose.conf, "gather_lookaside_repos", arch, variant)


def get_variant_packages(compose, arch, variant, package_sets=None):
    GatherSource = get_gather_source(compose.conf["gather_source"])
    source = GatherSource(compose)
    packages, groups = source(arch, variant)
#    if compose.conf["gather_source"] == "comps":
#        packages = set()
    filter_packages = set()

    # no variant -> no parent -> we have everything we need
    # doesn't make sense to do any package filtering
    if variant is None:
        return packages, groups, filter_packages

    packages |= get_additional_packages(compose, arch, variant)
    filter_packages |= get_filter_packages(compose, arch, variant)

    system_release_packages, system_release_filter_packages = get_system_release_packages(compose, arch, variant, package_sets)
    packages |= system_release_packages
    filter_packages |= system_release_filter_packages

    # if the variant is "optional", include all groups and packages
    # from the main "variant" and all "addons"
    if variant.type == "optional":
        for var in variant.parent.get_variants(arch=arch, types=["self", "variant", "addon", "layered-product"]):
            var_packages, var_groups, var_filter_packages = get_variant_packages(compose, arch, var, package_sets=package_sets)
            packages |= var_packages
            groups |= var_groups
            # we don't always want automatical inheritance of filtered packages from parent to child variants
            # filter_packages |= var_filter_packages

    if variant.type in ["addon", "layered-product"]:
        var_packages, var_groups, var_filter_packages = get_variant_packages(compose, arch, variant.parent, package_sets=package_sets)
        packages |= var_packages
        groups |= var_groups
        # filter_packages |= var_filter_packages

    return packages, groups, filter_packages


def get_system_release_packages(compose, arch, variant, package_sets):
    packages = set()
    filter_packages = set()

    if not variant:
        # include all system-release-* (gathering for a package superset)
        return packages, filter_packages

    if not package_sets or not package_sets.get(arch, None):
        return packages, filter_packages

    package_set = package_sets[arch]

    system_release_packages = set()
    for i in package_set:
        pkg = package_set[i]

        if pkg.is_system_release:
            system_release_packages.add(pkg)

    if not system_release_packages:
        return packages, filter_packages
    elif len(system_release_packages) == 1:
        # always include system-release package if available
        pkg = list(system_release_packages)[0]
        packages.add((pkg.name, None))
    else:
        if variant.type == "variant":
            # search for best match
            best_match = None
            for pkg in system_release_packages:
                if pkg.name.endswith("release-%s" % variant.uid.lower()) or pkg.name.startswith("%s-release" % variant.uid.lower()):
                    best_match = pkg
                    break
        else:
            # addons: return release packages from parent variant
            return get_system_release_packages(compose, arch, variant.parent, package_sets)

        if not best_match:
            # no package matches variant name -> pick the first one
            best_match = sorted(system_release_packages)[0]

        packages.add((best_match.name, None))
        for pkg in system_release_packages:
            if pkg.name == best_match.name:
                continue
            filter_packages.add((pkg.name, None))

    return packages, filter_packages
