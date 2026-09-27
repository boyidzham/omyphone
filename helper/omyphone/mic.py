"""Mutes the default microphone during a call and restores it afterwards (wpctl)."""
import subprocess
import sys
from pathlib import Path

SOURCE = "@DEFAULT_AUDIO_SOURCE@"


class Mic:
    def __init__(self, run=subprocess.run, state_path=None):
        self._run = run
        # The mute state from before this call's first change is also kept in a
        # file, so a helper restarted mid-call can still put it back.
        self._state = Path(state_path) if state_path else None
        self._saved = self._load()  # None = untouched this call
        self.muted = False

    def _load(self):
        try:
            return {"1": True, "0": False}.get(self._state.read_text().strip()) if self._state else None
        except OSError:
            return None

    def _store(self, value):
        if not self._state:
            return
        try:
            if value is None:
                self._state.unlink(missing_ok=True)
            else:
                self._state.parent.mkdir(parents=True, exist_ok=True)
                self._state.write_text("1" if value else "0")
        except OSError as error:
            print(f"omyphone: could not save mic state: {error}", file=sys.stderr)

    def refresh(self):
        self.muted = self._is_muted()
        return self.muted

    def set_muted(self, on):
        if self._saved is None:
            self._saved = self._is_muted()
            self._store(self._saved)
        self._wpctl("set-mute", SOURCE, "1" if on else "0")
        self.muted = on

    def restore(self):
        if self._saved is None:
            return
        self._wpctl("set-mute", SOURCE, "1" if self._saved else "0")
        self.muted = self._saved
        self._saved = None
        self._store(None)

    def _is_muted(self):
        result = self._wpctl("get-volume", SOURCE)
        return result is not None and "[MUTED]" in result.stdout

    def _wpctl(self, *args):
        try:
            return self._run(["wpctl", *args], capture_output=True, text=True, timeout=5)
        except (OSError, subprocess.SubprocessError) as error:
            print(f"omyphone: wpctl failed: {error}", file=sys.stderr)
            return None
