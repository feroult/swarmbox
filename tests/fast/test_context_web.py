"""Fast tests of the repository context in the Web Studio gateway (sysop.autocontext): what the snapshot says of each repository and each
session, the text a session started with (/api/sysop/context), and Rewrite (/api/sysop/context/rewrite).

The real Node `createGateway()` on 127.0.0.1:0 with an in-memory fake HerdrClient, a fake swarmbox-sysop, and the digests folder in a mktemp
HOME (no hc daemon, no sysop, nothing of the live box).

Run: python3 tests/fast/test_context_web.py
"""
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

NODE_HARNESS = r"""
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { EventEmitter } from 'node:events';
import { createGateway } from './server.mjs';
import { readContextState, readSysopSnapshot, startNewConversation } from './hc-client.mjs';

class FakeHc extends EventEmitter {
  constructor(terminals) { super(); this.proc = {}; this.terminals = terminals; }
  listSnapshot() { return this.terminals; }
  async call(method) { return method === 'terminal.list' ? { terminals: this.terminals } : { ok: true }; }
  close() {}
}

const live = [{ address: 't1', name: 'calc', state: 'live', labels: { 'swarmbox.agent': 'claude' } },
              { address: 't2', name: 'shell', state: 'live', labels: {} }];
const state = path.join(process.env.XDG_STATE_HOME, 'swarmbox', 'sysop');
const dir = path.join(state, 'digests');
const nowSec = Date.now() / 1000;
const KEY = '0123456789abcdef';
const KEY2 = 'fedcba9876543210';
const top = process.env.TEST_REPO;
fs.mkdirSync(path.join(dir, 'repos'), { recursive: true });
fs.mkdirSync(path.join(dir, 'sessions'), { recursive: true });
fs.writeFileSync(path.join(dir, 'repos', `${KEY}.json`), JSON.stringify({ base: 'a'.repeat(40), at: nowSec - 60, repo: 'calc', top }));
fs.writeFileSync(path.join(dir, 'repos', `${KEY}.md`), '## Purpose\nA calculator.\n');
fs.writeFileSync(path.join(dir, 'sessions', 't1.json'), JSON.stringify({ tab: 't1', agent: 'claude', cwd: top, repo: 'calc', key: KEY,
  commit: 'b'.repeat(12), context: true, base: 'a'.repeat(12), base_at: nowSec - 60, changes: 3, at: nowSec - 5 }));
fs.writeFileSync(path.join(dir, 'sessions', 't1.md'), '# Repository orientation: calc\nexactly this\n');
fs.writeFileSync(path.join(dir, 'sessions', 't9.json'), JSON.stringify({ tab: 't9', context: true }));   // a closed tab
fs.writeFileSync(path.join(dir, 'sessions', 't2.json'), JSON.stringify({ tab: 't2', repo: 'shop', key: KEY2, waiting: true, at: nowSec - 2 }));
fs.writeFileSync(path.join(state, 'system_events.jsonl'), [
  { kind: 'autocontext', phase: 'started', key: KEY2, repo: 'shop', commit: 'c'.repeat(12), ts: nowSec - 3, reason: 'new', tab: 't2' },
  { kind: 'autocontext', phase: 'session', key: KEY, repo: 'calc', commit: 'b'.repeat(12), ts: nowSec - 5, tab: 't1', context: true },
].map((e) => JSON.stringify(e)).join('\n') + '\n');

// what the snapshot says: the repositories (one being written for the first time), the sessions of the live tabs only
const ctx = readContextState(state, live, { settings: { autocontext: true } });
assert.equal(ctx.on, true);
const byKey = Object.fromEntries(ctx.repos.map((r) => [r.key, r]));
assert.deepEqual([byKey[KEY].repo, byKey[KEY].state, byKey[KEY].base, byKey[KEY].top], ['calc', 'ready', 'a'.repeat(12), top]);
assert.deepEqual([byKey[KEY2].repo, byKey[KEY2].state, byKey[KEY2].call.reason], ['shop', 'writing', 'new']);
assert.deepEqual(Object.keys(ctx.sessions).sort(), ['t1', 't2'], 'a closed tab has no session in the snapshot');
assert.deepEqual([ctx.sessions.t2.waiting, ctx.sessions.t2.context], [true, false], 'a launcher that waits for the first context');
assert.deepEqual([ctx.sessions.t1.context, ctx.sessions.t1.changes, ctx.sessions.t1.base], [true, 3, 'a'.repeat(12)]);
assert.equal(readContextState(state, live, { settings: { autocontext: false } }).on, false);

// a call that started long ago and never ended is stuck; a failure older than the digest is over
fs.appendFileSync(path.join(state, 'system_events.jsonl'), JSON.stringify(
  { kind: 'autocontext', phase: 'failed', key: KEY, repo: 'calc', commit: 'a'.repeat(12), ts: nowSec - 120, error: 'x' }) + '\n'
  + JSON.stringify({ kind: 'autocontext', phase: 'started', key: KEY2, repo: 'shop', commit: 'c'.repeat(12), ts: nowSec - 600 }) + '\n');
const ctx2 = readContextState(state, live, { settings: { autocontext: true } });
assert.equal(ctx2.repos.find((r) => r.key === KEY).state, 'ready');
assert.equal(ctx2.repos.find((r) => r.key === KEY2).state, 'stuck');

// the session event reaches the feed with what it started with
fs.mkdirSync(path.join(process.env.SB_RUN_DIR, 'sysop'), { recursive: true });
fs.writeFileSync(path.join(process.env.SB_RUN_DIR, 'sysop', 'status.json'), JSON.stringify({ pid: process.pid, settings: { autocontext: true } }));
const snap = readSysopSnapshot(live);
const sev = snap.system_events.find((e) => e.phase === 'session');
assert.deepEqual([sev.tab, sev.context], ['t1', true]);
assert.equal(snap.context.sessions.t1.repo, 'calc');
// the Events tab: what the sysop did by itself (no session records), not cut by New conversation
assert.ok(snap.events.length > 0 && snap.events.every((e) => e.phase !== 'session'));
startNewConversation(nowSec + 1);
assert.equal(readSysopSnapshot(live).events.length, snap.events.length);
assert.equal(readSysopSnapshot(live).system_events.length, 0);

const gw = createGateway({ hc: new FakeHc(live) });
await new Promise((r) => gw.server.listen(0, '127.0.0.1', r));
const base = `http://127.0.0.1:${gw.server.address().port}`;
async function api(method, p, body, origin = base) {
  const r = await fetch(`${base}${p}`, { method, headers: { 'Content-Type': 'application/json', Origin: origin },
    body: body !== undefined ? JSON.stringify(body) : undefined });
  return { status: r.status, data: await r.json().catch(() => ({})) };
}
try {
  // the exact text of a session, the current digest of a repository; nothing for a bad name or an unknown one
  const s1 = await api('GET', '/api/sysop/context?tab=t1');
  assert.equal(s1.status, 200);
  assert.deepEqual([s1.data.kind, s1.data.text, s1.data.meta.changes], ['session', '# Repository orientation: calc\nexactly this\n', 3]);
  const r1 = await api('GET', `/api/sysop/context?key=${KEY}`);
  assert.deepEqual([r1.status, r1.data.kind, r1.data.text], [200, 'repo', '## Purpose\nA calculator.\n']);
  for (const q of ['tab=..%2Fsecret', 'tab=t5', 'key=nothex', `key=${KEY2}`, '']) {
    assert.equal((await api('GET', `/api/sysop/context?${q}`)).status, 404, q);
  }

  // Rewrite: the sysop's context --force on the folder the sysop recorded, with the tab that asked in the environment
  const rw = await api('POST', '/api/sysop/context/rewrite', { key: KEY, tab: 't1' });
  assert.equal(rw.status, 202);
  const log = process.env.FAKE_SYSOP_LOG;
  for (let i = 0; i < 100 && !fs.existsSync(log); i++) await new Promise((r) => setTimeout(r, 20));
  assert.deepEqual(fs.readFileSync(log, 'utf8').trim().split('\n'), ['context', '--force', top, 'tab=t1']);
  fs.unlinkSync(log);
  const bad = await api('POST', '/api/sysop/context/rewrite', { key: KEY, tab: 't1; rm -rf ~' });
  assert.equal(bad.status, 202);
  for (let i = 0; i < 100 && !fs.existsSync(log); i++) await new Promise((r) => setTimeout(r, 20));
  assert.equal(fs.readFileSync(log, 'utf8').trim().split('\n').pop(), 'tab=', 'a tab that is not a name is dropped');
  assert.equal((await api('POST', '/api/sysop/context/rewrite', { key: KEY2 })).status, 404, 'no folder recorded for it');
  // a repository whose first call failed has no index: Retry now takes the folder its event names
  fs.appendFileSync(path.join(state, 'system_events.jsonl'), JSON.stringify(
    { kind: 'autocontext', phase: 'failed', key: KEY2, repo: 'shop', commit: 'c'.repeat(12), ts: nowSec, top, error: 'x' }) + '\n');
  fs.rmSync(log, { force: true });
  assert.equal((await api('POST', '/api/sysop/context/rewrite', { key: KEY2 })).status, 202);
  for (let i = 0; i < 100 && !fs.existsSync(log); i++) await new Promise((r) => setTimeout(r, 20));
  assert.equal(fs.readFileSync(log, 'utf8').split('\n')[2], top);
  assert.equal((await api('POST', '/api/sysop/context/rewrite', { key: KEY }, 'http://evil.example')).status, 403);
  console.log('CONTEXT_WEB_OK');
} finally {
  gw.server.close();
  gw.close?.();
  process.exit(process.exitCode || 0);
}
"""

FAKE_SYSOP = """#!/bin/sh
{ for a in "$@"; do printf '%s\\n' "$a"; done; printf 'tab=%s\\n' "${SWARMBOX_SYSOP_CONTEXT_TAB:-}"; } > "$FAKE_SYSOP_LOG.tmp"
mv "$FAKE_SYSOP_LOG.tmp" "$FAKE_SYSOP_LOG"
"""


class ContextWebTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="swarmbox-test-ctxweb.")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.home = os.path.join(self.tmp, "home")
        self.repo = os.path.join(self.home, "calc")
        os.makedirs(self.repo)

    def stage(self):
        """server.mjs and its modules in the scratch folder, with a zero-dependency `ws` stub (offline CI has no npm packages)."""
        web = os.path.join(self.tmp, "web")
        ws = os.path.join(web, "node_modules", "ws")
        os.makedirs(ws)
        for f in ("server.mjs", "hc-client.mjs", "file-preview.mjs", "agents.mjs"):
            shutil.copyfile(os.path.join(WEB, f), os.path.join(web, f))
        with open(os.path.join(ws, "package.json"), "w") as f:
            json.dump({"name": "ws", "type": "module", "main": "index.js"}, f)
        with open(os.path.join(ws, "index.js"), "w") as f:
            f.write("import { EventEmitter } from 'node:events';\n"
                    "export class WebSocketServer extends EventEmitter {\n"
                    "  constructor() { super(); this.clients = new Set(); }\n"
                    "  handleUpgrade() {}\n  close() {}\n}\n")
        with open(os.path.join(web, "run.mjs"), "w") as f:
            f.write(NODE_HARNESS)
        sysop = os.path.join(self.tmp, "fake-sysop")
        with open(sysop, "w") as f:
            f.write(FAKE_SYSOP)
        os.chmod(sysop, 0o755)
        return web, sysop

    def test_the_snapshot_the_session_text_and_rewrite(self):
        web, sysop = self.stage()
        env = {
            "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
            "SWARMBOX_IMAGE_ADDONS_DIR": os.path.join(ROOT, "container", "addons"),
            "HOME": self.home,
            "XDG_CONFIG_HOME": os.path.join(self.home, ".config"),
            "XDG_DATA_HOME": os.path.join(self.home, ".local", "share"),
            "XDG_STATE_HOME": os.path.join(self.home, ".local", "state"),
            "SB_RUN_DIR": os.path.join(self.tmp, "run"),
            "SWARMBOX_TEST_SYSOP_BIN": sysop,
            "FAKE_SYSOP_LOG": os.path.join(self.tmp, "sysop.log"),
            "TEST_REPO": self.repo,
        }
        p = subprocess.run(["node", "run.mjs"], cwd=web, env=env, capture_output=True, text=True, timeout=30)
        self.assertEqual(p.returncode, 0, "stdout:\n%s\nstderr:\n%s" % (p.stdout, p.stderr))
        self.assertIn("CONTEXT_WEB_OK", p.stdout)


if __name__ == "__main__":
    unittest.main()
