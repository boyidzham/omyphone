"""Client for PipeWire's org.pipewire.Telephony service on the session bus.

Uses the ofono-compatible methods and signals documented in PipeWire's
spa/plugins/bluez5/README-Telephony.md (1.6.8). Reports changes to a listener:
gateway(path, present), call(path, number, state), call_removed(path, ended).
ended is False when the service itself vanished (the call may still be going on
the phone), so it is not logged as a finished call.
"""
from gi.repository import Gio, GLib

from .dbuserror import remote_message

SERVICE = "org.pipewire.Telephony"
MANAGER_PATH = "/org/pipewire/Telephony"
MANAGER = "org.ofono.Manager"
CALL_MANAGER = "org.ofono.VoiceCallManager"
VOICE_CALL = "org.ofono.VoiceCall"
GATEWAY = "org.pipewire.Telephony.AudioGateway1"
CALL = "org.pipewire.Telephony.Call1"


def _items(value):
    """GetModems/GetCalls return a{oa{sv}} here; accept ofono's a(oa{sv}) as well."""
    return list(value.items()) if isinstance(value, dict) else list(value)


class Telephony:
    def __init__(self, bus, listener):
        self._bus = bus
        self._listener = listener
        self.gateways = set()
        self.calls = {}
        self._owner = None  # unique bus name of the running service
        handlers = {
            (MANAGER, "ModemAdded"): self._on_modem_added,
            (MANAGER, "ModemRemoved"): self._on_modem_removed,
            (CALL_MANAGER, "CallAdded"): self._on_call_added,
            (CALL_MANAGER, "CallRemoved"): self._on_call_removed,
            (VOICE_CALL, "PropertyChanged"): self._on_property_changed,
        }
        for (iface, member), handler in handlers.items():
            # Subscribed with sender=None so it keeps working when the service
            # restarts with a new unique name; on_signal then drops anything not
            # sent by the service's current owner, so no other bus client can
            # make up calls or remove the phone.
            bus.signal_subscribe(None, iface, member, None, None, Gio.DBusSignalFlags.NONE,
                                 self._signal_handler(handler))
        Gio.bus_watch_name_on_connection(bus, SERVICE, Gio.BusNameWatcherFlags.NONE,
                                         self._on_appeared, self._on_vanished)

    def _signal_handler(self, handler):
        def on_signal(_conn, sender, path, _iface, _member, params):
            if sender == self._owner and path.startswith(MANAGER_PATH):
                handler(path, params.unpack())
        return on_signal

    def first_gateway(self):
        return min(self.gateways) if self.gateways else None

    def dial(self, number, on_error):
        self._on_gateway(GATEWAY, "Dial", GLib.Variant("(s)", (number,)), on_error)

    def send_tones(self, digits, on_error):
        self._on_gateway(GATEWAY, "SendTones", GLib.Variant("(s)", (digits,)), on_error)

    def answer(self, path, on_error):
        self._invoke(path, CALL, "Answer", None, on_error)

    def hangup(self, path, on_error):
        self._invoke(path, CALL, "Hangup", None, on_error)

    def _on_gateway(self, iface, method, params, on_error):
        gateway = self.first_gateway()
        if gateway is None:
            on_error("Phone not connected")
            return
        self._invoke(gateway, iface, method, params, on_error)

    def _invoke(self, path, iface, method, params, on_error):
        def done(bus, result):
            try:
                bus.call_finish(result)
            except GLib.Error as error:
                on_error(remote_message(error))
        self._bus.call(SERVICE, path, iface, method, params, None, Gio.DBusCallFlags.NONE, 10000, None, done)

    def _on_appeared(self, _bus, _name, owner):
        self._owner = owner
        self._bus.call(SERVICE, MANAGER_PATH, MANAGER, "GetModems", None, None,
                       Gio.DBusCallFlags.NONE, 5000, None, self._on_modems)

    def _on_modems(self, bus, result):
        try:
            (modems,) = bus.call_finish(result).unpack()
        except GLib.Error:
            return
        for path, _props in _items(modems):
            self._add_gateway(path)

    def _add_gateway(self, path):
        if path not in self.gateways:
            self.gateways.add(path)
            self._listener.gateway(path, True)
        self._bus.call(SERVICE, path, CALL_MANAGER, "GetCalls", None, None,
                       Gio.DBusCallFlags.NONE, 5000, None, self._on_calls)

    def _on_calls(self, bus, result):
        try:
            (calls,) = bus.call_finish(result).unpack()
        except GLib.Error:
            return
        for path, props in _items(calls):
            self._update_call(path, props)

    def _on_vanished(self, _bus, _name):
        self._owner = None
        for path in list(self.calls):
            self._drop_call(path, ended=False)
        for path in sorted(self.gateways):
            self._listener.gateway(path, False)
        self.gateways.clear()

    def _on_modem_added(self, _path, args):
        self._add_gateway(args[0])

    def _on_modem_removed(self, _path, args):
        gateway = args[0]
        for path in [p for p in self.calls if p.startswith(gateway + "/")]:
            self._drop_call(path, ended=True)
        if gateway in self.gateways:
            self.gateways.discard(gateway)
            self._listener.gateway(gateway, False)

    def _on_call_added(self, _path, args):
        self._update_call(args[0], args[1])

    def _on_call_removed(self, _path, args):
        if args[0] in self.calls:
            self._drop_call(args[0], ended=True)

    def _on_property_changed(self, path, args):
        name, value = args
        if path in self.calls and name in ("State", "LineIdentification"):
            self._update_call(path, {name: value})

    def _update_call(self, path, props):
        old = self.calls.get(path, {"number": "", "state": ""})
        new = {"number": props.get("LineIdentification", old["number"]),
               "state": props.get("State", old["state"])}
        if new != self.calls.get(path):
            self.calls[path] = new
            self._listener.call(path, new["number"], new["state"])

    def _drop_call(self, path, ended):
        del self.calls[path]
        self._listener.call_removed(path, ended)
