"""The tab line of the terminal cockpit: the agent badge comes from what the program reports (OSC 7501 `app`) or its process name.

Runs cockpit.mjs under node with the real @xterm/headless of the image (skipped where it is not installed). Run: python3 tests/fast/test_cockpit_tabs.py
"""
import glob
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "support"))
from helpers import ROOT  # noqa: E402

WEB = os.path.join(ROOT, "container", "web", "herdr")
MODULES = [p for p in ("/usr/local/share/swarmbox/herdr-web/node_modules", os.path.join(WEB, "node_modules")) if os.path.isdir(os.path.join(p, "@xterm", "headless"))]

HARNESS = r"""
import { smartTabParts } from './cockpit.mjs';
const tab = (app, fg) => ({ name: 'shell', status: app ? { app } : undefined, foreground: { name: fg, cwd: '/' } });
console.log(JSON.stringify({
  claudeCode: smartTabParts(tab('claude-code', '2.1.332')).pill,
  antigravity: smartTabParts(tab('antigravity', 'agy')).pill,
  byProcess: smartTabParts(tab('', 'opencode')).pill,
  shell: smartTabParts(tab('', 'bash')).pill,
}));
"""


@unittest.skipUnless(shutil.which("node") and MODULES, "node or @xterm/headless is not installed")
class CockpitTabBadge(unittest.TestCase):
    def test_the_badge_names_the_agent_by_what_it_reports(self):
        tmp = tempfile.mkdtemp(prefix="cockpit-tabs-")
        self.addCleanup(shutil.rmtree, tmp, True)
        for f in glob.glob(os.path.join(WEB, "*.mjs")):
            shutil.copy(f, tmp)
        os.symlink(MODULES[0], os.path.join(tmp, "node_modules"))
        with open(os.path.join(tmp, "harness.mjs"), "w", encoding="utf-8") as f:
            f.write(HARNESS)
        p = subprocess.run(["node", "harness.mjs"], cwd=tmp, env=dict(os.environ, HOME=tmp), capture_output=True, text=True, timeout=60)
        self.assertEqual(p.returncode, 0, p.stderr)
        got = json.loads(p.stdout.strip().splitlines()[-1])
        self.assertEqual(got, {"claudeCode": "claude", "antigravity": "agy", "byProcess": "opencode", "shell": ""})

if __name__ == "__main__":
    unittest.main()
