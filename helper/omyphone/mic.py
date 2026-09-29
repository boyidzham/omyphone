"""Mutes the default microphone during a call and restores it afterwards (wpctl).

wpctl runs without blocking the helper: commands go through a queue, one at a
time and in order, and each reports back through a callback. Only
restore_now, for shutdown when the main loop has stopped, waits for wpctl.
"""
import subprocess
import sys
from pathlib import Path

from gi.repository import Gio, GLib

from .contacts import write_private_text

SOURCE = "@DEFAULT_AUDIO_SOURCE@"
TIMEOUT_S = 5


def gio_wpctl(args, on_done):
    """Run wpctl in the background; on_done(stdout), or on_done(None) if it failed."""
    try:
        proc = Gio.Subprocess.new(["wpctl", *args],
                                  Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_SILENCE)
    except GLib.Error as error:
        print(f"omyphone: wpctl failed: {error.message}", file=sys.stderr)
        on_done(None)
        return None
    timer = [0]

    def kill():
        timer[0] = 0
        print("omyphone: wpctl timed out", file=sys.stderr)
        proc.force_exit()
        return GLib.SOURCE_REMOVE

    def finished(proc, result):
        if timer[0]:
            GLib.source_remove(timer[0])
        try:
            _ok, stdout, _stderr = proc.communicate_utf8_finish(result)
        except GLib.Error as error:
            print(f"omyphone: wpctl failed: {error.message}", file=sys.stderr)
            stdout = None
        on_done(stdout)

    timer[0] = GLib.timeout_add_seconds(TIMEOUT_S, kill)
    proc.communicate_utf8_async(None, None, finished)
    return proc


class Mic:
    def __init__(self, wpctl=gio_wpctl, state_path=None, run=subprocess.run):
        self._wpctl = wpctl
        self._run = run
        # The mute state from before this call's first change is also kept in a
        # file, so a helper restarted mid-call can still put it back.
        self._state = Path(state_path) if state_path else None
        self._saved = self._load()  # None = untouched this call
        self._queue = []
        self._busy = False
        self._current = None  # the wpctl process running now, if any
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
                write_private_text(self._state, "1" if value else "0")
        except OSError as error:
            print(f"omyphone: could not save mic state: {error}", file=sys.stderr)

    # --- the queue ---

    def _enqueue(self, step):
        """step(next) does its work and then calls next()."""
        self._queue.append(step)
        if not self._busy:
            self._next()

    def _next(self):
        self._current = None
        if not self._queue:
            self._busy = False
            return
        self._busy = True
        self._queue.pop(0)(self._next)

    def _call(self, args, then):
        self._current = self._wpctl(args, then)

    # --- commands ---

    def refresh(self, on_done=None):
        def step(next_step):
            def read(stdout):
                self.muted = _is_muted(stdout)
                _report(on_done, self.muted)
                next_step()
            self._call(("get-volume", SOURCE), read)
        self._enqueue(step)

    def set_muted(self, on, on_done=None):
        def step(next_step):
            def mute(_stdout=None):
                def done(_stdout):
                    self.muted = on
                    _report(on_done, on)
                    next_step()
                self._call(("set-mute", SOURCE, "1" if on else "0"), done)

            def save(stdout):
                self._saved = _is_muted(stdout)
                self._store(self._saved)
                mute()
            if self._saved is None:
                self._call(("get-volume", SOURCE), save)
            else:
                mute()
        self._enqueue(step)

    def restore(self, on_done=None):
        def step(next_step):
            if self._saved is None:
                _report(on_done, self.muted)
                next_step()
                return
            saved = self._saved

            def done(_stdout):
                self.muted = saved
                self._saved = None
                self._store(None)
                _report(on_done, saved)
                next_step()
            self._call(("set-mute", SOURCE, "1" if saved else "0"), done)
        self._enqueue(step)

    def restore_now(self):
        """Put the mic back right away, waiting for wpctl: for shutdown only."""
        if self._current is not None:
            self._current.wait(None)  # let a running set-mute finish first
        if self._saved is None:
            return
        try:
            self._run(["wpctl", "set-mute", SOURCE, "1" if self._saved else "0"],
                      capture_output=True, timeout=TIMEOUT_S)
        except (OSError, subprocess.SubprocessError) as error:
            print(f"omyphone: wpctl failed: {error}", file=sys.stderr)
            return
        self.muted = self._saved
        self._saved = None
        self._store(None)


def _is_muted(stdout):
    return stdout is not None and "[MUTED]" in stdout


def _report(on_done, muted):
    if on_done:
        on_done(muted)
