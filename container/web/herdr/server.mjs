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
import { agentIconPath, browserRegistry, resolveAgent } from './agents.mjs';
import {
  ADDON_BIN,
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
  detectLiveAgent,
  detectTerminalAgent,
  normalizeAgentName,
  resolveDefaultAgent,
  isHiddenTerminal,
  listInstalledAgents,
  makePinId,
  noteRecentDir,
  publishTabEvent,
  readActiveTab,
  readBoxConfigSnapshot,
  readPins,
  readRecentDirs,
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
import {
  decodeRawPath,
  listDirectory,
  readTextFile,
  resolveAndStat,
  sandboxHeadersForRaw,
} from './file-preview.mjs';

export { HerdrClient };

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const PUBLIC_DIR = path.join(__dirname, 'public');
const FONTS_DIR = path.join(__dirname, 'fonts');
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

const PLAIN_SHELLS = new Set(['bash', 'sh', 'zsh', 'dash', 'fish', '-bash', '-sh', '-zsh']);

// Fast, zero-subprocess Git repository resolver (cached 2s per cwd) so Web UI can group
// main-checkout and worktree agent tabs under their parent repository cleanly.
const repoInfoCache = new Map();
const REPO_CACHE_TTL_MS = 2000;

export function resolveGitRepoInfo(cwd) {
  if (!cwd || typeof cwd !== 'string' || !cwd.startsWith('/')) return null;
  const now = Date.now();
  const cached = repoInfoCache.get(cwd);
  if (cached && (now - cached.ts) < REPO_CACHE_TTL_MS) return cached.val;

  let result = null;
  try {
    let dir = cwd.replace(/\/+$/, '') || '/';
    for (let depth = 0; depth < 24; depth++) {
      const gitPath = path.join(dir, '.git');
      let st = null;
      try { st = fs.statSync(gitPath); } catch (_) {}
      if (st) {
        if (st.isDirectory()) {
          let branch = '';
          try {
            const head = fs.readFileSync(path.join(gitPath, 'HEAD'), 'utf8').trim();
            if (head.startsWith('ref: refs/heads/')) branch = head.slice('ref: refs/heads/'.length);
          } catch (_) {}
          result = { root: dir, name: path.basename(dir) || dir, branch, is_worktree: false };
        } else if (st.isFile()) {
          const raw = fs.readFileSync(gitPath, 'utf8').trim();
          const m = raw.match(/^gitdir:\s*(.+)$/i);
          if (m) {
            const gitDir = path.resolve(dir, m[1].trim());
            let branch = '';
            try {
              const head = fs.readFileSync(path.join(gitDir, 'HEAD'), 'utf8').trim();
              if (head.startsWith('ref: refs/heads/')) branch = head.slice('ref: refs/heads/'.length);
            } catch (_) {}
            let root = dir;
            try {
              const commonRaw = fs.readFileSync(path.join(gitDir, 'commondir'), 'utf8').trim();
              if (commonRaw) {
                const commonDir = path.resolve(gitDir, commonRaw);
                root = path.basename(commonDir) === '.git' ? path.dirname(commonDir) : commonDir;
              }
            } catch (_) {
              const idx = gitDir.indexOf(`${path.sep}.git${path.sep}worktrees${path.sep}`);
              if (idx > 0) root = gitDir.slice(0, idx);
            }
            result = { root, name: path.basename(root) || root, branch, is_worktree: true };
          }
        }
        break;
      }
      const parent = path.dirname(dir);
      if (parent === dir) break;
      dir = parent;
    }
  } catch (_) {}

  if (repoInfoCache.size > 128) repoInfoCache.clear();
  repoInfoCache.set(cwd, { ts: now, val: result });
  return result;
}

function enrichTerminalsWithRepo(terminals) {
  return (terminals || []).map((t) => {
    const lbls = (t && t.labels) || {};
    if (lbls['swarmbox.repo']) {
      const root = String(lbls['swarmbox.repo']);
      return {
        ...t,
        repo: {
          root,
          name: path.basename(root) || root,
          branch: String(lbls['swarmbox.branch'] || ''),
          is_worktree: Boolean(lbls['swarmbox.worktree']),
        },
      };
    }
    const repo = resolveGitRepoInfo(terminalCwd(t));
    return repo ? { ...t, repo } : t;
  });
}

const SKIP_SCAN_DIRS = new Set(['node_modules', '.git', 'venv', '.venv', 'dist', 'build', 'target', '__pycache__']);

export function discoverProjects(terminals = [], pins = [], homeDir = HOME) {
  const byReal = new Map();
  const activeCounts = new Map();

  const normReal = (p) => {
    if (!p || typeof p !== 'string' || !p.startsWith('/')) return '';
    try { return fs.realpathSync(p); } catch (_) { return p.replace(/\/+$/, '') || '/'; }
  };

  const enriched = enrichTerminalsWithRepo(terminals);
  for (const t of enriched) {
    if (!detectTerminalAgent(t)) continue;
    const root = (t.repo && t.repo.root) || (t.labels && t.labels['swarmbox.repo']) || '';
    const rp = normReal(root);
    if (rp) activeCounts.set(rp, (activeCounts.get(rp) || 0) + 1);
  }

  const addRepoDir = (dirPath) => {
    const rp = normReal(dirPath);
    if (!rp || byReal.has(rp)) return;
    const info = resolveGitRepoInfo(dirPath);
    if (!info || info.is_worktree) return;
    const rootReal = normReal(info.root);
    if (!rootReal || byReal.has(rootReal)) return;
    byReal.set(rootReal, {
      path: info.root,
      name: info.name,
      branch: info.branch || 'main',
      is_git: true,
      active_count: activeCounts.get(rootReal) || 0,
    });
  };

  // 1. Scan HOME (depth 1..2) for Git repositories (skipping hidden dot-directories)
  if (homeDir && fs.existsSync(homeDir)) {
    const scanLevel = (base, depth) => {
      let entries;
      try { entries = fs.readdirSync(base, { withFileTypes: true }); } catch (_) { return; }
      for (const ent of entries) {
        if (!ent.isDirectory() && !ent.isSymbolicLink()) continue;
        const name = ent.name;
        if (!name || name.startsWith('.') || SKIP_SCAN_DIRS.has(name)) continue;
        const full = path.join(base, name);
        let isDir = ent.isDirectory();
        if (!isDir) {
          try { isDir = fs.statSync(full).isDirectory(); } catch (_) { continue; }
        }
        if (!isDir) continue;
        let hasGitDir = false;
        try { hasGitDir = fs.statSync(path.join(full, '.git')).isDirectory(); } catch (_) {}
        if (hasGitDir) {
          addRepoDir(full);
        } else if (depth < 2) {
          scanLevel(full, depth + 1);
        }
      }
    };
    scanLevel(homeDir, 1);
  }

  // 2. Include any active terminal repos and pinned repos even if outside HOME depth 2
  for (const t of enriched) {
    const root = (t.repo && t.repo.root) || (t.labels && t.labels['swarmbox.repo']) || '';
    if (root) addRepoDir(root);
  }
  for (const pin of pins || []) {
    const root = (pin && pin.worktree && pin.worktree.repo) || (pin && pin.cwd) || '';
    if (root) addRepoDir(root);
  }

  return Array.from(byReal.values()).sort((a, b) => a.name.localeCompare(b.name, undefined, { sensitivity: 'base' }));
}

// Describe one folder for the New agent picker: a Git checkout (repo name and branch) or a plain folder.
// Only a `.git` directly in `dir` makes it a repo row, so a plain subfolder of a repo stays a folder.
function describeDir(dir) {
  const name = path.basename(dir) || dir;
  let hasGit = false;
  try { fs.statSync(path.join(dir, '.git')); hasGit = true; } catch (_) {}
  const info = hasGit ? resolveGitRepoInfo(dir) : null;
  if (info) return { path: dir, name, is_git: true, is_worktree: Boolean(info.is_worktree), branch: info.branch || '' };
  return { path: dir, name, is_git: false, is_worktree: false, branch: '' };
}

// Recently used folders, newest first: launches from the Web Studio, then the folders of live tabs (shells
// included, so a folder you cd'd into shows up), then pinned sessions. Missing folders and managed
// worktrees (reached through their repo) are left out.
export function listRecentDirs(terminals = [], pins = [], recent = [], limit = 6) {
  const out = [];
  const seen = new Set();
  const add = (p) => {
    if (out.length >= limit || typeof p !== 'string' || !p.startsWith('/')) return;
    let real = p;
    try { real = fs.realpathSync(p); } catch (_) { return; }
    if (seen.has(real)) return;
    try { if (!fs.statSync(real).isDirectory()) return; } catch (_) { return; }
    seen.add(real);
    const d = describeDir(p.replace(/\/+$/, '') || '/');
    if (d.is_worktree) return;
    out.push(d);
  };
  for (const r of recent || []) add(r && r.path);
  const live = (terminals || []).slice().sort((a, b) => (b.created_ms || 0) - (a.created_ms || 0));
  for (const t of live) if (!(t.labels && t.labels['swarmbox.worktree'])) add(terminalCwd(t));
  for (const pin of pins || []) if (!pin.worktree) add(pin.cwd);
  return out;
}

const LIST_DIRS_MAX = 400;

// The subfolders of `dir` for the picker's folder browser: hidden folders and build/dependency folders skipped,
// symlinks to folders followed, repos flagged. Returns null when `dir` is not a readable folder.
export function listChildDirs(dir) {
  if (typeof dir !== 'string' || !dir.startsWith('/')) return null;
  const clean = path.resolve(dir);
  let entries;
  try { entries = fs.readdirSync(clean, { withFileTypes: true }); } catch (_) { return null; }
  const out = [];
  for (const ent of entries) {
    const name = ent.name;
    if (!name || name.startsWith('.') || SKIP_SCAN_DIRS.has(name)) continue;
    const full = path.join(clean, name);
    let isDir = ent.isDirectory();
    if (!isDir && ent.isSymbolicLink()) {
      try { isDir = fs.statSync(full).isDirectory(); } catch (_) { isDir = false; }
    }
    if (!isDir) continue;
    out.push(describeDir(full));
    if (out.length >= LIST_DIRS_MAX) break;
  }
  out.sort((a, b) => a.name.localeCompare(b.name, undefined, { sensitivity: 'base' }));
  return { path: clean, parent: clean === '/' ? null : path.dirname(clean), entries: out, truncated: out.length >= LIST_DIRS_MAX };
}

// Terminal protocol replies & mouse-tracking motion/hover reports that xterm.js emits
// automatically (not user keystrokes) — these must never abort an active resize mask.
const NON_TYPING_INPUT_RE = /^(?:\x1b\[<[0-9;]+[Mm]|\x1b\[M[\s\S]{3}|\x1b\[[IO]|\x1b\[[0-9;]*R|\x1b\[\?[0-9;]*c|\x1b\](?:10|11);[^\x07\x1b]*(?:\x07|\x1b\\))+$/;

// DEC Mode 2026 Synchronized Output markers (\x1b[?2026h begin, \x1b[?2026l end).
// xterm.js 5.5.0 ignores DEC 2026, so TUIs like agy that clear and redraw inside
// synchronized frames split across multiple PTY chunks would otherwise flash/reflow
// intermediate partial frames. Coalescing at the gateway makes every DEC 2026 frame atomic.
const SYNC_BEGIN_BUF = Buffer.from('\x1b[?2026h');
const SYNC_END_BUF = Buffer.from('\x1b[?2026l');
const CLEAR_SCREEN_BUF = Buffer.from('\x1b[2J');
const CLEAR_SCROLLBACK_BUF = Buffer.from('\x1b[3J');
const MAX_SYNC_FRAME_BYTES = 512 * 1024;
const MAX_SYNC_FRAME_MS = 120;
const LATE_REDRAW_WINDOW_MS = 2500;

export function createSyncOutputCoalescer(onEmit, opts = {}) {
  const maxMs = Number(opts.maxMs) || MAX_SYNC_FRAME_MS;
  const maxBytes = Number(opts.maxBytes) || MAX_SYNC_FRAME_BYTES;
  let inSync = false;
  let chunks = [];
  let totalBytes = 0;
  let timer = null;

  const flush = () => {
    if (timer) { clearTimeout(timer); timer = null; }
    inSync = false;
    if (!chunks.length) return;
    const merged = chunks.length === 1 ? chunks[0] : Buffer.concat(chunks, totalBytes);
    chunks = [];
    totalBytes = 0;
    onEmit(merged);
  };

  const push = (rawBuf) => {
    const buf = Buffer.isBuffer(rawBuf) ? rawBuf : Buffer.from(rawBuf);
    if (!buf.length) return;
    const lastBegin = buf.lastIndexOf(SYNC_BEGIN_BUF);
    const lastEnd = buf.lastIndexOf(SYNC_END_BUF);

    if (!inSync) {
      if (lastBegin === -1 || lastEnd > lastBegin) {
        // Complete or non-synchronized chunk: pass straight through with 0ms latency
        onEmit(buf);
        return;
      }
      // Opened a synchronized frame that does not close in this chunk: buffer until \x1b[?2026l
      inSync = true;
      chunks = [buf];
      totalBytes = buf.length;
      timer = setTimeout(flush, maxMs);
      if (timer.unref) timer.unref();
      return;
    }

    chunks.push(buf);
    totalBytes += buf.length;
    const closed = lastEnd !== -1 && lastEnd > lastBegin;
    if (closed || totalBytes >= maxBytes) {
      flush();
    }
  };

  const reset = () => {
    if (timer) { clearTimeout(timer); timer = null; }
    inSync = false;
    chunks = [];
    totalBytes = 0;
  };

  return {
    push,
    flush,
    reset,
    isBuffering: () => inSync,
  };
}

function isInteractiveTuiTerminal(term) {
  if (!term) return false;
  if (detectTerminalAgent(term)) return true;
  const fg = String((term.foreground && term.foreground.name) || '').toLowerCase().trim();
  if (fg && !PLAIN_SHELLS.has(fg)) return true;
  const word = /^[a-z0-9_]+/.exec(String(term.name || '').toLowerCase());
  if (word && normalizeAgentName(word[0])) return true;
  return false;
}

// ---------------------------------------------------------------------------
// Server factory (also exported for fast unit tests)
// ---------------------------------------------------------------------------
export function createGateway(options = {}) {
  const hc = options.hc || new HerdrClient(options.hcBin || HC_BIN);
  const runWt = options.runWorktreeCmd || runWorktreeCmd;
  const eventClients = new Set();
  // Per-terminal viewport ownership so an idle/reconnecting browser on another screen
  // (e.g. an ultrawide left open at home) cannot hijack the active client's PTY resolution.
  const ptyRooms = new Map();

  function clampCols(c) {
    return Math.max(20, Math.min(400, Number(c) || 100));
  }
  function clampRows(r) {
    return Math.max(6, Math.min(200, Number(r) || 30));
  }
  function getPtyRoom(termId) {
    let room = ptyRooms.get(termId);
    if (!room) {
      room = { clients: new Set(), owner: null, ptyCols: 0, ptyRows: 0 };
      ptyRooms.set(termId, room);
    }
    return room;
  }
  function getCurrentPtySize(termId, fallbackCols, fallbackRows) {
    const room = ptyRooms.get(termId);
    if (room && room.owner && room.owner.streamCols > 0 && room.owner.streamRows > 0) {
      return { cols: room.owner.streamCols, rows: room.owner.streamRows };
    }
    if (room && room.ptyCols > 0 && room.ptyRows > 0) {
      return { cols: room.ptyCols, rows: room.ptyRows };
    }
    const t = hc.terminals.get(termId);
    if (t && Number(t.cols) > 0 && Number(t.rows) > 0) {
      return { cols: clampCols(t.cols), rows: clampRows(t.rows) };
    }
    return { cols: clampCols(fallbackCols), rows: clampRows(fallbackRows) };
  }
  // herdr-core sizes a PTY from its attached streams: an attach or a resize frame applies that stream's size,
  // and so does focus(true) (it re-applies the size that stream last sent), and closing a stream applies a
  // remaining one's. So every stream must always have told hc its client's current size, or a later focus(true)
  // re-applies a stale size (a SIGWINCH and a full redraw nobody masked).
  function sendStreamSize(rec) {
    if (!rec.stream) return;
    rec.stream.resize(rec.wantCols, rec.wantRows);
    rec.streamCols = rec.wantCols;
    rec.streamRows = rec.wantRows;
    const room = ptyRooms.get(rec.termId);
    if (room) {
      room.ptyCols = rec.wantCols;
      room.ptyRows = rec.wantRows;
    }
    const t = hc.terminals.get(rec.termId);
    if (t) {
      t.cols = rec.wantCols;
      t.rows = rec.wantRows;
    }
  }
  // A PTY resize redraws the program for EVERY client attached to it, not only the one that asked: mask the
  // redraw on the others too, so a second window or device never paints the reflow without the loader.
  function maskRoomPeers(room, rec, isTui = true) {
    for (const peer of room.clients) {
      if (peer !== rec && typeof peer.onPeerResize === 'function') peer.onPeerResize(isTui);
    }
  }
  function claimPtyOwnership(room, rec, opts = {}) {
    if (opts.cols && opts.rows) {
      rec.wantCols = clampCols(opts.cols);
      rec.wantRows = clampRows(opts.rows);
    }
    const cur = getCurrentPtySize(rec.termId, room.ptyCols || rec.wantCols, room.ptyRows || rec.wantRows);
    room.owner = rec;
    rec.lastActiveMs = Date.now();
    if (opts.syncSize === false || !rec.stream) return false;
    if (cur.cols !== rec.wantCols || cur.rows !== rec.wantRows) {
      room.ptyCols = rec.wantCols;
      room.ptyRows = rec.wantRows;
      maskRoomPeers(room, rec);
      sendStreamSize(rec);
      return true;
    }
    // The PTY already has this size (another stream set it): still refresh this stream's size in hc,
    // which changes nothing now (same size, no SIGWINCH) but keeps a later focus(true) from going stale.
    if (rec.streamCols !== rec.wantCols || rec.streamRows !== rec.wantRows) sendStreamSize(rec);
    room.ptyCols = cur.cols;
    room.ptyRows = cur.rows;
    return false;
  }
  // A button of the Studio (Ask to commit, Resolve, Commit main, a verify hand-off) types its prompt straight into the
  // agent's PTY through an attach stream, not with hc's terminal.send: that one holds a delivery while a person was
  // active in the terminal (about 3 s after a mouse report, which xterm emits as the pointer crosses the terminal on its
  // way to the button, and up to `draft_wait`, 60 s, with text in the input box). The click is the person, so it must
  // not wait. The text goes first and the Enter as its own write after a pause: text and Enter in one burst reach a TUI
  // as a paste and the Enter becomes a line break (docs/spikes/enter.md: 50 ms was the smallest passing pause, 150 ms chosen).
  const PROMPT_ENTER_GAP_MS = 150;
  async function typePrompt(termId, text) {
    const room = ptyRooms.get(termId);
    const live = room ? [room.owner, ...room.clients].find((c) => c && c.stream) : null;
    let own = null;
    try {
      if (!live) {
        // No browser is on this terminal: attach at its current size (an attach applies its size in herdr-core).
        const size = getCurrentPtySize(termId, 100, 30);
        own = await hc.attach(termId, size.cols, size.rows, {}, 0);
      }
    } catch (_) {
      own = null;
    }
    const stream = live ? live.stream : own;
    if (!stream) {
      // Attach failed: the queued delivery of hc is still better than nothing.
      return hc.call('terminal.send', { terminal: termId, text, force: true });
    }
    try {
      stream.write(Buffer.from(text, 'utf8'));
      await new Promise((r) => setTimeout(r, PROMPT_ENTER_GAP_MS));
      stream.write(Buffer.from('\r'));
    } finally {
      if (own) setTimeout(() => own.close(), 300);
    }
    return { ok: true, typed: true };
  }
  let currentTheme = readSavedTheme();
  let lastBroadcastHash = '';
  let cachedWorktrees = [];
  let wtRefreshing = false;
  let repoStatusRefreshing = false;
  const repoStatuses = new Map();
  const verifyJobs = new Map();
  const lastTabCwd = new Map();
  const lastTabState = new Map();

  function normRealPath(p) {
    if (!p || typeof p !== 'string') return '';
    try { return fs.realpathSync(p); } catch (_) { return p.replace(/\/+$/, '') || '/'; }
  }

  // Worktrees whose tab is being closed. Between the kill and the auto-clean decision the hc events broadcast
  // snapshots in which the worktree has no live terminal; without this hold it shows as pending for a moment and
  // the sidebar flickers (the pending pill appears and goes). Keys are real paths taken while the folder exists.
  const closingWorktrees = new Set();

  // Drop a worktree that was just removed from the cached list, so no snapshot sent before the next `list` refresh
  // reports it as pending. Pass the real path too when it was taken before the folder went away.
  function forgetCachedWorktree(...paths) {
    const gone = new Set();
    for (const p of paths) {
      const raw = String(p || '').replace(/\/+$/, '');
      if (raw) { gone.add(raw); gone.add(normRealPath(raw)); }
    }
    if (gone.size === 0) return;
    cachedWorktrees = cachedWorktrees.filter((w) => {
      const wp = String((w && w.path) || '').replace(/\/+$/, '');
      return !gone.has(wp) && !gone.has(normRealPath(wp));
    });
  }

  function formatMainAgent(term) {
    if (!term) return null;
    return {
      address: term.address,
      title: (term.labels && term.labels['swarmbox.title']) || term.name || 'main',
    };
  }

  function findMainAgentTerminal(repoRoot, rawTerminals) {
    const targetReal = normRealPath(repoRoot);
    if (!targetReal) return null;
    for (const t of rawTerminals || []) {
      if (!t || isHiddenTerminal(t)) continue;
      if (t.state && t.state !== 'live') continue;
      const lbls = t.labels || {};
      if (lbls['swarmbox.worktree']) continue;
      const lblAgent = String(lbls['swarmbox.agent'] || '').toLowerCase().trim();
      const detected = detectTerminalAgent(t);
      const hasAgent = Boolean(detected) || Boolean(normalizeAgentName(lblAgent));
      if (!hasAgent) continue;

      const cwd = terminalCwd(t);
      if (cwd) {
        const info = resolveGitRepoInfo(cwd);
        if (info) {
          if (info.is_worktree) continue;
          if (normRealPath(info.root) === targetReal) return t;
          continue;
        }
      }
      const lblRepo = lbls['swarmbox.repo'] ? normRealPath(String(lbls['swarmbox.repo'])) : '';
      if (lblRepo && lblRepo === targetReal) return t;
      const cwdReal = normRealPath(cwd);
      if (cwdReal && (cwdReal === targetReal || cwdReal.startsWith(targetReal + path.sep))) {
        return t;
      }
    }
    return null;
  }

  async function refreshRepoStatus(repoRoot, opts = {}) {
    if (!repoRoot) return null;
    const rawKey = String(repoRoot).replace(/\/+$/, '') || String(repoRoot);
    try {
      const st = await runWt(['repo-status', rawKey]);
      if (!st || typeof st !== 'object') return null;
      const key = (st.repo_root && String(st.repo_root).replace(/\/+$/, '')) || rawKey;
      const prev = repoStatuses.get(key);
      const mainTerm = findMainAgentTerminal(key, hc.listSnapshot());
      const merged = {
        ...st,
        verify_job: verifyJobs.get(key) || verifyJobs.get(rawKey) || null,
        main_agent: formatMainAgent(mainTerm),
      };
      repoStatuses.set(key, merged);
      if (eventClients.size > 0 && JSON.stringify(prev || null) !== JSON.stringify(merged)) {
        broadcast(buildSnapshot({ type: 'snapshot' }));
      }
      return merged;
    } catch (err) {
      if (opts.throwOnError) throw err;
      return null;
    }
  }

  function refreshAllRepoStatuses(rawTerminals, pins) {
    if (repoStatusRefreshing) return;
    const roots = new Set();
    const enriched = enrichTerminalsWithRepo(rawTerminals || []);
    for (const t of enriched) {
      const r = (t.repo && t.repo.root) || (t.labels && t.labels['swarmbox.repo']) || '';
      if (r) roots.add(String(r).replace(/\/+$/, '') || String(r));
    }
    for (const pin of pins || []) {
      const r = (pin && pin.worktree && pin.worktree.repo) || '';
      if (r) {
        roots.add(String(r).replace(/\/+$/, '') || String(r));
      } else if (pin && pin.cwd) {
        const info = resolveGitRepoInfo(pin.cwd);
        if (info && info.root) roots.add(String(info.root).replace(/\/+$/, '') || String(info.root));
      }
    }
    for (const w of cachedWorktrees || []) {
      if (w && w.repo_root) roots.add(String(w.repo_root).replace(/\/+$/, '') || String(w.repo_root));
    }
    if (roots.size === 0) return;

    repoStatusRefreshing = true;
    Promise.allSettled(
      Array.from(roots).map(async (root) => {
        const st = await runWt(['repo-status', root]);
        if (!st || typeof st !== 'object') return false;
        const key = (st.repo_root && String(st.repo_root).replace(/\/+$/, '')) || root;
        const prev = repoStatuses.get(key);
        const mainTerm = findMainAgentTerminal(key, hc.listSnapshot());
        const merged = {
          ...st,
          verify_job: verifyJobs.get(key) || verifyJobs.get(root) || null,
          main_agent: formatMainAgent(mainTerm),
        };
        repoStatuses.set(key, merged);
        return JSON.stringify(prev || null) !== JSON.stringify(merged);
      })
    )
      .then((results) => {
        const changed = results.some((r) => r.status === 'fulfilled' && r.value === true);
        if (changed && eventClients.size > 0) {
          broadcast(buildSnapshot({ type: 'snapshot' }));
        }
      })
      .finally(() => {
        repoStatusRefreshing = false;
      });
  }

  function buildVerifyHandoffPrompt(context = {}, verifyCmd = '') {
    const branches = Array.isArray(context.mergedBranches) ? context.mergedBranches.filter(Boolean) : [];
    const commits = Array.isArray(context.commitsSummary) ? context.commitsSummary.filter(Boolean) : [];
    const files = Array.isArray(context.files) ? context.files.filter(Boolean) : [];
    const parts = [];
    if (branches.length === 1) {
      parts.push(`Merged branch ${branches[0]} into main.`);
    } else if (branches.length > 1) {
      parts.push(`Merged branches ${branches.join(', ')} into main.`);
    } else {
      parts.push('Local commits on main are ready for verification.');
    }
    if (commits.length > 0) {
      const sample = commits.slice(0, 6).join('; ');
      parts.push(`Commits: ${sample}${commits.length > 6 ? ` (+${commits.length - 6} more)` : ''}.`);
    }
    if (files.length > 0) {
      const sample = files.slice(0, 8).join(', ');
      parts.push(`Changed files: ${sample}${files.length > 8 ? ` (+${files.length - 8} more)` : ''}.`);
    }
    const shouldPush = context.push !== undefined ? Boolean(context.push) : true;
    if (shouldPush) {
      if (verifyCmd) {
        parts.push(`Please run the project verification (\`${verifyCmd}\`) and any relevant tests. If everything passes, push main to origin. If anything fails, fix or report the failure before pushing.`);
      } else {
        parts.push('Please run the project verification/tests. If everything passes, push main to origin. If anything fails, fix or report the failure before pushing.');
      }
    } else if (verifyCmd) {
      parts.push(`Please run the project verification (\`${verifyCmd}\`) and any relevant tests to confirm integration on main. Do not push yet; report the result (or fix any failure) so the user can review and push when ready.`);
    } else {
      parts.push('Please run the project verification/tests to confirm integration on main. Do not push yet; report the result (or fix any failure) so the user can review and push when ready.');
    }
    return parts.join(' ');
  }

  async function runHybridVerifyAndPush(repoRoot, context = {}) {
    const shouldPush = context.push !== undefined ? Boolean(context.push) : true;
    const rawKey = String(repoRoot || '').replace(/\/+$/, '') || String(repoRoot || '');
    const rawTerminals = hc.listSnapshot();
    const mainTerm = findMainAgentTerminal(rawKey, rawTerminals);
    let repoSt = repoStatuses.get(rawKey) || null;
    if (!repoSt && !context.verifyCmd && rawKey) {
      repoSt = await refreshRepoStatus(rawKey).catch(() => null);
    }
    const key = (repoSt && repoSt.repo_root && String(repoSt.repo_root).replace(/\/+$/, '')) || rawKey;
    const verifyCmd = String(context.verifyCmd || (repoSt && repoSt.verify_cmd) || '').trim();

    if (mainTerm) {
      const prompt = buildVerifyHandoffPrompt({ ...context, push: shouldPush }, verifyCmd);
      await typePrompt(mainTerm.address, prompt);
      return {
        mode: 'agent',
        push: shouldPush,
        terminal: mainTerm.address,
        title: (mainTerm.labels && mainTerm.labels['swarmbox.title']) || mainTerm.name || 'main',
      };
    }

    if (verifyCmd) {
      const job = {
        state: 'running',
        cmd: verifyCmd,
        push: shouldPush,
        started_at: Date.now(),
        finished_at: null,
        exit_code: null,
        output: '',
        error: null,
        merged_branches: Array.isArray(context.mergedBranches) ? [...context.mergedBranches] : [],
      };
      verifyJobs.set(key, job);
      if (repoSt) {
        repoStatuses.set(key, { ...repoSt, verify_job: job });
      }
      broadcast(buildSnapshot({ type: 'snapshot' }));

      Promise.resolve()
        .then(async () => {
          let verifyRes = null;
          try {
            verifyRes = await runWt(['verify', key], 190000);
          } catch (err) {
            const d = (err && err.data) || {};
            verifyJobs.set(key, {
              ...job,
              state: 'failed',
              finished_at: Date.now(),
              exit_code: d.exit_code != null ? d.exit_code : 1,
              output: d.output || err.message || '',
              error: err.message || 'verification failed',
            });
            return;
          }

          if (verifyRes && verifyRes.ok === true) {
            if (!shouldPush) {
              verifyJobs.set(key, {
                ...job,
                state: 'passed',
                finished_at: Date.now(),
                exit_code: verifyRes.exit_code != null ? verifyRes.exit_code : 0,
                output: verifyRes.output || '',
                error: null,
              });
              return;
            }
            try {
              await runWt(['push', key]);
              verifyJobs.set(key, {
                ...job,
                state: 'pushed',
                finished_at: Date.now(),
                exit_code: verifyRes.exit_code != null ? verifyRes.exit_code : 0,
                output: verifyRes.output || '',
                error: null,
              });
            } catch (pushErr) {
              verifyJobs.set(key, {
                ...job,
                state: 'passed',
                finished_at: Date.now(),
                exit_code: verifyRes.exit_code != null ? verifyRes.exit_code : 0,
                output: verifyRes.output || '',
                error: pushErr.message || 'push failed',
              });
            }
          } else {
            verifyJobs.set(key, {
              ...job,
              state: 'failed',
              finished_at: Date.now(),
              exit_code: (verifyRes && verifyRes.exit_code != null) ? verifyRes.exit_code : 1,
              output: (verifyRes && verifyRes.output) || '',
              error: (verifyRes && (verifyRes.msg || verifyRes.error)) || 'verification failed',
            });
          }
        })
        .finally(async () => {
          await refreshRepoStatus(key).catch(() => {});
          broadcast(buildSnapshot({ type: 'snapshot' }));
        });

      return { mode: 'backend_verify', push: shouldPush, cmd: verifyCmd, state: 'running' };
    }

    return {
      mode: 'manual_push',
      push: shouldPush,
      message: 'Merged locally. No agent on main or check script detected; verify and push when ready.',
    };
  }

  function refreshPendingWorktrees() {
    if (wtRefreshing) return;
    wtRefreshing = true;
    runWt(['list'])
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

  function purgePinsForWorktree(wtPath, pinId = '') {
    let wtReal = wtPath || '';
    if (wtReal) {
      try { wtReal = fs.realpathSync(wtReal); } catch (_) {}
    }
    const curPins = readPins();
    const kept = curPins.filter((p) => {
      if (!p) return false;
      if (pinId && p.id === pinId) return false;
      if (wtReal) {
        const pPaths = [p.cwd, p.worktree && p.worktree.path].filter(Boolean);
        for (const pp of pPaths) {
          let rp = pp;
          try { rp = fs.realpathSync(pp); } catch (_) {}
          if (rp === wtReal || pp === wtPath) return false;
        }
      }
      return true;
    });
    if (kept.length !== curPins.length) writePins(kept);
  }

  async function closeTerminalCleanly(tid) {
    if (!tid) return;
    await hc.call('terminal.keep', { terminal: tid, keep: false }).catch(() => {});
    await hc.call('terminal.kill', { terminal: tid }).catch(() => {});
    hc.call('terminal.rm', { terminal: tid }).catch(() => {});
    hc.terminals.delete(tid);
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
      return !livePaths.has(rp) && !pinnedPaths.has(rp) && !closingWorktrees.has(rp) && !closingWorktrees.has(w.path);
    });
  }

  function buildSnapshot(extra = {}) {
    const rawTerminals = hc.listSnapshot();
    const terminals = enrichTerminalsWithRepo(rawTerminals);
    const sysop = readSysopSnapshot(rawTerminals);
    const pins = buildPinsSnapshot(rawTerminals);
    const worktrees = pendingWorktreesFor(rawTerminals, pins);
    const worktree_prefs = readWorktreePrefs();
    const session_prefs = readSessionPrefs();
    const installed_agents = listInstalledAgents();
    const repo_statuses = {};
    for (const [k, st] of repoStatuses.entries()) {
      const mainTerm = findMainAgentTerminal(k, rawTerminals);
      repo_statuses[k] = {
        ...st,
        verify_job: verifyJobs.get(k) || null,
        main_agent: formatMainAgent(mainTerm),
      };
    }
    return {
      ...extra,
      terminals,
      active: readActiveTab(),
      sysop,
      theme: currentTheme,
      pins,
      worktrees,
      repo_statuses,
      worktree_prefs,
      session_prefs,
      installed_agents,
      home: HOME,
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
      // A tab that starts working is the user who just sent a request: the auto-namer names it a few seconds later
      // (when the request was not cancelled), instead of at the end of a turn that may take minutes.
      const isStart = type === 'status' && st === 'working' && prevSt !== 'working';
      if (isTurn || isFinishedWork || isStart) {
        publishTabEvent({
          event: isTurn ? 'turn' : isStart ? 'start' : 'status',
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

  async function inspectWorkingTreeForCwd(targetCwd, terminals, excludeAddr = null) {
    const prefs = readWorktreePrefs();
    const empty = {
      cwd: targetCwd || '',
      is_git: false,
      repo_root: null,
      repo_name: null,
      branch: null,
      worktree_path: null,
      dirty: false,
      collision: null,
      prefs,
    };
    if (!targetCwd || !fs.existsSync(targetCwd)) return empty;
    let targetInfo;
    try {
      targetInfo = await runWt(['inspect', targetCwd]);
    } catch (_) {
      return empty;
    }
    if (!targetInfo || !targetInfo.is_git) return empty;
    const targetWt = targetInfo.worktree_path;
    const branch = targetInfo.branch || targetInfo.base || 'HEAD';
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
    const collision = colliding.length > 0 ? {
      repo_root: targetInfo.repo_root,
      repo_name: targetInfo.repo_name,
      branch,
      worktree_path: targetWt,
      dirty: Boolean(targetInfo.dirty),
      active_tabs: colliding,
    } : null;
    return {
      cwd: targetCwd,
      is_git: true,
      repo_root: targetInfo.repo_root,
      repo_name: targetInfo.repo_name,
      branch,
      worktree_path: targetWt,
      dirty: Boolean(targetInfo.dirty),
      collision,
      prefs,
    };
  }

  async function detectWorkingTreeCollision(targetCwd, terminals, excludeAddr = null) {
    const info = await inspectWorkingTreeForCwd(targetCwd, terminals, excludeAddr);
    return info.collision;
  }

  // Every agent session persists until its tab is closed, however it was started: an agent typed into a
  // shell tab (the usual way into a folder without a repo), a cockpit or Sysop tab, a worktree opened from
  // its badge. The first time a terminal without a pin is seen running a known agent it gets an `auto` pin,
  // exactly like an agent tab opened with POST /api/tabs. `swarmbox.persist=off` (persist: false) opts out.
  const autoPinPending = new Set();
  function autoPinAgentTerminals(terms) {
    let pins = null;
    const added = [];
    for (const t of terms || []) {
      if (!t || !t.address || (t.state && t.state !== 'live') || isHiddenTerminal(t)) continue;
      const lbls = t.labels || {};
      if (lbls['swarmbox.pin_id'] || lbls['swarmbox.persist'] === 'off' || autoPinPending.has(t.address)) continue;
      const agent = detectLiveAgent(t);
      if (!agent) continue;
      if (!pins) pins = readPins();
      const cwd = terminalCwd(t);
      const nowSec = Math.floor(Date.now() / 1000);
      const labelTitle = cleanSessionTitle(lbls['swarmbox.title']);
      const labelSource = lbls['swarmbox.title_source'] === 'user' || lbls['swarmbox.title_source'] === 'auto' ? lbls['swarmbox.title_source'] : '';
      const rec = {
        id: makePinId(pins),
        title: labelTitle || defaultTitleForPath(cwd, agent),
        title_source: labelTitle ? labelSource : '',
        agent,
        cwd,
        resume: 'continue',
        autostart: readSessionPrefs().boot_mode === 'autostart',
        auto: true,
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
      }
      pins.push(rec);
      added.push({ term: t, rec });
    }
    if (added.length === 0) return false;
    try { writePins(pins); } catch (_) { return false; }
    for (const { term, rec } of added) {
      const newLabels = { 'swarmbox.pin_id': rec.id, 'swarmbox.agent': rec.agent };
      if (!(term.labels && term.labels['swarmbox.title'])) newLabels['swarmbox.title'] = rec.title;
      term.labels = { ...(term.labels || {}), ...newLabels };
      autoPinPending.add(term.address);
      hc.call('terminal.label', { terminal: term.address, labels: newLabels })
        .catch(() => {
          // The label did not stick: drop the pin so the next snapshot can try again instead of leaving an orphan.
          try { writePins(readPins().filter((p) => p.id !== rec.id)); } catch (_) {}
          if (term.labels) delete term.labels['swarmbox.pin_id'];
        })
        .finally(() => autoPinPending.delete(term.address));
    }
    return true;
  }

  function snapshotHash(snap) {
    return JSON.stringify({
      sysop: snap.sysop,
      theme: snap.theme,
      active: snap.active,
      pins: snap.pins,
      worktrees: snap.worktrees,
      repo_statuses: snap.repo_statuses,
      session_prefs: snap.session_prefs,
    });
  }

  hc.on('snapshot', () => {
    const terms = hc.listSnapshot();
    autoPinAgentTerminals(terms);
    syncPinsFromTerminals(terms);
    emitBusTabEvents(null, terms);
    const snap = buildSnapshot({ type: 'snapshot' });
    lastBroadcastHash = snapshotHash(snap);
    broadcast(snap);
  });

  hc.on('hc-event', ({ event }) => {
    if (event && event.type === 'size' && event.terminal && event.data) {
      const room = ptyRooms.get(event.terminal);
      if (room) {
        if (Number(event.data.cols) > 0) room.ptyCols = clampCols(event.data.cols);
        if (Number(event.data.rows) > 0) room.ptyRows = clampRows(event.data.rows);
      }
    }
    const terms = hc.listSnapshot();
    autoPinAgentTerminals(terms);
    syncPinsFromTerminals(terms);
    emitBusTabEvents(event, terms);
    const snap = buildSnapshot({ type: 'event', event });
    lastBroadcastHash = snapshotHash(snap);
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
      refreshAllRepoStatuses(hc.listSnapshot(), readPins());
    }
    const snap = buildSnapshot({ type: themeChanged ? 'theme' : 'sysop' });
    const h = snapshotHash(snap);
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

      // Local xterm.js & full JetBrains Mono + Noto Symbols + Nerd Font vendor bundles (zero CDN dependency)
      if (pathname === '/vendor/xterm.js') return serveFile(res, path.join(NODE_MODULES, '@xterm/xterm/lib/xterm.js'), true);
      if (pathname === '/vendor/xterm.css') return serveFile(res, path.join(NODE_MODULES, '@xterm/xterm/css/xterm.css'), true);
      if (pathname === '/vendor/addon-fit.js') return serveFile(res, path.join(NODE_MODULES, '@xterm/addon-fit/lib/addon-fit.js'), true);
      if (pathname === '/vendor/addon-web-links.js') return serveFile(res, path.join(NODE_MODULES, '@xterm/addon-web-links/lib/addon-web-links.js'), true);
      if (pathname === '/vendor/addon-canvas.js') return serveFile(res, path.join(NODE_MODULES, '@xterm/addon-canvas/lib/addon-canvas.js'), true);
      if (pathname === '/vendor/addon-unicode11.js') return serveFile(res, path.join(NODE_MODULES, '@xterm/addon-unicode11/lib/addon-unicode11.js'), true);
      if (pathname === '/vendor/fonts/JetBrainsMono-Regular.woff2') {
        return serveFile(res, path.join(FONTS_DIR, 'JetBrainsMono-Regular.woff2'), true);
      }
      if (pathname === '/vendor/fonts/JetBrainsMono-SemiBold.woff2') {
        return serveFile(res, path.join(FONTS_DIR, 'JetBrainsMono-SemiBold.woff2'), true);
      }
      if (pathname === '/vendor/fonts/JetBrainsMono-Bold.woff2') {
        return serveFile(res, path.join(FONTS_DIR, 'JetBrainsMono-Bold.woff2'), true);
      }
      if (pathname === '/vendor/fonts/JetBrainsMono-Italic.woff2') {
        return serveFile(res, path.join(FONTS_DIR, 'JetBrainsMono-Italic.woff2'), true);
      }
      if (pathname === '/vendor/fonts/noto-symbols-braille.woff2') {
        return serveFile(res, path.join(NODE_MODULES, '@fontsource/noto-sans-symbols-2/files/noto-sans-symbols-2-braille-400-normal.woff2'), true);
      }
      if (pathname === '/vendor/fonts/noto-symbols-math.woff2') {
        return serveFile(res, path.join(NODE_MODULES, '@fontsource/noto-sans-symbols-2/files/noto-sans-symbols-2-math-400-normal.woff2'), true);
      }
      if (pathname === '/vendor/fonts/noto-symbols.woff2') {
        return serveFile(res, path.join(NODE_MODULES, '@fontsource/noto-sans-symbols-2/files/noto-sans-symbols-2-symbols-400-normal.woff2'), true);
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
          home: HOME,
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
        const rawTerminals = (resList.terminals || []).filter((t) => t.state === 'live' && !isHiddenTerminal(t));
        const terminals = enrichTerminalsWithRepo(rawTerminals);
        const pins = buildPinsSnapshot(rawTerminals);
        return sendJson(res, 200, {
          terminals,
          active: readActiveTab(),
          sysop: readSysopSnapshot(rawTerminals),
          theme: currentTheme,
          pins,
          worktrees: pendingWorktreesFor(rawTerminals, pins),
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
          argv = buildAgentArgv(cmd, body.resume === 'continue' ? 'continue' : 'fresh');
          prefix = cmd === 'yolo' ? 'agent' : cmd;
        }

        const labels = {};
        if (agentKind && agentKind !== 'shell') labels['swarmbox.agent'] = agentKind;
        if (preset === 'agent' && body.persist === false) labels['swarmbox.persist'] = 'off';
        let createdWorktree = null;
        const requestedCwd = cwd;

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
        if (body.cwd) noteRecentDir(requestedCwd);
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
          const wtHold = wtPath ? normRealPath(wtPath) : '';
          if (wtHold) closingWorktrees.add(wtHold);
          let autoCleaned = false;
          try {
            await hc.call('terminal.keep', { terminal: termId, keep: false }).catch(() => {});
            await hc.call('terminal.kill', { terminal: termId }).catch(() => {});
            hc.call('terminal.rm', { terminal: termId }).catch(() => {});
            hc.terminals.delete(termId);
            // Auto-clean empty managed worktrees on close when no parked pin holds them
            if (!pinKept && wtPath) {
              try {
                const st = await runWorktreeCmd(['status', wtPath]);
                if (st && st.managed && st.empty) {
                  await runWorktreeCmd(['remove', wtPath]);
                  autoCleaned = true;
                  forgetCachedWorktree(wtPath, wtHold);
                }
              } catch (_) {}
            }
          } finally {
            if (wtHold) closingWorktrees.delete(wtHold);
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
          const list = await runWt(['list']);
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
        const info = await inspectWorkingTreeForCwd(cwd, hc.listSnapshot());
        return sendJson(res, 200, info);
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
          const st = await refreshRepoStatus(repo, { throwOnError: true });
          const mainTerm = findMainAgentTerminal((st && st.repo_root) || repo, hc.listSnapshot());
          return sendJson(res, 200, {
            ...(st || {}),
            main_agent: formatMainAgent(mainTerm),
          });
        } catch (err) {
          return sendJson(res, 404, { error: err.code || 'repo_status_error', message: err.message });
        }
      }

      if (pathname === '/api/worktrees/diff' && req.method === 'GET') {
        let wtPath = url.searchParams.get('path') || '';
        const tid = url.searchParams.get('terminal') || '';
        if (!wtPath && tid) {
          const t = hc.terminals.get(tid);
          if (t) wtPath = (t.labels && t.labels['swarmbox.worktree']) || terminalCwd(t);
        }
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
        let wtPath = String(body.path || '');
        const tid = body.terminal ? String(body.terminal) : '';
        const t = tid ? hc.terminals.get(tid) : null;
        if (!wtPath && t) {
          wtPath = (t.labels && t.labels['swarmbox.worktree']) || terminalCwd(t);
        }
        if (!wtPath) return sendJson(res, 400, { error: 'bad_arg', message: 'path or terminal required' });
        const args = ['sync', wtPath];
        if (body.rebase) args.push('--rebase');
        try {
          const resSync = await runWt(args);
          const repoRoot = (resSync && resSync.repo_root) || (t && t.labels && t.labels['swarmbox.repo']) || '';
          if (repoRoot) await refreshRepoStatus(repoRoot).catch(() => {});
          refreshPendingWorktrees();
          broadcast(buildSnapshot({ type: 'snapshot' }));
          return sendJson(res, 200, resSync);
        } catch (err) {
          return sendJson(res, 409, { error: err.code || 'sync_failed', message: err.message, ...(err.data || {}) });
        }
      }

      if (pathname === '/api/worktrees/merge' && req.method === 'POST') {
        const body = await readBody(req);
        let wtPath = String(body.path || '');
        const tid = body.terminal ? String(body.terminal) : '';
        const t = tid ? hc.terminals.get(tid) : null;
        if (!wtPath && t) {
          wtPath = (t.labels && t.labels['swarmbox.worktree']) || terminalCwd(t);
        }
        if (!wtPath) return sendJson(res, 400, { error: 'bad_arg', message: 'path or terminal required' });
        const args = ['merge', wtPath];
        if (body.squash) args.push('--squash');
        if (body.clean) args.push('--clean');
        try {
          const resMerge = await runWt(args);
          if (body.clean) {
            const pinId = (t && t.labels && t.labels['swarmbox.pin_id']) || '';
            purgePinsForWorktree(wtPath, pinId);
            forgetCachedWorktree(wtPath);
            if (tid) await closeTerminalCleanly(tid);
          }
          const repoRoot = (resMerge && resMerge.repo_root) || (t && t.labels && t.labels['swarmbox.repo']) || '';
          if (repoRoot) await refreshRepoStatus(repoRoot).catch(() => {});
          const doVerify = Boolean(body.verify || body.verify_and_push);
          const doPush = Boolean(body.push || body.verify_and_push);
          let handoff = null;
          if (doVerify && repoRoot) {
            handoff = await runHybridVerifyAndPush(repoRoot, {
              mergedBranches: resMerge && resMerge.branch ? [resMerge.branch] : [],
              commitsSummary: (resMerge && Array.isArray(resMerge.commits_list)) ? resMerge.commits_list : [],
              files: (resMerge && Array.isArray(resMerge.files)) ? resMerge.files : [],
              push: doPush,
            });
          }
          refreshPendingWorktrees();
          broadcast(buildSnapshot({ type: 'snapshot' }));
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
              forgetCachedWorktree(w.path);
              const matchingTerms = termByWtPath.get(normRealPath(w.path)) || [];
              if (matchingTerms.length > 0) {
                for (const mt of matchingTerms) {
                  const pinId = (mt.labels && mt.labels['swarmbox.pin_id']) || '';
                  purgePinsForWorktree(w.path, pinId);
                  await closeTerminalCleanly(mt.address);
                }
              } else {
                purgePinsForWorktree(w.path, '');
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

        await refreshRepoStatus(repo).catch(() => {});
        const doVerifyAll = Boolean(body.verify || body.verify_and_push);
        const doPushAll = Boolean(body.push || body.verify_and_push);
        let handoff = null;
        if (merged.length > 0 && doVerifyAll) {
          handoff = await runHybridVerifyAndPush(repo, {
            mergedBranches,
            commitsSummary,
            files: Array.from(filesSet),
            push: doPushAll,
          });
        }
        refreshPendingWorktrees();
        broadcast(buildSnapshot({ type: 'snapshot' }));
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
          const mainTerm = findMainAgentTerminal(key, hc.listSnapshot());
          if (!mainTerm) {
            return sendJson(res, 409, { error: 'no_main_agent', message: 'No active agent terminal on main for this repository' });
          }
          const prompt = 'Review the uncommitted changes on main, run relevant tests if needed, and create a clean git commit.';
          const r = await typePrompt(mainTerm.address, prompt);
          return sendJson(res, 200, { ok: true, action: 'commit', terminal: mainTerm.address, result: r });
        }

        if (action === 'verify' || action === 'verify_and_push') {
          await refreshRepoStatus(key).catch(() => {});
          const handoff = await runHybridVerifyAndPush(key, {
            mergedBranches: [],
            push: action === 'verify_and_push',
          });
          return sendJson(res, 200, { ok: true, action, handoff });
        }

        if (action === 'push') {
          try {
            const r = await runWt(['push', key]);
            const curJob = verifyJobs.get(key);
            if (curJob && curJob.state === 'passed') {
              verifyJobs.set(key, { ...curJob, state: 'pushed', error: null, finished_at: Date.now() });
            }
            await refreshRepoStatus(key).catch(() => {});
            broadcast(buildSnapshot({ type: 'snapshot' }));
            return sendJson(res, 200, { ok: true, ...(r || {}) });
          } catch (err) {
            return sendJson(res, 409, { error: err.code || 'push_failed', message: err.message, ...(err.data || {}) });
          }
        }

        if (action === 'undo_merge') {
          try {
            const r = await runWt(['undo-merge', key]);
            const curJob = verifyJobs.get(key);
            if (curJob && curJob.state === 'failed') verifyJobs.delete(key);
            const rKey = (r && r.repo_root && String(r.repo_root).replace(/\/+$/, '')) || '';
            if (rKey && verifyJobs.get(rKey) && verifyJobs.get(rKey).state === 'failed') verifyJobs.delete(rKey);
            await refreshRepoStatus(key).catch(() => {});
            broadcast(buildSnapshot({ type: 'snapshot' }));
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
          purgePinsForWorktree(wtPath, pinId);
          forgetCachedWorktree(wtPath);
          if (tid) await closeTerminalCleanly(tid);
          const repoRoot = (r && r.repo_root) || (t && t.labels && t.labels['swarmbox.repo']) || '';
          if (repoRoot) await refreshRepoStatus(repoRoot).catch(() => {});
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
        const r = await typePrompt(tid, prompt);
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
    const cols = clampCols(url.searchParams.get('cols') || 100);
    const rows = clampRows(url.searchParams.get('rows') || 30);
    const isReconnect = url.searchParams.get('reconnect') === '1';
    const isPassiveAttach = isReconnect || url.searchParams.get('focused') === '0';
    const attachIsTui = url.searchParams.get('tui') === '1' || isInteractiveTuiTerminal(hc.terminals.get(termId));

    const room = getPtyRoom(termId);
    const clientRec = {
      ws,
      termId,
      wantCols: cols,
      wantRows: rows,
      stream: null,
      focused: !isPassiveAttach,
      lastActiveMs: isPassiveAttach ? 0 : Date.now(),
    };
    room.clients.add(clientRec);
    const hasOtherOwner = Boolean(room.owner && room.owner !== clientRec && room.clients.has(room.owner));
    const claimOnAttach = !hasOtherOwner || !isPassiveAttach;
    // The size the PTY has right now. The owner's stream is exact (this gateway set it); hc's cached
    // size can lag a resize by a refresh, and attaching at a stale size would resize the PTY itself.
    const ownerRec = hasOtherOwner ? room.owner : null;
    const ptyNow = ownerRec && ownerRec.streamCols
      ? { cols: ownerRec.streamCols, rows: ownerRec.streamRows }
      : getCurrentPtySize(termId, cols, rows);
    let attachCols = cols;
    let attachRows = rows;
    if (claimOnAttach) {
      room.owner = clientRec;
      room.ptyCols = cols;
      room.ptyRows = rows;
      writeActiveTab(termId);
    } else {
      // A passive attach (a background window, a reconnect) must never change the PTY: join at its current size.
      attachCols = ptyNow.cols;
      attachRows = ptyNow.rows;
    }
    // In herdr-core an attach applies its size: when that changes the PTY, the program redraws for every
    // client. Mask it for the others now, and for this one right after its hydration (the SIGWINCH redraw
    // of a TUI tends to land after the replay that hydration releases).
    const attachResizesPty = clampCols(attachCols) !== ptyNow.cols || clampRows(attachRows) !== ptyNow.rows;
    if (attachResizesPty) maskRoomPeers(room, clientRec);
    if (typeof hc.refreshTerminals === 'function') hc.refreshTerminals();

    let stream = null;
    let hydrating = true;
    const attachStartMs = Date.now();
    let initLastChunkMs = 0;
    let initPostReplayBytes = 0;
    let initSawPostReplay = false;
    let initChunks = [];
    let flushTimer = null;
    let capTimer = null;
    let resizing = false;
    let resizeSeq = 0;
    let resizeBytes = 0;
    let resizeIsTui = false;
    let lastResizeAtMs = 0;
    let resizeChunks = [];
    let resizeQuietTimer = null;
    let resizeCapTimer = null;
    const syncCoalescer = createSyncOutputCoalescer((frame) => {
      if (ws.readyState === 1) ws.send(frame);
    });

    const clearHydrationTimers = () => {
      if (flushTimer) { clearTimeout(flushTimer); flushTimer = null; }
      if (capTimer) { clearTimeout(capTimer); capTimer = null; }
    };

    const clearResizeTimers = () => {
      if (resizeQuietTimer) { clearTimeout(resizeQuietTimer); resizeQuietTimer = null; }
      if (resizeCapTimer) { clearTimeout(resizeCapTimer); resizeCapTimer = null; }
    };

    const startResizeMask = (seqVal, isTuiHint = false) => {
      if (hydrating) return;
      syncCoalescer.flush();
      clearResizeTimers();
      resizing = true;
      lastResizeAtMs = Date.now();
      resizeSeq = Number(seqVal) || (resizeSeq + 1);
      resizeBytes = 0;
      resizeIsTui = Boolean(isTuiHint) || isInteractiveTuiTerminal(hc.terminals.get(termId));
      // Long-conversation TUIs like agy may take ~600-850ms to re-layout markdown before emitting
      // their clear+redraw burst, and up to ~2-3s to stream the full history. Give them room while
      // still releasing fast TUIs (Claude/empty agy) shortly after their burst settles.
      resizeQuietTimer = setTimeout(flushResize, resizeIsTui ? 900 : 110);
      resizeCapTimer = setTimeout(flushResize, resizeIsTui ? 3500 : 350);
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
      ws.send(JSON.stringify({
        type: 'hydrated',
        cols: room.ptyCols || clampCols(attachCols),
        rows: room.ptyRows || clampRows(attachRows),
      }));
      if (attachResizesPty && attachIsTui) {
        startResizeMask(0, true);
        ws.send(JSON.stringify({ type: 'resizing', seq: resizeSeq }));
      }
    };

    const flushResize = () => {
      if (!resizing) return;
      resizing = false;
      const doneSeq = resizeSeq;
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
      ws.send(JSON.stringify({ type: 'resized', seq: doneSeq, cols: room.ptyCols || clientRec.streamCols || clientRec.wantCols, rows: room.ptyRows || clientRec.streamRows || clientRec.wantRows }));
    };

    try {
      stream = await hc.attach(termId, attachCols, attachRows, {
        onData: (buf) => {
          if (hydrating) {
            const now = Date.now();
            initChunks.push(Buffer.from(buf));
            if (attachIsTui) {
              const elapsed = now - attachStartMs;
              const gap = initLastChunkMs > 0 ? now - initLastChunkMs : 0;
              // Distinguish the initial history replay from the post-attach SIGWINCH TUI redraw:
              // require an actual inter-burst pause (not just a large replay taking >65ms) and
              // substantial redraw bytes so a tiny spinner/status tick never ends hydration early.
              if (gap >= 60 || (elapsed >= 160 && gap >= 40)) {
                initPostReplayBytes += buf.length;
                if (initPostReplayBytes >= 256) initSawPostReplay = true;
              }
              initLastChunkMs = now;
              if (flushTimer) clearTimeout(flushTimer);
              flushTimer = setTimeout(flushInitial, initSawPostReplay ? 160 : 460);
            } else {
              initLastChunkMs = now;
              if (flushTimer) clearTimeout(flushTimer);
              flushTimer = setTimeout(flushInitial, 75);
            }
            return;
          }
          if (!resizing && lastResizeAtMs > 0 && (Date.now() - lastResizeAtMs) <= LATE_REDRAW_WINDOW_MS) {
            // Catch late full-screen/scrollback clear+redraw passes from heavy TUIs (e.g. agy
            // re-rendering a long conversation >900ms after SIGWINCH) BEFORE the clear hits xterm.
            const hasFullClear = buf.includes(CLEAR_SCROLLBACK_BUF) || buf.includes(CLEAR_SCREEN_BUF);
            if (hasFullClear && (resizeIsTui || isInteractiveTuiTerminal(hc.terminals.get(termId)))) {
              startResizeMask(0, true);
              if (ws.readyState === 1) ws.send(JSON.stringify({ type: 'resizing', seq: resizeSeq }));
            }
          }
          if (resizing) {
            resizeChunks.push(Buffer.from(buf));
            resizeBytes += buf.length;
            if (resizeQuietTimer) clearTimeout(resizeQuietTimer);
            // If the TUI opened a DEC 2026 synchronized frame that has not closed yet,
            // give it extra breathing room before declaring the redraw settled.
            const lb = buf.lastIndexOf(SYNC_BEGIN_BUF);
            const le = buf.lastIndexOf(SYNC_END_BUF);
            const openSync = lb !== -1 && lb > le;
            const quietMs = openSync
              ? 420
              : ((resizeIsTui && resizeBytes < 512) ? 650 : (resizeIsTui ? 320 : 85));
            resizeQuietTimer = setTimeout(flushResize, quietMs);
            return;
          }
          syncCoalescer.push(Buffer.from(buf));
        },
        onClose: (info) => {
          flushInitial();
          flushResize();
          syncCoalescer.flush();
          if (ws.readyState === 1) {
            ws.send(JSON.stringify({ type: 'closed', info }));
            ws.close();
          }
        },
      });
      clientRec.stream = stream;
      clientRec.streamCols = clampCols(attachCols);
      clientRec.streamRows = clampRows(attachRows);
      clientRec.onPeerResize = (isTui) => {
        if (hydrating || ws.readyState !== 1) return;
        startResizeMask(0, isTui);
        ws.send(JSON.stringify({ type: 'resizing', seq: resizeSeq }));
      };
    } catch (err) {
      clearHydrationTimers();
      clearResizeTimers();
      room.clients.delete(clientRec);
      if (room.owner === clientRec) room.owner = null;
      if (room.clients.size === 0) ptyRooms.delete(termId);
      if (ws.readyState === 1) {
        ws.send(JSON.stringify({ type: 'error', message: err.message }));
        ws.close();
      }
      return;
    }

    // Coalesce initial replay + post-attach TUI SIGWINCH redraw into one atomic hydrated frame.
    if (hydrating) {
      if (!flushTimer) flushTimer = setTimeout(flushInitial, attachIsTui ? 460 : 110);
      capTimer = setTimeout(flushInitial, attachIsTui ? 1400 : 350);
    }

    ws.on('message', (data, isBinary) => {
      if (!stream) return;
      if (isBinary) {
        const buf = Buffer.from(data);
        if (!NON_TYPING_INPUT_RE.test(buf.toString('utf8'))) {
          if (room.owner !== clientRec) {
            claimPtyOwnership(room, clientRec);
            writeActiveTab(termId);
            stream.focus(true);
          } else {
            claimPtyOwnership(room, clientRec);
          }
        }
        stream.write(buf);
        return;
      }
      const text = data.toString('utf8');
      if (text.startsWith('{')) {
        try {
          const msg = JSON.parse(text);
          if (msg.type === 'resize') {
            clientRec.wantCols = clampCols(msg.cols);
            clientRec.wantRows = clampRows(msg.rows);
            const canResize = !room.owner || room.owner === clientRec || Boolean(msg.claim);
            if (!canResize) {
              if (ws.readyState === 1) {
                ws.send(JSON.stringify({ type: 'resized', seq: Number(msg.seq) || 0 }));
              }
              return;
            }
            const before = getCurrentPtySize(termId, room.ptyCols || clientRec.wantCols, room.ptyRows || clientRec.wantRows);
            room.owner = clientRec;
            room.ptyCols = clientRec.wantCols;
            room.ptyRows = clientRec.wantRows;
            clientRec.lastActiveMs = Date.now();
            // Coalesce SIGWINCH full-screen TUI repaint bursts into one atomic frame
            // (covering debounced & multi-pass TUIs such as OpenCode, Claude, AGY, and Gemini).
            startResizeMask(msg.seq, Boolean(msg.tui));
            if (before.cols !== clientRec.wantCols || before.rows !== clientRec.wantRows) maskRoomPeers(room, clientRec);
            sendStreamSize(clientRec);
            return;
          }
          if (msg.type === 'focus') {
            if (msg.cols && msg.rows) {
              clientRec.wantCols = clampCols(msg.cols);
              clientRec.wantRows = clampRows(msg.rows);
            }
            if (msg.focused) {
              const wasOwner = room.owner === clientRec;
              const wasFocused = Boolean(clientRec.focused);
              const shouldClaim = Boolean(msg.claim) || !room.owner || wasOwner;
              if (shouldClaim) {
                const cur = getCurrentPtySize(termId, room.ptyCols || clientRec.wantCols, room.ptyRows || clientRec.wantRows);
                const willResize = cur.cols !== clientRec.wantCols || cur.rows !== clientRec.wantRows;
                if (willResize && !hydrating) {
                  startResizeMask(0, Boolean(msg.tui) || isInteractiveTuiTerminal(hc.terminals.get(termId)));
                  if (ws.readyState === 1) ws.send(JSON.stringify({ type: 'resizing', seq: resizeSeq }));
                }
                claimPtyOwnership(room, clientRec, { cols: msg.cols, rows: msg.rows });
                clientRec.focused = true;
                if (!wasOwner || !wasFocused) {
                  writeActiveTab(termId);
                  stream.focus(true);
                }
                if (!willResize && !hydrating && !resizing && ws.readyState === 1) {
                  ws.send(JSON.stringify({
                    type: 'resized',
                    seq: 0,
                    cols: room.ptyCols || clientRec.wantCols,
                    rows: room.ptyRows || clientRec.wantRows,
                  }));
                }
              }
            } else {
              clientRec.focused = false;
              stream.focus(false);
            }
            return;
          }
          if (msg.type === 'input' && typeof msg.data === 'string') {
            const isRealInput = !NON_TYPING_INPUT_RE.test(msg.data);
            if (isRealInput) {
              if (resizing) flushResize();
              const wasOwner = room.owner === clientRec;
              claimPtyOwnership(room, clientRec);
              if (!wasOwner) {
                writeActiveTab(termId);
                stream.focus(true);
              }
            }
            stream.write(Buffer.from(msg.data, 'utf8'));
            return;
          }
        } catch (_) {}
      }
      if (resizing) flushResize();
      if (!NON_TYPING_INPUT_RE.test(text)) {
        const wasOwner = room.owner === clientRec;
        claimPtyOwnership(room, clientRec);
        if (!wasOwner) {
          writeActiveTab(termId);
          stream.focus(true);
        }
      }
      stream.write(Buffer.from(text, 'utf8'));
    });

    ws.on('close', () => {
      clearHydrationTimers();
      clearResizeTimers();
      syncCoalescer.reset();
      initChunks = [];
      resizeChunks = [];
      hydrating = false;
      resizing = false;
      room.clients.delete(clientRec);
      if (room.owner === clientRec) room.owner = null;
      if (room.clients.size === 0) ptyRooms.delete(termId);
      // Closing this stream makes herdr-core apply a remaining stream's size: when that differs, the
      // program redraws for the clients still attached, so mask it for them.
      else if ([...room.clients].some((c) => c.streamCols && (c.streamCols !== clientRec.streamCols || c.streamRows !== clientRec.streamRows))) {
        maskRoomPeers(room, clientRec);
      }
      clientRec.onPeerResize = null;
      clientRec.stream = null;
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
