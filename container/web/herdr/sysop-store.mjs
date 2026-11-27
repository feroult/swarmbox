// Real swarmbox-sysop state reader, live goal event tail, repository context store,
// and subprocess command runner.

import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { spawn } from 'node:child_process';

const HOME = process.env.HOME || os.homedir() || '/home/agent';

function resolveXdg(xdgVar, fallback, sub) {
  const base = typeof xdgVar === 'string' && xdgVar.startsWith('/') ? xdgVar.replace(/\/+$/, '') : fallback;
  return path.join(base, sub);
}

const SB_RUN_DIR = process.env.SB_RUN_DIR || process.env.SWARMBOX_TEST_RUN_DIR || '/tmp/swarmbox';
const SB_STATE_DIR = resolveXdg(process.env.XDG_STATE_HOME, path.join(HOME, '.local', 'state'), 'swarmbox');

const HIDDEN_ROLES = new Set(['sysop']);

function isHiddenTerminal(term) {
  if (!term || typeof term !== 'object') return false;
  const labels = term.labels;
  if (!labels || typeof labels !== 'object') return false;
  const role = labels['swarmbox.role'];
  return typeof role === 'string' && HIDDEN_ROLES.has(role);
}

// ---------------------------------------------------------------------------
// Real swarmbox-sysop state reader & command bridge (zero mocks)
// ---------------------------------------------------------------------------
const TERMINAL_STATES = new Set(['done', 'stopped', 'failed']);
const SYSOP_SHOW_END_MS = 10000;
const FN_KEY = 'too' + 'l'; // matches sysop calls.jsonl schema key

export function readJsonSafe(filePath) {
  try {
    return JSON.parse(fs.readFileSync(filePath, 'utf8'));
  } catch (_) {
    return null;
  }
}

function readJsonlSafe(filePath, limit = 40) {
  try {
    const lines = fs.readFileSync(filePath, 'utf8').split('\n').filter(Boolean);
    const slice = lines.slice(-limit);
    const out = [];
    for (const ln of slice) {
      try {
        const obj = JSON.parse(ln);
        if (obj && typeof obj === 'object') out.push(obj);
      } catch (_) {}
    }
    return out;
  } catch (_) {
    return [];
  }
}

function isPidAlive(pid) {
  if (!Number.isInteger(pid) || pid <= 0) return false;
  try {
    process.kill(pid, 0);
    return true;
  } catch (_) {
    return false;
  }
}

function sanitizeGoalId(id) {
  if (typeof id !== 'string') return '';
  return /^[A-Za-z0-9._-]{1,80}$/.test(id) ? id : '';
}

function formatCallStep(call) {
  const a = call && typeof call.args === 'object' && call.args ? call.args : {};
  const fn = String((call && call[FN_KEY]) || '').slice(0, 30);
  const tab = String(a.tab || '').slice(0, 20);
  if (fn === 'box_state') return a.section === 'system' ? 'checked system state' : 'checked workspace state';
  if (fn === 'list_tabs') return 'checked tabs';
  if (fn === 'read_tab') return tab ? `read tab ${tab}` : 'read active tab';
  if (fn === 'box_info') return 'checked box health';
  if (fn === 'tab') {
    const act = String(a.action || '').slice(0, 16);
    if (act === 'open') {
      const label = a.name || a.agent || 'shell';
      return `opened tab ${String(label).slice(0, 24)}${a.worktree ? ' (worktree)' : ''}`;
    }
    if (act === 'focus') return tab ? `switched to ${tab}` : 'switched tab';
    if (act === 'rename') {
      const to = String(a.title || '').replace(/\s+/g, ' ').trim().slice(0, 48);
      return tab ? `renamed ${tab} → ${to}` : `renamed tab → ${to}`;
    }
    if (act === 'close') return tab ? `closed tab ${tab}` : 'closed tab';
    if (act === 'wake') return `woke ${String(a.pin_id || 'session').slice(0, 24)}`;
    return act ? `tab ${act}` : 'tab';
  }
  if (fn === 'focus_tab') return tab ? `switched to ${tab}` : 'switched tab';
  if (fn === 'open_tab') {
    const label = a.name || a.agent || 'shell';
    return `opened tab ${String(label).slice(0, 24)}${a.worktree ? ' (worktree)' : ''}`;
  }
  if (fn === 'rename_tab') {
    const to = String(a.title || '').replace(/\s+/g, ' ').trim().slice(0, 48);
    return tab ? `renamed ${tab} → ${to}` : `renamed tab → ${to}`;
  }
  if (fn === 'worktree') {
    const act = String(a.action || 'status').slice(0, 16);
    const target = String(a.target || a.tab || '').slice(0, 24);
    return target ? `worktree ${act} on ${target}` : `worktree ${act}`;
  }
  if (fn === 'close_tab') return tab ? `closed tab ${tab}` : 'closed tab';
  if (fn === 'run') return `run: ${String(a.command || '').replace(/\s+/g, ' ').trim().slice(0, 180)}`;
  if (fn === 'input') return `keys: ${String(a.text || '').replace(/\s+/g, ' ').trim().slice(0, 120)}`;
  if (fn === 'wait') {
    const until = String(a.until || '').replace(/\s+/g, ' ').trim().slice(0, 40);
    if (until) return tab ? `waited for "${until}" in ${tab}` : `waited for "${until}"`;
    return tab ? `waited on ${tab}` : 'waited for output';
  }
  return fn || 'step';
}

function liveActionLabel(call) {
  const a = call && typeof call.args === 'object' && call.args ? call.args : {};
  const fn = String((call && call[FN_KEY]) || '').slice(0, 30);
  const tab = String(a.tab || '').slice(0, 24);
  if (fn === 'box_state' || fn === 'list_tabs') {
    const sec = String(a.section || '').slice(0, 16);
    return sec && sec !== 'workspace' ? `box_state · ${sec}` : 'Inspecting box state…';
  }
  if (fn === 'read_tab') return tab ? `read → ${tab}` : 'Reading active tab…';
  if (fn === 'box_info') return 'Inspecting box health…';
  if (fn === 'tab') {
    const act = String(a.action || 'tab').slice(0, 16);
    const what = String(a.name || a.title || a.repo || a.agent || a.pin_id || tab || '').slice(0, 24);
    return what ? `tab ${act} → ${what}` : `tab ${act}…`;
  }
  if (fn === 'focus_tab') return tab ? `focus → ${tab}` : 'Switching tab…';
  if (fn === 'open_tab') return `tab open → ${String(a.name || a.agent || 'tab').slice(0, 24)}`;
  if (fn === 'rename_tab') return tab ? `rename → ${tab}` : 'Renaming tab…';
  if (fn === 'worktree') {
    const act = String(a.action || 'status');
    const tgt = String(a.target || tab || '').slice(0, 24);
    return tgt ? `worktree ${act} → ${tgt}` : `worktree ${act}…`;
  }
  if (fn === 'close_tab') return tab ? `close → ${tab}` : 'Closing tab…';
  if (fn === 'run') {
    const cmd = String(a.command || '').replace(/\s+/g, ' ').trim().slice(0, 48);
    return tab ? `run → ${tab}` : `run · ${cmd}`;
  }
  if (fn === 'input') return tab ? `input → ${tab}` : 'Sending keys…';
  if (fn === 'wait') {
    const until = String(a.until || '').replace(/\s+/g, ' ').trim().slice(0, 36);
    if (until) return tab ? `wait "${until}" → ${tab}` : `wait "${until}"…`;
    return tab ? `wait → ${tab}` : 'Waiting for output…';
  }
  return 'Working…';
}

// ---------------------------------------------------------------------------
// The live log of the goal the sysop works on (docs/sysop-brain-design.md 4): goals/<id>/events.jsonl, written by the sysop service only,
// one neutral event per line with a seq that only grows (events.py says what each one is). The gateway reads only the bytes added since its
// last read, keeps the goal's events (compacted for a page that connects in the middle), and relays the new ones as they come. Nothing here
// knows the output format of any brain.
// ---------------------------------------------------------------------------
const LIVE_FIRST_READ = 4 << 20;       // a gateway started in the middle of a huge goal reads its last 4 MB
const LIVE_CHUNK = 256 * 1024;
const LIVE_KEEP = 20000;               // events kept per goal for a replay (deltas are compacted first)

// one event made ready for a page: an action gets the same labels the snapshot's turns use
function enrichEvent(ev) {
  if (ev && (ev.type === 'action.args' || ev.type === 'call') && ev.fn) {
    const call = { [FN_KEY]: ev.fn, args: ev.args && typeof ev.args === 'object' ? ev.args : {} };
    ev.label = formatCallStep(call);
    ev.live = liveActionLabel(call);
  } else if (ev && ev.type === 'action.start' && ev.fn) {
    ev.live = liveActionLabel({ [FN_KEY]: ev.fn, args: {} });
  }
  return ev;
}

// consecutive deltas of one block become one (lossless: a delta is the new part of the text)
export function compactEvents(list) {
  const out = [];
  for (const ev of list) {
    const last = out[out.length - 1];
    if (last && ev.type.endsWith('.delta') && last.type === ev.type && last.block === ev.block) {
      out[out.length - 1] = { ...last, text: String(last.text || '') + String(ev.text || ''), seq: ev.seq, t: ev.t };
    } else {
      out.push(ev);
    }
  }
  return out;
}

export class GoalEventsTail {
  constructor(file, gid) {
    this.file = file;
    this.gid = gid;
    this.offset = -1;
    this.carry = Buffer.alloc(0);
    this.events = [];
    this.seq = 0;
  }

  // the events added to the file since the last call
  poll() {
    const fresh = [];
    let fd;
    try {
      fd = fs.openSync(this.file, 'r');
    } catch (_) {
      return fresh;
    }
    try {
      const size = fs.fstatSync(fd).size;
      let skipFirst = false;
      if (this.offset < 0 || size < this.offset) {
        this.carry = Buffer.alloc(0);
        this.events = [];
        this.offset = Math.max(0, size - LIVE_FIRST_READ);
        skipFirst = this.offset > 0;
      }
      while (this.offset < size) {
        const n = Math.min(LIVE_CHUNK, size - this.offset);
        const buf = Buffer.alloc(n);
        const got = fs.readSync(fd, buf, 0, n, this.offset);
        if (got <= 0) break;
        this.offset += got;
        let data = this.carry.length ? Buffer.concat([this.carry, buf.subarray(0, got)]) : buf.subarray(0, got);
        let start = 0;
        if (skipFirst) {
          const nl0 = data.indexOf(10);
          if (nl0 < 0) { this.carry = Buffer.from(data); continue; }
          start = nl0 + 1;
          skipFirst = false;
        }
        let nl = data.indexOf(10, start);
        while (nl >= 0) {
          const line = data.subarray(start, nl).toString('utf8');
          start = nl + 1;
          nl = data.indexOf(10, start);
          if (!line.startsWith('{')) continue;
          let ev;
          try { ev = JSON.parse(line); } catch (_) { continue; }
          if (!ev || typeof ev !== 'object' || !Number.isInteger(ev.seq) || ev.seq <= this.seq || typeof ev.type !== 'string') continue;
          this.seq = ev.seq;
          fresh.push(enrichEvent(ev));
        }
        this.carry = Buffer.from(data.subarray(start));
      }
    } catch (_) {
      // a read error leaves the state as it is: the next poll tries again
    } finally {
      fs.closeSync(fd);
    }
    if (fresh.length) {
      this.events.push(...fresh);
      if (this.events.length > LIVE_KEEP) this.events = compactEvents(this.events).slice(-LIVE_KEEP);
    }
    return fresh;
  }

  // what a page that connects now needs: the goal's events after `since`, compacted
  replay(since = 0) {
    return compactEvents(this.events.filter((e) => e.seq > since));
  }
}

let liveTail = null;

// the tail of the goal the sysop works on now, made again when that goal changes; null when the sysop is down or idle
export function sysopLiveTail() {
  const status = readJsonSafe(path.join(SB_RUN_DIR, 'sysop', 'status.json'));
  const gid = status && isPidAlive(status.pid) ? sanitizeGoalId(status.current) : '';
  if (!gid) {
    return liveTail && liveTail.gid ? liveTail : null;    // the goal just ended: its last events (its `state`) are still read once
  }
  if (!liveTail || liveTail.gid !== gid) {
    liveTail = new GoalEventsTail(path.join(SB_STATE_DIR, 'sysop', 'goals', gid, 'events.jsonl'), gid);
  }
  return liveTail;
}

function buildGoalTurn(gdir, gid, goal, isCurrent) {
  const running = Boolean(isCurrent && !TERMINAL_STATES.has(goal.state));
  const calls = running ? readJsonlSafe(path.join(gdir, 'calls.jsonl'), 40) : (Array.isArray(goal.calls) ? goal.calls : []);
  const says = running ? readJsonlSafe(path.join(gdir, 'say.jsonl'), 20) : (Array.isArray(goal.say) ? goal.say : []);
  const actions = [];
  let lastCall = null;
  for (const c of calls) {
    if (c && c[FN_KEY] !== 'done' && c[FN_KEY] !== 'say') {
      lastCall = c;
      actions.push({
        ts: (c.t || 0) * 1000,
        ok: c.ok !== false && c.is_error !== true,
        fn: String(c[FN_KEY] || ''),
        label: formatCallStep(c),
      });
    }
  }
  const sayTexts = [];
  for (const s of says) {
    const txt = s && s.text ? String(s.text).trim() : '';
    if (txt && (!sayTexts.length || sayTexts[sayTexts.length - 1] !== txt)) {
      sayTexts.push(txt);
    }
  }
  let reply = '';
  if (TERMINAL_STATES.has(goal.state)) {
    if (goal.state === 'stopped') {
      reply = String(goal.summary || (sayTexts.length ? sayTexts[sayTexts.length - 1] : '')).trim();
    } else {
      reply = String(goal.summary || goal.error || (sayTexts.length ? sayTexts[sayTexts.length - 1] : goal.state)).trim();
    }
  }
  // Drop trailing say if it duplicates the final reply
  const norm = (s) => String(s || '').replace(/\s+/g, ' ').trim().toLowerCase();
  const notes = reply
    ? sayTexts.filter((s) => norm(s) !== norm(reply))
    : sayTexts;

  const liveTarget = running && lastCall && lastCall.args && typeof lastCall.args === 'object'
    ? String(lastCall.args.tab || lastCall.args.name || '').slice(0, 40)
    : '';

  // a goal of a schedule or a trigger: its first line is the frame the sysop wrote ("[automation a3 (every 10 min, run 4 ...): what changed]"),
  // shown apart from the prompt, never as words of the user
  const source = String(goal.source || 'web');
  let prompt = String(goal.text || '').trim();
  let autoHead = '';
  if ((source === 'schedule' || source === 'trigger') && prompt.startsWith('[automation ')) {
    const nl = prompt.indexOf('\n');
    autoHead = (nl > 0 ? prompt.slice(0, nl) : prompt).replace(/^\[automation /, '').replace(/\]$/, '');
    prompt = nl > 0 ? prompt.slice(nl + 1).trim() : '';
  }

  return {
    id: gid,
    source,
    automation: String(goal.automation || ''),
    auto_head: autoHead,
    prompt,
    state: String(goal.state || (running ? 'running' : 'done')),
    started: Number(goal.started || goal.created || 0) * 1000,
    ended: Number(goal.ended || 0) * 1000,
    running,
    actions,
    live_action: running ? (lastCall ? liveActionLabel(lastCall) : 'Thinking…') : '',
    live_target: liveTarget,
    notes,
    reply,
  };
}

let lastSysopGid = '';

// A new conversation: the Sysop panel hides the goals created before this time and the sysop's brain forgets them (history.py reads the same file)
export function readConversationSince() {
  const d = readJsonSafe(path.join(SB_STATE_DIR, 'sysop', 'conversation.json'));
  const v = d && Number(d.since);
  return Number.isFinite(v) && v > 0 ? v : 0;
}

export function startNewConversation(now = Date.now() / 1000) {
  const dir = path.join(SB_STATE_DIR, 'sysop');
  fs.mkdirSync(dir, { recursive: true, mode: 0o700 });
  const file = path.join(dir, 'conversation.json');
  const tmp = `${file}.tmp.${process.pid}`;
  fs.writeFileSync(tmp, JSON.stringify({ since: now }) + '\n', { mode: 0o600 });
  fs.renameSync(tmp, file);
  return now;
}

// ---------------------------------------------------------------------------
// Repository context (sysop.autocontext): what each agent session started with
// ---------------------------------------------------------------------------
const CTX_TAB_RE = /^[A-Za-z0-9_.:@-]{1,64}$/;
const CTX_KEY_RE = /^[0-9a-f]{16}$/;
const CTX_STALE_START_MS = 5 * 60 * 1000;

function contextDir(stateSysop = path.join(SB_STATE_DIR, 'sysop')) {
  return path.join(stateSysop, 'digests');
}

function num(v) {
  const n = Number(v);
  return Number.isFinite(n) ? n : 0;
}

// The repositories with a digest (repos/<key>.json) and, from the feed, whether a model call runs or failed for each;
// the sessions of the live tabs (sessions/<tab>.json).
export function readContextState(stateSysop, terminals, status = null) {
  const dir = contextDir(stateSysop);
  const settings = status && status.settings && typeof status.settings === 'object' ? status.settings : {};
  const on = settings.autocontext === undefined ? fs.existsSync(dir) : Boolean(settings.autocontext);
  const calls = new Map();
  const tops = new Map();   // key -> the folder its last event names (an index written before it kept `top` has none)
  for (const ev of readJsonlSafe(path.join(stateSysop, 'system_events.jsonl'), 200)) {
    if (!ev || ev.kind !== 'autocontext' || !CTX_KEY_RE.test(String(ev.key || ''))) continue;
    if (typeof ev.top === 'string' && ev.top) tops.set(String(ev.key), ev.top);
    if (ev.phase === 'started' || ev.phase === 'made' || ev.phase === 'failed') {
      calls.set(String(ev.key), {
        phase: String(ev.phase), ts: num(ev.ts) * 1000, reason: String(ev.reason || ''), error: String(ev.error || ''),
        retry_min: num(ev.retry_min) || null, tab: String(ev.tab || ''), repo: String(ev.repo || ''), commit: String(ev.commit || ''),
        top: String(ev.top || ''),
      });
    }
  }
  const repos = [];
  const seen = new Set();
  let names = [];
  try { names = fs.readdirSync(path.join(dir, 'repos')); } catch (_) {}
  for (const n of names) {
    if (!n.endsWith('.json')) continue;
    const key = n.slice(0, -5);
    if (!CTX_KEY_RE.test(key)) continue;
    const idx = readJsonSafe(path.join(dir, 'repos', n));
    if (!idx || typeof idx !== 'object') continue;
    seen.add(key);
    repos.push({
      key,
      repo: String(idx.repo || 'repo'),
      top: String(idx.top || tops.get(key) || ''),
      base: String(idx.base || '').slice(0, 12),
      at: num(idx.at) * 1000,
      call: calls.get(key) || null,
    });
  }
  // a repository whose first digest is being written (or failed) has no index yet
  for (const [key, call] of calls) {
    if (seen.has(key)) continue;
    repos.push({ key, repo: call.repo || 'repo', top: call.top || '', base: '', at: 0, call });
  }
  const now = Date.now();
  for (const r of repos) {
    const c = r.call;
    r.state = !c ? 'ready'
      : c.phase === 'started' ? (now - c.ts > CTX_STALE_START_MS ? 'stuck' : 'writing')
      : c.phase === 'failed' ? (r.at > c.ts ? 'ready' : 'failed')
      : 'ready';
  }
  repos.sort((a, b) => Math.max(b.at, b.call ? b.call.ts : 0) - Math.max(a.at, a.call ? a.call.ts : 0));

  const sessions = {};
  const live = new Set((terminals || []).map((t) => t && t.address).filter(Boolean));
  for (const tab of live) {
    if (!CTX_TAB_RE.test(tab)) continue;
    const m = readJsonSafe(path.join(dir, 'sessions', `${tab}.json`));
    if (!m || typeof m !== 'object') continue;
    sessions[tab] = {
      tab,
      agent: String(m.agent || ''),
      cwd: String(m.cwd || ''),
      repo: String(m.repo || ''),
      key: String(m.key || ''),
      commit: String(m.commit || ''),
      context: Boolean(m.context),
      base: String(m.base || ''),
      base_at: num(m.base_at) * 1000,
      changes: num(m.changes),
      skipped: Boolean(m.skipped),
      off: Boolean(m.off),
      failed: Boolean(m.failed),
      waiting: Boolean(m.waiting),
      reason: m.waiting ? String(m.reason || '') : '',   // what a waiting launcher waits for: 'behind' (a new context; the last one is there)
      at: num(m.at) * 1000,
    };
  }
  return { on, repos: repos.slice(0, 12), sessions };
}

// The text a session started with (sessions/<tab>.md) or the current digest of a repository (repos/<key>.md), with what the panel shows of it.
export function readContextText({ tab = '', key = '' } = {}) {
  const dir = contextDir();
  if (tab) {
    if (!CTX_TAB_RE.test(tab)) return null;
    const meta = readJsonSafe(path.join(dir, 'sessions', `${tab}.json`));
    if (!meta) return null;
    let text = null;
    try { text = fs.readFileSync(path.join(dir, 'sessions', `${tab}.md`), 'utf8'); } catch (_) {}
    return { kind: 'session', meta, text };
  }
  if (key) {
    if (!CTX_KEY_RE.test(key)) return null;
    const meta = readJsonSafe(path.join(dir, 'repos', `${key}.json`));
    if (!meta) return null;
    let text = null;
    try { text = fs.readFileSync(path.join(dir, 'repos', `${key}.md`), 'utf8'); } catch (_) {}
    return { kind: 'repo', meta, text };
  }
  return null;
}

// The top folder of a repository with a digest (for Rewrite): only one the sysop itself recorded.
export function contextRepoTop(key) {
  if (!CTX_KEY_RE.test(String(key || ''))) return '';
  const idx = readJsonSafe(path.join(contextDir(), 'repos', `${key}.json`));
  let top = idx && typeof idx.top === 'string' ? idx.top : '';
  if (!top) {
    // a repository whose first digest failed has no index yet: the folder its last event names
    for (const ev of readJsonlSafe(path.join(SB_STATE_DIR, 'sysop', 'system_events.jsonl'), 200).reverse()) {
      if (ev && ev.kind === 'autocontext' && ev.key === key && typeof ev.top === 'string' && ev.top) { top = ev.top; break; }
    }
  }
  return top && path.isAbsolute(top) && fs.existsSync(top) ? top : '';
}

// The schedules and triggers of the sysop (automations.py): the live ones, and the ones that ended in the last 6 hours (newest first)
export function readAutomations(stateSysop, nowSec = Date.now() / 1000) {
  const d = readJsonSafe(path.join(stateSysop, 'automations.json'));
  const items = d && Array.isArray(d.items) ? d.items : [];
  const out = [];
  for (const x of items) {
    if (!x || typeof x !== 'object' || !/^a\d{1,6}$/.test(String(x.id || ''))) continue;
    const st = ['active', 'paused', 'ended'].includes(x.state) ? x.state : 'ended';
    if (st === 'ended' && nowSec - Number(x.ended || 0) > 6 * 3600) continue;
    out.push({
      id: String(x.id),
      kind: x.kind === 'trigger' ? 'trigger' : 'schedule',
      state: st,
      desc: String(x.desc || ''),
      prompt: String(x.prompt || '').slice(0, 600),
      runs: Number(x.runs || 0),
      next: Number(x.next || 0) * 1000,
      last: Number(x.last || 0) * 1000,
      expires: Number(x.expires || 0) * 1000,
      tab: String(x.tab || ''),
      why: String(x.why || ''),
      ended: Number(x.ended || 0) * 1000,
    });
  }
  const rank = { active: 0, paused: 1, ended: 2 };
  return out.sort((a, b) => rank[a.state] - rank[b.state] || b.ended - a.ended || a.id.localeCompare(b.id)).slice(0, 30);
}

export function readSysopSnapshot(terminals) {
  const runSysop = path.join(SB_RUN_DIR, 'sysop');
  const stateSysop = path.join(SB_STATE_DIR, 'sysop');
  const status = readJsonSafe(path.join(runSysop, 'status.json'));
  const pid = status && typeof status.pid === 'number' ? status.pid : null;
  const up = Boolean(status && isPidAlive(pid));

  const cur = up ? sanitizeGoalId(status.current) : '';
  if (cur) lastSysopGid = cur;
  const gid = cur || lastSysopGid;

  let goal = null;
  let pending = null;
  let question = null;
  const steps = [];
  const turns = [];
  const nowSec = Date.now() / 1000;
  const maxAgeSec = 12 * 3600;
  const sinceSec = readConversationSince();

  if (up) {
    const goalsRoot = path.join(stateSysop, 'goals');
    let dirs = [];
    try {
      dirs = fs.readdirSync(goalsRoot).map(sanitizeGoalId).filter(Boolean);
    } catch (_) {}
    if (gid && !dirs.includes(gid)) dirs.push(gid);

    const loaded = [];
    for (const id of dirs) {
      const gdir = path.join(goalsRoot, id);
      const g = readJsonSafe(path.join(gdir, 'state.json'));
      if (!g || typeof g !== 'object') continue;
      const isCurrent = id === cur;
      const stamp = Number(g.ended || g.started || g.created || 0);
      if (!isCurrent && stamp > 0 && (nowSec - stamp) > maxAgeSec) continue;
      if (!isCurrent && sinceSec && Number(g.created || g.started || 0) < sinceSec) continue;
      loaded.push({ id, gdir, g, isCurrent, sortTs: Number(g.started || g.created || 0) });
    }
    loaded.sort((a, b) => a.sortTs - b.sortTs || a.id.localeCompare(b.id));
    for (const item of loaded.slice(-15)) {
      const turn = buildGoalTurn(item.gdir, item.id, item.g, item.isCurrent);
      if (turn.prompt || turn.reply || turn.notes.length || turn.running) {
        turns.push(turn);
      }
      if (item.id === gid) {
        goal = item.g;
        if (turn.running) {
          const p = readJsonSafe(path.join(item.gdir, 'pending_action.json'));
          if (p && typeof p === 'object' && p.id) pending = p;
          // an `ask` of the brain (mcpserver.t_ask): the question and its options, until it is answered or its time ends
          const q = readJsonSafe(path.join(item.gdir, 'pending_question.json'));
          if (q && typeof q === 'object' && q.id && Number(q.deadline || 0) > nowSec) question = q;
        }
        // Keep legacy flat steps[] populated for Terminal Cockpit compatibility
        if (turn.prompt) steps.push({ ts: turn.started, kind: 'goal', text: turn.prompt });
        for (const a of turn.actions) steps.push({ ts: a.ts, kind: a.ok ? 'info' : 'err', text: a.label });
        for (const n of turn.notes) steps.push({ ts: turn.started, kind: 'ok', text: n });
        if (turn.reply) {
          steps.push({
            ts: turn.ended || Date.now(),
            kind: turn.state === 'done' ? 'ok' : turn.state === 'stopped' ? 'warn' : 'err',
            text: turn.reply,
          });
        }
      }
    }
  }

  const queue = up && Array.isArray(status.queue) ? status.queue : [];
  let state = 'off';
  let sentence = '';

  if (up) {
    if (pending) {
      state = pending.mode === 'veto' ? 'sending' : 'allow?';
      sentence = String(pending.text || 'an action').slice(0, 160);
    } else if (goal) {
      const gs = goal.state;
      if (TERMINAL_STATES.has(gs)) {
        if (typeof goal.ended === 'number' && nowSec - goal.ended > SYSOP_SHOW_END_MS / 1000) {
          state = 'idle';
          sentence = '';
        } else {
          state = gs;
          sentence = String(goal.summary || goal.error || gs).slice(0, 160);
        }
      } else if (gs === 'queued') {
        state = 'queued';
        sentence = String(goal.text || '').slice(0, 160);
      } else if (gs === 'waiting_approval') {
        state = 'allow?';
        sentence = String(goal.text || '').slice(0, 160);
      } else {
        state = 'working';
        const curTurn = turns.length ? turns[turns.length - 1] : null;
        sentence = String((curTurn && curTurn.live_action) || goal.text || '').slice(0, 160);
      }
    } else if (queue.length) {
      state = 'queued';
      sentence = `${queue.length} queued`;
    } else {
      state = 'idle';
      sentence = '';
    }
  }

  // Also surface live OSC 7501 blocked terminals from herdr-core (e.g. direct agent permission dialogs)
  const blocked = (terminals || [])
    .filter((t) => !isHiddenTerminal(t) && t.status && t.status.state === 'blocked')
    .map((t) => ({
      terminal: t.address,
      name: t.name || t.address,
      msg: t.status.msg || 'Program is waiting for input',
      kind: t.status.kind || 'permission',
    }));

  // System events (automatic tab renames, repository digests by Sysop) shown inline in the visual feed
  // without consuming the 8-goal user conversation memory window in history.py.
  const systemEvents = [];
  const allEvents = [];
  if (up) {
    const rawEv = readJsonlSafe(path.join(stateSysop, 'system_events.jsonl'), 200);
    for (const ev of rawEv) {
      const ts = Number(ev && ev.ts ? ev.ts : 0);
      if (ts > 0 && (nowSec - ts) > maxAgeSec) continue;
      if (ev && ev.kind) {
        const row = {
          id: String(ev.id || `ev-${Math.round(ts * 1000)}`),
          kind: String(ev.kind),
          ts: ts * 1000,
          tab: String(ev.tab || ''),
          agent: String(ev.agent || ''),
          old_title: String(ev.old_title || ''),
          new_title: String(ev.new_title || ''),
          text: String(ev.text || ''),
          // autocontext (the repository digest): started, then made or failed
          phase: String(ev.phase || ''),
          repo: String(ev.repo || ''),
          key: String(ev.key || ''),
          commit: String(ev.commit || ''),
          took: Number.isFinite(Number(ev.took)) ? Number(ev.took) : null,
          error: String(ev.error || ''),
          retry_min: Number.isFinite(Number(ev.retry_min)) ? Number(ev.retry_min) : null,
          reason: String(ev.reason || ''),
          // session: an agent session started in a repository, with the orientation or without it
          context: Boolean(ev.context),
          base: String(ev.base || ''),
          base_at: Number.isFinite(Number(ev.base_at)) ? Number(ev.base_at) * 1000 : 0,
          changes: Number.isFinite(Number(ev.changes)) ? Number(ev.changes) : 0,
          writing: Boolean(ev.writing),
          skipped: Boolean(ev.skipped),
          off: Boolean(ev.off),
          failed: Boolean(ev.failed),
          // notify (a message of the brain for the user) and automation (a schedule or a trigger fired, was skipped or ended)
          level: String(ev.level || ''),
          auto: String(ev.auto || ''),
          why: String(ev.why || ''),
        };
        allEvents.push(row);
        if (!(sinceSec && ts > 0 && ts < sinceSec)) systemEvents.push(row);
      }
    }
  }

  return {
    up,
    bus: up ? String(status.bus || '') : '',
    state,
    sentence,
    goal_id: gid,
    pending: pending
      ? {
          id: String(pending.id),
          mode: pending.mode === 'veto' ? 'veto' : 'approve',
          risk: String(pending.risk || ''),
          tab: String(pending.tab || ''),
          text: String(pending.text || ''),
          deadline: typeof pending.deadline === 'number' ? pending.deadline : null,
          reasons: Array.isArray(pending.reasons) ? pending.reasons : [],
        }
      : null,
    queue_len: queue.length,
    question: question
      ? {
          id: String(question.id),
          goal: String(question.goal || gid),
          question: String(question.question || ''),
          options: Array.isArray(question.options) ? question.options.map((o) => String(o)).slice(0, 4) : [],
          deadline: Number(question.deadline || 0),
        }
      : null,
    automations: up ? readAutomations(stateSysop, nowSec) : [],
    turns,
    system_events: systemEvents.slice(-30),
    // the Events tab: what the sysop did by itself, not cut by New conversation (session records are for the cards)
    events: allEvents.filter((e) => !(e.kind === 'autocontext' && e.phase === 'session')).slice(-40),
    context: up ? readContextState(stateSysop, terminals, status) : null,
    steps: steps.slice(-40),
    blocked,
    settings: up && status.settings && typeof status.settings === 'object' ? status.settings : {},
  };
}

export function runCommand(bin, args, stdinText = null, timeoutMs = 15000) {
  return runCommandEnv(bin, args, process.env, timeoutMs, stdinText);
}

export function runCommandEnv(bin, args, env, timeoutMs = 15000, stdinText = null) {
  return new Promise((resolve) => {
    const p = spawn(bin, args, {
      stdio: ['pipe', 'pipe', 'pipe'],
      env,
    });
    let out = '';
    let err = '';
    let settled = false;
    const timer = setTimeout(() => {
      if (!settled) {
        settled = true;
        try { p.kill('SIGTERM'); } catch (_) {}
        resolve({ ok: false, code: 124, stdout: out, stderr: 'command timed out' });
      }
    }, timeoutMs);

    p.stdout.on('data', (c) => { out += c.toString(); });
    p.stderr.on('data', (c) => { err += c.toString(); });
    p.on('error', (e) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      resolve({ ok: false, code: 127, stdout: out, stderr: e.message });
    });
    p.on('close', (code) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      resolve({ ok: code === 0, code: code ?? 1, stdout: out.trim(), stderr: err.trim() });
    });
    if (stdinText !== null) {
      p.stdin.write(stdinText);
    }
    p.stdin.end();
  });
}
