# CORTX Python common library.
# Copyright (c) 2021 Seagate Technology LLC and/or its Affiliates
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published
# by the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU Affero General Public License for more details.
# You should have received a copy of the GNU Affero General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.
# For any questions about this software or licensing,
# please email opensource@seagate.com or cortx-questions@seagate.com

class InterfaceError(Exception):
    """Error Handling for server components."""

    def __init__(self, rc, message, *args):
        """Initialize the error information."""
        self._rc = rc
        self._desc = message % (args)

    @property
    def rc(self):
        return self._rc

    @property
    def desc(self):
        return self._desc

    def __str__(self):
        """Return the error string."""
        if self._rc == 0:
            return self._desc
        return "error(%d): %s" % (self._rc, self._desc)


class NetworkError(InterfaceError):
    """Error Handling for Network related errors."""

    def __init__(self, rc, message, *message_args):
        """Initialize the Error information."""
        super(NetworkError, self).__init__(rc, message, *message_args)


class BuildInfoError(InterfaceError):
    """Error handling while fetching cortx build info."""

    def __init__(self, rc, message, *message_args):
        """Initialize the Error information."""
        super(BuildInfoError, self).__init__(rc, message, *message_args)


class SASError(InterfaceError):
    """Error Handling for SAS related errors."""

    def __init__(self, rc, message, *message_args):
        """Initialize the Error information."""
        super(SASError, self).__init__(rc, message, *message_args)


class ServiceError(InterfaceError):
    """Error handling while fetching service info."""

    def __init__(self, rc, message, *message_args):
        """Initialize the Error information."""
        super(ServiceError, self).__init__(rc, message, *message_args)
