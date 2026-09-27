"""Connects telephony, recents, mic and notifications, and handles commands."""
import json
import time

from .calllog import CallLog
from .mic import Mic
from .notifier import Notifier
from .protocol import ProtocolError, parse_command
from .recents import Recents
from .telephony import Telephony


class Engine:
    def __init__(self, emit, session_bus, bluez_bus, recents_path, address=None, poll_s=5.0, retry_s=30.0):
        self._emit = emit
        self._session_bus = session_bus
        self._bluez_bus = bluez_bus
        self._address = address
        self._poll_s = poll_s
        self._retry_s = retry_s
        self._tracked = set()
        self.recents = Recents(recents_path)
        self.calllog = CallLog(time.time)
        self.mic = Mic()
        self.notifier = Notifier(self._on_notification_action, session_bus)
        self.telephony = None

    def start(self):
        self._emit("recents", entries=self.recents.entries)
        self._emit("muted", muted=False)
        self.telephony = Telephony(self._session_bus, self)

    def stop(self):
        self.notifier.close_all()
        self.mic.restore()

    # --- listener methods (Telephony, PhoneLink) ---

    def phone(self, status):
        self._emit("phone", **status)

    def gateway(self, path, present):
        self._emit("gateway", path=path, present=present)

    def call(self, path, number, state):
        if not self._tracked:
            self._emit("muted", muted=self.mic.refresh())
        self._tracked.add(path)
        self.calllog.update(path, number, state)
        if state == "incoming":
            self.notifier.incoming(path, number)
        else:
            self.notifier.close(path)
        self._emit("call", path=path, number=number, state=state)

    def call_removed(self, path, ended):
        self._tracked.discard(path)
        self.notifier.close(path)
        entry = self.calllog.remove(path)
        self._emit("call-removed", path=path)
        if ended and entry is not None:
            self.recents.add(entry)
            if entry["direction"] == "missed":
                self.notifier.missed(entry["number"])
            self._emit("recents", entries=self.recents.entries)
        if not self._tracked:
            self.mic.restore()
            self._emit("muted", muted=self.mic.muted)

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
        elif name == "mute":
            if not self._tracked:
                on_error("No active call")
                return
            self.mic.set_muted(cmd["on"])
            self._emit("muted", muted=self.mic.muted)

    def _on_notification_action(self, path, action):
        # Same path as the popup's buttons, so validation and errors are shared.
        self.handle_line(json.dumps({"cmd": action, "call": path}))
