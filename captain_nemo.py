# Captain Nemo is a Nautilus extension which converts Nautilus into
# an orthodox file manager.
#
# This extension requires at least version 1.0-0ubuntu2 of the
# python-nautilus package.
#
# To install copy captain-nemo.py to ~/.local/share/nautilus-python/extensions/
#
# The following keyboard shorcuts are (re)defined to their orthodox meanings.
#
# ------  -----------------------------------  ---------------
#                   Operation
# Key     Orthodox       Nautilus              Alternative Key
# ------  -------------  --------------------  ---------------
# F3      View           Show/Hide Extra Pane
# F4      Edit           Not Used
# F5      Copy           Reload                Ctrl+R
# F6      RenMov         Switch Between Panes  Tab
# F7      Mkdir          Not Used
# F8      Delete         Not Used
# Ctrl+O  Open Terminal  Open File             Enter
#
# As can be seen from the above table for most redefined operations there
# exist commonly used alternatives.
#
# In addition this extension defined the following keyboard shortcut:
#   Ctrl+G - open a git client in the current directory
# Also the Compare... item is added to the context menu when two items are
# selected.

import contextlib
import logging
import os
import subprocess
import sys
import traceback
import urllib
from gi.repository import Nautilus, GObject, Gtk, GConf

DIFF = 'meld'
GIT_CLIENT = 'gitg'
TERMINAL_KEY = '/desktop/gnome/applications/terminal/exec'
EDITOR = 'gedit'
DEBUG = False

# This class allows depth-first traversal of a widget tree using an iterator.
class walk:
    def __init__(self, top, visit_submenu=True):
        self._generator = self._walk(top)
        self._visit_submenu = visit_submenu
        self._skip_children = False
        self._depth = 0

    def __iter__(self):
        return self._generator.__iter__()

    def depth(self):
        return self._depth

    # Skip children of the current widget.
    def skip_children(self):
        self._skip_children = True

    def _walk(self, widget):
        if widget == None: return
        yield widget
        if self._skip_children:
            self._skip_children = False
            return
        self._depth += 1
        if isinstance(widget, Gtk.Container):
            for child in widget.get_children():
                for w in self._walk(child):
                    yield w
        if self._visit_submenu and isinstance(widget, Gtk.MenuItem):
            for w in self._walk(widget.get_submenu()):
                yield w
        self._depth -= 1

if DEBUG:
    logging.basicConfig(
        filename=os.path.join(os.path.dirname(__file__), 'captain_nemo.log'),
        level=logging.DEBUG)

def get_filename(file_info):
    return urllib.unquote(file_info.get_uri()[7:])

def has_file_scheme(f):
    return f.get_uri_scheme() == 'file'

# Catches and logs all exceptions.
@contextlib.contextmanager
def catch_all():
    try:
        yield
    except:
        logging.error(sys.exc_info()[1])

class KeyboardShortcutsDialog(Gtk.Dialog):
    def add_accel(self, data, accel_path, key, mods, changed):
        label = Gtk.accelerator_get_label(key, mods)
        self.accel_store.append([accel_path, label])

    def create_shortcut_list(self):
        self.accel_store = Gtk.ListStore(str, str)
        self.accel_store.set_sort_column_id(0, Gtk.SortType.ASCENDING)
        Gtk.AccelMap.foreach(None, self.add_accel)

        view = Gtk.TreeView(self.accel_store)
        view.set_rules_hint(True)

        column = Gtk.TreeViewColumn("Action", Gtk.CellRendererText(), text=0)
        column.set_sort_column_id(0)
        view.append_column(column)

        renderer = Gtk.CellRendererAccel()
        renderer.set_property("editable", True)
        renderer.connect("accel-edited", self.accel_edited)
        column = Gtk.TreeViewColumn('Key', renderer, text=1)
        column.set_sort_column_id(1)
        view.append_column(column)
        return view

    def accel_edited(self, accel, path, key, mods, keycode):
        Gtk.AccelMap.change_entry(self.accel_store[path][0], key, mods, False)
        self.accel_store[path][1] = Gtk.accelerator_get_label(key, mods)

    def __init__(self, parent):
        Gtk.Dialog.__init__(self, "Keyboard Shortcuts", parent,
            Gtk.DialogFlags.DESTROY_WITH_PARENT)

        self.add_button('Close', Gtk.ResponseType.CLOSE)
        self.set_default_size(800, 500)
        self.set_border_width(5)

        window = Gtk.ScrolledWindow()
        window.add(self.create_shortcut_list())
        window.set_border_width(5)
        window.set_shadow_type(Gtk.ShadowType.IN)

        content = self.get_content_area()
        content.set_spacing(2)
        content.pack_start(window, True, True, 0)

# Keyboard shortcuts dialog is global because shortcuts apply for a
# whole application, not to a single window.
shortcuts_dialog = None

# Redefines keyboard shortcuts and adds extra widgets.
class WindowAgent:
    def __init__(self, window):
        self.window = window
        self.loc_entry1 = self.loc_entry2 = None

        # Find the main paned widget and the menubar.
        self.main_paned = menubar = None
        walker = walk(window, False)
        for w in walker:
            name = w.get_name()
            if name == 'NautilusToolbar':
                p = w.get_parent()
                while not isinstance(p, Gtk.Paned):
                    p = p.get_parent()
                self.main_paned = p
                walker.skip_children()
            if name == 'MenuBar':
                menubar = w
                walker.skip_children()

        if menubar != None:
            # Show extra pane.
            for w in walk(menubar):
                name = w.get_name()
                if name == 'Show Hide Extra Pane':
                    w.activate()
                    break
        else:
            print 'Menu bar not found'

        if self.main_paned != None:
            # Find location entries.
            self.loc_entry1 = self.find_loc_entry(self.main_paned.get_child1())
            self.loc_entry2 = self.find_loc_entry(self.main_paned.get_child2())
        else:
            print 'Main paned not found'

        # Remove the accelerator from the 'Show Hide Extra Pane' action (F3).
        Gtk.AccelMap.change_entry(
            '<Actions>/ShellActions/Show Hide Extra Pane', 0, 0, False)
        # Remove the accelerator from the 'SplitViewNextPane' action (F6).
        Gtk.AccelMap.change_entry(
            '<Actions>/ShellActions/SplitViewNextPane', 0, 0, False)
        # Change the accelerator for the Open action from Ctrl+O to F3.
        key, mods = Gtk.accelerator_parse('F3')
        Gtk.AccelMap.change_entry(
            '<Actions>/DirViewActions/Open', key, mods, False)

        accel_group = Gtk.accel_groups_from_object(window)[0]

        def connect(accel, func):
            key, mods = Gtk.accelerator_parse(accel)
            accel_group.connect(key, mods, Gtk.AccelFlags.VISIBLE, func)

        connect('F4', self.on_edit)

        if self.loc_entry1 != None and self.loc_entry2 != None:
            connect('<Ctrl>O', self.on_terminal)
            connect('<Ctrl>G', self.on_git)
        else:
            print 'Location entries not found'

        if menubar != None:
            for w in walk(menubar):
                name = w.get_name()
                if name == 'Copy to next pane':
                    connect('F5', self.on_copy)
                    self.copy_menuitem = w
                elif name == 'Move to next pane':
                    connect('F6', self.on_move)
                    self.move_menuitem = w
                elif name == 'New Folder':
                    connect('F7', self.on_mkdir)
                    self.mkdir_menuitem = w
                elif name == 'Trash':
                    connect('F8', self.on_delete)
                    self.delete_menuitem = w
                elif name == 'Edit':
                    item = Gtk.MenuItem('Keyboard Shortcuts')
                    w.add(item)
                    item.show()
                    item.connect('activate',
                        self.show_keyboard_shortcuts_dialog)

        if DEBUG:
            # Add the widget inspector.
            from nautilus_debug import WidgetInspector
            child = window.get_child()
            inspector = WidgetInspector(window)
            window.remove(child)
            paned = Gtk.VPaned()
            paned.pack1(child, True, True)
            paned.pack2(inspector, False, False)
            paned.show()
            window.add(paned)

    def find_loc_entry(self, widget):
        for w in walk(widget):
            if w.get_name() == 'NautilusLocationEntry':
                return w

    def get_selection(self):
        focus = self.window.get_focus()
        if not isinstance(focus, Gtk.TreeView) and \
           focus.get_parent().get_name() == 'NautilusListView':
            return []
        def collect_uris(treemodel, path, iter, uris):
            uris.append(treemodel[iter][0].get_uri())
        uris = []
        focus.get_selection().selected_foreach(collect_uris, uris)
        return uris

    def show_dialog(self, title, message):
        md = Gtk.MessageDialog(parent=self.window, title=title)
        md.set_property('message-type', Gtk.MessageType.QUESTION)
        md.set_markup(message)
        md.add_button(Gtk.STOCK_OK, Gtk.ResponseType.OK)
        md.add_button(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL)
        result = md.run()
        md.destroy()
        return result == Gtk.ResponseType.OK

    def on_copy(self, accel_group, acceleratable, keyval, modifier):
        with catch_all():
            if self.show_dialog('Copy',
                'Do you want to copy selected files/directories?'):
                self.copy_menuitem.activate()
        return True

    def on_move(self, accel_group, acceleratable, keyval, modifier):
        with catch_all():
            if self.show_dialog('Move',
                'Do you want to move selected files/directories?'):
                self.move_menuitem.activate()
        return True

    def on_mkdir(self, accel_group, acceleratable, keyval, modifier):
        with catch_all():
            self.mkdir_menuitem.activate()
        return True

    def on_delete(self, accel_group, acceleratable, keyval, modifier):
        with catch_all():
            if self.show_dialog('Delete',
                'Do you want to move selected files/directories to trash?'):
                self.delete_menuitem.activate()
        return True

    def on_edit(self, accel_group, acceleratable, keyval, modifier):
        with catch_all():
            selection = self.get_selection()
            logging.debug("on_edit: %s", selection)
            subprocess.Popen([EDITOR] + selection)
        return True

    def get_location(self):
        w = self.window.get_focus()
        while w != None:
            if w == self.main_paned.get_child1():
                entry = self.loc_entry1
                break
            if w == self.main_paned.get_child2():
                entry = self.loc_entry2
                break
            w = w.get_parent()
        return entry.get_text()

    def on_terminal(self, accel_group, acceleratable, keyval, modifier):
        with catch_all():
            location = self.get_location()
            logging.debug('on_terminal: location=%s', location)
            terminal = GConf.Client.get_default().get_string(TERMINAL_KEY)
            subprocess.Popen([terminal], cwd=location)
        return True

    def on_git(self, accel_group, acceleratable, keyval, modifier):
        with catch_all():
            location = self.get_location()
            logging.debug('on_git: location=%s', location)
            subprocess.Popen([GIT_CLIENT], cwd=location)
        return True

    def show_keyboard_shortcuts_dialog(self, widget):
        global shortcuts_dialog
        if shortcuts_dialog:
            shortcuts_dialog.present()
            return
        with catch_all():
            shortcuts_dialog = KeyboardShortcutsDialog(self.window)
            shortcuts_dialog.show_all()
            shortcuts_dialog.run()
            shortcuts_dialog.destroy()
        shortcuts_dialog = None

class WidgetProvider(GObject.GObject, Nautilus.LocationWidgetProvider):
    def __init__(self):
        with catch_all():
            self._window_agents = {}
            if DEBUG:
                # The nautilus_debug package is only imported in DEBUG mode to
                # avoid dependency on twisted for normal use.
                from nautilus_debug import SSHThread
                SSHThread(self._window_agents).start()

    def get_widget(self, uri, window):
        with catch_all():
            if uri == 'x-nautilus-desktop:///':
                return None
            agent = self._window_agents.get(window)
            if agent != None:
                return None
            window.connect('destroy', lambda w: self._window_agents.pop(w))
            agent = WindowAgent(window)
            self._window_agents[window] = agent
        return None

class CompareMenuProvider(GObject.GObject, Nautilus.MenuProvider):
    def on_compare(self, menu, files):
        subprocess.Popen([DIFF, get_filename(files[0]), get_filename(files[1])])
 
    def get_file_items(self, window, files):
        if len(files) != 2: return
        if not has_file_scheme(files[0]) or not has_file_scheme(files[1]):
            return
        item = Nautilus.MenuItem(
            name='SimpleMenuExtension::Compare_Files', label='Compare...',
            tip='Compare...')
        item.connect('activate', self.on_compare, files)
        return [item]
