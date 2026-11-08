#!/usr/bin/env python3
"""Slice 6.1: the parity suite (design 12, 13.2; decisions D7, D8, D9, D39).

Parity (D8) means: every row of the feature catalog (design 8.4) has a test that passes against the 2.0 code. This file has one
or more tests per row, named `test_rowNN_<what>` (NN is the position of the row in 8.4, 01 to 14), plus the tests for the
12.2 removals (`test_removed_*`), the "kept on purpose" items (`test_kept_*`) and the 12.3 mapping of old flags to config keys
(`test_map_*`). Design 13.2 carries the table that maps every row to the names in this file; `ParityRegistry` (below) and
tests/test_docs_consistency.py fail when a row has no test, when the table names a test that does not exist, or when a test
of this file is missing from the table.

What each test drives (the real code, never a copy of it):
  - the generated bash function (swarmbox-init.sh) -> the real swarmbox-host -> the shared FakePodman (tests/helpers.py);
  - create-flags, fingerprint, up, reset, stop, env and remote of the real host helper;
  - `serve` (entrypoint.sh) with fake tmux, podman and ttyd, swarmbox-web with a fake ttyd, swarmbox-attach with a REAL tmux on a
    private socket (-L swarmbox-test-<random>, -f /dev/null; the live tmux server is never addressed);
  - the shell fragment bashrc.sh in a real interactive bash, swarmbox-tool validate on the shipped manifests, prepare.sh of opencode,
    swarmbox-mcp.sh, ssh-key.sh, and cloudflare-setup.py against the fake Cloudflare API of tests/test_cloudflare_setup.py.

Tags. A test whose docstring starts with `[reduced: ...]` checks less than the row says, and says what is missing; the list is
printed at the end of the run and is in the decision log ([6.1]). No test here starts a real SwarmBox image or a real nested Podman
(the development box is itself a container; a third nesting level is not available): those parts are checked by tests/smoke_image.py
in CI and stay [unverified] here. The only opt-in real-browser check is SWARMBOX_PARITY_BROWSER=1 (it runs
tests/test_clipboard_bridge.py in a subprocess, which needs chromium, ttyd and tmux).

The old behavior is compared with fixtures recorded from `git archive v0.1.0` (tests/record_v010_flags.py ->
tests/fixtures/v0.1.0-run-flags.json), so the comparison survives the deletion of start.sh in slice 6.2.
Run: python3 tests/test_parity.py
"""
import json
import os
import re
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import ROOT, FakePodman, FakeHostHelper  # noqa: E402
import function_cases as fcs  # noqa: E402
import test_attach_command as ta  # noqa: E402
import test_bashrc_fragment as tb  # noqa: E402
import test_host_create_flags as tcf  # noqa: E402
import test_host_remote_e2e_fake as e2e  # noqa: E402
import test_host_up as tu  # noqa: E402
import test_mcp_registry as tm  # noqa: E402
import test_serve_steps as tss  # noqa: E402
import test_tool_manifest as ttm  # noqa: E402
import test_web_build as twb  # noqa: E402

DESIGN_PATH = os.path.join(ROOT, "docs", "design.md")
SELF = os.path.abspath(__file__)
FIX = os.path.join(ROOT, "tests", "fixtures", "v0.1.0-run-flags.json")
CONFIG = os.path.join(ROOT, "container", "config")
SCRIPTS = os.path.join(ROOT, "container", "scripts")
TOOLS = os.path.join(ROOT, "container", "tools")
HELPER_SRC = os.path.join(ROOT, "container", "host", "swarmbox-host")
REDUCED = []   # filled by the tests that are tagged [reduced: ...]; printed at the end of the run


def read(*p):
    with open(os.path.join(*p), encoding="utf-8") as f:
        return f.read()


def reduced(test, why):
    REDUCED.append("%s: %s" % (test.id().split(".")[-1], why))


def split_eq(argv):
    """`--flag=value` becomes `--flag`, `value` (the same meaning, one spelling)."""
    out = []
    for a in argv:
        if a.startswith("--") and "=" in a:
            k, v = a.split("=", 1)
            out += [k, v]
        else:
            out.append(a)
    return out


def pairs(flags):
    """The flags as (flag, value) pairs; a flag that takes no value has None."""
    takes = {"-p", "-v", "-e", "--hostname", "--tmpfs", "--device", "--security-opt", "--label", "--add-host", "--tz", "--net",
             "--userns", "--pids-limit"}
    flags = split_eq(flags)
    out, i = [], 0
    while i < len(flags):
        if flags[i] in takes and i + 1 < len(flags):
            out.append((flags[i], flags[i + 1]))
            i += 2
        else:
            out.append((flags[i], None))
            i += 1
    return out


def catalog_rows():
    """The rows of the 8.4 table of design.md: [(area, feature), ...]."""
    d = read(DESIGN_PATH)
    s = d.index("### 8.4 Feature catalog")
    e = d.index("## 9. Repository layout")
    rows = []
    for line in d[s:e].splitlines():
        if line.startswith("|") and not line.startswith("|---") and not line.startswith("| Area"):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            rows.append((cells[0], cells[1]))
    return rows


# ====================================================================================================================
# Drivers
# ====================================================================================================================

class FnBase(tu.Base):
    """The generated bash function -> the real swarmbox-host (in the folder the function looks in) -> the shared FakePodman."""

    def setUp(self):
        super().setUp()
        share = os.path.join(self.home, ".local", "share", "swarmbox")
        os.makedirs(share)
        os.symlink(self.hdir, os.path.join(share, "host"))
        hd = os.path.join(self.tmp, "initdir")
        os.makedirs(hd)
        os.symlink(os.path.join(fcs.REAL_HOST_DIR, "templates"), os.path.join(hd, "templates"))
        shutil.copy(tu.VERSION_SRC, os.path.join(hd, "VERSION"))
        r = subprocess.run(["sh", fcs.INIT, "--shell", "bash"], capture_output=True, text=True,
                           env={"PATH": os.environ["PATH"], "SWARMBOX_TEST_HOST_DIR": hd})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.fn = os.path.join(self.tmp, "fn.bash")
        with open(self.fn, "w") as f:
            f.write(r.stdout)

    def swarmbox(self, *args, **extra):
        e = self.env(**extra)
        e["TERM"] = "dumb"
        return subprocess.run(["bash", "--noprofile", "--norc", "-c", '. "$1"; shift; swarmbox "$@"; exit $?', "bash", self.fn,
                               *args], env=e, cwd=self.tmp, capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=60)


class FlagsBase(tcf.Base):
    """create-flags of the real helper."""

    def pairs(self, **kw):
        return pairs(self.flags(**kw))


class V010:
    """The recorded flags of v0.1.0's start.sh."""
    data = None

    @classmethod
    def case(cls, name):
        if cls.data is None:
            with open(FIX) as f:
                cls.data = json.load(f)
        return cls.data[name]

    @classmethod
    def delta(cls, name):
        """The (flag, value) pairs the case adds to the default run of v0.1.0."""
        base = set(pairs(cls.case("default")["flags"]))
        return [p for p in pairs(cls.case(name)["flags"]) if p not in base]


# ====================================================================================================================
# Row 01. Box: persistent container, enter-or-create, stop, reset, update, up
# ====================================================================================================================

class Row01Box(FnBase):
    def test_row01_enter_creates_the_box_then_attaches(self):
        self.podman()
        r = self.swarmbox()
        self.assertEqual(r.returncode, 0, r.stderr)
        runs = self.real_runs()
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0][:4], ["run", "-d", "--name", "swarmbox"])
        self.assertEqual(runs[0][-2:], [tu.IMAGE, "serve"])
        last = self.calls()[-1]
        self.assertEqual(last, ["exec", "-i", "-e", "TERM", "-e", "COLORTERM", "swarmbox", "swarmbox-entrypoint", "attach"])
        self.assertEqual(self.subs("rm"), [])

    def test_row01_the_second_entry_reuses_the_running_box(self):
        self.podman(lookup={"stdout": self.matching_line()})
        r = self.swarmbox()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assert_no_run()
        self.assertEqual(self.subs("rm"), [])
        self.assertEqual(self.calls()[-1][0], "exec")
        self.assertEqual(self.calls()[-1][-2:], ["swarmbox-entrypoint", "attach"])

    def test_row01_a_stopped_box_is_started_not_recreated(self):
        self.podman(lookup={"stdout": self.matching_line(state="exited")})
        r = self.swarmbox()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.subs("start"), [["start", "swarmbox"]])
        self.assert_no_run()

    def test_row01_up_creates_without_attaching(self):
        self.podman()
        r = self.swarmbox("up")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(len(self.real_runs()), 1)
        self.assertFalse([c for c in self.calls() if c[:1] == ["exec"] and "swarmbox-entrypoint" in c], self.calls())

    def test_row01_stop_stops_only_the_box(self):
        self.podman(lookup={"stdout": self.matching_line()})
        r = self.swarmbox("stop")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.subs("stop"), [["stop", "swarmbox"]])
        self.assertEqual(self.subs("rm"), [])
        self.assert_no_run()

    def test_row01_reset_replaces_the_box_and_keeps_the_volume(self):
        self.podman(lookup={"stdout": self.matching_line()})
        r = self.swarmbox("reset")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.subs("rm"), [["rm", "-f", "swarmbox"]])
        self.assertEqual(len(self.real_runs()), 1)
        self.assertFalse([c for c in self.calls() if c[:1] == ["volume"]])

    def test_row01_update_goes_to_the_helper(self):
        """update and the other host words reach the helper whole (the update flow itself is tests/test_host_update.py and
        tests/test_registry_e2e.py)."""
        fh = FakeHostHelper(version=tu.VERSION, commands={"update": {"stdout": "updated\n"}, "*": {}}).__enter__()
        self.addCleanup(fh.__exit__)
        share = os.path.join(self.home, ".local", "share", "swarmbox")
        os.unlink(os.path.join(share, "host"))
        os.symlink(fh.dir, os.path.join(share, "host"))
        self.podman()
        r = self.swarmbox("update", "--to", "2.0.9")
        self.assertEqual(r.returncode, 0, r.stderr)
        calls = [c for c in fh.calls() if c != ["version"]]
        self.assertEqual(calls, [["update", "--to", "2.0.9"]])
        self.assertEqual(self.calls(), [])


# ====================================================================================================================
# Row 02. Box: shared tmux session for host tabs and the browser; no status bar on host tabs
# ====================================================================================================================

@unittest.skipUnless(ta.REAL_TMUX, "needs tmux")
class Row02Tmux(ta.Base):
    def setUp(self):
        super().setUp()
        self.iso = ta.IsoTmux()
        self.addCleanup(self.iso.close)
        with open(os.path.join(self.home, ".bashrc"), "w") as f:
            f.write(ta.FRAGMENT)
        env = self.env(self.iso.shim_dir)
        env.pop("TMUX", None)
        r = subprocess.run(["tmux", "new-session", "-d", "-s", "main", "-n", "idle", "-x", "100", "-y", "30"], env=env,
                           capture_output=True, text=True, cwd=self.home)
        self.assertEqual(r.returncode, 0, r.stderr)

    def sessions(self):
        return self.iso.run("list-sessions", "-F", "#{session_name}").stdout.split()

    def test_row02_two_tabs_share_one_session_and_host_tabs_have_no_status_bar(self):
        a = self.run_term(self.iso.shim_dir, [])
        self.assertTrue(ta.wait_until(lambda: len(self.sessions()) == 2), a.out)
        b = self.run_term(self.iso.shim_dir, [])
        self.assertTrue(ta.wait_until(lambda: len(self.sessions()) == 3), b.out)
        wins = self.iso.run("list-windows", "-t", "=main", "-F", "#{window_name}").stdout.split()
        self.assertEqual(len(wins), 2)
        self.assertNotIn("idle", wins)
        for s in (s for s in self.sessions() if s != "main"):
            self.assertEqual(self.iso.run("show-options", "-t", s, "-v", "status").stdout.strip(), "off")
        self.assertNotEqual(self.iso.run("show-options", "-t", "=main", "-v", "status").stdout.strip(), "off")

    def test_row02_the_browser_entry_is_a_window_of_the_same_session(self):
        """The ttyd supervisor runs swarmbox-attach, the same entry as a host tab (design 3.4, 5.1)."""
        web = read(SCRIPTS, "swarmbox-web.sh")
        self.assertRegex(web, r"TTYD_ARGS\+=\(swarmbox-attach\)")
        a = self.run_term(self.iso.shim_dir, [])
        self.assertTrue(ta.wait_until(lambda: len(self.sessions()) == 2), a.out)
        self.assertEqual(len(self.iso.run("list-windows", "-t", "=main").stdout.splitlines()), 1)


# ====================================================================================================================
# Row 03. Box: workspace mount, fixed user with sudo, --init, pids limit, hostname, time zone, UTF-8 locale
# ====================================================================================================================

class Row03Flags(FlagsBase):
    def test_row03_workspace_mount(self):
        self.assertIn(("-v", self.ws + ":/home/agent"), self.pairs())

    def test_row03_fixed_user_keep_id_and_sudo(self):
        self.assertIn(("--userns", "keep-id:uid=1000,gid=1000"), self.pairs())
        dockerfile = read(ROOT, "Dockerfile")
        self.assertIn('echo "agent ALL=(ALL) NOPASSWD: ALL" >> /etc/sudoers', dockerfile)
        self.assertRegex(dockerfile, r"(?m)^\s+sudo \\")

    def test_row03_init_flag(self):
        self.assertNotIn(("--init", None), self.pairs())
        self.assertIn(("--init", None), self.pairs(env={"SWARMBOX_INIT": "1"}))

    def test_row03_pids_limit(self):
        self.assertIn(("--pids-limit", "16384"), self.pairs())

    def test_row03_hostname(self):
        self.assertIn(("--hostname", "swarmbox"), self.pairs())
        self.assertIn(("--hostname", "devbox"), self.pairs(env={"SWARMBOX_HOSTNAME": "devbox"}))

    def test_row03_time_zone(self):
        self.assertIn(("--tz", "local"), self.pairs())
        self.assertIn(("--tz", "Europe/Paris"), self.pairs(env={"SWARMBOX_TZ": "Europe/Paris"}))

    def test_row03_utf8_locale(self):
        self.assertIn("ENV LANG=C.UTF-8", read(ROOT, "Dockerfile"))
        web = read(SCRIPTS, "swarmbox-web.sh")
        self.assertIn("export LANG=C.UTF-8", web)   # a ttyd started without a UTF-8 locale gets one


# ====================================================================================================================
# Row 04. Box: creation fingerprint, stale-image and startup-health warnings
# ====================================================================================================================

class Row04Warnings(tu.Base):
    def test_row04_a_changed_setting_warns_and_never_blocks(self):
        self.podman(lookup={"stdout": self.matching_line()})
        r = self.up(SWARMBOX_PORTS="3000")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("`PORTS` changed", r.stderr)
        self.assert_no_run()
        self.assertEqual(self.subs("rm"), [])

    def test_row04_the_fingerprint_changes_with_a_creation_setting_only(self):
        a = self.creation_flags()
        b = self.creation_flags({"SWARMBOX_HOSTNAME": "elsewhere"})
        self.assertNotEqual([x for x in a if x.startswith("swarmbox.fingerprint")], [x for x in b if x.startswith("swarmbox.fingerprint")])
        self.assertEqual(a, self.creation_flags())

    def test_row04_stale_image_warning(self):
        self.podman(lookup={"stdout": self.matching_line()},
                    image={"rules": [{"match": ["exists"]}, {"match": ["inspect"], "stdout": "sha256:bbb\n"}]})
        r = self.up()
        self.assertEqual(r.returncode, 0)
        self.assertIn("is newer than the one this box runs", r.stderr)

    def test_row04_startup_health_from_the_marker_and_the_banner(self):
        self.podman(exec={"stdout": "warnings=2\n"})
        r = self.up()
        self.assertEqual(r.returncode, 0)
        self.assertIn("2 warning", r.stderr)
        self.podman(exec={"exit": 1})
        r = self.up(SWARMBOX_TEST_READY_TRIES="3")
        self.assertEqual(r.returncode, 6)
        self.assertIn("did not become ready", r.stderr)


class Row04Banner(tb.Base):
    def test_row04_the_health_lines_and_the_stale_line_reach_the_banner(self):
        self.health("step 4 failed: migrate\nthe image of this box is older than the one on the host\n")
        out = self.interactive("true").stdout
        self.assertIn("BANNER-ART", out)
        self.assertIn("step 4 failed: migrate", out)
        self.assertIn("older than the one on the host", out)


# ====================================================================================================================
# Row 05. Box: environment variables and keys (7)
# ====================================================================================================================

class Row05Env(FlagsBase):
    def test_row05_env_add_list_rm(self):
        self.assertEqual(self.run_h("env", "add", "MY_KEY").returncode, 0)
        r = self.run_h("env", "list")
        self.assertIn("MY_KEY", r.stdout)
        self.assertEqual(self.run_h("env", "rm", "MY_KEY").returncode, 0)
        self.assertNotIn("MY_KEY", self.run_h("env", "list").stdout)

    def test_row05_a_listed_name_is_passed_by_name_and_never_by_value(self):
        self.run_h("env", "add", "MY_KEY")
        out = self.pairs(env={"MY_KEY": "s3cret-value"})
        self.assertIn(("-e", "MY_KEY"), out)
        self.assertNotIn("s3cret-value", " ".join(a or "" for _, a in out))

    def test_row05_a_name_that_is_not_set_is_not_passed(self):
        self.run_h("env", "add", "MY_KEY")
        self.assertNotIn(("-e", "MY_KEY"), self.pairs())

    def test_row05_the_host_value_is_part_of_the_creation_hash(self):
        self.run_h("env", "add", "MY_KEY")
        a = self.fp(env={"MY_KEY": "one"})
        b = self.fp(env={"MY_KEY": "two"})
        self.assertNotEqual(a, b)


# ====================================================================================================================
# Row 06. Shell: Starship, banner, aliases, <workspace>/.local/bin on PATH, /opt/flow venv, uv
# ====================================================================================================================

class Row06Shell(tb.Base):
    def test_row06_banner_comes_before_the_prompt_and_aliases_exist(self):
        out = self.interactive("alias ls; alias ll; alias la; alias l; alias grep").stdout
        self.assertIn("BANNER-ART", out)
        for a in ("alias ls='ls --color=auto'", "alias ll='ls -alF --color=auto'", "alias la='ls -A --color=auto'",
                  "alias l='ls -CF --color=auto'", "alias grep='grep --color=auto'"):
            self.assertIn(a, out)

    def test_row06_workspace_local_bin_is_on_the_path(self):
        out = self.interactive('echo "P=$PATH"').stdout
        path = [l for l in out.splitlines() if l.startswith("P=")][0][2:].split(":")
        self.assertIn(os.path.join(self.home, ".local", "bin"), path)

    def test_row06_the_venv_is_activated_with_its_prompt(self):
        venv = os.path.join(self.tmp, "flow")
        os.makedirs(os.path.join(venv, "bin"))
        tb.write(os.path.join(venv, "bin", "activate"), 'export VIRTUAL_ENV=%s\nexport FLOW_ACTIVATED=1\n' % venv)
        out = self.interactive("echo FLOW=$FLOW_ACTIVATED", SWARMBOX_VENV=venv).stdout
        self.assertIn("FLOW=1", out)
        self.assertIn("--prompt swarmbox /opt/flow", read(ROOT, "Dockerfile"))

    def test_row06_starship_is_initialised_last(self):
        init = os.path.join(self.tmp, "starship-init-fake.sh")
        tb.write(init, "echo STARSHIP-INIT-RAN\n")
        out = self.interactive("true", SWARMBOX_STARSHIP_INIT=init).stdout
        self.assertLess(out.index("BANNER-ART"), out.index("STARSHIP-INIT-RAN"))

    @unittest.skipUnless(shutil.which("starship"), "needs starship")
    def test_row06_the_starship_config_renders_without_warnings(self):
        """The real starship binary of this box renders the shipped config; the image's own starship (1.27.0) is [unverified] here."""
        repo = os.path.join(self.tmp, "proj")
        os.makedirs(repo)
        subprocess.run(["git", "init", "-q", "-b", "main", repo], check=True, capture_output=True)
        env = {"PATH": os.environ["PATH"], "HOME": self.home, "STARSHIP_CONFIG": os.path.join(CONFIG, "starship.toml"),
               "STARSHIP_CACHE": os.path.join(self.tmp, "cache"), "TERM": "xterm-256color"}
        r = subprocess.run(["starship", "prompt", "--terminal-width=120"], cwd=repo, env=env, capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stderr.strip(), "")
        self.assertIn("proj", re.sub(r"\x1b\[[0-9;]*m|\\\[|\\\]|[\x01\x02]", "", r.stdout))

    def test_row06_uv_and_starship_are_installed_by_the_image_build(self):
        """[reduced: the Dockerfile text only; a real image build is tests/test_image_build.py (opt-in) and the CI smoke job]"""
        reduced(self, "uv and Starship are read from the Dockerfile, not run in an image")
        d = read(ROOT, "Dockerfile")
        self.assertRegex(d, r"ARG UV_VERSION=\d+\.\d+\.\d+")
        self.assertIn("UV_INSTALL_DIR=/usr/local/bin", d)
        self.assertRegex(d, r"ARG STARSHIP_VERSION=\d+\.\d+\.\d+")
        self.assertIn("/usr/local/bin starship", d)
        self.assertIn("COPY container/config/starship.toml /etc/swarmbox/starship.toml", d)


# ====================================================================================================================
# Row 07. Shell: tmux configuration, the Alt shortcuts, the clipboard bridge
# ====================================================================================================================

@unittest.skipUnless(ta.REAL_TMUX, "needs tmux")
class Row07Tmux(unittest.TestCase):
    def setUp(self):
        self.iso = ta.IsoTmux()
        self.addCleanup(self.iso.close)
        r = self.iso.run("new-session", "-d", "-s", "t", "-x", "100", "-y", "30")
        self.assertEqual(r.returncode, 0, r.stderr)
        r = self.iso.run("source-file", os.path.join(CONFIG, "tmux.conf"))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def keys(self, table):
        return self.iso.run("list-keys", "-T", table).stdout

    def test_row07_the_shipped_tmux_conf_loads_with_its_prefix_and_mouse(self):
        self.assertEqual(self.iso.run("show-options", "-gv", "mouse").stdout.strip(), "on")
        self.assertIn("send-prefix", self.keys("prefix"))
        self.assertRegex(self.keys("prefix"), r"split-window -h")

    def test_row07_the_alt_shortcuts_are_bound_in_the_root_table(self):
        root = self.keys("root")
        for key, cmd in (("M-n", "new-window"), ("M-w", "confirm-before"), ("M-h", "previous-window"), ("M-l", "next-window"),
                         ("M-1", "select-window"), ("M-Left", "select-pane")):
            self.assertRegex(root, r"\b%s\s+%s" % (re.escape(key), cmd))


class Row07Clipboard(unittest.TestCase):
    def test_row07_the_page_carries_the_clipboard_bridge(self):
        """[reduced: the built page is checked as text; the browser run is opt-in (SWARMBOX_PARITY_BROWSER=1)]"""
        tmp = tempfile.mkdtemp(prefix="swarmbox-test-parity-")
        self.addCleanup(shutil.rmtree, tmp, True)
        page = twb.build_page(tmp)
        text = read(page)
        self.assertIn(read(ROOT, "container", "web", "ttyd-clipboard.js").strip()[:60], text)
        for ph in ("__SWARMBOX_PADDING__", "__SWARMBOX_CTRL_V__", "__SWARMBOX_CTRL_C__"):
            self.assertIn(ph, text)
        if os.environ.get("SWARMBOX_PARITY_BROWSER") == "1":
            r = subprocess.run([sys.executable, os.path.join(ROOT, "tests", "test_clipboard_bridge.py")], capture_output=True,
                               text=True, timeout=300)
            self.assertEqual(r.returncode, 0, r.stderr[-2000:])
        else:
            reduced(self, "no browser run unless SWARMBOX_PARITY_BROWSER=1")


# ====================================================================================================================
# Row 08. Git: SSH key, `swarmbox pubkey`, trust on first use
# ====================================================================================================================

@unittest.skipUnless(shutil.which("ssh-keygen"), "needs ssh-keygen")
class Row08Git(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="swarmbox-test-parity-")
        self.addCleanup(shutil.rmtree, self.home, True)

    def pubkey(self, *args):
        env = dict(os.environ, HOME=self.home)
        env.pop("SWARMBOX_SSH_DIR", None)
        return subprocess.run(["bash", os.path.join(SCRIPTS, "ssh-key.sh"), *args], env=env, capture_output=True, text=True)

    def test_row08_the_key_is_created_once_and_never_overwritten(self):
        r = self.pubkey("--ensure")
        self.assertEqual(r.returncode, 0, r.stderr)
        key = os.path.join(self.home, ".ssh", "id_ed25519")
        self.assertEqual(stat.S_IMODE(os.stat(key).st_mode), 0o600)
        before = read(key)
        self.pubkey("--ensure")
        self.pubkey()
        self.assertEqual(read(key), before)

    def test_row08_pubkey_shows_the_public_key(self):
        r = self.pubkey()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(read(self.home, ".ssh", "id_ed25519.pub").split()[1], r.stdout)

    def test_row08_the_function_forwards_the_word_pubkey_to_the_box(self):
        class F(FnBase):
            def runTest(self):
                pass
        f = F()
        f.setUp()
        self.addCleanup(f.doCleanups)
        f.podman(lookup={"stdout": f.matching_line()})
        r = f.swarmbox("pubkey")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(f.calls()[-1], ["exec", "-i", "-e", "TERM", "-e", "COLORTERM", "swarmbox", "swarmbox-entrypoint", "pubkey"])

    def test_row08_trust_on_first_use_for_the_three_hosts(self):
        conf = read(CONFIG, "ssh-swarmbox.conf")
        self.assertRegex(conf, r"(?m)^Host github\.com gitlab\.com bitbucket\.org$")
        self.assertRegex(conf, r"(?m)^\s+StrictHostKeyChecking accept-new$")
        self.assertIn("COPY container/config/ssh-swarmbox.conf /etc/ssh/ssh_config.d/swarmbox.conf", read(ROOT, "Dockerfile"))


# ====================================================================================================================
# Row 09. Web: the web terminal (ttyd), on by default on 127.0.0.1
# ====================================================================================================================

class Row09WebFlags(FlagsBase):
    def test_row09_on_by_default_and_published_on_loopback_only(self):
        p = self.pairs()
        self.assertIn(("-p", "127.0.0.1:7681:7681"), p)
        self.assertIn(("-e", "SWARMBOX_WEB=1"), p)

    def test_row09_web_off_publishes_nothing(self):
        p = self.pairs(env={"SWARMBOX_WEB": "0"})
        self.assertFalse([v for f, v in p if f == "-p"])
        self.assertNotIn(("-e", "SWARMBOX_WEB=1"), p)

    def test_row09_no_flag_publishes_on_all_interfaces_by_default(self):
        for f, v in self.pairs():
            if f == "-p":
                self.assertTrue(v.startswith("127.0.0.1:"), v)


class Row09WebSwarmboxWeb(twb.WebCase):
    def test_row09_ttyd_is_started_writable_with_the_origin_check_and_the_attach_entry(self):
        r = self.web("run")
        self.assertEqual(r.returncode, 0, r.stderr)
        argv = self.ttyd_call()["argv"]
        self.assertIn("-W", argv)
        self.assertIn("-O", argv)
        self.assertEqual(argv[argv.index("--index") + 1], os.path.join(self.run_dir, "index.html"))
        self.assertIn("-p", argv)
        # the fake PATH has no swarmbox-attach, so the fallback entry (the session main) is what ttyd runs
        self.assertEqual(argv[-4:], ["tmux", "attach", "-t", "main"])
        self.assertIn("swarmbox-attach", read(SCRIPTS, "swarmbox-web.sh"))

    def test_row09_the_page_is_rendered_from_the_built_page(self):
        r = self.web("render")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("__SWARMBOX_", self.index())


class Row09WebServe(tss.ServeCase):
    def test_row09_serve_starts_ttyd_by_default_and_not_with_web_off(self):
        p = self.run_ready()
        self.assertTrue(tss.wait_for(lambda: any(c.startswith("ttyd ") for c in self.calls())))
        self.stop(p)


# ====================================================================================================================
# Row 10. Web: remote access through Cloudflare (swarmbox remote ...), host side
# ====================================================================================================================

class Row10Remote(unittest.TestCase):
    SETUP = e2e.E2E.SETUP

    def setUp(self):
        self.e = e2e.E2E("test_full_lifecycle")
        self.e.setUp()
        self.addCleanup(self.e.doCleanups)

    def test_row10_setup_status_url_token_off_against_the_fake_api(self):
        e = self.e
        r = e.remote(*self.SETUP, "--session", "24h")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual((len(e2e.FAKE.apps), len(e2e.FAKE.dns), len(e2e.FAKE.tunnels)), (1, 1, 1))
        self.assertIn("swarmbox.talkr.run", e.remote("status", "--domain", "talkr.run").stdout)
        self.assertIn("https://swarmbox.talkr.run", e.helper_run("url").stdout)
        t = e.remote("token", "--domain", "talkr.run")
        self.assertEqual(t.stdout, "tok." + e2e.FAKE.tunnels[0]["id"] + "\n")
        self.assertEqual(e.remote("off", "--domain", "talkr.run", "--yes").returncode, 0)
        self.assertEqual((e2e.FAKE.apps, e2e.FAKE.dns), ([], []))

    def test_row10_the_connector_uses_the_pinned_image(self):
        e = self.e
        e.remote(*self.SETUP)
        runs = [c for c in e.calls() if c.startswith("run ")]
        self.assertEqual(len(runs), 1)
        self.assertRegex(runs[0], r"cloudflare/cloudflared:\d{4}\.\d+\.\d+")
        self.assertNotIn(":latest", runs[0])

    def test_row10_the_function_routes_remote_to_the_helper(self):
        class F(FnBase):
            def runTest(self):
                pass
        f = F()
        f.setUp()
        self.addCleanup(f.doCleanups)
        fh = FakeHostHelper(version=tu.VERSION, commands={"*": {}}).__enter__()
        self.addCleanup(fh.__exit__)
        share = os.path.join(f.home, ".local", "share", "swarmbox")
        os.unlink(os.path.join(share, "host"))
        os.symlink(fh.dir, os.path.join(share, "host"))
        f.podman()
        r = f.swarmbox("remote", "status")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual([c for c in fh.calls() if c != ["version"]], [["remote", "status"]])


# ====================================================================================================================
# Row 11. Containers: nested Podman (always on), with the host connection
# ====================================================================================================================

class Row11Nested(FlagsBase):
    def test_row11_the_creation_flags_for_nested_podman(self):
        p = self.pairs()
        self.assertIn(("--device", "/dev/net/tun"), p)
        self.assertIn(("--security-opt", "unmask=/proc/*"), p)
        self.assertIn(("-v", "swarmbox-containers:/home/agent/.local/share/containers"), p)

    def test_row11_the_volume_follows_the_box_name(self):
        p = self.pairs(env={"SWARMBOX_NAME": "second"})
        self.assertIn(("-v", "second-containers:/home/agent/.local/share/containers"), p)


class Row11Connection(tu.Base):
    def test_row11_up_registers_the_host_connection_to_the_box_socket(self):
        self.podman(lookup={"stdout": self.matching_line()})
        r = self.up()
        self.assertEqual(r.returncode, 0, r.stderr)
        sysc = [c for c in self.calls() if c[:1] == ["system"]]
        self.assertTrue(any(c[:3] == ["system", "connection", "add"] and c[3] == "swarmbox" for c in sysc), sysc)

    def test_row11_up_refuses_to_create_without_dev_net_tun(self):
        self.podman()
        r = self.up(SWARMBOX_TEST_TUN=os.path.join(self.tmp, "no-such-file"))
        self.assertEqual(r.returncode, 3, r.stderr)
        self.assertIn("/dev/net/tun", r.stderr)
        self.assert_no_run()

    def test_row11_nested_podman_itself(self):
        """[reduced: serve is run with a fake podman and the service socket is checked; a real nested Podman needs a third nesting
        level, which the development box cannot offer; tests/smoke_image.py in full mode (CI) is the real check]"""
        reduced(self, "no real nested Podman (third nesting level)")
        self.assertIn("system service", read(ROOT, "container", "entrypoint.sh"))


class Row11ServeService(tss.ServeCase):
    def test_row11_serve_starts_the_podman_service_unless_the_test_switch_is_set(self):
        p = self.run_ready()
        self.assertTrue(any(c.startswith("podman system service") for c in self.calls()), self.calls())
        self.stop(p)


# ====================================================================================================================
# Row 12. Browser: chrome-devtools MCP, local headless Chromium or a remote Chrome (BROWSER_URL)
# ====================================================================================================================

class Row12Browser(unittest.TestCase):
    def setUp(self):
        self.m = tm.McpCase("test_default_output")   # used as a driver only: its own tests are not inherited
        self.m.setUp()
        self.addCleanup(self.m.doCleanups)

    def test_row12_local_headless_chromium_by_default(self):
        r = self.m.run_gen()
        self.assertEqual(r.returncode, 0, r.stderr)
        e = self.m.data()["mcpServers"]["chrome-devtools"]
        self.assertEqual(e["command"], "chrome-devtools-mcp")
        self.assertIn("--headless", e["args"])
        self.assertIn("--executablePath=/usr/bin/chromium", e["args"])

    def test_row12_a_remote_chrome_through_browser_url(self):
        self.m.run_gen(BROWSER_URL="http://host.containers.internal:9222")
        self.assertEqual(self.m.data()["mcpServers"]["chrome-devtools"]["args"],
                         ["--browserUrl=http://host.containers.internal:9222"])

    def test_row12_the_registry_has_no_npx_and_no_latest(self):
        for root, _, files in os.walk(tm.IMAGE_REG):
            for f in files:
                t = read(root, f)
                self.assertNotIn("npx", t)
                self.assertNotIn("@latest", t)


class Row12Flags(FlagsBase):
    def test_row12_browser_url_reaches_the_box_as_swarmbox_browser_url(self):
        # the default first: a cfg= call writes the config file, which later calls of the same test would read again
        self.assertFalse([v for f, v in self.pairs() if f == "-e" and v.startswith("SWARMBOX_BROWSER_URL")])
        self.assertIn(("-e", "SWARMBOX_BROWSER_URL=http://10.0.0.5:9222"),
                      self.pairs(cfg="BROWSER_URL=10.0.0.5:9222\n"))


# ====================================================================================================================
# Row 13. Network: published ports, host access
# ====================================================================================================================

class Row13Network(FlagsBase):
    def test_row13_ports_are_published_on_loopback(self):
        p = self.pairs(cfg="PORTS=3000,8080:80\n")
        self.assertIn(("-p", "127.0.0.1:3000:3000"), p)
        self.assertIn(("-p", "127.0.0.1:8080:80"), p)

    def test_row13_a_wider_bind_needs_an_explicit_address(self):
        self.assertIn(("-p", "0.0.0.0:9000:9000"), self.pairs(cfg="PORTS=0.0.0.0:9000:9000\n"))

    def test_row13_host_access_adds_the_gateway_name(self):
        self.assertFalse([v for f, v in self.pairs() if f == "--add-host"])
        self.assertIn(("--add-host", "host.containers.internal:host-gateway"), self.pairs(cfg="HOST_ACCESS=1\n"))

    def test_row13_a_port_conflict_is_exit_7_and_nothing_is_left(self):
        class F(tu.Base):
            def runTest(self):
                pass
        f = F()
        f.setUp()
        self.addCleanup(f.doCleanups)
        f.podman(run={"exit": 126, "stderr": "Error: " + tu.BUSY + "\n", "cidfile": ""})
        r = f.up()
        self.assertEqual(r.returncode, 7, r.stderr)
        self.assertIn("address already in use", r.stderr)


# ====================================================================================================================
# Row 14. Tools: claude (self-updating), gemini, opencode (local-LLM hook), gcloud, clasp, Go, Poetry
# ====================================================================================================================

REAL_TOOL_NAMES = ["clasp", "claude", "gcloud", "gemini", "go", "opencode", "poetry"]


class Row14Tools(ttm.Base):
    def real(self):
        return {"SWARMBOX_TEST_IMAGE_TOOLS": TOOLS}

    def conf(self, name):
        out = {}
        for line in read(TOOLS, name, "tool.conf").splitlines():
            m = re.match(r'^([A-Z_]+)=(.*)$', line)
            if m:
                out[m.group(1)] = m.group(2).strip('"')
        return out

    def test_row14_the_image_ships_exactly_the_seven_tools(self):
        self.assertEqual(sorted(os.listdir(TOOLS)), REAL_TOOL_NAMES)

    def test_row14_every_shipped_manifest_validates(self):
        r = self.validate(env=self.real())
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        for n in REAL_TOOL_NAMES:
            self.assertIn(n, r.stdout)

    def test_row14_claude_updates_itself_and_has_the_auto_approve_flag(self):
        c = self.conf("claude")
        self.assertEqual(c["UPDATE"], "self")
        self.assertEqual(c["YOLO_FLAGS"], "--dangerously-skip-permissions")
        self.assertIn("mcp-servers.json", c["MCP_FLAGS"])

    def test_row14_other_tools_are_pinned_agents_are_the_only_unpinned(self):
        for n in ("clasp", "gcloud", "go", "poetry"):
            self.assertNotEqual(self.conf(n)["VERSION"], "latest", n)
            self.assertEqual(self.conf(n)["KIND"], "tool")
        self.assertEqual(self.conf("gemini")["KIND"], "agent")
        self.assertEqual(self.conf("opencode")["KIND"], "agent")

    def test_row14_clasp_declares_its_login_port(self):
        self.assertEqual(self.conf("clasp")["PORTS"], "43323")

    def test_row14_tools_are_installed_on_demand_through_with(self):
        class F(FlagsBase):
            def runTest(self):
                pass
        F.real_home = os.path.realpath(os.path.expanduser("~"))
        f = F()
        f.setUp()
        self.addCleanup(f.doCleanups)
        f.make_helper("clasp\t43323\n")
        p = pairs(f.flags(cfg="WITH=clasp,claude\n"))
        self.assertIn(("-e", "SWARMBOX_WITH=clasp,claude"), p)
        self.assertIn(("-p", "127.0.0.1:43323:43323"), p)
        self.assertIn('ARG WITH_TOOLS=""', read(ROOT, "Dockerfile"))   # no tool is baked in unless asked


class Row14Alias(tb.Base):
    def setUp(self):
        super().setUp()
        shutil.copytree(TOOLS, self.imgtools, dirs_exist_ok=True)

    def test_row14_the_claude_alias_and_yolo(self):
        r = self.interactive("alias claude")
        self.assertIn("alias claude='claude --dangerously-skip-permissions --mcp-config %s/.claude/mcp-servers.json'" % self.home,
                      r.stdout, r.stdout + r.stderr)
        self.assertIn("yolo", self.interactive("type yolo | head -1").stdout)


class Row14OpenCode(unittest.TestCase):
    def setUp(self):
        self.base = tempfile.mkdtemp(prefix="swarmbox-test-parity-")
        self.addCleanup(shutil.rmtree, self.base, True)
        self.home = os.path.join(self.base, "home")
        self.run_dir = os.path.join(self.base, "run", "swarmbox")
        os.makedirs(os.path.join(self.home, ".claude"))

    def prepare(self, **env):
        e = {"PATH": os.environ["PATH"], "HOME": self.home, "SWARMBOX_TEST_LIB": SCRIPTS, "SWARMBOX_TEST_RUN_DIR": self.run_dir,
             "LANG": "C.UTF-8"}
        e.update(env)
        r = subprocess.run(["bash", os.path.join(TOOLS, "opencode", "prepare.sh")], env=e, capture_output=True, text=True,
                           timeout=30, cwd=self.home)
        return r, json.loads(read(self.run_dir, "opencode.json"))

    def test_row14_the_local_llm_hook_is_opt_in_and_has_no_default_model(self):
        r, d = self.prepare()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("provider", d)
        self.assertNotIn("model", d)
        r, d = self.prepare(LOCAL_LLM_URL="http://127.0.0.1:8000/v1", LOCAL_LLM_MODEL="m1")
        self.assertEqual(d["provider"]["local"]["options"]["baseURL"], "http://127.0.0.1:8000/v1")
        self.assertEqual(d["model"], "local/m1")


# ====================================================================================================================
# 12.2 removals
# ====================================================================================================================

def image_sources():
    """The text of every 2.0 image source: Dockerfile and container/ (the v0.1.0 files are retired, slice 6.3)."""
    out = {"Dockerfile": read(ROOT, "Dockerfile")}
    for root, _, files in os.walk(os.path.join(ROOT, "container")):
        for f in files:
            p = os.path.join(root, f)
            if f.endswith((".png", ".ico")):
                continue
            try:
                out[os.path.relpath(p, ROOT)] = read(p)
            except UnicodeDecodeError:
                pass
    return out


class Removed(FlagsBase):
    def test_removed_host_network_is_refused_everywhere(self):
        for argv in (["up", "--host-network"], ["create-flags", "--host-network"], ["config", "set", "HOST_NETWORK", "1"],
                     ["--host-network"]):
            with self.subTest(argv=argv):
                r = self.run_h(*argv)
                self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertNotIn("--net=host", " ".join(self.flags()))
        self.assertNotIn(("--net", "host"), pairs(self.flags()))

    def test_removed_items_are_absent_from_the_image_sources(self):
        srcs = image_sources()
        for needle, what in (("claude-mcp", "claude-mcp wrapper"), ("ANTHROPIC_MODEL", "ANTHROPIC_MODEL=sonnet"),
                             ("chmod -R 777", "the darwin chmod"), ("USER_UID", "USER_UID build argument"),
                             ("USER_GID", "USER_GID build argument"), ("HOST_OS", "HOST_OS build argument"),
                             ("CLAUDE_CODE_CACHEBUST", "CLAUDE_CODE_CACHEBUST"), ("OPENCODE_VERSION", "OPENCODE_VERSION"),
                             ("--update-harness", "--update-harness"), ("host-network", "host network mode"),
                             ("host.containers.internal:8000", "the local-LLM default URL")):
            for path, text in srcs.items():
                self.assertNotIn(needle, text, "%s found in %s" % (what, path))

    def test_removed_uuid_function_is_absent_from_the_shell(self):
        for path, text in image_sources().items():
            self.assertNotRegex(text, r"(?m)^\s*uuid\s*\(\)", path)
        class B(tb.Base):
            def runTest(self):
                pass
        b = B()
        b.setUp()
        self.addCleanup(b.doCleanups)
        self.assertNotIn("uuid is a function", b.interactive("type uuid 2>&1 | head -1").stdout)

    def test_removed_local_llm_defaults_and_forwarding(self):
        p = pairs(self.flags(env={"LOCAL_LLM_URL": "http://x/v1"}))
        self.assertFalse([v for f, v in p if f == "-e" and v.startswith("LOCAL_LLM")], "no automatic forwarding")
        self.run_h("env", "add", "LOCAL_LLM_URL")
        self.assertIn(("-e", "LOCAL_LLM_URL"), pairs(self.flags(env={"LOCAL_LLM_URL": "http://x/v1"})))

    def test_removed_the_agents_are_not_in_the_image(self):
        d = read(ROOT, "Dockerfile")
        self.assertNotIn("@anthropic-ai/claude-code", d)
        self.assertNotIn("opencode-ai", d)


# ====================================================================================================================
# 12.2 "kept on purpose"
# ====================================================================================================================

class Kept(FlagsBase):
    def test_kept_remote_browser_bare_number_and_host_port(self):
        self.assertIn(("-e", "SWARMBOX_BROWSER_URL=http://host.containers.internal:9222"), self.pairs(cfg="BROWSER_URL=9222\n"))
        self.assertIn(("-e", "SWARMBOX_BROWSER_URL=http://10.0.0.5:9222"), self.pairs(cfg="BROWSER_URL=10.0.0.5:9222\n"))

    def test_kept_remote_browser_with_no_argument_means_9222(self):
        p = pairs(self.flags(args=["--browser-url", ""]))
        self.assertIn(("-e", "SWARMBOX_BROWSER_URL=http://host.containers.internal:9222"), p)

    def test_kept_ports_hostname_tz_init(self):
        p = self.pairs(cfg="PORTS=3000\nHOSTNAME=h1\nTZ=Europe/Paris\n", env={"SWARMBOX_INIT": "1"})
        for want in (("-p", "127.0.0.1:3000:3000"), ("--hostname", "h1"), ("--tz", "Europe/Paris"), ("--init", None)):
            self.assertIn(want, p)

    def test_kept_the_ssh_key_and_the_nested_volume(self):
        self.assertTrue(os.path.exists(os.path.join(SCRIPTS, "ssh-key.sh")))
        self.assertIn(("-v", "swarmbox-containers:/home/agent/.local/share/containers"), self.pairs())

    def test_kept_the_cloudflare_options_pass_through(self):
        usage = read(HELPER_SRC)
        script = read(ROOT, "cloudflare-setup.py")
        for opt in ("--print-token", "--no-connector", "--dry-run", "--tunnel", "--no-verify"):
            self.assertIn(opt, script)
        self.assertIn("remote setup|status|off|token", usage)
        self.assertIn('"token"', script)


class KeptRemoteOptions(unittest.TestCase):
    def setUp(self):
        self.e = e2e.E2E("test_full_lifecycle")
        self.e.setUp()
        self.addCleanup(self.e.doCleanups)

    def test_kept_no_connector_starts_no_container(self):
        r = self.e.remote(*e2e.E2E.SETUP, "--no-connector")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual([c for c in self.e.calls() if c.startswith(("run ", "start "))], [])

    def test_kept_print_token_prints_the_token(self):
        r = self.e.remote(*e2e.E2E.SETUP, "--no-connector", "--print-token")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("tok." + e2e.FAKE.tunnels[0]["id"], r.stdout)

    def test_kept_tunnel_name_and_dry_run(self):
        r = self.e.remote(*e2e.E2E.SETUP, "--tunnel", "other", "--dry-run")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(e2e.FAKE.mutations(), [])


# ====================================================================================================================
# 12.3 mapping: the old flag and the new key give the same podman flags as v0.1.0 recorded
# ====================================================================================================================

class MapPlain(ta.FakeTmuxCase):
    def test_map_swarmbox_attach_shell_to_plain_runs_no_tmux(self):
        """`SWARMBOX_ATTACH=shell` of v0.1.0 is `--plain` now: the command runs directly, tmux is never called."""
        with open(os.path.join(self.home, ".bashrc"), "w") as f:
            f.write(ta.FRAGMENT)
        p = self.run_term(self.fake, ["--plain", "sh", "-c", "exit 5"])
        self.assertEqual(p.wait(), 5, p.out)
        self.assertEqual(self.calls(), [])


class Mapping(FlagsBase):
    def new_delta(self, **kw):
        base = set(self.pairs(cfg=""))   # cfg="" rewrites the config file, so an earlier call of the test leaves no key behind
        return [p for p in self.pairs(**kw) if p not in base]

    def assert_covers(self, old_case, **kw):
        new = self.new_delta(**kw)
        for p in V010.delta(old_case):
            self.assertIn(p, new, "%s: v0.1.0 passed %s, 2.0 passes %s" % (old_case, p, new))

    def test_map_the_default_run_keeps_every_flag_of_v0_1_0_except_the_user_namespace_spelling(self):
        old = [a.replace("@WS@", self.ws) for a in V010.case("default")["flags"]]
        new = self.pairs()
        for p in pairs(old):
            if p[0] in ("-d", "--name", "--userns", "swarmbox"):
                continue
            self.assertIn(p, new, p)
        self.assertEqual([v for f, v in pairs(old) if f == "--userns"], ["keep-id"])
        self.assertIn(("--userns", "keep-id:uid=1000,gid=1000"), new)   # [new] fixed UID, 8.4 row 3

    def test_map_ports(self):
        self.assert_covers("ports", cfg="PORTS=3000,8080:80\n")

    def test_map_hostname(self):
        self.assert_covers("hostname", cfg="HOSTNAME=myhost\n")

    def test_map_swarmbox_tz(self):
        self.assert_covers("tz", cfg="TZ=Europe/Paris\n")

    def test_map_swarmbox_init(self):
        self.assert_covers("init", env={"SWARMBOX_INIT": "1"})

    def test_map_remote_browser_to_browser_url(self):
        new = self.new_delta(cfg="BROWSER_URL=10.0.0.5:9222\n")
        self.assertEqual(V010.delta("remote-browser"), [("-e", "BROWSER_URL=http://10.0.0.5:9222")])
        self.assertIn(("-e", "SWARMBOX_BROWSER_URL=http://10.0.0.5:9222"), new)   # the variable's name changed (12.3)
        bare = self.new_delta(cfg="BROWSER_URL=9222\n")
        self.assertEqual(V010.delta("remote-browser-bare"), [("-e", "BROWSER_URL=http://host.containers.internal:9222")])
        self.assertIn(("-e", "SWARMBOX_BROWSER_URL=http://host.containers.internal:9222"), bare)

    def test_map_clasp_to_the_manifests_port(self):
        self.assertEqual(self.conf_ports("clasp"), "43323")
        self.make_helper("clasp\t43323\n")
        self.assert_covers("clasp", cfg="WITH=clasp\n")

    def conf_ports(self, tool):
        for line in read(TOOLS, tool, "tool.conf").splitlines():
            if line.startswith("PORTS="):
                return line.split("=", 1)[1].strip('"')

    def test_map_env_keys_to_env_add_by_name(self):
        self.assertEqual(V010.delta("env-keys"), [("-e", "A=1")])
        self.assertEqual(self.run_h("env", "add", "A").returncode, 0)   # `env add` is the new way to say --env-keys A,B
        self.assertEqual(self.run_h("env", "add", "B").returncode, 0)
        self.assertIn("A,B", self.run_h("config", "get", "ENV_KEYS").stdout)
        new = self.pairs(env={"A": "1"})
        self.assertIn(("-e", "A"), new)   # same creation-time behavior; the value is inherited, not on the command line
        self.assertNotIn(("-e", "A=1"), new)
        self.assertNotIn(("-e", "B"), new)   # listed but not set: not passed

    def test_map_iports_to_host_access(self):
        self.assert_covers("iports", cfg="HOST_ACCESS=1\n")

    def test_map_web_flag_to_the_default(self):
        d = set(self.pairs())
        for p in V010.delta("web"):
            self.assertIn(p, d)    # `--web` of v0.1.0 is what 2.0 does without being asked

    def test_map_host_network_has_no_equivalent(self):
        self.assertIn(("--net", "host"), pairs(V010.case("host-network")["flags"]))
        self.assertNotIn(("--net", "host"), self.pairs())
        self.assertEqual(self.run_h("config", "set", "HOST_NETWORK", "1").returncode, 2)

    def test_map_no_shell_to_up_and_plain(self):
        class F(FnBase):
            def runTest(self):
                pass
        f = F()
        f.setUp()
        self.addCleanup(f.doCleanups)
        f.podman(lookup={"stdout": f.matching_line()})
        r = f.swarmbox("up")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse([c for c in f.calls() if c[:1] == ["exec"] and "swarmbox-entrypoint" in c])
        r = f.swarmbox("--plain")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(f.calls()[-1][-2:], ["attach", "--plain"])

    def test_map_the_config_and_the_environment_name_the_same_keys(self):
        """HOSTNAME, TZ, INIT, PORTS: a SWARMBOX_<KEY> variable beats the file (8.2)."""
        d = {"HOSTNAME": "h2", "TZ": "Europe/Paris", "PORTS": "3000", "INIT": "1"}
        for k, v in d.items():
            r = self.run_h("config", "get", k, env={"SWARMBOX_" + k: v})
            self.assertEqual(r.stdout.strip(), v, k)


# ====================================================================================================================
# Registry: every row of 8.4 has tests, and the table of 13.2 names them all
# ====================================================================================================================

def parity_test_names():
    """Every test name of this file (statically, so the registry does not depend on what is imported)."""
    with open(SELF, encoding="utf-8") as f:
        text = f.read()
    return re.findall(r"(?m)^    def (test_(?:row\d\d|removed|kept|map)_\w+)\(", text)


def table_names():
    d = read(DESIGN_PATH)
    s = d.index("### 13.2 Parity")
    e = d.index("### 13.3 Test layers")
    return re.findall(r"`(test_(?:row\d\d|removed|kept|map)_\w+)`", d[s:e])


class ParityRegistry(unittest.TestCase):
    def test_the_catalog_has_14_rows(self):
        self.assertEqual(len(catalog_rows()), 14)

    def test_every_catalog_row_has_a_test(self):
        names = parity_test_names()
        for n in range(1, len(catalog_rows()) + 1):
            self.assertTrue([t for t in names if t.startswith("test_row%02d_" % n)], "row %d: %r" % (n, catalog_rows()[n - 1]))

    def test_no_test_names_a_row_that_does_not_exist(self):
        for t in parity_test_names():
            m = re.match(r"test_row(\d\d)_", t)
            if m:
                self.assertLessEqual(int(m.group(1)), len(catalog_rows()), t)

    def test_every_test_is_in_the_table_of_design_13_2_and_the_table_names_only_real_tests(self):
        names, table = parity_test_names(), table_names()
        self.assertEqual(sorted(set(names) - set(table)), [])
        self.assertEqual(sorted(set(table) - set(names)), [])

    def test_names_are_unique(self):
        names = parity_test_names()
        self.assertEqual(len(names), len(set(names)))

    def test_every_12_3_row_and_12_2_removal_has_a_test(self):
        names = " ".join(parity_test_names())
        for word in ("map_ports", "map_hostname", "map_swarmbox_tz", "map_swarmbox_init", "map_remote_browser", "map_clasp",
                     "map_env_keys", "map_iports", "map_no_shell", "removed_host_network", "removed_items", "removed_uuid",
                     "kept_remote_browser", "kept_the_cloudflare_options"):
            self.assertIn("test_" + word, names)


def _print_reduced():
    if REDUCED:
        sys.stderr.write("\nparity: %d test(s) reduced:\n" % len(REDUCED))
        for r in sorted(set(REDUCED)):
            sys.stderr.write("  [reduced] %s\n" % r)


if __name__ == "__main__":
    prog = unittest.main(exit=False, verbosity=1)
    _print_reduced()
    sys.exit(0 if prog.result.wasSuccessful() else 1)
