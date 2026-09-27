"""Finds the phone among BlueZ devices and keeps it connected.

The iPhone never reconnects to the PC by itself (tested 2026-09-27), so the PC
has to call Device1.Connect, the way a car kit does. Status is polled every
poll_s seconds; Connect is tried at most once every retry_s seconds, only while
the adapter is powered and the phone is paired but not connected.
"""
import sys
import time

from gi.repository import Gio, GLib

HFP_AG_UUID = "0000111f-0000-1000-8000-00805f9b34fb"
BLUEZ = "org.bluez"


def pick_phone(objects, address=None):
    """Return (status, device_path) for the phone among BlueZ managed objects."""
    adapters = {path: ifaces["org.bluez.Adapter1"] for path, ifaces in objects.items()
                if "org.bluez.Adapter1" in ifaces}
    for path in sorted(objects):
        dev = objects[path].get("org.bluez.Device1")
        if not dev or not dev.get("Paired", False):
            continue
        dev_address = dev.get("Address", "")
        if address:
            match = dev_address.upper() == address.upper()
        else:
            match = HFP_AG_UUID in [u.lower() for u in dev.get("UUIDs", [])]
        if match:
            adapter = adapters.get(dev.get("Adapter", ""), {})
            status = {"found": True, "address": dev_address,
                      "name": dev.get("Alias") or dev.get("Name") or dev_address,
                      "connected": bool(dev.get("Connected", False)),
                      "powered": bool(adapter.get("Powered", False))}
            return status, path
    powered = any(a.get("Powered", False) for a in adapters.values())
    return ({"found": False, "address": (address or "").upper(), "name": "",
             "connected": False, "powered": powered}, None)


class PhoneLink:
    def __init__(self, bus, listener, address=None, poll_s=5.0, retry_s=30.0, clock=time.monotonic):
        self._bus = bus
        self._listener = listener
        self._address = address
        self._retry_s = retry_s
        self._clock = clock
        self._last_attempt = None
        self._connecting = False
        self.status = None
        self._poll()
        GLib.timeout_add(max(50, int(poll_s * 1000)), self._poll)

    def _poll(self):
        self._bus.call(BLUEZ, "/", "org.freedesktop.DBus.ObjectManager", "GetManagedObjects", None,
                       GLib.VariantType("(a{oa{sa{sv}}})"), Gio.DBusCallFlags.NONE, 5000, None,
                       self._on_objects)
        return True

    def _on_objects(self, bus, result):
        try:
            (objects,) = bus.call_finish(result).unpack()
        except GLib.Error:
            objects = {}
        status, device = pick_phone(objects, self._address)
        if status != self.status:
            self.status = status
            self._listener.phone(status)
        if device and status["powered"] and not status["connected"] and self._may_attempt():
            self._last_attempt = self._clock()
            self._connecting = True
            bus.call(BLUEZ, device, "org.bluez.Device1", "Connect", None, None,
                     Gio.DBusCallFlags.NONE, 30000, None, self._on_connect)

    def _may_attempt(self):
        if self._connecting:
            return False
        return self._last_attempt is None or self._clock() - self._last_attempt >= self._retry_s

    def _on_connect(self, bus, result):
        self._connecting = False
        try:
            bus.call_finish(result)
        except GLib.Error as error:
            Gio.DBusError.strip_remote_error(error)
            print(f"omyphone: connect failed: {error.message}", file=sys.stderr)
