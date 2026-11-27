"""`create-flags`, `fingerprint` and the workspace checks of the host helper.

The helper runs as a real program, copied with a fixture `addon-ports` into a mktemp folder (the repository has none: the
image build writes it), with a cleared environment: PATH, a mktemp HOME and the variables a case sets. Nothing calls
Podman. Nothing touches the real home or a Windows drive: the WSL probe and the OS are test-overridable
(SWARMBOX_TEST_PROC_VERSION, SWARMBOX_TEST_OS), the local time file is SWARMBOX_LOCALTIME_FILE.
Run: python3 tests/fast/test_host_create_flags.py
"""
import concurrent.futures
import itertools
import os
import random
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "support"))
from helpers import DEFAULT_NAME, DEFAULT_IMAGE_REPO, DEFAULT_VOLUME  # noqa: E402
from host_support import CreateFlagsBase as _CreateFlagsBase, CANARY, DEFAULTS_SRC, FIXTURES, HELPER_SRC, PLAIN_VERSION, TOKEN, VERSION, VERSION_SRC, WINDOWS_DRIVE_MSG, WSL_VERSION, env_hash, fingerprint, pairs_of, values  # noqa: E402


_SHARED_DIR = None


def setUpModule():
    global _SHARED_DIR
    _SHARED_DIR = os.path.realpath(tempfile.mkdtemp(prefix="swarmbox-test-cf-sh."))
    hdir = os.path.join(_SHARED_DIR, "helper")
    os.makedirs(hdir)
    shutil.copy(HELPER_SRC, os.path.join(hdir, "swarmbox-host"))
    os.chmod(os.path.join(hdir, "swarmbox-host"), 0o755)
    shutil.copy(VERSION_SRC, os.path.join(hdir, "VERSION"))
    shutil.copy(DEFAULTS_SRC, os.path.join(hdir, "DEFAULTS"))
    with open(os.path.join(hdir, "addon-ports"), "w") as f:
        f.write("")
    open(os.path.join(_SHARED_DIR, "localtime"), "w").close()
    with open(os.path.join(_SHARED_DIR, "proc-version"), "w") as f:
        f.write(PLAIN_VERSION + "\n")


def tearDownModule():
    global _SHARED_DIR
    if _SHARED_DIR:
        shutil.rmtree(_SHARED_DIR, True)
        _SHARED_DIR = None


class Base(_CreateFlagsBase):
    def setUp(self):
        if _SHARED_DIR is None:
            super().setUp()
            return
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="swarmbox-test-cflags."))
        self.addCleanup(self._cleanup)
        self.home = os.path.join(self.tmp, "home")
        os.mkdir(self.home)
        self.assertNotEqual(os.path.realpath(self.home), self.real_home)
        self.ws = os.path.join(self.tmp, "ws")
        self.hdir = os.path.join(_SHARED_DIR, "helper")
        self.localtime = os.path.join(_SHARED_DIR, "localtime")
        self.procversion = os.path.join(_SHARED_DIR, "proc-version")
        self.cfgroot = os.path.join(self.home, ".config", "swarmbox")

    def make_helper(self, addon_ports, version=True):
        self.hdir = os.path.join(self.tmp, "helper")
        super().make_helper(addon_ports, version=version)


def _par(fn, items, max_workers=8):
    items = list(items)
    if len(items) <= 1 or os.environ.get("SWARMBOX_RUNNER_PARALLEL"):
        return [fn(x) for x in items]
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(max_workers, len(items))) as pool:
        return list(pool.map(fn, items))

# ============================================================================ the flag set: golden files

class GoldenTest(Base):
    def golden(self, name, subs):
        with open(os.path.join(FIXTURES, name)) as f:
            text = f.read()
        subs = dict(subs, **{"@NAME@": DEFAULT_NAME, "@IMAGE_REPO@": DEFAULT_IMAGE_REPO})   # from container/host/DEFAULTS
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

# ============================================================================ one test per key of the config table

class KeyTest(Base):
    def setUp(self):
        super().setUp()
        os.makedirs(self.ws, exist_ok=True)

    def test_name_names_the_volume_and_the_label_not_a_flag(self):
        out, out2 = _par(lambda e: self.flags(env=e), (None, {"SWARMBOX_NAME": "other"}))
        self.assertIn(("-v", (DEFAULT_VOLUME + ":/home/agent/.local/share/containers")), pairs_of(out))
        self.assertIn(("-e", "SWARMBOX_NAME=" + DEFAULT_NAME), pairs_of(out))
        self.assertNotIn("--name", out)   # `up` adds --name itself
        self.assertIn(("-v", "other-containers:/home/agent/.local/share/containers"), pairs_of(out2))
        self.assertIn(("-e", "SWARMBOX_NAME=other"), pairs_of(out2))

    def test_tz_local_zone_and_off(self):
        dflt, lisbon, off = _par(lambda e: self.flags(env=e), (None, {"SWARMBOX_TZ": "Europe/Lisbon"}, {"SWARMBOX_TZ": "off"}))
        self.assertIn("--tz=local", dflt)
        self.assertIn("--tz=Europe/Lisbon", lisbon)
        self.assertFalse([l for l in off if l.startswith("--tz")])

    def test_init_1_emits_init_0_does_not(self):
        on, off = _par(lambda e: self.flags(env=e), ({"SWARMBOX_INIT": "1"}, {"SWARMBOX_INIT": "0"}))
        self.assertIn("--init", on)
        self.assertNotIn("--init", off)

    def test_ports_default_is_loopback_only(self):
        out = self.flags(env={"SWARMBOX_PORTS": "3000"})
        self.assertIn(("-p", "127.0.0.1:3000:3000"), pairs_of(out))
        self.assertIn(("--label", "swarmbox.ports=127.0.0.1:3000:3000"), pairs_of(out))

    def test_web_port_maps_to_7681_on_loopback_and_web_0_drops_it(self):
        dflt, p8000, noweb = _par(lambda e: self.flags(env=e), (None, {"SWARMBOX_WEB_PORT": "8000"}, {"SWARMBOX_WEB": "0"}))
        self.assertIn(("-p", "127.0.0.1:7681:7681"), pairs_of(dflt))
        self.assertIn(("-p", "127.0.0.1:8000:7681"), pairs_of(p8000))
        self.assertFalse([v for v in values(noweb, "-p") if v.endswith(":7681")])

    def agent_of(self, out):
        return [v for k, v in pairs_of(out) if k == "-e" and v.startswith("SWARMBOX_AGENT=")]

    def test_the_default_agent_is_the_agent_setting(self):
        out = self.flags(env={"SWARMBOX_AGENT": "gemini", "SWARMBOX_WITH": "claude,gemini"})
        self.assertEqual(self.agent_of(out), ["SWARMBOX_AGENT=gemini"])

    def test_without_an_agent_setting_no_agent_is_recorded_and_with_goes_as_it_is(self):
        # the host cannot tell an agent from another addon (WITH=go,claude): the box picks the first agent of WITH from its registry
        withs = ("claude", "go,claude")
        outs = _par(lambda w: self.flags(env={"SWARMBOX_WITH": w}), withs)
        for with_, out in zip(withs, outs):
            with self.subTest(with_=with_):
                self.assertEqual(self.agent_of(out), [])
                self.assertIn("SWARMBOX_WITH=" + with_, values(out, "-e"))

    def test_the_agent_setting_wins_even_when_it_is_not_in_with(self):
        out = self.flags(env={"SWARMBOX_AGENT": "opencode", "SWARMBOX_WITH": "claude"})
        self.assertEqual(self.agent_of(out), ["SWARMBOX_AGENT=opencode"])

    def test_with_neither_agent_nor_with_no_default_agent_is_recorded(self):
        self.assertEqual(self.agent_of(self.flags()), [])

    def test_env_keys_are_passed_by_name_only_when_set(self):
        out = self.flags(env={"SWARMBOX_ENV_KEYS": "SET_ONE,UNSET_ONE,EMPTY_ONE", "SET_ONE": CANARY, "EMPTY_ONE": ""})
        es = values(out, "-e")
        self.assertIn("SET_ONE", es)
        self.assertIn("EMPTY_ONE", es)       # set, but empty: still passed (it is set)
        self.assertNotIn("UNSET_ONE", es)
        self.assertNotIn(CANARY, "\n".join(out))

class AlwaysAppliedTest(Base):
    def setUp(self):
        super().setUp()
        os.makedirs(self.ws, exist_ok=True)

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
        # the real throwaway-box smoke test runs inside the development box (a nested level), where /dev/net/tun,
        # the unmasked /proc and a private UTS namespace (--hostname) are refused; the switch removes exactly those three
        # and adds the variable the box's serve reads for the same purpose. Without the switch nothing changes (the goldens).
        b_out, l_out = _par(lambda e: self.flags(env=e), (None, {"SWARMBOX_TEST_NO_NESTED": "1"}))
        base = pairs_of(b_out)
        low = pairs_of(l_out)
        self.assertEqual(sorted(set(base) - set(low)),
                         sorted([("--device", "/dev/net/tun"), ("--security-opt", "unmask=/proc/*"), ("--hostname", DEFAULT_NAME)]))
        self.assertEqual(sorted(set(low) - set(base)), [("-e", "SWARMBOX_TEST_NO_NESTED=1")])
        self.assertEqual(len(low), len(base) - 3 + 1)

    def test_macos_extras_only_with_the_override(self):
        dflt, darwin, linux = _par(lambda e: self.flags(env=e), (None, {"SWARMBOX_TEST_OS": "Darwin"}, {"SWARMBOX_TEST_OS": "Linux"}))
        self.assertNotIn(("--security-opt", "label=disable"), pairs_of(dflt))
        self.assertIn(("--security-opt", "label=disable"), pairs_of(darwin))
        self.assertNotIn(("--security-opt", "label=disable"), pairs_of(linux))

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
        # the read loop of the generated function, in a real sh: one line must become one argument, byte for byte
        flags = os.path.join(self.tmp, "flags")
        with open(flags, "w") as f:
            f.write(p.stdout)
        script = ('f=$1\nset --\nwhile IFS= read -r line; do set -- "$@" "$line"; done < "$f"\n'
                  'printf "%s\\0" "$@"\n')
        shells = [sh for sh in (["sh"], ["dash"], ["bash", "--posix"], ["busybox", "sh"]) if shutil.which(sh[0])]
        results = _par(lambda sh: (sh, subprocess.run(sh + ["-c", script, "x", flags], capture_output=True, timeout=30)), shells)
        for sh, r in results:
            self.assertEqual(r.returncode, 0)
            got = r.stdout.decode().split("\0")[:-1]
            self.assertEqual(got, lines, sh)

# ============================================================================ addon ports

class AddonPortsTest(Base):
    TP = "clasp\t43323\ngcloud\t8085\ngcloud\t8086\n"

    def test_with_selects_only_its_addons_ports(self):
        self.make_helper(self.TP)
        out = self.flags(env={"SWARMBOX_WITH": "clasp"})
        ps = values(out, "-p")
        self.assertIn("127.0.0.1:43323:43323", ps)
        self.assertFalse([p for p in ps if ":8085:" in p])

    def test_a_port_the_user_already_publishes_is_not_added_twice(self):
        self.make_helper(self.TP)
        os.makedirs(self.ws, exist_ok=True)
        users = ("43323", "43323:43323", "127.0.0.1:43323:43323", "0.0.0.0:43323:80")
        outs = _par(lambda u: self.flags(env={"SWARMBOX_WITH": "clasp", "SWARMBOX_PORTS": u}), users)
        for user, out in zip(users, outs):
            ps = [p for p in values(out, "-p") if not p.endswith(":7681")]
            self.assertEqual(len([p for p in ps if p.split(":")[1] == "43323"]), 1, (user, ps))

    def test_a_missing_addon_ports_is_a_corrupted_helper_exit_3(self):
        self.make_helper(None)
        p = self.cf()
        self.assertEqual(p.returncode, 3)
        self.assertEqual(p.stdout, "")
        self.assertIn("addon-ports", p.stderr)
        self.assertIn("swarmbox update", p.stderr)

# ============================================================================ ports and BROWSER_URL parity (v0.1.0 flags)

class PortsParityTest(Base):
    def user_ports(self, spec):
        out = self.flags(env={"SWARMBOX_PORTS": spec})
        return [p for p in values(out, "-p") if not p.endswith(":7681")]

    def test_port_forms(self):
        os.makedirs(self.ws, exist_ok=True)
        table = {
            "3000": ["127.0.0.1:3000:3000"],
            "3000:3000": ["127.0.0.1:3000:3000"],
            "8080:80": ["127.0.0.1:8080:80"],
            "127.0.0.1:3000:3000": ["127.0.0.1:3000:3000"],
            "192.168.1.5:3000:3000": ["192.168.1.5:3000:3000"],
            "3000,8080:80": ["127.0.0.1:3000:3000", "127.0.0.1:8080:80"],
        }
        items = list(table.items())
        gots = _par(lambda kv: self.user_ports(kv[0]), items)
        for (spec, want), got in zip(items, gots):
            self.assertEqual(got, want, spec)

    def test_invalid_ports_are_exit_2(self):
        specs = ("abc", "1.2.3:80:80", "999.1.1.1:80:80", "0", "70000", "1:2:3:4", "3000,", "0.0.0.0::80", "a.b.c.d:1:1")
        ps = _par(lambda s: self.cf(env={"SWARMBOX_PORTS": s}), specs, max_workers=9)
        for spec, p in zip(specs, ps):
            self.assertEqual(p.returncode, 2, spec)
            self.assertEqual(p.stdout, "", spec)


class BrowserUrlParityTest(Base):
    def url(self, value=None, args=()):
        env = {} if value is None else {"SWARMBOX_BROWSER_URL": value}
        out = self.flags(env=env, args=args)
        got = [e.split("=", 1)[1] for e in values(out, "-e") if e.startswith("SWARMBOX_BROWSER_URL=")]
        return got[0] if got else None

    def test_forms(self):
        os.makedirs(self.ws, exist_ok=True)
        table = {
            "9222": "http://host.containers.internal:9222",
            "1234": "http://host.containers.internal:1234",
            "192.168.1.100:9222": "http://192.168.1.100:9222",
            "chrome.lan:9222": "http://chrome.lan:9222",
            "http://chrome.lan:9222": "http://chrome.lan:9222",
            "https://chrome.lan/x": "https://chrome.lan/x",
        }
        items = list(table.items())
        gots = _par(lambda kv: self.url(kv[0]), items)
        for (given, want), got in zip(items, gots):
            self.assertEqual(got, want, given)

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
        chosen = combos[:24]       # the product has 17280 combinations and one run costs a process: a seeded sample is enough
        os.makedirs(self.ws, exist_ok=True)
        envs = [dict(combo, A_ONE=CANARY, SWARMBOX_WORKSPACE=self.ws) for combo in chosen]
        results = _par(lambda e: (self.cf(env=e), e), envs, max_workers=12)
        for p, env in results:
            self.check(p, env)
        for k, vs in axes:      # the sample must have met every value of every axis (a changed seed or axis list could lose one)
            self.assertEqual({dict(c)[k] for c in chosen}, set(vs), k)

# ============================================================================ secrets

class SecretsTest(Base):
    def everything(self, env, cfg=None):
        os.makedirs(self.ws, exist_ok=True)
        if cfg is not None:
            os.makedirs(self.cfgroot, exist_ok=True)
            f = os.path.join(self.cfgroot, "config")
            with open(f, "w") as fh:
                fh.write(cfg)
            os.chmod(f, 0o600)
        ps = _par(lambda args: self.run_h(*args, env=env), (["create-flags"], ["fingerprint"], ["fingerprint", "--explain"]))
        return "\n".join(p.stdout + p.stderr for p in ps)

    def test_the_cloudflare_token_never_appears(self):
        os.makedirs(self.ws, exist_ok=True)
        h_cfg = os.path.join(self.tmp, "h-cfgtok")
        cf = os.path.join(h_cfg, ".config", "swarmbox", "config")
        os.makedirs(os.path.dirname(cf), exist_ok=True)
        with open(cf, "w") as fh:
            fh.write("CLOUDFLARE_TUNNEL_TOKEN=" + TOKEN + "\n")
        os.chmod(cf, 0o600)
        cmds = (["create-flags"], ["fingerprint"], ["fingerprint", "--explain"])
        calls = [(a, {"SWARMBOX_CLOUDFLARE_TUNNEL_TOKEN": TOKEN}) for a in cmds] + [(a, {"HOME": h_cfg}) for a in cmds]
        ps = _par(lambda c: self.run_h(*c[0], env=c[1]), calls, max_workers=6)
        self.assertNotIn(TOKEN, "\n".join(p.stdout + p.stderr for p in ps[:3]))
        self.assertNotIn(TOKEN, "\n".join(p.stdout + p.stderr for p in ps[3:]))

    def test_env_keys_values_never_appear_but_the_hash_follows_them(self):
        os.makedirs(self.ws, exist_ok=True)
        env = {"SWARMBOX_ENV_KEYS": "MY_SECRET,OTHER", "MY_SECRET": CANARY}
        changed = dict(env, MY_SECRET=CANARY + "2")
        unrelated = dict(env, UNRELATED="x")
        calls = (
            (["create-flags"], env),
            (["fingerprint"], env),
            (["fingerprint", "--explain"], env),
            (["fingerprint"], changed),
            (["fingerprint"], unrelated),
        )
        p_cf, p_fp, p_ex, p_chg, p_unr = _par(lambda c: self.run_h(*c[0], env=c[1]), calls)
        self.assertNotIn(CANARY, "\n".join(p.stdout + p.stderr for p in (p_cf, p_fp, p_ex)))
        self.assertEqual(p_cf.returncode, 0, p_cf.stderr)
        out = p_cf.stdout.split("\n")[:-1] if p_cf.stdout else []
        self.assertIn("MY_SECRET", values(out, "-e"))
        want = env_hash([("MY_SECRET", CANARY), ("OTHER", None)])
        self.assertIn(("--label", "swarmbox.env-hash=" + want), pairs_of(out))
        # a changed value changes the env-hash and the fingerprint; an unrelated variable changes neither
        for p in (p_fp, p_chg, p_unr):
            self.assertEqual(p.returncode, 0, p.stderr)
        self.assertNotEqual(p_fp.stdout.strip(), p_chg.stdout.strip())
        self.assertEqual(p_fp.stdout.strip(), p_unr.stdout.strip())

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
        os.makedirs(self.ws, exist_ok=True)
        cases = (
            None,
            {"SWARMBOX_STARSHIP": "0"}, {"SWARMBOX_UPDATE_CHECK": "0"}, {"SWARMBOX_ADDONS_DIR": "/x"},
            {"SWARMBOX_WEB_DOMAIN": "x.example"}, {"SWARMBOX_WEB_HOSTNAME": "h"},
            {"SWARMBOX_CLOUDFLARED_IMAGE": "img"}, {"SWARMBOX_CLOUDFLARE_TUNNEL_TOKEN": TOKEN},
            {"SWARMBOX_UNKNOWN": "1"},
        )
        fps = _par(lambda e: self.fp(env=e), cases, max_workers=9)
        base = fps[0]
        for env, got in zip(cases[1:], fps[1:]):
            self.assertEqual(got, base, next(iter(env)))

class ExplainTest(Base):
    def labels_of(self, env=None, cfg=None):
        out = self.flags(env=env, cfg=cfg)
        return ["--label=" + v for v in values(out, "--label")]

    def explain(self, labels, env=None, cfg=None):
        p = self.run_h("fingerprint", "--explain", *labels, env=env, cfg=cfg)
        return p

    def test_same_configuration_prints_the_hash_only_and_exits_0(self):
        os.makedirs(self.ws, exist_ok=True)
        labels, want = _par(lambda fn: fn(), (self.labels_of, self.fp))
        p = self.explain(labels)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(p.stdout.strip(), want)

    def test_ports_difference_uses_the_d30_wording(self):
        os.makedirs(self.ws, exist_ok=True)
        labels, want = _par(lambda fn: fn(), (
            lambda: self.labels_of(env={"SWARMBOX_PORTS": "3000"}),
            lambda: self.fp(env={"SWARMBOX_PORTS": "3000,8080"}),
        ))
        p = self.explain(labels, env={"SWARMBOX_PORTS": "3000,8080"})
        self.assertEqual(p.returncode, 1)
        lines = p.stdout.strip().split("\n")
        self.assertEqual(lines[0], want)
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

    # --- WSL, with a fake /proc/version; nothing under /mnt is ever created by these tests
    def set_wsl(self, on):
        self.procversion = os.path.join(self.tmp, "proc-version")
        with open(self.procversion, "w") as f:
            f.write((WSL_VERSION if on else PLAIN_VERSION) + "\n")

    def test_wsl_refuses_a_windows_drive_workspace_with_the_d34_text(self):
        self.set_wsl(True)
        wss = ("/mnt/c/Users/me/swarmbox", "/mnt/d/x", "/mnt/C/Users", "/mnt/c", "/mnt/z/deep/er/path")
        ps = _par(lambda ws: self.cf(env={"SWARMBOX_WORKSPACE": ws}), wss)
        for ws, p in zip(wss, ps):
            self.assertEqual(p.returncode, 4, ws)
            self.assertEqual(p.stdout, "", ws)
            self.assertEqual(p.stderr.strip(), WINDOWS_DRIVE_MSG % ws, ws)
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
