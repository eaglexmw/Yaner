#!/usr/bin/env python
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
This module contains the L{Task} class of L{yaner}.
"""

import os

from gi.repository import GLib
from gi.repository import GObject
from sqlalchemy import Column, Integer, PickleType, Unicode, ForeignKey
from sqlalchemy.orm import reconstructor, deferred
from sqlalchemy.ext.hybrid import hybrid_property

from yaner import SQLBase, SQLSession
from yaner.Misc import unquote
from yaner.utils.Logging import LoggingMixin
from yaner.utils.Enum import Enum
from yaner.utils.Notification import Notification

class Task(SQLBase, GObject.GObject, LoggingMixin):
    """
    Task class is just downloading tasks, which provides data to L{TaskListModel}.
    """

    __gsignals__ = {
            'changed': (GObject.SignalFlags.RUN_LAST, None, ()),
            }
    """
    GObject signals of this class.
    """

    TYPES = Enum((
        'NORMAL',
        'BT',
        'ML',
        ))
    """
    The types of the task, which is a L{Enum<yaner.utils.Enum>}.
    C{TYPES.NAME} will return the type number of C{NAME}.
    """

    STATUSES = Enum((
        'INACTIVE',
        'ACTIVE',
        'WAITING',
        'PAUSED',
        'COMPLETE',
        'ERROR',
        'TRASHED',
        ))
    """
    The statuses of the task, which is a L{Enum<yaner.utils.Enum>}.
    C{STATUSES.NAME} will return the type number of C{NAME}.
    """

    _UPDATE_INTERVAL = 1
    """Interval for status updating, in second(s)."""

    _SYNC_INTERVAL = 60
    """Interval for database sync, in second(s)."""

    name = Column(Unicode)
    _status = Column(Integer, default=STATUSES.INACTIVE)
    type = Column(Integer, nullable=False)
    uris = Column(PickleType, default=[])
    completed_length = Column(Integer, default=0)
    total_length = Column(Integer, default=0)
    gid = Column(Unicode, default='')
    metafile = deferred(Column(PickleType, default=None))
    options = Column(PickleType)
    session_id = Column(Unicode, default='')
    category_id = Column(Integer, ForeignKey('category.id'))

    __mapper_args__ = {'polymorphic_on': type}

    def __init__(self, name, type, category, options,
            status=STATUSES.INACTIVE, uris=[], completed_length=0,
            total_length=0, gid='', metafile=None, session_id=''):
        self.name = name
        self.status = status
        self.type = type
        self.uris = uris
        self.completed_length = completed_length
        self.total_length = total_length
        self.gid = gid
        self.metafile = metafile
        self.options = options
        self.session_id = session_id
        self.category = category

        LoggingMixin.__init__(self)
        self.logger.info(_('Adding new task: {}...').format(self))
        self.logger.debug(_('Task options: {}').format(options))

        SQLSession.add(self)
        SQLSession.commit()

        self._init()

    @reconstructor
    def _init(self):
        LoggingMixin.__init__(self)
        GObject.GObject.__init__(self)

        self.upload_speed = 0
        self.download_speed = 0
        self.connections = 0

        self._status_update_handle = None
        self._database_sync_handle = None

        self._renamed = False

    def __repr__(self):
        return _("<Task {}>").format(self.name)

    @hybrid_property
    def status(self):
        return self._status

    @hybrid_property
    def pool(self):
        return self.category.pool

    @status.setter
    def status(self, status):
        """Always sync when task status changes."""
        if hash(self) and self.status != status:
            self._status = status
            self._sync_update()
            self.changed()
        else:
            self._status = status

    @property
    def completed(self):
        """Check if task is completed, useful for task undelete."""
        return self.total_length and (self.total_length == self.completed_length)

    def start(self):
        """Unpause task if it's paused, otherwise add it (again)."""
        if self.status == self.STATUSES.PAUSED:
            deferred = self.pool.proxy.call('aria2.unpause', self.gid)
            deferred.add_callback(self._on_unpaused)
            deferred.add_errback(self._on_xmlrpc_error)
            deferred.start()
        elif self.status in [self.STATUSES.INACTIVE, self.STATUSES.ERROR]:
            self.add()
            self.pool.queuing.add_task(self)

    def pause(self):
        """Pause task if it's running."""
        if self.status in [self.STATUSES.ACTIVE, self.STATUSES.WAITING]:
            deferred = self.pool.proxy.call('aria2.pause', self.gid)
            deferred.add_callback(self._on_paused)
            deferred.add_errback(self._on_xmlrpc_error)
            deferred.start()

    def trash(self):
        """Move task to dustbin."""
        if self.status in (self.STATUSES.COMPLETE, self.STATUSES. ERROR,
                           self.STATUSES.INACTIVE):
            self._on_trashed()
        elif self.status in (self.STATUSES.WAITING, self.STATUSES.ACTIVE,
                             self.STATUSES.PAUSED):
            deferred = self.pool.proxy.call('aria2.remove', self.gid)
            deferred.add_callback(self._on_trashed)
            deferred.add_errback(self._on_xmlrpc_error)
            deferred.start()

    def restore(self):
        """Restore task."""
        if self.status == self.STATUSES.TRASHED:
            self.pool.dustbin.remove_task(self)
            if self.completed:
                self.category.add_task(self)
                self.status = self.STATUSES.COMPLETE
            else:
                self.pool.queuing.add_task(self)
                self.status = self.STATUSES.INACTIVE

    def remove(self):
        """Remove task."""
        if self.status == self.STATUSES.TRASHED:
            self.pool.dustbin.remove_task(self)
            SQLSession.delete(self)
            self._sync_update()

    def changed(self):
        """Emit signal "changed"."""
        self.emit('changed')

    def begin_update_status(self):
        """Begin to update status every second. Task must be marked
        waiting before calling this.
        """
        if self._status_update_handle is None:
            self.logger.info(_('{}: begin updating status.').format(self))
            self._status_update_handle = GLib.timeout_add_seconds(
                    self._UPDATE_INTERVAL, self._call_tell_status)
            self._database_sync_handle = GLib.timeout_add_seconds(
                    self._SYNC_INTERVAL, self._sync_update)

    def end_update_status(self):
        """Stop updating status every second."""
        if self._status_update_handle:
            self.logger.info(_('{}: end updating status.').format(self))
            GLib.source_remove(self._status_update_handle)
            self._status_update_handle = None
        if self._database_sync_handle:
            GLib.source_remove(self._database_sync_handle)
            self._database_sync_handle = None

    def _sync_update(self):
        SQLSession.commit()
        return True

    def _update_session_id(self):
        """Get session id of the pool and store it in task."""
        def on_got_session_info(deferred):
            """Set session id the task belongs to."""
            self.session_id = deferred.result['sessionId']
            self._sync_update()

        deferred = self.pool.proxy.call('aria2.getSessionInfo', self.gid)
        deferred.add_callback(on_got_session_info)
        deferred.add_errback(self._on_xmlrpc_error)
        deferred.start()

    def _on_started(self, deferred):
        """Task started callback, update task information."""

        gid = deferred.result
        self.gid = gid[-1] if isinstance(gid, list) else gid
        self.status = self.STATUSES.ACTIVE

        self._update_session_id()
        self.begin_update_status()

    def _on_paused(self, deferred):
        """Task paused callback, update status."""
        self.status = self.STATUSES.PAUSED

    def _on_unpaused(self, deferred):
        """Task unpaused callback, update status."""
        self.status = self.STATUSES.ACTIVE

    def _on_trashed(self, deferred=None):
        """Task removed callback, remove task from previous presentable and
        move it to dustbin.
        """
        completed = (self.status == self.STATUSES.COMPLETE)
        self.status = self.STATUSES.TRASHED
        if completed:
            self.category.remove_task(self)
        else:
            self.pool.queuing.remove_task(self)
        self.pool.dustbin.add_task(self)

    def _call_tell_status(self):
        """Call pool for the status of this task.

        Return True to keep calling this when timeout else stop.

        """
        if self.status in (self.STATUSES.COMPLETE, self.STATUSES.ERROR,
                self.STATUSES.TRASHED, self.STATUSES.INACTIVE):
            self.end_update_status()
            return False
        else:
            deferred = self.pool.proxy.call('aria2.tellStatus', self.gid)
            deferred.add_callback(self._update_status)
            deferred.add_errback(self._on_xmlrpc_error)
            deferred.start()
            return True

    def _update_status(self, deferred):
        """Update data fields of the task."""
        status = deferred.result
        self.total_length = int(status['totalLength'])
        self.completed_length = int(status['completedLength'])
        self.download_speed = int(status['downloadSpeed'])
        self.upload_speed = int(status['uploadSpeed'])
        self.connections = int(status['connections'])

        statuses = {'active': self.STATUSES.ACTIVE,
                'waiting': self.STATUSES.WAITING,
                'paused': self.STATUSES.PAUSED,
                'complete': self.STATUSES.COMPLETE,
                'error': self.STATUSES.ERROR,
                'removed': self.STATUSES.TRASHED,
                }
        self.status = statuses[status['status']]

        if self.status == self.STATUSES.COMPLETE:
            self.pool.queuing.remove_task(self)
            self.category.add_task(self)
        elif self.status == self.STATUSES.TRASHED:
            return self._on_trashed()
        else:
            self.changed()

        self.pool.connected = True

    def _on_xmlrpc_error(self, deferred):
        """Handle errors occured when calling some function via xmlrpc."""
        self.status = self.STATUSES.ERROR
        message = getattr(deferred.error, 'message', str(deferred.error))
        Notification(_('Network Error'), message).show()

class NormalTask(Task):
    """Normal Task."""

    __mapper_args__ = {'polymorphic_identity': Task.TYPES.NORMAL}

    id = Column(Integer, ForeignKey('task.id'), primary_key=True)

    def add(self):
        """Add the task to pool."""
        deferred = self.pool.proxy.call('aria2.addUri',
                self.uris, self.options)
        deferred.add_callback(self._on_started)
        deferred.add_errback(self._on_xmlrpc_error)
        deferred.start()

    def _update_status(self, deferred):
        """For normal task, if there is only one task(magnet may have more than
        one), use it's name for task name.
        """
        if not self._renamed:
            files = deferred.result['files']
            if len(files) == 1:
                name = unquote(os.path.basename(files[0]['path']))
                if name != '':
                    self.name = name
                    self._renamed = True
        Task._update_status(self, deferred)

class BTTask(Task):
    """BitTorrent Task."""

    __mapper_args__ = {'polymorphic_identity': Task.TYPES.BT}

    id = Column(Integer, ForeignKey('task.id'), primary_key=True)

    def add(self):
        """Add the task to pool."""
        deferred = self.pool.proxy.call('aria2.addTorrent',
                self.metafile, self.uris, self.options)
        deferred.add_callback(self._on_started)
        deferred.add_errback(self._on_xmlrpc_error)
        deferred.start()

    def _update_status(self, deferred):
        """For BT task, use internal name of the torrent if possible.
        """
        if not self._renamed:
            if 'bittorrent' in deferred.result:
                name = unquote(deferred.result['bittorrent']['info']['name'])
                if name != '':
                    self.name = name
                    self._renamed = True
        Task._update_status(self, deferred)

class MLTask(Task):
    """Metalink Task."""

    __mapper_args__ = {'polymorphic_identity': Task.TYPES.ML}

    id = Column(Integer, ForeignKey('task.id'), primary_key=True)

    def add(self):
        """Add the task to pool."""
        deferred = self.pool.proxy.call('aria2.addMetalink',
                self.metafile, self.options)
        deferred.add_callback(self._on_started)
        deferred.add_errback(self._on_xmlrpc_error)
        deferred.start()

GObject.type_register(Task)
