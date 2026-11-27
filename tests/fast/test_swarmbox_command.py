"""The `swarmbox` command: which words the script handles itself and which go to the box, and how they are forwarded.

The real script (container/host/swarmbox-host) runs as a program, with no shell function around it, against the shared FakePodman. The
box is a fake one that is already running and matches the configuration, so `up` takes its fast path and the test sees the
`podman exec` the script ends with. Nothing here starts a real container; tests/slow/smoke_image.py does.
Run: python3 tests/fast/test_swarmbox_command.py
"""
import concurrent.futures
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "support"))
from helpers import DEFAULT_NAME, FakePodman, pty_run  # noqa: E402
from host_support import DEFAULTS_SRC, HELPER_SRC, IMAGE, UpBase, VERSION_SRC, env_hash, fingerprint, line  # noqa: E402

_EMPTY_ENV_HASH = env_hash([])

# (arguments, the words after `swarmbox-entrypoint` in the `podman exec`)
ROUTING = [
    ([], ["attach"]),
    (["--plain", "ls", "-la"], ["attach", "--plain", "ls", "-la"]),
    (["claude"], ["attach", "claude"]),
    (["attach"], ["attach"]),                       # a leading `attach` is a prefix, not an argument
    (["attach", "make", "all"], ["attach", "make", "all"]),
    (["pubkey"], ["pubkey"]),                       # forwarded as they are
    (["addon", "list"], ["addon", "list"]),
    (["bus", "pub", "goal", "a b"], ["bus", "pub", "goal", "a b"]),
    (["tabs", "send", "work", "ls"], ["tabs", "send", "work", "ls"]),
    (["frobnicate", "up"], ["attach", "frobnicate", "up"]),     # only the FIRST word decides: a host word later on is an argument
]
AWKWARD = ["a b", "it's", 'say "hi"', "$HOME", "*", "x\ny", "", "--x=y z", "`id`", "~", "-n", "\\", "tab\there", "é", ";", "&", "!"]


class Base(UpBase):
    @classmethod
    def setUpClass(cls):
        cls._shared_dir = os.path.realpath(tempfile.mkdtemp(prefix="swarmbox-test-cmd-sh."))
        cls.addClassCleanup(shutil.rmtree, cls._shared_dir, True)
        hdir = os.path.join(cls._shared_dir, "helper")
        os.makedirs(hdir)
        shutil.copy(HELPER_SRC, os.path.join(hdir, "swarmbox-host"))
        os.chmod(os.path.join(hdir, "swarmbox-host"), 0o755)
        shutil.copy(VERSION_SRC, os.path.join(hdir, "VERSION"))
        shutil.copy(DEFAULTS_SRC, os.path.join(hdir, "DEFAULTS"))
        with open(os.path.join(hdir, "addon-ports"), "w") as f:
            f.write("")
        for n, c in (("localtime", ""), ("tun", ""), ("proc-version", "Linux version 6.1.0 (debian)\n")):
            with open(os.path.join(cls._shared_dir, n), "w") as f:
                f.write(c)

    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="swarmbox-test-up."))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.home = os.path.join(self.tmp, "home")
        os.mkdir(self.home)
        self.ws = os.path.join(self.tmp, "ws")
        os.mkdir(self.ws)
        self.state = os.path.join(self.home, ".local", "state", "swarmbox")
        self.hdir = os.path.join(self._shared_dir, "helper")
        self.helper = os.path.join(self.hdir, "swarmbox-host")
        self.fp = None
        self.podman()
        self.fp.configure(self.conf(lookup={"stdout": self.matching_line()}, exec={}))

    def env(self, **extra):
        e = super().env(
            SWARMBOX_LOCALTIME_FILE=os.path.join(self._shared_dir, "localtime"),
            SWARMBOX_TEST_PROC_VERSION=os.path.join(self._shared_dir, "proc-version"),
            SWARMBOX_TEST_TUN=os.path.join(self._shared_dir, "tun"),
            SWARMBOX_TEST_NAP="0.001",
        )
        e.update(extra)
        return e

    def matching_line(self, env_extra=None, **kw):
        if env_extra:
            return super().matching_line(env_extra, **kw)
        fp_lines = [
            "AGENT=", "BROWSER_URL=", "ENV_KEYS=", "HOSTNAME=" + NAME, "HOST_ACCESS=0",
            "IMAGE=" + IMAGE, "INIT=0", "NAME=" + NAME, "PORTS=",
            "TZ=local", "WEB=1", "WEB_PORT=7681", "WITH=", "WORKSPACE=" + self.ws, "YOLO=1",
        ]
        d = dict(ports="", env_hash=_EMPTY_ENV_HASH, fp=fingerprint(fp_lines, _EMPTY_ENV_HASH), ws=self.ws, image=IMAGE)
        d.update(kw)
        return line(**d)

    def _par(self, fn, items, max_workers=10):
        items = list(items)
        if len(items) <= 1 or os.environ.get("SWARMBOX_RUNNER_PARALLEL"):
            return [fn(x) for x in items]
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(max_workers, len(items))) as pool:
            return list(pool.map(fn, items))

    def _make_fp(self, conf):
        fp = FakePodman(conf)
        fp.__enter__()
        self.addCleanup(fp.__exit__)
        return fp

    def _env_for_fp(self, fp, **extra):
        e = self.env(**extra)
        e["PATH"] = fp.env()["PATH"]
        return e

    def exec_calls(self, fp=None):
        calls = (fp or self.fp).calls()
        return [c for c in calls if c[:1] == ["exec"] and "swarmbox-entrypoint" in c]

    def swarmbox(self, *args, env=None):
        return self.run_h(*args, env=env)

    def entry(self, *words, tty="-i", name=None):
        return ["exec", tty, "-e", "TERM", "-e", "COLORTERM", name or NAME, "swarmbox-entrypoint", *words]


NAME = DEFAULT_NAME


class RoutingTest(Base):
    def test_every_other_word_goes_to_the_box_after_up(self):
        if os.environ.get("SWARMBOX_RUNNER_PARALLEL"):
            for args, words in ROUTING:
                with self.subTest(args=args):
                    open(self.fp.log_path, "w").close()
                    r = self.swarmbox(*args)
                    self.assertEqual(r.returncode, 0, r.stderr)
                    self.assertEqual((r.stdout, r.stderr), ("", ""))
                    self.assertEqual(self.exec_calls(), [self.entry(*words)])
                    # up came first: the lookup of the box is before the exec
                    names = [c[0] + " " + c[1] if len(c) > 1 else c[0] for c in self.calls()]
                    self.assertLess(names.index("container inspect"), names.index("exec -i"))
            return
        conf = self.conf(lookup={"stdout": self.matching_line()}, exec={})
        items = [(args, words, self._make_fp(conf)) for args, words in ROUTING]
        results = self._par(lambda it: (it[0], it[1], it[2], self.swarmbox(*it[0], env=self._env_for_fp(it[2]))), items)
        for args, words, fp, r in results:
            with self.subTest(args=args):
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertEqual((r.stdout, r.stderr), ("", ""))
                self.assertEqual(self.exec_calls(fp), [self.entry(*words)])
                names = [c[0] + " " + c[1] if len(c) > 1 else c[0] for c in fp.calls()]
                self.assertLess(names.index("container inspect"), names.index("exec -i"))

    def test_arguments_with_awkward_characters_reach_podman_exec_as_single_words(self):
        r = self.swarmbox("printf", *AWKWARD)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.exec_calls(), [self.entry("attach", "printf", *AWKWARD)])
        self.assertEqual(r.stdout, "")

    def test_the_name_of_the_box_comes_from_the_config(self):
        r = self.swarmbox("ls", env=self.env(SWARMBOX_NAME="other"))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.exec_calls(), [self.entry("attach", "ls", name="other")])

    def test_the_exit_code_of_the_box_command_is_the_exit_code_of_swarmbox(self):
        cases = ((2, ["sh", "-c", "exit 2"]), (137, ["pubkey"]), (130, []))
        ml = self.matching_line()
        if os.environ.get("SWARMBOX_RUNNER_PARALLEL"):
            for rc, args in cases:
                with self.subTest(rc=rc):
                    self.fp.configure(self.conf(lookup={"stdout": ml}, exec={"exit": rc}))
                    self.assertEqual(self.swarmbox(*args).returncode, rc)
            return
        items = [(rc, args, self._make_fp(self.conf(lookup={"stdout": ml}, exec={"exit": rc}))) for rc, args in cases]
        results = self._par(lambda it: (it[0], self.swarmbox(*it[1], env=self._env_for_fp(it[2])).returncode), items, max_workers=3)
        for rc, got in results:
            with self.subTest(rc=rc):
                self.assertEqual(got, rc)

    def test_a_failing_up_stops_before_podman_exec(self):
        self.fp.configure(self.conf(lookup={"exit": 1, "stderr": "Error: boom\n"}))
        r = self.swarmbox("claude")
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(self.exec_calls(), [])
        self.assertTrue(r.stderr)


class HostWordsTest(Base):
    def test_help_words_print_the_list_with_no_podman_call(self):
        words = ("help", "--help", "-h")
        results = self._par(lambda w: (w, self.swarmbox(w)), words, max_workers=3)
        for word, r in results:
            with self.subTest(word=word):
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertTrue(r.stdout.startswith("usage: swarmbox"), r.stdout)
                self.assertEqual(r.stderr, "")
        self.assertEqual(self.calls(), [])

    def test_version_and_config_never_reach_the_box(self):
        argss = (["version"], ["config", "get", "NAME"], ["config", "list"], ["env", "list"], ["url"])
        results = self._par(lambda a: (a, self.swarmbox(*a)), argss, max_workers=5)
        for args, r in results:
            with self.subTest(args=args):
                self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.calls(), [])

    def test_up_and_stop_are_handled_by_the_script_and_do_not_exec(self):
        for word in ("up", "stop"):
            with self.subTest(word=word):
                open(self.fp.log_path, "w").close()
                r = self.swarmbox(word)
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertEqual(self.exec_calls(), [])
                self.assertTrue(self.calls())


class TerminalTest(Base):
    def pty(self, *args, stdin_tty=True, stdout_tty=True):
        return pty_run([self.helper, *args], self.env(), self.tmp, stdin_tty, stdout_tty)

    def test_a_terminal_on_both_ends_adds_t_to_every_exec_form_and_the_attach_carries_the_tty_of_the_tab(self):
        for args, words in (([], ["attach"]), (["pubkey"], ["pubkey"])):
            with self.subTest(args=args):
                open(self.fp.log_path, "w").close()
                rc, out, err = self.pty(*args)
                self.assertEqual(rc, 0, err)
                calls = self.exec_calls()
                self.assertEqual(len(calls), 1)
                call = calls[0]
                keys = [a for a in call if a.startswith("SWARMBOX_TAB=")]
                if words[0] == "attach":
                    # the pty of the terminal, which names the tab for as long as it lives: the box puts a returning tab back in its place
                    self.assertEqual(len(keys), 1, call)
                    self.assertRegex(keys[0], r"^SWARMBOX_TAB=/dev/(pts/\d+|tty\w*|ttys\d+)$")
                    i = call.index(keys[0])
                    self.assertEqual(call[i - 1], "-e")
                    call = call[:i - 1] + call[i + 1:]
                else:
                    self.assertEqual(keys, [], "pubkey and addon do not need it")
                self.assertEqual([call], [self.entry(*words, tty="-it")])

    # (without a terminal at all the Routing tests already see `exec -i` and no -t)
    def test_one_end_that_is_not_a_terminal_is_enough_to_leave_t_out(self):
        for stdin_tty, stdout_tty in ((True, False), (False, True)):
            with self.subTest(stdin_tty=stdin_tty, stdout_tty=stdout_tty):
                open(self.fp.log_path, "w").close()
                rc, out, err = self.pty("ls", stdin_tty=stdin_tty, stdout_tty=stdout_tty)
                self.assertEqual(rc, 0, err)
                self.assertEqual(self.exec_calls(), [self.entry("attach", "ls")])


class ShellTest(Base):
    def test_it_runs_under_other_posix_shells_with_no_rc_file(self):
        shells = [s for s in (shutil.which("dash"), shutil.which("bash")) if s]
        for sh in shells:
            with self.subTest(sh=sh):
                open(self.fp.log_path, "w").close()
                args = [sh] + (["--posix"] if sh.endswith("bash") else []) + [self.helper, "ls"]
                r = subprocess.run(args, env=self.env(), capture_output=True, text=True, input="", cwd=self.tmp)
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertEqual(self.exec_calls(), [self.entry("attach", "ls")])


if __name__ == "__main__":
    unittest.main()
