"""Slice 2.5: the web terminal of design 5.1. build-index.sh builds the page at image build (tests/test_build_index.py
covers the script itself); `swarmbox-web` (container/scripts/swarmbox-web.sh) turns it into box:/tmp/swarmbox/index.html at
every start with a plain text substitution of three values (padding, ctrlVPaste, ctrlCCopy), builds ttyd's `-t key=value`
options (font, theme, size, scrollback, anything else) from web-terminal.conf, and execs ttyd; `swarmbox-web restart`
signals the supervisor of slice 2.2.

Layers:
  1. swarmbox-web against a FAKE ttyd (records its arguments). Nothing is served. The test asserts that no port it hands
     out is 7681, 8889 or 43323, the ports of this very network namespace.
  2. serve (the real entrypoint, fake tmux/podman/ttyd) with the real swarmbox-web: `swarmbox-web restart` restarts ttyd.
  3. Browser: tests/test_clipboard_bridge.py and tests/test_web_style.py build the page with build-index.sh and render it with
     swarmbox-web (slice 6.2 moved that setup there; skipped without chromium, ttyd and tmux).

Test-only variables (decision log [2.5], not in the configuration table of design 8): SWARMBOX_TEST_LIB, SWARMBOX_TEST_RUN_DIR,
SWARMBOX_TEST_WEB_PAGE (the built page, default /usr/local/share/swarmbox/web/index.html), SWARMBOX_TEST_WEB_PORT (default
7681), SWARMBOX_TEST_WEB_IFACE (ttyd -i value, default none = all interfaces inside the box).
Run with: python3 tests/test_web_build.py
"""
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import ROOT  # noqa: E402
import test_clipboard_bridge as base  # noqa: E402
import test_serve_steps as serve_steps  # noqa: E402

WEB = os.path.join(ROOT, "container", "scripts", "swarmbox-web.sh")
BUILD = os.path.join(ROOT, "container", "web", "build-index.sh")
DIRS_SH = os.path.join(ROOT, "container", "scripts", "dirs.sh")
FORBIDDEN_PORTS = (7681, 8889, 43323)
STOCK = "<html><head><title>t</title></head><body><div id=terminal></div></body></html>"

FAKE_TTYD = '''#!/usr/bin/env python3
import json, os, sys
with open(os.path.join(os.environ["FAKE_DIR"], "ttyd.json"), "w") as f:
    json.dump({"argv": sys.argv[1:], "pid": os.getpid(), "lang": os.environ.get("LANG")}, f)
'''
FAKE_ATTACH = '#!/bin/sh\nexit 0\n'


def write_exec(path, text):
    with open(path, "w") as f:
        f.write(text)
    os.chmod(path, 0o755)


def build_page(dest_dir, stock=STOCK):
    """Run the real build-index.sh on a stock page and return the built page's path."""
    stock_p = os.path.join(dest_dir, "stock.html")
    with open(stock_p, "w") as f:
        f.write(stock)
    out = os.path.join(dest_dir, "web", "index.html")
    r = subprocess.run(["sh", BUILD, stock_p, base.BRIDGE, base.STYLE, out], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return out


class WebCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="web-build-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.home = os.path.join(self.tmp, "home")
        self.run_dir = os.path.join(self.tmp, "run")
        self.fake = os.path.join(self.tmp, "fake")
        self.lib = os.path.join(self.tmp, "lib")
        for d in (self.home, self.fake, self.lib):
            os.mkdir(d)
        os.symlink(DIRS_SH, os.path.join(self.lib, "dirs.sh"))
        write_exec(os.path.join(self.fake, "ttyd"), FAKE_TTYD)
        self.page = build_page(self.tmp)
        self.conf_dir = os.path.join(self.home, ".config", "swarmbox")
        self.port = str(20000 + (os.getpid() * 7) % 15000)
        self.assertNotIn(int(self.port), FORBIDDEN_PORTS)

    def conf(self, text):
        os.makedirs(self.conf_dir, exist_ok=True)
        with open(os.path.join(self.conf_dir, "web-terminal.conf"), "w") as f:
            f.write(text)

    def env(self, **extra):
        env = {"PATH": self.fake + ":/usr/bin:/bin", "HOME": self.home, "FAKE_DIR": self.tmp, "SWARMBOX_TEST_LIB": self.lib,
               "SWARMBOX_TEST_RUN_DIR": self.run_dir, "SWARMBOX_TEST_WEB_PAGE": self.page,
               "SWARMBOX_TEST_WEB_PORT": self.port, "SWARMBOX_TEST_WEB_IFACE": "lo", "LANG": "C.UTF-8"}
        for k in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME"):
            env.pop(k, None)
        env.update({k: v for k, v in extra.items() if v is not None})
        for k, v in extra.items():
            if v is None:
                env.pop(k, None)
        found = shutil.which("ttyd", path=env["PATH"])
        self.assertIn(found, (os.path.join(self.fake, "ttyd"), None), "a real ttyd must never run here")
        return env

    def web(self, *args, **extra):
        return subprocess.run(["bash", WEB, *args], env=self.env(**extra), capture_output=True, text=True, timeout=30)

    def ttyd_call(self):
        with open(os.path.join(self.tmp, "ttyd.json")) as f:
            return json.load(f)

    def opts(self, argv):
        out = {}
        for i, a in enumerate(argv):
            if a == "-t" and "=" in argv[i + 1]:   # not the `-t main` of `tmux attach -t main`
                k, v = argv[i + 1].split("=", 1)
                out[k] = v
        return out

    def index(self):
        with open(os.path.join(self.run_dir, "index.html")) as f:
            return f.read()


class Render(WebCase):
    def test_the_built_page_has_the_three_placeholders(self):
        with open(self.page) as f:
            text = f.read()
        for p in ("__SWARMBOX_PADDING__", "__SWARMBOX_CTRL_V__", "__SWARMBOX_CTRL_C__"):
            self.assertIn(p, text)

    def test_defaults_are_substituted_and_no_placeholder_is_left(self):
        r = self.web("render")
        self.assertEqual(r.returncode, 0, r.stderr)
        page = self.index()
        self.assertNotIn("__SWARMBOX_", page)
        self.assertIn("--swarmbox-padding:10px", page)
        self.assertIn('window.__swarmboxClipboard={"ctrlVPaste":true,"ctrlCCopy":true};', page)

    def test_the_users_three_values_are_substituted(self):
        self.conf("padding=24\nctrlVPaste=false\nctrlCCopy=false\n")
        self.assertEqual(self.web("render").returncode, 0)
        page = self.index()
        self.assertIn("--swarmbox-padding:24px", page)
        self.assertIn('{"ctrlVPaste":false,"ctrlCCopy":false}', page)
        self.assertNotIn("__SWARMBOX_", page)

    def test_only_the_word_false_turns_a_switch_off(self):
        self.conf("ctrlVPaste=0\nctrlCCopy=no\n")
        self.web("render")
        self.assertIn('{"ctrlVPaste":true,"ctrlCCopy":true}', self.index())

    def test_a_bad_padding_falls_back_to_10_with_a_message(self):
        for bad in ("abc", "100", "-1", "1.5", "", "10px", "1 2"):
            with self.subTest(bad=bad):
                self.conf("padding=%s\n" % bad)
                r = self.web("render")
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertIn("--swarmbox-padding:10px", self.index())
                if bad:
                    self.assertIn("padding", r.stderr)

    def test_a_changed_conf_changes_the_page_at_the_next_render(self):
        self.conf("padding=3\n")
        self.web("render")
        self.assertIn("--swarmbox-padding:3px", self.index())
        self.conf("padding=4\n")
        self.web("render")
        self.assertIn("--swarmbox-padding:4px", self.index())

    def test_the_source_page_is_never_changed(self):
        before = open(self.page).read()
        self.conf("padding=33\n")
        self.web("render")
        self.assertEqual(open(self.page).read(), before)

    def test_the_run_folder_is_created_and_the_page_is_world_readable(self):
        self.assertFalse(os.path.exists(self.run_dir))
        self.assertEqual(self.web("render").returncode, 0)
        self.assertEqual(os.stat(os.path.join(self.run_dir, "index.html")).st_mode & 0o044, 0o044)
        self.assertEqual([n for n in os.listdir(self.run_dir)], ["index.html"])   # no temp file left

    def test_a_missing_built_page_fails_with_a_message_and_writes_nothing(self):
        r = self.web("render", SWARMBOX_TEST_WEB_PAGE=os.path.join(self.tmp, "nope.html"))
        self.assertEqual(r.returncode, 1)
        self.assertIn("build-index", r.stderr)
        self.assertFalse(os.path.exists(os.path.join(self.run_dir, "index.html")))

    def test_a_page_without_placeholders_is_refused(self):
        # a stale or foreign page: the substitution would silently do nothing
        plain = os.path.join(self.tmp, "plain.html")
        open(plain, "w").write(STOCK)
        r = self.web("render", SWARMBOX_TEST_WEB_PAGE=plain)
        self.assertEqual(r.returncode, 1)
        self.assertIn("placeholder", r.stderr)

    def test_a_value_cannot_inject_into_the_page(self):
        self.conf("padding=1&2\nctrlVPaste=true</script>\n")
        self.web("render")
        page = self.index()
        self.assertNotIn("&2", page)
        self.assertNotIn("true</script>", page)

    def test_conf_in_xdg_config_home_is_used(self):
        alt = os.path.join(self.tmp, "xdg")
        os.makedirs(os.path.join(alt, "swarmbox"))
        open(os.path.join(alt, "swarmbox", "web-terminal.conf"), "w").write("padding=17\n")
        self.web("render", XDG_CONFIG_HOME=alt)
        self.assertIn("--swarmbox-padding:17px", self.index())


class Run(WebCase):
    def run_web(self, **extra):
        r = self.web("run", **extra)
        self.assertEqual(r.returncode, 0, r.stderr)
        return self.ttyd_call()

    def test_it_execs_ttyd_on_the_port_and_interface_given_with_the_rendered_page(self):
        call = self.run_web()
        argv = call["argv"]
        self.assertEqual(argv[argv.index("-p") + 1], self.port)
        self.assertEqual(argv[argv.index("-i") + 1], "lo")
        self.assertIn("-W", argv)
        self.assertIn("-O", argv)
        self.assertEqual(argv[argv.index("--index") + 1], os.path.join(self.run_dir, "index.html"))
        self.assertTrue(os.path.exists(os.path.join(self.run_dir, "index.html")))
        self.assertNotIn(int(argv[argv.index("-p") + 1]), FORBIDDEN_PORTS)

    def test_the_default_port_is_7681_on_every_interface_inside_the_box(self):
        # only the FAKE ttyd runs here: nothing binds anything
        argv = self.run_web(SWARMBOX_TEST_WEB_PORT=None, SWARMBOX_TEST_WEB_IFACE=None)["argv"]
        self.assertEqual(argv[argv.index("-p") + 1], "7681")
        self.assertNotIn("-i", argv)

    def test_ttyd_is_exec_ed_not_forked(self):
        write_exec(os.path.join(self.fake, "ttyd"), '#!/bin/sh\necho $PPID > "$FAKE_DIR/ppid"\n')
        p = subprocess.run(["bash", "-c", 'bash "$0" run; echo $$ > "$FAKE_DIR/me"', WEB], env=self.env(), capture_output=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        # the wrapper bash is the parent of swarmbox-web, which became ttyd: ttyd's parent is that bash
        self.assertEqual(open(os.path.join(self.tmp, "ppid")).read().strip(), open(os.path.join(self.tmp, "me")).read().strip())

    def test_the_default_options_include_font_size_and_theme(self):
        o = self.opts(self.run_web()["argv"])
        self.assertEqual(o["fontSize"], "21")
        self.assertEqual(o["fontWeight"], "400")
        self.assertEqual(json.loads(o["theme"])["background"], "#0c0c0c")
        self.assertIn("monospace", o["fontFamily"])
        self.assertEqual(o["titleFixed"], '"SwarmBox"')

    def test_user_font_size_theme_and_scrollback_reach_ttyd_as_t_options(self):
        theme = '{"background":"#000000","foreground":"#ffffff"}'
        self.conf("fontSize=15\ntheme=%s\nscrollback=5000\n# comment\n  cursorBlink = false  # trailing\n" % theme)
        o = self.opts(self.run_web()["argv"])
        self.assertEqual(o["fontSize"], "15")
        self.assertEqual(json.loads(o["theme"]), json.loads(theme))
        self.assertEqual(o["scrollback"], "5000")
        self.assertEqual(o["cursorBlink"], "false")

    def test_a_font_list_becomes_one_json_string(self):
        self.conf("fontFamily='A B', Consolas, monospace\n")
        o = self.opts(self.run_web()["argv"])
        self.assertEqual(json.loads(o["fontFamily"]), "'A B', Consolas, monospace")

    def test_the_three_page_settings_are_not_passed_to_ttyd(self):
        self.conf("padding=12\nctrlVPaste=false\nctrlCCopy=false\n")
        argv = self.run_web()["argv"]
        o = self.opts(argv)
        for k in ("padding", "ctrlVPaste", "ctrlCCopy"):
            self.assertNotIn(k, o)
        self.assertIn("--swarmbox-padding:12px", self.index())

    def test_the_session_is_swarmbox_attach_when_it_exists_else_tmux_attach(self):
        argv = self.run_web()["argv"]
        self.assertEqual(argv[-4:], ["tmux", "attach", "-t", "main"])
        write_exec(os.path.join(self.fake, "swarmbox-attach"), FAKE_ATTACH)
        argv = self.run_web()["argv"]
        self.assertEqual(argv[-1], "swarmbox-attach")
        self.assertNotIn("tmux", argv[-2:])

    def test_a_utf8_locale_is_made_sure_of(self):
        env_lang = self.run_web(LANG="C")["lang"]
        self.assertEqual(env_lang, "C.UTF-8")
        self.assertEqual(self.run_web(LANG="en_US.UTF-8")["lang"], "en_US.UTF-8")

    def test_a_failed_render_does_not_start_ttyd(self):
        r = self.web("run", SWARMBOX_TEST_WEB_PAGE=os.path.join(self.tmp, "nope.html"))
        self.assertEqual(r.returncode, 1)
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "ttyd.json")))

    def test_ttyd_missing_fails_with_127_and_a_message(self):
        os.unlink(os.path.join(self.fake, "ttyd"))
        if shutil.which("ttyd", path=self.fake + ":/usr/bin:/bin"):
            self.skipTest("a real ttyd is on the minimal PATH")
        r = self.web("run")
        self.assertEqual(r.returncode, 127)
        self.assertIn("ttyd", r.stderr)


class PortedFromWebTerminal(WebCase):
    """Slice 6.2: the cases of v0.1.0's tests/test_web_terminal.py (the v0.1.0 web wrapper), run against swarmbox-web."""

    def run_web(self, **extra):
        r = self.web("run", **extra)
        self.assertEqual(r.returncode, 0, r.stderr)
        return self.ttyd_call()

    def test_defaults_of_the_ttyd_command_line(self):
        argv = self.run_web()["argv"]
        o = self.opts(argv)
        for flag in ("-W", "-O"):
            self.assertIn(flag, argv)
        self.assertEqual((o["fontSize"], o["cursorBlink"], o["titleFixed"]), ("21", "true", '"SwarmBox"'))
        self.assertEqual((o["fontWeight"], o["fontWeightBold"]), ("400", "700"))
        theme = json.loads(o["theme"])
        self.assertEqual((theme["background"], theme["foreground"]), ("#0c0c0c", "#c2c2c2"))
        self.assertEqual(len(theme), 20, "background, foreground, cursor, selection and the 16 ANSI colors")
        families = json.loads(o["fontFamily"])
        self.assertTrue(families.startswith("'JetBrainsMono Nerd Font'"))
        self.assertTrue(families.endswith("monospace"))
        for nf in ("JetBrainsMono NF", "JetBrainsMono NFM", "CaskaydiaCove Nerd Font"):
            self.assertIn(nf, families, "Windows installs Nerd Fonts under these names")

    def test_the_config_file_overrides_and_adds_options(self):
        self.conf("# my terminal\n"
                  "fontFamily='JetBrainsMono Nerd Font', 'JetBrainsMono NFM', Consolas, monospace\n"
                  "  fontSize = 16   # trailing comment\n\nlineHeight=1.1\n"
                  'theme={"background":"#1e1e2e","foreground":"#cdd6f4"}\n'
                  "this line has no equals sign\n")
        argv = self.run_web()["argv"]
        o = self.opts(argv)
        self.assertEqual(json.loads(o["fontFamily"]), "'JetBrainsMono Nerd Font', 'JetBrainsMono NFM', Consolas, monospace")
        self.assertEqual(o["fontSize"], "16", "spaces around = and a trailing comment are ignored")
        self.assertEqual(o["lineHeight"], "1.1")
        self.assertEqual(json.loads(o["theme"]), {"background": "#1e1e2e", "foreground": "#cdd6f4"})
        self.assertEqual(o["cursorBlink"], "true", "defaults the file does not mention are kept")
        self.assertNotIn("this line has no equals sign", " ".join(argv))

    def test_values_are_handed_over_as_valid_json(self):
        self.conf("fontFamily=3270 Nerd Font, monospace\n"
                  'title=say "hi" \\ there\n'
                  "lineHeight=1.25\nbold=true\n"
                  'theme={"background":"#1e1e2e"}\n'
                  'quoted="already a string"\n')
        o = self.opts(self.run_web()["argv"])
        self.assertEqual(json.loads(o["fontFamily"]), "3270 Nerd Font, monospace")   # digits first, still a string
        self.assertEqual(json.loads(o["title"]), 'say "hi" \\ there')
        self.assertEqual(json.loads(o["lineHeight"]), 1.25)
        self.assertIs(json.loads(o["bold"]), True)
        self.assertEqual(json.loads(o["theme"]), {"background": "#1e1e2e"})
        self.assertEqual(json.loads(o["quoted"]), "already a string")

    def test_a_value_may_contain_equals_signs(self):
        self.conf("customGlyphs=a=b\n")
        self.assertEqual(json.loads(self.opts(self.run_web()["argv"])["customGlyphs"]), "a=b")

    def test_the_clipboard_switches_reach_the_page_and_not_ttyd(self):
        self.conf("ctrlVPaste=false\nctrlCCopy=false\npadding=9\nfontSize=17\n")
        o = self.opts(self.run_web()["argv"])
        for k in ("padding", "ctrlVPaste", "ctrlCCopy"):
            self.assertNotIn(k, o)
        self.assertEqual(o["fontSize"], "17")
        self.assertIn('window.__swarmboxClipboard={"ctrlVPaste":false,"ctrlCCopy":false};', self.index())

    def test_an_existing_utf8_locale_is_kept(self):
        for v in ("pt_BR.UTF-8", "en_US.utf8"):
            self.assertEqual(self.run_web(LANG=v)["lang"], v)

    def test_a_non_utf8_locale_is_replaced(self):
        for v in ("C", "POSIX"):
            self.assertEqual(self.run_web(LANG=v)["lang"], "C.UTF-8", v)

    def test_a_missing_locale_is_provided(self):
        self.assertEqual(self.run_web(LANG=None)["lang"], "C.UTF-8")

    def test_lc_all_decides_over_lang(self):
        r = self.web("run", LANG="pt_BR.UTF-8", LC_ALL="C")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.ttyd_call()["lang"], "C.UTF-8")


class Restart(WebCase):
    def start_listener(self):
        """A process of this test that records USR1; the only PID this test ever signals."""
        marker = os.path.join(self.tmp, "usr1")
        p = subprocess.Popen(["bash", "-c", 'trap "echo got >> %s" USR1; echo ready; while :; do sleep 0.05; done' % marker],
                             stdout=subprocess.PIPE, text=True)
        self.addCleanup(lambda: (p.kill(), p.wait(), p.stdout.close()))
        p.stdout.readline()
        return p, marker

    def test_restart_sends_usr1_to_the_pid_in_the_file(self):
        p, marker = self.start_listener()
        os.makedirs(self.run_dir)
        open(os.path.join(self.run_dir, "web-supervisor.pid"), "w").write("%d\n" % p.pid)
        r = self.web("restart")
        self.assertEqual(r.returncode, 0, r.stderr)
        serve_steps.wait_for(lambda: os.path.exists(marker), 5)
        self.assertEqual(open(marker).read().split(), ["got"])
        self.assertIsNone(p.poll())

    def test_no_pid_file_means_no_supervisor(self):
        r = self.web("restart")
        self.assertEqual(r.returncode, 1)
        self.assertIn("supervisor", r.stderr)

    def test_a_stale_garbage_or_unsafe_pid_is_refused_and_nothing_is_signalled(self):
        os.makedirs(self.run_dir)
        dead = subprocess.Popen(["true"])
        dead.wait()
        for content in ("%d\n" % dead.pid, "abc\n", "", "0\n", "1\n", "-1\n", "12 34\n"):
            with self.subTest(content=content):
                open(os.path.join(self.run_dir, "web-supervisor.pid"), "w").write(content)
                r = self.web("restart")
                self.assertEqual(r.returncode, 1, r.stderr)
                self.assertTrue(r.stderr)

    def test_usage(self):
        for args in ((), ("bogus",), ("run", "x")):
            with self.subTest(args=args):
                r = self.web(*args)
                self.assertEqual(r.returncode, 64)
                self.assertIn("usage", r.stderr.lower())


class WithServe(serve_steps.ServeCase):
    """serve (real entrypoint) runs `swarmbox-web run` under its supervisor; `swarmbox-web restart` restarts ttyd."""
    PROGRAMS = ("swarmbox-pubkey", "swarmbox-tool")

    def setUp(self):
        super().setUp()
        os.symlink(WEB, os.path.join(self.fake, "swarmbox-web"))
        self.page = build_page(self.base)
        self.port = str(20000 + (os.getpid() * 11) % 15000)

    def env(self, **extra):
        return super().env(SWARMBOX_TEST_WEB_PAGE=self.page, SWARMBOX_TEST_WEB_PORT=self.port,
                           SWARMBOX_TEST_WEB_IFACE="lo", **extra)

    def starts(self):
        return len(serve_steps.read(os.path.join(self.fake, "ttyd.starts")).split())

    def test_serve_renders_the_page_and_ttyd_gets_the_options(self):
        os.makedirs(os.path.join(self.home, ".config", "swarmbox"))
        serve_steps.put(os.path.join(self.home, ".config", "swarmbox", "web-terminal.conf"), "padding=13\nfontSize=17\n")
        p = self.run_ready()
        self.assertTrue(serve_steps.wait_for(lambda: any(c.startswith("ttyd ") for c in self.calls())))
        call = [c for c in self.calls() if c.startswith("ttyd ")][0]
        self.assertIn("-p %s" % self.port, call)
        self.assertIn("-t fontSize=17", call)
        self.assertNotIn("7681", call)
        page = serve_steps.read(os.path.join(self.run_dir, "index.html"))
        self.assertIn("--swarmbox-padding:13px", page)
        self.assertNotIn("__SWARMBOX_", page)
        self.stop(p)

    def test_swarmbox_web_restart_restarts_ttyd_and_the_box_stays_up(self):
        p = self.run_ready()
        self.assertTrue(serve_steps.wait_for(lambda: self.starts() == 1))
        old = serve_steps.read(os.path.join(self.fake, "ttyd.pid")).strip()
        serve_steps.put(os.path.join(self.home, "x"), "")
        os.makedirs(os.path.join(self.home, ".config", "swarmbox"), exist_ok=True)
        serve_steps.put(os.path.join(self.home, ".config", "swarmbox", "web-terminal.conf"), "padding=19\n")
        r = subprocess.run(["bash", WEB, "restart"], env=self.env(), capture_output=True, text=True, timeout=20)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(serve_steps.wait_for(lambda: self.starts() == 2), "ttyd was not restarted")
        self.assertTrue(serve_steps.wait_for(lambda: not serve_steps.alive(int(old)), 3))
        self.assertIn("--swarmbox-padding:19px", serve_steps.read(os.path.join(self.run_dir, "index.html")))
        self.assertIsNone(p.poll())
        self.stop(p)


class Static(unittest.TestCase):
    def test_script_is_bash_executable_and_clean(self):
        with open(WEB) as f:
            self.assertTrue(f.readline().startswith("#!/bin/bash"))
        self.assertEqual(subprocess.run(["bash", "-n", WEB], capture_output=True).returncode, 0)
        if shutil.which("shellcheck"):
            r = subprocess.run(["shellcheck", "-s", "bash", WEB], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stdout)

    def test_script_uses_no_python_at_run_time(self):
        with open(WEB) as f:
            text = f.read()
        for line in text.splitlines():
            if not line.lstrip().startswith("#"):
                self.assertNotIn("python", line)

    def test_dockerfile_builds_the_page_and_installs_swarmbox_web(self):
        with open(os.path.join(ROOT, "Dockerfile")) as f:
            d = f.read()
        self.assertIn("sh /usr/local/share/swarmbox/build-index.sh", d)
        self.assertIn("COPY container/scripts/swarmbox-web.sh /usr/local/bin/swarmbox-web", d)
        self.assertIn("/usr/local/bin/swarmbox-web", d.split("COPY container/entrypoint.sh")[1])  # chmod 755

    def test_the_supervisor_runs_swarmbox_web_run(self):
        with open(os.path.join(ROOT, "container", "entrypoint.sh")) as f:
            self.assertIn("TTYD_CMD=(swarmbox-web run)", f.read())


if __name__ == "__main__":
    unittest.main(verbosity=2)
