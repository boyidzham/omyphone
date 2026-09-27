import tempfile
import unittest
from pathlib import Path

from gi.repository import GLib

from omyphone.phonebook import Phonebook
from tests.harness import Fake, bus, needs_test_bus


def run(start, timeout=5.0):
    """Run the GLib loop until the callback passed to start(callback) fires."""
    loop, result = GLib.MainLoop(), []

    def callback(*args):
        result.append(args)
        loop.quit()

    start(callback)
    GLib.timeout_add(int(timeout * 1000), loop.quit)
    loop.run()
    if not result:
        raise AssertionError("no callback")
    return result[0]


@needs_test_bus
class PhonebookTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmpdir = Path(tmp.name) / "omyphone"
        self.book = Phonebook(bus(), self.tmpdir, timeout_s=3.0, poll_ms=20)

    def start_fake(self):
        self.fake = Fake("fake_obex.py", "org.bluez.obex")
        self.addCleanup(self.fake.stop)

    def pull(self, folders=("pb", "cch")):
        def start(callback):
            self.book.pull("AA:BB:CC:DD:EE:FF", folders,
                           lambda texts: callback("done", texts), lambda msg: callback("error", msg))
        return run(start)

    def test_not_available_without_obexd(self):
        self.assertEqual(run(self.book.available), (False,))

    def test_available_with_obexd(self):
        self.start_fake()
        self.assertEqual(run(self.book.available), (True,))
        self.assertEqual(self.fake.log(), [])  # checking never talks to obexd

    def test_pull_returns_each_folder(self):
        self.start_fake()
        kind, texts = self.pull()
        self.assertEqual(kind, "done")
        self.assertEqual(set(texts), {"pb", "cch"})
        self.assertIn("FN:Ali Ahmad", texts["pb"])
        self.assertIn("RemoveSession", self.fake.log())
        self.assertEqual(list(self.tmpdir.glob("*.vcf")), [])

    def test_tmpdir_is_private(self):
        self.start_fake()
        self.pull()
        self.assertEqual(self.tmpdir.stat().st_mode & 0o777, 0o700)

    def test_transfer_object_gone_counts_as_complete(self):
        self.start_fake()
        self.fake.control("SetMode", "(s)", ("vanish",))
        kind, texts = self.pull(("pb",))
        self.assertEqual(kind, "done")
        self.assertIn("FN:Ali Ahmad", texts["pb"])

    def test_empty(self):
        self.start_fake()
        self.fake.control("SetMode", "(s)", ("empty",))
        self.assertEqual(self.pull(("pb",)), ("done", {"pb": ""}))

    def test_stale_file_is_not_read(self):
        self.start_fake()
        self.fake.control("SetMode", "(s)", ("empty",))
        self.tmpdir.mkdir(parents=True)
        (self.tmpdir / "pb.vcf").write_text("BEGIN:VCARD\nFN:Stale\nTEL:1\nEND:VCARD\n")
        self.assertEqual(self.pull(("pb",)), ("done", {"pb": ""}))

    def test_refused_session(self):
        self.start_fake()
        self.fake.control("SetMode", "(s)", ("refuse",))
        self.assertEqual(self.pull(), ("error", "Unable to connect"))

    def test_transfer_error_removes_session(self):
        self.start_fake()
        self.fake.control("SetMode", "(s)", ("error",))
        self.assertEqual(self.pull(), ("error", "Transfer failed"))
        self.assertIn("RemoveSession", self.fake.log())

    def test_no_obexd_is_an_error_not_a_hang(self):
        kind, message = self.pull()
        self.assertEqual(kind, "error")
        self.assertTrue(message)
