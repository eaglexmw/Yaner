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
from yaner.utils.Enum import Enum
from yaner.utils.Logging import LoggingMixin

class Presentable(LoggingMixin, gobject.GObject):
    """
    The Presentable class of L{yaner}, which provides data for L{PoolModel}.
    """

    __gsignals__ = {
            'changed': (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, ()),
            'task-added': (gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, (Task,)),
            'task-removed': (gobject.SIGNAL_RUN_LAST,
                gobject.TYPE_NONE, (Task,)),
            }
    """
    GObject signals of this class.
    """

    TYPES = Enum((
        'QUEUING',
        'CATEGORY',
        'DUSTBIN',
        ))
    """Presentable types."""

    def __init__(self):
        LoggingMixin.__init__(self)
        gobject.GObject.__init__(self)

    def add_task(self, task):
        """When task added, emit signals."""
        self.emit('changed')
        self.emit('task-added', task)

    def remove_task(self, task):
        """When task removed, emit signals."""
        self.emit('changed')
        self.emit('task-removed', task)

class Queuing(Presentable):
    """
    Queuing presentable of the L{Pool}s.
    """

    TYPE = Presentable.TYPES.QUEUING
    """Presentable type."""

    def __init__(self, pool):
        Presentable.__init__(self)
        self._pool = pool
        self.parent = None

    @property
    def name(self):
        """Get the name of the presentable."""
        return self.pool.name

    @name.setter
    def name(self, new_name):
        """Set the name of the presentable."""
        self.pool.name = new_name
        self.emit('changed')

    @property
    def pool(self):
        """Get the pool of the presentable."""
        return self._pool

    @property
    def tasks(self):
        """Get the running tasks of the pool."""
        return self.pool.tasks.filter(Task.q.status != \
                Task.STATUSES.REMOVED).filter(Task.q.status != \
                Task.STATUSES.COMPLETE)

class Category(sqlobject.SQLObject, Presentable):
    """
    Category presentable of the L{Pool}s.
    """

    __metaclass__ = GObjectSQLObjectMeta

    name = sqlobject.UnicodeCol()
    directory = sqlobject.UnicodeCol()

    pool = sqlobject.ForeignKey('Pool')
    tasks = sqlobject.SQLMultipleJoin('Task')

    TYPE = Presentable.TYPES.CATEGORY
    """Presentable type."""

    def _init(self, *args, **kwargs):
        Presentable.__init__(self)
        sqlobject.SQLObject._init(self, *args, **kwargs)

        self.parent = self.pool.queuing

    def _set_name(self, new_name):
        """Set the name of the category."""
        self._SO_set_name(new_name)
        # When creating a new Pool, Presentable.__init__ isn't called,
        # hash(self) equals zero, and signals can't be emitted
        if hash(self):
            self.emit('changed')

    def _get_tasks(self):
        """Get the comleted tasks of the category."""
        tasks = self._SO_get_tasks()
        return tasks.filter(Task.q.status == Task.STATUSES.COMPLETE)

class Dustbin(Presentable):
    """
    Dustbin presentable of the L{Pool}s.
    """

    TYPE = Presentable.TYPES.DUSTBIN
    """Presentable type."""

    def __init__(self, pool):
        Presentable.__init__(self)
        self._pool = pool
        self.parent = pool.queuing

    @property
    def name(self):
        """Get the name of the presentable."""
        return _('Dustbin')

    @property
    def pool(self):
        """Get the pool of the presentable."""
        return self._pool

    @property
    def tasks(self):
        """Get the deleted tasks of the pool."""
        return self.pool.tasks.filter(Task.q.status == Task.STATUSES.REMOVED)

