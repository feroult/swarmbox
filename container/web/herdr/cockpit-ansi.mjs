// Pure ANSI 24-bit helpers, cell-width math, layout engine, and tab/status formatters
// for the SwarmBox Terminal Cockpit.

import { SHELL_NAMES } from './agents.mjs';
import { HOME, detectLiveAgent } from './hc-client.mjs';

export const ESC = '\x1b';
export const RESET = '\x1b[0m';
export const SYNC_START = '\x1b[?2026h';
export const SYNC_END = '\x1b[?2026l';
export const ANSI_RE = /\x1b(?:\[[0-9;?]*[ -/]*[@-~]|\][^\x07\x1b]*(?:\x07|\x1b\\)|[()][0-9A-B]|[@-Z\\-_=>])/g;

export function hexToRgb(hex) {
  const m = String(hex || '').trim().match(/^#?([0-9a-f]{6})$/i);
  if (!m) return [212, 212, 216];
  const n = parseInt(m[1], 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

export function fgHex(hex) {
  const [r, g, b] = hexToRgb(hex);
  return `\x1b[38;2;${r};${g};${b}m`;
}

export function bgHex(hex) {
  const [r, g, b] = hexToRgb(hex);
  return `\x1b[48;2;${r};${g};${b}m`;
}

export function charDisplayWidth(ch) {
  const cp = ch.codePointAt(0);
  if (cp === undefined || cp < 0x20 || (cp >= 0x7f && cp < 0xa0)) return 0;
  // Combining marks
  if (
    (cp >= 0x0300 && cp <= 0x036f) ||
    (cp >= 0x1ab0 && cp <= 0x1aff) ||
    (cp >= 0x20d0 && cp <= 0x20ff) ||
    (cp >= 0xfe00 && cp <= 0xfe0f) ||
    (cp >= 0xfe20 && cp <= 0xfe2f)
  ) {
    return 0;
  }
  if (
    cp >= 0x1100 &&
    (cp <= 0x115f ||
      cp === 0x2329 ||
      cp === 0x232a ||
      (cp >= 0x2e80 && cp <= 0xa4cf && cp !== 0x303f) ||
      (cp >= 0xac00 && cp <= 0xd7a3) ||
      (cp >= 0xf900 && cp <= 0xfaff) ||
      (cp >= 0xfe10 && cp <= 0xfe19) ||
      (cp >= 0xfe30 && cp <= 0xfe6f) ||
      (cp >= 0xff00 && cp <= 0xff60) ||
      (cp >= 0xffe0 && cp <= 0xffe6) ||
      (cp >= 0x1f300 && cp <= 0x1fbff))
  ) {
    return 2;
  }
  return 1;
}

export function visibleWidth(str) {
  const plain = String(str || '').replace(ANSI_RE, '');
  let w = 0;
  for (const ch of plain) w += charDisplayWidth(ch);
  return w;
}

export function clipText(text, maxWidth) {
  const maxW = Math.max(0, maxWidth);
  if (maxW === 0) return '';
  const clean = String(text || '').replace(/[\r\n\t\x00-\x1f\x7f]/g, ' ');
  const chars = Array.from(clean);
  let total = 0;
  for (const ch of chars) total += charDisplayWidth(ch);
  if (total <= maxW) return clean;
  if (maxW === 1) return '…';
  let out = '';
  let w = 0;
  for (const ch of chars) {
    const cw = charDisplayWidth(ch);
    if (w + cw > maxW - 1) break;
    out += ch;
    w += cw;
  }
  return out + '…';
}

export function fitText(text, width) {
  const maxW = Math.max(0, width);
  if (maxW === 0) return '';
  const clipped = clipText(text, maxW);
  const w = visibleWidth(clipped);
  return w < maxW ? clipped + ' '.repeat(maxW - w) : clipped;
}

// Build a guaranteed exact-width row from styled segments: [{ text, style }]
// Truncates/pads cleanly so the resulting visible width is ALWAYS strictly `width`.
export function buildRow(width, baseBg, segments) {
  const target = Math.max(0, width);
  let out = baseBg;
  let used = 0;
  for (const seg of segments) {
    if (used >= target) break;
    const remain = target - used;
    const raw = String(seg.text || '').replace(/[\r\n\t\x00-\x1f\x7f]/g, ' ');
    let piece = '';
    let pw = 0;
    for (const ch of raw) {
      const cw = charDisplayWidth(ch);
      if (pw + cw > remain) break;
      piece += ch;
      pw += cw;
    }
    if (piece) {
      const styled = (seg.style || '') + piece + RESET + baseBg;
      if (seg.href && /^https?:\/\/[^\x00-\x1f\x7f\s]+$/i.test(seg.href)) {
        out += `\x1b]8;;${seg.href}\x1b\\${styled}\x1b]8;;\x1b\\`;
      } else {
        out += styled;
      }
      used += pw;
    }
  }
  if (used < target) out += ' '.repeat(target - used);
  return out + RESET;
}

export function computeLayout(cols, rows, opts = {}) {
  const W = Math.max(40, Number(cols) || 80);
  const H = Math.max(12, Number(rows) || 24);
  const wantSidebar = opts.sidebarOpen ?? (W >= 100);
  const wantSysop = opts.sysopOpen ?? (W >= 124);

  let sidebarW = wantSidebar && W >= 72 ? Math.min(25, Math.max(19, Math.floor(W * 0.2))) : 0;
  let sysopW = wantSysop && W >= 78 ? Math.min(36, Math.max(26, Math.floor(W * 0.28))) : 0;

  // Always preserve at least 30 columns for the center terminal viewport
  const minCenter = 30;
  const divLeft = sidebarW > 0 ? 1 : 0;
  const divRight = sysopW > 0 ? 1 : 0;
  if (W - sidebarW - divLeft - sysopW - divRight < minCenter) {
    if (opts.priority === 'sysop' && sysopW > 0) {
      sidebarW = 0;
    } else if (opts.priority === 'sidebar' && sidebarW > 0) {
      sysopW = 0;
    } else {
      sysopW = 0;
      if (W - sidebarW - (sidebarW > 0 ? 1 : 0) < minCenter) sidebarW = 0;
    }
  }

  const leftDiv = sidebarW > 0 ? 1 : 0;
  const rightDiv = sysopW > 0 ? 1 : 0;
  const bodyY = 1;
  const bodyH = Math.max(6, H - 2);
  const paneX = sidebarW + leftDiv;
  const paneW = Math.max(20, W - sidebarW - leftDiv - sysopW - rightDiv);
  const panePad = paneW >= 46 ? 1 : 0;
  const sysopX = paneX + paneW + rightDiv;

  return {
    W,
    H,
    bodyY,
    bodyH,
    sidebar: sidebarW > 0 ? { x: 0, y: bodyY, w: sidebarW, h: bodyH } : null,
    leftDivX: sidebarW > 0 ? sidebarW : -1,
    pane: { x: paneX, y: bodyY, w: paneW, h: bodyH, pad: panePad, innerW: paneW - panePad * 2 },
    rightDivX: sysopW > 0 ? paneX + paneW : -1,
    sysop: sysopW > 0 ? { x: sysopX, y: bodyY, w: sysopW, h: bodyH } : null,
    footerY: H - 1,
  };
}

export function wrapText(text, width, maxLines = 4) {
  const w = Math.max(4, width);
  const words = String(text || '').replace(/[\r\n\t\x00-\x1f\x7f]+/g, ' ').trim().split(/\s+/).filter(Boolean);
  if (words.length === 0) return [];
  const lines = [];
  let cur = '';
  let curW = 0;
  for (const word of words) {
    const ww = visibleWidth(word);
    if (!cur) {
      if (ww <= w) {
        cur = word;
        curW = ww;
      } else {
        let rest = word;
        while (visibleWidth(rest) > w && lines.length < maxLines) {
          let chunk = '';
          let cw = 0;
          let i = 0;
          const arr = Array.from(rest);
          for (; i < arr.length; i++) {
            const chW = charDisplayWidth(arr[i]);
            if (cw + chW > w) break;
            chunk += arr[i];
            cw += chW;
          }
          lines.push(chunk);
          rest = arr.slice(i).join('');
        }
        cur = rest;
        curW = visibleWidth(rest);
      }
    } else if (curW + 1 + ww <= w) {
      cur += ' ' + word;
      curW += 1 + ww;
    } else {
      lines.push(cur);
      if (lines.length >= maxLines) return lines.slice(0, maxLines);
      cur = clipText(word, w);
      curW = visibleWidth(cur);
    }
  }
  if (cur && lines.length < maxLines) lines.push(cur);
  return lines.slice(0, maxLines);
}

export function cleanStatusText(raw) {
  return String(raw || '')
    .replace(/\*\*([^*]+)\*\*/g, '$1')
    .replace(/`([^`]+)`/g, '$1')
    .replace(/\s+/g, ' ')
    .trim();
}

export function smartTabParts(t) {
  if (!t) return { title: 'no tab', pill: '' };
  const rawName = String(t.name || '').trim();
  const isGenericShell = !rawName || /^shell(?:-\d+)?$/i.test(rawName);
  const fg = String((t.foreground && t.foreground.name) || '').trim();
  const fgLow = fg.toLowerCase();
  const badge = detectLiveAgent(t);
  const pill = badge && (isGenericShell || !rawName.toLowerCase().includes(badge)) ? badge : '';

  if (!isGenericShell) return { title: rawName, pill };

  const cwd = String((t.foreground && t.foreground.cwd) || t.cwd || '').replace(/\/+$/, '');
  if (cwd && cwd !== HOME && cwd !== '/') {
    const base = cwd.slice(cwd.lastIndexOf('/') + 1);
    if (base) return { title: base, pill };
  }
  if (fg && !SHELL_NAMES.has(fgLow) && fgLow !== pill) {
    return { title: fg, pill };
  }
  return { title: rawName || 'shell', pill };
}

export function smartTabName(t) {
  const p = smartTabParts(t);
  return p.pill ? `${p.title} [${p.pill}]` : p.title;
}

export function statusMeta(term, pal) {
  const st = term && term.status && typeof term.status === 'object' ? term.status.state : null;
  if (st === 'working') return { dot: '◉', color: pal.accentBright, label: 'working' };
  if (st === 'blocked') return { dot: '◆', color: pal.amber, label: term.status.kind || 'blocked' };
  if (st === 'error') return { dot: '✖', color: pal.red, label: 'error' };
  if (st === 'done') return { dot: '●', color: pal.green, label: 'done' };
  if (st === 'idle') return { dot: '●', color: pal.green, label: 'idle' };
  return { dot: '○', color: pal.dim, label: 'shell' };
}

export function sysopStyle(state, pal) {
  if (state === 'working' || state === 'queued') return { color: pal.accentBright, pill: state.toUpperCase() };
  if (state === 'allow?') return { color: pal.amber, pill: 'ALLOW?' };
  if (state === 'sending') return { color: pal.amber, pill: 'SENDING' };
  if (state === 'done') return { color: pal.green, pill: 'DONE' };
  if (state === 'failed' || state === 'stopped') return { color: pal.red, pill: state.toUpperCase() };
  if (state === 'idle') return { color: pal.green, pill: 'IDLE' };
  return { color: pal.dim, pill: 'OFF' };
}
