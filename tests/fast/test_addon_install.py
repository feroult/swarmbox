"""`swarmbox-addon install`, `run`, `list`, `update`.

All installers are fakes: scripts that record their environment and working directory, then write a fake program into
$ADDON_PREFIX (managed addons) or into ~/.local/bin under a temp HOME (UPDATE=self addons, like the vendor installer of Claude Code).
Nothing here touches the real home, the real addons folder or the real lock: the lock is moved with SWARMBOX_TEST_LOCK, the
architecture can be forced with SWARMBOX_TEST_ARCH, and HOME, TMPDIR and the manifest folders are temp folders.
Run with: python3 tests/fast/test_addon_install.py
"""
import hashlib
import os
import shutil
import subprocess
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "support"))
from addon_support import ADDON, Base, SHA, SHIM, tree_hash  # noqa: E402

class InstallManaged(Base):
    def test_passes_prefix_version_arch_and_runs_in_home(self):
        self.managed()
        r = self.addon("install", "demo")
        self.assertEqual(r.returncode, 0, r.stderr)
        (rec,) = self.records()
        self.assertEqual(rec[0], os.path.join(self.addons, "demo", "1.2.3"))
        self.assertEqual(rec[1], "1.2.3")
        self.assertEqual(rec[2], "amd64")
        self.assertEqual(rec[4], self.home)
        self.assertEqual(rec[5], self.home)

    def test_arch_from_uname_m(self):
        fake = os.path.join(self.base, "fakebin")
        os.makedirs(fake)
        for machine, want in (("x86_64", "amd64"), ("aarch64", "arm64"), ("arm64", "arm64"), ("amd64", "amd64")):
            with self.subTest(machine=machine):
                with open(os.path.join(fake, "uname"), "w") as f:
                    f.write("#!/bin/sh\necho %s\n" % machine)
                os.chmod(os.path.join(fake, "uname"), 0o755)
                shutil.rmtree(self.addons, ignore_errors=True)
                self.managed()
                env = self.env(PATH=fake + ":/usr/bin:/bin")
                del env["SWARMBOX_TEST_ARCH"]
                r = self.addon("install", "demo", env=env)
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertEqual(self.records()[-1][2], want)

    def test_failure_leaves_nothing_and_the_next_call_retries(self):
        self.managed()
        before = tree_hash(self.home)
        r = self.addon("install", "demo", FAKE_FAIL="1")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("could not resolve host", r.stderr)
        self.assertIn("demo", r.stderr)
        self.assertEqual(tree_hash(self.home), before)
        self.assertFalse(os.path.lexists(os.path.join(self.addons, "demo", "current")))
        r = self.addon("install", "demo")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.installs(), 2)
        self.assertTrue(os.path.islink(os.path.join(self.addons, "demo", "current")))

    def test_version_installs_side_by_side_and_moves_current(self):
        self.managed()
        self.addon("install", "demo")
        r = self.addon("install", "demo", "--version", "2.0.0")
        self.assertEqual(r.returncode, 0, r.stderr)
        d = os.path.join(self.addons, "demo")
        self.assertEqual(sorted(os.listdir(d)), ["1.2.3", "2.0.0", "current"])
        self.assertEqual(os.readlink(os.path.join(d, "current")), "2.0.0")
        self.assertEqual(self.records()[-1][1], "2.0.0")
        # asking again for the older installed version only moves the link, the installer does not run
        r = self.addon("install", "demo", "--version", "1.2.3")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(os.readlink(os.path.join(d, "current")), "1.2.3")
        self.assertEqual(self.installs(), 2)

    def test_force_reinstalls(self):
        self.managed()
        self.addon("install", "demo")
        r = self.addon("install", "demo", "--force")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.installs(), 2)
        self.assertTrue(os.path.isfile(os.path.join(self.addons, "demo", "current", "bin", "demo")))

    def test_sha256_mismatch_aborts_and_removes_files(self):
        arch = os.path.join(self.base, "fixture.tar.gz")
        with open(arch, "wb") as f:
            f.write(b"fixture archive bytes\n")
        self.managed(installer=SHA, SHA256_amd64="0" * 64, SHA256_arm64="1" * 64)
        before = tree_hash(self.home)
        r = self.addon("install", "demo", FIXTURE_ARCHIVE=arch)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("FAILED", r.stderr)  # sha256sum -c said so
        self.assertEqual(tree_hash(self.home), before)

    def test_sha256_match_installs_and_the_installer_gets_the_arch_checksum(self):
        arch = os.path.join(self.base, "fixture.tar.gz")
        with open(arch, "wb") as f:
            f.write(b"fixture archive bytes\n")
        good = hashlib.sha256(b"fixture archive bytes\n").hexdigest()
        self.managed(installer=SHA, SHA256_amd64=good, SHA256_arm64="1" * 64)
        r = self.addon("install", "demo", FIXTURE_ARCHIVE=arch)
        self.assertEqual(r.returncode, 0, r.stderr)
        r = self.addon("install", "demo", "--force", FIXTURE_ARCHIVE=arch, SWARMBOX_TEST_ARCH="arm64")
        self.assertNotEqual(r.returncode, 0)  # the arm64 checksum is wrong for this archive

class InstallSelf(Base):
    def setUp(self):
        super().setUp()
        self.selfy()
        self.record = os.path.join(self.addons, "selfy", "self")
        self.launcher = os.path.join(self.home, ".local", "bin", "selfy")

    def test_install_writes_the_record_dir_and_the_program_outside_it(self):
        r = self.addon("install", "selfy")
        self.assertEqual(r.returncode, 0, r.stderr)
        (rec,) = self.records()
        self.assertEqual(rec[1], "latest")
        self.assertTrue(os.path.isfile(os.path.join(self.record, ".swarmbox-env")))
        self.assertTrue(os.path.isfile(os.path.join(self.record, "installed")))  # written by the installer into ADDON_PREFIX
        self.assertTrue(os.access(self.launcher, os.X_OK))
        self.assertEqual(os.listdir(os.path.join(self.addons, "selfy")), ["self"])  # no current link, no versions, no staging

    def assert_nothing_recorded(self):
        folder = os.path.join(self.addons, "selfy")
        self.assertEqual(os.listdir(folder) if os.path.isdir(folder) else [], [], "no record and no staging folder: the next call installs again")

    def test_a_failing_installer_records_nothing_and_the_next_call_retries(self):
        r = self.addon("install", "selfy", FAKE_FAIL="1")
        self.assertEqual(r.returncode, 69)
        self.assertIn("the install of selfy failed (installer exit 1)", r.stderr)
        self.assert_nothing_recorded()
        self.assertEqual(self.addon("install", "selfy").returncode, 0)
        self.assertTrue(os.access(self.launcher, os.X_OK))
        self.assertTrue(os.path.isdir(self.record))

    def test_an_installer_whose_program_is_the_shim_is_refused_and_records_nothing(self):
        # the vendor installer links the command to swarmbox-shim: recording it would make the command call itself forever
        r = self.addon("install", "selfy", FAKE_LINK_TO_SHIM=SHIM)
        self.assertEqual(r.returncode, 69)
        self.assertIn("resolves to swarmbox-shim", r.stderr)
        self.assert_nothing_recorded()

    def test_update_runs_update_cmd_with_the_real_binary(self):
        self.addon("install", "selfy")
        r = self.addon("update", "selfy")
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(self.calls) as f:
            self.assertEqual(f.read().strip(), "update called with: update")

class Run(Base):
    def test_not_installed_triggers_install_then_exec(self):
        self.managed()
        r = self.addon("run", "demo", "demo", "--", "a")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout, "[a]\n")  # only the addon's stdout
        self.assertIn("Installing demo (first use)...", r.stderr)
        r = self.addon("run", "demo", "demo", "--", "b")
        self.assertEqual(r.stdout, "[b]\n")
        self.assertNotIn("Installing", r.stderr)
        self.assertEqual(self.installs(), 1)

class Concurrency(Base):
    def test_two_installs_at_once_run_the_installer_once(self):
        self.managed()
        env = self.env(FAKE_SLEEP="1.5")
        procs = [subprocess.Popen(["bash", ADDON, "install", "demo"], env=env, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, text=True, cwd=self.base) for _ in range(2)]
        outs = [p.communicate(timeout=60) for p in procs]
        for p, (_, err) in zip(procs, outs):
            self.assertEqual(p.returncode, 0, err)
        self.assertEqual(self.installs(), 1)
        self.assertTrue(any("already installed" in err for _, err in outs), outs)

class ListAndLater(Base):
    def test_list_shows_both_levels_and_the_state(self):
        self.managed()
        self.selfy()
        self.managed(name="other", level=self.user)
        self.addon("install", "demo")
        r = self.addon("list")
        self.assertEqual(r.returncode, 0, r.stderr)
        header = r.stdout.splitlines()[0].split()
        for col in ("NAME", "STATE", "DESCRIPTION", "VERSION", "UPDATE"):
            self.assertIn(col, header)
        self.assertEqual(len(header), len(set(header)))
        self.assertEqual(header[0], "NAME")
        self.assertEqual(sorted(h for h in header if h not in ("NAME", "STATE", "DESCRIPTION", "VERSION", "UPDATE", "LEVEL")), [])
        rows = {line.split()[0]: line for line in r.stdout.splitlines()[1:]}
        self.assertEqual(sorted(rows), ["demo", "other", "selfy"])
        self.assertIn("1.2.3", rows["demo"])
        self.assertIn("installed (1.2.3)", rows["demo"])
        self.assertIn("managed", rows["demo"])
        self.assertIn("A demo addon", rows["demo"])        # the DESCRIPTION of the manifest
        self.assertIn("self", rows["selfy"])
        self.assertIn("user", rows["other"])
        self.assertIn("image", rows["demo"])
        self.assertIn("not installed", rows["other"])
        self.assertIn("not installed", rows["selfy"])
        self.addon("install", "selfy")
        r = self.addon("list")
        self.assertIn("installed (self)", [x for x in r.stdout.splitlines() if x.startswith("selfy")][0])
        self.assertEqual(self.addon("list", "extra").returncode, 64)


# ---- addons installed at the image level (what the Dockerfile's WITH_ADDONS loop runs, as the owner of /opt/swarmbox/addons) ----
# `install NAME --image` installs into the image state folder (test override SWARMBOX_TEST_IMAGE_STATE) instead of the workspace, records
# the fingerprint, and for an UPDATE=self addon runs the installer with HOME=<image state>/<name>/home (the workspace home is a bind
# mount at run time). At run time `run`, `list`, `doctor` and the shim find the workspace install first and the image install second; a
# workspace install that is incomplete never shadows a complete image install.


class ImageLevel(Base):
    def setUp(self):
        super().setUp()
        self.state = os.path.join(self.base, "optstate")  # stands for /opt/swarmbox/addons (does not exist yet)

    def env(self, **extra):
        e = super().env(**extra)
        e["SWARMBOX_TEST_IMAGE_STATE"] = self.state
        return e

    def run_demo(self, *args):
        return self.addon("run", "demo", "demo", "--", *args)

    def test_managed_image_install_goes_to_the_image_state_not_the_workspace(self):
        self.managed()
        r = self.addon("install", "demo", "--image")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(os.path.isfile(os.path.join(self.state, "demo", "1.2.3", "bin", "demo")))
        self.assertEqual(os.readlink(os.path.join(self.state, "demo", "current")), "1.2.3")
        self.assertFalse(os.path.exists(self.addons), "the workspace addons folder was created")
        (rec,) = self.records()
        self.assertEqual(rec[0], os.path.join(self.state, "demo", "1.2.3"))

    def test_run_uses_the_image_install_without_the_installer_and_without_network(self):
        self.managed()
        self.assertEqual(self.addon("install", "demo", "--image").returncode, 0)
        n = self.installs()
        r = self.run_demo("a b", "c")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.splitlines(), ["[a b]", "[c]"])
        self.assertEqual(self.installs(), n, "run installed again")
        self.assertFalse(os.path.exists(self.addons), "run created a workspace install")

    def test_a_complete_workspace_install_wins_over_the_image_one(self):
        self.managed()
        self.addon("install", "demo", "--image")
        self.managed(VERSION="2.0.0")
        self.assertEqual(self.addon("install", "demo").returncode, 0)
        with open(os.path.join(self.addons, "demo", "2.0.0", "bin", "demo"), "w") as f:
            f.write("#!/bin/sh\necho WORKSPACE\n")
        r = self.run_demo()
        self.assertEqual(r.stdout.strip(), "WORKSPACE")

    def test_self_addon_image_install_uses_its_own_home_and_runs_from_it(self):
        self.selfy()
        r = self.addon("install", "selfy", "--image")
        self.assertEqual(r.returncode, 0, r.stderr)
        home = os.path.join(self.state, "selfy", "home")
        self.assertTrue(os.access(os.path.join(home, ".local", "bin", "selfy"), os.X_OK))
        self.assertFalse(os.path.exists(os.path.join(self.home, ".local", "bin", "selfy")), "wrote the workspace home")
        self.assertEqual(self.records()[0][5], home)
        self.assertTrue(os.path.isfile(os.path.join(self.state, "selfy", "self", ".swarmbox-env")))
        n = self.installs()
        out = self.addon("run", "selfy", "selfy", "--", "hi")
        self.assertEqual(out.stdout.strip(), "[hi]", out.stderr)
        self.assertEqual(self.installs(), n)
        self.assertIn("installed (self)", [x for x in self.addon("list").stdout.splitlines() if x.startswith("selfy")][0])

    def test_failed_image_install_leaves_nothing(self):
        self.managed()
        r = self.addon("install", "demo", "--image", FAKE_FAIL="1")
        self.assertNotEqual(r.returncode, 0)
        self.assertFalse(os.path.exists(os.path.join(self.state, "demo", "1.2.3")))
        self.assertFalse(os.path.exists(os.path.join(self.state, "demo", "current")))


if __name__ == "__main__":
    unittest.main()
