"""Step 6b of `swarmbox-entrypoint serve` with the REAL broker (everything else of serve is the fakes of tests/fast/test_serve_steps.py):
the step starts the broker, which answers on <run folder>/bus.sock; killed with -9 it is started again after the backoff of 1 s and takes
over the stale socket; SIGTERM of serve removes the socket. No multiplexer, no network. Run with: python3 tests/fast/test_bus_serve.py
"""
import concurrent.futures
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
    @classmethod
    def _make_case(cls):
        c = ServeCase()
        c.setUp()
        write_exec(os.path.join(c.fake, "swarmbox-bus"), '#!/bin/sh\nexec %s -S %s "$@"\n' % (sys.executable, BUS_PATH))
        c.sock = os.path.join(c.run_dir, "bus.sock")
        c.proc = c.run_ready()
        return c

    @classmethod
    def setUpClass(cls):
        if os.environ.get("SWARMBOX_RUNNER_PARALLEL"):
            cases = [cls._make_case() for _ in range(3)]
        else:
            with concurrent.futures.ThreadPoolExecutor(max_workers=3) as ex:
                futs = [ex.submit(cls._make_case) for _ in range(3)]
                cases = [f.result() for f in futs]
        for c in cases:
            cls.addClassCleanup(c.doCleanups)
        cls._shared, cls._kill, cls._stop = cases

    def setUp(self):
        pass

    def _bus(self, c, *args, stdin=None):
        env = dict(c.env(), SB_BUS_SOCKET=c.sock)
        return subprocess.run(["swarmbox-bus", *args], env=env, input=stdin, capture_output=True, timeout=20)

    def _broker_pid(self, c):
        try:
            return rpc(c.sock, {"op": "ping"}, 2)["pid"]
        except (OSError, TypeError, KeyError):
            return None

    def test_the_step_starts_the_broker_and_the_bus_works_end_to_end(self):
        c = self._shared
        self.assertEqual(c.marker(), "ok")
        self.assertEqual(c.health_lines(), [])
        self.assertEqual(self._bus(c, "ping").returncode, 0)
        self.assertEqual(oct(os.stat(c.sock).st_mode & 0o777), "0o600")
        sub = subprocess.Popen(["swarmbox-bus", "sub", "--raw", "-v", "jobs"], env=dict(c.env(), SB_BUS_SOCKET=c.sock),
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.addCleanup(lambda: (sub.poll() is None and sub.kill(), sub.wait(), sub.stdout.close(), sub.stderr.close()))
        self.assertIn(b"subscribed", sub.stderr.readline())
        self.assertEqual(self._bus(c, "pub", "jobs", "hello").returncode, 0)
        self.assertEqual(sub.stdout.readline(), b"hello\n")
        sub.terminate()
        sub.wait()
        self.assertIn("listening on", open(os.path.join(c.state, "bus.log")).read())

    def test_a_killed_broker_is_started_again_and_takes_over_the_stale_socket(self):
        """(the values of the backoff, 1 s then 2 s, are tested in test_serve_steps.py with fakes: here the backoff is 0)"""
        c = self._kill
        pid = self._broker_pid(c)
        self.assertTrue(pid)
        sup = int(open(os.path.join(c.run_dir, "bus-supervisor.pid")).read())
        os.kill(pid, signal.SIGKILL)
        new = wait_for(lambda: (self._broker_pid(c) not in (None, pid)) and self._broker_pid(c), 8, 0.01)
        self.assertTrue(new, "the broker was not started again")
        self.assertTrue(alive(sup))
        self.assertEqual(self._bus(c, "topics").returncode, 0)      # the new broker answers on the old socket path
        c.stop(c.proc)

    def test_sigterm_of_serve_stops_the_broker_and_removes_the_socket(self):
        c = self._stop
        pid = self._broker_pid(c)
        self.assertEqual(c.stop(c.proc), 143)
        self.assertTrue(wait_for(lambda: not alive(pid), 5, 0.01))
        self.assertFalse(os.path.exists(c.sock))
        self.assertFalse(os.path.exists(os.path.join(c.run_dir, "bus-supervisor.pid")))

    def test_a_broker_that_is_already_running_is_left_alone(self):
        c = self._shared
        pid = self._broker_pid(c)
        r = self._bus(c, "serve")
        self.assertEqual(r.returncode, 8)
        self.assertEqual(self._broker_pid(c), pid)


if __name__ == "__main__":
    unittest.main()
