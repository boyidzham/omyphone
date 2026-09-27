"""Fake org.bluez for the integration tests: one adapter and one HFP phone.

Control interface org.omyphone.Test at /org/omyphone/Test switches the phone's
connected/paired state, the adapter's power, and whether Connect fails.
"""
import warnings

warnings.filterwarnings("ignore", category=DeprecationWarning)

from gi.repository import Gio, GLib  # noqa: E402

NAME = "org.bluez"
ADAPTER = "/org/bluez/hci0"
DEVICE = ADAPTER + "/dev_AA_BB_CC_DD_EE_FF"
HFP_AG = "0000111f-0000-1000-8000-00805f9b34fb"

XML = """
<node>
  <interface name="org.freedesktop.DBus.ObjectManager">
    <method name="GetManagedObjects"><arg type="a{oa{sa{sv}}}" direction="out"/></method>
  </interface>
  <interface name="org.bluez.Device1">
    <method name="Connect"/>
  </interface>
  <interface name="org.omyphone.Test">
    <method name="SetConnected"><arg type="b" direction="in"/></method>
    <method name="SetPowered"><arg type="b" direction="in"/></method>
    <method name="SetPaired"><arg type="b" direction="in"/></method>
    <method name="SetConnectFails"><arg type="b" direction="in"/></method>
    <method name="Log"><arg type="as" direction="out"/></method>
  </interface>
</node>
"""
IFACES = {i.name: i for i in Gio.DBusNodeInfo.new_for_xml(XML).interfaces}


class FakeBluez:
    def __init__(self, conn):
        self.state = {"connected": True, "powered": True, "paired": True, "fails": False}
        self.log = []
        conn.register_object("/", IFACES["org.freedesktop.DBus.ObjectManager"], self.on_method, None, None)
        conn.register_object(DEVICE, IFACES["org.bluez.Device1"], self.on_method, None, None)
        conn.register_object("/org/omyphone/Test", IFACES["org.omyphone.Test"], self.on_method, None, None)

    def objects(self):
        s = self.state
        return {
            ADAPTER: {"org.bluez.Adapter1": {"Address": GLib.Variant("s", "00:11:22:33:44:55"),
                                             "Powered": GLib.Variant("b", s["powered"])}},
            DEVICE: {"org.bluez.Device1": {
                "Address": GLib.Variant("s", "AA:BB:CC:DD:EE:FF"),
                "Name": GLib.Variant("s", "Test Phone"),
                "Alias": GLib.Variant("s", "Test Phone"),
                "Paired": GLib.Variant("b", s["paired"]),
                "Connected": GLib.Variant("b", s["connected"]),
                "Adapter": GLib.Variant("o", ADAPTER),
                "UUIDs": GLib.Variant("as", [HFP_AG, "0000112f-0000-1000-8000-00805f9b34fb"]),
            }},
        }

    def on_method(self, conn, sender, path, iface, method, params, invocation):
        args = params.unpack()
        if method == "GetManagedObjects":
            invocation.return_value(GLib.Variant("(a{oa{sa{sv}}})", (self.objects(),)))
        elif method == "Connect":
            self.log.append("Connect")
            if self.state["fails"] or not self.state["powered"]:
                invocation.return_dbus_error("org.bluez.Error.Failed", "br-connection-page-timeout")
            else:
                self.state["connected"] = True
                invocation.return_value(None)
        elif method == "Log":
            invocation.return_value(GLib.Variant("(as)", (self.log,)))
        else:
            key = {"SetConnected": "connected", "SetPowered": "powered",
                   "SetPaired": "paired", "SetConnectFails": "fails"}[method]
            self.state[key] = args[0]
            invocation.return_value(None)


def main():
    loop = GLib.MainLoop()
    fakes = []
    Gio.bus_own_name(Gio.BusType.SESSION, NAME, Gio.BusNameOwnerFlags.NONE,
                     lambda conn, name: fakes.append(FakeBluez(conn)),
                     lambda conn, name: None,
                     lambda conn, name: loop.quit())
    loop.run()


if __name__ == "__main__":
    main()
