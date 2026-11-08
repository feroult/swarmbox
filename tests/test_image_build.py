"""Slice 2.1: checks on the built image (tag: image build). Skipped unless SWARMBOX_IMAGE_BUILD=1 and podman works.

It builds swarmbox-test-img-<rand> with dev/dev-build.sh (slow, minutes), inspects it in throwaway containers
(swarmbox-test-img-run-<rand>), records the size, and removes the container and the image by their exact names.
Environment: SWARMBOX_IMAGE_TAG=<swarmbox-test-...> reuses an existing image instead of building (it is then not removed).
Run: SWARMBOX_IMAGE_BUILD=1 python3 tests/test_image_build.py
"""
import json
import os
import random
import re
import shutil
import string
import subprocess
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import ROOT  # noqa: E402

ENABLED = os.environ.get("SWARMBOX_IMAGE_BUILD") == "1" and shutil.which("podman")
TARGET_BYTES = int(2.5 * 1000 ** 3)
TAG = None
OWN = False


def rnd():
    return "".join(random.choice(string.ascii_lowercase + string.digits) for _ in range(6))


def podman(*args, timeout=600):
    return subprocess.run(["podman"] + list(args), capture_output=True, text=True, timeout=timeout)


def in_image(*cmd):
    name = "swarmbox-test-img-run-" + rnd()
    try:
        return podman("run", "--rm", "--name", name, "--entrypoint", cmd[0], TAG, *cmd[1:])
    finally:
        podman("rm", "-f", name)


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
    sys.stderr.write(r.stdout[-3000:] + r.stderr[-3000:])
    if r.returncode != 0:
        raise AssertionError("image build failed")


def tearDownModule():
    if OWN and TAG and TAG.startswith("swarmbox-test-"):
        podman("rmi", TAG)


@unittest.skipUnless(ENABLED, "image build tests need SWARMBOX_IMAGE_BUILD=1 and podman")
class ImageTest(unittest.TestCase):
    def test_base_image_has_node_1000_b26(self):
        r = podman("run", "--rm", "--name", "swarmbox-test-img-run-" + rnd(), "node:24-slim", "id", "node")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("uid=1000(node) gid=1000(node)", r.stdout)

    def test_agent_is_1000(self):
        r = in_image("id", "agent")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("uid=1000(agent) gid=1000(agent)", r.stdout)
        self.assertNotEqual(in_image("id", "node").returncode, 0)
        r = in_image("id", "-un")
        self.assertEqual(r.stdout.strip(), "agent")

    def test_tools_present(self):
        for cmd in (["tmux", "-V"], ["ttyd", "--version"], ["starship", "--version"], ["git", "--version"],
                    ["podman", "--version"], ["chromium", "--version"], ["uv", "--version"], ["jq", "--version"]):
            r = in_image(*cmd)
            self.assertEqual(r.returncode, 0, "%s: %s" % (cmd[0], r.stderr))

    def test_what_must_not_be_there(self):
        # Since slice 4a.5 the image holds the claude SHIM (a link to swarmbox-shim, found on PATH); it is not the program.
        r = in_image("sh", "-c", "for c in claude opencode gemini gcloud clasp go poetry; do p=$(command -v $c) && echo \"FOUND $c $p\"; done; true")
        found = [l.split()[1:] for l in r.stdout.splitlines() if l.startswith("FOUND")]
        self.assertEqual(found, [["claude", "/usr/local/lib/swarmbox/shims/claude"]], r.stdout)
        r = in_image("sh", "-c", "readlink /usr/local/lib/swarmbox/shims/claude; "
                     "find / -xdev \\( -name claude -o -name .claude \\) -not -path '/usr/local/lib/swarmbox/*' -not -path '/proc/*' 2>/dev/null; "
                     "test ! -e /home/agent/.local && echo no-local")
        self.assertEqual(r.stdout.split(), ["/usr/local/bin/swarmbox-shim", "no-local"], r.stdout)

    def test_chrome_devtools_mcp_version_matches_pin(self):
        with open(os.path.join(ROOT, "Dockerfile")) as f:
            pin = re.search(r"^ARG CHROME_DEVTOOLS_MCP_VERSION=(\S+)$", f.read(), re.M).group(1)
        r = in_image("chrome-devtools-mcp", "--version")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(pin, r.stdout)
        r = in_image("chrome-devtools-mcp", "--help")
        self.assertEqual(r.returncode, 0, r.stderr)
        for opt in ("--executablePath", "--headless", "--chromeArg", "--browserUrl"):
            self.assertIn(opt, r.stdout + r.stderr)

    def test_npm_cache_owned_by_agent_and_npm_works_as_agent(self):
        r = in_image("sh", "-c", "stat -c '%U' /opt/npm-cache; find /opt/npm-cache ! -user agent | head -3; echo $NPM_CONFIG_CACHE")
        lines = r.stdout.split("\n")
        self.assertEqual(lines[0], "agent")
        self.assertEqual([l for l in lines[1:-2] if l], [], "root-owned entries in the npm cache")
        self.assertIn("/opt/npm-cache", r.stdout)

    def test_nested_podman_settings_in_the_image(self):
        r = in_image("sh", "-c", "cat /etc/containers/storage.conf /etc/containers/containers.conf /etc/subuid /etc/subgid; getcap /usr/bin/newuidmap /usr/bin/newgidmap; ls -l /usr/bin/newuidmap")
        for s in ("ignore_chown_errors", 'utsns = "host"', "agent:1001:64535", "cap_setuid", "cap_setgid"):
            self.assertIn(s, r.stdout)
        self.assertNotRegex(r.stdout, r"-rws")

    def test_cmd_and_entrypoint(self):
        r = podman("image", "inspect", TAG, "--format", "{{json .Config.Cmd}} {{json .Config.Entrypoint}} {{.Config.User}}")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), '["serve"] ["/usr/local/bin/swarmbox-entrypoint"] agent')

    def test_page_was_built_at_image_build(self):
        r = in_image("sh", "-c", "test -s /usr/local/share/swarmbox/web/index.html && grep -c '__SWARMBOX_' /usr/local/share/swarmbox/web/index.html")
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_size_is_recorded_against_the_budget_b27(self):
        r = podman("image", "inspect", TAG, "--format", "{{.Size}}")
        size = int(r.stdout.strip())
        h = podman("history", "--no-trunc=false", "--format", "{{.Size}}\t{{.CreatedBy}}", TAG)
        sys.stderr.write("\nIMAGE SIZE %d bytes (%.2f GB); budget %.1f GB\n%s\n" % (size, size / 1e9, TARGET_BYTES / 1e9, h.stdout))
        self.assertGreater(size, 100 * 1000 ** 2)
        # B27 is a budget: report, and fail only when it is exceeded so the owner sees it
        self.assertLess(size, TARGET_BYTES, "image is over the 2.5 GB budget")


if __name__ == "__main__":
    unittest.main(verbosity=2)
