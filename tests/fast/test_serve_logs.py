"""The log trimmer of `swarmbox-entrypoint serve`: the logs of the box (serve.log, bus.log, web-terminal.log) are written for weeks by `>>` redirections, so
the entrypoint cuts each one to its last quarter when it passes SWARMBOX_TEST_LOG_MAX (4 MiB in the box), looking every SWARMBOX_TEST_LOG_EVERY seconds (300),
and it ends with the box. The fakes of tests/support/serve_support.py (no real herdr-core, web server, podman or bus). Run with: python3 -W error tests/fast/test_serve_logs.py
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "support"))
import serve_support as tss  # noqa: E402


class Trimmer(tss.ServeCase):
    def big(self, name, size):
        os.makedirs(self.state, exist_ok=True)
        path = os.path.join(self.state, name)
        with open(path, "w") as f:
            for i in range(size // 50):
                f.write("%06d %s\n" % (i, "x" * 42))
        return path

    def test_a_log_past_the_limit_is_cut_to_its_last_quarter_and_a_small_one_is_left_alone(self):
        self.big("web-terminal.log", 8000)
        self.big("bus.log", 8000)
        self.big("serve.log", 9000)   # the serve log itself is trimmed too
        small = self.big("podman-service.log", 800)
        p = self.run_ready(SWARMBOX_TEST_LOG_EVERY="1", SWARMBOX_TEST_LOG_MAX="4000")
        web = os.path.join(self.state, "web-terminal.log")
        # the cut empties the file and then writes the end of it: wait for the finished log (its notice), not for the size
        self.assertTrue(tss.wait_for(lambda: "the log was cut" in tss.read(web), 15), "the log was not cut: %d bytes" % os.path.getsize(web))
        text = tss.read(web)
        self.assertIn("the log was cut to its last 1000 bytes", text)
        self.assertIn("000159 ", text, "what is kept is the END of the log")
        self.assertNotIn("000001 ", text)
        self.assertTrue(tss.wait_for(lambda: os.path.getsize(os.path.join(self.state, "bus.log")) < 4000, 15))
        self.assertTrue(tss.wait_for(lambda: os.path.getsize(os.path.join(self.state, "serve.log")) < 4000, 15))
        self.assertEqual(os.path.getsize(small), 800, "a log under the limit is not touched")
        # a writer that appends keeps writing at the new end
        with open(web, "a") as f:
            f.write("after the cut\n")
        self.assertTrue(tss.read(web).endswith("after the cut\n"))
        self.stop(p)

    def test_the_trimmer_ends_with_serve_and_leaves_no_sleep_behind(self):
        p = self.run_ready(SWARMBOX_TEST_LOG_EVERY="30")
        kids = lambda: [int(x) for x in os.listdir("/proc") if x.isdigit() and self.ppid(int(x)) == p.pid]
        self.assertTrue(kids())
        rc = self.stop(p)
        self.assertEqual(rc, 143)
        self.assertTrue(tss.wait_for(lambda: not kids(), 5), "children of serve are left: %s" % kids())

    @staticmethod
    def ppid(pid):
        try:
            with open("/proc/%d/stat" % pid) as f:
                return int(f.read().rsplit(")", 1)[1].split()[1])
        except (OSError, ValueError, IndexError):
            return -1


if __name__ == "__main__":
    unittest.main()
