"""Pulls phonebook folders from the phone through BlueZ obexd (org.bluez.obex).

obexd is in the optional bluez-obex package and runs on the session bus. It
drops a session when the client that created it disconnects, so the helper
owns the session for the whole pull. Folders: pb (contacts), cch (all calls),
mch (missed calls). Each folder is written by obexd to a file in a private
runtime directory, read, and deleted.
"""
import os
from pathlib import Path

from gi.repository import Gio, GLib

OBEX = "org.bluez.obex"
OBEX_PATH = "/org/bluez/obex"
CLIENT = "org.bluez.obex.Client1"
PBAP = "org.bluez.obex.PhonebookAccess1"
TRANSFER = "org.bluez.obex.Transfer1"


def default_tmpdir():
    return Path(os.environ.get("XDG_RUNTIME_DIR") or "/tmp") / "omyphone"


def _later(ms, fn):
    def run():
        fn()
        return GLib.SOURCE_REMOVE
    return GLib.timeout_add(ms, run)


class Phonebook:
    def __init__(self, bus, tmpdir, timeout_s=60.0, poll_ms=200):
        self.bus = bus
        self.tmpdir = Path(tmpdir)
        self.timeout_s = timeout_s
        self.poll_ms = poll_ms

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

    def pull(self, address, folders, on_done, on_error):
        _Pull(self, address, list(folders), on_done, on_error).start()


class _Pull:
    """One sync: CreateSession, then Select + PullAll per folder, then RemoveSession."""

    def __init__(self, book, address, folders, on_done, on_error):
        self.bus, self.tmpdir, self.poll_ms = book.bus, book.tmpdir, book.poll_ms
        self.address, self.folders = address, folders
        self.on_done, self.on_error = on_done, on_error
        self.session = None
        self.texts = {}
        self.finished = False
        self.timer = GLib.timeout_add(int(book.timeout_s * 1000), self._timeout)

    def start(self):
        try:
            self.tmpdir.mkdir(mode=0o700, parents=True, exist_ok=True)
            self.tmpdir.chmod(0o700)
        except OSError as error:
            self._fail(f"Could not create {self.tmpdir}: {error.strerror}")
            return
        self._call(OBEX_PATH, CLIENT, "CreateSession",
                   GLib.Variant("(sa{sv})", (self.address, {"Target": GLib.Variant("s", "PBAP")})),
                   "(o)", self._on_session)

    def _call(self, path, iface, method, params, reply, then):
        def done(bus, result):
            try:
                value = bus.call_finish(result).unpack()
            except GLib.Error as error:
                self._fail(_remote_message(error))
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
            self.on_done(self.texts)
            return
        folder = self.folders[0]
        self._call(self.session, PBAP, "Select", GLib.Variant("(ss)", ("int", folder)), None,
                   lambda _value: self._pull(folder))

    def _pull(self, folder):
        target = self.tmpdir / f"{folder}.vcf"
        try:
            target.unlink(missing_ok=True)  # never read a file left by an earlier run
        except OSError as error:
            self._fail(f"Could not remove {target.name}: {error.strerror}")
            return
        self._call(self.session, PBAP, "PullAll",
                   GLib.Variant("(sa{sv})", (str(target), {"Format": GLib.Variant("s", "vcard30")})),
                   "(oa{sv})", lambda value: self._watch(folder, target, value[0]))

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
                self._fail(f"Could not read {folder} from the phone")
            else:
                _later(self.poll_ms, lambda: self._watch(folder, target, transfer))
        self.bus.call(OBEX, transfer, "org.freedesktop.DBus.Properties", "Get",
                      GLib.Variant("(ss)", (TRANSFER, "Status")), GLib.VariantType("(v)"),
                      Gio.DBusCallFlags.NONE, 5000, None, done)

    def _read(self, folder, target):
        try:
            self.texts[folder] = target.read_bytes().decode("utf-8", "replace")
            target.unlink()
        except OSError as error:
            self._fail(f"Could not read {target.name}: {error.strerror}")
            return
        self.folders.pop(0)
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
        for leftover in self.tmpdir.glob("*.vcf"):
            try:
                leftover.unlink()
            except OSError:
                pass

    def _fail(self, message):
        if self.finished:
            return
        self._end()
        self.on_error(message)


def _ignore(bus, result):
    try:
        bus.call_finish(result)
    except GLib.Error:
        pass


def _remote_message(error):
    """The human part of a D-Bus error reply, without the GDBus.Error:<name>: prefix.

    Gio.DBusError.strip_remote_error(error) is documented to remove this prefix
    in place, but on this machine's PyGObject/GLib it mutates a temporary copy:
    it returns True yet error.message (and even error.copy().message) still
    carry the prefix. Gio.DBusError.get_remote_error(error) does correctly
    return the parsed error name, so the known prefix is stripped by hand.
    """
    name = Gio.DBusError.get_remote_error(error)
    if name:
        prefix = f"GDBus.Error:{name}: "
        if error.message.startswith(prefix):
            return error.message[len(prefix):]
    return error.message
