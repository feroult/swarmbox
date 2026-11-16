"""The watcher of the resident sysop service (swarmbox_sysop/watch.py, `serve --watch`): it starts the service again when it is killed or crashes, and only
then. REAL processes: the Watcher runs in a child python (signals need a main thread) with a scripted child command, and the real `swarmbox-sysop serve
--watch` runs with the real service under it. No tmux, no model; the bus is not there (the service says `bus down` and goes on).
Run with: python3 -W error tests/test_sysop_watch.py
"""
import os
import signal
import subprocess
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sysop_support as ss  # noqa: E402

from swarmbox_sysop import paths  # noqa: E402

DRIVER = r"""
import sys
sys.path.insert(0, %(lib)r)
from swarmbox_sysop import paths, watch
w = watch.Watcher(paths.Paths(), %(argv)r, log=lambda m: print(m, flush=True), backoff=(0.05, 0.2), crashes=(%(n)d, 30.0))
sys.exit(w.run())
"""


def wait_for(fn, seconds=15.0):
    return ss.wait_for(fn, seconds, 0.05)


def alive(pid):
    try:
        os.kill(pid, 0)
        with open("/proc/%d/stat" % pid) as f:
            return f.read().rsplit(")", 1)[1].split()[0] != "Z"
    except (OSError, IndexError):
        return False


class Scripted(unittest.TestCase):
    """a driver around a child that is a python script: the script appends to a file at every start and then does what the test says"""

    def setUp(self):
        self.e = ss.Env()
        self.addCleanup(self.e.cleanup)
        self.starts = os.path.join(self.e.dir, "starts")
        self.mode = os.path.join(self.e.dir, "mode")
        self.procs = []
        self.addCleanup(self.stop_all)

    def stop_all(self):
        for p in self.procs:
            try:
                os.killpg(p.pid, signal.SIGKILL)        # the watcher and what it started: a group of their own
            except OSError:
                pass
            p.wait(5)

    def child_script(self):
        return ("import os, signal, sys, time\n"
                "open(%r, 'a').write('%%d\\n' %% os.getpid())\n"
                "mode = open(%r).read().strip() if os.path.exists(%r) else 'sleep'\n"
                "if mode.startswith('exit'): sys.exit(int(mode[4:] or 1))\n"
                "if mode == 'kill9': os.kill(os.getpid(), signal.SIGKILL)\n"
                "if mode == 'selfterm': os.kill(os.getpid(), signal.SIGTERM); time.sleep(5)\n"
                "time.sleep(60)\n" % (self.starts, self.mode, self.mode))

    def set_mode(self, m):
        with open(self.mode, "w") as f:
            f.write(m)

    def n_starts(self):
        try:
            with open(self.starts) as f:
                return len(f.read().split())
        except OSError:
            return 0

    def last_pid(self):
        with open(self.starts) as f:
            return int(f.read().split()[-1])

    def start_watcher(self, crashes=5):
        drv = DRIVER % {"lib": ss.LIB, "argv": [sys.executable, "-c", self.child_script()], "n": crashes}
        env = dict(self.e.env)
        p = subprocess.Popen([sys.executable, "-c", drv], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL, start_new_session=True)
        self.procs.append(p)
        return p

    def test_a_child_that_is_killed_is_started_again(self):
        w = self.start_watcher()
        self.assertTrue(wait_for(lambda: self.n_starts() == 1))
        first = self.last_pid()
        os.kill(first, signal.SIGKILL)
        self.assertTrue(wait_for(lambda: self.n_starts() == 2), "a kill -9 must not end the service for good")
        self.assertNotEqual(self.last_pid(), first)
        self.assertIsNone(w.poll(), "the watcher itself stays")

    def test_a_clean_exit_a_refused_setting_and_a_sigterm_are_not_restarted(self):
        for mode, rc in (("exit0", 0), ("exit2", 2)):
            with self.subTest(mode=mode):
                self.stop_all()
                for f in (self.starts,):
                    if os.path.exists(f):
                        os.unlink(f)
                self.set_mode(mode)
                w = self.start_watcher()
                self.assertEqual(w.wait(15), rc)
                self.assertEqual(self.n_starts(), 1)
        self.set_mode("selfterm")
        os.unlink(self.starts)
        w = self.start_watcher()
        self.assertEqual(w.wait(15), 0, "a child that ended by SIGTERM was stopped on purpose")
        self.assertEqual(self.n_starts(), 1)

    def test_a_crash_loop_ends_in_giving_up_with_a_file_that_says_so_and_a_second_watcher_wakes_it(self):
        self.set_mode("kill9")
        w = self.start_watcher(crashes=3)
        pth = paths.Paths(self.e.env)
        self.assertTrue(wait_for(lambda: os.path.exists(pth.crashloop)), "the panel and the user are told")
        self.assertEqual(self.n_starts(), 3)
        time.sleep(0.6)
        self.assertEqual(self.n_starts(), 3, "it gave up: no more starts")
        self.assertIsNone(w.poll(), "and it stays alive, waiting for the call")
        with open(pth.crashloop) as f:
            self.assertIn("keeps crashing", f.read())
        self.set_mode("sleep")
        w2 = self.start_watcher()                    # what `swarmbox-addon prepare` does
        self.assertEqual(w2.wait(10), 0, "a second watcher ends at once")
        self.assertTrue(wait_for(lambda: self.n_starts() == 4), "the first one started the service again")
        self.assertTrue(wait_for(lambda: not os.path.exists(pth.crashloop)))
        self.assertTrue(alive(self.last_pid()))

    def test_sigterm_stops_the_child_and_the_watcher_and_leaves_no_file(self):
        w = self.start_watcher()
        self.assertTrue(wait_for(lambda: self.n_starts() == 1))
        child = self.last_pid()
        pth = paths.Paths(self.e.env)
        self.assertTrue(os.path.exists(pth.watch_pidfile))
        w.send_signal(signal.SIGTERM)
        self.assertEqual(w.wait(15), 0)
        self.assertTrue(wait_for(lambda: not alive(child)), "the child went with it")
        self.assertFalse(os.path.exists(pth.watch_pidfile))


class RealService(unittest.TestCase):
    """the real `swarmbox-sysop serve --log --watch`: kill -9 the service, it comes back; TERM the service, it does not"""

    def setUp(self):
        self.e = ss.Env()
        self.addCleanup(self.e.cleanup)
        self.pth = self.e.paths
        self.env = dict(os.environ)
        self.env.update(self.e.env)
        self.env["PYTHONPATH"] = ss.LIB
        self.watcher = subprocess.Popen([sys.executable, "-B", "-m", "swarmbox_sysop", "serve", "--log", "--watch"], env=self.env,
                                        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        self.addCleanup(self.cleanup_procs)

    def cleanup_procs(self):
        for pid in (self.service_pid(), self.watcher.pid):
            if pid and alive(pid):
                try:
                    os.kill(pid, signal.SIGKILL)
                except OSError:
                    pass
        try:
            os.killpg(self.watcher.pid, signal.SIGKILL)      # whatever else the watcher started (a service that was being replaced)
        except OSError:
            pass
        try:
            self.watcher.wait(5)
        except subprocess.TimeoutExpired:
            pass

    def service_pid(self):
        try:
            with open(self.pth.pidfile) as f:
                return int(f.read().strip())
        except (OSError, ValueError):
            return None

    def test_kill_9_of_the_service_brings_it_back_and_a_term_does_not(self):
        self.assertTrue(wait_for(lambda: self.service_pid() and alive(self.service_pid()), 20), "the service started under the watcher")
        first = self.service_pid()
        self.assertNotEqual(first, self.watcher.pid)
        os.kill(first, signal.SIGKILL)
        self.assertTrue(wait_for(lambda: self.service_pid() not in (None, first) and alive(self.service_pid()), 20), "the watcher started a new service")
        second = self.service_pid()
        self.assertIsNone(self.watcher.poll())
        os.kill(second, signal.SIGTERM)
        self.assertEqual(self.watcher.wait(20), 0, "a stop on purpose ends the watch")
        self.assertFalse(alive(second))
        self.assertFalse(os.path.exists(self.pth.watch_pidfile))

    def test_a_second_watch_start_changes_nothing_when_the_service_runs(self):
        self.assertTrue(wait_for(lambda: self.service_pid() and alive(self.service_pid()), 20))
        first = self.service_pid()
        r = subprocess.run([sys.executable, "-B", "-m", "swarmbox_sysop", "serve", "--log", "--watch"], env=self.env, timeout=20, stdin=subprocess.DEVNULL,
                           capture_output=True)
        self.assertEqual(r.returncode, 0)
        time.sleep(1.5)
        self.assertEqual(self.service_pid(), first)
        self.assertTrue(alive(first))


if __name__ == "__main__":
    unittest.main()
