"""The host Podman connection step against the real `podman system connection` (list, add, remove: none contacts a service) in an
isolated config: a mktemp HOME, XDG_CONFIG_HOME and CONTAINERS_CONF. The foreign connection added by the test must survive a
re-registration. The same step against a fake podman, with the boundaries of the socket path, is tests/fast/test_host_socket.py.

Needs a real `podman` (the test image has none: CI does). A module guard compares the real ~/.config/containers, ~/.local/state/swarmbox
and the real connection list before and after the run.
Run: python3 tests/slow/test_host_socket_real.py
"""
import hashlib
import os
import shutil
import subprocess
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "fast"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "support"))
from test_host_socket import Base, NAME, SUFFIX  # noqa: E402

REAL_HOME = os.path.expanduser("~")
REAL_WATCH = [os.path.join(REAL_HOME, ".config", "containers"), os.path.join(REAL_HOME, ".local", "state", "swarmbox")]
BEFORE = {}


def snapshot(path):
    """(relative path, size, mtime_ns, sha256) of every entry under path, or None when it does not exist."""
    if not os.path.lexists(path):
        return None
    out = []
    for dp, dns, fns in os.walk(path):
        for n in sorted(dns + fns):
            p = os.path.join(dp, n)
            st = os.lstat(p)
            h = ""
            if os.path.isfile(p) and not os.path.islink(p):
                with open(p, "rb") as f:
                    h = hashlib.sha256(f.read()).hexdigest()
            out.append((os.path.relpath(p, path), st.st_size, st.st_mtime_ns, h))
    return sorted(out)


def real_connections():
    r = subprocess.run(["podman", "system", "connection", "ls"], capture_output=True, text=True, timeout=60)
    return (r.returncode, r.stdout)


def setUpModule():
    if not shutil.which("podman"):
        raise unittest.SkipTest("needs podman")
    for p in REAL_WATCH:
        BEFORE[p] = snapshot(p)
    BEFORE["conns"] = real_connections()


def tearDownModule():
    if not BEFORE:
        return
    for p in REAL_WATCH:
        if snapshot(p) != BEFORE[p]:
            raise AssertionError("the test run changed %s" % p)
    if real_connections() != BEFORE["conns"]:
        raise AssertionError("the real `podman system connection ls` changed during the test run")


class RealPodmanIsolationTest(Base):
    """The real `podman system connection` (list, add, remove: none contacts a service) in an isolated config: a mktemp HOME,
    XDG_CONFIG_HOME and CONTAINERS_CONF. The foreign connection added by the test must survive a re-registration."""

    def reall(self, *args):
        e = self.env()
        e["PATH"] = os.environ["PATH"]
        return subprocess.run(["podman", *args], env=e, capture_output=True, text=True, timeout=60)

    def run_real(self, **extra):
        e = self.env(**extra)
        e["PATH"] = os.environ["PATH"]   # the real podman, not the fake
        return subprocess.run([self.helper, "connection"], env=e, capture_output=True, text=True, input="", cwd=self.tmp,
                              timeout=60)

    def test_register_replace_and_keep_the_foreign_connection(self):
        self.mkws(os.path.join(self.tmp, "ws"))
        a = self.reall("system", "connection", "add", "swarmbox-test-foreign", "unix:///tmp/swarmbox-test-foreign.sock")
        self.assertEqual(a.returncode, 0, a.stderr)
        old = self.reall("system", "connection", "add", NAME, "unix://" + self.ws + "/.swarmbox/podman.sock")
        self.assertEqual(old.returncode, 0, old.stderr)
        r = self.run_real()
        self.assertEqual(r.returncode, 0, r.stderr)
        r2 = self.run_real()
        self.assertEqual(r2.returncode, 0, r2.stderr)
        ls = self.reall("system", "connection", "list", "--format", "{{.Name}} {{.URI}}").stdout.splitlines()
        self.assertEqual(sorted(ls), sorted(["swarmbox-test-foreign unix:///tmp/swarmbox-test-foreign.sock",
                                             "%s unix://%s%s" % (NAME, self.ws, SUFFIX)]))
        # the isolated config holds the registrations: in containers.conf (Podman 4.x) or in podman-connections.json (5.x); the
        # guard in tearDownModule is what proves the real files were not the ones written
        found = ""
        for base, _, files in os.walk(self.tmp):
            for f in files:
                if f in ("containers.conf", "podman-connections.json"):
                    with open(os.path.join(base, f)) as fh:
                        found += fh.read()
        self.assertIn(NAME, found)


if __name__ == "__main__":
    unittest.main()
