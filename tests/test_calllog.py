import tempfile
import unittest
from pathlib import Path

from omyphone.calllog import CallLog

P = "/org/pipewire/Telephony/ag1/call1"


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


class CallLogTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.log = CallLog(self.clock)

    def test_outgoing_answered(self):
        self.log.update(P, "0123", "dialing")
        self.clock.t += 5
        self.log.update(P, "0123", "active")
        self.clock.t += 65
        self.assertEqual(self.log.remove(P),
                         {"number": "0123", "direction": "outgoing", "start": 1000, "duration": 65})

    def test_outgoing_not_answered(self):
        self.log.update(P, "0123", "dialing")
        self.log.update(P, "0123", "alerting")
        self.clock.t += 20
        self.assertEqual(self.log.remove(P)["duration"], 0)
        self.assertEqual(self.log.remove(P), None)

    def test_incoming_answered(self):
        self.log.update(P, "0123", "incoming")
        self.log.update(P, "0123", "active")
        self.clock.t += 30
        entry = self.log.remove(P)
        self.assertEqual((entry["direction"], entry["duration"]), ("incoming", 30))

    def test_incoming_not_answered_is_missed(self):
        self.log.update(P, "0123", "incoming")
        self.assertEqual(self.log.remove(P)["direction"], "missed")

    def test_waiting_call_not_answered_is_missed(self):
        self.log.update(P, "0123", "waiting")
        self.assertEqual(self.log.remove(P)["direction"], "missed")

    def test_declined_is_incoming_with_zero_duration(self):
        self.log.update(P, "0123", "incoming")
        self.log.mark_declined(P)
        self.assertEqual(self.log.remove(P)["direction"], "incoming")

    def test_number_learned_later_is_kept(self):
        self.log.update(P, "", "incoming")
        self.log.update(P, "0199", "incoming")
        self.log.update(P, "", "active")
        self.assertEqual(self.log.remove(P)["number"], "0199")

    def test_unknown_path(self):
        self.log.mark_declined(P)
        self.assertIsNone(self.log.remove(P))

    def test_active_since(self):
        self.log.update(P, "0123", "dialing")
        self.assertEqual(self.log.active_since(P), 0)
        self.clock.t += 5
        self.log.update(P, "0123", "active")
        self.assertEqual(self.log.active_since(P), 1005)

    def test_call_first_seen_mid_call_is_not_guessed(self):
        # Already going when first seen: direction and start are unknown, so
        # there is no timer and nothing is logged.
        self.log.update(P, "0123", "active")
        self.assertEqual(self.log.active_since(P), 0)
        self.assertIsNone(self.log.remove(P))

    def test_parked_call_is_picked_up_again(self):
        # The telephony service restarted: the call vanished, then came back.
        self.log.update(P, "0123", "incoming")
        self.clock.t += 5
        self.log.update(P, "0123", "active")
        self.log.park(P)
        self.clock.t += 10
        self.log.update(P, "0123", "active")
        self.assertEqual(self.log.active_since(P), 1005)
        self.clock.t += 20
        self.assertEqual(self.log.remove(P),
                         {"number": "0123", "direction": "incoming", "start": 1000, "duration": 30})

    def test_parked_path_used_by_a_new_call_starts_fresh(self):
        self.log.update(P, "0123", "incoming")
        self.log.update(P, "0123", "active")
        self.log.park(P)
        self.clock.t += 100
        self.log.update(P, "0199", "dialing")
        self.assertEqual(self.log.remove(P)["start"], 1100)


class SavedCallLogTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "omyphone" / "calls.json"
        self.clock = Clock()

    def test_call_survives_a_helper_restart(self):
        log = CallLog(self.clock, self.path)
        log.update(P, "0123", "incoming")
        self.clock.t += 5
        log.update(P, "0123", "active")
        again = CallLog(self.clock, self.path)  # a new helper, mid-call
        again.update(P, "0123", "active")
        self.assertEqual(again.active_since(P), 1005)
        self.clock.t += 60
        self.assertEqual(again.remove(P)["direction"], "incoming")

    def test_file_goes_when_the_last_call_ends(self):
        log = CallLog(self.clock, self.path)
        log.update(P, "0123", "dialing")
        self.assertTrue(self.path.exists())
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        log.remove(P)
        self.assertFalse(self.path.exists())

    def test_corrupt_file_is_ignored(self):
        self.path.parent.mkdir(parents=True)
        for text in ("not json", "[]", '{"x": 1}', '{"%s": {"number": 5}}' % P):
            self.path.write_text(text)
            log = CallLog(self.clock, self.path)
            log.update(P, "0123", "active")
            self.assertIsNone(log.remove(P))

    def test_corrupt_file_is_set_aside(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text("not json")
        CallLog(self.clock, self.path)
        self.assertEqual(self.path.with_name(self.path.name + ".bad").read_text(), "not json")


if __name__ == "__main__":
    unittest.main()
