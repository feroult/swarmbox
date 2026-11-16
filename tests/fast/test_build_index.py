"""Container/web/build-index.sh assembles the page with three placeholders.
Run: python3 tests/fast/test_build_index.py
"""
import os
import re
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "support"))
from helpers import ROOT  # noqa: E402

SCRIPT = os.path.join(ROOT, "container", "web", "build-index.sh")
STOCK = "<html><head><title>t</title></head><body><div id=terminal></div></body></html>"


class BuildIndex(unittest.TestCase):
    def build(self, stock=STOCK, js="var a=1;", css="body{margin:0}"):
        d = tempfile.mkdtemp()
        self.addCleanup(lambda: subprocess.run(["rm", "-rf", d]))
        paths = {}
        for name, text in (("stock.html", stock), ("b.js", js), ("s.css", css)):
            paths[name] = os.path.join(d, name)
            with open(paths[name], "w") as f:
                f.write(text)
        out = os.path.join(d, "sub", "index.html")
        r = subprocess.run(["sh", SCRIPT, paths["stock.html"], paths["b.js"], paths["s.css"], out], capture_output=True, text=True)
        return r, out

    def test_page_has_the_eight_placeholders_and_both_assets(self):
        r, out = self.build()
        self.assertEqual(r.returncode, 0, r.stderr)
        page = open(out).read()
        for p in ("__SWARMBOX_PADDING__", "__SWARMBOX_CTRL_V__", "__SWARMBOX_CTRL_C__", "__SWARMBOX_SCROLLBAR__", "__SWARMBOX_SCROLLBAR_FF__",
                  "__SWARMBOX_STRIP__", "__SWARMBOX_STRIP_CUSTOM__", "__SWARMBOX_STRIP_KEYS__"):
            self.assertEqual(page.count(p), 1, p)
        self.assertIn("var a=1;", page)
        self.assertIn("body{margin:0}", page)
        self.assertIn("<div id=terminal>", page)
        self.assertEqual(set(re.findall(r"__SWARMBOX_\w+__", page)), {"__SWARMBOX_PADDING__", "__SWARMBOX_CTRL_V__", "__SWARMBOX_CTRL_C__",
                                                                          "__SWARMBOX_SCROLLBAR__", "__SWARMBOX_SCROLLBAR_FF__", "__SWARMBOX_STRIP__",
                                                                          "__SWARMBOX_STRIP_CUSTOM__", "__SWARMBOX_STRIP_KEYS__"})

    def test_substitution_gives_valid_script_config(self):
        r, out = self.build()
        page = open(out).read().replace("__SWARMBOX_PADDING__", "12").replace("__SWARMBOX_CTRL_V__", "true").replace("__SWARMBOX_CTRL_C__", "false")
        page = page.replace("__SWARMBOX_SCROLLBAR__", "6").replace("__SWARMBOX_SCROLLBAR_FF__", "thin")
        page = page.replace("__SWARMBOX_STRIP__", "auto").replace("__SWARMBOX_STRIP_CUSTOM__", "false").replace("__SWARMBOX_STRIP_KEYS__", "Esc=Escape")
        self.assertIn('window.__swarmboxClipboard={"ctrlVPaste":true,"ctrlCCopy":false};', page)
        self.assertIn('window.__swarmboxStripCfg={"mode":"auto","custom":false,"keys":"Esc=Escape"};', page)
        self.assertIn("--swarmbox-padding:12px;--swarmbox-scrollbar:6px;--swarmbox-scrollbar-ff:thin", page)

    def test_the_page_gets_a_viewport_meta_unless_it_has_one(self):
        r, out = self.build()
        page = open(out).read()
        self.assertEqual(page.count('name="viewport"'), 1)
        for part in ("width=device-width", "viewport-fit=cover", "interactive-widget=resizes-content"):
            self.assertIn(part, page)
        r, out = self.build(stock='<html><head><meta name="viewport" content="width=800"></head><body></body></html>')
        self.assertEqual(open(out).read().count('name="viewport"'), 1, "an existing one is kept, not doubled")

    def test_closing_tags_inside_assets_are_escaped(self):
        r, out = self.build(js="var s='</script>';", css="/* </style> */")
        page = open(out).read()
        self.assertEqual(page.count("</script>"), 1 + 1)  # the config script and the bridge, no more
        self.assertEqual(page.count("</style>"), 1)

    def test_a_stock_page_without_a_body_fails_and_leaves_no_output(self):
        r, out = self.build(stock="<html></html>")
        self.assertNotEqual(r.returncode, 0)
        self.assertFalse(os.path.exists(out))

    def test_posix_sh_and_executable(self):
        self.assertTrue(os.access(SCRIPT, os.X_OK))
        with open(SCRIPT) as f:
            self.assertTrue(f.readline().startswith("#!/bin/sh"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
