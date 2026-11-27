"""Fast tests of the sysop's live events in the Web Studio gateway (docs/sysop-brain-design.md 4.4): the incremental tail of a goal's
events.jsonl (GoalEventsTail), the compaction of a replay, the labels an action gets, and the gateway's relay: a line the service appends
reaches every page as a `sysop_events` message at once (inotify), a page that connects gets the goal's events so far, an event that changes
the snapshot brings the snapshot, and a slow page gets its events held and coalesced.

The real hc-client.mjs and createGateway() with an in-memory fake HerdrClient and fake event sockets; run and state folders in a mktemp.

Run: python3 tests/fast/test_sysop_live_web.py
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
from helpers import ROOT, stage_herdr_web  # noqa: E402

WEB = os.path.join(ROOT, "container", "web", "herdr")

PRELUDE = r"""
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { EventEmitter } from 'node:events';
import { GoalEventsTail, compactEvents, sysopLiveTail } from './hc-client.mjs';

const goalsDir = path.join(process.env.XDG_STATE_HOME, 'swarmbox', 'sysop', 'goals');
let seq = 0;
const line = (type, fields = {}) => JSON.stringify({ seq: ++seq, t: Date.now() / 1000, type, ...fields }) + '\n';
function goal(gid) {
  const d = path.join(goalsDir, gid);
  fs.mkdirSync(d, { recursive: true });
  fs.writeFileSync(path.join(d, 'state.json'), JSON.stringify({ id: gid, source: 'web', text: 'oi', state: 'running', started: Date.now() / 1000 }));
  fs.writeFileSync(path.join(d, 'events.jsonl'), '');
  fs.mkdirSync(path.join(process.env.SB_RUN_DIR, 'sysop'), { recursive: true });
  fs.writeFileSync(path.join(process.env.SB_RUN_DIR, 'sysop', 'status.json'), JSON.stringify({ pid: process.pid, current: gid, queue: [] }));
  return path.join(d, 'events.jsonl');
}
"""


def run_node(test, js):
    """The harness in a scratch copy of the Web Studio modules, with a zero-dependency `ws` stub (offline CI has no npm packages)."""
    if not shutil.which("node"):
        test.skipTest("node is not installed")
    tmp = tempfile.mkdtemp(prefix="swarmbox-test-sysop-live.")
    test.addCleanup(shutil.rmtree, tmp, True)
    web = os.path.join(tmp, "web")
    ws = os.path.join(web, "node_modules", "ws")
    os.makedirs(ws)
    stage_herdr_web(web)
    with open(os.path.join(ws, "package.json"), "w") as f:
        json.dump({"name": "ws", "type": "module", "main": "index.js"}, f)
    with open(os.path.join(ws, "index.js"), "w") as f:
        f.write("import { EventEmitter } from 'node:events';\n"
                "export class WebSocketServer extends EventEmitter {\n"
                "  constructor() { super(); this.clients = new Set(); }\n"
                "  handleUpgrade() {}\n  close() {}\n}\n")
    with open(os.path.join(web, "run.mjs"), "w") as f:
        f.write(PRELUDE + js)
    env = {"PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"), "HOME": tmp, "TEST_TMP": tmp,
           "SB_RUN_DIR": os.path.join(tmp, "run"), "XDG_STATE_HOME": os.path.join(tmp, "state"),
           "XDG_CONFIG_HOME": os.path.join(tmp, "config"), "XDG_DATA_HOME": os.path.join(tmp, "data"),
           "SWARMBOX_IMAGE_ADDONS_DIR": os.path.join(ROOT, "container", "addons")}
    p = subprocess.run(["node", "run.mjs"], cwd=web, capture_output=True, text=True, env=env, timeout=30)
    test.assertEqual(p.returncode, 0, p.stderr)


class Tail(unittest.TestCase):
    def test_new_lines_once_each_even_cut_in_the_middle_and_actions_get_labels(self):
        run_node(self, r"""
const f = goal('g1');
const t = new GoalEventsTail(f, 'g1');
assert.deepEqual(t.poll(), []);
fs.appendFileSync(f, line('state', { state: 'running' }) + line('action.start', { block: 'toolu_1', fn: 'run' }));
const half = line('action.args', { block: 'toolu_1', fn: 'run', args: { tab: 't1', command: 'pytest -q' } });
fs.appendFileSync(f, half.slice(0, 20));
let got = t.poll();
assert.deepEqual(got.map((e) => e.type), ['state', 'action.start'], 'half a line waits');
assert.ok(got[1].live.startsWith('run'), got[1].live);
fs.appendFileSync(f, half.slice(20) + 'not json\n' + line('say.delta', { block: 'toolu_2', text: 'olá' }));
got = t.poll();
assert.deepEqual(got.map((e) => e.type), ['action.args', 'say.delta']);
assert.equal(got[0].label, 'run: pytest -q', 'the same labels the snapshot turns use');
assert.ok(got[0].live.includes('t1'));
assert.deepEqual(t.poll(), []);
// a gateway that starts in the middle of a goal gets it all from the file
const t2 = new GoalEventsTail(f, 'g1');
t2.poll();
assert.equal(t2.events.length, 4);
""")

    def test_a_replay_merges_the_deltas_of_one_block_without_losing_text(self):
        run_node(self, r"""
const ev = [{ seq: 1, type: 'say.delta', block: 'a', text: 'Ol' }, { seq: 2, type: 'say.delta', block: 'a', text: 'á ' },
            { seq: 3, type: 'call', id: 'a', fn: 'say' }, { seq: 4, type: 'text.delta', block: 'b', text: 'x' },
            { seq: 5, type: 'text.delta', block: 'c', text: 'y' }, { seq: 6, type: 'text.delta', block: 'c', text: 'z' }];
assert.deepEqual(compactEvents(ev).map((e) => [e.seq, e.type, e.text]), [[2, 'say.delta', 'Olá '], [3, 'call', undefined],
  [4, 'text.delta', 'x'], [6, 'text.delta', 'yz']]);
""")


class PageReducer(unittest.TestCase):
    """public/sysoplive.js: what the panel draws of the running goal from its events"""

    def test_a_goal_as_the_panel_sees_it_and_the_paced_reveal(self):
        if not shutil.which("node"):
            self.skipTest("node is not installed")
        js = r"""
const assert = require('node:assert/strict');
const fs = require('fs'), vm = require('vm');
const ctx = { module: { exports: {} } };
vm.runInNewContext(fs.readFileSync(%s, 'utf8'), ctx);     // as public/tabrefs.js is tested: the file as the page loads it
const R = ctx.module.exports;
const plain = (x) => JSON.parse(JSON.stringify(x));      // objects of the vm's realm, compared by value
const L = { ...R, parts: (g, f) => plain(R.parts(g, f)) };
const g = L.goal();
let n = 0;
const ev = (type, f = {}) => L.apply(g, { seq: ++n, type, ...f });
ev('thinking', { block: 'm1.0', state: 'started' });
assert.equal(L.line(g, 'x'), 'Thinking…');
ev('action.start', { block: 'tA', fn: 'say' });
ev('say.delta', { block: 'tA', text: 'Olhando ' });
ev('say.delta', { block: 'tA', text: 'as abas' });
let p = L.parts(g);
assert.deepEqual(p.notes, [{ text: '', streaming: true }], 'nothing is revealed before a frame');
assert.equal(p.line, 'Writing a note…');
let frames = 0;
while (L.pace(g, false).more) frames++;
assert.ok(frames >= 1 && frames < 10, 'a short burst is revealed in a few frames: ' + frames);
assert.deepEqual(L.parts(g).notes, [{ text: 'Olhando as abas', streaming: true }], 'still streaming: the say has not run');
ev('call', { id: 'tA', fn: 'say', args: {} });
ev('say', { text: 'Olhando as abas' });
ev('call.end', { id: 'tA', fn: 'say', ok: true });
assert.deepEqual(L.parts(g).notes, [{ text: 'Olhando as abas', streaming: false }]);
ev('action.start', { block: 'tB', fn: 'run', live: 'run · ' });
assert.equal(L.parts(g).line, 'run · ', 'the action shows the moment the model chose it');
ev('action.args', { block: 'tB', fn: 'run', args: { tab: 't1', command: 'make' }, label: 'run: make', live: 'run → t1' });
ev('call', { id: 'tB', fn: 'run', args: {}, label: 'run: make', live: 'run → t1' });
ev('approval', { id: 'tB', state: 'waiting' });
assert.equal(L.parts(g).line, 'Waiting for you · run → t1');
assert.deepEqual(L.parts(g).acts, [{ ok: true, state: 'waiting', label: 'run: make', fn: 'run' }]);
ev('approval', { id: 'tB', state: 'denied' });
ev('call.end', { id: 'tB', fn: 'run', ok: false });
assert.deepEqual(L.parts(g).acts.map((a) => [a.ok, a.state]), [[false, 'refused']], 'a refused action stays refused');
assert.equal(L.line(g, 'run → t1'), 'Thinking…', 'after a call ended, the model is at work: not the old label of the snapshot');
ev('action.start', { block: 'tC', fn: 'done' });
ev('reply.delta', { block: 'tC', text: 'x'.repeat(1000) });
frames = 0;
while (L.pace(g, false).more) frames++;
assert.ok(frames >= 8 && frames <= 40, 'a 1 KB burst takes a few hundred ms at 60 fps, not one frame: ' + frames);
ev('call', { id: 'tC', fn: 'done' });
ev('done', { summary: 'Pronto.' });
ev('text.delta', { block: 'm9.0', text: 'extra turn after done' });
L.pace(g, true);
assert.equal(L.parts(g).reply.text, 'Pronto.', 'the summary of done wins over the extra turn');
assert.equal(L.line(g, 'box_state · system'), 'Finishing…', 'after done the line says the goal is finishing, not an old action');
assert.equal(L.apply(g, { seq: 3, type: 'say', text: 'old' }), false, 'an event at or below the last seq is ignored');
""" % json.dumps(os.path.join(WEB, "public", "sysoplive.js"))
        p = subprocess.run(["node", "-e", js], capture_output=True, text=True, timeout=30)
        self.assertEqual(p.returncode, 0, p.stderr)
        with open(os.path.join(WEB, "public", "index.html")) as f:
            html = f.read()
        self.assertLess(html.index('src="/sysoplive.js"'), html.index('src="/app.js"'), "the reducer loads before the page that uses it")

    def test_bbs_afterglow_spans_and_styles(self):
        if not shutil.which("node"):
            self.skipTest("node is not installed")
        js = r"""
const assert = require('node:assert/strict');
const fs = require('fs'), vm = require('vm');
const ctx = { module: { exports: {} } };
vm.runInNewContext(fs.readFileSync(%s, 'utf8'), ctx);
const L = ctx.module.exports;
const plain = (x) => JSON.parse(JSON.stringify(x));
// Replay skips glow so existing text does not flash on reconnect
let e = L.glowStep(null, 20, 1000, 560, true);
assert.equal(e.len, 20);
assert.deepEqual(plain(e.spans), []);
// Incremental reveals record spans and prune expired ones
e = L.glowStep(e, 26, 1100, 560, false);
e = L.glowStep(e, 31, 1300, 560, false);
assert.deepEqual(plain(e.spans), [
  { from: 20, to: 26, at: 1100 },
  { from: 26, to: 31, at: 1300 },
]);
// Markdown closing syntax can shrink rendered text: clamp spans safely
e = L.glowStep(e, 28, 1350, 560, false);
assert.equal(e.len, 28);
assert.deepEqual(plain(e.spans), [
  { from: 20, to: 26, at: 1100 },
  { from: 26, to: 28, at: 1300 },
]);
// Once past decay duration, older spans expire
e = L.glowStep(e, 28, 1700, 560, false);
assert.deepEqual(plain(e.spans), [{ from: 26, to: 28, at: 1300 }]);
e = L.glowStep(e, 28, 1900, 560, false);
assert.deepEqual(plain(e.spans), []);
""" % json.dumps(os.path.join(WEB, "public", "sysoplive.js"))
        p = subprocess.run(["node", "-e", js], capture_output=True, text=True, timeout=30)
        self.assertEqual(p.returncode, 0, p.stderr)
        with open(os.path.join(WEB, "public", "app.css")) as f:
            css = f.read()
        self.assertIn("@keyframes bbs-afterglow", css)
        self.assertIn(".bbs-glow", css)
        self.assertIn("prefers-reduced-motion: reduce", css)


class Gateway(unittest.TestCase):
    def test_appended_events_reach_every_page_at_once_and_a_new_page_gets_the_goal_so_far(self):
        run_node(self, r"""
import { createGateway } from './server.mjs';
class FakeHc extends EventEmitter {
  constructor() { super(); this.proc = {}; }
  listSnapshot() { return []; }
  async call() { return { terminals: [] }; }
  close() {}
}
class FakeWs extends EventEmitter {
  constructor() { super(); this.readyState = 1; this.sent = []; this.bufferedAmount = 0; }
  send(raw) { this.sent.push(JSON.parse(raw)); }
  ping() {}
  close() { this.readyState = 3; }
}
const f = goal('g7');
fs.appendFileSync(f, line('state', { state: 'running' }));
// no fallback timer and no 600 ms snapshot timer in this test: inotify and the events must do it all
const gw = createGateway({ hc: new FakeHc(), liveFallbackMs: 60000, sysopPollMs: 60000 });
const a = new FakeWs();
gw.wss.emit('connection', a, {}, new URL('http://127.0.0.1:7681/ws/events?clientId=a'));
const live = (ws) => ws.sent.filter((m) => m.type === 'sysop_events');
const until = async (ok, what) => { for (let i = 0; i < 300 && !ok(); i++) await new Promise((r) => setTimeout(r, 10)); assert.ok(ok(), what); };
try {
  assert.equal(live(a)[0].replay, true, 'a page that connects gets the events so far');
  assert.deepEqual(live(a)[0].events.map((e) => e.type), ['state']);
  const t0 = Date.now();
  fs.appendFileSync(f, line('say.delta', { block: 'toolu_1', text: 'Tu' }) + line('say.delta', { block: 'toolu_1', text: 'do' }));
  await until(() => live(a).some((m) => !m.replay && m.events.some((e) => e.text === 'do')), 'inotify woke the pump');
  assert.ok(Date.now() - t0 < 1500, 'well before any fallback timer');
  const snaps = () => a.sent.filter((m) => m.type === 'sysop').length;
  const before = snaps();
  // the MCP server writes say.jsonl as it emits `say`: the snapshot's notes change, and the event brings that snapshot at once
  fs.writeFileSync(path.join(path.dirname(f), 'say.jsonl'), JSON.stringify({ t: Date.now() / 1000, text: 'Tudo' }) + '\n');
  fs.appendFileSync(f, line('call', { id: 'toolu_1', fn: 'say', args: { text: 'Tudo' } }) + line('say', { text: 'Tudo' }));
  await until(() => snaps() > before, 'a say brings the snapshot (the 600 ms timer is not waited for)');
  const snap = a.sent.filter((m) => m.type === 'sysop').at(-1);
  assert.deepEqual(snap.sysop.turns.at(-1).notes, ['Tudo']);
  // a second page now gets one compacted replay
  const b = new FakeWs();
  gw.wss.emit('connection', b, {}, new URL('http://127.0.0.1:7681/ws/events?clientId=b'));
  const r = live(b).find((m) => m.replay);
  assert.deepEqual(r.events.map((e) => e.type), ['state', 'say.delta', 'call', 'say']);
  assert.equal(r.events[1].text, 'Tudo');
  // a slow page: its events are held and come coalesced once its buffer drains
  a.bufferedAmount = 5 << 20;
  const n = live(a).length;
  fs.appendFileSync(f, line('text.delta', { block: 'm1.0', text: 'a' }));
  await until(() => live(b).some((m) => m.events.some((e) => e.text === 'a')), 'the fast page is not held back');
  fs.appendFileSync(f, line('text.delta', { block: 'm1.0', text: 'b' }));
  await until(() => live(b).some((m) => m.events.some((e) => e.text === 'b')), 'the fast page gets the next one');
  assert.equal(live(a).length, n, 'nothing is sent to a page whose buffer is full');
  a.bufferedAmount = 0;
  await until(() => live(a).length > n, 'the held events go once the buffer drains');
  const held = live(a).slice(n).flatMap((m) => m.events).filter((e) => e.type === 'text.delta');
  assert.deepEqual(held.map((e) => e.text), ['ab'], 'coalesced into one delta');
  const seqs = live(a).filter((m) => !m.replay).flatMap((m) => m.events).map((e) => e.seq);
  assert.deepEqual(seqs, [...seqs].sort((x, y) => x - y));
} finally {
  gw.shutdown();
}
""")


if __name__ == "__main__":
    unittest.main()
