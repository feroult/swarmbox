"""The opencode tool.

install.sh runs against a FAKE npm that builds a fake package tree (the layout measured for @opencode/cli 2.2.6 in spike:
several platform builds, bin/opencode.exe hard-linked to one of them). prepare.sh runs in a mktemp tree. The real npm and the
real package are NOT used here (that is tests/test_tool_real.py). Run with: python3 -W error tests/test_tool_opencode.py   (needs bash, jq)
"""
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import ROOT  # noqa: E402

TOOLDIR = os.path.join(ROOT, "container", "tools", "opencode")
TOOL = os.path.join(ROOT, "container", "scripts", "swarmbox-tool.sh")
LIB = os.path.join(ROOT, "container", "scripts")
FRAGMENT = os.path.join(ROOT, "container", "config", "bashrc.sh")
REAL_TOOLS = os.path.join(ROOT, "container", "tools")

# A fake npm: `npm install -g --prefix P PKG@V` builds the package tree; `npm cache clean --force` is recorded.
# FAKE_BUILDS: space separated build names; FAKE_LINK: the one bin/opencode.exe is hard-linked to ("none": a plain copy).
FAKE_NPM = r"""#!/bin/bash
echo "npm $*" >> "$FAKE_CALLS"
echo "cwd=$PWD" >> "$FAKE_CALLS"
echo "scratch=${npm_config_devdir:-unset}|${XDG_DATA_HOME:-unset}" >> "$FAKE_CALLS"
[ -z "${XDG_DATA_HOME:-}" ] || { mkdir -p "$XDG_DATA_HOME/opencode/log"; echo l > "$XDG_DATA_HOME/opencode/log/opencode.log"; }
if [ "$1" = cache ]; then exit "${FAKE_CACHE_EXIT:-0}"; fi
[ "$1" = install ] || exit 2
[ -z "${FAKE_NPM_FAIL:-}" ] || { echo "npm ERR! network" >&2; exit 1; }
shift
prefix=""
while [ $# -gt 0 ]; do
    case "$1" in --prefix) prefix=$2; shift 2 ;; -g) shift ;; *) pkg=$1; shift ;; esac
done
pkgdir="$prefix/lib/node_modules/${pkg%@*}"
rm -rf "$pkgdir"
mkdir -p "$pkgdir/bin" "$prefix/bin"
for b in $FAKE_BUILDS; do
    mkdir -p "$pkgdir/node_modules/@opencode/$b/bin"
    printf '#!/bin/sh\n%s\necho "opencode fake from %s"\n' "${FAKE_BREAK:+exit 1}" "$b" > "$pkgdir/node_modules/@opencode/$b/bin/opencode"
    chmod +x "$pkgdir/node_modules/@opencode/$b/bin/opencode"
    dd if=/dev/zero of="$pkgdir/node_modules/@opencode/$b/blob" bs=1k count=64 2>/dev/null
done
if [ "$FAKE_LINK" = none ]; then
    printf '#!/bin/sh\necho "opencode fake copy"\n' > "$pkgdir/bin/opencode.exe"; chmod +x "$pkgdir/bin/opencode.exe"
else
    ln "$pkgdir/node_modules/@opencode/$FAKE_LINK/bin/opencode" "$pkgdir/bin/opencode.exe"
fi
ln -sf "../lib/node_modules/${pkg%@*}/bin/opencode.exe" "$prefix/bin/opencode"
"""

ALL_BUILDS = "cli-linux-x64 cli-linux-x64-musl cli-linux-arm64 cli-darwin-arm64"


def write(path, text, mode=None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(text)
    if mode:
        os.chmod(path, mode)


def read(path):
    with open(path) as f:
        return f.read()


class InstallTest(unittest.TestCase):
    def setUp(self):
        self.base = tempfile.mkdtemp(prefix="opencode-install-")
        self.addCleanup(shutil.rmtree, self.base, ignore_errors=True)
        self.prefix = os.path.join(self.base, "prefix")
        self.home = os.path.join(self.base, "home")
        self.fakebin = os.path.join(self.base, "fakebin")
        self.calls = os.path.join(self.base, "calls.txt")
        os.makedirs(self.prefix)
        os.makedirs(self.home)
        write(os.path.join(self.fakebin, "npm"), FAKE_NPM, 0o755)

    def install(self, arch="amd64", version="latest", builds=ALL_BUILDS, link="cli-linux-x64", **extra):
        env = {"PATH": self.fakebin + ":/usr/bin:/bin", "HOME": self.home, "TOOL_PREFIX": self.prefix, "TOOL_VERSION": version,
               "TOOL_ARCH": arch, "FAKE_CALLS": self.calls, "FAKE_BUILDS": builds, "FAKE_LINK": link}
        env.update(extra)
        return subprocess.run(["bash", os.path.join(TOOLDIR, "install.sh")], env=env, capture_output=True, text=True,
                              timeout=60, cwd=self.home)

    def pkgdir(self):
        return os.path.join(self.prefix, "lib", "node_modules", "@opencode", "cli")

    def builds(self):
        d = os.path.join(self.pkgdir(), "node_modules", "@opencode")
        return sorted(os.listdir(d)) if os.path.isdir(d) else []

    def test_installs_the_package_under_the_prefix_and_cleans_the_cache(self):
        r = self.install()
        self.assertEqual(r.returncode, 0, r.stderr)
        calls = read(self.calls).splitlines()
        self.assertIn("npm install -g --prefix %s @opencode/cli@latest" % self.prefix, calls)
        self.assertIn("npm cache clean --force", calls)
        self.assertLess(calls.index("npm cache clean --force"), len(calls))
        self.assertEqual(r.stdout, "")   # stdout belongs to the tool

    def test_amd64_prunes_the_other_builds_and_keeps_the_linked_one(self):
        r = self.install(arch="amd64")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.builds(), ["cli-linux-x64"])
        out = subprocess.run([os.path.join(self.prefix, "bin", "opencode"), "--version"], capture_output=True, text=True)
        self.assertEqual(out.returncode, 0)
        self.assertIn("cli-linux-x64", out.stdout)

    def test_a_program_that_does_not_run_after_the_prune_fails_the_install(self):
        r = self.install(FAKE_BREAK="1")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("does not run", r.stderr)

    def test_the_whole_thing_through_swarmbox_tool_install(self):
        # the real manifest, the real install.sh, the fake npm: a complete managed install with the version folder and link
        image = os.path.join(self.base, "image")
        shutil.copytree(TOOLDIR, os.path.join(image, "opencode"))
        env = {"PATH": self.fakebin + ":/usr/bin:/bin", "HOME": self.home, "SWARMBOX_TEST_LIB": LIB,
               "SWARMBOX_TEST_IMAGE_TOOLS": image, "SWARMBOX_TEST_USER_TOOLS": os.path.join(self.base, "user"),
               "SWARMBOX_TEST_HOST_DIR": os.path.join(self.base, "host"), "SWARMBOX_TEST_ARCH": "amd64",
               "SWARMBOX_TEST_LOCK": os.path.join(self.base, "lock"), "FAKE_CALLS": self.calls, "FAKE_BUILDS": ALL_BUILDS,
               "FAKE_LINK": "cli-linux-x64", "SWARMBOX_TEST_RUN_DIR": os.path.join(self.base, "run"), "TMPDIR": self.base}
        r = subprocess.run(["bash", TOOL, "install", "opencode"], env=env, capture_output=True, text=True, timeout=60, cwd=self.base)
        self.assertEqual(r.returncode, 0, r.stderr)
        tools = os.path.join(self.home, ".local", "share", "swarmbox", "tools", "opencode")
        self.assertEqual(os.readlink(os.path.join(tools, "current")), "latest")
        self.assertTrue(os.access(os.path.join(tools, "current", "bin", "opencode"), os.X_OK))
        # and the prepare.sh that ran after the install rendered the configuration
        self.assertTrue(os.path.exists(os.path.join(self.base, "run", "opencode.json")), r.stderr)


class PrepareRenderTest(unittest.TestCase):
    def setUp(self):
        self.base = tempfile.mkdtemp(prefix="opencode-prepare-")
        self.addCleanup(shutil.rmtree, self.base, ignore_errors=True)
        self.home = os.path.join(self.base, "home")
        self.run_dir = os.path.join(self.base, "run", "swarmbox")
        os.makedirs(os.path.join(self.home, ".claude"))
        self.out = os.path.join(self.run_dir, "opencode.json")
        self.src = os.path.join(self.home, ".claude", "mcp-servers.json")

    def prepare(self, **env):
        e = {"PATH": os.environ["PATH"], "HOME": self.home, "SWARMBOX_TEST_LIB": LIB, "SWARMBOX_TEST_RUN_DIR": self.run_dir,
             "LANG": "C.UTF-8"}
        e.update(env)
        return subprocess.run(["bash", os.path.join(TOOLDIR, "prepare.sh")], env=e, capture_output=True, text=True, timeout=30,
                              cwd=self.home)

    def data(self):
        return json.loads(read(self.out))

    def test_unset_gives_no_local_provider_and_autoupdate_false(self):
        r = self.prepare()
        self.assertEqual(r.returncode, 0, r.stderr)
        d = self.data()
        self.assertNotIn("provider", d)
        self.assertNotIn("model", d)
        self.assertIs(d["autoupdate"], False)
        self.assertEqual(d["$schema"], "https://opencode.ai/config.json")

    def test_set_gives_the_local_provider(self):
        r = self.prepare(LOCAL_LLM_URL="http://127.0.0.1:8000/v1", LOCAL_LLM_MODEL="qwen-test", LOCAL_LLM_KEY="sk-x",
                         LOCAL_LLM_CONTEXT="32768", LOCAL_LLM_OUTPUT="4096")
        self.assertEqual(r.returncode, 0, r.stderr)
        d = self.data()
        p = d["provider"]["local"]
        self.assertEqual(p["options"], {"baseURL": "http://127.0.0.1:8000/v1", "apiKey": "sk-x"})
        self.assertEqual(p["models"], {"qwen-test": {"name": "qwen-test", "limit": {"context": 32768, "output": 4096}}})
        self.assertEqual(p["npm"], "@ai-sdk/openai-compatible")
        self.assertEqual(d["model"], "local/qwen-test")
        self.assertIs(d["autoupdate"], False)

    def test_mirror_mapping(self):
        write(self.src, json.dumps({"mcpServers": {
            "chrome-devtools": {"command": "chrome-devtools-mcp", "args": ["--executablePath=/usr/bin/chromium"]},
            "withenv": {"command": "srv", "env": {"K": "v"}},
            "noargs": {"command": "bare"}}}))
        r = self.prepare()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.data()["mcp"], {
            "chrome-devtools": {"type": "local", "command": ["chrome-devtools-mcp", "--executablePath=/usr/bin/chromium"], "enabled": True},
            "withenv": {"type": "local", "command": ["srv"], "enabled": True, "environment": {"K": "v"}},
            "noargs": {"type": "local", "command": ["bare"], "enabled": True}})

class ManifestTest(unittest.TestCase):
    def validate(self, folder):
        return subprocess.run(["bash", TOOL, "validate", folder], capture_output=True, text=True, timeout=60,
                              env={"PATH": "/usr/bin:/bin", "HOME": "/nonexistent", "SWARMBOX_TEST_LIB": LIB}, cwd=ROOT)

    def conf(self):
        return read(os.path.join(TOOLDIR, "tool.conf"))

    def test_the_real_tools_folder_validates_with_claude_and_opencode(self):
        r = self.validate(REAL_TOOLS)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("claude", r.stdout)
        self.assertIn("opencode", r.stdout)

if __name__ == "__main__":
    unittest.main()
