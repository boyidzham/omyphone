"""Contacts and call-history caches, and looking a caller's name up by number.

Numbers match on their trailing digits, so "012 345 6789", "+60123456789" and
"+60 12-345 6789" are the same number without guessing country codes. Numbers
shorter than 7 digits (999, service codes) only match exactly.
"""
import json
import os
import re
import sys
from pathlib import Path

MIN_DIGITS = 7
MAX_DIGITS = 9
DIRECTIONS = ("incoming", "outgoing", "missed")


def _digits(number):
    return re.sub(r"\D", "", number or "")


def numbers_match(a, b):
    a, b = _digits(a), _digits(b)
    if not a or not b:
        return False
    if len(a) < MIN_DIGITS or len(b) < MIN_DIGITS:
        return a == b
    n = min(len(a), len(b), MAX_DIGITS)
    return a[-n:] == b[-n:]


def _by_name(contacts):
    """A-Z by name, contacts without a name last."""
    return sorted(contacts, key=lambda c: (c["name"] == "", c["name"].casefold()))


class Directory:
    """Name lookup by number. When contacts share a number, the first A-Z wins.
    Contacts without a name are left out, so they never hide a named one."""

    def __init__(self, contacts):
        self._buckets = {}  # last 7 digits -> [(digits, name)]
        for contact in _by_name(c for c in contacts if c["name"]):
            for entry in contact["numbers"]:
                digits = _digits(entry["number"])
                if digits:
                    self._buckets.setdefault(digits[-MIN_DIGITS:], []).append((digits, contact["name"]))

    def lookup(self, number):
        digits = _digits(number)
        if not digits:
            return ""
        for other, name in self._buckets.get(digits[-MIN_DIGITS:], ()):
            if numbers_match(digits, other):
                return name
        return ""


def rows(contacts):
    """One row per number for the Contacts tab, sorted by name (nameless last)."""
    return [{"name": c["name"], "number": n["number"], "label": n["label"]}
            for c in _by_name(contacts) for n in c["numbers"]]


def write_private(path, data):
    """Write JSON readable only by this user, through a temp file so a crash never leaves half a file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as file:
        os.fchmod(file.fileno(), 0o600)
        json.dump(data, file)
    os.replace(tmp, path)


def _read(path):
    try:
        data = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _save(path, data):
    try:
        write_private(path, data)
    except OSError as error:
        print(f"omyphone: could not save {Path(path).name}: {error}", file=sys.stderr)


def _int(value):
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _valid_contact(c):
    return (isinstance(c, dict) and isinstance(c.get("name"), str) and isinstance(c.get("numbers"), list)
            and all(isinstance(n, dict) and isinstance(n.get("number"), str) and isinstance(n.get("label"), str)
                    for n in c["numbers"]))


def _valid_call(e):
    return (isinstance(e, dict) and isinstance(e.get("name"), str) and isinstance(e.get("number"), str)
            and e.get("direction") in DIRECTIONS and _int(e.get("start")) == e.get("start"))


def _list(data, key, valid):
    items = data.get(key)
    return [item for item in items if valid(item)] if isinstance(items, list) else []


class ContactsStore:
    def __init__(self, path):
        self.path = Path(path)
        data = _read(self.path)
        self.enabled = data.get("enabled") is True
        self.synced = _int(data.get("synced"))
        self.contacts = _list(data, "contacts", _valid_contact)
        # How the last pull of the phonebook went: "ready", "needs-permission" or
        # "error" (with its message), so a restart shows the same thing again.
        last = data.get("last")
        valid = isinstance(last, dict) and isinstance(last.get("state"), str) and isinstance(last.get("message"), str)
        self.last = {"state": last["state"], "message": last["message"]} if valid else {"state": "", "message": ""}

    def save(self):
        _save(self.path, {"enabled": self.enabled, "synced": self.synced, "contacts": self.contacts,
                          "last": self.last})


class HistoryStore:
    def __init__(self, path):
        self.path = Path(path)
        data = _read(self.path)
        self.synced = _int(data.get("synced"))
        self.calls = _list(data, "calls", _valid_call)
        self.missed = _list(data, "missed", _valid_call)

    def save(self):
        _save(self.path, {"synced": self.synced, "calls": self.calls, "missed": self.missed})
