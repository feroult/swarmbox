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
        },
    )
    return r.stdout.strip()


class WorktreeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="swarmbox-test-wt.")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.home = os.path.join(self.tmp, "home")
        self.repo = os.path.join(self.home, "shop-api")
        os.makedirs(self.repo, exist_ok=True)
        self.env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": self.home,
            "XDG_CONFIG_HOME": os.path.join(self.home, ".config"),
            "XDG_DATA_HOME": os.path.join(self.home, ".local", "share"),
            "GIT_AUTHOR_NAME": "Test",
            "GIT_AUTHOR_EMAIL": "test@example.com",
            "GIT_COMMITTER_NAME": "Test",
            "GIT_COMMITTER_EMAIL": "test@example.com",
        }
        git(self.repo, "init", "-b", "main")
        git(self.repo, "config", "user.name", "Test")
        git(self.repo, "config", "user.email", "test@example.com")
        with open(os.path.join(self.repo, "app.py"), "w", encoding="utf-8") as f:
            f.write("def greet():\n    return 'hello'\n")
        git(self.repo, "add", "app.py")
        git(self.repo, "commit", "-m", "initial")

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

        # Clean merge with --clean removes worktree and branch
        m = wt.merge_worktree(wt_path, clean=True, env=self.env)
        self.assertTrue(m["ok"])
        self.assertEqual(m["strategy"], "fast-forward")
        self.assertTrue(m["cleaned"])
        self.assertFalse(os.path.exists(wt_path))
        self.assertTrue(os.path.isfile(os.path.join(self.repo, "feature.py")))
        self.assertEqual(wt.list_worktrees(env=self.env), [])

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
                "#!/usr/bin/env python3\n"
                "import json, os, sys\n"
                "if sys.argv[1] == 'list':\n"
                f"    print(json.dumps([{{'tab': 't1', 'name': 'fix-auth', 'title': 'Fix Auth', 'dir': '~/shop-api', 'cmd': 'antigravity'}}]))\n"
                "elif sys.argv[1] == 'label':\n"
                f"    with open({label_log!r}, 'a', encoding='utf-8') as lf:\n"
                "        lf.write(' '.join(sys.argv[2:]) + '\\n')\n"
                "    print(json.dumps({'ok': True}))\n"
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
                "#!/usr/bin/env python3\n"
                "import json, sys\n"
                "if sys.argv[1] == 'list':\n"
                f"    print(json.dumps([{{'tab': 't1', 'name': 'active-agy', 'dir': '~/shop-api', 'cmd': 'antigravity'}}]))\n"
                "else:\n"
                "    print(json.dumps({'ok': True}))\n"
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


if __name__ == "__main__":
    unittest.main()
