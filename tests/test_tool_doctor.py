"""Slice 4b.5: the environment fingerprint (design 6.11) at `doctor`, `doctor --fix`, `link --user` and in the shim.

Policy under test (decision log [4b.5]): ARCH differs: the shim refuses (exit 69), doctor says `needs reinstall`. NODE_MAJOR or LIBC
differs: the shim warns once per entry and runs, doctor still lists `needs reinstall` (it is the audit view; the tool may work).
The running environment is forced with SWARMBOX_TEST_ARCH, SWARMBOX_TEST_NODE_MAJOR and SWARMBOX_TEST_LIBC.
Run with: python3 -W error tests/test_tool_doctor.py
"""
import fcntl
import os
import shutil
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_tool_link import tree_hash  # noqa: E402
from test_tool_shim import INTERPRETERS, ShimBase  # noqa: E402


def rows(out):
    res = {}
    for line in out.splitlines()[1:]:
        parts = line.split(None, 1)
        if parts:
            res[parts[0]] = parts[1] if len(parts) > 1 else ""
    return res


class DoctorBase(ShimBase):
    def env(self, **extra):
        e = super().env(**extra)
        e.setdefault("SWARMBOX_TEST_NODE_MAJOR", "24")
        e.setdefault("SWARMBOX_TEST_LIBC", "glibc")
        return e

    def fleet(self):
        """demo (managed, installed), selfy (self, installed), ghost (managed, never installed)."""
        self.managed()
        self.selfy()
        self.managed("ghost")
        for n in ("demo", "selfy"):
            self.assertEqual(self.tool("install", n).returncode, 0)


class Doctor(DoctorBase):
    def test_all_matching_is_ok_and_missing_is_not_a_failure(self):
        self.fleet()
        r = self.tool("doctor")
        self.assertEqual(r.returncode, 0, r.stderr)
        t = rows(r.stdout)
        self.assertTrue(t["demo"].startswith("ok"), r.stdout)
        self.assertTrue(t["selfy"].startswith("ok"), r.stdout)
        self.assertTrue(t["ghost"].startswith("missing"), r.stdout)

    def test_different_arch_needs_reinstall_for_managed_and_self(self):
        self.fleet()
        r = self.tool("doctor", SWARMBOX_TEST_ARCH="arm64")
        self.assertEqual(r.returncode, 1)
        t = rows(r.stdout)
        for n in ("demo", "selfy"):
            self.assertTrue(t[n].startswith("needs reinstall"), r.stdout)
            self.assertIn("ARCH amd64 -> arm64", t[n])
        self.assertTrue(t["ghost"].startswith("missing"))

    def test_different_node_major_and_libc_need_reinstall_in_the_listing(self):
        self.fleet()
        r = self.tool("doctor", SWARMBOX_TEST_NODE_MAJOR="22")
        self.assertEqual(r.returncode, 1)
        self.assertIn("NODE_MAJOR 24 -> 22", rows(r.stdout)["demo"])
        r = self.tool("doctor", SWARMBOX_TEST_LIBC="musl")
        self.assertEqual(r.returncode, 1)
        self.assertIn("LIBC glibc -> musl", rows(r.stdout)["selfy"])

    def test_unknown_current_node_does_not_count_as_a_difference(self):
        self.fleet()
        r = self.tool("doctor", SWARMBOX_TEST_NODE_MAJOR="")
        self.assertEqual(r.returncode, 0, r.stdout)

    def test_dangling_current_and_a_stale_self_record_need_reinstall(self):
        self.fleet()
        shutil.rmtree(os.path.join(self.tools, "demo", "1.2.3"))
        os.remove(os.path.join(self.home, ".local", "bin", "selfy"))
        r = self.tool("doctor")
        self.assertEqual(r.returncode, 1)
        t = rows(r.stdout)
        self.assertTrue(t["demo"].startswith("needs reinstall"), r.stdout)
        self.assertTrue(t["selfy"].startswith("needs reinstall"), r.stdout)

    def test_broken_manifest_is_reported_and_fails(self):
        self.fleet()
        with open(os.path.join(self.image, "ghost", "tool.conf"), "w") as f:
            f.write("exit 3\n")
        r = self.tool("doctor")
        self.assertEqual(r.returncode, 1)
        self.assertIn("broken", rows(r.stdout)["ghost"])

    def test_no_tools_and_usage(self):
        r = self.tool("doctor")
        self.assertEqual(r.returncode, 0, r.stderr)
        for args in (("doctor", "--bogus"), ("doctor", "x"), ("doctor", "--fix", "--fix")):
            self.assertEqual(self.tool(*args).returncode, 64, args)

    def test_doctor_changes_nothing(self):
        self.fleet()
        before = tree_hash(self.home)
        self.tool("doctor", SWARMBOX_TEST_ARCH="arm64")
        self.assertEqual(tree_hash(self.home), before)


class DoctorFix(DoctorBase):
    def test_fix_reinstalls_only_the_tools_that_need_it(self):
        self.fleet()
        selfy_before = tree_hash(os.path.join(self.tools, "selfy"))
        # a second managed tool that stays ok under the new node: install it under node 22 so it matches
        self.managed("steady")
        self.assertEqual(self.tool("install", "steady", SWARMBOX_TEST_NODE_MAJOR="22").returncode, 0)
        steady_before = tree_hash(os.path.join(self.tools, "steady"))
        n = self.installs()
        r = self.tool("doctor", "--fix", SWARMBOX_TEST_NODE_MAJOR="22")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        # demo and selfy were installed under 24: both are reinstalled; steady is untouched
        self.assertEqual(self.installs(), n + 2)
        self.assertEqual(tree_hash(os.path.join(self.tools, "steady")), steady_before)
        self.assertNotEqual(tree_hash(os.path.join(self.tools, "selfy")), selfy_before)
        self.assertFalse(os.path.exists(os.path.join(self.tools, "ghost")))  # missing is not installed by --fix
        r = self.tool("doctor", SWARMBOX_TEST_NODE_MAJOR="22")
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertEqual(self.tool("doctor", "--fix", SWARMBOX_TEST_NODE_MAJOR="22").returncode, 0)
        self.assertEqual(self.installs(), n + 2)  # nothing left to fix: no installer ran

    def test_fix_for_another_arch_passes_the_new_arch_and_keeps_the_version(self):
        self.managed()
        self.assertEqual(self.tool("install", "demo", "--version", "2.0.0").returncode, 0)
        r = self.tool("doctor", "--fix", SWARMBOX_TEST_ARCH="arm64")
        self.assertEqual(r.returncode, 0, r.stderr)
        last = self.records()[-1]
        self.assertEqual(last[1:3], ["2.0.0", "arm64"])
        self.assertEqual(os.readlink(os.path.join(self.tools, "demo", "current")), "2.0.0")
        with open(os.path.join(self.tools, "demo", "2.0.0", ".swarmbox-env")) as f:
            self.assertIn("ARCH=arm64", f.read())

    def test_fix_reports_a_failing_installer_and_exits_1(self):
        self.fleet()
        r = self.tool("doctor", "--fix", SWARMBOX_TEST_NODE_MAJOR="22", FAKE_FAIL="1")
        self.assertEqual(r.returncode, 1)
        self.assertIn("demo", r.stderr)

    def test_fix_respects_the_lock(self):
        self.fleet()
        os.makedirs(os.path.dirname(self.lock), exist_ok=True)
        with open(self.lock, "a") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            r = self.tool("doctor", "--fix", SWARMBOX_TEST_NODE_MAJOR="22", SWARMBOX_TEST_LOCK_WAIT="1")
        self.assertEqual(r.returncode, 1)
        self.assertIn("another install is running", r.stderr)


class ShimFingerprint(DoctorBase):
    def installed(self):
        self.setup_demo()
        self.assertEqual(self.tool("install", "demo").returncode, 0)
        self.assertEqual(self.tool("install", "selfy").returncode, 0)

    def warned_dir(self):
        return os.path.join(self.home, ".local", "state", "swarmbox", "tool-warned")

    def test_arch_mismatch_refuses_and_does_not_execute(self):
        self.installed()
        for iname, interp in INTERPRETERS:
            for name in ("demo", "selfy"):
                with self.subTest(interp=iname, tool=name):
                    r = self.call(os.path.join(self.ishims, name), "arg", interp=interp, SWARMBOX_TEST_ARCH="arm64")
                    self.assertEqual(r.returncode, 69, r.stderr)
                    self.assertEqual(r.stdout, "")
                    self.assertIn("amd64", r.stderr)
                    self.assertIn("arm64", r.stderr)
                    self.assertIn("swarmbox-tool install %s --force" % name, r.stderr)

    def test_node_mismatch_warns_once_per_entry_and_runs(self):
        self.installed()
        for iname, interp in INTERPRETERS:
            with self.subTest(interp=iname):
                shutil.rmtree(self.warned_dir(), ignore_errors=True)
                demo = os.path.join(self.ishims, "demo")
                r1 = self.call(demo, "one", interp=interp, SWARMBOX_TEST_NODE_MAJOR="22")
                self.assertEqual(r1.returncode, 0, r1.stderr)
                self.assertEqual(r1.stdout, "[one]\n")
                self.assertEqual(r1.stderr.count("NODE_MAJOR"), 1, r1.stderr)
                self.assertIn("24", r1.stderr)
                r2 = self.call(demo, "two", interp=interp, SWARMBOX_TEST_NODE_MAJOR="22")
                self.assertEqual(r2.returncode, 0)
                self.assertEqual(r2.stdout, "[two]\n")
                self.assertNotIn("NODE_MAJOR", r2.stderr)
                # a different entry (the markers are cleared by link --user) warns again; another tool has its own marker
                other = self.call(os.path.join(self.ishims, "selfy"), "x", interp=interp, SWARMBOX_TEST_NODE_MAJOR="22")
                self.assertEqual(other.stderr.count("NODE_MAJOR"), 1, other.stderr)

    def test_libc_mismatch_also_warns_and_runs(self):
        self.installed()
        r = self.call(os.path.join(self.ishims, "demo"), "x", SWARMBOX_TEST_LIBC="musl")
        self.assertEqual(r.returncode, 0)
        self.assertIn("LIBC", r.stderr)
        self.assertEqual(r.stdout, "[x]\n")

    def test_matching_environment_is_silent(self):
        self.installed()
        r = self.call(os.path.join(self.ishims, "demo"), "x")
        self.assertEqual((r.returncode, r.stderr), (0, ""))
        self.assertFalse(os.path.exists(self.warned_dir()))

    def test_link_user_warns_per_tool_marks_it_and_the_shim_stays_quiet_until_the_next_entry(self):
        self.installed()
        r = self.tool("link", "--user", SWARMBOX_TEST_NODE_MAJOR="22")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stderr.count("NODE_MAJOR"), 2, r.stderr)   # demo and selfy
        self.assertIn("linked the user level", r.stdout)
        shim = self.call(os.path.join(self.ishims, "demo"), "x", SWARMBOX_TEST_NODE_MAJOR="22")
        self.assertEqual(shim.returncode, 0)
        self.assertNotIn("NODE_MAJOR", shim.stderr)
        # the next entry: link --user starts over
        r = self.tool("link", "--user", SWARMBOX_TEST_NODE_MAJOR="22")
        self.assertEqual(r.stderr.count("NODE_MAJOR"), 2, r.stderr)

    def test_link_user_with_arch_mismatch_names_the_tool_and_still_succeeds(self):
        self.installed()
        r = self.tool("link", "--user", SWARMBOX_TEST_ARCH="arm64")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("demo", r.stderr)
        self.assertIn("reinstall", r.stderr)
        # the shim refuses regardless of any marker
        s = self.call(os.path.join(self.ishims, "demo"), "x", SWARMBOX_TEST_ARCH="arm64")
        self.assertEqual(s.returncode, 69)

    def test_link_user_with_nothing_installed_or_matching_prints_no_warning(self):
        r = self.tool("link", "--user")
        self.assertEqual(r.stderr, "")
        self.installed()
        r = self.tool("link", "--user")
        self.assertEqual(r.stderr, "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
