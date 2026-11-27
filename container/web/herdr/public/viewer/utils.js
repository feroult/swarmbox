/* Shared pure utilities for the SwarmBox File Viewer. */

export function escHtml(s) {
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

export function fmtBytes(n) {
  const v = Number(n) || 0;
  if (v < 1024) return v + ' B';
  if (v < 1024 * 1024) return (v / 1024).toFixed(1) + ' KB';
  if (v < 1024 * 1024 * 1024) return (v / (1024 * 1024)).toFixed(1) + ' MB';
  return (v / (1024 * 1024 * 1024)).toFixed(2) + ' GB';
}

export function encodeRawUrl(absPath) {
  return '/api/files/raw/' + String(absPath || '').replace(/^\/+/, '').split('/').map(encodeURIComponent).join('/');
}

export function resolveRelativePath(baseDir, rel) {
  const s = String(rel || '').trim();
  if (!s) return baseDir;
  if (/^file:\/\//i.test(s)) {
    try { return decodeURIComponent(new URL(s).pathname || ''); } catch (_) { return s.replace(/^file:\/\//i, ''); }
  }
  if (s.startsWith('/') || s.startsWith('~/')) return s;
  const parts = String(baseDir || '').replace(/\/+$/, '').split('/').filter(Boolean);
  for (const seg of s.split('/')) {
    if (!seg || seg === '.') continue;
    if (seg === '..') {
      if (parts.length > 0) parts.pop();
    } else {
      parts.push(seg);
    }
  }
  return '/' + parts.join('/');
}

export function isExternalUrl(href) {
  return /^(?:https?:|mailto:|tel:)/i.test(String(href || '').trim());
}
