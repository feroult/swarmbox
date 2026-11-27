// Local file preview drawer (SwarmBoxViewer integration) and terminal path/URL link providers.

import { state, dom, actions } from './state.js';
import { showTermToast } from './ui-chrome.js';

const fileStatCache = new Map(); // key -> { ts, stat }
const FILE_STAT_TTL_MS = 10000;

let fileViewer = null;
let filePreviewBound = false;

export function getFileViewer() {
  if (!fileViewer && typeof window !== 'undefined' && window.SwarmBoxViewer && dom.fileDrawerEl) {
    fileViewer = window.SwarmBoxViewer.createViewer({
      container: dom.fileDrawerEl,
      mode: 'drawer',
      onClose: closeFileDrawer,
      onToast: (msg) => showTermToast(msg),
    });
  }
  return fileViewer;
}

export function closeFileDrawer() {
  if (!state.fileDrawerOpen) return;
  state.fileDrawerOpen = false;
  dom.fileDrawerBackdropEl?.classList.add('hidden');
  if (typeof actions.focusTerminalIfDesktop === 'function') actions.focusTerminalIfDesktop();
}

export const closeFilePreview = closeFileDrawer;

export function handleFileDrawerKey(e) {
  if (!state.fileDrawerOpen) return false;
  if (e.key === 'Escape') {
    e.preventDefault();
    e.stopPropagation();
    closeFileDrawer();
    return true;
  }
  const viewer = getFileViewer();
  if (viewer) viewer.handleKey(e);
  return true;
}

export function initFilePreview() {
  getFileViewer();
  if (filePreviewBound || !dom.fileDrawerBackdropEl) return;
  filePreviewBound = true;
  dom.fileDrawerBackdropEl.addEventListener('click', (ev) => {
    if (ev.target === dom.fileDrawerBackdropEl) closeFileDrawer();
  });
}

export function terminalCwdFor(address) {
  const t = state.terminals.find((x) => x.address === address);
  return (t && t.cwd) ? t.cwd : '';
}

export async function statBoxPathCached(rawPath, cwd, fallbackDir) {
  const key = `${rawPath}\0${cwd || ''}\0${fallbackDir || ''}`;
  const cached = fileStatCache.get(key);
  const now = Date.now();
  if (cached && (now - cached.ts) < FILE_STAT_TTL_MS) return cached.stat;
  try {
    const qs = new URLSearchParams();
    qs.set('path', rawPath);
    if (cwd) qs.set('cwd', cwd);
    if (fallbackDir) qs.set('fallbackDir', fallbackDir);
    const res = await fetch('/api/files/stat?' + qs.toString());
    const data = await res.json();
    const stat = (res.ok && data && data.ok) ? data : null;
    fileStatCache.set(key, { ts: now, stat });
    if (fileStatCache.size > 400) {
      const firstKey = fileStatCache.keys().next().value;
      if (firstKey) fileStatCache.delete(firstKey);
    }
    return stat;
  } catch (_) {
    return null;
  }
}

export async function openFilePreview(targetPath, opts = {}) {
  if (!targetPath) return;
  const viewer = getFileViewer();
  if (opts.newTab) {
    const stat = await statBoxPathCached(targetPath, opts.cwd || '', opts.fallbackDir || '');
    const resolved = stat ? stat.path : targetPath;
    const line = stat && stat.line ? stat.line : opts.line;
    const url = viewer ? viewer.viewUrlFor(resolved, line) : ('/view?path=' + encodeURIComponent(resolved));
    window.open(url, '_blank', 'noopener,noreferrer');
    return;
  }
  if (!viewer || !dom.fileDrawerBackdropEl) return;
  state.fileDrawerOpen = true;
  dom.fileDrawerBackdropEl.classList.remove('hidden');
  viewer.open(targetPath, opts);
}

export function openFileDrawerInline(opts) {
  const viewer = getFileViewer();
  if (!viewer || !dom.fileDrawerBackdropEl || typeof viewer.openInline !== 'function') return;
  state.fileDrawerOpen = true;
  dom.fileDrawerBackdropEl.classList.remove('hidden');
  viewer.openInline(opts);
}

export function openLogInDrawer(title, subtitle, text) {
  openFileDrawerInline({
    title: title || 'Check output',
    subtitle: subtitle || '',
    content: text || '',
    kind: 'log',
  });
}

export async function openDiffInDrawer(wtPath, title, file) {
  if (!wtPath) return;
  const baseTitle = title || file || 'Diff';
  openFileDrawerInline({
    title: baseTitle,
    subtitle: 'Loading…',
    content: 'Loading diff…',
    kind: 'log',
  });
  try {
    const qs = new URLSearchParams();
    qs.set('path', wtPath);
    if (file) qs.set('file', file);
    const r = await fetch(`/api/worktrees/diff?${qs.toString()}`, { cache: 'no-store' });
    const d = await r.json().catch(() => ({}));
    if (!r.ok || !d.ok) {
      openFileDrawerInline({
        title: baseTitle,
        subtitle: 'Error',
        content: d.message || d.error || 'Unable to load diff.',
        kind: 'log',
      });
      return;
    }
    const subParts = [];
    if (d.branch && d.base) subParts.push(`${d.branch} vs ${d.base}`);
    if (d.file) subParts.push(d.file);
    if (d.truncated) subParts.push('truncated');
    openFileDrawerInline({
      title: title || d.file || d.branch || 'Diff',
      subtitle: subParts.join(' · '),
      content: d.diff || '',
      kind: 'diff',
    });
  } catch (_) {
    openFileDrawerInline({
      title: baseTitle,
      subtitle: 'Error',
      content: 'Failed to fetch diff from server.',
      kind: 'log',
    });
  }
}

export function createTerminalPathLinkProvider(term, address) {
  return {
    provideLinks(bufferLineNumber, callback) {
      if (!window.PathLinks) return callback(undefined);
      const buf = term.buffer && term.buffer.active;
      if (!buf) return callback(undefined);

      // 0-based index of the hovered row in xterm's buffer
      const row0 = bufferLineNumber - 1;
      const hoveredLine = buf.getLine(row0);
      if (!hoveredLine) return callback(undefined);

      // Expand upward/downward across soft-wrapped rows AND hard-wrapped rows from
      // herdr-core attach hydration (where a long path hits col N and continues at col 0).
      const cols = term.cols || 80;
      const isHardPathContinuation = (upperIdx, lowerIdx) => {
        const upper = buf.getLine(upperIdx);
        const lower = buf.getLine(lowerIdx);
        if (!upper || !lower) return false;
        if (lower.isWrapped) return true;
        const uText = upper.translateToString(true);
        const lText = lower.translateToString(true);
        if (!uText || !lText) return false;
        // Upper row reaches the right edge (within 2 cols) with no trailing space,
        // and lower row starts immediately with non-whitespace path characters.
        if (uText.length >= cols - 2 && !/\s$/.test(uText) && /^\S/.test(lText)) {
          const tailTok = uText.split(/\s+/).pop() || '';
          if (tailTok.includes('/') || tailTok.startsWith('~') || tailTok.startsWith('file:')) {
            return true;
          }
        }
        return false;
      };

      let startRow = row0;
      while (startRow > 0 && isHardPathContinuation(startRow - 1, startRow)) {
        startRow--;
      }
      let endRow = row0;
      while (endRow + 1 < buf.length && isHardPathContinuation(endRow, endRow + 1)) {
        endRow++;
      }

      // Build logical string and map each character offset to (row, col)
      const rows = [];
      let logical = '';
      for (let r = startRow; r <= endRow; r++) {
        const ln = buf.getLine(r);
        if (!ln) continue;
        const trimRight = (r === endRow) || !buf.getLine(r + 1)?.isWrapped;
        const text = ln.translateToString(trimRight);
        rows.push({ row1: r + 1, start: logical.length, end: logical.length + text.length });
        logical += text;
      }

      const matches = window.PathLinks.extractPathMatches(logical);
      if (!matches.length) return callback(undefined);

      // Look back up to 25 lines for the most recent absolute path dir (resolves e.g. `shots/`)
      let fallbackDir = '';
      const lookbackStart = Math.max(0, startRow - 25);
      for (let r = startRow; r >= lookbackStart && !fallbackDir; r--) {
        let sr = r;
        while (sr > lookbackStart && isHardPathContinuation(sr - 1, sr)) sr--;
        let er = r;
        while (er + 1 < buf.length && isHardPathContinuation(er, er + 1)) er++;
        let prevLogical = '';
        for (let k = sr; k <= er; k++) {
          const ln = buf.getLine(k);
          if (!ln) continue;
          const tr = (k === er) || !buf.getLine(k + 1)?.isWrapped;
          prevLogical += ln.translateToString(tr);
        }
        const prevMatches = window.PathLinks.extractPathMatches(prevLogical);
        for (let mi = prevMatches.length - 1; mi >= 0; mi--) {
          const d = window.PathLinks.dirnameOfAbsolute(prevMatches[mi].text);
          if (d) { fallbackDir = d; break; }
        }
        r = sr;
      }

      const cwd = terminalCwdFor(address);
      const posForOffset = (offset, isEnd) => {
        const idx = isEnd ? Math.max(0, offset - 1) : offset;
        for (const seg of rows) {
          if (idx >= seg.start && idx < seg.end) {
            return { x: (idx - seg.start) + 1, y: seg.row1 };
          }
        }
        const last = rows[rows.length - 1];
        return { x: Math.max(1, (last ? (last.end - last.start) : 1)), y: last ? last.row1 : bufferLineNumber };
      };

      Promise.all(matches.map(async (m) => {
        const stat = await statBoxPathCached(m.text, cwd, fallbackDir);
        if (!stat) return null;
        const startPos = posForOffset(m.start, false);
        const endPos = posForOffset(m.end, true);
        return {
          text: m.text,
          range: { start: startPos, end: endPos },
          decorations: { pointerCursor: true, underline: true },
          activate(event) {
            if (term.hasSelection && term.hasSelection()) return;
            if (event) event.preventDefault();
            const newTab = Boolean(event && (event.button === 1 || event.ctrlKey || event.metaKey));
            openFilePreview(stat.path, { line: stat.line, cwd, fallbackDir, newTab });
          },
        };
      })).then((resolved) => {
        const links = resolved.filter(Boolean);
        callback(links.length ? links : undefined);
      }).catch(() => callback(undefined));
    },
  };
}

// WebLinksAddon sees one buffer row at a time, so a URL that xterm soft-wraps
// gets split into unrelated links. Join each soft-wrapped run and expose only
// URLs that cross a row boundary; the addon continues to handle single-row URLs.
export function createWrappedUrlLinkProvider(term) {
  return {
    provideLinks(bufferLineNumber, callback) {
      const buf = term.buffer && term.buffer.active;
      if (!buf) return callback(undefined);
      const row0 = bufferLineNumber - 1;
      let startRow = row0;
      while (startRow > 0 && buf.getLine(startRow)?.isWrapped) startRow--;
      let endRow = row0;
      while (endRow + 1 < buf.length && buf.getLine(endRow + 1)?.isWrapped) endRow++;

      const rows = [];
      let logical = '';
      for (let r = startRow; r <= endRow; r++) {
        const line = buf.getLine(r);
        if (!line) continue;
        const value = line.translateToString(r === endRow);
        rows.push({ row1: r + 1, start: logical.length, end: logical.length + value.length });
        logical += value;
      }

      const posForOffset = (offset) => {
        for (const row of rows) {
          if (offset >= row.start && offset < row.end) {
            return { x: offset - row.start + 1, y: row.row1 };
          }
        }
        const last = rows[rows.length - 1];
        return { x: Math.max(1, last ? last.end - last.start : 1), y: last ? last.row1 : bufferLineNumber };
      };
      const links = [];
      const urlRe = /https?:\/\/[^\s"'<>`()[\]{}]+/gi;
      let match;
      while ((match = urlRe.exec(logical))) {
        let url = match[0];
        while (/[.,;:!?]+$/.test(url)) url = url.slice(0, -1);
        if (!url) continue;
        const start = match.index;
        const end = start + url.length;
        const firstRow = rows.find((row) => start >= row.start && start < row.end);
        const lastRow = rows.find((row) => end - 1 >= row.start && end - 1 < row.end);
        if (!firstRow || !lastRow || firstRow.row1 === lastRow.row1) continue;
        links.push({
          text: url,
          range: { start: posForOffset(start), end: posForOffset(end - 1) },
          decorations: { pointerCursor: true, underline: true },
          activate(event) {
            if (event) event.preventDefault();
            window.open(url, '_blank', 'noopener,noreferrer');
          },
        });
      }
      callback(links.length ? links : undefined);
    },
  };
}
