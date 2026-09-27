import unittest

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


if __name__ == "__main__":
    unittest.main()
