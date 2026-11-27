// Shared HTTP/security helpers, static/vendor file serving, image paste storage, and worktree target resolution.

import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { SB_RUN_DIR, terminalCwd } from './hc-client.mjs';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
export const PUBLIC_DIR = path.join(__dirname, 'public');
export const FONTS_DIR = path.join(__dirname, 'fonts');
export const NODE_MODULES = path.join(__dirname, 'node_modules');

// Local xterm.js & full JetBrains Mono + Noto Symbols + Nerd Font vendor bundles (zero CDN dependency)
export const VENDOR_ASSETS = new Map([
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

export function sendJson(res, code, data) {
  res.writeHead(code, {
    ...SECURITY_HEADERS,
    'Content-Type': 'application/json; charset=utf-8',
    'Cache-Control': 'no-store',
  });
  res.end(JSON.stringify(data));
}

export function readBody(req, limit = 256 * 1024) {
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

export const MAX_IMAGE_BYTES = 20 * 1024 * 1024;
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

export function readBinaryBody(req, limit = MAX_IMAGE_BYTES) {
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

export function savePastedImage(buf, pasteDir = path.join(SB_RUN_DIR, 'paste')) {
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

export function serveFile(res, filePath, cacheable = false) {
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

export function resolveWorktreeTarget(reqPath, tid, hc) {
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
