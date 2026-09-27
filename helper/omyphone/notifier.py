"""Missed-call notifications through notify-send.

Ringing calls are not notified here: Omarchy's notifications cannot show
buttons, so the shell shows its own incoming-call card (IncomingCallCard.qml)
with Answer and Decline.
"""
import sys

from gi.repository import Gio, GLib


class Notifier:
    def missed(self, number):
        argv = ["notify-send", "-a", "omyphone", "Missed call", number or "Unknown number"]
        try:
            Gio.Subprocess.new(argv, Gio.SubprocessFlags.NONE)
        except GLib.Error as error:
            print(f"omyphone: notify-send failed: {error.message}", file=sys.stderr)
