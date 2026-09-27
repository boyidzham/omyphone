"""Readable messages from D-Bus error replies."""
from gi.repository import Gio


def remote_message(error):
    """The human part of a D-Bus error reply, without the GDBus.Error:<name>: prefix.

    Gio.DBusError.strip_remote_error(error) is documented to remove this prefix
    in place, but on this machine's PyGObject/GLib it mutates a temporary copy:
    it returns True yet error.message (and even error.copy().message) still
    carry the prefix. Gio.DBusError.get_remote_error(error) does correctly
    return the parsed error name, so the known prefix is stripped by hand.
    """
    name = Gio.DBusError.get_remote_error(error)
    if name:
        prefix = f"GDBus.Error:{name}: "
        if error.message.startswith(prefix):
            return error.message[len(prefix):]
    return error.message
