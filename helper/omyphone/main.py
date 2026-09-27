"""Helper entry point: omyphone-helper [--phone ADDRESS].

Reads JSON-line commands from stdin and writes JSON-line events to stdout. Exits
when stdin closes, so it goes away with the shell that started it.
"""
import argparse
import os
import sys

import gi
from gi.repository import Gio, GLib

try:
    gi.require_version("GioUnix", "2.0")
    from gi.repository import GioUnix
    UnixInputStream = GioUnix.InputStream
except (ValueError, ImportError):
    UnixInputStream = Gio.UnixInputStream

from .engine import Engine
from .protocol import encode_event
from .recents import default_path


def main(argv=None):
    parser = argparse.ArgumentParser(prog="omyphone-helper")
    parser.add_argument("--phone", default="", help="Bluetooth address of the phone (default: auto-detect)")
    args = parser.parse_args(argv)

    session = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    if os.environ.get("OMYPHONE_BLUEZ_BUS") == "session":
        bluez_bus = session
    else:
        bluez_bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
    loop = GLib.MainLoop()

    def emit(event, **fields):
        try:
            sys.stdout.write(encode_event(event, **fields) + "\n")
            sys.stdout.flush()
        except BrokenPipeError:
            loop.quit()

    engine = Engine(emit, session, bluez_bus, default_path(), address=args.phone or None,
                    poll_s=float(os.environ.get("OMYPHONE_POLL_SECONDS", "5")),
                    retry_s=float(os.environ.get("OMYPHONE_RETRY_SECONDS", "30")))
    engine.start()

    stdin = Gio.DataInputStream.new(UnixInputStream.new(0, False))

    def on_line(stream, result):
        try:
            line, _length = stream.read_line_finish_utf8(result)
        except GLib.Error:
            line = None
        if line is None:
            loop.quit()
            return
        if line.strip():
            engine.handle_line(line)
        stream.read_line_async(GLib.PRIORITY_DEFAULT, None, on_line)

    stdin.read_line_async(GLib.PRIORITY_DEFAULT, None, on_line)
    loop.run()
    engine.stop()
    return 0
