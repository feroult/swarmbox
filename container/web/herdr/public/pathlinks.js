/* Pure path-link extraction for terminal output and Sysop messages.
 * Zero DOM dependencies so Node tests can exercise it directly.
 *
 * Detects:
 *   - file:///abs/path[#L10-L20]
 *   - ~/relative/path[:42[:10]][#L10-L20]
 *   - /home/... or /tmp/... (absolute paths with >= 2 segments)
 *   - ./rel/path, ../rel/path
 *   - bare relative dirs/files like shots/, docs/img/foo.png, PROPOSALS.md, server.mjs:712
 */
(function (root) {
  'use strict';

  const KNOWN_EXT_RE = /\.(?:md|markdown|mdx|html|htm|png|jpe?g|gif|webp|svg|bmp|ico|avif|pdf|json|jsonl|js|mjs|cjs|ts|tsx|jsx|py|sh|bash|zsh|css|scss|less|ya?ml|toml|xml|sql|go|rs|rb|java|kt|c|h|cc|cpp|hpp|cs|php|txt|log|csv|tsv|ini|conf|cfg|diff|patch|mp4|webm|mov|mp3|wav|ogg)$/i;

  // Match candidate path tokens while excluding http(s):// URLs
  const TOKEN_RE = /(?:file:\/\/\/[^\s"'<>`()[\]{}]+|(?:~\/|\.\.?\/|\/(?:home|tmp|var\/tmp|root|users|workspace|work)\/)[^\s"'<>`()[\]{}]+|(?:[A-Za-z0-9._-]+\/)+[A-Za-z0-9._-]*|[A-Za-z0-9._-]+\.[A-Za-z0-9]{1,8}(?::\d+(?::\d+)?|#L\d+(?:-L?\d+)?)?)/gi;

  const TRAILING_PUNCT_RE = /[.,;:!?)'"\]}>]+$/;

  function cleanCandidate(raw) {
    let s = String(raw || '');
    // Trim trailing punctuation unless it is part of a valid path/range
    while (s.length > 1 && TRAILING_PUNCT_RE.test(s)) {
      const ch = s[s.length - 1];
      // Preserve balanced parentheses inside filenames like foo(1).png
      if (ch === ')' && s.includes('(')) break;
      s = s.slice(0, -1);
    }
    return s;
  }

  function isLikelyPath(cand, fullText, matchStart) {
    if (!cand || cand.length < 2) return false;
    // Skip if preceded immediately by :// or @ (part of URL or email)
    if (matchStart > 0) {
      const before = fullText.slice(Math.max(0, matchStart - 12), matchStart);
      if (/https?:\/\/\S*$/i.test(before) || /wss?:\/\/\S*$/i.test(before)) return false;
      if (/[A-Za-z0-9._%+-]@$/.test(before)) return false;
      if (/[A-Za-z0-9_~/-]$/.test(before)) return false;
    }
    if (/^file:\/\//i.test(cand)) return true;
    if (cand.startsWith('~/') || cand.startsWith('./') || cand.startsWith('../')) {
      return cand.length > 2;
    }
    if (cand.startsWith('/')) {
      // Require at least 2 segments like /tmp/foo or /home/agent/bar
      return cand.split('/').filter(Boolean).length >= 2;
    }
    // Strip optional :line[:col] or #L10-L20 to inspect base path
    const base = cand.replace(/#L\d+(?:-L?\d+)?$/i, '').replace(/:\d+(?::\d+)?$/, '');
    // Skip numeric ratios/dates like 1/2, 25/11/2026, 24/7
    if (/^\d+(?:\/\d+)+$/.test(base)) return false;
    // Skip version-like tokens like v2.2.2 or 1.0.0
    if (/^v?\d+(?:\.\d+)+$/i.test(base)) return false;
    // Directory reference with trailing slash: shots/, docs/img/
    if (base.endsWith('/')) {
      const segs = base.split('/').filter(Boolean);
      if (!segs.length) return false;
      return segs.every((seg) => /^[A-Za-z0-9._-]+$/.test(seg) && !/^\d+$/.test(seg));
    }
    // Relative path with slash: docs/img/foo.png, container/web/herdr/server.mjs
    if (base.includes('/')) {
      const segs = base.split('/').filter(Boolean);
      if (segs.length < 2) return false;
      // Avoid common prose pairs like "and/or", "yes/no", "on/off", "read/write", "before/after"
      if (segs.length === 2 && !KNOWN_EXT_RE.test(base) && !segs[1].includes('.')) {
        return false;
      }
      return true;
    }
    // Single filename with known extension: PROPOSALS.md, metrics.json, server.mjs:712
    return KNOWN_EXT_RE.test(base);
  }

  function extractPathMatches(text) {
    const src = String(text || '');
    if (!src) return [];
    const out = [];
    TOKEN_RE.lastIndex = 0;
    let m;
    while ((m = TOKEN_RE.exec(src))) {
      const raw = m[0];
      const cleaned = cleanCandidate(raw);
      if (!cleaned) continue;
      if (!isLikelyPath(cleaned, src, m.index)) continue;
      out.push({
        text: cleaned,
        start: m.index,
        end: m.index + cleaned.length,
      });
    }
    return out;
  }

  function dirnameOfAbsolute(p) {
    let s = String(p || '').trim();
    if (!s) return '';
    if (/^file:\/\//i.test(s)) {
      try { s = decodeURIComponent(new URL(s).pathname || ''); } catch (_) { s = s.replace(/^file:\/\//i, ''); }
    }
    s = s.replace(/#L\d+(?:-L?\d+)?$/i, '').replace(/:\d+(?::\d+)?$/, '');
    if (!s.startsWith('~/') && !s.startsWith('/')) return '';
    if (s.endsWith('/')) return s.replace(/\/+$/, '') || '/';
    const idx = s.lastIndexOf('/');
    if (idx <= 0) return '';
    return s.slice(0, idx);
  }

  const api = { extractPathMatches, dirnameOfAbsolute, KNOWN_EXT_RE };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.PathLinks = api;
})(typeof globalThis !== 'undefined' ? globalThis : window);
