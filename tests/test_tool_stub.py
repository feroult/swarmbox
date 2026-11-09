"""Slice 2.5: the stub swarmbox-tool (container/scripts/swarmbox-tool.sh) and the empty tool-ports file (design 6.2, 6.3,
10.2). The real tool program arrives in Phase 4a in slices; `validate` is real since 4a.1, and `link` and `prepare`
do nothing (so `serve` does not warn at every start), and an unknown command exits 70 (use, remove, new and doctor became real in 4b.5).

Test-only variable (decision log [2.5]): SWARMBOX_TEST_HOST_DIR replaces /usr/local/share/swarmbox/host.
Run with: python3 tests/test_tool_stub.py
"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import ROOT  # noqa: E402

TOOL = os.path.join(ROOT, "container", "scripts", "swarmbox-tool.sh")
ENTRYPOINT = os.path.join(ROOT, "container", "entrypoint.sh")


class ToolStub(unittest.TestCase):
    def setUp(self):
        self.base = tempfile.mkdtemp(prefix="tool-stub-")
        self.addCleanup(shutil.rmtree, self.base, ignore_errors=True)
        self.host = os.path.join(self.base, "host")

    def run_tool(self, *args, host=True):
        env = {"PATH": "/usr/bin:/bin", "HOME": self.base, "SWARMBOX_TEST_IMAGE_TOOLS": os.path.join(self.base, "none"),
               "SWARMBOX_TEST_IMAGE_SHIMS": os.path.join(self.base, "out", "shims")}
        if host:
            env["SWARMBOX_TEST_HOST_DIR"] = self.host
        return subprocess.run(["bash", TOOL, *args], env=env, capture_output=True, text=True, timeout=20)

    def test_validate_with_no_manifests_passes_and_says_how_many_it_checked(self):
        # the real validate arrived in slice 4a.1 (tests/test_tool_manifest.py); with no manifest folders it checks nothing
        r = self.run_tool("validate")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("0 manifest(s) checked", r.stdout)

    def test_unknown_commands_print_the_usage_and_exit_64(self):
        r = self.run_tool("bogus")
        self.assertEqual(r.returncode, 64)
        self.assertIn("usage: swarmbox tool", r.stderr)
        self.assertIn("unknown command", r.stderr)
        self.assertEqual(r.stdout, "")

    def test_no_arguments_is_a_usage_error(self):
        r = self.run_tool()
        self.assertEqual(r.returncode, 64)
        self.assertIn("usage", r.stderr.lower())

    def test_bash_syntax_and_shellcheck(self):
        self.assertEqual(subprocess.run(["bash", "-n", TOOL], capture_output=True).returncode, 0)
        if shutil.which("shellcheck"):
            r = subprocess.run(["shellcheck", "-s", "bash", TOOL], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
