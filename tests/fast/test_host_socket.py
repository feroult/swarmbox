"""The host Podman connection (`podman -c <name>`) and the short-symlink fallback of the host helper.

The step is tested through `swarmbox-host connection` (the step on its own) and through `up` with the shared FakePodman. The
connection list is kept by a small stateful fake `podman` (below) that only knows `system connection list|add|remove`, records
every call and keeps its connections in a JSON file, so "registered twice does not duplicate" and "a foreign connection survives"
are observable. HOME, XDG_*, CONTAINERS_CONF and the workspace are mktemp folders. The same step against the real `podman system
connection` is tests/slow/test_host_socket_real.py. Run: python3 tests/fast/test_host_socket.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "support"))
from helpers import ROOT  # noqa: E402
from host_support import UpBase, NAME as UP_NAME  # noqa: E402

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
        open(os.path.join(hdir, "addon-ports"), "w").close()
        os.chmod(os.path.join(hdir, "swarmbox-host"), 0o755)
        self.helper = os.path.join(hdir, "swarmbox-host")
        self.fake = os.path.join(self.tmp, "fakebin")
        os.makedirs(self.fake)
        with open(os.path.join(self.fake, "podman"), "w") as f:
            f.write(_FAKE % {"python": sys.executable})
        os.chmod(os.path.join(self.fake, "podman"), 0o755)
        self.ws = os.path.join(self.tmp, "ws")
        open(os.path.join(self.tmp, "containers.conf"), "w").close()   # Podman wants the file named by CONTAINERS_CONF to exist

    def need_room_for_the_link(self):
        """The link path is <home>/.local/state/swarmbox/<name>.sock-dir/podman.sock: a long temporary folder (macOS) cannot hold it."""
        if len((self.link() + "/podman.sock").encode()) > LIMIT:
            self.skipTest("the temporary folder is too long for the short link (the Linux job covers this case)")

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
        self.need_room_for_the_link()
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
        self.need_room_for_the_link()
        os.symlink(self.ws + "/.local/state/swarmbox", self.link())
        ino = os.lstat(self.link()).st_ino
        r = self.connect()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(os.lstat(self.link()).st_ino, ino)
        self.assertEqual(os.readlink(self.link()), self.ws + "/.local/state/swarmbox")

    def test_a_link_to_another_place_is_relinked(self):
        self.need_room_for_the_link()
        os.symlink(os.path.join(self.tmp, "somewhere-else"), self.link())
        r = self.connect()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(os.readlink(self.link()), self.ws + "/.local/state/swarmbox")

    def test_anything_that_is_not_a_link_in_its_place_is_refused_and_left_alone(self):
        self.need_room_for_the_link()
        os.mkdir(self.link())
        r = self.connect()
        self.assertEqual(r.returncode, 4, r.stderr)
        self.assertIn("is not a symlink", r.stderr)
        self.assertTrue(os.path.isdir(self.link()) and not os.path.islink(self.link()))
        self.assertEqual(self.verbs("add"), [])


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

class UpIntegrationTest(UpBase):
    """`up` takes step 6 with the shared FakePodman, after the box is ready, with a workspace so deep that the short link is needed.
    (That the fast path costs one `system connection list` more is in test_host_up.py.)"""

    def test_up_that_creates_registers_after_the_box_is_ready_and_makes_the_link(self):
        self.ws = pad_ws(self.tmp, 120)
        os.makedirs(self.ws)
        self.podman()
        r = self.up(SWARMBOX_WORKSPACE=self.ws)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout, "")
        calls = self.calls()
        kinds = [" ".join(c[:3]) for c in calls]
        self.assertIn("system connection add", kinds)
        self.assertGreater(kinds.index("system connection add"), max(i for i, c in enumerate(calls) if c[0] == "run"))
        add = [c for c in calls if c[:3] == ["system", "connection", "add"]][0]
        link = os.path.join(self.state, UP_NAME + ".sock-dir")
        self.assertEqual(add[3:], [UP_NAME, "unix://" + link + "/podman.sock"])
        self.assertTrue(os.path.islink(link))


class SourceTest(unittest.TestCase):
    def test_the_helper_never_names_the_real_podman_config_folder(self):
        with open(HELPER_SRC) as f:
            self.assertNotIn("~/.config/containers", f.read())


if __name__ == "__main__":
    unittest.main()
