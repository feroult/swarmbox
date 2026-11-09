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
        self.assertTrue(os.path.isfile(os.path.join(ROOT, "Dockerfile")))
        self.assertTrue(os.path.isfile(os.path.join(ROOT, "container", "host", "swarmbox-host")))

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


if __name__ == "__main__":
    unittest.main()
