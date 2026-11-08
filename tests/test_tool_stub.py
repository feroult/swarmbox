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

    def test_link_user_with_no_manifests_and_prepare_succeed_and_write_no_tool_ports(self):
        # link is real since slice 4a.2 (tests/test_tool_link.py): with no manifests it leaves an empty user level in the
        # workspace dirs (here under HOME) and never writes tool-ports; prepare is still a no-op (4b owns prepare.sh)
        for args in (("link", "--user"), ("prepare",)):
            r = self.run_tool(*args)
            self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(os.path.exists(self.host))
        self.assertEqual(os.listdir(os.path.join(self.base, ".local", "share", "swarmbox", "shims")), [])

    def test_link_needs_a_known_flag(self):
        for args in (("link",), ("link", "--bogus")):
            self.assertEqual(self.run_tool(*args).returncode, 64)

    def test_unknown_commands_exit_70(self):
        # use, remove, new and doctor are real since slice 4b.5 (test_tool_use_remove.py, test_tool_new.py, test_tool_doctor.py)
        r = self.run_tool("bogus")
        self.assertEqual(r.returncode, 70)
        self.assertIn("unknown command", r.stderr)
        self.assertEqual(r.stdout, "")

    def test_the_former_stubs_answer_real_usage_errors_not_70(self):
        for args in (("use", "claude"), ("remove",), ("new",), ("doctor", "--bogus")):
            with self.subTest(args=args):
                self.assertEqual(self.run_tool(*args).returncode, 64)
        self.assertEqual(self.run_tool("doctor").returncode, 0)

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
