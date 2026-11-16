"""The fake world of the tests of the host script (container/host/swarmbox-host), shared by tests/fast/test_host_*.py,
test_swarmbox_command.py, test_security_review.py and the addon tests that look at `create-flags`.

CreateFlagsBase runs the script as a real program (copied with a fixture `addon-ports` into a mktemp folder: the repository has none, the
image build writes it) with a cleared environment: PATH, a mktemp HOME and the variables a case sets; it calls no Podman. Nothing touches
the real home or a Windows drive: the WSL probe and the OS are test-overridable (SWARMBOX_TEST_PROC_VERSION, SWARMBOX_TEST_OS), the local
time file is SWARMBOX_LOCALTIME_FILE.

UpBase runs it against the shared FakePodman (tests/support/helpers.py), which records every call and answers from a script. Tests-only
switches of the script used here (all start with SWARMBOX_TEST_): TUN (the file that stands for /dev/net/tun), NAP (the pause of the wait
loops, seconds), READY_TRIES, LOCK_TRIES, LOCK_PIDWAIT (the counts of those loops) and CREATE_FLAGS (a program that stands for
`swarmbox-host create-flags`, so a test can make it slow or make it fail).
"""
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import ROOT, FakePodman, DEFAULT_NAME, DEFAULT_IMAGE_REPO  # noqa: E402

HELPER_SRC = os.path.join(ROOT, "container", "host", "swarmbox-host")
VERSION_SRC = os.path.join(ROOT, "container", "host", "VERSION")
DEFAULTS_SRC = os.path.join(ROOT, "container", "host", "DEFAULTS")
FIXTURES = os.path.join(ROOT, "tests", "support", "fixtures")
with open(VERSION_SRC) as _f:
    VERSION = _f.read().strip()
CANARY = "CANARY-VALUE-do-not-print-7f3a"
TOKEN = "eyJhbGciOiJIUzI1NiJ9.canarytoken-0123456789"
WSL_VERSION = "Linux version 5.15.153.1-microsoft-standard-WSL2 (root@x) (gcc 11.2.0) #1 SMP"
PLAIN_VERSION = "Linux version 6.1.0-18-amd64 (debian-kernel@lists.debian.org) (gcc-12 (Debian 12.2.0-14)) #1 SMP"
WINDOWS_DRIVE_MSG = ("swarmbox: workspace %s is on a Windows drive; WSL2 is supported only with the workspace on the Linux "
       "filesystem (for example ~/swarmbox).")


def sha256(text):
    return hashlib.sha256(text.encode()).hexdigest()


def env_hash(pairs):
    """pairs: list of (name, value or None). NAME=value for a set name, NAME for an unset one, sorted."""
    lines = sorted(n if v is None else "%s=%s" % (n, v) for n, v in pairs)
    return sha256("".join(l + "\n" for l in lines))


def fingerprint(lines, ehash):
    all_lines = sorted(list(lines) + ["env-hash=" + ehash])
    return sha256("".join(l + "\n" for l in all_lines))


def pairs_of(args):
    """The flag/value pairs of an argument list: [(flag, value)] for flags that take a value on the next line."""
    out = []
    i = 0
    takes = {"-p", "-v", "-e", "--hostname", "--tmpfs", "--device", "--security-opt", "--label", "--add-host"}
    while i < len(args):
        if args[i] in takes:
            out.append((args[i], args[i + 1]))
            i += 2
        else:
            out.append((args[i], None))
            i += 1
    return out


def values(args, flag):
    return [v for f, v in pairs_of(args) if f == flag]


class CreateFlagsBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.real_home = os.path.realpath(os.path.expanduser("~"))

    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="swarmbox-test-cflags."))
        self.addCleanup(self._cleanup)
        self.home = os.path.join(self.tmp, "home")
        os.mkdir(self.home)
        self.assertNotEqual(os.path.realpath(self.home), self.real_home)
        self.ws = os.path.join(self.tmp, "ws")
        self.hdir = os.path.join(self.tmp, "helper")
        self.localtime = os.path.join(self.tmp, "localtime")
        self.procversion = os.path.join(self.tmp, "proc-version")
        for p in (self.localtime,):
            open(p, "w").close()
        with open(self.procversion, "w") as f:
            f.write(PLAIN_VERSION + "\n")
        self.make_helper("")
        self.cfgroot = os.path.join(self.home, ".config", "swarmbox")

    def _cleanup(self):
        for d, dirs, _files in os.walk(self.tmp):
            for n in dirs:
                try:
                    os.chmod(os.path.join(d, n), 0o700)
                except OSError:
                    pass
        shutil.rmtree(self.tmp, True)

    def make_helper(self, addon_ports, version=True):
        shutil.rmtree(self.hdir, True)
        os.makedirs(self.hdir)
        shutil.copy(HELPER_SRC, os.path.join(self.hdir, "swarmbox-host"))
        os.chmod(os.path.join(self.hdir, "swarmbox-host"), 0o755)
        if version:
            shutil.copy(VERSION_SRC, os.path.join(self.hdir, "VERSION"))
            shutil.copy(DEFAULTS_SRC, os.path.join(self.hdir, "DEFAULTS"))
        if addon_ports is not None:
            with open(os.path.join(self.hdir, "addon-ports"), "w") as f:
                f.write(addon_ports)

    @property
    def helper(self):
        return os.path.join(self.hdir, "swarmbox-host")

    def base_env(self):
        return {
            "PATH": os.environ["PATH"], "HOME": self.home,
            "SWARMBOX_WORKSPACE": self.ws, "SWARMBOX_INIT": "0",
            "SWARMBOX_LOCALTIME_FILE": self.localtime, "SWARMBOX_TEST_PROC_VERSION": self.procversion,
            "SWARMBOX_TEST_OS": "Linux",
        }

    def run_h(self, *args, env=None, drop=(), cfg=None, path=None, shell=None, cwd=None):
        e = self.base_env()
        e.update(env or {})
        for k in drop:
            e.pop(k, None)
        if path is not None:
            e["PATH"] = path
        if cfg is not None:
            name = (env or {}).get("SWARMBOX_NAME", DEFAULT_NAME)
            folder = self.cfgroot if name == DEFAULT_NAME else os.path.join(self.cfgroot, name)
            os.makedirs(folder, exist_ok=True)
            f = os.path.join(folder, "config")
            with open(f, "w") as fh:
                fh.write(cfg)
            os.chmod(f, 0o600)
        argv = (shell or []) + [self.helper, *args]
        return subprocess.run(argv, env=e, capture_output=True, text=True, input="", cwd=cwd or self.tmp, timeout=60)

    def cf(self, env=None, cfg=None, args=(), **kw):
        return self.run_h("create-flags", *args, env=env, cfg=cfg, **kw)

    def flags(self, env=None, cfg=None, args=(), **kw):
        p = self.cf(env=env, cfg=cfg, args=args, **kw)
        self.assertEqual(p.returncode, 0, p.stderr)
        return p.stdout.split("\n")[:-1] if p.stdout else []

    def fp(self, env=None, cfg=None, args=(), **kw):
        p = self.run_h("fingerprint", *args, env=env, cfg=cfg, **kw)
        self.assertEqual(p.returncode, 0, p.stderr)
        return p.stdout.strip()

    # the expected fingerprint lines of the default configuration; `over` replaces some of them
    def fp_lines(self, over=None):
        d = {
            "AGENT": "", "BROWSER_URL": "", "ENV_KEYS": "", "HOSTNAME": DEFAULT_NAME, "HOST_ACCESS": "0",
            "IMAGE": (DEFAULT_IMAGE_REPO + ":%s") % VERSION, "INIT": "0", "NAME": DEFAULT_NAME, "PORTS": "",
            "TZ": "local", "WEB": "1", "WEB_PORT": "7681", "WITH": "", "WORKSPACE": self.ws, "YOLO": "1",
        }
        d.update(over or {})
        return ["%s=%s" % kv for kv in d.items()]


NAME = DEFAULT_NAME
IMAGE = (DEFAULT_IMAGE_REPO + ":%s") % VERSION
BUSY = ("Error: rootlessport listen tcp 127.0.0.1:7681: bind: address already in use")
NOSUCH = {"exit": 125, "stderr": "Error: inspecting object: no such container swarmbox\n"}
HELPER_PROGRAMS = ["sh", "dash", "bash", "cat", "rm", "mkdir", "rmdir", "sleep", "kill", "sort", "tail", "head", "grep", "sed",
                "tr", "uname", "date", "find", "stat", "mv", "chmod", "printf", "cut", "readlink", "env", "id", "test",
                "sha256sum", "wc", "basename", "dirname", "mktemp", "touch", "ls", "true", "false", "expr", "awk"]


def line(state="running", name=NAME, image_id="sha256:aaa", init="false", managed="2", image=IMAGE, ports="",
         env_hash="", fp="", ws=""):
    """What `podman container inspect --format` prints for the box (the helper's format, in this order)."""
    return "|".join([state, name, image_id, init, managed, image, ports, env_hash, fp, ws]) + "\n"


class UpBase(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="swarmbox-test-up."))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.home = os.path.join(self.tmp, "home")
        os.mkdir(self.home)
        self.ws = os.path.join(self.tmp, "ws")
        os.mkdir(self.ws)
        self.state = os.path.join(self.home, ".local", "state", "swarmbox")
        self.hdir = os.path.join(self.tmp, "helper")
        os.makedirs(self.hdir)
        shutil.copy(HELPER_SRC, os.path.join(self.hdir, "swarmbox-host"))
        os.chmod(os.path.join(self.hdir, "swarmbox-host"), 0o755)
        shutil.copy(VERSION_SRC, os.path.join(self.hdir, "VERSION"))
        shutil.copy(os.path.join(ROOT, "container", "host", "DEFAULTS"), os.path.join(self.hdir, "DEFAULTS"))
        with open(os.path.join(self.hdir, "addon-ports"), "w") as f:
            f.write("")
        for n, c in (("localtime", ""), ("tun", ""), ("proc-version", "Linux version 6.1.0 (debian)\n")):
            with open(os.path.join(self.tmp, n), "w") as f:
                f.write(c)
        self.helper = os.path.join(self.hdir, "swarmbox-host")
        self.fp = None

    def podman(self, **over):
        """A FakePodman with a default script for a box that does not exist; `over` replaces entries."""
        conf = self.conf(**over)
        self.fp = FakePodman(conf)
        self.fp.__enter__()
        self.addCleanup(self.fp.__exit__)
        return self.fp

    def conf(self, lookup=None, state="running\n", mounts="", **over):
        lookup = NOSUCH if lookup is None else lookup
        c = {
            "container": {"rules": [
                {"match": ["inspect", ".Mounts"], "stdout": mounts},
                {"match": ["inspect", "swarmbox.fingerprint"], **lookup},
                {"match": ["inspect", "State.Status"], "stdout": state},
            ]},
            "image": {"rules": [{"match": ["exists"]}, {"match": ["inspect"], "stdout": "sha256:aaa\n"}]},
            "version": {"stdout": "4.3.1\n"},
            "exec": {"stdout": "ok\n"},
        }
        c.update(over)
        return c

    def env(self, **extra):
        e = self.fp.env() if self.fp else dict(os.environ)
        for k in list(e):
            if k.startswith("SWARMBOX_"):
                del e[k]
        e.update({
            "HOME": self.home, "SWARMBOX_WORKSPACE": self.ws, "SWARMBOX_INIT": "0",
            "SWARMBOX_LOCALTIME_FILE": os.path.join(self.tmp, "localtime"),
            "SWARMBOX_TEST_PROC_VERSION": os.path.join(self.tmp, "proc-version"),
            "SWARMBOX_TEST_OS": "Linux", "SWARMBOX_TEST_TUN": os.path.join(self.tmp, "tun"),
            "SWARMBOX_TEST_NAP": "0.02", "SWARMBOX_TEST_READY_TRIES": "40",
            "SWARMBOX_TEST_LOCK_TRIES": "100", "SWARMBOX_TEST_LOCK_PIDWAIT": "10",
        })
        for k in ("XDG_STATE_HOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME"):
            e.pop(k, None)
        e.update(extra)
        return e

    def run_h(self, *args, env=None, timeout=60):
        return subprocess.run([self.helper, *args], env=env if env is not None else self.env(), capture_output=True,
                              text=True, input="", cwd=self.tmp, timeout=timeout)

    def up(self, **extra):
        return self.run_h("up", env=self.env(**extra))

    def calls(self):
        return self.fp.calls()

    def subs(self, name):
        """The recorded calls of one podman subcommand (the first word)."""
        return [c for c in self.calls() if c and c[0] == name]

    def lookups(self):
        return [c for c in self.calls() if c[:2] == ["container", "inspect"] and any("swarmbox.fingerprint" in a for a in c)]

    def creation_flags(self, env_extra=None):
        """The real create-flags output for the default configuration: labels in it make a box that matches the config."""
        p = subprocess.run([self.helper, "create-flags"], env=self.env(**(env_extra or {})), capture_output=True, text=True,
                           input="", cwd=self.tmp)
        self.assertEqual(p.returncode, 0, p.stderr)
        return p.stdout.split("\n")[:-1]

    def matching_line(self, env_extra=None, **kw):
        """A lookup line whose labels equal what the helper would create now (so no warning is due)."""
        flags = self.creation_flags(env_extra)
        labels = {}
        for i, a in enumerate(flags):
            if a == "--label":
                k, v = flags[i + 1].split("=", 1)
                labels[k] = v
        d = dict(ports=labels["swarmbox.ports"], env_hash=labels["swarmbox.env-hash"], fp=labels["swarmbox.fingerprint"],
                 ws=labels["swarmbox.workspace"], image=labels["swarmbox.image"])
        d.update(kw)
        return line(**d)

    def assert_no_run(self):
        self.assertEqual([c for c in self.subs("run") if "--rm" not in c], [])

    def real_runs(self):
        return [c for c in self.subs("run") if "--rm" not in c]
