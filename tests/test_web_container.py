"""Slice 2.5: the web terminal, the stubs and the entrypoint subcommands in a real throwaway container from the image.

[reduced: development box, no nested Podman in the box] The development box is itself a container, so a third level of
nesting is not available: the container starts with SWARMBOX_TEST_NO_NESTED=1 (serve reaches ready with warnings). What is
checked: the page built at image build, swarmbox-web rendering box:/tmp/swarmbox/index.html with the three settings, ttyd on a
random high port bound to 127.0.0.1 INSIDE the container (its own network namespace; never 7681 in this one) serving it,
`pubkey`, `tool validate`, the tool-ports file and `host-helper`.

Skipped unless SWARMBOX_IMAGE_BUILD=1 and podman works. SWARMBOX_IMAGE_TAG=<swarmbox-test-...> reuses an image (and does not
remove it); otherwise the image is built with dev/dev-build.sh and removed at the end.
Containers are swarmbox-test-web-<random>, removed by exact name; the workspace is a mktemp directory.
Run: SWARMBOX_IMAGE_BUILD=1 python3 tests/test_web_container.py
"""
import io
import os
import random
import shutil
import string
import subprocess
import sys
import tarfile
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import ROOT  # noqa: E402

ENABLED = os.environ.get("SWARMBOX_IMAGE_BUILD") == "1" and shutil.which("podman")
TAG = None
OWN = False
FORBIDDEN_PORTS = (7681, 8889, 43323)


def rnd():
    return "".join(random.choice(string.ascii_lowercase + string.digits) for _ in range(6))


def podman(*args, timeout=120, **kw):
    return subprocess.run(["podman"] + list(args), capture_output=True, timeout=timeout, **kw)


def setUpModule():
    global TAG, OWN
    if not ENABLED:
        return
    TAG = os.environ.get("SWARMBOX_IMAGE_TAG")
    if TAG:
        assert TAG.startswith("swarmbox-test-"), TAG
        return
    TAG = "swarmbox-test-img-" + rnd()
    OWN = True
    r = subprocess.run(["sh", os.path.join(ROOT, "dev", "dev-build.sh"), "--tag", TAG], capture_output=True, text=True)
    if r.returncode != 0:
        sys.stderr.write(r.stdout[-3000:] + r.stderr[-3000:])
        raise AssertionError("image build failed")


def tearDownModule():
    if OWN and TAG and TAG.startswith("swarmbox-test-"):
        podman("rmi", TAG)


def wait_for(fn, seconds=60, step=0.3):
    end = time.time() + seconds
    while time.time() < end:
        v = fn()
        if v:
            return v
        time.sleep(step)
    return None


@unittest.skipUnless(ENABLED, "container tests need SWARMBOX_IMAGE_BUILD=1 and podman")
class WebInContainer(unittest.TestCase):
    def setUp(self):
        self.ws = tempfile.mkdtemp(prefix="web-ws-")
        self.names = []
        self.addCleanup(shutil.rmtree, self.ws, ignore_errors=True)
        self.addCleanup(self._remove)
        self.port = random.randrange(20000, 40000)
        while self.port in FORBIDDEN_PORTS:
            self.port = random.randrange(20000, 40000)

    def _remove(self):
        for n in self.names:
            assert n.startswith("swarmbox-test-web-")
            podman("rm", "-f", "-t", "0", n)

    def run_box(self, *extra_env):
        name = "swarmbox-test-web-" + rnd()
        self.names.append(name)
        args = ["run", "-d", "--name", name, "--userns=keep-id:uid=1000,gid=1000", "-v", self.ws + ":/home/agent",
                "--tmpfs", "/tmp/swarmbox", "-e", "SWARMBOX_TEST_NO_NESTED=1",
                # the test port, on the loopback of the container's OWN network namespace
                "-e", "SWARMBOX_TEST_WEB_PORT=%d" % self.port, "-e", "SWARMBOX_TEST_WEB_IFACE=lo"]
        for e in extra_env:
            args += ["-e", e]
        r = podman(*args, TAG, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        return name

    def sh(self, name, cmd):
        return podman("exec", name, "sh", "-c", cmd, text=True).stdout.strip()

    def ready(self, name):
        return wait_for(lambda: self.sh(name, "cat /tmp/swarmbox/ready 2>/dev/null"))

    def http(self, name, path="/"):
        return self.sh(name, "curl -s %s http://127.0.0.1:%d%s" % ("-o /dev/null -w '%{http_code}'" if path == "/code" else "", self.port, "/" if path == "/code" else path))

    def test_the_page_is_built_at_image_build_and_rendered_with_the_three_settings(self):
        self.assertNotIn(self.port, FORBIDDEN_PORTS)
        os.makedirs(os.path.join(self.ws, ".config", "swarmbox"))
        with open(os.path.join(self.ws, ".config", "swarmbox", "web-terminal.conf"), "w") as f:
            f.write("padding=23\nctrlVPaste=false\nfontSize=19\nscrollback=4321\n")
        name = self.run_box()
        # built at image build: the page with its placeholders is in the image, before any start
        built = podman("run", "--rm", "--entrypoint", "sh", TAG, "-c",
                       "grep -o '__SWARMBOX_[A-Z_]*__' /usr/local/share/swarmbox/web/index.html | sort -u", text=True)
        self.assertEqual(built.stdout.split(), ["__SWARMBOX_CTRL_C__", "__SWARMBOX_CTRL_V__", "__SWARMBOX_PADDING__"], built.stderr)
        self.assertIsNotNone(self.ready(name), podman("logs", name, text=True).stdout)
        self.assertTrue(wait_for(lambda: self.http(name, "/code") == "200", 30), self.sh(name, "tail -5 /home/agent/.local/state/swarmbox/web-terminal.log"))
        # box:/tmp/swarmbox/index.html: no placeholder, the user's values
        page = self.sh(name, "cat /tmp/swarmbox/index.html")
        self.assertNotIn("__SWARMBOX_", page)
        self.assertIn("--swarmbox-padding:23px", page)
        self.assertIn('{"ctrlVPaste":false,"ctrlCCopy":true}', page)
        # ttyd serves exactly that file
        served = self.http(name)
        self.assertIn("--swarmbox-padding:23px", served)
        self.assertIn('window.__swarmboxClipboard={"ctrlVPaste":false,"ctrlCCopy":true};', served)
        # the other settings went to ttyd as -t options (ttyd rewrites the "=" of key=value in its own argv to a NUL)
        cmd = self.sh(name, "tr '\\0' ' ' < /proc/$(pgrep -x ttyd | head -1)/cmdline")
        self.assertIn("-t fontSize 19", cmd)
        self.assertIn("-t scrollback 4321", cmd)
        self.assertIn("-p %d" % self.port, cmd)
        self.assertIn("-i lo", cmd)
        # bound to the loopback of the container only, on the test port; 7681 is not used inside either
        listen = self.sh(name, "cat /proc/net/tcp")
        self.assertIn("0100007F:%04X" % self.port, listen.upper())
        self.assertNotIn(":1E01 ", listen.upper().replace("0100007F:1E01", "X"))   # 7681 = 0x1E01

    def test_restart_after_editing_the_conf_gives_a_new_page_and_the_box_stays_up(self):
        name = self.run_box()
        self.assertIsNotNone(self.ready(name))
        self.assertTrue(wait_for(lambda: self.http(name, "/code") == "200", 30))
        old = self.sh(name, "pgrep -x ttyd | head -1")
        self.sh(name, "mkdir -p $HOME/.config/swarmbox && echo padding=31 > $HOME/.config/swarmbox/web-terminal.conf")
        out = podman("exec", name, "swarmbox-web", "restart", text=True)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertTrue(wait_for(lambda: (lambda p: p and p != old)(self.sh(name, "pgrep -x ttyd | head -1")), 20), "ttyd was not restarted")
        self.assertTrue(wait_for(lambda: "--swarmbox-padding:31px" in self.sh(name, "cat /tmp/swarmbox/index.html"), 10))
        self.assertTrue(wait_for(lambda: self.http(name, "/code") == "200", 20))
        self.assertEqual(podman("inspect", "--format", "{{.State.Status}}", name, text=True).stdout.strip(), "running")

    def test_pubkey_prints_the_public_key_and_serve_made_it_once(self):
        name = self.run_box()
        self.assertIsNotNone(self.ready(name))
        key = self.sh(name, "cat $HOME/.ssh/id_ed25519.pub")
        self.assertTrue(key.startswith("ssh-ed25519 "), key)
        out = podman("exec", name, "swarmbox-entrypoint", "pubkey", text=True)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn(key, out.stdout)
        self.assertEqual(self.sh(name, "cat $HOME/.ssh/id_ed25519.pub"), key)   # not regenerated
        # the box has no SSH-key warning
        self.assertNotIn("SSH key", self.sh(name, "cat $HOME/.local/state/swarmbox/health"))

    def test_tool_validate_placeholder_and_tool_ports_and_host_helper(self):
        for args in (["swarmbox-tool", "validate"], ["swarmbox-entrypoint", "tool", "validate"]):
            r = podman("run", "--rm", "--entrypoint", args[0], TAG, *args[1:], text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("manifest(s) checked", r.stdout)
        r = podman("run", "--rm", TAG, "tool", "install", "claude", text=True)
        self.assertEqual(r.returncode, 70)
        self.assertIn("Phase 4a", r.stderr)
        # the archive written by `podman run --rm <image> host-helper` is a clean tar with an empty tool-ports
        r = podman("run", "--rm", TAG, "host-helper")
        self.assertEqual(r.returncode, 0, r.stderr)
        tf = tarfile.open(fileobj=io.BytesIO(r.stdout))
        names = {n[2:] if n.startswith("./") else n for n in tf.getnames()}
        self.assertIn("tool-ports", names)
        self.assertIn("cloudflare-setup.py", names)
        self.assertEqual(tf.extractfile("./tool-ports").read(), b"")
        self.assertEqual(r.stderr, b"")

    def test_any_other_command_runs_as_given(self):
        r = podman("run", "--rm", TAG, "sh", "-c", 'echo "$1|$2"; exit 7', "x", "a b", "c", text=True)
        self.assertEqual(r.returncode, 7)
        self.assertEqual(r.stdout.strip(), "a b|c")


if __name__ == "__main__":
    unittest.main()
