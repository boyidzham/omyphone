import tempfile
import unittest
from pathlib import Path

from gi.repository import GLib

from omyphone.contacts import ContactsStore, HistoryStore
from omyphone.sync import INSTALL_ARGV, REFUSED, ContactsSync

FIXTURES = Path(__file__).resolve().parent / "fixtures"
FULL = {name: (FIXTURES / f"{name}.vcf").read_text() for name in ("pb", "cch", "mch")}
EMPTY = {"pb": "", "cch": "", "mch": ""}


class FakeBook:
    def __init__(self):
        self.ok = True
        self.results = []      # used in order: texts dicts, (texts, errors), or a string (every folder failed)
        self.pulls = []
        self.defer = False
        self.waiting = []

    def available(self, callback):
        callback(self.ok)

    def pull(self, address, folders, on_done):
        self.pulls.append((address, tuple(folders)))
        if self.defer:
            self.waiting.append((folders, on_done))
            return
        self.finish(folders, on_done)

    def finish(self, folders, on_done):
        result = self.results.pop(0) if self.results else EMPTY
        if isinstance(result, str):
            on_done({}, {folder: result for folder in folders})
        elif isinstance(result, tuple):
            on_done(*result)
        else:
            on_done({folder: result[folder] for folder in folders}, {})

    def release(self):
        self.defer = False
        while self.waiting:
            self.finish(*self.waiting.pop(0))


class Listener:
    def __init__(self):
        self.statuses, self.contacts, self.history = [], 0, 0

    def contacts_status(self, status):
        self.statuses.append(status)

    def contacts_changed(self):
        self.contacts += 1

    def history_changed(self):
        self.history += 1


class SyncTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.book = FakeBook()
        self.listener = Listener()
        self.scheduled = []
        self.spawned = []
        self.now = 1000.0
        self.address = "AA:BB:CC:DD:EE:FF"

    def make(self, enabled=False, contacts=None):
        store = ContactsStore(self.dir / "contacts.json")
        if enabled or contacts:
            store.enabled, store.contacts, store.synced = True, contacts or [], 1 if contacts else 0
            store.save()
            store = ContactsStore(self.dir / "contacts.json")
        self.sync = ContactsSync(self.book, store, HistoryStore(self.dir / "history.json"), self.listener,
                                 lambda: self.address, schedule=lambda s, fn: self.scheduled.append((s, fn)),
                                 spawn=self.spawned.append, clock=lambda: self.now, wallclock=lambda: 5000)
        self.sync.start()
        return self.sync

    def run_scheduled(self):
        jobs, self.scheduled = self.scheduled, []
        for _seconds, fn in jobs:
            fn()

    @property
    def state(self):
        return self.listener.statuses[-1]["state"]

    def test_off_until_the_user_asks(self):
        self.make()
        self.assertEqual(self.state, "off")
        self.sync.connected()
        self.sync.call_ended()
        self.run_scheduled()
        self.assertEqual(self.book.pulls, [])

    def test_needs_install_known_at_start(self):
        self.book.ok = False
        self.make()
        self.assertEqual(self.state, "needs-install")

    def test_user_sync_saves_contacts_without_owner_card(self):
        self.book.results = [FULL]
        self.make().user_sync()
        self.assertEqual(self.book.pulls, [(self.address, ("pb", "cch", "mch"))])
        self.assertEqual(self.state, "ready")
        names = [c["name"] for c in self.sync.contacts.contacts]
        self.assertIn("Ali Ahmad", names)
        self.assertNotIn("Test Owner", names)
        saved = ContactsStore(self.dir / "contacts.json")
        self.assertTrue(saved.enabled)
        self.assertEqual(saved.synced, 5000)
        self.assertEqual(len(HistoryStore(self.dir / "history.json").calls), 3)
        self.assertEqual((self.listener.contacts, self.listener.history), (1, 1))

    def test_missed_list_from_mch(self):
        self.book.results = [FULL]
        self.make().user_sync()
        self.assertEqual([e["direction"] for e in self.sync.history.missed], ["missed", "missed"])

    def test_empty_pull_asks_permission_then_retries(self):
        self.book.results = [EMPTY, FULL]
        self.make().user_sync()
        self.assertEqual(self.state, "needs-permission")
        self.assertEqual(self.scheduled[0][0], 5.0)
        self.run_scheduled()
        self.assertEqual(self.state, "ready")
        self.assertEqual(self.scheduled, [])

    def test_repeated_empty_syncs_schedule_only_one_retry(self):
        self.book.results = [EMPTY, EMPTY, EMPTY, FULL]
        sync = self.make()
        sync.user_sync()
        sync.user_sync()
        sync.user_sync()
        self.assertEqual(len(self.scheduled), 1)
        self.run_scheduled()
        self.assertEqual(self.state, "ready")

    def test_retries_stop_after_the_window(self):
        self.make().user_sync()
        self.now += 181
        self.run_scheduled()
        self.assertEqual(self.state, "needs-permission")
        self.assertEqual(self.scheduled, [])

    def test_empty_pull_keeps_cached_contacts(self):
        cached = [{"name": "Old", "numbers": [{"number": "1", "label": ""}]}]
        self.make(contacts=cached).connected()
        self.assertEqual(self.sync.contacts.contacts, cached)
        self.assertEqual(self.state, "needs-permission")
        self.assertEqual(self.scheduled, [])  # no retry loop without a user click

    def test_connected_syncs_when_enabled(self):
        self.book.results = [FULL]
        self.make(enabled=True).connected()
        self.assertEqual(self.book.pulls[0][1], ("pb", "cch", "mch"))

    def test_call_ended_syncs_history_only_after_delay(self):
        self.make(enabled=True).call_ended()
        self.assertEqual(self.book.pulls, [])
        self.assertEqual(self.scheduled[0][0], 3.0)
        self.run_scheduled()
        self.assertEqual(self.book.pulls, [(self.address, ("cch", "mch"))])

    def test_error_keeps_cache_and_reports(self):
        cached = [{"name": "Old", "numbers": [{"number": "1", "label": ""}]}]
        self.book.results = ["Unable to connect"]
        self.make(contacts=cached).user_sync()
        self.assertEqual(self.listener.statuses[-1]["message"], "Unable to connect")
        self.assertEqual(self.state, "error")
        self.assertEqual(self.sync.contacts.contacts, cached)

    def test_a_refused_connect_says_what_to_do(self):
        self.book.results = ["OBEX Connect failed with 0x41"]
        self.make().user_sync()
        self.assertEqual((self.state, self.listener.statuses[-1]["message"]), ("error", REFUSED))

    def test_history_failure_keeps_a_good_phonebook(self):
        self.book.results = [({"pb": FULL["pb"]}, {"cch": "Forbidden", "mch": "Forbidden"})]
        self.make().user_sync()
        self.assertEqual(self.state, "ready")
        self.assertIn("Ali Ahmad", [c["name"] for c in ContactsStore(self.dir / "contacts.json").contacts])
        self.assertEqual((self.listener.contacts, self.listener.history), (1, 0))

    def test_phonebook_failure_still_takes_the_history(self):
        self.book.results = [({"cch": FULL["cch"], "mch": FULL["mch"]}, {"pb": "Forbidden"})]
        self.make().user_sync()
        self.assertEqual((self.state, self.listener.statuses[-1]["message"]), ("error", "Forbidden"))
        self.assertEqual(len(HistoryStore(self.dir / "history.json").calls), 3)

    def test_half_a_history_is_not_saved(self):
        self.book.results = [FULL, ({"pb": FULL["pb"], "cch": FULL["cch"]}, {"mch": "Forbidden"})]
        self.make().user_sync()
        self.sync.user_sync()
        self.assertEqual(len(self.sync.history.missed), 2)  # the first sync's list is kept
        self.assertEqual(self.listener.history, 1)

    def test_last_error_is_shown_after_a_restart(self):
        self.book.results = ["Unable to connect"]
        self.make().user_sync()
        self.make()
        self.assertEqual((self.state, self.listener.statuses[-1]["message"]), ("error", "Unable to connect"))

    def test_needs_permission_is_shown_after_a_restart(self):
        self.book.results = ["Unable to connect", EMPTY]
        self.make().user_sync()
        self.sync.user_sync()
        self.make()
        self.assertEqual((self.state, self.listener.statuses[-1]["message"]), ("needs-permission", ""))

    def test_ready_after_a_restart_even_if_the_last_sync_failed(self):
        self.book.results = [FULL, "Unable to connect"]
        self.make().user_sync()
        self.sync.user_sync()
        self.make()
        self.assertEqual(self.state, "ready")

    def test_failed_sync_after_connect_is_retried(self):
        self.book.results = ["Unable to connect", FULL]
        self.make(enabled=True).connected()
        self.assertEqual(self.state, "error")
        self.assertEqual(self.scheduled[0][0], 5.0)
        self.run_scheduled()
        self.assertEqual(self.state, "ready")

    def test_connect_retries_are_limited(self):
        self.book.results = ["Unable to connect"] * 10
        self.make(enabled=True).connected()
        for _ in range(10):
            self.run_scheduled()
        self.assertEqual(len(self.book.pulls), 3)
        self.assertEqual(self.state, "error")

    def test_user_sync_while_not_connected(self):
        self.address = None
        self.make().user_sync()
        self.assertEqual((self.state, self.listener.statuses[-1]["message"]), ("error", "Phone not connected"))
        self.assertEqual(self.book.pulls, [])

    def test_requests_during_a_sync_run_once_afterwards(self):
        self.book.defer = True
        self.make(enabled=True).user_sync()
        self.sync.connected()
        self.sync.call_ended()
        self.run_scheduled()
        self.assertEqual(len(self.book.pulls), 1)
        self.book.release()
        self.assertEqual([p[1] for p in self.book.pulls], [("pb", "cch", "mch"), ("pb", "cch", "mch")])

    def test_install_opens_terminal_and_syncs_when_ready(self):
        self.book.ok = False
        self.book.results = [FULL]
        self.make().install()
        self.assertEqual(self.spawned, [INSTALL_ARGV])
        self.run_scheduled()          # still missing: checks again later
        self.assertEqual(len(self.scheduled), 1)
        self.book.ok = True
        self.run_scheduled()
        self.assertEqual(self.state, "ready")
        self.assertTrue(self.sync.contacts.enabled)

    def test_install_checks_stop_after_the_window(self):
        self.book.ok = False
        self.make().install()
        self.now += 601
        self.run_scheduled()
        self.assertEqual(self.scheduled, [])
        self.assertEqual(self.state, "needs-install")

    def test_install_twice_polls_once(self):
        self.book.ok = False
        self.make().install()
        self.sync.install()
        self.assertEqual(len(self.scheduled), 1)

    def test_terminal_failure_is_reported(self):
        def broken(argv):
            raise GLib.Error("no terminal")
        self.book.ok = False
        self.make()
        self.sync._spawn = broken
        self.sync.install()
        self.assertEqual(self.state, "error")
        self.assertIn("Could not open a terminal", self.listener.statuses[-1]["message"])
