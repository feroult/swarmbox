"""Slice 2.5: the subcommands of swarmbox-entrypoint (design 10.2): serve, attach, init, pubkey, tool, host-helper and
"any other command, run as given". Everything runs against container/entrypoint.sh with FAKE programs first on PATH.

Test-only variable (decision log [2.5]): SWARMBOX_TEST_HOST_DIR replaces /usr/local/share/swarmbox/host.
Run with: python3 tests/test_entrypoint.py
"""
import io
import json
import os
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import ROOT  # noqa: E402

ENTRYPOINT = os.path.join(ROOT, "container", "entrypoint.sh")
ATTACH = os.path.join(ROOT, "container", "scripts", "swarmbox-attach.sh")

# a fake program that records its name and arguments and exits with $FAKE_RC
FAKE = '''#!/usr/bin/env python3
import json, os, sys
with open(os.path.join(os.environ["FAKE_DIR"], "calls.jsonl"), "a") as f:
    f.write(json.dumps([os.path.basename(sys.argv[0])] + sys.argv[1:]) + "\\n")
sys.exit(int(os.environ.get("FAKE_RC", "0")))
'''
AWKWARD = ["plain", "with space", "", "--flag=value", "*", "a'b", 'a"b', "$HOME", "-x", "--", "tab\there"]


def write_exec(path, text):
    with open(path, "w") as f:
        f.write(text)
    os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR)


class Base(unittest.TestCase):
    def setUp(self):
        self.base = tempfile.mkdtemp(prefix="ep-test-")
        self.addCleanup(shutil.rmtree, self.base, ignore_errors=True)
        self.fake = os.path.join(self.base, "fake")
        os.mkdir(self.fake)
        for name in ("swarmbox-attach", "swarmbox-init", "swarmbox-pubkey", "swarmbox-tool"):
            write_exec(os.path.join(self.fake, name), FAKE)

    def env(self, path=None, **extra):
        env = {"PATH": (path or self.fake) + ":/usr/bin:/bin", "HOME": self.base, "FAKE_DIR": self.base}
        env.update(extra)
        return env

    def run_ep(self, *args, **kw):
        env = kw.pop("env", None) or self.env()
        return subprocess.run(["bash", ENTRYPOINT, *args], env=env, capture_output=True, stdin=subprocess.DEVNULL, timeout=30, **kw)

    def calls(self):
        p = os.path.join(self.base, "calls.jsonl")
        if not os.path.exists(p):
            return []
        with open(p) as f:
            return [json.loads(line) for line in f if line.strip()]


class Dispatch(Base):
    def test_each_subcommand_runs_its_program_with_every_argument_preserved(self):
        for sub, prog in (("attach", "swarmbox-attach"), ("init", "swarmbox-init"), ("pubkey", "swarmbox-pubkey"),
                          ("tool", "swarmbox-tool")):
            with self.subTest(sub=sub):
                os.path.exists(os.path.join(self.base, "calls.jsonl")) and os.unlink(os.path.join(self.base, "calls.jsonl"))
                r = self.run_ep(sub, *AWKWARD)
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertEqual(self.calls(), [[prog] + AWKWARD])

    def test_exit_status_of_the_program_is_the_exit_status_of_the_entrypoint(self):
        for sub in ("attach", "init", "pubkey", "tool"):
            for rc in (1, 3, 42, 130):
                with self.subTest(sub=sub, rc=rc):
                    r = self.run_ep(sub, "x", env=self.env(FAKE_RC=str(rc)))
                    self.assertEqual(r.returncode, rc)

    def test_a_subcommand_runs_no_other_program(self):
        self.run_ep("pubkey", "--ensure")
        self.assertEqual([c[0] for c in self.calls()], ["swarmbox-pubkey"])

    def test_the_entrypoint_execs_the_program_so_no_extra_process_stays(self):
        # the program sees the entrypoint's own PID as its parent's parent: it is exec'd, not forked
        write_exec(os.path.join(self.fake, "swarmbox-tool"), '#!/bin/sh\necho $PPID > "$FAKE_DIR/ppid"\n')
        p = subprocess.Popen(["bash", ENTRYPOINT, "tool", "validate"], env=self.env(), stdout=subprocess.PIPE)
        p.wait(timeout=20)
        # PPID of the program is the test's python (the entrypoint was replaced by the program)
        self.assertEqual(open(os.path.join(self.base, "ppid")).read().strip(), str(os.getpid()))

    def test_a_missing_program_fails_with_127_and_names_it(self):
        empty = os.path.join(self.base, "empty")
        os.mkdir(empty)
        for sub, prog in (("attach", "swarmbox-attach"), ("init", "swarmbox-init"), ("pubkey", "swarmbox-pubkey"),
                          ("tool", "swarmbox-tool")):
            with self.subTest(sub=sub):
                r = self.run_ep(sub, env=self.env(empty))
                self.assertEqual(r.returncode, 127)
                self.assertIn(prog.encode(), r.stderr)

    def test_no_command_is_64(self):
        r = self.run_ep()
        self.assertEqual(r.returncode, 64)
        self.assertTrue(r.stderr)

    def test_the_old_placeholder_is_gone(self):
        with open(ENTRYPOINT) as f:
            text = f.read()
        self.assertNotIn("is not implemented in this build yet", text)
        self.assertNotIn("exit 70", text.split("# ----")[-1])


class AnyOtherCommand(Base):
    def test_unknown_commands_run_unchanged_and_the_exit_code_passes_through(self):
        for argv, rc in ((["true"], 0), (["false"], 1), (["sh", "-c", "exit 7"], 7), (["sh", "-c", "kill -TERM $$"], -15)):
            with self.subTest(argv=argv):
                self.assertEqual(self.run_ep(*argv).returncode, rc)

    def test_arguments_and_stdin_and_environment_are_passed_as_given(self):
        r = subprocess.run(["bash", ENTRYPOINT, "sh", "-c", 'printf "%s|" "$@"; cat; echo "$MARK"', "x"] + AWKWARD,
                           env=self.env(MARK="m1"), input=b"in-data", capture_output=True, timeout=20)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.decode(), "|".join(AWKWARD) + "|in-datam1\n")

    def test_a_command_that_does_not_exist_is_127(self):
        r = self.run_ep("swarmbox-no-such-program-xyz")
        self.assertEqual(r.returncode, 127)

    def test_a_command_named_like_a_subcommand_but_not_equal_is_run_as_given(self):
        write_exec(os.path.join(self.fake, "serve2"), FAKE)
        r = self.run_ep("serve2", "a")
        self.assertEqual(r.returncode, 0)
        self.assertEqual(self.calls(), [["serve2", "a"]])


class AttachAgainstFakeTmux(Base):
    """`attach false` fails and `attach true` succeeds with the real swarmbox-attach and a fake tmux on PATH."""

    def test_attach_false_fails_and_attach_true_succeeds(self):
        bindir = os.path.join(self.base, "bin")
        os.mkdir(bindir)
        os.symlink(ATTACH, os.path.join(bindir, "swarmbox-attach"))
        write_exec(os.path.join(bindir, "tmux"), '#!/bin/sh\necho "$@" >> "$FAKE_DIR/tmux.log"\nexit 0\n')
        run = os.path.join(self.base, "run")
        os.mkdir(run)
        open(os.path.join(run, "ready"), "w").write("ok\n")
        env = self.env(bindir, SWARMBOX_TEST_LIB=os.path.join(ROOT, "container", "scripts"), SWARMBOX_TEST_RUN_DIR=run,
                       SWARMBOX_TEST_READY_TIMEOUT="3")
        for cmd, want in (("true", 0), ("false", 1)):
            r = self.run_ep("attach", cmd, env=env)
            self.assertEqual(r.returncode, want, r.stderr)


class HostHelper(Base):
    def make_dir(self):
        d = os.path.join(self.base, "host")
        os.makedirs(os.path.join(d, "templates"))
        write_exec(os.path.join(d, "swarmbox-host"), "#!/bin/sh\necho 2.0.0\n")
        open(os.path.join(d, "cloudflare-setup.py"), "w").write("# cf\n")
        open(os.path.join(d, "tool-ports"), "w").close()
        open(os.path.join(d, "templates", "bash"), "w").write("f() { :; }\n")
        return d

    def test_it_writes_the_helper_folder_as_a_tar_archive_on_stdout_and_nothing_else(self):
        d = self.make_dir()
        r = self.run_ep("host-helper", env=self.env(SWARMBOX_TEST_HOST_DIR=d))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stderr, b"")
        tf = tarfile.open(fileobj=io.BytesIO(r.stdout))
        names = sorted(n[2:] if n.startswith("./") else n for n in tf.getnames())
        self.assertEqual(names, [".", "cloudflare-setup.py", "swarmbox-host", "templates", "templates/bash", "tool-ports"])
        self.assertEqual(tf.getmember("./swarmbox-host").mode & 0o100, 0o100)   # the executable bit survives (3.7.1)
        self.assertEqual(tf.extractfile("./tool-ports").read(), b"")
        for m in tf.getmembers():
            self.assertEqual((m.uid, m.gid), (0, 0))

    def test_the_archive_of_the_repository_folder_has_the_files_of_3_7_1_and_the_templates_are_what_init_prints(self):
        # the image's folder as the Dockerfile builds it: container/host/ (swarmbox-host, VERSION, templates/), the cloudflare
        # script and an empty tool-ports
        d = os.path.join(self.base, "image-host")
        shutil.copytree(os.path.join(ROOT, "container", "host"), d)
        shutil.copy(os.path.join(ROOT, "cloudflare-setup.py"), d)
        open(os.path.join(d, "tool-ports"), "w").close()
        r = self.run_ep("host-helper", env=self.env(SWARMBOX_TEST_HOST_DIR=d))
        self.assertEqual(r.returncode, 0, r.stderr)
        tf = tarfile.open(fileobj=io.BytesIO(r.stdout))
        names = sorted(n[2:] if n.startswith("./") else n for n in tf.getnames())
        for want in ("swarmbox-host", "cloudflare-setup.py", "VERSION", "tool-ports", "templates", "templates/bash",
                     "templates/zsh", "templates/fish"):
            self.assertIn(want, names)
        self.assertEqual(tf.getmember("./swarmbox-host").mode & 0o111, 0o111)
        out = os.path.join(self.base, "unpacked")
        os.mkdir(out)
        t = subprocess.run(["tar", "-x", "-C", out, "-f", "-"], input=r.stdout, capture_output=True)
        self.assertEqual(t.returncode, 0, t.stderr)
        version = open(os.path.join(ROOT, "container", "host", "VERSION")).read().strip()
        v = subprocess.run([os.path.join(out, "swarmbox-host"), "version"], capture_output=True, text=True,
                           env={"PATH": "/usr/bin:/bin", "HOME": self.base})
        self.assertEqual((v.returncode, v.stdout.strip()), (0, version))
        # what init prints from the unpacked archive equals what it prints from the repository's templates
        init = os.path.join(ROOT, "container", "scripts", "swarmbox-init.sh")
        for shell in ("bash", "zsh", "fish"):
            a = subprocess.run(["sh", init, "--shell", shell], capture_output=True, text=True,
                               env={"PATH": "/usr/bin:/bin", "SWARMBOX_TEST_HOST_DIR": out})
            b = subprocess.run(["sh", init, "--shell", shell], capture_output=True, text=True,
                               env={"PATH": "/usr/bin:/bin", "SWARMBOX_TEST_HOST_DIR": os.path.join(ROOT, "container", "host")})
            self.assertEqual(a.returncode, 0, a.stderr)
            self.assertEqual(a.stdout, b.stdout)
            with open(os.path.join(out, "templates", shell), "rb") as f1, \
                    open(os.path.join(ROOT, "container", "host", "templates", shell), "rb") as f2:
                self.assertEqual(f1.read(), f2.read())

    def test_the_entrypoint_init_runs_the_real_program_with_the_shell_variable(self):
        init = os.path.join(ROOT, "container", "scripts", "swarmbox-init.sh")
        bindir = os.path.join(self.base, "realbin")
        os.mkdir(bindir)
        os.symlink(init, os.path.join(bindir, "swarmbox-init"))
        env = self.env(path=bindir, SWARMBOX_TEST_HOST_DIR=os.path.join(ROOT, "container", "host"), SHELL="/usr/bin/fish")
        r = self.run_ep("init", "--with", "claude", env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(b"function swarmbox", r.stdout)
        self.assertEqual(r.stderr, b"")

    def test_the_archive_unpacks_with_plain_tar(self):
        d = self.make_dir()
        r = self.run_ep("host-helper", env=self.env(SWARMBOX_TEST_HOST_DIR=d))
        out = os.path.join(self.base, "out")
        os.mkdir(out)
        t = subprocess.run(["tar", "-x", "-C", out, "-f", "-"], input=r.stdout, capture_output=True)
        self.assertEqual(t.returncode, 0, t.stderr)
        self.assertTrue(os.access(os.path.join(out, "swarmbox-host"), os.X_OK))

    def test_a_missing_folder_fails_with_a_message_and_no_output(self):
        r = self.run_ep("host-helper", env=self.env(SWARMBOX_TEST_HOST_DIR=os.path.join(self.base, "nope")))
        self.assertEqual(r.returncode, 1)
        self.assertEqual(r.stdout, b"")
        self.assertIn(b"host-helper", r.stderr)

    def test_extra_arguments_are_refused(self):
        d = self.make_dir()
        r = self.run_ep("host-helper", "extra", env=self.env(SWARMBOX_TEST_HOST_DIR=d))
        self.assertEqual(r.returncode, 64)
        self.assertEqual(r.stdout, b"")


class Static(unittest.TestCase):
    def test_bash_syntax_and_shellcheck(self):
        r = subprocess.run(["bash", "-n", ENTRYPOINT], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        if shutil.which("shellcheck"):
            r = subprocess.run(["shellcheck", "-s", "bash", ENTRYPOINT], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
