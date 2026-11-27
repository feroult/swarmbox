"""The test runner tests/run.sh (a front end of tests/support/runner.py).

The runner runs every selected test file as `python3 [-W error] file` under tests/support/reap_run.py, reads the count of tests from the
unittest summary and prints one line per file ("<file> <status> <ran> tests, <skipped> skipped, <s> s") and a total. The selectors
are the folders tests/fast, tests/slow and tests/e2e, and the macos list. These tests run it on a few small files only; they never run
a whole suite from inside the suite.
Run: python3 tests/fast/test_runner.py
"""
import contextlib
import io
import os
import re
import subprocess
import sys
import tempfile
import time
import shutil
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "support"))
from helpers import ROOT  # noqa: E402
import areas  # noqa: E402
import runner as runner_mod  # noqa: E402

RUNNER = os.path.join(ROOT, "tests", "run.sh")
TESTS = os.path.join(ROOT, "tests")


def run(*args, env=None):
    return subprocess.run(["sh", RUNNER, *args], capture_output=True, text=True, cwd=ROOT, timeout=300, env=env)


def run_inproc(*args, env=None):
    """Run runner.main(args) in-process without spawning sh + python3, returning a CompletedProcess-like result."""
    out, err = io.StringIO(), io.StringIO()
    tests_dir = (env or {}).get("SWARMBOX_TESTS_DIR") or TESTS
    old_tests = runner_mod.TESTS
    old_use_fork = runner_mod.USE_FORK
    use_fork = (
        sys.platform.startswith("linux")
        and hasattr(os, "fork")
        and not (env or os.environ).get("SWARMBOX_RUNNER_SUBPROCESS")
    )
    runner_mod.TESTS = tests_dir
    runner_mod.USE_FORK = use_fork
    rc = 0
    try:
        with contextlib.ExitStack() as stack:
            if env is not None:
                stack.enter_context(mock.patch.dict(os.environ, env, clear=True))
            stack.enter_context(contextlib.redirect_stdout(out))
            stack.enter_context(contextlib.redirect_stderr(err))
            try:
                rc = runner_mod.main(list(args))
            except SystemExit as e:
                if e.code is None:
                    rc = 0
                elif isinstance(e.code, int):
                    rc = e.code
                else:
                    err.write("%s\n" % (e.code,))
                    rc = 1
    finally:
        runner_mod.TESTS = old_tests
        runner_mod.USE_FORK = old_use_fork
    return subprocess.CompletedProcess(["runner", *args], rc, out.getvalue(), err.getvalue())


def on_disk(layer):
    return sorted("%s/%s" % (layer, f) for f in os.listdir(os.path.join(TESTS, layer)) if re.match(r"test_.*\.py$", f))


def fake_tests(files):
    """A tests folder of its own (SWARMBOX_TESTS_DIR) with the given fast files; returns (folder, env)."""
    tmp = tempfile.mkdtemp(prefix="swarmbox-test-runner.")
    os.mkdir(os.path.join(tmp, "fast"))
    for name, body in files.items():
        with open(os.path.join(tmp, "fast", name), "w") as f:
            f.write(body)
    return tmp, dict(os.environ, SWARMBOX_TESTS_DIR=tmp)


def fake_git_repo(test_files, extra_files=None):
    """A temporary git repo with tests/fast/ files committed; returns (repo_dir, env)."""
    tmp = tempfile.mkdtemp(prefix="swarmbox-test-runner-git.")
    os.makedirs(os.path.join(tmp, "tests", "fast"))
    for name, body in test_files.items():
        with open(os.path.join(tmp, "tests", "fast", name), "w") as f:
            f.write(body)
    for rel, body in (extra_files or {}).items():
        p = os.path.join(tmp, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as f:
            f.write(body)
    git_env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
    subprocess.run(["git", "init", "-q"], cwd=tmp, check=True, env=git_env)
    subprocess.run(["git", "add", "."], cwd=tmp, check=True, env=git_env)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=tmp, check=True, env=git_env)
    env = dict(os.environ, SWARMBOX_TESTS_DIR=os.path.join(tmp, "tests"))
    return tmp, env


GOOD = "import unittest\nclass T(unittest.TestCase):\n    def test_x(self):\n        pass\nunittest.main()\n"
BAD = "import unittest\nclass T(unittest.TestCase):\n    def test_x(self):\n        self.fail('no')\nunittest.main()\n"


class Runner(unittest.TestCase):
    def test_is_posix_sh_and_selectors_list_their_folders(self):
        with open(RUNNER) as f:
            self.assertEqual(f.readline().rstrip("\n"), "#!/bin/sh")
        p = run("fast", "--list")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(p.stdout.split(), on_disk("fast"), "fast")
        for sel, want in (("slow", on_disk("slow")), ("all", on_disk("fast") + on_disk("slow"))):
            p = run_inproc(sel, "--list")
            self.assertEqual(p.returncode, 0, p.stderr)
            self.assertEqual(p.stdout.split(), want, sel)
        self.assertEqual(run_inproc("--list").stdout.split(), on_disk("fast"), "fast is the default")
        e2e = run_inproc("e2e", "--list").stdout.split()
        self.assertTrue(all(x.startswith("e2e/") and x.endswith(".sh") for x in e2e), "e2e runs only the wrappers that start the container: %s" % e2e)
        self.assertFalse([x for x in run_inproc("all", "--list").stdout.split() if x.startswith("e2e/")], "the e2e harnesses are never part of all")

    def test_shuffle_prints_its_seed_and_the_same_seed_gives_the_same_order(self):
        tmp, env = fake_tests({"test_%s.py" % c: GOOD for c in "abcdef"})
        self.addCleanup(shutil.rmtree, tmp, True)
        first = run_inproc("fast", "-j", "1", "--shuffle", "7", env=env).stdout
        self.assertIn("shuffle seed 7", first)
        again = run_inproc("fast", "-j", "1", "--shuffle", "7", env=env).stdout
        order = lambda t: [l.split()[0] for l in t.splitlines() if l.endswith("s") and " OK " in l]  # noqa: E731
        self.assertEqual(len(order(first)), 6)
        self.assertEqual(order(first), order(again))

    def test_the_macos_list_names_fast_files_only(self):
        p = run_inproc("macos", "--list")
        self.assertEqual(p.returncode, 0, p.stderr)
        listed = p.stdout.split()
        self.assertGreater(len(listed), 10)
        self.assertTrue(set(listed) <= set(on_disk("fast")), set(listed) - set(on_disk("fast")))

    def test_only_runs_the_named_files_an_unknown_name_is_an_error_and_repeat_runs_each_n_times(self):
        tmp, env = fake_tests({"test_good.py": GOOD, "test_other.py": GOOD})
        self.addCleanup(shutil.rmtree, tmp, True)
        p = run_inproc("--only", "test_good.py,test_probe_missing.py", env=env)
        self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
        self.assertIn("test_probe_missing.py", p.stderr)
        p = run_inproc("--only", "test_good.py", "--werror", env=env)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertRegex(p.stdout, r"(?m)^test_good\.py OK \d+ tests, \d+ skipped, [\d.]+ s$")
        self.assertRegex(p.stdout, r"(?m)^TOTAL 1 files, (\d+) tests, 0 failed files")
        self.assertIn("slowest files:", p.stdout)
        self.assertNotIn("test_other.py", p.stdout)
        self.assertEqual(run_inproc("slow", "--only", "test_good.py", env=env).returncode, 2, "test_good.py is not a slow test")
        p = run_inproc("--only", "test_good.py", "--repeat", "2", env=env)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(len(re.findall(r"(?m)^test_good\.py OK", p.stdout)), 2)
        self.assertIn("TOTAL 2 runs", p.stdout)

    def test_a_failing_file_makes_the_runner_fail_and_files_run_in_parallel(self):
        tmp, env = fake_tests({"test_bad.py": BAD, "test_good.py": GOOD})
        self.addCleanup(shutil.rmtree, tmp, True)
        for j in ("1", "2"):
            p = run_inproc("-j", j, env=env)
            self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
            self.assertRegex(p.stdout, r"(?m)^test_bad\.py FAIL")
            self.assertRegex(p.stdout, r"(?m)^test_good\.py OK 1 tests")
            self.assertRegex(p.stdout, r"TOTAL 2 files, 2 tests, 1 failed files")
        p = run_inproc("--github", env=env)
        self.assertIn("::error title=test_bad.py failed::", p.stdout)

    def test_a_file_gets_no_terminal_and_the_terminal_of_the_runner_is_left_as_it_was(self):
        """A file once started a full-screen panel on the developer's terminal and left it in raw mode (the lines of the output no longer returned to
        the first column). The runner gives every file /dev/null as its stdin, and puts its own terminal back whatever happened."""
        import pty
        import select
        import termios
        body = ("import os, unittest\nclass T(unittest.TestCase):\n    def test_no_terminal(self):\n"
                "        self.assertFalse(os.isatty(0))\nunittest.main()\n")
        tmp, env = fake_tests({"test_tty.py": body})
        self.addCleanup(shutil.rmtree, tmp, True)
        master, slave = pty.openpty()
        self.addCleanup(os.close, master)
        self.addCleanup(os.close, slave)
        before = termios.tcgetattr(slave)
        p = subprocess.Popen(["sh", RUNNER], stdin=slave, stdout=slave, stderr=slave, env=env, cwd=ROOT, start_new_session=True)
        out = b""
        deadline = time.time() + 120
        while p.poll() is None and time.time() < deadline:
            if select.select([master], [], [], 0.02)[0]:
                out += os.read(master, 65536)
        self.assertEqual(p.poll(), 0, out.decode(errors="replace"))
        try:
            after = termios.tcgetattr(slave)
        except termios.error:
            return       # macOS: the terminal of a session that has ended cannot be asked any more; nothing of it is left to be found changed
        self.assertEqual(after, before, "the runner left its terminal changed")

    def test_a_file_over_its_time_limit_is_killed_and_reported(self):
        tmp, env = fake_tests({"test_hang.py": "import time\ntime.sleep(60)\n"})
        self.addCleanup(shutil.rmtree, tmp, True)
        p = run_inproc("--timeout", "0.05", env=env)
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertRegex(p.stdout, r"(?m)^test_hang\.py FAIL")
        self.assertIn("time limit", p.stdout)

    def test_multi_class_file_shards_safely_and_respects_module_hooks(self):
        sharded = (
            "import unittest\n"
            "class A(unittest.TestCase):\n    def test_a(self): pass\n"
            "class B(unittest.TestCase):\n    def test_b(self): pass\n"
            "class C(unittest.TestCase):\n    @unittest.skip('s')\n    def test_c(self): pass\n"
            "if __name__ == '__main__':\n    unittest.main()\n"
        )
        tmp_log = tempfile.mkdtemp(prefix="swarmbox-test-runner.")
        self.addCleanup(shutil.rmtree, tmp_log, True)
        hook_file = os.path.join(tmp_log, "hooks")
        hooked = (
            "import unittest\n"
            "def setUpModule():\n    open(%r, 'a').write('x')\n"
            "class A(unittest.TestCase):\n    def test_a(self): pass\n"
            "class B(unittest.TestCase):\n    def test_b(self): pass\n"
            "if __name__ == '__main__':\n    unittest.main()\n" % hook_file
        )
        folder, env = fake_tests({"test_sharded.py": sharded, "test_hooked.py": hooked})
        self.addCleanup(shutil.rmtree, folder, True)
        p = run_inproc("-j", "4", env=env)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertRegex(p.stdout, r"(?m)^test_sharded\.py OK 3 tests, 1 skipped, [\d.]+ s$")
        self.assertRegex(p.stdout, r"(?m)^test_hooked\.py OK 2 tests, 0 skipped, [\d.]+ s$")
        self.assertRegex(p.stdout, r"TOTAL 2 files, 5 tests, 0 failed files")
        with open(hook_file) as f:
            self.assertEqual(f.read(), "x", "setUpModule must run once, not once per class")

    @unittest.skipUnless(sys.platform.startswith("linux"), "reap_run adopts orphans with a Linux child subreaper (prctl)")
    def test_orphans_left_by_a_file_are_killed_and_counted(self):
        tmp = tempfile.mkdtemp(prefix="swarmbox-test-runner.")
        self.addCleanup(shutil.rmtree, tmp, True)
        pidfile = os.path.join(tmp, "pid")
        leak = ("import subprocess, unittest\nclass T(unittest.TestCase):\n    def test_x(self):\n"
                "        p = subprocess.Popen(['sleep', '60'], start_new_session=True)\n"
                "        open(%r, 'w').write(str(p.pid))\nunittest.main()\n" % pidfile)
        folder, env = fake_tests({"test_leak.py": leak})
        self.addCleanup(shutil.rmtree, folder, True)
        p = run_inproc(env=env)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertRegex(p.stdout, r"(?m)^test_leak\.py OK 1 tests, 0 skipped, [\d.]+ s, reaped 1$")
        with open(pidfile) as f:
            pid = int(f.read())
        self.addCleanup(lambda: os.path.exists("/proc/%d" % pid) and os.kill(pid, 9))
        self.assertFalse(os.path.exists("/proc/%d" % pid) and "sleep" in open("/proc/%d/cmdline" % pid).read())

    def test_usage_errors_exit_2_and_the_runner_starts_nothing_dangerous(self):
        self.assertEqual(run("--nonsense").returncode, 2, ["--nonsense"])
        for args in (["--repeat", "0"], ["-j", "x"], ["--only"], ["--area"], ["--area", "no-such-area"], ["--since"]):
            self.assertEqual(run_inproc(*args).returncode, 2, args)
        with open(os.path.join(TESTS, "support", "runner.py")) as f:
            src = f.read()
        for bad in ("pkill", "killall", "kill-server", "podman system", "rm -rf /", "--all"):
            self.assertNotIn(bad, src)

    def test_commit_and_smoke_are_aliases_for_fast_and_slow(self):
        self.assertEqual(run_inproc("commit", "--list").stdout.split(), on_disk("fast"))
        self.assertEqual(run_inproc("smoke", "--list").stdout.split(), on_disk("slow"))

    def test_areas_are_valid_and_area_flag_selects_area_plus_guards(self):
        fast_basenames = set(os.path.basename(f) for f in on_disk("fast"))
        required = {"guards", "herdr", "sysop", "voice", "host", "tabs", "bus", "worktree", "addons", "release", "runner"}
        self.assertTrue(required <= set(areas.AREAS), required - set(areas.AREAS))
        for g in areas.GUARDS:
            self.assertIn(g, fast_basenames)
        for name, files in areas.AREAS.items():
            for f in files:
                self.assertIn(f, fast_basenames, "area %s references missing %s" % (name, f))
        p_guards = run_inproc("--area", "guards", "--list")
        self.assertEqual(p_guards.returncode, 0, p_guards.stderr)
        self.assertEqual(p_guards.stdout.split(), sorted("fast/%s" % g for g in areas.GUARDS))
        p_csv = run_inproc("--area", "tabs,bus", "--list")
        p_rep = run_inproc("--area", "tabs", "--area", "bus", "--list")
        self.assertEqual(p_csv.returncode, 0, p_csv.stderr)
        self.assertEqual(p_csv.stdout.split(), p_rep.stdout.split())
        self.assertIn("fast/test_tabs.py", p_csv.stdout.split())
        self.assertIn("fast/test_bus.py", p_csv.stdout.split())
        for g in areas.GUARDS:
            self.assertIn("fast/%s" % g, p_csv.stdout.split())
        p_bad = run_inproc("--area", "unknown_xyz")
        self.assertEqual(p_bad.returncode, 2)
        self.assertIn("available:", p_bad.stderr)
        self.assertIn("herdr", p_bad.stderr)

    def test_fail_fast_stops_running_and_queued_jobs_in_fork_and_subprocess_modes(self):
        slow = "import time, unittest\nclass T(unittest.TestCase):\n    def test_slow(self):\n        time.sleep(30)\nunittest.main()\n"
        # Pad test_fail.py slightly so it is sorted early and starts immediately alongside one slow job.
        fast_fail = BAD + ("# pad\n" * 40)
        tmp, env = fake_tests({
            "test_fail.py": fast_fail,
            "test_slow_a.py": slow,
            "test_slow_b.py": slow,
        })
        self.addCleanup(shutil.rmtree, tmp, True)
        for mode, extra_env in (("fork", {}), ("subprocess", {"SWARMBOX_RUNNER_SUBPROCESS": "1"})):
            run_env = dict(env, **extra_env)
            t0 = time.monotonic()
            p = run_inproc("-j", "2", "--fail-fast", env=run_env)
            elapsed = time.monotonic() - t0
            self.assertEqual(p.returncode, 1, "%s: %s" % (mode, p.stdout + p.stderr))
            self.assertLess(elapsed, 10.0, "%s: fail-fast took %.1fs" % (mode, elapsed))
            self.assertRegex(p.stdout, r"(?m)^test_fail\.py FAIL")
            self.assertNotIn("test_slow_b.py OK", p.stdout)
            self.assertNotIn("test_slow_a.py OK", p.stdout)

    def test_loop_clean_tree_domain_edit_test_edit_and_since(self):
        base_tests = {
            "test_layout.py": GOOD,
            "test_dockerfile.py": GOOD,
            "test_guard_agents.py": GOOD,
            "test_guard_mux.py": GOOD,
            "test_herdr_backend.py": GOOD,
            "test_bus.py": GOOD,
            "test_worktree.py": GOOD,
        }
        repo, env = fake_git_repo(base_tests, {
            "container/web/herdr/server.mjs": "// v1\n",
            "container/scripts/swarmbox-bus.py": "# v1\n",
            "Dockerfile": "FROM scratch\n",
        })
        self.addCleanup(shutil.rmtree, repo, True)

        # Clean tree: runs guards only and prints note.
        p = run_inproc("loop", env=env)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn("loop: clean tree, running guards", p.stdout)
        self.assertRegex(p.stdout, r"TOTAL 4 files, 4 tests, 0 failed files")
        self.assertNotIn("test_herdr_backend.py", p.stdout)

        # Domain edit: herdr file -> herdr tests + guards.
        herdr_file = os.path.join(repo, "container", "web", "herdr", "server.mjs")
        with open(herdr_file, "w") as f:
            f.write("// v2\n")
        listed = run_inproc("loop", "--list", env=env).stdout.split()
        self.assertIn("fast/test_herdr_backend.py", listed)
        self.assertIn("fast/test_layout.py", listed)
        self.assertNotIn("fast/test_bus.py", listed)
        # Restore herdr file.
        with open(herdr_file, "w") as f:
            f.write("// v1\n")

        # Direct test-file edit (untracked new test file): included directly + guards.
        new_test = os.path.join(repo, "tests", "fast", "test_custom_feature.py")
        with open(new_test, "w") as f:
            f.write(GOOD)
        listed = run_inproc("loop", "--list", env=env).stdout.split()
        self.assertIn("fast/test_custom_feature.py", listed)
        self.assertIn("fast/test_layout.py", listed)
        self.assertNotIn("fast/test_bus.py", listed)
        os.remove(new_test)

        # --since / --ref diffs against a git ref even when working tree is clean.
        with open(os.path.join(repo, "container", "scripts", "swarmbox-bus.py"), "w") as f:
            f.write("# v2\n")
        git_env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
        subprocess.run(["git", "add", "container/scripts/swarmbox-bus.py"], cwd=repo, check=True, env=git_env)
        subprocess.run(["git", "commit", "-q", "-m", "bus change"], cwd=repo, check=True, env=git_env)
        self.assertEqual(len(run_inproc("loop", "--list", env=env).stdout.split()), 4)
        since_list = run_inproc("loop", "--since", "HEAD~1", "--list", env=env).stdout.split()
        ref_list = run_inproc("loop", "--ref", "HEAD~1", "--list", env=env).stdout.split()
        self.assertEqual(since_list, ref_list)
        self.assertIn("fast/test_bus.py", since_list)
        self.assertNotIn("fast/test_herdr_backend.py", since_list)
        self.assertEqual(run_inproc("loop", "--since", "no-such-ref-xyz", env=env).returncode, 2)

    def test_loop_falls_back_to_full_fast_on_shared_infra_and_unmapped_files(self):
        base_tests = {
            "test_layout.py": GOOD,
            "test_dockerfile.py": GOOD,
            "test_guard_agents.py": GOOD,
            "test_guard_mux.py": GOOD,
            "test_bus.py": GOOD,
            "test_worktree.py": GOOD,
        }
        shared_files = {
            "Dockerfile": "FROM scratch\n",
            "tests/support/helpers.py": "# helper\n",
            "container/scripts/swarmbox-agents.py": "# agents\n",
            "container/entrypoint.sh": "#!/bin/sh\n",
            "container/config/bashrc.sh": "# bashrc\n",
        }
        repo, env = fake_git_repo(base_tests, shared_files)
        self.addCleanup(shutil.rmtree, repo, True)
        all_fast = sorted("fast/%s" % n for n in base_tests)

        for shared, orig in shared_files.items():
            p_abs = os.path.join(repo, shared)
            with open(p_abs, "a") as f:
                f.write("# edit\n")
            p = run_inproc("loop", env=env)
            self.assertEqual(p.returncode, 0, "%s: %s" % (shared, p.stdout + p.stderr))
            self.assertIn("shared infra changed", p.stdout, shared)
            self.assertEqual(run_inproc("loop", "--list", env=env).stdout.split(), all_fast, shared)
            with open(p_abs, "w") as f:
                f.write(orig)

        # Unmapped production file also falls back safely to full fast suite.
        unmapped = os.path.join(repo, "container", "scripts", "brand_new_unmapped.py")
        os.makedirs(os.path.dirname(unmapped), exist_ok=True)
        with open(unmapped, "w") as f:
            f.write("# new\n")
        p = run_inproc("loop", env=env)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn("unmapped file changed", p.stdout)
        self.assertEqual(run_inproc("loop", "--list", env=env).stdout.split(), all_fast)

    def test_loop_implies_fail_fast_and_no_fail_fast_overrides_it(self):
        repo, env = fake_git_repo({
            "test_layout.py": BAD + ("# pad\n" * 40),
            "test_dockerfile.py": "import time, unittest\nclass T(unittest.TestCase):\n    def test_s(self):\n        time.sleep(30)\nunittest.main()\n",
            "test_guard_agents.py": GOOD,
            "test_guard_mux.py": GOOD,
        })
        self.addCleanup(shutil.rmtree, repo, True)
        t0 = time.monotonic()
        p = run_inproc("loop", "-j", "2", env=env)
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertLess(time.monotonic() - t0, 10.0)
        self.assertNotIn("test_dockerfile.py OK", p.stdout)

        # Replace sleeping guard with a fast passing guard and verify --no-fail-fast runs all 4 guards.
        with open(os.path.join(repo, "tests", "fast", "test_dockerfile.py"), "w") as f:
            f.write(GOOD)
        p_all = run_inproc("loop", "-j", "1", "--no-fail-fast", env=env)
        self.assertEqual(p_all.returncode, 1, p_all.stdout + p_all.stderr)
        self.assertRegex(p_all.stdout, r"TOTAL 4 files, 4 tests, 1 failed files")


if __name__ == "__main__":
    unittest.main()
