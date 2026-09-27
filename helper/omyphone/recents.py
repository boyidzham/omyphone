"""Recent calls, kept as a JSON list (newest first) under $XDG_STATE_HOME/omyphone."""
import json
import os
import sys
from pathlib import Path

from .contacts import numbers_match

LIMIT = 100
DIRECTIONS = ("incoming", "outgoing", "missed")
MATCH_WINDOW_S = 120


def default_path():
    base = os.environ.get("XDG_STATE_HOME") or os.path.join(os.path.expanduser("~"), ".local", "state")
    return Path(base) / "omyphone" / "recents.json"


def _valid(entry):
    return (isinstance(entry, dict) and isinstance(entry.get("number"), str)
            and entry.get("direction") in DIRECTIONS
            and isinstance(entry.get("start"), int) and isinstance(entry.get("duration"), int))


class Recents:
    def __init__(self, path):
        self.path = Path(path)
        self.entries = self._load()

    def _load(self):
        try:
            data = json.loads(self.path.read_text())
        except (OSError, ValueError):
            return []
        if not isinstance(data, list):
            return []
        return [e for e in data if _valid(e)][:LIMIT]

    def add(self, entry):
        self.entries.insert(0, entry)
        del self.entries[LIMIT:]
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.entries))
            os.replace(tmp, self.path)
        except OSError as error:
            print(f"omyphone: could not save recents: {error}", file=sys.stderr)


def merge(local, phone):
    """What Recent (or Missed) shows. With phone history: the phone's list, plus
    local entries it does not have yet (a call that just ended, before the
    history sync lands). Without it: the local log."""
    if phone is None:
        return list(local[:LIMIT])
    newest = max((e["start"] for e in phone), default=0)

    def known(entry):
        return any(numbers_match(p["number"], entry["number"])
                   and abs(p["start"] - entry["start"]) <= MATCH_WINDOW_S for p in phone)

    fresh = [e for e in local if e["start"] > newest and not known(e)]
    return (fresh + list(phone))[:LIMIT]
