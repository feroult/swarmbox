"""Slice 3.5: `swarmbox-init` and the shell templates (design 3.1, 3.7.5, 3.8, D20).

`swarmbox-init` is a POSIX sh program (container/scripts/swarmbox-init.sh, installed as /usr/local/bin/swarmbox-init and run by
`swarmbox-entrypoint init`). It prints on standard output, and only there, a comment line naming the version, then the marker
block of the chosen shell from container/host/templates/<shell>. Nothing is written to the machine. Tests-only switch:
SWARMBOX_TEST_HOST_DIR (the folder that holds VERSION and templates/, as /usr/local/share/swarmbox/host does in the image).
HOME and the XDG folders are mktemp folders. Run: python3 tests/test_init_output.py
"""
import os
import pty
import re
import select
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import ROOT  # noqa: E402

INIT = os.path.join(ROOT, "container", "scripts", "swarmbox-init.sh")
HOST_DIR = os.path.join(ROOT, "container", "host")
with open(os.path.join(HOST_DIR, "VERSION")) as _f:
    VERSION = _f.read().strip()
DEFAULT_IMAGE = "ghcr.io/<org>/swarmbox:%s" % VERSION
UNKNOWN = "swarmbox init: unknown shell '%s'. Use --shell bash, zsh or fish."


def snapshot(path):
    out = {}
    for d, _dirs, files in os.walk(path):
        for f in files:
            p = os.path.join(d, f)
            out[p] = (os.stat(p).st_mtime_ns, os.path.getsize(p))
    return out


class Base(unittest.TestCase):
    def setUp(self):
        self.base = tempfile.mkdtemp(prefix="swarmbox-test-init-")
        self.addCleanup(shutil.rmtree, self.base, True)
        self.home = os.path.join(self.base, "home")
        os.mkdir(self.home)

    def env(self, **extra):
        env = {"PATH": os.environ["PATH"], "HOME": self.home, "XDG_CONFIG_HOME": os.path.join(self.home, "c"),
               "XDG_DATA_HOME": os.path.join(self.home, "d"), "XDG_STATE_HOME": os.path.join(self.home, "s"),
               "SWARMBOX_TEST_HOST_DIR": HOST_DIR}
        env.update(extra)
        return env

    def init(self, *args, env=None, host_dir=None):
        e = self.env() if env is None else env
        if host_dir:
            e["SWARMBOX_TEST_HOST_DIR"] = host_dir
        return subprocess.run(["sh", INIT, *args], env=e, capture_output=True, text=True, stdin=subprocess.DEVNULL)


class Output(Base):
    def test_each_shell_prints_one_marker_pair_with_the_version(self):
        for shell in ("bash", "zsh", "fish"):
            with self.subTest(shell=shell):
                r = self.init("--shell", shell)
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertEqual(r.stderr, "")
                lines = r.stdout.split("\n")
                self.assertEqual(lines.count("# >>> swarmbox %s >>>" % VERSION), 1)
                self.assertEqual(lines.count("# <<< swarmbox %s <<<" % VERSION), 1)
                self.assertEqual(len(re.findall(r"^# >>> swarmbox ", r.stdout, re.M)), 1)
                self.assertEqual(len(re.findall(r"^# <<< swarmbox ", r.stdout, re.M)), 1)
                self.assertLess(r.stdout.index(">>>"), r.stdout.index("<<<"))
                self.assertTrue(r.stdout.startswith("# "), "the first line is a comment")
                self.assertIn(VERSION, lines[0])
                self.assertNotIn(">>>", lines[0])
                self.assertTrue(r.stdout.endswith("<<< swarmbox %s <<<\n" % VERSION))

    def test_no_placeholder_is_left(self):
        for shell in ("bash", "zsh", "fish"):
            with self.subTest(shell=shell):
                r = self.init("--shell", shell, "--with", "claude", "--workspace", "/w", "--image", "img:1")
                self.assertNotRegex(r.stdout, r"@[A-Z_]+@")

    def test_the_default_image_is_the_placeholder_org_and_the_version(self):
        r = self.init("--shell", "bash")
        self.assertIn(DEFAULT_IMAGE, r.stdout)

    def test_seeds_appear_only_for_the_flags_given(self):
        r = self.init("--shell", "bash")
        self.assertNotIn("claude", r.stdout)
        self.assertNotIn("/w", r.stdout)
        r = self.init("--shell", "bash", "--with", "claude,gcloud")
        self.assertIn("'claude,gcloud'", r.stdout)
        self.assertNotIn("--workspace /w", r.stdout)
        r = self.init("--shell", "zsh", "--workspace", "/srv/box")
        self.assertIn("'/srv/box'", r.stdout)
        self.assertNotIn("claude", r.stdout)
        r = self.init("--shell", "fish", "--image", "localhost:5000/sb:2.0.0")
        self.assertIn("'localhost:5000/sb:2.0.0'", r.stdout)
        self.assertNotIn(DEFAULT_IMAGE, r.stdout)

    def test_equals_form_of_the_flags(self):
        a = self.init("--shell", "bash", "--with", "x", "--workspace", "/w", "--image", "i:1")
        b = self.init("--shell=bash", "--with=x", "--workspace=/w", "--image=i:1")
        self.assertEqual(a.stdout, b.stdout)

    def test_awkward_seed_values_are_quoted_for_each_shell(self):
        ws = "/tmp/it's a $HOME `id` \\ \"x\" &"
        for shell in ("bash", "zsh", "fish"):
            with self.subTest(shell=shell):
                r = self.init("--shell", shell, "--workspace", ws)
                self.assertEqual(r.returncode, 0, r.stderr)
                if shell == "fish":
                    self.assertIn("it\\'s a $HOME `id` \\\\ \"x\" &", r.stdout)
                else:
                    self.assertIn("it'\\''s a $HOME `id` \\ \"x\" &", r.stdout)

    def test_a_newline_in_a_seed_is_refused(self):
        r = self.init("--shell", "bash", "--with", "a\nb")
        self.assertEqual(r.returncode, 2)
        self.assertEqual(r.stdout, "")
        self.assertIn("newline", r.stderr)

    def test_stdout_is_identical_across_two_runs(self):
        for shell in ("bash", "zsh", "fish"):
            a = self.init("--shell", shell, "--with", "claude", "--workspace", "/w")
            b = self.init("--shell", shell, "--with", "claude", "--workspace", "/w")
            self.assertEqual(a.stdout, b.stdout)
            self.assertNotEqual(a.stdout, "")

    def test_nothing_is_written_to_the_machine(self):
        before = snapshot(self.home)
        os.makedirs(os.path.join(self.home, ".bashrc.d"))
        before = snapshot(self.home)
        for shell in ("bash", "zsh", "fish"):
            self.init("--shell", shell, "--with", "claude")
        self.assertEqual(snapshot(self.home), before)
        self.assertEqual(sorted(os.listdir(self.home)), [".bashrc.d"])

    def test_the_version_comes_from_the_version_file(self):
        d = os.path.join(self.base, "hd")
        os.makedirs(d)
        os.symlink(os.path.join(HOST_DIR, "templates"), os.path.join(d, "templates"))
        with open(os.path.join(d, "VERSION"), "w") as f:
            f.write("2.0.10\n")
        r = self.init("--shell", "bash", host_dir=d)
        self.assertIn("# >>> swarmbox 2.0.10 >>>", r.stdout)
        self.assertIn("ghcr.io/<org>/swarmbox:2.0.10", r.stdout)

    def test_a_missing_or_malformed_version_file_exits_3(self):
        d = os.path.join(self.base, "hd")
        os.makedirs(d)
        os.symlink(os.path.join(HOST_DIR, "templates"), os.path.join(d, "templates"))
        r = self.init("--shell", "bash", host_dir=d)
        self.assertEqual(r.returncode, 3)
        self.assertEqual(r.stdout, "")
        with open(os.path.join(d, "VERSION"), "w") as f:
            f.write("not a version\n")
        r = self.init("--shell", "bash", host_dir=d)
        self.assertEqual(r.returncode, 3)
        self.assertEqual(r.stdout, "")

    def test_a_missing_template_exits_3_with_no_output(self):
        d = os.path.join(self.base, "hd")
        os.makedirs(os.path.join(d, "templates"))
        shutil.copy(os.path.join(HOST_DIR, "VERSION"), d)
        r = self.init("--shell", "bash", host_dir=d)
        self.assertEqual(r.returncode, 3)
        self.assertEqual(r.stdout, "")


class Shell(Base):
    def test_unknown_shell_exits_2_with_the_exact_text(self):
        for bad in ("tcsh", "powershell", "", "BASH"):
            with self.subTest(bad=bad):
                r = self.init("--shell", bad)
                self.assertEqual(r.returncode, 2)
                self.assertEqual(r.stdout, "")
                self.assertEqual(r.stderr, UNKNOWN % bad + "\n")

    def test_the_shell_comes_from_the_shell_variable(self):
        bash = self.init("--shell", "bash").stdout
        zsh = self.init("--shell", "zsh").stdout
        fish = self.init("--shell", "fish").stdout
        self.assertEqual(len({bash, zsh, fish}), 3)
        for var, want in (("/bin/zsh", zsh), ("/usr/bin/fish", fish), ("/bin/bash", bash), ("zsh", zsh)):
            with self.subTest(shell=var):
                r = self.init(env=self.env(SHELL=var))
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertEqual(r.stdout, want)

    def test_any_other_shell_variable_gives_bash_silently(self):
        bash = self.init("--shell", "bash").stdout
        for var in ("/bin/dash", "/bin/sh", "/usr/bin/tcsh", "", "/weird path/ksh93", "/usr/local/bin/nu"):
            with self.subTest(shell=var):
                r = self.init(env=self.env(SHELL=var))
                self.assertEqual(r.returncode, 0)
                self.assertEqual(r.stderr, "")
                self.assertEqual(r.stdout, bash)

    def test_no_shell_variable_gives_bash(self):
        r = self.init()
        self.assertEqual(r.stdout, self.init("--shell", "bash").stdout)

    def test_explicit_shell_overrides_the_variable(self):
        r = self.init("--shell", "fish", env=self.env(SHELL="/bin/zsh"))
        self.assertEqual(r.stdout, self.init("--shell", "fish").stdout)
        r = self.init("--shell", "bash", env=self.env(SHELL="/usr/bin/fish"))
        self.assertEqual(r.stdout, self.init("--shell", "bash").stdout)

    def test_an_unknown_variable_value_does_not_matter_with_an_explicit_shell(self):
        r = self.init("--shell", "zsh", env=self.env(SHELL="/bin/dash"))
        self.assertEqual(r.returncode, 0)

    def test_usage_errors_exit_2(self):
        for args in (["--bogus"], ["--with"], ["--shell"], ["extra"], ["--workspace"]):
            with self.subTest(args=args):
                r = self.init(*args)
                self.assertEqual(r.returncode, 2)
                self.assertEqual(r.stdout, "")
                self.assertIn("swarmbox init:", r.stderr)

    def test_help_prints_usage_on_stdout(self):
        r = self.init("--help")
        self.assertEqual(r.returncode, 0)
        self.assertIn("usage: swarmbox init", r.stdout)
        self.assertNotIn(">>>", r.stdout)


class Terminal(Base):
    def run_pty(self, *args):
        master, slave = pty.openpty()
        p = subprocess.Popen(["sh", INIT, *args], env=self.env(), stdin=subprocess.DEVNULL, stdout=slave,
                             stderr=subprocess.PIPE)
        os.close(slave)
        out = b""
        while True:
            r, _, _ = select.select([master], [], [], 5)
            if not r:
                break
            try:
                chunk = os.read(master, 65536)
            except OSError:
                break
            if not chunk:
                break
            out += chunk
        err = p.stderr.read()
        p.stderr.close()
        p.wait()
        os.close(master)
        return p.returncode, out.decode(), err.decode()

    def test_a_hint_on_stderr_only_when_stdout_is_a_terminal(self):
        rc, out, err = self.run_pty("--shell", "bash")
        self.assertEqual(rc, 0)
        self.assertIn(">>> swarmbox", out)
        self.assertIn("append", err)
        self.assertIn("shell startup file", err)
        r = self.init("--shell", "bash")
        self.assertEqual(r.stderr, "")

    def test_no_hint_when_stdout_is_a_pipe_or_a_file(self):
        out = os.path.join(self.base, "out")
        with open(out, "w") as f:
            r = subprocess.run(["sh", INIT, "--shell", "fish"], env=self.env(), stdout=f, stderr=subprocess.PIPE,
                               stdin=subprocess.DEVNULL, text=True)
        self.assertEqual(r.stderr, "")
        with open(out) as f:
            self.assertIn("<<< swarmbox", f.read())


class Syntax(unittest.TestCase):
    def printed(self, shell):
        r = subprocess.run(["sh", INIT, "--shell", shell, "--with", "claude", "--workspace", "it's here", "--image", "i:1"],
                           env={"PATH": os.environ["PATH"], "SWARMBOX_TEST_HOST_DIR": HOST_DIR}, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def check(self, cmd, shell, suffix):
        text = self.printed(shell)
        with tempfile.NamedTemporaryFile("w", suffix=suffix, delete=False) as f:
            f.write(text)
        try:
            r = subprocess.run(cmd + [f.name], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
        finally:
            os.unlink(f.name)

    def test_the_bash_output_passes_bash_n_and_posix(self):
        self.check(["bash", "-n"], "bash", ".sh")
        self.check(["bash", "--posix", "-n"], "bash", ".sh")

    @unittest.skipUnless(shutil.which("zsh"), "zsh is not installed")
    def test_the_zsh_output_passes_zsh_n(self):
        self.check(["zsh", "-n"], "zsh", ".zsh")

    @unittest.skipUnless(shutil.which("fish"), "fish is not installed")
    def test_the_fish_output_passes_fish_no_execute(self):
        self.check(["fish", "--no-execute"], "fish", ".fish")

    def test_the_template_files_exist_for_each_shell(self):
        for shell in ("bash", "zsh", "fish"):
            self.assertTrue(os.path.isfile(os.path.join(HOST_DIR, "templates", shell)), shell)

    def test_the_program_itself_is_posix_sh(self):
        self.assertTrue(os.path.isfile(INIT))
        with open(INIT) as f:
            first = f.readline()
        self.assertEqual(first, "#!/bin/sh\n")
        for sh in ("dash", "bash --posix"):
            r = subprocess.run(sh.split() + ["-n", INIT], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)


if __name__ == "__main__":
    unittest.main()
