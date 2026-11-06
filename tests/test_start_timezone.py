#!/usr/bin/env python3
"""Tests for the time zone handling in start.sh (the container would otherwise run in UTC).

Run:  python3 tests/test_start_timezone.py

start.sh runs against a fake `podman` that records its calls. By default new containers follow the machine's
zone (--tz=local); SWARMBOX_TZ chooses another zone or turns it off; SWARMBOX_LOCALTIME_FILE only lets the
tests control whether the machine "has" a /etc/localtime.
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
  run) echo cid ;;
esac
exit 0
"""


class StartTimezone(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.mkdtemp()
        self.bin = tempfile.mkdtemp()
        self.log = os.path.join(self.work, "calls.log")
        stub = os.path.join(self.bin, "podman")
        with open(stub, "w") as f:
            f.write(STUB)
        os.chmod(stub, os.stat(stub).st_mode | stat.S_IXUSR)
        self.localtime = os.path.join(self.work, "localtime")
        open(self.localtime, "w").close()
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

    def start(self, *args, tz=None, localtime=True, existing=False):
        env = {"PATH": self.bin + os.pathsep + os.environ["PATH"], "HOME": self.work, "STUB_LOG": self.log,
               "SWARMBOX_LOCALTIME_FILE": self.localtime if localtime else "/nonexistent/localtime",
               "SWARMBOX_INIT": "0"}
        if tz is not None:
            env["SWARMBOX_TZ"] = tz
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

    def tz_args(self, calls):
        self.assertEqual(len(self.creation(calls)), 1)
        return [a for a in self.creation(calls)[0].split() if a.startswith("--tz")]

    def test_by_default_the_container_follows_the_machines_time_zone(self):
        _, calls = self.start()
        self.assertEqual(self.tz_args(calls), ["--tz=local"])

    def test_without_a_localtime_file_no_flag_is_passed(self):
        _, calls = self.start(localtime=False)
        self.assertEqual(self.tz_args(calls), [])

    def test_a_zone_can_be_chosen(self):
        _, calls = self.start(tz="America/Sao_Paulo")
        self.assertEqual(self.tz_args(calls), ["--tz=America/Sao_Paulo"])
        os.remove(self.log)
        _, calls = self.start(tz="Etc/GMT+3", localtime=False)  # even without a localtime file
        self.assertIn("--tz=Etc/GMT+3", self.tz_args(calls))

    def test_it_can_be_turned_off(self):
        for value in ("off", "OFF", "none"):
            os.remove(self.log) if os.path.exists(self.log) else None
            _, calls = self.start(tz=value)
            self.assertEqual(self.tz_args(calls), [], value)

    def test_an_invalid_zone_is_ignored_and_cannot_inject_arguments(self):
        for bad in ("America/Sao Paulo --privileged", "x;rm -rf /", "$(id)", "a b"):
            os.remove(self.log) if os.path.exists(self.log) else None
            out, calls = self.start(tz=bad)
            self.assertEqual(self.tz_args(calls), [], bad)
            self.assertNotIn("--privileged", self.creation(calls)[0], bad)
            self.assertIn("is not a time zone name", out, bad)

    def test_reset_also_passes_the_time_zone(self):
        _, calls = self.start("--reset", existing=True)
        self.assertEqual(self.tz_args(calls), ["--tz=local"])

    def test_reattaching_creates_nothing(self):
        _, calls = self.start(existing=True)
        self.assertEqual(self.creation(calls), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
