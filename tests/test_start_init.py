#!/usr/bin/env python3
"""Tests for the `--init` handling in start.sh (so exited processes get reaped in the container).

Run:  python3 tests/test_start_init.py

start.sh runs against a fake `podman` that records its calls. A throwaway `podman run --rm --init IMAGE true`
tells whether this podman can run an init; STUB_INIT_FAILS makes every run that carries --init fail.
"""
import os
import socket
import stat
import subprocess
import tempfile
import unittest

from helpers import ROOT

START = os.path.join(ROOT, "start.sh")
STUB = """#!/bin/sh
echo "$*" >> "$STUB_LOG"
case "$1" in
  images) echo img1 ;;
  ps) [ -n "$STUB_EXISTS" ] && echo cid1 ;;
  run)
    case "$*" in *--init*) [ -n "$STUB_INIT_FAILS" ] && exit 125 ;; esac
    echo cid ;;
esac
exit 0
"""


class StartInit(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.mkdtemp()
        self.bin = tempfile.mkdtemp()
        self.log = os.path.join(self.work, "calls.log")
        stub = os.path.join(self.bin, "podman")
        with open(stub, "w") as f:
            f.write(STUB)
        os.chmod(stub, os.stat(stub).st_mode | stat.S_IXUSR)
        # a socket file where start.sh looks for the nested podman API, so it does not wait for it
        os.makedirs(os.path.join(self.work, ".work", ".swarmbox"))
        sock = socket.socket(socket.AF_UNIX)
        cwd = os.getcwd()
        os.chdir(os.path.join(self.work, ".work", ".swarmbox"))
        try:
            sock.bind("podman.sock")
        finally:
            os.chdir(cwd)
        self.addCleanup(sock.close)

    def start(self, *args, init=None, init_fails=False, existing=False):
        env = {"PATH": self.bin + os.pathsep + os.environ["PATH"], "HOME": self.work, "STUB_LOG": self.log}
        if init is not None:
            env["SWARMBOX_INIT"] = init
        if init_fails:
            env["STUB_INIT_FAILS"] = "1"
        if existing:
            env["STUB_EXISTS"] = "1"
        r = subprocess.run(["bash", START, "--no-shell"] + list(args), cwd=self.work, env=env,
                           capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(self.log) as f:
            calls = f.read().splitlines()
        return r.stdout + r.stderr, calls

    @staticmethod
    def creation(calls):
        return [c for c in calls if c.startswith("run ") and "--name swarmbox " in c]

    @staticmethod
    def probes(calls):
        return [c for c in calls if c.startswith("run --rm --init ")]

    def test_by_default_init_is_used_when_podman_can_run_it(self):
        _, calls = self.start()
        self.assertEqual(len(self.probes(calls)), 1)
        self.assertEqual(len(self.creation(calls)), 1)
        self.assertIn("--init", self.creation(calls)[0])

    def test_when_podman_cannot_run_init_the_container_is_still_created_without_it(self):
        out, calls = self.start(init_fails=True)
        self.assertEqual(len(self.creation(calls)), 1)
        self.assertNotIn("--init", self.creation(calls)[0])
        self.assertIn("podman cannot run --init here", out)

    def test_init_can_be_forced_without_probing(self):
        _, calls = self.start(init="1", init_fails=True)  # forced: no probe, so a failing probe is not noticed
        self.assertEqual(self.probes(calls), [])
        self.assertIn("--init", self.creation(calls)[0])

    def test_init_can_be_turned_off_without_probing(self):
        for value in ("0", "false", "no"):
            os.remove(self.log) if os.path.exists(self.log) else None
            _, calls = self.start(init=value)
            self.assertEqual(self.probes(calls), [], value)
            self.assertNotIn("--init", self.creation(calls)[0], value)

    def test_reset_also_creates_the_container_with_init(self):
        _, calls = self.start("--reset", existing=True)
        self.assertEqual(len(self.creation(calls)), 1)
        self.assertIn("--init", self.creation(calls)[0])

    def test_reattaching_to_an_existing_container_does_not_probe_or_create(self):
        _, calls = self.start(existing=True)
        self.assertEqual(self.probes(calls), [])
        self.assertEqual(self.creation(calls), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
