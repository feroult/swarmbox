"""Slice 3.1: the host helper's configuration surface (design 3.7.2, 3.7.3, 3.7.5, 7, 8.2).

container/host/swarmbox-host runs here as a real program with a cleared environment: PATH, a mktemp HOME and the XDG
variables the case sets, nothing else (so a SWARMBOX_* variable of the live box can never leak in). Nothing touches the
real home: a module-level guard compares a listing of the real SwarmBox folders before and after the run.
Run: python3 tests/test_host_config.py
"""
import os
import pty
import select
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import ROOT  # noqa: E402

HELPER = os.path.join(ROOT, "container", "host", "swarmbox-host")
with open(os.path.join(ROOT, "container", "host", "VERSION")) as _f:
    VERSION = _f.read().strip()
TOKEN = "eyJhbGciOiJIUzI1NiJ9.canarytoken-0123456789"
CANARY = "CANARY-VALUE-do-not-print-7f3a"

# key -> (default or None for "unset", a good value, a different good value, [bad values])
KEYS = {
    "WORKSPACE": (None, "/srv/work", "/srv/other", ["a:b", "a\nb"]),
    "HOSTNAME": ("swarmbox", "devbox", "box2", ["-x", "a b", "a_b", "x" * 64]),
    "TZ": ("local", "Europe/Lisbon", "off", ["a b", "Europe/", "../etc", "9am", "A//B"]),
    "INIT": ("auto", "1", "0", ["yes", "2"]),
    "PORTS": (None, "3000,8080:80", "127.0.0.1:9000:3000", ["abc", "3000,", "99999", "1:2:3:4", "0", ",1", "1,,2", "1 2"]),
    "HOST_ACCESS": ("0", "1", "0", ["yes", "2", "true"]),
    "BROWSER_URL": (None, "9222", "host.example:1234", ["a b", "ftp://x", "99999", "nohostport", ":1234"]),
    "WEB": ("1", "0", "1", ["yes", "2"]),
    "WEB_PORT": ("7681", "8000", "8001", ["0", "65536", "abc", "-1"]),
    "WITH": (None, "claude,gcloud", "claude", ["Claude", "a b", "a,,b", ",a", "a,"]),
    "AGENT": (None, "claude", "opencode", ["a,b", "A B"]),
    "YOLO": ("1", "0", "1", ["yes", "2"]),
    "ENV_KEYS": (None, "ANTHROPIC_API_KEY,GEMINI_API_KEY", "FOO", ["1BAD", "A,SWARMBOX_CLOUDFLARE_X", "a b", "A-B"]),
    "IMAGE": (None, "localhost:5000/sb:2.0.1", "swarmbox:dev", ["a b", "x\ty"]),
}
LIST_ORDER = ["NAME", "WORKSPACE", "HOSTNAME", "TZ", "INIT", "PORTS", "HOST_ACCESS", "BROWSER_URL", "WEB", "WEB_PORT",
              "WITH", "AGENT", "YOLO", "ENV_KEYS", "IMAGE", "CLOUDFLARE_TUNNEL_TOKEN"]


def slurp(path):
    with open(path, errors="replace") as f:
        return f.read()


def write_file(path, text):
    with open(path, "w") as f:
        f.write(text)


def real_listing():
    """Listing (path, size, mtime) of the folders the helper must never touch in the real home."""
    home = os.path.expanduser("~")
    out = []
    for parts in ((".config", "swarmbox"), (".local", "state", "swarmbox"), (".local", "share", "swarmbox")):
        root = os.path.join(home, *parts)
        for d, dirs, files in os.walk(root):
            for n in sorted(dirs + files):
                p = os.path.join(d, n)
                try:
                    st = os.lstat(p)
                    out.append((p, st.st_size, st.st_mtime_ns))
                except OSError:
                    out.append((p, None, None))
    return out


_BEFORE = None


def setUpModule():
    global _BEFORE
    _BEFORE = real_listing()


def tearDownModule():
    assert real_listing() == _BEFORE, "the helper changed the real SwarmBox folders in the real home"


class Base(unittest.TestCase):
    name = None

    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="swarmbox-test-hostcfg."))   # realpath: /var is a link on macOS
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.home = os.path.join(self.tmp, "home")
        os.mkdir(self.home)
        self.assertNotEqual(os.path.realpath(self.home), os.path.realpath(os.path.expanduser("~")))
        self.cfgroot = os.path.join(self.home, ".config", "swarmbox")
        self.state = os.path.join(self.home, ".local", "state", "swarmbox")

    @property
    def cfg_file(self):
        return os.path.join(self.cfgroot, "config")

    def env(self, extra=None, path=None):
        e = {"PATH": path or os.environ["PATH"], "HOME": self.home}
        e.update(extra or {})
        return e

    def run_h(self, *args, env=None, path=None, stdin=None, cwd=None, helper=None):
        return subprocess.run([helper or HELPER, *args], env=self.env(env, path), capture_output=True, text=True,
                              input=stdin if stdin is not None else "", cwd=cwd or self.tmp, timeout=60)

    def write_cfg(self, text, mode=0o600, file=None):
        f = file or self.cfg_file
        os.makedirs(os.path.dirname(f), exist_ok=True)
        if os.path.exists(f):
            os.chmod(f, 0o600)
        with open(f, "w") as fh:
            fh.write(text)
        os.chmod(f, mode)

    def mode(self, f=None):
        return stat.S_IMODE(os.stat(f or self.cfg_file).st_mode)

    def get(self, key, env=None):
        p = self.run_h("config", "get", key, env=env)
        return p.returncode, p.stdout, p.stderr


class VersionTest(Base):
    def test_version_prints_the_file_next_to_the_helper(self):
        p = self.run_h("version")
        self.assertEqual((p.returncode, p.stdout, p.stderr), (0, VERSION + "\n", ""))

    def test_version_follows_a_copied_helper_and_its_version_file(self):
        d = os.path.join(self.tmp, "copy")
        os.mkdir(d)
        shutil.copy(HELPER, d)
        os.chmod(os.path.join(d, "swarmbox-host"), 0o755)
        write_file(os.path.join(d, "VERSION"), "9.8.7\n")
        p = self.run_h("version", helper=os.path.join(d, "swarmbox-host"))
        self.assertEqual((p.returncode, p.stdout), (0, "9.8.7\n"))

    def test_missing_or_bad_version_file_exits_3(self):
        d = os.path.join(self.tmp, "copy")
        os.mkdir(d)
        shutil.copy(HELPER, d)
        h = os.path.join(d, "swarmbox-host")
        os.chmod(h, 0o755)
        p = self.run_h("version", helper=h)
        self.assertEqual(p.returncode, 3)
        self.assertIn("VERSION", p.stderr)
        write_file(os.path.join(d, "VERSION"), "banana\n")
        self.assertEqual(self.run_h("version", helper=h).returncode, 3)
        self.assertEqual(self.run_h("config", "list", helper=h).returncode, 3)

    def test_usage_and_unknown_subcommands(self):
        self.assertEqual(self.run_h().returncode, 2)
        p = self.run_h("frobnicate")
        self.assertEqual(p.returncode, 2)
        self.assertEqual(p.stdout, "")
        self.assertEqual(self.run_h("version", "extra").returncode, 2)
        self.assertEqual(self.run_h("config").returncode, 2)
        self.assertEqual(self.run_h("config", "frob").returncode, 2)

    def test_later_subcommands_say_so_and_do_nothing(self):
        for c in ("up", "reset", "stop", "update", "url", "remote"):   # create-flags and fingerprint arrived in slice 3.2
            p = self.run_h(c)
            self.assertEqual(p.returncode, 70, c)
            self.assertIn("not implemented", p.stderr)
            self.assertEqual(p.stdout, "")
        self.assertFalse(os.path.exists(os.path.join(self.home, ".config")))


class DefaultsAndPrecedenceTest(Base):
    def default(self, key):
        d = KEYS[key][0]
        if key == "WORKSPACE":
            return os.path.join(self.home, "swarmbox")
        if key == "IMAGE":
            return "ghcr.io/<org>/swarmbox:" + VERSION
        return d

    def test_every_key_default_get(self):
        for key in KEYS:
            rc, out, err = self.get(key)
            want = self.default(key)
            if key == "IMAGE":
                want = "ghcr.io/<org>/swarmbox:" + VERSION
            if want is None:
                self.assertEqual((rc, out), (1, ""), key)
            else:
                self.assertEqual((rc, out), (0, want + "\n"), key)
            self.assertEqual(err, "", key)
        self.assertEqual(self.get("NAME")[:2], (0, "swarmbox\n"))
        self.assertEqual(self.get("CLOUDFLARE_TUNNEL_TOKEN")[:2], (1, ""))

    def test_unknown_key_exits_2(self):
        for k in ("NOPE", "workspace", "SWARMBOX_WITH", "LOCAL_LLM_URL", ""):
            rc, out, err = self.get(k)
            self.assertEqual((rc, out), (2, ""), k)
            self.assertIn("unknown key", err)

    def test_file_value_then_env_override_for_every_key(self):
        for key, (_, good, other, _bad) in KEYS.items():
            self.write_cfg("%s=%s\n" % (key, good))
            self.assertEqual(self.get(key)[:2], (0, good + "\n"), key)
            self.assertEqual(self.get(key, env={"SWARMBOX_" + key: other})[:2], (0, other + "\n"), key)
            # an empty environment value does not override
            self.assertEqual(self.get(key, env={"SWARMBOX_" + key: ""})[:2], (0, good + "\n"), key)

    def test_env_beats_default_without_a_file(self):
        for key, (_, good, _o, _b) in KEYS.items():
            self.assertEqual(self.get(key, env={"SWARMBOX_" + key: good})[:2], (0, good + "\n"), key)

    def test_empty_file_value_means_default(self):
        self.write_cfg("TZ=\nWITH=\nPORTS=\n")
        self.assertEqual(self.get("TZ")[:2], (0, "local\n"))
        self.assertEqual(self.get("WITH")[:2], (1, ""))
        self.assertEqual(self.get("PORTS")[:2], (1, ""))

    def test_list_every_key_with_source(self):
        self.write_cfg("WITH=claude\nHOSTNAME=fromfile\n")
        p = self.run_h("config", "list", env={"SWARMBOX_HOSTNAME": "fromenv", "SWARMBOX_TZ": "off"})
        self.assertEqual(p.returncode, 0)
        self.assertEqual(p.stderr, "")
        lines = p.stdout.splitlines()
        self.assertEqual([l.split("=", 1)[0] for l in lines], LIST_ORDER)
        got = {l.split("=", 1)[0]: l.split("=", 1)[1].split("\t") for l in lines}
        self.assertEqual(got["WITH"], ["claude", "file"])
        self.assertEqual(got["HOSTNAME"], ["fromenv", "env"])
        self.assertEqual(got["TZ"], ["off", "env"])
        self.assertEqual(got["INIT"], ["auto", "default"])
        self.assertEqual(got["PORTS"], ["", "default"])
        self.assertEqual(got["NAME"], ["swarmbox", "default"])
        self.assertEqual(got["IMAGE"], ["ghcr.io/<org>/swarmbox:" + VERSION, "default"])
        self.assertEqual(got["CLOUDFLARE_TUNNEL_TOKEN"], ["unset", "default"])

    def test_xdg_variables_are_honored_and_bad_ones_ignored(self):
        x = os.path.join(self.tmp, "xdgc")
        self.write_cfg("WITH=viaxdg\n", file=os.path.join(x, "swarmbox", "config"))
        self.assertEqual(self.get("WITH", env={"XDG_CONFIG_HOME": x})[:2], (0, "viaxdg\n"))
        # relative or empty XDG values are ignored (as in dirs.sh)
        self.write_cfg("WITH=viahome\n")
        self.assertEqual(self.get("WITH", env={"XDG_CONFIG_HOME": "relative/x"})[:2], (0, "viahome\n"))
        self.assertEqual(self.get("WITH", env={"XDG_CONFIG_HOME": ""})[:2], (0, "viahome\n"))
        # state: the notices file goes to XDG_STATE_HOME
        s = os.path.join(self.tmp, "xdgs")
        self.run_h("config", "seed", "--with", "a", env={"XDG_STATE_HOME": s})
        self.run_h("config", "seed", "--with", "b", env={"XDG_STATE_HOME": s})
        self.assertTrue(os.path.isfile(os.path.join(s, "swarmbox", "notices")))
        self.assertFalse(os.path.exists(self.state))

    def test_home_not_absolute_exits_1(self):
        p = subprocess.run([HELPER, "config", "list"], env={"PATH": os.environ["PATH"], "HOME": "rel"}, capture_output=True, text=True)
        self.assertEqual(p.returncode, 1)


class GrammarTest(Base):
    def test_values_are_literal(self):
        self.write_cfg("WORKSPACE=/srv/my work dir\nIMAGE=a=b\nHOSTNAME=  padded \t \nTZ=Europe/Lisbon\r\n")
        self.assertEqual(self.get("WORKSPACE")[:2], (0, "/srv/my work dir\n"))
        self.assertEqual(self.get("IMAGE")[:2], (0, "a=b\n"))          # '=' inside the value
        self.assertEqual(self.get("HOSTNAME")[:2], (0, "padded\n"))    # blanks trimmed
        self.assertEqual(self.get("TZ")[:2], (0, "Europe/Lisbon\n"))   # CRLF file
        self.write_cfg("WORKSPACE=$HOME/x \"q\" 'r' \\n ${A}\n")
        self.assertEqual(self.get("WORKSPACE")[:2], (0, "$HOME/x \"q\" 'r' \\n ${A}\n"))

    def test_comments_and_blank_lines(self):
        self.write_cfg("# a comment\n\n   # indented comment WITH=no\n\t\nWITH=yes\n   # HOSTNAME=no\n")
        self.assertEqual(self.get("WITH")[:3], (0, "yes\n", ""))
        self.assertEqual(self.get("HOSTNAME")[:2], (0, "swarmbox\n"))

    def test_later_line_wins(self):
        self.write_cfg("WITH=a\nWITH=b\nTZ=off\nWITH=c\n")
        self.assertEqual(self.get("WITH")[:3], (0, "c\n", ""))

    def test_last_line_without_newline(self):
        self.write_cfg("WITH=a\nHOSTNAME=last")
        self.assertEqual(self.get("HOSTNAME")[:2], (0, "last\n"))

    def test_unknown_key_warns_once_and_is_ignored(self):
        self.write_cfg("FOO=1\nWITH=a\nFOO=2\nlower=3\nnot a pair\n")
        p = self.run_h("config", "list")
        self.assertEqual(p.returncode, 0)
        self.assertEqual(p.stderr.count("unknown key"), 1)
        for k in ("FOO", "lower", "not a pair"):
            self.assertIn(k, p.stderr)
        self.assertEqual(p.stderr.count("FOO"), 1)
        self.assertNotIn("FOO", p.stdout)
        rc, out, err = self.get("WITH")
        self.assertEqual((rc, out), (0, "a\n"))
        self.assertEqual(err.count("unknown key"), 1)

    def test_name_line_is_an_unknown_key(self):
        self.write_cfg("NAME=hijack\nWITH=a\n")
        rc, out, err = self.get("NAME")
        self.assertEqual((rc, out), (0, "swarmbox\n"))
        self.assertIn("NAME", err)
        self.assertIn("unknown key", err)
        # and it did not move the folder: the default box still reads this file
        self.assertEqual(self.get("WITH")[1], "a\n")

    def test_name_comes_only_from_the_environment(self):
        self.assertEqual(self.get("NAME", env={"SWARMBOX_NAME": "other"})[:2], (0, "other\n"))
        p = self.run_h("config", "set", "NAME", "x")
        self.assertEqual(p.returncode, 2)
        self.assertIn("SWARMBOX_NAME", p.stderr)
        self.assertFalse(os.path.exists(self.cfg_file))

    def test_second_box_has_its_own_folder(self):
        self.write_cfg("WITH=first\n")
        second = os.path.join(self.cfgroot, "other", "config")
        self.write_cfg("WITH=second\n", file=second)
        self.assertEqual(self.get("WITH")[1], "first\n")
        self.assertEqual(self.get("WITH", env={"SWARMBOX_NAME": "other"})[1], "second\n")
        p = self.run_h("config", "set", "WITH", "third", env={"SWARMBOX_NAME": "other"})
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("WITH=third", slurp(second))
        self.assertEqual(self.get("WITH")[1], "first\n")
        # an explicit default name is the default box
        self.assertEqual(self.get("WITH", env={"SWARMBOX_NAME": "swarmbox"})[1], "first\n")
        self.assertEqual(self.mode(second), 0o600)

    def test_invalid_box_names_exit_2(self):
        for n in ("../x", "a/b", ".hidden", "a b", "config", "-x", "x;y"):
            p = self.run_h("config", "get", "WITH", env={"SWARMBOX_NAME": n})
            self.assertEqual(p.returncode, 2, n)
            self.assertIn("SWARMBOX_NAME", p.stderr)
        self.assertFalse(os.path.exists(os.path.join(self.home, ".config")))


class SetTest(Base):
    def test_set_every_key_roundtrip_and_file_mode(self):
        for key, (_, good, other, _bad) in KEYS.items():
            p = self.run_h("config", "set", key, good)
            self.assertEqual((p.returncode, p.stdout, p.stderr), (0, "", ""), (key, p.stderr))
            self.assertEqual(self.get(key)[:2], (0, good + "\n"), key)
            p = self.run_h("config", "set", key, other)
            self.assertEqual(p.returncode, 0, key)
            self.assertEqual(self.get(key)[:2], (0, other + "\n"), key)
            self.assertEqual(self.mode(), 0o600, key)

    def test_rejections_name_the_key_and_the_rule_and_write_nothing(self):
        for key, (_, good, _o, bad) in KEYS.items():
            self.write_cfg("# keep\n%s=%s\n" % (key, good))
            before = slurp(self.cfg_file)
            for v in bad:
                p = self.run_h("config", "set", key, v)
                self.assertEqual(p.returncode, 2, (key, v))
                self.assertEqual(p.stdout, "")
                self.assertIn(key, p.stderr)
                self.assertRegex(p.stderr, r"must|cannot", (key, v))
                self.assertEqual(slurp(self.cfg_file), before, (key, v))

    def test_newline_is_refused_with_its_own_message(self):
        p = self.run_h("config", "set", "WITH", "a\nb=c")
        self.assertEqual(p.returncode, 2)
        self.assertIn("newline", p.stderr)
        self.assertFalse(os.path.exists(self.cfg_file))

    def test_unknown_key_and_usage(self):
        self.assertEqual(self.run_h("config", "set", "NOPE", "x").returncode, 2)
        self.assertEqual(self.run_h("config", "set", "WITH").returncode, 2)
        self.assertEqual(self.run_h("config", "set").returncode, 2)
        self.assertEqual(self.run_h("config", "set", "WITH", "a", "b").returncode, 2)
        self.assertFalse(os.path.exists(self.cfg_file))

    def test_empty_value_means_default(self):
        self.run_h("config", "set", "TZ", "off")
        p = self.run_h("config", "set", "TZ", "")
        self.assertEqual(p.returncode, 0)
        self.assertEqual(self.get("TZ")[:2], (0, "local\n"))

    def test_set_keeps_other_lines_and_replaces_every_duplicate(self):
        self.write_cfg("# my comment\nWITH=a\nFOO=bar\nWITH=b\nTZ=off\n")
        self.run_h("config", "set", "WITH", "z")
        text = slurp(self.cfg_file)
        self.assertIn("# my comment\n", text)
        self.assertIn("FOO=bar\n", text)
        self.assertIn("TZ=off\n", text)
        self.assertEqual(text.count("WITH="), 1)
        self.assertEqual(self.get("WITH")[1], "z\n")

    def test_value_with_spaces_and_equals_is_stored_literally(self):
        self.run_h("config", "set", "WORKSPACE", "/srv/a b=c")
        self.assertIn("WORKSPACE=/srv/a b=c\n", slurp(self.cfg_file))
        self.assertEqual(self.get("WORKSPACE")[1], "/srv/a b=c\n")
        self.run_h("config", "set", "WORKSPACE", "  /srv/trim  ")
        self.assertEqual(self.get("WORKSPACE")[1], "/srv/trim\n")

    def test_workspace_normalization(self):
        d = os.path.join(self.tmp, "cwd")
        os.mkdir(d)
        self.run_h("config", "set", "WORKSPACE", "rel/ws", cwd=d)
        self.assertEqual(self.get("WORKSPACE")[1], d + "/rel/ws\n")
        self.run_h("config", "set", "WORKSPACE", ".", cwd=d)
        self.assertEqual(self.get("WORKSPACE")[1], d + "\n")
        self.run_h("config", "set", "WORKSPACE", "~/proj/")
        self.assertEqual(self.get("WORKSPACE")[1], self.home + "/proj\n")

    def test_file_created_with_600_under_umask_022_and_kept_after_rewrite(self):
        script = 'umask 022; exec "$@"'
        p = subprocess.run(["sh", "-c", script, "x", HELPER, "config", "set", "WITH", "a"], env=self.env(),
                           capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(self.mode(), 0o600)
        self.assertEqual(self.mode(self.cfgroot), 0o700)
        os.chmod(self.cfg_file, 0o644)
        subprocess.run(["sh", "-c", script, "x", HELPER, "config", "set", "TZ", "off"], env=self.env(), capture_output=True)
        self.assertEqual(self.mode(), 0o600)
        # no temporary file is left behind
        self.assertEqual(sorted(os.listdir(self.cfgroot)), ["config"])

    def test_set_clears_the_notice_of_that_key(self):
        self.run_h("config", "seed", "--with", "a")
        self.run_h("config", "set", "WITH", "b")
        p = self.run_h("config", "seed", "--with", "a")
        self.assertIn("WITH", p.stderr)
        self.assertEqual(self.run_h("config", "seed", "--with", "a").stderr, "")
        self.run_h("config", "set", "WITH", "c")           # re-arms
        self.assertIn("WITH", self.run_h("config", "seed", "--with", "a").stderr)


class UnreadableConfigTest(Base):
    def test_unreadable_config_exits_1_with_one_message(self):
        self.write_cfg("WITH=a\n", mode=0o000)
        try:
            for args in (("config", "get", "WITH"), ("config", "list"), ("env", "list"), ("config", "set", "WITH", "b")):
                p = self.run_h(*args)
                if os.access(self.cfg_file, os.R_OK):
                    self.skipTest("running as a user that can read a mode 000 file")
                self.assertEqual(p.returncode, 1, args)
                self.assertEqual(p.stderr.count("cannot read"), 1, p.stderr)
        finally:
            os.chmod(self.cfg_file, 0o600)


class SeedTest(Base):
    def test_creates_the_file_once_with_the_given_seeds(self):
        p = self.run_h("config", "seed", "--with", "claude,gcloud", "--workspace", "/srv/ws", "--image", "x/y:1.2.3")
        self.assertEqual((p.returncode, p.stdout), (0, ""))
        self.assertEqual(self.get("WITH")[1], "claude,gcloud\n")
        self.assertEqual(self.get("WORKSPACE")[1], "/srv/ws\n")
        self.assertEqual(self.get("IMAGE")[1], "x/y:1.2.3\n")
        self.assertEqual(self.mode(), 0o600)
        self.assertIn("/srv/ws", p.stderr)

    def test_seed_without_values_still_creates_the_file(self):
        self.assertEqual(self.run_h("config", "seed").returncode, 0)
        self.assertTrue(os.path.isfile(self.cfg_file))
        self.assertEqual(self.get("WITH")[:2], (1, ""))

    def test_seed_equals_form(self):
        self.assertEqual(self.run_h("config", "seed", "--with=a", "--image=i:1").returncode, 0)
        self.assertEqual(self.get("WITH")[1], "a\n")
        self.assertEqual(self.get("IMAGE")[1], "i:1\n")

    def test_relative_workspace_is_made_absolute_and_printed(self):
        d = os.path.join(self.tmp, "here")
        os.mkdir(d)
        p = self.run_h("config", "seed", "--workspace", "proj", cwd=d)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(self.get("WORKSPACE")[1], d + "/proj\n")
        self.assertIn(d + "/proj", p.stderr)

    def test_second_call_changes_nothing_and_notices_once_per_key(self):
        self.run_h("config", "seed", "--with", "a", "--workspace", "/w1")
        before = slurp(self.cfg_file)
        p = self.run_h("config", "seed", "--with", "b", "--workspace", "/w1", "--image", "i:1")
        self.assertEqual(p.returncode, 0)
        self.assertEqual(slurp(self.cfg_file), before)
        lines = [l for l in p.stderr.splitlines() if "init asked for" in l]
        self.assertEqual(len(lines), 2, p.stderr)          # WITH differs, IMAGE differs (file has the default); WORKSPACE same
        self.assertTrue(any("WITH=b" in l and "WITH=a" in l and "swarmbox config set WITH b" in l for l in lines))
        self.assertTrue(any("IMAGE=i:1" in l for l in lines))
        self.assertFalse(any("WORKSPACE" in l for l in lines))
        self.assertEqual(self.run_h("config", "seed", "--with", "b", "--workspace", "/w1", "--image", "i:1").stderr, "")
        notices = slurp(os.path.join(self.state, "notices")).splitlines()
        self.assertEqual(sorted(notices), ["swarmbox:IMAGE", "swarmbox:WITH"])

    def test_notices_are_per_box(self):
        self.run_h("config", "seed", "--with", "a")
        self.run_h("config", "seed", "--with", "a", env={"SWARMBOX_NAME": "other"})
        self.assertIn("WITH", self.run_h("config", "seed", "--with", "b").stderr)
        self.assertIn("WITH", self.run_h("config", "seed", "--with", "b", env={"SWARMBOX_NAME": "other"}).stderr)
        self.assertEqual(sorted(slurp(os.path.join(self.state, "notices")).splitlines()), ["other:WITH", "swarmbox:WITH"])

    def test_seeds_never_come_from_the_environment_and_env_does_not_leak_into_the_file(self):
        self.run_h("config", "seed", "--with", "a", env={"SWARMBOX_WITH": "fromenv", "SWARMBOX_TZ": "off"})
        text = slurp(self.cfg_file)
        self.assertIn("WITH=a", text)
        self.assertNotIn("fromenv", text)
        self.assertNotIn("TZ=", text)

    def test_invalid_values_exit_2_and_create_nothing(self):
        for args in (["--with", "A B"], ["--image", "a b"], ["--workspace", "/a:b"], ["--bogus", "x"], ["--with"], ["stray"]):
            p = self.run_h("config", "seed", *args)
            self.assertEqual(p.returncode, 2, args)
            self.assertFalse(os.path.exists(self.cfg_file), args)
        # a valid and an invalid seed together: nothing is written
        p = self.run_h("config", "seed", "--with", "a", "--image", "a b")
        self.assertEqual(p.returncode, 2)
        self.assertFalse(os.path.exists(self.cfg_file))

    def test_existing_file_is_never_rewritten(self):
        self.write_cfg("# mine\nWITH=a\n", mode=0o640)
        st = os.stat(self.cfg_file)
        self.run_h("config", "seed", "--with", "b")
        self.assertEqual(slurp(self.cfg_file), "# mine\nWITH=a\n")
        self.assertEqual(self.mode(), 0o640)
        self.assertEqual(os.stat(self.cfg_file).st_mtime_ns, st.st_mtime_ns)


class EnvTest(Base):
    def test_add_list_rm_and_idempotence(self):
        self.assertEqual(self.run_h("env", "list").stdout, "")
        self.assertEqual(self.run_h("env", "add", "ANTHROPIC_API_KEY").returncode, 0)
        self.assertEqual(self.run_h("env", "add", "GEMINI_API_KEY").returncode, 0)
        self.assertEqual(self.run_h("env", "add", "ANTHROPIC_API_KEY").returncode, 0)
        self.assertEqual(self.get("ENV_KEYS")[1], "ANTHROPIC_API_KEY,GEMINI_API_KEY\n")
        self.assertEqual(self.mode(), 0o600)
        p = self.run_h("env", "list", env={"GEMINI_API_KEY": CANARY})
        self.assertEqual(p.stdout, "ANTHROPIC_API_KEY\tnot set\nGEMINI_API_KEY\tset\n")
        self.assertEqual(self.run_h("env", "rm", "ANTHROPIC_API_KEY").returncode, 0)
        self.assertEqual(self.get("ENV_KEYS")[1], "GEMINI_API_KEY\n")
        self.assertEqual(self.run_h("env", "rm", "ANTHROPIC_API_KEY").returncode, 0)   # idempotent
        self.assertEqual(self.run_h("env", "rm", "GEMINI_API_KEY").returncode, 0)
        self.assertEqual(self.run_h("env", "list").stdout, "")

    def test_valid_and_invalid_names(self):
        for ok in ("A", "_X", "a_b1", "LOCAL_LLM_URL", "SWARMBOX_FOO"):
            self.assertEqual(self.run_h("env", "add", ok).returncode, 0, ok)
        for bad in ("1A", "A-B", "A B", "", "A=B", "$X", "A;B", "A.B"):
            p = self.run_h("env", "add", bad)
            self.assertEqual(p.returncode, 2, repr(bad))
            self.assertEqual(self.run_h("env", "rm", bad).returncode, 2, repr(bad))

    def test_cloudflare_prefix_is_refused_with_exit_2(self):
        for n in ("SWARMBOX_CLOUDFLARE_TUNNEL_TOKEN", "SWARMBOX_CLOUDFLARE_X", "SWARMBOX_CLOUDFLARE_"):
            for sub in ("add", "rm"):
                p = self.run_h("env", sub, n)
                self.assertEqual(p.returncode, 2, (sub, n))
                self.assertIn("SWARMBOX_CLOUDFLARE_", p.stderr)
        self.assertFalse(os.path.exists(self.cfg_file))
        # a name that only resembles the prefix is accepted
        self.assertEqual(self.run_h("env", "add", "SWARMBOX_CLOUDFLAREX").returncode, 0)

    def test_usage(self):
        self.assertEqual(self.run_h("env").returncode, 2)
        self.assertEqual(self.run_h("env", "add").returncode, 2)
        self.assertEqual(self.run_h("env", "add", "A", "B").returncode, 2)
        self.assertEqual(self.run_h("env", "frob").returncode, 2)
        self.assertEqual(self.run_h("env", "list", "x").returncode, 2)

    def test_values_are_never_printed_or_stored(self):
        self.run_h("env", "add", "MYSECRET")
        outs = []
        for args in (("env", "list"), ("env", "add", "MYSECRET"), ("config", "list"), ("config", "get", "ENV_KEYS"),
                     ("env", "rm", "MYSECRET"), ("env", "add", "MYSECRET")):
            p = self.run_h(*args, env={"MYSECRET": CANARY})
            outs.append(p.stdout + p.stderr)
        self.assertNotIn(CANARY, "".join(outs))
        self.assertNotIn(CANARY, slurp(self.cfg_file))
        for d, _, files in os.walk(self.home):
            for n in files:
                self.assertNotIn(CANARY, slurp(os.path.join(d, n)))

    def test_set_but_empty_counts_as_set(self):
        self.run_h("env", "add", "EMPTYVAR")
        self.assertEqual(self.run_h("env", "list", env={"EMPTYVAR": ""}).stdout, "EMPTYVAR\tset\n")

    def test_env_override_note_and_invalid_names_in_the_file_are_skipped(self):
        self.write_cfg("ENV_KEYS=GOOD,bad name,1X,SWARMBOX_CLOUDFLARE_Y\n")
        p = self.run_h("env", "list")
        self.assertEqual(p.stdout, "GOOD\tnot set\n")
        self.assertEqual(p.stderr.count("ignoring the invalid name"), 3)
        p = self.run_h("env", "add", "NEW", env={"SWARMBOX_ENV_KEYS": "X"})
        self.assertIn("SWARMBOX_ENV_KEYS", p.stderr)

    def test_env_commands_act_on_the_second_box_file(self):
        self.run_h("env", "add", "A1")
        self.run_h("env", "add", "B2", env={"SWARMBOX_NAME": "other"})
        self.assertEqual(self.run_h("env", "list").stdout, "A1\tnot set\n")
        self.assertEqual(self.run_h("env", "list", env={"SWARMBOX_NAME": "other"}).stdout, "B2\tnot set\n")


def pty_run(argv, env, typed=None, wait_prompt=True, cwd=None, timeout=20):
    """Run argv on a pseudo-terminal; type `typed` (a line) after the prompt. Returns (exit code, everything the terminal showed)."""
    pid, fd = pty.fork()
    if pid == 0:
        if cwd:
            os.chdir(cwd)
        os.execve(argv[0], argv, env)
    out = b""
    sent = typed is None
    end = time.time() + timeout
    while time.time() < end:
        r, _, _ = select.select([fd], [], [], 0.2)
        if r:
            try:
                chunk = os.read(fd, 4096)
            except OSError:
                break
            if not chunk:
                break
            out += chunk
        if not sent and b"hidden" in out:
            time.sleep(0.3)   # let stty -echo take effect
            os.write(fd, typed.encode() + b"\n")
            sent = True
    _, status = os.waitpid(pid, 0)
    try:
        os.close(fd)
    except OSError:
        pass
    return os.waitstatus_to_exitcode(status), out.decode(errors="replace")


class TokenTest(Base):
    def set_token(self, token=TOKEN, extra_env=None, path=None):
        return pty_run([HELPER, "config", "set", "CLOUDFLARE_TUNNEL_TOKEN"], self.env(extra_env, path), typed=token)

    def test_set_reads_the_terminal_without_echo(self):
        rc, shown = self.set_token()
        self.assertEqual(rc, 0, shown)
        self.assertNotIn(TOKEN, shown)                      # typed with echo off: the terminal never showed it
        self.assertIn("CLOUDFLARE_TUNNEL_TOKEN=" + TOKEN + "\n", slurp(self.cfg_file))
        self.assertEqual(self.mode(), 0o600)
        self.assertEqual(self.get("CLOUDFLARE_TUNNEL_TOKEN")[:2], (0, TOKEN + "\n"))

    def test_the_terminal_is_restored(self):
        script = 'stty -g > "$1/before"; "$2" config set CLOUDFLARE_TUNNEL_TOKEN; stty -g > "$1/after"'
        rc, _ = pty_run(["/bin/sh", "-c", script, "x", self.tmp, HELPER], self.env(), typed=TOKEN)
        self.assertEqual(rc, 0)
        self.assertEqual(slurp(os.path.join(self.tmp, "before")), slurp(os.path.join(self.tmp, "after")))

    def test_value_on_the_command_line_is_refused(self):
        p = self.run_h("config", "set", "CLOUDFLARE_TUNNEL_TOKEN", TOKEN)
        self.assertEqual(p.returncode, 2)
        self.assertNotIn(TOKEN, p.stdout + p.stderr)
        self.assertFalse(os.path.exists(self.cfg_file))

    def test_without_a_terminal_it_is_refused(self):
        p = self.run_h("config", "set", "CLOUDFLARE_TUNNEL_TOKEN", stdin=TOKEN + "\n")
        self.assertEqual(p.returncode, 2)
        self.assertFalse(os.path.exists(self.cfg_file))

    def test_invalid_token_is_refused(self):
        for bad in ("has space", "semi;colon", "quote'x"):
            rc, shown = self.set_token(bad)
            self.assertEqual(rc, 2, bad)
            self.assertNotIn(bad, shown.replace("hidden", ""))
        rc, _ = self.set_token("")
        self.assertEqual(rc, 2)
        self.assertFalse(os.path.exists(self.cfg_file))

    def test_refuses_to_write_when_chmod_fails(self):
        d = os.path.join(self.tmp, "fakebin")
        os.mkdir(d)
        with open(os.path.join(d, "chmod"), "w") as f:
            f.write("#!/bin/sh\nexit 1\n")
        os.chmod(os.path.join(d, "chmod"), 0o755)
        self.write_cfg("WITH=a\n")
        before = slurp(self.cfg_file)
        rc, shown = self.set_token(path=d + os.pathsep + os.environ["PATH"])
        self.assertEqual(rc, 1, shown)
        self.assertEqual(slurp(self.cfg_file), before)
        self.assertEqual(sorted(os.listdir(self.cfgroot)), ["config"])      # temporary file removed
        self.assertNotIn(TOKEN, shown)
        # any other key is refused too: the write is reported as failed and the file is untouched
        p = self.run_h("config", "set", "TZ", "off", path=d + os.pathsep + os.environ["PATH"])
        self.assertEqual(p.returncode, 1)
        self.assertEqual(slurp(self.cfg_file), before)

    def test_list_never_prints_the_token(self):
        self.write_cfg("CLOUDFLARE_TUNNEL_TOKEN=%s\n" % TOKEN)
        p = self.run_h("config", "list")
        self.assertNotIn(TOKEN, p.stdout + p.stderr)
        self.assertIn("CLOUDFLARE_TUNNEL_TOKEN=set\tfile\n", p.stdout)
        p = self.run_h("config", "list", env={"SWARMBOX_CLOUDFLARE_TUNNEL_TOKEN": CANARY})
        self.assertNotIn(CANARY, p.stdout + p.stderr)
        self.assertIn("CLOUDFLARE_TUNNEL_TOKEN=set\tenv\n", p.stdout)

    def test_environment_beats_the_file_token(self):
        self.write_cfg("CLOUDFLARE_TUNNEL_TOKEN=%s\n" % TOKEN)
        self.assertEqual(self.get("CLOUDFLARE_TUNNEL_TOKEN", env={"SWARMBOX_CLOUDFLARE_TUNNEL_TOKEN": "envtok"})[1], "envtok\n")

    def test_loose_mode_makes_the_helper_ignore_the_token(self):
        self.write_cfg("WITH=a\nCLOUDFLARE_TUNNEL_TOKEN=%s\n" % TOKEN, mode=0o644)
        rc, out, err = self.get("CLOUDFLARE_TUNNEL_TOKEN")
        self.assertEqual((rc, out), (1, ""))
        self.assertIn("mode is 644", err)
        self.assertIn("chmod 600 " + self.cfg_file, err)
        self.assertNotIn(TOKEN, err)
        self.assertEqual(err.count("chmod 600"), 1)
        # the rest of the file is still read
        self.assertEqual(self.get("WITH")[1], "a\n")
        p = self.run_h("config", "list")
        self.assertIn("CLOUDFLARE_TUNNEL_TOKEN=unset\tdefault\n", p.stdout)
        self.assertEqual(p.stderr.count("chmod 600"), 1)
        # the environment still works
        self.assertEqual(self.get("CLOUDFLARE_TUNNEL_TOKEN", env={"SWARMBOX_CLOUDFLARE_TUNNEL_TOKEN": "e"})[1], "e\n")
        os.chmod(self.cfg_file, 0o600)
        rc, out, err = self.get("CLOUDFLARE_TUNNEL_TOKEN")
        self.assertEqual((rc, out, err), (0, TOKEN + "\n", ""))

    def test_other_loose_modes_and_no_token_means_no_warning(self):
        for m in (0o640, 0o666, 0o400, 0o700, 0o601):
            self.write_cfg("CLOUDFLARE_TUNNEL_TOKEN=%s\n" % TOKEN, mode=m)
            rc, out, err = self.get("CLOUDFLARE_TUNNEL_TOKEN")
            self.assertEqual((rc, out), (1, ""), oct(m))
            self.assertIn("mode is %o;" % m, err)
        self.write_cfg("WITH=a\nCLOUDFLARE_TUNNEL_TOKEN=\n", mode=0o644)    # empty token: nothing to protect
        self.assertEqual(self.get("WITH")[2], "")
        self.write_cfg("WITH=a\n", mode=0o644)
        self.assertEqual(self.get("WITH")[2], "")


class ModeCheckTest(Base):
    """The portable octal mode check (B22, B34): stat -c %a, then stat -f %Lp, then find -perm; never the text of ls.

    Each variant puts shims first in PATH. A shim logs its call, so the test also proves which form answered. The
    macOS form (`stat -f %Lp`) is simulated: the shim translates it to GNU stat, so that variant is tagged reduced.
    """
    MODES = [0o600, 0o644, 0o640, 0o400, 0o666, 0o4755, 0o1777 & 0o7777]

    def make_shims(self, variant):
        d = os.path.join(self.tmp, "shims-" + variant)
        os.mkdir(d)
        self.log = os.path.join(d, "calls.log")
        real_stat = shutil.which("stat")
        real_find = shutil.which("find")

        def put(name, body):
            path = os.path.join(d, name)
            write_file(path, "#!/bin/sh\nprintf '%s %s\\n' " + name + " \"$*\" >> \"" + self.log + "\"\n" + body)
            os.chmod(path, 0o755)

        if variant == "c_only":
            if not self.gnu_stat():
                self.skipTest("[skipped: this host's stat has no -c form (BSD stat); the c_only variant needs GNU stat]")
            put("stat", 'if [ "$1" = -c ]; then exec %s "$@"; fi\necho "stat: illegal option" >&2\nexit 1\n' % real_stat)
        elif variant == "f_only":
            if self.gnu_stat():   # simulate BSD stat on a GNU host; on a BSD host the real `stat -f %Lp` answers
                put("stat", 'if [ "$1" = -f ] && [ "$2" = %%Lp ]; then exec %s -c %%a "$3"; fi\necho "stat: illegal option" >&2\nexit 1\n' % real_stat)
            else:
                put("stat", 'if [ "$1" = -f ] && [ "$2" = %%Lp ]; then exec %s -f %%Lp "$3"; fi\necho "stat: illegal option" >&2\nexit 1\n' % real_stat)
        else:
            put("stat", 'echo "stat: not available" >&2\nexit 1\n')
        put("find", 'exec %s "$@"\n' % real_find)
        put("ls", 'echo "-rw-------@ 1 user staff 10 Jan  1 00:00 config"\n')
        return d + os.pathsep + os.environ["PATH"]

    def gnu_stat(self):
        p = subprocess.run(["stat", "-c", "%a", self.tmp], capture_output=True, text=True)
        return p.returncode == 0

    def calls(self):
        return slurp(self.log).splitlines() if os.path.exists(self.log) else []

    def check_variant(self, variant, via):
        path = self.make_shims(variant)
        for m in self.MODES:
            self.write_cfg("CLOUDFLARE_TUNNEL_TOKEN=%s\n" % TOKEN, mode=m)
            os.chmod(self.cfg_file, m)
            rc, out, err = (lambda p: (p.returncode, p.stdout, p.stderr))(self.run_h("config", "get", "CLOUDFLARE_TUNNEL_TOKEN", path=path))
            if m == 0o600:
                self.assertEqual((rc, out, err), (0, TOKEN + "\n", ""), (variant, oct(m)))
            else:
                self.assertEqual((rc, out), (1, ""), (variant, oct(m)))
                self.assertIn("mode is %o;" % m, err, (variant, oct(m)))
        calls = self.calls()
        self.assertFalse([c for c in calls if c.startswith("ls ")], "ls must never be called")
        used = {c.split()[0] + " " + (c.split()[1] if len(c.split()) > 1 else "") for c in calls}
        if via == "c":
            self.assertTrue(any(u.startswith("stat -c") for u in used))
            self.assertFalse(any(u.startswith("stat -f") for u in used))
            self.assertFalse(any(u.startswith("find") for u in used))
        elif via == "f":
            self.assertTrue(any(u.startswith("stat -f") for u in used), used)
            self.assertFalse(any(u.startswith("find") for u in used))
        else:
            self.assertTrue(any(u.startswith("find") for u in used), used)

    def test_stat_c_only(self):
        self.check_variant("c_only", "c")

    def test_stat_f_only_simulated_macos_form_reduced(self):
        # tagged reduced: the shim stands in for BSD stat (real macOS is B34's Phase 6 part)
        self.check_variant("f_only", "f")

    def test_neither_stat_form_uses_find_perm(self):
        self.check_variant("neither", "find")

    def test_ls_is_never_parsed_even_when_it_would_say_600_with_an_at_sign(self):
        path = self.make_shims("c_only")
        self.write_cfg("CLOUDFLARE_TUNNEL_TOKEN=%s\n" % TOKEN, mode=0o644)
        rc, out, err = (lambda p: (p.returncode, p.stdout, p.stderr))(self.run_h("config", "get", "CLOUDFLARE_TUNNEL_TOKEN", path=path))
        self.assertEqual((rc, out), (1, ""))        # the fake ls claims -rw-------@; the real mode 644 decides
        self.assertFalse([c for c in self.calls() if c.startswith("ls ")])
        # and the helper source has no call of ls at all
        with open(HELPER) as f:
            code = "\n".join(l.split("#")[0] for l in f.read().splitlines())
        self.assertNotRegex(code, r"(^|[\s;|&(`])ls(\s|$)")

    def test_a_file_with_an_extended_attribute(self):
        self.write_cfg("CLOUDFLARE_TUNNEL_TOKEN=%s\n" % TOKEN, mode=0o600)
        if not hasattr(os, "setxattr"):
            self.skipTest("[skipped: os.setxattr missing; the macOS '@' case stays unverified (B34)]")
        try:
            os.setxattr(self.cfg_file, "user.swarmbox-test", b"1")
        except OSError as e:
            self.skipTest("[skipped: this filesystem refuses user extended attributes: %s; B34 xattr case unverified here]" % e)
        for variant, via in (("c_only", "c"), ("f_only", "f"), ("neither", "find")):
            path = self.make_shims(variant) if not os.path.exists(os.path.join(self.tmp, "shims-" + variant)) else \
                os.path.join(self.tmp, "shims-" + variant) + os.pathsep + os.environ["PATH"]
            self.log = os.path.join(self.tmp, "shims-" + variant, "calls.log")
            self.assertEqual(self.get_with(path), (0, TOKEN + "\n", ""), variant)

    def get_with(self, path):
        p = self.run_h("config", "get", "CLOUDFLARE_TUNNEL_TOKEN", path=path)
        return p.returncode, p.stdout, p.stderr

    def test_find_fallback_reads_special_bits_too(self):
        # 4-digit modes through the find path alone
        path = self.make_shims("neither")
        for m in (0o2755, 0o7777, 0o1600):
            self.write_cfg("CLOUDFLARE_TUNNEL_TOKEN=%s\n" % TOKEN, mode=m)
            os.chmod(self.cfg_file, m)
            rc, out, err = self.get_with(path)
            self.assertEqual((rc, out), (1, ""), oct(m))
            self.assertIn("mode is %o;" % m, err, oct(m))
            os.chmod(self.cfg_file, 0o600)


if __name__ == "__main__":
    unittest.main()
