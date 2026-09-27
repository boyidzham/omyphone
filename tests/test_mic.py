import subprocess
import unittest

from omyphone.mic import SOURCE, Mic


class FakeWpctl:
    def __init__(self, muted=False):
        self.muted = muted
        self.calls = []

    def __call__(self, argv, **kwargs):
        self.calls.append(argv[1:])
        if argv[1] == "get-volume":
            return subprocess.CompletedProcess(argv, 0, "Volume: 1.00" + (" [MUTED]" if self.muted else ""), "")
        self.muted = argv[3] == "1"
        return subprocess.CompletedProcess(argv, 0, "", "")


class MicTests(unittest.TestCase):
    def test_refresh_reads_state(self):
        self.assertTrue(Mic(FakeWpctl(muted=True)).refresh())
        self.assertFalse(Mic(FakeWpctl(muted=False)).refresh())

    def test_mute_then_restore_unmutes(self):
        wpctl = FakeWpctl()
        mic = Mic(wpctl)
        mic.set_muted(True)
        self.assertTrue(wpctl.muted and mic.muted)
        mic.restore()
        self.assertFalse(wpctl.muted or mic.muted)
        self.assertIn(["set-mute", SOURCE, "0"], wpctl.calls)

    def test_restore_puts_back_a_mic_that_was_already_muted(self):
        wpctl = FakeWpctl(muted=True)
        mic = Mic(wpctl)
        mic.set_muted(False)
        mic.set_muted(True)
        mic.set_muted(False)
        mic.restore()
        self.assertTrue(wpctl.muted and mic.muted)

    def test_restore_without_changes_does_nothing(self):
        wpctl = FakeWpctl()
        Mic(wpctl).restore()
        self.assertEqual(wpctl.calls, [])

    def test_missing_wpctl_does_not_raise(self):
        def broken(argv, **kwargs):
            raise FileNotFoundError("wpctl")
        mic = Mic(broken)
        self.assertFalse(mic.refresh())
        mic.set_muted(True)
        mic.restore()


if __name__ == "__main__":
    unittest.main()
