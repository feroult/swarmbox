"""`swarmbox update [--to TAG]` (the "Update flow" and "Rollback" of docs/design.md).

The script runs as a real program, installed the way the installers do it (a lone file `bin/swarmbox`, the support files in the data
folder), against the shared FakePodman, which records every call. The "image" is a tar archive built in
Python (tests/helpers.make_archive: swarmbox-host, VERSION, ...) that the fake `podman run ... host-helper` writes to
standard output. HOME is a mktemp folder, so the config file and the helper folder (`~/.local/share/swarmbox/host`) are the
test's own. Nothing starts a real container; tests/test_registry_e2e.py runs the same flow against a real local registry.
Reduced: the real Podman (pull, tag, run) is not involved here, only its recorded calls and the answers the fake gives.
Run: python3 tests/test_host_update.py
"""
import hashlib
import os
import shutil
import subprocess
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_host_up as up_tests  # noqa: E402
from helpers import make_archive  # noqa: E402
from helpers import ROOT, DEFAULT_IMAGE_REPO, HELPER_SH  # noqa: E402

with open(os.path.join(ROOT, "container", "host", "swarmbox-host")) as _f:
    REAL_SCRIPT = _f.read()
REPO = "localhost:34567/org/swarmbox"
with open(os.path.join(ROOT, "container", "host", "VERSION")) as _f:
    CUR = _f.read().strip()   # the version of the real script (the tests follow a version bump)
MSG = "updated to %s; run `swarmbox reset` to use it (running sessions end)\n"


def snap(path):
    """Everything under path (names, modes, contents) as one comparable value; None when it does not exist."""
    if not os.path.lexists(path):
        return None
    out = []
    for dp, dns, fns in os.walk(path):
        for n in sorted(dns + fns):
            p = os.path.join(dp, n)
            st = os.lstat(p)
            h = ""
            if os.path.isfile(p) and not os.path.islink(p):
                with open(p, "rb") as f:
                    h = hashlib.sha256(f.read()).hexdigest()
            out.append((os.path.relpath(p, path), st.st_mode, h))
    return out


class UpdateBase(up_tests.Base):
    def setUp(self):
        super().setUp()
        self.cfg_dir = os.path.join(self.home, ".config", "swarmbox")
        self.cfg = os.path.join(self.cfg_dir, "config")
        self.host_dir = os.path.join(self.home, ".local", "share", "swarmbox", "host")
        self.write_config("IMAGE=%s:2.0.0\n" % REPO)
        self.install_old_helper("2.0.0")
        self.n = 0
        self.bin = os.path.join(self.tmp, "bin")
        os.makedirs(self.bin)
        self.helper = os.path.join(self.bin, "swarmbox")
        self.install_script()

    def install_script(self):
        """The real script as the installers write it: alone in a folder, with no VERSION next to it."""
        shutil.copy(up_tests.HELPER_SRC, self.helper)
        os.chmod(self.helper, 0o755)

    def script_text(self):
        with open(self.helper) as f:
            return f.read()

    def bin_names(self):
        return sorted(os.listdir(self.bin))

    def write_config(self, text):
        os.makedirs(self.cfg_dir, exist_ok=True)
        with open(self.cfg, "w") as f:
            f.write(text)
        os.chmod(self.cfg, 0o600)

    def install_old_helper(self, version):
        os.makedirs(self.host_dir, exist_ok=True)
        for n, c in (("VERSION", version + "\n"), ("DEFAULTS", open(os.path.join(ROOT, "container", "host", "DEFAULTS")).read()),
                     ("tool-ports", "")):
            p = os.path.join(self.host_dir, n)
            with open(p, "w") as f:
                f.write(c)

    def config_text(self):
        with open(self.cfg) as f:
            return f.read()

    def image_line(self):
        return [ln for ln in self.config_text().splitlines() if ln.startswith("IMAGE=")]

    def archive(self, **kw):
        self.n += 1
        p = os.path.join(self.tmp, "image-%d.tar" % self.n)
        make_archive(p, **kw)
        return p

    def podman_for(self, version="2.0.9", pull=None, tag=None, run=None, **archive_kw):
        conf = {"pull": pull or {}, "tag": tag or {},
                "run": run or {"stdout_file": self.archive(version=version, **archive_kw)}}
        return self.podman(**conf)

    def update(self, *args, **extra):
        self.install_script()
        return self.run_h("update", *args, env=self.env(**extra))

    def names(self):
        return [c[0] for c in self.calls()]

    def assert_unchanged(self, before, tag_calls=0):
        self.assertEqual(snap(self.host_dir), before["host"])
        self.assertEqual(snap(self.bin), before["bin"])
        with open(self.cfg, "rb") as f:
            self.assertEqual(f.read(), before["cfg"])
        self.assertEqual(os.stat(self.cfg).st_mode, before["mode"])
        self.assertEqual(len(self.subs("tag")), tag_calls)

    def before(self):
        with open(self.cfg, "rb") as f:
            return {"host": snap(self.host_dir), "bin": snap(self.bin), "cfg": f.read(), "mode": os.stat(self.cfg).st_mode}


class PlainUpdateTest(UpdateBase):
    def test_pulls_the_series_tag_reads_the_version_tags_and_writes_image(self):
        self.podman_for("2.0.9")
        r = self.update()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.calls(), [
            ["pull", "-q", REPO + ":2.0"],
            ["run", "--rm", REPO + ":2.0", "host-helper"],
            ["tag", REPO + ":2.0", REPO + ":2.0.9"],
        ])
        self.assertEqual(self.image_line(), ["IMAGE=%s:2.0.9" % REPO])
        with open(os.path.join(self.host_dir, "VERSION")) as f:
            self.assertEqual(f.read().strip(), "2.0.9")
        # the script of the image is the new command, in place, and its copy is not left in the support folder
        self.assertEqual(self.script_text(), HELPER_SH)
        self.assertTrue(os.access(self.helper, os.X_OK))
        self.assertEqual(self.bin_names(), ["swarmbox"])
        self.assertEqual(sorted(set(os.listdir(self.host_dir)) - {"calls"}),   # calls: the fake script records its `version` call
                         ["DEFAULTS", "VERSION", "cloudflare-setup.py", "tool-ports"])

    def test_the_series_comes_from_the_current_image_tag(self):
        for tag, series in (("2.0.0", "2.0"), ("2.1", "2.1"), ("10.12.3", "10.12"), ("3.4.5-rc1", "3.4")):
            with self.subTest(tag=tag):
                self.write_config("IMAGE=%s:%s\n" % (REPO, tag))
                self.podman_for("%s.9" % series)
                r = self.update()
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertEqual(self.calls()[0], ["pull", "-q", "%s:%s" % (REPO, series)])
                self.assertEqual(self.image_line(), ["IMAGE=%s:%s.9" % (REPO, series)])

    def test_an_image_that_is_not_in_a_series_is_exit_2_before_any_podman_call(self):
        for ref in ("swarmbox", "%s:dev" % REPO, "%s:latest" % REPO, "%s:2" % REPO, "%s:main-2.0" % REPO):
            with self.subTest(ref=ref):
                self.write_config("IMAGE=%s\n" % ref)
                self.podman_for("2.0.9")
                before = self.before()
                r = self.update()
                self.assertEqual(r.returncode, 2, r.stderr)
                self.assertIn("update --to", r.stderr)
                self.assertEqual(self.calls(), [])
                self.assert_unchanged(before)

    def test_update_never_recreates_the_box(self):
        # no rm, stop, start, create, a box run or an inspect of the box: pull, the helper's `run --rm` and tag only
        self.podman_for("2.0.9")
        r = self.update()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(sorted(self.names()), ["pull", "run", "tag"])
        for c in self.subs("run"):
            self.assertEqual(c[:2], ["run", "--rm"])
            self.assertEqual(c[-1], "host-helper")

class PullProgressTest(UpdateBase):
    def test_with_a_terminal_the_pull_shows_podmans_progress_and_without_one_it_is_quiet(self):
        import pty
        self.podman_for("2.0.9")
        self.install_script()
        master, slave = pty.openpty()
        try:   # standard error is a terminal: no -q, so Podman's progress bars reach the person
            r = subprocess.run([self.helper, "update"], env=self.env(), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                               stderr=slave, cwd=self.tmp, timeout=60)
        finally:
            os.close(slave)
            os.close(master)
        self.assertEqual(r.returncode, 0)
        self.assertEqual(self.subs("pull"), [["pull", REPO + ":2.0"]])

    def test_a_failed_pull_with_a_terminal_points_at_the_error_already_shown(self):
        import pty
        self.podman_for("2.0.9", pull={"exit": 125, "stderr": "Error: unable to pull: connection refused\n"})
        self.install_script()
        master, slave = pty.openpty()
        try:
            r = subprocess.run([self.helper, "update"], env=self.env(), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                               stderr=slave, cwd=self.tmp, timeout=60)
            os.set_blocking(master, False)
            try:
                shown = os.read(master, 65536).decode(errors="replace")
            except BlockingIOError:
                shown = ""
        finally:
            os.close(slave)
            os.close(master)
        self.assertEqual(r.returncode, 3)
        self.assertIn("cannot pull %s:2.0: see the Podman error above" % REPO, shown)


class ScriptRefreshTest(UpdateBase):
    def test_a_script_newer_than_the_image_is_kept_with_a_clear_message(self):
        self.podman_for("1.9.2")
        r = self.update("--to", "1.9.2")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("this script (%s) is newer than the image (1.9.2); the script is kept." % CUR, r.stderr)
        self.assertEqual(self.script_text(), REAL_SCRIPT)
        self.assertEqual(self.bin_names(), ["swarmbox"])
        self.assertEqual(self.image_line(), ["IMAGE=%s:1.9.2" % REPO])

    def test_the_same_version_replaces_nothing_and_says_nothing(self):
        self.podman_for(CUR)
        r = self.update("--to", CUR)
        self.assertEqual((r.returncode, r.stdout), (0, MSG % CUR))
        self.assertNotIn("newer", r.stderr)
        self.assertEqual(self.script_text(), REAL_SCRIPT)

    def test_two_digit_numbers_are_compared_as_numbers(self):
        self.podman_for("2.0.10")
        r = self.update("--to", "2.0.10")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.script_text(), HELPER_SH)

    def test_a_folder_that_cannot_be_written_warns_and_still_updates_the_rest(self):
        if os.geteuid() == 0:
            self.skipTest("root ignores the mode")
        self.podman_for("2.0.9")
        self.install_script()
        os.chmod(self.bin, 0o500)
        self.addCleanup(os.chmod, self.bin, 0o700)
        r = self.run_h("update", env=self.env())
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("cannot write next to this script", r.stderr)
        self.assertEqual(self.script_text(), REAL_SCRIPT)
        self.assertEqual(self.image_line(), ["IMAGE=%s:2.0.9" % REPO])

    def test_the_script_is_replaced_by_a_rename_so_a_running_copy_is_never_cut(self):
        self.podman_for("2.0.9")
        self.install_script()
        before = os.stat(self.helper).st_ino
        r = self.run_h("update", env=self.env())
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotEqual(os.stat(self.helper).st_ino, before)

    def test_a_checkout_is_never_replaced(self):
        # run from the folder that holds VERSION (the repository, the image's own folder): the file is not an installed copy
        self.podman_for("2.0.9")
        with open(up_tests.HELPER_SRC) as f:
            src = f.read()
        r = subprocess.run([up_tests.HELPER_SRC, "update"], env=self.env(), capture_output=True, text=True, input="", cwd=self.tmp)
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(up_tests.HELPER_SRC) as f:
            self.assertEqual(f.read(), src)


class ToTest(UpdateBase):
    def test_to_an_exact_tag_pulls_exactly_that_tag(self):
        for tag, ver in (("2.0.0", "2.0.0"), ("2.0.5", "2.0.5"), ("2.3.1", "2.3.1"), ("3.0.0", "3.0.0"), ("1.9.2", "1.9.2")):
            with self.subTest(tag=tag):
                self.podman_for(ver)
                r = self.update("--to", tag)
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertEqual(r.stdout, MSG % ver)
                self.assertEqual(self.calls(), [["pull", "-q", "%s:%s" % (REPO, tag)],
                                                ["run", "--rm", "%s:%s" % (REPO, tag), "host-helper"]])
                self.assertEqual(self.image_line(), ["IMAGE=%s:%s" % (REPO, ver)])
                with open(os.path.join(self.host_dir, "VERSION")) as f:
                    self.assertEqual(f.read().strip(), ver)

    def test_to_a_moving_tag_tags_the_exact_version(self):
        for tag in ("2.1", "3", "latest", "edge"):
            with self.subTest(tag=tag):
                self.podman_for("2.1.7")
                r = self.update("--to", tag)
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertEqual(self.subs("tag"), [["tag", "%s:%s" % (REPO, tag), REPO + ":2.1.7"]])
                self.assertEqual(self.image_line(), ["IMAGE=%s:2.1.7" % REPO])

    def test_an_invalid_tag_is_exit_2_before_any_podman_call(self):
        bad = ["", "a/b", "a:b", "a b", "-x", ".x", "a@b", "x" * 129, "$(id)", "a\nb", "a;b", "a'b", "a`b", "ü", "*", "a\tb",
               "sha256:abc", "2.0.0@sha256:" + "a" * 64, "a\\b", "a?b"]
        for tag in bad:
            with self.subTest(tag=tag):
                self.podman_for("2.0.9")
                before = self.before()
                r = self.update("--to", tag)
                self.assertEqual(r.returncode, 2, r.stderr)
                self.assertEqual(r.stdout, "")
                self.assertIn("tag", r.stderr)
                self.assertEqual(self.calls(), [])
                self.assert_unchanged(before)

class FailureTest(UpdateBase):
    def check_nothing_changed(self, r, code=3, tag_calls=0):
        self.assertEqual(r.returncode, code, r.stderr)
        self.assertEqual(r.stdout, "")
        self.assert_unchanged(self.snapshot, tag_calls)
        self.assertEqual(sorted(os.listdir(os.path.dirname(self.host_dir))), ["host"])

    def setUp(self):
        super().setUp()
        self.snapshot = self.before()

    def test_a_failed_pull_changes_nothing_and_is_exit_3(self):
        for args in ([], ["--to", "2.0.9"]):
            with self.subTest(args=args):
                self.podman_for("2.0.9", pull={"exit": 125, "stderr": "Error: unable to pull: connection refused\n"})
                r = self.update(*args)
                self.check_nothing_changed(r)
                self.assertIn("cannot pull %s:" % REPO, r.stderr)
                self.assertIn("connection refused", r.stderr)
                self.assertEqual(self.names(), ["pull"])

    def test_an_archive_with_no_helper_is_exit_3(self):
        self.podman_for("2.0.9", helper=False)
        r = self.update()
        self.check_nothing_changed(r)
        self.assertIn("no usable host helper", r.stderr)

    def test_an_exact_tag_whose_helper_reports_another_version_is_exit_3(self):
        self.podman_for("2.0.7")
        r = self.update("--to", "2.0.6")
        self.check_nothing_changed(r)
        self.assertIn("2.0.6", r.stderr)
        self.assertIn("2.0.7", r.stderr)

    def test_an_unwritable_config_folder_is_exit_1_after_the_helper_is_replaced(self):
        # documented order: tag, helper rename, config write; a failing write is the one failure that leaves the new helper
        if os.geteuid() == 0:
            self.skipTest("root ignores the mode")
        self.podman_for("2.0.9")
        os.chmod(self.cfg_dir, 0o500)
        self.addCleanup(os.chmod, self.cfg_dir, 0o700)
        r = self.update()
        self.assertEqual(r.returncode, 1, r.stderr)
        with open(self.cfg) as f:
            self.assertEqual(f.read(), "IMAGE=%s:2.0.0\n" % REPO)


class AfterUpdateTest(UpdateBase):
    def test_reset_after_update_uses_the_exact_tag_and_needs_no_network(self):
        self.podman_for("2.0.9")
        r = self.update()
        self.assertEqual(r.returncode, 0, r.stderr)
        # now the box: no network at all (a fake pull would fail), the exact image is present locally
        conf = self.conf(lookup={"stdout": up_tests.line(image=REPO + ":2.0.0")},
                         pull={"exit": 125, "stderr": "Error: no route to host\n"})
        self.fp.configure(conf)
        open(self.fp.log_path, "w").close()
        env = self.env()
        env.pop("SWARMBOX_IMAGE", None)
        # the new script (a copy of the real one: the archive's script is a fake) runs on the support files that update wrote
        self.install_script()
        r = subprocess.run([self.helper, "reset"], env=env, capture_output=True, text=True, input="", cwd=self.tmp, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.subs("pull"), [])
        runs = self.real_runs()
        self.assertEqual(len(runs), 1)
        self.assertIn(REPO + ":2.0.9", runs[0])
        self.assertNotIn(REPO + ":2.0", runs[0])
        self.assertNotIn(REPO + ":2.0.0", runs[0])
        self.assertEqual(self.subs("image")[0][:2], ["image", "exists"])
        self.assertIn("swarmbox.image=%s:2.0.9" % REPO, runs[0])

if __name__ == "__main__":
    unittest.main()
