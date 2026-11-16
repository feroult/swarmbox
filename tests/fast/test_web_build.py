"""The page of the web terminal. build-index.sh assembles it at image build from ttyd's own page with the clipboard script, the style and eight
placeholders; `swarmbox-web` (container/scripts/swarmbox-web.sh) turns it into box:/tmp/swarmbox/index.html at every start with a plain text
substitution of the values of web-terminal.conf (padding, ctrlVPaste, ctrlCCopy, scrollbar, strip, stripKeys), builds ttyd's `-t key=value` options
(font, theme, size, scrollback, anything else) from the same file, and execs ttyd; `swarmbox-web restart` signals the supervisor.

Layers:
  1. build-index.sh on a small stock page.
  2. swarmbox-web against a FAKE ttyd (records its arguments). Nothing is served. No port it hands out is 7681, 8889 or 43323 (the ports of
     this very network namespace).
  3. serve (the real entrypoint, fake tmux/podman/ttyd) with the real swarmbox-web: `swarmbox-web restart` restarts ttyd.
  The page in a real browser is in tests/slow/test_clipboard_bridge.py, test_web_style.py and test_web_strip.py; the strip's script and its settings
  are in test_web_strip_script.py.

Test-only variables (not in the configuration table): SWARMBOX_TEST_LIB, SWARMBOX_TEST_RUN_DIR,
SWARMBOX_TEST_WEB_PAGE (the built page, default /usr/local/share/swarmbox/web/index.html), SWARMBOX_TEST_WEB_PORT (default
7681), SWARMBOX_TEST_WEB_IFACE (ttyd -i value, default none = all interfaces inside the box).
Run with: python3 tests/fast/test_web_build.py
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "support"))
from helpers import ROOT  # noqa: E402
import serve_support as serve_steps  # noqa: E402

WEB = os.path.join(ROOT, "container", "scripts", "swarmbox-web.sh")
BUILD = os.path.join(ROOT, "container", "web", "build-index.sh")
DIRS_SH = os.path.join(ROOT, "container", "scripts", "dirs.sh")
BRIDGE = os.path.join(ROOT, "container", "web", "ttyd-clipboard.js")
STYLE = os.path.join(ROOT, "container", "web", "ttyd-style.css")
FORBIDDEN_PORTS = (7681, 8889, 43323)
STOCK = "<html><head><title>t</title></head><body><div id=terminal></div></body></html>"

FAKE_TTYD = '''#!/usr/bin/env python3
import json, os, sys
with open(os.path.join(os.environ["FAKE_DIR"], "ttyd.json"), "w") as f:
    json.dump({"argv": sys.argv[1:], "pid": os.getpid(), "lang": os.environ.get("LANG")}, f)
'''
FAKE_ATTACH = '#!/bin/sh\nexit 0\n'


def put(path, text):
    with open(path, "w") as f:
        f.write(text)


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
    r = subprocess.run(["sh", BUILD, stock_p, BRIDGE, STYLE, out], capture_output=True, text=True)
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
    def test_defaults_are_substituted_and_no_placeholder_is_left(self):
        r = self.web("render")
        self.assertEqual(r.returncode, 0, r.stderr)
        page = self.index()
        self.assertNotIn("__SWARMBOX_", page)
        self.assertIn("--swarmbox-padding:10px", page)
        self.assertIn('window.__swarmboxClipboard={"ctrlVPaste":true,"ctrlCCopy":true};', page)
        self.assertIn("--swarmbox-scrollbar:0px;--swarmbox-scrollbar-ff:none", page, "no scrollbar by default: tmux owns the scrollback")

    def test_scrollbar_true_brings_back_a_thin_scrollbar_and_nothing_else_does(self):
        self.conf("scrollbar=true\n")
        self.assertEqual(self.web("render").returncode, 0)
        self.assertIn("--swarmbox-scrollbar:6px;--swarmbox-scrollbar-ff:thin", self.index())
        for value in ("false", "1", "yes", "True", ""):
            self.conf("scrollbar=%s\n" % value)
            self.web("render")
            self.assertIn("--swarmbox-scrollbar:0px;--swarmbox-scrollbar-ff:none", self.index(), value)

    def test_the_browser_keeps_no_scrollback_unless_the_bar_is_on_or_the_conf_sets_one(self):
        for conf, want in (("", "0"), ("scrollbar=false\n", "0"), ("scrollbar=true\n", None), ("scrollback=500\n", "500"),
                           ("scrollbar=true\nscrollback=0\n", "0"), ("scrollbar=true\nscrollback=2000\n", "2000")):
            self.conf(conf)
            self.assertEqual(self.web("run").returncode, 0, conf)
            self.assertEqual(self.opts(self.ttyd_call()["argv"]).get("scrollback"), want, conf)

    def test_only_the_word_false_turns_a_switch_off_and_a_bad_padding_is_the_default(self):
        self.conf("ctrlVPaste=0\nctrlCCopy=no\npadding=lots\n")
        self.web("render")
        page = self.index()
        self.assertIn('{"ctrlVPaste":true,"ctrlCCopy":true}', page)
        self.assertIn("--swarmbox-padding:10px", page)
        self.conf("ctrlVPaste=false\nctrlCCopy=false\npadding=12\n")
        self.web("render")
        page = self.index()
        self.assertIn('{"ctrlVPaste":false,"ctrlCCopy":false}', page)
        self.assertIn("--swarmbox-padding:12px", page)

    def test_a_missing_built_page_fails_with_a_message_and_writes_nothing(self):
        r = self.web("render", SWARMBOX_TEST_WEB_PAGE=os.path.join(self.tmp, "nope.html"))
        self.assertEqual(r.returncode, 1)
        self.assertIn("build-index", r.stderr)
        self.assertFalse(os.path.exists(os.path.join(self.run_dir, "index.html")))

    def test_a_value_cannot_inject_into_the_page(self):
        self.conf("padding=1&2\nctrlVPaste=true</script>\n")
        self.web("render")
        page = self.index()
        self.assertNotIn("&2", page)
        self.assertNotIn("true</script>", page)

    def test_the_settings_the_page_consumes_never_reach_ttyd_as_options(self):
        self.conf("padding=13\nscrollbar=true\nctrlVPaste=false\nctrlCCopy=false\nstrip=on\nstripKeys=Esc=Escape\nfontSize=17\n")
        self.assertEqual(self.web("run").returncode, 0)
        opts = self.opts(self.ttyd_call()["argv"])
        for consumed in ("padding", "scrollbar", "ctrlVPaste", "ctrlCCopy", "strip", "stripKeys"):
            self.assertNotIn(consumed, opts)
        self.assertEqual(opts.get("fontSize"), "17")

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

    def test_user_font_size_theme_and_scrollback_reach_ttyd_as_t_options(self):
        theme = '{"background":"#000000","foreground":"#ffffff"}'
        self.conf("fontSize=15\ntheme=%s\nscrollback=5000\n# comment\n  cursorBlink = false  # trailing\n" % theme)
        o = self.opts(self.run_web()["argv"])
        self.assertEqual(o["fontSize"], "15")
        self.assertEqual(json.loads(o["theme"]), json.loads(theme))
        self.assertEqual(o["scrollback"], "5000")
        self.assertEqual(o["cursorBlink"], "false")

    def test_the_selection_of_the_browser_is_the_violet_that_tmux_uses_for_its_own(self):
        # a selection made with Shift (the browser's, not tmux's) must not be another color than tmux's: both are the violet of the box
        o = self.opts(self.run_web()["argv"])
        theme = json.loads(o["theme"])
        with open(os.path.join(ROOT, "container", "config", "tmux.conf")) as f:
            tmux = [l for l in f if l.startswith("setw -g mode-style")][0]
        self.assertEqual(theme["selectionBackground"], tmux.split("bg=")[1].split(",")[0])
        self.assertEqual(theme["selectionBackground"], "#6d28d9")
        self.assertEqual(theme["selectionForeground"], tmux.split("fg=")[1].split('"')[0])

    def test_mac_option_is_meta_by_default_and_the_user_can_turn_it_off(self):
        # without it Option+1 types a character on a Mac and tmux's Alt+digit window shortcuts never arrive
        self.assertEqual(self.opts(self.run_web()["argv"])["macOptionIsMeta"], "true")
        self.conf("macOptionIsMeta=false\n")
        self.assertEqual(self.opts(self.run_web()["argv"])["macOptionIsMeta"], "false")

    def test_ttyd_always_gets_a_utf8_locale_so_an_accent_typed_alone_is_not_dropped(self):
        for env in ({"LANG": "C"}, {"LANG": None}, {"LANG": "en_US.UTF-8"}):
            with self.subTest(env=env):
                lang = self.run_web(**env)["lang"]
                self.assertEqual(lang, env["LANG"] if env["LANG"] and "UTF" in env["LANG"] else "C.UTF-8")

    def test_a_value_is_handed_to_ttyd_as_json_so_a_font_list_keeps_its_fallbacks(self):
        # ttyd stops reading at the first thing that parses: 'A', 'B', monospace would become A
        self.conf("fontFamily='JetBrains Mono', Menlo, monospace\nfontSize=15\ncursorBlink=true\nletterSpacing=0.5\nthemeName=a\"b\n")
        o = self.opts(self.run_web()["argv"])
        self.assertEqual(o["fontFamily"], '"\'JetBrains Mono\', Menlo, monospace"')
        self.assertEqual([o["fontSize"], o["cursorBlink"], o["letterSpacing"]], ["15", "true", "0.5"])
        self.assertEqual(o["themeName"], '"a\\"b"')

    def test_the_session_is_swarmbox_attach_when_it_exists_else_tmux_attach(self):
        argv = self.run_web()["argv"]
        self.assertEqual(argv[-4:], ["tmux", "attach", "-t", "main"])
        write_exec(os.path.join(self.fake, "swarmbox-attach"), FAKE_ATTACH)
        argv = self.run_web()["argv"]
        self.assertEqual(argv[-2:], ["swarmbox-attach", "--web"])   # --web keeps tmux's status bar (the tabs) in the browser

    def test_a_failed_render_does_not_start_ttyd(self):
        r = self.web("run", SWARMBOX_TEST_WEB_PAGE=os.path.join(self.tmp, "nope.html"))
        self.assertEqual(r.returncode, 1)
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "ttyd.json")))

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
        put(os.path.join(self.run_dir, "web-supervisor.pid"), "%d\n" % p.pid)
        r = self.web("restart")
        self.assertEqual(r.returncode, 0, r.stderr)
        serve_steps.wait_for(lambda: os.path.exists(marker), 5)
        self.assertEqual(serve_steps.read(marker).split(), ["got"])
        self.assertIsNone(p.poll())

    def test_a_stale_garbage_or_unsafe_pid_is_refused_and_nothing_is_signalled(self):
        os.makedirs(self.run_dir)
        dead = subprocess.Popen(["true"])
        dead.wait()
        r = self.web("restart")   # no pid file at all: the supervisor is not running
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertIn("no web terminal supervisor is running", r.stderr)
        for content in ("%d\n" % dead.pid, "abc\n", "", "0\n", "1\n", "-1\n", "12 34\n"):
            with self.subTest(content=content):
                put(os.path.join(self.run_dir, "web-supervisor.pid"), content)
                r = self.web("restart")
                self.assertEqual(r.returncode, 1, r.stderr)
                self.assertTrue(r.stderr)

class WithServe(serve_steps.ServeCase):
    """serve (real entrypoint) runs `swarmbox-web run` under its supervisor; `swarmbox-web restart` restarts ttyd."""
    PROGRAMS = ("swarmbox-pubkey", "swarmbox-addon")

    def setUp(self):
        super().setUp()
        os.replace(os.path.join(self.fake, "swarmbox-web"), os.path.join(self.fake, "ttyd"))   # the base set-up's fake becomes the ttyd that swarmbox-web runs
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


BUILD_STOCK = "<html><head><title>t</title></head><body><div id=terminal></div></body></html>"
PLACEHOLDERS = {"__SWARMBOX_PADDING__", "__SWARMBOX_CTRL_V__", "__SWARMBOX_CTRL_C__", "__SWARMBOX_SCROLLBAR__", "__SWARMBOX_SCROLLBAR_FF__",
                "__SWARMBOX_STRIP__", "__SWARMBOX_STRIP_CUSTOM__", "__SWARMBOX_STRIP_KEYS__"}


class BuildIndex(unittest.TestCase):
    """build-index.sh itself, on a stock page of a few bytes."""

    def build(self, stock=BUILD_STOCK, js="var a=1;", css="body{margin:0}"):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        paths = {}
        for name, text in (("stock.html", stock), ("b.js", js), ("s.css", css)):
            paths[name] = os.path.join(d, name)
            with open(paths[name], "w") as f:
                f.write(text)
        out = os.path.join(d, "sub", "index.html")
        r = subprocess.run(["sh", BUILD, paths["stock.html"], paths["b.js"], paths["s.css"], out], capture_output=True, text=True)
        return r, out

    def test_the_page_has_each_placeholder_once_and_both_assets_and_the_stock_page(self):
        r, out = self.build()
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(out) as f:
            page = f.read()
        for p in PLACEHOLDERS:
            self.assertEqual(page.count(p), 1, p)
        self.assertEqual(set(re.findall(r"__SWARMBOX_\w+__", page)), PLACEHOLDERS)
        for part in ("var a=1;", "body{margin:0}", "<div id=terminal>"):
            self.assertIn(part, page)

    def test_the_page_gets_a_viewport_meta_unless_it_has_one(self):
        r, out = self.build()
        with open(out) as f:
            page = f.read()
        self.assertEqual(page.count('name="viewport"'), 1)
        for part in ("width=device-width", "viewport-fit=cover", "interactive-widget=resizes-content"):
            self.assertIn(part, page)
        r, out = self.build(stock='<html><head><meta name="viewport" content="width=800"></head><body></body></html>')
        with open(out) as f:
            self.assertEqual(f.read().count('name="viewport"'), 1, "an existing one is kept, not doubled")

    def test_closing_tags_inside_assets_are_escaped(self):
        r, out = self.build(js="var s='</script>';", css="/* </style> */")
        with open(out) as f:
            page = f.read()
        self.assertEqual(page.count("</script>"), 2)  # the config script and the bridge, no more
        self.assertEqual(page.count("</style>"), 1)

    def test_a_stock_page_without_a_body_fails_and_leaves_no_output(self):
        r, out = self.build(stock="<html></html>")
        self.assertNotEqual(r.returncode, 0)
        self.assertFalse(os.path.exists(out))


if __name__ == "__main__":
    unittest.main(verbosity=2)
