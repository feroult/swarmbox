#!/usr/bin/env python3
"""Tests for the shared fake podman in helpers.py.  Run:  python3 tests/test_helpers.py"""
import json
import os
import shutil
import subprocess
import unittest

from helpers import ROOT, UNKNOWN_COMMAND_EXIT, FakeHostHelper, FakePodman


def run(fp, *args, **kw):
    return subprocess.run(["podman", *args], env=fp.env(), capture_output=True, text=True, **kw)


class Helpers(unittest.TestCase):
    def test_root_is_the_repository(self):
        self.assertTrue(os.path.isfile(os.path.join(ROOT, "start.sh")))

    def test_records_exact_argv(self):
        odd = ["a b", 'q"uote\'s', "$HOME `x`", "line1\nline2", "", "--flag=x y"]
        with FakePodman() as fp:
            run(fp, "run", *odd)
            self.assertEqual(fp.calls(), [["run", *odd]])
            with open(fp.log_path) as f:
                lines = f.read().splitlines()
            self.assertEqual(len(lines), 1)  # the newline inside an argument did not split the record
            self.assertEqual(json.loads(lines[0])["argv"], ["run", *odd])

    def test_exit_stdout_stderr_per_subcommand(self):
        with FakePodman({"ps": {"stdout": "cid1\n"}, "stop": {"exit": 3, "stderr": "boom\n"},
                         "create-flags": {"stdout": ["--hostname", "a b"]}}) as fp:
            r = run(fp, "ps", "-a")
            self.assertEqual((r.returncode, r.stdout), (0, "cid1\n"))
            r = run(fp, "stop", "x")
            self.assertEqual((r.returncode, r.stdout, r.stderr), (3, "", "boom\n"))
            self.assertEqual(run(fp, "create-flags").stdout, "--hostname\na b\n")

    def test_unconfigured_default_is_exit_0_and_silent(self):
        with FakePodman() as fp:
            r = run(fp, "whatever")
            self.assertEqual((r.returncode, r.stdout, r.stderr), (0, "", ""))

    def test_fallback_and_global_options_are_skipped(self):
        with FakePodman({"*": {"exit": 7}, "version": {"stdout": "v\n"}}) as fp:
            self.assertEqual(run(fp, "--url", "unix:///x/p.sock", "version").stdout, "v\n")
            self.assertEqual(run(fp, "images").returncode, 7)

    def test_reconfigure_between_calls(self):
        with FakePodman() as fp:
            self.assertEqual(run(fp, "ps").stdout, "")
            fp.configure({"ps": {"stdout": "z\n"}})
            self.assertEqual(run(fp, "ps").stdout, "z\n")

    def test_log_accumulates_across_invocations(self):
        with FakePodman() as fp:
            for n in range(3):
                run(fp, "ps", str(n))
            self.assertEqual(fp.calls(), [["ps", "0"], ["ps", "1"], ["ps", "2"]])

    def test_concurrent_invocations_do_not_interleave(self):
        big = "x" * 3000
        loop = 'i=0; while [ $i -lt 25 ]; do podman run "$1" "$2"; i=$((i+1)); done'
        with FakePodman() as fp:
            procs = [subprocess.Popen(["sh", "-c", loop, "sh", str(k), big], env=fp.env()) for k in range(2)]
            for p in procs:
                self.assertEqual(p.wait(timeout=120), 0)
            calls = fp.calls()  # json.loads raises on a torn record
            self.assertEqual(len(calls), 50)
            self.assertTrue(all(c[0] == "run" and c[2] == big for c in calls))
            self.assertEqual(sorted(c[1] for c in calls), ["0"] * 25 + ["1"] * 25)

    def test_cidfile_written_only_when_configured(self):
        with FakePodman({"run": {"cidfile": "abc123"}}) as fp:
            cid = os.path.join(fp.dir, "cid")
            run(fp, "run", "--cidfile", cid, "img")
            with open(cid) as f:
                self.assertEqual(f.read(), "abc123")
            cid2 = os.path.join(fp.dir, "cid2")
            run(fp, "run", "--cidfile=" + cid2, "img")
            self.assertTrue(os.path.exists(cid2))
            fp.configure({})
            cid3 = os.path.join(fp.dir, "cid3")
            run(fp, "run", "--cidfile", cid3, "img")
            self.assertFalse(os.path.exists(cid3))

    def test_fake_shadows_real_podman_and_never_executes_anything(self):
        with FakePodman() as fp:
            self.assertEqual(shutil.which("podman"), os.path.join(fp.dir, "podman"))
            with open(os.path.join(fp.dir, "podman")) as f:
                src = f.read()
            for word in ("subprocess", "os.exec", "os.system", "popen"):
                self.assertNotIn(word, src)

    def test_leak_check_fails_loudly_when_another_podman_is_first(self):
        with FakePodman() as fp:
            other = os.path.join(fp.dir, "other")
            os.mkdir(other)
            exe = os.path.join(other, "podman")
            with open(exe, "w") as f:
                f.write("#!/bin/sh\nexit 99\n")
            os.chmod(exe, 0o755)
            saved = os.environ["PATH"]
            os.environ["PATH"] = other + os.pathsep + saved
            try:
                with self.assertRaises(AssertionError):
                    fp.assert_no_leak()
            finally:
                os.environ["PATH"] = saved
            fp.assert_no_leak()

    def test_path_and_tempdir_are_restored_on_exit(self):
        before = os.environ["PATH"]
        with FakePodman() as fp:
            d = fp.dir
            self.assertTrue(os.path.isdir(d))
        self.assertEqual(os.environ["PATH"], before)
        self.assertFalse(os.path.exists(d))

    def test_cleanup_happens_when_the_body_raises(self):
        before = os.environ["PATH"]
        d = None
        with self.assertRaises(RuntimeError):
            with FakePodman() as fp:
                d = fp.dir
                raise RuntimeError("x")
        self.assertEqual(os.environ["PATH"], before)
        self.assertFalse(os.path.exists(d))


def host(fh, *args):
    return subprocess.run([fh.path, *args], capture_output=True, text=True)


class FakePodmanRules(unittest.TestCase):
    """Slice 3.3: rules by arguments and answers in sequence."""

    def test_rules_pick_the_first_match_and_default_answers_the_rest(self):
        conf = {"container": {"rules": [{"match": ["inspect", "State.ExitCode"], "stdout": "exited 1\n"},
                                        {"match": ["inspect"], "stdout": "line\n"}],
                              "default": {"exit": 9}}}
        with FakePodman(conf) as fp:
            self.assertEqual(run(fp, "container", "inspect", "--format", "{{.State.ExitCode}}", "x").stdout, "exited 1\n")
            self.assertEqual(run(fp, "container", "inspect", "--format", "{{.Name}}", "x").stdout, "line\n")
            self.assertEqual(run(fp, "container", "exists", "x").returncode, 9)

    def test_seq_answers_one_entry_per_call_of_its_rule_and_the_last_repeats(self):
        conf = {"container": {"rules": [{"match": ["inspect"], "seq": [{"exit": 125, "stderr": "no such\n"}, {"stdout": "a\n"},
                                                                     {"stdout": "b\n"}]},
                                        {"match": ["exists"], "stdout": "other\n"}]}}
        with FakePodman(conf) as fp:
            self.assertEqual(run(fp, "container", "inspect", "x").returncode, 125)
            run(fp, "container", "exists", "x")  # another rule: does not advance the sequence
            self.assertEqual(run(fp, "container", "inspect", "x").stdout, "a\n")
            self.assertEqual(run(fp, "container", "inspect", "x").stdout, "b\n")
            self.assertEqual(run(fp, "container", "inspect", "x").stdout, "b\n")

    def test_seq_with_a_cidfile(self):
        conf = {"run": {"seq": [{"exit": 126, "cidfile": "abc"}]}}
        with FakePodman(conf) as fp:
            cid = os.path.join(fp.dir, "cid")
            self.assertEqual(run(fp, "run", "--cidfile", cid, "img").returncode, 126)
            with open(cid) as f:
                self.assertEqual(f.read(), "abc")


class FakePodmanRules(unittest.TestCase):
    """Slice 3.3: rules by arguments and answers in sequence."""

    def test_rules_pick_the_first_match_and_default_answers_the_rest(self):
        conf = {"container": {"rules": [{"match": ["inspect", "State.ExitCode"], "stdout": "exited 1\n"},
                                        {"match": ["inspect"], "stdout": "line\n"}],
                              "default": {"exit": 9}}}
        with FakePodman(conf) as fp:
            self.assertEqual(run(fp, "container", "inspect", "--format", "{{.State.ExitCode}}", "x").stdout, "exited 1\n")
            self.assertEqual(run(fp, "container", "inspect", "--format", "{{.Name}}", "x").stdout, "line\n")
            self.assertEqual(run(fp, "container", "exists", "x").returncode, 9)

    def test_seq_answers_one_entry_per_call_of_its_rule_and_the_last_repeats(self):
        conf = {"container": {"rules": [{"match": ["inspect"], "seq": [{"exit": 125, "stderr": "no such\n"}, {"stdout": "a\n"},
                                                                     {"stdout": "b\n"}]},
                                        {"match": ["exists"], "stdout": "other\n"}]}}
        with FakePodman(conf) as fp:
            self.assertEqual(run(fp, "container", "inspect", "x").returncode, 125)
            run(fp, "container", "exists", "x")  # another rule: does not advance the sequence
            self.assertEqual(run(fp, "container", "inspect", "x").stdout, "a\n")
            self.assertEqual(run(fp, "container", "inspect", "x").stdout, "b\n")
            self.assertEqual(run(fp, "container", "inspect", "x").stdout, "b\n")

    def test_seq_with_a_cidfile(self):
        conf = {"run": {"seq": [{"exit": 126, "cidfile": "abc"}]}}
        with FakePodman(conf) as fp:
            cid = os.path.join(fp.dir, "cid")
            self.assertEqual(run(fp, "run", "--cidfile", cid, "img").returncode, 126)
            with open(cid) as f:
                self.assertEqual(f.read(), "abc")


class FakeHost(unittest.TestCase):
    def test_version_is_set_by_the_test(self):
        with FakeHostHelper(version="2.0.10") as fh:
            r = host(fh, "version")
            self.assertEqual((r.returncode, r.stdout), (0, "2.0.10\n"))
            fh.set_version("1.9.0")
            self.assertEqual(host(fh, "version").stdout, "1.9.0\n")

    def test_version_none_prints_nothing(self):
        with FakeHostHelper(version=None) as fh:
            r = host(fh, "version")
            self.assertEqual((r.returncode, r.stdout, r.stderr), (0, "", ""))

    def test_missing_and_non_executable(self):
        with FakeHostHelper(present=False) as fh:
            self.assertFalse(os.path.exists(fh.path))
        with FakeHostHelper(executable=False) as fh:
            self.assertTrue(os.path.isfile(fh.path))
            self.assertFalse(os.access(fh.path, os.X_OK))
            fh.set_executable(True)
            self.assertTrue(os.access(fh.path, os.X_OK))
            self.assertEqual(host(fh, "version").stdout, "2.0.0\n")

    def test_records_exact_argv(self):
        odd = ["a b", 'q"uote\'s', "$HOME `x`", "line1\nline2", "", "--flag=x y"]
        with FakeHostHelper(commands={"*": {}}) as fh:
            host(fh, "config", *odd)
            self.assertEqual(fh.calls(), [["config", *odd]])

    def test_exit_stdout_stderr_per_command(self):
        with FakeHostHelper(commands={"up": {"exit": 6, "stderr": "not ready\n"},
                                      "config": {"stdout": ["a b", "c"]}}) as fh:
            r = host(fh, "up")
            self.assertEqual((r.returncode, r.stdout, r.stderr), (6, "", "not ready\n"))
            self.assertEqual(host(fh, "config", "get", "NAME").stdout, "a b\nc\n")
            fh.configure({"up": {"exit": 0}})
            self.assertEqual(host(fh, "up").returncode, 0)

    def test_unknown_command_exits_with_the_documented_code(self):
        self.assertEqual(UNKNOWN_COMMAND_EXIT, 64)
        with FakeHostHelper() as fh:
            r = host(fh, "frobnicate")
            self.assertEqual((r.returncode, r.stdout, r.stderr), (64, "", ""))
            self.assertEqual(fh.calls(), [["frobnicate"]])
        with FakeHostHelper(commands={"*": {"exit": 2}}) as fh:
            self.assertEqual(host(fh, "frobnicate").returncode, 2)

    def test_configured_version_entry_overrides_the_option(self):
        with FakeHostHelper(version="2.0.0", commands={"version": {"stdout": "9.9.9\n", "exit": 1}}) as fh:
            r = host(fh, "version")
            self.assertEqual((r.returncode, r.stdout), (1, "9.9.9\n"))

    def test_cleanup(self):
        with FakeHostHelper() as fh:
            d = fh.dir
        self.assertFalse(os.path.exists(d))


# PROTOTYPE of the function logic (design 3.6, D33), NOT product code. It is a tiny sh stand-in that proves the pair
# FakeHostHelper + FakePodman can express the bootstrap condition. The real function (Phase 2, generated by `init`) and
# its function tests (bash, zsh, fish; Phase 3) replace it. POSIX sh, as the sketch in 3.6.
STUB = r'''
host="$1"; version="$2"; image="img:$2"; hv=""
[ -x "$host" ] && hv=$("$host" version 2>/dev/null)
if [ ! -x "$host" ] || { [ "$hv" != "$version" ] && [ "$(printf '%s\n%s\n' "$hv" "$version" | sort -V | head -n 1)" = "$hv" ]; }; then
  podman run --rm "$image" host-helper
elif [ "$hv" != "$version" ]; then
  echo "skew: $hv newer than $version" >&2
fi
'''


class BootstrapConditionPrototype(unittest.TestCase):
    def check(self, version, marker, expect_run, **kw):
        with FakePodman() as fp, FakeHostHelper(version=version, **kw) as fh:
            r = subprocess.run(["sh", "-c", STUB, "stub", fh.path, marker], env=fp.env(),
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            want = [["run", "--rm", "img:" + marker, "host-helper"]] if expect_run else []
            self.assertEqual(fp.calls(), want)
            return r

    def test_missing_helper_is_extracted(self):
        self.check("2.0.0", "2.0.0", True, present=False)

    def test_non_executable_helper_is_extracted(self):
        self.check("2.0.0", "2.0.0", True, executable=False)

    def test_helper_printing_no_version_is_extracted(self):
        self.check(None, "2.0.0", True)

    def test_old_helper_is_extracted(self):
        self.check("1.9.0", "2.0.0", True)

    def test_current_helper_is_kept_silently(self):
        r = self.check("2.0.0", "2.0.0", False)
        self.assertEqual((r.stdout, r.stderr), ("", ""))

    def test_sort_v_order_not_text_order(self):
        # 2.0.10 against a marker of 2.0.9: newer (kept, with the notice). A text order would call it older.
        r = self.check("2.0.10", "2.0.9", False)
        self.assertIn("newer", r.stderr)
        # and the other way round: 2.0.9 against 2.0.10 is older, so it is extracted
        self.check("2.0.9", "2.0.10", True)


if __name__ == "__main__":
    unittest.main()
