"""Slice 2.5: the stub swarmbox-tool (container/scripts/swarmbox-tool.sh) and the empty tool-ports file (design 6.2, 6.3,
10.2). The real tool program arrives in Phase 4a; until then `validate` is a placeholder that passes, `link` and `prepare`
do nothing (so `serve` does not warn at every start), and anything else exits 70 and says where it comes from.

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
        env = {"PATH": "/usr/bin:/bin", "HOME": self.base}
        if host:
            env["SWARMBOX_TEST_HOST_DIR"] = self.host
        return subprocess.run(["bash", TOOL, *args], env=env, capture_output=True, text=True, timeout=20)

    def test_validate_is_a_placeholder_that_passes_and_says_so(self):
        r = self.run_tool("validate")
        self.assertEqual(r.returncode, 0, r.stderr)
        out = (r.stdout + r.stderr).lower()
        self.assertIn("placeholder", out)
        self.assertIn("phase 4a", out)

    def test_link_system_writes_an_empty_tool_ports_file_and_is_idempotent(self):
        for _ in range(2):
            r = self.run_tool("link", "--system")
            self.assertEqual(r.returncode, 0, r.stderr)
            p = os.path.join(self.host, "tool-ports")
            self.assertTrue(os.path.isfile(p))
            self.assertEqual(os.path.getsize(p), 0)

    def test_link_system_empties_a_file_that_has_content(self):
        os.makedirs(self.host)
        with open(os.path.join(self.host, "tool-ports"), "w") as f:
            f.write("clasp\t43323\n")
        self.assertEqual(self.run_tool("link", "--system").returncode, 0)
        self.assertEqual(os.path.getsize(os.path.join(self.host, "tool-ports")), 0)

    def test_link_system_touches_nothing_else(self):
        os.makedirs(self.host)
        open(os.path.join(self.host, "keep.txt"), "w").write("k")
        self.run_tool("link", "--system")
        self.assertEqual(sorted(os.listdir(self.host)), ["keep.txt", "tool-ports"])

    def test_link_user_and_prepare_succeed_and_write_nothing(self):
        for args in (("link", "--user"), ("prepare",)):
            r = self.run_tool(*args)
            self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(os.path.exists(self.host))
        self.assertEqual(os.listdir(self.base), [])

    def test_link_needs_a_known_flag(self):
        for args in (("link",), ("link", "--bogus")):
            self.assertEqual(self.run_tool(*args).returncode, 64)

    def test_everything_else_exits_70_and_points_to_phase_4a(self):
        for args in (("install", "claude"), ("run", "claude"), ("update",), ("list",), ("bogus",)):
            with self.subTest(args=args):
                r = self.run_tool(*args)
                self.assertEqual(r.returncode, 70)
                self.assertIn("Phase 4a", r.stderr)
                self.assertEqual(r.stdout, "")

    def test_no_arguments_is_a_usage_error(self):
        r = self.run_tool()
        self.assertEqual(r.returncode, 64)
        self.assertIn("usage", r.stderr.lower())

    def test_through_the_entrypoint(self):
        bindir = os.path.join(self.base, "bin")
        os.mkdir(bindir)
        os.symlink(TOOL, os.path.join(bindir, "swarmbox-tool"))
        r = subprocess.run(["bash", ENTRYPOINT, "tool", "validate"], env={"PATH": bindir + ":/usr/bin:/bin", "HOME": self.base},
                           capture_output=True, text=True, timeout=20)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_dockerfile_installs_the_stub_and_writes_tool_ports_at_build(self):
        with open(os.path.join(ROOT, "Dockerfile")) as f:
            d = f.read()
        self.assertIn("COPY container/scripts/swarmbox-tool.sh /usr/local/bin/swarmbox-tool", d)
        self.assertIn("/usr/local/bin/swarmbox-tool", d.split("COPY container/entrypoint.sh")[1])  # chmod 755
        self.assertIn("swarmbox-tool link --system", d)
        self.assertIn("COPY cloudflare-setup.py /usr/local/share/swarmbox/host/cloudflare-setup.py", d)

    def test_bash_syntax_and_shellcheck(self):
        self.assertEqual(subprocess.run(["bash", "-n", TOOL], capture_output=True).returncode, 0)
        if shutil.which("shellcheck"):
            r = subprocess.run(["shellcheck", "-s", "bash", TOOL], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
