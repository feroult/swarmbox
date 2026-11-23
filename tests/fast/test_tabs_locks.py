"""The lock files of swarmbox-tabs (one per tab, in <run folder>/tabs/): those of tabs that are gone are deleted past LOCK_KEEP, those of live tabs and of
a send that is still typing never are, and a send that waited for a lock that was deleted takes the new file (two sends to one tab never interleave).
Against the FAKE hc of tests/support/tabs_support.py: no herdr-core, network or model. Run with: python3 -W error tests/fast/test_tabs_locks.py
"""
import fcntl
import os
import sys
import threading
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "support"))
from tabs_support import FakeHc, load_module  # noqa: E402

mod = load_module()


class Locks(unittest.TestCase):
    def setUp(self):
        self.ft = FakeHc()
        self.addCleanup(self.ft.close)
        self.ft.term("t1", "one")
        self.ft.term("t2", "two")
        self.ft.save()
        self.d = os.path.join(self.ft.dir, "tabs")
        os.makedirs(self.d, mode=0o700, exist_ok=True)

    def make_dead(self, n):
        for i in range(100, 100 + n):
            open(os.path.join(self.d, "tab-%d.lock" % i), "w").close()

    def names(self):
        return sorted(os.listdir(self.d))

    def test_the_locks_of_tabs_that_are_gone_are_deleted_past_the_limit_and_live_ones_stay(self):
        self.make_dead(mod.LOCK_KEEP + 30)
        d = self.ft.driver()
        d.send("t1", run="a")
        d.send("t2", run="b")
        self.assertEqual(self.names(), ["tab-t1.lock", "tab-t2.lock"], "the dead ones went, the live ones (and the new ones) are there")

    def test_a_few_old_locks_are_left_alone(self):
        self.make_dead(10)
        self.ft.driver().send("t1", run="a")
        self.assertEqual(len(self.names()), 11)

    def test_a_lock_that_is_held_is_never_deleted(self):
        self.make_dead(mod.LOCK_KEEP + 5)
        held = os.path.join(self.d, "tab-100.lock")
        fd = os.open(held, os.O_RDWR)
        fcntl.flock(fd, fcntl.LOCK_EX)
        try:
            self.ft.driver().send("t1", run="a")
        finally:
            os.close(fd)
        self.assertIn("tab-100.lock", self.names(), "a send to a tab that is just closing still holds it")
        self.assertEqual(len(self.names()), 2)

    def test_a_send_that_waited_for_a_deleted_lock_takes_the_new_file(self):
        """A holds the file; B waits on it; the file is deleted and A lets go; B must not go on with the lock of an inode nobody can see: it takes the
        file that a third sender now creates, so B and C do not type together"""
        d = self.ft.driver(lock_timeout=5)
        path = os.path.join(self.d, "tab-t1.lock")
        open(path, "w").close()
        a = os.open(path, os.O_RDWR)
        fcntl.flock(a, fcntl.LOCK_EX)
        got = []

        def b():
            with d._lock("t1"):
                got.append(os.path.exists(path))
        t = threading.Thread(target=b)
        t.start()
        time.sleep(0.3)
        os.unlink(path)                    # the sweep
        os.close(a)                        # A lets go of the unlinked file: B's flock succeeds on it
        t.join(10)
        self.assertEqual(len(got), 1)
        self.assertTrue(os.path.exists(path), "B created the new file and holds that one")


if __name__ == "__main__":
    unittest.main()
