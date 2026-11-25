"""The wheel (two fingers on a trackpad) in the terminal cockpit: history scrolls here, a program that wants the wheel gets it.

Runs cockpit.mjs under node with the real @xterm/headless of the image (skipped where it is not installed). Run: python3 tests/fast/test_cockpit_wheel.py
"""
import glob
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "support"))
from helpers import ROOT  # noqa: E402

WEB = os.path.join(ROOT, "container", "web", "herdr")
MODULES = [p for p in ("/usr/local/share/swarmbox/herdr-web/node_modules", os.path.join(WEB, "node_modules")) if os.path.isdir(os.path.join(p, "@xterm", "headless"))]

HARNESS = r"""
import { Cockpit } from './cockpit.mjs';
import xt from '@xterm/headless';
const out = {};
async function scenario(name, feed) {
  const writes = [];
  const c = new Cockpit({ stdin: { on() {}, setRawMode() {}, resume() {} }, stdout: { write() {}, columns: 120, rows: 40, on() {} }, hc: { on() {}, listSnapshot() { return []; } } });
  c.scheduleRender = () => {};
  const t = new xt.Terminal({ cols: 80, rows: 20, scrollback: 2000, allowProposedApi: true });
  await new Promise((r) => t.write(feed, r));
  c.xterm = t; c.stream = { write: (b) => writes.push(Buffer.from(b).toString('latin1')) };
  const P = c.layout().pane;
  const x = P.x + P.pad + 9, y = P.y + 4;   // 0-indexed cell inside the pane: inner (9, 4)
  c._onStdin(Buffer.from(`\x1b[<64;${x + 1};${y + 1}M`));   // wheel up
  c._onStdin(Buffer.from(`\x1b[<65;${x + 1};${y + 1}M`));   // wheel down
  c._onStdin(Buffer.from(`\x1b[<64;1;1M`));                 // wheel up on the sidebar corner, outside the pane
  out[name] = { offset: c.scrollOffset, writes };
}
const lines = Array.from({ length: 100 }, (_, i) => 'line ' + i).join('\r\n');
await scenario('history', lines);
await scenario('alt', '\x1b[?1049h' + lines);
await scenario('altApp', '\x1b[?1049h\x1b[?1h' + lines);
await scenario('mouse', '\x1b[?1049h\x1b[?1000h\x1b[?1006h' + lines);
await scenario('mouseOld', '\x1b[?1000h' + lines);
console.log(JSON.stringify(out));
"""


@unittest.skipUnless(shutil.which("node") and MODULES, "node or @xterm/headless is not installed")
class CockpitWheelTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="cockpit-wheel-")
        for f in glob.glob(os.path.join(WEB, "*.mjs")):
            shutil.copy(f, cls.tmp)
        os.symlink(MODULES[0], os.path.join(cls.tmp, "node_modules"))
        with open(os.path.join(cls.tmp, "harness.mjs"), "w", encoding="utf-8") as f:
            f.write(HARNESS)
        env = dict(os.environ, HOME=cls.tmp)
        r = subprocess.run(["node", "harness.mjs"], cwd=cls.tmp, env=env, capture_output=True, text=True, timeout=60)
        if r.returncode != 0:
            raise RuntimeError(r.stderr)
        cls.out = json.loads(r.stdout.strip().splitlines()[-1])

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, True)

    def test_a_shell_with_history_scrolls_the_history_and_forwards_nothing(self):
        o = self.out["history"]
        self.assertEqual(o["writes"], [])
        self.assertEqual(o["offset"], 3)      # up 3, down 3, up 3 on the sidebar corner

    def test_a_program_on_the_alternate_screen_gets_arrow_keys(self):
        o = self.out["alt"]
        self.assertEqual(o["offset"], 0)
        self.assertEqual(o["writes"], ["\x1b[A" * 3, "\x1b[B" * 3])

    def test_arrow_keys_follow_the_application_cursor_mode(self):
        self.assertEqual(self.out["altApp"]["writes"], ["\x1bOA" * 3, "\x1bOB" * 3])

    def test_a_program_that_asked_for_the_mouse_gets_sgr_wheel_events_in_its_own_cells(self):
        o = self.out["mouse"]
        self.assertEqual(o["offset"], 0)
        self.assertEqual(o["writes"], ["\x1b[<64;10;5M", "\x1b[<65;10;5M"])   # cell (9, 4) of the pane, 1-indexed; the corner is dropped

    def test_a_program_without_sgr_gets_the_classic_encoding(self):
        o = self.out["mouseOld"]
        self.assertEqual(o["writes"], ["\x1b[M" + chr(32 + 64) + chr(33 + 9) + chr(33 + 4), "\x1b[M" + chr(32 + 65) + chr(33 + 9) + chr(33 + 4)])


if __name__ == "__main__":
    unittest.main()
