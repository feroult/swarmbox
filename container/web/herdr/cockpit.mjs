#!/usr/bin/env node
// SwarmBox × herdr-core Terminal Cockpit (`sx` / `swarmbox` interactive TUI).
//
// Provides full terminal parity with the SwarmBox Web UI on top of herdr-core (`hc connect`):
//   - Collapsible left sidebar with live OSC 7501 status dots (filters swarmbox.role=sysop)
//   - Full 24-bit TrueColor center terminal viewport backed by @xterm/headless
//   - Collapsible right Sysop panel with real-time state, ALLOW?/VETO cards, and goal input
//   - Five synchronized themes persisted in ~/.config/swarmbox/herdr-web-theme
//   - Ctrl+A prefix + Alt shortcuts + SGR 1006 mouse support, zero host dependencies

import fs from 'node:fs';
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
// ANSI 24-bit helpers & pure layout engine (exported for fast unit tests)
// ---------------------------------------------------------------------------
const ESC = '\x1b';
const RESET = '\x1b[0m';
const SYNC_START = '\x1b[?2026h';
const SYNC_END = '\x1b[?2026l';

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

export function computeLayout(cols, rows, opts = {}) {
  const W = Math.max(40, Number(cols) || 80);
  const H = Math.max(12, Number(rows) || 24);
  const wantSidebar = opts.sidebarOpen ?? (W >= 100);
  const wantSysop = opts.sysopOpen ?? (W >= 124);

  let sidebarW = wantSidebar && W >= 72 ? Math.min(24, Math.max(18, Math.floor(W * 0.2))) : 0;
  let sysopW = wantSysop && W >= 78 ? Math.min(34, Math.max(24, Math.floor(W * 0.28))) : 0;

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
  const bodyH = Math.max(4, H - 2);
  const paneX = sidebarW + leftDiv;
  const paneW = Math.max(20, W - sidebarW - leftDiv - sysopW - rightDiv);
  const sysopX = paneX + paneW + rightDiv;

  return {
    W,
    H,
    bodyY,
    bodyH,
    sidebar: sidebarW > 0 ? { x: 0, y: bodyY, w: sidebarW, h: bodyH } : null,
    leftDivX: sidebarW > 0 ? sidebarW : -1,
    pane: { x: paneX, y: bodyY, w: paneW, h: bodyH },
    rightDivX: sysopW > 0 ? paneX + paneW : -1,
    sysop: sysopW > 0 ? { x: sysopX, y: bodyY, w: sysopW, h: bodyH } : null,
    footerY: H - 1,
  };
}

function charDisplayWidth(ch) {
  const cp = ch.codePointAt(0);
  if (cp === undefined || cp < 0x20 || (cp >= 0x7f && cp < 0xa0)) return 0;
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

export function fitText(text, width) {
  const maxW = Math.max(0, width);
  if (maxW === 0) return '';
  const clean = String(text || '').replace(/[\r\n\t\x00-\x1f\x7f]/g, ' ');
  let out = '';
  let w = 0;
  for (const ch of clean) {
    const cw = charDisplayWidth(ch);
    if (w + cw > maxW) {
      if (maxW >= 2 && w < maxW) {
        out += '…';
        w += 1;
      } else if (out.length > 0 && maxW >= 2) {
        out = out.slice(0, -1) + '…';
      }
      break;
    }
    out += ch;
    w += cw;
  }
  if (w < maxW) out += ' '.repeat(maxW - w);
  return out;
}

function wrapText(text, width, maxLines = 4) {
  const w = Math.max(4, width);
  const words = String(text || '').replace(/[\r\n\t\x00-\x1f\x7f]+/g, ' ').trim().split(/\s+/).filter(Boolean);
  if (words.length === 0) return [];
  const lines = [];
  let cur = '';
  for (const word of words) {
    if (!cur) {
      if (word.length <= w) {
        cur = word;
      } else {
        let rest = word;
        while (rest.length > w && lines.length < maxLines) {
          lines.push(rest.slice(0, w));
          rest = rest.slice(w);
        }
        cur = rest;
      }
    } else if (cur.length + 1 + word.length <= w) {
      cur += ' ' + word;
    } else {
      lines.push(cur);
      if (lines.length >= maxLines) return lines.slice(0, maxLines);
      cur = word.slice(0, w);
    }
  }
  if (cur && lines.length < maxLines) lines.push(cur);
  return lines.slice(0, maxLines);
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

    // Poll real swarmbox-sysop state + shared theme file (stays synced with Web UI!)
    this.pollTimer = setInterval(() => {
      if (this.closed) return;
      const diskTheme = readSavedTheme();
      let dirty = false;
      if (diskTheme !== this.themeName) {
        this.themeName = diskTheme;
        this.prevRows = [];
        dirty = true;
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
    const c = L.pane.w;
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
    this.xtermCols = L.pane.w;
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
      argv = ['/bin/bash', '-lc', `exec ${cmd}`];
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
        this.setToast(`Opened ${preset} (${addr})`);
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
    this.prevRows = [];
    this._syncPaneSize();
    this.scheduleRender(true);
  }

  async _submitGoal() {
    const goal = this.goalDraft.trim();
    this.goalDraft = '';
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

    // Strip & handle SGR mouse packets first
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

      // Goal input box mode
      if (this.focus === 'goal') {
        this._handleGoalKey(buf);
        return;
      }

      // Prefix mode (after Ctrl+A)
      if (this.prefixMode) {
        this._clearPrefix();
        const byte = buf[0];
        const rest = buf.subarray(1);
        this._handlePrefixKey(byte);
        buf = rest;
        continue;
      }

      // Shift+PgUp / Shift+PgDn for scrollback
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

      // Direct Alt shortcuts (ESC + single printable ASCII key)
      if (buf.length === 2 && buf[0] === 0x1b) {
        const ch = String.fromCharCode(buf[1]);
        if (this._handleAltKey(ch)) return;
      }

      // Ctrl+A enters prefix mode
      if (buf[0] === 0x01) {
        this._enterPrefix();
        buf = buf.subarray(1);
        continue;
      }

      // Normal terminal pass-through (reset scrollback on typing)
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
      // Ctrl+A Ctrl+A -> literal Ctrl+A to terminal
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
    if (low === 'n') {
      this._createTab('shell');
      return true;
    }
    if (low === 'b') {
      this._toggleSidebar();
      return true;
    }
    if (low === 's') {
      this._toggleSysop();
      return true;
    }
    if (low === 'g') {
      this._focusGoal();
      return true;
    }
    if (low === 't') {
      this._cycleTheme();
      return true;
    }
    return false;
  }

  _handleGoalKey(buf) {
    const s = buf.toString('utf8');
    if (s === '\x1b' || s === '\x03') {
      this.focus = 'terminal';
      this.scheduleRender();
      return;
    }
    if (s === '\r' || s === '\n') {
      this._submitGoal();
      return;
    }
    if (s === '\x7f' || s === '\x08') {
      this.goalDraft = Array.from(this.goalDraft).slice(0, -1).join('');
      this.scheduleRender();
      return;
    }
    if (s === '\x15') {
      this.goalDraft = '';
      this.scheduleRender();
      return;
    }
    // Strip control sequences, append printable UTF-8 text
    const printable = s.replace(/\x1b\[[0-9;?]*[ -/]*[@-~]/g, '').replace(/[\x00-\x1f\x7f]/g, '');
    if (printable) {
      this.goalDraft += printable;
      this.scheduleRender();
    }
  }

  _handleMouse(btn, x, y, press) {
    if (!press) return;
    // Wheel up (64) / down (65)
    if (btn === 64) {
      this._scroll(3);
      return;
    }
    if (btn === 65) {
      this._scroll(-3);
      return;
    }
    if (btn !== 0) return;

    // Check clickable UI hitboxes
    for (const hb of this.hitboxes) {
      if (y >= hb.y1 && y <= hb.y2 && x >= hb.x1 && x <= hb.x2) {
        hb.onClick();
        return;
      }
    }

    // Clicking inside center pane returns focus to terminal
    const L = this.layout();
    if (x >= L.pane.x && x < L.pane.x + L.pane.w && y >= L.pane.y && y < L.pane.y + L.pane.h) {
      if (this.focus !== 'terminal') {
        this.focus = 'terminal';
        this.scheduleRender();
      }
    }
  }

  // -------------------------------------------------------------------------
  // Compositor (24-bit TrueColor, synchronized output, row diffing)
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

  render() {
    const L = this.layout();
    const pal = this.palette();
    this.hitboxes = [];
    const rows = new Array(L.H);

    // 1. Top bar
    rows[0] = this._renderTopBar(L, pal);

    // 2. Sidebar rows + Center terminal rows + Sysop panel rows
    const sidebarLines = L.sidebar ? this._renderSidebar(L.sidebar, pal) : null;
    const paneLines = this._renderTerminalPane(L.pane, pal);
    const sysopLines = L.sysop ? this._renderSysopPanel(L.sysop, pal) : null;
    const divStr = `${bgHex(pal.bg)}${fgHex(pal.border)}│`;

    for (let i = 0; i < L.bodyH; i++) {
      let line = '';
      if (sidebarLines) line += sidebarLines[i] + divStr;
      line += paneLines[i];
      if (sysopLines) line += divStr + sysopLines[i];
      rows[L.bodyY + i] = line + RESET;
    }

    // 3. Bottom status / shortcut bar
    rows[L.footerY] = this._renderFooter(L, pal);

    // 4. Optional help overlay
    if (this.helpOpen) {
      this._overlayHelp(rows, L, pal);
    }

    // Flush only changed rows inside synchronized update frame
    let out = SYNC_START + `${ESC}[?25l`;
    for (let r = 0; r < L.H; r++) {
      if (this.prevRows[r] !== rows[r]) {
        out += `${ESC}[${r + 1};1H${rows[r]}`;
        this.prevRows[r] = rows[r];
      }
    }

    // Position real cursor
    if (!this.helpOpen) {
      if (this.focus === 'goal' && L.sysop) {
        const gx = L.sysop.x + 1 + Math.min(L.sysop.w - 3, 2 + this.goalDraft.length);
        const gy = L.sysop.y + L.sysop.h - 1;
        out += `${ESC}[${gy};${gx + 1}H${ESC}[?25h`;
      } else if (this.xterm && this.scrollOffset === 0) {
        const b = this.xterm.buffer.active;
        const cx = Math.min(L.pane.w - 1, Math.max(0, b.cursorX));
        const cy = Math.min(L.pane.h - 1, Math.max(0, b.cursorY));
        out += `${ESC}[${L.pane.y + cy + 1};${L.pane.x + cx + 1}H${ESC}[?25h`;
      }
    }

    out += SYNC_END;
    this.stdout.write(out);
  }

  _renderTopBar(L, pal) {
    const active = this.terminals.find((t) => t.address === this.activeAddr);
    const activeName = active ? (active.name || active.address) : 'no tab';
    const sm = statusMeta(active, pal);
    const ss = sysopStyle(this.sysop.state, pal);
    const themeLabel = (HERDR_THEMES[this.themeName] || HERDR_THEMES['purple-glow']).label;

    const leftPlain = ` ● SWARMBOX · herdr  ›  ${activeName} (${sm.label})`;
    const rightPlain = `SYSOP:${ss.pill}  ·  ${themeLabel}  ·  ^A? `;
    const gap = Math.max(1, L.W - leftPlain.length - rightPlain.length);

    let s = bgHex(pal.surface);
    s += `${fgHex(pal.accentBright)}\x1b[1m ● SWARMBOX${RESET}${bgHex(pal.surface)}${fgHex(pal.dim)} · ${fgHex(pal.accent)}herdr`;
    s += `${fgHex(pal.dim)}  ›  ${fgHex(pal.text)}\x1b[1m${activeName}${RESET}${bgHex(pal.surface)} ${fgHex(sm.color)}(${sm.label})`;
    s += ' '.repeat(gap);
    s += `${fgHex(ss.color)}\x1b[1mSYSOP:${ss.pill}${RESET}${bgHex(pal.surface)}`;
    s += `${fgHex(pal.dim)}  ·  ${fgHex(pal.muted)}${themeLabel}  ·  ${fgHex(pal.accent)}^A? `;

    // Top bar click on right toggles sysop / theme
    this.hitboxes.push({
      x1: Math.max(0, L.W - rightPlain.length),
      x2: Math.max(0, L.W - themeLabel.length - 8),
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
    return s + RESET;
  }

  _renderSidebar(box, pal) {
    const out = [];
    const bgS = bgHex(pal.surface);
    const bgBand = bgHex(pal.band);
    const bgBtn = bgHex(pal.surface2);

    // Header
    out.push(`${bgS}${fgHex(pal.dim)} ${fitText(`TERMINALS (${this.terminals.length})`, box.w - 1)}`);

    const footerRows = 4; // spacer + [+ Shell] + [+ Agent] + [Theme]
    const listMax = Math.max(1, box.h - 1 - footerRows);

    for (let i = 0; i < listMax; i++) {
      const t = this.terminals[i];
      if (!t) {
        out.push(`${bgS}${' '.repeat(box.w)}`);
        continue;
      }
      const isAct = t.address === this.activeAddr;
      const sm = statusMeta(t, pal);
      const name = t.name || t.address;
      const rowY = box.y + 1 + i;
      this.hitboxes.push({
        x1: box.x,
        x2: box.x + box.w - 1,
        y1: rowY,
        y2: rowY,
        onClick: () => this._attachTo(t.address).catch(() => {}),
      });

      const prefix = isAct ? `${fgHex(pal.accentBright)}▌` : ' ';
      const num = i < 9 ? `${i + 1}` : '·';
      const label = fitText(`${num} ${name}`, box.w - 4);
      const rowBg = isAct ? bgBand : bgS;
      const txtCol = isAct ? `${fgHex(pal.text)}\x1b[1m` : fgHex(pal.muted);
      out.push(`${rowBg}${prefix}${fgHex(sm.color)}${sm.dot} ${txtCol}${label}${RESET}${rowBg}`);
    }

    // Bottom pinned actions
    const actY = box.y + 1 + listMax;
    out.push(`${bgS}${fgHex(pal.border)}${'─'.repeat(box.w)}`);

    // [+ Shell]
    out.push(`${bgBtn}${fgHex(pal.accentBright)} ${fitText('+ Shell        ^A c', box.w - 1)}`);
    this.hitboxes.push({
      x1: box.x,
      x2: box.x + box.w - 1,
      y1: actY + 1,
      y2: actY + 1,
      onClick: () => this._createTab('shell'),
    });

    // [+ Agent]
    out.push(`${bgBtn}${fgHex(pal.accent)} ${fitText('+ Agent        ^A C', box.w - 1)}`);
    this.hitboxes.push({
      x1: box.x,
      x2: box.x + box.w - 1,
      y1: actY + 2,
      y2: actY + 2,
      onClick: () => this._createTab('agent'),
    });

    // [Theme]
    const tLabel = (HERDR_THEMES[this.themeName] || HERDR_THEMES['purple-glow']).label;
    out.push(`${bgS}${fgHex(pal.muted)} ${fitText(`◐ ${tLabel} (^A t)`, box.w - 1)}`);
    this.hitboxes.push({
      x1: box.x,
      x2: box.x + box.w - 1,
      y1: actY + 3,
      y2: actY + 3,
      onClick: () => this._cycleTheme(),
    });

    while (out.length < box.h) out.push(`${bgS}${' '.repeat(box.w)}`);
    return out.slice(0, box.h);
  }

  _renderTerminalPane(box, pal) {
    const bgDefault = bgHex(pal.bg);
    const fgDefault = fgHex(pal.termFg);
    const emptyRow = `${bgDefault}${fgDefault}${' '.repeat(box.w)}`;

    if (!this.xterm) {
      const lines = new Array(box.h).fill(emptyRow);
      if (box.h > 2) {
        lines[Math.floor(box.h / 2)] = `${bgDefault}${fgHex(pal.dim)}${fitText('  Connecting to herdr-core…', box.w)}`;
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

      let rowStr = '';
      let lastStyle = '';
      let col = 0;

      while (col < box.w) {
        line.getCell(col, cell);
        const w = cell.getWidth();
        if (w === 0) {
          col += 1;
          continue;
        }
        let ch = cell.getChars();
        if (!ch || cell.isInvisible()) ch = ' ';
        // Prevent raw control chars from corrupting the outer terminal
        if (ch.length === 1 && ch.charCodeAt(0) < 0x20) ch = ' ';

        const style = this._cellSgr(cell, pal);
        if (style !== lastStyle) {
          rowStr += style;
          lastStyle = style;
        }
        if (w === 2 && col + 1 >= box.w) {
          rowStr += ' ';
          col += 1;
        } else {
          rowStr += ch;
          col += w;
        }
      }
      out.push(rowStr + RESET);
    }
    return out;
  }

  _cellSgr(cell, pal) {
    let fg = '';
    let bg = '';
    if (cell.isFgDefault()) {
      fg = fgHex(pal.termFg);
    } else if (cell.isFgRGB()) {
      const c = cell.getFgColor();
      fg = `\x1b[38;2;${(c >> 16) & 255};${(c >> 8) & 255};${c & 255}m`;
    } else {
      fg = `\x1b[38;5;${cell.getFgColor()}m`;
    }

    if (cell.isBgDefault()) {
      bg = bgHex(pal.bg);
    } else if (cell.isBgRGB()) {
      const c = cell.getBgColor();
      bg = `\x1b[48;2;${(c >> 16) & 255};${(c >> 8) & 255};${c & 255}m`;
    } else {
      bg = `\x1b[48;5;${cell.getBgColor()}m`;
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

    // Header row
    const headLeft = ' ● SYSOP';
    const headRight = `${ss.pill} `;
    const pad = Math.max(1, box.w - headLeft.length - headRight.length);
    out.push(
      `${bgS}${fgHex(ss.color)}\x1b[1m${headLeft}${RESET}${bgS}${' '.repeat(pad)}${fgHex(ss.color)}\x1b[1m${headRight}${RESET}${bgS}`,
    );

    const inputRows = 2; // divider + goal input row
    const feedArea = Math.max(2, box.h - 1 - inputRows);
    const body = [];

    // Pending approval / veto card OR OSC 7501 blocked card
    if (this.sysop.pending) {
      const p = this.sysop.pending;
      const secs = typeof p.deadline === 'number' ? Math.max(0, Math.ceil(p.deadline - Date.now() / 1000)) : null;
      const title = p.mode === 'veto' ? `SENDING${secs !== null ? ` (${secs}s)` : ''}` : `ALLOW?${secs !== null ? ` (${secs}s)` : ''}`;
      body.push({ bg: bgBand, fg: pal.amber, bold: true, text: ` ◆ ${title}` });
      for (const ln of wrapText(p.text || 'pending action', box.w - 3, 3)) {
        body.push({ bg: bgBand, fg: pal.text, text: `  ${ln}` });
      }
      const btnRowIdx = body.length;
      body.push({
        bg: bgBand,
        raw: `${bgBand} ${bgHex(pal.accentDeep)}${fgHex(pal.text)}\x1b[1m Allow (^Aa) ${RESET}${bgBand} ${bgHex(pal.surface2)}${fgHex(pal.red)} Veto (^Av) ${RESET}${bgBand}${' '.repeat(Math.max(0, box.w - 27))}`,
        onHit: (rowY) => {
          this.hitboxes.push({ x1: box.x + 1, x2: box.x + 13, y1: rowY, y2: rowY, onClick: () => this._sysopAction('approve') });
          this.hitboxes.push({ x1: box.x + 15, x2: box.x + 26, y1: rowY, y2: rowY, onClick: () => this._sysopAction('veto') });
        },
        btnRowIdx,
      });
      body.push({ bg: bgS, fg: pal.border, text: '─'.repeat(box.w) });
    } else if (this.sysop.blocked.length > 0) {
      const b = this.sysop.blocked[0];
      body.push({ bg: bgBand, fg: pal.amber, bold: true, text: ` ◆ BLOCKED: ${b.name}` });
      for (const ln of wrapText(b.msg, box.w - 3, 2)) {
        body.push({ bg: bgBand, fg: pal.text, text: `  ${ln}` });
      }
      body.push({
        bg: bgBand,
        raw: `${bgBand} ${bgHex(pal.accentDeep)}${fgHex(pal.text)}\x1b[1m Allow (^Aa) ${RESET}${bgBand} ${bgHex(pal.surface2)}${fgHex(pal.red)} Deny (^Av) ${RESET}${bgBand}${' '.repeat(Math.max(0, box.w - 27))}`,
        onHit: (rowY) => {
          this.hitboxes.push({ x1: box.x + 1, x2: box.x + 13, y1: rowY, y2: rowY, onClick: () => this._sysopAction('approve') });
          this.hitboxes.push({ x1: box.x + 15, x2: box.x + 26, y1: rowY, y2: rowY, onClick: () => this._sysopAction('veto') });
        },
      });
      body.push({ bg: bgS, fg: pal.border, text: '─'.repeat(box.w) });
    }

    // Steps feed
    const stepLines = [];
    if (!this.sysop.up) {
      stepLines.push({ bg: bgS, fg: pal.dim, text: ' Sysop service is off.' });
      stepLines.push({ bg: bgS, fg: pal.dim, text: ' Enable with: swarmbox-addon' });
      stepLines.push({ bg: bgS, fg: pal.dim, text: ' install sysop' });
    } else if (this.sysop.steps.length === 0) {
      stepLines.push({ bg: bgS, fg: pal.muted, text: ' Ready for a goal.' });
      stepLines.push({ bg: bgS, fg: pal.dim, text: ' Press ^A g (or Alt+G) to' });
      stepLines.push({ bg: bgS, fg: pal.dim, text: ' type a goal for the active' });
      stepLines.push({ bg: bgS, fg: pal.dim, text: ' tab or any terminal.' });
    } else {
      for (const st of this.sysop.steps) {
        const icon = st.kind === 'goal' ? '›' : st.kind === 'ok' ? '✓' : st.kind === 'err' ? '!' : '·';
        const col = st.kind === 'goal' ? pal.accentBright : st.kind === 'ok' ? pal.green : st.kind === 'err' ? pal.red : pal.muted;
        const wrapped = wrapText(st.text, box.w - 4, 3);
        wrapped.forEach((ln, idx) => {
          stepLines.push({
            bg: bgS,
            fg: col,
            bold: st.kind === 'goal' && idx === 0,
            text: ` ${idx === 0 ? icon : ' '} ${ln}`,
          });
        });
      }
    }

    const availFeed = Math.max(0, feedArea - body.length);
    const tail = stepLines.slice(-availFeed);
    const combined = [...body, ...tail];

    for (let i = 0; i < feedArea; i++) {
      const item = combined[i];
      const rowY = box.y + 1 + i;
      if (!item) {
        out.push(`${bgS}${' '.repeat(box.w)}`);
      } else if (item.raw) {
        out.push(item.raw);
        if (item.onHit) item.onHit(rowY);
      } else {
        out.push(`${item.bg}${fgHex(item.fg)}${item.bold ? '\x1b[1m' : ''}${fitText(item.text, box.w)}${RESET}${item.bg}`);
      }
    }

    // Bottom goal input box
    const inpY = box.y + 1 + feedArea;
    const isGoal = this.focus === 'goal';
    out.push(`${bgS}${fgHex(isGoal ? pal.accentBright : pal.border)}${'─'.repeat(box.w)}`);

    const visibleDraft = this.goalDraft.length > box.w - 4
      ? '…' + this.goalDraft.slice(-(box.w - 5))
      : this.goalDraft;
    const promptTxt = isGoal
      ? ` › ${visibleDraft}`
      : ' › Ask sysop… (^A g)';
    const inpBg = isGoal ? bgBand : bg2;
    const inpFg = isGoal ? pal.text : pal.dim;
    out.push(`${inpBg}${fgHex(inpFg)}${fitText(promptTxt, box.w)}`);
    this.hitboxes.push({
      x1: box.x,
      x2: box.x + box.w - 1,
      y1: inpY + 1,
      y2: inpY + 1,
      onClick: () => this._focusGoal(),
    });

    return out.slice(0, box.h);
  }

  _renderFooter(L, pal) {
    const bgS = bgHex(pal.surface);
    if (this.prefixMode) {
      return `${bgHex(pal.accentDeep)}${fgHex(pal.text)}\x1b[1m${fitText(' ^A PREFIX: 1-9 tab · n/p next/prev · c shell · C agent · b sidebar · s sysop · g goal · a allow · v veto · t theme · d detach · ? help', L.W)}${RESET}`;
    }
    if (this.focus === 'goal') {
      return `${bgHex(pal.band)}${fgHex(pal.accentBright)}${fitText(' SYSOP GOAL: Type goal and press Enter to send · Esc to return to terminal · Ctrl+U clear', L.W)}${RESET}`;
    }
    if (this.toast) {
      return `${bgHex(pal.band)}${fgHex(pal.accentBright)}${fitText(` ✦ ${this.toast}`, L.W)}${RESET}`;
    }
    if (this.scrollOffset > 0) {
      return `${bgHex(pal.band)}${fgHex(pal.amber)}${fitText(` SCROLL +${this.scrollOffset} lines · Shift+PgUp/PgDn or wheel · type any key to return to live`, L.W)}${RESET}`;
    }
    const hint = ' ^A prefix · Alt+1-9 tabs · Alt+N shell · Alt+B sidebar · Alt+S sysop · Alt+G goal · Alt+T theme · ^A d detach';
    return `${bgS}${fgHex(pal.dim)}${fitText(hint, L.W)}${RESET}`;
  }

  _overlayHelp(rows, L, pal) {
    const lines = [
      'SwarmBox Terminal Cockpit (herdr-core)',
      '',
      'Ctrl+A c / Alt+N    New shell tab',
      'Ctrl+A C            New agent tab',
      'Ctrl+A 1..9 / Alt+N Switch tab',
      'Ctrl+A n / p        Next / previous tab',
      'Ctrl+A x            Close active tab',
      'Ctrl+A b / Alt+B    Toggle left sidebar',
      'Ctrl+A s / Alt+S    Toggle Sysop panel',
      'Ctrl+A g / Alt+G    Ask Sysop (goal input)',
      'Ctrl+A a / v / X    Sysop Allow / Veto / Stop',
      'Ctrl+A t / Alt+T    Cycle 5 synced themes',
      'Ctrl+A Ctrl+A       Send literal Ctrl+A',
      'Ctrl+A d            Detach (keeps terminals)',
      'Shift+PgUp / PgDn   Scroll terminal history',
      '',
      'Press any key to close',
    ];
    const boxW = Math.min(L.W - 4, 50);
    const boxH = Math.min(L.H - 2, lines.length + 2);
    const top = Math.max(1, Math.floor((L.H - boxH) / 2));
    const left = Math.max(1, Math.floor((L.W - boxW) / 2));
    const padL = ' '.repeat(left);
    const bgB = bgHex(pal.surface2);
    const bd = fgHex(pal.accent);

    rows[top] = `${bgHex(pal.bg)}${padL}${bgB}${bd}╭${'─'.repeat(boxW - 2)}╮${RESET}`;
    for (let i = 0; i < boxH - 2; i++) {
      const txt = lines[i] || '';
      const col = i === 0 ? `${fgHex(pal.accentBright)}\x1b[1m` : fgHex(pal.text);
      rows[top + 1 + i] = `${bgHex(pal.bg)}${padL}${bgB}${bd}│${col} ${fitText(txt, boxW - 4)} ${RESET}${bgB}${bd}│${RESET}`;
    }
    rows[top + boxH - 1] = `${bgHex(pal.bg)}${padL}${bgB}${bd}╰${'─'.repeat(boxW - 2)}╯${RESET}`;
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
