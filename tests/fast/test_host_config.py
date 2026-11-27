"""The host helper's configuration surface.

container/host/swarmbox-host runs here as a real program with a cleared environment: PATH, a mktemp HOME and the XDG
variables the case sets, nothing else (so a SWARMBOX_* variable of the live box can never leak in). Nothing touches the
real home: a module-level guard compares a listing of the real SwarmBox folders before and after the run.
Run: python3 tests/fast/test_host_config.py
"""
import concurrent.futures
import os
import pty
import select
import shutil
import stat
import subprocess
import sys
import tempfile
import termios
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "support"))
from helpers import ROOT, DEFAULT_NAME, DEFAULT_IMAGE_REPO, pty_answer  # noqa: E402

HELPER = os.path.join(ROOT, "container", "host", "swarmbox-host")
with open(os.path.join(ROOT, "container", "host", "VERSION")) as _f:
    VERSION = _f.read().strip()
TOKEN = "eyJhbGciOiJIUzI1NiJ9.canarytoken-0123456789"
CANARY = "CANARY-VALUE-do-not-print-7f3a"

# key -> (default or None for "unset", a good value, a different good value, [bad values])
KEYS = {
    "WORKSPACE": (None, "/srv/work", "/srv/other", ["a:b", "a\nb"]),
    "HOSTNAME": (DEFAULT_NAME, "devbox", "box2", ["-x", "a b", "a_b", "x" * 64]),
    "TZ": ("local", "Europe/Lisbon", "off", ["a b", "Europe/", "../etc", "9am", "A//B"]),
    "INIT": ("auto", "1", "0", ["yes", "2"]),
    "PORTS": (None, "3000,8080:80", "127.0.0.1:9000:3000", ["abc", "3000,", "99999", "1:2:3:4", "0", ",1", "1,,2", "1 2"]),
    "HOST_ACCESS": ("0", "1", "0", ["yes", "2", "true"]),
    "BROWSER_URL": (None, "9222", "host.example:1234", ["a b", "ftp://x", "99999", "nohostport", ":1234"]),
    "WEB": ("1", "0", "1", ["yes", "2"]),
    "WEB_PORT": ("7681", "8000", "8001", ["0", "65536", "abc", "-1"]),
    "WITH": (None, "claude,gcloud", "claude", ["Claude", "a b", "a,,b", ",a", "a,"]),
    "AGENT": (None, "claude", "opencode", ["a,b", "A B", "yolo"]),
    "YOLO": ("1", "0", "1", ["yes", "2"]),
    "ENV_KEYS": (None, "ANTHROPIC_API_KEY,GEMINI_API_KEY", "FOO", ["1BAD", "A,SWARMBOX_CLOUDFLARE_X", "a b", "A-B"]),
    "voice.language": ("auto", "pt", "en", ["pt-br", "P", "abcd", "x1", "a b"]),
    "voice.stt.model": ("small", "medium", "large-v3", ["small.en", "Small", "-x", "a b", ".x", "a/b"]),
    "voice.stt.vocabulary": (None, "kubectl, podman, tmux", "SwarmBox", ["x" * 501]),
    "voice.web": ("1", "0", "1", ["yes", "2"]),
    "voice.topic": ("goal", "speech", "voice.goals", ["Goal", "-x", "a b", "a/b", "x" * 64, "a\nb"]),
    "sysop.topic": ("goal", "ops", "a-b_c.d", ["Goal", "-x", "a b", "a/b", "x" * 64, ".x"]),
    "sysop.group": ("sysop", "ops2", "g-1", ["Sysop", "-x", "a b", "a/b", "x" * 64, "_x"]),
    "sysop.brain": ("auto", "claude", "gemini -p {mcp_config}", ["a\nb", "foo bar", "gemini -p", "-x", "Claude"]),
    "sysop.model": ("auto", "haiku", "claude-sonnet-4-5", ["a b", "-x", "a;b", "$(x)"]),
    "sysop.autonomy": ("full-auto", "auto", "confirm-all", ["yes", "Auto", "confirm", "full", "fullauto"]),
    "sysop.autoname": ("1", "0", "1", ["yes", "2", "true"]),
    "sysop.autocontext": ("1", "0", "1", ["yes", "2", "true"]),
    "sysop.countdown": ("4", "0", "30", ["31", "-1", "1.5", "abc", "04", "+3"]),
    "sysop.max_steps": ("0", "0", "500", ["-1", "501", "x", "010"]),
    "sysop.max_seconds": ("0", "0", "3600", ["9", "3601", "1e3", "-1"]),
    "IMAGE": (None, "localhost:5000/sb:2.0.1", "swarmbox:dev", ["a b", "x\ty"]),
}


def ENVNAME(key):
    return "SWARMBOX_" + key.upper().replace(".", "_")


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

    def _par(self, fn, items, max_workers=12):
        items = list(items)
        if len(items) <= 1:
            return [fn(x) for x in items]
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(max_workers, len(items))) as pool:
            return list(pool.map(fn, items))

    def _iso_home(self, tag):
        h = os.path.join(self.tmp, "h-" + tag)
        os.makedirs(h, exist_ok=True)
        return h, os.path.join(h, ".config", "swarmbox", "config")


class VersionTest(Base):
    def test_version_prints_the_version_of_the_script_and_it_is_the_one_of_the_version_file(self):
        p = self.run_h("version")
        self.assertEqual((p.returncode, p.stdout, p.stderr), (0, VERSION + "\n", ""))
        with open(HELPER) as f:
            self.assertIn("\nSCRIPT_VERSION=%s\n" % VERSION, f.read())

    def test_support_files_of_another_version_give_one_short_warning_once(self):
        with open(os.path.join(ROOT, "container", "host", "DEFAULTS")) as f:
            h = self.copied_helper(f.read(), version="9.8.7")
        p = self.run_h("config", "get", "WEB_PORT", helper=h)
        self.assertEqual((p.returncode, p.stdout), (0, "7681\n"))
        self.assertEqual(p.stderr.count("\n"), 1, p.stderr)
        self.assertIn("this script is %s but the image files are 9.8.7" % VERSION, p.stderr)
        self.assertIn("swarmbox update", p.stderr)
        p = self.run_h("config", "get", "WEB_PORT", helper=h)
        self.assertEqual((p.returncode, p.stderr), (0, ""))

    def test_a_missing_support_file_is_exit_3_with_the_way_out(self):
        d = os.path.join(self.tmp, "bin")
        os.mkdir(d)
        shutil.copy(HELPER, os.path.join(d, "swarmbox"))
        os.chmod(os.path.join(d, "swarmbox"), 0o755)
        p = self.run_h("config", "list", helper=os.path.join(d, "swarmbox"), env={"XDG_DATA_HOME": os.path.join(self.tmp, "nodata")})
        self.assertEqual(p.returncode, 3)
        self.assertIn("the support files are missing", p.stderr)
        self.assertIn("swarmbox update", p.stderr)
        p = self.run_h("version", helper=os.path.join(d, "swarmbox"), env={"XDG_DATA_HOME": os.path.join(self.tmp, "nodata")})
        self.assertEqual((p.returncode, p.stdout), (0, VERSION + "\n"))

    def copied_helper(self, defaults_text, version="9.8.7"):
        d = os.path.join(self.tmp, "copy")
        os.mkdir(d)
        shutil.copy(HELPER, d)
        os.chmod(os.path.join(d, "swarmbox-host"), 0o755)
        write_file(os.path.join(d, "VERSION"), version + "\n")
        if defaults_text is not None:
            write_file(os.path.join(d, "DEFAULTS"), defaults_text)
        return os.path.join(d, "swarmbox-host")

    def test_the_default_names_come_from_the_defaults_file(self):
        """Flipping the two lines of DEFAULTS flips the box name, the hostname key and the image of a copied helper."""
        h = self.copied_helper("SWARMBOX_DEFAULT_NAME=flipped\nSWARMBOX_DEFAULT_IMAGE_REPO='ghcr.io/<org>/flipped'\n")
        cases = (("NAME", "flipped"), ("HOSTNAME", "flipped"), ("IMAGE", "ghcr.io/<org>/flipped:" + VERSION))
        ps = self._par(lambda kw: self.run_h("config", "get", kw[0], helper=h), cases)
        for (key, want), p in zip(cases, ps):
            self.assertEqual((p.returncode, p.stdout.strip()), (0, want), (key, p.stderr))

class DefaultsAndPrecedenceTest(Base):
    def default(self, key):
        d = KEYS[key][0]
        if key == "WORKSPACE":
            return os.path.join(self.home, "swarmbox")
        if key == "IMAGE":
            return (DEFAULT_IMAGE_REPO + ":") + VERSION
        return d

    def test_every_key_default_get(self):
        all_keys = list(KEYS) + ["NAME", "CLOUDFLARE_TUNNEL_TOKEN"]
        res = dict(zip(all_keys, self._par(self.get, all_keys)))
        for key in KEYS:
            rc, out, err = res[key]
            want = self.default(key)
            if key == "IMAGE":
                want = (DEFAULT_IMAGE_REPO + ":") + VERSION
            if want is None:
                self.assertEqual((rc, out), (1, ""), key)
            else:
                self.assertEqual((rc, out), (0, want + "\n"), key)
            self.assertEqual(err, "", key)
        self.assertEqual(res["NAME"][:2], (0, DEFAULT_NAME + "\n"))
        self.assertEqual(res["CLOUDFLARE_TUNNEL_TOKEN"][:2], (1, ""))

    def test_file_value_then_env_override_for_every_key(self):
        def check_one(item):
            i, (key, (_, good, other, _bad)) = item
            h, cf = self._iso_home("ov-%d" % i)
            self.write_cfg("%s=%s\n" % (key, good), file=cf)
            r1 = self.get(key, env={"HOME": h})[:2]
            r2 = self.get(key, env={"HOME": h, ENVNAME(key): other})[:2]
            r3 = self.get(key, env={"HOME": h, ENVNAME(key): ""})[:2]
            return key, good, other, r1, r2, r3
        for key, good, other, r1, r2, r3 in self._par(check_one, enumerate(KEYS.items())):
            self.assertEqual(r1, (0, good + "\n"), key)
            self.assertEqual(r2, (0, other + "\n"), key)
            # an empty environment value does not override
            self.assertEqual(r3, (0, good + "\n"), key)

class GrammarTest(Base):
    def test_values_are_literal(self):
        self.write_cfg("WORKSPACE=/srv/my work dir\nIMAGE=a=b\nHOSTNAME=  padded \t \nTZ=Europe/Lisbon\r\n")
        r_ws, r_im, r_hn, r_tz = self._par(self.get, ("WORKSPACE", "IMAGE", "HOSTNAME", "TZ"))
        self.assertEqual(r_ws[:2], (0, "/srv/my work dir\n"))
        self.assertEqual(r_im[:2], (0, "a=b\n"))          # '=' inside the value
        self.assertEqual(r_hn[:2], (0, "padded\n"))    # blanks trimmed
        self.assertEqual(r_tz[:2], (0, "Europe/Lisbon\n"))   # CRLF file
        self.write_cfg("WORKSPACE=$HOME/x \"q\" 'r' \\n ${A}\n")
        self.assertEqual(self.get("WORKSPACE")[:2], (0, "$HOME/x \"q\" 'r' \\n ${A}\n"))

    def test_name_comes_only_from_the_environment(self):
        self.assertEqual(self.get("NAME", env={"SWARMBOX_NAME": "other"})[:2], (0, "other\n"))
        p = self.run_h("config", "set", "NAME", "x")
        self.assertEqual(p.returncode, 2)
        self.assertIn("SWARMBOX_NAME", p.stderr)
        self.assertFalse(os.path.exists(self.cfg_file))

    def test_help_prints_the_user_commands_on_stdout_and_exits_0(self):
        words = ("help", "--help", "-h", "config")
        ps = self._par(self.run_h, words)
        for word, p in zip(words[:3], ps[:3]):
            self.assertEqual(p.returncode, 0, word)
            self.assertIn("usage: swarmbox [--plain]", p.stdout)
            self.assertNotIn("swarmbox-host", p.stdout)
        self.assertEqual(ps[3].returncode, 2)

    def test_invalid_box_names_exit_2(self):
        names = ("../x", "a/b", ".hidden", "a b", "config", "-x", "x;y")
        ps = self._par(lambda n: self.run_h("config", "get", "WITH", env={"SWARMBOX_NAME": n}), names)
        for n, p in zip(names, ps):
            self.assertEqual(p.returncode, 2, n)
            self.assertIn("SWARMBOX_NAME", p.stderr)
        self.assertFalse(os.path.exists(os.path.join(self.home, ".config")))


class SetTest(Base):
    def test_set_every_key_roundtrip_and_file_mode(self):
        def check_one(item):
            i, (key, (_, good, other, _bad)) = item
            h, cf = self._iso_home("set-%d" % i)
            e = {"HOME": h}
            p1 = self.run_h("config", "set", key, good, env=e)
            g1 = self.get(key, env=e)[:2]
            p2 = self.run_h("config", "set", key, other, env=e)
            g2 = self.get(key, env=e)[:2]
            m = self.mode(cf)
            return key, good, other, p1, g1, p2, g2, m
        for key, good, other, p1, g1, p2, g2, m in self._par(check_one, enumerate(KEYS.items())):
            self.assertEqual((p1.returncode, p1.stdout, p1.stderr), (0, "", ""), (key, p1.stderr))
            self.assertEqual(g1, (0, good + "\n"), key)
            self.assertEqual(p2.returncode, 0, key)
            self.assertEqual(g2, (0, other + "\n"), key)
            self.assertEqual(m, 0o600, key)

    def test_rejections_name_the_key_and_the_rule_and_write_nothing(self):
        def check_one(item):
            i, (key, (_, good, _o, bad)) = item
            h, cf = self._iso_home("rej-%d" % i)
            self.write_cfg("# keep\n%s=%s\n" % (key, good), file=cf)
            before = slurp(cf)
            out = []
            for v in bad:
                p = self.run_h("config", "set", key, v, env={"HOME": h})
                out.append((v, p, slurp(cf)))
            return key, before, out
        for key, before, out in self._par(check_one, enumerate(KEYS.items())):
            for v, p, after in out:
                self.assertEqual(p.returncode, 2, (key, v))
                self.assertEqual(p.stdout, "")
                self.assertIn(key, p.stderr)
                self.assertRegex(p.stderr, r"must|cannot", (key, v))
                self.assertEqual(after, before, (key, v))


class UnsetAndPathTest(Base):
    """config unset KEY removes the key from the file (the default, or the environment, applies again); config path prints the file."""

    def test_unset_every_key_brings_back_the_default_and_keeps_the_rest(self):
        def check_one(item):
            i, (key, (_d, good, _o, _b)) = item
            h, cf = self._iso_home("uns-%d" % i)
            e = {"HOME": h}
            baseline = self.get(key, env=e)[:2]                       # what the key resolves to with no file: its default
            self.write_cfg("# my notes\nWEB=0\n%s=%s\n" % (key, good) if key != "WEB" else "# my notes\nYOLO=0\nWEB=0\n", file=cf)
            p = self.run_h("config", "unset", key, env=e)
            text = slurp(cf)
            m = self.mode(cf)
            after = self.get(key, env=e)[:2]
            return key, baseline, p, text, m, after
        for key, baseline, p, text, m, after in self._par(check_one, enumerate(KEYS.items())):
            self.assertEqual((p.returncode, p.stdout), (0, ""), (key, p.stderr))
            self.assertIn("removed %s" % key, p.stderr)
            self.assertNotRegex(text, r"(?m)^%s=" % key.replace(".", r"\."), key)
            self.assertIn("# my notes\n", text, key)
            self.assertIn("YOLO=0\n" if key == "WEB" else "WEB=0\n", text, key)
            self.assertEqual(m, 0o600, key)
            self.assertEqual(after, baseline, key)

    def test_unset_says_when_the_environment_still_sets_the_key(self):
        self.write_cfg("WEB_PORT=8000\n")
        p = self.run_h("config", "unset", "WEB_PORT", env={"SWARMBOX_WEB_PORT": "8100"})
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("SWARMBOX_WEB_PORT in the environment still sets it", p.stderr)
        self.assertEqual(slurp(self.cfg_file).count("WEB_PORT="), 0)

    def test_unset_of_a_key_not_in_the_file_changes_nothing(self):
        p = self.run_h("config", "unset", "WEB_PORT")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("nothing to remove", p.stderr)
        self.assertFalse(os.path.exists(self.cfg_file), "no file is created")
        self.write_cfg("# keep\nWEB=0\n")
        before = slurp(self.cfg_file)
        self.assertEqual(self.run_h("config", "unset", "TZ").returncode, 0)
        self.assertEqual(slurp(self.cfg_file), before)

    def test_unset_cleans_stale_and_unknown_keys_of_the_file(self):
        self.write_cfg("OLD_KEY=tmux\nsysop.gone=off\nTYPO_KEY=1\nWEB=0\n")
        for key in ("OLD_KEY", "sysop.gone", "TYPO_KEY"):
            p = self.run_h("config", "unset", key)
            self.assertEqual(p.returncode, 0, (key, p.stderr))
        self.assertEqual(slurp(self.cfg_file), "WEB=0\n")
        p = self.run_h("config", "list")
        self.assertNotIn("ignoring", p.stderr)

    def test_unset_refuses_name_and_unknown_keys(self):
        argss = (("unset", "NAME"), ("unset", "NOPE"), ("unset", "web_port"), ("unset",), ("unset", "WEB", "PORT"))
        ps = self._par(lambda a: self.run_h("config", *a), argss)
        for a, p in zip(argss[:3], ps[:3]):
            self.assertEqual(p.returncode, 2, a[-1])
            self.assertEqual(p.stdout, "")
        self.assertEqual(ps[3].returncode, 2)
        self.assertEqual(ps[4].returncode, 2)

    def test_unset_removes_the_tunnel_token(self):
        self.write_cfg("CLOUDFLARE_TUNNEL_TOKEN=%s\nWEB=1\n" % TOKEN)
        p = self.run_h("config", "unset", "CLOUDFLARE_TUNNEL_TOKEN")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertNotIn(TOKEN, p.stdout + p.stderr)
        self.assertNotIn(TOKEN, slurp(self.cfg_file))
        self.assertEqual(self.get("CLOUDFLARE_TUNNEL_TOKEN")[0], 1)

    def test_path_prints_the_file_with_or_without_it(self):
        p = self.run_h("config", "path")
        self.assertEqual((p.returncode, p.stdout), (0, self.cfg_file + "\n"))
        self.assertIn("does not exist yet", p.stderr)
        self.write_cfg("WEB=0\n")
        p = self.run_h("config", "path")
        self.assertEqual((p.returncode, p.stdout, p.stderr), (0, self.cfg_file + "\n", ""))
        xdg = os.path.join(self.tmp, "xdg")
        p = self.run_h("config", "path", env={"XDG_CONFIG_HOME": xdg})
        self.assertEqual(p.stdout, os.path.join(xdg, "swarmbox", "config") + "\n")
        p = self.run_h("config", "path", env={"SWARMBOX_NAME": "work"})
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("work", p.stdout)
        self.assertEqual(self.run_h("config", "path", "extra").returncode, 2)


class SeedTest(Base):
    def test_creates_the_file_once_with_the_given_seeds(self):
        p = self.run_h("config", "seed", "--with", "claude,gcloud", "--workspace", "/srv/ws", "--image", "x/y:1.2.3")
        self.assertEqual((p.returncode, p.stdout), (0, ""))
        self.assertEqual(self.get("WITH")[1], "claude,gcloud\n")
        self.assertEqual(self.get("WORKSPACE")[1], "/srv/ws\n")
        self.assertEqual(self.get("IMAGE")[1], "x/y:1.2.3\n")
        self.assertEqual(self.mode(), 0o600)
        self.assertIn("/srv/ws", p.stderr)

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

class TokenTest(Base):
    def set_token(self, token=TOKEN, extra_env=None, path=None):
        argv = [HELPER, "config", "set", "CLOUDFLARE_TUNNEL_TOKEN"]
        env = self.env(extra_env, path)
        pid, fd = pty.fork()
        if pid == 0:
            os.execve(argv[0], argv, env)
        out = b""
        sent = False
        end = time.monotonic() + 20
        try:
            while time.monotonic() < end:
                if select.select([fd], [], [], 0.01)[0]:
                    try:
                        chunk = os.read(fd, 4096)
                    except OSError:
                        break
                    if not chunk:
                        break
                    out += chunk
                if not sent and b"hidden" in out:
                    # wait deterministically for `stty -echo` to take effect instead of a blind 0.3s sleep
                    echo_end = time.monotonic() + 1.0
                    while time.monotonic() < echo_end:
                        try:
                            if not (termios.tcgetattr(fd)[3] & termios.ECHO):
                                break
                        except termios.error:
                            break
                        time.sleep(0.002)
                    os.write(fd, token.encode() + b"\n")
                    sent = True
            _, status = os.waitpid(pid, 0)
        finally:
            try:
                os.close(fd)
            except OSError:
                pass
        return os.waitstatus_to_exitcode(status), out.decode(errors="replace")

    def test_set_reads_the_terminal_without_echo(self):
        rc, shown = self.set_token()
        self.assertEqual(rc, 0, shown)
        self.assertNotIn(TOKEN, shown)                      # typed with echo off: the terminal never showed it
        self.assertIn("CLOUDFLARE_TUNNEL_TOKEN=" + TOKEN + "\n", slurp(self.cfg_file))
        self.assertEqual(self.mode(), 0o600)
        self.assertEqual(self.get("CLOUDFLARE_TUNNEL_TOKEN")[:2], (0, TOKEN + "\n"))

    def test_value_on_the_command_line_is_refused(self):
        p = self.run_h("config", "set", "CLOUDFLARE_TUNNEL_TOKEN", TOKEN)
        self.assertEqual(p.returncode, 2)
        self.assertNotIn(TOKEN, p.stdout + p.stderr)
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

class ModeCheckTest(Base):
    """The portable octal mode check: stat -c %a, then stat -f %Lp, then find -perm; never the text of ls.

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

    def test_a_file_with_an_extended_attribute(self):
        self.write_cfg("CLOUDFLARE_TUNNEL_TOKEN=%s\n" % TOKEN, mode=0o600)
        if not hasattr(os, "setxattr"):
            self.skipTest("[skipped: os.setxattr missing; the macOS '@' case stays unverified]")
        try:
            os.setxattr(self.cfg_file, "user.swarmbox-test", b"1")
        except OSError as e:
            self.skipTest("[skipped: this filesystem refuses user extended attributes: %s; xattr case unverified here]" % e)
        for variant, via in (("c_only", "c"), ("f_only", "f"), ("neither", "find")):
            path = self.make_shims(variant) if not os.path.exists(os.path.join(self.tmp, "shims-" + variant)) else \
                os.path.join(self.tmp, "shims-" + variant) + os.pathsep + os.environ["PATH"]
            self.log = os.path.join(self.tmp, "shims-" + variant, "calls.log")
            self.assertEqual(self.get_with(path), (0, TOKEN + "\n", ""), variant)

    def get_with(self, path):
        p = self.run_h("config", "get", "CLOUDFLARE_TUNNEL_TOKEN", path=path)
        return p.returncode, p.stdout, p.stderr


from host_support import CreateFlagsBase  # noqa: E402


class SysopFlagsTest(CreateFlagsBase):
    """The sysop.* keys reach the box as SWARMBOX_SYSOP_* only when they differ from the default (a box that never set one keeps its fingerprint)."""

    def sysop(self, flags):
        return [flags[i + 1] for i, f in enumerate(flags) if f == "-e" and flags[i + 1].startswith("SWARMBOX_SYSOP_")]

    def test_defaults_and_explicit_defaults_pass_nothing(self):
        os.makedirs(self.ws, exist_ok=True)
        cfg = "sysop.brain=auto\nsysop.model=auto\nsysop.autonomy=full-auto\nsysop.countdown=4\nsysop.max_steps=0\nsysop.max_seconds=0\n"
        h2 = os.path.join(self.tmp, "h-exp")
        cf2 = os.path.join(h2, ".config", "swarmbox", "config")
        os.makedirs(os.path.dirname(cf2), exist_ok=True)
        with open(cf2, "w") as fh:
            fh.write(cfg)
        os.chmod(cf2, 0o600)
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            base, dflags, eflags, efp = list(pool.map(lambda fn: fn(), (
                self.fp, self.flags,
                lambda: self.flags(env={"HOME": h2}), lambda: self.fp(env={"HOME": h2}),
            )))
        self.assertEqual(self.sysop(dflags), [])
        self.assertEqual(self.sysop(eflags), [])
        self.assertEqual(efp, base)

    def test_the_old_defaults_claude_and_sonnet_are_now_choices_that_are_passed(self):
        # auto is the brain and the model an agent of the box declares (Claude Code's: claude, sonnet); naming them chooses them
        self.assertEqual(self.sysop(self.flags(cfg="sysop.brain=claude\nsysop.model=sonnet\n")),
                         ["SWARMBOX_SYSOP_BRAIN=claude", "SWARMBOX_SYSOP_MODEL=sonnet"])

    def test_the_old_default_auto_is_now_a_choice_that_is_passed(self):
        self.assertEqual(self.sysop(self.flags(cfg="sysop.autonomy=auto\n")), ["SWARMBOX_SYSOP_AUTONOMY=auto"])

    def test_other_values_pass_and_change_the_fingerprint(self):
        os.makedirs(self.ws, exist_ok=True)
        cfg = ("sysop.brain=gemini -p {mcp_config} 'x'\nsysop.model=haiku\nsysop.autonomy=confirm-risky\nsysop.countdown=0\n"
               "sysop.max_steps=5\nsysop.max_seconds=60\n")
        h2 = os.path.join(self.tmp, "h-oth")
        cf2 = os.path.join(h2, ".config", "swarmbox", "config")
        os.makedirs(os.path.dirname(cf2), exist_ok=True)
        with open(cf2, "w") as fh:
            fh.write(cfg)
        os.chmod(cf2, 0o600)
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            base, oflags, ofp = list(pool.map(lambda fn: fn(), (
                self.fp, lambda: self.flags(env={"HOME": h2}), lambda: self.fp(env={"HOME": h2}),
            )))
        self.assertEqual(self.sysop(oflags), [
            "SWARMBOX_SYSOP_BRAIN=gemini -p {mcp_config} 'x'", "SWARMBOX_SYSOP_MODEL=haiku", "SWARMBOX_SYSOP_AUTONOMY=confirm-risky",
            "SWARMBOX_SYSOP_COUNTDOWN=0", "SWARMBOX_SYSOP_MAX_STEPS=5", "SWARMBOX_SYSOP_MAX_SECONDS=60"])
        self.assertNotEqual(ofp, base)

    def test_an_invalid_value_in_the_file_stops_create_flags(self):
        self.assertEqual(self.cf(cfg="sysop.autonomy=yolo\n").returncode, 2)


if __name__ == "__main__":
    unittest.main()
