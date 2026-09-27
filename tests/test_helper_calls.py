"""The real helper against the fake telephony service (no BlueZ fake running)."""
import tempfile
import time
import unittest
from pathlib import Path

from tests.harness import Fake, Helper, Stubs, needs_test_bus, wait_until


def is_event(name, **fields):
    return lambda e: e.get("event") == name and all(e.get(k) == v for k, v in fields.items())


@needs_test_bus
class HelperCallTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.stubs = Stubs(self.dir)
        self.fake = Fake("fake_telephony.py", "org.pipewire.Telephony")
        # A lambda, so cleanup stops whichever fake is current (one test replaces it).
        self.addCleanup(lambda: self.fake.stop())
        self.fake.control("AddGateway")

    def start_helper(self):
        self.helper = Helper(self.dir)
        self.addCleanup(self.helper.close)
        self.helper.wait_for(is_event("gateway", present=True))

    def incoming(self, number="0123"):
        (path,) = self.fake.control("AddCall", "(ss)", (number, "incoming"), "(o)")
        self.helper.wait_for(is_event("call", path=path, state="incoming"))
        return path

    def last_recent(self):
        return self.helper.wait_for(is_event("recents"))["entries"][0]

    def test_start_sends_recents_and_mute_state(self):
        helper = Helper(self.dir)
        self.addCleanup(helper.close)
        self.assertEqual(helper.wait_for(is_event("recents"))["entries"], [])
        self.assertFalse(helper.wait_for(is_event("muted"))["muted"])

    def test_outgoing_call(self):
        self.start_helper()
        self.helper.send({"cmd": "dial", "number": "012-345 6789"})
        call = self.helper.wait_for(is_event("call", state="dialing"))
        self.assertEqual(call["number"], "0123456789")
        self.assertIn("Dial 0123456789", self.fake.log())
        self.fake.control("SetState", "(os)", (call["path"], "active"))
        self.helper.wait_for(is_event("call", path=call["path"], state="active"))
        self.helper.send({"cmd": "hangup", "call": call["path"]})
        self.helper.wait_for(is_event("call-removed", path=call["path"]))
        self.assertEqual(self.last_recent()["direction"], "outgoing")
        self.assertTrue((self.dir / "state" / "omyphone" / "recents.json").exists())

    def test_answer_command_from_card(self):
        self.start_helper()
        path = self.incoming("+60123")
        self.helper.send({"cmd": "answer", "call": path})
        self.helper.wait_for(is_event("call", path=path, state="active"))
        self.assertIn(f"Answer {path}", self.fake.log())

    def test_incoming_call_sends_no_notification(self):
        # The shell shows its own card with Answer/Decline (Omarchy's
        # notifications cannot show buttons), so the helper must not also
        # send an Omarchy notification for a ringing call.
        self.start_helper()
        self.incoming("0199")
        time.sleep(0.5)  # a notify-send started while ringing would have logged by now
        self.assertEqual(self.stubs.notifications(), [])

    def test_decline_command_from_popup(self):
        self.start_helper()
        path = self.incoming()
        self.helper.send({"cmd": "decline", "call": path})
        self.helper.wait_for(is_event("call-removed", path=path))
        self.assertEqual(self.last_recent()["direction"], "incoming")

    def test_missed_call(self):
        self.start_helper()
        path = self.incoming("0199")
        self.fake.control("RemoveCall", "(o)", (path,))
        self.helper.wait_for(is_event("call-removed", path=path))
        self.assertEqual(self.last_recent()["direction"], "missed")
        missed = self.stubs.wait_notification("Missed call")
        self.assertEqual(missed[:2], ["-a", "omyphone"])
        self.assertEqual(missed[-1], "0199")

    def test_tones(self):
        self.start_helper()
        self.helper.send({"cmd": "tones", "digits": "12#"})
        wait_until(lambda: "SendTones 12#" in self.fake.log())

    def test_mute_kept_until_last_call_ends(self):
        self.start_helper()
        first = self.incoming("1")
        self.fake.control("SetState", "(os)", (first, "active"))
        self.helper.send({"cmd": "mute", "on": True})
        self.assertTrue(self.helper.wait_for(is_event("muted"))["muted"])
        self.assertIn("set-mute @DEFAULT_AUDIO_SOURCE@ 1", self.stubs.wpctl())
        second = self.incoming("2")
        self.fake.control("RemoveCall", "(o)", (first,))
        self.helper.wait_for(is_event("call-removed", path=first))
        self.assertTrue((self.dir / "mic-muted").exists())
        self.fake.control("RemoveCall", "(o)", (second,))
        self.helper.wait_for(is_event("call-removed", path=second))
        self.assertFalse(self.helper.wait_for(is_event("muted"))["muted"])
        self.assertFalse((self.dir / "mic-muted").exists())

    def test_mute_without_call_is_an_error(self):
        self.start_helper()
        self.helper.send({"cmd": "mute", "on": True})
        self.assertEqual(self.helper.wait_for(is_event("error"))["message"], "No active call")

    def test_existing_call_reported_on_start(self):
        (path,) = self.fake.control("AddCall", "(ss)", ("0123", "active"), "(o)")
        self.start_helper()
        self.helper.wait_for(is_event("call", path=path, state="active"))

    def test_gateway_removed_mid_call_removes_calls(self):
        self.start_helper()
        path = self.incoming()
        self.fake.control("SetState", "(os)", (path, "active"))
        self.fake.control("RemoveGateway")
        self.helper.wait_for(is_event("call-removed", path=path))
        self.helper.wait_for(is_event("gateway", present=False))

    def test_answer_non_incoming_call_reports_error(self):
        self.start_helper()
        path = self.incoming()
        self.fake.control("SetState", "(os)", (path, "active"))
        self.helper.send({"cmd": "answer", "call": path})
        error = self.helper.wait_for(is_event("error", cmd="answer"))
        self.assertIn("not incoming", error["message"])

    def test_dial_without_phone(self):
        self.fake.control("RemoveGateway")
        helper = Helper(self.dir)
        self.addCleanup(helper.close)
        helper.send({"cmd": "dial", "number": "123"})
        self.assertEqual(helper.wait_for(is_event("error", cmd="dial"))["message"], "Phone not connected")

    def test_bad_commands_do_not_kill_the_helper(self):
        self.start_helper()
        self.helper.send("not json")
        self.assertEqual(self.helper.wait_for(is_event("error"))["message"], "invalid JSON")
        self.helper.send({"cmd": "dial", "number": "abc"})
        self.assertEqual(self.helper.wait_for(is_event("error"))["message"], "invalid number")
        self.helper.send({"cmd": "dial", "number": "999"})
        self.helper.wait_for(is_event("call", number="999"))

    def test_telephony_restart_mid_call(self):
        self.start_helper()
        path = self.incoming()
        self.fake.control("SetState", "(os)", (path, "active"))
        self.fake.stop()
        self.helper.wait_for(is_event("call-removed", path=path))
        self.helper.wait_for(is_event("gateway", present=False))
        self.fake = Fake("fake_telephony.py", "org.pipewire.Telephony")
        self.fake.control("AddGateway")
        self.helper.wait_for(is_event("gateway", present=True))
        (again,) = self.fake.control("AddCall", "(ss)", ("0123", "active"), "(o)")
        self.helper.wait_for(is_event("call", path=again, state="active"))
        self.assertFalse((self.dir / "state" / "omyphone" / "recents.json").exists())

    def test_helper_exits_when_stdin_closes(self):
        self.start_helper()
        self.helper.proc.stdin.close()
        self.assertEqual(self.helper.proc.wait(5), 0)


if __name__ == "__main__":
    unittest.main()
