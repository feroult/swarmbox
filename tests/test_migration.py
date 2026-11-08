"""Slice 2.6: the layout migration of design 12.4 (container/scripts/swarmbox-migrate.sh, serve step 4).

The fixture is built in a mktemp directory from the v0.1.0 code (git show v0.1.0:container/scripts/init.sh, podman-service.sh,
container/web/web-terminal.sh, Dockerfile line 213): settings.json plus the link <home>/.claude/settings.json, web-terminal.conf,
web-terminal.lock and .log, podman-service.lock and .log, podman.sock, ttyd-index.html, opencode-local.json and a memory/ folder.
It is NOT a copy of a real v0.1.0 workspace (B29 stays to be run once on a copy of one, in Phase 6). Nothing here touches a
real home path: HOME, XDG_* and the fixture are all under mktemp, and the sockets are plain files.

Run with: python3 tests/test_migration.py
"""
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import ROOT  # noqa: E402
import test_serve_steps as S  # noqa: E402

MIGRATE = os.path.join(ROOT, "container", "scripts", "swarmbox-migrate.sh")
DIRS_SH = os.path.join(ROOT, "container", "scripts", "dirs.sh")


def put(path, text=""):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(text)


def get(path):
    with open(path) as f:
        return f.read()


class Fixture(unittest.TestCase):
    SETTINGS = '{"permissions": {"allow": ["Bash(ls)"]}, "theme": "dark"}\n'

    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="migrate-test-")
        self.addCleanup(self._cleanup)
        self.libdir = tempfile.mkdtemp(prefix="migrate-lib-")
        self.addCleanup(shutil.rmtree, self.libdir, ignore_errors=True)
        os.symlink(DIRS_SH, os.path.join(self.libdir, "dirs.sh"))
        self.old = os.path.join(self.home, ".swarmbox")
        self.claude = os.path.join(self.home, ".claude", "settings.json")
        self.conf_dest = os.path.join(self.home, ".config", "swarmbox", "web-terminal.conf")
        self.state = os.path.join(self.home, ".local", "state", "swarmbox")

    def _cleanup(self):
        for root, dirs, _ in os.walk(self.home):  # a test may leave a folder read-only
            for d in dirs:
                try:
                    os.chmod(os.path.join(root, d), 0o755)
                except OSError:
                    pass
        os.chmod(self.home, 0o755)
        shutil.rmtree(self.home, ignore_errors=True)

    def build_v010(self, memory=True):
        """The .swarmbox/ of a v0.1.0 workspace, and the link init.sh made."""
        put(os.path.join(self.old, "settings.json"), self.SETTINGS)
        os.makedirs(os.path.dirname(self.claude), exist_ok=True)
        os.symlink(os.path.join(self.old, "settings.json"), self.claude)
        put(os.path.join(self.old, "web-terminal.conf"), "padding=14\nctrlVPaste=false\n")
        put(os.path.join(self.old, "web-terminal.lock"))
        put(os.path.join(self.old, "web-terminal.log"), "ttyd log\n")
        put(os.path.join(self.old, "podman-service.lock"))
        put(os.path.join(self.old, "podman-service.log"), "service log\n")
        put(os.path.join(self.old, "podman.sock"))  # a plain file: no real socket
        put(os.path.join(self.old, "ttyd-index.html"), "<html></html>")
        put(os.path.join(self.old, "opencode-local.json"), "{}")
        if memory:
            put(os.path.join(self.old, "memory", "notes.db"), "data")

    def migrate(self, **extra):
        env = {"PATH": "/usr/bin:/bin", "HOME": self.home, "SWARMBOX_TEST_LIB": self.libdir, "LANG": "C.UTF-8"}
        env.update(extra)
        return subprocess.run(["bash", MIGRATE], env=env, capture_output=True, text=True, timeout=30)

    def tree(self):
        out = []
        for root, dirs, files in os.walk(self.home):
            for n in dirs + files:
                p = os.path.join(root, n)
                rel = os.path.relpath(p, self.home)
                out.append((rel, os.readlink(p) if os.path.islink(p) else (get(p) if os.path.isfile(p) else "<dir>")))
        return sorted(out)


class Table(Fixture):
    def test_settings_link_is_replaced_by_a_real_file_with_the_same_content(self):
        self.build_v010()
        r = self.migrate()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(os.path.islink(self.claude))
        self.assertTrue(os.path.isfile(self.claude))
        self.assertEqual(get(self.claude), self.SETTINGS)
        self.assertFalse(os.path.exists(os.path.join(self.old, "settings.json")))

    def test_web_terminal_conf_is_moved(self):
        self.build_v010()
        self.assertEqual(self.migrate().returncode, 0)
        self.assertEqual(get(self.conf_dest), "padding=14\nctrlVPaste=false\n")
        self.assertFalse(os.path.exists(os.path.join(self.old, "web-terminal.conf")))

    def test_regenerated_files_logs_locks_and_the_socket_file_are_deleted(self):
        self.build_v010()
        self.assertEqual(self.migrate().returncode, 0)
        for n in ("ttyd-index.html", "opencode-local.json", "podman.sock", "web-terminal.log", "podman-service.log",
                  "web-terminal.lock", "podman-service.lock"):
            self.assertFalse(os.path.lexists(os.path.join(self.old, n)), n)
        # nothing is created in the destinations of the deleted files
        self.assertFalse(os.path.exists(os.path.join(self.state, "podman.sock")))
        self.assertFalse(os.path.exists(os.path.join(self.state, "web-terminal.log")))

    def test_memory_is_left_with_its_content_and_mentioned_once(self):
        self.build_v010()
        r = self.migrate()
        self.assertEqual(get(os.path.join(self.old, "memory", "notes.db")), "data")
        mentions = [l for l in (r.stdout + r.stderr).splitlines() if "memory" in l]
        self.assertEqual(len(mentions), 1, mentions)
        self.assertEqual(sorted(os.listdir(self.old)), ["memory"])  # the folder stays because memory/ exists

    def test_old_folder_is_removed_when_empty_afterwards(self):
        self.build_v010(memory=False)
        self.assertEqual(self.migrate().returncode, 0)
        self.assertFalse(os.path.exists(self.old))

    def test_a_file_the_table_does_not_know_stays_and_keeps_the_folder(self):
        self.build_v010(memory=False)
        put(os.path.join(self.old, "mine.txt"), "user file")
        r = self.migrate()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(get(os.path.join(self.old, "mine.txt")), "user file")
        self.assertIn("mine.txt", r.stdout + r.stderr)

    def test_only_the_files_that_exist_are_acted_on(self):
        put(os.path.join(self.old, "ttyd-index.html"), "x")
        r = self.migrate()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(os.path.exists(self.old))
        self.assertFalse(os.path.exists(os.path.join(self.home, ".claude")))  # nothing to copy: no folder made
        self.assertFalse(os.path.exists(os.path.join(self.home, ".config")))


class NeverOverwrites(Fixture):
    def test_existing_web_terminal_conf_is_not_overwritten_and_the_old_one_stays(self):
        self.build_v010(memory=False)
        put(self.conf_dest, "padding=3\n")
        r = self.migrate()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(get(self.conf_dest), "padding=3\n")
        self.assertEqual(get(os.path.join(self.old, "web-terminal.conf")), "padding=14\nctrlVPaste=false\n")
        self.assertIn("web-terminal.conf", r.stdout + r.stderr)

    def test_existing_different_real_settings_file_is_not_overwritten(self):
        self.build_v010(memory=False)
        os.unlink(self.claude)
        put(self.claude, '{"theme": "light"}\n')
        r = self.migrate()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(get(self.claude), '{"theme": "light"}\n')
        self.assertEqual(get(os.path.join(self.old, "settings.json")), self.SETTINGS)
        self.assertIn("settings.json", r.stdout + r.stderr)

    def test_existing_identical_real_settings_file_lets_the_old_copy_go(self):
        self.build_v010(memory=False)
        os.unlink(self.claude)
        put(self.claude, self.SETTINGS)
        self.assertEqual(self.migrate().returncode, 0)
        self.assertEqual(get(self.claude), self.SETTINGS)
        self.assertFalse(os.path.exists(self.old))

    def test_a_link_that_points_somewhere_else_is_the_users_choice_and_stays(self):
        self.build_v010(memory=False)
        target = os.path.join(self.home, "elsewhere.json")
        put(target, '{"x": 1}\n')
        os.unlink(self.claude)
        os.symlink(target, self.claude)
        r = self.migrate()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(os.readlink(self.claude), target)
        self.assertEqual(get(target), '{"x": 1}\n')
        self.assertEqual(get(os.path.join(self.old, "settings.json")), self.SETTINGS)


class OldLayoutOddities(Fixture):
    def test_dangling_link_into_the_old_folder_is_removed(self):
        # .swarmbox/settings.json is gone but the link init.sh made is still there
        os.makedirs(self.old)
        os.makedirs(os.path.dirname(self.claude))
        os.symlink(os.path.join(self.old, "settings.json"), self.claude)
        r = self.migrate()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(os.path.lexists(self.claude))
        self.assertFalse(os.path.exists(self.old))

    def test_dangling_link_elsewhere_is_left_alone(self):
        os.makedirs(os.path.dirname(self.claude))
        os.symlink("/nonexistent/place.json", self.claude)
        put(os.path.join(self.old, "ttyd-index.html"), "x")
        self.assertEqual(self.migrate().returncode, 0)
        self.assertEqual(os.readlink(self.claude), "/nonexistent/place.json")

    def test_dangling_symlink_named_like_a_deletable_file_is_deleted_without_following_it(self):
        os.makedirs(self.old)
        os.symlink("/nonexistent/x", os.path.join(self.old, "opencode-local.json"))
        os.symlink("/nonexistent/y", os.path.join(self.old, "web-terminal.log"))
        r = self.migrate()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(os.path.exists(self.old))

    def test_podman_sock_that_is_a_real_unix_socket_is_deleted_too(self):
        import socket
        os.makedirs(self.old)
        s = socket.socket(socket.AF_UNIX)
        self.addCleanup(s.close)
        os.chdir(self.old)  # short relative path: the socket path limit
        s.bind("podman.sock")
        os.chdir(ROOT)
        self.assertTrue(stat.S_ISSOCK(os.lstat(os.path.join(self.old, "podman.sock")).st_mode))
        self.assertEqual(self.migrate().returncode, 0)
        self.assertFalse(os.path.exists(self.old))

    def test_old_folder_that_is_a_symlink_is_not_followed(self):
        real = os.path.join(self.home, "realdir")
        put(os.path.join(real, "ttyd-index.html"), "x")
        os.symlink(real, self.old)
        r = self.migrate()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(os.path.exists(os.path.join(real, "ttyd-index.html")))
        self.assertTrue(os.path.islink(self.old))


class Idempotence(Fixture):
    def test_second_run_is_a_no_op(self):
        self.build_v010()
        self.assertEqual(self.migrate().returncode, 0)
        before = self.tree()
        r = self.migrate()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.tree(), before)

    def test_second_run_after_a_kept_conflict_changes_nothing(self):
        self.build_v010()
        put(self.conf_dest, "padding=3\n")
        self.assertEqual(self.migrate().returncode, 0)
        before = self.tree()
        self.assertEqual(self.migrate().returncode, 0)
        self.assertEqual(self.tree(), before)

    def test_workspace_without_the_old_folder_is_untouched(self):
        put(os.path.join(self.home, "project", "a.txt"), "a")
        put(os.path.join(self.home, ".claude", "settings.json"), '{"mine": true}\n')
        os.symlink("/nonexistent", os.path.join(self.home, "dangling"))
        before = self.tree()
        r = self.migrate()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.tree(), before)
        self.assertEqual((r.stdout + r.stderr).strip(), "")  # a quiet start: nothing to say

    def test_a_workspace_with_a_space_in_its_path(self):
        self.build_v010(memory=False)
        spaced = tempfile.mkdtemp(prefix="migrate test ")
        self.addCleanup(shutil.rmtree, spaced, ignore_errors=True)
        shutil.rmtree(spaced)
        shutil.copytree(self.home, spaced, symlinks=True)
        # the link in the copy still points into the first workspace: rebuild it for the new path
        link = os.path.join(spaced, ".claude", "settings.json")
        os.unlink(link)
        os.symlink(os.path.join(spaced, ".swarmbox", "settings.json"), link)
        env = {"PATH": "/usr/bin:/bin", "HOME": spaced, "SWARMBOX_TEST_LIB": self.libdir}
        r = subprocess.run(["bash", MIGRATE], env=env, capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(get(link), self.SETTINGS)
        self.assertFalse(os.path.exists(os.path.join(spaced, ".swarmbox")))


class SoftFailure(Fixture):
    def test_a_folder_that_cannot_be_written_gives_exit_1_a_message_and_no_data_loss(self):
        if os.geteuid() == 0:
            self.skipTest("root ignores directory permissions")
        self.build_v010()
        os.chmod(self.old, 0o555)  # nothing inside can be deleted or moved away
        r = self.migrate()
        self.assertEqual(r.returncode, 1)
        self.assertIn("swarmbox-migrate", r.stderr)
        # the copy of settings.json happened first or not at all, but never lost the content
        self.assertEqual(get(os.path.join(self.old, "settings.json")), self.SETTINGS)
        os.chmod(self.old, 0o755)
        # once the cause is fixed, the next start finishes the job
        r = self.migrate()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(get(self.claude), self.SETTINGS)
        self.assertFalse(os.path.islink(self.claude))

    def test_one_failure_does_not_stop_the_other_rows(self):
        if os.geteuid() == 0:
            self.skipTest("root ignores directory permissions")
        self.build_v010(memory=False)
        os.makedirs(os.path.join(self.home, ".config"))
        os.chmod(os.path.join(self.home, ".config"), 0o555)  # web-terminal.conf cannot be moved there
        r = self.migrate()
        self.assertEqual(r.returncode, 1)
        self.assertEqual(get(os.path.join(self.old, "web-terminal.conf")), "padding=14\nctrlVPaste=false\n")
        self.assertFalse(os.path.lexists(os.path.join(self.old, "ttyd-index.html")))
        self.assertEqual(get(self.claude), self.SETTINGS)


class ServeStep4(S.ServeCase):
    """serve runs the real script as step 4; a failure is one health line and serve goes on (a 2.2 style test)."""

    def setUp(self):
        super().setUp()
        os.unlink(os.path.join(self.fake, "swarmbox-migrate"))
        os.symlink(MIGRATE, os.path.join(self.fake, "swarmbox-migrate"))

    def old_layout(self):
        put(os.path.join(self.home, ".swarmbox", "settings.json"), "{}\n")
        put(os.path.join(self.home, ".swarmbox", "ttyd-index.html"), "x")
        put(os.path.join(self.home, ".swarmbox", "web-terminal.conf"), "padding=1\n")

    def test_serve_migrates_and_is_ready_with_no_warning(self):
        self.old_layout()
        p = self.run_ready()
        self.assertEqual(self.marker(), "ok")
        self.assertFalse(os.path.exists(os.path.join(self.home, ".swarmbox")))
        self.assertEqual(get(os.path.join(self.home, ".claude", "settings.json")), "{}\n")
        self.assertTrue(os.path.isfile(os.path.join(self.home, ".config", "swarmbox", "web-terminal.conf")))
        self.stop(p)

    def test_serve_on_a_new_workspace_logs_nothing_alarming(self):
        p = self.run_ready()
        self.assertEqual(self.marker(), "ok")
        self.assertEqual(self.health_lines(), [])
        self.stop(p)

    def test_failing_migration_is_one_health_line_and_serve_continues(self):
        if os.geteuid() == 0:
            self.skipTest("root ignores directory permissions")
        self.old_layout()
        old = os.path.join(self.home, ".swarmbox")
        os.chmod(old, 0o555)
        self.addCleanup(os.chmod, old, 0o755)
        p = self.run_ready()
        self.assertEqual(self.marker(), "warnings=1")
        lines = self.health_lines()
        self.assertEqual(len(lines), 1, lines)
        self.assertIn("migrat", lines[0].lower())
        self.assertTrue(any(c.startswith("ttyd ") for c in self.calls()))
        self.assertIn("swarmbox-migrate", self.serve_log())
        self.stop(p)


class StaticChecks(unittest.TestCase):
    def test_dockerfile_installs_the_script(self):
        text = get(os.path.join(ROOT, "Dockerfile"))
        self.assertIn("container/scripts/swarmbox-migrate.sh /usr/local/bin/swarmbox-migrate", text)
        chmod = [l for l in text.splitlines() if "chmod 755" in l or "swarmbox-entrypoint &&" in l]
        self.assertTrue(any("/usr/local/bin/swarmbox-migrate" in l for l in chmod), chmod)

    def test_script_never_uses_recursive_removal(self):
        text = get(MIGRATE)
        self.assertNotIn("rm -rf", text)
        self.assertNotIn("rm -fr", text)
        self.assertNotIn("rm -r", text)


if __name__ == "__main__":
    unittest.main()
