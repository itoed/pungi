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


from pypungi.checks import validate_options


class PhaseBase(object):
    config_options = ()

    def __init__(self, compose):
        self.compose = compose
        self.msg = "---------- PHASE: %s ----------" % self.name.upper()
        self.finished = False
        self._skipped = False

    def validate(self):
        errors = validate_options(self.compose.conf, self.config_options)
        if errors:
            raise ValueError("\n".join(errors))

    def conf_assert_str(self, name):
        missing = []
        invalid = []
        if name not in self.compose.conf:
            missing.append(name)
        elif not isinstance(self.compose.conf[name], str):
            invalid.append(name, type(self.compose.conf[name]), str)
        return missing, invalid

    def skip(self):
        if self._skipped:
            return True
        if self.compose.just_phases and self.name not in self.compose.just_phases:
            return True
        if self.name in self.compose.skip_phases:
            return True
        if self.name in self.compose.conf.get("skip_phases", []):
            return True
        return False

    def start(self):
        self._skipped = self.skip()
        if self._skipped:
            self.compose.log_warning("[SKIP ] %s" % self.msg)
            self.finished = True
            return
        self.compose.log_info("[BEGIN] %s" % self.msg)
        self.run()

    def stop(self):
        if self.finished:
            return
        if hasattr(self, "pool"):
            self.pool.stop()
        self.finished = True
        self.compose.log_info("[DONE ] %s" % self.msg)

    def run(self):
        raise NotImplementedError
