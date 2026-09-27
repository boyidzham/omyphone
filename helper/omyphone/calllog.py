"""Turns call lifecycles (states reported by PipeWire) into recents entries."""


class CallLog:
    def __init__(self, clock):
        self._clock = clock
        self._calls = {}

    def update(self, path, number, state):
        info = self._calls.get(path)
        if info is None:
            info = {"number": "", "start": self._clock(), "incoming": state in ("incoming", "waiting"),
                    "active_at": None, "declined": False}
            self._calls[path] = info
        if number:
            info["number"] = number
        if state == "active" and info["active_at"] is None:
            info["active_at"] = self._clock()

    def mark_declined(self, path):
        if path in self._calls:
            self._calls[path]["declined"] = True

    def remove(self, path):
        """Stop tracking a call. Returns its recents entry, or None if unknown."""
        info = self._calls.pop(path, None)
        if info is None:
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
