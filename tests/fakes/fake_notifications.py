"""Fake org.freedesktop.Notifications for the integration tests.

Implements what omyphone uses from the Desktop Notifications Specification,
plus a control interface (org.omyphone.Test at /org/omyphone/Test) that tests
use to read what was notified and to click a notification's action.
"""
import json
import warnings

warnings.filterwarnings("ignore", category=DeprecationWarning)

from gi.repository import Gio, GLib  # noqa: E402

NAME = "org.freedesktop.Notifications"
PATH = "/org/freedesktop/Notifications"

XML = """
<node>
  <interface name="org.freedesktop.Notifications">
    <method name="Notify">
      <arg type="s" direction="in"/><arg type="u" direction="in"/><arg type="s" direction="in"/>
      <arg type="s" direction="in"/><arg type="s" direction="in"/><arg type="as" direction="in"/>
      <arg type="a{sv}" direction="in"/><arg type="i" direction="in"/><arg type="u" direction="out"/>
    </method>
    <method name="CloseNotification"><arg type="u" direction="in"/></method>
    <signal name="ActionInvoked"><arg type="u"/><arg type="s"/></signal>
    <signal name="NotificationClosed"><arg type="u"/><arg type="u"/></signal>
  </interface>
  <interface name="org.omyphone.Test">
    <method name="Log"><arg type="as" direction="out"/></method>
    <method name="Invoke"><arg type="u" direction="in"/><arg type="s" direction="in"/></method>
  </interface>
</node>
"""
IFACES = {i.name: i for i in Gio.DBusNodeInfo.new_for_xml(XML).interfaces}


class FakeNotifications:
    def __init__(self, conn):
        self.conn = conn
        self.log = []  # one JSON object per Notify call
        self.next_id = 1
        conn.register_object(PATH, IFACES[NAME], self.on_method, None, None)
        conn.register_object("/org/omyphone/Test", IFACES["org.omyphone.Test"], self.on_method, None, None)

    def emit(self, name, signature, args):
        self.conn.emit_signal(None, PATH, NAME, name, GLib.Variant(signature, args))

    def on_method(self, conn, sender, path, iface, method, params, invocation):
        args = params.unpack()
        if method == "Notify":
            app, _replaces, _icon, summary, body, actions, _hints, _timeout = args
            self.log.append(json.dumps({"id": self.next_id, "app": app, "summary": summary, "body": body,
                                        "actions": actions}))
            invocation.return_value(GLib.Variant("(u)", (self.next_id,)))
            self.next_id += 1
        elif method == "CloseNotification":
            invocation.return_value(None)
            self.emit("NotificationClosed", "(uu)", (args[0], 3))
        elif method == "Log":
            invocation.return_value(GLib.Variant("(as)", (self.log,)))
        elif method == "Invoke":
            invocation.return_value(None)
            self.emit("ActionInvoked", "(us)", args)
            self.emit("NotificationClosed", "(uu)", (args[0], 2))


def main():
    loop = GLib.MainLoop()
    fakes = []
    Gio.bus_own_name(Gio.BusType.SESSION, NAME, Gio.BusNameOwnerFlags.NONE,
                     lambda conn, name: fakes.append(FakeNotifications(conn)),
                     lambda conn, name: None,
                     lambda conn, name: loop.quit())
    loop.run()


if __name__ == "__main__":
    main()
