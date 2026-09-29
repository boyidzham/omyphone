"""Missed-call notifications over D-Bus (org.freedesktop.Notifications).

Ringing calls are not notified here: Omarchy's notifications cannot show
buttons, so the shell shows its own incoming-call card (IncomingCallCard.qml)
with Answer and Decline. Clicking a missed-call notification runs its "default"
action; on_show("missed") then asks the shell to open the missed-calls list.

The caller's name and number go over the session bus, not on a command line,
so other users cannot read them from the process list.
"""
import sys

from gi.repository import Gio, GLib

from .dbuserror import remote_message

SERVICE = "org.freedesktop.Notifications"
PATH = "/org/freedesktop/Notifications"


class Notifier:
    def __init__(self, bus, on_show):
        self._bus = bus
        self._on_show = on_show
        self._owner = None  # unique bus name of the notification service
        self._ids = set()  # our notifications still on screen
        # Only signals from the service's current owner count, so no other bus
        # client can fake a click.
        bus.signal_subscribe(None, SERVICE, "ActionInvoked", PATH, None, Gio.DBusSignalFlags.NONE,
                             self._on_action)
        bus.signal_subscribe(None, SERVICE, "NotificationClosed", PATH, None, Gio.DBusSignalFlags.NONE,
                             self._on_closed)
        Gio.bus_watch_name_on_connection(bus, SERVICE, Gio.BusNameWatcherFlags.NONE,
                                         self._on_appeared, self._on_vanished)

    def _on_appeared(self, _bus, _name, owner):
        self._owner = owner

    def _on_vanished(self, _bus, _name):
        self._owner = None
        self._ids.clear()

    def missed(self, number, name=""):
        def done(bus, result):
            try:
                self._ids.add(bus.call_finish(result).unpack()[0])
            except GLib.Error as error:
                print(f"omyphone: could not show a notification: {remote_message(error)}", file=sys.stderr)

        params = GLib.Variant("(susssasa{sv}i)", ("omyphone", 0, "", "Missed call", name or number or "Unknown number",
                                                   ["default", "Show missed calls"], {}, -1))
        self._bus.call(SERVICE, PATH, SERVICE, "Notify", params, GLib.VariantType("(u)"),
                       Gio.DBusCallFlags.NONE, 5000, None, done)

    def _on_action(self, _bus, sender, _path, _iface, _signal, params):
        notification, action = params.unpack()
        if sender == self._owner and notification in self._ids and action == "default":
            self._on_show("missed")

    def _on_closed(self, _bus, sender, _path, _iface, _signal, params):
        if sender == self._owner:
            self._ids.discard(params.unpack()[0])
