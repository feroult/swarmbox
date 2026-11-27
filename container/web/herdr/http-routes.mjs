// Web UI HTTP gateway routes, security/origin guards, static/vendor serving, and REST API handlers.

import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { agentIconPath, browserRegistry, getAgent, resolveAgent } from './agents.mjs';
import {
  ADDON_BIN,
  HERDR_THEMES,
  HOME,
  SB_RUN_DIR,
  SYSOP_BIN,
  buildAgentArgv,
  buildPinsSnapshot,
  cleanSessionTitle,
  contextRepoTop,
  defaultTitleForPath,
  detectTerminalAgent,
  isHiddenTerminal,
  listInstalledAgents,
  makePinId,
  normalizeAgentName,
  noteRecentDir,
  readActiveTab,
  readBoxConfigSnapshot,
  readContextText,
  readPins,
  readRecentDirs,
  readSessionPrefs,
  readSysopSnapshot,
  readWorktreePrefs,
  resolveDefaultAgent,
  runCommand,
  runCommandEnv,
  saveTheme,
  startNewConversation,
  terminalCwd,
  uniqueTabName,
  writeActiveTab,
  writePins,
  writeSessionPrefs,
  writeWorktreePrefs,
} from './hc-client.mjs';
import {
  decodeRawPath,
  listDirectory,
  readTextFile,
  resolveAndStat,
  sandboxHeadersForRaw,
} from './file-preview.mjs';
import {
  describeDir,
  discoverProjects,
  enrichTerminalsWithRepo,
  listChildDirs,
  listRecentDirs,
  normRealPath,
} from './repo-discovery.mjs';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const PUBLIC_DIR = path.join(__dirname, 'public');
const FONTS_DIR = path.join(__dirname, 'fonts');
const NODE_MODULES = path.join(__dirname, 'node_modules');

// Local xterm.js & full JetBrains Mono + Noto Symbols + Nerd Font vendor bundles (zero CDN dependency)
const VENDOR_ASSETS = new Map([
  ['/vendor/xterm.js', path.join(NODE_MODULES, '@xterm/xterm/lib/xterm.js')],
  ['/vendor/xterm.css', path.join(NODE_MODULES, '@xterm/xterm/css/xterm.css')],
  ['/vendor/addon-fit.js', path.join(NODE_MODULES, '@xterm/addon-fit/lib/addon-fit.js')],
  ['/vendor/addon-web-links.js', path.join(NODE_MODULES, '@xterm/addon-web-links/lib/addon-web-links.js')],
  ['/vendor/addon-canvas.js', path.join(NODE_MODULES, '@xterm/addon-canvas/lib/addon-canvas.js')],
  ['/vendor/addon-unicode11.js', path.join(NODE_MODULES, '@xterm/addon-unicode11/lib/addon-unicode11.js')],
  ['/vendor/fonts/JetBrainsMono-Regular.woff2', path.join(FONTS_DIR, 'JetBrainsMono-Regular.woff2')],
  ['/vendor/fonts/JetBrainsMono-SemiBold.woff2', path.join(FONTS_DIR, 'JetBrainsMono-SemiBold.woff2')],
  ['/vendor/fonts/JetBrainsMono-Bold.woff2', path.join(FONTS_DIR, 'JetBrainsMono-Bold.woff2')],
  ['/vendor/fonts/JetBrainsMono-Italic.woff2', path.join(FONTS_DIR, 'JetBrainsMono-Italic.woff2')],
  ['/vendor/fonts/noto-symbols-braille.woff2', path.join(NODE_MODULES, '@fontsource/noto-sans-symbols-2/files/noto-sans-symbols-2-braille-400-normal.woff2')],
  ['/vendor/fonts/noto-symbols-math.woff2', path.join(NODE_MODULES, '@fontsource/noto-sans-symbols-2/files/noto-sans-symbols-2-math-400-normal.woff2')],
  ['/vendor/fonts/noto-symbols.woff2', path.join(NODE_MODULES, '@fontsource/noto-sans-symbols-2/files/noto-sans-symbols-2-symbols-400-normal.woff2')],
  ['/vendor/fonts/nerd-symbols.woff2', path.join(NODE_MODULES, '@azurity/pure-nerd-font/PureNerdFont.woff2')],
]);

// ---------------------------------------------------------------------------
// Security & HTTP helpers
// ---------------------------------------------------------------------------
export const SECURITY_HEADERS = {
  'Content-Security-Policy': "frame-ancestors 'self'",
  'X-Frame-Options': 'SAMEORIGIN',
  'X-Content-Type-Options': 'nosniff',
};

export const MIME = {
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

export function isLoopbackAddress(addr) {
  const ip = String(addr || '').trim().toLowerCase();
  return ip === '127.0.0.1' || ip === '::1' || ip === '::ffff:127.0.0.1';
}

export function validateOpenUrl(raw) {
  if (typeof raw !== 'string') return null;
  const url = raw.trim();
  if (!url || url.length > 4096) return null;
  if (/[\x00-\x1f\x7f\s]/.test(url)) return null;
  try {
    const parsed = new URL(url);
    if ((parsed.protocol !== 'http:' && parsed.protocol !== 'https:') || !parsed.host) return null;
    return url;
  } catch (_) {
    return null;
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

function resolveWorktreeTarget(reqPath, tid, hc) {
  const explicit = String(reqPath || '');
  const terminal = tid ? hc.terminals.get(tid) : null;
  if (explicit) return { target: explicit, terminal };
  if (terminal) {
    return {
      target: (terminal.labels && terminal.labels['swarmbox.worktree']) || terminalCwd(terminal),
      terminal,
    };
  }
  return { target: '', terminal };
}

export function createHttpHandler({ hc, hub, worktreeHub, ptyBridge, runWt }) {
  return async (req, res) => {
    const url = new URL(req.url, `http://${req.headers.host || 'localhost'}`);
    const pathname = url.pathname;

    try {
      // Origin guard on all mutating API routes
      if (pathname.startsWith('/api/') && req.method !== 'GET' && req.method !== 'HEAD') {
        if (!checkSameOrigin(req)) {
          return sendJson(res, 403, { error: 'bad_origin', message: 'cross-origin calls are not allowed' });
        }
      }

      const vendorFile = VENDOR_ASSETS.get(pathname);
      if (vendorFile) return serveFile(res, vendorFile, true);

      // Health & state
      if (pathname === '/api/health' && req.method === 'GET') {
        const snap = hub.buildSnapshot();
        return sendJson(res, 200, {
          ok: true,
          mux: 'herdr',
          herdr: Boolean(hc.proc),
          tabs: snap.terminals.length,
          sysop_up: snap.sysop.up,
          theme: hub.getTheme(),
          home: HOME,
        });
      }

      if (pathname === '/api/theme' && req.method === 'GET') {
        const theme = hub.refreshTheme();
        return sendJson(res, 200, { theme, themes: Object.keys(HERDR_THEMES) });
      }
      if (pathname === '/api/theme' && req.method === 'POST') {
        const body = await readBody(req);
        const name = String(body.theme || '');
        if (!HERDR_THEMES[name]) return sendJson(res, 400, { error: 'unknown_theme' });
        hub.setTheme(name);
        saveTheme(name);
        hub.broadcast(hub.buildSnapshot({ type: 'theme' }));
        return sendJson(res, 200, { ok: true, theme: hub.getTheme() });
      }

      if (pathname === '/api/open-url' && req.method === 'POST') {
        const remote = req.socket && req.socket.remoteAddress;
        if (!isLoopbackAddress(remote)) {
          return sendJson(res, 403, { error: 'forbidden', message: 'loopback only' });
        }
        const body = await readBody(req, 16 * 1024);
        const targetUrl = validateOpenUrl(body && body.url);
        if (!targetUrl) {
          return sendJson(res, 400, { error: 'invalid_url', message: 'only http:// and https:// URLs are supported' });
        }
        let delivered = 0;
        for (const ws of hub.eventClients) {
          if (ws.readyState === 1) delivered += 1;
        }
        if (delivered > 0) {
          hub.broadcast({ type: 'open_url', url: targetUrl, ts: Date.now() });
        }
        return sendJson(res, 200, { ok: true, delivered });
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

      // The agent registry for the page (docs/agents-design.md): /agents.js sets window.SWARMBOX_AGENTS before app.js runs, so the first
      // render already knows which tabs are agents; /api/agents refreshes it; /agents/<id>/icon.svg is an agent's icon as a file.
      if (pathname === '/agents.js' && req.method === 'GET') {
        const body = `window.SWARMBOX_AGENTS = ${JSON.stringify(browserRegistry()).replace(/</g, '\\u003c')};\n`;
        res.writeHead(200, { ...SECURITY_HEADERS, 'Content-Type': 'text/javascript; charset=utf-8', 'Cache-Control': 'no-store' });
        return res.end(body);
      }
      if (pathname === '/api/agents' && req.method === 'GET') {
        return sendJson(res, 200, browserRegistry());
      }
      {
        const m = /^\/agents\/([a-z0-9][a-z0-9_-]*)\/icon\.svg$/.exec(pathname);
        if (m && req.method === 'GET') {
          const icon = resolveAgent(m[1]) === m[1] ? agentIconPath(m[1]) : '';
          if (!icon) return sendJson(res, 404, { error: 'no_icon', message: 'no such agent or it has no icon' });
          return serveFile(res, icon, false);
        }
      }

      if (pathname === '/api/config' && req.method === 'GET') {
        const theme = hub.refreshTheme();
        const cfg = readBoxConfigSnapshot(hc.listSnapshot());
        cfg.theme = theme;
        return sendJson(res, 200, cfg);
      }

      // Settings > Addons: install, update (a managed addon installed again: the newest release of a floating one, the version the
      // image names for a pinned one; an addon that updates itself is not offered) and remove (the install only, never its settings).
      const addonMatch = pathname.match(/^\/api\/addons\/([a-z0-9][a-z0-9_-]{0,40})\/(install|update|remove)$/);
      if (addonMatch && req.method === 'POST') {
        const [, addonName, action] = addonMatch;
        const curCfg = readBoxConfigSnapshot(hc.listSnapshot());
        const addon = curCfg.addons.find((a) => a.name === addonName);
        if (!addon) {
          return sendJson(res, 404, { error: 'unknown_addon', message: `Addon "${addonName}" not found` });
        }
        if ((action === 'update' && !addon.canUpdate) || (action === 'remove' && !addon.canRemove)) {
          return sendJson(res, 409, { error: `addon_${action}_refused`, message: `${addonName} cannot be ${action === 'update' ? 'updated' : 'removed'} here` });
        }
        const args = { install: ['install', addonName], update: ['install', addonName, '--force'], remove: ['remove', addonName] }[action];
        const r = await runCommand(ADDON_BIN, args, null, 180000);
        if (!r.ok) {
          return sendJson(res, 502, {
            error: `addon_${action}_failed`,
            message: r.stderr || r.stdout || `swarmbox-addon ${args.join(' ')} failed`,
          });
        }
        if (action !== 'remove') await runCommand(ADDON_BIN, ['prepare'], null, 60000);
        hub.broadcast(hub.buildSnapshot({ type: 'sysop' }));
        return sendJson(res, 200, {
          ok: true,
          addon: addonName,
          action,
          message: r.stdout || `${addonName}: ${action} done`,
          config: readBoxConfigSnapshot(hc.listSnapshot()),
        });
      }

      if (pathname === '/api/tabs' && req.method === 'GET') {
        const resList = await hc.call('terminal.list', { all: false });
        const rawTerminals = (resList.terminals || []).filter((t) => t.state === 'live' && !isHiddenTerminal(t));
        const terminals = enrichTerminalsWithRepo(rawTerminals);
        const pins = buildPinsSnapshot(rawTerminals);
        return sendJson(res, 200, {
          terminals,
          active: readActiveTab(),
          sysop: readSysopSnapshot(rawTerminals),
          theme: hub.getTheme(),
          pins,
          worktrees: worktreeHub.pendingWorktreesFor(rawTerminals, pins),
          worktree_prefs: readWorktreePrefs(),
          session_prefs: readSessionPrefs(),
          installed_agents: listInstalledAgents(),
          home: HOME,
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
          // A named agent, else the default agent of the box, else `yolo` (which explains in the tab that there is none).
          const defaultAgent = resolveDefaultAgent();
          const requested = String(body.agent || '').trim().toLowerCase();
          const named = requested !== 'yolo' ? normalizeAgentName(requested) : '';
          const cmd = named || (!requested && defaultAgent) || 'yolo';
          agentKind = cmd === 'yolo' ? (defaultAgent || 'yolo') : cmd;
          argv = buildAgentArgv(cmd, body.resume === 'continue' ? 'continue' : 'fresh', process.env, { context: body.context !== false });
          prefix = cmd === 'yolo' ? 'agent' : cmd;
        }

        const labels = {};
        if (agentKind && agentKind !== 'shell') labels['swarmbox.agent'] = agentKind;
        if (preset === 'agent' && body.persist === false) labels['swarmbox.persist'] = 'off';
        let createdWorktree = null;
        const requestedCwd = cwd;

        if (preset === 'agent' && worktreeChoice !== 'same') {
          const collision = await worktreeHub.detectWorkingTreeCollision(cwd, liveTerms);
          if (worktreeChoice === 'new' || (collision && prefs.mode === 'auto')) {
            try {
              const wtRes = await runWt(['create', cwd]);
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
          // Unticked "Repository context" in the New agent box: a restart of this pin starts without it too
          if (body.context === false) autoPin.context = false;
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
        if (body.cwd) noteRecentDir(requestedCwd);
        if (createdWorktree) worktreeHub.refreshPendingWorktrees();
        hub.broadcast(hub.buildSnapshot({ type: 'snapshot' }));
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
          hub.broadcast(hub.buildSnapshot({ type: 'snapshot' }));
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
          const wtHold = wtPath ? normRealPath(wtPath) : '';
          if (wtHold) worktreeHub.closingWorktrees.add(wtHold);
          let autoCleaned = false;
          try {
            await worktreeHub.closeTerminalCleanly(termId);
            // Auto-clean empty managed worktrees on close when no parked pin holds them
            if (!pinKept && wtPath) {
              try {
                const st = await runWt(['status', wtPath]);
                if (st && st.managed && st.empty) {
                  await runWt(['remove', wtPath]);
                  autoCleaned = true;
                  worktreeHub.forgetCachedWorktree(wtPath, wtHold);
                }
              } catch (_) {}
            }
          } finally {
            if (wtHold) worktreeHub.closingWorktrees.delete(wtHold);
          }
          worktreeHub.refreshPendingWorktrees();
          hub.broadcast(hub.buildSnapshot({ type: 'snapshot' }));
          return sendJson(res, 200, { ok: true, pinned: pinKept, auto_cleaned_worktree: autoCleaned });
        }
        if (action === 'worktree' && req.method === 'GET') {
          const { target, terminal: t } = resolveWorktreeTarget('', termId, hc);
          if (!t) return sendJson(res, 404, { error: 'no_such_tab', message: 'tab not found' });
          try {
            const st = await runWt(['status', target]);
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
          // The Allow / Cancel card of a blocked agent: the keys its agent.conf declares (ANSWER_ALLOW, ANSWER_DENY: hc key names), pressed
          // as keys. An agent that declares none is answered in its own terminal, never with a guess: a typed `n` and Enter confirm the
          // highlighted option of a menu, which in a permission dialog is the one that allows (measured with Claude Code 2.1).
          const body = await readBody(req);
          if (typeof body.text === 'string') {
            const r = await hc.call('terminal.send', { terminal: termId, text: body.text, force: true });
            return sendJson(res, 200, { ok: true, result: r });
          }
          const aid = detectTerminalAgent(hc.terminals.get(termId));
          const a = aid ? getAgent(aid) : null;
          const keys = a ? (body.decision === 'allow' ? a.answer.allow : a.answer.deny) : [];
          if (!keys.length) {
            return sendJson(res, 409, { error: 'no_answer_keys', message: 'this agent does not say how its dialog is answered: answer it in its terminal' });
          }
          const r = await hc.call('terminal.keys', { terminal: termId, keys });
          return sendJson(res, 200, { ok: true, result: r, keys });
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
              const inf = await runWt(['inspect', cwd]);
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
          hub.broadcast(hub.buildSnapshot({ type: 'snapshot' }));
          return sendJson(res, 201, { ok: true, pin: rec, pins: buildPinsSnapshot(hc.listSnapshot()) });
        }
        const cwd = typeof body.cwd === 'string' && body.cwd.startsWith('/') ? body.cwd : HOME;
        // an agent is stored by its id; yolo as the default agent it runs (a pin keeps its agent), or as yolo when the box has none
        const agent = normalizeAgentName(body.agent) || (body.agent === 'yolo' ? resolveDefaultAgent() || 'yolo' : 'shell');
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
        hub.broadcast(hub.buildSnapshot({ type: 'snapshot' }));
        return sendJson(res, 201, { ok: true, pin: rec, pins: buildPinsSnapshot(hc.listSnapshot()) });
      }

      if (pathname === '/api/pins/prefs' && req.method === 'GET') {
        return sendJson(res, 200, { prefs: readSessionPrefs() });
      }
      if (pathname === '/api/pins/prefs' && req.method === 'PATCH') {
        const body = await readBody(req);
        try {
          const prefs = writeSessionPrefs(body);
          hub.broadcast(hub.buildSnapshot({ type: 'snapshot' }));
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
          hub.broadcast(hub.buildSnapshot({ type: 'snapshot' }));
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
          hub.broadcast(hub.buildSnapshot({ type: 'snapshot' }));
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
            const collision = await worktreeHub.detectWorkingTreeCollision(cwd, liveTerms);
            if (worktreeChoice === 'new' || (collision && prefs.mode === 'auto')) {
              try {
                const wtRes = await runWt(['create', cwd]);
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

          const argv = buildAgentArgv(pin.agent || 'shell', resumeMode, process.env, { context: pin.context !== false });
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
          if (createdWorktree) worktreeHub.refreshPendingWorktrees();
          hub.broadcast(hub.buildSnapshot({ type: 'snapshot' }));
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
          const list = await runWt(['list']);
          const worktrees = worktreeHub.setCachedWorktrees(list);
          return sendJson(res, 200, {
            worktrees,
            pending: worktreeHub.pendingWorktreesFor(hc.listSnapshot(), readPins()),
            prefs: readWorktreePrefs(),
          });
        } catch (err) {
          return sendJson(res, 500, { error: err.code || 'worktree_error', message: err.message });
        }
      }

      if (pathname === '/api/projects' && req.method === 'GET') {
        const live = hc.listSnapshot();
        const pinsNow = readPins();
        const projects = discoverProjects(live, pinsNow);
        const recent = listRecentDirs(live, pinsNow, readRecentDirs());
        return sendJson(res, 200, { projects, recent, home: HOME });
      }

      if (pathname === '/api/dirs' && req.method === 'GET') {
        const raw = url.searchParams.get('path') || HOME;
        const listing = listChildDirs(raw.startsWith('/') ? raw : HOME);
        if (!listing) return sendJson(res, 404, { error: 'not_a_dir', message: `Not a readable folder: ${raw}` });
        return sendJson(res, 200, { ...listing, home: HOME, self: describeDir(listing.path) });
      }

      if (pathname === '/api/worktrees/check' && req.method === 'GET') {
        const rawCwd = url.searchParams.get('cwd') || '';
        const cwd = rawCwd && rawCwd.startsWith('/') ? rawCwd : HOME;
        const info = await worktreeHub.inspectWorkingTreeForCwd(cwd, hc.listSnapshot());
        return sendJson(res, 200, info);
      }

      if (pathname === '/api/worktrees/prefs' && req.method === 'PATCH') {
        const body = await readBody(req);
        try {
          const prefs = writeWorktreePrefs(body);
          hub.broadcast(hub.buildSnapshot({ type: 'snapshot' }));
          return sendJson(res, 200, { ok: true, prefs });
        } catch (err) {
          return sendJson(res, 400, { error: 'bad_prefs', message: err.message });
        }
      }

      if (pathname === '/api/worktrees/status' && req.method === 'GET') {
        const { target } = resolveWorktreeTarget(url.searchParams.get('path'), url.searchParams.get('terminal') || '', hc);
        if (!target) return sendJson(res, 400, { error: 'bad_arg', message: 'path or terminal required' });
        try {
          const st = await runWt(['status', target]);
          return sendJson(res, 200, st);
        } catch (err) {
          return sendJson(res, 404, { error: err.code || 'not_a_worktree', message: err.message });
        }
      }

      if (pathname === '/api/worktrees/repo-status' && req.method === 'GET') {
        const repo = url.searchParams.get('repo') || '';
        if (!repo) return sendJson(res, 400, { error: 'bad_arg', message: 'repo required' });
        try {
          const st = await worktreeHub.refreshRepoStatus(repo, { throwOnError: true });
          const mainTerm = worktreeHub.findMainAgentTerminal((st && st.repo_root) || repo, hc.listSnapshot());
          return sendJson(res, 200, {
            ...(st || {}),
            main_agent: worktreeHub.formatMainAgent(mainTerm),
          });
        } catch (err) {
          return sendJson(res, 404, { error: err.code || 'repo_status_error', message: err.message });
        }
      }

      if (pathname === '/api/worktrees/diff' && req.method === 'GET') {
        const { target: wtPath } = resolveWorktreeTarget(url.searchParams.get('path'), url.searchParams.get('terminal') || '', hc);
        if (!wtPath) return sendJson(res, 400, { error: 'bad_arg', message: 'path or terminal required' });
        const file = url.searchParams.get('file') || '';
        try {
          const diffRes = await runWt(['diff', wtPath, ...(file ? ['--file', file] : [])]);
          return sendJson(res, 200, diffRes);
        } catch (err) {
          return sendJson(res, 404, { error: err.code || 'diff_error', message: err.message });
        }
      }

      if (pathname === '/api/worktrees/sync' && req.method === 'POST') {
        const body = await readBody(req);
        const tid = body.terminal ? String(body.terminal) : '';
        const { target: wtPath, terminal: t } = resolveWorktreeTarget(body.path, tid, hc);
        if (!wtPath) return sendJson(res, 400, { error: 'bad_arg', message: 'path or terminal required' });
        const args = ['sync', wtPath];
        if (body.rebase) args.push('--rebase');
        try {
          const resSync = await runWt(args);
          const repoRoot = (resSync && resSync.repo_root) || (t && t.labels && t.labels['swarmbox.repo']) || '';
          if (repoRoot) await worktreeHub.refreshRepoStatus(repoRoot).catch(() => {});
          worktreeHub.refreshPendingWorktrees();
          hub.broadcast(hub.buildSnapshot({ type: 'snapshot' }));
          return sendJson(res, 200, resSync);
        } catch (err) {
          return sendJson(res, 409, { error: err.code || 'sync_failed', message: err.message, ...(err.data || {}) });
        }
      }

      if (pathname === '/api/worktrees/merge' && req.method === 'POST') {
        const body = await readBody(req);
        const tid = body.terminal ? String(body.terminal) : '';
        const { target: wtPath, terminal: t } = resolveWorktreeTarget(body.path, tid, hc);
        if (!wtPath) return sendJson(res, 400, { error: 'bad_arg', message: 'path or terminal required' });
        const args = ['merge', wtPath];
        if (body.squash) args.push('--squash');
        if (body.clean) args.push('--clean');
        try {
          const resMerge = await runWt(args);
          if (body.clean) {
            const pinId = (t && t.labels && t.labels['swarmbox.pin_id']) || '';
            worktreeHub.purgePinsForWorktree(wtPath, pinId);
            worktreeHub.forgetCachedWorktree(wtPath);
            if (tid) await worktreeHub.closeTerminalCleanly(tid);
          }
          const repoRoot = (resMerge && resMerge.repo_root) || (t && t.labels && t.labels['swarmbox.repo']) || '';
          if (repoRoot) await worktreeHub.refreshRepoStatus(repoRoot).catch(() => {});
          const doVerify = Boolean(body.verify || body.verify_and_push);
          const doPush = Boolean(body.push || body.verify_and_push);
          let handoff = null;
          if (doVerify && repoRoot) {
            handoff = await worktreeHub.runHybridVerifyAndPush(repoRoot, {
              mergedBranches: resMerge && resMerge.branch ? [resMerge.branch] : [],
              commitsSummary: (resMerge && Array.isArray(resMerge.commits_list)) ? resMerge.commits_list : [],
              files: (resMerge && Array.isArray(resMerge.files)) ? resMerge.files : [],
              push: doPush,
            });
          }
          worktreeHub.refreshPendingWorktrees();
          hub.broadcast(hub.buildSnapshot({ type: 'snapshot' }));
          return sendJson(res, 200, handoff ? { ...resMerge, handoff } : resMerge);
        } catch (err) {
          return sendJson(res, 409, { error: err.code || 'merge_failed', message: err.message, ...(err.data || {}) });
        }
      }

      if (pathname === '/api/worktrees/merge-all' && req.method === 'POST') {
        const body = await readBody(req);
        const repo = String(body.repo || '');
        if (!repo) return sendJson(res, 400, { error: 'bad_arg', message: 'repo required' });
        const repoReal = normRealPath(repo);
        let list = [];
        try {
          const rawList = await runWt(['list', repo]);
          list = Array.isArray(rawList) ? rawList : [];
        } catch (err) {
          return sendJson(res, 500, { error: err.code || 'list_failed', message: err.message });
        }

        const liveTerms = hc.listSnapshot();
        const termByWtPath = new Map();
        for (const t of liveTerms) {
          const p = (t.labels && t.labels['swarmbox.worktree']) || terminalCwd(t);
          if (p) {
            const rp = normRealPath(p);
            if (!termByWtPath.has(rp)) termByWtPath.set(rp, []);
            termByWtPath.get(rp).push(t);
          }
        }

        const candidates = list.filter((w) => {
          if (!w || !w.path) return false;
          if (w.repo_root && normRealPath(w.repo_root) !== repoReal) return false;
          return !w.dirty && Number(w.ahead) > 0 && Boolean(w.can_merge);
        });

        const merged = [];
        const failed = [];
        const mergedBranches = [];
        const commitsSummary = [];
        const filesSet = new Set();

        for (const w of candidates) {
          const args = ['merge', w.path];
          if (body.squash) args.push('--squash');
          if (body.clean) args.push('--clean');
          try {
            const resMerge = await runWt(args);
            merged.push({ ...resMerge, path: w.path, branch: (resMerge && resMerge.branch) || w.branch });
            if ((resMerge && resMerge.branch) || w.branch) {
              mergedBranches.push((resMerge && resMerge.branch) || w.branch);
            }
            if (resMerge && Array.isArray(resMerge.commits_list)) {
              commitsSummary.push(...resMerge.commits_list);
            }
            if (resMerge && Array.isArray(resMerge.files)) {
              for (const f of resMerge.files) filesSet.add(f);
            }
            if (body.clean) {
              worktreeHub.forgetCachedWorktree(w.path);
              const matchingTerms = termByWtPath.get(normRealPath(w.path)) || [];
              if (matchingTerms.length > 0) {
                for (const mt of matchingTerms) {
                  const pinId = (mt.labels && mt.labels['swarmbox.pin_id']) || '';
                  worktreeHub.purgePinsForWorktree(w.path, pinId);
                  await worktreeHub.closeTerminalCleanly(mt.address);
                }
              } else {
                worktreeHub.purgePinsForWorktree(w.path, '');
              }
            }
          } catch (err) {
            failed.push({
              path: w.path,
              branch: w.branch,
              error: err.code || 'merge_failed',
              message: err.message,
              ...(err.data || {}),
            });
            break;
          }
        }

        await worktreeHub.refreshRepoStatus(repo).catch(() => {});
        const doVerifyAll = Boolean(body.verify || body.verify_and_push);
        const doPushAll = Boolean(body.push || body.verify_and_push);
        let handoff = null;
        if (merged.length > 0 && doVerifyAll) {
          handoff = await worktreeHub.runHybridVerifyAndPush(repo, {
            mergedBranches,
            commitsSummary,
            files: Array.from(filesSet),
            push: doPushAll,
          });
        }
        worktreeHub.refreshPendingWorktrees();
        hub.broadcast(hub.buildSnapshot({ type: 'snapshot' }));
        return sendJson(res, 200, { ok: true, merged, failed, handoff });
      }

      if (pathname === '/api/worktrees/main/action' && req.method === 'POST') {
        const body = await readBody(req);
        const repo = String(body.repo || '');
        const action = String(body.action || '');
        if (!repo || !action) {
          return sendJson(res, 400, { error: 'bad_arg', message: 'repo and action required' });
        }
        const key = repo.replace(/\/+$/, '') || repo;

        if (action === 'commit') {
          const mainTerm = worktreeHub.findMainAgentTerminal(key, hc.listSnapshot());
          if (!mainTerm) {
            return sendJson(res, 409, { error: 'no_main_agent', message: 'No active agent terminal on main for this repository' });
          }
          const prompt = 'Review the uncommitted changes on main, run relevant tests if needed, and create a clean git commit.';
          const r = await ptyBridge.typePrompt(mainTerm.address, prompt);
          return sendJson(res, 200, { ok: true, action: 'commit', terminal: mainTerm.address, result: r });
        }

        if (action === 'verify' || action === 'verify_and_push') {
          await worktreeHub.refreshRepoStatus(key).catch(() => {});
          const handoff = await worktreeHub.runHybridVerifyAndPush(key, {
            mergedBranches: [],
            push: action === 'verify_and_push',
          });
          return sendJson(res, 200, { ok: true, action, handoff });
        }

        if (action === 'push') {
          try {
            const r = await runWt(['push', key]);
            const curJob = worktreeHub.verifyJobs.get(key);
            if (curJob && curJob.state === 'passed') {
              worktreeHub.verifyJobs.set(key, { ...curJob, state: 'pushed', error: null, finished_at: Date.now() });
            }
            await worktreeHub.refreshRepoStatus(key).catch(() => {});
            hub.broadcast(hub.buildSnapshot({ type: 'snapshot' }));
            return sendJson(res, 200, { ok: true, ...(r || {}) });
          } catch (err) {
            return sendJson(res, 409, { error: err.code || 'push_failed', message: err.message, ...(err.data || {}) });
          }
        }

        if (action === 'undo_merge') {
          try {
            const r = await runWt(['undo-merge', key]);
            const curJob = worktreeHub.verifyJobs.get(key);
            if (curJob && curJob.state === 'failed') worktreeHub.verifyJobs.delete(key);
            const rKey = (r && r.repo_root && String(r.repo_root).replace(/\/+$/, '')) || '';
            if (rKey && worktreeHub.verifyJobs.get(rKey) && worktreeHub.verifyJobs.get(rKey).state === 'failed') {
              worktreeHub.verifyJobs.delete(rKey);
            }
            await worktreeHub.refreshRepoStatus(key).catch(() => {});
            hub.broadcast(hub.buildSnapshot({ type: 'snapshot' }));
            return sendJson(res, 200, { ok: true, ...(r || {}) });
          } catch (err) {
            return sendJson(res, 409, { error: err.code || 'undo_merge_failed', message: err.message, ...(err.data || {}) });
          }
        }

        return sendJson(res, 400, { error: 'unknown_action', message: `unsupported action: ${action}` });
      }

      if (pathname === '/api/worktrees/remove' && req.method === 'POST') {
        const body = await readBody(req);
        const wtPath = String(body.path || '');
        if (!wtPath) return sendJson(res, 400, { error: 'bad_arg', message: 'path required' });
        const args = ['remove', wtPath];
        if (body.force) args.push('--force');
        try {
          const r = await runWt(args);
          const tid = body.terminal ? String(body.terminal) : '';
          const t = tid ? hc.terminals.get(tid) : null;
          const pinId = (t && t.labels && t.labels['swarmbox.pin_id']) || '';
          worktreeHub.purgePinsForWorktree(wtPath, pinId);
          worktreeHub.forgetCachedWorktree(wtPath);
          if (tid) await worktreeHub.closeTerminalCleanly(tid);
          const repoRoot = (r && r.repo_root) || (t && t.labels && t.labels['swarmbox.repo']) || '';
          if (repoRoot) await worktreeHub.refreshRepoStatus(repoRoot).catch(() => {});
          worktreeHub.refreshPendingWorktrees();
          hub.broadcast(hub.buildSnapshot({ type: 'snapshot' }));
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
        const st = await runWt(['status', wtPath]).catch(() => null);
        // The agent asked for, else the default agent of the box, else a shell: never an agent the box may not have.
        const reqAgent = String(body.agent || '').trim().toLowerCase();
        const cmd = normalizeAgentName(reqAgent) || resolveDefaultAgent() || (reqAgent === 'yolo' ? 'yolo' : '') || 'shell';
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
        worktreeHub.refreshPendingWorktrees();
        hub.broadcast(hub.buildSnapshot({ type: 'snapshot' }));
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
        const r = await ptyBridge.typePrompt(tid, prompt);
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
        hub.broadcast(hub.buildSnapshot({ type: 'sysop' }));
        return sendJson(res, 200, { ok: true, goal_id: r.stdout, sysop: readSysopSnapshot(hc.listSnapshot()) });
      }

      if (pathname === '/api/sysop/approve' && req.method === 'POST') {
        const r = await runCommand(SYSOP_BIN, ['approve']);
        hub.broadcast(hub.buildSnapshot({ type: 'sysop' }));
        if (!r.ok) return sendJson(res, 409, { error: 'approve_failed', message: r.stderr || r.stdout || 'nothing waiting' });
        return sendJson(res, 200, { ok: true, message: r.stdout || 'allowed' });
      }

      if (pathname === '/api/sysop/veto' && req.method === 'POST') {
        const r = await runCommand(SYSOP_BIN, ['veto']);
        hub.broadcast(hub.buildSnapshot({ type: 'sysop' }));
        if (!r.ok) return sendJson(res, 409, { error: 'veto_failed', message: r.stderr || r.stdout || 'nothing waiting' });
        return sendJson(res, 200, { ok: true, message: r.stdout || 'cancelled' });
      }

      // Repository context (sysop.autocontext): the text a session started with, or the current digest of a repository
      if (pathname === '/api/sysop/context' && req.method === 'GET') {
        const got = readContextText({ tab: url.searchParams.get('tab') || '', key: url.searchParams.get('key') || '' });
        if (!got) return sendJson(res, 404, { error: 'no_context', message: 'no repository context for that' });
        return sendJson(res, 200, { ok: true, ...got });
      }

      // Rewrite: the sysop writes the digest of the repository again now (the panel shows the call)
      // How far the digest is from a folder's commit (the New agent box says whether the session waits for a new one); writes nothing
      if (pathname === '/api/sysop/context/check' && req.method === 'GET') {
        const cwd = url.searchParams.get('cwd') || '';
        if (!cwd.startsWith('/') || !fs.existsSync(cwd)) return sendJson(res, 400, { error: 'bad_arg', message: 'an absolute folder is required' });
        const r = await runCommand(SYSOP_BIN, ['context', '--check', cwd], null, 8000);
        let info = null;
        try { info = r.ok ? JSON.parse(r.stdout) : null; } catch (_) { info = null; }
        if (!info || typeof info !== 'object') return sendJson(res, 200, { ok: false });
        return sendJson(res, 200, {
          ok: true,
          need: typeof info.need === 'string' ? info.need : null,
          wait: info.wait === true,
          changes: Number.isFinite(info.changes) ? info.changes : null,
          at: Number.isFinite(info.at) ? info.at * 1000 : 0,
        });
      }

      if (pathname === '/api/sysop/context/rewrite' && req.method === 'POST') {
        const body = await readBody(req);
        const top = contextRepoTop(String(body.key || ''));
        if (!top) return sendJson(res, 404, { error: 'no_repo', message: 'no repository with that digest' });
        // the tab that asked rides in the environment: an older sysop ignores it instead of refusing an unknown option
        const tab = String(body.tab || '');
        const env = { ...process.env, SWARMBOX_SYSOP_CONTEXT_TAB: /^[A-Za-z0-9_.:@-]{1,64}$/.test(tab) ? tab : '' };
        runCommandEnv(SYSOP_BIN, ['context', '--force', top], env, 180000).then(() => hub.broadcast(hub.buildSnapshot({ type: 'sysop' })));
        return sendJson(res, 202, { ok: true });
      }

      if (pathname === '/api/sysop/new' && req.method === 'POST') {
        startNewConversation();
        hub.broadcast(hub.buildSnapshot({ type: 'sysop' }));
        return sendJson(res, 200, { ok: true });
      }

      if (pathname === '/api/sysop/stop' && req.method === 'POST') {
        const body = await readBody(req).catch(() => ({}));
        const rawId = body && body.goal_id ? String(body.goal_id).trim() : '';
        const goalId = /^[A-Za-z0-9._-]{1,64}$/.test(rawId) ? rawId : '';
        const r = await runCommand(SYSOP_BIN, goalId ? ['stop', goalId] : ['stop']);
        hub.broadcast(hub.buildSnapshot({ type: 'sysop' }));
        if (!r.ok) return sendJson(res, 409, { error: 'stop_failed', message: r.stderr || r.stdout || 'nothing to stop' });
        return sendJson(res, 200, { ok: true, message: r.stdout || 'stopped' });
      }

      // ---------------------------------------------------------------------
      // Local File Preview API (read-only, rooted at HOME and /tmp)
      // ---------------------------------------------------------------------
      if (pathname === '/api/files/stat' && req.method === 'GET') {
        const p = url.searchParams.get('path') || '';
        const cwd = url.searchParams.get('cwd') || '';
        const fallbackDir = url.searchParams.get('fallbackDir') || '';
        const info = resolveAndStat(p, { cwd, fallbackDir, homeDir: HOME });
        if (!info.ok) return sendJson(res, info.status || 404, { ok: false, error: info.error, message: info.message });
        return sendJson(res, 200, info);
      }

      if (pathname === '/api/files/list' && req.method === 'GET') {
        const p = url.searchParams.get('path') || '';
        const cwd = url.searchParams.get('cwd') || '';
        const fallbackDir = url.searchParams.get('fallbackDir') || '';
        const info = resolveAndStat(p, { cwd, fallbackDir, homeDir: HOME });
        if (!info.ok) return sendJson(res, info.status || 404, { ok: false, error: info.error, message: info.message });
        if (info.kind !== 'dir') {
          return sendJson(res, 400, { ok: false, error: 'not_a_directory', message: 'target is not a directory' });
        }
        const listing = listDirectory(info.path, HOME);
        return sendJson(res, 200, { ...info, ...listing });
      }

      if (pathname === '/api/files/read' && req.method === 'GET') {
        const p = url.searchParams.get('path') || '';
        const cwd = url.searchParams.get('cwd') || '';
        const fallbackDir = url.searchParams.get('fallbackDir') || '';
        const info = resolveAndStat(p, { cwd, fallbackDir, homeDir: HOME });
        if (!info.ok) return sendJson(res, info.status || 404, { ok: false, error: info.error, message: info.message });
        if (info.kind !== 'file') {
          return sendJson(res, 400, { ok: false, error: 'not_a_file', message: 'target is a directory' });
        }
        const read = readTextFile(info.path);
        return sendJson(res, 200, { ...info, content: read.content, truncated: read.truncated, binary: read.binary });
      }

      if (pathname.startsWith('/api/files/raw/') && (req.method === 'GET' || req.method === 'HEAD')) {
        const decoded = decodeRawPath(pathname.slice('/api/files/raw/'.length));
        const info = resolveAndStat(decoded, { homeDir: HOME });
        if (!info.ok) {
          res.writeHead(info.status || 404, { ...SECURITY_HEADERS, 'Content-Type': 'text/plain; charset=utf-8' });
          return res.end(info.message || 'Not found');
        }
        if (info.kind !== 'file') {
          res.writeHead(400, { ...SECURITY_HEADERS, 'Content-Type': 'text/plain; charset=utf-8' });
          return res.end('Target is a directory');
        }
        const forceDownload = url.searchParams.get('download') === '1';
        const headers = {
          ...sandboxHeadersForRaw(info.category, info.name, forceDownload),
          'Content-Type': info.mime || 'application/octet-stream',
          'Accept-Ranges': 'bytes',
        };
        const total = info.size;
        const range = req.headers.range;
        if (range && /^bytes=\d*-\d*$/.test(range) && total > 0) {
          const [startStr, endStr] = range.slice(6).split('-');
          const start = startStr ? parseInt(startStr, 10) : Math.max(0, total - parseInt(endStr, 10));
          const end = endStr ? Math.min(total - 1, parseInt(endStr, 10)) : total - 1;
          if (Number.isNaN(start) || Number.isNaN(end) || start > end || start >= total) {
            res.writeHead(416, { ...headers, 'Content-Range': `bytes */${total}` });
            return res.end();
          }
          res.writeHead(206, {
            ...headers,
            'Content-Range': `bytes ${start}-${end}/${total}`,
            'Content-Length': String(end - start + 1),
          });
          if (req.method === 'HEAD') return res.end();
          return fs.createReadStream(info.path, { start, end }).pipe(res);
        }
        res.writeHead(200, { ...headers, 'Content-Length': String(total) });
        if (req.method === 'HEAD') return res.end();
        return fs.createReadStream(info.path).pipe(res);
      }

      // Standalone fullscreen viewer route (/view?path=...)
      if (pathname === '/view' && (req.method === 'GET' || req.method === 'HEAD')) {
        return serveFile(res, path.join(PUBLIC_DIR, 'view.html'), false);
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
  };
}
