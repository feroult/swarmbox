// Live SwarmBox configuration, addons, MCP, SSH pubkey & health snapshot.

import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { execFileSync } from 'node:child_process';
import { THEME_ORDER, readSavedTheme } from './themes.mjs';
import { readSysopSnapshot } from './sysop-store.mjs';
import { listInstalledAgents, readSessionPrefs, readWorktreePrefs } from './pins-store.mjs';

const HOME = process.env.HOME || os.homedir() || '/home/agent';

function resolveXdg(xdgVar, fallback, sub) {
  const base = typeof xdgVar === 'string' && xdgVar.startsWith('/') ? xdgVar.replace(/\/+$/, '') : fallback;
  return path.join(base, sub);
}

const SB_STATE_DIR = resolveXdg(process.env.XDG_STATE_HOME, path.join(HOME, '.local', 'state'), 'swarmbox');
const SB_DATA_DIR = resolveXdg(process.env.XDG_DATA_HOME, path.join(HOME, '.local', 'share'), 'swarmbox');
const SB_CONFIG_DIR = resolveXdg(process.env.XDG_CONFIG_HOME, path.join(HOME, '.config'), 'swarmbox');

function readTextSafe(filePath) {
  try {
    return fs.readFileSync(filePath, 'utf8').trim();
  } catch (_) {
    return '';
  }
}

// readBuildCommit(): the commit the image was built from (/usr/local/share/swarmbox/COMMIT, written from the SWARMBOX_COMMIT build
// argument), or, with no such file (the gateway run from a checkout), `git rev-parse HEAD` of the folder this module is in, read once;
// '' when neither says. A sha with `-dirty` after it is a build from a checkout with uncommitted changes.
const COMMIT_FILE = '/usr/local/share/swarmbox/COMMIT';
let checkoutCommit = null;
export function readBuildCommit(file = COMMIT_FILE, srcDir = path.dirname(new URL(import.meta.url).pathname)) {
  const baked = readTextSafe(file);
  if (baked) return baked;
  if (checkoutCommit === null) {
    try {
      checkoutCommit = execFileSync('git', ['-C', srcDir, 'rev-parse', 'HEAD'], {
        encoding: 'utf8', timeout: 2000, stdio: ['ignore', 'pipe', 'ignore'],
      }).trim();
    } catch (_) {
      checkoutCommit = '';
    }
  }
  return checkoutCommit;
}

function parseAddonConf(filePath) {
  const txt = readTextSafe(filePath);
  if (!txt) return null;
  const out = {};
  for (const raw of txt.split('\n')) {
    const ln = raw.trim();
    if (!ln || ln.startsWith('#')) continue;
    const eq = ln.indexOf('=');
    if (eq <= 0) continue;
    const k = ln.slice(0, eq).trim();
    let v = ln.slice(eq + 1).trim();
    if ((v.startsWith('"') && v.endsWith('"')) || (v.startsWith("'") && v.endsWith("'"))) {
      v = v.slice(1, -1);
    }
    out[k] = v;
  }
  return out.NAME ? out : null;
}

// installedOf(dir, item): where the complete install of the addon in the state folder `dir` is, by the record swarmbox-addon writes
// last (its is_installed): `current/.swarmbox-env` for a managed addon, `self/.swarmbox-env` for one that updates itself (UPDATE=self,
// no `current` link). Answers { version: the link's target (a pinned version, or `latest`) or VERSION, cmd: the path of its first
// command (real_command_at) }, or null.
function installedOf(dir, item, home) {
  const base = path.join(dir, item.name);
  const first = item.commands[0];
  if (item.update === 'self') {
    if (!fs.existsSync(path.join(base, 'self', '.swarmbox-env'))) return null;
    const h = dir === home.baked ? path.join(base, 'home') : home.user;
    return { version: item.manifestVersion || 'latest', cmd: first ? path.join(h, '.local', 'bin', first) : '' };
  }
  if (!fs.existsSync(path.join(base, 'current', '.swarmbox-env'))) return null;
  let version = '';
  try { version = path.basename(fs.readlinkSync(path.join(base, 'current'))); } catch (_) {}
  return { version, cmd: first ? path.join(base, 'current', 'bin', first) : '' };
}

// reportedVersion(cmd): the version a floating install's program reports (`CMD --version`: the first thing on its standard output
// that looks like a version, `2.1.332 (Claude Code)` -> 2.1.332), or ''. It runs with a scratch HOME (a program may create its folders
// on a first run) and a timeout, and is kept until the program's file changes: an update of itself replaces it (a new link target, a
// new file), so the version shown follows it without asking again on every read.
const reportedCache = new Map();
function reportedVersion(cmd) {
  let st;
  let real;
  try { real = fs.realpathSync(cmd); st = fs.statSync(real); } catch (_) { return ''; }
  if (!st.isFile()) return '';
  const key = `${real}:${st.mtimeMs}:${st.size}`;
  if (reportedCache.get(cmd)?.key === key) return reportedCache.get(cmd).version;
  let version = '';
  let scratch = '';
  try {
    scratch = fs.mkdtempSync(path.join(os.tmpdir(), 'swarmbox-version-'));
    const out = execFileSync(cmd, ['--version'], {
      env: { ...process.env, HOME: scratch }, cwd: scratch, timeout: 5000, stdio: ['ignore', 'pipe', 'ignore'], encoding: 'utf8',
    });
    const m = String(out).match(/\d+\.\d+(?:\.\d+)*(?:[-+][0-9A-Za-z.]+)?/);
    version = m ? m[0] : '';
  } catch (_) {
    version = '';
  } finally {
    if (scratch) fs.rmSync(scratch, { recursive: true, force: true });
  }
  reportedCache.set(cmd, { key, version });
  return version;
}

function listAddonsSnapshot(env = process.env) {
  const imageDir = env.SWARMBOX_IMAGE_ADDONS_DIR || '/usr/local/lib/swarmbox/addons';
  const userDir = path.join(SB_CONFIG_DIR, 'addons');
  const dataDir = path.join(SB_DATA_DIR, 'addons');
  const bakedDir = env.SWARMBOX_TEST_IMAGE_STATE || '/opt/swarmbox/addons';
  const byName = new Map();

  for (const [level, dir] of [['image', imageDir], ['user', userDir]]) {
    let entries = [];
    try { entries = fs.readdirSync(dir, { withFileTypes: true }); } catch (_) {}
    for (const ent of entries) {
      if (!ent.isDirectory()) continue;
      const conf = parseAddonConf(path.join(dir, ent.name, 'addon.conf'));
      if (!conf) continue;
      byName.set(conf.NAME, {
        name: conf.NAME,
        description: conf.DESCRIPTION || '',
        manifestVersion: conf.VERSION || '',
        commands: (conf.COMMANDS || '').split(/\s+/).filter(Boolean),
        update: conf.UPDATE || 'managed',
        level,
      });
    }
  }

  const out = [];
  const home = { user: HOME, baked: bakedDir };
  for (const item of Array.from(byName.values()).sort((a, b) => a.name.localeCompare(b.name))) {
    let installed = false;
    let installedVersion = '';
    let location = '';
    let cmd = '';
    for (const [loc, dir] of [['workspace', dataDir], ['image', bakedDir]]) {
      const got = installedOf(dir, item, home);
      if (got === null) continue;
      installed = true;
      installedVersion = got.version;
      cmd = got.cmd;
      location = loc;
      break;
    }
    // a floating install (`latest`) shows the version its program reports; a pinned one is the version it names
    const pinnedBehind = installed && item.update !== 'self' && installedVersion !== 'latest' && !!item.manifestVersion
      && installedVersion !== item.manifestVersion;
    const reported = installed && cmd && installedVersion === 'latest' ? reportedVersion(cmd) : '';
    out.push({
      ...item,
      installed,
      installedVersion: reported || installedVersion,
      channel: installedVersion,
      selfUpdate: item.update === 'self',
      location,
      // Update installs a managed addon again: a floating one (`latest`) gets the newest release, a pinned one the version the image
      // names, offered only when that differs from the installed one (a newer image). One that updates itself is never offered.
      updateAvailable: pinnedBehind,
      canUpdate: installed && item.update !== 'self' && (installedVersion === 'latest' || pinnedBehind),
      // `swarmbox-addon remove` deletes the workspace's install; one baked into the image stays
      canRemove: installed && location === 'workspace',
    });
  }
  return out;
}

function listMcpServers() {
  const names = new Set();
  for (const dir of ['/etc/swarmbox/mcp', path.join(SB_CONFIG_DIR, 'mcp')]) {
    try {
      for (const ent of fs.readdirSync(dir, { withFileTypes: true })) {
        if (!ent.isDirectory()) continue;
        if (fs.existsSync(path.join(dir, ent.name, 'config.json'))) names.add(ent.name);
      }
    } catch (_) {}
  }
  return Array.from(names).sort();
}

function envField(envKey, defVal, env = process.env) {
  const raw = env[envKey];
  const has = typeof raw === 'string' && raw.trim() !== '';
  const value = has ? raw.trim() : defVal;
  return { value, default: defVal, custom: has && value !== defVal };
}

export function readBoxConfigSnapshot(terminals = [], env = process.env) {
  const version = readTextSafe('/usr/local/share/swarmbox/host/VERSION') || 'dev';
  const sysopSnap = readSysopSnapshot(terminals);
  const pubkey = readTextSafe(path.join(HOME, '.ssh', 'id_ed25519.pub'))
    || readTextSafe(path.join(HOME, '.ssh', 'id_rsa.pub'))
    || '';
  const healthRaw = readTextSafe(path.join(SB_STATE_DIR, 'health'));
  const health = healthRaw ? healthRaw.split('\n').map((s) => s.trim()).filter(Boolean) : [];
  const addons = listAddonsSnapshot(env);
  const installedAgents = listInstalledAgents(env);

  const box = {
    NAME: envField('SWARMBOX_NAME', 'swarmbox', env),
    AGENT: envField('SWARMBOX_AGENT', '', env),
    YOLO: envField('SWARMBOX_YOLO', '1', env),
    WEB: envField('SWARMBOX_WEB', '1', env),
    WEB_PORT: envField('SWARMBOX_WEB_PORT', '7681', env),
    TZ: { value: (env.TZ && env.TZ.trim()) || 'local', default: 'local', custom: Boolean(env.TZ && env.TZ.trim() && env.TZ.trim() !== 'local') },
    HOSTNAME: { value: os.hostname() || 'swarmbox', default: 'swarmbox', custom: Boolean(os.hostname() && os.hostname() !== 'swarmbox') },
    WITH: envField('SWARMBOX_WITH', '', env),
    BROWSER_URL: envField('SWARMBOX_BROWSER_URL', '', env),
  };

  const sysopSettings = {
    'sysop.autonomy': envField('SWARMBOX_SYSOP_AUTONOMY', 'full-auto', env),
    'sysop.autoname': envField('SWARMBOX_SYSOP_AUTONAME', '1', env),
    'sysop.autocontext': envField('SWARMBOX_SYSOP_AUTOCONTEXT', '1', env),
    'sysop.brain': envField('SWARMBOX_SYSOP_BRAIN', 'auto', env),
    'sysop.model': envField('SWARMBOX_SYSOP_MODEL', 'auto', env),
    'sysop.countdown': envField('SWARMBOX_SYSOP_COUNTDOWN', '4', env),
    'sysop.max_steps': envField('SWARMBOX_SYSOP_MAX_STEPS', '20', env),
    'sysop.max_seconds': envField('SWARMBOX_SYSOP_MAX_SECONDS', '300', env),
    'sysop.topic': envField('SWARMBOX_SYSOP_TOPIC', 'goal', env),
    'sysop.group': envField('SWARMBOX_SYSOP_GROUP', 'sysop', env),
  };

  const voiceSettings = {
    'voice.language': envField('SWARMBOX_VOICE_LANGUAGE', 'auto', env),
    'voice.stt.model': envField('SWARMBOX_VOICE_STT_MODEL', 'small', env),
    'voice.stt.vocabulary': envField('SWARMBOX_VOICE_STT_VOCABULARY', '', env),
    'voice.web': envField('SWARMBOX_VOICE_WEB', '1', env),
    'voice.topic': envField('SWARMBOX_VOICE_TOPIC', 'goal', env),
  };

  return {
    version,
    commit: readBuildCommit(),
    theme: readSavedTheme(),
    themes: THEME_ORDER,
    box,
    sysop: {
      up: sysopSnap.up,
      state: sysopSnap.state,
      settings: sysopSettings,
    },
    voice: {
      settings: voiceSettings,
    },
    addons,
    installed_agents: installedAgents,
    mcp: listMcpServers(),
    pubkey,
    health,
    worktree_prefs: readWorktreePrefs(),
    session_prefs: readSessionPrefs(),
  };
}
