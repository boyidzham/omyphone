"""Fake org.bluez.obex (BlueZ obexd) for the integration tests.

Serves tests/fixtures/<folder>.vcf over a PBAP-shaped API, with CRLF line ends
like a real phone. Control interface org.omyphone.Test at /org/omyphone/Test:
SetMode(normal | empty | error | refuse | vanish) and Log().
"""
import warnings
from pathlib import Path

warnings.filterwarnings("ignore", category=DeprecationWarning)

from gi.repository import Gio, GLib  # noqa: E402

NAME = "org.bluez.obex"
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"

XML = """
<node>
  <interface name="org.bluez.obex.Client1">
    <method name="CreateSession">
      <arg type="s" direction="in"/><arg type="a{sv}" direction="in"/><arg type="o" direction="out"/>
    </method>
    <method name="RemoveSession"><arg type="o" direction="in"/></method>
  </interface>
  <interface name="org.bluez.obex.PhonebookAccess1">
    <method name="Select"><arg type="s" direction="in"/><arg type="s" direction="in"/></method>
    <method name="PullAll">
      <arg type="s" direction="in"/><arg type="a{sv}" direction="in"/>
      <arg type="o" direction="out"/><arg type="a{sv}" direction="out"/>
    </method>
  </interface>
  <interface name="org.bluez.obex.Transfer1">
    <property name="Status" type="s" access="read"/>
  </interface>
  <interface name="org.omyphone.Test">
    <method name="SetMode"><arg type="s" direction="in"/></method>
    <method name="Log"><arg type="as" direction="out"/></method>
  </interface>
</node>
"""
IFACES = {i.name: i for i in Gio.DBusNodeInfo.new_for_xml(XML).interfaces}


class FakeObex:
    def __init__(self, conn):
        self.conn = conn
        self.mode = "normal"
        self.log = []
        self.count = 0
        self.sessions = {}   # path -> {"id": registration id, "folder": str}
        self.reads = {}      # transfer path -> Status reads so far
        conn.register_object("/org/bluez/obex", IFACES["org.bluez.obex.Client1"], self.on_method, None, None)
        conn.register_object("/org/omyphone/Test", IFACES["org.omyphone.Test"], self.on_method, None, None)

    def on_method(self, conn, sender, path, iface, method, params, invocation):
        args = params.unpack()
        if method == "CreateSession":
            self.log.append(f"CreateSession {args[0]} {args[1].get('Target', '')}")
            if self.mode == "refuse":
                invocation.return_dbus_error("org.bluez.obex.Error.Failed", "Unable to connect")
                return
            self.count += 1
            session = f"/org/bluez/obex/client/session{self.count}"
            reg = conn.register_object(session, IFACES["org.bluez.obex.PhonebookAccess1"],
                                       self.on_method, None, None)
            self.sessions[session] = {"id": reg, "folder": ""}
            invocation.return_value(GLib.Variant("(o)", (session,)))
        elif method == "RemoveSession":
            self.log.append("RemoveSession")
            session = self.sessions.pop(args[0], None)
            if session:
                conn.unregister_object(session["id"])
            invocation.return_value(None)
        elif method == "Select":
            self.log.append(f"Select {args[1]}")
            self.sessions[path]["folder"] = args[1]
            invocation.return_value(None)
        elif method == "PullAll":
            folder = self.sessions[path]["folder"]
            self.log.append(f"PullAll {folder} {args[1].get('Format', '')}")
            if self.mode == "error":
                invocation.return_dbus_error("org.bluez.obex.Error.Failed", "Transfer failed")
                return
            fixture = FIXTURES / f"{folder}.vcf"
            text = fixture.read_text() if self.mode != "empty" and fixture.exists() else ""
            Path(args[0]).write_text(text.replace("\n", "\r\n"), newline="")
            self.count += 1
            transfer = f"{path}/transfer{self.count}"
            if self.mode != "vanish":
                self.reads[transfer] = 0
                conn.register_object(transfer, IFACES["org.bluez.obex.Transfer1"], None,
                                     self.get_property, None)
            invocation.return_value(GLib.Variant("(oa{sv})", (transfer, {})))
        elif method == "SetMode":
            self.mode = args[0]
            invocation.return_value(None)
        elif method == "Log":
            invocation.return_value(GLib.Variant("(as)", (self.log,)))

    def get_property(self, conn, sender, path, iface, prop):
        self.reads[path] = self.reads.get(path, 0) + 1
        return GLib.Variant("s", "queued" if self.reads[path] == 1 else "complete")


def main():
    loop = GLib.MainLoop()
    fakes = []
    Gio.bus_own_name(Gio.BusType.SESSION, NAME, Gio.BusNameOwnerFlags.NONE,
                     lambda conn, name: fakes.append(FakeObex(conn)),
                     lambda conn, name: None,
                     lambda conn, name: loop.quit())
    loop.run()


if __name__ == "__main__":
    main()
