"""Self-check of the Phase 0 spike harness (tests/spikes/spikes_common.py), with a fake podman and a fake tmux.

Proves: names without the swarmbox-test- prefix are refused; cleanup removes by exact name only; tmux is only
run as `tmux -L swarmbox-test-<unique> -f /dev/null` with TMUX unset; ports are 127.0.0.1 and 20000-40000, never
7681, 8889 or 43323; and no spike script contains a forbidden port or a forbidden command.
Run: python3 tests/test_spikes_common.py
"""
import glob
import os
import re
import stat
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "spikes"))
from helpers import ROOT  # noqa: E402
import spikes_common as sc  # noqa: E402

FAKE = """#!/bin/sh
printf '%s\\n' "$0 $*" >> "$FAKE_LOG"
printf 'TMUX=%s\\n' "${TMUX-unset}" >> "$FAKE_LOG.env"
exit 0
"""


class HarnessTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="swarmbox-test-selfcheck-")
        self.log = os.path.join(self.dir, "calls.log")
        open(self.log, "w").close()
        for n in ("podman", "tmux"):
            p = os.path.join(self.dir, n)
            with open(p, "w") as f:
                f.write(FAKE)
            os.chmod(p, os.stat(p).st_mode | stat.S_IXUSR)
        self.old_path = os.environ["PATH"]
        os.environ["PATH"] = self.dir + os.pathsep + self.old_path
        os.environ["FAKE_LOG"] = self.log
        os.environ.pop("TMUX", None)

    def tearDown(self):
        os.environ["PATH"] = self.old_path
        import shutil
        shutil.rmtree(self.dir, ignore_errors=True)

    def calls(self):
        with open(self.log) as f:
            return [l.split(" ", 1)[1].strip() for l in f if l.strip()]

    def test_refuses_names_without_prefix(self):
        for bad in ("main", "swarmbox", "swarmbox-test-", "", "x-swarmbox-test-a", "swarmbox-test- a"):
            with self.assertRaises(sc.Refused):
                sc.check_name(bad)
        self.assertEqual(sc.check_name("swarmbox-test-b3-abc"), "swarmbox-test-b3-abc")

    def test_podman_refuses_unprefixed_name_and_dangerous_verbs(self):
        s = sc.Spike("t1")
        with self.assertRaises(sc.Refused):
            s.run("main", "img")
        for args in (["system", "prune"], ["system", "reset"], ["volume", "prune"], ["image", "prune"],
                     ["rm", "-a"], ["stop", "--all"], ["rmi", "-a"], ["kill", "-a"],
                     ["rm", "-f", "somebox"], ["stop", "-t", "3", "somebox"],
                     ["run", "--name", "mybox", "img"], ["exec", "mybox", "true"],
                     ["run", "--network", "host", "--name", "swarmbox-test-x", "img"],
                     ["run", "-P", "--name", "swarmbox-test-x", "img"]):
            with self.assertRaises(sc.Refused, msg=str(args)):
                sc.check_podman_args(args)
        self.assertEqual(self.calls(), [])  # nothing reached podman
        sc.check_podman_args(["kill", "--signal", "INT", "swarmbox-test-x"])
        sc.check_podman_args(["stop", "-t", "10", "swarmbox-test-x"])
        sc.check_podman_args(["logs", "--tail", "5", "swarmbox-test-x"])
        s.cleanup()

    def test_cleanup_removes_by_exact_name_only(self):
        s = sc.Spike("t2")
        a, b = s.name("a"), s.name("b")
        s.run(a, "img")
        s.run(b, "img", "-p", "127.0.0.1:%d:7681" % s.free_port())
        s.cleanup()
        rm = [c for c in self.calls() if " rm " in " " + c + " "]
        self.assertEqual(len(rm), 2)
        self.assertTrue(rm[0].endswith(" " + b) and rm[1].endswith(" " + a), rm)  # reverse order, exact names
        for c in rm:
            self.assertNotIn(" -a", c)
            self.assertNotIn("--all", c)
            self.assertNotIn("*", c)
        self.assertFalse([c for c in self.calls() if "prune" in c or " reset" in c])
        s.cleanup()  # idempotent
        self.assertEqual(len([c for c in self.calls() if " rm " in " " + c + " "]), 2)

    def test_tmux_only_with_own_socket_and_no_TMUX(self):
        s = sc.Spike("t3")
        os.environ["TMUX"] = "/tmp/tmux-1000/default,1,0"
        try:
            with self.assertRaises(sc.Refused):
                sc.check_tmux_args(["-L", "swarmbox-test-x", "-f", "/dev/null", "ls"], dict(os.environ))
            s.tmux_host("new-session", "-d")  # the wrapper unsets TMUX itself
        finally:
            os.environ.pop("TMUX")
        with open(self.log + ".env") as f:
            self.assertEqual(set(f.read().split()), {"TMUX=unset"})
        for bad in (["ls"], ["-L", "main", "-f", "/dev/null", "ls"], ["-L", "swarmbox-test-x", "ls"],
                    ["kill-server"]):
            with self.assertRaises(sc.Refused):
                sc.check_tmux_args(bad, {})
        s.cleanup()
        tm = self.calls()
        self.assertTrue(tm)
        for c in tm:
            self.assertRegex(c, r"^-L swarmbox-test-t3-[0-9a-f]{6} -f /dev/null ")
        # the only kill-server is on the spike's own socket
        ks = [c for c in tm if "kill-server" in c]
        self.assertEqual(len(ks), 1)
        self.assertRegex(ks[0], r"^-L swarmbox-test-t3-[0-9a-f]{6} -f /dev/null kill-server")

    def test_ports(self):
        for bad in (7681, 8889, 43323, 80, 19999, 40001):
            with self.assertRaises(sc.Refused):
                sc.check_host_port(bad)
        for bad in ("7681:7681", "0.0.0.0:25000:7681", "25000:7681", "127.0.0.1:7681:7681", ":25000:7681",
                    "127.0.0.1:43323:1"):
            with self.assertRaises(sc.Refused, msg=bad):
                sc.check_port_spec(bad)
        self.assertEqual(sc.check_port_spec("127.0.0.1:25000:7681"), "127.0.0.1:25000:7681")
        s = sc.Spike("t4")
        for _ in range(50):
            p = s.free_port()
            self.assertTrue(20000 <= p <= 40000 and p not in sc.FORBIDDEN_PORTS)
        s.cleanup()

    def test_evidence_line(self):
        e = sc.evidence("test run", "img:1")
        self.assertRegex(e, r"^\[verified: test run; \d{4}-\d\d-\d\d; Podman .*, .*; img:1\]$")
        self.assertIn("reduced: because", sc.evidence("x", "i", reduced="because"))

    def test_spike_scripts_respect_the_rules(self):
        """Static scan: no spike names a forbidden port, binds 0.0.0.0, or runs a forbidden command."""
        files = glob.glob(os.path.join(ROOT, "tests", "spikes", "*.py"))
        self.assertTrue(files)
        for f in files:
            with open(f) as fh:
                src = fh.read()
            body = src
            if f.endswith("spikes_common.py"):
                continue  # the harness names the forbidden values in order to refuse them
            self.assertNotRegex(body, r"\b(7681|8889|43323)\b", f)
            self.assertNotIn("0.0.0.0", body, f)
            for line in body.splitlines():  # kill-server is only ever aimed at an explicit private socket
                if "kill-server" in line:
                    self.assertTrue("$S " in line or "-L " in line, "%s: %s" % (f, line))
            for bad in ("pkill", "killall", "system prune", "system reset", "volume prune",
                        "image prune", "rm -a", "git push", "--network host", "--network=host"):
                self.assertNotIn(bad, body, "%s: %s" % (f, bad))
            for m in re.finditer(r"""["']tmux["']""", body):
                self.fail("%s calls tmux directly; use spike.tmux_host or run tmux inside a container" % f)
            self.assertNotRegex(body, r"subprocess\.\w+\(\s*\[\s*[\"']podman", f)  # go through Spike.podman


if __name__ == "__main__":
    unittest.main()
