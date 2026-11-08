"""Slice 3.6: `swarmbox-host update [--to TAG]` (design 3.7.2, 3.8 "Update flow", "Rollback", D17, D27, D33, D35, B20).

The helper runs as a real program against the shared FakePodman, which records every call. The "image" is a tar archive built in
Python (tests/function_cases.make_archive: swarmbox-host, VERSION, ...) that the fake `podman run ... host-helper` writes to
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
from function_cases import make_archive  # noqa: E402
from helpers import ROOT  # noqa: E402

REPO = "localhost:34567/org/swarmbox"
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

    def write_config(self, text):
        os.makedirs(self.cfg_dir, exist_ok=True)
        with open(self.cfg, "w") as f:
            f.write(text)
        os.chmod(self.cfg, 0o600)

    def install_old_helper(self, version):
        os.makedirs(self.host_dir, exist_ok=True)
        for n, c in (("swarmbox-host", "#!/bin/sh\necho old\n"), ("VERSION", version + "\n"), ("tool-ports", "")):
            p = os.path.join(self.host_dir, n)
            with open(p, "w") as f:
                f.write(c)
        os.chmod(os.path.join(self.host_dir, "swarmbox-host"), 0o755)

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

    def podman_for(self, version="2.0.1", pull=None, tag=None, run=None, **archive_kw):
        conf = {"pull": pull or {}, "tag": tag or {},
                "run": run or {"stdout_file": self.archive(version=version, **archive_kw)}}
        return self.podman(**conf)

    def update(self, *args, **extra):
        return self.run_h("update", *args, env=self.env(**extra))

    def names(self):
        return [c[0] for c in self.calls()]

    def assert_unchanged(self, before, tag_calls=0):
        self.assertEqual(snap(self.host_dir), before["host"])
        with open(self.cfg, "rb") as f:
            self.assertEqual(f.read(), before["cfg"])
        self.assertEqual(os.stat(self.cfg).st_mode, before["mode"])
        self.assertEqual(len(self.subs("tag")), tag_calls)

    def before(self):
        with open(self.cfg, "rb") as f:
            return {"host": snap(self.host_dir), "cfg": f.read(), "mode": os.stat(self.cfg).st_mode}


class PlainUpdateTest(UpdateBase):
    def test_pulls_the_series_tag_reads_the_version_tags_and_writes_image(self):
        self.podman_for("2.0.1")
        r = self.update()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.calls(), [
            ["pull", "-q", REPO + ":2.0"],
            ["run", "--rm", REPO + ":2.0", "host-helper"],
            ["tag", REPO + ":2.0", REPO + ":2.0.1"],
        ])
        self.assertEqual(self.image_line(), ["IMAGE=%s:2.0.1" % REPO])
        with open(os.path.join(self.host_dir, "VERSION")) as f:
            self.assertEqual(f.read().strip(), "2.0.1")
        self.assertTrue(os.access(os.path.join(self.host_dir, "swarmbox-host"), os.X_OK))

    def test_the_success_message_is_exact_and_everything_else_is_quiet(self):
        self.podman_for("2.0.1")
        r = self.update()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout, MSG % "2.0.1")
        self.assertEqual(r.stderr, "swarmbox: pulling %s:2.0 (this can take a while)...\n" % REPO)

    def test_the_config_keeps_its_other_lines_and_its_mode(self):
        self.write_config("# mine\nWEB_PORT=9000\nIMAGE=%s:2.0.0\nWITH=claude\n" % REPO)
        self.podman_for("2.0.3")
        r = self.update()
        self.assertEqual(r.returncode, 0, r.stderr)
        text = self.config_text()
        self.assertIn("# mine\n", text)
        self.assertIn("WEB_PORT=9000\n", text)
        self.assertIn("WITH=claude\n", text)
        self.assertEqual(self.image_line(), ["IMAGE=%s:2.0.3" % REPO])
        self.assertEqual(os.stat(self.cfg).st_mode & 0o777, 0o600)

    def test_the_series_comes_from_the_current_image_tag(self):
        for tag, series in (("2.0.0", "2.0"), ("2.1", "2.1"), ("10.12.3", "10.12"), ("3.4.5-rc1", "3.4")):
            with self.subTest(tag=tag):
                self.write_config("IMAGE=%s:%s\n" % (REPO, tag))
                self.podman_for("%s.9" % series)
                r = self.update()
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertEqual(self.calls()[0], ["pull", "-q", "%s:%s" % (REPO, series)])
                self.assertEqual(self.image_line(), ["IMAGE=%s:%s.9" % (REPO, series)])

    def test_the_repo_with_a_registry_port_is_kept_whole(self):
        for repo in ("localhost:5000/org/swarmbox", "registry.example.com:8443/a/b/swarmbox", "ghcr.io/org/swarmbox",
                     "swarmbox", "localhost/swarmbox"):
            with self.subTest(repo=repo):
                self.write_config("IMAGE=%s:2.0.0\n" % repo)
                self.podman_for("2.0.4")
                r = self.update()
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertEqual(self.calls()[0], ["pull", "-q", repo + ":2.0"])
                self.assertEqual(self.calls()[2], ["tag", repo + ":2.0", repo + ":2.0.4"])
                self.assertEqual(self.image_line(), ["IMAGE=%s:2.0.4" % repo])

    def test_without_a_config_the_default_image_series_is_used(self):
        os.unlink(self.cfg)
        self.podman_for("2.0.2")
        r = self.update()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.calls()[0], ["pull", "-q", "ghcr.io/<org>/swarmbox:2.0"])
        self.assertEqual(self.image_line(), ["IMAGE=ghcr.io/<org>/swarmbox:2.0.2"])
        self.assertEqual(os.stat(self.cfg).st_mode & 0o777, 0o600)

    def test_an_environment_image_is_used_for_the_repo_and_the_override_is_reported(self):
        self.podman_for("2.0.1")
        r = self.update(SWARMBOX_IMAGE="localhost:1/x/sb:2.0.0")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.calls()[0], ["pull", "-q", "localhost:1/x/sb:2.0"])
        self.assertIn("SWARMBOX_IMAGE is set", r.stderr)
        self.assertIn("overrides", r.stderr)
        self.assertEqual(self.image_line(), ["IMAGE=localhost:1/x/sb:2.0.1"])

    def test_an_image_that_is_not_in_a_series_is_exit_2_before_any_podman_call(self):
        for ref in ("swarmbox", "%s:dev" % REPO, "%s:latest" % REPO, "%s:2" % REPO, "%s:main-2.0" % REPO):
            with self.subTest(ref=ref):
                self.write_config("IMAGE=%s\n" % ref)
                self.podman_for("2.0.1")
                before = self.before()
                r = self.update()
                self.assertEqual(r.returncode, 2, r.stderr)
                self.assertIn("update --to", r.stderr)
                self.assertEqual(self.calls(), [])
                self.assert_unchanged(before)

    def test_an_image_pinned_by_digest_is_refused_for_a_plain_update(self):
        d = "@sha256:" + "a" * 64
        for ref in (REPO + d, REPO + ":2.0.0" + d):
            with self.subTest(ref=ref):
                self.write_config("IMAGE=%s\n" % ref)
                self.podman_for("2.0.1")
                before = self.before()
                r = self.update()
                self.assertEqual(r.returncode, 2, r.stderr)
                self.assertIn("digest", r.stderr)
                self.assertIn("update --to", r.stderr)
                self.assertEqual(self.calls(), [])
                self.assert_unchanged(before)

    def test_update_never_recreates_the_box(self):
        # D27: no rm, stop, start, create, a box run or an inspect of the box: pull, the helper's `run --rm` and tag only
        self.podman_for("2.0.1")
        r = self.update()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(sorted(self.names()), ["pull", "run", "tag"])
        for c in self.subs("run"):
            self.assertEqual(c[:2], ["run", "--rm"])
            self.assertEqual(c[-1], "host-helper")

    def test_it_needs_no_lock_and_leaves_no_temporary_folder(self):
        self.podman_for("2.0.1")
        r = self.update()
        self.assertEqual(r.returncode, 0, r.stderr)
        parent = os.path.dirname(self.host_dir)
        self.assertEqual(sorted(os.listdir(parent)), ["host"])

    def test_a_missing_helper_folder_is_created_by_update(self):
        shutil.rmtree(self.host_dir)
        self.podman_for("2.0.1")
        r = self.update()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(os.access(os.path.join(self.host_dir, "swarmbox-host"), os.X_OK))

    def test_the_same_version_again_still_succeeds(self):
        self.podman_for("2.0.0")
        r = self.update()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout, MSG % "2.0.0")
        self.assertEqual(self.image_line(), ["IMAGE=%s:2.0.0" % REPO])


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

    def test_to_with_an_equals_sign(self):
        self.podman_for("2.0.9")
        r = self.update("--to=2.0.9")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.calls()[0], ["pull", "-q", REPO + ":2.0.9"])

    def test_to_a_moving_tag_tags_the_exact_version(self):
        for tag in ("2.1", "3", "latest", "edge"):
            with self.subTest(tag=tag):
                self.podman_for("2.1.7")
                r = self.update("--to", tag)
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertEqual(self.subs("tag"), [["tag", "%s:%s" % (REPO, tag), REPO + ":2.1.7"]])
                self.assertEqual(self.image_line(), ["IMAGE=%s:2.1.7" % REPO])

    def test_to_works_with_a_digest_pinned_image(self):
        self.write_config("IMAGE=%s:2.0.0@sha256:%s\n" % (REPO, "b" * 64))
        self.podman_for("2.2.0")
        r = self.update("--to", "2.2.0")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.calls()[0], ["pull", "-q", REPO + ":2.2.0"])
        self.assertEqual(self.image_line(), ["IMAGE=%s:2.2.0" % REPO])

    def test_to_works_when_the_current_image_has_no_series(self):
        self.write_config("IMAGE=%s:dev\n" % REPO)
        self.podman_for("2.0.0")
        r = self.update("--to", "2.0.0")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.image_line(), ["IMAGE=%s:2.0.0" % REPO])

    def test_an_invalid_tag_is_exit_2_before_any_podman_call(self):
        bad = ["", "a/b", "a:b", "a b", "-x", ".x", "a@b", "x" * 129, "$(id)", "a\nb", "a;b", "a'b", "a`b", "ü", "*", "a\tb",
               "sha256:abc", "2.0.0@sha256:" + "a" * 64, "a\\b", "a?b"]
        for tag in bad:
            with self.subTest(tag=tag):
                self.podman_for("2.0.1")
                before = self.before()
                r = self.update("--to", tag)
                self.assertEqual(r.returncode, 2, r.stderr)
                self.assertEqual(r.stdout, "")
                self.assertIn("tag", r.stderr)
                self.assertEqual(self.calls(), [])
                self.assert_unchanged(before)

    def test_the_longest_valid_tag_is_accepted(self):
        self.podman_for("2.0.1")
        tag = "a" + "b" * 127
        r = self.update("--to", tag)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.calls()[0][-1], "%s:%s" % (REPO, tag))

    def test_usage_errors_are_exit_2_and_call_nothing(self):
        for args in (["--to"], ["--to", "2.0.1", "x"], ["x"], ["--bogus"], ["--to", "2.0.1", "--to", "2.0.2"], ["--to="]):
            with self.subTest(args=args):
                self.podman_for("2.0.1")
                before = self.before()
                r = self.update(*args)
                self.assertEqual(r.returncode, 2, r.stderr)
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
                self.podman_for("2.0.1", pull={"exit": 125, "stderr": "Error: unable to pull: connection refused\n"})
                r = self.update(*args)
                self.check_nothing_changed(r)
                self.assertIn("cannot pull %s:" % REPO, r.stderr)
                self.assertIn("connection refused", r.stderr)
                self.assertEqual(self.names(), ["pull"])

    def test_no_podman_is_exit_3(self):
        path = os.path.join(self.tmp, "nopath")
        os.mkdir(path)
        for t in ("sh", "dash", "bash", "cat", "rm", "mkdir", "sed", "tr", "head", "tail", "dirname", "mktemp", "mv", "chmod",
                  "printf", "tar", "uname", "date", "grep"):
            src = shutil.which(t)
            if src:
                os.symlink(src, os.path.join(path, t))
        env = self.env(PATH=path)
        r = subprocess.run(["/bin/sh", self.helper, "update"], env=env, capture_output=True, text=True, input="", cwd=self.tmp)
        self.assertEqual(r.returncode, 3, r.stderr)
        self.assertIn("Podman is not installed", r.stderr)
        self.assertEqual(snap(self.host_dir), self.snapshot["host"])
        self.assertEqual(self.config_text(), "IMAGE=%s:2.0.0\n" % REPO)

    def test_a_helper_that_is_not_executable_in_the_image_is_exit_3_and_changes_nothing(self):
        self.podman_for("2.0.1", executable=False)
        r = self.update()
        self.check_nothing_changed(r)
        self.assertIn("no usable host helper", r.stderr)
        self.assertEqual(self.subs("tag"), [])

    def test_an_archive_with_no_helper_is_exit_3(self):
        self.podman_for("2.0.1", helper=False)
        r = self.update()
        self.check_nothing_changed(r)
        self.assertIn("no usable host helper", r.stderr)

    def test_garbage_instead_of_an_archive_is_exit_3(self):
        bad = os.path.join(self.tmp, "garbage")
        with open(bad, "wb") as f:
            f.write(b"this is not a tar archive\n" * 50)
        self.podman_for(run={"stdout_file": bad})
        r = self.update()
        self.check_nothing_changed(r)
        self.assertIn("no usable host helper", r.stderr)

    def test_a_failing_host_helper_run_is_exit_3(self):
        self.podman_for(run={"exit": 126, "stderr": "Error: crun: executable file `host-helper` not found\n"})
        r = self.update()
        self.check_nothing_changed(r)
        self.assertIn("not found", r.stderr)
        self.assertEqual(self.subs("tag"), [])

    def test_a_helper_that_reports_no_version_is_exit_3(self):
        for version in ("", "banana", "2.0", "2.0.1; rm -rf /"):
            with self.subTest(version=version):
                self.podman_for(version)
                r = self.update()
                self.check_nothing_changed(r)
                self.assertIn("version", r.stderr)

    def test_a_failed_tag_is_exit_3_with_nothing_written(self):
        self.podman_for("2.0.1", tag={"exit": 125, "stderr": "Error: tag: no such image\n"})
        r = self.update()
        self.check_nothing_changed(r, tag_calls=1)
        self.assertIn("cannot tag", r.stderr)
        self.assertIn("no such image", r.stderr)
        self.assertEqual(self.image_line(), ["IMAGE=%s:2.0.0" % REPO])

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
        self.podman_for("2.0.1")
        os.chmod(self.cfg_dir, 0o500)
        self.addCleanup(os.chmod, self.cfg_dir, 0o700)
        r = self.update()
        self.assertEqual(r.returncode, 1, r.stderr)
        with open(self.cfg) as f:
            self.assertEqual(f.read(), "IMAGE=%s:2.0.0\n" % REPO)


class AfterUpdateTest(UpdateBase):
    def test_reset_after_update_uses_the_exact_tag_and_needs_no_network(self):
        self.podman_for("2.0.1")
        r = self.update()
        self.assertEqual(r.returncode, 0, r.stderr)
        # now the box: no network at all (a fake pull would fail), the exact image is present locally
        conf = self.conf(lookup={"stdout": up_tests.line(image=REPO + ":2.0.0")},
                         pull={"exit": 125, "stderr": "Error: no route to host\n"})
        self.fp.configure(conf)
        open(self.fp.log_path, "w").close()
        env = self.env()
        env.pop("SWARMBOX_IMAGE", None)
        # the helper that update installed is the one that runs
        r = subprocess.run([self.helper, "reset"], env=env, capture_output=True, text=True, input="", cwd=self.tmp, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.subs("pull"), [])
        runs = self.real_runs()
        self.assertEqual(len(runs), 1)
        self.assertIn(REPO + ":2.0.1", runs[0])
        self.assertNotIn(REPO + ":2.0", runs[0])
        self.assertNotIn(REPO + ":2.0.0", runs[0])
        self.assertEqual(self.subs("image")[0][:2], ["image", "exists"])
        self.assertIn("swarmbox.image=%s:2.0.1" % REPO, runs[0])

    def test_the_next_call_of_the_function_keeps_the_updated_helper(self):
        bash = shutil.which("bash")
        init = os.path.join(ROOT, "container", "scripts", "swarmbox-init.sh")
        hd = os.path.join(self.tmp, "initdir")
        os.makedirs(hd)
        os.symlink(os.path.join(ROOT, "container", "host", "templates"), os.path.join(hd, "templates"))
        with open(os.path.join(hd, "VERSION"), "w") as f:
            f.write("2.0.0\n")
        r = subprocess.run(["sh", init, "--shell", "bash", "--image", REPO + ":2.0.0"], capture_output=True, text=True,
                           env={"PATH": os.environ["PATH"], "SWARMBOX_TEST_HOST_DIR": hd})
        self.assertEqual(r.returncode, 0, r.stderr)
        fn = os.path.join(self.tmp, "fn.bash")
        with open(fn, "w") as f:
            f.write(r.stdout)
        # the old helper (2.0.0) is replaced by update with 2.0.1 (newer than the function's marker 2.0.0)
        self.podman_for("2.0.1")
        r = self.update()
        self.assertEqual(r.returncode, 0, r.stderr)
        open(self.fp.log_path, "w").close()
        env = self.env()
        env["XDG_DATA_HOME"] = os.path.join(self.home, ".local", "share")
        r = subprocess.run([bash, "--noprofile", "--norc", "-c", '. "$1"; swarmbox version', "bash", fn], env=env,
                           capture_output=True, text=True, input="", cwd=self.tmp)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), "2.0.1")
        self.assertIn("the helper (2.0.1) is newer than this function (2.0.0); kept", r.stderr)
        self.assertEqual(self.subs("run"), [], "the bootstrap must not extract again")
        with open(os.path.join(self.host_dir, "VERSION")) as f:
            self.assertEqual(f.read().strip(), "2.0.1")


class StaticTest(unittest.TestCase):
    def test_update_is_routed_and_only_remote_is_still_unimplemented(self):
        with open(os.path.join(ROOT, "container", "host", "swarmbox-host")) as f:
            text = f.read()
        self.assertIn("cmd_update()", text)
        self.assertIn("update) cmd_update", text)
        self.assertNotIn("update|remote)", text)


if __name__ == "__main__":
    unittest.main()
