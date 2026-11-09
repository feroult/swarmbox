"""Slice 6.4: the whole migration sequence of design 12.4 on a realistic copy of a v0.1.0 workspace, with fakes (B29, D10, 3.4, 3.8, D8).

What runs, in the order of 12.4, all against mktemp folders and never against a real workspace:
  1. a larger fixture workspace is generated (a v0.1.0 `.work/` with projects, Claude and SSH state, the `.swarmbox/` of every file
     the v0.1.0 scripts wrote, extra odd files, `memory/`); its hash is taken and the migration works on a COPY, so the test can
     prove that the source stays byte-identical;
  2. the v0.1.0 container still exists (fake podman): the first `up` of 2.0 refuses with exit 5 and changes nothing (3.8);
  3. `podman rm -f swarmbox` (the fake records it), then the generated bash function with `init --workspace <copy>`, then
     `swarmbox env add` for the former --env-keys, `swarmbox config set` for PORTS and BROWSER_URL (12.4 steps 2 to 4);
  4. the first `swarmbox up` creates the box (fake podman) and re-registers the host connection that pointed at the old
     `<workspace>/.swarmbox/podman.sock` (3.4); it never touches the box volume `<name>-containers`;
  5. the real container/scripts/swarmbox-migrate.sh (what `serve` step 4 runs) runs on the copy; every row of the 12.4 table is
     asserted, a second run changes nothing, and `.swarmbox/` stays because `memory/` exists.
Every result here is tagged [reduced: fixture]: the fixture is derived from what the v0.1.0 scripts write (see FIXTURE_NOTES), not
copied from a real v0.1.0 workspace, no real Podman or box is involved, and the run on the owner's real workspace is an owner action
(docs/migration.md). Run: python3 tests/test_migration_e2e.py
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import ROOT, FakePodman, DEFAULT_VOLUME, DEFAULT_NAME, OLD_NAME  # noqa: E402

MIGRATE = os.path.join(ROOT, "container", "scripts", "swarmbox-migrate.sh")
DIRS_SH = os.path.join(ROOT, "container", "scripts", "dirs.sh")
INIT = os.path.join(ROOT, "container", "scripts", "swarmbox-init.sh")
HOST_DIR = os.path.join(ROOT, "container", "host")
with open(os.path.join(HOST_DIR, "VERSION")) as _f:
    VERSION = _f.read().strip()
NAME = DEFAULT_NAME
SETTINGS = '{"permissions": {"allow": ["Bash(ls)"]}, "theme": "dark"}\n'
FIXTURE_NOTES = ("derived from init.sh, podman-service.sh, web-terminal.sh and the Dockerfile of v0.1.0; a file those scripts did "
                 "not write is not covered; sizes and the exact log text are invented")
REAL_HOME = os.path.expanduser("~")
REAL_WATCH = [os.path.join(REAL_HOME, p) for p in (".config/swarmbox", ".local/share/swarmbox", ".local/state/swarmbox",
                                                    ".swarmbox")]  # not .claude or .ssh: the live box writes there


def put(path, text="", mode=None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(text)
    if mode:
        os.chmod(path, mode)


def get(path):
    with open(path) as f:
        return f.read()


def digest(root):
    """Hash of a tree: (relative path, kind, link target or sha256 of content, mode) of every entry, without following links."""
    out = []
    if not os.path.lexists(root):
        return None
    for dp, dns, fns in os.walk(root):
        for n in sorted(dns + fns):
            p = os.path.join(dp, n)
            rel = os.path.relpath(p, root)
            st = os.lstat(p)
            if os.path.islink(p):
                out.append((rel, "link", os.readlink(p), 0))
            elif os.path.isdir(p):
                out.append((rel, "dir", "", st.st_mode & 0o777))
            elif os.path.isfile(p):
                with open(p, "rb") as f:
                    out.append((rel, "file", hashlib.sha256(f.read()).hexdigest(), st.st_mode & 0o777))
            else:
                out.append((rel, "other", "", st.st_mode & 0o777))
    return sorted(out)


def build_fixture(ws):
    """A v0.1.0 workspace (the folder that holds .swarmbox/ at the owner's: the folder that is the box's home)."""
    old = os.path.join(ws, ".swarmbox")
    put(os.path.join(old, "settings.json"), SETTINGS)
    os.makedirs(os.path.join(ws, ".claude"))
    os.symlink(os.path.join(old, "settings.json"), os.path.join(ws, ".claude", "settings.json"))
    put(os.path.join(old, "web-terminal.conf"), "# web terminal\npadding=14\nctrlVPaste=false\ncopyOnSelect=true\n")
    put(os.path.join(old, "web-terminal.lock"))
    put(os.path.join(old, "web-terminal.log"), "ttyd log line\n" * 400)
    put(os.path.join(old, "podman-service.lock"))
    put(os.path.join(old, "podman-service.log"), "service log\n" * 200)
    put(os.path.join(old, "podman.sock"))  # a plain file stands for the socket
    put(os.path.join(old, "ttyd-index.html"), "<html>" + "x" * 5000 + "</html>")
    put(os.path.join(old, "opencode-local.json"), '{"provider": {}}\n')
    put(os.path.join(old, "memory", "notes.db"), "db" * 100)
    put(os.path.join(old, "memory", "sub", "deep", "index.json"), "{}\n")
    put(os.path.join(old, "web-terminal.conf.bak"), "padding=10\n")  # "any copies" of the table: a file with another name
    # the rest of a lived-in home
    put(os.path.join(ws, ".claude", ".credentials.json"), '{"token": "secret-fixture"}\n', 0o600)
    put(os.path.join(ws, ".claude", "projects", "p1", "session.jsonl"), "{}\n" * 50)
    put(os.path.join(ws, ".claude.json"), '{"numStartups": 7}\n')
    put(os.path.join(ws, ".ssh", "id_ed25519"), "fixture-private\n", 0o600)
    put(os.path.join(ws, ".ssh", "id_ed25519.pub"), "ssh-ed25519 AAAA fixture\n")
    put(os.path.join(ws, ".gitconfig"), "[user]\n\tname = Fixture\n")
    put(os.path.join(ws, ".bash_history"), "ls\ncd work\n")
    put(os.path.join(ws, "work", "app", "package.json"), '{"name": "app"}\n')
    put(os.path.join(ws, "work", "app", "src", "index.js"), "console.log(1)\n")
    put(os.path.join(ws, "work", "app", ".git", "HEAD"), "ref: refs/heads/main\n")
    put(os.path.join(ws, "work", "notes with space", "a b.txt"), "spaces\n")
    put(os.path.join(ws, ".npm", "_cacache", "index-v5", "ab", "cd"), "cache\n")
    put(os.path.join(ws, ".local", "share", "opencode", "auth.json"), "{}\n", 0o600)
    put(os.path.join(ws, ".config", "gcloud", "configurations", "config_default"), "[core]\n")
    put(os.path.join(ws, ".config", "swarmbox", "unrelated.txt"), "keep\n")
    os.symlink("work/app", os.path.join(ws, "app-link"))


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="swarmbox-test-mig-e2e-"))
        self.addCleanup(self._cleanup)
        self.source = os.path.join(self.tmp, "source", ".work")
        os.makedirs(self.source)
        build_fixture(self.source)
        self.src_digest = digest(self.source)
        self.ws = os.path.join(self.tmp, "copy", ".work")
        shutil.copytree(self.source, self.ws, symlinks=True)
        self.assertEqual(digest(self.ws), self.src_digest, "the copy must start identical to the source")
        self.old = os.path.join(self.ws, ".swarmbox")
        self.claude = os.path.join(self.ws, ".claude", "settings.json")
        self.watch = {p: digest(p) for p in REAL_WATCH}

    def _cleanup(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def tearDown(self):
        self.assertEqual(digest(self.source), self.src_digest, "the source fixture must never change")
        for p, d in self.watch.items():
            self.assertEqual(digest(p), d, "a real home path was written: %s" % p)

    def migrate(self, ws=None, **extra):
        libdir = os.path.join(self.tmp, "lib")
        if not os.path.isdir(libdir):
            os.mkdir(libdir)
            os.symlink(DIRS_SH, os.path.join(libdir, "dirs.sh"))
        env = {"PATH": "/usr/bin:/bin", "HOME": ws or self.ws, "SWARMBOX_TEST_LIB": libdir, "LANG": "C.UTF-8"}
        env.update(extra)
        return subprocess.run(["bash", MIGRATE], env=env, capture_output=True, text=True, timeout=60)


class TableOnTheFixture(Base):
    """[reduced: fixture] Each verb of the 12.4 table, on the larger workspace."""

    def test_every_row_and_the_rest_of_the_home_untouched(self):
        before_rest = {e for e in digest(self.ws)
                       if not e[0].startswith(".swarmbox") and e[0] != os.path.join(".claude", "settings.json")}
        r = self.migrate()
        self.assertEqual(r.returncode, 0, r.stderr)
        # copied, then removed
        self.assertFalse(os.path.islink(self.claude))
        self.assertEqual(get(self.claude), SETTINGS)
        self.assertFalse(os.path.lexists(os.path.join(self.old, "settings.json")))
        # moved
        dest = os.path.join(self.ws, ".config", "swarmbox", "web-terminal.conf")
        self.assertEqual(get(dest), "# web terminal\npadding=14\nctrlVPaste=false\ncopyOnSelect=true\n")
        self.assertFalse(os.path.lexists(os.path.join(self.old, "web-terminal.conf")))
        # deleted
        for n in ("ttyd-index.html", "opencode-local.json", "podman.sock", "web-terminal.log",
                  "podman-service.log", "web-terminal.lock", "podman-service.lock"):
            self.assertFalse(os.path.lexists(os.path.join(self.old, n)), n)
        # left alone: memory/ (whole tree), and the file the table does not know
        self.assertEqual(get(os.path.join(self.old, "memory", "notes.db")), "db" * 100)
        self.assertEqual(get(os.path.join(self.old, "memory", "sub", "deep", "index.json")), "{}\n")
        self.assertEqual(get(os.path.join(self.old, "web-terminal.conf.bak")), "padding=10\n")
        self.assertTrue(os.path.isdir(self.old), ".swarmbox/ must stay while memory/ exists")
        self.assertEqual(sorted(os.listdir(self.old)), ["memory", "web-terminal.conf.bak"])
        self.assertEqual(len([ln for ln in r.stdout.splitlines() if "memory" in ln]), 1, "memory/ is mentioned once: %r" % r.stdout)
        self.assertIn("web-terminal.conf.bak", r.stdout)
        # nothing else of the home changed (projects, credentials, ssh, caches, links)
        after = set(digest(self.ws))
        new_entries = {e[0] for e in after - before_rest if not e[0].startswith(".swarmbox")}
        self.assertTrue(before_rest <= after, sorted(before_rest - after))
        self.assertEqual(new_entries, {os.path.join(".config", "swarmbox", "web-terminal.conf"),
                                       os.path.join(".claude", "settings.json")} | {
            n for n in new_entries if n in (".config", ".config/swarmbox")})

    def test_the_second_run_changes_nothing_and_says_only_the_memory_line(self):
        self.assertEqual(self.migrate().returncode, 0)
        after_first = digest(self.ws)
        r = self.migrate()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(digest(self.ws), after_first)
        self.assertEqual(len([ln for ln in r.stdout.splitlines() if "memory" in ln]), 1)
        self.assertNotIn("settings.json", r.stdout)

    def test_without_memory_the_old_folder_goes_when_empty_and_a_third_run_is_silent(self):
        shutil.rmtree(os.path.join(self.old, "memory"))
        os.unlink(os.path.join(self.old, "web-terminal.conf.bak"))
        r = self.migrate()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(os.path.lexists(self.old))
        r2 = self.migrate()
        self.assertEqual((r2.returncode, r2.stdout, r2.stderr), (0, "", ""))


class NeverOverwritesOnTheFixture(Base):
    def test_existing_destinations_are_kept_and_the_old_copies_stay(self):
        put(os.path.join(self.ws, ".config", "swarmbox", "web-terminal.conf"), "padding=99\n")
        os.unlink(self.claude)
        put(self.claude, '{"theme": "light"}\n')
        r = self.migrate()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(get(os.path.join(self.ws, ".config", "swarmbox", "web-terminal.conf")), "padding=99\n")
        self.assertEqual(get(self.claude), '{"theme": "light"}\n')
        self.assertEqual(get(os.path.join(self.old, "web-terminal.conf")), "# web terminal\npadding=14\nctrlVPaste=false\ncopyOnSelect=true\n")
        self.assertEqual(get(os.path.join(self.old, "settings.json")), SETTINGS)
        before = digest(self.ws)
        self.assertEqual(self.migrate().returncode, 0)
        self.assertEqual(digest(self.ws), before, "a kept conflict stays a kept conflict")

    def test_a_symlinked_old_folder_is_not_followed(self):
        elsewhere = os.path.join(self.tmp, "elsewhere")
        os.rename(self.old, elsewhere)
        os.symlink(elsewhere, self.old)
        os.unlink(self.claude)  # the v0.1.0 link would dangle through the link; the point here is the folder
        before = digest(elsewhere)
        r = self.migrate()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(digest(elsewhere), before)
        self.assertTrue(os.path.islink(self.old))


class Sequence(Base):
    """[reduced: fixture, fake podman] Steps 2 to 6 of 12.4 with the generated bash function and the real host helper."""

    def setUp(self):
        super().setUp()
        self.home = os.path.join(self.tmp, "home")
        self.data = os.path.join(self.home, "data")
        self.cfg = os.path.join(self.home, "cfg")
        self.stt = os.path.join(self.home, "state")
        hd = os.path.join(self.data, "swarmbox", "host")
        os.makedirs(hd)
        for n in ("swarmbox-host", "VERSION", "DEFAULTS"):
            shutil.copy(os.path.join(HOST_DIR, n), hd)
        os.chmod(os.path.join(hd, "swarmbox-host"), 0o755)
        put(os.path.join(hd, "tool-ports"), "")
        for n, c in (("localtime", ""), ("tun", ""), ("proc-version", "Linux version 6.1.0 (debian)\n")):
            put(os.path.join(self.tmp, n), c)
        self.old_sock = "unix://%s/.swarmbox/podman.sock" % self.ws
        self.new_sock = "unix://%s/.local/state/swarmbox/podman.sock" % self.ws
        self.fp = FakePodman(self.script(old_box=True)).__enter__()
        self.addCleanup(self.fp.__exit__)
        self.fn = self.make_function("--workspace", self.ws)

    def script(self, old_box):
        look = ({"stdout": "running|%s|sha256:aaa|false||old:latest|||\n" % NAME} if old_box
                else {"exit": 125, "stderr": "Error: no such container %s\n" % NAME})
        return {
            "container": {"rules": [
                {"match": ["inspect", ".Mounts"], "stdout": self.ws if old_box else ""},
                {"match": ["inspect", "swarmbox.fingerprint"], **look},
                {"match": ["inspect", "State.Status"], "stdout": "running\n"}]},
            "image": {"rules": [{"match": ["exists"]}, {"match": ["inspect"], "stdout": "sha256:aaa\n"}]},
            "version": {"stdout": "4.3.1\n"}, "exec": {"stdout": "ok\n"}, "run": {"cidfile": "abc\n"}, "ps": {}, "rm": {},
            "system": {"rules": [{"match": ["connection", "list"], "seq": [
                {"stdout": "%s %s\nother unix:///x/other.sock\n" % (NAME, self.old_sock)},
                {"stdout": "%s %s\nother unix:///x/other.sock\n" % (NAME, self.new_sock)}]}]},
        }

    def make_function(self, *flags):
        r = subprocess.run(["sh", INIT, "--shell", "bash", *flags],
                           env={"PATH": os.environ["PATH"], "SWARMBOX_TEST_HOST_DIR": HOST_DIR}, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        path = os.path.join(self.tmp, "fn.bash")
        put(path, r.stdout)
        return path

    def env(self, **extra):
        e = self.fp.env()
        for k in list(e):
            if k.startswith(("SWARMBOX_", "XDG_")):
                del e[k]
        e.update({"HOME": self.home, "XDG_DATA_HOME": self.data, "XDG_CONFIG_HOME": self.cfg, "XDG_STATE_HOME": self.stt,
                  "SWARMBOX_INIT": "0", "SWARMBOX_LOCALTIME_FILE": os.path.join(self.tmp, "localtime"),
                  "SWARMBOX_TEST_PROC_VERSION": os.path.join(self.tmp, "proc-version"), "SWARMBOX_TEST_OS": "Linux",
                  "SWARMBOX_TEST_TUN": os.path.join(self.tmp, "tun"), "SWARMBOX_TEST_NAP": "0.02",
                  "SWARMBOX_TEST_READY_TRIES": "40", "LC_ALL": "C", "TERM": "dumb"})
        e.update(extra)
        return e

    def sw(self, *args):
        return subprocess.run(["bash", "--noprofile", "--norc", "-c", '. "$1"; shift; swarmbox "$@"; exit $?', "bash", self.fn,
                               *args], env=self.env(), capture_output=True, text=True, stdin=subprocess.DEVNULL, cwd=self.tmp,
                              timeout=90)

    def subs(self, name):
        return [c for c in self.fp.calls() if c and c[0] == name]

    def idx(self, pred):
        for i, c in enumerate(self.fp.calls()):
            if pred(c):
                return i
        self.fail("no such podman call")

    def test_full_12_4_sequence(self):
        # step 2 is not done yet: the first call of 2.0 stops on the v0.1.0 container and changes nothing
        r = self.sw("up")
        self.assertEqual(r.returncode, 5, r.stderr)
        self.assertIn("made by SwarmBox v0.1.0", r.stderr)
        self.assertIn("podman rm -f %s" % NAME, r.stderr)
        self.assertEqual([c for c in self.fp.calls() if c[0] in ("rm", "run", "stop", "start")], [])
        self.assertEqual(self.subs("system"), [c for c in self.subs("system") if c[:3] == ["system", "connection", "list"]]
                         or [])
        # step 2: the owner removes the old container; the workspace and the volume stay
        subprocess.run(["podman", "rm", "-f", NAME], env=self.env(), check=True, capture_output=True)
        self.fp.configure(self.script(old_box=False))
        # step 3: init --workspace (in the function's seed), then the first call records WORKSPACE
        # step 4: env add for the former --env-keys, config set for the other flags
        for args in (("env", "add", "GITHUB_TOKEN"), ("env", "add", "NPM_TOKEN"), ("config", "set", "PORTS", "3000,8080"),
                     ("config", "set", "BROWSER_URL", "9222")):
            r = self.sw(*args)
            self.assertEqual(r.returncode, 0, "%s: %s" % (args, r.stderr))
        cfg = get(os.path.join(self.cfg, "swarmbox", "config"))
        self.assertIn("WORKSPACE=" + self.ws, cfg)
        self.assertIn("PORTS=3000,8080", cfg)
        self.assertIn("ENV_KEYS=", cfg)
        for k in ("GITHUB_TOKEN", "NPM_TOKEN"):
            self.assertIn(k, cfg)
        self.assertIn("BROWSER_URL=", cfg)
        # the first up creates the box and re-registers the connection (3.4)
        r = self.sw("up")
        self.assertEqual(r.returncode, 0, r.stderr)
        calls = self.fp.calls()
        rm = self.idx(lambda c: c[:2] == ["rm", "-f"] and NAME in c)
        run = self.idx(lambda c: c[0] == "run" or c[:2] == ["container", "run"])
        rem = self.idx(lambda c: c[:3] == ["system", "connection", "remove"])
        add = self.idx(lambda c: c[:3] == ["system", "connection", "add"])
        self.assertLess(rm, run)
        self.assertLess(run, rem)
        self.assertLess(rem, add)
        self.assertEqual(calls[rem][3], NAME)
        self.assertEqual(calls[add][3:], [NAME, self.new_sock])
        # the box is created on the copy as its workspace and on the existing volume only
        runc = calls[run]
        self.assertTrue(any(self.ws in a for a in runc), runc)
        for c in calls:
            self.assertFalse(c[:2] == ["volume", "rm"] or c[:3] == ["volume", "prune"], c)
            self.assertFalse(c[0] == "rm" and DEFAULT_VOLUME in c, c)
            self.assertFalse(c[:2] == ["system", "reset"] or c[:2] == ["system", "prune"], c)
        self.assertEqual(len([c for c in calls if c[0] == "rm"]), 1, "only the old container was removed")
        # the connection step on its own now finds the new address: no second remove and add
        before = len(self.fp.calls())
        r = subprocess.run([os.path.join(self.data, "swarmbox", "host", "swarmbox-host"), "connection"], env=self.env(),
                           capture_output=True, text=True, stdin=subprocess.DEVNULL, cwd=self.tmp, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), self.new_sock)
        self.assertEqual([c for c in self.fp.calls()[before:] if c[:3] in (["system", "connection", "remove"], ["system", "connection", "add"])], [])
        # step 6: serve's layout migration (the real script) on the copy, then again
        r = self.migrate()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(os.path.isdir(os.path.join(self.old, "memory")))
        after = digest(self.ws)
        self.assertEqual(self.migrate().returncode, 0)
        self.assertEqual(digest(self.ws), after)
        # the data of the user is the data of the fixture
        self.assertEqual(get(os.path.join(self.ws, "work", "app", "src", "index.js")), "console.log(1)\n")
        self.assertEqual(get(os.path.join(self.ws, ".claude", ".credentials.json")), '{"token": "secret-fixture"}\n')

    def test_calling_the_function_before_init_records_the_default_workspace_the_documented_trap(self):
        """Without the seed the first call would use the default workspace of 3.7.5: this is why 12.4 forbids a call between the
        removal and init. Only config get is run here (no box, no podman)."""
        plain = self.make_function()
        r = subprocess.run(["bash", "--noprofile", "--norc", "-c", '. "$1"; swarmbox config get WORKSPACE', "bash", plain],
                           env=self.env(), capture_output=True, text=True, stdin=subprocess.DEVNULL, cwd=self.tmp, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotEqual(r.stdout.strip(), self.ws)
        self.assertTrue(r.stdout.strip().endswith("swarmbox"), r.stdout)
        self.assertEqual(self.fp.calls().count([]), 0)


class FixtureHonesty(unittest.TestCase):
    def test_every_name_in_the_fixture_is_written_by_the_v0_1_0_scripts_or_marked_extra(self):
        """The names of `.swarmbox/` in the fixture, checked against git show v0.1.0 when the tag exists."""
        r = subprocess.run(["git", "-C", ROOT, "rev-parse", "--verify", "-q", "v0.1.0^{commit}"], capture_output=True, text=True)
        if r.returncode != 0:
            self.skipTest("tag v0.1.0 not present")
        text = ""
        for p in ("container/scripts/init.sh", "container/scripts/podman-service.sh", "container/web/web-terminal.sh", "Dockerfile"):
            g = subprocess.run(["git", "-C", ROOT, "show", "v0.1.0:" + p], capture_output=True, text=True)
            text += g.stdout
        for n in ("settings.json", "web-terminal.conf", "web-terminal.lock", "web-terminal.log", "podman-service.lock",
                  "podman-service.log", "podman.sock", "ttyd-index.html", "opencode-local.json"):
            self.assertIn(n, text, "%s is not named by the v0.1.0 scripts" % n)
        self.assertIn(".swarmbox", text)

    def test_the_source_and_the_copy_are_distinct_mktemp_folders_never_a_real_workspace(self):
        self.assertNotIn(os.path.join(REAL_HOME, "swarmbox"), tempfile.gettempdir())
        src = inspect_source()
        body = src.split("def build_fixture")[1].split("class Base")[0]
        self.assertNotIn("expanduser", body)
        self.assertNotIn("REAL_HOME", body)


def inspect_source():
    with open(__file__) as f:
        return f.read()


class DocsText(unittest.TestCase):
    """The backup comes first, in the migration checklist and in the README."""

    def read(self, *p):
        with open(os.path.join(ROOT, *p)) as f:
            return f.read()

    def test_migration_checklist_tells_to_back_up_before_any_command(self):
        t = self.read("docs", "migration.md")
        low = t.lower()
        self.assertIn("back up", low)
        first_cmd = min(i for i in (t.find("podman rm -f"), t.find("init --workspace"), t.find("swarmbox env add")) if i >= 0)
        self.assertLess(low.find("back up"), first_cmd)
        for needle in ("podman rm -f swarmbox", "init --workspace", "swarmbox env add", "swarmbox config set PORTS",
                       "swarmbox config set BROWSER_URL", "swarmbox remote status", OLD_NAME + "-containers", "memory/",
                       "copy", "sha256sum"):
            self.assertIn(needle, t)
        real = t[t.index("## The real migration"):]
        self.assertLess(real.find("podman rm -f swarmbox"), real.find("init --workspace"))
        self.assertLess(real.find("init --workspace"), real.find("swarmbox env add"))
        self.assertLess(t.lower().find("back up"), t.index("## Try it on a copy"))
        self.assertEqual(t.count("```") % 2, 0)

    def test_readme_points_to_it_and_repeats_the_backup(self):
        t = self.read("README.md")
        self.assertIn("docs/migration.md", t)
        i = t.find("v0.1.0")
        self.assertGreaterEqual(i, 0)
        self.assertIn("back up", t.lower())

    def test_design_b29_says_fixture_closed_and_real_copy_is_an_owner_action(self):
        t = self.read("docs", "design.md")
        row = [ln for ln in t.splitlines() if ln.startswith("| B29 ")][0]
        self.assertIn("6.4", row)
        self.assertIn("owner", row.lower())
        self.assertIn("docs/migration.md", row)


if __name__ == "__main__":
    unittest.main()
