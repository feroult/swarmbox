// agents.mjs: the agent registry of SwarmBox for Node (the gateway server.mjs, hc-client.mjs, the cockpit). The twin of
// container/scripts/swarmbox_agents.py: the same reading of the same files, checked against the same vectors
// (tests/support/fixtures/agents/cases.json). An addon is a coding agent if and only if it has agent/agent.conf
// (docs/agents-design.md 3.2); this module is the only place in Node that knows which programs are agents.
//
// The format of agent.conf, the two addon levels and what "installed" means are described in swarmbox_agents.py.

import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));

export const SCHEMA = 1;
export const PSEUDO_AGENTS = new Set(['shell', 'yolo']);
// The names of a plain shell process (the foreground of a tab that runs no program): one list for every reader.
export const SHELL_NAMES = new Set(['bash', 'sh', 'zsh', 'dash', 'fish', 'ash', 'ksh', 'nu', 'nushell', 'busybox', 'login',
  '-bash', '-sh', '-zsh', '-dash', '-fish', '-ksh']);

const ID_RE = /^[a-z0-9][a-z0-9_-]*$/;
const KEY_RE = /^[A-Z][A-Z0-9_]*$/;
const BAD_VALUE_RE = /["$\\`]/;

export const TERM_DEFAULTS = Object.freeze({
  resize_quiet_ms: 900, resize_cap_ms: 3500, resize_client_fallback_ms: 4200,
  hydrate_gap_ms: 60, hydrate_min_bytes: 256, hydrate_flush_ms: 460, hydrate_cap_ms: 1400,
  late_redraw_ms: 2500, settle_ms: 650,
  copy_prompt_glyphs: '❯', copy_gutter_glyphs: '│┃║▕▎▏', image_paste: 'path',
});
const TERM_INT_KEYS = ['resize_quiet_ms', 'resize_cap_ms', 'resize_client_fallback_ms', 'hydrate_gap_ms', 'hydrate_min_bytes',
  'hydrate_flush_ms', 'hydrate_cap_ms', 'late_redraw_ms', 'settle_ms'];
const HOOKS = { screen: 'screen.py', history: 'history.py', shell: 'shell.sh', mcp: 'mcp.sh', statusline: 'statusline.sh',
  terminal: 'terminal.mjs', icon: 'icon.svg', settings: 'settings.json' };

// parseConf(text) -> { values, problems }: the KEY=value pairs of an agent.conf text (same rules as parse_conf in Python).
export function parseConf(text) {
  const values = {};
  const problems = [];
  String(text || '').split('\n').forEach((raw, i) => {
    const line = raw.trim();
    if (!line || line.startsWith('#')) return;
    const eq = line.indexOf('=');
    const k = eq > 0 ? line.slice(0, eq) : '';
    if (!k || !KEY_RE.test(k)) { problems.push(`line ${i + 1} is not KEY=value`); return; }
    let v = line.slice(eq + 1);
    if (v.length >= 2 && v[0] === '"' && v[v.length - 1] === '"') v = v.slice(1, -1);
    if (BAD_VALUE_RE.test(v)) { problems.push(`line ${i + 1} (${k}): a value has no quotes inside, no $, no backslash and no backtick`); return; }
    values[k] = v.trim();
  });
  return { values, problems };
}

function xdg(v, fallback) {
  const base = typeof v === 'string' && v.startsWith('/') ? v : fallback;
  return path.join(base.replace(/\/+$/, '') || '/', 'swarmbox');
}

function homeOf(env) {
  return env.HOME || os.homedir() || '/home/agent';
}

export function imageAddonsDir(env = process.env) {
  if (env.SWARMBOX_TEST_IMAGE_ADDONS) return env.SWARMBOX_TEST_IMAGE_ADDONS;
  if (env.SWARMBOX_IMAGE_ADDONS_DIR) return env.SWARMBOX_IMAGE_ADDONS_DIR;
  const repo = path.resolve(HERE, '..', '..', 'addons');
  try { if (fs.statSync(repo).isDirectory()) return repo; } catch (_) {}
  return '/usr/local/lib/swarmbox/addons';
}

export function userAddonsDir(env = process.env) {
  if (env.SWARMBOX_TEST_USER_ADDONS) return env.SWARMBOX_TEST_USER_ADDONS;
  return path.join(xdg(env.XDG_CONFIG_HOME, path.join(homeOf(env), '.config')), 'addons');
}

function readText(p) {
  try { return fs.readFileSync(p, 'utf8'); } catch (_) { return null; }
}

function addonConf(dir) {
  const txt = readText(path.join(dir, 'addon.conf'));
  if (txt === null) return null;
  const out = {};
  for (const raw of txt.split('\n')) {
    const ln = raw.trim();
    if (!ln || ln.startsWith('#')) continue;
    const eq = ln.indexOf('=');
    if (eq <= 0) continue;
    let v = ln.slice(eq + 1).trim();
    if (v.length >= 2 && v[0] === v[v.length - 1] && (v[0] === '"' || v[0] === "'")) v = v.slice(1, -1);
    out[ln.slice(0, eq).trim()] = v;
  }
  return out.NAME ? out : null;
}

function isFile(p) {
  try { return fs.statSync(p).isFile(); } catch (_) { return false; }
}

function installed(addon, conf, cmd, env) {
  const home = homeOf(env);
  const data = xdg(env.XDG_DATA_HOME, path.join(home, '.local', 'share'));
  const imageState = env.SWARMBOX_TEST_IMAGE_STATE || '/opt/swarmbox/addons';
  const self = conf.UPDATE === 'self';
  for (const root of [path.join(data, 'addons'), imageState]) {
    if (isFile(path.join(root, addon, self ? 'self' : 'current', '.swarmbox-env'))) return true;
  }
  if (self) {
    const p = path.join(home, '.local', 'bin', cmd);
    try { fs.accessSync(p, fs.constants.X_OK); return isFile(p); } catch (_) { return false; }
  }
  return false;
}

const words = (v) => (v ? String(v).split(/\s+/).filter(Boolean) : []);
const int = (v, d) => (/^[0-9]+$/.test(String(v || '')) ? parseInt(v, 10) : d);

function agentFrom(dir, level, conf, values, env) {
  const adir = path.join(dir, 'agent');
  const id = values.ID || '';
  const cmd = values.CMD || id;
  const aliases = [];
  for (let w of [conf.NAME, cmd, ...words(values.ALIASES)]) {
    w = String(w).toLowerCase();
    if (w !== id && !aliases.includes(w)) aliases.push(w);
  }
  const term = { ...TERM_DEFAULTS };
  for (const k of TERM_INT_KEYS) {
    const v = values[`TERM_${k.toUpperCase()}`];
    if (v) term[k] = int(v, term[k]);
  }
  for (const k of ['copy_prompt_glyphs', 'copy_gutter_glyphs', 'image_paste']) {
    const v = values[`TERM_${k.toUpperCase()}`];
    if (v) term[k] = v;
  }
  const hooks = {};
  for (const [h, f] of Object.entries(HOOKS)) hooks[h] = isFile(path.join(adir, f));
  hooks.shell = hooks.shell || isFile(path.join(dir, 'shell.sh'));
  return {
    id,
    cmd,
    label: values.LABEL || id,
    aliases,
    color: values.COLOR || '',
    addon: conf.NAME,
    level,
    dir: adir,
    installed: installed(conf.NAME, conf, cmd, env),
    yolo_args: words(values.YOLO_ARGS),
    mcp_args: words(values.MCP_ARGS),
    passthrough: words(values.PASSTHROUGH),
    print_flags: words(values.PRINT_FLAGS),
    resume: { args: words(values.RESUME_ARGS), fast_fail_s: int(values.RESUME_FAST_FAIL_S, 4), scope: values.RESUME_SCOPE || 'cwd' },
    status: values.STATUS || 'osc7501',
    reserved_prefixes: 'RESERVED_PREFIXES' in values ? words(values.RESERVED_PREFIXES) : ['/', '!'],
    answer: { allow: values.ANSWER_ALLOW || '', deny: values.ANSWER_DENY || '' },
    history: values.HISTORY || '',
    namer: values.NAMER || '',
    brain: values.BRAIN || '',
    login_hint: values.LOGIN_HINT || '',
    model: values.MODEL || '',
    secrets: { env: words(values.SECRET_ENV), files: words(values.SECRET_FILES) },
    term,
    hooks,
  };
}

function stampOf(dirs) {
  const parts = [];
  for (const d of dirs) {
    let names = [];
    try { names = fs.readdirSync(d).sort(); } catch (_) { continue; }
    for (const n of names) {
      for (const rel of ['addon.conf', 'agent', path.join('agent', 'agent.conf'), 'shell.sh']) {
        try {
          const st = fs.statSync(path.join(d, n, rel));
          parts.push(`${d}|${n}|${rel}|${st.mtimeMs}|${st.size}`);
        } catch (_) {}
      }
    }
  }
  return parts.join('\n');
}

const CACHE = new Map();

// loadRegistry(env) -> { agents: [...] (sorted by id), byName: Map(name -> id) }. Cached while no manifest changes.
export function loadRegistry(env = process.env) {
  const levels = [['image', imageAddonsDir(env)], ['user', userAddonsDir(env)]];
  const key = [...levels.map((l) => l[1]), env.HOME || '', env.XDG_DATA_HOME || '', env.XDG_CONFIG_HOME || ''].join('\0');
  const stamp = stampOf(levels.map((l) => l[1]));
  const hit = CACHE.get(key);
  if (hit && hit.stamp === stamp && Date.now() - hit.at < 5000) return hit.reg;
  const found = new Map();
  for (const [level, root] of levels) {
    let names = [];
    try { names = fs.readdirSync(root).sort(); } catch (_) { continue; }
    for (const n of names) {
      const d = path.join(root, n);
      const conf = addonConf(d);
      if (!conf) continue;
      const txt = readText(path.join(d, 'agent', 'agent.conf'));
      if (txt === null) { found.delete(conf.NAME); continue; }
      const { values } = parseConf(txt);
      if (!ID_RE.test(values.ID || '') || PSEUDO_AGENTS.has(values.ID) || values.ID === 'sysop') continue;
      found.set(conf.NAME, agentFrom(d, level, conf, values, env));
    }
  }
  const agents = Array.from(found.values()).sort((a, b) => (a.id < b.id ? -1 : a.id > b.id ? 1 : 0));
  const byName = new Map();
  for (const a of agents) if (!byName.has(a.id)) byName.set(a.id, a.id);
  for (const a of agents) for (const al of a.aliases) if (!byName.has(al)) byName.set(al, a.id);
  const reg = { agents, byName };
  CACHE.set(key, { stamp, reg, at: Date.now() });
  return reg;
}

export function listAgents(env = process.env, { installedOnly = false } = {}) {
  return loadRegistry(env).agents.filter((a) => a.installed || !installedOnly);
}

export function getAgent(id, env = process.env) {
  return loadRegistry(env).agents.find((a) => a.id === id) || null;
}

// resolveAgent(name) -> the agent id of a name (an id, a command, an alias), or ''. A path is reduced to its last part and a login
// shell's leading '-' is dropped. Pseudo-agents (shell, yolo) give ''.
export function resolveAgent(name, env = process.env) {
  const n = path.basename(String(name || '').trim()).toLowerCase().replace(/^-+/, '');
  if (!n) return '';
  return loadRegistry(env).byName.get(n) || '';
}

export function isAgent(name, env = process.env) {
  return Boolean(resolveAgent(name, env));
}

// The default agent of the box: AGENT if it names an agent, else the first WITH entry that is an agent, else the first installed agent.
export function defaultAgent(env = process.env) {
  const a = resolveAgent(env.SWARMBOX_AGENT, env);
  if (a) return a;
  for (const tok of String(env.SWARMBOX_WITH || '').replace(/,/g, ' ').split(/\s+/).filter(Boolean)) {
    const b = resolveAgent(tok, env);
    if (b) return b;
  }
  const inst = listAgents(env, { installedOnly: true });
  return inst.length ? inst[0].id : '';
}

function bareShell(argv, fg) {
  const list = Array.isArray(argv) ? argv : [];
  const f = path.basename(String(fg || '')).toLowerCase();
  return list.length <= 2 && (!f || SHELL_NAMES.has(f));
}

// detectAgent(term, { live }) -> the agent a terminal runs: OSC 7501 app, then the foreground process, then (not when live) the
// swarmbox.agent label, trusted only when the terminal was not a bare login shell. Never the tab name.
export function detectAgent(term, { live = false } = {}, env = process.env) {
  if (!term || typeof term !== 'object') return '';
  const st = term.status;
  if (st && typeof st === 'object') {
    const a = resolveAgent(st.app, env);
    if (a) return a;
  }
  const fg = term.foreground && typeof term.foreground === 'object' ? term.foreground.name : term.cmd;
  const b = resolveAgent(fg, env);
  if (b || live) return b;
  const lbl = term.labels && typeof term.labels === 'object' ? term.labels['swarmbox.agent'] : term.agent;
  if (typeof lbl === 'string' && resolveAgent(lbl, env)) {
    if (!bareShell(term.argv, fg)) return resolveAgent(lbl, env);
  }
  return '';
}

export function resumeArgv(id, env = process.env) {
  const a = getAgent(id, env);
  return a ? [...a.resume.args] : [];
}

function shq(w) {
  return /^[A-Za-z0-9_./=:,+@%-]+$/.test(w) ? w : `'${String(w).replace(/'/g, "'\\''")}'`;
}

// launchScript(id, { resume }) -> the bash -lic script that starts agent `id` in a tab (same text as launch_script in Python).
export function launchScript(id, { resume = true } = {}, env = process.env) {
  const a = getAgent(id, env);
  if (!a) return 'exec /bin/bash -l';
  const cmd = shq(a.cmd);
  const rargs = a.resume.args.map(shq).join(' ');
  if (resume && rargs) {
    return `_sb_t0=$(date +%s); SWARMBOX_WORKTREE_GUARD=0 ${cmd} ${rargs}; _sb_rc=$?; ` +
      `if [ "$_sb_rc" -ne 0 ] && [ $(( $(date +%s) - _sb_t0 )) -lt ${a.resume.fast_fail_s} ]; then SWARMBOX_WORKTREE_GUARD=0 ${cmd}; fi; exec /bin/bash -l`;
  }
  return `SWARMBOX_WORKTREE_GUARD=0 ${cmd}; exec /bin/bash -l`;
}

// buildAgentArgv(agent, resume) -> the argv of a terminal that runs `agent` (same rules as build_argv in Python).
export function buildAgentArgv(agent, resume = 'continue', env = process.env) {
  const name = String(agent || 'shell').trim().toLowerCase();
  let id;
  if (name === 'yolo') {
    id = defaultAgent(env);
    if (!id) return ['/bin/bash', '-lic', 'SWARMBOX_WORKTREE_GUARD=0 yolo; exec /bin/bash -l'];
  } else {
    id = resolveAgent(name, env);
  }
  if (!id) return ['/bin/bash', '-l'];
  return ['/bin/bash', '-lic', launchScript(id, { resume: resume === 'continue' }, env)];
}

// publicAgent(a): an agent as the browser sees it (no file system paths).
export function publicAgent(a) {
  const { dir, ...rest } = a;
  return rest;
}

export function registryJson(env = process.env) {
  return { schema: SCHEMA, default: defaultAgent(env), agents: listAgents(env).map(publicAgent) };
}

// agentIconPath(id) -> the icon.svg of agent `id`, or '' when it has none.
export function agentIconPath(id, env = process.env) {
  const a = getAgent(id, env);
  return a && a.hooks.icon ? path.join(a.dir, 'icon.svg') : '';
}
