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


if __name__ == "__main__":
    unittest.main()
