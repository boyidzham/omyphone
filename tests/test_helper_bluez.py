"""The real helper against the fake BlueZ (reconnect behaviour)."""
import tempfile
import time
import unittest
from pathlib import Path

from tests.harness import Fake, Helper, needs_test_bus


def phone_event(**fields):
    return lambda e: e.get("event") == "phone" and all(e.get(k) == v for k, v in fields.items())


@needs_test_bus
class HelperBluezTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.bluez = Fake("fake_bluez.py", "org.bluez")
        self.addCleanup(self.bluez.stop)

    def start_helper(self, *args):
        helper = Helper(self.dir, args)
        self.addCleanup(helper.close)
        return helper

    def test_reports_connected_phone_without_connecting(self):
        helper = self.start_helper()
        event = helper.wait_for(phone_event(found=True))
        self.assertEqual((event["name"], event["connected"], event["powered"]), ("Test Phone", True, True))
        time.sleep(0.5)
        self.assertEqual(self.bluez.log(), [])

    def test_reconnects_a_disconnected_phone(self):
        helper = self.start_helper()
        helper.wait_for(phone_event(connected=True))
        self.bluez.control("SetConnected", "(b)", (False,))
        helper.wait_for(phone_event(connected=False))
        helper.wait_for(phone_event(connected=True))
        self.assertEqual(self.bluez.log(), ["Connect"])

    def test_retries_after_a_failed_connect(self):
        self.bluez.control("SetConnected", "(b)", (False,))
        self.bluez.control("SetConnectFails", "(b)", (True,))
        helper = self.start_helper()
        helper.wait_for(phone_event(connected=False))
        time.sleep(0.5)
        self.assertEqual(self.bluez.log(), ["Connect"])  # retry interval is 1 s in tests
        self.bluez.control("SetConnectFails", "(b)", (False,))
        helper.wait_for(phone_event(connected=True), timeout=5)
        self.assertEqual(self.bluez.log(), ["Connect", "Connect"])

    def test_no_attempts_while_adapter_is_off(self):
        self.bluez.control("SetPowered", "(b)", (False,))
        self.bluez.control("SetConnected", "(b)", (False,))
        helper = self.start_helper()
        helper.wait_for(phone_event(powered=False))
        time.sleep(1.5)
        self.assertEqual(self.bluez.log(), [])

    def test_no_phone_paired(self):
        self.bluez.control("SetPaired", "(b)", (False,))
        helper = self.start_helper()
        helper.wait_for(phone_event(found=False))

    def test_phone_setting_selects_device(self):
        helper = self.start_helper("--phone", "aa:bb:cc:dd:ee:ff")
        helper.wait_for(phone_event(found=True, address="AA:BB:CC:DD:EE:FF"))
        other = self.start_helper("--phone", "11:22:33:44:55:66")
        other.wait_for(phone_event(found=False, address="11:22:33:44:55:66"))


if __name__ == "__main__":
    unittest.main()
