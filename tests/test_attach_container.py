"""Slice 2.3: `swarmbox-entrypoint attach` in a real throwaway container from the 2.1 image.

This part needs only nesting level 2 (the container the development box runs), so it is a full result, not reduced, with one
exception: the nested Podman service is switched off by the test-only SWARMBOX_TEST_NO_NESTED=1 (as in test_serve_container.py),
so the box is ready with warnings. `serve` creates tmux session main with the idle window; then:
  - `attach false` fails and `attach true` succeeds, with and without a terminal;
  - two interactive `attach` calls give two windows of ONE session and the idle window is gone (B36, D1);
  - output without a terminal has no CR.
The terminal is a pty made by the test (`podman exec -it`).

Skipped unless SWARMBOX_IMAGE_BUILD=1 and podman works. SWARMBOX_IMAGE_TAG=<swarmbox-test-...> reuses an image (and does not
remove it); otherwise the image is built with dev/dev-build.sh and removed at the end.
Containers are swarmbox-test-attach-<random>, removed by exact name; the workspace is a mktemp directory.
Run: SWARMBOX_IMAGE_BUILD=1 python3 tests/test_attach_container.py
"""
import os
import random
import shutil
import signal
import string
import subprocess
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import ROOT  # noqa: E402
from test_attach_command import PtyProc, wait_until  # noqa: E402

ENABLED = os.environ.get("SWARMBOX_IMAGE_BUILD") == "1" and shutil.which("podman")
TAG = None
OWN = False


def rnd():
    return "".join(random.choice(string.ascii_lowercase + string.digits) for _ in range(6))


def podman(*args, timeout=120, **kw):
    return subprocess.run(["podman"] + list(args), capture_output=True, timeout=timeout, **kw)


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


@unittest.skipUnless(ENABLED, "container tests need SWARMBOX_IMAGE_BUILD=1 and podman")
class AttachInContainer(unittest.TestCase):
    def setUp(self):
        self.ws = tempfile.mkdtemp(prefix="attach-ws-")
        self.name = "swarmbox-test-attach-" + rnd()
        self.ptys = []
        self.addCleanup(shutil.rmtree, self.ws, ignore_errors=True)
        self.addCleanup(self._remove)
        r = podman("run", "-d", "--name", self.name, "--userns=keep-id:uid=1000,gid=1000", "-v", self.ws + ":/home/agent",
                   "--tmpfs", "/tmp/swarmbox", "-e", "SWARMBOX_TEST_NO_NESTED=1", "-e", "SWARMBOX_WEB=0", TAG)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(wait_until(lambda: self.sh("test -f /tmp/swarmbox/ready && echo y") == "y", 60, 0.3),
                        podman("logs", self.name).stdout)

    def _remove(self):
        for p in self.ptys:
            p.close()
        assert self.name.startswith("swarmbox-test-attach-")
        podman("rm", "-f", "-t", "0", self.name)

    def sh(self, cmd):
        return podman("exec", self.name, "sh", "-c", cmd).stdout.decode().strip()

    def term(self, *args):
        p = PtyProc(["podman", "exec", "-it", self.name, "swarmbox-entrypoint", "attach"] + list(args),
                    dict(os.environ, TERM="xterm-256color"))
        self.ptys.append(p)
        return p

    def windows(self):
        return [l for l in self.sh("tmux list-windows -t =main -F '#{window_name}'").splitlines() if l]

    def test_attach_false_fails_and_true_succeeds_without_a_terminal(self):
        self.assertEqual(podman("exec", self.name, "swarmbox-entrypoint", "attach", "false").returncode, 1)
        self.assertEqual(podman("exec", self.name, "swarmbox-entrypoint", "attach", "true").returncode, 0)
        r = podman("exec", self.name, "swarmbox-entrypoint", "attach", "sh", "-c", "exit 7")
        self.assertEqual(r.returncode, 7)

    def test_attach_false_and_true_through_a_terminal_window(self):
        p = self.term("false")
        self.assertEqual(p.wait(60), 1, p.out)
        p = self.term("true")
        self.assertEqual(p.wait(60), 0, p.out)
        p = self.term("sh", "-c", "exit 130")
        self.assertEqual(p.wait(60), 130, p.out)
        # the idle window is left alone by commands, and no grouped session is left
        self.assertEqual(self.windows(), ["idle"])
        self.assertEqual(self.sh("tmux list-sessions -F '#{session_name}'"), "main")

    def test_no_terminal_output_has_no_cr(self):
        r = podman("exec", "-i", self.name, "swarmbox-entrypoint", "attach", "printf", "a\\nb\\n", stdin=subprocess.DEVNULL)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout, b"a\nb\n")
        self.assertEqual(r.stderr, b"")

    def test_two_attach_calls_share_one_session_as_two_windows_and_the_idle_window_is_gone(self):
        self.assertEqual(self.windows(), ["idle"])
        a = self.term()
        self.assertTrue(wait_until(lambda: len(self.sh("tmux list-sessions -F x").split()) == 2, 30), a.out)
        self.assertEqual(len(self.windows()), 1)
        self.assertNotIn("idle", self.windows())
        b = self.term()
        self.assertTrue(wait_until(lambda: len(self.sh("tmux list-sessions -F x").split()) == 3, 30), b.out)
        self.assertEqual(len(self.windows()), 2)
        self.assertNotIn("idle", self.windows())
        groups = set(self.sh("tmux list-sessions -F '#{session_group}'").split())
        self.assertEqual(groups, {"main"})  # one group: one shared session
        # leave the tabs the normal way: the tmux detach key (prefix C-a, d; /etc/tmux.conf). Killing the host-side
        # `podman exec` instead leaves the in-box client running (podman keeps the exec session; see decision [2.3]).
        for tab in (a, b):
            tab.write(b"\x01d")
            self.assertEqual(tab.wait(30), 0, tab.out)
        self.assertTrue(wait_until(lambda: len(self.sh("tmux list-sessions -F x").split()) == 1, 30))
        self.assertEqual(len(self.windows()), 2)  # the windows outlive the tabs

    def test_not_ready_gives_6(self):
        self.sh("rm -f /tmp/swarmbox/ready")
        t0 = time.time()
        r = podman("exec", "-e", "SWARMBOX_TEST_READY_TIMEOUT=2", self.name, "swarmbox-entrypoint", "attach", "true")
        self.assertEqual(r.returncode, 6, r.stderr)
        self.assertIn(b"not ready", r.stderr)
        self.assertLess(time.time() - t0, 30)


if __name__ == "__main__":
    unittest.main()
