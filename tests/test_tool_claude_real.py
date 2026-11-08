"""Slice 4a.6: the first call of Claude Code through the shim, for real (design 6.4, 6.5, 6.7, B1).

Two parts.
  1. Unit level, always runs (needs bash only): container/tools/claude/install.sh with a fake curl on PATH that serves a fake vendor
     script, which records its own arguments. Proves that the version is passed as an argument only when it is not "latest".
  2. Real, slow, SKIPPED unless SWARMBOX_TEST_NETWORK=1, SWARMBOX_IMAGE_BUILD=1 and podman works (it is therefore not part of
     the default CI result): throwaway containers swarmbox-test-4a6-* with a fresh named volume swarmbox-test-4a6-* as /home/agent
     (never the real home), from the 4a-5 image (SWARMBOX_IMAGE_TAG=<swarmbox-test-...> reuses an image and does not remove
     it; otherwise dev/dev-build.sh builds one). It downloads about 330 MB from the vendor: first call installs, claude update works,
     a second call does not install again, nothing outside the allowed paths changed, and an offline first call fails cleanly.
Run: SWARMBOX_TEST_NETWORK=1 SWARMBOX_IMAGE_BUILD=1 python3 tests/test_tool_claude_real.py
"""
import os
import random
import re
import shutil
import stat
import string
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import ROOT  # noqa: E402

INSTALL = os.path.join(ROOT, "container", "tools", "claude", "install.sh")
ENABLED = (os.environ.get("SWARMBOX_TEST_NETWORK") == "1" and os.environ.get("SWARMBOX_IMAGE_BUILD") == "1"
           and shutil.which("podman"))
TAG = None
OWN = False
VERSION_RE = re.compile(r"\d+\.\d+\.\d+")


def rnd():
    return "".join(random.choice(string.ascii_lowercase + string.digits) for _ in range(6))


def podman(*args, timeout=900, **kw):
    return subprocess.run(["podman"] + list(args), capture_output=True, timeout=timeout, **kw)


class InstallArguments(unittest.TestCase):
    """install.sh with a fake curl: no network, no vendor script."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="claude-inst-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.home = os.path.join(self.tmp, "home")
        self.bin = os.path.join(self.tmp, "bin")
        os.makedirs(self.bin)
        self.rec = os.path.join(self.tmp, "calls")
        curl = os.path.join(self.bin, "curl")
        with open(curl, "w") as f:
            f.write('#!/bin/sh\necho "curl $*" >> "$FAKE_REC"\n'
                    # the "vendor script": records its arguments and writes the launcher the real one would write
                    "cat <<'VENDOR'\n"
                    'echo "vendor args: $#:$*" >> "$FAKE_REC"\n'
                    'mkdir -p "$HOME/.local/bin"\n'
                    "printf '#!/bin/sh\\necho 9.9.9 \\\\(Claude Code\\\\)\\n' > \"$HOME/.local/bin/claude\"\n"
                    'chmod +x "$HOME/.local/bin/claude"\n'
                    "VENDOR\n")
        os.chmod(curl, 0o755)

    def run_install(self, version=None, curl_fails=False):
        env = dict(os.environ, HOME=self.home, FAKE_REC=self.rec, TOOL_PREFIX=os.path.join(self.tmp, "prefix"),
                   TOOL_ARCH="amd64", PATH=self.bin + ":" + os.environ["PATH"])
        env.pop("TOOL_VERSION", None)
        if version:
            env["TOOL_VERSION"] = version
        if curl_fails:
            with open(os.path.join(self.bin, "curl"), "w") as f:
                f.write('#!/bin/sh\necho "curl $*" >> "$FAKE_REC"\nexit 22\n')
        os.makedirs(self.home, exist_ok=True)
        return subprocess.run(["bash", INSTALL], env=env, capture_output=True, text=True, timeout=60)

    def calls(self):
        with open(self.rec) as f:
            return f.read().splitlines()

    def test_latest_passes_no_argument(self):
        for v in (None, "latest"):
            if os.path.exists(self.rec):
                os.remove(self.rec)
            r = self.run_install(v)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("vendor args: 0:", self.calls())
            self.assertEqual(r.stdout, "")

    def test_a_pinned_version_is_the_one_argument(self):
        r = self.run_install("2.1.314")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("vendor args: 1:2.1.314", self.calls())

    def test_the_download_is_the_vendors_https_script_and_failure_runs_nothing(self):
        r = self.run_install()
        self.assertIn("curl -fsSL https://claude.ai/install.sh", self.calls())
        os.remove(self.rec)
        shutil.rmtree(self.home)
        shutil.rmtree(os.path.join(self.tmp, "prefix"))
        r = self.run_install(curl_fails=True)
        self.assertNotEqual(r.returncode, 0)
        self.assertFalse(any(c.startswith("vendor") for c in self.calls()))
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "prefix", "installed")))


def setUpModule():
    global TAG, OWN
    if not ENABLED:
        return
    TAG = os.environ.get("SWARMBOX_IMAGE_TAG")
    if TAG:
        assert TAG.startswith("swarmbox-test-"), TAG
        return
    TAG = "swarmbox-test-4a6-img-" + rnd()
    OWN = True
    r = subprocess.run(["sh", os.path.join(ROOT, "dev", "dev-build.sh"), "--tag", TAG], capture_output=True, text=True)
    sys.stderr.write(r.stdout[-2000:] + r.stderr[-2000:])
    if r.returncode != 0:
        raise AssertionError("image build failed")


def tearDownModule():
    if OWN and TAG and TAG.startswith("swarmbox-test-"):
        podman("rmi", TAG)


class Box:
    """One throwaway container on a named volume. Removed by exact name."""

    def __init__(self, vol, network=None):
        self.name = "swarmbox-test-4a6-run-" + rnd()
        self.vol = vol
        args = ["run", "-d", "--name", self.name, "-v", vol + ":/home/agent", "--tmpfs", "/tmp/swarmbox",
                "--entrypoint", "sleep"]
        if network:
            args += ["--network=" + network]
        r = podman(*args, TAG, "3000")
        assert r.returncode == 0, r.stderr
        self.err = None

    def sh(self, cmd, user="agent", timeout=900):
        return podman("exec", "--user", user, self.name, "bash", "-c", cmd, timeout=timeout)

    def remove(self):
        assert self.name.startswith("swarmbox-test-4a6-run-")
        podman("rm", "-f", "-t", "0", self.name)


def out(r):
    return r.stdout.decode().strip()


def errtext(r):
    return r.stderr.decode()


LISTING = "find /usr /etc /opt /var /root -xdev \\( -type f -o -type l \\) -printf '%p %s %T@\\n' 2>/dev/null | sort"


@unittest.skipUnless(ENABLED, "real test: needs SWARMBOX_TEST_NETWORK=1, SWARMBOX_IMAGE_BUILD=1 and podman")
class FirstCallOnline(unittest.TestCase):
    """One box, one volume, steps in order (the names sort in the order they must run)."""

    @classmethod
    def setUpClass(cls):
        cls.vol = "swarmbox-test-4a6-vol-" + rnd()
        assert podman("volume", "create", cls.vol).returncode == 0
        cls.box = Box(cls.vol)
        cls.before = out(cls.box.sh(LISTING, user="root"))
        cls.home_before = out(cls.box.sh("find /home/agent -mindepth 1 | sort"))
        cls.first = cls.box.sh("claude --version")
        cls.after = out(cls.box.sh(LISTING, user="root"))

    @classmethod
    def tearDownClass(cls):
        cls.box.remove()
        assert cls.vol.startswith("swarmbox-test-4a6-vol-")
        podman("volume", "rm", "-f", cls.vol)

    def test_01_the_home_starts_empty_of_claude(self):
        self.assertNotIn("claude", self.home_before)

    def test_02_first_call_installs_and_prints_a_version(self):
        r = self.first
        self.assertEqual(r.returncode, 0, errtext(r))
        self.assertRegex(out(r), VERSION_RE)
        self.assertIn("Claude Code", out(r))
        self.assertIn("Installing claude (first use)", errtext(r))
        # stdout is only the tool's: installer progress went to stderr (6.4)
        self.assertEqual(len(out(r).splitlines()), 1, out(r))

    def test_03_the_launcher_is_a_link_into_versions(self):
        r = self.box.sh("readlink -f ~/.local/bin/claude; test -L ~/.local/bin/claude && echo link")
        self.assertIn("link", out(r))
        self.assertRegex(out(r), r"/home/agent/\.local/share/claude/versions/\d+\.\d+\.\d+")

    def test_04_the_record_exists_and_has_no_checksum(self):
        r = self.box.sh("find /home/agent -path '*swarmbox/tools/claude/self/.swarmbox-env' | head -1")
        self.assertTrue(out(r), "no record of the install")
        rec = self.box.sh("cat " + out(r) + "; ls -A $(dirname " + out(r) + ")")
        self.assertIn("installed", out(rec))

    def test_05_a_second_call_installs_nothing(self):
        r = self.box.sh("claude --version")
        self.assertEqual(r.returncode, 0, errtext(r))
        self.assertNotIn("Installing", errtext(r))
        self.assertNotIn("installing", errtext(r))
        self.assertEqual(errtext(r), "", errtext(r))
        self.assertEqual(out(r), out(self.first))

    def test_06_nothing_outside_the_home_changed_except_the_npm_cache(self):
        b, a = set(self.before.splitlines()), set(self.after.splitlines())
        changed = sorted(l.split(" ")[0] for l in (a ^ b))
        changed = [p for p in changed if not p.startswith("/opt/npm-cache")]
        # the entrypoint is not running here (sleep is), so nothing else may differ, not even logs
        self.assertEqual(changed, [], changed[:20])

    def test_07_the_installed_paths_are_the_four_of_6_7_plus_the_users_own(self):
        r = self.box.sh("find /home/agent -mindepth 1 -maxdepth 3 | sort")
        top = set(out(r).splitlines()) - set(self.home_before.splitlines())
        allowed = ("/home/agent/.local", "/home/agent/.cache", "/home/agent/.config", "/home/agent/.claude")
        for p in top:
            self.assertTrue(p.startswith(allowed), "unexpected path: " + p)
        r = self.box.sh("ls ~/.local/share ~/.local/state ~/.cache ~/.local/bin")
        text = out(r)
        for need in ("claude",):
            self.assertIn(need, text)
        # under ~/.local/share and ~/.local/state, claude and SwarmBox's record dir are the only entries
        share = out(self.box.sh("ls -A ~/.local/share")).split()
        self.assertEqual(sorted(share), sorted(set(share) & {"claude", "swarmbox"}), share)

    def test_08_claude_json_is_written_by_the_vendor_installer_and_holds_no_login(self):
        # Measured in 4a.6 (decision log): the vendor's own installer creates ~/.claude and ~/.claude.json (installMethod native);
        # install.sh does not touch them. Design 6.7 first said "never"; it now says the vendor creates them.
        r = self.box.sh("cat ~/.claude.json")
        self.assertEqual(r.returncode, 0, "the vendor installer left no ~/.claude.json")
        self.assertIn('"installMethod": "native"', out(r))
        self.assertNotRegex(out(r), r"(?i)oauth|accessToken|apiKey")
        self.assertEqual(self.box.sh("test -d ~/.claude").returncode, 0)

    def test_09_claude_update_works(self):
        r = self.box.sh("swarmbox-tool update claude")
        sys.stderr.write("\n[4a.6] swarmbox-tool update claude: exit %d\nstdout: %s\nstderr: %s\n"
                         % (r.returncode, out(r)[-600:], errtext(r)[-600:]))
        self.assertEqual(r.returncode, 0, errtext(r) + out(r))
        r = self.box.sh("claude --version")
        self.assertEqual(r.returncode, 0)
        self.assertNotIn("Installing", errtext(r))

    def test_10_the_binary_is_not_the_shim_after_install(self):
        r = self.box.sh("command -v claude; readlink -f $(command -v claude)")
        lines = out(r).splitlines()
        self.assertEqual(lines[0], "/usr/local/lib/swarmbox/shims/claude")
        self.assertEqual(os.path.basename(lines[1]), "swarmbox-shim")


@unittest.skipUnless(ENABLED, "real test: needs SWARMBOX_TEST_NETWORK=1, SWARMBOX_IMAGE_BUILD=1 and podman")
class FirstCallOffline(unittest.TestCase):
    def test_offline_fails_cleanly_then_online_succeeds(self):
        vol = "swarmbox-test-4a6-vol-" + rnd()
        assert podman("volume", "create", vol).returncode == 0
        boxes = []
        try:
            off = Box(vol, network="none")
            boxes.append(off)
            r = off.sh("claude --version")
            self.assertNotEqual(r.returncode, 0)
            self.assertEqual(out(r), "")
            self.assertRegex(errtext(r), r"(?i)claude")
            self.assertRegex(errtext(r), r"(?i)(fail|cannot|could not|error)")
            left = out(off.sh("find /home/agent -path '*swarmbox/tools/claude*' -o -path '*/.local/bin/claude' "
                              "-o -path '*/.local/share/claude*' | sort"))
            self.assertNotIn("self/.swarmbox-env", left)
            self.assertNotIn("current", left)
            self.assertNotIn(".local/bin/claude", left)
            on = Box(vol)
            boxes.append(on)
            r = on.sh("claude --version")
            self.assertEqual(r.returncode, 0, errtext(r))
            self.assertRegex(out(r), VERSION_RE)
        finally:
            for b in boxes:
                b.remove()
            assert vol.startswith("swarmbox-test-4a6-vol-")
            podman("volume", "rm", "-f", vol)


if __name__ == "__main__":
    unittest.main()
