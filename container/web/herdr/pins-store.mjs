// Persistent Pinned Sessions (pins.json), Worktree Prefs, Session Prefs,
// Recent Dirs, agent/title/cwd helpers & tab.events Bus.

import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import crypto from 'node:crypto';
import { fileURLToPath } from 'node:url';
import { spawn } from 'node:child_process';
import {
  buildAgentArgv as registryBuildAgentArgv,
  defaultAgent,
  detectAgent,
  listAgents,
  resolveAgent,
} from './agents.mjs';
import { readJsonSafe, runCommand } from './sysop-store.mjs';

const __clientDir = path.dirname(fileURLToPath(import.meta.url));
const HOME = process.env.HOME || os.homedir() || '/home/agent';

function resolveXdg(xdgVar, fallback, sub) {
  const base = typeof xdgVar === 'string' && xdgVar.startsWith('/') ? xdgVar.replace(/\/+$/, '') : fallback;
  return path.join(base, sub);
}

const SB_STATE_DIR = resolveXdg(process.env.XDG_STATE_HOME, path.join(HOME, '.local', 'state'), 'swarmbox');
const SB_CONFIG_DIR = resolveXdg(process.env.XDG_CONFIG_HOME, path.join(HOME, '.config'), 'swarmbox');
const BUS_BIN = process.env.SWARMBOX_TEST_BUS_BIN || 'swarmbox-bus';
const WORKTREE_BIN = process.env.SWARMBOX_TEST_WORKTREE_BIN || '';

export const PINS_FILE = path.join(SB_CONFIG_DIR, 'pins.json');
export const SESSION_PREFS_FILE = path.join(SB_CONFIG_DIR, 'session-prefs.json');
export const WORKTREE_PREFS_FILE = path.join(SB_CONFIG_DIR, 'worktree-prefs.json');

// The agent id of a name: an agent command, or another name of it (the OSC 7501 app it reports, its addon name). '' for anything
// else, `yolo` included: yolo is the shell function that runs the default agent, not an agent. The registry (agents.mjs) answers.
export function normalizeAgentName(raw) {
  return resolveAgent(raw);
}

// The default agent of the box: AGENT if it names an agent, else the first agent of WITH, else the first installed agent, else ''.
// The same answer for every place that starts or offers the default agent: New agent, worktree open, the cockpit, the launcher.
export function resolveDefaultAgent(env = process.env) {
  return defaultAgent(env);
}

export function cleanSessionTitle(raw) {
  return String(raw || '')
    .replace(/[\x00-\x1f\x7f]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
    .slice(0, 60);
}

export function defaultTitleForPath(cwd, agent = 'shell') {
  const clean = String(cwd || '').replace(/\/+$/, '');
  const home = HOME.replace(/\/+$/, '');
  if (clean && clean !== '/' && clean !== home) {
    const base = path.basename(clean);
    if (base) return cleanSessionTitle(base);
  }
  return agent && agent !== 'shell' ? agent : 'shell';
}

export function terminalCwd(term) {
  const c = (term && term.foreground && term.foreground.cwd) || (term && term.cwd) || HOME;
  return typeof c === 'string' && c.startsWith('/') ? c : HOME;
}

// The agent a terminal runs, by the registry's one detection order: OSC 7501 app, foreground process, then the swarmbox.agent label
// while the terminal is not a bare login shell. Never the tab name.
export function detectTerminalAgent(term) {
  return detectAgent(term);
}

// The agent a terminal is running right now, from live signals only (OSC 7501 status or the foreground
// process). Unlike detectTerminalAgent it ignores labels, so a plain shell tab still carrying an old
// `swarmbox.agent` label is not mistaken for a running agent.
export function detectLiveAgent(term) {
  return detectAgent(term, { live: true });
}

// Folders recently used to launch a tab from the Web Studio, newest first (state, not config).
export const RECENT_DIRS_FILE = path.join(SB_STATE_DIR, 'recent-dirs.json');
const RECENT_DIRS_MAX = 12;

export function readRecentDirs() {
  const d = readJsonSafe(RECENT_DIRS_FILE);
  if (!d || !Array.isArray(d.dirs)) return [];
  return d.dirs.filter((x) => x && typeof x.path === 'string' && x.path.startsWith('/'));
}

export function noteRecentDir(dir) {
  if (typeof dir !== 'string' || !dir.startsWith('/')) return;
  const clean = dir.replace(/\/+$/, '') || '/';
  try {
    const dirs = [{ path: clean, ts: Math.floor(Date.now() / 1000) }]
      .concat(readRecentDirs().filter((x) => x.path !== clean))
      .slice(0, RECENT_DIRS_MAX);
    fs.mkdirSync(SB_STATE_DIR, { recursive: true, mode: 0o700 });
    const tmp = `${RECENT_DIRS_FILE}.tmp.${process.pid}.${crypto.randomBytes(2).toString('hex')}`;
    fs.writeFileSync(tmp, JSON.stringify({ dirs }, null, 2) + '\n', { mode: 0o600 });
    fs.renameSync(tmp, RECENT_DIRS_FILE);
  } catch (_) {}
}

// The argv of a terminal that runs `agent` (shell, yolo or an agent): the registry's, the twin of build_argv in swarmbox_agents.py.
export function buildAgentArgv(agent, resume = 'continue', env = process.env, opts = {}) {
  return registryBuildAgentArgv(agent, resume, env, opts);
}

export function readPins() {
  const d = readJsonSafe(PINS_FILE);
  if (!d || !Array.isArray(d.pins)) return [];
  return d.pins.filter((p) => p && typeof p === 'object' && typeof p.id === 'string' && p.id);
}

export function writePins(pins) {
  fs.mkdirSync(SB_CONFIG_DIR, { recursive: true, mode: 0o700 });
  const tmp = `${PINS_FILE}.tmp.${process.pid}.${crypto.randomBytes(2).toString('hex')}`;
  fs.writeFileSync(tmp, JSON.stringify({ schema: 1, pins }, null, 2) + '\n', { mode: 0o600 });
  fs.renameSync(tmp, PINS_FILE);
  return pins;
}

export function makePinId(existing = []) {
  const used = new Set(existing.map((p) => p && p.id));
  for (let i = 0; i < 32; i++) {
    const id = 'p_' + crypto.randomBytes(3).toString('hex');
    if (!used.has(id)) return id;
  }
  return 'p_' + Date.now().toString(36);
}

// Live auto-follow: keep pinned tabs' cwd, active agent (never downgrading an agent pin to shell),
// title, and worktree metadata synchronized in pins.json whenever they change.
export function syncPinsFromTerminals(terminals) {
  if (!Array.isArray(terminals) || terminals.length === 0) return false;
  const pins = readPins();
  if (pins.length === 0) return false;
  const byPinId = new Map();
  for (const t of terminals) {
    const pid = t && t.labels && t.labels['swarmbox.pin_id'];
    if (pid) byPinId.set(String(pid), t);
  }
  let changed = false;
  const nowSec = Math.floor(Date.now() / 1000);
  for (const pin of pins) {
    const t = byPinId.get(pin.id);
    if (!t) continue;
    const cwd = terminalCwd(t);
    if (cwd && cwd !== pin.cwd && fs.existsSync(cwd)) {
      pin.cwd = cwd;
      pin.updated_at = nowSec;
      changed = true;
    }
    // Upgrade or switch agent when a known agent is active; never downgrade an agent pin to shell on temporary exit
    const liveAgent = detectTerminalAgent(t);
    if (liveAgent && liveAgent !== pin.agent) {
      pin.agent = liveAgent;
      pin.updated_at = nowSec;
      changed = true;
    }
    const lblTitle = cleanSessionTitle(t.labels && t.labels['swarmbox.title']);
    const lblSrc = String((t.labels && t.labels['swarmbox.title_source']) || '');
    if (lblTitle && lblTitle !== pin.title) {
      pin.title = lblTitle;
      if (lblSrc === 'user' || lblSrc === 'auto') pin.title_source = lblSrc;
      pin.updated_at = nowSec;
      changed = true;
    } else if ((lblSrc === 'user' || lblSrc === 'auto') && lblSrc !== pin.title_source) {
      pin.title_source = lblSrc;
      pin.updated_at = nowSec;
      changed = true;
    }
    const wtPath = t.labels && t.labels['swarmbox.worktree'];
    if (wtPath && (!pin.worktree || pin.worktree.path !== wtPath)) {
      pin.worktree = {
        path: String(wtPath),
        branch: String((t.labels && t.labels['swarmbox.branch']) || ''),
        base: String((t.labels && t.labels['swarmbox.base']) || ''),
        repo: String((t.labels && t.labels['swarmbox.repo']) || ''),
      };
      pin.updated_at = nowSec;
      changed = true;
    }
  }
  if (changed) {
    try { writePins(pins); } catch (_) {}
  }
  return changed;
}

export function buildPinsSnapshot(terminals) {
  const pins = readPins();
  const liveByPin = new Map();
  for (const t of terminals || []) {
    const pid = t && t.labels && t.labels['swarmbox.pin_id'];
    if (pid) liveByPin.set(String(pid), t);
  }
  const kept = [];
  const snap = [];
  let pruned = false;
  for (const p of pins) {
    const liveTerm = liveByPin.get(p.id) || null;
    const cwd = String(p.cwd || '');
    let missingCwd = false;
    try { missingCwd = !cwd || !fs.existsSync(cwd); } catch (_) { missingCwd = true; }
    // Drop orphaned automatic worktree pins once the worktree directory is gone and no live tab uses it.
    if (!liveTerm && missingCwd && p.auto && p.worktree && p.worktree.path) {
      pruned = true;
      continue;
    }
    kept.push(p);
    snap.push({
      ...p,
      live: Boolean(liveTerm),
      parked: !liveTerm,
      live_address: liveTerm ? liveTerm.address : null,
      missing_cwd: missingCwd,
    });
  }
  if (pruned) {
    try { writePins(kept); } catch (_) {}
  }
  return snap;
}

// The agents offered by the Web Studio (launcher, settings): the installed agents and those of WITH (installed at startup), the default
// agent first and marked; with no default agent, the first one is marked.
export function listInstalledAgents(env = process.env) {
  const withIds = new Set(String(env.SWARMBOX_WITH || '').replace(/,/g, ' ').split(/\s+/).filter(Boolean).map((t) => resolveAgent(t, env)));
  const def = defaultAgent(env);
  const found = listAgents(env)
    .filter((a) => a.installed || withIds.has(a.id))
    .map((a) => ({ id: a.id, name: a.label, default: a.id === def }));
  found.sort((a, b) => (a.default === b.default ? 0 : a.default ? -1 : 1));
  if (found.length > 0 && !found.some((x) => x.default)) found[0].default = true;
  return found;
}

const VALID_BOOT_MODES = new Set(['autostart', 'parked']);

export function readSessionPrefs() {
  const d = readJsonSafe(SESSION_PREFS_FILE);
  return {
    boot_mode: d && VALID_BOOT_MODES.has(d.boot_mode) ? d.boot_mode : 'autostart',
  };
}

export function writeSessionPrefs(patch = {}) {
  const cur = readSessionPrefs();
  if (patch.boot_mode !== undefined) {
    if (!VALID_BOOT_MODES.has(patch.boot_mode)) throw new Error('boot_mode must be autostart or parked');
    cur.boot_mode = patch.boot_mode;
  }
  fs.mkdirSync(SB_CONFIG_DIR, { recursive: true, mode: 0o700 });
  const tmp = `${SESSION_PREFS_FILE}.tmp.${process.pid}`;
  fs.writeFileSync(tmp, JSON.stringify(cur, null, 2) + '\n', { mode: 0o600 });
  fs.renameSync(tmp, SESSION_PREFS_FILE);
  // Sync autostart flag across all persisted sessions so boot restoration matches the global setting
  const pins = readPins();
  const wantAuto = cur.boot_mode === 'autostart';
  let changed = false;
  for (const p of pins) {
    if (Boolean(p.autostart) !== wantAuto) {
      p.autostart = wantAuto;
      changed = true;
    }
  }
  if (changed) writePins(pins);
  return cur;
}

const VALID_WT_MODES = new Set(['ask', 'auto', 'off']);

export function readWorktreePrefs() {
  const d = readJsonSafe(WORKTREE_PREFS_FILE);
  return {
    mode: d && VALID_WT_MODES.has(d.mode) ? d.mode : 'ask',
    copy_env: d && typeof d.copy_env === 'boolean' ? d.copy_env : true,
  };
}

export function writeWorktreePrefs(patch = {}) {
  const cur = readWorktreePrefs();
  if (patch.mode !== undefined) {
    if (!VALID_WT_MODES.has(patch.mode)) throw new Error('mode must be ask, auto, or off');
    cur.mode = patch.mode;
  }
  if (patch.copy_env !== undefined) {
    cur.copy_env = Boolean(patch.copy_env);
  }
  fs.mkdirSync(SB_CONFIG_DIR, { recursive: true, mode: 0o700 });
  const tmp = `${WORKTREE_PREFS_FILE}.tmp.${process.pid}`;
  fs.writeFileSync(tmp, JSON.stringify(cur, null, 2) + '\n', { mode: 0o600 });
  fs.renameSync(tmp, WORKTREE_PREFS_FILE);
  return cur;
}

function resolveWorktreeCommand() {
  if (WORKTREE_BIN) return [WORKTREE_BIN, []];
  const sibling = path.resolve(__clientDir, '..', '..', 'scripts', 'swarmbox-worktree.py');
  if (fs.existsSync(sibling)) return ['python3', [sibling]];
  return ['swarmbox-worktree', []];
}

export async function runWorktreeCmd(args, timeoutMs = 20000) {
  const [bin, prefix] = resolveWorktreeCommand();
  const r = await runCommand(bin, [...prefix, ...args], null, timeoutMs);
  let data = null;
  if (r.stdout) {
    try { data = JSON.parse(r.stdout); } catch (_) {}
  }
  if (!r.ok) {
    const err = new Error((data && data.msg) || r.stderr || r.stdout || `worktree ${args[0] || ''} failed`);
    err.code = (data && data.err) || 'worktree_error';
    err.data = data || {};
    throw err;
  }
  return data;
}

export function publishTabEvent(payload) {
  if (!payload || typeof payload !== 'object') return;
  try {
    const p = spawn(BUS_BIN, ['pub', '--allow-none', '--source', 'gateway', 'tab.events', '-'], {
      stdio: ['pipe', 'ignore', 'ignore'],
      env: process.env,
    });
    p.on('error', () => {});
    p.stdin.on('error', () => {});
    p.stdin.end(JSON.stringify(payload) + '\n');
  } catch (_) {}
}
