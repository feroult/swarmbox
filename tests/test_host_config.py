"""The host helper's configuration surface.

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
from helpers import ROOT, DEFAULT_NAME, DEFAULT_IMAGE_REPO  # noqa: E402

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

    def copied_helper(self, defaults_text):
        d = os.path.join(self.tmp, "copy")
        os.mkdir(d)
        shutil.copy(HELPER, d)
        os.chmod(os.path.join(d, "swarmbox-host"), 0o755)
        write_file(os.path.join(d, "VERSION"), "9.8.7\n")
        if defaults_text is not None:
            write_file(os.path.join(d, "DEFAULTS"), defaults_text)
        return os.path.join(d, "swarmbox-host")

    def test_the_default_names_come_from_the_defaults_file(self):
        """Flipping the two lines of DEFAULTS flips the box name, the hostname key and the image of a copied helper."""
        h = self.copied_helper("SWARMBOX_DEFAULT_NAME=flipped\nSWARMBOX_DEFAULT_IMAGE_REPO='ghcr.io/<org>/flipped'\n")
        for key, want in (("NAME", "flipped"), ("HOSTNAME", "flipped"), ("IMAGE", "ghcr.io/<org>/flipped:9.8.7")):
            p = self.run_h("config", "get", key, helper=h)
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
        for key in KEYS:
            rc, out, err = self.get(key)
            want = self.default(key)
            if key == "IMAGE":
                want = (DEFAULT_IMAGE_REPO + ":") + VERSION
            if want is None:
                self.assertEqual((rc, out), (1, ""), key)
            else:
                self.assertEqual((rc, out), (0, want + "\n"), key)
            self.assertEqual(err, "", key)
        self.assertEqual(self.get("NAME")[:2], (0, DEFAULT_NAME + "\n"))
        self.assertEqual(self.get("CLOUDFLARE_TUNNEL_TOKEN")[:2], (1, ""))

    def test_file_value_then_env_override_for_every_key(self):
        for key, (_, good, other, _bad) in KEYS.items():
            self.write_cfg("%s=%s\n" % (key, good))
            self.assertEqual(self.get(key)[:2], (0, good + "\n"), key)
            self.assertEqual(self.get(key, env={"SWARMBOX_" + key: other})[:2], (0, other + "\n"), key)
            # an empty environment value does not override
            self.assertEqual(self.get(key, env={"SWARMBOX_" + key: ""})[:2], (0, good + "\n"), key)

class GrammarTest(Base):
    def test_values_are_literal(self):
        self.write_cfg("WORKSPACE=/srv/my work dir\nIMAGE=a=b\nHOSTNAME=  padded \t \nTZ=Europe/Lisbon\r\n")
        self.assertEqual(self.get("WORKSPACE")[:2], (0, "/srv/my work dir\n"))
        self.assertEqual(self.get("IMAGE")[:2], (0, "a=b\n"))          # '=' inside the value
        self.assertEqual(self.get("HOSTNAME")[:2], (0, "padded\n"))    # blanks trimmed
        self.assertEqual(self.get("TZ")[:2], (0, "Europe/Lisbon\n"))   # CRLF file
        self.write_cfg("WORKSPACE=$HOME/x \"q\" 'r' \\n ${A}\n")
        self.assertEqual(self.get("WORKSPACE")[:2], (0, "$HOME/x \"q\" 'r' \\n ${A}\n"))

    def test_name_comes_only_from_the_environment(self):
        self.assertEqual(self.get("NAME", env={"SWARMBOX_NAME": "other"})[:2], (0, "other\n"))
        p = self.run_h("config", "set", "NAME", "x")
        self.assertEqual(p.returncode, 2)
        self.assertIn("SWARMBOX_NAME", p.stderr)
        self.assertFalse(os.path.exists(self.cfg_file))

    def test_help_prints_the_user_commands_on_stdout_and_exits_0(self):
        for word in ("help", "--help", "-h"):
            p = self.run_h(word)
            self.assertEqual(p.returncode, 0, word)
            self.assertIn("usage: swarmbox [--plain]", p.stdout)
            self.assertNotIn("swarmbox-host", p.stdout)
        self.assertEqual(self.run_h("config").returncode, 2)

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

if __name__ == "__main__":
    unittest.main()
