"""The real helper with fake BlueZ, telephony and obexd services."""
import json
import os
import stat
import tempfile
import time
import unittest
from pathlib import Path

from tests.harness import Fake, Helper, Stubs, needs_test_bus, wait_until

ADDRESS = "AA:BB:CC:DD:EE:FF"


def is_event(name, **fields):
    return lambda e: e.get("event") == name and all(e.get(k) == v for k, v in fields.items())


@needs_test_bus
class HelperContactsTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.stubs = Stubs(self.dir)
        self.bluez = Fake("fake_bluez.py", "org.bluez")
        self.addCleanup(self.bluez.stop)
        self.telephony = Fake("fake_telephony.py", "org.pipewire.Telephony")
        self.addCleanup(self.telephony.stop)
        self.telephony.control("AddGateway")
        self.obex = None

    def start_obex(self):
        self.obex = Fake("fake_obex.py", "org.bluez.obex")
        self.addCleanup(self.obex.stop)

    def launch_helper(self):
        # Deviation from the brief: split out of start_helper() so tests that need
        # to see the helper's very first contacts-status event can read it before
        # gateway discovery (which needs an extra round trip: GetNameOwner, then
        # GetModems) has a chance to arrive first and get skipped over by a
        # wait_for("gateway") below it. See task-7-report.md.
        self.helper = Helper(self.dir)
        self.addCleanup(self.helper.close)

    def start_helper(self):
        self.launch_helper()
        # Deviation from the brief: wait for both "gateway" and a connected "phone"
        # in one pass (order between them is not guaranteed). sync-contacts needs
        # the phone's address (self._phone_address in Engine, set from the "phone"
        # event); without this wait, tests that send sync-contacts right after
        # start_helper() race PhoneLink's own discovery and can see "Phone not
        # connected" instead of exercising obexd. The fake bluez in this file's
        # setUp always reports the phone connected, so this never blocks. See
        # task-7-report.md.
        seen = {"gateway": False, "phone": False}

        def both(e):
            if e.get("event") == "gateway" and e.get("present") is True:
                seen["gateway"] = True
            elif e.get("event") == "phone" and e.get("connected") is True:
                seen["phone"] = True
            return seen["gateway"] and seen["phone"]

        self.helper.wait_for(both)

    def status(self, state, timeout=5.0):
        return self.helper.wait_for(is_event("contacts-status", state=state), timeout)

    def synced(self):
        self.start_obex()
        self.start_helper()
        self.helper.send({"cmd": "sync-contacts"})
        self.status("ready")

    def test_nothing_sent_to_obexd_before_opt_in(self):
        self.start_obex()
        self.launch_helper()
        self.status("off")
        time.sleep(0.5)
        self.assertEqual(self.obex.log(), [])

    def test_sync_sends_contacts_and_saves_private_files(self):
        self.start_obex()
        self.start_helper()
        self.helper.send({"cmd": "sync-contacts"})
        rows = self.helper.wait_for(lambda e: e.get("event") == "contacts" and e["entries"])["entries"]
        names = [r["name"] for r in rows]
        self.assertIn("Ali Ahmad", names)
        self.assertNotIn("Test Owner", names)
        self.assertEqual(names, sorted(names, key=str.casefold))
        self.status("ready")
        # Deviation from the brief: contacts-status "ready" is emitted (sync.py
        # _done()) before the same call's history.calls/.save() runs, so history.json
        # is not guaranteed to exist yet. The "recents" event with entries is emitted
        # only after history_changed(), i.e. after history.save() -- wait for it
        # before checking the private files. See task-7-report.md.
        self.helper.wait_for(lambda e: e.get("event") == "recents" and e["entries"])
        log = self.obex.log()
        self.assertEqual(log[0], f"CreateSession {ADDRESS} PBAP")
        self.assertIn("RemoveSession", log)
        for name in ("contacts.json", "history.json"):
            path = self.dir / "state" / "omyphone" / name
            self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)

    def test_calls_carry_the_contact_name(self):
        self.synced()
        (known,) = self.telephony.control("AddCall", "(ss)", ("0123456789", "incoming"), "(o)")
        self.assertEqual(self.helper.wait_for(is_event("call", path=known))["name"], "Ali Ahmad")
        (unknown,) = self.telephony.control("AddCall", "(ss)", ("0155", "waiting"), "(o)")
        self.assertEqual(self.helper.wait_for(is_event("call", path=unknown))["name"], "")

    def test_recents_come_from_phone_history_with_names(self):
        self.synced()
        recents = self.helper.wait_for(lambda e: e.get("event") == "recents" and e["entries"])
        self.assertEqual((recents["entries"][0]["name"], recents["entries"][0]["direction"]),
                         ("Ali Ahmad", "outgoing"))
        self.assertEqual(len(recents["missed"]), 2)

    def test_missed_notification_uses_the_name(self):
        self.synced()
        (path,) = self.telephony.control("AddCall", "(ss)", ("+60 12-345 6789", "incoming"), "(o)")
        self.helper.wait_for(is_event("call", path=path))
        self.telephony.control("RemoveCall", "(o)", (path,))
        self.assertEqual(self.stubs.wait_notification("Missed call")[-1], "Ali Ahmad")

    def test_history_synced_again_after_a_call(self):
        self.synced()
        before = self.obex.log().count("Select cch")
        (path,) = self.telephony.control("AddCall", "(ss)", ("0123456789", "active"), "(o)")
        self.helper.wait_for(is_event("call", path=path))
        self.telephony.control("RemoveCall", "(o)", (path,))
        wait_until(lambda: self.obex.log().count("Select cch") > before)
        self.assertEqual(self.obex.log().count("Select pb"), 1)

    def test_phone_not_sharing_then_allowed(self):
        self.start_obex()
        self.obex.control("SetMode", "(s)", ("empty",))
        self.start_helper()
        self.helper.send({"cmd": "sync-contacts"})
        self.status("needs-permission")
        self.obex.control("SetMode", "(s)", ("normal",))
        self.status("ready")

    def test_obexd_missing_then_installed(self):
        self.launch_helper()
        self.status("needs-install")
        self.helper.send({"cmd": "install-contacts"})
        wait_until(lambda: self.stubs.terminal())
        self.assertEqual(self.stubs.terminal()[0], ["omarchy-pkg-add", "bluez-obex"])
        self.start_obex()
        self.status("ready")

    def test_obexd_missing_keeps_calls_working(self):
        self.start_helper()
        self.helper.send({"cmd": "dial", "number": "0123"})
        self.helper.wait_for(is_event("call", state="dialing"))

    def test_refused_session_reports_error_then_recovers(self):
        self.start_obex()
        self.obex.control("SetMode", "(s)", ("refuse",))
        self.start_helper()
        self.helper.send({"cmd": "sync-contacts"})
        self.assertEqual(self.status("error")["message"], "Unable to connect")
        self.obex.control("SetMode", "(s)", ("normal",))
        self.helper.send({"cmd": "sync-contacts"})
        self.status("ready")

    def test_enabled_contacts_sync_on_connect(self):
        state = self.dir / "state" / "omyphone"
        state.mkdir(parents=True)
        (state / "contacts.json").write_text(json.dumps({"enabled": True, "synced": 0, "contacts": []}))
        self.start_obex()
        self.start_helper()
        self.status("ready")
        self.assertEqual(self.obex.log()[0], f"CreateSession {ADDRESS} PBAP")


if __name__ == "__main__":
    unittest.main()
