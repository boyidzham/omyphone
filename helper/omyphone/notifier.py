"""Missed-call notifications through notify-send.

Ringing calls are not notified here: Omarchy's notifications cannot show
buttons, so the shell shows its own incoming-call card (IncomingCallCard.qml)
with Answer and Decline. Clicking a missed-call notification runs its "default"
action, which notify-send prints; on_show("missed") then asks the shell to open
the missed-calls list.
"""
import sys

from gi.repository import Gio, GLib


class Notifier:
    def __init__(self, on_show):
        self._on_show = on_show
        self._waiting = set()  # notify-send processes still waiting for a click

    def missed(self, number):
        argv = ["notify-send", "-a", "omyphone", "-A", "default=Show missed calls",
                "Missed call", number or "Unknown number"]
        try:
            proc = Gio.Subprocess.new(argv, Gio.SubprocessFlags.STDOUT_PIPE)
        except GLib.Error as error:
            print(f"omyphone: notify-send failed: {error.message}", file=sys.stderr)
            return
        self._waiting.add(proc)

        def on_output(proc, result):
            self._waiting.discard(proc)
            try:
                _ok, stdout, _stderr = proc.communicate_utf8_finish(result)
            except GLib.Error:
                return
            if stdout and stdout.strip() == "default":
                self._on_show("missed")

        proc.communicate_utf8_async(None, None, on_output)

    def close_all(self):
        for proc in list(self._waiting):
            proc.force_exit()
        self._waiting.clear()
