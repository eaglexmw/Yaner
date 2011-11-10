#!/usr/bin/env python2
# vim:fileencoding=UTF-8

# This file is part of Yaner.

# Yaner - GTK+ interface for aria2 download mananger
# Copyright (C) 2010-2011  Iven <ivenvd#gmail.com>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#

"""
This module contains the L{Presentable} class of L{yaner}.
"""

import gobject
import sqlobject

from yaner.Task import Task
from yaner.Misc import GObjectSQLObjectMeta
from yaner.utils.Logging import LoggingMixin

class Presentable(LoggingMixin, gobject.GObject):
    """
    The Presentable class of L{yaner}, which provides data for L{PoolModel}.
    """

    __gsignals__ = {
            'changed': (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, ()),
            'removed': (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, ()),
            'task-added': (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, (Task,)),
            'task-removed': (gobject.SIGNAL_RUN_LAST,
                gobject.TYPE_NONE, (Task,)),
            'task-changed': (gobject.SIGNAL_RUN_LAST,
                gobject.TYPE_NONE, (Task,)),
            }
    """
    GObject signals of this class.
    """

    def _init(self, *args, **kwargs):
        LoggingMixin.__init__(self)
        gobject.GObject.__init__(self)

        self._description = ''

    @property
    def description(self):
        """Get the description of the presentable."""
        return self._description

class Queuing(Presentable):
    """
    Queuing presentable of the L{Pool}s.
    """

    def __init__(self, name):
        Presentable.__init__(self)
        self._name = name
        self.parent = None
        self.icon = "gtk-connect"

    @property
    def name(self):
        """Get the name of the presentable."""
        return self._name

    @name.setter
    def name(self, new_name):
        """Set the name of the presentable."""
        self._name = new_name
        self.emit('changed')

class Category(Presentable, sqlobject.SQLObject):
    """
    Category presentable of the L{Pool}s.
    """

    __metaclass__ = GObjectSQLObjectMeta

    name = sqlobject.UnicodeCol()
    directory = sqlobject.UnicodeCol()

    pool = sqlobject.ForeignKey('Pool')
    tasks = sqlobject.MultipleJoin('Task')

    def _init(self, *args, **kwargs):
        Presentable.__init__(self)
        sqlobject.SQLObject._init(self, *args, **kwargs)

        self.parent = kwargs['queuing']
        self.icon = "gtk-directory"

    def _set_name(self, new_name):
        """Set the name of the category."""
        self._SO_set_name(new_name)
        self.emit('changed')

class Dustbin(Presentable):
    """
    Dustbin presentable of the L{Pool}s.
    """
    def __init__(self, queuing):
        Presentable.__init__(self)
        self.parent = queuing
        self.icon = "gtk-delete"

    @property
    def name(self):
        """Get the name of the presentable."""
        return _('Dustbin')

