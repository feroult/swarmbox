"""Slice 5.7: `swarmbox-host remote ...` end to end against the fake Cloudflare API and a fake podman (design 5.2, 13; D14, D16, D28).

The REAL wrapper and the REAL cloudflare-setup.py run as subprocesses. The API base URL is redirected with the script's existing
CLOUDFLARE_API_BASE variable (the mechanism of tests/test_cloudflare_setup.py, whose in-process fake server is reused and which
binds 127.0.0.1 on a random port). podman is a shell shim first in PATH. HOME and XDG_* are mktemp folders.
This is the reduced form of the owner's end-to-end run: no real Cloudflare account, no real connector image pull.
Run: python3 tests/test_host_remote_e2e_fake.py
"""
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_cloudflare_setup as tcs  # noqa: E402  (starts the fake server on 127.0.0.1, sets CLOUDFLARE_API_BASE)
from helpers import ROOT, DEFAULT_NAME  # noqa: E402

HELPER_SRC = os.path.join(ROOT, "container", "host", "swarmbox-host")
VERSION_SRC = os.path.join(ROOT, "container", "host", "VERSION")
DEFAULTS_SRC = os.path.join(ROOT, "container", "host", "DEFAULTS")
SCRIPT_SRC = os.path.join(ROOT, "cloudflare-setup.py")
FAKE = tcs.FAKE
API = os.environ["CLOUDFLARE_API_BASE"]

PODMAN = '''#!/bin/sh
echo "$@" >> "$SHIM_DIR/calls"
case "$1" in
  inspect) [ -f "$SHIM_DIR/state" ] || exit 1
           read st tok < "$SHIM_DIR/state"
           if [ "$st" = running ]; then r=true; else r=false; fi
           printf '%s|TUNNEL_TOKEN=%s\\n' "$r" "$tok"; exit 0 ;;
  run) echo "running $TUNNEL_TOKEN" > "$SHIM_DIR/state" ;;
  start) read st tok < "$SHIM_DIR/state"; echo "running $tok" > "$SHIM_DIR/state" ;;
  stop) : ;;
  rm) rm -f "$SHIM_DIR/state" ;;
esac
'''


class E2E(unittest.TestCase):
    def setUp(self):
        FAKE.reset()
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="swarmbox-test-remote-e2e."))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.home = os.path.join(self.tmp, "home")
        self.xdg = os.path.join(self.tmp, "xdg")
        os.makedirs(self.home)
        hd = os.path.join(self.tmp, "helper")
        os.makedirs(hd)
        self.helper = os.path.join(hd, "swarmbox-host")
        shutil.copy(HELPER_SRC, self.helper)
        shutil.copy(VERSION_SRC, os.path.join(hd, "VERSION"))
        shutil.copy(DEFAULTS_SRC, os.path.join(hd, "DEFAULTS"))
        shutil.copy(SCRIPT_SRC, os.path.join(hd, "cloudflare-setup.py"))
        os.chmod(self.helper, 0o755)
        self.shim = os.path.join(self.tmp, "shim")
        os.makedirs(self.shim)
        p = os.path.join(self.shim, "podman")
        with open(p, "w") as f:
            f.write(PODMAN)
        os.chmod(p, os.stat(p).st_mode | stat.S_IXUSR)

    def env(self):
        e = {k: v for k, v in os.environ.items() if not k.startswith(("SWARMBOX_", "XDG_", "CLOUDFLARE_"))}
        e.update({"HOME": self.home, "XDG_CONFIG_HOME": os.path.join(self.xdg, "c"),
                  "XDG_DATA_HOME": os.path.join(self.xdg, "d"), "XDG_STATE_HOME": os.path.join(self.xdg, "s"),
                  "CLOUDFLARE_API_TOKEN": tcs.GOOD_TOKEN, "CLOUDFLARE_API_BASE": API, "SHIM_DIR": self.shim,
                  "PATH": self.shim + os.pathsep + os.environ["PATH"]})
        return e

    def helper_run(self, *args):
        return subprocess.run([self.helper, *args], env=self.env(), capture_output=True, text=True, input="",
                              cwd=self.tmp, timeout=120)

    def remote(self, *args):
        return self.helper_run("remote", *args)

    def calls(self):
        p = os.path.join(self.shim, "calls")
        if not os.path.exists(p):
            return []
        with open(p) as f:
            return f.read().splitlines()

    SETUP = ["setup", "--domain", "talkr.run", "--email", "me@example.com", "--no-verify"]

    def test_the_base_url_is_loopback_and_not_a_reserved_port(self):
        self.assertTrue(API.startswith("http://127.0.0.1:"))
        port = int(API.split(":")[2].split("/")[0])
        self.assertGreaterEqual(port, 1024)
        self.assertNotIn(port, (7681, 8889, 43323))

    def test_dry_run_changes_nothing_and_starts_no_connector(self):
        r = self.remote(*self.SETUP, "--dry-run")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(FAKE.mutations(), [])
        self.assertEqual([c for c in self.calls() if c.startswith(("run ", "start "))], [])
        self.assertEqual((FAKE.apps, FAKE.dns, FAKE.tunnels), ([], [], []))

    def test_full_lifecycle(self):
        r = self.remote(*self.SETUP, "--session", "24h")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual((len(FAKE.apps), len(FAKE.policies), len(FAKE.dns), len(FAKE.tunnels)), (1, 1, 1, 1))
        self.assertEqual(FAKE.apps[0]["session_duration"], "24h")
        self.assertEqual(len([c for c in self.calls() if c.startswith("run ")]), 1)
        self.assertNotIn("tok.", "\n".join(self.calls()), "the token is never on the podman command line")
        st = self.remote("status", "--domain", "talkr.run")
        self.assertEqual(st.returncode, 0, st.stderr)
        self.assertIn(DEFAULT_NAME + ".talkr.run", st.stdout + st.stderr)
        u = self.helper_run("url")
        self.assertIn("https://" + DEFAULT_NAME + ".talkr.run", u.stdout)
        # a rerun without --session keeps the session and adds no second connector
        r = self.remote(*self.SETUP)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(FAKE.apps[0]["session_duration"], "24h")
        self.assertEqual(len([c for c in self.calls() if c.startswith("run ")]), 1)
        t = self.remote("token", "--domain", "talkr.run")
        self.assertEqual(t.returncode, 0, t.stderr)
        self.assertEqual(t.stdout, "tok." + FAKE.tunnels[0]["id"] + "\n")
        o = self.remote("off", "--domain", "talkr.run", "--yes")
        self.assertEqual(o.returncode, 0, o.stderr)
        self.assertEqual((FAKE.apps, FAKE.policies, FAKE.dns), ([], [], []))
        self.assertEqual(FAKE.configs[FAKE.tunnels[0]["id"]]["ingress"], [{"service": "http_status:404"}])
        self.assertTrue(any(c.startswith("rm ") for c in self.calls()), "the connector is removed")

    def test_writes_stay_inside_the_mktemp_folders(self):
        self.remote(*self.SETUP)
        self.remote("off", "--domain", "talkr.run", "--yes")
        cfg = os.path.join(self.xdg, "c", "swarmbox", "cloudflare.json")
        self.assertTrue(os.path.exists(cfg))
        for root, _, files in os.walk(self.home):
            for n in files:
                self.assertTrue(os.path.realpath(os.path.join(root, n)).startswith(self.tmp))


if __name__ == "__main__":
    unittest.main()
