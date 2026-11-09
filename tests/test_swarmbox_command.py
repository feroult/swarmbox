"""The `swarmbox` command: which words the script handles itself and which go to the box, and how they are forwarded.

The real script (container/host/swarmbox-host) runs as a program, with no shell function around it, against the shared FakePodman. The
box is a fake one that is already running and matches the configuration, so `up` takes its fast path and the test sees the
`podman exec` the script ends with. Nothing here starts a real container; tests/smoke_image.py does.
Run: python3 tests/test_swarmbox_command.py
"""
import os
import shutil
import subprocess
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_host_up as up_tests  # noqa: E402
from helpers import DEFAULT_NAME, pty_run  # noqa: E402

HOST_WORDS = ["stop", "reset", "up", "url", "update", "config", "env", "remote", "fingerprint", "version", "help", "--help", "-h"]
# (arguments, the words after `swarmbox-entrypoint` in the `podman exec`)
ROUTING = [
    ([], ["attach"]),
    (["--plain"], ["attach", "--plain"]),
    (["--plain", "ls", "-la"], ["attach", "--plain", "ls", "-la"]),
    (["claude"], ["attach", "claude"]),
    (["ls", "-la"], ["attach", "ls", "-la"]),
    (["attach"], ["attach"]),                       # a leading `attach` is a prefix, not an argument
    (["attach", "--plain"], ["attach", "--plain"]),
    (["attach", "make", "all"], ["attach", "make", "all"]),
    (["pubkey"], ["pubkey"]),                       # forwarded as they are
    (["tool", "list"], ["tool", "list"]),
    (["tool"], ["tool"]),
    (["frobnicate", "up"], ["attach", "frobnicate", "up"]),     # only the FIRST word decides
    (["bash", "-c", "stop"], ["attach", "bash", "-c", "stop"]),
]
AWKWARD = ["a b", "it's", 'say "hi"', "$HOME", "*", "x\ny", "", "--x=y z", "`id`", "~", "-n", "\\", "tab\there", "é", ";", "&", "!"]


class Base(up_tests.Base):
    def setUp(self):
        super().setUp()
        self.podman()
        self.fp.configure(self.conf(lookup={"stdout": self.matching_line()}, exec={}))

    def exec_calls(self):
        return [c for c in self.calls() if c[:1] == ["exec"] and "swarmbox-entrypoint" in c]

    def swarmbox(self, *args, env=None):
        return self.run_h(*args, env=env)

    def entry(self, *words, tty="-i", name=None):
        return ["exec", tty, "-e", "TERM", "-e", "COLORTERM", name or NAME, "swarmbox-entrypoint", *words]


NAME = DEFAULT_NAME


class RoutingTest(Base):
    def test_every_other_word_goes_to_the_box_after_up(self):
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

    def test_arguments_with_awkward_characters_reach_podman_exec_as_single_words(self):
        r = self.swarmbox("printf", *AWKWARD)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.exec_calls(), [self.entry("attach", "printf", *AWKWARD)])
        self.assertEqual(r.stdout, "")

    def test_the_name_of_the_box_comes_from_the_config(self):
        r = self.swarmbox("ls", env=self.env(SWARMBOX_NAME="other"))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.exec_calls(), [self.entry("attach", "ls", name="other")])

    def test_exit_codes_of_forwarded_commands_propagate(self):
        for rc in (0, 1, 2, 3, 130, 137):
            with self.subTest(rc=rc):
                self.fp.configure(self.conf(lookup={"stdout": self.matching_line()}, exec={"exit": rc}))
                for args in (["sh", "-c", "exit %d" % rc], ["pubkey"], []):
                    self.assertEqual(self.swarmbox(*args).returncode, rc)

    def test_a_failing_up_stops_before_podman_exec(self):
        self.fp.configure(self.conf(lookup={"exit": 1, "stderr": "Error: boom\n"}))
        r = self.swarmbox("claude")
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(self.exec_calls(), [])
        self.assertTrue(r.stderr)


class HostWordsTest(Base):
    def test_help_words_print_the_list_with_no_podman_call(self):
        for word in ("help", "--help", "-h"):
            with self.subTest(word=word):
                r = self.swarmbox(word)
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertTrue(r.stdout.startswith("usage: swarmbox"), r.stdout)
                self.assertEqual(r.stderr, "")
                self.assertEqual(self.calls(), [])

    def test_version_and_config_never_reach_the_box(self):
        for args in (["version"], ["config", "get", "NAME"], ["config", "list"], ["env", "list"], ["url"]):
            with self.subTest(args=args):
                r = self.swarmbox(*args)
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

    def test_a_host_word_counts_only_as_the_first_word(self):
        r = self.swarmbox("run", "stop")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.exec_calls(), [self.entry("attach", "run", "stop")])

    def test_every_host_word_is_in_the_case_of_the_script(self):
        with open(up_tests.HELPER_SRC) as f:
            text = f.read()
        tail = text[text.rindex("\ncase ${1-} in"):]
        for word in HOST_WORDS:
            self.assertRegex(tail, r"(^|[|\s])%s[|)\s]" % word, word)


class TerminalTest(Base):
    def pty(self, *args, stdin_tty=True, stdout_tty=True):
        return pty_run([self.helper, *args], self.env(), self.tmp, stdin_tty, stdout_tty)

    def test_no_t_without_a_terminal(self):
        for args in (["pubkey"], ["ls"], []):
            self.swarmbox(*args)
        for c in self.exec_calls():
            self.assertEqual(c[1], "-i")
            self.assertNotIn("-t", c)

    def test_a_terminal_on_both_ends_adds_t_to_every_exec_form(self):
        for args, words in (([], ["attach"]), (["pubkey"], ["pubkey"]), (["ls", "-l"], ["attach", "ls", "-l"]),
                            (["--plain"], ["attach", "--plain"])):
            with self.subTest(args=args):
                open(self.fp.log_path, "w").close()
                rc, out, err = self.pty(*args)
                self.assertEqual(rc, 0, err)
                self.assertEqual(self.exec_calls(), [self.entry(*words, tty="-it")])

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
