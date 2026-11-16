"""The swarmbox-addon manifest loading and `validate`.

The manifests are built in mktemp directories and passed through the test-only variables:
SWARMBOX_TEST_IMAGE_ADDONS (replaces /usr/local/lib/swarmbox/addons), SWARMBOX_TEST_USER_ADDONS (replaces the user level,
$SB_CONFIG_DIR/addons) and SWARMBOX_TEST_LIB (the folder with dirs.sh). Nothing here touches the real home.
Run with: python3 tests/fast/test_addon_manifest.py
"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "support"))
from helpers import ROOT  # noqa: E402
from addon_support import ADDON, Base, GOOD_INSTALL, LIB, SELF_UPDATING, make_addon  # noqa: E402

ADDON = os.path.join(ROOT, "container", "scripts", "swarmbox-addon.sh")
LIB = os.path.join(ROOT, "container", "scripts")
REAL_ADDONS = os.path.join(ROOT, "container", "addons")

class Base(unittest.TestCase):
    def setUp(self):
        self.base = tempfile.mkdtemp(prefix="addon-manifest-")
        self.addCleanup(shutil.rmtree, self.base, ignore_errors=True)
        self.image = os.path.join(self.base, "image")
        self.user = os.path.join(self.base, "user")
        os.makedirs(self.image)
        os.makedirs(self.user)
        self.cwd = self.base

    def run_addon(self, *args, cwd=None, env=None):
        e = {"PATH": "/usr/bin:/bin", "HOME": self.base, "SWARMBOX_TEST_LIB": LIB,
             "SWARMBOX_TEST_IMAGE_ADDONS": self.image, "SWARMBOX_TEST_USER_ADDONS": self.user,
             "SWARMBOX_TEST_HOST_DIR": os.path.join(self.base, "host"),
             "SWARMBOX_TEST_IMAGE_SHIMS": os.path.join(self.base, "out", "shims"),
             "SWARMBOX_TEST_USER_SHIMS": os.path.join(self.base, "out", "ushims")}
        e.update(env or {})
        return subprocess.run(["bash", ADDON, *args], env=e, capture_output=True, text=True, timeout=30,
                              cwd=cwd or self.cwd)

    def validate(self, *args, **kw):
        return self.run_addon("validate", *args, **kw)

    def assertFails(self, r, *words):
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        out = r.stdout + r.stderr
        for w in words:
            self.assertIn(w, out)
        return out


class Loader(Base):
    def test_a_valid_manifest_passes_and_is_printed_as_checked(self):
        make_addon(self.image)
        r = self.validate()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("demo", r.stdout)
        self.assertIn("1 manifest", r.stdout)

    def test_each_required_field_is_reported_when_missing(self):
        for key in ("NAME", "DESCRIPTION", "COMMANDS", "VERSION", "SCHEMA"):
            with self.subTest(key=key):
                shutil.rmtree(self.image)
                os.makedirs(self.image)
                if key == "NAME":
                    # NAME missing: the folder name is not a substitute
                    make_addon(self.image, drop=("NAME",), NAME="")
                else:
                    make_addon(self.image, drop=(key,))
                self.assertFails(self.validate(), key)

    def test_an_unknown_key_does_not_replace_a_mandatory_one(self):
        # a key the manifest format does not have is not read: it neither satisfies COMMANDS nor changes the result
        make_addon(self.image, drop=("COMMANDS",), FOO='"demo"')
        self.assertFails(self.validate(), "COMMANDS")
        shutil.rmtree(self.image)
        os.makedirs(self.image)
        make_addon(self.image, FOO="x", BAR="y")
        r = self.validate()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_the_listing_of_validate_says_version_and_update(self):
        make_addon(self.image, name="selfy", COMMANDS='"selfy"', conf=SELF_UPDATING)
        make_addon(self.image, name="pinned", COMMANDS='"pinned"', VERSION="2.0.0")
        r = self.validate()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertRegex(r.stdout, r"selfy.*VERSION=latest, UPDATE=self")
        self.assertRegex(r.stdout, r"pinned.*VERSION=2\.0\.0, UPDATE=managed")

    def test_a_newer_schema_is_refused_with_an_update_message(self):
        make_addon(self.image, SCHEMA="2")
        out = self.assertFails(self.validate(), "SCHEMA")
        self.assertIn("update SwarmBox", out)

    def test_the_name_must_match_its_folder_and_be_a_plain_word(self):
        make_addon(self.image, name="demo", NAME="other")
        self.assertFails(self.validate(), "NAME", "folder")
        shutil.rmtree(self.image)
        os.makedirs(self.image)
        make_addon(self.image, name="Bad", NAME="Bad")
        self.assertFails(self.validate(), "NAME")

    def test_a_manifest_that_does_not_source_fails_validate_and_is_reported_by_link(self):
        make_addon(self.image, extra="if then fi (\n")
        make_addon(self.image, name="fine")
        self.assertFails(self.validate(), "demo", "source")
        r = self.run_addon("link", "--system")
        self.assertEqual(r.returncode, 0, r.stderr)  # skipped, not fatal
        self.assertIn("demo", r.stderr)
        self.assertIn("skip", r.stderr)
        self.assertNotIn("fine: ", r.stderr)

class Rules(Base):
    """One failing-then-passing pair for every rule of validate."""

    def case(self, bad, good, *words, name="demo", **kw):
        d = make_addon(self.image, name=name, **bad, **kw)
        self.assertFails(self.validate(), *words)
        shutil.rmtree(d)
        make_addon(self.image, name=name, **good, **kw)
        r = self.validate()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_install_sh_must_exist(self):
        self.case(dict(install=None), dict(), "install.sh")

    def test_update_self_needs_latest_and_a_command(self):
        good = dict(conf=SELF_UPDATING)
        self.case(dict(conf=dict(VERSION="latest", UPDATE="self")), good, "UPDATE_CMD")
        self.case(dict(conf=dict(VERSION="latest", UPDATE="self", UPDATE_CMD='""')), good, "UPDATE_CMD")

    def test_latest_may_be_managed_by_swarmbox(self):
        # an npm agent without an update command of its own (gemini, opencode) follows the newest release and SwarmBox installs it again
        make_addon(self.image, name="npmagent", COMMANDS='"npmagent"', VERSION="latest", UPDATE="managed")
        make_addon(self.image, name="npmdefault", COMMANDS='"npmdefault"', VERSION="latest")
        r = self.validate()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertRegex(r.stdout, r"npmagent.*VERSION=latest, UPDATE=managed")

    def test_a_pinned_version_is_managed(self):
        good = dict(conf=dict(VERSION="1.0.0"))
        self.case(dict(conf=dict(VERSION="1.0.0", UPDATE="self", UPDATE_CMD='"demo update"')), good, "UPDATE", "latest")
        make_addon(self.image, name="other", COMMANDS='"other"', VERSION="1.0.0", UPDATE="managed")
        r = self.validate()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("UPDATE=managed", r.stdout)

    def test_an_unknown_update_value_fails(self):
        self.case(dict(conf=dict(UPDATE="auto")), dict(conf=dict(UPDATE="managed")), "UPDATE", "auto")

    def test_description_must_be_a_line_of_text(self):
        self.case(dict(conf=dict(DESCRIPTION='""')), dict(), "DESCRIPTION")

    def test_commands_must_be_plain_command_names(self):
        self.case(dict(conf=dict(COMMANDS='"demo ../evil"')), dict(), "COMMANDS", "../evil")

    def test_a_checksum_for_one_architecture_needs_the_other(self):
        h = "a" * 64
        self.case(dict(conf=dict(SHA256_amd64=h)), dict(conf=dict(SHA256_amd64=h, SHA256_arm64=h)),
                  "SHA256_arm64")
        shutil.rmtree(os.path.join(self.image, "demo"))
        make_addon(self.image, conf=dict(SHA256_arm64=h))
        self.assertFails(self.validate(), "SHA256_amd64")

    def test_install_sh_lint_rejects_apt_apt_get_and_sudo(self):
        for bad in ("apt install foo", "apt-get install -y foo", "sudo make install", "x=1; sudo -n true"):
            with self.subTest(bad=bad):
                self.case(dict(install=GOOD_INSTALL + bad + "\n"), dict(), "install.sh", "lint")
                shutil.rmtree(os.path.join(self.image, "demo"))

    def test_lint_rejects_writes_outside_the_prefix(self):
        for bad in ("echo x > /etc/foo", "cp a /usr/local/bin/a", 'echo "export A=1" >> "$HOME/.bashrc"',
                    "ln -s a ~/.profile", "mkdir -p /opt/thing", "tee /var/lib/x < /dev/null"):
            with self.subTest(bad=bad):
                make_addon(self.image, install=GOOD_INSTALL + bad + "\n")
                self.assertFails(self.validate(), "install.sh", "outside")
                shutil.rmtree(os.path.join(self.image, "demo"))

    def test_a_command_in_two_addons_of_one_level_is_an_error(self):
        make_addon(self.image, name="a", COMMANDS='"shared a"')
        make_addon(self.image, name="b", COMMANDS='"b shared"')
        self.assertFails(self.validate(), "shared", "a", "b")

    def test_every_error_is_listed_not_only_the_first(self):
        make_addon(self.image, install=None, drop=("COMMANDS", "DESCRIPTION"))
        out = self.assertFails(self.validate())
        for w in ("DESCRIPTION", "COMMANDS", "install.sh"):
            self.assertIn(w, out)

class NoProjectLevel(Base):
    """An addons folder inside a project is never read."""

    def test_nothing_in_the_project_is_read_by_validate_link_or_the_loader(self):
        marker = os.path.join(self.base, "SOURCED")
        proj = os.path.join(self.base, "proj")
        for rel in (".swarmbox/addons", "addons", "container/addons", ".config/swarmbox/addons"):
            make_addon(os.path.join(proj, rel), name="evil", extra="touch %s\n" % marker)
        make_addon(self.image, name="fine")
        # cwd is the project and also a subfolder of it; HOME is the project too, but the user level is overridden
        for cwd in (proj, os.path.join(proj, ".swarmbox")):
            for args in (("validate",), ("link", "--system"), ("link", "--user")):
                r = self.run_addon(*args, cwd=cwd)
                self.assertEqual(r.returncode, 0, (args, r.stdout, r.stderr))
                self.assertNotIn("evil", r.stdout + r.stderr)
        self.assertFalse(os.path.exists(marker))


class Cli(Base):
    """The command line of swarmbox-addon: a usage error is 64, and the script is clean bash."""

    def test_validate_with_no_manifests_passes_and_says_how_many_it_checked(self):
        r = self.validate()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("0 manifest(s) checked", r.stdout)

    def test_no_arguments_or_an_unknown_command_is_a_usage_error_64(self):
        for args in ((), ("bogus",)):
            with self.subTest(args=args):
                r = self.run_addon(*args)
                self.assertEqual(r.returncode, 64)
                self.assertIn("usage: swarmbox addon", r.stderr)
                self.assertEqual(r.stdout, "")

    def test_the_script_is_bash_and_shellcheck_clean(self):
        self.assertEqual(subprocess.run(["bash", "-n", ADDON], capture_output=True).returncode, 0)
        if not shutil.which("shellcheck"):
            self.skipTest("shellcheck is not installed")
        r = subprocess.run(["shellcheck", "-s", "bash", ADDON], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout)


class RealClaudeManifest(Base):
    def test_the_repository_addons_folder_validates_with_every_addon_it_ships(self):
        r = self.validate(REAL_ADDONS)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        for name in sorted(os.listdir(REAL_ADDONS)):
            self.assertIn(name, r.stdout)

    def test_the_claude_installer_passes_bash_n_shellcheck_and_the_lint(self):
        inst = os.path.join(REAL_ADDONS, "claude", "install.sh")
        self.assertTrue(os.access(inst, os.X_OK))
        self.assertEqual(subprocess.run(["bash", "-n", inst]).returncode, 0)
        sc = shutil.which("shellcheck")
        if sc:
            r = subprocess.run([sc, "-s", "bash", inst], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stdout)
        else:
            self.skipTest("shellcheck is not installed")

    def test_the_claude_installer_fails_when_the_vendor_installer_fails(self):
        fake = os.path.join(self.base, "fakebin")
        os.makedirs(fake)
        with open(os.path.join(fake, "curl"), "w") as f:
            f.write("#!/bin/sh\nexit 22\n")
        os.chmod(os.path.join(fake, "curl"), 0o755)
        home = os.path.join(self.base, "home")
        os.makedirs(home)
        r = subprocess.run(["bash", os.path.join(REAL_ADDONS, "claude", "install.sh")], capture_output=True, text=True,
                           timeout=30, env={"PATH": fake + ":/usr/bin:/bin", "HOME": home,
                                            "ADDON_PREFIX": os.path.join(home, "p"), "ADDON_VERSION": "latest",
                                            "ADDON_ARCH": "amd64"})
        self.assertNotEqual(r.returncode, 0)
        self.assertFalse(os.path.exists(os.path.join(home, "p", "installed")))


if __name__ == "__main__":
    unittest.main()
