import tempfile
import unittest
from pathlib import Path

from omyphone.mic import SOURCE, Mic


class FakeWpctl:
    """Stands in for wpctl. With hold=True, each command waits for finish()."""

    def __init__(self, muted=False, hold=False):
        self.muted = muted
        self.hold = hold
        self.calls = []
        self.waiting = []

    def __call__(self, args, on_done):
        self.calls.append(list(args))
        if self.hold:
            self.waiting.append((args, on_done))
        else:
            self.answer(args, on_done)

    def answer(self, args, on_done):
        if args[0] == "get-volume":
            on_done("Volume: 1.00" + (" [MUTED]" if self.muted else ""))
        else:
            self.muted = args[2] == "1"
            on_done("")

    def finish(self):
        args, on_done = self.waiting.pop(0)
        self.answer(args, on_done)


def run(args, **kwargs):
    raise AssertionError("the blocking wpctl is only for shutdown")


class MicTests(unittest.TestCase):
    def results(self):
        seen = []
        return seen, seen.append

    def test_refresh_reads_state(self):
        for muted in (True, False):
            seen, done = self.results()
            Mic(FakeWpctl(muted=muted), run=run).refresh(done)
            self.assertEqual(seen, [muted])

    def test_mute_then_restore_unmutes(self):
        wpctl = FakeWpctl()
        mic = Mic(wpctl, run=run)
        seen, done = self.results()
        mic.set_muted(True, done)
        self.assertTrue(wpctl.muted and mic.muted)
        mic.restore(done)
        self.assertFalse(wpctl.muted or mic.muted)
        self.assertEqual(seen, [True, False])
        self.assertIn(["set-mute", SOURCE, "0"], wpctl.calls)

    def test_restore_puts_back_a_mic_that_was_already_muted(self):
        wpctl = FakeWpctl(muted=True)
        mic = Mic(wpctl, run=run)
        mic.set_muted(False)
        mic.set_muted(True)
        mic.set_muted(False)
        mic.restore()
        self.assertTrue(wpctl.muted and mic.muted)

    def test_restore_without_changes_does_nothing(self):
        wpctl = FakeWpctl()
        seen, done = self.results()
        Mic(wpctl, run=run).restore(done)
        self.assertEqual(wpctl.calls, [])
        self.assertEqual(seen, [False])

    def test_commands_run_one_at_a_time_in_order(self):
        wpctl = FakeWpctl(hold=True)
        mic = Mic(wpctl, run=run)
        seen, done = self.results()
        mic.set_muted(True, done)
        mic.restore(done)
        self.assertEqual(wpctl.calls, [["get-volume", SOURCE]])  # nothing else starts meanwhile
        while wpctl.waiting:
            wpctl.finish()
        self.assertEqual(wpctl.calls, [["get-volume", SOURCE], ["set-mute", SOURCE, "1"],
                                       ["set-mute", SOURCE, "0"]])
        self.assertEqual(seen, [True, False])
        self.assertFalse(wpctl.muted)

    def test_saved_state_survives_a_helper_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "omyphone" / "mic-before-call"
            wpctl = FakeWpctl(muted=False)
            Mic(wpctl, state, run=run).set_muted(True)
            again = Mic(wpctl, state, run=run)  # a new helper, mid-call
            again.set_muted(False)
            again.set_muted(True)
            again.restore()
            self.assertFalse(wpctl.muted)
            self.assertFalse(state.exists())

    def test_restore_now_blocks_for_shutdown(self):
        wpctl = FakeWpctl()
        ran = []
        mic = Mic(wpctl, run=lambda argv, **kwargs: ran.append(argv))
        mic.set_muted(True)
        mic.restore_now()
        self.assertEqual(ran, [["wpctl", "set-mute", SOURCE, "0"]])
        mic.restore_now()  # nothing left to put back
        self.assertEqual(len(ran), 1)

    def test_failed_wpctl_does_not_raise(self):
        def broken(args, on_done):
            on_done(None)

        def broken_run(argv, **kwargs):
            raise FileNotFoundError("wpctl")
        mic = Mic(broken, run=broken_run)
        seen, done = self.results()
        mic.refresh(done)
        self.assertEqual(seen, [False])
        mic.set_muted(True)
        mic.restore_now()


if __name__ == "__main__":
    unittest.main()
