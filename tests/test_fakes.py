"""Checks the fakes themselves, so helper test failures point at the helper."""
import unittest

from gi.repository import Gio, GLib

from tests.harness import Fake, bus, needs_test_bus

ROOT = "/org/pipewire/Telephony"
GW = ROOT + "/ag1"


def call(name, path, iface, method, params=None, reply=None):
    result = bus().call_sync(name, path, iface, method, params,
                             GLib.VariantType(reply) if reply else None,
                             Gio.DBusCallFlags.NONE, 2000, None)
    return result.unpack()


@needs_test_bus
class FakeTelephonyTests(unittest.TestCase):
    def setUp(self):
        self.fake = Fake("fake_telephony.py", "org.pipewire.Telephony")
        self.addCleanup(self.fake.stop)

    def test_gateway_and_calls(self):
        name = "org.pipewire.Telephony"
        self.assertEqual(call(name, ROOT, "org.ofono.Manager", "GetModems", reply="(a{oa{sv}})"), ({},))
        self.fake.control("AddGateway")
        self.assertEqual(list(call(name, ROOT, "org.ofono.Manager", "GetModems", reply="(a{oa{sv}})")[0]), [GW])
        (path,) = self.fake.control("AddCall", "(ss)", ("0123", "incoming"), "(o)")
        calls = call(name, GW, "org.ofono.VoiceCallManager", "GetCalls", reply="(a{oa{sv}})")[0]
        self.assertEqual(calls[path]["State"], "incoming")
        call(name, path, "org.pipewire.Telephony.Call1", "Answer")
        call(name, GW, "org.pipewire.Telephony.AudioGateway1", "Dial", GLib.Variant("(s)", ("555",)))
        self.assertEqual(self.fake.log(), [f"Answer {path}", "Dial 555"])

    def test_answer_twice_is_invalid_state(self):
        self.fake.control("AddGateway")
        (path,) = self.fake.control("AddCall", "(ss)", ("0123", "incoming"), "(o)")
        call("org.pipewire.Telephony", path, "org.pipewire.Telephony.Call1", "Answer")
        with self.assertRaises(GLib.Error):
            call("org.pipewire.Telephony", path, "org.pipewire.Telephony.Call1", "Answer")


@needs_test_bus
class FakeBluezTests(unittest.TestCase):
    def setUp(self):
        self.fake = Fake("fake_bluez.py", "org.bluez")
        self.addCleanup(self.fake.stop)

    def objects(self):
        return call("org.bluez", "/", "org.freedesktop.DBus.ObjectManager", "GetManagedObjects",
                    reply="(a{oa{sa{sv}}})")[0]

    def test_connect_when_powered(self):
        self.fake.control("SetConnected", "(b)", (False,))
        device = next(p for p, ifs in self.objects().items() if "org.bluez.Device1" in ifs)
        call("org.bluez", device, "org.bluez.Device1", "Connect")
        self.assertTrue(self.objects()[device]["org.bluez.Device1"]["Connected"])
        self.assertEqual(self.fake.log(), ["Connect"])

    def test_connect_fails_when_powered_off(self):
        self.fake.control("SetPowered", "(b)", (False,))
        device = next(p for p, ifs in self.objects().items() if "org.bluez.Device1" in ifs)
        with self.assertRaises(GLib.Error):
            call("org.bluez", device, "org.bluez.Device1", "Connect")


if __name__ == "__main__":
    unittest.main()
