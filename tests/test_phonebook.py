import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from gi.repository import GLib

from omyphone.phonebook import Phonebook, default_tmpdir
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


class DefaultTmpdirTests(unittest.TestCase):
    def test_runtime_dir(self):
        with mock.patch.dict(os.environ, {"XDG_RUNTIME_DIR": "/run/user/1000"}):
            self.assertEqual(default_tmpdir(), Path("/run/user/1000/omyphone"))

    def test_without_runtime_dir_uses_the_cache_not_tmp(self):
        env = {k: v for k, v in os.environ.items() if k not in ("XDG_RUNTIME_DIR", "XDG_CACHE_HOME")}
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertEqual(default_tmpdir(), Path.home() / ".cache" / "omyphone")
        with mock.patch.dict(os.environ, {"XDG_CACHE_HOME": "/c"}, clear=True):
            self.assertEqual(default_tmpdir(), Path("/c/omyphone"))


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
            self.book.pull("AA:BB:CC:DD:EE:FF", folders, callback)
        return run(start)

    def test_not_available_without_obexd(self):
        self.assertEqual(run(self.book.available), (False,))

    def test_available_with_obexd(self):
        self.start_fake()
        self.assertEqual(run(self.book.available), (True,))
        self.assertEqual(self.fake.log(), [])  # checking never talks to obexd

    def test_pull_returns_each_folder(self):
        self.start_fake()
        texts, errors = self.pull()
        self.assertEqual(errors, {})
        self.assertEqual(set(texts), {"pb", "cch"})
        self.assertIn("FN:Ali Ahmad", texts["pb"])
        self.assertIn("RemoveSession", self.fake.log())
        self.assertEqual(list(self.tmpdir.glob("*.vcf")), [])

    def test_tmpdir_is_private(self):
        self.start_fake()
        self.pull()
        self.assertEqual(self.tmpdir.stat().st_mode & 0o777, 0o700)

    def test_tmpdir_that_is_a_symlink_is_refused(self):
        self.start_fake()
        elsewhere = self.tmpdir.with_name("elsewhere")
        elsewhere.mkdir()
        (elsewhere / "pb.vcf").write_text("not ours")
        self.tmpdir.symlink_to(elsewhere)
        texts, errors = self.pull()
        self.assertEqual(texts, {})
        self.assertEqual(errors, {f: f"{self.tmpdir} is not a private folder" for f in ("pb", "cch")})
        self.assertNotIn("CreateSession", " ".join(self.fake.log()))
        self.assertEqual((elsewhere / "pb.vcf").read_text(), "not ours")

    def test_transfer_object_gone_counts_as_complete(self):
        self.start_fake()
        self.fake.control("SetMode", "(s)", ("vanish",))
        texts, errors = self.pull(("pb",))
        self.assertEqual(errors, {})
        self.assertIn("FN:Ali Ahmad", texts["pb"])

    def test_empty(self):
        self.start_fake()
        self.fake.control("SetMode", "(s)", ("empty",))
        self.assertEqual(self.pull(("pb",)), ({"pb": ""}, {}))

    def test_stale_file_is_not_read(self):
        self.start_fake()
        self.fake.control("SetMode", "(s)", ("empty",))
        self.tmpdir.mkdir(parents=True)
        (self.tmpdir / "pb.vcf").write_text("BEGIN:VCARD\nFN:Stale\nTEL:1\nEND:VCARD\n")
        self.assertEqual(self.pull(("pb",)), ({"pb": ""}, {}))

    def test_refused_session(self):
        self.start_fake()
        self.fake.control("SetMode", "(s)", ("refuse",))
        self.assertEqual(self.pull(), ({}, {"pb": "Unable to connect", "cch": "Unable to connect"}))

    def test_transfer_error_removes_session(self):
        self.start_fake()
        self.fake.control("SetMode", "(s)", ("error",))
        self.assertEqual(self.pull(), ({}, {"pb": "Transfer failed", "cch": "Transfer failed"}))
        self.assertIn("RemoveSession", self.fake.log())

    def test_one_failed_folder_keeps_the_others(self):
        self.start_fake()
        self.fake.control("SetMode", "(s)", ("fail-cch",))
        texts, errors = self.pull(("pb", "cch", "mch"))
        self.assertEqual(errors, {"cch": "Transfer failed"})
        self.assertEqual(set(texts), {"pb", "mch"})
        self.assertIn("FN:Ali Ahmad", texts["pb"])
        self.assertEqual(self.fake.log().count("RemoveSession"), 1)

    def test_no_obexd_is_an_error_not_a_hang(self):
        texts, errors = self.pull()
        self.assertEqual(texts, {})
        self.assertEqual(set(errors), {"pb", "cch"})
        self.assertTrue(errors["pb"])
