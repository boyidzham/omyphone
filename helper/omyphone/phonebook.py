"""Pulls phonebook folders from the phone through BlueZ obexd (org.bluez.obex).

obexd is in the optional bluez-obex package and runs on the session bus. It
drops a session when the client that created it disconnects, so the helper
owns the session for the whole pull. Folders: pb (contacts), cch (all calls),
mch (missed calls). Each folder is written by obexd to a file in a private
runtime directory, read, and deleted. A folder that fails does not stop the
others: the result has the text of each folder pulled and the error of each
one that was not.
"""
import os
import stat
from pathlib import Path

from gi.repository import Gio, GLib

from .dbuserror import remote_message

OBEX = "org.bluez.obex"
OBEX_PATH = "/org/bluez/obex"
CLIENT = "org.bluez.obex.Client1"
PBAP = "org.bluez.obex.PhonebookAccess1"
TRANSFER = "org.bluez.obex.Transfer1"
MAX_BYTES = 128 * 1024 * 1024  # per folder; far above a real phonebook, even with photos


def default_tmpdir():
    """Never a fixed name under /tmp, which another user could create first."""
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    if runtime:
        return Path(runtime) / "omyphone"
    return Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "omyphone"


def _later(ms, fn):
    def run():
        fn()
        return GLib.SOURCE_REMOVE
    return GLib.timeout_add(ms, run)


class Phonebook:
    def __init__(self, bus, tmpdir, timeout_s=60.0, poll_ms=200, max_bytes=MAX_BYTES):
        self.bus = bus
        self.tmpdir = Path(tmpdir)
        self.timeout_s = timeout_s
        self.poll_ms = poll_ms
        self.max_bytes = max_bytes

    def available(self, callback):
        """callback(True) when obexd is running or can be started on demand."""
        def ask(method, then):
            def done(bus, result):
                try:
                    names = bus.call_finish(result).unpack()[0]
                except GLib.Error:
                    names = []
                then(names)
            self.bus.call("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus", method,
                          None, GLib.VariantType("(as)"), Gio.DBusCallFlags.NONE, 5000, None, done)

        ask("ListNames", lambda names: callback(True) if OBEX in names
            else ask("ListActivatableNames", lambda more: callback(OBEX in more)))

    def pull(self, address, folders, on_done):
        """on_done(texts, errors): {folder: vCard text} and {folder: error message}."""
        _Pull(self, address, list(folders), on_done).start()


class _Pull:
    """One sync: CreateSession, then Select + PullAll per folder, then RemoveSession."""

    def __init__(self, book, address, folders, on_done):
        self.bus, self.tmpdir, self.poll_ms, self.max_bytes = book.bus, book.tmpdir, book.poll_ms, book.max_bytes
        self.address, self.folders = address, folders
        self.on_done = on_done
        self.session = None
        self.texts = {}
        self.errors = {}
        self.finished = False
        self.checked = False  # tmpdir is known to be ours: only then clean it up
        self.timer = GLib.timeout_add(int(book.timeout_s * 1000), self._timeout)

    def start(self):
        try:
            self.tmpdir.mkdir(mode=0o700, parents=True, exist_ok=True)
            info = os.lstat(self.tmpdir)
            if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
                self._fail(f"{self.tmpdir} is not a private folder")
                return
            self.tmpdir.chmod(0o700)
            self.checked = True
        except OSError as error:
            self._fail(f"Could not create {self.tmpdir}: {error.strerror}")
            return
        self._call(OBEX_PATH, CLIENT, "CreateSession",
                   GLib.Variant("(sa{sv})", (self.address, {"Target": GLib.Variant("s", "PBAP")})),
                   "(o)", self._on_session, self._fail)

    def _call(self, path, iface, method, params, reply, then, on_error):
        def done(bus, result):
            try:
                value = bus.call_finish(result).unpack()
            except GLib.Error as error:
                if not self.finished:
                    on_error(remote_message(error))
                return
            if self.finished:
                if method == "CreateSession":
                    self._remove(value[0])  # the pull already timed out: do not leak the session
                return
            then(value)
        self.bus.call(OBEX, path, iface, method, params, GLib.VariantType(reply) if reply else None,
                      Gio.DBusCallFlags.NONE, 30000, None, done)

    def _on_session(self, value):
        self.session = value[0]
        self._next()

    def _next(self):
        if not self.folders:
            self._end()
            self.on_done(self.texts, self.errors)
            return
        folder = self.folders[0]
        self._call(self.session, PBAP, "Select", GLib.Variant("(ss)", ("int", folder)), None,
                   lambda _value: self._pull(folder), self._folder_failed)

    def _pull(self, folder):
        target = self.tmpdir / f"{folder}.vcf"
        try:
            target.unlink(missing_ok=True)  # never read a file left by an earlier run
        except OSError as error:
            self._folder_failed(f"Could not remove {target.name}: {error.strerror}")
            return
        self._call(self.session, PBAP, "PullAll",
                   GLib.Variant("(sa{sv})", (str(target), {"Format": GLib.Variant("s", "vcard30")})),
                   "(oa{sv})", lambda value: self._watch(folder, target, value[0]), self._folder_failed)

    def _watch(self, folder, target, transfer):
        def done(bus, result):
            if self.finished:
                return
            try:
                status = bus.call_finish(result).unpack()[0]
            except GLib.Error:
                # obexd drops a transfer object once it is done
                status = "complete" if target.exists() else "error"
            if status == "complete":
                self._read(folder, target)
            elif status == "error":
                self._folder_failed(f"Could not read {folder} from the phone")
            else:
                _later(self.poll_ms, lambda: self._watch(folder, target, transfer))
        self.bus.call(OBEX, transfer, "org.freedesktop.DBus.Properties", "Get",
                      GLib.Variant("(ss)", (TRANSFER, "Status")), GLib.VariantType("(v)"),
                      Gio.DBusCallFlags.NONE, 5000, None, done)

    def _read(self, folder, target):
        try:
            with open(target, "rb") as file:
                data = file.read(self.max_bytes + 1)
            target.unlink()
        except OSError as error:
            self._folder_failed(f"Could not read {target.name}: {error.strerror}")
            return
        if len(data) > self.max_bytes:
            self._folder_failed(f"The phone sent too much data for {folder}")
            return
        self.texts[folder] = data.decode("utf-8", "replace")
        self.folders.pop(0)
        self._next()

    def _folder_failed(self, message):
        """The current folder failed: note why and go on with the next one."""
        self.errors[self.folders.pop(0)] = message
        self._next()

    def _timeout(self):
        self.timer = None
        self._fail("The phone did not answer in time")
        return GLib.SOURCE_REMOVE

    def _remove(self, session):
        self.bus.call(OBEX, OBEX_PATH, CLIENT, "RemoveSession", GLib.Variant("(o)", (session,)), None,
                      Gio.DBusCallFlags.NONE, 5000, None, lambda bus, result: _ignore(bus, result))

    def _end(self):
        self.finished = True
        if self.timer is not None:
            GLib.source_remove(self.timer)
            self.timer = None
        if self.session:
            self._remove(self.session)
            self.session = None
        for leftover in self.tmpdir.glob("*.vcf") if self.checked else ():
            try:
                leftover.unlink()
            except OSError:
                pass

    def _fail(self, message):
        """Nothing more can be pulled: every folder not pulled yet failed with message."""
        if self.finished:
            return
        self._end()
        self.errors.update((folder, message) for folder in self.folders)
        self.on_done(self.texts, self.errors)


def _ignore(bus, result):
    try:
        bus.call_finish(result)
    except GLib.Error:
        pass
