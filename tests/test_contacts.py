import json
import os
import stat
import tempfile
import time
import unittest
from pathlib import Path

from omyphone.contacts import ContactsStore, Directory, HistoryStore, numbers_match, rows, write_private


def contact(name, *numbers):
    return {"name": name, "numbers": [{"number": n, "label": ""} for n in numbers]}


class MatchTests(unittest.TestCase):
    def test_local_and_international_forms(self):
        for a, b in [("012 345 6789", "+60123456789"), ("+60 12-345 6789", "0123456789"),
                     ("03-8888 7777", "+60 (3) 8888-7777")]:
            with self.subTest(a=a, b=b):
                self.assertTrue(numbers_match(a, b))

    def test_eight_digit_local_numbers(self):
        self.assertTrue(numbers_match("9123 4567", "+65 9123 4567"))
        self.assertTrue(numbers_match("+852 5123 4567", "51234567"))

    def test_different_numbers(self):
        self.assertFalse(numbers_match("+60123456789", "+60123456780"))

    def test_short_numbers_only_exact(self):
        self.assertTrue(numbers_match("999", "999"))
        self.assertFalse(numbers_match("999", "+60999"))
        self.assertFalse(numbers_match("", ""))


class DirectoryTests(unittest.TestCase):
    def test_lookup(self):
        directory = Directory([contact("Ali Ahmad", "+60123456789"), contact("Siti", "012 345 6780")])
        self.assertEqual(directory.lookup("0123456789"), "Ali Ahmad")
        self.assertEqual(directory.lookup("+60 12-345 6780"), "Siti")
        self.assertEqual(directory.lookup("+60155556666"), "")
        self.assertEqual(directory.lookup(""), "")

    def test_shared_number_first_name_wins(self):
        home = "+60 3-2345 6789"
        for order in ([contact("zaki", home), contact("Aminah", home)],
                      [contact("Aminah", home), contact("zaki", home)]):
            self.assertEqual(Directory(order).lookup("0323456789"), "Aminah")

    def test_nameless_contact_does_not_hide_a_named_one(self):
        home = "+60 3-2345 6789"
        self.assertEqual(Directory([contact("", home), contact("Aminah", home)]).lookup(home), "Aminah")

    def test_large_directory_is_fast(self):
        directory = Directory([contact(f"P{i}", f"+6012{i:07d}") for i in range(2000)])
        started = time.monotonic()
        for i in range(2000):
            directory.lookup(f"012{i:07d}")
        self.assertLess(time.monotonic() - started, 1.0)


class RowsTests(unittest.TestCase):
    def test_one_row_per_number_sorted_by_name(self):
        result = rows([contact("siti", "1", "2"), contact("Ali", "3")])
        self.assertEqual([(r["name"], r["number"]) for r in result], [("Ali", "3"), ("siti", "1"), ("siti", "2")])
        self.assertEqual(set(result[0]), {"name", "number", "label"})

    def test_nameless_contacts_come_last(self):
        result = rows([contact("", "9"), contact("zaki", "1"), contact("Ali", "3")])
        self.assertEqual([r["name"] for r in result], ["Ali", "zaki", ""])


class StoreTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name) / "omyphone"

    def test_write_private_is_0600_and_atomic(self):
        path = self.dir / "x.json"
        write_private(path, {"a": 1})
        self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)
        self.assertEqual(json.loads(path.read_text()), {"a": 1})
        self.assertEqual([p.name for p in self.dir.iterdir()], ["x.json"])

    def test_contacts_round_trip(self):
        store = ContactsStore(self.dir / "contacts.json")
        self.assertEqual((store.enabled, store.synced, store.contacts), (False, 0, []))
        store.enabled, store.synced, store.contacts = True, 5, [contact("Ali", "1")]
        store.save()
        loaded = ContactsStore(self.dir / "contacts.json")
        self.assertEqual((loaded.enabled, loaded.synced, loaded.contacts), (True, 5, [contact("Ali", "1")]))

    def test_history_round_trip(self):
        call = {"name": "", "number": "1", "direction": "missed", "start": 3}
        store = HistoryStore(self.dir / "history.json")
        store.synced, store.calls, store.missed = 7, [call], [call]
        store.save()
        loaded = HistoryStore(self.dir / "history.json")
        self.assertEqual((loaded.synced, loaded.calls, loaded.missed), (7, [call], [call]))

    def test_corrupt_files_are_empty(self):
        self.dir.mkdir(parents=True)
        (self.dir / "contacts.json").write_text("{nope")
        (self.dir / "history.json").write_text("[1, 2]")
        self.assertEqual(ContactsStore(self.dir / "contacts.json").contacts, [])
        self.assertEqual(HistoryStore(self.dir / "history.json").calls, [])
        self.assertEqual((self.dir / "contacts.json.bad").read_text(), "{nope")
        self.assertEqual((self.dir / "history.json.bad").read_text(), "[1, 2]")
        self.assertFalse((self.dir / "contacts.json").exists())

    def test_unreadable_file_is_set_aside(self):
        self.dir.mkdir(parents=True)
        (self.dir / "contacts.json").write_bytes(b"\xff\xfe")
        self.assertEqual(ContactsStore(self.dir / "contacts.json").contacts, [])
        self.assertEqual((self.dir / "contacts.json.bad").read_bytes(), b"\xff\xfe")

    def test_invalid_entries_are_dropped(self):
        self.dir.mkdir(parents=True)
        (self.dir / "contacts.json").write_text(json.dumps(
            {"enabled": True, "synced": 1, "contacts": [contact("Ok", "1"), {"name": 3}, "x"]}))
        self.assertEqual(ContactsStore(self.dir / "contacts.json").contacts, [contact("Ok", "1")])

    def test_save_failure_does_not_raise(self):
        self.dir.parent.chmod(0o500)
        self.addCleanup(self.dir.parent.chmod, 0o700)
        ContactsStore(self.dir / "contacts.json").save()  # prints to stderr, no exception
