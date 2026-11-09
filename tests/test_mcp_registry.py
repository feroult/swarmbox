"""Container/scripts/swarmbox-mcp.sh, the generator of <workspace>/.claude/mcp-servers.json.

Everything runs in mktemp directories: HOME (the workspace), the XDG folders and a copy of the registry. Nothing touches the
real configuration. Run with: python3 -W error tests/test_mcp_registry.py   (needs bash and jq)
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import ROOT  # noqa: E402

GEN = os.path.join(ROOT, "container", "scripts", "swarmbox-mcp.sh")
DIRS_SH = os.path.join(ROOT, "container", "scripts", "dirs.sh")
IMAGE_REG = os.path.join(ROOT, "container", "mcp")


def put(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(text)


def read(path):
    with open(path) as f:
        return f.read()


class McpCase(unittest.TestCase):
    def setUp(self):
        self.base = tempfile.mkdtemp(prefix="mcp-test-")
        self.addCleanup(shutil.rmtree, self.base, ignore_errors=True)
        self.home = os.path.join(self.base, "home")
        self.reg = os.path.join(self.base, "registry")
        self.lib = os.path.join(self.base, "lib")
        os.makedirs(self.home)
        os.makedirs(self.lib)
        os.symlink(DIRS_SH, os.path.join(self.lib, "dirs.sh"))
        shutil.copytree(IMAGE_REG, self.reg)
        self.out = os.path.join(self.home, ".claude", "mcp-servers.json")
        self.user = os.path.join(self.home, ".config", "swarmbox", "mcp")

    def run_gen(self, args=(), **extra):
        env = {"PATH": os.environ["PATH"], "HOME": self.home, "SWARMBOX_TEST_LIB": self.lib,
               "SWARMBOX_TEST_MCP_DIR": self.reg, "LANG": "C.UTF-8"}
        env.update({k: v for k, v in extra.items() if v is not None})
        return subprocess.run(["bash", GEN, *args], env=env, capture_output=True, text=True, timeout=30)

    def data(self):
        return json.loads(read(self.out))

    # -- the image file ------------------------------------------------------------------------------------------------
    def test_image_file_has_the_design_shape(self):
        c = json.loads(read(os.path.join(IMAGE_REG, "chrome-devtools", "config.json")))
        self.assertEqual(c["command"], "chrome-devtools-mcp")
        self.assertEqual(c["browserUrlArgs"], ["--browserUrl=${BROWSER_URL}"])
        self.assertEqual(c["env"], {})
        self.assertIn("--executablePath=/usr/bin/chromium", c["args"])
        self.assertIn("--headless", c["args"])

    # -- generation ------------------------------------------------------------------------------------------------------
    def test_default_output(self):
        r = self.run_gen()
        self.assertEqual(r.returncode, 0, r.stderr)
        d = self.data()
        self.assertEqual(list(d), ["mcpServers"])
        e = d["mcpServers"]["chrome-devtools"]
        self.assertNotIn("browserUrlArgs", e)
        self.assertNotIn("enabled", e)
        self.assertIn("--chromeArg=--no-sandbox", e["args"])
        self.assertEqual(e["env"], {})

    def test_browser_url_replaces_args(self):
        r = self.run_gen(BROWSER_URL="http://host.example:9222")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.data()["mcpServers"]["chrome-devtools"]["args"], ["--browserUrl=http://host.example:9222"])

    def test_off_switch_drops_the_entry(self):
        put(os.path.join(self.user, "chrome-devtools", "config.json"), '{"enabled": false}')
        r = self.run_gen()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.data(), {"mcpServers": {}})

    def test_user_fields_override_the_image(self):
        put(os.path.join(self.user, "chrome-devtools", "config.json"), '{"args": ["--foo"], "env": {"A": "1"}}')
        self.run_gen()
        e = self.data()["mcpServers"]["chrome-devtools"]
        self.assertEqual(e["args"], ["--foo"])
        self.assertEqual(e["env"], {"A": "1"})
        self.assertEqual(e["command"], "chrome-devtools-mcp")

    def test_user_only_server_is_added(self):
        put(os.path.join(self.user, "mine", "config.json"), '{"command": "my-mcp", "args": ["x"]}')
        r = self.run_gen()
        self.assertEqual(r.returncode, 0, r.stderr)
        d = self.data()["mcpServers"]
        self.assertEqual(d["mine"], {"command": "my-mcp", "args": ["x"]})
        self.assertIn("chrome-devtools", d)

    def test_malformed_user_json_gives_one_warning_and_the_others_still_generate(self):
        put(os.path.join(self.user, "broken", "config.json"), "{not json")
        put(os.path.join(self.user, "mine", "config.json"), '{"command": "my-mcp"}')
        r = self.run_gen()
        self.assertEqual(r.returncode, 1)  # the file is written, the exit status tells serve to log a health line
        self.assertEqual(len([l for l in r.stderr.splitlines() if "broken" in l]), 1, r.stderr)
        self.assertEqual(sorted(self.data()["mcpServers"]), ["chrome-devtools", "mine"])

    # -- writing -----------------------------------------------------------------------------------------------------------
    def test_failure_to_write_leaves_no_partial_file_and_keeps_the_old_one(self):
        put(self.out, '{"mcpServers": {"old": {"command": "x"}}}')
        os.chmod(os.path.dirname(self.out), 0o500)
        self.addCleanup(os.chmod, os.path.dirname(self.out), 0o700)
        if os.access(os.path.dirname(self.out), os.W_OK):
            self.skipTest("running as a user that ignores directory permissions")
        r = self.run_gen()
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(read(self.out), '{"mcpServers": {"old": {"command": "x"}}}')
        self.assertEqual(os.listdir(os.path.dirname(self.out)), ["mcp-servers.json"])


if __name__ == "__main__":
    unittest.main()
