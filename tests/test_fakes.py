"""Checks the fakes themselves, so helper test failures point at the helper."""
import tempfile
import unittest
from pathlib import Path

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


@needs_test_bus
class FakeObexTests(unittest.TestCase):
    def setUp(self):
        self.fake = Fake("fake_obex.py", "org.bluez.obex")
        self.addCleanup(self.fake.stop)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.target = Path(tmp.name) / "pb.vcf"

    def obex(self, path, iface, method, signature=None, args=None, reply=None):
        params = GLib.Variant(signature, args) if signature else None
        return bus().call_sync("org.bluez.obex", path, iface, method, params,
                               GLib.VariantType(reply) if reply else None,
                               Gio.DBusCallFlags.NONE, 5000, None).unpack()

    def session(self):
        return self.obex("/org/bluez/obex", "org.bluez.obex.Client1", "CreateSession", "(sa{sv})",
                         ("AA:BB:CC:DD:EE:FF", {"Target": GLib.Variant("s", "PBAP")}), "(o)")[0]

    def pull(self, session, folder="pb"):
        self.obex(session, "org.bluez.obex.PhonebookAccess1", "Select", "(ss)", ("int", folder))
        return self.obex(session, "org.bluez.obex.PhonebookAccess1", "PullAll", "(sa{sv})",
                         (str(self.target), {"Format": GLib.Variant("s", "vcard30")}), "(oa{sv})")[0]

    def status(self, transfer):
        return self.obex(transfer, "org.freedesktop.DBus.Properties", "Get", "(ss)",
                         ("org.bluez.obex.Transfer1", "Status"), "(v)")[0]

    def test_pull_writes_fixture_with_crlf(self):
        transfer = self.pull(self.session())
        self.assertEqual(self.status(transfer), "queued")
        self.assertEqual(self.status(transfer), "complete")
        self.assertIn("BEGIN:VCARD\r\n", self.target.read_text(newline=""))
        self.assertEqual(self.fake.log()[:3], ["CreateSession AA:BB:CC:DD:EE:FF PBAP", "Select pb", "PullAll pb vcard30"])

    def test_empty_mode_writes_empty_file(self):
        self.fake.control("SetMode", "(s)", ("empty",))
        self.pull(self.session())
        self.assertEqual(self.target.read_text(), "")

    def test_refuse_and_error_modes(self):
        self.fake.control("SetMode", "(s)", ("error",))
        with self.assertRaises(GLib.Error):
            self.pull(self.session())
        self.fake.control("SetMode", "(s)", ("refuse",))
        with self.assertRaises(GLib.Error):
            self.session()

    def test_vanish_mode_has_no_transfer_object(self):
        self.fake.control("SetMode", "(s)", ("vanish",))
        transfer = self.pull(self.session())
        self.assertTrue(self.target.exists())
        with self.assertRaises(GLib.Error):
            self.status(transfer)

    def test_remove_session(self):
        session = self.session()
        self.obex("/org/bluez/obex", "org.bluez.obex.Client1", "RemoveSession", "(o)", (session,))
        self.assertIn("RemoveSession", self.fake.log())


@needs_test_bus
class TestBusTests(unittest.TestCase):
    def test_no_service_activation_on_the_test_bus(self):
        names = bus().call_sync("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus",
                                "ListActivatableNames", None, GLib.VariantType("(as)"),
                                Gio.DBusCallFlags.NONE, 2000, None).unpack()[0]
        self.assertNotIn("org.bluez.obex", names)


if __name__ == "__main__":
    unittest.main()
