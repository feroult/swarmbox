#!/usr/bin/env node
// SwarmBox × herdr-core Terminal Cockpit (`sx` / `swarmbox` interactive TUI).
//
// Provides full terminal parity with the SwarmBox Web UI on top of herdr-core (`hc connect`):
//   - Collapsible left sidebar with live OSC 7501 status dots (filters swarmbox.role=sysop)
//   - Full 24-bit TrueColor center terminal viewport backed by @xterm/headless
//   - Collapsible right Sysop panel with real-time state, ALLOW?/VETO cards, and framed goal composer
//   - Five synchronized themes persisted in ~/.config/swarmbox/herdr-web-theme
//   - Ctrl+A prefix + Alt shortcuts + SGR 1006 mouse support, zero host dependencies

import path from 'node:path';
import { fileURLToPath } from 'node:url';
import xtermHeadless from '@xterm/headless';
import {
  ALLOWED_AGENT_CMDS,
  HC_BIN,
  HERDR_THEMES,
  HOME,
  HerdrClient,
  SYSOP_BIN,
  THEME_ORDER,
  readActiveTab,
  readSavedTheme,
  readSysopSnapshot,
  runCommand,
  saveTheme,
  uniqueTabName,
  writeActiveTab,
} from './hc-client.mjs';

const HeadlessTerminal = xtermHeadless.Terminal || xtermHeadless.default?.Terminal;

// ---------------------------------------------------------------------------
// ANSI 24-bit helpers, exact cell-width math & pure layout engine
// ---------------------------------------------------------------------------
const ESC = '\x1b';
const RESET = '\x1b[0m';
const SYNC_START = '\x1b[?2026h';
const SYNC_END = '\x1b[?2026l';
const ANSI_RE = /\x1b(?:\[[0-9;?]*[ -/]*[@-~]|\][^\x07\x1b]*(?:\x07|\x1b\\)|[()][0-9A-B]|[@-Z\\-_=>])/g;

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
function buildRow(width, baseBg, segments) {
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
      out += (seg.style || '') + piece + RESET + baseBg;
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

function wrapText(text, width, maxLines = 4) {
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

const AGENT_APP_LABELS = {
  antigravity: 'agy',
  agy: 'agy',
  claude: 'claude',
  codex: 'codex',
  opencode: 'opencode',
  gemini: 'gemini',
};
const SHELL_NAMES = new Set(['bash', 'sh', 'zsh', 'dash', 'fish', '-bash', '-sh', '-zsh']);

function smartTabParts(t) {
  if (!t) return { title: 'no tab', pill: '', usedMsgAsTitle: false };
  const rawName = String(t.name || '').trim();
  const isGenericShell = !rawName || /^shell(?:-\d+)?$/i.test(rawName);
  const app = String((t.status && t.status.app) || '').toLowerCase();
  const fg = String((t.foreground && t.foreground.name) || '').trim();
  const fgLow = fg.toLowerCase();
  const badge = AGENT_APP_LABELS[app] || AGENT_APP_LABELS[fgLow] || '';
  const pill = badge && (isGenericShell || !rawName.toLowerCase().includes(badge)) ? badge : '';

  if (!isGenericShell) return { title: rawName, pill, usedMsgAsTitle: false };

  const stMsg = String((t.status && t.status.msg) || '').trim();
  if (badge === 'agy' && stMsg) {
    return { title: stMsg, pill: 'agy', usedMsgAsTitle: true };
  }

  const cwd = String((t.foreground && t.foreground.cwd) || t.cwd || '').replace(/\/+$/, '');
  if (cwd && cwd !== HOME && cwd !== '/') {
    const base = cwd.slice(cwd.lastIndexOf('/') + 1);
    if (base) return { title: base, pill, usedMsgAsTitle: false };
  }
  if (fg && !SHELL_NAMES.has(fgLow) && fgLow !== pill) {
    return { title: fg, pill, usedMsgAsTitle: false };
  }
  return { title: 'shell', pill, usedMsgAsTitle: false };
}

function smartTabName(t) {
  const p = smartTabParts(t);
  return p.pill ? `${p.title} [${p.pill}]` : p.title;
}

function statusMeta(term, pal) {
  const st = term && term.status && typeof term.status === 'object' ? term.status.state : null;
  if (st === 'working') return { dot: '◉', color: pal.accentBright, label: 'working' };
  if (st === 'blocked') return { dot: '◆', color: pal.amber, label: term.status.kind || 'blocked' };
  if (st === 'error') return { dot: '✖', color: pal.red, label: 'error' };
  if (st === 'done') return { dot: '●', color: pal.green, label: 'done' };
  if (st === 'idle') return { dot: '●', color: pal.green, label: 'idle' };
  return { dot: '○', color: pal.dim, label: 'shell' };
}

function sysopStyle(state, pal) {
  if (state === 'working' || state === 'queued') return { color: pal.accentBright, pill: state.toUpperCase() };
  if (state === 'allow?') return { color: pal.amber, pill: 'ALLOW?' };
  if (state === 'sending') return { color: pal.amber, pill: 'SENDING' };
  if (state === 'done') return { color: pal.green, pill: 'DONE' };
  if (state === 'failed' || state === 'stopped') return { color: pal.red, pill: state.toUpperCase() };
  if (state === 'idle') return { color: pal.green, pill: 'IDLE' };
  return { color: pal.dim, pill: 'OFF' };
}

// ---------------------------------------------------------------------------
// SGR 1006 mouse & escape input parser
// ---------------------------------------------------------------------------
const SGR_MOUSE_RE = /^\x1b\[<(\d+);(\d+);(\d+)([Mm])/;

// ---------------------------------------------------------------------------
// SwarmBox Terminal Cockpit
// ---------------------------------------------------------------------------
export class Cockpit {
  constructor(options = {}) {
    this.stdin = options.stdin || process.stdin;
    this.stdout = options.stdout || process.stdout;
    this.hc = options.hc || new HerdrClient(options.hcBin || HC_BIN, { quiet: true });
    this.sysopBin = options.sysopBin || SYSOP_BIN;

    this.themeName = readSavedTheme();
    this.terminals = [];
    this.activeAddr = readActiveTab();
    this.sysop = readSysopSnapshot([]);

    this.sidebarPref = null; // null = auto by width
    this.sysopPref = null;   // null = auto by width
    this.layoutPriority = 'sidebar';
    this.focus = 'terminal'; // 'terminal' | 'goal'
    this.goalDraft = '';
    this.goalCursor = 0;     // character index inside Array.from(this.goalDraft)
    this.prefixMode = false;
    this.prefixTimer = null;
    this.helpOpen = false;
    this.toast = '';
    this.toastTimer = null;
    this.scrollOffset = 0;

    // Active herdr-core stream + @xterm/headless buffer
    this.attachedAddr = null;
    this.stream = null;
    this.xterm = null;
    this.xtermCols = 0;
    this.xtermRows = 0;

    // Frame cache for flicker-free row diffing + clickable regions
    this.prevRows = [];
    this.hitboxes = [];
    this.goalCursorPos = null; // { x, y } 0-indexed coordinates computed during render
    this.renderQueued = false;
    this.closed = false;
    this.pollTimer = null;
    this._onDataBound = (chunk) => this._onStdin(chunk);
    this._onResizeBound = () => this._onResize();
  }

  palette() {
    return (HERDR_THEMES[this.themeName] || HERDR_THEMES['purple-glow']).cockpit;
  }

  cols() {
    return this.stdout.columns || Number(process.env.COLUMNS) || 100;
  }

  rows() {
    return this.stdout.rows || Number(process.env.LINES) || 30;
  }

  layout() {
    const W = this.cols();
    const H = this.rows();
    const autoSysop = W >= 124 || Boolean(this.sysop.pending && W >= 80) || this.focus === 'goal';
    return computeLayout(W, H, {
      sidebarOpen: this.sidebarPref !== null ? this.sidebarPref : W >= 100,
      sysopOpen: this.sysopPref !== null ? this.sysopPref : autoSysop,
      priority: this.focus === 'goal' || this.sysop.pending ? 'sysop' : this.layoutPriority,
    });
  }

  setToast(msg, ms = 2600) {
    this.toast = String(msg || '');
    if (this.toastTimer) clearTimeout(this.toastTimer);
    this.toastTimer = setTimeout(() => {
      this.toast = '';
      this.toastTimer = null;
      this.scheduleRender();
    }, ms);
    if (this.toastTimer.unref) this.toastTimer.unref();
    this.scheduleRender();
  }

  async start() {
    this.hc.on('snapshot', (list) => this._onTerminals(list));
    this.hc.on('hc-event', ({ terminals }) => this._onTerminals(terminals));

    await this.hc.start();

    if (this.stdin.isTTY && typeof this.stdin.setRawMode === 'function') {
      this.stdin.setRawMode(true);
    }
    this.stdin.resume();
    this.stdin.on('data', this._onDataBound);
    this.stdout.on('resize', this._onResizeBound);

    // Enter alternate screen, enable SGR mouse tracking, hide cursor until first paint
    this.stdout.write(`${ESC}[?1049h${ESC}[?1000h${ESC}[?1006h${ESC}[?25l${ESC}[2J`);

    this.terminals = this.hc.listSnapshot();
    await this._ensureActiveAttached();

    // Poll real swarmbox-sysop state + shared theme file (stays synced with Web UI)
    let pollTick = 0;
    let lastClockMin = new Date().getMinutes();
    this.pollTimer = setInterval(() => {
      if (this.closed) return;
      const diskTheme = readSavedTheme();
      let dirty = false;
      if (diskTheme !== this.themeName) {
        this.themeName = diskTheme;
        this.prevRows = [];
        dirty = true;
      }
      const curMin = new Date().getMinutes();
      if (curMin !== lastClockMin) {
        lastClockMin = curMin;
        dirty = true;
      }
      pollTick = (pollTick + 1) % 5;
      if (pollTick === 0 && typeof this.hc.refreshTerminals === 'function') {
        this.hc.refreshTerminals();
      }
      const nextSysop = readSysopSnapshot(this.terminals);
      const prevKey = JSON.stringify({
        up: this.sysop.up,
        state: this.sysop.state,
        sentence: this.sysop.sentence,
        pending: this.sysop.pending,
        stepsLen: this.sysop.steps.length,
        lastStep: this.sysop.steps[this.sysop.steps.length - 1]?.text,
        blocked: this.sysop.blocked,
      });
      const nextKey = JSON.stringify({
        up: nextSysop.up,
        state: nextSysop.state,
        sentence: nextSysop.sentence,
        pending: nextSysop.pending,
        stepsLen: nextSysop.steps.length,
        lastStep: nextSysop.steps[nextSysop.steps.length - 1]?.text,
        blocked: nextSysop.blocked,
      });
      if (prevKey !== nextKey || Boolean(nextSysop.pending?.deadline)) {
        this.sysop = nextSysop;
        dirty = true;
      }
      if (dirty) this.scheduleRender();
    }, 500);
    if (this.pollTimer.unref) this.pollTimer.unref();

    this.scheduleRender(true);
  }

  shutdown(code = 0) {
    if (this.closed) return;
    this.closed = true;
    if (this.pollTimer) clearInterval(this.pollTimer);
    if (this.prefixTimer) clearTimeout(this.prefixTimer);
    if (this.toastTimer) clearTimeout(this.toastTimer);
    this.stdin.off('data', this._onDataBound);
    this.stdout.off('resize', this._onResizeBound);
    if (this.stream) {
      try { this.stream.close(); } catch (_) {}
      this.stream = null;
    }
    if (this.xterm) {
      try { this.xterm.dispose(); } catch (_) {}
      this.xterm = null;
    }
    this.hc.close();
    if (this.stdin.isTTY && typeof this.stdin.setRawMode === 'function') {
      try { this.stdin.setRawMode(false); } catch (_) {}
    }
    try {
      this.stdout.write(`${ESC}[?1006l${ESC}[?1000l${ESC}[?25h${RESET}${ESC}[?1049l`);
    } catch (_) {}
    if (code !== null) process.exit(code);
  }

  _onResize() {
    this.prevRows = [];
    this._syncPaneSize();
    this.scheduleRender(true);
  }

  _syncPaneSize() {
    const L = this.layout();
    const c = L.pane.innerW;
    const r = L.pane.h;
    if (this.xterm && (this.xtermCols !== c || this.xtermRows !== r)) {
      this.xtermCols = c;
      this.xtermRows = r;
      try { this.xterm.resize(c, r); } catch (_) {}
      if (this.stream) {
        try { this.stream.resize(c, r); } catch (_) {}
      }
    }
  }

  _onTerminals(list) {
    this.terminals = Array.isArray(list) ? list : [];
    this.sysop = readSysopSnapshot(this.terminals);
    const hasActive = this.terminals.some((t) => t.address === this.activeAddr);
    if (!hasActive) {
      this.activeAddr = this.terminals[0]?.address || null;
      this._ensureActiveAttached().catch(() => {});
    } else if (this.attachedAddr !== this.activeAddr) {
      this._ensureActiveAttached().catch(() => {});
    }
    this.scheduleRender();
  }

  async _ensureActiveAttached() {
    if (this.closed) return;
    if (this.terminals.length === 0) {
      try {
        const created = await this.hc.call('terminal.run', {
          argv: ['/bin/bash', '-l'],
          name: uniqueTabName('shell', 'shell', this.terminals),
          cwd: HOME,
          keep: true,
          no_parent: true,
        });
        const addr = created?.terminal?.address;
        if (addr) {
          this.activeAddr = addr;
          this.terminals = this.hc.listSnapshot();
        }
      } catch (err) {
        this.setToast(`Failed to open shell: ${err.message}`);
        return;
      }
    }
    if (!this.activeAddr || !this.terminals.some((t) => t.address === this.activeAddr)) {
      this.activeAddr = this.terminals[0]?.address || null;
    }
    if (!this.activeAddr || this.attachedAddr === this.activeAddr) return;
    await this._attachTo(this.activeAddr);
  }

  async _attachTo(addr) {
    if (this.closed || !addr) return;
    if (this.stream) {
      try { this.stream.close(); } catch (_) {}
      this.stream = null;
    }
    if (this.xterm) {
      try { this.xterm.dispose(); } catch (_) {}
      this.xterm = null;
    }
    this.attachedAddr = addr;
    this.activeAddr = addr;
    this.scrollOffset = 0;
    writeActiveTab(addr);

    const L = this.layout();
    this.xtermCols = L.pane.innerW;
    this.xtermRows = L.pane.h;
    const term = new HeadlessTerminal({
      cols: this.xtermCols,
      rows: this.xtermRows,
      scrollback: 2000,
      allowProposedApi: true,
    });
    this.xterm = term;
    this.prevRows = [];

    try {
      const stream = await this.hc.attach(
        addr,
        this.xtermCols,
        this.xtermRows,
        {
          onData: (buf) => {
            if (this.xterm !== term || this.closed) return;
            term.write(buf, () => this.scheduleRender());
          },
          onClose: () => {
            if (this.attachedAddr === addr) {
              this.attachedAddr = null;
              this.stream = null;
              this.scheduleRender();
            }
          },
        },
        400,
      );
      if (this.attachedAddr !== addr || this.closed) {
        stream.close();
        return;
      }
      this.stream = stream;
      stream.focus(true);
      this.scheduleRender(true);
    } catch (err) {
      this.setToast(`Attach error: ${err.message}`);
    }
  }

  async _createTab(preset) {
    const cwd = HOME;
    let argv = ['/bin/bash', '-l'];
    let prefix = 'shell';
    if (preset === 'agent') {
      const requested = String(process.env.SWARMBOX_AGENT || 'yolo').trim();
      const cmd = ALLOWED_AGENT_CMDS.has(requested) ? requested : 'yolo';
      argv = ['/bin/bash', '-lic', `${cmd}; exec /bin/bash -l`];
      prefix = cmd === 'yolo' ? 'agent' : cmd;
    }
    try {
      const created = await this.hc.call('terminal.run', {
        argv,
        name: uniqueTabName(prefix, prefix, this.terminals),
        cwd,
        keep: true,
        no_parent: true,
      });
      const addr = created?.terminal?.address;
      if (addr) {
        this.setToast(`Opened ${created.terminal.name || preset}`);
        await this._attachTo(addr);
      }
    } catch (err) {
      this.setToast(`New tab failed: ${err.message}`);
    }
  }

  async _closeActiveTab() {
    if (this.terminals.length <= 1) {
      this.setToast('Last tab — use Ctrl+A d to detach');
      return;
    }
    const target = this.activeAddr;
    if (!target) return;
    try {
      await this.hc.call('terminal.kill', { terminal: target });
      this.hc.call('terminal.rm', { terminal: target }).catch(() => {});
      this.setToast(`Closed ${target}`);
    } catch (err) {
      this.setToast(`Close failed: ${err.message}`);
    }
  }

  _switchIndex(idx) {
    if (idx < 0 || idx >= this.terminals.length) return;
    const t = this.terminals[idx];
    if (t && t.address !== this.activeAddr) {
      this._attachTo(t.address).catch(() => {});
    }
  }

  _cycleTab(delta) {
    if (this.terminals.length <= 1) return;
    const cur = Math.max(0, this.terminals.findIndex((t) => t.address === this.activeAddr));
    const next = (cur + delta + this.terminals.length) % this.terminals.length;
    this._switchIndex(next);
  }

  _cycleTheme() {
    const i = THEME_ORDER.indexOf(this.themeName);
    const next = THEME_ORDER[(i + 1) % THEME_ORDER.length];
    this.themeName = next;
    saveTheme(next);
    this.prevRows = [];
    this.setToast(`Theme: ${HERDR_THEMES[next].label}`);
  }

  _toggleSidebar() {
    const cur = this.layout().sidebar !== null;
    this.sidebarPref = !cur;
    this.layoutPriority = 'sidebar';
    this.prevRows = [];
    this._syncPaneSize();
    this.scheduleRender(true);
  }

  _toggleSysop() {
    const cur = this.layout().sysop !== null;
    this.sysopPref = !cur;
    this.layoutPriority = 'sysop';
    if (!this.sysopPref && this.focus === 'goal') this.focus = 'terminal';
    this.prevRows = [];
    this._syncPaneSize();
    this.scheduleRender(true);
  }

  _focusGoal() {
    this.sysopPref = true;
    this.layoutPriority = 'sysop';
    this.focus = 'goal';
    this.goalCursor = Array.from(this.goalDraft).length;
    this.prevRows = [];
    this._syncPaneSize();
    this.scheduleRender(true);
  }

  async _submitGoal() {
    const goal = this.goalDraft.trim();
    this.goalDraft = '';
    this.goalCursor = 0;
    this.focus = 'terminal';
    this.scheduleRender();
    if (!goal) return;
    if (this.activeAddr) writeActiveTab(this.activeAddr);
    this.setToast('Sending goal to Sysop…');
    const r = await runCommand(this.sysopBin, ['goal', '--source', 'cockpit', '--', '-'], goal + '\n');
    if (r.ok) {
      this.setToast(`Goal queued (${r.stdout || 'ok'})`);
    } else {
      this.setToast(`Sysop error: ${(r.stderr || r.stdout || 'failed').slice(0, 60)}`);
    }
    this.sysop = readSysopSnapshot(this.terminals);
    this.scheduleRender();
  }

  async _sysopAction(action) {
    if (action === 'approve' && !this.sysop.pending && this.sysop.blocked.length > 0) {
      const b = this.sysop.blocked[0];
      await this.hc.call('terminal.send', { terminal: b.terminal, text: 'y', force: true }).catch(() => {});
      this.setToast(`Allowed ${b.name}`);
      return;
    }
    if (action === 'veto' && !this.sysop.pending && this.sysop.blocked.length > 0) {
      const b = this.sysop.blocked[0];
      await this.hc.call('terminal.send', { terminal: b.terminal, text: 'n', force: true }).catch(() => {});
      this.setToast(`Denied ${b.name}`);
      return;
    }
    const r = await runCommand(this.sysopBin, [action]);
    this.setToast(r.ok ? `Sysop: ${r.stdout || action}` : `Sysop: ${(r.stderr || r.stdout || 'nothing waiting').slice(0, 56)}`);
    this.sysop = readSysopSnapshot(this.terminals);
    this.scheduleRender();
  }

  _scroll(delta) {
    if (!this.xterm) return;
    const maxScroll = this.xterm.buffer.active.baseY;
    this.scrollOffset = Math.max(0, Math.min(maxScroll, this.scrollOffset + delta));
    this.scheduleRender();
  }

  // -------------------------------------------------------------------------
  // Input handling (Ctrl+A prefix, Alt shortcuts, Goal editor, SGR mouse, PTY)
  // -------------------------------------------------------------------------
  _onStdin(chunk) {
    if (this.closed) return;
    let buf = Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk);

    while (buf.length > 0) {
      const str = buf.toString('utf8');
      const m = str.match(SGR_MOUSE_RE);
      if (m) {
        const consumed = Buffer.byteLength(m[0], 'utf8');
        this._handleMouse(Number(m[1]), Number(m[2]) - 1, Number(m[3]) - 1, m[4] === 'M');
        buf = buf.subarray(consumed);
        continue;
      }

      if (this.helpOpen) {
        this.helpOpen = false;
        this.prevRows = [];
        this.scheduleRender(true);
        return;
      }

      if (this.focus === 'goal') {
        this._handleGoalKey(buf);
        return;
      }

      if (this.prefixMode) {
        this._clearPrefix();
        const byte = buf[0];
        const rest = buf.subarray(1);
        this._handlePrefixKey(byte);
        buf = rest;
        continue;
      }

      if (str.startsWith('\x1b[5;2~')) {
        this._scroll(Math.max(3, Math.floor(this.layout().pane.h / 2)));
        buf = buf.subarray(6);
        continue;
      }
      if (str.startsWith('\x1b[6;2~')) {
        this._scroll(-Math.max(3, Math.floor(this.layout().pane.h / 2)));
        buf = buf.subarray(6);
        continue;
      }

      if (buf.length === 2 && buf[0] === 0x1b) {
        const ch = String.fromCharCode(buf[1]);
        if (this._handleAltKey(ch)) return;
      }

      if (buf[0] === 0x01) {
        this._enterPrefix();
        buf = buf.subarray(1);
        continue;
      }

      if (this.scrollOffset > 0) {
        this.scrollOffset = 0;
        this.scheduleRender();
      }
      if (this.stream) {
        this.stream.write(buf);
      }
      return;
    }
  }

  _enterPrefix() {
    this.prefixMode = true;
    if (this.prefixTimer) clearTimeout(this.prefixTimer);
    this.prefixTimer = setTimeout(() => {
      this.prefixMode = false;
      this.prefixTimer = null;
      this.scheduleRender();
    }, 3000);
    if (this.prefixTimer.unref) this.prefixTimer.unref();
    this.scheduleRender();
  }

  _clearPrefix() {
    this.prefixMode = false;
    if (this.prefixTimer) {
      clearTimeout(this.prefixTimer);
      this.prefixTimer = null;
    }
  }

  _handlePrefixKey(byte) {
    if (byte === 0x01) {
      if (this.stream) this.stream.write(Buffer.from([0x01]));
      this.scheduleRender();
      return;
    }
    if (byte === 0x1b) {
      this.scheduleRender();
      return;
    }
    const ch = String.fromCharCode(byte);
    if (ch >= '1' && ch <= '9') {
      this._switchIndex(Number(ch) - 1);
    } else if (ch === 'n') {
      this._cycleTab(1);
    } else if (ch === 'p') {
      this._cycleTab(-1);
    } else if (ch === 'c') {
      this._createTab('shell');
    } else if (ch === 'C') {
      this._createTab('agent');
    } else if (ch === 'x') {
      this._closeActiveTab();
    } else if (ch === 'b') {
      this._toggleSidebar();
    } else if (ch === 's') {
      this._toggleSysop();
    } else if (ch === 'g') {
      this._focusGoal();
    } else if (ch === 'a') {
      this._sysopAction('approve');
    } else if (ch === 'v') {
      this._sysopAction('veto');
    } else if (ch === 'X') {
      this._sysopAction('stop');
    } else if (ch === 't') {
      this._cycleTheme();
    } else if (ch === 'd' || ch === 'q') {
      this.shutdown(0);
    } else if (ch === '?') {
      this.helpOpen = true;
      this.prevRows = [];
      this.scheduleRender(true);
    } else {
      this.scheduleRender();
    }
  }

  _handleAltKey(ch) {
    if (ch >= '1' && ch <= '9') {
      this._switchIndex(Number(ch) - 1);
      return true;
    }
    const low = ch.toLowerCase();
    if (low === 'n') { this._createTab('shell'); return true; }
    if (low === 'b') { this._toggleSidebar(); return true; }
    if (low === 's') { this._toggleSysop(); return true; }
    if (low === 'g') { this._focusGoal(); return true; }
    if (low === 't') { this._cycleTheme(); return true; }
    return false;
  }

  _handleGoalKey(buf) {
    const s = buf.toString('utf8');
    const chars = Array.from(this.goalDraft);
    this.goalCursor = Math.max(0, Math.min(chars.length, this.goalCursor));

    if (s === '\x1b' || s === '\x03') {
      this.focus = 'terminal';
      this.scheduleRender();
      return;
    }
    if (s === '\r' || s === '\n') {
      this._submitGoal();
      return;
    }
    if (s === '\x1b[D') { // Left arrow
      if (this.goalCursor > 0) this.goalCursor -= 1;
      this.scheduleRender();
      return;
    }
    if (s === '\x1b[C') { // Right arrow
      if (this.goalCursor < chars.length) this.goalCursor += 1;
      this.scheduleRender();
      return;
    }
    if (s === '\x1b[H' || s === '\x01') { // Home / Ctrl+A
      this.goalCursor = 0;
      this.scheduleRender();
      return;
    }
    if (s === '\x1b[F' || s === '\x05') { // End / Ctrl+E
      this.goalCursor = chars.length;
      this.scheduleRender();
      return;
    }
    if (s === '\x7f' || s === '\x08') { // Backspace
      if (this.goalCursor > 0) {
        chars.splice(this.goalCursor - 1, 1);
        this.goalDraft = chars.join('');
        this.goalCursor -= 1;
        this.scheduleRender();
      }
      return;
    }
    if (s === '\x1b[3~') { // Delete
      if (this.goalCursor < chars.length) {
        chars.splice(this.goalCursor, 1);
        this.goalDraft = chars.join('');
        this.scheduleRender();
      }
      return;
    }
    if (s === '\x15') { // Ctrl+U
      this.goalDraft = '';
      this.goalCursor = 0;
      this.scheduleRender();
      return;
    }
    const printable = s.replace(/\x1b\[[0-9;?]*[ -/]*[@-~]/g, '').replace(/[\x00-\x1f\x7f]/g, '');
    if (printable) {
      const ins = Array.from(printable);
      chars.splice(this.goalCursor, 0, ...ins);
      this.goalDraft = chars.join('');
      this.goalCursor += ins.length;
      this.scheduleRender();
    }
  }

  _handleMouse(btn, x, y, press) {
    if (!press) return;
    if (btn === 64) { this._scroll(3); return; }
    if (btn === 65) { this._scroll(-3); return; }
    if (btn !== 0) return;

    for (const hb of this.hitboxes) {
      if (y >= hb.y1 && y <= hb.y2 && x >= hb.x1 && x <= hb.x2) {
        hb.onClick();
        return;
      }
    }

    const L = this.layout();
    if (x >= L.pane.x && x < L.pane.x + L.pane.w && y >= L.pane.y && y < L.pane.y + L.pane.h) {
      if (this.focus !== 'terminal') {
        this.focus = 'terminal';
        this.scheduleRender();
      }
    }
  }

  // -------------------------------------------------------------------------
  // Compositor (24-bit TrueColor, synchronized output, exact cell-width rows)
  // -------------------------------------------------------------------------
  scheduleRender(forceFull = false) {
    if (forceFull) this.prevRows = [];
    if (this.renderQueued || this.closed) return;
    this.renderQueued = true;
    setImmediate(() => {
      this.renderQueued = false;
      if (!this.closed) this.render();
    });
  }

  buildFrame() {
    const L = this.layout();
    const pal = this.palette();
    this.hitboxes = [];
    this.goalCursorPos = null;
    const rows = new Array(L.H);

    rows[0] = this._renderTopBar(L, pal);

    const sidebarLines = L.sidebar ? this._renderSidebar(L.sidebar, pal) : null;
    const paneLines = this._renderTerminalPane(L.pane, pal);
    const sysopLines = L.sysop ? this._renderSysopPanel(L.sysop, pal) : null;
    const divLeft = `${bgHex(pal.bg)}${fgHex(pal.border)}│${RESET}`;
    const divRight = `${bgHex(pal.bg)}${fgHex(this.focus === 'goal' ? pal.borderStrong : pal.border)}│${RESET}`;

    for (let i = 0; i < L.bodyH; i++) {
      let line = '';
      if (sidebarLines) line += sidebarLines[i] + divLeft;
      line += paneLines[i];
      if (sysopLines) line += divRight + sysopLines[i];
      rows[L.bodyY + i] = line + RESET;
    }

    rows[L.footerY] = this._renderFooter(L, pal);

    if (this.helpOpen) {
      this._overlayHelp(rows, L, pal);
    }

    return { L, rows };
  }

  render() {
    const { L, rows } = this.buildFrame();

    let out = SYNC_START + `${ESC}[?25l`;
    for (let r = 0; r < L.H; r++) {
      if (this.prevRows[r] !== rows[r]) {
        out += `${ESC}[${r + 1};1H${rows[r]}`;
        this.prevRows[r] = rows[r];
      }
    }

    // Position real 1-indexed terminal cursor accurately
    if (!this.helpOpen) {
      if (this.focus === 'goal' && this.goalCursorPos) {
        out += `${ESC}[${this.goalCursorPos.y + 1};${this.goalCursorPos.x + 1}H${ESC}[?25h`;
      } else if (this.xterm && this.scrollOffset === 0) {
        const b = this.xterm.buffer.active;
        const cx = Math.min(L.pane.innerW - 1, Math.max(0, b.cursorX));
        const cy = Math.min(L.pane.h - 1, Math.max(0, b.cursorY));
        out += `${ESC}[${L.pane.y + cy + 1};${L.pane.x + L.pane.pad + cx + 1}H${ESC}[?25h`;
      }
    }

    out += SYNC_END;
    this.stdout.write(out);
  }

  _renderTopBar(L, pal) {
    const bgS = bgHex(pal.surface);
    const active = this.terminals.find((t) => t.address === this.activeAddr);
    const activeName = smartTabName(active);
    const sm = statusMeta(active, pal);
    const ss = sysopStyle(this.sysop.state, pal);
    const themeLabel = (HERDR_THEMES[this.themeName] || HERDR_THEMES['purple-glow']).label;
    const now = new Date();
    const clock = `${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}`;

    const rightSegments = [];
    let rightW = 0;
    const urgentSysop = this.sysop.state === 'allow?' || this.sysop.state === 'sending';
    const showTopSysop = !L.sysop || urgentSysop;
    const sysopSeg = urgentSysop
      ? [
          { text: '◆ ', style: fgHex(ss.color) },
          { text: `SYSOP · ${ss.pill}`, style: `${fgHex(ss.color)}\x1b[1m` },
        ]
      : [
          { text: '● ', style: fgHex(ss.color) },
          { text: 'SYSOP', style: fgHex(pal.muted) },
          { text: ' · ', style: fgHex(pal.dim) },
          { text: ss.pill, style: `${fgHex(ss.color)}\x1b[1m` },
        ];
    if (L.W >= 96) {
      if (showTopSysop) {
        rightSegments.push(...sysopSeg, { text: '  ·  ', style: fgHex(pal.dim) });
      }
      rightSegments.push(
        { text: '◐ ', style: fgHex(pal.accent) },
        { text: themeLabel, style: fgHex(pal.muted) },
      );
      if (L.W >= 112) {
        rightSegments.push(
          { text: '  ·  ', style: fgHex(pal.dim) },
          { text: clock, style: fgHex(pal.dim) },
        );
      }
      rightSegments.push(
        { text: '  ·  ', style: fgHex(pal.dim) },
        { text: '^A?', style: fgHex(pal.accent) },
        { text: ' ', style: '' },
      );
    } else if (L.W >= 68) {
      rightSegments.push(
        ...sysopSeg,
        { text: '  ·  ', style: fgHex(pal.dim) },
        { text: '^A? ', style: fgHex(pal.accent) },
      );
    } else {
      rightSegments.push(...sysopSeg, { text: ' ', style: '' });
    }
    for (const seg of rightSegments) rightW += visibleWidth(seg.text);

    const maxLeft = Math.max(12, L.W - rightW - 1);
    const leftSegments = [
      { text: ' ● ', style: `${fgHex(pal.accentBright)}\x1b[1m` },
      { text: 'SWARMBOX', style: `${fgHex(pal.text)}\x1b[1m` },
      { text: ' · ', style: fgHex(pal.dim) },
      { text: 'herdr', style: fgHex(pal.accent) },
    ];
    let leftW = leftSegments.reduce((a, s) => a + visibleWidth(s.text), 0);

    const crumbBudget = maxLeft - leftW;
    if (crumbBudget > 8) {
      const rawCwd = String((active && active.foreground && active.foreground.cwd) || (active && active.cwd) || '');
      const shortCwd = rawCwd === HOME ? '~' : (rawCwd.startsWith(HOME + '/') ? '~' + rawCwd.slice(HOME.length) : rawCwd);
      const hasRichStatus = active && active.status && typeof active.status === 'object' && active.status.state;
      const suffixText = hasRichStatus
        ? ` · ${sm.label}`
        : (shortCwd && shortCwd !== activeName ? ` · ${clipText(shortCwd, 22)}` : '');
      const suffixStyle = hasRichStatus ? fgHex(sm.color) : fgHex(pal.dim);
      const nameRoom = Math.max(4, crumbBudget - 5 - visibleWidth(suffixText));
      const shownName = clipText(activeName, nameRoom);
      leftSegments.push(
        { text: '  ›  ', style: fgHex(pal.dim) },
        { text: shownName, style: `${fgHex(pal.text)}\x1b[1m` },
      );
      leftW += 5 + visibleWidth(shownName);
      if (suffixText && leftW + visibleWidth(suffixText) <= maxLeft) {
        leftSegments.push({ text: suffixText, style: suffixStyle });
        leftW += visibleWidth(suffixText);
      }
    }

    const gap = Math.max(1, L.W - leftW - rightW);
    const allSegments = [...leftSegments, { text: ' '.repeat(gap), style: '' }, ...rightSegments];

    this.hitboxes.push({
      x1: Math.max(0, L.W - rightW),
      x2: Math.max(0, L.W - 1),
      y1: 0,
      y2: 0,
      onClick: () => this._toggleSysop(),
    });
    this.hitboxes.push({
      x1: 0,
      x2: 18,
      y1: 0,
      y2: 0,
      onClick: () => this._toggleSidebar(),
    });
    return buildRow(L.W, bgS, allSegments);
  }

  _renderSidebar(box, pal) {
    const out = [];
    const bgS = bgHex(pal.surface);
    const bgBand = bgHex(pal.band);
    const bgBtn = bgHex(pal.surface2);

    // Header: " TERMINALS" left + count pill right + subtle hairline divider
    const countStr = String(this.terminals.length);
    const headLeft = ' TERMINALS';
    const headGap = Math.max(1, box.w - visibleWidth(headLeft) - countStr.length - 1);
    out.push(
      buildRow(box.w, bgS, [
        { text: headLeft, style: `${fgHex(pal.dim)}\x1b[1m` },
        { text: ' '.repeat(headGap), style: '' },
        { text: countStr, style: `${fgHex(pal.accent)}\x1b[1m` },
        { text: ' ', style: '' },
      ]),
    );
    out.push(buildRow(box.w, bgS, [{ text: '─'.repeat(box.w), style: fgHex(pal.border) }]));

    const footerRows = 3; // hairline + [+ New tab] + [Theme]
    const listMax = Math.max(1, box.h - 2 - footerRows);
    const renderedTabRows = [];
    const allowSubRows = listMax >= this.terminals.length * 2;

    for (let i = 0; i < this.terminals.length && renderedTabRows.length < listMax; i++) {
      const t = this.terminals[i];
      const isAct = t.address === this.activeAddr;
      const sm = statusMeta(t, pal);
      const { title: tabTitle, pill, usedMsgAsTitle } = smartTabParts(t);
      const rowY = box.y + 2 + renderedTabRows.length;
      const onSelect = () => this._attachTo(t.address).catch(() => {});

      const idxStr = i < 9 ? `${i + 1}` : '·';
      const pct = t.status && t.status.state === 'working' && typeof t.status.progress === 'number'
        ? Math.max(0, Math.min(100, Math.round(t.status.progress)))
        : null;
      const pctStr = pct !== null ? `${pct}% ` : '';
      const pillStr = pill ? ` ${pill}` : '';
      const rowBg = isAct ? bgBand : bgS;
      const rightMetaW = visibleWidth(pillStr) + visibleWidth(pctStr) + visibleWidth(idxStr) + 2;
      const nameBudget = Math.max(3, box.w - 4 - rightMetaW);
      const shown = pill ? clipText(tabTitle, nameBudget) : fitText(tabTitle, nameBudget);
      const padAfterPill = pill ? ' '.repeat(Math.max(0, nameBudget - visibleWidth(shown))) : '';

      this.hitboxes.push({ x1: box.x, x2: box.x + box.w - 1, y1: rowY, y2: rowY, onClick: onSelect });
      renderedTabRows.push(
        buildRow(box.w, rowBg, [
          { text: isAct ? '▌' : ' ', style: isAct ? fgHex(pal.accentBright) : '' },
          { text: ' ', style: '' },
          { text: sm.dot, style: fgHex(sm.color) },
          { text: ' ', style: '' },
          { text: shown, style: isAct ? `${fgHex(pal.text)}\x1b[1m` : fgHex(pal.muted) },
          ...(pill ? [{ text: pillStr, style: fgHex(pal.accent) }, { text: padAfterPill, style: '' }] : []),
          { text: ' ', style: '' },
          ...(pctStr ? [{ text: pctStr, style: fgHex(pal.accent) }] : []),
          { text: idxStr, style: isAct ? fgHex(pal.accent) : fgHex(pal.dim) },
          { text: ' ', style: '' },
        ]),
      );

      // Optional rich OSC 7501 sub-row (SwarmBox ▰▱ progress bar or blocked message) when space allows
      if (allowSubRows && renderedTabRows.length < listMax && t.status && typeof t.status === 'object') {
        const subY = box.y + 2 + renderedTabRows.length;
        if (t.status.state === 'working' && !usedMsgAsTitle && (pct !== null || t.status.msg)) {
          const barLen = 6;
          const filled = pct !== null ? Math.round((pct / 100) * barLen) : 3;
          const barSegs = pct !== null
            ? [
                { text: '▰'.repeat(filled), style: fgHex(pal.accent) },
                { text: '▱'.repeat(barLen - filled), style: fgHex(pal.border) },
                { text: ' ', style: '' },
              ]
            : [];
          const msgBudget = Math.max(4, box.w - 5 - (pct !== null ? barLen + 1 : 0));
          const msgTxt = clipText(t.status.msg || 'working…', msgBudget);
          this.hitboxes.push({ x1: box.x, x2: box.x + box.w - 1, y1: subY, y2: subY, onClick: onSelect });
          renderedTabRows.push(
            buildRow(box.w, rowBg, [
              { text: isAct ? '▌' : ' ', style: isAct ? fgHex(pal.accent) : '' },
              { text: '   ', style: '' },
              ...barSegs,
              { text: msgTxt, style: fgHex(pal.dim) },
            ]),
          );
        } else if (t.status.state === 'blocked' && t.status.msg) {
          this.hitboxes.push({ x1: box.x, x2: box.x + box.w - 1, y1: subY, y2: subY, onClick: onSelect });
          renderedTabRows.push(
            buildRow(box.w, rowBg, [
              { text: isAct ? '▌' : ' ', style: isAct ? fgHex(pal.amber) : '' },
              { text: '   ↳ ', style: fgHex(pal.amber) },
              { text: clipText(t.status.msg, Math.max(4, box.w - 6)), style: fgHex(pal.amber) },
            ]),
          );
        }
      }
    }

    while (renderedTabRows.length < listMax) renderedTabRows.push(buildRow(box.w, bgS, []));
    out.push(...renderedTabRows);

    const actY = box.y + 2 + listMax;
    out.push(buildRow(box.w, bgS, [{ text: '─'.repeat(box.w), style: fgHex(pal.border) }]));

    const actionRow = (bg, iconCol, leftTxt, hintTxt) => {
      const rightW = visibleWidth(hintTxt) + 1;
      const leftBudget = Math.max(4, box.w - rightW - 1);
      const leftFit = fitText(leftTxt, leftBudget);
      return buildRow(box.w, bg, [
        { text: ' ', style: '' },
        { text: leftFit, style: iconCol },
        { text: hintTxt, style: fgHex(pal.dim) },
        { text: ' ', style: '' },
      ]);
    };

    out.push(actionRow(bgBtn, `${fgHex(pal.accentBright)}\x1b[1m`, '+ New tab', '^Ac'));
    this.hitboxes.push({ x1: box.x, x2: box.x + box.w - 1, y1: actY + 1, y2: actY + 1, onClick: () => this._createTab('shell') });

    const tLabel = (HERDR_THEMES[this.themeName] || HERDR_THEMES['purple-glow']).label;
    out.push(actionRow(bgS, fgHex(pal.muted), `◐ ${tLabel}`, '^At'));
    this.hitboxes.push({ x1: box.x, x2: box.x + box.w - 1, y1: actY + 2, y2: actY + 2, onClick: () => this._cycleTheme() });

    while (out.length < box.h) out.push(buildRow(box.w, bgS, []));
    return out.slice(0, box.h);
  }

  _renderTerminalPane(box, pal) {
    const bgDefault = bgHex(pal.bg);
    const fgDefault = fgHex(pal.termFg);
    const padStr = box.pad > 0 ? `${bgDefault}${' '.repeat(box.pad)}` : '';
    const emptyRow = `${bgDefault}${fgDefault}${' '.repeat(box.w)}${RESET}`;

    if (!this.xterm) {
      const lines = new Array(box.h).fill(emptyRow);
      if (box.h > 2) {
        lines[Math.floor(box.h / 2)] = buildRow(box.w, bgDefault, [
          { text: '  Connecting to herdr-core…', style: fgHex(pal.dim) },
        ]);
      }
      return lines;
    }

    const buf = this.xterm.buffer.active;
    const baseRow = Math.max(0, buf.viewportY - this.scrollOffset);
    const cell = buf.getNullCell();
    const out = [];

    for (let y = 0; y < box.h; y++) {
      const line = buf.getLine(baseRow + y);
      if (!line) {
        out.push(emptyRow);
        continue;
      }

      let rowStr = padStr;
      let lastStyle = '';
      let col = 0;

      while (col < box.innerW) {
        line.getCell(col, cell);
        const w = cell.getWidth();
        if (w === 0) {
          col += 1;
          continue;
        }
        let ch = cell.getChars();
        if (!ch || cell.isInvisible()) ch = ' ';
        if (ch.length === 1 && ch.charCodeAt(0) < 0x20) ch = ' ';

        const style = this._cellSgr(cell, pal);
        if (style !== lastStyle) {
          rowStr += style;
          lastStyle = style;
        }
        if (w === 2 && col + 1 >= box.innerW) {
          rowStr += ' ';
          col += 1;
        } else {
          rowStr += ch;
          col += w;
        }
      }
      if (box.pad > 0) rowStr += padStr;
      out.push(rowStr + RESET);
    }
    return out;
  }

  _cellSgr(cell, pal) {
    let fg = '';
    let bg = '';
    const ansi16 = pal.ansi16;
    if (cell.isFgDefault()) {
      fg = fgHex(pal.termFg);
    } else if (cell.isFgRGB()) {
      const c = cell.getFgColor();
      fg = `\x1b[38;2;${(c >> 16) & 255};${(c >> 8) & 255};${c & 255}m`;
    } else {
      const idx = cell.getFgColor();
      fg = ansi16 && idx >= 0 && idx < 16 ? fgHex(ansi16[idx]) : `\x1b[38;5;${idx}m`;
    }

    if (cell.isBgDefault()) {
      bg = bgHex(pal.bg);
    } else if (cell.isBgRGB()) {
      const c = cell.getBgColor();
      bg = `\x1b[48;2;${(c >> 16) & 255};${(c >> 8) & 255};${c & 255}m`;
    } else {
      const idx = cell.getBgColor();
      bg = ansi16 && idx >= 0 && idx < 16 ? bgHex(ansi16[idx]) : `\x1b[48;5;${idx}m`;
    }

    let attr = '\x1b[0m';
    if (cell.isBold()) attr += '\x1b[1m';
    if (cell.isDim()) attr += '\x1b[2m';
    if (cell.isItalic()) attr += '\x1b[3m';
    if (cell.isUnderline()) attr += '\x1b[4m';
    if (cell.isInverse()) attr += '\x1b[7m';
    return attr + fg + bg;
  }

  _renderSysopPanel(box, pal) {
    const bgS = bgHex(pal.surface);
    const bg2 = bgHex(pal.surface2);
    const bgBand = bgHex(pal.band);
    const ss = sysopStyle(this.sysop.state, pal);
    const out = [];

    // Header row + subtle hairline divider (matching left sidebar & Web UI)
    const headLeft = ' ● SYSOP';
    const headRight = `${ss.pill} `;
    const hGap = Math.max(1, box.w - visibleWidth(headLeft) - visibleWidth(headRight));
    out.push(
      buildRow(box.w, bgS, [
        { text: headLeft, style: `${fgHex(ss.color)}\x1b[1m` },
        { text: ' '.repeat(hGap), style: '' },
        { text: headRight, style: `${fgHex(ss.color)}\x1b[1m` },
      ]),
    );
    out.push(buildRow(box.w, bgS, [{ text: '─'.repeat(box.w), style: fgHex(pal.border) }]));

    // 3-row framed Goal Composer pinned cleanly at bottom of Sysop panel
    const composerRows = 3;
    const feedArea = Math.max(1, box.h - 2 - composerRows);
    const body = [];

    const makeDecisionButtonsRow = (denyLabel) => {
      const allowLbl = box.w >= 28 ? ' Allow ^Aa ' : ' Allow ';
      const vetoLbl = box.w >= 28 ? ` ${denyLabel} ^Av ` : ` ${denyLabel} `;
      const rowStr = buildRow(box.w, bgBand, [
        { text: '▌', style: fgHex(pal.amber) },
        { text: ' ', style: '' },
        { text: allowLbl, style: `${bgHex(pal.accentDeep)}${fgHex(pal.text)}\x1b[1m` },
        { text: ' ', style: '' },
        { text: vetoLbl, style: `${bgHex(pal.surface2)}${fgHex(pal.red)}` },
      ]);
      const allowStart = 2;
      const allowEnd = allowStart + visibleWidth(allowLbl) - 1;
      const vetoStart = allowEnd + 2;
      const vetoEnd = vetoStart + visibleWidth(vetoLbl) - 1;
      return {
        raw: rowStr,
        onHit: (rowY) => {
          this.hitboxes.push({ x1: box.x + allowStart, x2: box.x + allowEnd, y1: rowY, y2: rowY, onClick: () => this._sysopAction('approve') });
          this.hitboxes.push({ x1: box.x + vetoStart, x2: box.x + vetoEnd, y1: rowY, y2: rowY, onClick: () => this._sysopAction('veto') });
        },
      };
    };

    if (this.sysop.pending) {
      const p = this.sysop.pending;
      const secs = typeof p.deadline === 'number' ? Math.max(0, Math.ceil(p.deadline - Date.now() / 1000)) : null;
      const tabObj = p.tab ? this.terminals.find((t) => t.address === p.tab) : null;
      const tabTag = tabObj ? (tabObj.name || p.tab) : (p.tab || '');
      const title = p.mode === 'veto' ? `SENDING${secs !== null ? ` · ${secs}s` : ''}` : `ALLOW?${secs !== null ? ` · ${secs}s` : ''}`;
      const rightTag = tabTag ? `${tabTag} ` : '';
      const tGap = Math.max(1, box.w - 3 - visibleWidth(title) - visibleWidth(rightTag));
      body.push({
        raw: buildRow(box.w, bgBand, [
          { text: '▌ ', style: fgHex(pal.amber) },
          { text: '◆ ', style: fgHex(pal.amber) },
          { text: title, style: `${fgHex(pal.amber)}\x1b[1m` },
          { text: ' '.repeat(Math.max(1, tGap - 1)), style: '' },
          { text: rightTag, style: fgHex(pal.muted) },
        ]),
      });
      for (const ln of wrapText(p.text || 'pending action', box.w - 4, 3)) {
        body.push({
          raw: buildRow(box.w, bgBand, [
            { text: '▌ ', style: fgHex(pal.amber) },
            { text: ln, style: fgHex(pal.text) },
          ]),
        });
      }
      if (secs !== null) {
        const barW = Math.max(8, Math.min(24, box.w - 4));
        const ratio = Math.max(0, Math.min(1, secs / Math.max(secs, 30)));
        const fill = Math.max(1, Math.round(ratio * barW));
        body.push({
          raw: buildRow(box.w, bgBand, [
            { text: '▌ ', style: fgHex(pal.amber) },
            { text: '▰'.repeat(fill), style: fgHex(pal.amber) },
            { text: '▱'.repeat(barW - fill), style: fgHex(pal.border) },
          ]),
        });
      }
      body.push(makeDecisionButtonsRow('Veto'));
      body.push({ raw: buildRow(box.w, bgS, [{ text: '─'.repeat(box.w), style: fgHex(pal.border) }]) });
      body.push({ raw: buildRow(box.w, bgS, []) });
    } else if (this.sysop.blocked.length > 0) {
      const b = this.sysop.blocked[0];
      body.push({
        raw: buildRow(box.w, bgBand, [
          { text: '▌ ', style: fgHex(pal.amber) },
          { text: `◆ BLOCKED · ${b.name}`, style: `${fgHex(pal.amber)}\x1b[1m` },
        ]),
      });
      for (const ln of wrapText(b.msg, box.w - 4, 2)) {
        body.push({
          raw: buildRow(box.w, bgBand, [
            { text: '▌ ', style: fgHex(pal.amber) },
            { text: ln, style: fgHex(pal.text) },
          ]),
        });
      }
      body.push(makeDecisionButtonsRow('Deny'));
      body.push({ raw: buildRow(box.w, bgS, [{ text: '─'.repeat(box.w), style: fgHex(pal.border) }]) });
      body.push({ raw: buildRow(box.w, bgS, []) });
    }

    // Activity feed
    const stepLines = [];
    if (!this.sysop.up) {
      stepLines.push({ raw: buildRow(box.w, bgS, [{ text: ' Sysop service is offline.', style: fgHex(pal.dim) }]) });
      stepLines.push({ raw: buildRow(box.w, bgS, [{ text: ' Install with:', style: fgHex(pal.dim) }]) });
      stepLines.push({ raw: buildRow(box.w, bgS, [{ text: ' swarmbox addon install sysop', style: fgHex(pal.muted) }]) });
    } else if (this.sysop.steps.length === 0) {
      stepLines.push({ raw: buildRow(box.w, bgS, [{ text: ' Ready for goals.', style: fgHex(pal.muted) }]) });
      for (const ln of wrapText('Press ^A g or Alt+G to ask Sysop to work on the active tab or route to your agent.', box.w - 2, 4)) {
        stepLines.push({ raw: buildRow(box.w, bgS, [{ text: ` ${ln}`, style: fgHex(pal.dim) }]) });
      }
    } else {
      for (const st of this.sysop.steps) {
        const icon = st.kind === 'goal' ? '❯' : st.kind === 'ok' ? '✓' : st.kind === 'err' ? '!' : '·';
        const col = st.kind === 'goal' ? pal.accentBright : st.kind === 'ok' ? pal.green : st.kind === 'err' ? pal.red : pal.muted;
        const wrapped = wrapText(st.text, box.w - 4, 3);
        wrapped.forEach((ln, idx) => {
          stepLines.push({
            raw: buildRow(box.w, bgS, [
              { text: ` ${idx === 0 ? icon : ' '} `, style: fgHex(col) },
              { text: ln, style: `${fgHex(col)}${st.kind === 'goal' && idx === 0 ? '\x1b[1m' : ''}` },
            ]),
          });
        });
      }
    }

    const availFeed = Math.max(0, feedArea - body.length);
    const leadingSpacer = body.length === 0 && stepLines.length > 0 && availFeed > stepLines.length
      ? [{ raw: buildRow(box.w, bgS, []) }]
      : [];
    const combined = [...body, ...leadingSpacer, ...stepLines.slice(-Math.max(0, availFeed - leadingSpacer.length))];

    for (let i = 0; i < feedArea; i++) {
      const item = combined[i];
      const rowY = box.y + 2 + i;
      if (!item) {
        out.push(buildRow(box.w, bgS, []));
      } else {
        out.push(item.raw);
        if (item.onHit) item.onHit(rowY);
      }
    }

    // Framed 3-row Goal Composer (outer │ keeps panel bgS so rounded corners are razor-clean!)
    const isGoal = this.focus === 'goal';
    const borderCol = isGoal ? pal.accentBright : pal.border;
    const innerBg = isGoal ? bgBand : bg2;
    const frameW = Math.max(10, box.w - 2); // 1-col margin left + right
    const innerW = frameW - 2;              // inside │ ... │
    const composerTopY = box.y + 2 + feedArea;

    // Top border: " ╭─ Goal ────────╮ "
    const topLabel = isGoal ? '─ Goal ' : '─ Ask Sysop ';
    const topFill = Math.max(0, innerW - visibleWidth(topLabel));
    out.push(
      buildRow(box.w, bgS, [
        { text: ' ', style: '' },
        { text: '╭', style: fgHex(borderCol) },
        { text: topLabel, style: isGoal ? `${fgHex(pal.accentBright)}\x1b[1m` : fgHex(pal.dim) },
        { text: '─'.repeat(topFill), style: fgHex(borderCol) },
        { text: '╮', style: fgHex(borderCol) },
        { text: ' ', style: '' },
      ]),
    );

    // Input row: " │ ❯ <draft> │ " (symmetric 1-col left & right inner padding)
    const textAreaW = Math.max(3, innerW - 4); // ' ❯ '(3) + textAreaW + ' '(1)
    const draftChars = Array.from(this.goalDraft);
    const curIdx = Math.max(0, Math.min(draftChars.length, this.goalCursor));

    let shownDraft = '';
    let cursorOffsetCols = 0;
    if (!isGoal && draftChars.length === 0) {
      shownDraft = fitText('Type a goal…', textAreaW);
    } else {
      // Scroll window around cursor so typing never clips past right border
      let start = 0;
      let widthToCursor = 0;
      for (let k = 0; k < curIdx; k++) widthToCursor += charDisplayWidth(draftChars[k]);
      while (widthToCursor > Math.max(0, textAreaW - 1) && start < curIdx) {
        widthToCursor -= charDisplayWidth(draftChars[start]);
        start += 1;
      }
      let slice = '';
      let sw = 0;
      for (let k = start; k < draftChars.length; k++) {
        const cw = charDisplayWidth(draftChars[k]);
        if (sw + cw > textAreaW) break;
        slice += draftChars[k];
        sw += cw;
      }
      shownDraft = fitText(slice, textAreaW);
      cursorOffsetCols = widthToCursor;
    }

    out.push(
      buildRow(box.w, bgS, [
        { text: ' ', style: '' },
        { text: '│', style: fgHex(borderCol) },
        { text: ' ❯ ', style: `${innerBg}${isGoal ? fgHex(pal.accentBright) : fgHex(pal.dim)}` },
        { text: shownDraft, style: `${innerBg}${isGoal ? fgHex(pal.text) : fgHex(pal.dim)}` },
        { text: ' ', style: innerBg },
        { text: '│', style: fgHex(borderCol) },
        { text: ' ', style: '' },
      ]),
    );

    if (isGoal) {
      this.goalCursorPos = {
        x: box.x + 1 + 1 + 3 + Math.min(textAreaW - 1, cursorOffsetCols),
        y: composerTopY + 1,
      };
    }

    // Bottom border: " ╰─ Enter · Esc ─╯ "
    const botLabel = isGoal ? '─ ↵ send · Esc ' : '─ ^A g · Alt+G ';
    const botFill = Math.max(0, innerW - visibleWidth(botLabel));
    out.push(
      buildRow(box.w, bgS, [
        { text: ' ', style: '' },
        { text: '╰', style: fgHex(borderCol) },
        { text: botLabel, style: fgHex(pal.dim) },
        { text: '─'.repeat(botFill), style: fgHex(borderCol) },
        { text: '╯', style: fgHex(borderCol) },
        { text: ' ', style: '' },
      ]),
    );

    this.hitboxes.push({
      x1: box.x,
      x2: box.x + box.w - 1,
      y1: composerTopY,
      y2: composerTopY + 2,
      onClick: () => this._focusGoal(),
    });

    return out.slice(0, box.h);
  }

  _renderFooter(L, pal) {
    const bgS = bgHex(pal.surface);
    if (this.prefixMode) {
      return buildRow(L.W, bgHex(pal.accentDeep), [
        { text: ' ^A PREFIX ', style: `${fgHex(pal.text)}\x1b[1m` },
        { text: ' 1-9 tab · n/p cycle · c shell · C agent · x close · b sidebar · s sysop · g goal · a allow · v veto · t theme · d detach · ? help', style: fgHex(pal.text) },
      ]);
    }
    if (this.focus === 'goal') {
      return buildRow(L.W, bgHex(pal.band), [
        { text: ' SYSOP GOAL ', style: `${fgHex(pal.accentBright)}\x1b[1m` },
        { text: ' Enter send · Esc return to terminal · ←/→ edit · Ctrl+U clear', style: fgHex(pal.muted) },
      ]);
    }
    if (this.toast) {
      return buildRow(L.W, bgHex(pal.band), [
        { text: ` ✦ ${this.toast}`, style: fgHex(pal.accentBright) },
      ]);
    }
    if (this.scrollOffset > 0) {
      return buildRow(L.W, bgHex(pal.band), [
        { text: ` SCROLL +${this.scrollOffset} lines · Shift+PgUp/PgDn or wheel · press any key to return live`, style: fgHex(pal.amber) },
      ]);
    }
    const hints = [
      ['^A', ' prefix'],
      ['Alt+1-9', ' tabs'],
      ['Alt+N', ' shell'],
      ['Alt+B', ' sidebar'],
      ['Alt+S', ' sysop'],
      ['Alt+G', ' goal'],
      ['Alt+T', ' theme'],
      ['^A d', ' detach'],
    ];
    const segs = [{ text: ' ', style: '' }];
    let used = 1;
    for (let i = 0; i < hints.length; i++) {
      const [key, desc] = hints[i];
      const sep = i === 0 ? '' : ' · ';
      const needed = visibleWidth(sep) + visibleWidth(key) + visibleWidth(desc);
      if (used + needed > L.W - 1) break;
      if (sep) segs.push({ text: sep, style: fgHex(pal.dim) });
      segs.push({ text: key, style: i === 0 ? fgHex(pal.accent) : fgHex(pal.muted) });
      segs.push({ text: desc, style: fgHex(pal.dim) });
      used += needed;
    }
    return buildRow(L.W, bgS, segs);
  }

  _overlayHelp(rows, L, pal) {
    const entries = [
      ['Ctrl+A c / Alt+N', 'New shell tab'],
      ['Ctrl+A C', 'New agent tab'],
      ['Ctrl+A 1..9 / Alt+#', 'Switch tab'],
      ['Ctrl+A n / p', 'Next / previous tab'],
      ['Ctrl+A x', 'Close active tab'],
      ['Ctrl+A b / Alt+B', 'Toggle left sidebar'],
      ['Ctrl+A s / Alt+S', 'Toggle Sysop panel'],
      ['Ctrl+A g / Alt+G', 'Ask Sysop (goal input)'],
      ['Ctrl+A a / v / X', 'Sysop Allow / Veto / Stop'],
      ['Ctrl+A t / Alt+T', 'Cycle 5 synced themes'],
      ['Ctrl+A Ctrl+A', 'Send literal Ctrl+A'],
      ['Ctrl+A d', 'Detach (keeps terminals)'],
      ['Shift+PgUp / PgDn', 'Scroll terminal history'],
    ];
    const boxW = Math.min(L.W - 4, 54);
    const innerW = boxW - 4;
    const boxH = Math.min(L.H - 2, entries.length + 6);
    const top = Math.max(1, Math.floor((L.H - boxH) / 2));
    const left = Math.max(1, Math.floor((L.W - boxW) / 2));
    const right = Math.max(0, L.W - left - boxW);
    const bgOuter = bgHex(pal.bg);
    const bgB = bgHex(pal.surface2);
    const bgHead = bgHex(pal.band);
    const bd = fgHex(pal.accent);

    rows[top] = buildRow(L.W, bgOuter, [
      { text: ' '.repeat(left), style: '' },
      { text: `╭${'─'.repeat(boxW - 2)}╮`, style: `${bgHead}${bd}` },
      { text: ' '.repeat(right), style: '' },
    ]);
    rows[top + 1] = buildRow(L.W, bgOuter, [
      { text: ' '.repeat(left), style: '' },
      { text: '│', style: `${bgHead}${bd}` },
      { text: ` ${fitText('● SWARMBOX Terminal Cockpit · Shortcuts', innerW)} `, style: `${bgHead}${fgHex(pal.accentBright)}\x1b[1m` },
      { text: '│', style: `${bgHead}${bd}` },
      { text: ' '.repeat(right), style: '' },
    ]);
    rows[top + 2] = buildRow(L.W, bgOuter, [
      { text: ' '.repeat(left), style: '' },
      { text: '├', style: `${bgB}${bd}` },
      { text: '─'.repeat(boxW - 2), style: `${bgB}${fgHex(pal.border)}` },
      { text: '┤', style: `${bgB}${bd}` },
      { text: ' '.repeat(right), style: '' },
    ]);
    const keyW = Math.min(21, Math.floor(innerW * 0.45));
    const descW = Math.max(8, innerW - keyW - 1);
    const maxItems = Math.max(1, boxH - 6);
    for (let i = 0; i < maxItems; i++) {
      const pair = entries[i];
      if (!pair) continue;
      rows[top + 3 + i] = buildRow(L.W, bgOuter, [
        { text: ' '.repeat(left), style: '' },
        { text: '│', style: `${bgB}${bd}` },
        { text: ` ${fitText(pair[0], keyW)} `, style: `${bgB}${fgHex(pal.accentBright)}` },
        { text: `${fitText(pair[1], descW)} `, style: `${bgB}${fgHex(pal.text)}` },
        { text: '│', style: `${bgB}${bd}` },
        { text: ' '.repeat(right), style: '' },
      ]);
    }
    rows[top + boxH - 3] = buildRow(L.W, bgOuter, [
      { text: ' '.repeat(left), style: '' },
      { text: '├', style: `${bgB}${bd}` },
      { text: '─'.repeat(boxW - 2), style: `${bgB}${fgHex(pal.border)}` },
      { text: '┤', style: `${bgB}${bd}` },
      { text: ' '.repeat(right), style: '' },
    ]);
    rows[top + boxH - 2] = buildRow(L.W, bgOuter, [
      { text: ' '.repeat(left), style: '' },
      { text: '│', style: `${bgB}${bd}` },
      { text: ` ${fitText('Press any key to close', innerW)} `, style: `${bgB}${fgHex(pal.dim)}` },
      { text: '│', style: `${bgB}${bd}` },
      { text: ' '.repeat(right), style: '' },
    ]);
    rows[top + boxH - 1] = buildRow(L.W, bgOuter, [
      { text: ' '.repeat(left), style: '' },
      { text: `╰${'─'.repeat(boxW - 2)}╯`, style: `${bgB}${bd}` },
      { text: ' '.repeat(right), style: '' },
    ]);
  }
}

// Direct CLI entry point
if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const cockpit = new Cockpit();
  const onSig = () => cockpit.shutdown(0);
  process.on('SIGTERM', onSig);
  process.on('SIGINT', onSig);
  process.on('uncaughtException', (err) => {
    cockpit.shutdown(null);
    console.error('swarmbox-cockpit:', err.message);
    process.exit(1);
  });

  cockpit.start().catch((err) => {
    cockpit.shutdown(null);
    console.error('swarmbox-cockpit: failed to connect to herdr-core:', err.message);
    process.exit(1);
  });
}
