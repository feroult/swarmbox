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
from helpers import ROOT  # noqa: E402

HELPER_SRC = os.path.join(ROOT, "container", "host", "swarmbox-host")
VERSION_SRC = os.path.join(ROOT, "container", "host", "VERSION")
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
            name = (env or {}).get("SWARMBOX_NAME", "swarmbox")
            folder = self.cfgroot if name == "swarmbox" else os.path.join(self.cfgroot, name)
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
            "AGENT": "", "BROWSER_URL": "", "ENV_KEYS": "", "HOSTNAME": "swarmbox", "HOST_ACCESS": "0",
            "IMAGE": "ghcr.io/<org>/swarmbox:%s" % VERSION, "INIT": "0", "NAME": "swarmbox", "PORTS": "",
            "TZ": "local", "WEB": "1", "WEB_PORT": "7681", "WITH": "", "WORKSPACE": self.ws, "YOLO": "1",
        }
        d.update(over or {})
        return ["%s=%s" % kv for kv in d.items()]


# ============================================================================ the flag set: golden files

class GoldenTest(Base):
    def golden(self, name, subs):
        with open(os.path.join(FIXTURES, name)) as f:
            text = f.read()
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

    def test_macos_golden_adds_only_label_disable(self):
        out = self.flags(env={"SWARMBOX_TEST_OS": "Darwin"})
        base = self.flags()
        self.assertIn(("--security-opt", "label=disable"), pairs_of(out))
        self.assertNotIn(("--security-opt", "label=disable"), pairs_of(base))
        self.assertIn("--userns=keep-id:uid=1000,gid=1000", out)


# ============================================================================ one test per key of 8.2

class KeyTest(Base):
    def test_name_names_the_volume_and_the_label_not_a_flag(self):
        out = self.flags()
        self.assertIn(("-v", "swarmbox-containers:/home/agent/.local/share/containers"), pairs_of(out))
        self.assertIn(("-e", "SWARMBOX_NAME=swarmbox"), pairs_of(out))
        self.assertNotIn("--name", out)   # `up` adds --name itself
        out = self.flags(env={"SWARMBOX_NAME": "other"})
        self.assertIn(("-v", "other-containers:/home/agent/.local/share/containers"), pairs_of(out))
        self.assertIn(("-e", "SWARMBOX_NAME=other"), pairs_of(out))

    def test_workspace_mount(self):
        out = self.flags()
        self.assertIn(("-v", self.ws + ":/home/agent"), pairs_of(out))
        self.assertIn(("--label", "swarmbox.workspace=" + self.ws), pairs_of(out))
        other = os.path.join(self.tmp, "other-ws")
        out = self.flags(env={"SWARMBOX_WORKSPACE": other})
        self.assertIn(("-v", other + ":/home/agent"), pairs_of(out))

    def test_hostname(self):
        self.assertIn(("--hostname", "swarmbox"), pairs_of(self.flags()))
        self.assertIn(("--hostname", "devbox"), pairs_of(self.flags(env={"SWARMBOX_HOSTNAME": "devbox"})))

    def test_tz_local_zone_and_off(self):
        self.assertIn("--tz=local", self.flags())
        self.assertIn("--tz=Europe/Lisbon", self.flags(env={"SWARMBOX_TZ": "Europe/Lisbon"}))
        out = self.flags(env={"SWARMBOX_TZ": "off"})
        self.assertFalse([l for l in out if l.startswith("--tz")])

    def test_tz_local_without_a_local_time_file_gives_no_flag_and_a_warning(self):
        p = self.cf(env={"SWARMBOX_LOCALTIME_FILE": os.path.join(self.tmp, "nonexistent")})
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertFalse([l for l in p.stdout.split("\n") if l.startswith("--tz")])
        self.assertIn("UTC", p.stderr)

    def test_tz_old_off_spellings_of_v0_1_0_still_mean_off(self):
        for v in ("OFF", "none", "NONE"):
            out = self.flags(env={"SWARMBOX_TZ": v})
            self.assertFalse([l for l in out if l.startswith("--tz")], v)

    def test_tz_invalid_is_exit_2(self):
        p = self.cf(env={"SWARMBOX_TZ": "not a zone"})
        self.assertEqual(p.returncode, 2)
        self.assertEqual(p.stdout, "")

    def test_init_1_emits_init_0_does_not(self):
        self.assertIn("--init", self.flags(env={"SWARMBOX_INIT": "1"}))
        self.assertNotIn("--init", self.flags(env={"SWARMBOX_INIT": "0"}))

    def test_init_auto_is_a_usage_error_up_resolves_it(self):
        for env, drop in (({"SWARMBOX_INIT": "auto"}, ()), ({}, ("SWARMBOX_INIT",))):
            p = self.cf(env=env, drop=drop)
            self.assertEqual(p.returncode, 2, (env, p.stderr))
            self.assertEqual(p.stdout, "")
            self.assertIn("INIT", p.stderr)
            self.assertIn("auto", p.stderr)

    def test_init_from_the_file_is_read_too(self):
        out = self.flags(cfg="INIT=1\n", drop=("SWARMBOX_INIT",))
        self.assertIn("--init", out)

    def test_ports_default_is_loopback_only(self):
        out = self.flags(env={"SWARMBOX_PORTS": "3000"})
        self.assertIn(("-p", "127.0.0.1:3000:3000"), pairs_of(out))
        self.assertIn(("--label", "swarmbox.ports=127.0.0.1:3000:3000"), pairs_of(out))

    def test_host_access_adds_the_host_gateway_name(self):
        self.assertNotIn(("--add-host", "host.containers.internal:host-gateway"), pairs_of(self.flags()))
        out = self.flags(env={"SWARMBOX_HOST_ACCESS": "1"})
        self.assertIn(("--add-host", "host.containers.internal:host-gateway"), pairs_of(out))

    def test_browser_url_is_passed_as_a_plain_variable(self):
        self.assertFalse([v for v in values(self.flags(), "-e") if v.startswith("SWARMBOX_BROWSER_URL")])
        out = self.flags(env={"SWARMBOX_BROWSER_URL": "1234"})
        self.assertIn(("-e", "SWARMBOX_BROWSER_URL=http://host.containers.internal:1234"), pairs_of(out))

    def test_web_and_yolo_are_always_passed(self):
        es = values(self.flags(), "-e")
        self.assertIn("SWARMBOX_WEB=1", es)
        self.assertIn("SWARMBOX_YOLO=1", es)
        es = values(self.flags(env={"SWARMBOX_WEB": "0", "SWARMBOX_YOLO": "0"}), "-e")
        self.assertIn("SWARMBOX_WEB=0", es)
        self.assertIn("SWARMBOX_YOLO=0", es)

    def test_web_port_maps_to_7681_on_loopback_and_web_0_drops_it(self):
        self.assertIn(("-p", "127.0.0.1:7681:7681"), pairs_of(self.flags()))
        self.assertIn(("-p", "127.0.0.1:8000:7681"), pairs_of(self.flags(env={"SWARMBOX_WEB_PORT": "8000"})))
        out = self.flags(env={"SWARMBOX_WEB": "0"})
        self.assertFalse([v for v in values(out, "-p") if v.endswith(":7681")])

    def test_with_and_agent_are_passed_when_set(self):
        es = values(self.flags(), "-e")
        self.assertFalse([e for e in es if e.startswith("SWARMBOX_WITH") or e.startswith("SWARMBOX_AGENT")])
        es = values(self.flags(env={"SWARMBOX_WITH": "claude,gcloud", "SWARMBOX_AGENT": "claude"}), "-e")
        self.assertIn("SWARMBOX_WITH=claude,gcloud", es)
        self.assertIn("SWARMBOX_AGENT=claude", es)

    def test_env_keys_are_passed_by_name_only_when_set(self):
        out = self.flags(env={"SWARMBOX_ENV_KEYS": "SET_ONE,UNSET_ONE,EMPTY_ONE", "SET_ONE": CANARY, "EMPTY_ONE": ""})
        es = values(out, "-e")
        self.assertIn("SET_ONE", es)
        self.assertIn("EMPTY_ONE", es)       # set, but empty: still passed (it is set)
        self.assertNotIn("UNSET_ONE", es)
        self.assertNotIn(CANARY, "\n".join(out))

    def test_env_keys_listed_but_not_set_warn_before_creation(self):
        p = self.cf(env={"SWARMBOX_ENV_KEYS": "UNSET_ONE"})
        self.assertEqual(p.returncode, 0)
        self.assertIn("UNSET_ONE is listed but not set in this terminal; the box will start without it", p.stderr)

    def test_image_is_a_label_not_an_argument_position(self):
        out = self.flags(env={"SWARMBOX_IMAGE": "localhost:5000/sb:2.0.1"})
        self.assertIn(("--label", "swarmbox.image=localhost:5000/sb:2.0.1"), pairs_of(out))
        self.assertNotIn("localhost:5000/sb:2.0.1", out)    # `up` puts the image after the flags, not create-flags
        out = self.flags()
        self.assertIn(("--label", "swarmbox.image=ghcr.io/<org>/swarmbox:%s" % VERSION), pairs_of(out))


class AlwaysAppliedTest(Base):
    def test_the_always_applied_flags_of_8_3(self):
        out = self.flags()
        self.assertIn("--userns=keep-id:uid=1000,gid=1000", out)
        self.assertIn("--pids-limit=16384", out)
        pr = pairs_of(out)
        self.assertIn(("--tmpfs", "/tmp/swarmbox"), pr)
        self.assertIn(("--device", "/dev/net/tun"), pr)
        self.assertIn(("--security-opt", "unmask=/proc/*"), pr)
        self.assertIn(("-v", "swarmbox-containers:/home/agent/.local/share/containers"), pr)

    def test_the_six_labels_of_3_7_4_and_no_other(self):
        out = self.flags()
        labels = values(out, "--label")
        names = [l.split("=", 1)[0] for l in labels]
        self.assertEqual(names, ["swarmbox.managed", "swarmbox.image", "swarmbox.workspace", "swarmbox.ports",
                                 "swarmbox.env-hash", "swarmbox.fingerprint"])
        self.assertEqual(labels[0], "swarmbox.managed=2")

    def test_the_label_fingerprint_is_what_the_fingerprint_command_prints(self):
        env = {"SWARMBOX_PORTS": "3000", "SWARMBOX_WITH": "claude"}
        out = self.flags(env=env)
        self.assertIn(("--label", "swarmbox.fingerprint=" + self.fp(env=env)), pairs_of(out))

    def test_macos_extras_only_with_the_override(self):
        self.assertNotIn(("--security-opt", "label=disable"), pairs_of(self.flags()))
        self.assertIn(("--security-opt", "label=disable"), pairs_of(self.flags(env={"SWARMBOX_TEST_OS": "Darwin"})))
        self.assertNotIn(("--security-opt", "label=disable"), pairs_of(self.flags(env={"SWARMBOX_TEST_OS": "Linux"})))

    def test_the_host_os_is_used_without_the_override(self):
        want = subprocess.run(["uname", "-s"], capture_output=True, text=True).stdout.strip()
        out = self.flags(drop=("SWARMBOX_TEST_OS",))
        self.assertEqual(("--security-opt", "label=disable") in pairs_of(out), want == "Darwin")

    def test_usage_errors(self):
        for args in (["--bogus"], ["extra"], ["--browser-url"]):
            p = self.cf(args=args)
            self.assertEqual(p.returncode, 2, args)
            self.assertEqual(p.stdout, "")


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

    def test_no_value_can_carry_a_newline(self):
        p = self.cf(env={"SWARMBOX_WORKSPACE": "/tmp/a\nb"})
        self.assertEqual(p.returncode, 2)
        self.assertEqual(p.stdout, "")

    def test_a_path_with_a_colon_is_refused(self):
        p = self.cf(env={"SWARMBOX_WORKSPACE": "/tmp/a:b"})
        self.assertEqual(p.returncode, 2)

    def test_nothing_is_printed_when_a_later_check_fails(self):
        # the failure happens after some lines were composed: stdout must stay empty, so `up` never sees half a list
        p = self.cf(env={"SWARMBOX_PORTS": "3000,bad"})
        self.assertEqual(p.returncode, 2)
        self.assertEqual(p.stdout, "")


# ============================================================================ tool ports

class ToolPortsTest(Base):
    TP = "clasp\t43323\ngcloud\t8085\ngcloud\t8086\n"

    def test_with_selects_only_its_tools_ports(self):
        self.make_helper(self.TP)
        out = self.flags(env={"SWARMBOX_WITH": "clasp"})
        ps = values(out, "-p")
        self.assertIn("127.0.0.1:43323:43323", ps)
        self.assertFalse([p for p in ps if ":8085:" in p])

    def test_with_a_tool_with_several_ports(self):
        self.make_helper(self.TP)
        ps = values(self.flags(env={"SWARMBOX_WITH": "gcloud"}), "-p")
        self.assertEqual([p for p in ps if not p.endswith(":7681")], ["127.0.0.1:8085:8085", "127.0.0.1:8086:8086"])

    def test_with_selecting_none_adds_nothing(self):
        self.make_helper(self.TP)
        for w in ("", "claude", "mytool"):
            ps = values(self.flags(env={"SWARMBOX_WITH": w}), "-p")
            self.assertEqual(ps, ["127.0.0.1:7681:7681"], w)

    def test_a_port_the_user_already_publishes_is_not_added_twice(self):
        self.make_helper(self.TP)
        for user in ("43323", "43323:43323", "127.0.0.1:43323:43323", "0.0.0.0:43323:80"):
            out = self.flags(env={"SWARMBOX_WITH": "clasp", "SWARMBOX_PORTS": user})
            ps = [p for p in values(out, "-p") if not p.endswith(":7681")]
            self.assertEqual(len([p for p in ps if p.split(":")[1] == "43323"]), 1, (user, ps))

    def test_the_tool_ports_enter_the_label_and_the_fingerprint(self):
        self.make_helper(self.TP)
        env = {"SWARMBOX_WITH": "clasp", "SWARMBOX_PORTS": "3000"}
        out = self.flags(env=env)
        self.assertIn(("--label", "swarmbox.ports=127.0.0.1:3000:3000,127.0.0.1:43323:43323"), pairs_of(out))
        plain = self.fp(env={"SWARMBOX_WITH": "claude", "SWARMBOX_PORTS": "3000"})
        self.assertNotEqual(self.fp(env=env), plain)

    def test_the_same_port_from_two_tools_is_published_once(self):
        self.make_helper("a\t5000\nb\t5000\n")
        ps = values(self.flags(env={"SWARMBOX_WITH": "a,b"}), "-p")
        self.assertEqual(len([p for p in ps if p == "127.0.0.1:5000:5000"]), 1)

    def test_an_empty_tool_ports_file_is_valid(self):
        self.make_helper("")
        p = self.cf(env={"SWARMBOX_WITH": "clasp"})
        self.assertEqual(p.returncode, 0, p.stderr)

    def test_a_missing_tool_ports_is_a_corrupted_helper_exit_3(self):
        self.make_helper(None)
        p = self.cf()
        self.assertEqual(p.returncode, 3)
        self.assertEqual(p.stdout, "")
        self.assertIn("tool-ports", p.stderr)
        self.assertIn("swarmbox update", p.stderr)

    def test_the_fingerprint_needs_tool_ports_too(self):
        self.make_helper(None)
        p = self.run_h("fingerprint")
        self.assertEqual(p.returncode, 3)
        self.assertIn("tool-ports", p.stderr)

    def test_a_malformed_line_is_skipped_with_a_warning(self):
        self.make_helper("clasp\tabc\nnotab\nclasp\t43323\n")
        p = self.cf(env={"SWARMBOX_WITH": "clasp"})
        self.assertEqual(p.returncode, 0)
        self.assertIn("127.0.0.1:43323:43323", p.stdout)
        self.assertEqual([v for v in values(p.stdout.split("\n")[:-1], "-p") if not v.endswith(":7681")], ["127.0.0.1:43323:43323"])
        self.assertIn("tool-ports", p.stderr)


# ============================================================================ ports and BROWSER_URL parity (design 7.2, 8.2, start.sh today)

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

    def test_all_interfaces_needs_the_explicit_address_and_warns(self):
        p = self.cf(env={"SWARMBOX_PORTS": "0.0.0.0:80:80"})
        self.assertEqual(p.returncode, 0)
        self.assertIn("0.0.0.0:80:80", values(p.stdout.split("\n")[:-1], "-p"))
        self.assertIn("0.0.0.0:80:80", p.stderr)
        self.assertIn("all network interfaces", p.stderr)
        p = self.cf(env={"SWARMBOX_PORTS": "127.0.0.1:80:80"})
        self.assertNotIn("all network interfaces", p.stderr)

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

    def test_unset_passes_nothing(self):
        self.assertIsNone(self.url())

    def test_the_empty_argument_form_means_9222_like_remote_browser_today(self):
        self.assertEqual(self.url(args=["--browser-url", ""]), "http://host.containers.internal:9222")
        self.assertEqual(self.url(args=["--browser-url="]), "http://host.containers.internal:9222")

    def test_the_option_overrides_the_configuration(self):
        self.assertEqual(self.url("1234", args=["--browser-url", "5555"]), "http://host.containers.internal:5555")

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

    def test_invalid_is_exit_2(self):
        for given in ("a b", "99999", "ftp://x", "nohostport", ":1234", "0"):
            p = self.cf(env={"SWARMBOX_BROWSER_URL": given})
            self.assertEqual(p.returncode, 2, given)
        p = self.cf(args=["--browser-url", "a b"])
        self.assertEqual(p.returncode, 2)

    def test_browser_url_is_not_a_secret_so_it_is_in_the_fingerprint(self):
        self.assertNotEqual(self.fp(), self.fp(env={"SWARMBOX_BROWSER_URL": "9222"}))


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
            ("SWARMBOX_NAME", ["swarmbox", "second"]),
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

    def test_the_guard_exists_in_the_helper(self):
        with open(HELPER_SRC) as f:
            src = f.read()
        self.assertIn("--network", src)              # the guard names it (D7)
        self.assertNotIn("--network=host\n", [l for l in src.split("\n") if l.strip().startswith("emit")])

    def test_host_network_cannot_be_asked_for_through_any_key(self):
        for k in ("SWARMBOX_HOSTNAME", "SWARMBOX_WORKSPACE", "SWARMBOX_PORTS", "SWARMBOX_TZ", "SWARMBOX_WITH",
                  "SWARMBOX_AGENT", "SWARMBOX_ENV_KEYS", "SWARMBOX_BROWSER_URL", "SWARMBOX_IMAGE", "SWARMBOX_NAME"):
            p = self.cf(env={k: "--network=host"})
            self.assertNotIn("--network=host", p.stdout.split("\n"), k)
            for l in p.stdout.split("\n"):
                self.assertFalse(l.startswith("--network"), (k, l))
        p = self.cf(args=["--network=host"])
        self.assertEqual(p.returncode, 2)
        self.assertEqual(p.stdout, "")


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

    def test_the_token_does_not_change_the_fingerprint(self):
        a = self.fp()
        self.assertEqual(a, self.fp(env={"SWARMBOX_CLOUDFLARE_TUNNEL_TOKEN": TOKEN}))
        self.assertEqual(a, self.fp(cfg="CLOUDFLARE_TUNNEL_TOKEN=" + TOKEN + "\n"))

    def test_the_token_never_enters_the_box_as_an_env_flag(self):
        out = self.flags(env={"SWARMBOX_CLOUDFLARE_TUNNEL_TOKEN": TOKEN, "SWARMBOX_ENV_KEYS": "FOO"})
        self.assertFalse([l for l in out if "CLOUDFLARE" in l])

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

    def test_the_value_is_passed_by_name_so_ps_never_shows_it(self):
        out = self.flags(env={"SWARMBOX_ENV_KEYS": "MY_SECRET", "MY_SECRET": CANARY})
        i = out.index("-e")
        pairs = [(out[j], out[j + 1]) for j in range(len(out) - 1) if out[j] == "-e"]
        self.assertIn(("-e", "MY_SECRET"), pairs)
        self.assertTrue(all("=" in v or v == "MY_SECRET" for _, v in pairs))
        self.assertNotIn(CANARY, " ".join(out))
        self.assertGreaterEqual(i, 0)

    def test_the_config_file_cannot_smuggle_a_cloudflare_name_into_env_keys(self):
        p = self.cf(env={"SWARMBOX_ENV_KEYS": "SWARMBOX_CLOUDFLARE_TUNNEL_TOKEN"})
        self.assertEqual(p.returncode, 2)
        self.assertEqual(p.stdout, "")

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

    def test_is_a_sha256_hex(self):
        h = self.fp()
        self.assertEqual(len(h), 64)
        int(h, 16)

    def test_stable_across_key_order_and_comments_in_the_file(self):
        a = self.fp(cfg="PORTS=3000\nWITH=claude\nHOSTNAME=devbox\n")
        b = self.fp(cfg="# a comment\n\nHOSTNAME=devbox\nWITH=claude\n  PORTS = 3000  \n")
        self.assertEqual(a, b)

    def test_changes_with_each_creation_time_key(self):
        self.make_helper("clasp\t43323\n")
        base = self.fp()
        alts = {
            "NAME": "other", "WORKSPACE": os.path.join(self.tmp, "ws2"), "HOSTNAME": "devbox", "TZ": "off", "INIT": "1",
            "PORTS": "3000", "HOST_ACCESS": "1", "BROWSER_URL": "9222", "WEB": "0", "WEB_PORT": "8000", "WITH": "clasp",
            "AGENT": "claude", "YOLO": "0", "ENV_KEYS": "FOO", "IMAGE": "swarmbox:dev",
        }
        seen = {base}
        for k, v in alts.items():
            h = self.fp(env={"SWARMBOX_" + k: v})
            self.assertNotEqual(h, base, k)
            self.assertNotIn(h, seen, k)
            seen.add(h)

    def test_unchanged_by_runtime_only_keys_and_secrets(self):
        base = self.fp()
        for k, v in (("SWARMBOX_STARSHIP", "0"), ("SWARMBOX_UPDATE_CHECK", "0"), ("SWARMBOX_TOOLS_DIR", "/x"),
                     ("SWARMBOX_WEB_DOMAIN", "x.example"), ("SWARMBOX_WEB_HOSTNAME", "h"),
                     ("SWARMBOX_CLOUDFLARED_IMAGE", "img"), ("SWARMBOX_CLOUDFLARE_TUNNEL_TOKEN", TOKEN),
                     ("SWARMBOX_UNKNOWN", "1")):
            self.assertEqual(self.fp(env={k: v}), base, k)

    def test_tz_is_resolved_local_without_a_localtime_file_equals_off(self):
        gone = {"SWARMBOX_LOCALTIME_FILE": os.path.join(self.tmp, "nonexistent")}
        self.assertEqual(self.fp(env=gone), self.fp(env={"SWARMBOX_TZ": "off"}))
        self.assertNotEqual(self.fp(env=gone), self.fp())

    def test_workspace_is_absolute_in_the_fingerprint_and_nothing_is_created(self):
        rel = self.fp(env={"SWARMBOX_WORKSPACE": "relws"}, drop=())
        want = fingerprint(self.fp_lines({"WORKSPACE": os.path.join(self.tmp, "relws")}), env_hash([]))
        self.assertEqual(rel, want)
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "relws")))

    def test_init_auto_is_taken_literally(self):
        # up resolves it for create-flags; the entry-time comparison is made with the value up reads from the box
        h = self.fp(env={"SWARMBOX_INIT": "auto"})
        self.assertEqual(h, fingerprint(self.fp_lines({"INIT": "auto"}), env_hash([])))

    def test_sha256sum_and_shasum_are_both_used_via_shim(self):
        want = self.fp()
        for variant in ("sha256sum", "shasum"):
            bindir = os.path.join(self.tmp, "bin-" + variant)
            log = os.path.join(self.tmp, "log-" + variant)
            os.makedirs(bindir)
            skip = {"sha256sum", "shasum"}
            for d in os.environ["PATH"].split(":"):
                if not os.path.isdir(d):
                    continue
                for n in os.listdir(d):
                    t = os.path.join(d, n)
                    if n not in skip and not os.path.exists(os.path.join(bindir, n)) and os.access(t, os.X_OK) and os.path.isfile(t):
                        os.symlink(t, os.path.join(bindir, n))
            real = shutil.which(variant)
            with open(os.path.join(bindir, variant), "w") as f:
                f.write('#!/bin/sh\necho "%s $*" >> %s\nexec %s "$@"\n' % (variant, log, real))
            os.chmod(os.path.join(bindir, variant), 0o755)
            h = self.fp(path=bindir)
            self.assertEqual(h, want, variant)
            with open(log) as f:
                calls = f.read().split("\n")[:-1]
            self.assertTrue(calls, variant)
            if variant == "shasum":
                self.assertTrue(all(c == "shasum -a 256" for c in calls), calls)

    def test_no_sha256_tool_is_a_missing_prerequisite_exit_3(self):
        bindir = os.path.join(self.tmp, "bin-none")
        os.makedirs(bindir)
        for d in os.environ["PATH"].split(":"):
            if os.path.isdir(d):
                for n in os.listdir(d):
                    t = os.path.join(d, n)
                    if n not in ("sha256sum", "shasum") and not os.path.exists(os.path.join(bindir, n)) and os.access(t, os.X_OK) and os.path.isfile(t):
                        os.symlink(t, os.path.join(bindir, n))
        p = self.run_h("fingerprint", path=bindir)
        self.assertEqual(p.returncode, 3)
        self.assertIn("sha256sum", p.stderr)
        p = self.run_h("create-flags", path=bindir)
        self.assertEqual(p.returncode, 3)
        self.assertEqual(p.stdout, "")


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

    def test_image_workspace_and_variables_differences(self):
        labels = self.labels_of(env={"SWARMBOX_ENV_KEYS": "VV", "VV": CANARY + "1"})
        ws2 = os.path.join(self.tmp, "ws2")
        env = {"SWARMBOX_ENV_KEYS": "VV", "VV": CANARY + "2", "SWARMBOX_IMAGE": "swarmbox:dev", "SWARMBOX_WORKSPACE": ws2}
        p = self.explain(labels, env=env)
        self.assertEqual(p.returncode, 1)
        lines = p.stdout.strip().split("\n")[1:]
        self.assertIn("this box was created from ghcr.io/<org>/swarmbox:%s; the config asks for swarmbox:dev; "
                      "run `swarmbox reset`" % VERSION, lines)
        self.assertIn("the workspace in the config is %s, this box uses %s; run `swarmbox reset` to switch" % (ws2, self.ws), lines)
        self.assertIn("the variables changed on the host; run `swarmbox reset` to apply them", lines)
        self.assertNotIn(CANARY, p.stdout + p.stderr)   # the values never appear

    def test_a_difference_in_a_key_without_a_label_gets_the_generic_line(self):
        labels = self.labels_of()
        p = self.explain(labels, env={"SWARMBOX_HOSTNAME": "devbox"})
        self.assertEqual(p.returncode, 1)
        lines = p.stdout.strip().split("\n")[1:]
        self.assertEqual(len(lines), 1)
        self.assertIn("another creation setting changed", lines[0])
        self.assertIn("run `swarmbox reset` to apply", lines[0])

    def test_no_labels_is_no_box_exit_5(self):
        p = self.run_h("fingerprint", "--explain")
        self.assertEqual(p.returncode, 5)
        self.assertIn("no box", p.stderr)

    def test_labels_without_a_fingerprint_label_is_a_box_not_made_by_this_design_exit_5(self):
        p = self.run_h("fingerprint", "--label=swarmbox.image=x")
        self.assertEqual(p.returncode, 5)

    def test_without_explain_the_exit_code_still_compares(self):
        labels = self.labels_of()
        self.assertEqual(self.run_h("fingerprint", *labels).returncode, 0)
        self.assertEqual(self.run_h("fingerprint", *labels, env={"SWARMBOX_WEB_PORT": "8000"}).returncode, 1)

    def test_label_option_forms_and_errors(self):
        labels = self.labels_of()
        two = []
        for l in labels:
            two += ["--label", l[len("--label="):]]
        self.assertEqual(self.run_h("fingerprint", *two).returncode, 0)
        self.assertEqual(self.run_h("fingerprint", "--label").returncode, 2)
        self.assertEqual(self.run_h("fingerprint", "--label", "novalue").returncode, 2)
        self.assertEqual(self.run_h("fingerprint", "--bogus").returncode, 2)


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

    def test_the_default_workspace_is_home_swarmbox(self):
        p = self.cf(drop=("SWARMBOX_WORKSPACE",))
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertTrue(os.path.isdir(os.path.join(self.home, "swarmbox")))
        self.assertIn(os.path.join(self.home, "swarmbox") + ":/home/agent", p.stdout.split("\n"))

    @unittest.skipIf(os.geteuid() == 0, "root can write everywhere")
    def test_not_writable_is_exit_4(self):
        ws = os.path.join(self.tmp, "ro")
        os.mkdir(ws)
        os.chmod(ws, 0o555)
        p = self.cf(env={"SWARMBOX_WORKSPACE": ws})
        self.assertEqual(p.returncode, 4)
        self.assertEqual(p.stdout, "")
        self.assertEqual(p.stderr.strip(), "swarmbox: workspace %s is not writable by this user" % ws)

    @unittest.skipIf(os.geteuid() == 0, "root can write everywhere")
    def test_a_workspace_that_cannot_be_created_is_exit_4(self):
        ro = os.path.join(self.tmp, "ro")
        os.mkdir(ro)
        os.chmod(ro, 0o555)
        ws = os.path.join(ro, "sub", "ws")
        p = self.cf(env={"SWARMBOX_WORKSPACE": ws})
        self.assertEqual(p.returncode, 4)
        self.assertIn("cannot create the workspace folder", p.stderr)
        self.assertEqual(p.stdout, "")

    def test_a_file_is_not_a_workspace_exit_4(self):
        f = os.path.join(self.tmp, "afile")
        open(f, "w").close()
        p = self.cf(env={"SWARMBOX_WORKSPACE": f})
        self.assertEqual(p.returncode, 4)
        self.assertIn("is not a folder", p.stderr)

    def test_a_relative_workspace_is_made_absolute_against_the_current_folder(self):
        cwd = os.path.join(self.tmp, "cwd")
        os.mkdir(cwd)
        p = self.cf(env={"SWARMBOX_WORKSPACE": "rel/ws"}, cwd=cwd)
        self.assertEqual(p.returncode, 0, p.stderr)
        want = os.path.join(cwd, "rel", "ws")
        self.assertTrue(os.path.isdir(want))
        self.assertIn(want + ":/home/agent", p.stdout.split("\n"))
        self.assertIn("swarmbox.workspace=" + want, p.stdout.split("\n"))

    def test_a_tilde_workspace_is_expanded(self):
        p = self.cf(env={"SWARMBOX_WORKSPACE": "~/tws"})
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertTrue(os.path.isdir(os.path.join(self.home, "tws")))

    def test_a_trailing_slash_is_dropped(self):
        p = self.cf(env={"SWARMBOX_WORKSPACE": self.ws + "/"})
        self.assertIn(self.ws + ":/home/agent", p.stdout.split("\n"))

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

    def test_wsl_does_not_refuse_other_mnt_paths_or_linux_paths(self):
        if os.path.exists("/mnt/wsl") or os.path.exists("/mnt/data"):
            self.skipTest("a real /mnt/wsl or /mnt/data exists here; the test must not create anything under it")
        self.set_wsl(True)
        for ws in ("/mnt/wsl/swarmbox-test-never/x", "/mnt/data/swarmbox-test-never", "/mntx/c/x", "/mnt/cc/x"):
            if os.path.exists(ws.rsplit("/", 1)[0]) and os.access(ws.rsplit("/", 1)[0], os.W_OK):
                self.skipTest("%s is writable here" % ws)
            p = self.cf(env={"SWARMBOX_WORKSPACE": ws})
            self.assertNotIn("Windows drive", p.stderr, ws)
        p = self.cf()    # a Linux path under WSL is fine
        self.assertEqual(p.returncode, 0, p.stderr)

    def test_a_symlink_to_a_windows_drive_is_refused_too_on_wsl(self):
        # the link target is checked through `pwd -P`; here the target does not exist, so only the written path counts
        self.set_wsl(True)
        link = os.path.join(self.tmp, "link")
        os.symlink("/mnt/c/Users/me", link)
        p = self.cf(env={"SWARMBOX_WORKSPACE": link})
        self.assertEqual(p.returncode, 4)
        self.assertIn("Windows drive", p.stderr)

    def test_not_wsl_a_mnt_c_path_is_allowed(self):
        if os.geteuid() == 0 or os.path.exists("/mnt/c") or os.path.exists("/mnt/z"):
            self.skipTest("root or a real /mnt/c here: the test must not create anything under /mnt")
        self.set_wsl(False)
        p = self.cf(env={"SWARMBOX_WORKSPACE": "/mnt/z/x"})
        # not refused as a Windows drive: it fails later only because /mnt is not writable here
        self.assertNotIn("Windows drive", p.stderr)
        self.assertEqual(p.returncode, 4)
        self.assertIn("cannot create the workspace folder", p.stderr)

    def test_the_wsl_probe_handles_the_variants_of_the_kernel_string(self):
        for s, wsl in (("Linux version 4.4.0-19041-Microsoft (Microsoft@Microsoft.com)", True),
                       ("Linux version 5.15.90.1-microsoft-standard-WSL2", True),
                       ("Linux version 6.1.0-18-amd64", False), ("", False)):
            with open(self.procversion, "w") as f:
                f.write(s + "\n")
            p = self.cf(env={"SWARMBOX_WORKSPACE": "/mnt/c/Users/me/swarmbox"})
            self.assertEqual("Windows drive" in p.stderr, wsl, s)

    def test_a_missing_proc_version_means_not_wsl(self):
        os.unlink(self.procversion)
        p = self.cf(env={"SWARMBOX_WORKSPACE": "/mnt/z/x"})
        self.assertNotIn("Windows drive", p.stderr)

    def test_the_real_proc_version_of_this_machine_is_read_without_the_override(self):
        want = False
        try:
            with open("/proc/version") as f:
                want = "microsoft" in f.read().lower()
        except OSError:
            pass
        p = self.cf(env={"SWARMBOX_WORKSPACE": "/mnt/c/Users/me/swarmbox"}, drop=("SWARMBOX_TEST_PROC_VERSION",))
        self.assertEqual("Windows drive" in p.stderr, want)
        self.assertFalse(os.path.exists("/mnt/c/Users/me/swarmbox"))

    def test_the_fingerprint_does_not_check_or_create_the_workspace(self):
        self.set_wsl(True)
        p = self.run_h("fingerprint", env={"SWARMBOX_WORKSPACE": "/mnt/c/Users/me/swarmbox"})
        self.assertEqual(p.returncode, 0)
        p = self.run_h("fingerprint", env={"SWARMBOX_WORKSPACE": os.path.join(self.tmp, "nope")})
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "nope")))


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


class ShellMatrixTest(Base):
    def test_the_required_shells_are_present(self):
        names = interpreters()
        for need in ("dash", "bash --posix", "busybox sh"):
            if need not in names:
                self.skipTest("[unverified] %s is not installed here; install it to run this test" % need)

    def test_create_flags_and_fingerprint_are_identical_under_every_shell(self):
        self.make_helper("clasp\t43323\n")
        env = {"SWARMBOX_WITH": "clasp", "SWARMBOX_PORTS": "3000,0.0.0.0:80:80", "SWARMBOX_ENV_KEYS": "K1,K2", "K1": CANARY,
               "SWARMBOX_BROWSER_URL": "9222", "SWARMBOX_INIT": "1", "SWARMBOX_HOST_ACCESS": "1", "SWARMBOX_TZ": "Europe/Lisbon"}
        self.cf(env=env)    # the first call creates the workspace and says so; the compared calls find it
        ref = self.cf(env=env)
        self.assertEqual(ref.returncode, 0, ref.stderr)
        ref_fp = self.run_h("fingerprint", env=env)
        ref_ex = self.run_h("fingerprint", "--explain", "--label=swarmbox.fingerprint=00", env=env)
        for name, prefix in interpreters().items():
            with self.subTest(shell=name):
                p = self.cf(env=env, shell=prefix)
                self.assertEqual((p.returncode, p.stdout, p.stderr), (ref.returncode, ref.stdout, ref.stderr))
                f = self.run_h("fingerprint", env=env, shell=prefix)
                self.assertEqual((f.returncode, f.stdout), (ref_fp.returncode, ref_fp.stdout))
                e = self.run_h("fingerprint", "--explain", "--label=swarmbox.fingerprint=00", env=env, shell=prefix)
                self.assertEqual((e.returncode, e.stdout), (ref_ex.returncode, ref_ex.stdout))

    def test_errors_are_identical_under_every_shell(self):
        for name, prefix in interpreters().items():
            with self.subTest(shell=name):
                self.assertEqual(self.cf(env={"SWARMBOX_INIT": "auto"}, shell=prefix).returncode, 2)
                self.assertEqual(self.cf(env={"SWARMBOX_PORTS": "x"}, shell=prefix).returncode, 2)
                self.make_helper(None)
                self.assertEqual(self.cf(shell=prefix).returncode, 3)
                self.make_helper("")
                self.set_wsl_and_check(prefix)

    def set_wsl_and_check(self, prefix):
        with open(self.procversion, "w") as f:
            f.write(WSL_VERSION + "\n")
        p = self.cf(env={"SWARMBOX_WORKSPACE": "/mnt/c/x"}, shell=prefix)
        self.assertEqual(p.returncode, 4)
        with open(self.procversion, "w") as f:
            f.write(PLAIN_VERSION + "\n")


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

    def test_the_helper_calls_no_podman_in_this_slice(self):
        with open(HELPER_SRC) as f:
            lines = [l for l in f.read().split("\n") if not l.lstrip().startswith("#")]
        self.assertFalse([l for l in lines if l.strip().startswith("podman ") or "podman run" in l])


if __name__ == "__main__":
    unittest.main()
