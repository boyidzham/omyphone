"""Fake org.pipewire.Telephony for the integration tests.

Implements what omyphone uses from PipeWire's spa/plugins/bluez5/README-Telephony.md,
plus a control interface (org.omyphone.Test at /org/omyphone/Test) that tests use
to add a gateway, create calls, change their state and read what was called.
"""
import warnings

warnings.filterwarnings("ignore", category=DeprecationWarning)

from gi.repository import Gio, GLib  # noqa: E402

NAME = "org.pipewire.Telephony"
ROOT = "/org/pipewire/Telephony"
GW = ROOT + "/ag1"
INVALID_STATE = "org.pipewire.Telephony.Error.InvalidState"

XML = """
<node>
  <interface name="org.ofono.Manager">
    <method name="GetModems"><arg type="a{oa{sv}}" direction="out"/></method>
    <signal name="ModemAdded"><arg type="o"/><arg type="a{sv}"/></signal>
    <signal name="ModemRemoved"><arg type="o"/></signal>
  </interface>
  <interface name="org.pipewire.Telephony.AudioGateway1">
    <method name="Dial"><arg type="s" direction="in"/></method>
    <method name="SendTones"><arg type="s" direction="in"/></method>
  </interface>
  <interface name="org.ofono.VoiceCallManager">
    <method name="GetCalls"><arg type="a{oa{sv}}" direction="out"/></method>
    <signal name="CallAdded"><arg type="o"/><arg type="a{sv}"/></signal>
    <signal name="CallRemoved"><arg type="o"/></signal>
  </interface>
  <interface name="org.pipewire.Telephony.Call1">
    <method name="Answer"/>
    <method name="Hangup"/>
  </interface>
  <interface name="org.ofono.VoiceCall">
    <signal name="PropertyChanged"><arg type="s"/><arg type="v"/></signal>
  </interface>
  <interface name="org.omyphone.Test">
    <method name="AddGateway"/>
    <method name="RemoveGateway"/>
    <method name="AddCall">
      <arg type="s" direction="in"/><arg type="s" direction="in"/><arg type="o" direction="out"/>
    </method>
    <method name="SetState"><arg type="o" direction="in"/><arg type="s" direction="in"/></method>
    <method name="RemoveCall"><arg type="o" direction="in"/></method>
    <method name="Log"><arg type="as" direction="out"/></method>
  </interface>
</node>
"""
IFACES = {i.name: i for i in Gio.DBusNodeInfo.new_for_xml(XML).interfaces}


class InvalidState(Exception):
    pass


class FakeTelephony:
    def __init__(self, conn):
        self.conn = conn
        self.gateway_ids = []
        self.calls = {}
        self.counter = 0
        self.log = []
        conn.register_object(ROOT, IFACES["org.ofono.Manager"], self.on_method, None, None)
        conn.register_object("/org/omyphone/Test", IFACES["org.omyphone.Test"], self.on_method, None, None)

    def emit(self, path, iface, name, signature, args):
        self.conn.emit_signal(None, path, iface, name, GLib.Variant(signature, args))

    def props(self, path):
        call = self.calls[path]
        return {"LineIdentification": GLib.Variant("s", call["number"]),
                "State": GLib.Variant("s", call["state"]),
                "Name": GLib.Variant("s", ""), "Multiparty": GLib.Variant("b", False)}

    def add_gateway(self):
        if self.gateway_ids:
            return
        for name in ("org.pipewire.Telephony.AudioGateway1", "org.ofono.VoiceCallManager"):
            self.gateway_ids.append(self.conn.register_object(GW, IFACES[name], self.on_method, None, None))
        self.emit(ROOT, "org.ofono.Manager", "ModemAdded", "(oa{sv})", (GW, {}))

    def remove_gateway(self):
        # Like a phone going out of range: calls vanish without CallRemoved.
        for path in list(self.calls):
            self.drop_call(path, announce=False)
        for reg in self.gateway_ids:
            self.conn.unregister_object(reg)
        self.gateway_ids = []
        self.emit(ROOT, "org.ofono.Manager", "ModemRemoved", "(o)", (GW,))

    def add_call(self, number, state):
        self.counter += 1
        path = f"{GW}/call{self.counter}"
        ids = [self.conn.register_object(path, IFACES[n], self.on_method, None, None)
               for n in ("org.pipewire.Telephony.Call1", "org.ofono.VoiceCall")]
        self.calls[path] = {"number": number, "state": state, "ids": ids}
        self.emit(GW, "org.ofono.VoiceCallManager", "CallAdded", "(oa{sv})", (path, self.props(path)))
        return path

    def set_state(self, path, state):
        self.calls[path]["state"] = state
        self.emit(path, "org.ofono.VoiceCall", "PropertyChanged", "(sv)", ("State", GLib.Variant("s", state)))

    def drop_call(self, path, announce=True):
        call = self.calls.pop(path)
        if announce:
            self.emit(path, "org.ofono.VoiceCall", "PropertyChanged", "(sv)",
                      ("State", GLib.Variant("s", "disconnected")))
        for reg in call["ids"]:
            self.conn.unregister_object(reg)
        if announce:
            self.emit(GW, "org.ofono.VoiceCallManager", "CallRemoved", "(o)", (path,))

    def on_method(self, conn, sender, path, iface, method, params, invocation):
        try:
            invocation.return_value(self.dispatch(path, method, params.unpack()))
        except InvalidState as error:
            invocation.return_dbus_error(INVALID_STATE, str(error))
        except KeyError:
            invocation.return_dbus_error("org.freedesktop.DBus.Error.UnknownObject", path)

    def dispatch(self, path, method, args):
        if method == "GetModems":
            return GLib.Variant("(a{oa{sv}})", ({GW: {}} if self.gateway_ids else {},))
        if method == "GetCalls":
            return GLib.Variant("(a{oa{sv}})", ({p: self.props(p) for p in self.calls},))
        if method == "Dial":
            self.log.append(f"Dial {args[0]}")
            self.add_call(args[0], "dialing")
            return None
        if method == "SendTones":
            self.log.append(f"SendTones {args[0]}")
            return None
        if method == "Answer":
            self.log.append(f"Answer {path}")
            if self.calls[path]["state"] != "incoming":
                raise InvalidState("call is not incoming")
            self.set_state(path, "active")
            return None
        if method == "Hangup":
            self.log.append(f"Hangup {path}")
            self.drop_call(path)
            return None
        if method == "AddGateway":
            self.add_gateway()
            return None
        if method == "RemoveGateway":
            self.remove_gateway()
            return None
        if method == "AddCall":
            return GLib.Variant("(o)", (self.add_call(*args),))
        if method == "SetState":
            self.set_state(*args)
            return None
        if method == "RemoveCall":
            self.drop_call(args[0])
            return None
        if method == "Log":
            return GLib.Variant("(as)", (self.log,))
        raise KeyError(method)


def main():
    loop = GLib.MainLoop()
    fakes = []
    Gio.bus_own_name(Gio.BusType.SESSION, NAME, Gio.BusNameOwnerFlags.NONE,
                     lambda conn, name: fakes.append(FakeTelephony(conn)),
                     lambda conn, name: None,
                     lambda conn, name: loop.quit())
    loop.run()


if __name__ == "__main__":
    main()
