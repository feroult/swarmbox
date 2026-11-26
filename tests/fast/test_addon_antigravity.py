"""The antigravity addon (command agy): its installer with a fake vendor server, and its manifest.

The real install (the vendor's release server) is in tests/slow/test_addon_real.py. Run with: python3 -W error tests/fast/test_addon_antigravity.py
"""
import colorsys
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "support"))
from helpers import ROOT  # noqa: E402

ADDON = os.path.join(ROOT, "container", "addons", "antigravity")
INSTALL = os.path.join(ADDON, "install.sh")
MCP_SH = os.path.join(ADDON, "agent", "mcp.sh")
ADDON_SH = os.path.join(ROOT, "container", "scripts", "swarmbox-addon.sh")
STATUSLINE = os.path.join(ADDON, "statusline.sh")
LIB = os.path.join(ROOT, "container", "scripts")
SGR = re.compile(r"\x1b\[[0-9;]*m")
VIOLET, LAVENDER, FUCHSIA, ROSE = 147, 189, 177, 204


def plain(text):
    return SGR.sub("", text)


def rgb256(n):
    if n >= 232:
        v = 8 + 10 * (n - 232)
        return (v, v, v)
    n -= 16
    lv = (0, 95, 135, 175, 215, 255)
    return (lv[n // 36], lv[n // 6 % 6], lv[n % 6])

# the fake vendor server: the manifest names the tarball by a path under FAKE_SERVER; every call is recorded
FAKE_CURL = r"""#!/bin/sh
echo "curl $*" >> "$FAKE_CALLS"
out=""
while [ $# -gt 0 ]; do
    case "$1" in -o) out=$2; shift ;; -*) ;; *) url=$1 ;; esac
    shift
done
[ -z "${FAKE_CURL_FAIL:-}" ] || exit 22
case "$url" in
    */manifests/*) f="$FAKE_SERVER/manifest.json" ;;
    *) f="$FAKE_SERVER/payload.tar.gz" ;;
esac
if [ -n "$out" ]; then cp "$f" "$out"; else cat "$f"; fi
"""
AGY = '#!/bin/sh\necho "1.2.3"\necho "$HOME" >> "$FAKE_CALLS"\n'


class InstallTest(unittest.TestCase):
    def setUp(self):
        self.base = tempfile.mkdtemp(prefix="agy-install-")
        self.addCleanup(shutil.rmtree, self.base, ignore_errors=True)
        self.home = os.path.join(self.base, "home")
        self.prefix = os.path.join(self.base, "prefix")
        self.server = os.path.join(self.base, "server")
        self.fakebin = os.path.join(self.base, "fakebin")
        self.calls = os.path.join(self.base, "calls.txt")
        for d in (self.home, self.server, self.fakebin):
            os.makedirs(d)
        with open(self.calls, "w"):
            pass
        with open(os.path.join(self.fakebin, "curl"), "w") as f:
            f.write(FAKE_CURL)
        os.chmod(os.path.join(self.fakebin, "curl"), 0o755)
        self.publish()

    def publish(self, sha=None, url="https://example.invalid/agy/cli_linux_x64.tar.gz"):
        src = os.path.join(self.server, "antigravity")
        with open(src, "w") as f:
            f.write(AGY)
        os.chmod(src, 0o755)
        tgz = os.path.join(self.server, "payload.tar.gz")
        with tarfile.open(tgz, "w:gz") as t:
            t.add(src, arcname="antigravity")
        with open(tgz, "rb") as f:
            digest = hashlib.sha512(f.read()).hexdigest()
        with open(os.path.join(self.server, "manifest.json"), "w") as f:
            f.write('{\n  "version": "1.2.3",\n  "url": "%s",\n  "sha512": "%s"\n}\n' % (url, sha or digest))

    def install(self, version="latest", arch="amd64", **env):
        e = {"PATH": self.fakebin + ":/usr/bin:/bin", "HOME": self.home, "ADDON_PREFIX": self.prefix, "ADDON_ARCH": arch,
             "FAKE_SERVER": self.server, "FAKE_CALLS": self.calls, "TMPDIR": self.base}
        if version is not None:
            e["ADDON_VERSION"] = version
        e.update(env)
        return subprocess.run(["bash", INSTALL], env=e, capture_output=True, text=True, timeout=60, cwd=self.base)

    def test_installs_agy_into_the_local_bin_and_records_it(self):
        r = self.install()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout, "")  # stdout belongs to the addon
        agy = os.path.join(self.home, ".local", "bin", "agy")
        self.assertTrue(os.access(agy, os.X_OK))
        with open(os.path.join(self.prefix, "installed")) as f:
            self.assertEqual(f.read(), "requested=latest\nreported=1.2.3\narch=amd64\n")

    def test_the_manifest_asked_for_is_the_one_of_the_platform(self):
        self.assertEqual(self.install(arch="arm64").returncode, 0)
        with open(self.calls) as f:
            self.assertIn("/manifests/linux_arm64.json", f.read())

    def test_the_vendor_installer_is_never_run_and_nothing_else_is_written(self):
        self.assertEqual(self.install().returncode, 0)
        found = []
        for root, dirs, files in os.walk(self.base):
            if root.startswith((self.prefix, self.fakebin, self.server)):
                continue
            found += [os.path.relpath(os.path.join(root, n), self.base) for n in files + dirs]
        self.assertEqual(sorted(f for f in found if f not in ("home", "prefix", "fakebin", "server", "calls.txt")),
                         [os.path.join("home", ".local"), os.path.join("home", ".local", "bin"), os.path.join("home", ".local", "bin", "agy")])
        with open(self.calls) as f:
            self.assertNotIn("install.sh", f.read())

    def test_the_version_check_does_not_touch_the_home_of_the_user(self):
        self.assertEqual(self.install().returncode, 0)
        with open(self.calls) as f:
            homes = [line.strip() for line in f if line.startswith("/")]
        self.assertTrue(homes)
        self.assertNotIn(self.home, homes)

    def test_a_download_that_does_not_match_the_checksum_installs_nothing(self):
        self.publish(sha="0" * 128)
        r = self.install()
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("SHA-512", r.stderr)
        self.assertFalse(os.path.exists(os.path.join(self.home, ".local", "bin", "agy")))
        self.assertFalse(os.path.exists(os.path.join(self.prefix, "installed")))

    def test_a_url_that_is_not_https_is_refused(self):
        self.publish(url="http://example.invalid/agy.tar.gz")
        r = self.install()
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("https", r.stderr)

    def test_a_failing_download_fails_the_install(self):
        r = self.install(FAKE_CURL_FAIL="1")
        self.assertNotEqual(r.returncode, 0)
        self.assertFalse(os.path.exists(os.path.join(self.prefix, "installed")))

    def test_a_pinned_version_is_refused_because_the_vendor_offers_only_the_newest(self):
        r = self.install(version="1.0.0")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("newest", r.stderr)
        self.assertFalse(os.path.exists(os.path.join(self.home, ".local", "bin", "agy")))

    def test_a_missing_version_falls_back_to_latest(self):
        self.assertEqual(self.install(version=None).returncode, 0)

    def test_an_unsupported_architecture_is_refused(self):
        self.assertNotEqual(self.install(arch="riscv64").returncode, 0)

    def test_a_running_agy_is_replaced_by_a_rename_and_not_overwritten(self):
        self.assertEqual(self.install().returncode, 0)
        agy = os.path.join(self.home, ".local", "bin", "agy")
        before = os.stat(agy).st_ino
        os.remove(self.calls)
        open(self.calls, "w").close()
        self.assertEqual(self.install().returncode, 0)
        self.assertNotEqual(os.stat(agy).st_ino, before)
        self.assertEqual([n for n in os.listdir(os.path.dirname(agy))], ["agy"])  # no temporary file is left


@unittest.skipUnless(shutil.which("jq") and shutil.which("git"), "needs jq and git")
class StatuslineTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="agy-statusline-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.home = os.path.join(self.tmp, "home")
        self.repo = os.path.join(self.home, "work", "a", "swarmbox")
        os.makedirs(self.repo)
        git = lambda *a: subprocess.run(("git", "-c", "user.email=t@t", "-c", "user.name=t") + a, cwd=self.repo, check=True, capture_output=True)
        git("init", "-q", "-b", "main", ".")
        with open(os.path.join(self.repo, "f"), "w") as f:
            f.write("x\n")
        git("add", "f")
        git("commit", "-q", "-m", "first")

    def run_line(self, doc, raw=None, **env):
        e = {"PATH": os.environ["PATH"], "HOME": self.home, "LANG": "C.UTF-8"}
        e.update(env)
        r = subprocess.run(["bash", STATUSLINE], input=raw if raw is not None else json.dumps(doc), env=e, capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stderr, "")
        return r.stdout.rstrip("\n")

    def doc(self, ctx=34, in_tok=88244, out_tok=61074, cost=None, quota=None, cwd=None, model="Gemini 4 Neon (High)", width=None, subagents=None, tasks=None):
        d = {
            "product": "antigravity",
            "workspace": {"current_dir": cwd or self.repo},
            "model": {"display_name": model},
            "context_window": {"used_percentage": ctx, "total_input_tokens": in_tok, "total_output_tokens": out_tok},
        }
        if cost is not None:
            d["cost"] = {"total_usd": cost}
        if quota is not None:
            d["quota"] = quota
        if width is not None:
            d["terminal_width"] = width
        if subagents is not None:
            d["subagents"] = subagents
        if tasks is not None:
            d["task_count"] = tasks
        return d

    def test_renders_directory_branch_model_context_bar_and_tokens(self):
        out = plain(self.run_line(self.doc(34.4)))
        self.assertEqual(out, "╶─ …/a/swarmbox ─ main ─ Gemini 4 Neon (High) ─ ▰▰▰▱▱▱▱▱▱▱ 34% 149k")

    def test_formats_millions_of_tokens_and_dirty_repo_and_home_tilde(self):
        with open(os.path.join(self.repo, "f"), "a") as f:
            f.write("changed\n")
        out = plain(self.run_line(self.doc(62, in_tok=950000, out_tok=300000)))
        self.assertIn("main ! ─", out)
        self.assertIn("62% 1.2M", out)
        self.assertEqual(plain(self.run_line(self.doc(ctx=12, in_tok=0, out_tok=0, cwd=self.home))),
                         "╶─ ~ ─ Gemini 4 Neon (High) ─ ▰▱▱▱▱▱▱▱▱▱ 12%")

    def test_renders_cost_quotas_and_active_background_work(self):
        quota = {
            "gemini-weekly": {"remaining_fraction": 0.9378, "reset_in_seconds": 560580},
            "gemini-5h": {"remaining_fraction": 0.25, "reset_in_seconds": 7200},
            "ignored-disabled": {"remaining_fraction": 0.1, "disabled": True},
        }
        subagents = [{"name": "a", "status": "running"}, {"name": "b", "status": "completed"}]
        out = plain(self.run_line(self.doc(14.2, cost=0.4213, quota=quota, subagents=subagents, tasks=2)))
        self.assertTrue(out.endswith("14% 149k ─ $0.42 ─ 5h 75% ─ 7d 6% ─ 1 sub 2 task"), out)

    def test_colors_escalate_violet_to_fuchsia_to_rose_with_no_orange(self):
        def codes(doc):
            return {int(n) for n in re.findall(r"\x1b\[38;5;(\d+)m", self.run_line(doc))}
        self.assertIn(VIOLET, codes(self.doc(69)))
        self.assertNotIn(FUCHSIA, codes(self.doc(69)))
        self.assertIn(FUCHSIA, codes(self.doc(70)))
        self.assertNotIn(ROSE, codes(self.doc(89)))
        self.assertIn(ROSE, codes(self.doc(90)))
        self.assertIn(FUCHSIA, codes(self.doc(10, quota={"gemini-5h": {"remaining_fraction": 0.28}})))
        self.assertIn(ROSE, codes(self.doc(10, quota={"gemini-weekly": {"remaining_fraction": 0.05}})))
        for ctx, rem in ((0, 1.0), (34, 0.5), (70, 0.3), (95, 0.05)):
            for n in codes(self.doc(ctx, cost=1.5, quota={"gemini-weekly": {"remaining_fraction": rem}})):
                r, g, b = (c / 255 for c in rgb256(n))
                h, s, _ = colorsys.rgb_to_hsv(r, g, b)
                self.assertFalse(15 <= h * 360 <= 50 and s > 0.35, "color %d is orange/amber" % n)

    def test_fits_terminal_width_and_wraps_to_two_lines_on_narrow_screens_keeping_model_and_context(self):
        quota = {"gemini-5h": {"remaining_fraction": 0.3}, "gemini-weekly": {"remaining_fraction": 0.6}}
        full = plain(self.run_line(self.doc(82, cost=1.25, quota=quota, tasks=1)))
        self.assertIn("1 task", full)
        self.assertEqual(len(full.splitlines()), 1)
        trimmed = plain(self.run_line(self.doc(82, cost=1.25, quota=quota, tasks=1, width=len(full) - 2)))
        self.assertNotIn("1 task", trimmed)
        self.assertIn("7d", trimmed)
        self.assertEqual(len(trimmed.splitlines()), 1)
        # Phone width (56 cols): wraps cleanly into two lines so folder, active model, and context stay visible
        phone = plain(self.run_line(self.doc(82, cost=1.25, quota=quota, tasks=1, width=56)))
        lines = phone.splitlines()
        self.assertEqual(len(lines), 2, phone)
        self.assertIn("swarmbox", lines[0])
        self.assertIn("Gemini 4 Neon (High)", lines[1])
        self.assertIn("82%", lines[1])
        for ln in lines:
            self.assertLessEqual(len(ln), 56, ln)
        # Very narrow (40 cols): shrinks the bar to 5 cells and still keeps folder, model, and context %
        tiny = plain(self.run_line(self.doc(82, cost=1.25, quota=quota, tasks=1, width=40)))
        tlines = tiny.splitlines()
        self.assertEqual(len(tlines), 2, tiny)
        self.assertIn("Gemini 4 Neon (High)", tlines[1])
        self.assertIn("82%", tlines[1])
        self.assertIn("▰▰▰▰▱", tlines[1])

    def test_no_color_and_bad_json_never_fail(self):
        out = self.run_line(self.doc(95), NO_COLOR="1")
        self.assertEqual(SGR.findall(out), [])
        self.assertIn("95%", out)
        self.assertEqual(self.run_line(None, raw="not json"), "")
        self.assertEqual(self.run_line(None, raw=""), "")


@unittest.skipUnless(shutil.which("jq"), "needs jq")
class PrepareTest(unittest.TestCase):
    def setUp(self):
        self.base = tempfile.mkdtemp(prefix="agy-prepare-")
        self.addCleanup(shutil.rmtree, self.base, ignore_errors=True)
        self.home = os.path.join(self.base, "home")
        os.makedirs(self.home)
        self.settings = os.path.join(self.home, ".gemini", "antigravity-cli", "settings.json")

    def run_prepare(self):
        """what serve's step 7 runs for the addon: `swarmbox-addon prepare` (its agent/mcp.sh, then its agent/settings.json seeded)"""
        state = os.path.join(self.base, "image-state")
        os.makedirs(state, exist_ok=True)
        e = {"PATH": os.environ["PATH"], "HOME": self.home, "SWARMBOX_TEST_LIB": LIB, "TMPDIR": self.base, "SWARMBOX_WITH": "antigravity",
             "SWARMBOX_TEST_IMAGE_ADDONS": os.path.dirname(ADDON), "SWARMBOX_TEST_USER_ADDONS": os.path.join(self.base, "no-user-addons"),
             "SWARMBOX_TEST_IMAGE_STATE": state, "SWARMBOX_TEST_LOCK": os.path.join(self.base, "lock")}
        return subprocess.run(["bash", ADDON_SH, "prepare"], env=e, capture_output=True, text=True, timeout=60, cwd=self.home)

    def read_settings(self):
        with open(self.settings, encoding="utf-8") as f:
            return json.load(f)

    def test_seeds_default_settings_isolated_to_antigravity_with_mode_600(self):
        r = self.run_prepare()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout, "")
        self.assertTrue(os.path.isfile(self.settings))
        self.assertEqual(stat.S_IMODE(os.stat(self.settings).st_mode), 0o600)
        cfg = self.read_settings()
        self.assertEqual(cfg["statusLine"], {"type": "command", "command": STATUSLINE})
        self.assertEqual(cfg["colorScheme"], "tokyo night")
        self.assertIs(cfg["showFeedbackSurvey"], False)
        self.assertIs(cfg["allowNonWorkspaceAccess"], True)
        # Never touches Claude Code's folder
        self.assertFalse(os.path.exists(os.path.join(self.home, ".claude")))

    def test_merges_missing_defaults_without_overwriting_existing_user_keys(self):
        os.makedirs(os.path.dirname(self.settings), exist_ok=True)
        existing = {
            "colorScheme": "dark",
            "model": "Gemini 4 Neon (High)",
            "trustedWorkspaces": ["/home/agent/proj"],
            "statusLine": {"type": "command", "command": "/my/custom.sh"},
        }
        with open(self.settings, "w", encoding="utf-8") as f:
            json.dump(existing, f)
        r = self.run_prepare()
        self.assertEqual(r.returncode, 0, r.stderr)
        cfg = self.read_settings()
        self.assertEqual(cfg["colorScheme"], "dark")
        self.assertEqual(cfg["model"], "Gemini 4 Neon (High)")
        self.assertEqual(cfg["trustedWorkspaces"], ["/home/agent/proj"])
        self.assertEqual(cfg["statusLine"], {"type": "command", "command": "/my/custom.sh"})
        self.assertIs(cfg["showFeedbackSurvey"], False)
        self.assertIs(cfg["allowNonWorkspaceAccess"], True)

    def test_seeds_only_once_so_user_reset_to_agy_default_is_respected(self):
        self.assertEqual(self.run_prepare().returncode, 0)
        # Simulate user running `/statusline delete` or resetting colorScheme to terminal (agy removes keys matching its defaults)
        with open(self.settings, "w", encoding="utf-8") as f:
            json.dump({"model": "Gemini 4 Neon (High)"}, f)
        self.assertEqual(self.run_prepare().returncode, 0)
        self.assertEqual(self.read_settings(), {"model": "Gemini 4 Neon (High)"})
        # Deleting the file completely re-seeds SwarmBox defaults
        os.unlink(self.settings)
        self.assertEqual(self.run_prepare().returncode, 0)
        self.assertEqual(self.read_settings()["statusLine"]["command"], STATUSLINE)

    def test_broken_settings_json_is_left_untouched_and_reports_error(self):
        os.makedirs(os.path.dirname(self.settings), exist_ok=True)
        with open(self.settings, "w", encoding="utf-8") as f:
            f.write("{not valid json")
        r = self.run_prepare()
        self.assertEqual(r.returncode, 1)
        self.assertIn("not a JSON object", r.stderr)
        with open(self.settings, encoding="utf-8") as f:
            self.assertEqual(f.read(), "{not valid json")


class PrepareMcpTest(unittest.TestCase):
    """agy gets the MCP servers of the box through a plugin of SwarmBox's own, rewritten at every start."""

    run_prepare = PrepareTest.run_prepare

    def setUp(self):
        PrepareTest.setUp(self)
        self.plugin = os.path.join(self.home, ".gemini", "config", "plugins", "swarmbox")
        self.src = os.path.join(self.home, ".local", "share", "swarmbox", "mcp-servers.json")   # the box's list (swarmbox-mcp)
        os.makedirs(os.path.dirname(self.src))

    def write_src(self, text):
        with open(self.src, "w", encoding="utf-8") as f:
            f.write(text)

    def servers(self):
        with open(os.path.join(self.plugin, "mcp_config.json"), encoding="utf-8") as f:
            return json.load(f)["mcpServers"]

    def test_the_box_mcp_servers_become_a_plugin_and_follow_every_start(self):
        cdp = {"command": "chrome-devtools-mcp", "args": ["--browserUrl=http://127.0.0.1:9222"], "env": {}}
        self.write_src(json.dumps({"mcpServers": {"chrome-devtools": cdp}}))
        self.assertEqual(self.run_prepare().returncode, 0)
        self.assertEqual(self.servers(), {"chrome-devtools": cdp})
        with open(os.path.join(self.plugin, "plugin.json"), encoding="utf-8") as f:
            self.assertEqual(json.load(f)["name"], "swarmbox")
        self.assertEqual(stat.S_IMODE(os.stat(os.path.join(self.plugin, "mcp_config.json")).st_mode), 0o600)
        self.assertFalse(os.path.exists(os.path.join(self.home, ".gemini", "config", "mcp_config.json")), "the user's own file is not touched")
        # Settings are seeded once, but the servers follow the box at every start
        self.write_src(json.dumps({"mcpServers": {}}))
        self.assertEqual(self.run_prepare().returncode, 0)
        self.assertEqual(self.servers(), {})

    def test_no_source_writes_nothing_and_a_broken_one_keeps_the_plugin(self):
        self.assertEqual(self.run_prepare().returncode, 0)
        self.assertFalse(os.path.exists(self.plugin))
        self.write_src(json.dumps({"mcpServers": {"a": {"command": "a"}}}))
        self.assertEqual(self.run_prepare().returncode, 0)
        self.write_src("{broken")
        r = self.run_prepare()
        self.assertEqual(r.returncode, 1)
        self.assertIn("not a usable MCP file", r.stderr)
        self.assertEqual(self.servers(), {"a": {"command": "a"}})


class StaticTest(unittest.TestCase):
    def test_the_scripts_pass_bash_n_and_shellcheck(self):
        for f in (INSTALL, MCP_SH, STATUSLINE):
            self.assertTrue(os.access(f, os.X_OK), f)
            self.assertEqual(subprocess.run(["bash", "-n", f]).returncode, 0, f)
        for f in (INSTALL, MCP_SH, STATUSLINE):
            if shutil.which("shellcheck"):
                r = subprocess.run(["shellcheck", "-s", "bash", f], capture_output=True, text=True)
                self.assertEqual(r.returncode, 0, r.stdout)

    def test_the_manifest_is_a_self_updating_addon_named_antigravity_that_provides_agy(self):
        with open(os.path.join(ADDON, "addon.conf")) as f:
            text = f.read()
        for line in ("NAME=antigravity", 'COMMANDS="agy"', "VERSION=latest", "UPDATE=self", 'UPDATE_CMD="agy update"'):
            self.assertIn(line + "\n", text)


if __name__ == "__main__":
    unittest.main()
