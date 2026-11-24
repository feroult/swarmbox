#!/usr/bin/env node
// SwarmBox × herdr-core Web Gateway.
//
// Multiplexes a single framed binary JSON-RPC 2.0 connection (`hc connect`) to serve:
//   - Live xterm.js PTY streams (/ws/pty/:address) with CREDIT flow control & zero node-pty
//   - Live OSC 7501 terminal status + real swarmbox-sysop state events (/ws/events)
//   - Tab lifecycle, active-tab tracking, theme synchronization, and real Sysop controls (/api/*)
//
// Accepts `-p PORT` / `-i IFACE` so `swarmbox-voice front` can sit transparently in front
// of it when the voice addon is installed, handling /voice/* and proxying everything else.

import http from 'node:http';
import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { WebSocketServer } from 'ws';
import {
  ADDON_BIN,
  ALLOWED_AGENT_CMDS,
  HC_BIN,
  HERDR_THEMES,
  HOME,
  HerdrClient,
  SB_RUN_DIR,
  SYSOP_BIN,
  buildAgentArgv,
  buildPinsSnapshot,
  cleanSessionTitle,
  defaultTitleForPath,
  detectTerminalAgent,
  isHiddenTerminal,
  listInstalledAgents,
  makePinId,
  publishTabEvent,
  readActiveTab,
  readBoxConfigSnapshot,
  readPins,
  readSavedTheme,
  readSessionPrefs,
  readSysopSnapshot,
  readWorktreePrefs,
  runCommand,
  runWorktreeCmd,
  saveTheme,
  startNewConversation,
  syncPinsFromTerminals,
  terminalCwd,
  uniqueTabName,
  writeActiveTab,
  writePins,
  writeSessionPrefs,
  writeWorktreePrefs,
} from './hc-client.mjs';

export { HerdrClient };

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const PUBLIC_DIR = path.join(__dirname, 'public');
const NODE_MODULES = path.join(__dirname, 'node_modules');

export function parseCliArgs(argv) {
  let port = Number(process.env.SWARMBOX_WEB_PORT || 7681);
  let iface = process.env.SWARMBOX_WEB_IFACE || '0.0.0.0';
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if ((a === '-p' || a === '--port') && i + 1 < argv.length) {
      port = Number(argv[++i]);
    } else if (a.startsWith('--port=')) {
      port = Number(a.slice('--port='.length));
    } else if ((a === '-i' || a === '--interface') && i + 1 < argv.length) {
      iface = argv[++i];
    } else if (a.startsWith('--interface=')) {
      iface = a.slice('--interface='.length);
    }
  }
  if (iface === 'lo') iface = '127.0.0.1';
  if (!Number.isInteger(port) || port < 1 || port > 65535) port = 7681;
  return { port, iface };
}

// ---------------------------------------------------------------------------
// Security & HTTP helpers
// ---------------------------------------------------------------------------
const SECURITY_HEADERS = {
  'Content-Security-Policy': "frame-ancestors 'self'",
  'X-Frame-Options': 'SAMEORIGIN',
  'X-Content-Type-Options': 'nosniff',
};

const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.js': 'application/javascript; charset=utf-8',
  '.mjs': 'application/javascript; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.woff2': 'font/woff2',
};

export function checkSameOrigin(req) {
  const origin = req.headers.origin;
  if (!origin) return true;
  const host = (req.headers.host || '').trim().toLowerCase();
  if (!host) return false;
  try {
    return new URL(origin).host.toLowerCase() === host;
  } catch (_) {
    return false;
  }
}

function sendJson(res, code, data) {
  res.writeHead(code, {
    ...SECURITY_HEADERS,
    'Content-Type': 'application/json; charset=utf-8',
    'Cache-Control': 'no-store',
  });
  res.end(JSON.stringify(data));
}

function readBody(req, limit = 256 * 1024) {
  return new Promise((resolve, reject) => {
    let data = '';
    req.on('data', (c) => {
      data += c;
      if (data.length > limit) {
        reject(new Error('body too large'));
        req.destroy();
      }
    });
    req.on('end', () => {
      if (!data) return resolve({});
      try {
        resolve(JSON.parse(data));
      } catch (e) {
        reject(new Error('invalid JSON body'));
      }
    });
    req.on('error', reject);
  });
}

const MAX_IMAGE_BYTES = 20 * 1024 * 1024;
const MAX_PASTED_IMAGES = 40;

export function detectImageFormat(buf) {
  if (!Buffer.isBuffer(buf) || buf.length < 12) return null;
  // PNG: 89 50 4E 47 0D 0A 1A 0A
  if (
    buf[0] === 0x89 && buf[1] === 0x50 && buf[2] === 0x4e && buf[3] === 0x47 &&
    buf[4] === 0x0d && buf[5] === 0x0a && buf[6] === 0x1a && buf[7] === 0x0a
  ) return { ext: 'png', mime: 'image/png' };
  // JPEG: FF D8 FF
  if (buf[0] === 0xff && buf[1] === 0xd8 && buf[2] === 0xff) {
    return { ext: 'jpg', mime: 'image/jpeg' };
  }
  // GIF: GIF87a / GIF89a
  if (
    buf[0] === 0x47 && buf[1] === 0x49 && buf[2] === 0x46 && buf[3] === 0x38 &&
    (buf[4] === 0x37 || buf[4] === 0x39) && buf[5] === 0x61
  ) return { ext: 'gif', mime: 'image/gif' };
  // WebP: RIFF....WEBP
  if (
    buf[0] === 0x52 && buf[1] === 0x49 && buf[2] === 0x46 && buf[3] === 0x46 &&
    buf[8] === 0x57 && buf[9] === 0x45 && buf[10] === 0x42 && buf[11] === 0x50
  ) return { ext: 'webp', mime: 'image/webp' };
  // BMP: BM
  if (buf[0] === 0x42 && buf[1] === 0x4d) {
    return { ext: 'bmp', mime: 'image/bmp' };
  }
  return null;
}

function readBinaryBody(req, limit = MAX_IMAGE_BYTES) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    let total = 0;
    let aborted = false;
    req.on('data', (chunk) => {
      if (aborted) return;
      total += chunk.length;
      if (total > limit) {
        aborted = true;
        const err = new Error('image exceeds 20 MB limit');
        err.status = 413;
        reject(err);
        req.resume();
        return;
      }
      chunks.push(chunk);
    });
    req.on('end', () => {
      if (!aborted) resolve(Buffer.concat(chunks, total));
    });
    req.on('error', (err) => {
      if (!aborted) reject(err);
    });
  });
}

function pruneOldPastedImages(dir) {
  try {
    const entries = fs.readdirSync(dir)
      .filter((n) => n.startsWith('img-'))
      .map((name) => {
        const full = path.join(dir, name);
        let mtimeMs = 0;
        try { mtimeMs = fs.statSync(full).mtimeMs; } catch (_) {}
        return { full, mtimeMs };
      })
      .sort((a, b) => b.mtimeMs - a.mtimeMs);
    for (const old of entries.slice(MAX_PASTED_IMAGES)) {
      try { fs.unlinkSync(old.full); } catch (_) {}
    }
  } catch (_) {}
}

function savePastedImage(buf, pasteDir = path.join(SB_RUN_DIR, 'paste')) {
  const fmt = detectImageFormat(buf);
  if (!fmt) return null;
  fs.mkdirSync(pasteDir, { recursive: true, mode: 0o700 });
  const now = new Date();
  const stamp = [
    String(now.getHours()).padStart(2, '0'),
    String(now.getMinutes()).padStart(2, '0'),
    String(now.getSeconds()).padStart(2, '0'),
  ].join('');
  const rand = crypto.randomBytes(2).toString('hex');
  const name = `img-${stamp}-${rand}.${fmt.ext}`;
  const filePath = path.join(pasteDir, name);
  fs.writeFileSync(filePath, buf, { mode: 0o600 });
  pruneOldPastedImages(pasteDir);
  return { path: filePath, name, bytes: buf.length, mime: fmt.mime };
}

function serveFile(res, filePath, cacheable = false) {
  fs.readFile(filePath, (err, content) => {
    if (err) {
      res.writeHead(404, SECURITY_HEADERS);
      res.end('Not found');
      return;
    }
    const ext = path.extname(filePath);
    res.writeHead(200, {
      ...SECURITY_HEADERS,
      'Content-Type': MIME[ext] || 'application/octet-stream',
      'Cache-Control': cacheable ? 'public, max-age=3600' : 'no-store',
    });
    res.end(content);
  });
}

// ---------------------------------------------------------------------------
// Server factory (also exported for fast unit tests)
// ---------------------------------------------------------------------------
export function createGateway(options = {}) {
  const hc = options.hc || new HerdrClient(options.hcBin || HC_BIN);
  const eventClients = new Set();
  let currentTheme = readSavedTheme();
  let lastBroadcastHash = '';
  let cachedWorktrees = [];
  let wtRefreshing = false;
  const lastTabCwd = new Map();
  const lastTabState = new Map();

  function refreshPendingWorktrees() {
    if (wtRefreshing) return;
    wtRefreshing = true;
    runWorktreeCmd(['list'])
      .then((list) => {
        if (Array.isArray(list)) {
          const prev = JSON.stringify(cachedWorktrees);
          cachedWorktrees = list;
          if (JSON.stringify(cachedWorktrees) !== prev && eventClients.size > 0) {
            broadcast(buildSnapshot({ type: 'worktrees' }));
          }
        }
      })
      .catch(() => {})
      .finally(() => {
        wtRefreshing = false;
      });
  }

  function pendingWorktreesFor(terminals, pins) {
    const livePaths = new Set();
    for (const t of terminals || []) {
      const p = (t.labels && t.labels['swarmbox.worktree']) || terminalCwd(t);
      if (p) {
        try { livePaths.add(fs.realpathSync(p)); } catch (_) { livePaths.add(p); }
      }
    }
    const pinnedPaths = new Set();
    for (const pin of pins || []) {
      const p = (pin.worktree && pin.worktree.path) || pin.cwd;
      if (p) {
        try { pinnedPaths.add(fs.realpathSync(p)); } catch (_) { pinnedPaths.add(p); }
      }
    }
    return cachedWorktrees.filter((w) => {
      let rp = w.path;
      try { rp = fs.realpathSync(w.path); } catch (_) {}
      return !livePaths.has(rp) && !pinnedPaths.has(rp);
    });
  }

  function buildSnapshot(extra = {}) {
    const terminals = hc.listSnapshot();
    const sysop = readSysopSnapshot(terminals);
    const pins = buildPinsSnapshot(terminals);
    const worktrees = pendingWorktreesFor(terminals, pins);
    const worktree_prefs = readWorktreePrefs();
    const session_prefs = readSessionPrefs();
    const installed_agents = listInstalledAgents();
    return {
      ...extra,
      terminals,
      active: readActiveTab(),
      sysop,
      theme: currentTheme,
      pins,
      worktrees,
      worktree_prefs,
      session_prefs,
      installed_agents,
    };
  }

  function broadcast(payload) {
    const raw = JSON.stringify(payload);
    for (const ws of eventClients) {
      if (ws.readyState === 1) ws.send(raw);
    }
  }

  function emitBusTabEvents(ev, terminals) {
    const type = ev && ev.type;
    const addr = ev && ev.terminal;
    if (addr) {
      const t = (terminals || []).find((x) => x.address === addr);
      if (!t) return;
      const lbls = (t && t.labels) || {};
      const st = (t.status && t.status.state) || 'idle';
      const prevSt = lastTabState.get(addr) || '';
      lastTabState.set(addr, st);
      const cwd = terminalCwd(t);
      const prevCwd = lastTabCwd.get(addr) || '';
      lastTabCwd.set(addr, cwd);
      const isTurn = type === 'turn';
      const isFinishedWork = type === 'status' && prevSt === 'working' && (st === 'done' || st === 'idle');
      if (isTurn || isFinishedWork) {
        publishTabEvent({
          event: isTurn ? 'turn' : 'status',
          tab: addr,
          cwd,
          agent: detectTerminalAgent(t) || 'shell',
          state: st,
          title: lbls['swarmbox.title'] || '',
          title_source: lbls['swarmbox.title_source'] || '',
        });
      }
      return;
    }
    for (const t of terminals || []) {
      const cwd = terminalCwd(t);
      const prevCwd = lastTabCwd.get(t.address);
      lastTabCwd.set(t.address, cwd);
      if (prevCwd && prevCwd !== cwd) {
        const lbls = (t && t.labels) || {};
        publishTabEvent({
          event: 'cwd',
          tab: t.address,
          cwd,
          agent: detectTerminalAgent(t) || 'shell',
          state: (t.status && t.status.state) || 'idle',
          title: lbls['swarmbox.title'] || '',
          title_source: lbls['swarmbox.title_source'] || '',
        });
      }
    }
  }

  async function detectWorkingTreeCollision(targetCwd, terminals, excludeAddr = null) {
    if (!targetCwd || !fs.existsSync(targetCwd)) return null;
    let targetInfo;
    try {
      targetInfo = await runWorktreeCmd(['inspect', targetCwd]);
    } catch (_) {
      return null;
    }
    if (!targetInfo || !targetInfo.is_git) return null;
    const targetWt = targetInfo.worktree_path;
    const colliding = [];
    for (const t of terminals || []) {
      if (excludeAddr && t.address === excludeAddr) continue;
      const agentKind = detectTerminalAgent(t);
      if (!agentKind) continue;
      const tCwd = terminalCwd(t);
      if (!tCwd) continue;
      let tReal = tCwd;
      try { tReal = fs.realpathSync(tCwd); } catch (_) {}
      if (tReal === targetWt || tReal.startsWith(targetWt + path.sep)) {
        colliding.push({
          address: t.address,
          name: (t.labels && t.labels['swarmbox.title']) || t.name || t.address,
          agent: agentKind,
        });
      }
    }
    if (colliding.length === 0) return null;
    return {
      repo_root: targetInfo.repo_root,
      repo_name: targetInfo.repo_name,
      branch: targetInfo.branch || targetInfo.base || 'HEAD',
      worktree_path: targetWt,
      dirty: Boolean(targetInfo.dirty),
      active_tabs: colliding,
    };
  }

  hc.on('snapshot', () => {
    const terms = hc.listSnapshot();
    syncPinsFromTerminals(terms);
    emitBusTabEvents(null, terms);
    const snap = buildSnapshot({ type: 'snapshot' });
    lastBroadcastHash = JSON.stringify({ sysop: snap.sysop, theme: snap.theme, active: snap.active, pins: snap.pins, worktrees: snap.worktrees, session_prefs: snap.session_prefs });
    broadcast(snap);
  });

  hc.on('hc-event', ({ event }) => {
    const terms = hc.listSnapshot();
    syncPinsFromTerminals(terms);
    emitBusTabEvents(event, terms);
    const snap = buildSnapshot({ type: 'event', event });
    lastBroadcastHash = JSON.stringify({ sysop: snap.sysop, theme: snap.theme, active: snap.active, pins: snap.pins, worktrees: snap.worktrees, session_prefs: snap.session_prefs });
    broadcast(snap);
  });

  // Poll real swarmbox-sysop state files & shared theme file; broadcast only on actual changes.
  // Every 4th tick (~2.4s) when a browser is open, also refresh live foreground cwd/metadata.
  let pollTick = 0;
  const sysopTimer = setInterval(() => {
    const diskTheme = readSavedTheme();
    const themeChanged = diskTheme !== currentTheme;
    if (themeChanged) currentTheme = diskTheme;
    if (eventClients.size === 0) return;
    pollTick = (pollTick + 1) % 8;
    if (pollTick % 4 === 0 && typeof hc.refreshTerminals === 'function') {
      hc.refreshTerminals();
    }
    if (pollTick === 0) {
      refreshPendingWorktrees();
    }
    const snap = buildSnapshot({ type: themeChanged ? 'theme' : 'sysop' });
    const h = JSON.stringify({ sysop: snap.sysop, theme: snap.theme, active: snap.active, pins: snap.pins, worktrees: snap.worktrees, session_prefs: snap.session_prefs });
    if (h !== lastBroadcastHash) {
      lastBroadcastHash = h;
      broadcast(snap);
    }
  }, 600);
  if (sysopTimer.unref) sysopTimer.unref();

  const server = http.createServer(async (req, res) => {
    const url = new URL(req.url, `http://${req.headers.host || 'localhost'}`);
    const pathname = url.pathname;

    try {
      // Origin guard on all mutating API routes
      if (pathname.startsWith('/api/') && req.method !== 'GET' && req.method !== 'HEAD') {
        if (!checkSameOrigin(req)) {
          return sendJson(res, 403, { error: 'bad_origin', message: 'cross-origin calls are not allowed' });
        }
      }

      // Local xterm.js & JetBrains Mono + Nerd Font vendor bundles (zero CDN dependency)
      if (pathname === '/vendor/xterm.js') return serveFile(res, path.join(NODE_MODULES, '@xterm/xterm/lib/xterm.js'), true);
      if (pathname === '/vendor/xterm.css') return serveFile(res, path.join(NODE_MODULES, '@xterm/xterm/css/xterm.css'), true);
      if (pathname === '/vendor/addon-fit.js') return serveFile(res, path.join(NODE_MODULES, '@xterm/addon-fit/lib/addon-fit.js'), true);
      if (pathname === '/vendor/addon-web-links.js') return serveFile(res, path.join(NODE_MODULES, '@xterm/addon-web-links/lib/addon-web-links.js'), true);
      if (pathname === '/vendor/fonts/jetbrains-mono-latin.woff2') {
        return serveFile(res, path.join(NODE_MODULES, '@fontsource-variable/jetbrains-mono/files/jetbrains-mono-latin-wght-normal.woff2'), true);
      }
      if (pathname === '/vendor/fonts/jetbrains-mono-latin-ext.woff2') {
        return serveFile(res, path.join(NODE_MODULES, '@fontsource-variable/jetbrains-mono/files/jetbrains-mono-latin-ext-wght-normal.woff2'), true);
      }
      if (pathname === '/vendor/fonts/jetbrains-mono-latin-italic.woff2') {
        return serveFile(res, path.join(NODE_MODULES, '@fontsource-variable/jetbrains-mono/files/jetbrains-mono-latin-wght-italic.woff2'), true);
      }
      if (pathname === '/vendor/fonts/nerd-symbols.woff2') {
        return serveFile(res, path.join(NODE_MODULES, '@azurity/pure-nerd-font/PureNerdFont.woff2'), true);
      }

      // Health & state
      if (pathname === '/api/health' && req.method === 'GET') {
        const snap = buildSnapshot();
        return sendJson(res, 200, {
          ok: true,
          mux: 'herdr',
          herdr: Boolean(hc.proc),
          tabs: snap.terminals.length,
          sysop_up: snap.sysop.up,
          theme: currentTheme,
        });
      }

      if (pathname === '/api/theme' && req.method === 'GET') {
        currentTheme = readSavedTheme();
        return sendJson(res, 200, { theme: currentTheme, themes: Object.keys(HERDR_THEMES) });
      }
      if (pathname === '/api/theme' && req.method === 'POST') {
        const body = await readBody(req);
        const name = String(body.theme || '');
        if (!HERDR_THEMES[name]) return sendJson(res, 400, { error: 'unknown_theme' });
        currentTheme = name;
        saveTheme(name);
        broadcast(buildSnapshot({ type: 'theme' }));
        return sendJson(res, 200, { ok: true, theme: currentTheme });
      }

      if (pathname === '/api/paste-image' && req.method === 'POST') {
        let buf;
        try {
          buf = await readBinaryBody(req, MAX_IMAGE_BYTES);
        } catch (err) {
          return sendJson(res, err.status || 400, { error: 'upload_failed', message: err.message });
        }
        if (!buf || buf.length === 0) {
          return sendJson(res, 400, { error: 'empty_image', message: 'no image data received' });
        }
        const saved = savePastedImage(buf);
        if (!saved) {
          return sendJson(res, 415, { error: 'unsupported_image', message: 'supported formats: PNG, JPEG, WebP, GIF, BMP' });
        }
        return sendJson(res, 200, { ok: true, ...saved });
      }

      if (pathname === '/api/config' && req.method === 'GET') {
        currentTheme = readSavedTheme();
        const cfg = readBoxConfigSnapshot(hc.listSnapshot());
        cfg.theme = currentTheme;
        return sendJson(res, 200, cfg);
      }

      const addonMatch = pathname.match(/^\/api\/addons\/([a-z0-9][a-z0-9_-]{0,40})\/install$/);
      if (addonMatch && req.method === 'POST') {
        const addonName = addonMatch[1];
        const curCfg = readBoxConfigSnapshot(hc.listSnapshot());
        if (!curCfg.addons.some((a) => a.name === addonName)) {
          return sendJson(res, 404, { error: 'unknown_addon', message: `Addon "${addonName}" not found` });
        }
        const r = await runCommand(ADDON_BIN, ['install', addonName], null, 180000);
        if (!r.ok) {
          return sendJson(res, 502, {
            error: 'addon_install_failed',
            message: r.stderr || r.stdout || `swarmbox-addon install ${addonName} failed`,
          });
        }
        await runCommand(ADDON_BIN, ['prepare'], null, 60000);
        broadcast(buildSnapshot({ type: 'sysop' }));
        return sendJson(res, 200, {
          ok: true,
          addon: addonName,
          message: r.stdout || `${addonName} installed`,
          config: readBoxConfigSnapshot(hc.listSnapshot()),
        });
      }

      if (pathname === '/api/tabs' && req.method === 'GET') {
        const resList = await hc.call('terminal.list', { all: false });
        const terminals = (resList.terminals || []).filter((t) => t.state === 'live' && !isHiddenTerminal(t));
        const pins = buildPinsSnapshot(terminals);
        return sendJson(res, 200, {
          terminals,
          active: readActiveTab(),
          sysop: readSysopSnapshot(terminals),
          theme: currentTheme,
          pins,
          worktrees: pendingWorktreesFor(terminals, pins),
          worktree_prefs: readWorktreePrefs(),
          session_prefs: readSessionPrefs(),
          installed_agents: listInstalledAgents(),
        });
      }

      if (pathname === '/api/tabs' && req.method === 'POST') {
        const body = await readBody(req);
        const preset = String(body.preset || 'shell');
        let cwd = typeof body.cwd === 'string' && body.cwd.startsWith('/') ? body.cwd : HOME;
        const worktreeChoice = String(body.worktree_choice || '').trim().toLowerCase(); // '' | 'new' | 'same'
        const prefs = readWorktreePrefs();
        const liveTerms = hc.listSnapshot();

        let argv = ['/bin/bash', '-l'];
        let prefix = 'shell';
        let agentKind = 'shell';
        if (preset === 'agent') {
          const requested = String(body.agent || process.env.SWARMBOX_AGENT || 'yolo').trim();
          const cmd = ALLOWED_AGENT_CMDS.has(requested) ? requested : 'yolo';
          agentKind = cmd === 'yolo' ? (ALLOWED_AGENT_CMDS.has(process.env.SWARMBOX_AGENT) ? process.env.SWARMBOX_AGENT : 'yolo') : cmd;
          argv = buildAgentArgv(cmd, body.resume === 'continue' ? 'continue' : 'fresh');
          prefix = cmd === 'yolo' ? 'agent' : cmd;
        }

        const labels = {};
        if (agentKind && agentKind !== 'shell') labels['swarmbox.agent'] = agentKind;
        let createdWorktree = null;

        if (preset === 'agent' && worktreeChoice !== 'same') {
          const collision = await detectWorkingTreeCollision(cwd, liveTerms);
          if (worktreeChoice === 'new' || (collision && prefs.mode === 'auto')) {
            try {
              const wtRes = await runWorktreeCmd(['create', cwd]);
              cwd = wtRes.path;
              createdWorktree = wtRes;
              labels['swarmbox.worktree'] = wtRes.path;
              labels['swarmbox.branch'] = wtRes.branch;
              labels['swarmbox.base'] = wtRes.base;
              labels['swarmbox.repo'] = wtRes.repo_root;
            } catch (err) {
              return sendJson(res, 409, { error: err.code || 'worktree_failed', message: err.message });
            }
          } else if (collision && prefs.mode === 'ask') {
            return sendJson(res, 409, {
              error: 'worktree_collision',
              message: `${collision.repo_name} already has an active agent on ${collision.branch}`,
              cwd,
              preset,
              agent: agentKind,
              collision,
              prefs,
            });
          }
        }

        const customTitle = cleanSessionTitle(body.title);
        if (customTitle) {
          labels['swarmbox.title'] = customTitle;
          labels['swarmbox.title_source'] = body.title_source === 'auto' ? 'auto' : 'user';
        }

        // Option 1: auto-persist open agent sessions so they survive restarts/resets automatically
        // according to the global boot_mode setting (autostart by default; closing with X removes them).
        let autoPin = null;
        if (preset === 'agent' && body.persist !== false) {
          const curPins = readPins();
          const pinId = makePinId(curPins);
          const nowSec = Math.floor(Date.now() / 1000);
          const sprefs = readSessionPrefs();
          const title = customTitle || defaultTitleForPath(cwd, agentKind);
          autoPin = {
            id: pinId,
            title,
            title_source: customTitle ? (body.title_source === 'auto' ? 'auto' : 'user') : '',
            agent: agentKind,
            cwd,
            resume: body.resume === 'fresh' ? 'fresh' : 'continue',
            autostart: sprefs.boot_mode === 'autostart',
            auto: true,
            created_at: nowSec,
            updated_at: nowSec,
          };
          if (createdWorktree) {
            autoPin.worktree = {
              path: createdWorktree.path,
              branch: createdWorktree.branch || '',
              base: createdWorktree.base || '',
              repo: createdWorktree.repo_root || '',
            };
          }
          labels['swarmbox.pin_id'] = pinId;
          if (!labels['swarmbox.title']) labels['swarmbox.title'] = title;
          curPins.push(autoPin);
          writePins(curPins);
        }

        const name = uniqueTabName(body.name || customTitle, prefix, Array.from(hc.terminals.values()));
        const runParams = {
          argv,
          name,
          cwd,
          keep: true,
          no_parent: true,
        };
        if (Object.keys(labels).length > 0) runParams.labels = labels;
        const created = await hc.call('terminal.run', runParams);
        const createdTerm = (created && created.terminal) || created;
        const addr = createdTerm && createdTerm.address;
        if (addr) {
          writeActiveTab(addr);
          hc.terminals.set(addr, createdTerm);
        }
        if (createdWorktree) refreshPendingWorktrees();
        broadcast(buildSnapshot({ type: 'snapshot' }));
        const resp = { ...(createdTerm || {}), terminal: createdTerm };
        if (createdWorktree) resp.worktree = createdWorktree;
        if (autoPin) resp.pin = autoPin;
        return sendJson(res, 201, resp);
      }

      const tabMatch = pathname.match(/^\/api\/tabs\/([^/]+)(?:\/(focus|send|keys|interrupt|answer|worktree))?$/);
      if (tabMatch) {
        const termId = decodeURIComponent(tabMatch[1]);
        const action = tabMatch[2];

        if (!action && req.method === 'PATCH') {
          const body = await readBody(req);
          const title = cleanSessionTitle(body.title);
          if (!title) return sendJson(res, 400, { error: 'bad_title', message: 'title cannot be empty' });
          const source = body.title_source === 'auto' ? 'auto' : 'user';
          await hc.call('terminal.label', {
            terminal: termId,
            labels: {
              'swarmbox.title': title,
              'swarmbox.title_source': source,
            },
          });
          const t = hc.terminals.get(termId);
          if (t) {
            t.labels = { ...(t.labels || {}), 'swarmbox.title': title, 'swarmbox.title_source': source };
            const pinId = t.labels['swarmbox.pin_id'];
            if (pinId) {
              const pins = readPins();
              const pin = pins.find((p) => p.id === pinId);
              if (pin) {
                pin.title = title;
                pin.title_source = source;
                pin.updated_at = Math.floor(Date.now() / 1000);
                writePins(pins);
              }
            }
          }
          broadcast(buildSnapshot({ type: 'snapshot' }));
          return sendJson(res, 200, { ok: true, terminal: termId, title, title_source: source });
        }

        if (!action && req.method === 'DELETE') {
          const t = hc.terminals.get(termId);
          const lbls = (t && t.labels) || {};
          const pinId = lbls['swarmbox.pin_id'] || '';
          const wtPath = lbls['swarmbox.worktree'] || '';
          let pinKept = false;
          if (pinId) {
            const pins = readPins();
            const existingPin = pins.find((p) => p.id === pinId);
            const dropRequested = url.searchParams.get('drop_pin') === '1';
            if (existingPin && (existingPin.auto || dropRequested)) {
              writePins(pins.filter((p) => p.id !== pinId));
            } else if (existingPin) {
              pinKept = true;
            }
          }
          await hc.call('terminal.keep', { terminal: termId, keep: false }).catch(() => {});
          await hc.call('terminal.kill', { terminal: termId }).catch(() => {});
          hc.call('terminal.rm', { terminal: termId }).catch(() => {});
          hc.terminals.delete(termId);
          let autoCleaned = false;
          // Auto-clean empty managed worktrees on close when no parked pin holds them
          if (!pinKept && wtPath) {
            try {
              const st = await runWorktreeCmd(['status', wtPath]);
              if (st && st.managed && st.empty) {
                await runWorktreeCmd(['remove', wtPath]);
                autoCleaned = true;
              }
            } catch (_) {}
          }
          refreshPendingWorktrees();
          broadcast(buildSnapshot({ type: 'snapshot' }));
          return sendJson(res, 200, { ok: true, pinned: pinKept, auto_cleaned_worktree: autoCleaned });
        }
        if (action === 'worktree' && req.method === 'GET') {
          const t = hc.terminals.get(termId);
          if (!t) return sendJson(res, 404, { error: 'no_such_tab', message: 'tab not found' });
          const target = (t.labels && t.labels['swarmbox.worktree']) || terminalCwd(t);
          try {
            const st = await runWorktreeCmd(['status', target]);
            return sendJson(res, 200, st);
          } catch (err) {
            return sendJson(res, 404, { error: err.code || 'not_a_worktree', message: err.message });
          }
        }
        if (action === 'focus' && req.method === 'POST') {
          writeActiveTab(termId);
          return sendJson(res, 200, { ok: true, active: termId });
        }
        if (action === 'send' && req.method === 'POST') {
          const body = await readBody(req);
          const r = await hc.call('terminal.send', {
            terminal: termId,
            text: String(body.text || ''),
            force: Boolean(body.force),
          });
          return sendJson(res, 200, r);
        }
        if (action === 'answer' && req.method === 'POST') {
          const body = await readBody(req);
          const decision = body.decision === 'allow' ? 'y' : 'n';
          const r = await hc.call('terminal.send', {
            terminal: termId,
            text: typeof body.text === 'string' ? body.text : decision,
            force: true,
          });
          return sendJson(res, 200, { ok: true, result: r });
        }
        if (action === 'keys' && req.method === 'POST') {
          const body = await readBody(req);
          const keys = Array.isArray(body.keys) ? body.keys.map(String) : [];
          const r = await hc.call('terminal.keys', { terminal: termId, keys });
          return sendJson(res, 200, r);
        }
        if (action === 'interrupt' && req.method === 'POST') {
          const r = await hc.call('terminal.interrupt', { terminal: termId, timeout: 2 });
          return sendJson(res, 200, r);
        }
      }

      // ---------------------------------------------------------------------
      // Pinned Sessions API (/api/pins)
      // ---------------------------------------------------------------------
      if (pathname === '/api/pins' && req.method === 'GET') {
        const pins = buildPinsSnapshot(hc.listSnapshot());
        return sendJson(res, 200, { pins });
      }

      if (pathname === '/api/pins' && req.method === 'POST') {
        const body = await readBody(req);
        const pins = readPins();
        const nowSec = Math.floor(Date.now() / 1000);
        if (body.terminal) {
          const tid = String(body.terminal);
          const t = hc.terminals.get(tid);
          if (!t) return sendJson(res, 404, { error: 'no_such_tab', message: 'tab not found' });
          const lbls = t.labels || {};
          const existingId = lbls['swarmbox.pin_id'];
          if (existingId) {
            const existing = pins.find((p) => p.id === existingId);
            if (existing) return sendJson(res, 200, { ok: true, pin: existing, pins: buildPinsSnapshot(hc.listSnapshot()) });
          }
          const cwd = terminalCwd(t);
          const agent = detectTerminalAgent(t) || 'shell';
          const title = cleanSessionTitle(body.title || lbls['swarmbox.title']) || defaultTitleForPath(cwd, agent);
          const titleSource = body.title ? 'user' : (lbls['swarmbox.title_source'] || '');
          const pinId = makePinId(pins);
          const rec = {
            id: pinId,
            title,
            title_source: titleSource,
            agent,
            cwd,
            resume: body.resume === 'fresh' ? 'fresh' : 'continue',
            autostart: Boolean(body.autostart),
            created_at: nowSec,
            updated_at: nowSec,
          };
          if (lbls['swarmbox.worktree']) {
            rec.worktree = {
              path: String(lbls['swarmbox.worktree']),
              branch: String(lbls['swarmbox.branch'] || ''),
              base: String(lbls['swarmbox.base'] || ''),
              repo: String(lbls['swarmbox.repo'] || ''),
            };
          } else {
            try {
              const inf = await runWorktreeCmd(['inspect', cwd]);
              if (inf && inf.is_git && inf.is_worktree) {
                rec.worktree = {
                  path: inf.worktree_path,
                  branch: inf.branch || '',
                  base: inf.base || '',
                  repo: inf.repo_root || '',
                };
              }
            } catch (_) {}
          }
          pins.push(rec);
          writePins(pins);
          const newLabels = {
            'swarmbox.pin_id': pinId,
            'swarmbox.title': title,
            'swarmbox.agent': agent,
          };
          if (titleSource) newLabels['swarmbox.title_source'] = titleSource;
          if (rec.worktree) {
            newLabels['swarmbox.worktree'] = rec.worktree.path;
            if (rec.worktree.branch) newLabels['swarmbox.branch'] = rec.worktree.branch;
            if (rec.worktree.base) newLabels['swarmbox.base'] = rec.worktree.base;
            if (rec.worktree.repo) newLabels['swarmbox.repo'] = rec.worktree.repo;
          }
          await hc.call('terminal.label', { terminal: tid, labels: newLabels });
          t.labels = { ...(t.labels || {}), ...newLabels };
          broadcast(buildSnapshot({ type: 'snapshot' }));
          return sendJson(res, 201, { ok: true, pin: rec, pins: buildPinsSnapshot(hc.listSnapshot()) });
        }
        const cwd = typeof body.cwd === 'string' && body.cwd.startsWith('/') ? body.cwd : HOME;
        const agent = ALLOWED_AGENT_CMDS.has(body.agent) ? body.agent : 'shell';
        const title = cleanSessionTitle(body.title) || defaultTitleForPath(cwd, agent);
        const rec = {
          id: makePinId(pins),
          title,
          title_source: body.title ? 'user' : '',
          agent,
          cwd,
          resume: body.resume === 'fresh' ? 'fresh' : 'continue',
          autostart: Boolean(body.autostart),
          created_at: nowSec,
          updated_at: nowSec,
        };
        pins.push(rec);
        writePins(pins);
        broadcast(buildSnapshot({ type: 'snapshot' }));
        return sendJson(res, 201, { ok: true, pin: rec, pins: buildPinsSnapshot(hc.listSnapshot()) });
      }

      if (pathname === '/api/pins/prefs' && req.method === 'GET') {
        return sendJson(res, 200, { prefs: readSessionPrefs() });
      }
      if (pathname === '/api/pins/prefs' && req.method === 'PATCH') {
        const body = await readBody(req);
        try {
          const prefs = writeSessionPrefs(body);
          broadcast(buildSnapshot({ type: 'snapshot' }));
          return sendJson(res, 200, { ok: true, prefs, pins: buildPinsSnapshot(hc.listSnapshot()) });
        } catch (err) {
          return sendJson(res, 400, { error: 'bad_prefs', message: err.message });
        }
      }

      // Lightweight mobile touch/scroll/zoom gesture diagnostic log (bounded to 250 lines in SB_RUN_DIR)
      const touchLogPath = path.join(SB_RUN_DIR, 'touch-debug.jsonl');
      if (pathname === '/api/debug/touch' && req.method === 'GET') {
        let lines = [];
        try {
          lines = fs.readFileSync(touchLogPath, 'utf8').split('\n').filter(Boolean).slice(-250).map((l) => {
            try { return JSON.parse(l); } catch (_) { return { raw: l }; }
          });
        } catch (_) {}
        return sendJson(res, 200, { path: touchLogPath, count: lines.length, events: lines });
      }
      if (pathname === '/api/debug/touch' && req.method === 'POST') {
        const body = await readBody(req, 16 * 1024);
        try {
          fs.mkdirSync(SB_RUN_DIR, { recursive: true, mode: 0o700 });
          const rec = { ts: new Date().toISOString(), ...(body && typeof body === 'object' ? body : {}) };
          let existing = [];
          try { existing = fs.readFileSync(touchLogPath, 'utf8').split('\n').filter(Boolean); } catch (_) {}
          existing.push(JSON.stringify(rec));
          if (existing.length > 250) existing = existing.slice(-250);
          fs.writeFileSync(touchLogPath, existing.join('\n') + '\n', { mode: 0o600 });
        } catch (_) {}
        return sendJson(res, 200, { ok: true });
      }

      const pinMatch = pathname.match(/^\/api\/pins\/([^/]+)(?:\/(wake))?$/);
      if (pinMatch) {
        const pinId = decodeURIComponent(pinMatch[1]);
        const pinAction = pinMatch[2];

        if (!pinAction && req.method === 'PATCH') {
          const body = await readBody(req);
          const pins = readPins();
          const pin = pins.find((p) => p.id === pinId);
          if (!pin) return sendJson(res, 404, { error: 'no_such_pin', message: 'pin not found' });
          if (body.title !== undefined) {
            const clean = cleanSessionTitle(body.title);
            if (!clean) return sendJson(res, 400, { error: 'bad_title', message: 'title cannot be empty' });
            pin.title = clean;
            pin.title_source = body.title_source === 'auto' ? 'auto' : 'user';
          }
          if (body.autostart !== undefined) pin.autostart = Boolean(body.autostart);
          if (body.resume === 'continue' || body.resume === 'fresh') pin.resume = body.resume;
          pin.updated_at = Math.floor(Date.now() / 1000);
          writePins(pins);
          // Sync title to any live terminal bound to this pin
          for (const t of hc.listSnapshot()) {
            if (t.labels && t.labels['swarmbox.pin_id'] === pinId && body.title !== undefined) {
              const upd = { 'swarmbox.title': pin.title, 'swarmbox.title_source': pin.title_source || 'user' };
              hc.call('terminal.label', { terminal: t.address, labels: upd }).catch(() => {});
              t.labels = { ...t.labels, ...upd };
            }
          }
          broadcast(buildSnapshot({ type: 'snapshot' }));
          return sendJson(res, 200, { ok: true, pin, pins: buildPinsSnapshot(hc.listSnapshot()) });
        }

        if (!pinAction && req.method === 'DELETE') {
          const pins = readPins();
          const kept = pins.filter((p) => p.id !== pinId);
          if (kept.length === pins.length) return sendJson(res, 404, { error: 'no_such_pin', message: 'pin not found' });
          writePins(kept);
          for (const t of hc.listSnapshot()) {
            if (t.labels && t.labels['swarmbox.pin_id'] === pinId) {
              hc.call('terminal.label', { terminal: t.address, labels: { 'swarmbox.pin_id': '' } }).catch(() => {});
              delete t.labels['swarmbox.pin_id'];
            }
          }
          broadcast(buildSnapshot({ type: 'snapshot' }));
          return sendJson(res, 200, { ok: true, pins: buildPinsSnapshot(hc.listSnapshot()) });
        }

        if (pinAction === 'wake' && req.method === 'POST') {
          const body = await readBody(req);
          const pins = readPins();
          const pin = pins.find((p) => p.id === pinId);
          if (!pin) return sendJson(res, 404, { error: 'no_such_pin', message: 'pin not found' });
          const liveTerms = hc.listSnapshot();
          const already = liveTerms.find((t) => t.labels && t.labels['swarmbox.pin_id'] === pinId);
          if (already) {
            writeActiveTab(already.address);
            return sendJson(res, 200, { ok: true, terminal: already, already_live: true });
          }
          let cwd = pin.cwd || HOME;
          if (!fs.existsSync(cwd)) {
            return sendJson(res, 409, { error: 'missing_cwd', message: `Directory no longer exists: ${cwd}` });
          }
          const worktreeChoice = String(body.worktree_choice || '').trim().toLowerCase();
          const prefs = readWorktreePrefs();
          let resumeMode = pin.resume || 'continue';
          let createdWorktree = null;
          const labels = {
            'swarmbox.pin_id': pin.id,
            'swarmbox.title': pin.title || defaultTitleForPath(cwd, pin.agent),
            'swarmbox.agent': pin.agent || 'shell',
          };
          if (pin.title_source) labels['swarmbox.title_source'] = pin.title_source;
          if (pin.worktree && pin.worktree.path) {
            labels['swarmbox.worktree'] = pin.worktree.path;
            if (pin.worktree.branch) labels['swarmbox.branch'] = pin.worktree.branch;
            if (pin.worktree.base) labels['swarmbox.base'] = pin.worktree.base;
            if (pin.worktree.repo) labels['swarmbox.repo'] = pin.worktree.repo;
          }

          if (pin.agent && pin.agent !== 'shell' && worktreeChoice !== 'same') {
            const collision = await detectWorkingTreeCollision(cwd, liveTerms);
            if (worktreeChoice === 'new' || (collision && prefs.mode === 'auto')) {
              try {
                const wtRes = await runWorktreeCmd(['create', cwd]);
                cwd = wtRes.path;
                createdWorktree = wtRes;
                // A brand-new worktree path has no prior conversation for --continue
                resumeMode = 'fresh';
                // Open as an isolated tab without overwriting the pin's original binding
                delete labels['swarmbox.pin_id'];
                labels['swarmbox.worktree'] = wtRes.path;
                labels['swarmbox.branch'] = wtRes.branch;
                labels['swarmbox.base'] = wtRes.base;
                labels['swarmbox.repo'] = wtRes.repo_root;
              } catch (err) {
                return sendJson(res, 409, { error: err.code || 'worktree_failed', message: err.message });
              }
            } else if (collision && prefs.mode === 'ask') {
              return sendJson(res, 409, {
                error: 'worktree_collision',
                message: `${collision.repo_name} already has an active agent on ${collision.branch}`,
                pin_id: pin.id,
                cwd,
                collision,
                prefs,
              });
            }
          }

          const argv = buildAgentArgv(pin.agent || 'shell', resumeMode);
          const name = uniqueTabName(pin.title, pin.agent || 'pin', Array.from(hc.terminals.values()));
          const created = await hc.call('terminal.run', {
            argv,
            name,
            cwd,
            keep: true,
            no_parent: true,
            labels,
          });
          const createdTerm = (created && created.terminal) || created;
          const addr = createdTerm && createdTerm.address;
          if (addr) {
            writeActiveTab(addr);
            hc.terminals.set(addr, createdTerm);
          }
          if (createdWorktree) refreshPendingWorktrees();
          broadcast(buildSnapshot({ type: 'snapshot' }));
          const resp = { ...(createdTerm || {}), terminal: createdTerm };
          if (createdWorktree) resp.worktree = createdWorktree;
          return sendJson(res, 201, resp);
        }
      }

      // ---------------------------------------------------------------------
      // Git Worktrees API (/api/worktrees/*)
      // ---------------------------------------------------------------------
      if (pathname === '/api/worktrees' && req.method === 'GET') {
        try {
          const list = await runWorktreeCmd(['list']);
          cachedWorktrees = Array.isArray(list) ? list : [];
          return sendJson(res, 200, {
            worktrees: cachedWorktrees,
            pending: pendingWorktreesFor(hc.listSnapshot(), readPins()),
            prefs: readWorktreePrefs(),
          });
        } catch (err) {
          return sendJson(res, 500, { error: err.code || 'worktree_error', message: err.message });
        }
      }

      if (pathname === '/api/worktrees/prefs' && req.method === 'PATCH') {
        const body = await readBody(req);
        try {
          const prefs = writeWorktreePrefs(body);
          broadcast(buildSnapshot({ type: 'snapshot' }));
          return sendJson(res, 200, { ok: true, prefs });
        } catch (err) {
          return sendJson(res, 400, { error: 'bad_prefs', message: err.message });
        }
      }

      if (pathname === '/api/worktrees/status' && req.method === 'GET') {
        let target = url.searchParams.get('path') || '';
        const tid = url.searchParams.get('terminal') || '';
        if (!target && tid) {
          const t = hc.terminals.get(tid);
          if (t) target = (t.labels && t.labels['swarmbox.worktree']) || terminalCwd(t);
        }
        if (!target) return sendJson(res, 400, { error: 'bad_arg', message: 'path or terminal required' });
        try {
          const st = await runWorktreeCmd(['status', target]);
          return sendJson(res, 200, st);
        } catch (err) {
          return sendJson(res, 404, { error: err.code || 'not_a_worktree', message: err.message });
        }
      }

      if (pathname === '/api/worktrees/merge' && req.method === 'POST') {
        const body = await readBody(req);
        let wtPath = String(body.path || '');
        const tid = body.terminal ? String(body.terminal) : '';
        if (!wtPath && tid) {
          const t = hc.terminals.get(tid);
          if (t) wtPath = (t.labels && t.labels['swarmbox.worktree']) || terminalCwd(t);
        }
        if (!wtPath) return sendJson(res, 400, { error: 'bad_arg', message: 'path or terminal required' });
        const args = ['merge', wtPath];
        if (body.squash) args.push('--squash');
        if (body.clean) args.push('--clean');
        try {
          const resMerge = await runWorktreeCmd(args);
          if (body.clean && tid) {
            // If pinned, unpin when explicitly merged & cleaned
            const t = hc.terminals.get(tid);
            const pinId = t && t.labels && t.labels['swarmbox.pin_id'];
            if (pinId) {
              const kept = readPins().filter((p) => p.id !== pinId);
              writePins(kept);
            }
            hc.call('terminal.kill', { terminal: tid }).catch(() => {});
            hc.call('terminal.rm', { terminal: tid }).catch(() => {});
            hc.terminals.delete(tid);
          }
          refreshPendingWorktrees();
          broadcast(buildSnapshot({ type: 'snapshot' }));
          return sendJson(res, 200, resMerge);
        } catch (err) {
          return sendJson(res, 409, { error: err.code || 'merge_failed', message: err.message, ...(err.data || {}) });
        }
      }

      if (pathname === '/api/worktrees/remove' && req.method === 'POST') {
        const body = await readBody(req);
        const wtPath = String(body.path || '');
        if (!wtPath) return sendJson(res, 400, { error: 'bad_arg', message: 'path required' });
        const args = ['remove', wtPath];
        if (body.force) args.push('--force');
        try {
          const r = await runWorktreeCmd(args);
          if (body.terminal) {
            const tid = String(body.terminal);
            hc.call('terminal.kill', { terminal: tid }).catch(() => {});
            hc.call('terminal.rm', { terminal: tid }).catch(() => {});
            hc.terminals.delete(tid);
          }
          refreshPendingWorktrees();
          broadcast(buildSnapshot({ type: 'snapshot' }));
          return sendJson(res, 200, r);
        } catch (err) {
          return sendJson(res, 409, { error: err.code || 'remove_failed', message: err.message });
        }
      }

      if (pathname === '/api/worktrees/open' && req.method === 'POST') {
        const body = await readBody(req);
        const wtPath = String(body.path || '');
        if (!wtPath || !fs.existsSync(wtPath)) {
          return sendJson(res, 404, { error: 'missing_path', message: 'worktree folder does not exist' });
        }
        const st = await runWorktreeCmd(['status', wtPath]).catch(() => null);
        const reqAgent = String(body.agent || process.env.SWARMBOX_AGENT || 'claude').trim();
        const cmd = ALLOWED_AGENT_CMDS.has(reqAgent) ? reqAgent : 'shell';
        const argv = buildAgentArgv(cmd, 'continue');
        const labels = {
          'swarmbox.agent': cmd,
          'swarmbox.worktree': wtPath,
        };
        if (st) {
          if (st.branch) labels['swarmbox.branch'] = st.branch;
          if (st.base) labels['swarmbox.base'] = st.base;
          if (st.repo_root) labels['swarmbox.repo'] = st.repo_root;
        }
        const name = uniqueTabName(st && st.branch ? st.branch.replace(/^sb\//, '') : path.basename(wtPath), cmd, Array.from(hc.terminals.values()));
        const created = await hc.call('terminal.run', { argv, name, cwd: wtPath, keep: true, no_parent: true, labels });
        const createdTerm = (created && created.terminal) || created;
        const addr = createdTerm && createdTerm.address;
        if (addr) {
          writeActiveTab(addr);
          hc.terminals.set(addr, createdTerm);
        }
        refreshPendingWorktrees();
        broadcast(buildSnapshot({ type: 'snapshot' }));
        return sendJson(res, 201, { ...(createdTerm || {}), terminal: createdTerm });
      }

      if ((pathname === '/api/worktrees/commit' || pathname === '/api/worktrees/resolve-conflict') && req.method === 'POST') {
        const body = await readBody(req);
        const tid = String(body.terminal || '');
        if (!tid) return sendJson(res, 400, { error: 'bad_arg', message: 'terminal required' });
        const base = String(body.base || 'main');
        const prompt = pathname.endsWith('/commit')
          ? 'Review our uncommitted changes in this worktree, run tests if relevant, and create a clean git commit.'
          : `Pull ${base} into this worktree branch (git merge ${base}), resolve any merge conflicts preserving both intents, run tests, and commit the resolution.`;
        const r = await hc.call('terminal.send', { terminal: tid, text: prompt, force: true });
        return sendJson(res, 200, { ok: true, result: r });
      }

      // Real swarmbox-sysop controls
      if (pathname === '/api/sysop/goal' && req.method === 'POST') {
        const body = await readBody(req);
        const goal = String(body.goal || '').trim();
        if (!goal) return sendJson(res, 400, { error: 'empty_goal', message: 'goal cannot be empty' });
        if (body.terminal) writeActiveTab(String(body.terminal));
        const r = await runCommand(SYSOP_BIN, ['goal', '--source', 'web', '--', '-'], goal + '\n');
        if (!r.ok) {
          return sendJson(res, r.code === 127 ? 503 : 502, {
            error: 'sysop_goal_failed',
            message: r.stderr || r.stdout || `swarmbox-sysop exited ${r.code}`,
          });
        }
        broadcast(buildSnapshot({ type: 'sysop' }));
        return sendJson(res, 200, { ok: true, goal_id: r.stdout, sysop: readSysopSnapshot(hc.listSnapshot()) });
      }

      if (pathname === '/api/sysop/approve' && req.method === 'POST') {
        const r = await runCommand(SYSOP_BIN, ['approve']);
        broadcast(buildSnapshot({ type: 'sysop' }));
        if (!r.ok) return sendJson(res, 409, { error: 'approve_failed', message: r.stderr || r.stdout || 'nothing waiting' });
        return sendJson(res, 200, { ok: true, message: r.stdout || 'allowed' });
      }

      if (pathname === '/api/sysop/veto' && req.method === 'POST') {
        const r = await runCommand(SYSOP_BIN, ['veto']);
        broadcast(buildSnapshot({ type: 'sysop' }));
        if (!r.ok) return sendJson(res, 409, { error: 'veto_failed', message: r.stderr || r.stdout || 'nothing waiting' });
        return sendJson(res, 200, { ok: true, message: r.stdout || 'cancelled' });
      }

      if (pathname === '/api/sysop/new' && req.method === 'POST') {
        startNewConversation();
        broadcast(buildSnapshot({ type: 'sysop' }));
        return sendJson(res, 200, { ok: true });
      }

      if (pathname === '/api/sysop/stop' && req.method === 'POST') {
        const r = await runCommand(SYSOP_BIN, ['stop']);
        broadcast(buildSnapshot({ type: 'sysop' }));
        if (!r.ok) return sendJson(res, 409, { error: 'stop_failed', message: r.stderr || r.stdout || 'nothing to stop' });
        return sendJson(res, 200, { ok: true, message: r.stdout || 'stopped' });
      }

      // Static frontend assets
      if (pathname === '/favicon.ico') return serveFile(res, path.join(PUBLIC_DIR, 'favicon.svg'), true);
      const rel = pathname === '/' ? 'index.html' : pathname.replace(/^\/+/, '');
      const safePath = path.normalize(path.join(PUBLIC_DIR, rel));
      if (safePath !== PUBLIC_DIR && !safePath.startsWith(PUBLIC_DIR + path.sep)) {
        res.writeHead(403, SECURITY_HEADERS);
        return res.end('Forbidden');
      }
      return serveFile(res, safePath, false);
    } catch (err) {
      return sendJson(res, 500, { error: 'internal', message: err.message });
    }
  });

  const wss = new WebSocketServer({ noServer: true });

  // WebSocket ping/pong keepalive (prevents tunnels/proxies from dropping idle PTY connections)
  const wsPingTimer = setInterval(() => {
    for (const client of wss.clients) {
      if (client.isAlive === false) {
        try { client.terminate(); } catch (_) {}
        continue;
      }
      client.isAlive = false;
      try { client.ping(); } catch (_) {}
    }
  }, 25000);
  if (wsPingTimer.unref) wsPingTimer.unref();

  server.on('upgrade', (req, socket, head) => {
    if (!checkSameOrigin(req)) {
      socket.write('HTTP/1.1 403 Forbidden\r\nConnection: close\r\n\r\n');
      socket.destroy();
      return;
    }
    const url = new URL(req.url, `http://${req.headers.host || 'localhost'}`);
    if (url.pathname === '/ws/events' || url.pathname.startsWith('/ws/pty/')) {
      wss.handleUpgrade(req, socket, head, (ws) => {
        wss.emit('connection', ws, req, url);
      });
    } else {
      socket.destroy();
    }
  });

  wss.on('connection', async (ws, _req, url) => {
    ws.isAlive = true;
    ws.on('pong', () => { ws.isAlive = true; });

    if (url.pathname === '/ws/events') {
      eventClients.add(ws);
      ws.send(JSON.stringify(buildSnapshot({ type: 'snapshot' })));
      if (typeof hc.refreshTerminals === 'function') hc.refreshTerminals();
      ws.on('close', () => eventClients.delete(ws));
      return;
    }

    const termId = decodeURIComponent(url.pathname.slice('/ws/pty/'.length));
    const cols = Number(url.searchParams.get('cols') || 100);
    const rows = Number(url.searchParams.get('rows') || 30);
    writeActiveTab(termId);
    if (typeof hc.refreshTerminals === 'function') hc.refreshTerminals();

    let stream = null;
    let hydrating = true;
    let initChunks = [];
    let flushTimer = null;
    let capTimer = null;
    let resizing = false;
    let resizeChunks = [];
    let resizeQuietTimer = null;
    let resizeCapTimer = null;

    const clearHydrationTimers = () => {
      if (flushTimer) { clearTimeout(flushTimer); flushTimer = null; }
      if (capTimer) { clearTimeout(capTimer); capTimer = null; }
    };

    const clearResizeTimers = () => {
      if (resizeQuietTimer) { clearTimeout(resizeQuietTimer); resizeQuietTimer = null; }
      if (resizeCapTimer) { clearTimeout(resizeCapTimer); resizeCapTimer = null; }
    };

    const flushInitial = () => {
      if (!hydrating) return;
      hydrating = false;
      clearHydrationTimers();
      if (ws.readyState !== 1) {
        initChunks = [];
        return;
      }
      if (initChunks.length > 0) {
        const merged = initChunks.length === 1 ? initChunks[0] : Buffer.concat(initChunks);
        initChunks = [];
        ws.send(merged);
      }
      ws.send(JSON.stringify({ type: 'hydrated' }));
    };

    const flushResize = () => {
      if (!resizing) return;
      resizing = false;
      clearResizeTimers();
      if (ws.readyState !== 1) {
        resizeChunks = [];
        return;
      }
      if (resizeChunks.length > 0) {
        const merged = resizeChunks.length === 1 ? resizeChunks[0] : Buffer.concat(resizeChunks);
        resizeChunks = [];
        ws.send(merged);
      }
      ws.send(JSON.stringify({ type: 'resized' }));
    };

    try {
      stream = await hc.attach(termId, cols, rows, {
        onData: (buf) => {
          if (hydrating) {
            initChunks.push(Buffer.from(buf));
            if (flushTimer) clearTimeout(flushTimer);
            flushTimer = setTimeout(flushInitial, 55);
            return;
          }
          if (resizing) {
            resizeChunks.push(Buffer.from(buf));
            if (resizeQuietTimer) clearTimeout(resizeQuietTimer);
            resizeQuietTimer = setTimeout(flushResize, 55);
            return;
          }
          if (ws.readyState === 1) ws.send(buf);
        },
        onClose: (info) => {
          flushInitial();
          flushResize();
          if (ws.readyState === 1) {
            ws.send(JSON.stringify({ type: 'closed', info }));
            ws.close();
          }
        },
      });
    } catch (err) {
      clearHydrationTimers();
      clearResizeTimers();
      if (ws.readyState === 1) {
        ws.send(JSON.stringify({ type: 'error', message: err.message }));
        ws.close();
      }
      return;
    }

    // If the terminal has no initial output, finish hydration promptly; otherwise cap burst at 350ms
    if (hydrating) {
      if (!flushTimer) flushTimer = setTimeout(flushInitial, 110);
      capTimer = setTimeout(flushInitial, 350);
    }

    ws.on('message', (data, isBinary) => {
      if (!stream) return;
      if (isBinary) {
        stream.write(Buffer.from(data));
        return;
      }
      const text = data.toString('utf8');
      if (text.startsWith('{')) {
        try {
          const msg = JSON.parse(text);
          if (msg.type === 'resize') {
            // Coalesce SIGWINCH full-screen TUI repaint bursts into one atomic frame
            if (!hydrating) {
              clearResizeTimers();
              resizing = true;
              resizeQuietTimer = setTimeout(flushResize, 85);
              resizeCapTimer = setTimeout(flushResize, 320);
            }
            stream.resize(msg.cols, msg.rows);
            return;
          }
          if (msg.type === 'focus') {
            if (msg.focused) writeActiveTab(termId);
            stream.focus(Boolean(msg.focused));
            return;
          }
          if (msg.type === 'input' && typeof msg.data === 'string') {
            if (resizing) flushResize();
            stream.write(Buffer.from(msg.data, 'utf8'));
            return;
          }
        } catch (_) {}
      }
      if (resizing) flushResize();
      stream.write(Buffer.from(text, 'utf8'));
    });

    ws.on('close', () => {
      clearHydrationTimers();
      clearResizeTimers();
      initChunks = [];
      resizeChunks = [];
      hydrating = false;
      resizing = false;
      if (stream) {
        stream.close();
        stream = null;
      }
    });
  });

  function shutdown() {
    clearInterval(sysopTimer);
    clearInterval(wsPingTimer);
    for (const ws of eventClients) {
      try { ws.close(); } catch (_) {}
    }
    wss.close();
    server.close();
    hc.close();
  }

  return { server, wss, hc, shutdown };
}

// Direct CLI entry point
if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const { port, iface } = parseCliArgs(process.argv.slice(2));
  const gw = createGateway();

  const onSignal = () => {
    gw.shutdown();
    process.exit(0);
  };
  process.on('SIGTERM', onSignal);
  process.on('SIGINT', onSignal);

  gw.hc
    .start()
    .then(() => {
      gw.server.listen(port, iface, () => {
        console.log(`swarmbox-herdr-web: listening on http://${iface}:${port}`);
      });
    })
    .catch((err) => {
      console.error('swarmbox-herdr-web: failed to connect to herdr-core:', err.message);
      process.exit(1);
    });
}
