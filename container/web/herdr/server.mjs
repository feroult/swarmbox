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
  isHiddenTerminal,
  readActiveTab,
  readBoxConfigSnapshot,
  readSavedTheme,
  readSysopSnapshot,
  runCommand,
  saveTheme,
  uniqueTabName,
  writeActiveTab,
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

  function buildSnapshot(extra = {}) {
    const terminals = hc.listSnapshot();
    const sysop = readSysopSnapshot(terminals);
    return {
      ...extra,
      terminals,
      active: readActiveTab(),
      sysop,
      theme: currentTheme,
    };
  }

  function broadcast(payload) {
    const raw = JSON.stringify(payload);
    for (const ws of eventClients) {
      if (ws.readyState === 1) ws.send(raw);
    }
  }

  hc.on('snapshot', () => {
    const snap = buildSnapshot({ type: 'snapshot' });
    lastBroadcastHash = JSON.stringify({ sysop: snap.sysop, theme: snap.theme });
    broadcast(snap);
  });

  hc.on('hc-event', ({ event }) => {
    const snap = buildSnapshot({ type: 'event', event });
    lastBroadcastHash = JSON.stringify({ sysop: snap.sysop, theme: snap.theme });
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
    pollTick = (pollTick + 1) % 4;
    if (pollTick === 0 && typeof hc.refreshTerminals === 'function') {
      hc.refreshTerminals();
    }
    const snap = buildSnapshot({ type: themeChanged ? 'theme' : 'sysop' });
    const h = JSON.stringify({ sysop: snap.sysop, theme: snap.theme });
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
        return sendJson(res, 200, {
          terminals,
          active: readActiveTab(),
          sysop: readSysopSnapshot(terminals),
          theme: currentTheme,
        });
      }

      if (pathname === '/api/tabs' && req.method === 'POST') {
        const body = await readBody(req);
        const preset = String(body.preset || 'shell');
        const cwd = typeof body.cwd === 'string' && body.cwd.startsWith('/') ? body.cwd : HOME;
        let argv = ['/bin/bash', '-l'];
        let prefix = 'shell';
        if (preset === 'agent') {
          const requested = String(body.agent || process.env.SWARMBOX_AGENT || 'yolo').trim();
          const cmd = ALLOWED_AGENT_CMDS.has(requested) ? requested : 'yolo';
          argv = ['/bin/bash', '-lic', `${cmd}; exec /bin/bash -l`];
          prefix = cmd === 'yolo' ? 'agent' : cmd;
        }
        const name = uniqueTabName(body.name, prefix, Array.from(hc.terminals.values()));
        const created = await hc.call('terminal.run', {
          argv,
          name,
          cwd,
          keep: true,
          no_parent: true,
        });
        const addr = created && created.terminal && created.terminal.address;
        if (addr) writeActiveTab(addr);
        return sendJson(res, 201, created);
      }

      const tabMatch = pathname.match(/^\/api\/tabs\/([^/]+)(?:\/(focus|send|keys|interrupt|answer))?$/);
      if (tabMatch) {
        const termId = decodeURIComponent(tabMatch[1]);
        const action = tabMatch[2];

        if (!action && req.method === 'DELETE') {
          await hc.call('terminal.kill', { terminal: termId });
          hc.call('terminal.rm', { terminal: termId }).catch(() => {});
          return sendJson(res, 200, { ok: true });
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

    const clearHydrationTimers = () => {
      if (flushTimer) { clearTimeout(flushTimer); flushTimer = null; }
      if (capTimer) { clearTimeout(capTimer); capTimer = null; }
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

    try {
      stream = await hc.attach(termId, cols, rows, {
        onData: (buf) => {
          if (hydrating) {
            initChunks.push(Buffer.from(buf));
            if (flushTimer) clearTimeout(flushTimer);
            flushTimer = setTimeout(flushInitial, 55);
            return;
          }
          if (ws.readyState === 1) ws.send(buf);
        },
        onClose: (info) => {
          flushInitial();
          if (ws.readyState === 1) {
            ws.send(JSON.stringify({ type: 'closed', info }));
            ws.close();
          }
        },
      });
    } catch (err) {
      clearHydrationTimers();
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
            stream.resize(msg.cols, msg.rows);
            return;
          }
          if (msg.type === 'focus') {
            if (msg.focused) writeActiveTab(termId);
            stream.focus(Boolean(msg.focused));
            return;
          }
          if (msg.type === 'input' && typeof msg.data === 'string') {
            stream.write(Buffer.from(msg.data, 'utf8'));
            return;
          }
        } catch (_) {}
      }
      stream.write(Buffer.from(text, 'utf8'));
    });

    ws.on('close', () => {
      clearHydrationTimers();
      initChunks = [];
      hydrating = false;
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
