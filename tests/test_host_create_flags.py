"""Slice 3.2: `create-flags`, `fingerprint` and the workspace checks of the host helper (design 3.5, 3.6, 3.7.2, 3.7.4, 7, 8.2, 8.3).

The helper runs as a real program, copied with a fixture `tool-ports` into a mktemp folder (the repository has none: the
image build writes it), with a cleared environment: PATH, a mktemp HOME and the variables a case sets. Nothing calls
Podman. Nothing touches the real home or a Windows drive: the WSL probe and the OS are test-overridable
(SWARMBOX_TEST_PROC_VERSION, SWARMBOX_TEST_OS), the local time file is SWARMBOX_LOCALTIME_FILE.
Run: python3 tests/test_host_create_flags.py
"""
import hashlib
import itertools
import os
import random
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import ROOT, DEFAULT_NAME, DEFAULT_IMAGE_REPO, DEFAULT_VOLUME  # noqa: E402

HELPER_SRC = os.path.join(ROOT, "container", "host", "swarmbox-host")
VERSION_SRC = os.path.join(ROOT, "container", "host", "VERSION")
DEFAULTS_SRC = os.path.join(ROOT, "container", "host", "DEFAULTS")
FIXTURES = os.path.join(ROOT, "tests", "fixtures")
with open(VERSION_SRC) as _f:
    VERSION = _f.read().strip()
CANARY = "CANARY-VALUE-do-not-print-7f3a"
TOKEN = "eyJhbGciOiJIUzI1NiJ9.canarytoken-0123456789"
WSL_VERSION = "Linux version 5.15.153.1-microsoft-standard-WSL2 (root@x) (gcc 11.2.0) #1 SMP"
PLAIN_VERSION = "Linux version 6.1.0-18-amd64 (debian-kernel@lists.debian.org) (gcc-12 (Debian 12.2.0-14)) #1 SMP"
D34 = ("swarmbox: workspace %s is on a Windows drive; WSL2 is supported only with the workspace on the Linux "
       "filesystem (for example ~/swarmbox).")


def sha256(text):
    return hashlib.sha256(text.encode()).hexdigest()


def env_hash(pairs):
    """pairs: list of (name, value or None). Design 7.1: NAME=value for a set name, NAME for an unset one, sorted."""
    lines = sorted(n if v is None else "%s=%s" % (n, v) for n, v in pairs)
    return sha256("".join(l + "\n" for l in lines))


def fingerprint(lines, ehash):
    all_lines = sorted(list(lines) + ["env-hash=" + ehash])
    return sha256("".join(l + "\n" for l in all_lines))


def pairs_of(args):
    """The flag/value pairs of an argument list: [(flag, value)] for flags that take a value on the next line."""
    out = []
    i = 0
    takes = {"-p", "-v", "-e", "--hostname", "--tmpfs", "--device", "--security-opt", "--label", "--add-host"}
    while i < len(args):
        if args[i] in takes:
            out.append((args[i], args[i + 1]))
            i += 2
        else:
            out.append((args[i], None))
            i += 1
    return out


def values(args, flag):
    return [v for f, v in pairs_of(args) if f == flag]


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.real_home = os.path.realpath(os.path.expanduser("~"))

    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="swarmbox-test-cflags."))
        self.addCleanup(self._cleanup)
        self.home = os.path.join(self.tmp, "home")
        os.mkdir(self.home)
        self.assertNotEqual(os.path.realpath(self.home), self.real_home)
        self.ws = os.path.join(self.tmp, "ws")
        self.hdir = os.path.join(self.tmp, "helper")
        self.localtime = os.path.join(self.tmp, "localtime")
        self.procversion = os.path.join(self.tmp, "proc-version")
        for p in (self.localtime,):
            open(p, "w").close()
        with open(self.procversion, "w") as f:
            f.write(PLAIN_VERSION + "\n")
        self.make_helper("")
        self.cfgroot = os.path.join(self.home, ".config", "swarmbox")

    def _cleanup(self):
        for d, dirs, _files in os.walk(self.tmp):
            for n in dirs:
                try:
                    os.chmod(os.path.join(d, n), 0o700)
                except OSError:
                    pass
        shutil.rmtree(self.tmp, True)

    def make_helper(self, tool_ports, version=True):
        shutil.rmtree(self.hdir, True)
        os.makedirs(self.hdir)
        shutil.copy(HELPER_SRC, os.path.join(self.hdir, "swarmbox-host"))
        os.chmod(os.path.join(self.hdir, "swarmbox-host"), 0o755)
        if version:
            shutil.copy(VERSION_SRC, os.path.join(self.hdir, "VERSION"))
            shutil.copy(DEFAULTS_SRC, os.path.join(self.hdir, "DEFAULTS"))
        if tool_ports is not None:
            with open(os.path.join(self.hdir, "tool-ports"), "w") as f:
                f.write(tool_ports)

    @property
    def helper(self):
        return os.path.join(self.hdir, "swarmbox-host")

    def base_env(self):
        return {
            "PATH": os.environ["PATH"], "HOME": self.home,
            "SWARMBOX_WORKSPACE": self.ws, "SWARMBOX_INIT": "0",
            "SWARMBOX_LOCALTIME_FILE": self.localtime, "SWARMBOX_TEST_PROC_VERSION": self.procversion,
            "SWARMBOX_TEST_OS": "Linux",
        }

    def run_h(self, *args, env=None, drop=(), cfg=None, path=None, shell=None, cwd=None):
        e = self.base_env()
        e.update(env or {})
        for k in drop:
            e.pop(k, None)
        if path is not None:
            e["PATH"] = path
        if cfg is not None:
            name = (env or {}).get("SWARMBOX_NAME", DEFAULT_NAME)
            folder = self.cfgroot if name == DEFAULT_NAME else os.path.join(self.cfgroot, name)
            os.makedirs(folder, exist_ok=True)
            f = os.path.join(folder, "config")
            with open(f, "w") as fh:
                fh.write(cfg)
            os.chmod(f, 0o600)
        argv = (shell or []) + [self.helper, *args]
        return subprocess.run(argv, env=e, capture_output=True, text=True, input="", cwd=cwd or self.tmp, timeout=60)

    def cf(self, env=None, cfg=None, args=(), **kw):
        return self.run_h("create-flags", *args, env=env, cfg=cfg, **kw)

    def flags(self, env=None, cfg=None, args=(), **kw):
        p = self.cf(env=env, cfg=cfg, args=args, **kw)
        self.assertEqual(p.returncode, 0, p.stderr)
        return p.stdout.split("\n")[:-1] if p.stdout else []

    def fp(self, env=None, cfg=None, args=(), **kw):
        p = self.run_h("fingerprint", *args, env=env, cfg=cfg, **kw)
        self.assertEqual(p.returncode, 0, p.stderr)
        return p.stdout.strip()

    # the expected fingerprint lines of the default configuration; `over` replaces some of them
    def fp_lines(self, over=None):
        d = {
            "AGENT": "", "BROWSER_URL": "", "ENV_KEYS": "", "HOSTNAME": DEFAULT_NAME, "HOST_ACCESS": "0",
            "IMAGE": (DEFAULT_IMAGE_REPO + ":%s") % VERSION, "INIT": "0", "NAME": DEFAULT_NAME, "PORTS": "",
            "TZ": "local", "WEB": "1", "WEB_PORT": "7681", "WITH": "", "WORKSPACE": self.ws, "YOLO": "1",
        }
        d.update(over or {})
        return ["%s=%s" % kv for kv in d.items()]


# ============================================================================ the flag set: golden files

class GoldenTest(Base):
    def golden(self, name, subs):
        with open(os.path.join(FIXTURES, name)) as f:
            text = f.read()
        subs = dict(subs, **{"@NAME@": DEFAULT_NAME, "@IMAGE_REPO@": DEFAULT_IMAGE_REPO})   # D40: from container/host/DEFAULTS
        for k, v in subs.items():
            text = text.replace(k, v)
        return text.split("\n")[:-1]

    def test_default_flag_set_equals_the_golden_file(self):
        out = self.flags()
        ehash = env_hash([])
        fpr = fingerprint(self.fp_lines(), ehash)
        want = self.golden("create-flags.default.golden", {"@WS@": self.ws, "@VERSION@": VERSION, "@ENVHASH@": ehash, "@FP@": fpr})
        self.assertEqual(out, want)

    def test_full_flag_set_equals_the_golden_file(self):
        self.make_helper("clasp\t43323\nclasp\t43324\ngcloud\t8085\n")
        cfg = ("HOSTNAME=devbox\nTZ=Europe/Lisbon\nPORTS=3000,8080:80,0.0.0.0:9000:9000\nHOST_ACCESS=1\nBROWSER_URL=9222\n"
               "WEB_PORT=8000\nWITH=clasp,claude\nAGENT=claude\nYOLO=0\nENV_KEYS=ALPHA_KEY,BETA_KEY,GONE_KEY\nIMAGE=localhost:5000/sb:2.0.1\n")
        out = self.flags(cfg=cfg, env={"SWARMBOX_INIT": "1", "SWARMBOX_NAME": "second", "ALPHA_KEY": "a-secret", "BETA_KEY": ""})
        ehash = env_hash([("ALPHA_KEY", "a-secret"), ("BETA_KEY", ""), ("GONE_KEY", None)])
        lines = self.fp_lines({
            "HOSTNAME": "devbox", "TZ": "Europe/Lisbon", "HOST_ACCESS": "1", "INIT": "1", "NAME": "second",
            "PORTS": "127.0.0.1:3000:3000,127.0.0.1:8080:80,0.0.0.0:9000:9000,127.0.0.1:43323:43323,127.0.0.1:43324:43324",
            "BROWSER_URL": "http://host.containers.internal:9222", "WEB_PORT": "8000", "WITH": "clasp,claude",
            "AGENT": "claude", "YOLO": "0", "ENV_KEYS": "ALPHA_KEY,BETA_KEY,GONE_KEY", "IMAGE": "localhost:5000/sb:2.0.1",
        })
        fpr = fingerprint(lines, ehash)
        want = self.golden("create-flags.full.golden", {"@WS@": self.ws, "@ENVHASH@": ehash, "@FP@": fpr})
        self.assertEqual(out, want)

# ============================================================================ one test per key of 8.2

class KeyTest(Base):
    def test_name_names_the_volume_and_the_label_not_a_flag(self):
        out = self.flags()
        self.assertIn(("-v", (DEFAULT_VOLUME + ":/home/agent/.local/share/containers")), pairs_of(out))
        self.assertIn(("-e", "SWARMBOX_NAME=" + DEFAULT_NAME), pairs_of(out))
        self.assertNotIn("--name", out)   # `up` adds --name itself
        out = self.flags(env={"SWARMBOX_NAME": "other"})
        self.assertIn(("-v", "other-containers:/home/agent/.local/share/containers"), pairs_of(out))
        self.assertIn(("-e", "SWARMBOX_NAME=other"), pairs_of(out))

    def test_tz_local_zone_and_off(self):
        self.assertIn("--tz=local", self.flags())
        self.assertIn("--tz=Europe/Lisbon", self.flags(env={"SWARMBOX_TZ": "Europe/Lisbon"}))
        out = self.flags(env={"SWARMBOX_TZ": "off"})
        self.assertFalse([l for l in out if l.startswith("--tz")])

    def test_init_1_emits_init_0_does_not(self):
        self.assertIn("--init", self.flags(env={"SWARMBOX_INIT": "1"}))
        self.assertNotIn("--init", self.flags(env={"SWARMBOX_INIT": "0"}))

    def test_ports_default_is_loopback_only(self):
        out = self.flags(env={"SWARMBOX_PORTS": "3000"})
        self.assertIn(("-p", "127.0.0.1:3000:3000"), pairs_of(out))
        self.assertIn(("--label", "swarmbox.ports=127.0.0.1:3000:3000"), pairs_of(out))

    def test_web_port_maps_to_7681_on_loopback_and_web_0_drops_it(self):
        self.assertIn(("-p", "127.0.0.1:7681:7681"), pairs_of(self.flags()))
        self.assertIn(("-p", "127.0.0.1:8000:7681"), pairs_of(self.flags(env={"SWARMBOX_WEB_PORT": "8000"})))
        out = self.flags(env={"SWARMBOX_WEB": "0"})
        self.assertFalse([v for v in values(out, "-p") if v.endswith(":7681")])

    def test_env_keys_are_passed_by_name_only_when_set(self):
        out = self.flags(env={"SWARMBOX_ENV_KEYS": "SET_ONE,UNSET_ONE,EMPTY_ONE", "SET_ONE": CANARY, "EMPTY_ONE": ""})
        es = values(out, "-e")
        self.assertIn("SET_ONE", es)
        self.assertIn("EMPTY_ONE", es)       # set, but empty: still passed (it is set)
        self.assertNotIn("UNSET_ONE", es)
        self.assertNotIn(CANARY, "\n".join(out))

class AlwaysAppliedTest(Base):
    def test_the_always_applied_flags_of_8_3(self):
        out = self.flags()
        self.assertIn("--userns=keep-id:uid=1000,gid=1000", out)
        self.assertIn("--pids-limit=16384", out)
        pr = pairs_of(out)
        self.assertIn(("--tmpfs", "/tmp/swarmbox"), pr)
        self.assertIn(("--device", "/dev/net/tun"), pr)
        self.assertIn(("--security-opt", "unmask=/proc/*"), pr)
        self.assertIn(("-v", (DEFAULT_VOLUME + ":/home/agent/.local/share/containers")), pr)

    def test_the_tests_only_no_nested_switch_drops_what_a_third_level_cannot_honour(self):
        # slice 3.3: the real throwaway-box smoke test runs inside the development box (a nested level), where /dev/net/tun,
        # the unmasked /proc and a private UTS namespace (--hostname) are refused; the switch removes exactly those three
        # and adds the variable the box's serve reads for the same purpose. Without the switch nothing changes (the goldens).
        base = pairs_of(self.flags())
        low = pairs_of(self.flags(env={"SWARMBOX_TEST_NO_NESTED": "1"}))
        self.assertEqual(sorted(set(base) - set(low)),
                         sorted([("--device", "/dev/net/tun"), ("--security-opt", "unmask=/proc/*"), ("--hostname", DEFAULT_NAME)]))
        self.assertEqual(sorted(set(low) - set(base)), [("-e", "SWARMBOX_TEST_NO_NESTED=1")])
        self.assertEqual(len(low), len(base) - 3 + 1)

    def test_macos_extras_only_with_the_override(self):
        self.assertNotIn(("--security-opt", "label=disable"), pairs_of(self.flags()))
        self.assertIn(("--security-opt", "label=disable"), pairs_of(self.flags(env={"SWARMBOX_TEST_OS": "Darwin"})))
        self.assertNotIn(("--security-opt", "label=disable"), pairs_of(self.flags(env={"SWARMBOX_TEST_OS": "Linux"})))

# ============================================================================ framing

class FramingTest(Base):
    NASTY = "wo rk 'q\" $HOME `x` *?[a] \\ back"

    def test_one_line_is_one_argument_for_a_workspace_with_spaces_quotes_dollar_and_globs(self):
        ws = os.path.join(self.tmp, self.NASTY)
        p = self.cf(env={"SWARMBOX_WORKSPACE": ws})
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertTrue(os.path.isdir(ws))
        lines = p.stdout.split("\n")[:-1]
        self.assertIn(ws + ":/home/agent", lines)
        self.assertIn("swarmbox.workspace=" + ws, lines)
        # the read loop of design 3.6, in a real sh: one line must become one argument, byte for byte
        flags = os.path.join(self.tmp, "flags")
        with open(flags, "w") as f:
            f.write(p.stdout)
        script = ('f=$1\nset --\nwhile IFS= read -r line; do set -- "$@" "$line"; done < "$f"\n'
                  'printf "%s\\0" "$@"\n')
        for sh in (["sh"], ["dash"], ["bash", "--posix"], ["busybox", "sh"]):
            if not shutil.which(sh[0]):
                continue
            r = subprocess.run(sh + ["-c", script, "x", flags], capture_output=True, timeout=30)
            self.assertEqual(r.returncode, 0)
            got = r.stdout.decode().split("\0")[:-1]
            self.assertEqual(got, lines, sh)

# ============================================================================ tool ports

class ToolPortsTest(Base):
    TP = "clasp\t43323\ngcloud\t8085\ngcloud\t8086\n"

    def test_with_selects_only_its_tools_ports(self):
        self.make_helper(self.TP)
        out = self.flags(env={"SWARMBOX_WITH": "clasp"})
        ps = values(out, "-p")
        self.assertIn("127.0.0.1:43323:43323", ps)
        self.assertFalse([p for p in ps if ":8085:" in p])

    def test_a_port_the_user_already_publishes_is_not_added_twice(self):
        self.make_helper(self.TP)
        for user in ("43323", "43323:43323", "127.0.0.1:43323:43323", "0.0.0.0:43323:80"):
            out = self.flags(env={"SWARMBOX_WITH": "clasp", "SWARMBOX_PORTS": user})
            ps = [p for p in values(out, "-p") if not p.endswith(":7681")]
            self.assertEqual(len([p for p in ps if p.split(":")[1] == "43323"]), 1, (user, ps))

    def test_a_missing_tool_ports_is_a_corrupted_helper_exit_3(self):
        self.make_helper(None)
        p = self.cf()
        self.assertEqual(p.returncode, 3)
        self.assertEqual(p.stdout, "")
        self.assertIn("tool-ports", p.stderr)
        self.assertIn("swarmbox update", p.stderr)

# ============================================================================ ports and BROWSER_URL parity (design 7.2, 8.2, v0.1.0 flags)

class PortsParityTest(Base):
    def user_ports(self, spec):
        out = self.flags(env={"SWARMBOX_PORTS": spec})
        return [p for p in values(out, "-p") if not p.endswith(":7681")]

    def test_port_forms(self):
        table = {
            "3000": ["127.0.0.1:3000:3000"],
            "3000:3000": ["127.0.0.1:3000:3000"],
            "8080:80": ["127.0.0.1:8080:80"],
            "127.0.0.1:3000:3000": ["127.0.0.1:3000:3000"],
            "192.168.1.5:3000:3000": ["192.168.1.5:3000:3000"],
            "3000,8080:80": ["127.0.0.1:3000:3000", "127.0.0.1:8080:80"],
        }
        for spec, want in table.items():
            self.assertEqual(self.user_ports(spec), want, spec)

    def test_invalid_ports_are_exit_2(self):
        for spec in ("abc", "1.2.3:80:80", "999.1.1.1:80:80", "0", "70000", "1:2:3:4", "3000,", "0.0.0.0::80", "a.b.c.d:1:1"):
            p = self.cf(env={"SWARMBOX_PORTS": spec})
            self.assertEqual(p.returncode, 2, spec)
            self.assertEqual(p.stdout, "", spec)


class BrowserUrlParityTest(Base):
    def url(self, value=None, args=()):
        env = {} if value is None else {"SWARMBOX_BROWSER_URL": value}
        out = self.flags(env=env, args=args)
        got = [e.split("=", 1)[1] for e in values(out, "-e") if e.startswith("SWARMBOX_BROWSER_URL=")]
        return got[0] if got else None

    def test_forms(self):
        table = {
            "9222": "http://host.containers.internal:9222",
            "1234": "http://host.containers.internal:1234",
            "192.168.1.100:9222": "http://192.168.1.100:9222",
            "chrome.lan:9222": "http://chrome.lan:9222",
            "http://chrome.lan:9222": "http://chrome.lan:9222",
            "https://chrome.lan/x": "https://chrome.lan/x",
        }
        for given, want in table.items():
            self.assertEqual(self.url(given), want, given)

# ============================================================================ nothing unsafe, ever

class NeverUnsafeTest(Base):
    FORBIDDEN_PREFIXES = ("--network", "--net", "--privileged", "--pid=", "--ipc=", "--uts=", "--cap-add", "--userns=host",
                          "--security-opt=seccomp", "--device=/dev/mem")

    def check(self, p, env):
        self.assertEqual(p.returncode, 0, (env, p.stderr))
        lines = p.stdout.split("\n")[:-1]
        for l in lines:
            self.assertNotEqual(l, "--network=host", env)
            for pre in self.FORBIDDEN_PREFIXES:
                self.assertFalse(l.startswith(pre), (l, env))
            self.assertNotIn("host", [l] if l.startswith("--network") else [])
        explicit_all = "0.0.0.0" in env.get("SWARMBOX_PORTS", "")
        for pv in values(lines, "-p"):
            if pv.startswith("0.0.0.0:"):
                self.assertTrue(explicit_all, (pv, env))
                self.assertIn("all network interfaces", p.stderr)
            else:
                self.assertTrue(pv.startswith("127.0.0.1:") or explicit_all and pv.split(":")[0].count(".") == 3, (pv, env))

    def test_loop_over_key_combinations(self):
        self.make_helper("clasp\t43323\n")
        axes = [
            ("SWARMBOX_WEB", ["0", "1"]),
            ("SWARMBOX_HOST_ACCESS", ["0", "1"]),
            ("SWARMBOX_INIT", ["0", "1"]),
            ("SWARMBOX_TZ", ["local", "off", "Europe/Lisbon"]),
            ("SWARMBOX_PORTS", ["", "3000", "8080:80,3000", "0.0.0.0:80:80", "127.0.0.1:9:9"]),
            ("SWARMBOX_WITH", ["", "clasp", "claude,clasp"]),
            ("SWARMBOX_BROWSER_URL", ["", "9222", "h:1", "http://x:2"]),
            ("SWARMBOX_ENV_KEYS", ["", "A_ONE", "A_ONE,B_TWO"]),
            ("SWARMBOX_TEST_OS", ["Linux", "Darwin"]),
            ("SWARMBOX_NAME", [DEFAULT_NAME, "second"]),
        ]
        combos = list(itertools.product(*[[(k, v) for v in vs] for k, vs in axes]))
        random.Random(32).shuffle(combos)
        n = 0
        for combo in combos[:120]:
            env = dict(combo)
            env["A_ONE"] = CANARY
            env["SWARMBOX_WORKSPACE"] = self.ws
            p = self.cf(env=env)
            self.check(p, env)
            n += 1
        self.assertEqual(n, 120)

# ============================================================================ secrets

class SecretsTest(Base):
    def everything(self, env, cfg=None):
        outs = []
        for args in (["create-flags"], ["fingerprint"], ["fingerprint", "--explain"]):
            p = self.run_h(*args, env=env, cfg=cfg)
            outs.append(p.stdout + p.stderr)
        return "\n".join(outs)

    def test_the_cloudflare_token_never_appears(self):
        env = {"SWARMBOX_CLOUDFLARE_TUNNEL_TOKEN": TOKEN}
        self.assertNotIn(TOKEN, self.everything(env))
        self.assertNotIn(TOKEN, self.everything({}, cfg="CLOUDFLARE_TUNNEL_TOKEN=" + TOKEN + "\n"))

    def test_env_keys_values_never_appear_but_the_hash_follows_them(self):
        env = {"SWARMBOX_ENV_KEYS": "MY_SECRET,OTHER", "MY_SECRET": CANARY}
        self.assertNotIn(CANARY, self.everything(env))
        out = self.flags(env=env)
        self.assertIn("MY_SECRET", values(out, "-e"))
        want = env_hash([("MY_SECRET", CANARY), ("OTHER", None)])
        self.assertIn(("--label", "swarmbox.env-hash=" + want), pairs_of(out))
        # a changed value changes the env-hash and the fingerprint; an unrelated variable changes neither
        changed = dict(env, MY_SECRET=CANARY + "2")
        self.assertNotEqual(self.fp(env=env), self.fp(env=changed))
        self.assertEqual(self.fp(env=env), self.fp(env=dict(env, UNRELATED="x")))

    def test_an_env_name_cannot_override_the_box_variables_we_set(self):
        # ENV_KEYS entries come before the SWARMBOX_* ones, so the last -e wins and it is ours
        out = self.flags(env={"SWARMBOX_ENV_KEYS": "SWARMBOX_WEB", "SWARMBOX_WEB": "0"})
        es = values(out, "-e")
        self.assertLess(es.index("SWARMBOX_WEB"), es.index("SWARMBOX_WEB=0"))


# ============================================================================ fingerprint

class FingerprintTest(Base):
    def test_matches_an_independent_computation(self):
        want = fingerprint(self.fp_lines(), env_hash([]))
        self.assertEqual(self.fp(), want)

    def test_unchanged_by_runtime_only_keys_and_secrets(self):
        base = self.fp()
        for k, v in (("SWARMBOX_STARSHIP", "0"), ("SWARMBOX_UPDATE_CHECK", "0"), ("SWARMBOX_TOOLS_DIR", "/x"),
                     ("SWARMBOX_WEB_DOMAIN", "x.example"), ("SWARMBOX_WEB_HOSTNAME", "h"),
                     ("SWARMBOX_CLOUDFLARED_IMAGE", "img"), ("SWARMBOX_CLOUDFLARE_TUNNEL_TOKEN", TOKEN),
                     ("SWARMBOX_UNKNOWN", "1")):
            self.assertEqual(self.fp(env={k: v}), base, k)

class ExplainTest(Base):
    def labels_of(self, env=None, cfg=None):
        out = self.flags(env=env, cfg=cfg)
        return ["--label=" + v for v in values(out, "--label")]

    def explain(self, labels, env=None, cfg=None):
        p = self.run_h("fingerprint", "--explain", *labels, env=env, cfg=cfg)
        return p

    def test_same_configuration_prints_the_hash_only_and_exits_0(self):
        labels = self.labels_of()
        p = self.explain(labels)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(p.stdout.strip(), self.fp())

    def test_ports_difference_uses_the_d30_wording(self):
        labels = self.labels_of(env={"SWARMBOX_PORTS": "3000"})
        p = self.explain(labels, env={"SWARMBOX_PORTS": "3000,8080"})
        self.assertEqual(p.returncode, 1)
        lines = p.stdout.strip().split("\n")
        self.assertEqual(lines[0], self.fp(env={"SWARMBOX_PORTS": "3000,8080"}))
        self.assertIn("`PORTS` changed: box has 127.0.0.1:3000:3000, config has 127.0.0.1:3000:3000,127.0.0.1:8080:8080; "
                      "run `swarmbox reset` to apply", lines[1:])
        self.assertEqual(len(lines), 2)

# ============================================================================ workspace checks

class WorkspaceTest(Base):
    def test_a_missing_workspace_is_created_with_one_message(self):
        ws = os.path.join(self.tmp, "a", "b", "ws")     # a missing parent is created too
        p = self.cf(env={"SWARMBOX_WORKSPACE": ws})
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertTrue(os.path.isdir(ws))
        msgs = [l for l in p.stderr.split("\n") if "created" in l]
        self.assertEqual(msgs, ["swarmbox: created the workspace folder %s" % ws])
        p = self.cf(env={"SWARMBOX_WORKSPACE": ws})
        self.assertNotIn("created", p.stderr)

    # --- WSL (D34, B32), with a fake /proc/version; nothing under /mnt is ever created by these tests
    def set_wsl(self, on):
        with open(self.procversion, "w") as f:
            f.write((WSL_VERSION if on else PLAIN_VERSION) + "\n")

    def test_wsl_refuses_a_windows_drive_workspace_with_the_d34_text(self):
        self.set_wsl(True)
        for ws in ("/mnt/c/Users/me/swarmbox", "/mnt/d/x", "/mnt/C/Users", "/mnt/c", "/mnt/z/deep/er/path"):
            p = self.cf(env={"SWARMBOX_WORKSPACE": ws})
            self.assertEqual(p.returncode, 4, ws)
            self.assertEqual(p.stdout, "", ws)
            self.assertEqual(p.stderr.strip(), D34 % ws, ws)
        self.assertFalse(os.path.exists("/mnt/z"))

# ============================================================================ the real helper under other shells

def interpreters():
    out = {}
    if shutil.which("dash"):
        out["dash"] = [shutil.which("dash")]
    if shutil.which("bash"):
        out["bash --posix"] = [shutil.which("bash"), "--posix"]
    if shutil.which("busybox"):
        out["busybox sh"] = [shutil.which("busybox"), "sh"]
    if os.path.exists("/bin/sh"):
        out["/bin/sh"] = ["/bin/sh"]
    if shutil.which("zsh"):
        out["zsh --emulate sh"] = [shutil.which("zsh"), "--emulate", "sh"]
    return out


class SourceRulesTest(unittest.TestCase):
    def test_no_bashisms_in_the_new_code(self):
        with open(HELPER_SRC) as f:
            src = f.read()
        code = [l for l in src.split("\n") if not l.lstrip().startswith("#")]
        text = "\n".join(code)
        for bad in ("[[ ", " ]]", "echo -e", "read -s", "<<<", "$'", "declare ", "mapfile", "readarray", "${!", "=~"):
            self.assertNotIn(bad, text, bad)
        import re
        self.assertIsNone(re.search(r"(^|[;{(&|]\s*)local\s+[A-Za-z_]", text, re.M), "local")

if __name__ == "__main__":
    unittest.main()
