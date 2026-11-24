"""Fast end-to-end gateway tests for Pinned Sessions, Rename, Live Auto-Follow, and Git Worktrees.

Spins up the real Node `createGateway()` on 127.0.0.1:0 with an in-memory fake HerdrClient and a
real temporary Git repository in mktemp (zero real hc daemon, zero touches to live workspace).

Run: python3 tests/fast/test_pins_web.py
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

SERVER_MJS = os.path.join(ROOT, "container", "web", "herdr", "server.mjs")
CLIENT_MJS = os.path.join(ROOT, "container", "web", "herdr", "hc-client.mjs")


def git(cwd, *args):
    subprocess.run(
        ["git", *args],
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=True,
        env={
            **os.environ,
            "GIT_AUTHOR_NAME": "Test",
            "GIT_AUTHOR_EMAIL": "test@example.com",
            "GIT_COMMITTER_NAME": "Test",
            "GIT_COMMITTER_EMAIL": "test@example.com",
        },
    )


NODE_HARNESS = r"""
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { EventEmitter } from 'node:events';
import { execFileSync } from 'node:child_process';
import { createGateway } from SERVER_PATH;
import { syncPinsFromTerminals, readPins, readSysopSnapshot, startNewConversation } from CLIENT_PATH;

class FakeHc extends EventEmitter {
  constructor() {
    super();
    this.proc = {};
    this.terminals = new Map();
    this.seq = 0;
    this.sent = [];
  }
  listSnapshot() {
    return Array.from(this.terminals.values()).filter((t) => t.state === 'live');
  }
  async call(method, params = {}) {
    if (method === 'terminal.list') return { terminals: this.listSnapshot() };
    if (method === 'terminal.run') {
      this.seq += 1;
      const addr = `t${this.seq}`;
      const t = {
        address: addr,
        name: params.name || addr,
        cwd: params.cwd || process.env.HOME,
        argv: params.argv || [],
        state: 'live',
        created_ms: this.seq * 1000,
        labels: { ...(params.labels || {}) },
        foreground: { name: (params.labels && params.labels['swarmbox.agent']) || 'bash', cwd: params.cwd || process.env.HOME },
      };
      this.terminals.set(addr, t);
      return { terminal: t };
    }
    if (method === 'terminal.label') {
      const t = this.terminals.get(params.terminal);
      if (!t) throw new Error('not found');
      t.labels = { ...(t.labels || {}) };
      for (const [k, v] of Object.entries(params.labels || {})) {
        if (v === '') delete t.labels[k];
        else t.labels[k] = v;
      }
      return t;
    }
    if (method === 'terminal.kill' || method === 'terminal.rm') {
      this.terminals.delete(params.terminal);
      return { ok: true };
    }
    if (method === 'terminal.send') {
      this.sent.push(params);
      return { ok: true };
    }
    return { ok: true };
  }
  close() {}
}

const repo = process.env.TEST_REPO;
const proj2 = process.env.TEST_PROJ2;
const hc = new FakeHc();
const gw = createGateway({ hc });

await new Promise((resolve) => gw.server.listen(0, '127.0.0.1', resolve));
const { port } = gw.server.address();
const base = `http://127.0.0.1:${port}`;

async function api(method, p, body) {
  const r = await fetch(`${base}${p}`, {
    method,
    headers: { 'Content-Type': 'application/json', Origin: base },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  const data = await r.json().catch(() => ({}));
  return { status: r.status, data };
}

try {
  // 1. Create an agent tab in repo
  const r1 = await api('POST', '/api/tabs', { preset: 'agent', agent: 'claude', cwd: repo });
  assert.equal(r1.status, 201);
  const t1 = r1.data.terminal.address;

  // 2. Pin t1, rename it, and verify live auto-follow (cwd moves, agent never downgrades to shell)
  const pinRes = await api('POST', '/api/pins', { terminal: t1 });
  assert.equal(pinRes.status, 201);
  const pinId = pinRes.data.pin.id;
  assert.equal(pinRes.data.pin.agent, 'claude');
  assert.equal(pinRes.data.pin.title, 'shop-api');
  assert.equal(pinRes.data.pin.autostart, false);

  const ren = await api('PATCH', `/api/tabs/${t1}`, { title: 'Shop Core' });
  assert.equal(ren.status, 200);
  assert.equal(readPins()[0].title, 'Shop Core');
  assert.equal(readPins()[0].title_source, 'user');

  // Simulate user cd'ing to proj2 and temporarily exiting claude to bash
  const liveT1 = hc.terminals.get(t1);
  liveT1.foreground = { name: 'bash', cwd: proj2 };
  liveT1.agent = 'bash';
  assert.equal(syncPinsFromTerminals(hc.listSnapshot()), true);
  assert.equal(readPins()[0].cwd, proj2);
  assert.equal(readPins()[0].agent, 'claude', 'agent pin must not downgrade to shell');

  // Move back to repo for collision tests
  liveT1.foreground = { name: 'claude', cwd: repo };
  syncPinsFromTerminals(hc.listSnapshot());

  // 3. Opening a second agent in repo triggers 409 worktree_collision in default `ask` mode
  const col = await api('POST', '/api/tabs', { preset: 'agent', agent: 'agy', cwd: repo });
  assert.equal(col.status, 409);
  assert.equal(col.data.error, 'worktree_collision');
  assert.equal(col.data.collision.repo_name, 'shop-api');

  // Choosing `new` creates a real isolated Git worktree
  const wtTab = await api('POST', '/api/tabs', { preset: 'agent', agent: 'agy', cwd: repo, worktree_choice: 'new' });
  assert.equal(wtTab.status, 201);
  assert.ok(wtTab.data.worktree && wtTab.data.worktree.path);
  const t2 = wtTab.data.terminal.address;
  const wtPath = wtTab.data.worktree.path;
  assert.ok(fs.existsSync(wtPath));

  // Closing an empty unpinned worktree auto-removes the worktree!
  const delEmpty = await api('DELETE', `/api/tabs/${t2}`);
  assert.equal(delEmpty.status, 200);
  assert.equal(delEmpty.data.auto_cleaned_worktree, true);
  assert.equal(fs.existsSync(wtPath), false);

  // 4. Create another worktree, commit inside it, merge cleanly with clean=true
  const wtTab2 = await api('POST', '/api/tabs', { preset: 'agent', agent: 'claude', cwd: repo, worktree_choice: 'new' });
  assert.equal(wtTab2.status, 201);
  const t3 = wtTab2.data.terminal.address;
  const wtPath2 = wtTab2.data.worktree.path;
  fs.writeFileSync(path.join(wtPath2, 'cache.py'), 'TTL = 60\n');
  const gitEnv = { ...process.env, GIT_AUTHOR_NAME: 'T', GIT_AUTHOR_EMAIL: 't@e', GIT_COMMITTER_NAME: 'T', GIT_COMMITTER_EMAIL: 't@e' };
  execFileSync('git', ['add', 'cache.py'], { cwd: wtPath2, env: gitEnv });
  execFileSync('git', ['commit', '-m', 'add cache'], { cwd: wtPath2, env: gitEnv });

  const wtSt = await api('GET', `/api/tabs/${t3}/worktree`);
  assert.equal(wtSt.status, 200);
  assert.equal(wtSt.data.ahead, 1);
  assert.equal(wtSt.data.can_merge, true);

  const mrg = await api('POST', '/api/worktrees/merge', { terminal: t3, clean: true });
  assert.equal(mrg.status, 200);
  assert.equal(mrg.data.cleaned, true);
  assert.ok(fs.existsSync(path.join(repo, 'cache.py')));
  assert.equal(fs.existsSync(wtPath2), false);

  // 5. Close pinned tab t1 -> stays PARKED; wake it -> launches with --continue
  const delPinTab = await api('DELETE', `/api/tabs/${t1}`);
  assert.equal(delPinTab.status, 200);
  assert.equal(delPinTab.data.pinned, true);
  const pinsAfterClose = await api('GET', '/api/pins');
  assert.equal(pinsAfterClose.data.pins[0].parked, true);

  const woken = await api('POST', `/api/pins/${pinId}/wake`, {});
  assert.equal(woken.status, 201);
  assert.ok(woken.data.terminal.argv.join(' ').includes('claude --continue'));

  // 6. Prefs update (auto/off/ask)
  const pr = await api('PATCH', '/api/worktrees/prefs', { mode: 'off', copy_env: false });
  assert.equal(pr.status, 200);
  assert.equal(pr.data.prefs.mode, 'off');
  assert.equal(pr.data.prefs.copy_env, false);

  // 7. System events (autoname) surfaced in Sysop snapshot & filtered by New conversation
  const runSysop = path.join(process.env.SB_RUN_DIR, 'sysop');
  const stateSysop = path.join(process.env.XDG_STATE_HOME, 'swarmbox', 'sysop');
  fs.mkdirSync(runSysop, { recursive: true });
  fs.mkdirSync(stateSysop, { recursive: true });
  fs.writeFileSync(path.join(runSysop, 'status.json'), JSON.stringify({ pid: process.pid, bus: 'connected' }));
  const nowSec = Date.now() / 1000;
  fs.writeFileSync(
    path.join(stateSysop, 'system_events.jsonl'),
    JSON.stringify({ id: 'ev1', kind: 'autoname', ts: nowSec - 5, tab: 't1', old_title: 'shop-api', new_title: 'Fix Cache' }) + '\n',
  );
  const snap1 = readSysopSnapshot([]);
  assert.equal(snap1.system_events.length, 1);
  assert.equal(snap1.system_events[0].new_title, 'Fix Cache');
  startNewConversation(nowSec);
  const snap2 = readSysopSnapshot([]);
  assert.equal(snap2.system_events.length, 0);

  // 8. Unpin removes pin
  const unpin = await api('DELETE', `/api/pins/${pinId}`);
  assert.equal(unpin.status, 200);
  assert.equal(readPins().length, 0);

  console.log('ALL_PINS_WEB_OK');
} finally {
  gw.shutdown();
}
"""


class PinsWebGatewayTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="swarmbox-test-pinsweb.")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.home = os.path.join(self.tmp, "home")
        self.repo = os.path.join(self.home, "shop-api")
        self.proj2 = os.path.join(self.home, "other-proj")
        os.makedirs(self.repo, exist_ok=True)
        os.makedirs(self.proj2, exist_ok=True)
        git(self.repo, "init", "-b", "main")
        git(self.repo, "config", "user.name", "Test")
        git(self.repo, "config", "user.email", "test@example.com")
        with open(os.path.join(self.repo, "README.md"), "w", encoding="utf-8") as f:
            f.write("# shop-api\n")
        git(self.repo, "add", "README.md")
        git(self.repo, "commit", "-m", "init")

    def test_pins_rename_worktree_collision_merge_and_sysop_events(self):
        # Stage server.mjs and hc-client.mjs in tmp with a minimal zero-dep `ws` stub so this
        # test runs identically offline on bare CI runners where npm packages are not installed.
        web_dir = os.path.join(self.tmp, "web")
        ws_dir = os.path.join(web_dir, "node_modules", "ws")
        os.makedirs(ws_dir, exist_ok=True)
        shutil.copyfile(SERVER_MJS, os.path.join(web_dir, "server.mjs"))
        shutil.copyfile(CLIENT_MJS, os.path.join(web_dir, "hc-client.mjs"))
        with open(os.path.join(ws_dir, "package.json"), "w", encoding="utf-8") as f:
            json.dump({"name": "ws", "type": "module", "main": "index.js"}, f)
        with open(os.path.join(ws_dir, "index.js"), "w", encoding="utf-8") as f:
            f.write("import { EventEmitter } from 'node:events';\n"
                    "export class WebSocketServer extends EventEmitter {\n"
                    "  constructor() { super(); this.clients = new Set(); }\n"
                    "  handleUpgrade(_req, _sock, _head, cb) { cb({ readyState: 1, send() {}, close() {}, on() {}, ping() {} }); }\n"
                    "  close() {}\n"
                    "}\n")
        staged_server = os.path.join(web_dir, "server.mjs")
        staged_client = os.path.join(web_dir, "hc-client.mjs")
        script = NODE_HARNESS.replace("SERVER_PATH", json.dumps(staged_server)).replace("CLIENT_PATH", json.dumps(staged_client))
        test_mjs = os.path.join(web_dir, "run.mjs")
        with open(test_mjs, "w", encoding="utf-8") as f:
            f.write(script)
        wt_bin = os.path.join(ROOT, "container", "scripts", "swarmbox-worktree.py")
        env = {
            "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
            "HOME": self.home,
            "XDG_CONFIG_HOME": os.path.join(self.home, ".config"),
            "XDG_DATA_HOME": os.path.join(self.home, ".local", "share"),
            "XDG_STATE_HOME": os.path.join(self.home, ".local", "state"),
            "SB_RUN_DIR": os.path.join(self.tmp, "run"),
            "SWARMBOX_TEST_WORKTREE_BIN": wt_bin,
            "TEST_REPO": self.repo,
            "TEST_PROJ2": self.proj2,
        }
        p = subprocess.run(["node", test_mjs], env=env, capture_output=True, text=True, timeout=30)
        self.assertEqual(p.returncode, 0, "stdout:\n%s\nstderr:\n%s" % (p.stdout, p.stderr))
        self.assertIn("ALL_PINS_WEB_OK", p.stdout)


if __name__ == "__main__":
    unittest.main()
