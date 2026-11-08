"""Slice 3.6: the end-to-end run against a local registry (opt-in: SWARMBOX_E2E=1; skipped otherwise).

It runs tests/e2e_registry.py in a child process (a registry:2 container on 127.0.0.1, the documented install line, the first
call, joining, two terminals at once, stop, update, update with the registry down, reset offline, update --to, in bash, zsh and
fish) and asserts that every STEP line is PASS or SKIP, that the cleanup step passed, and that nothing named swarmbox-test-3-
remains afterwards. Slow (10 to 20 minutes): run it in the background. REDUCED: the boxes have no nested Podman (the
development box is a container itself); nothing runs on macOS or arm64.
Run: SWARMBOX_E2E=1 python3 tests/test_registry_e2e.py
"""
import os
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))


@unittest.skipUnless(os.environ.get("SWARMBOX_E2E") == "1", "opt-in: set SWARMBOX_E2E=1 (slow, starts a registry container)")
class RegistryE2E(unittest.TestCase):
    def test_install_update_reset_against_a_local_registry(self):
        p = subprocess.run([sys.executable, "-u", os.path.join(HERE, "e2e_registry.py")], capture_output=True, text=True,
                           timeout=3600)
        print(p.stdout)
        steps = [ln.split(" ", 3) for ln in p.stdout.splitlines() if ln.startswith("STEP ")]
        self.assertTrue(steps, p.stdout + p.stderr)
        for _, sid, status, *_rest in steps:
            self.assertIn(status, ("PASS", "SKIP"), "%s: %s" % (sid, p.stdout[-3000:]))
        self.assertTrue(any(s[1] == "cleanup" and s[2] == "PASS" for s in steps), "no passing cleanup step")
        self.assertEqual(p.returncode, 0, p.stdout[-2000:] + p.stderr)
        left = subprocess.run(["podman", "ps", "-a", "--format", "{{.Names}}"], capture_output=True, text=True).stdout.split()
        self.assertEqual([n for n in left if n.startswith("swarmbox-test-3-")], [])


if __name__ == "__main__":
    unittest.main()
