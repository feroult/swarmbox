"""Slice 3.4: the host Podman connection (`podman -c <name>`) and the short-symlink fallback of the host helper
(design 3.5 socket paragraph, 3.7.2 `up` step 6, 3.8 short-path row, 12.1, 12.4, 8.3, B5, B12).

The step is tested through `swarmbox-host connection` (the step on its own) and through `up` with the shared FakePodman. The
connection list is kept by a small stateful fake `podman` (below) that only knows `system connection list|add|remove`, records
every call and keeps its connections in a JSON file, so "registered twice does not duplicate" and "a foreign connection survives"
are observable. HOME, XDG_*, CONTAINERS_CONF and the workspace are mktemp folders; the isolation guard compares snapshots of the
real ~/.config/containers, ~/.local/state/swarmbox and the real `podman system connection ls` around the whole run.
Reduced checks (tagged in their docstrings): the stand-in unix-socket server in a throwaway container stands for the nested Podman
service; nothing here runs a real nested Podman service and nothing runs on macOS or arm64.
Run: python3 tests/test_host_socket.py
"""
import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import ROOT, FakePodman  # noqa: E402

HELPER_SRC = os.path.join(ROOT, "container", "host", "swarmbox-host")
VERSION_SRC = os.path.join(ROOT, "container", "host", "VERSION")
DEFAULTS_SRC = os.path.join(ROOT, "container", "host", "DEFAULTS")
NAME = "swarmbox-test-3-4"
SUFFIX = "/.local/state/swarmbox/podman.sock"
LIMIT = 100
MSG = ("swarmbox: cannot make a short path to the Podman socket (workspace %s is too deep). "
       "Choose a shorter workspace path with `swarmbox config set WORKSPACE`.")

_FAKE = r'''#!%(python)s
import json, os, sys
d = os.path.dirname(os.path.abspath(__file__))
argv = sys.argv[1:]
fd = os.open(os.path.join(d, "calls.jsonl"), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
os.write(fd, (json.dumps(argv) + "\n").encode())
os.close(fd)
sf = os.path.join(d, "conns.json")
conns = json.load(open(sf)) if os.path.exists(sf) else {}
if argv[:3] == ["system", "connection", "list"]:
    if os.path.exists(os.path.join(d, "fail-list")):
        sys.exit(125)
    for n, u in conns.items():
        print(n, u)
elif argv[:3] == ["system", "connection", "add"]:
    if os.path.exists(os.path.join(d, "fail-add")):
        sys.stderr.write("Error: cannot add\n")
        sys.exit(125)
    if argv[3] in conns:
        sys.stderr.write("Error: connection already exists\n")
        sys.exit(125)
    conns[argv[3]] = argv[4]
    json.dump(conns, open(sf, "w"))
elif argv[:3] == ["system", "connection", "remove"]:
    conns.pop(argv[3], None)
    json.dump(conns, open(sf, "w"))
else:
    sys.stderr.write("unexpected call %%r\n" %% (argv,))
    sys.exit(99)
'''


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


REAL_HOME = os.path.expanduser("~")
REAL_WATCH = [os.path.join(REAL_HOME, ".config", "containers"), os.path.join(REAL_HOME, ".local", "state", "swarmbox")]
BEFORE = {}


def setUpModule():
    for p in REAL_WATCH:
        BEFORE[p] = snapshot(p)
    BEFORE["conns"] = real_connections() if shutil.which("podman") else None


def pad_ws(base, nbytes_total):
    """A workspace path under base whose byte length is exactly nbytes_total (ASCII filler in one last component)."""
    need = nbytes_total - len(base.encode())
    assert need >= 2, need
    return base + "/" + "w" * (need - 1)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="swarmbox-test-sock."))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.home = os.path.join(self.tmp, "home")
        os.makedirs(self.home)
        self.state = os.path.join(self.home, ".local", "state", "swarmbox")
        hdir = os.path.join(self.tmp, "helper")
        os.makedirs(hdir)
        shutil.copy(HELPER_SRC, hdir)
        shutil.copy(VERSION_SRC, hdir)
        shutil.copy(DEFAULTS_SRC, hdir)
        open(os.path.join(hdir, "tool-ports"), "w").close()
        os.chmod(os.path.join(hdir, "swarmbox-host"), 0o755)
        self.helper = os.path.join(hdir, "swarmbox-host")
        self.fake = os.path.join(self.tmp, "fakebin")
        os.makedirs(self.fake)
        with open(os.path.join(self.fake, "podman"), "w") as f:
            f.write(_FAKE % {"python": sys.executable})
        os.chmod(os.path.join(self.fake, "podman"), 0o755)
        self.ws = os.path.join(self.tmp, "ws")
        open(os.path.join(self.tmp, "containers.conf"), "w").close()   # Podman wants the file named by CONTAINERS_CONF to exist

    def mkws(self, path):
        os.makedirs(os.path.join(path, ".local", "state", "swarmbox"), exist_ok=True)
        self.ws = path
        return path

    def env(self, **extra):
        e = {k: v for k, v in os.environ.items() if not k.startswith(("SWARMBOX_", "XDG_"))}
        e["PATH"] = self.fake + os.pathsep + e["PATH"]
        e.update({"HOME": self.home, "SWARMBOX_NAME": NAME, "SWARMBOX_WORKSPACE": self.ws, "SWARMBOX_TEST_OS": "Linux",
                  "CONTAINERS_CONF": os.path.join(self.tmp, "containers.conf"),
                  "XDG_CONFIG_HOME": os.path.join(self.tmp, "xdgconf")})
        e.update(extra)
        return e

    def connect(self, **extra):
        return subprocess.run([self.helper, "connection"], env=self.env(**extra), capture_output=True, text=True, input="",
                              cwd=self.tmp, timeout=60)

    def calls(self):
        p = os.path.join(self.fake, "calls.jsonl")
        if not os.path.exists(p):
            return []
        with open(p) as f:
            return [json.loads(x) for x in f if x.strip()]

    def verbs(self, verb):
        return [c for c in self.calls() if c[:3] == ["system", "connection", verb]]

    def conns(self):
        p = os.path.join(self.fake, "conns.json")
        if not os.path.exists(p):
            return {}
        with open(p) as f:
            return json.load(f)

    def seed(self, conns):
        with open(os.path.join(self.fake, "conns.json"), "w") as f:
            json.dump(conns, f)

    def link(self):
        return os.path.join(self.state, NAME + ".sock-dir")


class BoundaryTest(Base):
    def test_exactly_100_characters_is_registered_directly_with_no_symlink(self):
        ws = self.mkws(pad_ws(self.tmp, LIMIT - len(SUFFIX)))
        self.assertEqual(len((ws + SUFFIX).encode()), 100)
        r = self.connect()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.conns(), {NAME: "unix://" + ws + SUFFIX})
        self.assertEqual(r.stdout, "unix://" + ws + SUFFIX + "\n")
        self.assertFalse(os.path.lexists(self.link()))

    def test_101_characters_gets_the_symlink_and_registers_the_link_path(self):
        ws = self.mkws(pad_ws(self.tmp, LIMIT - len(SUFFIX) + 1))
        self.assertEqual(len((ws + SUFFIX).encode()), 101)
        r = self.connect()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(os.path.islink(self.link()))
        self.assertEqual(os.readlink(self.link()), ws + "/.local/state/swarmbox")
        self.assertEqual(self.conns(), {NAME: "unix://" + self.link() + "/podman.sock"})
        self.assertLessEqual(len((self.link() + "/podman.sock").encode()), LIMIT)

    def test_a_workspace_too_deep_for_the_symlink_too_exits_4_and_registers_nothing(self):
        ws = self.mkws(pad_ws(self.tmp, 140))
        long_name = NAME + "-" + "n" * 60
        r = self.connect(SWARMBOX_NAME=long_name)
        link_path = os.path.join(self.state, long_name + ".sock-dir", "podman.sock")
        self.assertGreater(len(link_path), LIMIT, "the test needs a link path over the limit")
        self.assertEqual(r.returncode, 4, r.stderr)
        self.assertEqual(r.stderr, MSG % ws + "\n")
        self.assertEqual(r.stdout, "")
        self.assertEqual(self.verbs("add"), [])
        self.assertFalse(os.path.lexists(os.path.join(self.state, long_name + ".sock-dir")))

class SymlinkRefreshTest(Base):
    def setUp(self):
        super().setUp()
        self.mkws(pad_ws(self.tmp, 120))
        os.makedirs(self.state)

    def test_a_correct_link_is_kept(self):
        os.symlink(self.ws + "/.local/state/swarmbox", self.link())
        ino = os.lstat(self.link()).st_ino
        r = self.connect()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(os.lstat(self.link()).st_ino, ino)
        self.assertEqual(os.readlink(self.link()), self.ws + "/.local/state/swarmbox")

class RegistrationTest(Base):
    def setUp(self):
        super().setUp()
        self.mkws(os.path.join(self.tmp, "ws"))
        self.uri = "unix://" + self.ws + SUFFIX

    def test_a_changed_address_replaces_it(self):
        old = "unix://" + self.ws + "/.swarmbox/podman.sock"
        self.seed({NAME: old})
        r = self.connect()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.conns(), {NAME: self.uri})
        self.assertEqual(self.verbs("remove"), [["system", "connection", "remove", NAME]])
        self.assertEqual(self.verbs("add"), [["system", "connection", "add", NAME, self.uri]])

class UpIntegrationTest(unittest.TestCase):
    """`up` and `reset` take step 6 with the shared FakePodman: it is the last thing before they return (and after readiness),
    and the fast path costs one `system connection list` more (design 3.7.2 step 4, B35)."""

    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="swarmbox-test-sockup."))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.home = os.path.join(self.tmp, "home")
        self.ws = pad_ws(self.tmp, 120)
        os.makedirs(self.home)
        os.makedirs(self.ws)
        hdir = os.path.join(self.tmp, "helper")
        os.makedirs(hdir)
        shutil.copy(HELPER_SRC, hdir)
        shutil.copy(VERSION_SRC, hdir)
        shutil.copy(DEFAULTS_SRC, hdir)
        open(os.path.join(hdir, "tool-ports"), "w").close()
        os.chmod(os.path.join(hdir, "swarmbox-host"), 0o755)
        self.helper = os.path.join(hdir, "swarmbox-host")
        for n, c in (("localtime", ""), ("tun", ""), ("proc-version", "Linux version 6.1.0 (debian)\n")):
            with open(os.path.join(self.tmp, n), "w") as f:
                f.write(c)

    def run_up(self, fp, verb="up", **extra):
        e = fp.env()
        for k in list(e):
            if k.startswith(("SWARMBOX_", "XDG_")):
                del e[k]
        e.update({"HOME": self.home, "SWARMBOX_WORKSPACE": self.ws, "SWARMBOX_INIT": "0", "SWARMBOX_NAME": "swarmbox",
                  "SWARMBOX_LOCALTIME_FILE": os.path.join(self.tmp, "localtime"),
                  "SWARMBOX_TEST_PROC_VERSION": os.path.join(self.tmp, "proc-version"), "SWARMBOX_TEST_OS": "Linux",
                  "SWARMBOX_TEST_TUN": os.path.join(self.tmp, "tun"), "SWARMBOX_TEST_NAP": "0.02",
                  "SWARMBOX_TEST_READY_TRIES": "40"})
        e.update(extra)
        return subprocess.run([self.helper, verb], env=e, capture_output=True, text=True, input="", cwd=self.tmp, timeout=60)

    def conf(self, lookup=None):
        return {"container": {"rules": [
            {"match": ["inspect", ".Mounts"], "stdout": ""},
            {"match": ["inspect", "swarmbox.fingerprint"], **(lookup or {"exit": 125, "stderr": "no such container swarmbox\n"})},
            {"match": ["inspect", "State.Status"], "stdout": "running\n"}]},
            "image": {"rules": [{"match": ["exists"]}, {"match": ["inspect"], "stdout": "sha256:aaa\n"}]},
            "version": {"stdout": "4.3.1\n"}, "exec": {"stdout": "ok\n"}, "run": {"cidfile": "abc\n"}, "ps": {}}

    def test_up_that_creates_registers_after_the_box_is_ready_and_makes_the_link(self):
        with FakePodman(self.conf()) as fp:
            r = self.run_up(fp)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(r.stdout, "")
            calls = fp.calls()
            kinds = [" ".join(c[:3]) for c in calls]
            self.assertIn("system connection add", kinds)
            self.assertGreater(kinds.index("system connection add"), kinds.index("container run") if "container run" in kinds
                               else max(i for i, c in enumerate(calls) if c[0] == "run"))
            add = [c for c in calls if c[:3] == ["system", "connection", "add"]][0]
            link = os.path.join(self.home, ".local", "state", "swarmbox", "swarmbox.sock-dir")
            self.assertEqual(add[3:], ["swarmbox", "unix://" + link + "/podman.sock"])
            self.assertTrue(os.path.islink(link))

    def test_the_fast_path_adds_one_connection_call_and_nothing_else(self):
        # a running box whose labels match the configuration
        with FakePodman(self.conf()) as fp:
            p = subprocess.run([self.helper, "create-flags"], capture_output=True, text=True, input="", cwd=self.tmp,
                               env=dict(fp.env(), HOME=self.home, SWARMBOX_WORKSPACE=self.ws, SWARMBOX_INIT="0",
                                        SWARMBOX_NAME="swarmbox", SWARMBOX_TEST_OS="Linux",
                                        SWARMBOX_LOCALTIME_FILE=os.path.join(self.tmp, "localtime"),
                                        SWARMBOX_TEST_PROC_VERSION=os.path.join(self.tmp, "proc-version"),
                                        SWARMBOX_TEST_TUN=os.path.join(self.tmp, "tun")))
            self.assertEqual(p.returncode, 0, p.stderr)
            flags = p.stdout.split("\n")[:-1]
            labels = {}
            for i, a in enumerate(flags):
                if a == "--label":
                    k, v = flags[i + 1].split("=", 1)
                    labels[k] = v
            line = "|".join(["running", "swarmbox", "sha256:aaa", "false", "2", labels["swarmbox.image"],
                             labels["swarmbox.ports"], labels["swarmbox.env-hash"], labels["swarmbox.fingerprint"],
                             labels["swarmbox.workspace"]]) + "\n"
            fp.configure(self.conf({"stdout": line}))
            r = self.run_up(fp)
            self.assertEqual(r.returncode, 0, r.stderr)
            calls = fp.calls()
            plain = [c for c in calls if c[:1] != ["system"]]
            sysc = [c for c in calls if c[:1] == ["system"]]
            self.assertLessEqual(len(plain), 2, calls)
            self.assertEqual(sysc[0][:3], ["system", "connection", "list"])
            self.assertLessEqual(len(sysc), 2, calls)   # the list, and the add when it is not registered yet


@unittest.skipUnless(shutil.which("podman"), "no podman")
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
        with open(os.path.join(self.tmp, "containers.conf")) as f:   # the isolated file holds the registrations
            self.assertIn(NAME, f.read())


def tearDownModule():
    # the isolation guard: the real files and the real connection list are the same as before the run
    for p in REAL_WATCH:
        if snapshot(p) != BEFORE[p]:
            raise AssertionError("the test run changed %s" % p)
    if BEFORE["conns"] is not None and real_connections() != BEFORE["conns"]:
        raise AssertionError("the real `podman system connection ls` changed during the test run")
    # and the helper source itself: it never names the real paths
    with open(HELPER_SRC) as f:
        src = f.read()
    if "~/.config/containers" in src:
        raise AssertionError("the helper must not touch ~/.config/containers itself")


if __name__ == "__main__":
    unittest.main()
