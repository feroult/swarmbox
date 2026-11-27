"""`swarmbox update [--to TAG]` (the "Update flow" and "Rollback" of docs/design.md).

The script runs as a real program, installed the way the installers do it (a lone file `bin/swarmbox`, the support files in the data
folder), against the shared FakePodman, which records every call. The "image" is a tar archive built in
Python (tests/helpers.make_archive: swarmbox-host, VERSION, ...) that the fake `podman run ... host-helper` writes to
standard output. HOME is a mktemp folder, so the config file and the helper folder (`~/.local/share/swarmbox/host`) are the
test's own. Nothing starts a real container; tests/test_registry_e2e.py runs the same flow against a real local registry.
Reduced: the real Podman (pull, tag, run) is not involved here, only its recorded calls and the answers the fake gives.
Run: python3 tests/fast/test_host_update.py
"""
import concurrent.futures
import hashlib
import io
import os
import shutil
import select
import time
import subprocess
import sys
import tarfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "support"))
from host_support import UpBase, HELPER_SRC, line  # noqa: E402
from helpers import FakePodman, make_archive  # noqa: E402
from helpers import ROOT, HELPER_SH  # noqa: E402

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


class UpdateBase(UpBase):
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
        shutil.copy(HELPER_SRC, self.helper)
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
        with open(os.path.join(ROOT, "container", "host", "DEFAULTS")) as f:
            defaults = f.read()
        for n, c in (("VERSION", version + "\n"), ("DEFAULTS", defaults), ("addon-ports", "")):
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

    def podman(self, **over):
        if self.fp is not None:
            self.fp.configure(self.conf(**over))
            open(self.fp.log_path, "w").close()
            return self.fp
        return super().podman(**over)

    def podman_for(self, version="2.99.99", pull=None, tag=None, run=None, **archive_kw):
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

    def iso_env(self, tag, cfg_text, version="2.99.99", run=None, **archive_kw):
        """An isolated (helper, env, fp, cfg, host_dir, bin) under self.tmp so subtests can run concurrently."""
        d = os.path.join(self.tmp, "iso-" + tag)
        home = os.path.join(d, "home")
        cfg_dir = os.path.join(home, ".config", "swarmbox")
        cfg = os.path.join(cfg_dir, "config")
        host_dir = os.path.join(home, ".local", "share", "swarmbox", "host")
        bindir = os.path.join(d, "bin")
        os.makedirs(cfg_dir)
        os.makedirs(host_dir)
        os.makedirs(bindir)
        with open(cfg, "w") as f:
            f.write(cfg_text)
        os.chmod(cfg, 0o600)
        with open(os.path.join(ROOT, "container", "host", "DEFAULTS")) as f:
            defaults = f.read()
        for n, c in (("VERSION", "2.0.0\n"), ("DEFAULTS", defaults), ("addon-ports", "")):
            with open(os.path.join(host_dir, n), "w") as f:
                f.write(c)
        helper = os.path.join(bindir, "swarmbox")
        shutil.copy(HELPER_SRC, helper)
        os.chmod(helper, 0o755)
        if run is None:
            arc = os.path.join(d, "image.tar")
            make_archive(arc, version=version, **archive_kw)
            run = {"stdout_file": arc}
        fp = FakePodman(self.conf(pull={}, tag={}, run=run))
        fp.__enter__()
        self.addCleanup(fp.__exit__)
        e = self.env(HOME=home)
        e["PATH"] = fp.env()["PATH"]
        return helper, e, fp, cfg, host_dir, bindir


class PlainUpdateTest(UpdateBase):
    def test_pulls_the_series_tag_reads_the_version_tags_and_writes_image(self):
        self.podman_for("2.99.99")
        r = self.update()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.calls(), [
            ["pull", "-q", REPO + ":2.0"],
            ["run", "--rm", REPO + ":2.0", "host-helper"],
            ["tag", REPO + ":2.0", REPO + ":2.99.99"],
        ])
        self.assertEqual(self.image_line(), ["IMAGE=%s:2.99.99" % REPO])
        with open(os.path.join(self.host_dir, "VERSION")) as f:
            self.assertEqual(f.read().strip(), "2.99.99")
        # the script of the image is the new command, in place, and its copy is not left in the support folder
        self.assertEqual(self.script_text(), HELPER_SH)
        self.assertTrue(os.access(self.helper, os.X_OK))
        self.assertEqual(self.bin_names(), ["swarmbox"])
        self.assertEqual(sorted(set(os.listdir(self.host_dir)) - {"calls"}),   # calls: the fake script records its `version` call
                         ["DEFAULTS", "VERSION", "addon-ports", "cloudflare-setup.py"])

    def test_the_series_comes_from_the_current_image_tag(self):
        cases = (("2.0.0", "2.0"), ("2.1", "2.1"), ("10.12.3", "10.12"), ("3.4.5-rc1", "3.4"))
        prepped = [(tag, series, self.iso_env("ser-%d" % i, "IMAGE=%s:%s\n" % (REPO, tag), "%s.9" % series))
                   for i, (tag, series) in enumerate(cases)]

        def run_one(item):
            tag, series, (helper, e, fp, cfg, _hd, _bd) = item
            r = subprocess.run([helper, "update"], env=e, capture_output=True, text=True, input="", cwd=self.tmp, timeout=60)
            with open(cfg) as f:
                img = [ln for ln in f.read().splitlines() if ln.startswith("IMAGE=")]
            return tag, series, r, fp.calls(), img

        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(run_one, prepped))
        for tag, series, r, calls, img in results:
            with self.subTest(tag=tag):
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertEqual(calls[0], ["pull", "-q", "%s:%s" % (REPO, series)])
                self.assertEqual(img, ["IMAGE=%s:%s.9" % (REPO, series)])

    def test_an_image_that_is_not_in_a_series_is_exit_2_before_any_podman_call(self):
        for ref in ("swarmbox", "%s:dev" % REPO, "%s:latest" % REPO, "%s:2" % REPO, "%s:main-2.0" % REPO):
            with self.subTest(ref=ref):
                self.write_config("IMAGE=%s\n" % ref)
                self.podman_for("2.99.99")
                before = self.before()
                r = self.update()
                self.assertEqual(r.returncode, 2, r.stderr)
                self.assertIn("update --to", r.stderr)
                self.assertEqual(self.calls(), [])
                self.assert_unchanged(before)

    def test_update_never_recreates_the_box(self):
        # no rm, stop, start, create, a box run or an inspect of the box: pull, the helper's `run --rm` and tag only
        self.podman_for("2.99.99")
        r = self.update()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(sorted(self.names()), ["pull", "run", "tag"])
        for c in self.subs("run"):
            self.assertEqual(c[:2], ["run", "--rm"])
            self.assertEqual(c[-1], "host-helper")

class PullProgressTest(UpdateBase):
    def update_on_a_terminal(self, **env):
        """`swarmbox update` with standard error on a pseudo-terminal: (exit status, what was written there). TERM is set (or removed)
        here, never taken from the machine that runs the tests: the progress line needs one, and a CI runner has none."""
        import pty
        self.install_script()
        e = self.env(SWARMBOX_TEST_PULL_TICK="0.01", **env)
        for k in ("TERM", "NO_COLOR", "SWARMBOX_PROGRESS", "STARSHIP_SHELL"):
            if k not in env:
                e.pop(k, None)
        master, slave = pty.openpty()
        try:
            # read WHILE it runs and until it has ended, and only then close the slave: on macOS the last close of the slave throws away what was not read yet
            # (on Linux it is still there), which made `shown` empty on the CI runner of macOS
            p = subprocess.Popen([self.helper, "update"], env=e, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=slave, cwd=self.tmp)
            chunks, end = [], time.monotonic() + 60

            def pull(wait):
                if not select.select([master], [], [], wait)[0]:
                    return False
                try:
                    data = os.read(master, 65536)
                except OSError:
                    return False
                if data:
                    chunks.append(data)
                return bool(data)
            while p.poll() is None and time.monotonic() < end:
                pull(0.01)
            if p.poll() is None:
                p.kill()
                p.wait()
            if sys.platform.startswith("linux"):
                os.close(slave)
                slave = -1
                while pull(0.05):
                    pass
            else:
                while pull(0.02):
                    pass
            shown = b"".join(chunks).decode(errors="replace")
            r = p
        finally:
            if slave >= 0:
                os.close(slave)
            os.close(master)
        return r.returncode, shown

    def test_with_a_terminal_the_pull_has_no_quiet_flag(self):
        envs = ({"TERM": "xterm-256color", "LANG": "C.UTF-8"}, {}, {"TERM": "dumb"}, {"TERM": "xterm", "SWARMBOX_PROGRESS": "plain"})
        prepped = [(env, self.iso_env("pty-%d" % i, "IMAGE=%s:2.0.0\n" % REPO, "2.99.99")) for i, env in enumerate(envs)]

        def run_one(item):
            import pty
            env, (helper, base_e, fp, _cfg, _hd, _bd) = item
            e = dict(base_e, SWARMBOX_TEST_PULL_TICK="0.01", **env)
            for k in ("TERM", "NO_COLOR", "SWARMBOX_PROGRESS", "STARSHIP_SHELL"):
                if k not in env:
                    e.pop(k, None)
            master, slave = pty.openpty()
            try:
                p = subprocess.Popen([helper, "update"], env=e, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=slave, cwd=self.tmp)
                end = time.monotonic() + 60

                def drain(wait):
                    if not select.select([master], [], [], wait)[0]:
                        return False
                    try:
                        return bool(os.read(master, 65536))
                    except OSError:
                        return False
                while p.poll() is None and time.monotonic() < end:
                    drain(0.01)
                if p.poll() is None:
                    p.kill()
                    p.wait()
                if sys.platform.startswith("linux"):
                    os.close(slave)
                    slave = -1
                    while drain(0.05):
                        pass
                else:
                    while drain(0.02):
                        pass
                rc = p.returncode
            finally:
                if slave >= 0:
                    os.close(slave)
                os.close(master)
            pulls = [c for c in fp.calls() if c and c[0] == "pull"]
            return env, rc, pulls

        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(run_one, prepped))
        for env, rc, pulls in results:
            self.assertEqual(rc, 0, env)
            self.assertEqual(pulls[-1], ["pull", REPO + ":2.0"], env)

    def test_a_failed_pull_with_the_progress_line_shows_podmans_error_and_says_it_in_the_message(self):
        self.podman_for("2.99.99", pull={"exit": 125, "stderr": "Error: unable to pull: connection refused\n"})
        rc, shown = self.update_on_a_terminal(TERM="xterm-256color", LANG="C.UTF-8")
        self.assertEqual(rc, 3)
        self.assertIn("cannot pull %s:2.0: Error: unable to pull: connection refused" % REPO, shown)

    def test_a_failed_pull_without_a_TERM_leaves_podmans_own_output_and_points_at_it(self):
        self.podman_for("2.99.99", pull={"exit": 125, "stderr": "Error: unable to pull: connection refused\n"})
        rc, shown = self.update_on_a_terminal()
        self.assertEqual(rc, 3)
        self.assertIn("cannot pull %s:2.0: see the Podman error above" % REPO, shown)


class NewerVersionLiteralsTest(unittest.TestCase):
    def test_the_versions_that_stand_for_an_image_newer_than_the_script_are_still_newer(self):
        # Many tests here say "the image is 2.99.99" or "2.99.100" to mean "newer than this script". They stop meaning it when the script reaches
        # that version, and the failure shows up in the middle of a release (it did, twice). This fails well before that, with the cause.
        ver = tuple(int(x) for x in CUR.split("-")[0].split(".")[:3])
        self.assertLess(ver, (2, 99, 90), "the script is %s: raise the literals 2.99.99 and 2.99.100 of this file well above it" % CUR)


class ScriptRefreshTest(UpdateBase):
    def test_a_script_newer_than_the_image_is_kept_with_a_clear_message(self):
        self.podman_for("0.0.1")
        r = self.update("--to", "0.0.1")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("this script (%s) is newer than the image (0.0.1); the script is kept." % CUR, r.stderr)
        self.assertEqual(self.script_text(), REAL_SCRIPT)
        self.assertEqual(self.bin_names(), ["swarmbox"])
        self.assertEqual(self.image_line(), ["IMAGE=%s:0.0.1" % REPO])

    def test_the_same_version_replaces_nothing_and_says_nothing(self):
        self.podman_for(CUR)
        r = self.update("--to", CUR)
        self.assertEqual((r.returncode, r.stdout), (0, MSG % CUR))
        self.assertNotIn("newer", r.stderr)
        self.assertEqual(self.script_text(), REAL_SCRIPT)

    def test_two_digit_numbers_are_compared_as_numbers(self):
        self.podman_for("2.99.100")
        r = self.update("--to", "2.99.100")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.script_text(), HELPER_SH)

    def test_a_folder_that_cannot_be_written_warns_and_still_updates_the_rest(self):
        if os.geteuid() == 0:
            self.skipTest("root ignores the mode")
        self.podman_for("2.99.99")
        self.install_script()
        os.chmod(self.bin, 0o500)
        self.addCleanup(os.chmod, self.bin, 0o700)
        r = self.run_h("update", env=self.env())
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("cannot write next to this script", r.stderr)
        self.assertEqual(self.script_text(), REAL_SCRIPT)
        self.assertEqual(self.image_line(), ["IMAGE=%s:2.99.99" % REPO])

    def test_the_script_is_replaced_by_a_rename_so_a_running_copy_is_never_cut(self):
        self.podman_for("2.99.99")
        self.install_script()
        before = os.stat(self.helper).st_ino
        r = self.run_h("update", env=self.env())
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotEqual(os.stat(self.helper).st_ino, before)

    def test_a_checkout_is_never_replaced(self):
        # run from the folder that holds VERSION (the repository, the image's own folder): the file is not an installed copy
        self.podman_for("2.99.99")
        with open(HELPER_SRC) as f:
            src = f.read()
        r = subprocess.run([HELPER_SRC, "update"], env=self.env(), capture_output=True, text=True, input="", cwd=self.tmp)
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(HELPER_SRC) as f:
            self.assertEqual(f.read(), src)


class ToTest(UpdateBase):
    def test_to_an_exact_tag_pulls_exactly_that_tag(self):
        cases = (("2.0.0", "2.0.0"), ("2.0.5", "2.0.5"), ("2.3.1", "2.3.1"), ("3.0.0", "3.0.0"), ("1.9.2", "1.9.2"))
        prepped = [(tag, ver, self.iso_env("exact-%d" % i, "IMAGE=%s:2.0.0\n" % REPO, ver)) for i, (tag, ver) in enumerate(cases)]

        def run_one(item):
            tag, ver, (helper, e, fp, cfg, host_dir, _bd) = item
            r = subprocess.run([helper, "update", "--to", tag], env=e, capture_output=True, text=True, input="", cwd=self.tmp, timeout=60)
            with open(cfg) as f:
                img = [ln for ln in f.read().splitlines() if ln.startswith("IMAGE=")]
            with open(os.path.join(host_dir, "VERSION")) as f:
                got_ver = f.read().strip()
            return tag, ver, r, fp.calls(), img, got_ver

        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
            results = list(pool.map(run_one, prepped))
        for tag, ver, r, calls, img, got_ver in results:
            with self.subTest(tag=tag):
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertEqual(r.stdout, MSG % ver)
                self.assertEqual(calls, [["pull", "-q", "%s:%s" % (REPO, tag)],
                                         ["run", "--rm", "%s:%s" % (REPO, tag), "host-helper"]])
                self.assertEqual(img, ["IMAGE=%s:%s" % (REPO, ver)])
                self.assertEqual(got_ver, ver)

    def test_to_a_moving_tag_tags_the_exact_version(self):
        tags = ("2.1", "3", "latest", "edge")
        prepped = [(tag, self.iso_env("mov-%d" % i, "IMAGE=%s:2.0.0\n" % REPO, "2.1.7")) for i, tag in enumerate(tags)]

        def run_one(item):
            tag, (helper, e, fp, cfg, _hd, _bd) = item
            r = subprocess.run([helper, "update", "--to", tag], env=e, capture_output=True, text=True, input="", cwd=self.tmp, timeout=60)
            with open(cfg) as f:
                img = [ln for ln in f.read().splitlines() if ln.startswith("IMAGE=")]
            tag_calls = [c for c in fp.calls() if c and c[0] == "tag"]
            return tag, r, tag_calls, img

        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(run_one, prepped))
        for tag, r, tag_calls, img in results:
            with self.subTest(tag=tag):
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertEqual(tag_calls, [["tag", "%s:%s" % (REPO, tag), REPO + ":2.1.7"]])
                self.assertEqual(img, ["IMAGE=%s:2.1.7" % REPO])

    # one tag per class of what a tag must not be: a reference (path, registry, digest), an option, a hidden name, too long, a character
    # that separates words (space, tab, newline), that a shell expands or quotes, or that is not ASCII
    BAD_TAGS = ["", "a/b", "a:b", "a@b", "sha256:abc", "2.0.0@sha256:" + "a" * 64, "-x", "--help", ".hidden", "x" * 129,
                "a b", "a\tb", "a\nb", "a\rb", "a;b", "a&b", "a|b", "a>b", "$(touch MARK)", "`touch MARK`", "${HOME}", "a'b", 'a"b',
                "a\\b", "a*b", "a?b", "~", "\u00fc"]

    def test_an_invalid_tag_is_exit_2_before_any_podman_call_and_runs_nothing(self):
        self.podman_for("2.99.99")
        before = self.before()
        env = self.env()
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda t: (t, self.run_h("update", "--to", t, env=env)), self.BAD_TAGS))
        for tag, r in results:
            with self.subTest(tag=tag):
                self.assertEqual(r.returncode, 2, r.stderr)
                self.assertEqual(r.stdout, "")
                self.assertIn("tag", r.stderr)
        self.assertEqual(self.calls(), [])
        self.assert_unchanged(before)
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "MARK")), "a command substitution ran")

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
        for args in ([], ["--to", "2.99.99"]):
            with self.subTest(args=args):
                self.podman_for("2.99.99", pull={"exit": 125, "stderr": "Error: unable to pull: connection refused\n"})
                r = self.update(*args)
                self.check_nothing_changed(r)
                self.assertIn("cannot pull %s:" % REPO, r.stderr)
                self.assertIn("connection refused", r.stderr)
                self.assertEqual(self.names(), ["pull"])

    def test_an_archive_with_no_helper_is_exit_3(self):
        self.podman_for("2.99.99", helper=False)
        r = self.update()
        self.check_nothing_changed(r)
        self.assertIn("no usable host helper", r.stderr)

    def test_an_exact_tag_whose_helper_reports_another_version_is_exit_3(self):
        self.podman_for("2.0.7")
        r = self.update("--to", "2.0.6")
        self.check_nothing_changed(r)
        self.assertIn("2.0.6", r.stderr)
        self.assertIn("2.0.7", r.stderr)

    def test_an_archive_with_an_unsafe_member_is_refused_and_nothing_escapes(self):
        # security review SR-05: one member per class a tar can use to write outside the temporary folder or leave a link behind
        escaped = os.path.join(self.tmp, "escaped")
        absname = os.path.join(self.tmp, "abs-escaped")

        def member(name, kind=tarfile.REGTYPE, link=""):
            ti = tarfile.TarInfo(name)
            ti.type, ti.linkname = kind, link
            return ti
        cases = (("parent", member("../escaped")), ("deep parent", member("a/../../escaped")),
                 ("absolute", member(absname)), ("symlink", member("./evil", tarfile.SYMTYPE, escaped)),
                 ("hard link", member("./evil", tarfile.LNKTYPE, "swarmbox-host")))
        prepped = []
        for i, (label, ti) in enumerate(cases):
            p = self.archive(version="2.0.1")
            with tarfile.open(p, "a") as tf:
                tf.addfile(ti, io.BytesIO(b"") if ti.type == tarfile.REGTYPE else None)
            iso = self.iso_env("unsafe-%d" % i, "IMAGE=%s:2.0.0\n" % REPO, run={"stdout_file": p})
            _, _, _, cfg, host_dir, bindir = iso
            with open(cfg, "rb") as f:
                snap_before = {"host": snap(host_dir), "bin": snap(bindir), "cfg": f.read(), "mode": os.stat(cfg).st_mode}
            prepped.append((label, iso, snap_before))

        def run_one(item):
            label, (helper, e, fp, cfg, host_dir, bindir), snap_before = item
            r = subprocess.run([helper, "update", "--to", "2.0.1"], env=e, capture_output=True, text=True, input="", cwd=self.tmp, timeout=60)
            with open(cfg, "rb") as f:
                snap_after = {"host": snap(host_dir), "bin": snap(bindir), "cfg": f.read(), "mode": os.stat(cfg).st_mode}
            tag_calls = [c for c in fp.calls() if c and c[0] == "tag"]
            return label, r, snap_before, snap_after, tag_calls

        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
            results = list(pool.map(run_one, prepped))
        for label, r, snap_before, snap_after, tag_calls in results:
            with self.subTest(label):
                self.assertEqual(snap_after, snap_before)
                self.assertEqual(len(tag_calls), 0)
                self.assertEqual(r.returncode, 3, r.stderr)
                self.assertFalse(os.path.lexists(escaped))
                self.assertFalse(os.path.lexists(absname))

    def test_an_unwritable_config_folder_is_exit_1_after_the_helper_is_replaced(self):
        # documented order: tag, helper rename, config write; a failing write is the one failure that leaves the new helper
        if os.geteuid() == 0:
            self.skipTest("root ignores the mode")
        self.podman_for("2.99.99")
        os.chmod(self.cfg_dir, 0o500)
        self.addCleanup(os.chmod, self.cfg_dir, 0o700)
        r = self.update()
        self.assertEqual(r.returncode, 1, r.stderr)
        with open(self.cfg) as f:
            self.assertEqual(f.read(), "IMAGE=%s:2.0.0\n" % REPO)


class AfterUpdateTest(UpdateBase):
    def test_reset_after_update_uses_the_exact_tag_and_needs_no_network(self):
        self.podman_for("2.99.99")
        r = self.update()
        self.assertEqual(r.returncode, 0, r.stderr)
        # now the box: no network at all (a fake pull would fail), the exact image is present locally
        conf = self.conf(lookup={"stdout": line(image=REPO + ":2.0.0")},
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
        self.assertIn(REPO + ":2.99.99", runs[0])
        self.assertNotIn(REPO + ":2.0", runs[0])
        self.assertNotIn(REPO + ":2.0.0", runs[0])
        self.assertEqual(self.subs("image")[0][:2], ["image", "exists"])
        self.assertIn("swarmbox.image=%s:2.99.99" % REPO, runs[0])

if __name__ == "__main__":
    unittest.main()
