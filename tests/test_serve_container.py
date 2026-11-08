"""Slice 2.2: `serve` in a real throwaway container from the 2.1 image (tag: image build, reduced).

[reduced: development box, no nested Podman in the box] The development box is itself a container, so a third level of
nesting is not available: the container starts with SWARMBOX_TEST_NO_NESTED=1 (no /dev/net/tun, no nested service), so
serve reaches ready with warnings. This checks PID 1 signals, `podman stop` timing, the exit codes, ttyd under the
supervisor, tmux session main and the tmpfs (B17 recheck). It does NOT check step 8 for real.

Skipped unless SWARMBOX_IMAGE_BUILD=1 and podman works. SWARMBOX_IMAGE_TAG=<swarmbox-test-...> reuses an image (and does
not remove it); otherwise the image is built with dev/dev-build.sh and removed at the end.
Containers are swarmbox-test-serve-<random>, removed by exact name; the workspace is a mktemp directory.
Run: SWARMBOX_IMAGE_BUILD=1 python3 tests/test_serve_container.py
"""
import os
import random
import shutil
import string
import subprocess
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import ROOT  # noqa: E402

ENABLED = os.environ.get("SWARMBOX_IMAGE_BUILD") == "1" and shutil.which("podman")
TAG = None
OWN = False


def rnd():
    return "".join(random.choice(string.ascii_lowercase + string.digits) for _ in range(6))


def podman(*args, timeout=120):
    return subprocess.run(["podman"] + list(args), capture_output=True, text=True, timeout=timeout)


def setUpModule():
    global TAG, OWN
    if not ENABLED:
        return
    TAG = os.environ.get("SWARMBOX_IMAGE_TAG")
    if TAG:
        assert TAG.startswith("swarmbox-test-"), TAG
        return
    TAG = "swarmbox-test-img-" + rnd()
    OWN = True
    r = subprocess.run(["sh", os.path.join(ROOT, "dev", "dev-build.sh"), "--tag", TAG], capture_output=True, text=True)
    if r.returncode != 0:
        sys.stderr.write(r.stdout[-3000:] + r.stderr[-3000:])
        raise AssertionError("image build failed")


def tearDownModule():
    if OWN and TAG and TAG.startswith("swarmbox-test-"):
        podman("rmi", TAG)


def wait_for(fn, seconds=60, step=0.3):
    end = time.time() + seconds
    while time.time() < end:
        v = fn()
        if v:
            return v
        time.sleep(step)
    return None


@unittest.skipUnless(ENABLED, "container tests need SWARMBOX_IMAGE_BUILD=1 and podman")
class ServeInContainer(unittest.TestCase):
    def setUp(self):
        self.ws = tempfile.mkdtemp(prefix="serve-ws-")
        self.names = []
        self.addCleanup(shutil.rmtree, self.ws, ignore_errors=True)
        self.addCleanup(self._remove)

    def _remove(self):
        for n in self.names:
            assert n.startswith("swarmbox-test-serve-")
            podman("rm", "-f", "-t", "0", n)

    def run_box(self, *extra_env, init=False):
        name = "swarmbox-test-serve-" + rnd()
        self.names.append(name)
        args = ["run", "-d", "--name", name, "--userns=keep-id:uid=1000,gid=1000", "-v", self.ws + ":/home/agent",
                "--tmpfs", "/tmp/swarmbox", "-e", "SWARMBOX_TEST_NO_NESTED=1"]
        for e in extra_env:
            args += ["-e", e]
        if init:
            args.append("--init")
        r = podman(*args, TAG)
        self.assertEqual(r.returncode, 0, r.stderr)
        return name

    def sh(self, name, cmd):
        return podman("exec", name, "sh", "-c", cmd).stdout.strip()

    def ready(self, name):
        return wait_for(lambda: self.sh(name, "cat /tmp/swarmbox/ready 2>/dev/null"))

    def state(self, name):
        return podman("inspect", "--format", "{{.State.Status}} {{.State.ExitCode}}", name).stdout.strip()

    def test_lifecycle_ready_stop_start_and_tmpfs(self):
        name = self.run_box()
        marker = self.ready(name)
        self.assertIsNotNone(marker, podman("logs", name).stdout + podman("logs", name).stderr)
        self.assertTrue(marker.startswith("warnings="), marker)  # no nested Podman: tun and service are warnings
        health = self.sh(name, "cat /home/agent/.local/state/swarmbox/health")
        self.assertIn("nested Podman", health)
        # PID 1 is serve itself
        self.assertIn("swarmbox-entrypoint", self.sh(name, "tr '\\0' ' ' < /proc/1/cmdline"))
        self.assertIn("serve", self.sh(name, "tr '\\0' ' ' < /proc/1/cmdline"))
        # tmux session main with one window, ttyd answering inside the box
        self.assertIn("main:", self.sh(name, "tmux ls"))
        self.assertTrue(wait_for(lambda: self.sh(name, "curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:7681/") == "200", 20))
        # a file in the tmpfs and one in the workspace
        self.sh(name, "echo x > /tmp/swarmbox/stale; echo y > /home/agent/keep.txt")
        t0 = time.time()
        r = podman("stop", "-t", "10", name, timeout=60)
        took = time.time() - t0
        self.assertEqual(r.returncode, 0, r.stderr)
        sys.stderr.write("\n[serve container] podman stop -t 10: %.2f s, marker %s\n" % (took, marker))
        self.assertLess(took, 2.0, "podman stop -t 10 took %.2f s" % took)
        self.assertEqual(self.state(name), "exited 143")
        # start again: tmpfs empty (B17), the marker is the new run's, the workspace file survived
        self.assertEqual(podman("start", name).returncode, 0)
        self.assertIsNotNone(self.ready(name))
        self.assertEqual(self.sh(name, "test -e /tmp/swarmbox/stale && echo STALE || echo gone"), "gone")
        self.assertEqual(self.sh(name, "cat /home/agent/keep.txt"), "y")
        log = self.sh(name, "cat /home/agent/.local/state/swarmbox/serve.log")
        self.assertIn("received SIGTERM", log)

    def test_sigint_gives_130_and_web_off_has_no_ttyd(self):
        name = self.run_box("SWARMBOX_WEB=0")
        self.assertIsNotNone(self.ready(name))
        self.assertEqual(self.sh(name, "pgrep -x ttyd >/dev/null && echo yes || echo no"), "no")
        t0 = time.time()
        self.assertEqual(podman("kill", "--signal", "INT", name).returncode, 0)
        self.assertTrue(wait_for(lambda: self.state(name).startswith("exited"), 10, 0.1))
        self.assertLess(time.time() - t0, 2.0)
        self.assertEqual(self.state(name), "exited 130")

    def test_under_init_sigterm_is_143(self):
        name = self.run_box(init=True)
        self.assertIsNotNone(self.ready(name))
        t0 = time.time()
        self.assertEqual(podman("stop", "-t", "10", name, timeout=60).returncode, 0)
        self.assertLess(time.time() - t0, 2.0)
        self.assertEqual(self.state(name), "exited 143")

    def test_ttyd_killed_comes_back_and_restart_signal_works(self):
        name = self.run_box()
        self.assertIsNotNone(self.ready(name))
        self.assertTrue(wait_for(lambda: self.sh(name, "pgrep -x ttyd | head -1")))
        old = self.sh(name, "pgrep -x ttyd | head -1")
        self.sh(name, "kill %s" % old)  # the ttyd this box started; the supervisor restarts it after 1 s
        new = wait_for(lambda: (lambda p: p if p and p != old else None)(self.sh(name, "pgrep -x ttyd | head -1")), 15)
        self.assertTrue(new, "ttyd was not restarted")
        sup = self.sh(name, "cat /tmp/swarmbox/web-supervisor.pid")
        self.sh(name, "kill -USR1 %s" % sup)  # what swarmbox-web restart does
        newer = wait_for(lambda: (lambda p: p if p and p != new else None)(self.sh(name, "pgrep -x ttyd | head -1")), 15)
        self.assertTrue(newer, "ttyd was not restarted by the signal")
        self.assertEqual(self.state(name).split()[0], "running")


if __name__ == "__main__":
    unittest.main()
