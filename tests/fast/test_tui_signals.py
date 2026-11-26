"""Fast tests of how the Web Studio gateway tells a full-screen program (a TUI) from a plain terminal: by the terminal's own signals,
never by a name (docs/agents-design.md, step 4). createTermModeTracker reads the modes a program sets in its PTY stream, isTuiTerminal
adds the OSC 7501 status an agent reports, and tuiTimings takes the agent's TERM_* keys over the core's TUI profile.
Run with: python3 -W error tests/fast/test_tui_signals.py
"""
import json
import os
import shutil
import subprocess
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HERDR = os.path.join(ROOT, "container", "web", "herdr")

HARNESS = r"""
import { registerHooks } from 'node:module';
if (typeof registerHooks === 'function') {
  registerHooks({ resolve(specifier, context, next) {
    if (specifier === 'ws') return { shortCircuit: true, url: 'data:text/javascript,export class WebSocketServer { constructor(){ this.clients = new Set(); } on(){} handleUpgrade(){} }' };
    return next(specifier, context);
  } });
}
const { createTermModeTracker, isTuiTerminal, tuiTimings } = await import('./server.mjs');
const run = (chunks) => { const t = createTermModeTracker(); for (const c of chunks) t.push(Buffer.from(c, 'latin1')); return t.state(); };
const out = {
  plain: run(['$ ls\r\nfile\r\n', '\x1b[1;32mgreen\x1b[0m\r\n']),
  altOn: run(['\x1b[?1049h\x1b[H\x1b[2Jvim']),
  altOff: run(['\x1b[?1049h', 'text', '\x1b[?1049l']),
  alt47: run(['\x1b[?47h']),
  split: run(['abc\x1b[?10', '49h']),
  splitEsc: run(['abc\x1b', '[?1049h']),
  mouse: run(['\x1b[?1000;1006h']),
  mouseOff: run(['\x1b[?1002h', '\x1b[?1002l']),
  encodingOnly: run(['\x1b[?1006h']),
  reset: run(['\x1b[?1049h\x1b[?1000h', '\x1bc']),
  other: run(['\x1b[?25l\x1b[?2026h\x1b[?2026l\x1b[?2004h']),
};
out.tui = {
  bareShellWithAgentLabel: isTuiTerminal({ name: 'claude', foreground: { name: 'bash' }, labels: { 'swarmbox.agent': 'claude' } }, { alt: false, mouse: false }),
  busyCommand: isTuiTerminal({ foreground: { name: 'npm' } }, { alt: false, mouse: false }),
  agentStatus: isTuiTerminal({ foreground: { name: '2.1.332' }, status: { app: 'claude-code', state: 'idle' } }, null),
  emptyStatus: isTuiTerminal({ status: { app: '' } }, null),
  altScreen: isTuiTerminal({ foreground: { name: 'vim' } }, { alt: true, mouse: false }),
  mouseMode: isTuiTerminal({ foreground: { name: 'htop' } }, { alt: false, mouse: true }),
};
out.timings = {
  claude: tuiTimings({ status: { app: 'claude-code' } }).resize_quiet_ms,
  none: tuiTimings({ foreground: { name: 'vim' } }).resize_quiet_ms,
};
console.log(JSON.stringify(out));
"""


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class TuiSignals(unittest.TestCase):
    def test_modes_status_and_profiles(self):
        env = dict(os.environ, HOME="/nonexistent-home", SWARMBOX_HC_AUTOSTART="0", SWARMBOX_TEST_USER_ADDONS="/nonexistent")
        env.pop("SWARMBOX_IMAGE_ADDONS_DIR", None)
        p = subprocess.run(["node", "--input-type=module", "-e", HARNESS], cwd=HERDR, env=env, capture_output=True, text=True, timeout=60)
        self.assertEqual(p.returncode, 0, p.stderr)
        o = json.loads(p.stdout.strip().splitlines()[-1])
        off = {"alt": False, "mouse": False}
        self.assertEqual(o["plain"], off)
        self.assertEqual(o["altOn"], {"alt": True, "mouse": False})
        self.assertEqual(o["altOff"], off)
        self.assertEqual(o["alt47"], {"alt": True, "mouse": False})
        self.assertEqual(o["split"], {"alt": True, "mouse": False}, "a sequence cut between two chunks")
        self.assertEqual(o["splitEsc"], {"alt": True, "mouse": False}, "a chunk that ends in a lone ESC")
        self.assertEqual(o["mouse"], {"alt": False, "mouse": True})
        self.assertEqual(o["mouseOff"], off)
        self.assertEqual(o["encodingOnly"], off, "1006 picks an encoding, it turns no reporting on")
        self.assertEqual(o["reset"], off, "a full reset (ESC c) clears the modes")
        self.assertEqual(o["other"], off, "cursor, DEC 2026 and bracketed paste are not TUI modes")
        t = o["tui"]
        # bug 9: an agent label or an agent-like name on a bare shell, or a busy command, is no TUI
        self.assertFalse(t["bareShellWithAgentLabel"])
        self.assertFalse(t["busyCommand"])
        self.assertFalse(t["emptyStatus"])
        self.assertTrue(t["agentStatus"])
        self.assertTrue(t["altScreen"])
        self.assertTrue(t["mouseMode"])
        self.assertEqual(o["timings"], {"claude": 900, "none": 900})


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class AgentTimings(unittest.TestCase):
    def test_an_agent_term_key_overrides_the_core_profile(self):
        import tempfile
        tmp = tempfile.mkdtemp(prefix="sbtui-")
        self.addCleanup(shutil.rmtree, tmp, True)
        d = os.path.join(tmp, "slowbot")
        os.makedirs(os.path.join(d, "agent"))
        with open(os.path.join(d, "addon.conf"), "w") as f:
            f.write('SCHEMA=1\nNAME=slowbot\nDESCRIPTION="x"\nVERSION=1\nCOMMANDS="slowbot"\n')
        with open(os.path.join(d, "agent", "agent.conf"), "w") as f:
            f.write("ID=slowbot\nTERM_RESIZE_QUIET_MS=1500\nTERM_HYDRATE_CAP_MS=2000\n")
        js = ("const { tuiTimings } = await import('./server.mjs');"
              "const t = tuiTimings({ foreground: { name: 'slowbot' } });"
              "console.log(JSON.stringify([t.resize_quiet_ms, t.hydrate_cap_ms, t.resize_cap_ms]));")
        env = dict(os.environ, HOME=tmp, SWARMBOX_HC_AUTOSTART="0", SWARMBOX_TEST_USER_ADDONS=tmp)
        p = subprocess.run(["node", "--input-type=module", "-e", HARNESS.split("const { createTermModeTracker")[0] + js], cwd=HERDR, env=env,
                           capture_output=True, text=True, timeout=60)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(json.loads(p.stdout.strip().splitlines()[-1]), [1500, 2000, 3500])


if __name__ == "__main__":
    unittest.main()
