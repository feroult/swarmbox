"""Container/web/build-index.sh assembles the page with three placeholders.
Run: python3 tests/test_build_index.py
"""
import os
import re
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
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

    def test_page_has_the_three_placeholders_and_both_assets(self):
        r, out = self.build()
        self.assertEqual(r.returncode, 0, r.stderr)
        page = open(out).read()
        for p in ("__SWARMBOX_PADDING__", "__SWARMBOX_CTRL_V__", "__SWARMBOX_CTRL_C__"):
            self.assertEqual(page.count(p), 1, p)
        self.assertIn("var a=1;", page)
        self.assertIn("body{margin:0}", page)
        self.assertIn("<div id=terminal>", page)
        self.assertEqual(set(re.findall(r"__SWARMBOX_\w+__", page)), {"__SWARMBOX_PADDING__", "__SWARMBOX_CTRL_V__", "__SWARMBOX_CTRL_C__"})

    def test_substitution_gives_valid_script_config(self):
        r, out = self.build()
        page = open(out).read().replace("__SWARMBOX_PADDING__", "12").replace("__SWARMBOX_CTRL_V__", "true").replace("__SWARMBOX_CTRL_C__", "false")
        self.assertIn('window.__swarmboxClipboard={"ctrlVPaste":true,"ctrlCCopy":false};', page)
        self.assertIn("--swarmbox-padding:12px", page)

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
