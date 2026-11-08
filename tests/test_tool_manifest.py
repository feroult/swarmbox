"""Slice 4a.1: swarmbox-tool manifest loading and `validate` (design 6.1 to 6.4, 6.7, 6.9, 6.10; decisions D3, D18, D21).

The manifests are built in mktemp directories and passed through the test-only variables of decision log [4a.1]:
SWARMBOX_TEST_IMAGE_TOOLS (replaces /usr/local/lib/swarmbox/tools), SWARMBOX_TEST_USER_TOOLS (replaces the user level,
$SB_CONFIG_DIR/tools) and SWARMBOX_TEST_LIB (the folder with dirs.sh). Nothing here touches the real home.
Run with: python3 tests/test_tool_manifest.py
"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import ROOT  # noqa: E402

TOOL = os.path.join(ROOT, "container", "scripts", "swarmbox-tool.sh")
LIB = os.path.join(ROOT, "container", "scripts")
REAL_TOOLS = os.path.join(ROOT, "container", "tools")

GOOD_CONF = {
    "SCHEMA": "1", "NAME": "demo", "KIND": "tool", "PROVIDES": '"demo demo2"', "VERSION": "1.2.3",
}
GOOD_INSTALL = '#!/bin/bash\nset -euo pipefail\nmkdir -p "$TOOL_PREFIX/bin"\necho installing >&2\n'


def write_conf(path, conf, extra=""):
    with open(path, "w") as f:
        for k, v in conf.items():
            f.write("%s=%s\n" % (k, v))
        f.write(extra)


def make_tool(level, name="demo", conf=None, install=GOOD_INSTALL, executable=True, extra="", drop=(), **over):
    d = os.path.join(level, name)
    os.makedirs(d, exist_ok=True)
    c = dict(GOOD_CONF, NAME=name)
    c.update(conf or {})
    c.update(over)
    for k in drop:
        c.pop(k, None)
    write_conf(os.path.join(d, "tool.conf"), c, extra)
    if install is not None:
        p = os.path.join(d, "install.sh")
        with open(p, "w") as f:
            f.write(install)
        os.chmod(p, 0o755 if executable else 0o644)
    return d


class Base(unittest.TestCase):
    def setUp(self):
        self.base = tempfile.mkdtemp(prefix="tool-manifest-")
        self.addCleanup(shutil.rmtree, self.base, ignore_errors=True)
        self.image = os.path.join(self.base, "image")
        self.user = os.path.join(self.base, "user")
        os.makedirs(self.image)
        os.makedirs(self.user)
        self.cwd = self.base

    def run_tool(self, *args, cwd=None, env=None):
        e = {"PATH": "/usr/bin:/bin", "HOME": self.base, "SWARMBOX_TEST_LIB": LIB,
             "SWARMBOX_TEST_IMAGE_TOOLS": self.image, "SWARMBOX_TEST_USER_TOOLS": self.user,
             "SWARMBOX_TEST_HOST_DIR": os.path.join(self.base, "host"),
             "SWARMBOX_TEST_IMAGE_SHIMS": os.path.join(self.base, "out", "shims"),
             "SWARMBOX_TEST_USER_SHIMS": os.path.join(self.base, "out", "ushims")}
        e.update(env or {})
        return subprocess.run(["bash", TOOL, *args], env=e, capture_output=True, text=True, timeout=30,
                              cwd=cwd or self.cwd)

    def validate(self, *args, **kw):
        return self.run_tool("validate", *args, **kw)

    def assertFails(self, r, *words):
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        out = r.stdout + r.stderr
        for w in words:
            self.assertIn(w, out)
        return out


class Loader(Base):
    def test_a_valid_manifest_passes_and_is_printed_as_checked(self):
        make_tool(self.image)
        r = self.validate()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("demo", r.stdout)
        self.assertIn("1 manifest", r.stdout)

    def test_each_required_field_is_reported_when_missing(self):
        for key in ("NAME", "KIND", "PROVIDES", "VERSION", "SCHEMA"):
            with self.subTest(key=key):
                shutil.rmtree(self.image)
                os.makedirs(self.image)
                if key == "NAME":
                    # NAME missing: the folder name is not a substitute
                    make_tool(self.image, drop=("NAME",), NAME="")
                else:
                    make_tool(self.image, drop=(key,))
                self.assertFails(self.validate(), key)

    def test_an_empty_required_value_counts_as_missing(self):
        make_tool(self.image, PROVIDES='""')
        self.assertFails(self.validate(), "PROVIDES")

    def test_an_unknown_kind_fails(self):
        make_tool(self.image, KIND="plugin")
        self.assertFails(self.validate(), "KIND", "plugin")

    def test_a_newer_schema_is_refused_with_an_update_message(self):
        make_tool(self.image, SCHEMA="2")
        out = self.assertFails(self.validate(), "SCHEMA")
        self.assertIn("update SwarmBox", out)

    def test_a_non_numeric_schema_fails_without_the_update_message(self):
        make_tool(self.image, SCHEMA="one")
        out = self.assertFails(self.validate(), "SCHEMA")
        self.assertNotIn("update SwarmBox", out)

    def test_unknown_keys_are_ignored(self):
        make_tool(self.image, extra="FUTURE_KEY=whatever\nANOTHER=\"x y\"\n")
        r = self.validate()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_the_name_must_match_its_folder_and_be_a_plain_word(self):
        make_tool(self.image, name="demo", NAME="other")
        self.assertFails(self.validate(), "NAME", "folder")
        shutil.rmtree(self.image)
        os.makedirs(self.image)
        make_tool(self.image, name="Bad", NAME="Bad")
        self.assertFails(self.validate(), "NAME")

    def test_provides_entries_must_be_plain_command_names(self):
        make_tool(self.image, PROVIDES='"ok ../evil"')
        self.assertFails(self.validate(), "PROVIDES", "../evil")

    def test_a_manifest_that_does_not_source_fails_validate_and_is_reported_by_link(self):
        make_tool(self.image, extra="if then fi (\n")
        make_tool(self.image, name="fine")
        self.assertFails(self.validate(), "demo", "source")
        r = self.run_tool("link", "--system")
        self.assertEqual(r.returncode, 0, r.stderr)  # skipped, not fatal
        self.assertIn("demo", r.stderr)
        self.assertIn("skip", r.stderr)
        self.assertNotIn("fine: ", r.stderr)

    def test_a_manifest_that_exits_nonzero_when_sourced_does_not_source(self):
        make_tool(self.image, extra="exit 3\n")
        self.assertFails(self.validate(), "source")

    def test_the_environment_does_not_leak_into_a_manifest(self):
        make_tool(self.image, drop=("VERSION",))
        self.assertFails(self.validate(env={"VERSION": "9.9"}), "VERSION")

    def test_a_folder_without_tool_conf_fails_validate(self):
        os.makedirs(os.path.join(self.image, "empty"))
        self.assertFails(self.validate(), "empty", "tool.conf")

    def test_a_missing_level_folder_is_not_an_error(self):
        shutil.rmtree(self.image)
        shutil.rmtree(self.user)
        r = self.validate()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("0 manifest", r.stdout)


class Rules(Base):
    """One failing-then-passing pair for every rule of design 6.9."""

    def case(self, bad, good, *words, name="demo", **kw):
        d = make_tool(self.image, name=name, **bad, **kw)
        self.assertFails(self.validate(), *words)
        shutil.rmtree(d)
        make_tool(self.image, name=name, **good, **kw)
        r = self.validate()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_install_sh_must_exist(self):
        self.case(dict(install=None), dict(), "install.sh")

    def test_install_sh_must_be_executable(self):
        self.case(dict(executable=False), dict(), "install.sh", "executable")

    def test_update_self_needs_latest_and_a_command(self):
        good = dict(conf=dict(KIND="agent", VERSION="latest", UPDATE="self", UPDATE_CMD='"demo update"'))
        self.case(dict(conf=dict(KIND="agent", VERSION="latest", UPDATE="self")), good, "UPDATE_CMD")
        self.case(dict(conf=dict(KIND="agent", VERSION="latest", UPDATE="self", UPDATE_CMD='""')), good, "UPDATE_CMD")

    def test_update_self_rejects_a_pinned_version(self):
        out = make_tool(self.image, KIND="tool", VERSION="1.0", UPDATE="self", UPDATE_CMD='"x update"')
        r = self.validate()
        self.assertFails(r, "UPDATE=self", "latest")
        shutil.rmtree(out)

    def test_an_unknown_update_mode_fails(self):
        self.case(dict(conf=dict(UPDATE="auto")), dict(conf=dict(UPDATE="managed")), "UPDATE")

    def test_an_agent_with_a_pinned_version_fails(self):
        self.case(dict(conf=dict(KIND="agent", VERSION="1.0.0")), dict(conf=dict(KIND="agent", VERSION="latest")),
                  "agent", "latest")

    def test_a_non_agent_tool_with_latest_fails(self):
        self.case(dict(conf=dict(KIND="tool", VERSION="latest")), dict(conf=dict(KIND="tool", VERSION="3.4")),
                  "pinned")

    def test_a_checksum_for_one_architecture_needs_the_other(self):
        h = "a" * 64
        self.case(dict(conf=dict(SHA256_amd64=h)), dict(conf=dict(SHA256_amd64=h, SHA256_arm64=h)),
                  "SHA256_arm64")
        shutil.rmtree(os.path.join(self.image, "demo"))
        make_tool(self.image, conf=dict(SHA256_arm64=h))
        self.assertFails(self.validate(), "SHA256_amd64")

    def test_a_checksum_must_look_like_sha256(self):
        h = "a" * 64
        self.case(dict(conf=dict(SHA256_amd64="xyz", SHA256_arm64=h)),
                  dict(conf=dict(SHA256_amd64=h, SHA256_arm64=h)), "SHA256_amd64")

    def test_install_sh_lint_rejects_apt_apt_get_and_sudo(self):
        for bad in ("apt install foo", "apt-get install -y foo", "sudo make install", "x=1; sudo -n true"):
            with self.subTest(bad=bad):
                self.case(dict(install=GOOD_INSTALL + bad + "\n"), dict(), "install.sh", "lint")
                shutil.rmtree(os.path.join(self.image, "demo"))

    def test_lint_does_not_flag_words_that_merely_contain_apt(self):
        make_tool(self.image, install=GOOD_INSTALL + "echo adapt captain sudoku >&2\n")
        r = self.validate()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_lint_rejects_writes_outside_the_prefix(self):
        for bad in ("echo x > /etc/foo", "cp a /usr/local/bin/a", 'echo "export A=1" >> "$HOME/.bashrc"',
                    "ln -s a ~/.profile", "mkdir -p /opt/thing", "tee /var/lib/x < /dev/null"):
            with self.subTest(bad=bad):
                make_tool(self.image, install=GOOD_INSTALL + bad + "\n")
                self.assertFails(self.validate(), "install.sh", "outside")
                shutil.rmtree(os.path.join(self.image, "demo"))

    def test_lint_allows_the_prefix_and_reads(self):
        make_tool(self.image, install=GOOD_INSTALL + 'cp /etc/hostname "$TOOL_PREFIX/h"\ncat /usr/share/x > "$TOOL_PREFIX/y"\n')
        r = self.validate()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_update_self_may_write_its_own_paths_in_the_home_only(self):
        own = 'mkdir -p "$HOME/.local/bin" "$HOME/.local/share/demo" ~/.cache/demo\nln -sf a "$HOME/.local/bin/demo"\n'
        conf = dict(KIND="agent", VERSION="latest", UPDATE="self", UPDATE_CMD='"demo update"')
        make_tool(self.image, conf=conf, install=GOOD_INSTALL + own)
        r = self.validate()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        # the same lines fail for a managed tool
        shutil.rmtree(os.path.join(self.image, "demo"))
        make_tool(self.image, install=GOOD_INSTALL + own)
        self.assertFails(self.validate(), "outside")
        # and other home paths, the shell startup files, and system paths fail even for UPDATE=self
        for bad in ('echo x >> "$HOME/.bashrc"', 'mkdir -p "$HOME/.claude"', "echo x > /etc/y"):
            with self.subTest(bad=bad):
                shutil.rmtree(os.path.join(self.image, "demo"))
                make_tool(self.image, conf=conf, install=GOOD_INSTALL + bad + "\n")
                self.assertFails(self.validate(), "outside")

    def test_duplicate_provides_at_one_level_is_an_error(self):
        make_tool(self.image, name="a", PROVIDES='"shared a"')
        make_tool(self.image, name="b", PROVIDES='"b shared"')
        self.assertFails(self.validate(), "shared", "a", "b")

    def test_user_over_image_duplicate_is_allowed_and_user_wins(self):
        make_tool(self.image, name="a", PROVIDES='"shared"')
        make_tool(self.user, name="b", PROVIDES='"shared"')
        r = self.validate()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("shared", r.stdout)
        self.assertIn("overrid", r.stdout)

    def test_the_same_tool_name_at_both_levels_is_allowed_and_user_wins(self):
        make_tool(self.image, name="a")
        make_tool(self.user, name="a", VERSION="9.9")
        r = self.validate()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("2 manifest", r.stdout)
        self.assertIn("overrid", r.stdout)

    def test_every_error_is_listed_not_only_the_first(self):
        make_tool(self.image, KIND="plugin", install=None, drop=("PROVIDES",))
        out = self.assertFails(self.validate())
        for w in ("KIND", "PROVIDES", "install.sh"):
            self.assertIn(w, out)

    def test_a_broken_manifest_does_not_hide_the_good_ones(self):
        make_tool(self.image, name="good")
        make_tool(self.image, name="bad", KIND="plugin")
        out = self.assertFails(self.validate(), "bad")
        self.assertIn("good", out)

    def test_a_directory_argument_validates_only_that_level_folder(self):
        make_tool(self.image, name="bad", KIND="plugin")
        other = os.path.join(self.base, "other")
        os.makedirs(other)
        make_tool(other, name="fine")
        r = self.validate(other)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn("bad", r.stdout)
        self.assertEqual(self.validate(os.path.join(self.base, "nope")).returncode, 64)

    def test_validate_takes_at_most_one_argument(self):
        self.assertEqual(self.validate("a", "b").returncode, 64)


class NoProjectLevel(Base):
    """D18: a tools folder inside a project is never read."""

    def test_nothing_in_the_project_is_read_by_validate_link_or_the_loader(self):
        marker = os.path.join(self.base, "SOURCED")
        proj = os.path.join(self.base, "proj")
        for rel in (".swarmbox/tools", "tools", "container/tools", ".config/swarmbox/tools"):
            make_tool(os.path.join(proj, rel), name="evil", extra="touch %s\n" % marker)
        make_tool(self.image, name="fine")
        # cwd is the project and also a subfolder of it; HOME is the project too, but the user level is overridden
        for cwd in (proj, os.path.join(proj, ".swarmbox")):
            for args in (("validate",), ("link", "--system"), ("link", "--user")):
                r = self.run_tool(*args, cwd=cwd)
                self.assertEqual(r.returncode, 0, (args, r.stdout, r.stderr))
                self.assertNotIn("evil", r.stdout + r.stderr)
        self.assertFalse(os.path.exists(marker))

    def test_without_overrides_the_user_level_is_the_config_folder_not_the_project(self):
        marker = os.path.join(self.base, "SOURCED")
        proj = os.path.join(self.base, "proj")
        make_tool(os.path.join(proj, ".swarmbox", "tools"), name="evil", extra="touch %s\n" % marker)
        home = os.path.join(self.base, "home")
        make_tool(os.path.join(home, ".config", "swarmbox", "tools"), name="mine")
        env = {"HOME": home, "SWARMBOX_TEST_USER_TOOLS": "", "SWARMBOX_TEST_IMAGE_TOOLS": os.path.join(self.base, "none")}
        r = self.run_tool("validate", cwd=proj, env=env)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("mine", r.stdout)
        self.assertNotIn("evil", r.stdout)
        self.assertFalse(os.path.exists(marker))

    def test_the_script_never_names_a_project_path(self):
        with open(TOOL) as f:
            text = f.read()
        for needle in (".swarmbox/tools", "$PWD", "$(pwd)", "pwd -P"):
            self.assertNotIn(needle, text)


class RealClaudeManifest(Base):
    def test_the_repository_tools_folder_validates(self):
        r = self.validate(REAL_TOOLS)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("claude", r.stdout)

    def test_the_claude_manifest_has_the_fields_of_design_6_3(self):
        got = subprocess.run(
            ["bash", "-c", '. "$1"; printf "%s|" "$SCHEMA" "$NAME" "$KIND" "$PROVIDES" "$VERSION" "$UPDATE" "$UPDATE_CMD" "$YOLO_FLAGS" "$MCP_FLAGS"',
             "x", os.path.join(REAL_TOOLS, "claude", "tool.conf")],
            env={"PATH": "/usr/bin:/bin", "HOME": "/home/agent"}, capture_output=True, text=True).stdout
        self.assertEqual(got, "1|claude|agent|claude|latest|self|claude update|--dangerously-skip-permissions|"
                              "--mcp-config /home/agent/.claude/mcp-servers.json|")

    def test_the_claude_installer_passes_bash_n_shellcheck_and_the_lint(self):
        inst = os.path.join(REAL_TOOLS, "claude", "install.sh")
        self.assertTrue(os.access(inst, os.X_OK))
        self.assertEqual(subprocess.run(["bash", "-n", inst]).returncode, 0)
        sc = shutil.which("shellcheck")
        if sc:
            r = subprocess.run([sc, "-s", "bash", inst], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stdout)
        else:
            self.skipTest("shellcheck is not installed")

    def test_the_claude_installer_describes_the_vendor_call(self):
        text = open(os.path.join(REAL_TOOLS, "claude", "install.sh")).read()
        self.assertIn("https://claude.ai/install.sh", text)
        self.assertIn("bash -s", text)
        self.assertIn("latest", text)
        for banned in ("apt", "sudo"):
            self.assertNotIn(banned, text.replace("adapt", ""))

    def test_the_claude_installer_passes_no_argument_for_latest_and_the_version_otherwise(self):
        # runs the installer with a fake curl on PATH that serves a fake vendor script, in a throwaway home
        fake = os.path.join(self.base, "fakebin")
        os.makedirs(fake)
        home = os.path.join(self.base, "home")
        prefix = os.path.join(home, "tools", "claude", "self")
        os.makedirs(home)
        with open(os.path.join(fake, "curl"), "w") as f:
            f.write("#!/bin/sh\ncat <<'VENDOR'\n"
                    'echo "args=$#:$*" >> "$HOME/vendor.log"\n'
                    'mkdir -p "$HOME/.local/bin"\n'
                    "printf '#!/bin/sh\\necho claude 9.9\\n' > \"$HOME/.local/bin/claude\"\n"
                    'chmod +x "$HOME/.local/bin/claude"\n'
                    "VENDOR\n")
        os.chmod(os.path.join(fake, "curl"), 0o755)
        inst = os.path.join(REAL_TOOLS, "claude", "install.sh")
        for ver, want in (("latest", "args=0:"), ("2.1.314", "args=1:2.1.314")):
            with self.subTest(ver=ver):
                shutil.rmtree(os.path.join(home, ".local"), ignore_errors=True)
                if os.path.exists(os.path.join(home, "vendor.log")):
                    os.remove(os.path.join(home, "vendor.log"))
                r = subprocess.run(["bash", inst], capture_output=True, text=True, timeout=30,
                                   env={"PATH": fake + ":/usr/bin:/bin", "HOME": home, "TOOL_PREFIX": prefix,
                                        "TOOL_VERSION": ver, "TOOL_ARCH": "amd64"})
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertEqual(r.stdout, "")  # stdout belongs to the tool (6.4)
                self.assertEqual(open(os.path.join(home, "vendor.log")).read().strip(), want)
                self.assertTrue(os.path.isfile(os.path.join(prefix, "installed")))

    def test_the_claude_installer_fails_when_the_vendor_installer_fails(self):
        fake = os.path.join(self.base, "fakebin")
        os.makedirs(fake)
        with open(os.path.join(fake, "curl"), "w") as f:
            f.write("#!/bin/sh\nexit 22\n")
        os.chmod(os.path.join(fake, "curl"), 0o755)
        home = os.path.join(self.base, "home")
        os.makedirs(home)
        r = subprocess.run(["bash", os.path.join(REAL_TOOLS, "claude", "install.sh")], capture_output=True, text=True,
                           timeout=30, env={"PATH": fake + ":/usr/bin:/bin", "HOME": home,
                                            "TOOL_PREFIX": os.path.join(home, "p"), "TOOL_VERSION": "latest",
                                            "TOOL_ARCH": "amd64"})
        self.assertNotEqual(r.returncode, 0)
        self.assertFalse(os.path.exists(os.path.join(home, "p", "installed")))


if __name__ == "__main__":
    unittest.main()
