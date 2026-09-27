"""Connects telephony, contacts, recents, mic and notifications, and handles commands."""
import time
from pathlib import Path

from .bluez import PhoneLink
from .calllog import CallLog
from .contacts import ContactsStore, Directory, HistoryStore, rows
from .mic import Mic
from .notifier import Notifier
from .phonebook import Phonebook, default_tmpdir
from .protocol import ProtocolError, parse_command
from .recents import Recents, merge
from .sync import ContactsSync
from .telephony import Telephony


class Engine:
    def __init__(self, emit, session_bus, bluez_bus, recents_path, address=None, poll_s=5.0, retry_s=30.0,
                 contacts_timing=None):
        self._emit = emit
        self._session_bus = session_bus
        self._bluez_bus = bluez_bus
        self._address = address
        self._poll_s = poll_s
        self._retry_s = retry_s
        self._tracked = set()
        self.recents = Recents(recents_path)
        self.calllog = CallLog(time.time)
        self.mic = Mic(state_path=Path(recents_path).parent / "mic-before-call")
        self.notifier = Notifier(lambda tab: self._emit("show", tab=tab))
        self.telephony = None
        self.link = None
        state_dir = Path(recents_path).parent
        self._contacts_store = ContactsStore(state_dir / "contacts.json")
        self._history_store = HistoryStore(state_dir / "history.json")
        self._contacts_timing = contacts_timing or {}
        self.directory = Directory(self._contacts_store.contacts)
        self._phone_address = None
        self.contacts = None

    def start(self):
        # Contacts first: PhoneLink reports the phone (and so triggers a sync) as soon as it exists.
        self.contacts = ContactsSync(Phonebook(self._session_bus, default_tmpdir()), self._contacts_store,
                                     self._history_store, self, lambda: self._phone_address,
                                     **self._contacts_timing)
        self._emit("contacts", entries=rows(self._contacts_store.contacts))
        self.contacts.start()
        self._emit_recents()
        self._emit("muted", muted=False)
        self.telephony = Telephony(self._session_bus, self)
        self.link = PhoneLink(self._bluez_bus, self, self._address, poll_s=self._poll_s, retry_s=self._retry_s)

    def stop(self):
        self.notifier.close_all()
        self.mic.restore()

    # --- listener methods (Telephony, PhoneLink) ---

    def phone(self, status):
        connected = status["found"] and status["connected"]
        was_connected = self._phone_address is not None
        self._phone_address = status["address"] if connected else None
        self._emit("phone", **status)
        if connected and not was_connected:
            self.contacts.connected()

    def gateway(self, path, present):
        self._emit("gateway", path=path, present=present)

    def call(self, path, number, state):
        if not self._tracked:
            self._emit("muted", muted=self.mic.refresh())
        self._tracked.add(path)
        self.calllog.update(path, number, state)
        self._emit("call", path=path, number=number, state=state, name=self.directory.lookup(number))

    def call_removed(self, path, ended):
        self._tracked.discard(path)
        entry = self.calllog.remove(path)
        self._emit("call-removed", path=path)
        if ended and entry is not None:
            self.recents.add(entry)
            if entry["direction"] == "missed":
                self.notifier.missed(entry["number"], self.directory.lookup(entry["number"]))
            self._emit_recents()
            self.contacts.call_ended()
        if not self._tracked:
            self.mic.restore()
            self._emit("muted", muted=self.mic.muted)

    # --- listener methods (ContactsSync) ---

    def contacts_status(self, status):
        self._emit("contacts-status", **status)

    def contacts_changed(self):
        self.directory = Directory(self._contacts_store.contacts)
        self._emit("contacts", entries=rows(self._contacts_store.contacts))
        self._emit_recents()

    def history_changed(self):
        self._emit_recents()

    def _emit_recents(self):
        history = self._history_store
        synced = history.synced > 0
        local_missed = [e for e in self.recents.entries if e["direction"] == "missed"]
        self._emit("recents",
                   entries=[self._named(e) for e in merge(self.recents.entries, history.calls if synced else None)],
                   missed=[self._named(e) for e in merge(local_missed, history.missed if synced else None)])

    def _named(self, entry):
        return {**entry, "name": self.directory.lookup(entry["number"]) or entry.get("name", "")}

    # --- commands ---

    def handle_line(self, line):
        try:
            cmd = parse_command(line)
        except ProtocolError as error:
            self._emit("error", cmd=error.cmd, message=str(error))
            return
        name = cmd["cmd"]

        def on_error(message):
            self._emit("error", cmd=name, message=message)

        if name == "dial":
            self.telephony.dial(cmd["number"], on_error)
        elif name == "answer":
            self.telephony.answer(cmd["call"], on_error)
        elif name == "hangup":
            self.telephony.hangup(cmd["call"], on_error)
        elif name == "decline":
            self.calllog.mark_declined(cmd["call"])
            self.telephony.hangup(cmd["call"], on_error)
        elif name == "tones":
            self.telephony.send_tones(cmd["digits"], on_error)
        elif name == "sync-contacts":
            self.contacts.user_sync()
        elif name == "install-contacts":
            self.contacts.install()
        elif name == "mute":
            if not self._tracked:
                on_error("No active call")
                return
            self.mic.set_muted(cmd["on"])
            self._emit("muted", muted=self.mic.muted)
