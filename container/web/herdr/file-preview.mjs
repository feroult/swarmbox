// Safe local file inspection & streaming helpers for the SwarmBox Web Viewer.
// Read-only, scoped to HOME and /tmp, with explicit secret-path guards and
// sandboxed CSP headers for HTML/SVG previews.

import fs from 'node:fs';
import path from 'node:path';

export const MAX_TEXT_READ_BYTES = 2 * 1024 * 1024; // 2 MB
export const MAX_DIR_ENTRIES = 500;

const IMAGE_EXTS = new Set(['.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg', '.bmp', '.ico', '.avif']);
const MARKDOWN_EXTS = new Set(['.md', '.markdown', '.mdx']);
const HTML_EXTS = new Set(['.html', '.htm']);
const PDF_EXTS = new Set(['.pdf']);
const VIDEO_EXTS = new Set(['.mp4', '.webm', '.mov', '.ogv']);
const AUDIO_EXTS = new Set(['.mp3', '.wav', '.ogg', '.m4a', '.flac']);
const JSON_EXTS = new Set(['.json', '.jsonl', '.jsonc']);
const CODE_EXTS = new Set([
  '.js', '.mjs', '.cjs', '.ts', '.tsx', '.jsx', '.py', '.sh', '.bash', '.zsh',
  '.css', '.scss', '.less', '.yaml', '.yml', '.toml', '.xml', '.sql', '.go',
  '.rs', '.rb', '.java', '.kt', '.c', '.h', '.cc', '.cpp', '.hpp', '.cs', '.php',
  '.txt', '.log', '.csv', '.tsv', '.ini', '.conf', '.cfg', '.diff', '.patch',
  '.dockerfile', '.makefile', '.gitignore', '.gitattributes', '.editorconfig',
]);
const CODE_BASENAMES = new Set([
  'dockerfile', 'makefile', 'procfile', 'gemfile', 'rakefile', 'vagrantfile',
  'license', 'readme', 'changelog', 'contributing', 'cmakelists.txt',
]);

export const MIME_MAP = {
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.gif': 'image/gif',
  '.webp': 'image/webp',
  '.svg': 'image/svg+xml',
  '.bmp': 'image/bmp',
  '.ico': 'image/x-icon',
  '.avif': 'image/avif',
  '.html': 'text/html; charset=utf-8',
  '.htm': 'text/html; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.js': 'application/javascript; charset=utf-8',
  '.mjs': 'application/javascript; charset=utf-8',
  '.cjs': 'application/javascript; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.jsonl': 'application/x-ndjson; charset=utf-8',
  '.md': 'text/markdown; charset=utf-8',
  '.markdown': 'text/markdown; charset=utf-8',
  '.txt': 'text/plain; charset=utf-8',
  '.log': 'text/plain; charset=utf-8',
  '.csv': 'text/csv; charset=utf-8',
  '.xml': 'application/xml; charset=utf-8',
  '.yaml': 'text/yaml; charset=utf-8',
  '.yml': 'text/yaml; charset=utf-8',
  '.pdf': 'application/pdf',
  '.mp4': 'video/mp4',
  '.webm': 'video/webm',
  '.mov': 'video/quicktime',
  '.mp3': 'audio/mpeg',
  '.wav': 'audio/wav',
  '.ogg': 'audio/ogg',
  '.m4a': 'audio/mp4',
  '.woff2': 'font/woff2',
  '.woff': 'font/woff',
  '.ttf': 'font/ttf',
};

// Parse optional :line, :line:col, #L10, #L10-L25 suffix from a user/terminal path.
export function parsePathTarget(input) {
  let raw = String(input || '').trim();
  let line = null;
  let endLine = null;
  let col = null;

  if (!raw) return { rawPath: '', line, endLine, col };

  // Strip surrounding angle brackets or quotes if present
  if ((raw.startsWith('<') && raw.endsWith('>')) || (raw.startsWith('"') && raw.endsWith('"')) || (raw.startsWith("'") && raw.endsWith("'"))) {
    raw = raw.slice(1, -1).trim();
  }

  // Handle file:// URIs
  if (/^file:\/\//i.test(raw)) {
    try {
      const u = new URL(raw);
      raw = decodeURIComponent(u.pathname || '');
      if (u.hash) raw += u.hash;
    } catch (_) {
      raw = raw.replace(/^file:\/\//i, '');
    }
  }

  // Hash line range: #L12 or #L12-L34
  const hashMatch = raw.match(/#L(\d+)(?:-L?(\d+))?$/i);
  if (hashMatch) {
    line = Number(hashMatch[1]) || null;
    endLine = hashMatch[2] ? Number(hashMatch[2]) || null : null;
    raw = raw.slice(0, hashMatch.index);
  } else {
    // Colon line/col suffix: file.js:42 or file.js:42:10
    const colonMatch = raw.match(/:(\d+)(?::(\d+))?$/);
    if (colonMatch) {
      line = Number(colonMatch[1]) || null;
      col = colonMatch[2] ? Number(colonMatch[2]) || null : null;
      raw = raw.slice(0, colonMatch.index);
    }
  }

  return { rawPath: raw, line, endLine, col };
}

function safeRealpath(p) {
  try {
    return fs.realpathSync(p);
  } catch (_) {
    return path.resolve(p);
  }
}

export function isRestrictedPath(realPath, homeDir) {
  const realHome = safeRealpath(homeDir);
  if (!realPath.startsWith(realHome + path.sep) && realPath !== realHome) return false;
  const rel = realPath.slice(realHome.length + 1).replace(/\\/g, '/');
  if (!rel) return false;
  const lower = rel.toLowerCase();
  if (lower === '.ssh' || lower.startsWith('.ssh/')) return true;
  if (lower === '.gnupg' || lower.startsWith('.gnupg/')) return true;
  if (lower === '.swarmbox/env' || lower === '.config/swarmbox/env') return true;
  if (lower === '.aws/credentials' || lower === '.netrc' || lower === '.npmrc') return true;
  return false;
}

export function allowedRoots(homeDir, extraRoots = []) {
  const roots = [homeDir, '/tmp', ...extraRoots].filter(Boolean);
  const out = [];
  const seen = new Set();
  for (const r of roots) {
    const rp = safeRealpath(r);
    if (!seen.has(rp)) {
      seen.add(rp);
      out.push(rp);
    }
  }
  return out;
}

export function isWithinRoots(realPath, roots) {
  for (const root of roots) {
    if (realPath === root || realPath.startsWith(root + path.sep)) return true;
  }
  return false;
}

export function toDisplayPath(absPath, homeDir) {
  const cleanHome = String(homeDir || '').replace(/\/+$/, '');
  if (cleanHome && (absPath === cleanHome || absPath.startsWith(cleanHome + '/'))) {
    return '~' + absPath.slice(cleanHome.length);
  }
  return absPath;
}

export function classifyFile(filePath, isDir = false) {
  if (isDir) return { category: 'dir', mime: 'inode/directory' };
  const ext = path.extname(filePath).toLowerCase();
  const base = path.basename(filePath).toLowerCase();
  const mime = MIME_MAP[ext] || 'application/octet-stream';
  if (IMAGE_EXTS.has(ext)) return { category: 'image', mime };
  if (MARKDOWN_EXTS.has(ext)) return { category: 'markdown', mime };
  if (HTML_EXTS.has(ext)) return { category: 'html', mime };
  if (PDF_EXTS.has(ext)) return { category: 'pdf', mime };
  if (VIDEO_EXTS.has(ext)) return { category: 'video', mime };
  if (AUDIO_EXTS.has(ext)) return { category: 'audio', mime };
  if (JSON_EXTS.has(ext)) return { category: 'json', mime };
  if (CODE_EXTS.has(ext) || CODE_BASENAMES.has(base)) {
    return { category: 'code', mime: mime === 'application/octet-stream' ? 'text/plain; charset=utf-8' : mime };
  }
  return { category: 'binary', mime };
}

export function looksBinary(buf) {
  const len = Math.min(buf.length, 4096);
  for (let i = 0; i < len; i++) {
    if (buf[i] === 0) return true;
  }
  return false;
}

export function encodeRawUrl(absPath) {
  const parts = absPath.replace(/^\/+/, '').split('/').map((seg) => encodeURIComponent(seg));
  return '/api/files/raw/' + parts.join('/');
}

export function decodeRawPath(urlSuffix) {
  const stripped = String(urlSuffix || '').replace(/^\/+/, '');
  if (!stripped) return '';
  const parts = stripped.split('/').map((seg) => {
    try {
      return decodeURIComponent(seg);
    } catch (_) {
      return seg;
    }
  });
  return '/' + parts.join('/');
}

// Resolve a requested path (absolute, ~/, file://, or relative to cwd/fallbackDir),
// enforce allowlist & secret guards, and stat the target.
export function resolveAndStat(rawInput, { cwd = '', fallbackDir = '', homeDir = '', extraRoots = [] } = {}) {
  const parsed = parsePathTarget(rawInput);
  let target = parsed.rawPath;
  if (!target) {
    return { ok: false, status: 400, error: 'missing_path', message: 'path is required' };
  }

  const expandHome = (p) => {
    if (p === '~') return homeDir;
    if (p.startsWith('~/')) return path.join(homeDir, p.slice(2));
    return p;
  };

  const candidates = [];
  if (target === '~' || target.startsWith('~/') || path.isAbsolute(target)) {
    candidates.push(path.resolve(expandHome(target)));
  } else {
    if (cwd) candidates.push(path.resolve(expandHome(cwd), target));
    if (fallbackDir && fallbackDir !== cwd) candidates.push(path.resolve(expandHome(fallbackDir), target));
    if (!cwd && !fallbackDir && homeDir) candidates.push(path.resolve(homeDir, target));
  }

  const roots = allowedRoots(homeDir, extraRoots);
  let lastError = { ok: false, status: 404, error: 'not_found', message: 'file or directory not found' };

  for (const cand of candidates) {
    let st;
    try {
      st = fs.statSync(cand);
    } catch (_) {
      continue;
    }
    const realPath = safeRealpath(cand);
    if (!isWithinRoots(realPath, roots)) {
      lastError = { ok: false, status: 403, error: 'outside_root', message: 'path is outside allowed workspace roots' };
      continue;
    }
    if (isRestrictedPath(realPath, homeDir)) {
      lastError = { ok: false, status: 403, error: 'restricted_path', message: 'access to this sensitive path is restricted' };
      continue;
    }
    const isDir = st.isDirectory();
    let { category, mime } = classifyFile(realPath, isDir);
    // Sniff extensionless small files so README/scripts render as code instead of binary
    if (!isDir && category === 'binary' && st.size > 0 && st.size <= MAX_TEXT_READ_BYTES) {
      try {
        const fd = fs.openSync(realPath, 'r');
        const sample = Buffer.alloc(Math.min(4096, st.size));
        fs.readSync(fd, sample, 0, sample.length, 0);
        fs.closeSync(fd);
        if (!looksBinary(sample)) {
          category = 'code';
          mime = 'text/plain; charset=utf-8';
        }
      } catch (_) {}
    }
    return {
      ok: true,
      path: realPath,
      displayPath: toDisplayPath(realPath, homeDir),
      name: path.basename(realPath) || realPath,
      dir: isDir ? realPath : path.dirname(realPath),
      dirDisplay: toDisplayPath(isDir ? realPath : path.dirname(realPath), homeDir),
      kind: isDir ? 'dir' : 'file',
      category,
      mime,
      size: st.size,
      mtimeMs: st.mtimeMs,
      rawUrl: isDir ? '' : encodeRawUrl(realPath),
      line: parsed.line,
      endLine: parsed.endLine,
      col: parsed.col,
    };
  }

  return lastError;
}

export function listDirectory(dirPath, homeDir) {
  const rawEntries = fs.readdirSync(dirPath, { withFileTypes: true });
  const items = [];
  let truncated = false;
  for (const ent of rawEntries) {
    if (items.length >= MAX_DIR_ENTRIES) {
      truncated = true;
      break;
    }
    const full = path.join(dirPath, ent.name);
    let st;
    try {
      st = fs.statSync(full);
    } catch (_) {
      continue;
    }
    const real = safeRealpath(full);
    if (isRestrictedPath(real, homeDir)) continue;
    const isDir = st.isDirectory();
    const { category, mime } = classifyFile(real, isDir);
    items.push({
      name: ent.name,
      path: real,
      displayPath: toDisplayPath(real, homeDir),
      kind: isDir ? 'dir' : 'file',
      category,
      mime,
      size: isDir ? 0 : st.size,
      mtimeMs: st.mtimeMs,
      rawUrl: isDir ? '' : encodeRawUrl(real),
    });
  }
  items.sort((a, b) => {
    if (a.kind !== b.kind) return a.kind === 'dir' ? -1 : 1;
    return a.name.localeCompare(b.name, undefined, { numeric: true, sensitivity: 'base' });
  });
  return { items, truncated };
}

export function readTextFile(filePath, maxBytes = MAX_TEXT_READ_BYTES) {
  const st = fs.statSync(filePath);
  const toRead = Math.min(st.size, maxBytes);
  const fd = fs.openSync(filePath, 'r');
  try {
    const buf = Buffer.alloc(toRead);
    const bytesRead = fs.readSync(fd, buf, 0, toRead, 0);
    const slice = buf.subarray(0, bytesRead);
    return {
      content: slice.toString('utf8'),
      truncated: st.size > maxBytes,
      size: st.size,
      binary: looksBinary(slice),
    };
  } finally {
    fs.closeSync(fd);
  }
}

export function sandboxHeadersForRaw(category, fileName, forceDownload = false) {
  const headers = {
    'X-Content-Type-Options': 'nosniff',
    'Cache-Control': 'no-store',
  };
  if (forceDownload) {
    const safeName = String(fileName || 'download').replace(/["\\\r\n]/g, '_');
    headers['Content-Disposition'] = `attachment; filename="${safeName}"`;
    headers['Content-Security-Policy'] = "default-src 'none'; sandbox";
    return headers;
  }
  if (category === 'html' || category === 'image') {
    // HTML & SVG previews run in an opaque sandbox origin: scripts/CSS/images work,
    // but fetch/XHR/WebSocket and parent/cookie access to herdr APIs are blocked.
    if (category === 'html' || String(fileName || '').toLowerCase().endsWith('.svg')) {
      headers['Content-Security-Policy'] =
        "sandbox allow-scripts; default-src 'none'; img-src * data: blob:; media-src * data: blob:; font-src * data:; style-src * 'unsafe-inline'; script-src * 'unsafe-inline' 'unsafe-eval'; frame-ancestors 'self'";
      headers['X-Frame-Options'] = 'SAMEORIGIN';
      return headers;
    }
  }
  headers['Content-Security-Policy'] = "frame-ancestors 'self'";
  headers['X-Frame-Options'] = 'SAMEORIGIN';
  return headers;
}
