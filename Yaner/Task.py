#!/usr/bin/env python
# -*- coding: UTF-8 -*-

# This file is part of Yaner.

# Yaner - GTK+ interface for aria2 download mananger
# Copyright (C) 2010  Iven Day <ivenvd#gmail.com>
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
    This file contains classes about download tasks.
"""

from __future__ import division
import glib
import os
import xmlrpclib
from pynotify import Notification
from twisted.web import xmlrpc
from twisted.internet.error import ConnectionRefusedError

from Yaner.Constants import *
from Yaner.Pretty import psize, pspeed

class TaskMixin:
    """
    General task class.
    """

    instances = {}

    def __init__(self, cate, conf):
        self.server = cate.server
        self.cate = cate
        self.conf = conf
        self.iter = None
        self.__add_iter()

        # Add self to the global dict
        self.instances[conf.info.uuid] = self

    def __on_paused(self, retval):
        """
        Being called when task is paused.
        """
        pass

    def __on_unpaused(self, retval):
        """
        Being called when task is unpaused.
        """
        pass

    def pause(self):
        """
        Pause the task.
        """
        deferred = self.server.proxy.callRemote(
                "aria2.pause", self.conf.info.gid)
        deferred.addCallbacks(self.__on_paused, self.on_twisted_error)

    def unpause(self):
        """
        Unpause the task.
        """
        deferred = self.server.proxy.callRemote(
                "aria2.unpause", self.conf.info.gid)
        deferred.addCallbacks(self.__on_unpaused, self.on_twisted_error)

    def get_uris(self):
        """
        Get URIs from config file.
        """
        return self.conf.info.uris.split('|')

    def get_options(self):
        """
        Get options from config file.
        """
        return dict(self.conf.options)

    def __add_iter(self):
        """
        Add an iter to the queuing model and start updating it.
        """
        server = self.server
        queuing_model = server.models[ITER_QUEUING]
        percent = float(self.conf.info.percent)
        size = int(self.conf.info.size)
        self.iter = queuing_model.append(None, [self.conf.info.gid,
            "gtk-new", self.conf.info.name, percent,
            '%.2f%% / %s' % (percent, psize(percent * size / 100)),
            psize(size), '', '', 0, self.conf.info.uuid])

    def on_started(self, gid):
        """
        Start updating iter when gid is received.
        """
        # FIXME: Workaround for Metalink.
        self.conf.info['gid'] = gid[-1] if type(gid) is list else gid
        self.server.group.select_iter(self.server.iters[ITER_QUEUING])
        glib.timeout_add_seconds(1, self.__call_for_status)

    def __call_for_status(self):
        """
        Call server for the status of this task.
        Return True means keep calling it when timeout.
        """
        if self.conf.info.gid:
            deferred = self.server.proxy.callRemote(
                    "aria2.tellStatus", self.conf.info.gid)
            deferred.addCallbacks(self.__update_iter, self.on_twisted_error)
            return True
        else:
            return False

    def __update_iter(self, status):
        """
        Update data fields of the task iter.
        """
        comp_length = status['completedLength']
        total_length = status['totalLength']
        if status['status'] == 'complete':
            percent = 100
            self.server.models[ITER_QUEUING].set(self.iter,
                    0, self.conf.info.gid,
                    2, self.conf.info.name,
                    3, percent,
                    4, '%.2f%% / %s' % (percent, psize(comp_length)),
                    5, psize(total_length),
                    6, 0,
                    7, 0,
                    8, 0)
            self.conf.info['gid'] = ''
        else:
            percent = int(comp_length) / int(total_length) * 100 \
                    if total_length != '0' else 0
            self.server.models[ITER_QUEUING].set(self.iter,
                    0, self.conf.info.gid,
                    2, self.conf.info.name,
                    3, percent,
                    4, '%.2f%% / %s' % (percent, psize(comp_length)),
                    5, psize(total_length),
                    6, pspeed(status['downloadSpeed']),
                    7, pspeed(status['uploadSpeed']),
                    8, int(status['connections']))
        if total_length != self.conf.info.size:
            self.conf.info['size'] = total_length
        if percent != self.conf.info.percent:
            self.conf.info['percent'] = percent

    def on_twisted_error(self, failure):
        """
        Handle errors occured when calling some functions via twisted.
        """
        message = failure.getErrorMessage()
        Notification(_('Network Error'), message, APP_ICON_NAME).show()

class MetalinkTask(TaskMixin):
    """
    Metalink Task Class
    """
    def __init__(self, cate, conf):
        TaskMixin.__init__(self, cate, conf)
        # Encode file
        with open(conf.info.metalink) as m_file:
            self.m_binary = xmlrpc.Binary(m_file.read())

    def start(self):
        """
        Start the task.
        """
        deferred = self.server.proxy.callRemote(
                "aria2.addMetalink", self.m_binary, self.get_options())
        deferred.addCallbacks(self.on_started, self.on_twisted_error)

class BTTask(TaskMixin):
    """
    BT Task Class
    """
    def __init__(self, cate, conf):
        TaskMixin.__init__(self, cate, conf)
        # Encode file
        with open(conf.info.torrent) as t_file:
            self.t_binary = xmlrpc.Binary(t_file.read())

    def start(self):
        """
        Start the task.
        """
        deferred = self.server.proxy.callRemote(
                "aria2.addTorrent", self.t_binary,
                self.get_uris(), self.get_options())
        deferred.addCallbacks(self.on_started, self.on_twisted_error)

    def __update_iter(self, status):
        """
        Update data fields of the task iter.
        """
        if status.has_key('bittorrent'):
            name = status['bittorrent']['info']['name']
            if name != self.conf.info.name:
                self.conf.info['name'] = name
        TaskMixin.__update_iter(self, status)

class NormalTask(TaskMixin):
    """
    Normal Task Class
    """
    def __init__(self, cate, conf):
        TaskMixin.__init__(self, cate, conf)

    def start(self):
        """
        Start the task.
        """
        deferred = self.server.proxy.callRemote("aria2.addUri",
                self.get_uris(), self.get_options())
        deferred.addCallbacks(self.on_started, self.on_twisted_error)

    def __update_iter(self, status):
        """
        Update data fields of the task iter.
        """
        name = os.path.basename(status['files'][0]['path'])
        if name != self.conf.info.name:
            self.conf.info['name'] = name
        TaskMixin.__update_iter(self, status)

TASK_CLASSES = (
        NormalTask,
        BTTask,
        MetalinkTask
        )

