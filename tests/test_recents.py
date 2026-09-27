import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from omyphone.recents import LIMIT, Recents, default_path, merge


def entry(number, direction="outgoing"):
    return {"number": number, "direction": direction, "start": 1, "duration": 0}


def at(number, start, direction="outgoing"):
    return {"number": number, "direction": direction, "start": start, "duration": 0}


class RecentsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "omyphone" / "recents.json"

    def test_missing_file_is_empty(self):
        self.assertEqual(Recents(self.path).entries, [])

    def test_add_is_newest_first_and_persists(self):
        recents = Recents(self.path)
        recents.add(entry("1"))
        recents.add(entry("2"))
        self.assertEqual([e["number"] for e in Recents(self.path).entries], ["2", "1"])

    def test_capped_at_limit(self):
        recents = Recents(self.path)
        for i in range(LIMIT + 5):
            recents.add(entry(str(i)))
        loaded = Recents(self.path).entries
        self.assertEqual(len(loaded), LIMIT)
        self.assertEqual(loaded[0]["number"], str(LIMIT + 4))

    def test_corrupt_file_is_empty(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text("{not json")
        self.assertEqual(Recents(self.path).entries, [])

    def test_invalid_entries_are_dropped(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text(json.dumps([entry("1"), {"number": 5}, entry("2", "sideways"), "x"]))
        self.assertEqual([e["number"] for e in Recents(self.path).entries], ["1"])

    def test_unwritable_location_keeps_entries_in_memory(self):
        blocker = Path(self.tmp.name) / "blocker"
        blocker.write_text("a file where a folder should be")
        recents = Recents(blocker / "recents.json")
        recents.add(entry("1"))
        self.assertEqual(len(recents.entries), 1)

    def test_default_path_uses_xdg_state_home(self):
        with mock.patch.dict(os.environ, {"XDG_STATE_HOME": "/x/state"}):
            self.assertEqual(default_path(), Path("/x/state/omyphone/recents.json"))


class MergeTests(unittest.TestCase):
    def test_no_phone_history_uses_local(self):
        local = [at("1", 10)]
        self.assertEqual(merge(local, None), local)

    def test_phone_history_replaces_local(self):
        phone = [at("2", 100)]
        self.assertEqual(merge([at("1", 50)], phone), phone)

    def test_newer_local_call_shown_on_top(self):
        phone = [at("+60123456789", 100)]
        self.assertEqual(merge([at("0155", 200)], phone), [at("0155", 200)] + phone)

    def test_local_call_already_in_phone_history_not_repeated(self):
        phone = [at("+60123456789", 200)]
        self.assertEqual(merge([at("0123456789", 230)], phone), phone)

    def test_capped(self):
        phone = [at(str(i), 1000 - i) for i in range(LIMIT)]
        self.assertEqual(len(merge([at("x", 5000)], phone)), LIMIT)


if __name__ == "__main__":
    unittest.main()
