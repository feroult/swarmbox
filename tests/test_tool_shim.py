"""Slice 4a.4: the dispatcher `swarmbox-shim` and the whole shim call lifecycle (design 6.1, 6.2, 6.5; decisions D2, D18).

Chain under test: symlink -> swarmbox-shim -> swarmbox-tool run -> fake installer -> fake program, all in a temp tree
(HOME, the two manifest levels, both shim folders and both indexes are temp folders; the real /usr/local is never read).
The shim is run by every shell that exists here (its shebang /bin/sh, dash, bash, busybox sh), by its absolute symlink path and
through a PATH lookup (evidence B12: $0 is the path as invoked). Run with: python3 tests/test_tool_shim.py
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

    def test_managed_tool_through_the_shim_and_current_bin_on_path(self):
        self.setup_demo()
        shim = os.path.join(self.ishims, "demo")
        r = self.call(shim, "x")
        self.assertEqual((r.returncode, r.stdout), (0, "[x]\n"), r.stderr)
        self.assertIn("Installing demo (first use)...", r.stderr)
        self.assertEqual(self.call(shim, "y").stdout, "[y]\n")
        self.assertEqual(self.installs(), 1)
        cur = os.path.join(self.tools, "demo", "current", "bin")
        self.assertEqual(shutil.which("demo", path=cur + ":" + self.env()["PATH"]), os.path.join(cur, "demo"))

    def test_exit_status_of_the_real_program_is_returned(self):
        self.setup_demo()
        shim = os.path.join(self.ishims, "selfy")
        self.assertEqual(self.call(shim, DEMO_EXIT="7").returncode, 7)
        self.assertEqual(self.call(shim, DEMO_EXIT="0").returncode, 0)

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

    def test_stdin_and_directory_are_kept(self):
        self.setup_demo()
        with open(os.path.join(self.home, ".local", "share", "swarmbox", "x"), "w"):
            pass
        cat = os.path.join(self.base, "wd")
        os.makedirs(cat)
        self.assertEqual(self.call(os.path.join(self.ishims, "selfy")).returncode, 0)
        prog = os.path.join(self.home, ".local", "bin", "selfy")
        with open(prog, "w") as f:
            f.write('#!/bin/sh\npwd; cat\n')
        r = subprocess.run([os.path.join(self.ishims, "selfy")], env=self.env(), input="from stdin", capture_output=True,
                           text=True, cwd=cat)
        self.assertEqual(r.stdout, cat + "\nfrom stdin")


class Index(ShimBase):
    def test_unknown_command_is_127_with_a_clear_message(self):
        self.setup_demo()
        self.link("image", self.ishims, "ghost")
        r = self.call(os.path.join(self.ishims, "ghost"))
        self.assertEqual(r.returncode, 127)
        self.assertIn("ghost: command not found", r.stderr)
        self.assertEqual(r.stdout, "")
        self.assertEqual(self.installs(), 0)

    def test_no_index_at_all_is_127(self):
        self.link("image", self.ishims, "ghost")
        r = self.call(os.path.join(self.ishims, "ghost"))
        self.assertEqual(r.returncode, 127)

    def test_user_index_overrides_the_image_index(self):
        mgr = self.fake_mgr()
        self.index(self.ishims, "tool-x img-tool")
        self.index(self.ushims, "other y", "tool-x user-tool")
        self.link("user", self.ushims, "tool-x")
        r = self.call(os.path.join(self.ushims, "tool-x"), "q", env=self.env(SWARMBOX_TEST_TOOL=mgr))
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(self.args) as f:
            self.assertEqual(f.read().split("\n"), ["run", "user-tool", "tool-x", "--", "q", ""])

    def test_image_index_used_when_the_user_index_lacks_the_command(self):
        mgr = self.fake_mgr()
        self.index(self.ishims, "tool-x img-tool")
        self.index(self.ushims, "other y")
        self.link("image", self.ishims, "tool-x")
        self.assertEqual(self.call(os.path.join(self.ishims, "tool-x"), env=self.env(SWARMBOX_TEST_TOOL=mgr)).returncode, 0)
        with open(self.args) as f:
            self.assertEqual(f.read().split("\n")[:3], ["run", "img-tool", "tool-x"])

    def test_last_index_line_without_a_newline_and_prefix_names(self):
        mgr = self.fake_mgr()
        with open(os.path.join(os.path.dirname(self.ishims), "index"), "w") as f:
            f.write("tool-xy wrong\ntool-x right")
        self.link("image", self.ishims, "tool-x")
        self.assertEqual(self.call(os.path.join(self.ishims, "tool-x"), env=self.env(SWARMBOX_TEST_TOOL=mgr)).returncode, 0)
        with open(self.args) as f:
            self.assertEqual(f.read().split("\n")[1], "right")

    def test_hot_path_never_sources_a_manifest(self):
        """After link the manifest may be broken: the shim only reads the index (6.5, exit criterion 3)."""
        mgr = self.fake_mgr()
        d = make_tool(self.image, "demo", PROVIDES='"demo"')
        self.index(self.ishims, "demo demo")
        self.link("image", self.ishims, "demo")
        marker = os.path.join(self.base, "sourced")
        with open(os.path.join(d, "tool.conf"), "w") as f:
            f.write("touch '%s'\nexit 3\n)(\n" % marker)
        r = self.call(os.path.join(self.ishims, "demo"), env=self.env(SWARMBOX_TEST_TOOL=mgr))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(os.path.exists(marker))

    def test_manager_arguments_survive_odd_characters(self):
        mgr = self.fake_mgr()
        self.index(self.ishims, "demo demo")
        self.link("image", self.ishims, "demo")
        odd = ["a b", "", "*", "$HOME", "it's", "-n", "--", "line\nbreak"]
        r = self.call(os.path.join(self.ishims, "demo"), *odd, env=self.env(SWARMBOX_TEST_TOOL=mgr))
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(self.args) as f:
            self.assertEqual(f.read(), "\n".join(["run", "demo", "demo", "--", *odd]) + "\n")

    def test_missing_manager_is_70(self):
        self.index(self.ishims, "demo demo")
        self.link("image", self.ishims, "demo")
        r = self.call(os.path.join(self.ishims, "demo"), env=self.env(SWARMBOX_TEST_TOOL=os.path.join(self.base, "nope")))
        self.assertEqual(r.returncode, 70)
        self.assertIn("nope", r.stderr)

    def test_the_dispatcher_called_by_its_own_name_explains_itself(self):
        r = self.call(SHIM)
        self.assertEqual(r.returncode, 64)
        self.assertIn("dispatcher", r.stderr)

    def test_user_index_found_through_dirs_sh_without_the_test_override(self):
        mgr = self.fake_mgr()
        self.index(self.ushims, "tool-x user-tool")
        self.link("user", self.ushims, "tool-x")
        env = self.env(SWARMBOX_TEST_TOOL=mgr)
        del env["SWARMBOX_TEST_USER_SHIMS"]
        r = self.call(os.path.join(self.ushims, "tool-x"), env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(self.args) as f:
            self.assertEqual(f.read().split("\n")[1], "user-tool")


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

    def test_depth_is_passed_on_and_garbage_depth_is_ignored(self):
        mgr = self.fake_mgr()
        self.index(self.ishims, "demo demo")
        self.link("image", self.ishims, "demo")
        for given, want in (("", "1"), ("3", "4"), ("junk", "1"), ("15", "16")):
            with self.subTest(given=given):
                self.assertEqual(self.call(os.path.join(self.ishims, "demo"),
                                           env=self.env(SWARMBOX_TEST_TOOL=mgr, SWARMBOX_SHIM_DEPTH=given)).returncode, 0)
                with open(self.args + ".depth") as f:
                    self.assertEqual(f.read().strip(), want)


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

    def test_dockerfile_installs_the_shim_where_links_point(self):
        with open(os.path.join(ROOT, "Dockerfile")) as f:
            text = f.read()
        self.assertIn("COPY container/scripts/swarmbox-shim.sh /usr/local/bin/swarmbox-shim", text)
        chmod_line = [l for l in text.split("\n") if "swarmbox-tool /usr/local" in l]
        self.assertTrue(chmod_line and "/usr/local/bin/swarmbox-shim" in chmod_line[-1])


if __name__ == "__main__":
    unittest.main()
