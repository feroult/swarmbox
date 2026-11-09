"""The dispatcher `swarmbox-shim` and the whole shim call lifecycle.

Chain under test: symlink -> swarmbox-shim -> swarmbox-tool run -> fake installer -> fake program, all in a temp tree
(HOME, the two manifest levels, both shim folders and both indexes are temp folders; the real /usr/local is never read).
The shim is run by every shell that exists here (its shebang /bin/sh, dash, bash, busybox sh), by its absolute symlink path and
through a PATH lookup ($0 is the path as invoked). Run with: python3 tests/test_tool_shim.py
"""
import os
import shutil
import subprocess
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import ROOT  # noqa: E402
from test_tool_install import Base, SELF, SELF_CONF, TOOL  # noqa: E402
from test_tool_manifest import make_tool  # noqa: E402

SHIM = os.path.join(ROOT, "container", "scripts", "swarmbox-shim.sh")

INTERPRETERS = [("shebang", None)]
for _name, _argv in (("dash", ["dash"]), ("bash", ["bash"]), ("busybox", ["busybox", "sh"])):
    if shutil.which(_argv[0]):
        INTERPRETERS.append((_name, _argv))

# A "tool manager" that only records how it was called (for tests that must not run the real swarmbox-tool).
FAKE_MGR = """#!/bin/sh
printf '%s\\n' "$@" > "$FAKE_ARGS"
printf '%s\\n' "${SWARMBOX_SHIM_DEPTH:-}" > "$FAKE_ARGS.depth"
exit "${MGR_EXIT:-0}"
"""


class ShimBase(Base):
    def setUp(self):
        super().setUp()
        j = lambda *p: os.path.join(self.base, *p)  # noqa: E731
        self.ishims, self.ushims = j("img", "shims"), j("home", ".local", "share", "swarmbox", "shims")
        os.makedirs(self.ishims)
        os.makedirs(self.ushims)
        self.args = j("args.txt")

    def env(self, **extra):
        e = super().env(**extra)
        for k, v in (("SWARMBOX_TEST_IMAGE_SHIMS", self.ishims), ("SWARMBOX_TEST_USER_SHIMS", self.ushims),
                     ("SWARMBOX_TEST_TOOL", TOOL), ("FAKE_ARGS", self.args)):
            e.setdefault(k, v)
        e["PATH"] = ":".join([os.path.join(self.home, ".local", "bin"), self.ushims, self.ishims, "/usr/bin", "/bin"])
        return e

    def link(self, level, shims, *commands):
        """Shims of `commands` in `shims` pointing to the real dispatcher in the repository."""
        for c in commands:
            p = os.path.join(shims, c)
            if os.path.lexists(p):
                os.remove(p)
            os.symlink(SHIM, p)

    def index(self, shims, *lines):
        with open(os.path.join(os.path.dirname(shims), "index"), "w") as f:
            f.write("".join(l + "\n" for l in lines))

    def call(self, shim_path, *args, interp=None, env=None, **extra):
        argv = (interp or []) + [shim_path, *args]
        return subprocess.run(argv, env=env or self.env(**extra), capture_output=True, text=True, timeout=60, cwd=self.base)

    def fake_mgr(self):
        p = os.path.join(self.base, "fake-mgr")
        with open(p, "w") as f:
            f.write(FAKE_MGR)
        os.chmod(p, 0o755)
        return p

    def setup_demo(self, **over):
        """Image-level managed tool 'demo' and self tool 'selfy', both indexed and linked."""
        self.managed(**over)
        self.selfy()
        self.index(self.ishims, "demo demo", "selfy selfy")
        self.link("image", self.ishims, "demo", "selfy")


class Lifecycle(ShimBase):
    def test_first_call_installs_then_runs_the_real_program_for_every_interpreter(self):
        for iname, interp in INTERPRETERS:
            for how in ("symlink", "path"):
                with self.subTest(interp=iname, how=how):
                    shutil.rmtree(self.home, ignore_errors=True)
                    os.makedirs(self.home)
                    for f in (self.count, self.rec):
                        if os.path.exists(f):
                            os.remove(f)
                    os.makedirs(self.ushims, exist_ok=True)
                    self.setup_demo()
                    target = os.path.join(self.ishims, "selfy")
                    if how == "path":
                        target = shutil.which("selfy", path=self.env()["PATH"])
                        self.assertEqual(os.path.realpath(target), SHIM)
                    r = self.call(target, "a b", "", "--x=1", interp=interp)
                    self.assertEqual(r.returncode, 0, r.stderr)
                    self.assertEqual(r.stdout, "[a b]\n[]\n[--x=1]\n")
                    self.assertIn("Installing selfy (first use)...", r.stderr)
                    self.assertNotIn("Installing", r.stdout)
                    self.assertEqual(self.installs(), 1)

    def test_second_call_runs_no_installer_and_path_finds_the_real_binary(self):
        self.setup_demo()
        shim = os.path.join(self.ishims, "selfy")
        self.assertEqual(self.call(shim, "one").returncode, 0)
        self.assertEqual(self.installs(), 1)
        self.assertEqual(shutil.which("selfy", path=self.env()["PATH"]), os.path.join(self.home, ".local", "bin", "selfy"))
        for _ in range(3):
            r = self.call(shim, "two")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(r.stdout, "[two]\n")
            self.assertNotIn("Installing", r.stderr)
        self.assertEqual(self.installs(), 1, "zero installer runs after the first success")

    def test_install_failure_message_nonzero_no_run_and_retry(self):
        self.setup_demo()
        shim = os.path.join(self.ishims, "selfy")
        r = self.call(shim, "x", FAKE_FAIL="1")
        self.assertEqual(r.returncode, 69)
        self.assertEqual(r.stdout, "")
        self.assertIn("Installing selfy (first use)...", r.stderr)
        self.assertIn("could not resolve host", r.stderr)
        self.assertIn("next call retries", r.stderr)
        self.assertFalse(os.path.lexists(os.path.join(self.home, ".local", "bin", "selfy")))
        r = self.call(shim, "x")
        self.assertEqual((r.returncode, r.stdout), (0, "[x]\n"), r.stderr)
        self.assertEqual(self.installs(), 2)

class Index(ShimBase):
    def test_unknown_command_is_127_with_a_clear_message(self):
        self.setup_demo()
        self.link("image", self.ishims, "ghost")
        r = self.call(os.path.join(self.ishims, "ghost"))
        self.assertEqual(r.returncode, 127)
        self.assertIn("ghost: command not found", r.stderr)
        self.assertEqual(r.stdout, "")
        self.assertEqual(self.installs(), 0)

    def test_user_index_overrides_the_image_index(self):
        mgr = self.fake_mgr()
        self.index(self.ishims, "tool-x img-tool")
        self.index(self.ushims, "other y", "tool-x user-tool")
        self.link("user", self.ushims, "tool-x")
        r = self.call(os.path.join(self.ushims, "tool-x"), "q", env=self.env(SWARMBOX_TEST_TOOL=mgr))
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(self.args) as f:
            self.assertEqual(f.read().split("\n"), ["run", "user-tool", "tool-x", "--", "q", ""])

class LoopGuard(ShimBase):
    def test_real_command_that_is_the_shim_is_refused_not_looped(self):
        self.setup_demo()
        shim = os.path.join(self.ishims, "selfy")
        r = self.call(shim, FAKE_LINK_TO_SHIM=shim)
        self.assertEqual(r.returncode, 69)
        self.assertIn("swarmbox-shim", r.stderr)
        self.assertIn("forever", r.stderr)
        self.assertEqual(self.installs(), 1)

    def test_depth_guard_stops_a_chain_that_loops_anyway(self):
        mgr = self.fake_mgr()
        self.index(self.ishims, "demo demo")
        self.link("image", self.ishims, "demo")
        r = self.call(os.path.join(self.ishims, "demo"), env=self.env(SWARMBOX_TEST_TOOL=mgr, SWARMBOX_SHIM_DEPTH="16"))
        self.assertEqual(r.returncode, 70)
        self.assertIn("called itself", r.stderr)
        self.assertFalse(os.path.exists(self.args))

class Lint(unittest.TestCase):
    def test_shellcheck_clean(self):
        sc = shutil.which("shellcheck")
        if not sc:
            self.skipTest("shellcheck is not installed")
        r = subprocess.run([sc, SHIM, TOOL], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout)

    def test_shim_is_posix_sh_with_an_sh_shebang(self):
        with open(SHIM) as f:
            self.assertEqual(f.readline().strip(), "#!/bin/sh")
        self.assertTrue(os.access(SHIM, os.X_OK))

if __name__ == "__main__":
    unittest.main()
