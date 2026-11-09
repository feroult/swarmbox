"""The shared case table for the generated function (slice 3.5; design 3.3, 3.6, 3.7.1, 3.8, 13.3 layer 4, D33).

One table, three shells. tests/test_function_bash.py, test_function_zsh.py and test_function_fish.py each subclass
FunctionCases and say which shell runs it. Every case drives the shell as a subprocess with the tool's REAL function text
(the output of container/scripts/swarmbox-init.sh from the real templates), a FakeHostHelper (the helper folder is a link to the
fake's folder) and a FakePodman. Nothing here starts a real container, touches the real home or runs the real helper: HOME and
the XDG folders are mktemp folders and every SWARMBOX_* variable is removed from the environment.

The bootstrap cases build tar archives in Python (a good one has an executable `swarmbox-host`, a small sh script that records
its calls) and make the fake `podman run ... host-helper` write them to standard output (the `stdout_file` key of FakePodman).
"""
import io
import json
import os
import pty
import select
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import ROOT, FakeHostHelper, FakePodman, DEFAULT_IMAGE_REPO  # noqa: E402

INIT = os.path.join(ROOT, "container", "scripts", "swarmbox-init.sh")
REAL_HOST_DIR = os.path.join(ROOT, "container", "host")
ORG_IMAGE = (DEFAULT_IMAGE_REPO + ":%s")
BASE_TOOLS = ["sh", "bash", "dash", "tar", "mktemp", "mv", "rm", "mkdir", "sort", "head", "tail", "cat", "dirname", "printf",
              "true", "false", "uname", "env", "sed", "tr", "grep", "ls", "pwd", "basename", "chmod", "rmdir", "wc", "cut"]

HELPER_SH = """#!/bin/sh
d=$(dirname "$0")
echo "$*" >> "$d/calls"
case "$1" in
    version) cat "$d/VERSION" ;;
    config) [ "$2" = get ] && echo swarmbox ;;
esac
exit 0
"""

# The word routing of design 3.3: (arguments, where it goes). "host" words are passed to the helper whole; "exec" words become
# `podman exec ... swarmbox-entrypoint <words>`. The sequence before it is always: config get NAME and up (host words skip both).
HOST_WORDS = ["stop", "reset", "up", "url", "update", "config", "env", "remote", "fingerprint", "version"]
ROUTING = [
    ([], ["attach"]),
    (["--plain"], ["attach", "--plain"]),
    (["--plain", "ls", "-la"], ["attach", "--plain", "ls", "-la"]),
    (["claude"], ["attach", "claude"]),
    (["ls", "-la"], ["attach", "ls", "-la"]),
    (["attach"], ["attach"]),
    (["attach", "--plain"], ["attach", "--plain"]),
    (["attach", "make", "all"], ["attach", "make", "all"]),
    (["pubkey"], ["pubkey"]),
    (["tool", "list"], ["tool", "list"]),
    (["tool"], ["tool"]),
    (["frobnicate", "up"], ["attach", "frobnicate", "up"]),     # only the FIRST word decides
    (["bash", "-c", "stop"], ["attach", "bash", "-c", "stop"]),
]
AWKWARD = ["a b", "it's", 'say "hi"', "$HOME", "*", "x\ny", "", "--x=y z", "`id`", "~", "-n", "\\", "tab\there", "é", ";", "&", "!"]
EXIT_CODES = [0, 1, 2, 3, 130, 137]


def make_archive(path, version="2.0.0", helper=True, executable=True, extra=None):
    """A helper archive like the image's: swarmbox-host, VERSION, cloudflare-setup.py, templates/, tool-ports."""
    with tarfile.open(path, "w") as tf:
        def add(name, data, mode):
            ti = tarfile.TarInfo("./" + name)
            ti.size = len(data)
            ti.mode = mode
            ti.mtime = int(time.time())
            tf.addfile(ti, io.BytesIO(data))
        if helper:
            add("swarmbox-host", HELPER_SH.encode(), 0o755 if executable else 0o644)
        add("VERSION", (version + "\n").encode(), 0o644)
        add("DEFAULTS", open(os.path.join(ROOT, "container", "host", "DEFAULTS"), "rb").read(), 0o644)
        add("cloudflare-setup.py", b"# cf\n", 0o644)
        add("tool-ports", b"", 0o644)
        add("templates/bash", b"x\n", 0o644)
        for name, data in (extra or {}).items():
            add(name, data, 0o644)


def pty_run(argv, env, cwd, stdin_tty, stdout_tty=True):
    master, slave = pty.openpty()
    p = subprocess.Popen(argv, env=env, cwd=cwd, stdin=slave if stdin_tty else subprocess.DEVNULL,
                         stdout=slave if stdout_tty else subprocess.PIPE, stderr=subprocess.PIPE)
    if not stdout_tty:
        out, err = p.communicate()
        os.close(slave)
        os.close(master)
        return p.returncode, out.decode(), err.decode()
    os.close(slave)
    out = b""
    while True:
        r, _, _ = select.select([master], [], [], 10)
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


class FunctionCases:
    """Mixin: set SHELL (a list: the program and its options) and NAME; STRICT is the option for `set -u` or None."""
    SHELL = None
    NAME = None
    STRICT = None

    def setUp(self):
        self.base = tempfile.mkdtemp(prefix="swarmbox-test-fn-")
        self.addCleanup(shutil.rmtree, self.base, True)
        self.home = os.path.join(self.base, "home")
        self.data = os.path.join(self.home, "data")
        self.cwd = os.path.join(self.base, "cwd")
        for d in (self.home, self.data, self.cwd):
            os.makedirs(d)
        self.host_dir = os.path.join(self.data, "swarmbox", "host")
        self.fp = FakePodman({"exec": {}}).__enter__()
        self.addCleanup(self.fp.__exit__)
        self.shims = os.path.join(self.base, "shims")
        os.mkdir(self.shims)
        self.fn_n = 0
        self.fn = self.make_fn()

    # -- building blocks -------------------------------------------------------------------------------------------

    def make_fn(self, version="2.0.0", *flags):
        """The function text for this shell with the marker `version`, written to a file; returns the path."""
        hd = os.path.join(self.base, "initdir-%s" % version)
        if not os.path.isdir(hd):
            os.makedirs(hd)
            os.symlink(os.path.join(REAL_HOST_DIR, "templates"), os.path.join(hd, "templates"))
            with open(os.path.join(hd, "VERSION"), "w") as f:
                f.write(version + "\n")
            shutil.copy(os.path.join(REAL_HOST_DIR, "DEFAULTS"), hd)
        r = subprocess.run(["sh", INIT, "--shell", self.NAME, *flags],
                           env={"PATH": os.environ["PATH"], "SWARMBOX_TEST_HOST_DIR": hd}, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.fn_n += 1
        path = os.path.join(self.base, "fn-%d.%s" % (self.fn_n, self.NAME))
        with open(path, "w") as f:
            f.write(r.stdout)
        return path

    def fake_helper(self, version="2.0.0", **kw):
        kw.setdefault("commands", {"config get": {"stdout": "swarmbox\n"}, "*": {}})
        fh = FakeHostHelper(version=version, **kw).__enter__()
        self.addCleanup(fh.__exit__)
        os.makedirs(os.path.dirname(self.host_dir), exist_ok=True)
        if os.path.lexists(self.host_dir):
            os.unlink(self.host_dir)
        os.symlink(fh.dir, self.host_dir)
        return fh

    def archive(self, **kw):
        path = os.path.join(self.base, "helper-%d.tar" % len(os.listdir(self.base)))
        make_archive(path, **kw)
        return path

    def shim(self, name, body):
        p = os.path.join(self.shims, name)
        with open(p, "w") as f:
            f.write("#!/bin/sh\n" + body + "\n")
        os.chmod(p, 0o755)

    def env(self, path=None, **extra):
        env = {k: v for k, v in os.environ.items() if not k.startswith("SWARMBOX_")}
        env.update({"HOME": self.home, "XDG_DATA_HOME": self.data, "XDG_CONFIG_HOME": os.path.join(self.home, "c"),
                    "XDG_STATE_HOME": os.path.join(self.home, "s"), "LC_ALL": "C", "TERM": "dumb"})
        env.pop("SHELL", None)
        env["PATH"] = path if path is not None else self.shims + os.pathsep + self.fp.env()["PATH"]
        env.update(extra)
        return env

    def argv(self, fn, args, strict=False):
        sh = list(self.SHELL)
        if strict:
            sh.append(self.STRICT)
        if self.NAME == "fish":
            script = 'set -l f $argv[1]; set -e argv[1]; source $f; swarmbox $argv; exit $status'
            return sh + ["-c", script, fn] + list(args)
        script = '. "$1"; shift; swarmbox "$@"; exit $?'
        return sh + ["-c", script, self.NAME, fn] + list(args)

    def call(self, *args, fn=None, path=None, strict=False, **env):
        r = subprocess.run(self.argv(fn or self.fn, args, strict), env=self.env(path=path, **env), cwd=self.cwd,
                           capture_output=True, text=True, stdin=subprocess.DEVNULL)
        return r

    def call_pty(self, *args, stdin_tty=True, stdout_tty=True):
        return pty_run(self.argv(self.fn, args), self.env(), self.cwd, stdin_tty, stdout_tty)

    def exec_call(self, *words, tty="-i"):
        return ["exec", tty, "-e", "TERM", "-e", "COLORTERM", "swarmbox", "swarmbox-entrypoint", *words]

    def hcalls(self, fh):
        """The helper's calls without the first `version` probe that every call of the function makes."""
        calls = fh.calls()
        if calls and calls[0] == ["version"]:
            calls = calls[1:]
        return calls

    def podman_calls(self):
        return self.fp.calls()

    def tree(self):
        d = os.path.join(self.data, "swarmbox")
        return sorted(os.listdir(d)) if os.path.isdir(d) else []

    def installed_version(self):
        r = subprocess.run([os.path.join(self.host_dir, "swarmbox-host"), "version"], capture_output=True, text=True)
        return r.stdout.strip()

    # -- word routing (3.3) -----------------------------------------------------------------------------------------

    def test_word_routing_table(self):
        for args, words in ROUTING:
            with self.subTest(args=args):
                self.fp.configure({"exec": {}})
                open(self.fp.log_path, "w").close()
                fh = self.fake_helper()
                r = self.call(*args)
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertEqual((r.stdout, r.stderr), ("", ""))
                self.assertEqual(self.hcalls(fh), [["up"], ["config", "get", "NAME"]])
                self.assertEqual(self.podman_calls(), [self.exec_call(*words)])

    def test_host_words_go_to_the_helper_whole_and_nothing_else_runs(self):
        for word in HOST_WORDS:
            for rest in ([], ["a", "b c"]):
                with self.subTest(word=word, rest=rest):
                    open(self.fp.log_path, "w").close()
                    fh = self.fake_helper()
                    r = self.call(word, *rest)
                    self.assertEqual(r.returncode, 0, r.stderr)
                    self.assertEqual(self.hcalls(fh), [[word, *rest]])
                    self.assertEqual(self.podman_calls(), [])

    def test_a_host_word_only_counts_as_the_first_word(self):
        fh = self.fake_helper()
        self.call("run", "stop")
        self.assertEqual(self.hcalls(fh)[0], ["up"])

    def test_arguments_with_awkward_characters_reach_podman_exec_as_single_words(self):
        fh = self.fake_helper()
        r = self.call("printf", *AWKWARD)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.podman_calls(), [self.exec_call("attach", "printf", *AWKWARD)])
        self.assertEqual(self.hcalls(fh), [["up"], ["config", "get", "NAME"]])
        # nothing in them was expanded or run
        self.assertEqual(r.stdout, "")

    # -- exit codes -------------------------------------------------------------------------------------------------

    def test_exit_codes_of_forwarded_commands_propagate(self):
        for rc in EXIT_CODES:
            with self.subTest(rc=rc):
                self.fp.configure({"exec": {"exit": rc}})
                self.fake_helper()
                self.assertEqual(self.call("sh", "-c", "exit %d" % rc).returncode, rc)
                self.assertEqual(self.call("pubkey").returncode, rc)
                self.assertEqual(self.call().returncode, rc)

    def test_a_failing_up_stops_before_podman_exec(self):
        for rc in (3, 4, 5, 6, 7):
            with self.subTest(rc=rc):
                open(self.fp.log_path, "w").close()
                fh = self.fake_helper(commands={"up": {"exit": rc, "stderr": "swarmbox: nope\n"}, "*": {}})
                r = self.call("claude")
                self.assertEqual(r.returncode, rc)
                self.assertIn("swarmbox: nope", r.stderr)
                self.assertEqual(self.hcalls(fh), [["up"]])
                self.assertEqual(self.podman_calls(), [])

    # -- the terminal (3.3, "No terminal") ----------------------------------------------------------------------------

    def test_no_t_without_a_terminal(self):
        self.fake_helper()
        self.call("pubkey")
        self.call("ls")
        self.call()
        for c in self.podman_calls():
            self.assertNotIn("-t", c)
            self.assertNotIn("-it", c)
            self.assertEqual(c[1], "-i")

    def test_a_pty_adds_t_to_every_exec_form(self):
        self.fake_helper()
        for args, words in ((["pubkey"], ["pubkey"]), (["ls", "-l"], ["attach", "ls", "-l"]), ([], ["attach"]),
                            (["--plain"], ["attach", "--plain"])):
            with self.subTest(args=args):
                open(self.fp.log_path, "w").close()
                rc, out, err = self.call_pty(*args)
                self.assertEqual(rc, 0, err)
                self.assertEqual(self.podman_calls(), [self.exec_call(*words, tty="-it")])

    # -- bootstrap condition (D33, 3.6) ---------------------------------------------------------------------------------

    def check_extracts(self, **fh_kw):
        good = self.archive()
        self.fp.configure({"run": {"stdout_file": good}, "exec": {}})
        if fh_kw.pop("absent", False):
            pass
        else:
            self.fake_helper(**fh_kw)
        r = self.call("url")
        self.assertEqual(r.returncode, 0, r.stderr)
        runs = [c for c in self.podman_calls() if c[0] == "run"]
        self.assertEqual(runs, [["run", "--rm", ORG_IMAGE % "2.0.0", "host-helper"]])
        self.assertEqual(self.tree(), ["host"])
        self.assertEqual(r.stdout, "")
        with open(os.path.join(self.host_dir, "calls")) as f:
            self.assertEqual(f.read().strip(), "url")      # the NEW helper handled the word
        self.assertEqual(self.installed_version(), "2.0.0")
        self.assertTrue(os.access(os.path.join(self.host_dir, "swarmbox-host"), os.X_OK))
        self.assertFalse(os.path.exists(os.path.join(self.host_dir, "helper.tar")))
        return r

    def test_a_missing_helper_is_extracted_once(self):
        self.check_extracts(absent=True)

    def test_a_helper_file_that_is_not_executable_is_extracted(self):
        self.check_extracts(executable=False)

    def test_an_older_helper_is_extracted(self):
        self.check_extracts(version="1.9.0")

    def test_the_same_version_is_kept_with_no_podman_call_and_no_notice(self):
        fh = self.fake_helper(version="2.0.0")
        r = self.call("url")
        self.assertEqual((r.returncode, r.stdout, r.stderr), (0, "", ""))
        self.assertEqual(self.podman_calls(), [])
        self.assertEqual(self.hcalls(fh), [["url"]])

    def test_a_newer_helper_is_kept_with_one_notice_line(self):
        for hv in ("2.0.1", "2.1.0", "3.0.0", "2.0.10"):
            with self.subTest(hv=hv):
                open(self.fp.log_path, "w").close()
                fh = self.fake_helper(version=hv)
                r = self.call("url")
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertEqual(self.podman_calls(), [])
                self.assertEqual(self.hcalls(fh), [["url"]])
                lines = r.stderr.splitlines()
                self.assertEqual(len(lines), 1, r.stderr)
                self.assertEqual(lines[0], "swarmbox: the helper (%s) is newer than this function (2.0.0); kept" % hv)
                self.assertEqual(r.stdout, "")

    def test_sort_v_order_not_text_order(self):
        # 2.0.10 against a marker of 2.0.9 is newer (a text order calls it older and would extract)
        fn = self.make_fn("2.0.9")
        fh = self.fake_helper(version="2.0.10")
        r = self.call("url", fn=fn)
        self.assertEqual(self.podman_calls(), [])
        self.assertIn("newer", r.stderr)
        self.assertEqual(self.hcalls(fh), [["url"]])
        # and the other way round: 2.0.9 against a marker of 2.0.10 is older and is extracted
        fn10 = self.make_fn("2.0.10")
        good = self.archive(version="2.0.10")
        self.fp.configure({"run": {"stdout_file": good}, "exec": {}})
        self.fake_helper(version="2.0.9")
        r = self.call("url", fn=fn10)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual([c[0] for c in self.podman_calls()], ["run"])

    # -- failures of the extraction ----------------------------------------------------------------------------------

    def previous_helper(self):
        return self.fake_helper(version="1.9.0")

    def assert_failed_cleanly(self, r, message, expect_calls=None):
        self.assertEqual(r.returncode, 3, r.stderr)
        self.assertIn("swarmbox: cannot pull %s: " % (ORG_IMAGE % "2.0.0"), r.stderr)
        self.assertIn(message, r.stderr)
        self.assertIn("Check the network, or set SWARMBOX_IMAGE to an image you already have.", r.stderr)
        self.assertEqual(r.stdout, "")
        self.assertEqual(self.tree(), ["host"], "no temporary folder and no .old folder is left")
        self.assertEqual(self.installed_version(), "1.9.0", "the previous helper is intact")
        self.assertEqual([c[0] for c in self.podman_calls()], ["run"])

    def test_offline_with_no_image_exits_3_with_the_message_and_the_old_helper_intact(self):
        self.previous_helper()
        self.fp.configure({"run": {"exit": 125, "stderr": "Trying to pull x...\nError: initializing source: pinging container registry: no route to host\n"}})
        r = self.call("url")
        self.assert_failed_cleanly(r, "Error: initializing source: pinging container registry: no route to host")

    def test_podman_exiting_non_zero_even_with_a_good_archive_fails(self):
        self.previous_helper()
        self.fp.configure({"run": {"exit": 1, "stdout_file": self.archive(), "stderr": "Error: boom\n"}})
        self.assert_failed_cleanly(self.call("url"), "Error: boom")

    def test_a_corrupt_archive_fails(self):
        self.previous_helper()
        self.fp.configure({"run": {"stdout": "this is not a tar archive\n" * 200}})
        self.assert_failed_cleanly(self.call("url"), "the image has no usable host helper")

    def test_an_archive_without_swarmbox_host_fails(self):
        self.previous_helper()
        self.fp.configure({"run": {"stdout_file": self.archive(helper=False)}})
        self.assert_failed_cleanly(self.call("url"), "the image has no usable host helper")

    def test_a_failure_with_no_previous_helper_leaves_no_folder(self):
        self.fp.configure({"run": {"stdout_file": self.archive(helper=False)}})
        r = self.call("url")
        self.assertEqual(r.returncode, 3)
        self.assertEqual(self.tree(), [])
        self.assertEqual(os.listdir(os.path.dirname(self.host_dir)), [])

    def test_podman_absent_gives_exit_3_with_the_install_advice(self):
        tools = os.path.join(self.base, "tools")
        os.mkdir(tools)
        for t in BASE_TOOLS:
            p = shutil.which(t)
            if p and not os.path.exists(os.path.join(tools, t)):
                os.symlink(p, os.path.join(tools, t))
        self.assertFalse(os.path.exists(os.path.join(tools, "podman")))
        r = self.call("claude", path=tools)
        self.assertEqual(r.returncode, 3)
        self.assertEqual(r.stdout, "")
        self.assertIn("swarmbox: Podman is not installed.", r.stderr)
        self.assertIn("sudo apt install podman", r.stderr)
        self.assertIn("brew install podman", r.stderr)
        self.assertEqual(self.tree(), [])

    # -- update, then the next call (D33, 3.8) ---------------------------------------------------------------------------

    def test_update_then_next_call_does_not_undo_the_update(self):
        fh = self.fake_helper(version="2.0.0")
        r = self.call("update")
        self.assertEqual((r.returncode, r.stderr), (0, ""))
        fh.set_version("2.0.1")                         # what `update` left behind: a helper extracted from the 2.0.1 image
        open(self.fp.log_path, "w").close()
        r = self.call("claude")                         # second call, same 2.0.0 block
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual([c for c in self.podman_calls() if c[0] == "run"], [])
        self.assertEqual(r.stderr.splitlines(), ["swarmbox: the helper (2.0.1) is newer than this function (2.0.0); kept"])
        self.assertEqual(self.podman_calls(), [self.exec_call("attach", "claude")])       # and the word was routed
        self.assertEqual(self.installed_version(), "2.0.1")
        fn201 = self.make_fn("2.0.1")                    # a third call with a block of the new marker: no notice
        r = self.call("claude", fn=fn201)
        self.assertEqual((r.returncode, r.stderr), (0, ""))

    def test_the_block_with_an_image_flag_extracts_from_that_image(self):
        fn = self.make_fn("2.0.0", "--image", "localhost:5000/sb:2.0.0")
        self.fp.configure({"run": {"stdout_file": self.archive()}, "exec": {}})
        r = self.call("url", fn=fn)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.podman_calls()[0], ["run", "--rm", "localhost:5000/sb:2.0.0", "host-helper"])

    # -- sort without -V ----------------------------------------------------------------------------------------------

    def test_a_sort_without_dash_v_keeps_the_helper_and_does_not_crash(self):
        self.shim("sort", 'for a in "$@"; do [ "$a" = -V ] && { echo "sort: invalid option -- V" >&2; exit 2; }; done; exec %s "$@"'
                  % shutil.which("sort"))
        for hv in ("2.0.1", "1.9.0", "2.0.10"):
            with self.subTest(hv=hv):
                open(self.fp.log_path, "w").close()
                fh = self.fake_helper(version=hv)
                r = self.call("url")
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertEqual(self.podman_calls(), [])
                self.assertEqual(self.hcalls(fh), [["url"]])
                self.assertNotIn("newer", r.stderr)         # no false claim when the comparison gave no answer
                self.assertNotIn("sort", r.stderr)
                self.assertNotIn("invalid option", r.stderr)

    # -- seeds (D20, 3.7.5) -------------------------------------------------------------------------------------------

    def seed_call(self, fh):
        return [c for c in self.hcalls(fh) if c[:2] == ["config", "seed"]]

    def test_no_seed_flags_no_seed_call(self):
        fh = self.fake_helper()
        self.call("url")
        self.assertEqual(self.seed_call(fh), [])

    def test_seeds_are_passed_as_arguments_in_a_fixed_order(self):
        fn = self.make_fn("2.0.0", "--with", "claude,gcloud", "--workspace", "/srv/box", "--image", "img:2.0.0")
        fh = self.fake_helper()
        r = self.call("url", fn=fn)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.hcalls(fh), [["config", "seed", "--with", "claude,gcloud", "--workspace", "/srv/box", "--image", "img:2.0.0"],
                                      ["url"]])

    def test_only_the_seeds_given_are_passed(self):
        for flags, want in ((["--with", "x"], ["--with", "x"]), (["--workspace", "/w"], ["--workspace", "/w"]),
                            (["--image", "i:1"], ["--image", "i:1"]), (["--with", "x", "--image", "i:1"], ["--with", "x", "--image", "i:1"])):
            with self.subTest(flags=flags):
                fh = self.fake_helper(version="2.0.0")
                self.call("url", fn=self.make_fn("2.0.0", *flags))
                self.assertEqual(self.seed_call(fh), [["config", "seed", *want]])

    def test_seeds_with_awkward_characters_arrive_unchanged(self):
        ws = "/tmp/it's a $HOME `id` \\ \"x\" & dir"
        fh = self.fake_helper()
        self.call("url", fn=self.make_fn("2.0.0", "--workspace", ws, "--with", "a b"))
        self.assertEqual(self.seed_call(fh), [["config", "seed", "--with", "a b", "--workspace", ws]])

    def test_seeds_are_never_exported_as_swarmbox_variables(self):
        fh = self.fake_helper()
        self.call("claude", fn=self.make_fn("2.0.0", "--with", "claude", "--workspace", "/w", "--image", "i:1"))
        for env in fh.envs():
            self.assertEqual(env, {}, "the helper saw SWARMBOX_* variables: %r" % env)

    def test_a_relative_workspace_is_made_absolute_against_the_current_folder(self):
        for given, want in (("rel/dir", "%s/rel/dir"), ("./x", "%s/x"), ("plain", "%s/plain"), ("../up", "%s/../up")):
            with self.subTest(given=given):
                fh = self.fake_helper()
                self.call("url", fn=self.make_fn("2.0.0", "--workspace", given))
                self.assertEqual(self.seed_call(fh), [["config", "seed", "--workspace", want % os.path.realpath(self.cwd)]])

    def test_a_relative_workspace_with_spaces_is_made_absolute(self):
        d = os.path.join(self.cwd, "my dir")
        os.makedirs(d)
        fh = self.fake_helper()
        r = subprocess.run(self.argv(self.make_fn("2.0.0", "--workspace", "sub dir/x"), ["url"]), env=self.env(), cwd=d,
                           capture_output=True, text=True, stdin=subprocess.DEVNULL)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.seed_call(fh), [["config", "seed", "--workspace", os.path.realpath(d) + "/sub dir/x"]])

    def test_absolute_and_home_relative_workspaces_pass_unchanged(self):
        for given in ("/abs/path", "~", "~/code/box", "/"):
            with self.subTest(given=given):
                fh = self.fake_helper()
                self.call("url", fn=self.make_fn("2.0.0", "--workspace", given))
                self.assertEqual(self.seed_call(fh), [["config", "seed", "--workspace", given]])

    def test_a_failing_seed_stops_the_call(self):
        fh = self.fake_helper(commands={"config seed": {"exit": 2, "stderr": "swarmbox: bad seed\n"}, "*": {}})
        r = self.call("claude", fn=self.make_fn("2.0.0", "--with", "x"))
        self.assertEqual(r.returncode, 2)
        self.assertIn("bad seed", r.stderr)
        self.assertEqual(self.hcalls(fh), [["config", "seed", "--with", "x"]])
        self.assertEqual(self.podman_calls(), [])

    def test_the_seed_runs_after_the_bootstrap_and_before_the_word(self):
        fn = self.make_fn("2.0.0", "--with", "claude")
        self.fp.configure({"run": {"stdout_file": self.archive()}, "exec": {}})
        r = self.call("url", fn=fn)
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(os.path.join(self.host_dir, "calls")) as f:
            self.assertEqual(f.read().splitlines(), ["config seed --with claude", "url"])

    # -- the shell itself -----------------------------------------------------------------------------------------------

    def test_the_helper_is_found_under_xdg_data_home_and_falls_back_to_home(self):
        fh = self.fake_helper()
        r = self.call("url")
        self.assertEqual(self.hcalls(fh), [["url"]])
        # without XDG_DATA_HOME the helper lives under $HOME/.local/share/swarmbox/host
        home_host = os.path.join(self.home, ".local", "share", "swarmbox")
        os.makedirs(home_host)
        os.symlink(fh.dir, os.path.join(home_host, "host"))
        env = self.env()
        env.pop("XDG_DATA_HOME")
        open(fh.log_path, "w").close()
        r = subprocess.run(self.argv(self.fn, ["url"]), env=env, cwd=self.cwd, capture_output=True, text=True,
                           stdin=subprocess.DEVNULL)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.hcalls(fh), [["url"]])

    def test_it_works_with_unset_variables_made_an_error(self):
        if not self.STRICT:
            self.skipTest("this shell has no set -u")
        fh = self.fake_helper()
        r = self.call("claude", strict=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        r = self.call(strict=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        r = self.call("url", strict=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stderr, "")
        r = self.call("url", strict=True, fn=self.make_fn("2.0.0", "--with", "x", "--workspace", "rel"))
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_the_block_is_one_function_between_markers(self):
        text = open(self.fn).read()
        self.assertEqual(text.count("# >>> swarmbox 2.0.0 >>>"), 1)
        self.assertEqual(text.count("# <<< swarmbox 2.0.0 <<<"), 1)
