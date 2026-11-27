"""Fast tests for container/scripts/swarmbox-worktree.py using real temporary Git repositories.

Covers: inspect (main repo, managed worktree, external worktree, non-git dir), create (HEAD start,
root .env copy with 0600 mode, skipping .env.example and oversized files, .swarmbox-worktree manifest,
uncommitted source detection), status (ahead/behind, in-memory git merge-tree clean & conflict detection),
merge (fast-forward, squash, --clean, refusing dirty worktree / dirty base / wrong branch / conflict),
remove (refusing dirty/unmerged without --force, --force cleanup), and prefs persistence.

Run: python3 tests/fast/test_worktree.py
"""
import importlib.util
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "support"))
from helpers import ROOT  # noqa: E402

WT_SCRIPT = os.path.join(ROOT, "container", "scripts", "swarmbox-worktree.py")
_spec = importlib.util.spec_from_file_location("swarmbox_worktree_mod", WT_SCRIPT)
wt = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(wt)


def git(cwd, *args):
    r = subprocess.run(
        ["git", *args],
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=True,
        env={
            **os.environ,
            "GIT_AUTHOR_NAME": "Test",
            "GIT_AUTHOR_EMAIL": "test@example.com",
            "GIT_COMMITTER_NAME": "Test",
            "GIT_COMMITTER_EMAIL": "test@example.com",
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_CONFIG_SYSTEM": "/dev/null",
        },
    )
    return r.stdout.strip()


class WorktreeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tpl_tmp = tempfile.mkdtemp(prefix="swarmbox-test-wt-tpl.")
        cls.addClassCleanup(shutil.rmtree, cls._tpl_tmp, True)
        cls._tpl_repo = os.path.join(cls._tpl_tmp, "shop-api")
        os.makedirs(cls._tpl_repo, exist_ok=True)
        git(cls._tpl_repo, "init", "-q", "-b", "main")
        git(cls._tpl_repo, "config", "user.name", "Test")
        git(cls._tpl_repo, "config", "user.email", "test@example.com")
        with open(os.path.join(cls._tpl_repo, "app.py"), "w", encoding="utf-8") as f:
            f.write("def greet():\n    return 'hello'\n")
        git(cls._tpl_repo, "add", "app.py")
        git(cls._tpl_repo, "commit", "-q", "-m", "initial")

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="swarmbox-test-wt.")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.home = os.path.join(self.tmp, "home")
        self.repo = os.path.join(self.home, "shop-api")
        shutil.copytree(self._tpl_repo, self.repo)
        self.env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": self.home,
            "XDG_CONFIG_HOME": os.path.join(self.home, ".config"),
            "XDG_DATA_HOME": os.path.join(self.home, ".local", "share"),
            "GIT_AUTHOR_NAME": "Test",
            "GIT_AUTHOR_EMAIL": "test@example.com",
            "GIT_COMMITTER_NAME": "Test",
            "GIT_COMMITTER_EMAIL": "test@example.com",
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_CONFIG_SYSTEM": "/dev/null",
        }

    def test_inspect_non_git_and_main_repo(self):
        plain = os.path.join(self.tmp, "plain")
        os.makedirs(plain)
        self.assertFalse(wt.inspect_dir(plain, env=self.env)["is_git"])
        info = wt.inspect_dir(self.repo, env=self.env)
        self.assertTrue(info["is_git"])
        self.assertFalse(info["is_worktree"])
        self.assertEqual(info["repo_name"], "shop-api")
        self.assertEqual(info["branch"], "main")
        self.assertFalse(info["dirty"])

    def test_create_copies_root_env_and_manifest_skips_examples_and_large_files(self):
        with open(os.path.join(self.repo, ".env"), "w", encoding="utf-8") as f:
            f.write("SECRET=123\n")
        with open(os.path.join(self.repo, ".env.local"), "w", encoding="utf-8") as f:
            f.write("PORT=3000\n")
        with open(os.path.join(self.repo, ".env.example"), "w", encoding="utf-8") as f:
            f.write("SECRET=\n")
        with open(os.path.join(self.repo, ".env.huge"), "wb") as f:
            f.write(b"x" * (wt.MAX_ENV_BYTES + 10))
        os.makedirs(os.path.join(self.repo, "cfg"), exist_ok=True)
        with open(os.path.join(self.repo, "cfg", "local.json"), "w", encoding="utf-8") as f:
            f.write('{"dev": true}\n')
        with open(os.path.join(self.repo, ".swarmbox-worktree"), "w", encoding="utf-8") as f:
            f.write("# extra local files\ncfg/local.json\n../escape.txt\n")

        res = wt.create_worktree(self.repo, env=self.env)
        self.assertTrue(res["ok"])
        self.assertTrue(res["branch"].startswith("sb/wt-"))
        self.assertEqual(res["base"], "main")
        self.assertTrue(res["uncommitted_in_source"])
        self.assertIn(".env", res["copied_files"])
        self.assertIn(".env.local", res["copied_files"])
        self.assertIn("cfg/local.json", res["copied_files"])
        self.assertNotIn(".env.example", res["copied_files"])
        self.assertNotIn(".env.huge", res["copied_files"])

        env_dst = os.path.join(res["path"], ".env")
        self.assertEqual(stat.S_IMODE(os.stat(env_dst).st_mode), 0o600)
        # Stored under $XDG_DATA_HOME/swarmbox/worktrees/shop-api/
        self.assertIn(os.path.join(".local", "share", "swarmbox", "worktrees", "shop-api"), res["path"])

        info = wt.inspect_dir(res["path"], env=self.env)
        self.assertTrue(info["is_worktree"])
        self.assertTrue(info["managed"])
        self.assertEqual(info["repo_root"], os.path.realpath(self.repo))

    def test_clean_merge_and_remove_workflow(self):
        created = wt.create_worktree(self.repo, env=self.env)
        wt_path = created["path"]

        st0 = wt.status_worktree(wt_path, env=self.env)
        self.assertTrue(st0["empty"])
        self.assertEqual(st0["ahead"], 0)

        # Make a commit inside the worktree
        with open(os.path.join(wt_path, "feature.py"), "w", encoding="utf-8") as f:
            f.write("VALUE = 42\n")
        # Dirty worktree refuses merge and refuses non-force remove
        with self.assertRaises(wt.WorktreeError) as ctx:
            wt.merge_worktree(wt_path, env=self.env)
        self.assertEqual(ctx.exception.code, "dirty_worktree")
        with self.assertRaises(wt.WorktreeError) as ctx:
            wt.remove_worktree(wt_path, force=False, env=self.env)
        self.assertEqual(ctx.exception.code, "dirty_worktree")

        git(wt_path, "add", "feature.py")
        git(wt_path, "commit", "-m", "add feature")

        st1 = wt.status_worktree(wt_path, env=self.env)
        self.assertFalse(st1["dirty"])
        self.assertFalse(st1["empty"])
        self.assertEqual(st1["ahead"], 1)
        self.assertTrue(st1["can_merge"])
        self.assertEqual(st1["conflict_files"], [])

        # Unmerged commits refuse non-force remove
        with self.assertRaises(wt.WorktreeError) as ctx:
            wt.remove_worktree(wt_path, force=False, env=self.env)
        self.assertEqual(ctx.exception.code, "unmerged_commits")

        # Dirty main repo blocks local merge safely
        with open(os.path.join(self.repo, "scratch.txt"), "w", encoding="utf-8") as f:
            f.write("dirty main\n")
        with self.assertRaises(wt.WorktreeError) as ctx:
            wt.merge_worktree(wt_path, env=self.env)
        self.assertEqual(ctx.exception.code, "dirty_base")
        os.unlink(os.path.join(self.repo, "scratch.txt"))

        # Seed a pin for this worktree and an unrelated pin to verify merge --clean purges only the removed worktree's pin
        pins_file = os.path.join(wt.config_dir(self.env), "pins.json")
        os.makedirs(os.path.dirname(pins_file), exist_ok=True)
        with open(pins_file, "w", encoding="utf-8") as f:
            json.dump({"schema": 1, "pins": [
                {"id": "p-wt", "cwd": wt_path, "auto": True, "worktree": {"path": wt_path, "branch": created["branch"]}},
                {"id": "p-main", "cwd": self.repo, "auto": False},
            ]}, f)

        # Clean merge with --clean removes worktree, branch, and its pin
        m = wt.merge_worktree(wt_path, clean=True, env=self.env)
        self.assertTrue(m["ok"])
        self.assertEqual(m["strategy"], "fast-forward")
        self.assertTrue(m["cleaned"])
        self.assertFalse(os.path.exists(wt_path))
        self.assertTrue(os.path.isfile(os.path.join(self.repo, "feature.py")))
        self.assertEqual(wt.list_worktrees(env=self.env), [])
        with open(pins_file, encoding="utf-8") as f:
            remaining_pins = json.load(f)["pins"]
        self.assertEqual([p["id"] for p in remaining_pins], ["p-main"])

    def test_in_memory_conflict_detection_leaves_main_repo_clean(self):
        created = wt.create_worktree(self.repo, env=self.env)
        wt_path = created["path"]

        # Modify same line on main and in worktree
        with open(os.path.join(self.repo, "app.py"), "w", encoding="utf-8") as f:
            f.write("def greet():\n    return 'main-change'\n")
        git(self.repo, "add", "app.py")
        git(self.repo, "commit", "-m", "main edit")

        with open(os.path.join(wt_path, "app.py"), "w", encoding="utf-8") as f:
            f.write("def greet():\n    return 'wt-change'\n")
        git(wt_path, "add", "app.py")
        git(wt_path, "commit", "-m", "wt edit")

        st = wt.status_worktree(wt_path, env=self.env)
        self.assertFalse(st["can_merge"])
        self.assertIn("app.py", st["conflict_files"])
        # Main repo must remain completely clean (merge-tree runs in memory)
        self.assertFalse(st["main_dirty"])

        with self.assertRaises(wt.WorktreeError) as ctx:
            wt.merge_worktree(wt_path, env=self.env)
        self.assertEqual(ctx.exception.code, "merge_conflict")
        self.assertIn("app.py", ctx.exception.extra.get("conflict_files", []))

        # Force remove cleans up conflicted worktree
        rem = wt.remove_worktree(wt_path, force=True, env=self.env)
        self.assertTrue(rem["ok"])
        self.assertTrue(rem["branch_deleted"])

    def test_detects_external_worktree_passively_and_prefs_roundtrip(self):
        ext_path = os.path.join(self.tmp, "manual-wt")
        git(self.repo, "worktree", "add", "-b", "ext-branch", ext_path, "HEAD")
        info = wt.inspect_dir(ext_path, env=self.env)
        self.assertTrue(info["is_worktree"])
        self.assertFalse(info["managed"])
        self.assertEqual(info["branch"], "ext-branch")

        self.assertEqual(wt.read_prefs(env=self.env), {"mode": "ask", "copy_env": True})
        updated = wt.write_prefs(mode="auto", copy_env=False, env=self.env)
        self.assertEqual(updated, {"mode": "auto", "copy_env": False})
        self.assertEqual(wt.read_prefs(env=self.env), {"mode": "auto", "copy_env": False})

        # CLI smoke check
        p = subprocess.run([sys.executable, WT_SCRIPT, "prefs", "get"], env=self.env, capture_output=True, text=True, check=True)
        self.assertEqual(json.loads(p.stdout), {"mode": "auto", "copy_env": False})

    def test_shell_guard_ask_auto_off_cancel_and_labels(self):
        # Fake swarmbox-tabs returning one active agent (t1) in self.repo and logging label calls
        label_log = os.path.join(self.tmp, "labels.log")
        fake_tabs = os.path.join(self.tmp, "fake-tabs")
        with open(fake_tabs, "w", encoding="utf-8") as f:
            f.write(
                "#!/bin/sh\n"
                "if [ \"$1\" = list ]; then\n"
                "  printf '%s\\n' '[{\"tab\":\"t1\",\"name\":\"fix-auth\",\"title\":\"Fix Auth\",\"dir\":\"~/shop-api\",\"cmd\":\"antigravity\"}]'\n"
                "elif [ \"$1\" = label ]; then\n"
                "  shift\n"
                f"  printf '%s\\n' \"$*\" >> {label_log!r}\n"
                "  printf '%s\\n' '{\"ok\":true}'\n"
                "fi\n"
            )
        os.chmod(fake_tabs, 0o755)
        genv = {
            **self.env,
            "SWARMBOX_TEST_TABS_BIN": fake_tabs,
            "SWARMBOX_TEST_GUARD_STDIN": "1",
            "HC_TERMINAL_ID": "t2",
        }

        # Excluding the only colliding tab -> no collision
        r_self = subprocess.run(
            [sys.executable, WT_SCRIPT, "guard", "--shell", "--agent", "agy", "--exclude", "t1", self.repo],
            env=genv, capture_output=True, text=True, check=True,
        )
        self.assertEqual(r_self.stdout.strip(), "")

        # Mode off -> no prompt, no worktree
        wt.write_prefs(mode="off", env=genv)
        r_off = subprocess.run(
            [sys.executable, WT_SCRIPT, "guard", "--shell", "--agent", "agy", self.repo],
            env=genv, capture_output=True, text=True, check=True,
        )
        self.assertEqual(r_off.stdout.strip(), "")

        # Mode ask + 'c' -> exit 130 (cancel)
        wt.write_prefs(mode="ask", env=genv)
        r_cancel = subprocess.run(
            [sys.executable, WT_SCRIPT, "guard", "--shell", "--agent", "agy", self.repo],
            input="c\n", env=genv, capture_output=True, text=True,
        )
        self.assertEqual(r_cancel.returncode, 130)
        self.assertIn("Collision in shop-api", r_cancel.stderr)

        # Mode ask + 's' -> same folder (exit 0, empty stdout)
        r_same = subprocess.run(
            [sys.executable, WT_SCRIPT, "guard", "--shell", "--agent", "agy", self.repo],
            input="s\n", env=genv, capture_output=True, text=True, check=True,
        )
        self.assertEqual(r_same.stdout.strip(), "")

        # Mode ask + Enter (default W) -> creates isolated worktree AND labels current tab t2
        r_wt = subprocess.run(
            [sys.executable, WT_SCRIPT, "guard", "--shell", "--agent", "agy", self.repo],
            input="\n", env=genv, capture_output=True, text=True, check=True,
        )
        wt_path = r_wt.stdout.strip()
        self.assertTrue(os.path.isdir(wt_path), wt_path)
        self.assertNotEqual(os.path.realpath(wt_path), os.path.realpath(self.repo))
        with open(label_log, encoding="utf-8") as f:
            lbl_lines = f.read().splitlines()
        self.assertTrue(any(ln.startswith("t2 ") and "swarmbox.worktree=" in ln and "swarmbox.agent=agy" in ln for ln in lbl_lines), lbl_lines)

        # Mode auto -> creates worktree without prompting
        wt.write_prefs(mode="auto", env=genv)
        r_auto = subprocess.run(
            [sys.executable, WT_SCRIPT, "guard", "--shell", "--agent", "claude", self.repo],
            env=genv, capture_output=True, text=True, check=True,
        )
        wt_path2 = r_auto.stdout.strip()
        self.assertTrue(os.path.isdir(wt_path2), wt_path2)
        self.assertNotEqual(wt_path2, wt_path)

    def test_bashrc_interactive_tty_guard_isolates_manual_agy_and_skips_print_mode(self):
        import pty
        import select
        import time

        fake_bin = os.path.join(self.tmp, "bin")
        os.makedirs(fake_bin, exist_ok=True)
        run_log = os.path.join(self.tmp, "agy-runs.log")
        with open(os.path.join(fake_bin, "agy"), "w", encoding="utf-8") as f:
            f.write(f"#!/bin/sh\necho \"cwd=$(pwd) args=$*\" >> {run_log}\n")
        os.chmod(os.path.join(fake_bin, "agy"), 0o755)

        fake_tabs = os.path.join(self.tmp, "fake-tabs-tty")
        with open(fake_tabs, "w", encoding="utf-8") as f:
            f.write(
                "#!/bin/sh\n"
                "if [ \"$1\" = list ]; then\n"
                "  printf '%s\\n' '[{\"tab\":\"t1\",\"name\":\"active-agy\",\"dir\":\"~/shop-api\",\"cmd\":\"antigravity\"}]'\n"
                "else\n"
                "  printf '%s\\n' '{\"ok\":true}'\n"
                "fi\n"
            )
        os.chmod(fake_tabs, 0o755)

        wt.write_prefs(mode="auto", env=self.env)
        env = {
            **self.env,
            "PATH": fake_bin + ":" + os.environ.get("PATH", "/usr/bin:/bin"),
            "SWARMBOX_DIRS_SH": os.path.join(ROOT, "container", "scripts", "dirs.sh"),
            "SWARMBOX_IMAGE_ADDONS_DIR": os.path.join(ROOT, "container", "addons"),
            "SWARMBOX_IMAGE_SHIMS_DIR": fake_bin,
            "SWARMBOX_STARSHIP_INIT": "/nonexistent",
            "SWARMBOX_VENV": "/nonexistent",
            "SWARMBOX_TEST_WORKTREE_BIN": WT_SCRIPT,
            "SWARMBOX_TEST_TABS_BIN": fake_tabs,
            "SWARMBOX_AGENTS_BIN": os.path.join(ROOT, "container", "scripts", "swarmbox-agents.py"),   # the agent functions of the registry
            "HC_TERMINAL_ID": "t2",
        }
        bashrc = os.path.join(ROOT, "container", "config", "bashrc.sh")

        # Run bash -i on a real PTY:
        # 1) `agy -p hi` skips the guard and stays in self.repo
        # 2) `agy` triggers auto-worktree guard and runs inside the newly created worktree!
        master, slave = pty.openpty()
        proc = subprocess.Popen(
            ["/bin/bash", "--norc", "-i"],
            cwd=self.repo,
            env=env,
            stdin=slave,
            stdout=slave,
            stderr=slave,
            close_fds=True,
        )
        os.close(slave)
        try:
            cmds = f"source {bashrc}\nagy -p hi\nSWARMBOX_WORKTREE_GUARD=0 agy\nagy\nexit\n".encode()
            os.write(master, cmds)
            deadline = time.time() + 10.0
            while time.time() < deadline:
                if proc.poll() is not None:
                    break
                r, _, _ = select.select([master], [], [], 0.1)
                if r:
                    try:
                        os.read(master, 4096)
                    except OSError:
                        break
            proc.wait(timeout=5.0)
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=2.0)
            os.close(master)

        with open(run_log, encoding="utf-8") as f:
            lines = f.read().splitlines()
        self.assertEqual(len(lines), 3, lines)
        self.assertTrue(lines[0].startswith(f"cwd={os.path.realpath(self.repo)} "), lines)
        self.assertTrue(lines[1].startswith(f"cwd={os.path.realpath(self.repo)} "), lines)
        self.assertIn("/worktrees/shop-api/sb-wt-", lines[2], lines)

    def test_detect_verify_cmd_precedence_and_override(self):
        d = os.path.join(self.tmp, "detect-repo")
        os.makedirs(d)
        self.assertEqual(wt.detect_verify_cmd(d), "")

        # f) go.mod
        with open(os.path.join(d, "go.mod"), "w", encoding="utf-8") as f:
            f.write("module example.com/app\n")
        self.assertEqual(wt.detect_verify_cmd(d), "go test ./...")

        # e) Cargo.toml takes precedence over go.mod
        with open(os.path.join(d, "Cargo.toml"), "w", encoding="utf-8") as f:
            f.write("[package]\nname = 'app'\n")
        self.assertEqual(wt.detect_verify_cmd(d), "cargo test")

        # d) Python tests (pytest on PATH vs missing)
        os.makedirs(os.path.join(d, "tests", "unit"), exist_ok=True)
        with open(os.path.join(d, "tests", "unit", "test_x.py"), "w", encoding="utf-8") as f:
            f.write("def test_ok(): pass\n")
        fake_bin = os.path.join(self.tmp, "pytest-bin")
        os.makedirs(fake_bin, exist_ok=True)
        with open(os.path.join(fake_bin, "pytest"), "w", encoding="utf-8") as f:
            f.write("#!/bin/sh\nexit 0\n")
        os.chmod(os.path.join(fake_bin, "pytest"), 0o755)
        self.assertEqual(wt.detect_verify_cmd(d, env={"PATH": fake_bin}), "pytest")
        self.assertEqual(wt.detect_verify_cmd(d, env={"PATH": "/nonexistent-dir"}), "python3 -m unittest")

        # c) package.json default placeholder is ignored; real script wins
        with open(os.path.join(d, "package.json"), "w", encoding="utf-8") as f:
            json.dump({"scripts": {"test": 'echo "Error: no test specified" && exit 1'}}, f)
        self.assertEqual(wt.detect_verify_cmd(d, env={"PATH": "/nonexistent-dir"}), "python3 -m unittest")
        with open(os.path.join(d, "package.json"), "w", encoding="utf-8") as f:
            json.dump({"scripts": {"test": "vitest run"}}, f)
        self.assertEqual(wt.detect_verify_cmd(d), "npm test")

        # b) Makefile check: and test:
        with open(os.path.join(d, "Makefile"), "w", encoding="utf-8") as f:
            f.write("test := ignored\ncheck:\n\techo ok\n")
        self.assertEqual(wt.detect_verify_cmd(d), "make check")
        with open(os.path.join(d, "Makefile"), "w", encoding="utf-8") as f:
            f.write("test:\n\techo ok\ncheck:\n\techo ok\n")
        self.assertEqual(wt.detect_verify_cmd(d), "make test")

        # a) dev/check.sh
        os.makedirs(os.path.join(d, "dev"), exist_ok=True)
        with open(os.path.join(d, "dev", "check.sh"), "w", encoding="utf-8") as f:
            f.write("#!/bin/sh\nexit 0\n")
        self.assertEqual(wt.detect_verify_cmd(d), "sh dev/check.sh")

        # .swarmbox-check overrides everything
        with open(os.path.join(d, ".swarmbox-check"), "w", encoding="utf-8") as f:
            f.write("\n# custom verification\n  ./scripts/run-ci.sh --fast  \nsecond-line\n")
        self.assertEqual(wt.detect_verify_cmd(d), "./scripts/run-ci.sh --fast")

    def test_status_commits_files_diff_and_upstream(self):
        # Set up bare origin remote and push main
        bare = os.path.join(self.tmp, "origin.git")
        git(self.tmp, "init", "--bare", bare)
        git(self.repo, "remote", "add", "origin", bare)
        git(self.repo, "push", "-u", "origin", "main")

        # Add a verify script in repo
        with open(os.path.join(self.repo, ".swarmbox-check"), "w", encoding="utf-8") as f:
            f.write("echo verified\n")
        git(self.repo, "add", ".swarmbox-check")
        git(self.repo, "commit", "-m", "add check")

        # Main is now 1 commit ahead of origin/main
        created = wt.create_worktree(self.repo, env=self.env)
        wt_path = created["path"]

        # Make two commits in worktree: add new file, modify app.py
        with open(os.path.join(wt_path, "new_mod.py"), "w", encoding="utf-8") as f:
            f.write("a = 1\nb = 2\n")
        git(wt_path, "add", "new_mod.py")
        git(wt_path, "commit", "-m", "add new_mod")

        with open(os.path.join(wt_path, "app.py"), "w", encoding="utf-8") as f:
            f.write("def greet():\n    return 'hi'\n    # extra\n")
        git(wt_path, "add", "app.py")
        git(wt_path, "commit", "-m", "update greet")

        st = wt.status_worktree(wt_path, env=self.env)
        self.assertEqual(st["ahead"], 2)
        self.assertEqual(len(st["commits"]), 2)
        self.assertEqual([c["subject"] for c in st["commits"]], ["update greet", "add new_mod"])
        self.assertTrue(all(c["sha"] and c["rel_time"] for c in st["commits"]))

        files_by_path = {f["path"]: f for f in st["files"]}
        self.assertIn("new_mod.py", files_by_path)
        self.assertEqual(files_by_path["new_mod.py"]["status"], "A")
        self.assertEqual(files_by_path["new_mod.py"]["added"], 2)
        self.assertEqual(files_by_path["new_mod.py"]["deleted"], 0)
        self.assertIn("app.py", files_by_path)
        self.assertEqual(files_by_path["app.py"]["status"], "M")
        self.assertEqual(st["diff_stat"]["files"], 2)
        self.assertGreaterEqual(st["diff_stat"]["insertions"], 4)
        self.assertEqual(st["main_upstream"], "origin/main")
        self.assertEqual(st["main_ahead_origin"], 1)
        self.assertEqual(st["main_behind_origin"], 0)
        self.assertEqual(st["verify_cmd"], "echo verified")

        # diff_worktree full, single file, and truncated
        df_all = wt.diff_worktree(wt_path, env=self.env)
        self.assertTrue(df_all["ok"])
        self.assertFalse(df_all["truncated"])
        self.assertIn("new_mod.py", df_all["diff"])
        self.assertIn("app.py", df_all["diff"])

        df_one = wt.diff_worktree(wt_path, file_path="app.py", env=self.env)
        self.assertEqual(df_one["file"], "app.py")
        self.assertIn("app.py", df_one["diff"])
        self.assertNotIn("new_mod.py", df_one["diff"])

        df_trunc = wt.diff_worktree(wt_path, max_bytes=32, env=self.env)
        self.assertTrue(df_trunc["truncated"])
        self.assertLessEqual(len(df_trunc["diff"].encode("utf-8")), 32)

        # CLI diff check
        p = subprocess.run(
            [sys.executable, WT_SCRIPT, "diff", wt_path, "--file", "new_mod.py"],
            env=self.env, capture_output=True, text=True, check=True,
        )
        cli_df = json.loads(p.stdout)
        self.assertTrue(cli_df["ok"])
        self.assertIn("new_mod.py", cli_df["diff"])

    def test_sync_worktree_merge_rebase_and_conflict_abort(self):
        created = wt.create_worktree(self.repo, env=self.env)
        wt_path = created["path"]

        # Advance main with non-conflicting file
        with open(os.path.join(self.repo, "main_only.txt"), "w", encoding="utf-8") as f:
            f.write("from main\n")
        git(self.repo, "add", "main_only.txt")
        git(self.repo, "commit", "-m", "main_only")

        # Worktree makes a dirty change -> sync refuses
        with open(os.path.join(wt_path, "wt_only.txt"), "w", encoding="utf-8") as f:
            f.write("from wt\n")
        with self.assertRaises(wt.WorktreeError) as ctx:
            wt.sync_worktree(wt_path, env=self.env)
        self.assertEqual(ctx.exception.code, "dirty_worktree")

        git(wt_path, "add", "wt_only.txt")
        git(wt_path, "commit", "-m", "wt_only")

        # Clean merge sync
        s1 = wt.sync_worktree(wt_path, rebase=False, env=self.env)
        self.assertTrue(s1["ok"])
        self.assertEqual(s1["mode"], "merge")
        self.assertEqual(s1["behind"], 0)
        self.assertTrue(os.path.isfile(os.path.join(wt_path, "main_only.txt")))

        # Advance main again and test rebase sync via CLI
        with open(os.path.join(self.repo, "main_two.txt"), "w", encoding="utf-8") as f:
            f.write("two\n")
        git(self.repo, "add", "main_two.txt")
        git(self.repo, "commit", "-m", "main_two")

        p = subprocess.run(
            [sys.executable, WT_SCRIPT, "sync", wt_path, "--rebase"],
            env=self.env, capture_output=True, text=True, check=True,
        )
        s2 = json.loads(p.stdout)
        self.assertTrue(s2["ok"])
        self.assertEqual(s2["mode"], "rebase")
        self.assertEqual(s2["behind"], 0)

        # Now create a conflict on app.py and test both merge and rebase abort cleanly
        with open(os.path.join(self.repo, "app.py"), "w", encoding="utf-8") as f:
            f.write("def greet():\n    return 'main-conflict'\n")
        git(self.repo, "add", "app.py")
        git(self.repo, "commit", "-m", "main conflict")

        with open(os.path.join(wt_path, "app.py"), "w", encoding="utf-8") as f:
            f.write("def greet():\n    return 'wt-conflict'\n")
        git(wt_path, "add", "app.py")
        git(wt_path, "commit", "-m", "wt conflict")

        for use_rebase in (False, True):
            with self.assertRaises(wt.WorktreeError) as ctx:
                wt.sync_worktree(wt_path, rebase=use_rebase, env=self.env)
            self.assertEqual(ctx.exception.code, "sync_conflict")
            self.assertIn("app.py", ctx.exception.extra.get("conflict_files", []))
            # Worktree MUST be left completely clean (no leftover merge/rebase state)
            self.assertEqual(git(wt_path, "status", "--porcelain"), "")

    def test_merge_undo_repo_status_and_push_to_bare_origin(self):
        bare = os.path.join(self.tmp, "remote.git")
        git(self.tmp, "init", "--bare", "-b", "main", bare)
        git(self.repo, "remote", "add", "origin", bare)

        # Push initial main without upstream yet (uses origin)
        p_init = wt.push_repo(self.repo, env=self.env)
        self.assertTrue(p_init["ok"])
        self.assertEqual(p_init["upstream"], "origin/main")

        rs0 = wt.repo_status(self.repo, env=self.env)
        self.assertTrue(rs0["ok"])
        self.assertEqual(rs0["upstream"], "origin/main")
        self.assertEqual(rs0["ahead_origin"], 0)
        self.assertEqual(rs0["behind_origin"], 0)
        self.assertFalse(rs0["can_undo_merge"])
        self.assertIsNone(rs0["last_merge"])

        # Create worktree, commit, and merge
        created = wt.create_worktree(self.repo, env=self.env)
        wt_path = created["path"]
        with open(os.path.join(wt_path, "feat.py"), "w", encoding="utf-8") as f:
            f.write("X = 1\n")
        git(wt_path, "add", "feat.py")
        git(wt_path, "commit", "-m", "add feat")

        pre_head = git(self.repo, "rev-parse", "HEAD")
        m = wt.merge_worktree(wt_path, clean=True, env=self.env)
        post_head = git(self.repo, "rev-parse", "HEAD")
        self.assertEqual(m["pre_sha"], pre_head)
        self.assertEqual(m["post_sha"], post_head)
        self.assertEqual(m["commits_list"], ["add feat"])
        self.assertEqual(m["files"], ["feat.py"])

        # Persistent last_merge metadata file has mode 0600 and does not pollute list_worktrees
        meta_fp = wt._repo_meta_path(wt.worktree_root(self.env), self.repo)
        self.assertTrue(os.path.isfile(meta_fp))
        self.assertEqual(stat.S_IMODE(os.stat(meta_fp).st_mode), 0o600)
        self.assertEqual(wt.list_worktrees(env=self.env), [])

        # repo-status CLI shows ahead_origin=1 and can_undo_merge=True
        p_rs = subprocess.run(
            [sys.executable, WT_SCRIPT, "repo-status", self.repo],
            env=self.env, capture_output=True, text=True, check=True,
        )
        rs1 = json.loads(p_rs.stdout)
        self.assertEqual(rs1["ahead_origin"], 1)
        self.assertTrue(rs1["can_undo_merge"])
        self.assertEqual(rs1["last_merge"]["post_sha"], post_head)

        # Undo refused when repo is dirty
        with open(os.path.join(self.repo, "dirty.txt"), "w", encoding="utf-8") as f:
            f.write("dirty\n")
        self.assertFalse(wt.repo_status(self.repo, env=self.env)["can_undo_merge"])
        with self.assertRaises(wt.WorktreeError) as ctx:
            wt.undo_merge(self.repo, env=self.env)
        self.assertEqual(ctx.exception.code, "dirty_base")
        os.unlink(os.path.join(self.repo, "dirty.txt"))

        # Undo succeeds via CLI and restores pre_sha
        p_undo = subprocess.run(
            [sys.executable, WT_SCRIPT, "undo-merge", self.repo],
            env=self.env, capture_output=True, text=True, check=True,
        )
        undone = json.loads(p_undo.stdout)
        self.assertTrue(undone["ok"])
        self.assertEqual(undone["restored_sha"], pre_head)
        self.assertEqual(git(self.repo, "rev-parse", "HEAD"), pre_head)
        self.assertFalse(os.path.exists(os.path.join(self.repo, "feat.py")))
        self.assertFalse(wt.repo_status(self.repo, env=self.env)["can_undo_merge"])

        # Second merge followed by a new manual commit -> undo must be refused
        c2 = wt.create_worktree(self.repo, env=self.env)
        with open(os.path.join(c2["path"], "f2.py"), "w", encoding="utf-8") as f:
            f.write("Y = 2\n")
        git(c2["path"], "add", "f2.py")
        git(c2["path"], "commit", "-m", "add f2")
        wt.merge_worktree(c2["path"], clean=True, env=self.env)

        with open(os.path.join(self.repo, "manual.txt"), "w", encoding="utf-8") as f:
            f.write("manual\n")
        git(self.repo, "add", "manual.txt")
        git(self.repo, "commit", "-m", "manual commit")

        self.assertFalse(wt.repo_status(self.repo, env=self.env)["can_undo_merge"])
        with self.assertRaises(wt.WorktreeError) as ctx:
            wt.undo_merge(self.repo, env=self.env)
        self.assertEqual(ctx.exception.code, "undo_unavailable")

        # Push succeeds via CLI and brings ahead_origin back to 0
        p_push = subprocess.run(
            [sys.executable, WT_SCRIPT, "push", self.repo],
            env=self.env, capture_output=True, text=True, check=True,
        )
        pushed = json.loads(p_push.stdout)
        self.assertTrue(pushed["ok"])
        self.assertEqual(wt.repo_status(self.repo, env=self.env)["ahead_origin"], 0)

        # Simulate another clone pushing to bare origin so repo is behind_origin=1
        other = os.path.join(self.tmp, "other-clone")
        git(self.tmp, "clone", "-b", "main", bare, other)
        git(other, "config", "user.name", "Other")
        git(other, "config", "user.email", "other@example.com")
        with open(os.path.join(other, "remote_only.txt"), "w", encoding="utf-8") as f:
            f.write("remote\n")
        git(other, "add", "remote_only.txt")
        git(other, "commit", "-m", "remote commit")
        git(other, "push", "origin", "main")
        git(self.repo, "fetch", "origin")
        self.assertEqual(wt.repo_status(self.repo, env=self.env)["behind_origin"], 1)

    def test_verify_repo_pass_fail_tail_and_missing_cmd(self):
        # No verify command detected -> WorktreeError("no_verify_cmd")
        with self.assertRaises(wt.WorktreeError) as ctx:
            wt.verify_repo(self.repo, env=self.env)
        self.assertEqual(ctx.exception.code, "no_verify_cmd")

        # Explicit passing command via CLI
        p_ok = subprocess.run(
            [sys.executable, WT_SCRIPT, "verify", self.repo, "--cmd", "echo ALL_GOOD"],
            env=self.env, capture_output=True, text=True, check=True,
        )
        r_ok = json.loads(p_ok.stdout)
        self.assertTrue(r_ok["ok"])
        self.assertEqual(r_ok["exit_code"], 0)
        self.assertIn("ALL_GOOD", r_ok["output"])
        self.assertIsInstance(r_ok["duration_ms"], int)

        # Failing command via CLI still exits 0 with ok=False so callers can read structured JSON
        p_fail = subprocess.run(
            [sys.executable, WT_SCRIPT, "verify", self.repo, "--cmd", "echo BOOM >&2; exit 3"],
            env=self.env, capture_output=True, text=True, check=True,
        )
        r_fail = json.loads(p_fail.stdout)
        self.assertFalse(r_fail["ok"])
        self.assertEqual(r_fail["exit_code"], 3)
        self.assertIn("BOOM", r_fail["output"])

        # Output tail is capped at 16 KiB
        r_big = wt.verify_repo(self.repo, cmd="head -c 30000 /dev/zero | tr '\\0' A; echo TAIL_END", env=self.env)
        self.assertTrue(r_big["ok"])
        self.assertLessEqual(len(r_big["output"].encode("utf-8")), 16 * 1024)
        self.assertIn("TAIL_END", r_big["output"])


class TabAgentKind(unittest.TestCase):
    """Which agent a `swarmbox-tabs list` row runs, for the collision check."""

    def test_the_agent_label_counts_while_the_foreground_is_not_a_shell(self):
        # An agent the process name does not tell (OpenCode through node) is still found by its label.
        self.assertEqual(wt._tab_agent_kind({"tab": "t1", "cmd": "node", "agent": "opencode"}), "opencode")
        self.assertEqual(wt._tab_agent_kind({"tab": "t1", "cmd": "2.1.332", "agent": "antigravity"}), "agy")

    def test_a_label_on_a_plain_shell_is_not_an_agent(self):
        self.assertEqual(wt._tab_agent_kind({"tab": "t1", "cmd": "bash", "agent": "claude"}), "")
        self.assertEqual(wt._tab_agent_kind({"tab": "t1", "cmd": "-bash", "agent": "claude"}), "")

    def test_status_and_command_still_win(self):
        self.assertEqual(wt._tab_agent_kind({"tab": "t1", "cmd": "node", "status": {"app": "claude-code"}}), "claude")
        self.assertEqual(wt._tab_agent_kind({"tab": "t1", "cmd": "agy"}), "agy")
        self.assertEqual(wt._tab_agent_kind({"tab": "t1", "cmd": "node", "name": "claude-2"}), "")


if __name__ == "__main__":
    unittest.main()
