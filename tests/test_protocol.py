import json
import unittest

from omyphone.protocol import ProtocolError, encode_event, parse_command

CALL = "/org/pipewire/Telephony/ag1/call3"


class ParseCommandTests(unittest.TestCase):
    def assertRejected(self, line, cmd, message):
        with self.assertRaises(ProtocolError) as ctx:
            parse_command(line)
        self.assertEqual(ctx.exception.cmd, cmd)
        self.assertEqual(str(ctx.exception), message)

    def test_dial_strips_formatting(self):
        cmd = parse_command(json.dumps({"cmd": "dial", "number": "+60 (12) 345-6789"}))
        self.assertEqual(cmd, {"cmd": "dial", "number": "+60123456789"})

    def test_dial_accepts_star_and_hash(self):
        self.assertEqual(parse_command('{"cmd":"dial","number":"*123#"}')["number"], "*123#")

    def test_dial_rejects_letters_plus_in_middle_and_too_long(self):
        for number in ["abc", "12+34", "", "1" * 33, 123]:
            self.assertRejected(json.dumps({"cmd": "dial", "number": number}), "dial", "invalid number")

    def test_answer_hangup_decline_need_a_call_path(self):
        for name in ("answer", "hangup", "decline"):
            self.assertEqual(parse_command(json.dumps({"cmd": name, "call": CALL})), {"cmd": name, "call": CALL})
            self.assertRejected(json.dumps({"cmd": name, "call": "/etc/passwd"}), name, "invalid call path")
            self.assertRejected(json.dumps({"cmd": name}), name, "invalid call path")

    def test_tones(self):
        self.assertEqual(parse_command('{"cmd":"tones","digits":"12#*A"}'), {"cmd": "tones", "digits": "12#*A"})
        self.assertRejected('{"cmd":"tones","digits":"1 2"}', "tones", "invalid tones")

    def test_mute_needs_a_boolean(self):
        self.assertEqual(parse_command('{"cmd":"mute","on":true}'), {"cmd": "mute", "on": True})
        self.assertRejected('{"cmd":"mute","on":1}', "mute", "invalid mute value")

    def test_trailing_newline_is_rejected(self):
        self.assertRejected(json.dumps({"cmd": "dial", "number": "123\n"}), "dial", "invalid number")
        self.assertRejected(json.dumps({"cmd": "tones", "digits": "1\n"}), "tones", "invalid tones")
        self.assertRejected(json.dumps({"cmd": "answer", "call": CALL + "\n"}), "answer", "invalid call path")

    def test_bad_input(self):
        self.assertRejected("not json", "", "invalid JSON")
        self.assertRejected("[1,2]", "", "missing cmd")
        self.assertRejected('{"cmd":"reboot"}', "reboot", "unknown command")


class EncodeEventTests(unittest.TestCase):
    def test_single_compact_line(self):
        line = encode_event("call", path=CALL, number="123", state="active")
        self.assertNotIn("\n", line)
        self.assertEqual(json.loads(line), {"event": "call", "path": CALL, "number": "123", "state": "active"})


if __name__ == "__main__":
    unittest.main()
