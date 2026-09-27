"""Incoming-call and missed-call notifications through notify-send.

The incoming notification runs `notify-send -p -A ...`, which prints the
notification ID straight away and later the chosen action name. Omarchy lets
critical notifications from app "notify-send" through Do Not Disturb.
"""
import sys

from gi.repository import Gio, GLib

NOTIFICATIONS = "org.freedesktop.Notifications"


class Notifier:
    def __init__(self, on_action, bus):
        self._on_action = on_action
        self._bus = bus
        self._open = {}  # call path -> {"proc": Gio.Subprocess, "id": int | None}

    def incoming(self, path, number):
        if path in self._open:
            return
        proc = self._spawn(["notify-send", "-u", "critical", "-p",
                            "-A", "answer=Answer", "-A", "decline=Decline",
                            "Incoming call", number or "Unknown number"],
                           Gio.SubprocessFlags.STDOUT_PIPE)
        if proc is None:
            return
        entry = {"proc": proc, "id": None}
        self._open[path] = entry
        stream = Gio.DataInputStream.new(proc.get_stdout_pipe())

        def on_line(stream, result):
            try:
                line, _length = stream.read_line_finish_utf8(result)
            except GLib.Error:
                line = None
            if line is None:
                if self._open.get(path) is entry:
                    del self._open[path]
                return
            line = line.strip()
            if entry["id"] is None and line.isdigit():
                entry["id"] = int(line)
            elif line in ("answer", "decline") and self._open.get(path) is entry:
                del self._open[path]
                self._on_action(path, line)
            stream.read_line_async(GLib.PRIORITY_DEFAULT, None, on_line)

        stream.read_line_async(GLib.PRIORITY_DEFAULT, None, on_line)

    def close(self, path):
        entry = self._open.pop(path, None)
        if entry is None:
            return
        if entry["id"] is not None:
            self._bus.call(NOTIFICATIONS, "/org/freedesktop/Notifications", NOTIFICATIONS,
                           "CloseNotification", GLib.Variant("(u)", (entry["id"],)), None,
                           Gio.DBusCallFlags.NO_AUTO_START, 2000, None, _ignore_reply)
        entry["proc"].force_exit()

    def close_all(self):
        for path in list(self._open):
            self.close(path)

    def missed(self, number):
        self._spawn(["notify-send", "-a", "omyphone", "Missed call", number or "Unknown number"],
                    Gio.SubprocessFlags.NONE)

    @staticmethod
    def _spawn(argv, flags):
        try:
            return Gio.Subprocess.new(argv, flags)
        except GLib.Error as error:
            print(f"omyphone: {argv[0]} failed: {error.message}", file=sys.stderr)
            return None


def _ignore_reply(bus, result):
    try:
        bus.call_finish(result)
    except GLib.Error:
        pass
