"""Shared pieces for the integration tests: fake services, the helper process,
and readers for what the stub commands recorded.

Integration tests need their own D-Bus session bus. tests/run.sh provides one
(dbus-run-session) and sets OMYPHONE_TEST_BUS=1; without it they skip, so they
never touch the real desktop bus.
"""
import json
import os
import queue
import subprocess
import sys
import threading
import time
import unittest
from pathlib import Path

from gi.repository import Gio, GLib

ROOT = Path(__file__).resolve().parents[1]
FAKES = ROOT / "tests" / "fakes"
STUBS = ROOT / "tests" / "stubs"
HELPER = ROOT / "helper" / "omyphone-helper"

needs_test_bus = unittest.skipUnless(os.environ.get("OMYPHONE_TEST_BUS") == "1",
                                     "needs tests/run.sh (private D-Bus bus)")


def wait_until(check, timeout=5.0, message="condition not met in time"):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = check()
        if result:
            return result
        time.sleep(0.05)
    raise AssertionError(message)


def bus():
    return Gio.bus_get_sync(Gio.BusType.SESSION, None)


def name_has_owner(name):
    reply = bus().call_sync("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus",
                            "NameHasOwner", GLib.Variant("(s)", (name,)), GLib.VariantType("(b)"),
                            Gio.DBusCallFlags.NONE, 2000, None)
    return reply.unpack()[0]


def pid_alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


class Fake:
    """A fake D-Bus service running as its own process."""

    def __init__(self, script, name):
        self.name = name
        self.proc = subprocess.Popen([sys.executable, str(FAKES / script)])
        wait_until(lambda: name_has_owner(name), message=f"{name} did not appear")

    def control(self, method, signature=None, args=None, reply=None):
        params = GLib.Variant(signature, args) if signature else None
        result = bus().call_sync(self.name, "/org/omyphone/Test", "org.omyphone.Test", method, params,
                                 GLib.VariantType(reply) if reply else None,
                                 Gio.DBusCallFlags.NONE, 5000, None)
        return result.unpack()

    def log(self):
        return self.control("Log", reply="(as)")[0]

    def stop(self):
        if self.proc.poll() is None:
            self.proc.terminate()
            self.proc.wait(5)
        wait_until(lambda: not name_has_owner(self.name), message=f"{self.name} did not go away")


class Helper:
    """The real helper as a subprocess, with stubs first on PATH and fast timers."""

    def __init__(self, workdir, args=()):
        workdir = Path(workdir)
        env = dict(os.environ,
                   PATH=f"{STUBS}:{os.environ['PATH']}",
                   OMYPHONE_STUB_DIR=str(workdir),
                   XDG_STATE_HOME=str(workdir / "state"),
                   XDG_RUNTIME_DIR=str(workdir / "run"),
                   OMYPHONE_BLUEZ_BUS="session",
                   OMYPHONE_POLL_SECONDS="0.2",
                   OMYPHONE_RETRY_SECONDS="1",
                   OMYPHONE_CONTACTS_RETRY_SECONDS="0.2",
                   OMYPHONE_CONTACTS_RETRY_WINDOW_SECONDS="10",
                   OMYPHONE_INSTALL_CHECK_SECONDS="0.2",
                   OMYPHONE_HISTORY_DELAY_SECONDS="0.2")
        self.proc = subprocess.Popen([sys.executable, str(HELPER), *args], stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, text=True, env=env)
        self._events = queue.Queue()
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        for line in self.proc.stdout:
            self._events.put(json.loads(line))
        self._events.put(None)

    def send(self, message):
        text = message if isinstance(message, str) else json.dumps(message)
        self.proc.stdin.write(text + "\n")
        self.proc.stdin.flush()

    def wait_for(self, match, timeout=5.0):
        """Return the next event for which match(event) is true, skipping others."""
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise AssertionError("expected helper event not seen")
            try:
                event = self._events.get(timeout=remaining)
            except queue.Empty:
                raise AssertionError("expected helper event not seen") from None
            if event is None:
                raise AssertionError("helper exited")
            if match(event):
                return event

    def close(self):
        if self.proc.poll() is None:
            self.proc.stdin.close()
            try:
                self.proc.wait(5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait()


class Stubs:
    """What the stub notify-send and wpctl recorded, and a way to click a button."""

    def __init__(self, workdir):
        self.dir = Path(workdir)

    def _lines(self, name):
        path = self.dir / name
        return path.read_text().splitlines() if path.exists() else []

    def notifications(self):
        return [json.loads(line) for line in self._lines("notify.log")]

    def wait_notification(self, title):
        return wait_until(lambda: next((n for n in self.notifications() if title in n), None),
                          message=f"no notification titled {title!r}")

    def choose(self, action):
        tmp = self.dir / "action.tmp"
        tmp.write_text(action + "\n")
        tmp.rename(self.dir / "action")

    def wpctl(self):
        return self._lines("wpctl.log")

    def terminal(self):
        return [json.loads(line) for line in self._lines("terminal.log")]

    def notify_pids(self):
        return [int(line) for line in self._lines("notify.pids")]
