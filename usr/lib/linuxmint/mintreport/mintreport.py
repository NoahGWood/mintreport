#!/usr/bin/python3

import apt
import os
import sys
import gettext
import gi
gi.require_version("Gtk", "3.0")
gi.require_version('GtkSource', '3.0')
from gi.repository import Gtk, Gdk, GtkSource
import subprocess
import shutil
import time

# i18n
gettext.install("mintreport", "/usr/share/linuxmint/locale")

CRASH_DIR = "/var/crash"

TMP_DIR = "/tmp/mintreport"
UNPACK_DIR = os.path.join(TMP_DIR, "crash")
CRASH_ARCHIVE = os.path.join(TMP_DIR, "crash.tar.gz")

class MintReport():

    def __init__(self):
        self.cache = apt.Cache()
        # Set the Glade file
        gladefile = "/usr/share/linuxmint/mintreport/mintreport.ui"
        builder = Gtk.Builder()
        builder.add_from_file(gladefile)
        self.window = builder.get_object("main_window")
        self.window.set_title(_("System Reports"))
        self.window.set_icon_name("mintreport")
        self.window.connect("delete_event", Gtk.main_quit)

        # the treeview
        self.treeview_crashes = builder.get_object("treeview_crashes")

        column = Gtk.TreeViewColumn("", Gtk.CellRendererText(), text=0)
        column.set_sort_column_id(0)
        column.set_resizable(True)
        self.treeview_crashes.append_column(column)
        column = Gtk.TreeViewColumn("", Gtk.CellRendererText(), text=1)
        column.set_sort_column_id(1)
        column.set_resizable(True)
        self.treeview_crashes.append_column(column)
        self.treeview_crashes.show()
        self.model_crashes = Gtk.TreeStore(str, str)
        self.model_crashes.set_sort_column_id(0, Gtk.SortType.DESCENDING)
        self.treeview_crashes.set_model(self.model_crashes)

        self.load_crashes()

        self.buffer = GtkSource.Buffer()
        self.language_manager = GtkSource.LanguageManager()
        style_manager = GtkSource.StyleSchemeManager()
        self.buffer.set_style_scheme(style_manager.get_scheme("oblivion"))
        self.sourceview = GtkSource.View.new_with_buffer(self.buffer)
        builder.get_object("scrolledwindow_crash").add(self.sourceview)
        self.sourceview.show()

        self.treeview_crashes.get_selection().connect("changed", self.on_crash_selected)

        self.bugtracker = "https://bugs.launchpad.net/"

        self.localfiles_button = builder.get_object("button_browse_crash_report")
        self.bugtracker_button = builder.get_object("button_open_bugtracker")

        self.localfiles_button.connect("clicked", self.on_button_browse_crash_report_clicked)
        self.bugtracker_button.connect("clicked", self.on_button_open_bugtracker_clicked)

        self.window.show_all()

    def load_crashes(self):
        self.model_crashes.clear()
        if os.path.exists(CRASH_DIR):
            for file in os.listdir(CRASH_DIR):
                if file.endswith(".crash"):
                    if "apport" not in file:
                        iter = self.model_crashes.insert_before(None, None)
                        mtime = time.ctime(os.path.getmtime(os.path.join(CRASH_DIR, file)))
                        self.model_crashes.set_value(iter, 0, mtime)
                        self.model_crashes.set_value(iter, 1, file)

    def on_crash_selected(self, selection):

        self.localfiles_button.set_sensitive(True)
        self.bugtracker_button.set_sensitive(True)
        self.buffer.set_language(self.language_manager.get_language(""))

        os.system("rm -rf %s/*" % UNPACK_DIR)
        model, iter = selection.get_selected()
        file = os.path.join(CRASH_DIR, model.get_value(iter, 1))
        if os.path.exists(file):
            subprocess.call(["apport-unpack", file, UNPACK_DIR])
            os.chdir(UNPACK_DIR)

            # Add info about the Linux Mint release
            if os.path.exists("/etc/linuxmint/info"):
                shutil.copyfile("/etc/linuxmint/info", "LinuxMintInfo")

            # Produce an Inxi report
            if os.path.exists("/usr/bin/inxi"):
                with open("Inxi", "w") as f:
                    subprocess.call(['inxi', '-Fxxrzc0'], stdout=f)

            # Produce a list of installed packages
            with open("Packages", "w") as f:
                subprocess.call(['dpkg', '-l'], stdout=f)

            executable_path = ""
            if os.path.exists("ExecutablePath"):
                with open("ExecutablePath") as f:
                    executable_path = f.readlines()[0]

            # Identify bug tracker
            self.bugtracker = "https://bugs.launchpad.net/"
            output = subprocess.check_output(["dpkg", "-S", executable_path]).decode("utf-8")
            if ":" in output:
                output = output.split(":")[0]
                # Check if -dbg package is missing
                dbg_name = "%s-dbg" % output
                if dbg_name in self.cache and not self.cache[dbg_name].is_installed:
                    self.localfiles_button.set_sensitive(False)
                    self.bugtracker_button.set_sensitive(False)
                    self.buffer.set_text(_("The debug symbols are missing for %s.\nPlease install %s.") % (output, dbg_name))
                    return

                if "mate" in output or output in ["caja", "atril", "pluma", "engrampa", "eog"]:
                    self.bugtracker = "https://github.com/mate-desktop/%s/issues" % output
                elif output in self.cache:
                    pkg = self.cache[output]
                    self.bugtracker = "https://bugs.launchpad.net/%s" % output
                    for origin in pkg.installed.origins:
                        if origin.origin == "linuxmint":
                            self.bugtracker = "https://github.com/linuxmint/%s/issues" % output
                            break

            # Produce a stack trace
            if os.path.exists("CoreDump"):
                os.system("echo '===================================================================' > StackTrace")
                os.system("echo ' GDB Log                                                           ' >> StackTrace")
                os.system("echo '===================================================================' >> StackTrace")
                os.system("LANG=C gdb %s CoreDump --batch >> StackTrace 2>&1" % executable_path)
                os.system("echo '\n===================================================================' >> StackTrace")
                os.system("echo ' GDB Backtrace                                                     ' >> StackTrace")
                os.system("echo '===================================================================' >> StackTrace")
                os.system("LANG=C gdb %s CoreDump --batch --ex bt >> StackTrace 2>&1" % executable_path)
                os.system("echo '\n===================================================================' >> StackTrace")
                os.system("echo ' GDB Backtrace (all threads)                                       ' >> StackTrace")
                os.system("echo '===================================================================' >> StackTrace")
                os.system("LANG=C gdb %s CoreDump --batch --ex 'thread apply all bt full' --ex bt >> StackTrace 2>&1" % executable_path)
                with open("StackTrace") as f:
                    text = f.read()
                    self.buffer.set_text(text)
                    self.buffer.set_language(self.language_manager.get_language("gdb-log"))
            elif os.path.exists("Traceback"):
                with open("Traceback") as f:
                    text = f.read()
                    self.buffer.set_text(text)
                    self.buffer.set_language(self.language_manager.get_language("python"))

            # Archive the crash report - exclude the CoreDump as it can be very big (close to 1GB)
            os.chdir(TMP_DIR)
            subprocess.call(["tar", "caf", CRASH_ARCHIVE, "crash", "--exclude", "CoreDump"])

    def on_button_browse_crash_report_clicked(self, button):
        os.system("xdg-open %s" % TMP_DIR)

    def on_button_open_bugtracker_clicked(self, button):
        os.system("xdg-open %s" % self.bugtracker)

if __name__ == "__main__":
    os.system("mkdir -p %s" % UNPACK_DIR)
    MintReport()
    Gtk.main()
