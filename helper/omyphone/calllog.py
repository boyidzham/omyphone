"""Turns call lifecycles (states reported by PipeWire) into recents entries.

PipeWire reports a call's state but not its direction or start time, so both
are learned by watching the call from its first state. Calls in progress are
also kept in a file, so a helper restarted mid-call (or a telephony service
that restarted) picks the same call up again instead of guessing. A call first
seen already going, such as when the phone connects mid-call, has no known
direction or start: it gets no timer and is not logged.
"""
import sys
from pathlib import Path

from .contacts import read_json, write_private

STARTS = ("incoming", "waiting", "dialing", "alerting")


def _valid(info):
    number = (int, float)
    return (isinstance(info, dict) and isinstance(info.get("number"), str)
            and isinstance(info.get("start"), number) and isinstance(info.get("incoming"), bool)
            and (info.get("active_at") is None or isinstance(info.get("active_at"), number))
            and isinstance(info.get("declined"), bool) and isinstance(info.get("known"), bool))


class CallLog:
    def __init__(self, clock, path=None):
        self._clock = clock
        self._path = Path(path) if path else None
        self._calls = {}
        self._parked = self._load()  # calls no longer reported that may come back

    def update(self, path, number, state):
        info = self._calls.get(path)
        if info is None:
            parked = self._parked.pop(path, None)
            if parked is not None and state not in STARTS:
                info = parked
            else:
                info = {"number": "", "start": self._clock(), "incoming": state in ("incoming", "waiting"),
                        "active_at": None, "declined": False, "known": state in STARTS}
            self._calls[path] = info
        if number:
            info["number"] = number
        if state == "active" and info["active_at"] is None and info["known"]:
            info["active_at"] = self._clock()
        self._save()

    def active_since(self, path):
        """When the call was answered (clock seconds), or 0 if not yet or unknown."""
        info = self._calls.get(path)
        return info["active_at"] or 0 if info else 0

    def mark_declined(self, path):
        if path in self._calls:
            self._calls[path]["declined"] = True
            self._save()

    def park(self, path):
        """The call is no longer reported but may still be going on the phone."""
        if path in self._calls:
            self._parked[path] = self._calls.pop(path)
            self._save()

    def remove(self, path):
        """Stop tracking an ended call. Returns its recents entry, or None if
        unknown or first seen mid-call."""
        info = self._calls.pop(path, None)
        if not self._calls:
            self._parked.clear()
        self._save()
        if info is None or not info["known"]:
            return None
        answered = info["active_at"] is not None
        duration = int(round(self._clock() - info["active_at"])) if answered else 0
        if not info["incoming"]:
            direction = "outgoing"
        elif not answered and not info["declined"]:
            direction = "missed"
        else:
            direction = "incoming"
        return {"number": info["number"], "direction": direction,
                "start": int(info["start"]), "duration": max(0, duration)}

    def _load(self):
        if not self._path:
            return {}
        data = read_json(self._path, dict)
        if data is None:
            return {}
        return {path: info for path, info in data.items() if _valid(info)}

    def _save(self):
        if not self._path:
            return
        calls = {**self._parked, **self._calls}
        try:
            if calls:
                write_private(self._path, calls)
            else:
                self._path.unlink(missing_ok=True)
        except OSError as error:
            print(f"omyphone: could not save calls in progress: {error}", file=sys.stderr)
