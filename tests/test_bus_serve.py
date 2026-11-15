"""Step 6b of `swarmbox-entrypoint serve` with the REAL broker (everything else of serve is the fakes of tests/test_serve_steps.py):
the step starts the broker, which answers on <run folder>/bus.sock; killed with -9 it is started again after the backoff of 1 s and takes
over the stale socket; SIGTERM of serve removes the socket. No tmux, no network. Run with: python3 tests/test_bus_serve.py
"""
import os
import signal
import subprocess
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bus_support import BUS_PATH, rpc  # noqa: E402
from test_serve_steps import ServeCase, alive, wait_for, write_exec  # noqa: E402


class RealBroker(ServeCase):
    def setUp(self):
        super().setUp()
        write_exec(os.path.join(self.fake, "swarmbox-bus"), '#!/bin/sh\nexec %s -S %s "$@"\n' % (sys.executable, BUS_PATH))
        self.sock = os.path.join(self.run_dir, "bus.sock")

    def bus(self, *args, stdin=None):
        env = dict(self.env(), SB_BUS_SOCKET=self.sock)
        return subprocess.run(["swarmbox-bus", *args], env=env, input=stdin, capture_output=True, timeout=20)

    def broker_pid(self):
        try:
            return rpc(self.sock, {"op": "ping"}, 2)["pid"]
        except (OSError, TypeError, KeyError):
            return None

    def test_the_step_starts_the_broker_and_the_bus_works_end_to_end(self):
        p = self.run_ready()
        self.assertEqual(self.marker(), "ok")
        self.assertEqual(self.health_lines(), [])
        self.assertEqual(self.bus("ping").returncode, 0)
        self.assertEqual(oct(os.stat(self.sock).st_mode & 0o777), "0o600")
        sub = subprocess.Popen(["swarmbox-bus", "sub", "--raw", "-v"], env=dict(self.env(), SB_BUS_SOCKET=self.sock),
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertIn(b"subscribed", sub.stderr.readline())
        self.assertEqual(self.bus("pub", "goal", "hello").returncode, 0)
        self.assertEqual(sub.stdout.readline(), b"hello\n")
        sub.terminate()
        sub.wait()
        sub.stdout.close(), sub.stderr.close()
        self.assertIn("listening on", open(os.path.join(self.state, "bus.log")).read())
        self.stop(p)

    def test_a_killed_broker_is_restarted_after_the_backoff_and_takes_over_the_stale_socket(self):
        p = self.run_ready(SWARMBOX_TEST_BACKOFF_SCALE="1")
        pid = self.broker_pid()
        self.assertTrue(pid)
        sup = int(open(os.path.join(self.run_dir, "bus-supervisor.pid")).read())
        t0 = time.time()
        os.kill(pid, signal.SIGKILL)
        self.assertTrue(os.path.exists(self.sock), "kill -9 leaves the socket file")
        self.assertEqual(self.bus("ping").returncode, 4)
        new = wait_for(lambda: (self.broker_pid() or None), 8)
        dt = time.time() - t0
        self.assertTrue(new and new != pid, "the broker was not started again")
        self.assertGreaterEqual(dt, 0.9, "the first retry waits 1 s")
        self.assertLess(dt, 4)
        self.assertTrue(alive(sup))
        self.assertIn("bus exited; restarting in 1 s", self.serve_log())
        self.assertEqual(self.bus("ls").returncode, 0)          # the broker answers (its driver is the tmux one: this run has no tmux session)
        # a second kill: 2 s of backoff
        t0 = time.time()
        os.kill(new, signal.SIGKILL)
        again = wait_for(lambda: (self.broker_pid() or None), 10)
        self.assertTrue(again and again != new)
        self.assertGreaterEqual(time.time() - t0, 1.9)
        self.assertIn("bus exited; restarting in 2 s", self.serve_log())
        self.stop(p)

    def test_sigterm_of_serve_stops_the_broker_and_removes_the_socket(self):
        p = self.run_ready()
        pid = self.broker_pid()
        self.assertEqual(self.stop(p), 143)
        self.assertTrue(wait_for(lambda: not alive(pid), 5))
        self.assertFalse(os.path.exists(self.sock))
        self.assertFalse(os.path.exists(os.path.join(self.run_dir, "bus-supervisor.pid")))

    def test_a_broker_that_is_already_running_is_left_alone(self):
        p = self.run_ready()
        pid = self.broker_pid()
        r = self.bus("serve")
        self.assertEqual(r.returncode, 8)
        self.assertEqual(self.broker_pid(), pid)
        self.stop(p)


if __name__ == "__main__":
    unittest.main()
