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
This module contains the tree view classes of the C{Gtk.TreeView} on the
left of the toplevel window.

A B{Pool} means a aria2 server, to avoid conflict with download servers.
"""

from gi.repository import Gtk
from gi.repository import GLib
from gi.repository import Pango

from yaner.Presentable import Presentable
from yaner.ui.Misc import get_mix_color
from yaner.utils.Enum import Enum
from yaner.utils.Pretty import psize
from yaner.utils.Logging import LoggingMixin

class PoolModel(Gtk.TreeStore, LoggingMixin):
    """
    The tree interface used by L{PoolView}.
    """

    COLUMNS = Enum('PRESENTABLE')
    """
    The column names of the tree model, which is a L{Enum<yaner.utils.Enum>}.
    C{COLUMNS.NAME} will return the column number of C{NAME}.
    """

    def __init__(self):
        """L{PoolModel} initializing."""
        Gtk.TreeStore.__init__(self, Presentable)
        LoggingMixin.__init__(self)

        self._pool_handlers = {}
        self._presentable_handlers = {}

    def add_pool(self, pool):
        """When a pool is added to the model, connect signals, and add all
        Presentables to the model.
        """
        self.logger.debug('Adding {}...'.format(pool))
        self._pool_handlers[pool] = [
                pool.connect('presentable-added', self.on_presentable_added),
                pool.connect('presentable-removed', self.on_presentable_removed),
                ]
        for presentable in pool.presentables:
            self.add_presentable(presentable)

    def remove_pool(self, pool):
        """Removed the pool and presentables, disconnect signals."""
        self.logger.debug('Removing {}...'.format(pool))
        for presentable in pool.presentables:
            self.remove_presentable(presentable)
        if pool in self._pool_handlers:
            for handler in self._pool_handlers[pool]:
                pool.disconnect(handler)
            del self._pool_handlers[pool]

    def on_presentable_added(self, pool, presentable):
        """When new presentable appears in one of the pools, add it to the model."""
        self.add_presentable(presentable, insert=True)

    def on_presentable_removed(self, pool, presentable):
        """
        When a presentable removed from one of the pools, remove it from
        the model.
        """
        self.remove_presentable(presentable)

    def on_presentable_changed(self, presentable):
        """When a presentable changed, update the iter of the model."""
        iter_ = self.get_iter_for_presentable(presentable)
        if iter_:
            self.row_changed(self.get_path(iter_), iter_)

    def add_presentable(self, presentable, insert=False):
        """Add a presentable to the model."""
        if self.get_iter_for_presentable(presentable):
            return

        self.logger.debug('Adding {}...'.format(presentable))
        parent = presentable.parent
        parent_iter = None
        if not parent is None:
            parent_iter = self.get_iter_for_presentable(parent)
            if parent_iter is None:
                self.logger.warning('No parent presentable for {0}.'.format(
                    presentable.name))
                self.add_presentable(parent)
                parent_iter = self.get_iter_for_presentable(parent)
        if insert:
            dustbin = presentable.pool.dustbin
            dustbin_iter = self.get_iter_for_presentable(dustbin)
            iter_ = self.insert_before(parent_iter, dustbin_iter)
        else:
            iter_ = self.append(parent_iter)
        self.set(iter_, self.COLUMNS.PRESENTABLE, presentable)

        handler = presentable.connect('changed', self.on_presentable_changed)
        self._presentable_handlers[presentable] = handler

    def remove_presentable(self, presentable):
        """Remove a presentable from the model."""
        iter_ = self.get_iter_for_presentable(presentable)
        if iter_ is not None:
            self.remove(iter_)
        if presentable in self._presentable_handlers:
            presentable.disconnect(self._presentable_handlers.pop(presentable))

    def get_iter_for_presentable(self, presentable, parent=None):
        """Get the TreeIter according to the presentable."""
        iter_ = self.iter_children(parent)
        while iter_:
            if presentable is self.get_presentable(iter_):
                return iter_

            result = self.get_iter_for_presentable(presentable, iter_)
            if result:
                return result

            iter_ = self.iter_next(iter_)
        return None

    def get_presentable(self, iter_):
        """Get the presentable according to the given iter."""
        return self.get_value(iter_, self.COLUMNS.PRESENTABLE)

class PoolView(Gtk.TreeView):
    """
    The C{Gtk.TreeView} displaying L{PoolModel}.
    """

    def __init__(self, model):
        """
        L{PoolView} initializing.
        @arg model:The interface of the tree view.
        @type model:L{PoolModel}
        """
        Gtk.TreeView.__init__(self, model)

        model.connect('row-deleted', self._on_row_deleted)

        # Set up TreeViewColumn
        column = Gtk.TreeViewColumn()
        self.append_column(column)

        renderer = Gtk.CellRendererPixbuf()
        column.pack_start(renderer, False)
        column.set_cell_data_func(renderer, self._pixbuf_data_func)

        renderer = Gtk.CellRendererText()
        column.pack_start(renderer, True)
        column.set_cell_data_func(renderer, self._markup_data_func)

    @property
    def selection(self):
        """Get the C{Gtk.TreeSelection} of the tree view."""
        return self.get_selection()

    @property
    def selected_presentable(self):
        """Get selected presentable."""
        (model, iter_) = self.selection.get_selected()
        if iter_ is None:
            return None
        else:
            return model.get_presentable(iter_)

    def _on_row_deleted(self, model, path):
        """If the row deleted is selected, reset the selection."""
        (model, iter_) = self.selection.get_selected()
        if iter_ is None or model.get_path(iter_) is None:
            self.selection.select_iter(model.iter_children(None))

    def _pixbuf_data_func(self, column, renderer, model, iter_, data=None):
        """Method for set the icon and its size in the column."""
        presentable = model.get_presentable(iter_)

        types = Presentable.TYPES
        icons = {types.QUEUING: 'gtk-connect',
                types.CATEGORY: 'gtk-directory',
                types.DUSTBIN: 'gtk-delete',
                }
        icon = icons[presentable.TYPE]
        if presentable.TYPE == types.QUEUING and \
                not presentable.pool.connected:
            icon = 'gtk-disconnect'

        renderer.set_properties(
                stock_id = icon,
                stock_size = Gtk.IconSize.LARGE_TOOLBAR,
                )

    def _markup_data_func(self, column, renderer, model, iter_, data=None):
        """
        Method for format the text in the column.
        """
        presentable = model.get_presentable(iter_)
        # Get current state of the iter
        if self.selection.iter_is_selected(iter_):
            if self.has_focus():
                state = Gtk.StateFlags.SELECTED
            else:
                state = Gtk.StateFlags.ACTIVE
        else:
            state = Gtk.StateFlags.NORMAL
        # Get the color for the description
        color = get_mix_color(self, state)

        tasks = list(presentable.tasks)
        total_length = sum(task.total_length for task in tasks)
        description = _('{} Task(s) {}').format(len(tasks), psize(total_length))
        markup = '<small>' \
                     '<b>{}</b>\n' \
                     '<span fgcolor="{}">{}</span>' \
                 '</small>' \
                 .format(GLib.markup_escape_text(presentable.name),
                         color, description)

        renderer.set_properties(
                markup = markup,
                ellipsize_set = True,
                ellipsize = Pango.EllipsizeMode.MIDDLE,
                )

