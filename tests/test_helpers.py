#!/usr/bin/env python3
"""Tests for the shared fake podman in helpers.py.  Run:  python3 tests/test_helpers.py"""
import json
import os
import shutil
import subprocess
import unittest

from helpers import ROOT, FakePodman


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


if __name__ == "__main__":
    unittest.main()
