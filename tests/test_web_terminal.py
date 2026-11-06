#!/usr/bin/env python3
"""Tests for container/scripts/web-terminal.sh (how it builds the ttyd command line).

Run:  python3 tests/test_web_terminal.py

A fake `ttyd` records the arguments it was started with, so nothing real is served.
"""
import json
import os
import stat
import subprocess
import tempfile
import time
import unittest

from helpers import ROOT

SCRIPT = os.path.join(ROOT, "container", "scripts", "web-terminal.sh")
SHIM = """#!/bin/sh
for a in "$@"; do printf '%s\\n' "$a"; done > "$OUT"
env | grep -E '^(LANG|LC_ALL)=' > "$OUT.env"
sleep 2
"""


class WebTerminal(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp()
        self.bin = tempfile.mkdtemp()
        self.out = os.path.join(self.home, "args.txt")
        shim = os.path.join(self.bin, "ttyd")
        with open(shim, "w") as f:
            f.write(SHIM)
        os.chmod(shim, os.stat(shim).st_mode | stat.S_IXUSR)

    def conf(self, text):
        os.makedirs(os.path.join(self.home, ".swarmbox"), exist_ok=True)
        with open(os.path.join(self.home, ".swarmbox", "web-terminal.conf"), "w") as f:
            f.write(text)

    def run_script(self, web="1", extra=None):
        env = {"HOME": self.home, "PATH": self.bin + os.pathsep + os.environ["PATH"], "OUT": self.out,
               "SWARMBOX_WEB_PORT": "17999"}
        if web:
            env["SWARMBOX_WEB"] = web
        env.update({"SWARMBOX_TTYD_STOCK": "/nonexistent/stock.html", "SWARMBOX_TTYD_BRIDGE": "/nonexistent/bridge.js"})
        env.update(extra or {})
        subprocess.run(["bash", SCRIPT], env=env, check=True, timeout=10)
        for _ in range(30):
            if os.path.exists(self.out):
                time.sleep(0.1)
                break
            time.sleep(0.1)
        if not os.path.exists(self.out):
            return None
        with open(self.out) as f:
            args = f.read().splitlines()
        opts = {}
        for i, a in enumerate(args):
            if a == "-t":
                k, _, v = args[i + 1].partition("=")
                opts[k] = v
        return args, opts

    def test_not_started_without_the_web_flag(self):
        self.assertIsNone(self.run_script(web=""))

    def test_defaults(self):
        args, opts = self.run_script()
        self.assertEqual(args[:2], ["-p", "17999"])
        self.assertIn("-W", args)
        self.assertIn("-O", args)
        self.assertEqual(args[-5:], ["tmux", "new", "-A", "-s", "main"])
        # values reach ttyd as JSON: numbers/booleans bare, strings quoted
        self.assertEqual((opts["fontSize"], opts["cursorBlink"], opts["titleFixed"]), ("21", "true", '"SwarmBox"'))
        self.assertEqual((opts["fontWeight"], opts["fontWeightBold"]), ("400", "700"))
        theme = json.loads(opts["theme"])
        self.assertEqual((theme["background"], theme["foreground"]), ("#0c0c0c", "#c2c2c2"), "dark out of the box")
        self.assertEqual(len(theme), 20, "background, foreground, cursor, selection and the 16 ANSI colors")
        families = json.loads(opts["fontFamily"])
        self.assertTrue(families.startswith("'JetBrainsMono Nerd Font'"))
        self.assertTrue(families.endswith("monospace"))
        for nf in ("JetBrainsMono NF", "JetBrainsMono NFM", "CaskaydiaCove Nerd Font"):
            self.assertIn(nf, families, "Windows installs Nerd Fonts under these names")

    def test_config_file_overrides_and_adds(self):
        self.conf("""# my terminal
fontFamily='JetBrainsMono Nerd Font', 'JetBrainsMono NFM', Consolas, monospace
  fontSize = 16   # trailing comment

lineHeight=1.1
theme={"background":"#1e1e2e","foreground":"#cdd6f4"}
this line has no equals sign
""")
        args, opts = self.run_script()
        # the whole list as ONE JSON string: ttyd would otherwise keep only the first family
        self.assertEqual(json.loads(opts["fontFamily"]),
                         "'JetBrainsMono Nerd Font', 'JetBrainsMono NFM', Consolas, monospace")
        self.assertEqual(opts["fontSize"], "16", "spaces around = and a trailing comment are ignored")
        self.assertEqual(opts["lineHeight"], "1.1")
        self.assertEqual(json.loads(opts["theme"]), {"background": "#1e1e2e", "foreground": "#cdd6f4"})
        self.assertEqual(opts["cursorBlink"], "true", "defaults not mentioned in the file are kept")
        self.assertNotIn("this line has no equals sign", " ".join(args))

    def test_values_are_handed_over_as_valid_json(self):
        self.conf("fontFamily=3270 Nerd Font, monospace\n"
                  'title=say "hi" \\ there\n'
                  "lineHeight=1.25\n"
                  "bold=true\n"
                  'theme={"background":"#1e1e2e"}\n'
                  'quoted="already a string"\n')
        _, opts = self.run_script()
        # starts with digits and still must stay a string
        self.assertEqual(json.loads(opts["fontFamily"]), "3270 Nerd Font, monospace")
        self.assertEqual(json.loads(opts["title"]), 'say "hi" \\ there')
        self.assertEqual(json.loads(opts["lineHeight"]), 1.25)
        self.assertIs(json.loads(opts["bold"]), True)
        self.assertEqual(json.loads(opts["theme"]), {"background": "#1e1e2e"})
        self.assertEqual(json.loads(opts["quoted"]), "already a string")

    def locale_seen_by_ttyd(self, extra=None):
        self.assertIsNotNone(self.run_script(extra=extra))
        with open(self.out + ".env") as f:
            return dict(line.split("=", 1) for line in f.read().splitlines())

    def test_a_utf8_locale_is_provided_when_there_is_none(self):
        # without one, bash drops an accented character typed on its own (dead key + letter)
        self.assertEqual(self.locale_seen_by_ttyd(), {"LANG": "C.UTF-8"})

    def test_an_existing_utf8_locale_is_kept(self):
        self.assertEqual(self.locale_seen_by_ttyd({"LANG": "pt_BR.UTF-8"}), {"LANG": "pt_BR.UTF-8"})
        self.assertEqual(self.locale_seen_by_ttyd({"LANG": "en_US.utf8"}), {"LANG": "en_US.utf8"})

    def test_a_non_utf8_locale_is_replaced(self):
        self.assertEqual(self.locale_seen_by_ttyd({"LANG": "C"}), {"LANG": "C.UTF-8"})
        self.assertEqual(self.locale_seen_by_ttyd({"LANG": "POSIX"}), {"LANG": "C.UTF-8"})

    def test_lc_all_decides_over_lang(self):
        seen = self.locale_seen_by_ttyd({"LANG": "pt_BR.UTF-8", "LC_ALL": "C"})
        self.assertEqual(seen, {"LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"})

    # ---- clipboard bridge: ttyd's page with a script injected ---------------------------------------
    def bridge_env(self, page="<html><body><p>ttyd</p></body></html>", js="/* bridge */ var x = 1;"):
        stock = os.path.join(self.home, "stock.html")
        bridge = os.path.join(self.home, "bridge.js")
        with open(stock, "w") as f:
            f.write(page)
        with open(bridge, "w") as f:
            f.write(js)
        return {"SWARMBOX_TTYD_STOCK": stock, "SWARMBOX_TTYD_BRIDGE": bridge}

    def index_path(self):
        return os.path.join(self.home, ".swarmbox", "ttyd-index.html")

    def read_index(self):
        with open(self.index_path()) as f:
            return f.read()

    def test_ttyd_serves_its_page_with_the_bridge_injected_before_the_body_ends(self):
        args, _ = self.run_script(extra=self.bridge_env())
        self.assertEqual(args[args.index("--index") + 1], self.index_path())
        page = self.read_index()
        self.assertIn('window.__swarmboxClipboard={"ctrlVPaste": true, "ctrlCCopy": true}', page)
        self.assertIn("/* bridge */ var x = 1;", page)
        self.assertTrue(page.startswith("<html><body><p>ttyd</p><script>"))
        self.assertTrue(page.endswith("</script></body></html>"))
        self.assertEqual(page.count("</body>"), 1)

    def test_without_the_page_or_the_bridge_ttyd_serves_its_own_page(self):
        args, _ = self.run_script()
        self.assertNotIn("--index", args)
        env = self.bridge_env()
        os.remove(env["SWARMBOX_TTYD_BRIDGE"])
        args, _ = self.run_script(extra=env)
        self.assertNotIn("--index", args)

    def test_an_unexpected_page_falls_back_to_the_original(self):
        args, _ = self.run_script(extra=self.bridge_env(page="<html>no body end</html>"))
        self.assertNotIn("--index", args)
        self.assertFalse(os.path.exists(self.index_path()))

    def test_clipboard_options_are_consumed_not_passed_to_ttyd(self):
        self.conf("ctrlVPaste=false\nctrlCCopy=false\npadding=9\nfontSize=17\n")
        args, opts = self.run_script(extra=self.bridge_env())
        self.assertNotIn("padding", opts, "padding is CSS, not a ttyd option")
        self.assertNotIn("ctrlVPaste", opts)
        self.assertNotIn("ctrlCCopy", opts)
        self.assertEqual(opts["fontSize"], "17")
        self.assertIn('{"ctrlVPaste": false, "ctrlCCopy": false}', self.read_index())

    def test_the_page_is_rebuilt_only_when_something_changed(self):
        env = self.bridge_env()
        self.run_script(extra=env)
        first = os.stat(self.index_path()).st_mtime_ns
        time.sleep(0.05)
        self.run_script(extra=env)
        self.assertEqual(os.stat(self.index_path()).st_mtime_ns, first, "same inputs: not rebuilt")
        with open(env["SWARMBOX_TTYD_BRIDGE"], "w") as f:
            f.write("var changed = true;")
        self.run_script(extra=env)
        self.assertIn("var changed = true;", self.read_index())
        self.conf("ctrlVPaste=false\n")
        self.run_script(extra=env)
        self.assertIn('"ctrlVPaste": false', self.read_index())

    def test_a_script_tag_inside_the_bridge_cannot_end_the_injected_script(self):
        self.run_script(extra=self.bridge_env(js="var s = '</script><b>';"))
        page = self.read_index()
        self.assertEqual(page.count("</script>"), 2, "only our own two closing tags")
        self.assertNotIn("</script><b>", page)

    def test_value_may_contain_equals_signs(self):
        self.conf("customGlyphs=a=b\n")
        _, opts = self.run_script()
        self.assertEqual(json.loads(opts["customGlyphs"]), "a=b")


if __name__ == "__main__":
    unittest.main(verbosity=2)
