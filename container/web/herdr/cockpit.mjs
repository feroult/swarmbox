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
import {
  DEFAULT_THEME,
  HC_BIN,
  HERDR_THEMES,
  HerdrClient,
  SYSOP_BIN,
  readActiveTab,
  readSavedTheme,
  readSysopSnapshot,
} from './hc-client.mjs';
import { computeLayout } from './cockpit-ansi.mjs';
import {
  clearPrefix,
  enterPrefix,
  handleAltKey,
  handleGoalKey,
  handleMouse,
  handlePrefixKey,
  handleStdin,
  handleWheel,
  scrollBuffer,
} from './cockpit-input.mjs';
import {
  overlayHelp,
  renderFooter,
  renderSidebar,
  renderTopBar,
} from './cockpit-render-chrome.mjs';
import {
  buildFrame,
  cellSgr,
  renderFrame,
  renderSysopPanel,
  renderTerminalPane,
} from './cockpit-render-pane.mjs';
import {
  attachTo,
  closeActiveTab,
  createTab,
  cycleTab,
  cycleTheme,
  ensureActiveAttached,
  focusGoal,
  getRunDir,
  onTerminals,
  pollOpenUrl,
  readOpenUrlEvent,
  shutdownCockpit,
  startCockpit,
  submitGoal,
  switchIndex,
  syncPaneSize,
  sysopAction,
  toggleSidebar,
  toggleSysop,
} from './cockpit-session.mjs';

export {
  bgHex,
  charDisplayWidth,
  clipText,
  computeLayout,
  fgHex,
  fitText,
  hexToRgb,
  smartTabParts,
  visibleWidth,
} from './cockpit-ansi.mjs';

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
    this.toastHref = '';
    this.toastTimer = null;
    this.lastOpenUrlId = '';
    this._markerPath = '';
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
    return (HERDR_THEMES[this.themeName] || HERDR_THEMES[DEFAULT_THEME]).cockpit;
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

  setToast(msg, ms = 2600, href = '') {
    this.toast = String(msg || '');
    this.toastHref = String(href || '');
    if (this.toastTimer) clearTimeout(this.toastTimer);
    this.toastTimer = setTimeout(() => {
      this.toast = '';
      this.toastHref = '';
      this.toastTimer = null;
      this.scheduleRender();
    }, ms);
    if (this.toastTimer.unref) this.toastTimer.unref();
    this.scheduleRender();
  }

  _runDir() { return getRunDir(); }
  _readOpenUrlEvent() { return readOpenUrlEvent(this); }
  _pollOpenUrl() { return pollOpenUrl(this); }

  start() { return startCockpit(this); }
  shutdown(code = 0) { return shutdownCockpit(this, code); }

  _onResize() {
    this.prevRows = [];
    this._syncPaneSize();
    this.scheduleRender(true);
  }

  _syncPaneSize() { return syncPaneSize(this); }
  _onTerminals(list) { return onTerminals(this, list); }
  _ensureActiveAttached() { return ensureActiveAttached(this); }
  _attachTo(addr) { return attachTo(this, addr); }
  _createTab(preset) { return createTab(this, preset); }
  _closeActiveTab() { return closeActiveTab(this); }
  _switchIndex(idx) { return switchIndex(this, idx); }
  _cycleTab(delta) { return cycleTab(this, delta); }
  _cycleTheme() { return cycleTheme(this); }
  _toggleSidebar() { return toggleSidebar(this); }
  _toggleSysop() { return toggleSysop(this); }
  _focusGoal() { return focusGoal(this); }
  _submitGoal() { return submitGoal(this); }
  _sysopAction(action) { return sysopAction(this, action); }

  _wheel(dir, btn, x, y) { return handleWheel(this, dir, btn, x, y); }
  _scroll(delta) { return scrollBuffer(this, delta); }
  _onStdin(chunk) { return handleStdin(this, chunk); }
  _enterPrefix() { return enterPrefix(this); }
  _clearPrefix() { return clearPrefix(this); }
  _handlePrefixKey(byte) { return handlePrefixKey(this, byte); }
  _handleAltKey(ch) { return handleAltKey(this, ch); }
  _handleGoalKey(buf) { return handleGoalKey(this, buf); }
  _handleMouse(btn, x, y, press) { return handleMouse(this, btn, x, y, press); }

  scheduleRender(forceFull = false) {
    if (forceFull) this.prevRows = [];
    if (this.renderQueued || this.closed) return;
    this.renderQueued = true;
    setImmediate(() => {
      this.renderQueued = false;
      if (!this.closed) this.render();
    });
  }

  buildFrame() { return buildFrame(this); }
  render() { return renderFrame(this); }
  _renderTopBar(L, pal) { return renderTopBar(this, L, pal); }
  _renderSidebar(box, pal) { return renderSidebar(this, box, pal); }
  _renderTerminalPane(box, pal) { return renderTerminalPane(this, box, pal); }
  _cellSgr(cell, pal) { return cellSgr(cell, pal); }
  _renderSysopPanel(box, pal) { return renderSysopPanel(this, box, pal); }
  _renderFooter(L, pal) { return renderFooter(this, L, pal); }
  _overlayHelp(rows, L, pal) { return overlayHelp(rows, L, pal); }
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
