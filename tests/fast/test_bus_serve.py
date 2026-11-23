"""Step 6b of `swarmbox-entrypoint serve` with the REAL broker (everything else of serve is the fakes of tests/fast/test_serve_steps.py):
the step starts the broker, which answers on <run folder>/bus.sock; killed with -9 it is started again after the backoff of 1 s and takes
over the stale socket; SIGTERM of serve removes the socket. No multiplexer, no network. Run with: python3 tests/fast/test_bus_serve.py
"""
import os
import signal
import subprocess
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "support"))
from bus_support import BUS_PATH, rpc  # noqa: E402
from serve_support import ServeCase, alive, wait_for, write_exec  # noqa: E402


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
        sub = subprocess.Popen(["swarmbox-bus", "sub", "--raw", "-v", "jobs"], env=dict(self.env(), SB_BUS_SOCKET=self.sock),
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertIn(b"subscribed", sub.stderr.readline())
        self.assertEqual(self.bus("pub", "jobs", "hello").returncode, 0)
        self.assertEqual(sub.stdout.readline(), b"hello\n")
        sub.terminate()
        sub.wait()
        sub.stdout.close(), sub.stderr.close()
        self.assertIn("listening on", open(os.path.join(self.state, "bus.log")).read())
        self.stop(p)

    def test_a_killed_broker_is_started_again_and_takes_over_the_stale_socket(self):
        """(the values of the backoff, 1 s then 2 s, are tested in test_serve_steps.py with fakes: here the backoff is 0)"""
        p = self.run_ready()
        pid = self.broker_pid()
        self.assertTrue(pid)
        sup = int(open(os.path.join(self.run_dir, "bus-supervisor.pid")).read())
        os.kill(pid, signal.SIGKILL)
        new = wait_for(lambda: (self.broker_pid() not in (None, pid)) and self.broker_pid(), 8)
        self.assertTrue(new, "the broker was not started again")
        self.assertTrue(alive(sup))
        self.assertEqual(self.bus("topics").returncode, 0)      # the new broker answers on the old socket path
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
