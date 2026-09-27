"""Mutes the default microphone during a call and restores it afterwards (wpctl)."""
import subprocess
import sys

SOURCE = "@DEFAULT_AUDIO_SOURCE@"


class Mic:
    def __init__(self, run=subprocess.run):
        self._run = run
        self._saved = None  # mute state before this call's first change; None = untouched
        self.muted = False

    def refresh(self):
        self.muted = self._is_muted()
        return self.muted

    def set_muted(self, on):
        if self._saved is None:
            self._saved = self._is_muted()
        self._wpctl("set-mute", SOURCE, "1" if on else "0")
        self.muted = on

    def restore(self):
        if self._saved is None:
            return
        self._wpctl("set-mute", SOURCE, "1" if self._saved else "0")
        self.muted = self._saved
        self._saved = None

    def _is_muted(self):
        result = self._wpctl("get-volume", SOURCE)
        return result is not None and "[MUTED]" in result.stdout

    def _wpctl(self, *args):
        try:
            return self._run(["wpctl", *args], capture_output=True, text=True, timeout=5)
        except (OSError, subprocess.SubprocessError) as error:
            print(f"omyphone: wpctl failed: {error}", file=sys.stderr)
            return None
