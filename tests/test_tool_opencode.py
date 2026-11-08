"""Slice 4b.2: the opencode tool (design 6.3, 6.4, 6.6, 6.12, 4.4; D3, D4, B2, B10).

install.sh runs against a FAKE npm that builds a fake package tree (the layout measured for @opencode/cli 2.2.6 in spike B10:
several platform builds, bin/opencode.exe hard-linked to one of them). prepare.sh runs in a mktemp tree. The real npm and the
real package are NOT used here (that is slice 4b.7, reduced). Run with: python3 -W error tests/test_tool_opencode.py   (needs bash, jq)
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
        self.assertEqual(r.stdout, "")   # stdout belongs to the tool (6.4)

    def test_the_install_runs_in_a_scratch_environment_that_is_removed(self):
        """Measured in 4b.7: the package's postinstall ran the program, which wrote ~/.local/share/opencode/log/opencode.log."""
        r = self.install()
        self.assertEqual(r.returncode, 0, r.stderr)
        line = [l for l in read(self.calls).splitlines() if l.startswith("scratch=")][0][len("scratch="):]
        gyp, data = line.split("|")
        for d in (gyp, data):
            self.assertNotEqual(d, "unset")
            self.assertFalse(d.startswith(self.home), d)
            self.assertFalse(os.path.exists(d), "left behind: " + d)
        self.assertFalse(os.path.exists(os.path.join(self.home, ".local")))

    def test_a_pinned_version_is_passed_to_npm(self):
        self.install(version="2.2.6")
        self.assertIn("@opencode/cli@2.2.6", read(self.calls))

    def test_writes_nothing_outside_the_prefix(self):
        before = set(os.listdir(self.home))
        self.install()
        self.assertEqual(set(os.listdir(self.home)), before)
        self.assertEqual(sorted(os.listdir(self.base)), ["calls.txt", "fakebin", "home", "prefix"])

    def test_amd64_prunes_the_other_builds_and_keeps_the_linked_one(self):
        r = self.install(arch="amd64")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.builds(), ["cli-linux-x64"])
        out = subprocess.run([os.path.join(self.prefix, "bin", "opencode"), "--version"], capture_output=True, text=True)
        self.assertEqual(out.returncode, 0)
        self.assertIn("cli-linux-x64", out.stdout)

    def test_arm64_keeps_the_arm64_build(self):
        r = self.install(arch="arm64", link="cli-linux-arm64")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.builds(), ["cli-linux-arm64"])
        out = subprocess.run([os.path.join(self.prefix, "bin", "opencode")], capture_output=True, text=True)
        self.assertIn("cli-linux-arm64", out.stdout)

    def test_the_musl_build_is_kept_when_that_is_the_one_linked(self):
        r = self.install(link="cli-linux-x64-musl")
        self.assertEqual(r.returncode, 0, r.stderr)
        # the plain amd64 build stays too: the current architecture's build is never removed (safer than saving 250 MB more)
        self.assertEqual(self.builds(), ["cli-linux-x64", "cli-linux-x64-musl"])

    def test_the_current_architecture_build_is_never_removed_even_when_not_the_linked_one(self):
        # a wrong link (here to darwin) must not delete the amd64 build of an amd64 box
        r = self.install(arch="amd64", link="cli-darwin-arm64")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("cli-linux-x64", self.builds())
        self.assertIn("cli-darwin-arm64", self.builds())
        self.assertNotIn("cli-linux-arm64", self.builds())

    def test_when_no_build_is_linked_nothing_is_removed(self):
        r = self.install(link="none")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.builds(), sorted(ALL_BUILDS.split()))
        self.assertIn("nothing removed", r.stderr)

    def test_the_prune_saves_space(self):
        self.install(link="none")
        full = subprocess.run(["du", "-sk", self.prefix], capture_output=True, text=True).stdout.split()[0]
        shutil.rmtree(self.prefix)
        os.makedirs(self.prefix)
        self.install()
        pruned = subprocess.run(["du", "-sk", self.prefix], capture_output=True, text=True).stdout.split()[0]
        self.assertLess(int(pruned), int(full) - 150)

    def test_a_failing_npm_fails_the_install(self):
        r = self.install(FAKE_NPM_FAIL="1")
        self.assertNotEqual(r.returncode, 0)

    def test_a_program_that_does_not_run_after_the_prune_fails_the_install(self):
        r = self.install(FAKE_BREAK="1")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("does not run", r.stderr)

    def test_a_failing_cache_clean_is_only_a_warning(self):
        r = self.install(FAKE_CACHE_EXIT="1")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("warning", r.stderr)

    def test_idempotent(self):
        self.assertEqual(self.install().returncode, 0)
        self.assertEqual(self.install().returncode, 0)
        self.assertEqual(self.builds(), ["cli-linux-x64"])

    def test_the_package_name_is_one_variable(self):
        text = read(os.path.join(TOOLDIR, "install.sh"))
        self.assertEqual([l for l in text.splitlines() if l.startswith("PACKAGE=")], ['PACKAGE="@opencode/cli"'])
        code = [l for l in text.splitlines() if not l.lstrip().startswith("#")]
        self.assertEqual([l for l in code if "@opencode/cli" in l and not l.startswith("PACKAGE=")], [])

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

    def test_empty_url_is_off_too(self):
        r = self.prepare(LOCAL_LLM_URL="", LOCAL_LLM_MODEL="m")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("provider", self.data())

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

    def test_defaults_for_key_context_and_output(self):
        self.prepare(LOCAL_LLM_URL="http://h/v1", LOCAL_LLM_MODEL="m")
        p = self.data()["provider"]["local"]
        self.assertEqual(p["options"]["apiKey"], "sk-local")
        self.assertEqual(p["models"]["m"]["limit"], {"context": 65536, "output": 8192})

    def test_a_url_without_a_model_leaves_the_provider_out_and_says_so(self):
        r = self.prepare(LOCAL_LLM_URL="http://h/v1")
        self.assertEqual(r.returncode, 1)
        self.assertIn("LOCAL_LLM_MODEL", r.stderr)
        self.assertNotIn("provider", self.data())

    def test_a_bad_number_leaves_the_provider_out_and_says_so(self):
        r = self.prepare(LOCAL_LLM_URL="http://h/v1", LOCAL_LLM_MODEL="m", LOCAL_LLM_CONTEXT="lots")
        self.assertEqual(r.returncode, 1)
        self.assertIn("whole numbers", r.stderr)
        self.assertNotIn("provider", self.data())

    def test_a_model_name_with_quotes_stays_valid_json(self):
        self.prepare(LOCAL_LLM_URL="http://h/v1", LOCAL_LLM_MODEL='we"ird $name')
        self.assertIn('we"ird $name', self.data()["provider"]["local"]["models"])

    def test_file_mode_is_600_and_nothing_else_is_left_in_the_folder(self):
        self.prepare(LOCAL_LLM_URL="http://h/v1", LOCAL_LLM_MODEL="m", LOCAL_LLM_KEY="secret")
        self.assertEqual(stat.S_IMODE(os.stat(self.out).st_mode), 0o600)
        self.assertEqual(os.listdir(self.run_dir), ["opencode.json"])

    def test_idempotent_byte_for_byte(self):
        write(self.src, '{"mcpServers": {"a": {"command": "x", "args": ["1"]}}}')
        env = dict(LOCAL_LLM_URL="http://h/v1", LOCAL_LLM_MODEL="m")
        self.prepare(**env)
        first = read(self.out)
        self.prepare(**env)
        self.assertEqual(read(self.out), first)

    def test_the_old_file_is_replaced_not_merged(self):
        self.prepare(LOCAL_LLM_URL="http://h/v1", LOCAL_LLM_MODEL="m")
        self.prepare()
        self.assertNotIn("provider", self.data())

    def test_no_mcp_file_means_no_mcp_key(self):
        self.prepare()
        self.assertNotIn("mcp", self.data())

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

    def test_an_empty_server_list_gives_an_empty_mcp_object(self):
        write(self.src, '{"mcpServers": {}}')
        self.prepare()
        self.assertEqual(self.data()["mcp"], {})

    def test_a_broken_mcp_file_is_reported_and_the_rest_is_still_written(self):
        write(self.src, "{not json")
        r = self.prepare(LOCAL_LLM_URL="http://h/v1", LOCAL_LLM_MODEL="m")
        self.assertEqual(r.returncode, 1)
        self.assertIn("not a usable MCP file", r.stderr)
        d = self.data()
        self.assertNotIn("mcp", d)
        self.assertEqual(d["model"], "local/m")

    def test_the_mirror_equals_the_v0_1_0_function(self):
        # the old sync_opencode_mcp, extracted from the tag and run on the same inputs
        old = subprocess.run(["git", "-C", ROOT, "show", "v0.1.0:container/scripts/init.sh"], capture_output=True, text=True)
        if old.returncode != 0:
            self.skipTest("the tag v0.1.0 is not in this clone")
        text = old.stdout
        start = text.index("sync_opencode_mcp() {")
        end = text.index("\n}\n", start) + 3
        func = text[start:end]
        fixtures = [
            {"mcpServers": {"chrome-devtools": {"command": "npx", "args": ["-y", "chrome-devtools-mcp@latest", "--x"]}}},
            {"mcpServers": {"a": {"command": "x"}, "b": {"command": "y", "args": [], "env": {"A": "1", "B": "2"}}}},
            {"mcpServers": {}},
            {"mcpServers": {"m": {"command": "z", "args": ["p q", "$HOME"], "env": {}}}},
        ]
        for i, fx in enumerate(fixtures):
            with self.subTest(i=i):
                write(self.src, json.dumps(fx))
                sdir = os.path.join(self.base, "old%d" % i)
                os.makedirs(sdir)
                base_cfg = os.path.join(sdir, "opencode-local.json")
                write(base_cfg, json.dumps({"autoupdate": False}))
                script = "SWARMBOX_DIR=%s\nHOME=%s\n%s\nsync_opencode_mcp\n" % (sdir, self.home, func)
                r = subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=30)
                self.assertEqual(r.returncode, 0, r.stderr)
                new = self.prepare()
                self.assertEqual(new.returncode, 0, new.stderr)
                self.assertEqual(json.loads(read(base_cfg))["mcp"], self.data()["mcp"])

    def test_works_with_the_generated_mcp_file_of_4b_1(self):
        gen = subprocess.run(["bash", os.path.join(LIB, "swarmbox-mcp.sh"), "generate"],
                             env={"PATH": os.environ["PATH"], "HOME": self.home, "SWARMBOX_TEST_LIB": LIB,
                                  "SWARMBOX_TEST_MCP_DIR": os.path.join(ROOT, "container", "mcp")},
                             capture_output=True, text=True, timeout=30)
        self.assertEqual(gen.returncode, 0, gen.stderr)
        self.assertEqual(self.prepare().returncode, 0)
        m = self.data()["mcp"]["chrome-devtools"]
        self.assertEqual(m["command"][0], "chrome-devtools-mcp")
        self.assertTrue(m["enabled"])

    def test_the_template_is_valid_and_both_copies_agree(self):
        t = json.loads(read(os.path.join(TOOLDIR, "local-llm.json")))
        self.assertIs(t["autoupdate"], False)
        old = os.path.join(ROOT, "container", "opencode", "local-llm.json")   # kept for Dockerfile.v0.1.0 until Phase 6
        if os.path.exists(old):
            self.assertEqual(read(old), read(os.path.join(TOOLDIR, "local-llm.json")))

    def test_an_unwritable_run_folder_exits_2(self):
        os.makedirs(os.path.dirname(self.run_dir))
        write(self.run_dir, "a file, not a folder")
        r = self.prepare()
        self.assertEqual(r.returncode, 2)

    def test_prepare_writes_only_the_one_file(self):
        before = subprocess.run(["find", self.home], capture_output=True, text=True).stdout
        self.prepare(LOCAL_LLM_URL="http://h/v1", LOCAL_LLM_MODEL="m")
        self.assertEqual(subprocess.run(["find", self.home], capture_output=True, text=True).stdout, before)


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

    def test_manifest_values(self):
        out = subprocess.run(["bash", "-c", ". %s/tool.conf; echo \"$KIND|$PROVIDES|$VERSION|${UPDATE:-managed}|$MCP_FORMAT|$YOLO_FLAGS|"
                              "$YOLO_ALIAS|${PORTS:-}|${MCP_FLAGS:-}\"" % TOOLDIR], capture_output=True, text=True).stdout.strip()
        self.assertEqual(out, "agent|opencode|latest|managed|opencode|--auto|0||")

    def test_files_and_modes(self):
        for f in ("install.sh", "prepare.sh", "shell.sh", "tool.conf", "local-llm.json"):
            self.assertTrue(os.path.isfile(os.path.join(TOOLDIR, f)), f)
        self.assertTrue(os.access(os.path.join(TOOLDIR, "install.sh"), os.X_OK))

    def test_mcp_format_values(self):
        for value, ok in (("opencode", True), ("claude", True), ("", True), ("gemini", False), ("OpenCode", False)):
            with self.subTest(value=value):
                d = tempfile.mkdtemp(prefix="opencode-mcpfmt-")
                self.addCleanup(shutil.rmtree, d, ignore_errors=True)
                t = os.path.join(d, "opencode")
                shutil.copytree(TOOLDIR, t)
                write(os.path.join(t, "tool.conf"), self.conf().replace("MCP_FORMAT=opencode", "MCP_FORMAT=%s" % value))
                r = self.validate(d)
                self.assertEqual(r.returncode == 0, ok, r.stdout + r.stderr)
                if not ok:
                    self.assertIn("MCP_FORMAT", r.stdout + r.stderr)

    def test_the_shim_exists_ports_are_empty_and_no_yolo_alias(self):
        d = tempfile.mkdtemp(prefix="opencode-link-")
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        env = {"PATH": "/usr/bin:/bin", "HOME": d, "SWARMBOX_TEST_LIB": LIB, "SWARMBOX_TEST_IMAGE_TOOLS": REAL_TOOLS,
               "SWARMBOX_TEST_USER_TOOLS": os.path.join(d, "u"), "SWARMBOX_TEST_HOST_DIR": os.path.join(d, "host"),
               "SWARMBOX_TEST_IMAGE_SHIMS": os.path.join(d, "shims")}
        r = subprocess.run(["bash", TOOL, "link", "--system"], env=env, capture_output=True, text=True, timeout=60, cwd=d)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(os.path.islink(os.path.join(d, "shims", "opencode")) or os.path.exists(os.path.join(d, "shims", "opencode")))
        ports = read(os.path.join(d, "host", "tool-ports"))
        self.assertNotIn("opencode", ports)

    def test_bashrc_fragment_makes_no_opencode_alias_but_yolo_works(self):
        d = tempfile.mkdtemp(prefix="opencode-frag-")
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        env = {"PATH": "/usr/bin:/bin", "HOME": d, "XDG_CONFIG_HOME": os.path.join(d, "c"), "XDG_DATA_HOME": os.path.join(d, "d"),
               "XDG_STATE_HOME": os.path.join(d, "s"), "SWARMBOX_AGENT": "opencode", "SWARMBOX_TEST_IMAGE_TOOLS": REAL_TOOLS,
               "SWARMBOX_TEST_LIB": LIB, "SWARMBOX_TEST_NO_BANNER": "1"}
        script = ". %s\nalias opencode 2>&1 | head -n 1\ntype yolo | head -n 1\n" % FRAGMENT
        r = subprocess.run(["bash", "--norc", "-i"], input=script, env=env, capture_output=True, text=True, timeout=30, cwd=d)
        out = r.stdout
        self.assertNotIn("alias opencode=", out)
        self.assertIn("yolo is a function", out)

    def test_shell_sh_exports_the_config_path(self):
        r = subprocess.run(["bash", "-c", ". %s/shell.sh; echo $OPENCODE_CONFIG" % TOOLDIR], capture_output=True, text=True)
        self.assertEqual(r.stdout.strip(), "/tmp/swarmbox/opencode.json")


if __name__ == "__main__":
    unittest.main()
