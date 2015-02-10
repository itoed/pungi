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
The KojiPackageSet object obtains the latest RPMs from a Koji tag.
It automatically finds a signed copies according to *sigkey_ordering*.
"""


import os

import kobo.log
import kobo.pkgset
import kobo.rpmlib

from kobo.threads import WorkerThread, ThreadPool

from pypungi.util import pkg_is_srpm
from pypungi.arch import get_valid_arches


class ReaderPool(ThreadPool):
    def __init__(self, package_set, logger=None):
        ThreadPool.__init__(self, logger)
        self.package_set = package_set


class ReaderThread(WorkerThread):
    def process(self, item, num):
        # rpm_info, build_info = item

        if (num % 100 == 0) or (num == self.pool.queue_total):
            self.pool.package_set.log_debug("Processed %s out of %s packages" % (num, self.pool.queue_total))

        rpm_path = self.pool.package_set.get_package_path(item)
        rpm_obj = self.pool.package_set.file_cache.add(rpm_path)
        self.pool.package_set.rpms_by_arch.setdefault(rpm_obj.arch, []).append(rpm_obj)

        if pkg_is_srpm(rpm_obj):
            self.pool.package_set.srpms_by_name[rpm_obj.file_name] = rpm_obj
        elif rpm_obj.arch == "noarch":
            srpm = self.pool.package_set.srpms_by_name.get(rpm_obj.sourcerpm, None)
            if srpm:
                # HACK: copy {EXCLUDE,EXCLUSIVE}ARCH from SRPM to noarch RPMs
                rpm_obj.excludearch = srpm.excludearch
                rpm_obj.exclusivearch = srpm.exclusivearch
            else:
                self.pool.log_warning("Can't find a SRPM for %s" % rpm_obj.file_name)


class PackageSetBase(kobo.log.LoggingBase):
    def __init__(self, sigkey_ordering, arches=None, logger=None):
        kobo.log.LoggingBase.__init__(self, logger=logger)
        self.file_cache = kobo.pkgset.FileCache(kobo.pkgset.SimpleRpmWrapper)
        self.sigkey_ordering = sigkey_ordering or [None]
        self.arches = arches
        self.rpms_by_arch = {}
        self.srpms_by_name = {}

    def __getitem__(self, name):
        return self.file_cache[name]

    def __len__(self):
        return len(self.file_cache)

    def __iter__(self):
        for i in self.file_cache:
            yield i

    def __getstate__(self):
        result = self.__dict__.copy()
        del result["_logger"]
        return result

    def __setstate__(self, data):
        self._logger = None
        self.__dict__.update(data)

    def read_packages(self, rpms, srpms):
        srpm_pool = ReaderPool(self, self._logger)
        rpm_pool = ReaderPool(self, self._logger)

        for i in rpms:
            rpm_pool.queue_put(i)

        for i in srpms:
            srpm_pool.queue_put(i)

        thread_count = 10
        for i in range(thread_count):
            srpm_pool.add(ReaderThread(srpm_pool))
            rpm_pool.add(ReaderThread(rpm_pool))

        # process SRC and NOSRC packages first (see ReaderTread for the EXCLUDEARCH/EXCLUSIVEARCH hack for noarch packages)
        self.log_debug("Package set: spawning %s worker threads (SRPMs)" % thread_count)
        srpm_pool.start()
        srpm_pool.stop()
        self.log_debug("Package set: worker threads stopped (SRPMs)")

        self.log_debug("Package set: spawning %s worker threads (RPMs)" % thread_count)
        rpm_pool.start()
        rpm_pool.stop()
        self.log_debug("Package set: worker threads stopped (RPMs)")

        return self.rpms_by_arch

    def merge(self, other, primary_arch, arch_list):
        msg = "Merging package sets for %s: %s" % (primary_arch, arch_list)
        self.log_debug("[BEGIN] %s" % msg)

        # if "src" is present, make sure "nosrc" is included too
        if "src" in arch_list and "nosrc" not in arch_list:
            arch_list.append("nosrc")

        # make sure sources are processed last
        for i in ("nosrc", "src"):
            if i in arch_list:
                arch_list.remove(i)
                arch_list.append(i)

        seen_sourcerpms = set()
        # {Exclude,Exclusive}Arch must match *tree* arch + compatible native arches (excluding multilib arches)
        exclusivearch_list = get_valid_arches(primary_arch, multilib=False, add_noarch=False, add_src=False)
        for arch in arch_list:
            self.rpms_by_arch.setdefault(arch, [])
            for i in other.rpms_by_arch.get(arch, []):
                if i.file_path in self.file_cache:
                    # TODO: test if it really works
                    continue
                if arch == "noarch":
                    if i.excludearch and set(i.excludearch) & set(exclusivearch_list):
                        self.log_debug("Excluding (EXCLUDEARCH: %s): %s" % (sorted(set(i.excludearch)), i.file_name))
                        continue
                    if i.exclusivearch and not (set(i.exclusivearch) & set(exclusivearch_list)):
                        self.log_debug("Excluding (EXCLUSIVEARCH: %s): %s " % (sorted(set(i.exclusivearch)), i.file_name))
                        continue

                if arch in ("nosrc", "src"):
                    # include only sources having binary packages
                    if i.name not in seen_sourcerpms:
                        continue
                else:
                    sourcerpm_name = kobo.rpmlib.parse_nvra(i.sourcerpm)["name"]
                    seen_sourcerpms.add(sourcerpm_name)

                self.file_cache.file_cache[i.file_path] = i
                self.rpms_by_arch[arch].append(i)

        self.log_debug("[DONE ] %s" % msg)

    def save_file_list(self, file_path, remove_path_prefix=None):
        f = open(file_path, "w")
        for arch in sorted(self.rpms_by_arch):
            for i in self.rpms_by_arch[arch]:
                rpm_path = i.file_path
                if remove_path_prefix and rpm_path.startswith(remove_path_prefix):
                    rpm_path = rpm_path[len(remove_path_prefix):]
                f.write("%s\n" % rpm_path)
        f.close()


class FilelistPackageSet(PackageSetBase):
    def get_package_path(self, queue_item):
        # TODO: sigkey checking
        rpm_path = os.path.abspath(queue_item)
        return rpm_path

    def populate(self, file_list):
        result_rpms = []
        result_srpms = []
        msg = "Getting RPMs from file list"
        self.log_info("[BEGIN] %s" % msg)
        for i in file_list:
            if i.endswith(".src.rpm") or i.endswith(".nosrc.rpm"):
                result_srpms.append(i)
            else:
                result_rpms.append(i)
        result = self.read_packages(result_rpms, result_srpms)
        self.log_info("[DONE ] %s" % msg)
        return result


class KojiPackageSet(PackageSetBase):
    def __init__(self, koji_proxy, sigkey_ordering, arches=None, logger=None):
        PackageSetBase.__init__(self, sigkey_ordering=sigkey_ordering, arches=arches, logger=logger)
        self.koji_proxy = koji_proxy
        self.koji_pathinfo = getattr(__import__(koji_proxy.__module__, {}, {}, []), "pathinfo")

    def __getstate__(self):
        result = self.__dict__.copy()
        result["koji_class"] = self.koji_proxy.__class__.__name__
        result["koji_module"] = self.koji_proxy.__class__.__module__
        result["koji_baseurl"] = self.koji_proxy.baseurl
        result["koji_opts"] = self.koji_proxy.opts
        del result["koji_proxy"]
        del result["koji_pathinfo"]
        del result["_logger"]
        return result

    def __setstate__(self, data):
        class_name = data.pop("koji_class")
        module_name = data.pop("koji_module")
        module = __import__(module_name, {}, {}, [class_name])
        cls = getattr(module, class_name)
        self.koji_proxy = cls(data.pop("koji_baseurl"), data.pop("koji_opts"))
        self._logger = None
        self.__dict__.update(data)

    def get_latest_rpms(self, tag, event, inherit=True):
        return self.koji_proxy.listTaggedRPMS(tag, event=event, inherit=inherit, latest=True)

    def get_package_path(self, queue_item):
        rpm_info, build_info = queue_item
        rpm_path = None
        found = False
        pathinfo = self.koji_pathinfo
        for sigkey in self.sigkey_ordering:
            if sigkey is None:
                # we're looking for *signed* copies here
                continue
            sigkey = sigkey.lower()
            rpm_path = os.path.join(pathinfo.build(build_info), pathinfo.signed(rpm_info, sigkey))
            if os.path.isfile(rpm_path):
                found = True
                break

        if not found:
            if None in self.sigkey_ordering:
                # use an unsigned copy (if allowed)
                rpm_path = os.path.join(pathinfo.build(build_info), pathinfo.rpm(rpm_info))
                if os.path.isfile(rpm_path):
                    found = True
            else:
                # or raise an exception
                raise RuntimeError("RPM not found for sigs: %s" % self.sigkey_ordering)

        if not found:
            raise RuntimeError("Package not found: %s" % rpm_info)
        return rpm_path

    def populate(self, tag, event=None, inherit=True):
        result_rpms = []
        result_srpms = []

        if type(event) is dict:
            event = event["id"]

        msg = "Getting latest RPMs (tag: %s, event: %s, inherit: %s)" % (tag, event, inherit)
        self.log_info("[BEGIN] %s" % msg)
        rpms, builds = self.get_latest_rpms(tag, event)

        builds_by_id = {}
        for build_info in builds:
            builds_by_id.setdefault(build_info["build_id"], build_info)

        skipped_arches = []
        for rpm_info in rpms:
            if self.arches and rpm_info["arch"] not in self.arches:
                if rpm_info["arch"] not in skipped_arches:
                    self.log_debug("Skipping packages for arch: %s" % rpm_info["arch"])
                    skipped_arches.append(rpm_info["arch"])
                continue

            build_info = builds_by_id[rpm_info["build_id"]]
            if rpm_info["arch"] in ("src", "nosrc"):
                result_srpms.append((rpm_info, build_info))
            else:
                result_rpms.append((rpm_info, build_info))
        result = self.read_packages(result_rpms, result_srpms)
        self.log_info("[DONE ] %s" % msg)
        return result
