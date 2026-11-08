"""Slice 4b.7: the real-installer tests of design 6.9 and 13.4, one table row per tool in container/tools.

Two parts.
  1. Always runs (python3, bash, find): the HARNESS itself. The scan that finds "side effects" is run against fake installers, one clean
     and several that misbehave on purpose (a dotfile in the home, a write below a fake /usr/local, an uncleaned npm cache), so the
     real test below cannot pass vacuously. Also: the table covers every tool folder, and the commands match the manifests.
  2. Real, slow, SKIPPED unless SWARMBOX_TEST_NETWORK=1, SWARMBOX_IMAGE_BUILD=1 and podman works: for each tool of TABLE, throwaway
     containers swarmbox-test-4b7-run-<rand> on a fresh named volume swarmbox-test-4b7-vol-<rand> as /home/agent (never the real
     home), from an image built by dev/dev-build.sh (SWARMBOX_IMAGE_TAG=<swarmbox-test-...> reuses one and does not remove it).
       - first call through the shim installs as uid 1000 and the tool prints its version;
       - NO SIDE EFFECTS: no file under /usr /etc /opt /var /root /home changed after a stamp, except below the tool's TOOL_PREFIX
         and SwarmBox's own state (design 6.4, 6.9); for npm tools /opt/npm-cache holds no files afterwards (the cache rule);
       - SURVIVES A RESET: the container is removed and a second one is created on the same volume: the tool runs again, installs
         nothing and the version is the same.
     SWARMBOX_REAL_TOOLS=go,poetry limits the table. A failed first call is retried once (network flakes); the retry is reported.
     claude is covered by tests/test_tool_claude_real.py (a different installer shape).
Run: SWARMBOX_TEST_NETWORK=1 SWARMBOX_IMAGE_BUILD=1 python3 tests/test_tool_real.py
"""
import os
import random
import re
import shutil
import string
import subprocess
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import ROOT  # noqa: E402

TOOLS_DIR = os.path.join(ROOT, "container", "tools")
VERSION_RE = r"\d+\.\d+\.\d+"
# name -> (command that triggers the first install and prints the version, regex of that output, npm-based installer?)
# The exact pinned version, when the manifest has one, is added to the check from tool.conf at run time.
TABLE = {
    "opencode": (["opencode", "--version"], VERSION_RE, True),
    "gemini": (["gemini", "--version"], VERSION_RE, True),
    "clasp": (["clasp", "--version"], VERSION_RE, True),
    "poetry": (["poetry", "--version"], r"(?i)poetry.*" + VERSION_RE, False),
    "go": (["go", "version"], r"go version go" + VERSION_RE + r" linux/(amd64|arm64)", False),
    "gcloud": (["gcloud", "--version"], r"Google Cloud SDK " + VERSION_RE, False),
}
COVERED_ELSEWHERE = {"claude": "tests/test_tool_claude_real.py"}
ROOTS = ["/usr", "/etc", "/opt", "/var", "/root", "/home"]
CACHE = "/opt/npm-cache"


def conf(name, key):
    with open(os.path.join(TOOLS_DIR, name, "tool.conf"), encoding="utf-8") as f:
        for line in f:
            m = re.match(r"^%s=(.*)$" % key, line.strip())
            if m:
                return m.group(1).strip('"')
    return None


# ---- the harness (part 1 tests it, part 2 uses it) ---------------------------------------------------------------------------

def scan_command(roots, stamp):
    """Shell text that lists every file or link below roots that is newer than the stamp file, one path per line, sorted."""
    return ("find %s \\( -type f -o -type l \\) -newer %s -print 2>/dev/null | sort"
            % (" ".join(roots), stamp))


def offenders(changed, allowed_prefixes):
    """The changed paths that are not below an allowed prefix (a prefix ends the path at a "/" boundary)."""
    bad = []
    for p in changed:
        if not any(p == a.rstrip("/") or p.startswith(a.rstrip("/") + "/") for a in allowed_prefixes):
            bad.append(p)
    return bad


def allowed_for(name, home="/home/agent", cache=CACHE):
    """Where an installer of a managed tool may leave files: its install folder, SwarmBox's own state and the npm cache."""
    return [home + "/.local/share/swarmbox/tools/" + name, home + "/.local/state/swarmbox", "/tmp", cache]


# What a clean cache still holds: npm's log folder and its update-notifier timestamp (an empty marker, measured in 4b.7).
CACHE_RESIDUE = ("/_logs/", "/_update-notifier-last-checked")


def cache_leftovers(files, cache=CACHE):
    """Files left in the npm cache after an install, not counting the two things that a `npm cache clean` leaves behind."""
    return [p for p in files if p.startswith(cache.rstrip("/") + "/") and not any(r in p + "/" or p.endswith(r) for r in CACHE_RESIDUE)]


class Harness(unittest.TestCase):
    """The scan against fake installers. Roots are temp folders standing for /usr, /etc, /opt, /var, /root and /home."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="real-harness-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.roots = {}
        for r in ("usr", "etc", "opt", "var", "root", "home"):
            self.roots[r] = os.path.join(self.tmp, r)
        os.makedirs(os.path.join(self.roots["home"], "agent"))
        os.makedirs(os.path.join(self.roots["usr"], "local", "bin"))
        os.makedirs(os.path.join(self.roots["opt"], "npm-cache"))
        for d in ("etc", "var", "root"):
            os.makedirs(self.roots[d])
        self.home = os.path.join(self.roots["home"], "agent")
        self.prefix = os.path.join(self.home, ".local", "share", "swarmbox", "tools", "demo", "1.0.0")
        # an old file in every root: only files NEWER than the stamp count
        for r in self.roots.values():
            p = os.path.join(r, "old.txt")
            open(p, "w").close()
            os.utime(p, (time.time() - 3600, time.time() - 3600))
        self.stamp = os.path.join(self.tmp, "stamp")
        open(self.stamp, "w").close()
        past = time.time() - 60
        os.utime(self.stamp, (past, past))

    def install(self, body, env=None):
        script = os.path.join(self.tmp, "install.sh")
        with open(script, "w") as f:
            f.write("#!/bin/bash\nset -eu\n" + body)
        e = dict(os.environ, HOME=self.home, TOOL_PREFIX=self.prefix, USR=self.roots["usr"],
                 NPM_CACHE=os.path.join(self.roots["opt"], "npm-cache"))
        e.update(env or {})
        r = subprocess.run(["bash", script], env=e, capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)

    def changed(self):
        cmd = scan_command(list(self.roots.values()), self.stamp)
        r = subprocess.run(["bash", "-c", cmd], capture_output=True, text=True, timeout=30)
        return [l for l in r.stdout.splitlines() if l]

    def bad(self):
        home_allowed = allowed_for("demo", home=self.home, cache=os.path.join(self.roots["opt"], "npm-cache"))
        home_allowed = [a for a in home_allowed if a != "/tmp"]
        return offenders(self.changed(), home_allowed)

    GOOD = 'mkdir -p "$TOOL_PREFIX/bin"; echo x > "$TOOL_PREFIX/bin/demo"; chmod +x "$TOOL_PREFIX/bin/demo"\n'

    def test_a_clean_installer_has_no_offenders(self):
        self.install(self.GOOD)
        self.assertTrue(self.changed(), "the scan saw nothing at all: it would pass vacuously")
        self.assertEqual(self.bad(), [])

    def test_the_stamp_hides_old_files(self):
        self.install(self.GOOD)
        self.assertFalse([p for p in self.changed() if p.endswith("old.txt")])

    def test_a_dotfile_in_the_home_is_found(self):
        self.install(self.GOOD + 'echo x > "$HOME/.foo"\n')
        self.assertEqual(self.bad(), [os.path.join(self.home, ".foo")])

    def test_a_write_below_usr_local_is_found(self):
        self.install(self.GOOD + 'echo x > "$USR/local/bin/demo"\n')
        self.assertEqual(self.bad(), [os.path.join(self.roots["usr"], "local", "bin", "demo")])

    def test_a_symlink_is_found_too(self):
        self.install(self.GOOD + 'ln -s "$TOOL_PREFIX/bin/demo" "$HOME/.local-demo-link"\n')
        self.assertEqual(self.bad(), [os.path.join(self.home, ".local-demo-link")])

    def test_a_write_to_another_tools_folder_is_found(self):
        self.install(self.GOOD + 'mkdir -p "$HOME/.local/share/swarmbox/tools/other"; echo x > "$HOME/.local/share/swarmbox/tools/other/f"\n')
        self.assertEqual(self.bad(), [os.path.join(self.home, ".local/share/swarmbox/tools/other/f")])

    def test_a_folder_with_the_same_prefix_is_not_the_tool_folder(self):
        self.install(self.GOOD + 'mkdir -p "$HOME/.local/share/swarmbox/tools/demo-evil"; echo x > "$HOME/.local/share/swarmbox/tools/demo-evil/f"\n')
        self.assertEqual(len(self.bad()), 1)

    def test_the_cache_is_allowed_but_left_files_are_reported(self):
        self.install(self.GOOD + 'mkdir -p "$NPM_CACHE/_cacache"; echo x > "$NPM_CACHE/_cacache/blob"; mkdir -p "$NPM_CACHE/_logs"; echo x > "$NPM_CACHE/_logs/l.log"\n')
        self.assertEqual(self.bad(), [])
        cache = os.path.join(self.roots["opt"], "npm-cache")
        left = cache_leftovers(self.changed(), cache=cache)
        self.assertEqual(left, [os.path.join(cache, "_cacache", "blob")])

    def test_a_cleaned_cache_has_no_leftovers(self):
        self.install(self.GOOD + 'mkdir -p "$NPM_CACHE/_logs"; echo x > "$NPM_CACHE/_logs/l.log"; : > "$NPM_CACHE/_update-notifier-last-checked"\n')
        cache = os.path.join(self.roots["opt"], "npm-cache")
        self.assertEqual(cache_leftovers(self.changed(), cache=cache), [])

    def test_offenders_unit(self):
        self.assertEqual(offenders(["/usr/x", "/home/agent/.local/share/swarmbox/tools/go/1/bin/go"],
                                   allowed_for("go")), ["/usr/x"])
        self.assertEqual(offenders(["/tmp/swarmbox/tools.lock"], allowed_for("go")), [])


class Table(unittest.TestCase):
    def test_the_table_covers_every_tool_folder(self):
        folders = {d for d in os.listdir(TOOLS_DIR) if os.path.isdir(os.path.join(TOOLS_DIR, d))}
        self.assertEqual(folders, set(TABLE) | set(COVERED_ELSEWHERE), "a tool without a real-installer test")

    def test_every_covered_elsewhere_test_exists(self):
        for path in COVERED_ELSEWHERE.values():
            self.assertTrue(os.path.isfile(os.path.join(ROOT, path)), path)

    def test_the_command_is_a_command_the_manifest_provides(self):
        for name, (cmd, _, _) in TABLE.items():
            self.assertIn(cmd[0], (conf(name, "PROVIDES") or "").split(), name)

    def test_npm_flag_matches_the_installer(self):
        for name, (_, _, npm) in TABLE.items():
            with open(os.path.join(TOOLS_DIR, name, "install.sh"), encoding="utf-8") as f:
                text = f.read()
            self.assertEqual("npm install" in text, npm, name)
            if npm:
                self.assertIn("npm cache clean", text, name)

    def test_the_real_tests_are_off_by_default(self):
        # a developer running the file without the switches must not download anything
        if os.environ.get("SWARMBOX_TEST_NETWORK") != "1":
            self.assertFalse(ENABLED)


# ---- part 2: real containers -------------------------------------------------------------------------------------------------

ENABLED = bool(os.environ.get("SWARMBOX_TEST_NETWORK") == "1" and os.environ.get("SWARMBOX_IMAGE_BUILD") == "1"
               and shutil.which("podman"))
TAG = None
OWN = False


def rnd():
    return "".join(random.choice(string.ascii_lowercase + string.digits) for _ in range(6))


def podman(*args, timeout=1800):
    return subprocess.run(["podman"] + list(args), capture_output=True, timeout=timeout)


def setUpModule():
    global TAG, OWN
    if not ENABLED:
        return
    TAG = os.environ.get("SWARMBOX_IMAGE_TAG")
    if TAG:
        assert TAG.startswith("swarmbox-test-"), TAG
        return
    TAG = "swarmbox-test-4b7-img-" + rnd()
    OWN = True
    r = subprocess.run(["sh", os.path.join(ROOT, "dev", "dev-build.sh"), "--tag", TAG], capture_output=True, text=True)
    sys.stderr.write(r.stdout[-1500:] + r.stderr[-1500:])
    if r.returncode != 0:
        raise AssertionError("image build failed")


def tearDownModule():
    if OWN and TAG and TAG.startswith("swarmbox-test-"):
        podman("rmi", TAG)


class Box:
    """One throwaway container on a named volume, kept alive with sleep (the entrypoint does not run). Removed by exact name."""

    def __init__(self, vol):
        self.name = "swarmbox-test-4b7-run-" + rnd()
        assert vol.startswith("swarmbox-test-4b7-vol-")
        r = podman("run", "-d", "--name", self.name, "-v", vol + ":/home/agent", "--tmpfs", "/tmp/swarmbox",
                   "--entrypoint", "sleep", TAG, "5400")
        assert r.returncode == 0, r.stderr
        self.removed = False

    def sh(self, cmd, user="agent", timeout=1800):
        return podman("exec", "--user", user, self.name, "bash", "-c", cmd, timeout=timeout)

    def remove(self):
        if self.removed:
            return
        assert self.name.startswith("swarmbox-test-4b7-run-")
        podman("rm", "-f", "-t", "0", self.name)
        self.removed = True


def out(r):
    return r.stdout.decode().strip()


def err(r):
    return r.stderr.decode()


def selected():
    only = os.environ.get("SWARMBOX_REAL_TOOLS")
    names = [n for n in TABLE]
    if only:
        names = [n for n in names if n in only.split(",")]
    return names


def make_real_class(name):
    cmd, regex, npm = TABLE[name]
    pinned = conf(name, "VERSION")
    cmd_text = " ".join(cmd)

    @unittest.skipUnless(ENABLED, "real test: needs SWARMBOX_TEST_NETWORK=1, SWARMBOX_IMAGE_BUILD=1 and podman")
    class Real(unittest.TestCase):
        @classmethod
        def setUpClass(cls):
            cls.vol = "swarmbox-test-4b7-vol-" + rnd()
            cls.boxes = []
            assert podman("volume", "create", cls.vol).returncode == 0
            cls.box = Box(cls.vol)
            cls.boxes.append(cls.box)
            cls.box.sh("touch /tmp/stamp-4b7", user="root")
            time.sleep(1.1)  # find -newer compares times: leave a gap after the stamp
            cls.home_before = out(cls.box.sh("find /home/agent -mindepth 1 | sort"))
            cls.t0 = time.time()
            # Step 1: the INSTALLER alone (swarmbox-tool install), so that what the tool itself writes when it runs (Go's telemetry
            # folder, for one) is not blamed on the installer. Retried once on failure (network flakes).
            cls.inst = cls.box.sh("swarmbox-tool install " + name)
            cls.retried = False
            if cls.inst.returncode != 0:
                cls.retried = True
                sys.stderr.write("\n[4b.7] %s: install failed (%d), retrying once: %s\n"
                                 % (name, cls.inst.returncode, err(cls.inst)[-400:]))
                cls.inst = cls.box.sh("swarmbox-tool install " + name)
            cls.seconds = time.time() - cls.t0
            cls.changed = [l for l in out(cls.box.sh(scan_command(ROOTS, "/tmp/stamp-4b7"), user="root")).splitlines() if l]
            # Step 2: the first call of the tool through the shim. Files it creates outside the prefix are the tool's own run-time
            # state (reported, not judged: they are not the installer's doing).
            cls.first = cls.box.sh(cmd_text)
            after = [l for l in out(cls.box.sh(scan_command(ROOTS, "/tmp/stamp-4b7"), user="root")).splitlines() if l]
            cls.runtime = sorted(set(offenders(after, allowed_for(name))) - set(cls.changed))
            if cls.runtime:
                sys.stderr.write("\n[4b.7] %s: files the tool itself wrote when run: %s\n" % (name, cls.runtime[:6]))
            sys.stderr.write("\n[4b.7] %s: first call %.0fs, exit %d, retried=%s, output: %s\n"
                             % (name, cls.seconds, cls.first.returncode, cls.retried, out(cls.first)[:200]))

        @classmethod
        def tearDownClass(cls):
            for b in cls.boxes:
                b.remove()
            assert cls.vol.startswith("swarmbox-test-4b7-vol-")
            podman("volume", "rm", "-f", cls.vol)

        def test_01_the_home_starts_without_the_tool(self):
            self.assertNotIn("/home/agent/.local/share/swarmbox/tools/" + name, self.home_before)
            self.assertNotIn("/home/agent/.local/share/swarmbox", self.home_before)

        def test_02_install_then_first_call_prints_the_version(self):
            self.assertEqual(self.inst.returncode, 0, err(self.inst) + out(self.inst))
            r = self.first
            self.assertEqual(r.returncode, 0, err(r) + out(r))
            self.assertRegex(out(r), regex)
            if pinned and pinned != "latest":
                self.assertIn(pinned, out(r))
            self.assertNotRegex(err(r), r"(?i)installing")  # the installer already ran: the call installs nothing

        def test_03_no_side_effects_outside_the_prefix(self):
            bad = offenders(self.changed, allowed_for(name))
            self.assertEqual(bad, [], bad[:20])
            self.assertTrue([p for p in self.changed if "/tools/%s/" % name in p], "nothing was installed under the prefix")

        def test_04_the_npm_cache_rule(self):
            left = cache_leftovers(out(self.box.sh("find %s -type f 2>/dev/null" % CACHE, user="root")).splitlines())
            if npm:
                self.assertEqual(left, [], "an npm installer left the cache full (design 6.4): %s" % left[:5])
            else:
                self.assertEqual(left, [], "a non-npm installer touched the npm cache")

        def test_05_the_install_belongs_to_the_agent_user(self):
            r = self.box.sh("find /home/agent/.local/share/swarmbox/tools/%s ! -user agent | head" % name, user="root")
            self.assertEqual(out(r), "")

        def test_06_a_second_call_installs_nothing(self):
            r = self.box.sh(cmd_text)
            self.assertEqual(r.returncode, 0, err(r))
            self.assertNotRegex(err(r), r"(?i)installing")
            self.assertEqual(out(r), out(self.first))

        def test_07_survives_a_reset(self):
            self.box.remove()
            new = Box(self.vol)
            self.boxes.append(new)
            # the tool-ports file and the index live in the image: both exist again in the new container
            r = new.sh(cmd_text)
            self.assertEqual(r.returncode, 0, err(r))
            self.assertNotRegex(err(r), r"(?i)installing")
            self.assertEqual(out(r), out(self.first))
            lst = new.sh("swarmbox-tool list")
            self.assertIn(name, out(lst))
            if name == "clasp":
                ports = new.sh("cat /usr/local/share/swarmbox/host/tool-ports")
                self.assertIn("43323", out(ports) + err(ports))
            if name == "opencode":
                # observed only (the OpenCode 2.x shared background server must not be assumed): listening TCP sockets now
                lis = new.sh("awk '$4==\"0A\"{print $2}' /proc/net/tcp /proc/net/tcp6 2>/dev/null")
                sys.stderr.write("\n[4b.7] opencode: listening sockets after --version: %r\n" % out(lis))

    Real.__name__ = "Real_" + name
    Real.__qualname__ = Real.__name__
    return Real


for _n in TABLE:
    if _n in selected() or not ENABLED:
        globals()["Real_" + _n] = make_real_class(_n)


if __name__ == "__main__":
    unittest.main()
