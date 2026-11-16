"""The stub swarmbox-addon (container/scripts/swarmbox-addon.sh) and the empty addon-ports file.
The stub's `link` and `prepare` do nothing (so `serve` does not warn at every start), and an unknown command exits 70 (use, remove, new and doctor became real in 4b.5).

Test-only variable: SWARMBOX_TEST_HOST_DIR replaces /usr/local/share/swarmbox/host.
Run with: python3 tests/fast/test_addon_stub.py
"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "support"))
from helpers import ROOT  # noqa: E402

ADDON = os.path.join(ROOT, "container", "scripts", "swarmbox-addon.sh")
ENTRYPOINT = os.path.join(ROOT, "container", "entrypoint.sh")


class AddonStub(unittest.TestCase):
    def setUp(self):
        self.base = tempfile.mkdtemp(prefix="addon-stub-")
        self.addCleanup(shutil.rmtree, self.base, ignore_errors=True)
        self.host = os.path.join(self.base, "host")

    def run_addon(self, *args, host=True):
        env = {"PATH": "/usr/bin:/bin", "HOME": self.base, "SWARMBOX_TEST_IMAGE_ADDONS": os.path.join(self.base, "none"),
               "SWARMBOX_TEST_IMAGE_SHIMS": os.path.join(self.base, "out", "shims")}
        if host:
            env["SWARMBOX_TEST_HOST_DIR"] = self.host
        return subprocess.run(["bash", ADDON, *args], env=env, capture_output=True, text=True, timeout=20)

    def test_validate_with_no_manifests_passes_and_says_how_many_it_checked(self):
        # the real validate is tested in tests/fast/test_addon_manifest.py; with no manifest folders it checks nothing
        r = self.run_addon("validate")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("0 manifest(s) checked", r.stdout)

    def test_unknown_commands_print_the_usage_and_exit_64(self):
        r = self.run_addon("bogus")
        self.assertEqual(r.returncode, 64)
        self.assertIn("usage: swarmbox addon", r.stderr)
        self.assertIn("unknown command", r.stderr)
        self.assertEqual(r.stdout, "")

    def test_no_arguments_is_a_usage_error(self):
        r = self.run_addon()
        self.assertEqual(r.returncode, 64)
        self.assertIn("usage", r.stderr.lower())

    def test_bash_syntax_and_shellcheck(self):
        self.assertEqual(subprocess.run(["bash", "-n", ADDON], capture_output=True).returncode, 0)
        if shutil.which("shellcheck"):
            r = subprocess.run(["shellcheck", "-s", "bash", ADDON], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
