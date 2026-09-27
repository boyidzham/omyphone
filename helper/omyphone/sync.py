"""Keeps the contacts and call-history caches in sync with the phone.

States (sent to the shell as contacts-status): off (the user never asked),
needs-install (no obexd), syncing, needs-permission (the phone sent nothing:
sharing is not allowed on it yet), ready, error.

Opt-in: nothing is pulled until the user asks once (user_sync or install).
After that, every connect pulls everything and every ended call pulls the
history. The phone only offers its "Sync Contacts" switch after a PC has asked
once, so an empty pull after a user click is retried for a while.
"""
import sys
import time

from gi.repository import Gio, GLib

from . import vcard

INSTALL_ARGV = ["omarchy-launch-floating-terminal-with-presentation", "omarchy-pkg-add", "bluez-obex"]
FULL = ("pb", "cch", "mch")
HISTORY = ("cch", "mch")


def glib_schedule(seconds, fn):
    def run():
        fn()
        return GLib.SOURCE_REMOVE
    GLib.timeout_add(max(1, int(seconds * 1000)), run)


def spawn(argv):
    Gio.Subprocess.new(argv, Gio.SubprocessFlags.NONE)


class ContactsSync:
    def __init__(self, phonebook, contacts, history, listener, address, *, schedule=glib_schedule, spawn=spawn,
                 clock=time.monotonic, wallclock=time.time, retry_s=5.0, retry_window_s=180.0,
                 install_check_s=3.0, install_window_s=600.0, history_delay_s=3.0):
        self._phonebook = phonebook
        self.contacts = contacts
        self.history = history
        self._listener = listener
        self._address = address
        self._schedule = schedule
        self._spawn = spawn
        self._clock = clock
        self._wallclock = wallclock
        self._retry_s = retry_s
        self._retry_window_s = retry_window_s
        self._install_check_s = install_check_s
        self._install_window_s = install_window_s
        self._history_delay_s = history_delay_s
        self.state = "off"
        self.message = ""
        self._busy = False
        self._pending = None          # "full" or "history", run after the current sync
        self._retry_until = 0.0
        self._retry_scheduled = False
        self._install_until = 0.0
        self._install_polling = False

    def start(self):
        initial = "off" if not self.contacts.enabled else "ready" if self.contacts.synced else "needs-permission"
        self._phonebook.available(lambda ok: self._set(initial if ok else "needs-install"))

    def status(self):
        return {"state": self.state, "enabled": self.contacts.enabled,
                "synced": self.contacts.synced, "message": self.message}

    def _set(self, state, message=""):
        self.state, self.message = state, message
        self._listener.contacts_status(self.status())

    # --- triggers ---

    def user_sync(self):
        if not self.contacts.enabled:
            self.contacts.enabled = True
            self.contacts.save()
        self._retry_until = self._clock() + self._retry_window_s
        self._request("full", user=True)

    def connected(self):
        if self.contacts.enabled:
            self._request("full")

    def call_ended(self):
        if self.contacts.enabled:
            self._schedule(self._history_delay_s, lambda: self._request("history"))

    def install(self):
        try:
            self._spawn(INSTALL_ARGV)
        except GLib.Error as error:
            print(f"omyphone: install failed: {error.message}", file=sys.stderr)
            self._set("error", f"Could not open a terminal: {error.message}")
            return
        self._install_until = self._clock() + self._install_window_s
        if not self._install_polling:
            self._install_polling = True
            self._schedule(self._install_check_s, self._check_install)

    def _check_install(self):
        def on_result(ok):
            if ok:
                self._install_polling = False
                self.user_sync()
            elif self._clock() < self._install_until:
                self._schedule(self._install_check_s, self._check_install)
            else:
                self._install_polling = False
        self._phonebook.available(on_result)

    # --- syncing ---

    def _request(self, kind, user=False):
        if self._busy:
            if kind == "full" or self._pending is None:
                self._pending = kind
            return
        address = self._address()
        if not address:
            if user:
                self._set("error", "Phone not connected")
            return
        self._busy = True
        self._phonebook.available(lambda ok: self._start(kind, address, ok))

    def _start(self, kind, address, ok):
        if not ok:
            self._busy = False
            self._pending = None
            self._set("needs-install")
            return
        if kind == "full" and self.state != "needs-permission":
            self._set("syncing")
        self._phonebook.pull(address, FULL if kind == "full" else HISTORY,
                             lambda texts: self._done(kind, texts), self._failed)

    def _done(self, kind, texts):
        self._busy = False
        now = int(self._wallclock())
        if kind == "full":
            cards = vcard.parse_cards(texts.get("pb", ""))
            if not cards:
                self._set("needs-permission")
                if self._clock() < self._retry_until and not self._retry_scheduled:
                    self._retry_scheduled = True
                    self._schedule(self._retry_s, self._run_retry)
            else:
                # The first card is the phone owner's own card (PBAP handle 0).
                self.contacts.contacts = vcard.contacts_from_cards(cards[1:])
                self.contacts.synced = now
                self.contacts.save()
                self._retry_until = 0.0
                self._retry_scheduled = False
                self._listener.contacts_changed()
                self._set("ready")
        calls = vcard.history_from_cards(vcard.parse_cards(texts.get("cch", "")))
        if calls:
            self.history.calls = calls
            self.history.missed = vcard.history_from_cards(vcard.parse_cards(texts.get("mch", "")), "missed")
            self.history.synced = now
            self.history.save()
            self._listener.history_changed()
        self._run_pending()

    def _failed(self, message):
        self._busy = False
        print(f"omyphone: contacts sync failed: {message}", file=sys.stderr)
        self._set("error", message)
        self._run_pending()

    def _run_retry(self):
        self._retry_scheduled = False
        self._request("full")

    def _run_pending(self):
        kind, self._pending = self._pending, None
        if kind:
            self._request(kind)
