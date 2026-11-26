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
PREVIEW_MJS = os.path.join(ROOT, "container", "web", "herdr", "file-preview.mjs")


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
import http from 'node:http';
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
      const had = this.terminals.delete(params.terminal);
      // Like the real daemon, a kill is followed by events that the gateway broadcasts while the close is still running.
      if (had && method === 'terminal.kill') this.emit('hc-event', { event: { type: 'removed', terminal: params.terminal } });
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
  // 0. Pre-flight /api/worktrees/check: non-Git folder vs clean Git repo (no collision)
  const chkNonGit = await api('GET', `/api/worktrees/check?cwd=${encodeURIComponent(proj2)}`);
  assert.equal(chkNonGit.status, 200);
  assert.equal(chkNonGit.data.is_git, false);
  assert.equal(chkNonGit.data.collision, null);
  assert.equal(chkNonGit.data.prefs.mode, 'ask');

  const chkClean = await api('GET', `/api/worktrees/check?cwd=${encodeURIComponent(repo)}`);
  assert.equal(chkClean.status, 200);
  assert.equal(chkClean.data.is_git, true);
  assert.equal(chkClean.data.repo_name, 'shop-api');
  assert.equal(chkClean.data.branch, 'main');
  assert.equal(chkClean.data.collision, null);

  // 0b. Proactive worktree creation even when there is NO collision (unified New Agent popover)
  const proactiveWt = await api('POST', '/api/tabs', { preset: 'agent', agent: 'claude', cwd: repo, worktree_choice: 'new', persist: false });
  assert.equal(proactiveWt.status, 201);
  assert.ok(proactiveWt.data.worktree && proactiveWt.data.worktree.path);
  const tProactive = proactiveWt.data.terminal.address;
  const delProactive = await api('DELETE', `/api/tabs/${tProactive}`);
  assert.equal(delProactive.status, 200);
  assert.equal(delProactive.data.auto_cleaned_worktree, true);

  // 1. Create an agent tab in repo -> Option 1 auto-persists it with autostart=true by default
  const r1 = await api('POST', '/api/tabs', { preset: 'agent', agent: 'claude', cwd: repo });
  assert.equal(r1.status, 201);
  const t1 = r1.data.terminal.address;
  assert.ok(r1.data.pin && r1.data.pin.id, 'agent tab should auto-persist');
  assert.equal(r1.data.pin.auto, true);
  assert.equal(r1.data.pin.agent, 'claude');
  assert.equal(r1.data.pin.title, 'shop-api');
  assert.equal(r1.data.pin.autostart, true);

  // 1b. Global session prefs: toggle boot_mode -> parked syncs existing pins, then back to autostart
  const spGet = await api('GET', '/api/pins/prefs');
  assert.equal(spGet.status, 200);
  assert.equal(spGet.data.prefs.boot_mode, 'autostart');
  const spParked = await api('PATCH', '/api/pins/prefs', { boot_mode: 'parked' });
  assert.equal(spParked.status, 200);
  assert.equal(spParked.data.prefs.boot_mode, 'parked');
  assert.equal(readPins()[0].autostart, false);
  const spAuto = await api('PATCH', '/api/pins/prefs', { boot_mode: 'autostart' });
  assert.equal(spAuto.status, 200);
  assert.equal(readPins()[0].autostart, true);

  // 1c. Closing an auto-persisted agent tab deletes its auto pin cleanly (no zombie parked card)
  const delAuto = await api('DELETE', `/api/tabs/${t1}`);
  assert.equal(delAuto.status, 200);
  assert.equal(delAuto.data.pinned, false);
  assert.equal(readPins().length, 0);

  // 2. Explicit manual pin (persist: false -> POST /api/pins), rename, and live auto-follow
  const r1m = await api('POST', '/api/tabs', { preset: 'agent', agent: 'claude', cwd: repo, persist: false });
  assert.equal(r1m.status, 201);
  const t1m = r1m.data.terminal.address;
  const pinRes = await api('POST', '/api/pins', { terminal: t1m });
  assert.equal(pinRes.status, 201);
  const pinId = pinRes.data.pin.id;
  assert.equal(pinRes.data.pin.agent, 'claude');
  assert.equal(pinRes.data.pin.title, 'shop-api');
  assert.equal(pinRes.data.pin.autostart, false);

  const ren = await api('PATCH', `/api/tabs/${t1m}`, { title: 'Shop Core' });
  assert.equal(ren.status, 200);
  assert.equal(readPins()[0].title, 'Shop Core');
  assert.equal(readPins()[0].title_source, 'user');

  // Simulate user cd'ing to proj2 and temporarily exiting claude to bash
  const liveT1 = hc.terminals.get(t1m);
  liveT1.foreground = { name: 'bash', cwd: proj2 };
  liveT1.agent = 'bash';
  assert.equal(syncPinsFromTerminals(hc.listSnapshot()), true);
  assert.equal(readPins()[0].cwd, proj2);
  assert.equal(readPins()[0].agent, 'claude', 'agent pin must not downgrade to shell');

  // Move back to repo for collision tests
  liveT1.foreground = { name: 'claude', cwd: repo };
  syncPinsFromTerminals(hc.listSnapshot());

  // 3. /api/worktrees/check reports live collision upfront, and POST /api/tabs still enforces 409 in `ask` mode
  const chkCol = await api('GET', `/api/worktrees/check?cwd=${encodeURIComponent(repo)}`);
  assert.equal(chkCol.status, 200);
  assert.equal(chkCol.data.is_git, true);
  assert.ok(chkCol.data.collision, 'expected live collision in check response');
  assert.equal(chkCol.data.collision.repo_name, 'shop-api');
  assert.equal(chkCol.data.collision.branch, 'main');
  assert.equal(chkCol.data.collision.active_tabs.length, 1);

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

  // Closing an empty unpinned worktree auto-removes the worktree, and no snapshot broadcast during the close reports it as
  // pending: that showed the Pending worktrees pill for a moment and made the sidebar jump.
  const listed = await api('GET', '/api/worktrees');
  assert.ok(listed.data.worktrees.some((w) => w.path === wtPath), 'the worktree is in the cached list before the close');
  // An events client (the fake ws module records what it is sent in globalThis.__wsSent).
  const upReq = http.request({ host: '127.0.0.1', port, path: '/ws/events', headers: { Connection: 'Upgrade', Upgrade: 'websocket' } });
  upReq.on('error', () => {});
  upReq.end();
  await new Promise((resolve) => setTimeout(resolve, 100));
  globalThis.__wsSent = [];
  const delEmpty = await api('DELETE', `/api/tabs/${t2}`);
  const evMsgs = globalThis.__wsSent.map((d) => { try { return JSON.parse(d); } catch (_) { return {}; } });
  upReq.destroy();
  assert.equal(delEmpty.status, 200);
  assert.equal(delEmpty.data.auto_cleaned_worktree, true);
  assert.equal(fs.existsSync(wtPath), false);
  const duringClose = evMsgs.filter((m) => Array.isArray(m.worktrees));
  assert.ok(duringClose.length >= 2, 'the kill event and the close both broadcast');
  for (const m of duringClose) {
    assert.ok(!m.worktrees.some((w) => w.path === wtPath), `a ${m.type} broadcast listed the closing worktree as pending`);
  }

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

  // 5. Close manually pinned tab t1m -> stays PARKED; wake it -> launches with --continue
  const delPinTab = await api('DELETE', `/api/tabs/${t1m}`);
  assert.equal(delPinTab.status, 200);
  assert.equal(delPinTab.data.pinned, true);
  const pinsAfterClose = await api('GET', '/api/pins');
  assert.equal(pinsAfterClose.data.pins.find((p) => p.id === pinId).parked, true);

  const woken = await api('POST', `/api/pins/${pinId}/wake`, {});
  assert.equal(woken.status, 201);
  assert.ok(woken.data.terminal.argv.join(' ').includes('claude --continue'));

  // 6. Prefs update (auto/off/ask)
  const pr = await api('PATCH', '/api/worktrees/prefs', { mode: 'off', copy_env: false });
  assert.equal(pr.status, 200);
  assert.equal(pr.data.prefs.mode, 'off');
  assert.equal(pr.data.prefs.copy_env, false);

  // 6b. Installed agents + session_prefs surfaced in /api/tabs
  const tabsSnap = await api('GET', '/api/tabs');
  assert.equal(tabsSnap.status, 200);
  assert.ok(Array.isArray(tabsSnap.data.installed_agents));
  assert.equal(tabsSnap.data.session_prefs.boot_mode, 'autostart');

  // 6c. Mobile touch/zoom diagnostic telemetry endpoint
  const dbgPost = await api('POST', '/api/debug/touch', { kind: 'scroll_end', agent: 'agy', bufType: 'alternate', dy: 120, wheelSent: 4 });
  assert.equal(dbgPost.status, 200);
  assert.equal(dbgPost.data.ok, true);
  const dbgGet = await api('GET', '/api/debug/touch');
  assert.equal(dbgGet.status, 200);
  assert.equal(dbgGet.data.events.length, 1);
  assert.equal(dbgGet.data.events[0].agent, 'agy');

  // 7. System events (autoname) surfaced in Sysop snapshot & filtered by New conversation
  const runSysop = path.join(process.env.SB_RUN_DIR, 'sysop');
  const stateSysop = path.join(process.env.XDG_STATE_HOME, 'swarmbox', 'sysop');
  fs.mkdirSync(runSysop, { recursive: true });
  fs.mkdirSync(stateSysop, { recursive: true });
  fs.writeFileSync(path.join(runSysop, 'status.json'), JSON.stringify({ pid: process.pid, bus: 'connected' }));
  const nowSec = Date.now() / 1000;
  fs.writeFileSync(
    path.join(stateSysop, 'system_events.jsonl'),
    JSON.stringify({ id: 'ev1', kind: 'autoname', ts: nowSec - 5, tab: 't1', old_title: 'shop-api', new_title: 'Fix Cache' }) + '\n'
      + JSON.stringify({ id: 'ev2', kind: 'autocontext', ts: nowSec - 4, phase: 'failed', repo: 'shop', key: 'k1', commit: 'abc123',
        tab: 't1', agent: 'claude', error: 'not logged in', retry_min: 10 }) + '\n',
  );
  const snap1 = readSysopSnapshot([]);
  assert.equal(snap1.system_events.length, 2);
  assert.equal(snap1.system_events[0].new_title, 'Fix Cache');
  const ctx = snap1.system_events[1];
  assert.deepEqual([ctx.phase, ctx.repo, ctx.commit, ctx.error, ctx.retry_min], ['failed', 'shop', 'abc123', 'not logged in', 10]);
  startNewConversation(nowSec);
  const snap2 = readSysopSnapshot([]);
  assert.equal(snap2.system_events.length, 0);

  // 8. Unpin removes pin
  const unpin = await api('DELETE', `/api/pins/${pinId}`);
  assert.equal(unpin.status, 200);
  assert.equal(readPins().length, 0);

  // 9. An agent typed into a plain shell tab in a folder without a repo is auto-pinned on the next snapshot,
  //    once, with the live agent and folder, so a restart brings the agent back instead of a bare shell.
  const sh = await api('POST', '/api/tabs', { preset: 'shell', cwd: proj2 });
  assert.equal(sh.status, 201);
  const tSh = sh.data.terminal.address;
  hc.emit('snapshot');
  assert.equal(readPins().filter((p) => p.cwd === proj2).length, 0, 'a plain shell is not pinned');
  hc.terminals.get(tSh).foreground = { name: 'agy', cwd: proj2 };
  hc.emit('snapshot');
  hc.emit('snapshot');
  await new Promise((r) => setTimeout(r, 20));
  const shPins = readPins().filter((p) => p.cwd === proj2);
  assert.equal(shPins.length, 1, 'exactly one auto pin for the shell that started an agent');
  assert.equal(shPins[0].agent, 'agy');
  assert.equal(shPins[0].auto, true);
  assert.equal(shPins[0].autostart, true);
  assert.equal(shPins[0].title, 'other-proj');
  assert.equal(hc.terminals.get(tSh).labels['swarmbox.pin_id'], shPins[0].id);
  // Closing the tab drops the auto pin like any other agent tab
  const delSh = await api('DELETE', `/api/tabs/${tSh}`);
  assert.equal(delSh.status, 200);
  assert.equal(readPins().filter((p) => p.cwd === proj2).length, 0);

  // 9b. persist: false opts an agent tab out of auto-pinning
  const np = await api('POST', '/api/tabs', { preset: 'agent', agent: 'claude', cwd: proj2, persist: false });
  assert.equal(np.status, 201);
  hc.emit('snapshot');
  await new Promise((r) => setTimeout(r, 20));
  assert.equal(readPins().filter((p) => p.cwd === proj2).length, 0, 'persist:false must not be auto-pinned');

  // 10. The New agent picker: recent folders (launches first) and a folder browser that flags repos
  const projs = await api('GET', '/api/projects');
  assert.equal(projs.status, 200);
  assert.equal(projs.data.recent[0].path, proj2);
  assert.equal(projs.data.recent[0].is_git, false);
  const dirs = await api('GET', `/api/dirs?path=${encodeURIComponent(process.env.HOME)}`);
  assert.equal(dirs.status, 200);
  const byName = Object.fromEntries(dirs.data.entries.map((d) => [d.name, d]));
  assert.equal(byName['shop-api'].is_git, true);
  assert.equal(byName['shop-api'].branch, 'main');
  assert.equal(byName['other-proj'].is_git, false);
  assert.ok(!dirs.data.entries.some((d) => d.name.startsWith('.')), 'hidden folders are skipped');
  const noDir = await api('GET', `/api/dirs?path=${encodeURIComponent(path.join(proj2, 'missing'))}`);
  assert.equal(noDir.status, 404);

  // 11. The default agent: one answer for New agent and worktree open, whatever name the box's AGENT setting uses
  const killAll = async () => { for (const t of hc.listSnapshot()) await api('DELETE', `/api/tabs/${t.address}`); };
  process.env.SWARMBOX_AGENT = 'antigravity';   // the addon name of agy
  const defTab = await api('POST', '/api/tabs', { preset: 'agent', cwd: proj2, persist: false });
  assert.equal(defTab.status, 201);
  const defTerm = hc.terminals.get(defTab.data.address);
  assert.equal(defTerm.labels['swarmbox.agent'], 'agy');
  assert.ok(defTerm.argv.join(' ').includes('agy'), defTerm.argv.join(' '));
  await killAll();
  delete process.env.SWARMBOX_AGENT;             // a box without a default agent
  const wtOpen = await api('POST', '/api/worktrees/open', { path: proj2 });
  const wtTerm = hc.listSnapshot().find((t) => t.cwd === proj2);
  assert.ok(wtTerm, JSON.stringify(wtOpen));
  assert.equal(wtTerm.labels['swarmbox.agent'], 'shell', 'worktree open must not start an agent the box may not have');
  assert.deepEqual(wtTerm.argv, ['/bin/bash', '-l']);

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
        shutil.copyfile(PREVIEW_MJS, os.path.join(web_dir, "file-preview.mjs"))
        shutil.copyfile(os.path.join(ROOT, "container", "web", "herdr", "agents.mjs"), os.path.join(web_dir, "agents.mjs"))
        with open(os.path.join(ws_dir, "package.json"), "w", encoding="utf-8") as f:
            json.dump({"name": "ws", "type": "module", "main": "index.js"}, f)
        with open(os.path.join(ws_dir, "index.js"), "w", encoding="utf-8") as f:
            f.write("import { EventEmitter } from 'node:events';\n"
                    "export class WebSocketServer extends EventEmitter {\n"
                    "  constructor() { super(); this.clients = new Set(); }\n"
                    "  handleUpgrade(_req, _sock, _head, cb) {\n"
                    "    cb({ readyState: 1, send(d) { (globalThis.__wsSent ||= []).push(d); }, close() {}, on() {}, ping() {} });\n"
                    "  }\n"
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
            "SWARMBOX_IMAGE_ADDONS_DIR": os.path.join(ROOT, "container", "addons"),   # the staged agents.mjs is not next to them
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
