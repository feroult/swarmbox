// xterm.js terminal session lifecycle: canvas renderer, fit/resize, smart copy, image paste/drop, PTY WebSocket, and tab switching.

import {
  STUDIO_CLIENT_ID,
  MAX_TAB_SESSIONS,
  state,
  dom,
  actions,
  activeSession,
  syncConnPill,
  dismissBoot,
} from './state.js';
import {
  DEFAULT_THEME,
  THEMES,
  computeFontSize,
  computeLineHeight,
  syncAppearanceControls,
} from './themes.js';
import { tabAgentKind } from './icons.js';
import { showTermToast } from './ui-chrome.js';
import {
  clearTouchOffset,
  touchOffsetOnScroll,
  touchOffsetOnRender,
  isViewportPinchingOrBouncing,
  isTouchActive,
  isTouchPinchOrCooldown,
  setZoomCooldown,
  isZoomCooldownElapsed,
  logTouchDebug,
  stopTouchCoast,
} from './touch-scroll.js';
import {
  terminalCwdFor,
  openFilePreview,
  createTerminalPathLinkProvider,
  createWrappedUrlLinkProvider,
} from './file-preview.js';

export const tabSessions = state.tabSessions;

function plural(n, word) {
  if (n === 1) return `${n} ${word}`;
  return `${n} ${/[^aeiou]y$/.test(word) ? `${word.slice(0, -1)}ies` : `${word}s`}`;
}

function isRealFormField(el) {
  if (!el || !el.tagName) return false;
  if (el.tagName === 'TEXTAREA') return !el.classList?.contains('xterm-helper-textarea');
  return el.tagName === 'INPUT' || el.tagName === 'SELECT';
}

// Pixel-perfect block-drawing & box-drawing glyphs are rendered procedurally by
// @xterm/addon-canvas (customGlyphs: true) across full cell height (including lineHeight).
export function attachCanvasRenderer(term) {
  if (!window.CanvasAddon) return null;
  try {
    const addon = new window.CanvasAddon.CanvasAddon();
    term.loadAddon(addon);
    // Guard against Chromium/Android ResizeObserver devicePixelContentBoxSize disagreeing with
    // window.devicePixelRatio (e.g. during optical pinch-zoom or CDP DPR emulation), which
    // would otherwise shrink canvas backing pixels while leaving device.cell scaled and clip.
    const renderer = addon._renderer;
    if (renderer && typeof renderer._setCanvasDevicePixelDimensions === 'function') {
      const origSet = renderer._setCanvasDevicePixelDimensions.bind(renderer);
      renderer._setCanvasDevicePixelDimensions = (w, h) => {
        const dims = renderer.dimensions;
        const expectedW = (term.cols || 0) * (dims?.device?.cell?.width || 0);
        const expectedH = (term.rows || 0) * (dims?.device?.cell?.height || 0);
        if (expectedW > 0 && Math.abs(w - expectedW) > Math.max(8, expectedW * 0.06)) return;
        if (expectedH > 0 && Math.abs(h - expectedH) > Math.max(8, expectedH * 0.06)) return;
        return origSet(w, h);
      };
    }
    return addon;
  } catch (_) {
    return null;
  }
}

// Show sleek floating "Jump to live" pill whenever user scrolls up into history.
// Avoid DOM layout reads (scrollHeight/clientHeight/scrollTop) on every scroll frame!
let lastJumpVisible = false;
export function syncJumpLive() {
  if (!dom.btnJumpLive) return;
  const sess = activeSession();
  if (!sess || sess.hydrating) {
    if (lastJumpVisible) {
      lastJumpVisible = false;
      dom.btnJumpLive.classList.remove('visible');
    }
    return;
  }
  const buf = sess.term.buffer && sess.term.buffer.active;
  const up = Boolean(buf && buf.type === 'normal' && buf.baseY - buf.viewportY > 2);
  if (up !== lastJumpVisible) {
    lastJumpVisible = up;
    dom.btnJumpLive.classList.toggle('visible', up);
  }
}

export function isSessionAtBottom(sess) {
  if (!sess) return true;
  try {
    const buf = sess.term.buffer && sess.term.buffer.active;
    if (buf && typeof buf.baseY === 'number' && typeof buf.viewportY === 'number') {
      return (buf.baseY - buf.viewportY) <= 1;
    }
  } catch (_) {}
  return true;
}

export function syncStageLoader() {
  if (!dom.termStageLoaderEl) return;
  const sess = activeSession();
  const busy = Boolean(sess && (sess.resizing || sess.hydrating || sess.revealPending));
  // While the active agent's launcher waits for the first context of its repository, the same loader covers the terminal with
  // what it waits for and a way out (Enter in the terminal does the same: the launcher reads it).
  const t = state.activeId ? state.terminals.find((x) => x.address === state.activeId) : null;
  let ctx = null;
  try {
    ctx = (t && typeof actions.ctxSessionFor === 'function') ? actions.ctxSessionFor(t) : null;
  } catch (_) {
    ctx = null; // called once before the context state exists
  }
  const waiting = Boolean(ctx && ctx.waiting);
  if (dom.stageLoaderCtxEl) {
    dom.stageLoaderCtxEl.hidden = !waiting;
    if (waiting) {
      const secs = Math.max(0, Math.round((Date.now() - (ctx.at || Date.now())) / 1000));
      const behind = ctx.reason === 'behind';
      dom.stageLoaderCtxTitleEl.textContent = `${behind ? 'Rewriting' : 'Preparing'} the context of ${ctx.repo || 'this repository'}`;
      dom.stageLoaderCtxSubEl.textContent = behind
        ? `${ctx.changes ? `${plural(ctx.changes, 'file')} changed` : 'Its docs changed'} since the last one · ${secs}s · the agent starts with the new one`
        : `The sysop is writing it · ${secs}s · the agent starts with it`;
      if (dom.stageLoaderCtxSkipEl && dom.stageLoaderCtxSkipEl.firstChild) {
        dom.stageLoaderCtxSkipEl.firstChild.textContent = behind ? 'Start with the last one ' : 'Start without it ';
      }
    }
  }
  dom.termStageLoaderEl.classList.toggle('is-ctx', waiting);
  // During initial page load, #sb-boot already covers the viewport; once dismissed,
  // use the stage-scoped SwarmBox loader whenever a resize or cold tab hydration runs.
  const show = state.bootDismissed && (busy || waiting || dom.termWrapEl.classList.contains('term-loading'));
  dom.termStageLoaderEl.classList.toggle('visible', show);
}

// A full-screen program in this session, by the terminal's own signals: the alternate screen or mouse reporting in this page's
// xterm, or what the gateway last said (its view adds the OSC 7501 status the agents report). Never by a name.
export function isSessionTui(sess) {
  if (!sess) return false;
  try {
    const buf = sess.term && sess.term.buffer && sess.term.buffer.active;
    if (buf && buf.type === 'alternate') return true;
    const mm = sess.term && sess.term.modes && sess.term.modes.mouseTrackingMode;
    if (mm && mm !== 'none') return true;
  } catch (_) {}
  return Boolean(sess.serverTui);
}

export function concatChunks(chunks) {
  let total = 0;
  for (const c of chunks) total += c.byteLength;
  const out = new Uint8Array(total);
  let off = 0;
  for (const c of chunks) {
    out.set(c, off);
    off += c.byteLength;
  }
  return out;
}

export function finishResizeCycle(sess, seq = null) {
  if (!sess || !sess.resizing) return;
  if (seq !== null && seq > 0 && sess.resizeSeq > 0 && seq < sess.resizeSeq) return;
  sess.resizing = false;
  sess.resizeAwaitingServer = false;
  sess.revealPending = true;
  if (sess.resizeFallbackTimer) {
    clearTimeout(sess.resizeFallbackTimer);
    sess.resizeFallbackTimer = null;
  }
  const batch = sess.resizeChunks || [];
  sess.resizeChunks = [];
  const keepBottom = sess.resizeWasAtBottom !== false;
  const savedOffset = Number.isFinite(sess.resizeLinesFromBottom) ? sess.resizeLinesFromBottom : 0;
  const restoreScroll = () => {
    const vp = sess.paneEl.querySelector('.xterm-viewport');
    if (keepBottom) {
      try { sess.term.scrollToBottom(); } catch (_) {}
      if (vp) vp.scrollTop = vp.scrollHeight;
    } else {
      try {
        const b = sess.term.buffer && sess.term.buffer.active;
        if (b && b.type === 'normal' && b.baseY > 0) {
          sess.term.scrollToLine(Math.max(0, b.baseY - savedOffset));
        }
      } catch (_) {}
    }
  };
  const reveal = () => {
    if (sess.resizing) return;
    restoreScroll();
    requestAnimationFrame(() => {
      if (sess.resizing) return;
      restoreScroll();
      requestAnimationFrame(() => {
        if (sess.resizing) return;
        sess.revealPending = false;
        sess.paneEl.classList.remove('resizing');
        if (state.activeId === sess.address) {
          syncStageLoader();
          syncJumpLive();
        }
      });
    });
  };
  if (batch.length > 0) {
    sess.term.write(concatChunks(batch), reveal);
  } else {
    reveal();
  }
}

export function beginResizeCycle(sess) {
  if (!sess || sess.hydrating) return;
  if (!sess.resizing) {
    sess.resizeWasAtBottom = isSessionAtBottom(sess);
    sess.resizeChunks = [];
    sess.resizing = true;
    sess.revealPending = false;
    sess.paneEl.classList.add('resizing');
  }
  if (state.activeId === sess.address) syncStageLoader();
  if (sess.resizeFallbackTimer) clearTimeout(sess.resizeFallbackTimer);
  // the gateway's number (the agent's profile) when it gave one, else the core's TUI or plain one
  const fallbackMs = sess.serverFallbackMs || (isSessionTui(sess) ? 4200 : 600);
  sess.resizeFallbackTimer = setTimeout(() => finishResizeCycle(sess), fallbackMs);
}

export function fitSession(sess, sendResize = true) {
  if (!sess) return;
  if (isTouchPinchOrCooldown()) {
    return;
  }
  try {
    const nextFont = computeFontSize();
    const nextLH = computeLineHeight();
    if (sess.term.options.fontSize !== nextFont) sess.term.options.fontSize = nextFont;
    if (sess.term.options.lineHeight !== nextLH) sess.term.options.lineHeight = nextLH;
    const wasAtBottom = isSessionAtBottom(sess);
    const bufBefore = sess.term.buffer && sess.term.buffer.active;
    const linesFromBottom = (bufBefore && bufBefore.type === 'normal')
      ? Math.max(0, bufBefore.baseY - bufBefore.viewportY)
      : 0;
    const canSendResize = sendResize && sess.isOwner !== false;
    // Pre-mask BEFORE fitAddon.fit() reflows xterm's normal buffer so no half-wrapped frame paints.
    let willChange = false;
    if (canSendResize && !sess.hydrating && sess.ws && sess.ws.readyState === 1 && typeof sess.fitAddon.proposeDimensions === 'function') {
      try {
        const prop = sess.fitAddon.proposeDimensions();
        if (prop && prop.cols && prop.rows && (prop.cols !== sess.lastCols || prop.rows !== sess.lastRows)) {
          willChange = true;
          sess.resizeWasAtBottom = wasAtBottom;
          sess.resizeLinesFromBottom = linesFromBottom;
          beginResizeCycle(sess);
        }
      } catch (_) {}
    }
    sess.fitAddon.fit();
    sess.needsFit = false;
    const changed = sess.term.cols !== sess.lastCols || sess.term.rows !== sess.lastRows;
    if (canSendResize && changed && sess.ws && sess.ws.readyState === 1) {
      const prevCols = sess.lastCols;
      const prevRows = sess.lastRows;
      sess.lastCols = sess.term.cols;
      sess.lastRows = sess.term.rows;
      sess.resizeSeq = (sess.resizeSeq || 0) + 1;
      if (!sess.hydrating) {
        sess.resizeWasAtBottom = wasAtBottom;
        sess.resizeLinesFromBottom = linesFromBottom;
        sess.resizeAwaitingServer = true;
        if (!willChange) beginResizeCycle(sess);
        logTouchDebug('resize_sent', {
          prevCols,
          prevRows,
          cols: sess.term.cols,
          rows: sess.term.rows,
          vvTop: window.visualViewport ? Math.round(window.visualViewport.offsetTop || 0) : 0,
          vvLeft: window.visualViewport ? Math.round(window.visualViewport.offsetLeft || 0) : 0,
        });
      }
      sess.ws.send(JSON.stringify({
        type: 'resize',
        cols: sess.term.cols,
        rows: sess.term.rows,
        seq: sess.resizeSeq,
      }));
    } else if (canSendResize && !changed && sess.resizing && !sess.resizeAwaitingServer) {
      // Pre-armed resize cycle (e.g. panel toggle) produced identical cols/rows: reveal cleanly.
      finishResizeCycle(sess);
    }
  } catch (_) {}
}

let desktopFitDebounce = 0;
let mobileFitDebounce = 0;

export function fitAndResize() {
  if (isTouchPinchOrCooldown()) return;
  syncAppearanceControls();
  const active = activeSession();
  for (const sess of state.tabSessions.values()) {
    if (sess === active) fitSession(sess, true);
    else sess.needsFit = true;
  }
}

export function scheduleFit() {
  if (isTouchPinchOrCooldown()) return;
  if (window.innerWidth <= 860) {
    // Debounce all mobile fit triggers (ResizeObserver, window.resize, keyboard slide animation)
    // so a 250ms iOS keyboard slide sends 1 clean final SIGWINCH instead of 5 intermediate ones.
    clearTimeout(mobileFitDebounce);
    mobileFitDebounce = setTimeout(() => {
      mobileFitDebounce = 0;
      if (!isTouchPinchOrCooldown()) {
        fitAndResize();
      }
    }, 160);
    return;
  }
  // Debounce continuous desktop window-drag resizes (90ms) so dragging a window edge sends
  // one clean final SIGWINCH to the agents' TUIs instead of 30+ intermediate reflows.
  // Instant panel toggles bypass scheduleFit() and call fitAndResize() synchronously.
  const active = activeSession();
  if (active && active.isOwner !== false && !active.hydrating && active.ws && active.ws.readyState === 1 && typeof active.fitAddon.proposeDimensions === 'function') {
    try {
      const prop = active.fitAddon.proposeDimensions();
      if (prop && prop.cols && prop.rows && (prop.cols !== active.lastCols || prop.rows !== active.lastRows)) {
        beginResizeCycle(active);
      }
    } catch (_) {}
  }
  clearTimeout(desktopFitDebounce);
  desktopFitDebounce = setTimeout(() => {
    desktopFitDebounce = 0;
    fitAndResize();
  }, 150);
}

// Wait for self-hosted JetBrains Mono before the first PTY attach so initial cols/rows
// match exact glyph metrics on frame 0 (eliminating post-boot font-metric reflow).
let fontsSettled = false;

export function flushAllTextureAtlases() {
  for (const s of state.tabSessions.values()) {
    try { s.term.clearTextureAtlas(); } catch (_) {}
  }
}

export const fontsReadyPromise = (typeof document !== 'undefined' && document.fonts && document.fonts.ready)
  ? Promise.race([
      Promise.all([
        typeof document.fonts.load === 'function'
          ? document.fonts.load('400 16px "JetBrains Mono"').catch(() => {})
          : Promise.resolve(),
        document.fonts.ready.catch(() => {}),
      ]),
      new Promise((r) => setTimeout(r, 1200)),
    ]).then(() => {
      fontsSettled = true;
      flushAllTextureAtlases();
    })
  : Promise.resolve().then(() => { fontsSettled = true; });

export function ensureFontLoaded() {
  return fontsReadyPromise;
}

if (typeof document !== 'undefined' && document.fonts && typeof document.fonts.addEventListener === 'function') {
  document.fonts.addEventListener('loadingdone', () => {
    flushAllTextureAtlases();
  });
}

// Mobile keyboard & terminal-keys state: user-pinned keys never disappear mid-tap, and the
// open Sysop sheet tracks visualViewport height/offsetTop cleanly when the OS keyboard rises.
export function syncMobileKeys() {
  if (!dom.appEl) return;
  const isMob = window.innerWidth <= 860;
  const sheetOpen = dom.appEl.dataset.mobileSysop === '1';
  const focusSysop = document.activeElement === dom.goalInputEl;
  const kbTerm = isMob && state.mobileKbOpen && !sheetOpen && !focusSysop;
  const kbSysop = isMob && state.mobileKbOpen && (sheetOpen || focusSysop);
  dom.appEl.dataset.kbTerm = kbTerm ? '1' : '0';
  dom.appEl.dataset.kbSysop = kbSysop ? '1' : '0';
  const showKeys = isMob && !sheetOpen && (state.mobileKeysPinned || (kbTerm && !state.mobileKeysDismissedForKb));
  dom.appEl.dataset.mobileKeys = showKeys ? '1' : '0';
  if (dom.btnMobileKeys) dom.btnMobileKeys.dataset.on = showKeys ? '1' : '0';
}

let baseMobileH = (typeof document !== 'undefined' && typeof window !== 'undefined')
  ? (document.documentElement.clientHeight || window.innerHeight || 0)
  : 0;
let lastAppliedVvH = 0;
let lastLoggedZoomScale = 1;
let touchDbgZoomTimer = 0;
let zoomCooldownTimer = 0;

export function syncViewport(fromScroll = false) {
  if (typeof window === 'undefined' || !window.visualViewport) {
    syncMobileKeys();
    return;
  }
  const vv = window.visualViewport;
  const vvScale = Number(vv.scale || 1);
  const zoomed = vvScale > 1.02;
  const pinchingOrBouncing = isViewportPinchingOrBouncing();
  dom.appEl.dataset.zoomed = zoomed ? '1' : '0';
  if (Math.abs(vvScale - lastLoggedZoomScale) > 0.04) {
    lastLoggedZoomScale = vvScale;
    clearTimeout(touchDbgZoomTimer);
    touchDbgZoomTimer = setTimeout(() => {
      logTouchDebug(zoomed ? 'zoom' : 'zoom_reset', {
        scale: Number(vvScale.toFixed(3)),
        vvTop: Math.round(vv.offsetTop || 0),
        vvLeft: Math.round(vv.offsetLeft || 0),
      });
    }, 220);
  }
  if (pinchingOrBouncing) {
    // Optical browser pinch-zoom or iOS pinch-out rubber-band bounce:
    // Freeze #app at its pre-zoom pixel height (NEVER switch to 100dvh mid-pinch, which shifts
    // Safari's toolbar/dock height!), NEVER poison baseMobileH, and NEVER trigger SIGWINCH.
    setZoomCooldown(650);
    state.mobileKbOpen = false;
    syncMobileKeys();
    clearTimeout(zoomCooldownTimer);
    zoomCooldownTimer = setTimeout(() => syncViewport(false), 680);
    return;
  }
  const layoutH = document.documentElement.clientHeight || window.innerHeight || 0;
  const vvH = layoutH > 0 ? Math.min(layoutH, Math.round(vv.height)) : Math.round(vv.height);
  const vvTop = Math.max(0, Math.round(vv.offsetTop || 0));
  dom.appEl.style.setProperty('--vv-h', `${vvH}px`);
  dom.appEl.style.setProperty('--vv-top', `${vvTop}px`);
  dom.appEl.style.height = `${vvH}px`;
  if (window.innerWidth <= 860) {
    if (layoutH > 0 && vvH >= layoutH - 20) baseMobileH = layoutH;
    else if (vvH > baseMobileH && (layoutH === 0 || vvH <= layoutH)) baseMobileH = vvH;
    const wasKb = state.mobileKbOpen;
    state.mobileKbOpen = (baseMobileH - vvH) > 110;
    if (wasKb && !state.mobileKbOpen) state.mobileKeysDismissedForKb = false;
  } else {
    state.mobileKbOpen = false;
    state.mobileKeysDismissedForKb = false;
  }
  syncMobileKeys();
  if (dom.appEl.dataset.kbSysop === '1' && dom.appEl.dataset.mobileSysop === '1' && dom.sysopFeedEl) {
    requestAnimationFrame(() => { dom.sysopFeedEl.scrollTop = dom.sysopFeedEl.scrollHeight; });
  }
  const hChanged = Math.abs(vvH - lastAppliedVvH) >= 2;
  lastAppliedVvH = vvH;
  if (!fromScroll && hChanged && isZoomCooldownElapsed()) {
    scheduleFit();
  }
}

export function focusTerminalIfDesktop() {
  if (state.settingsOpen) return;
  const sess = activeSession();
  if (sess && window.innerWidth > 860 && document.activeElement !== dom.goalInputEl) {
    sess.term.focus();
  }
}

const MOUSE_MOTION_INPUT_RE = /^(?:\x1b\[<[0-9;]+[Mm]|\x1b\[M[\s\S]{3})+$/;

export function sendPtyInput(data, targetSession = null) {
  const sess = targetSession || activeSession();
  if (!data || !sess) return;
  if ((sess.resizing || sess.hydrating || sess.revealPending) && MOUSE_MOTION_INPUT_RE.test(data)) {
    return;
  }
  if (sess.ws && sess.ws.readyState === 1) {
    sess.ws.send(JSON.stringify({ type: 'input', data }));
    return;
  }
  // Never silently drop keystrokes when the PTY socket dipped or is reconnecting:
  // buffer the input and immediately re-attach to the active terminal.
  sess.pendingInput.push(data);
  if (sess.pendingInput.length > 64) sess.pendingInput = sess.pendingInput.slice(-64);
  if (!sess.ws || sess.ws.readyState === 2 || sess.ws.readyState === 3) {
    openSessionSocket(sess, { silent: true, reset: true });
  }
}

// Real user interaction (pointerdown/keydown/wheel/tab click) claims viewport ownership on the server
// so only the last active channel sizes the PTY, with zero ping-pong against idle devices.
export function claimSessionViewport(sess) {
  if (!sess || !sess.ws || sess.ws.readyState !== 1) return;
  fitSession(sess, false);
  const cols = sess.term.cols || 100;
  const rows = sess.term.rows || 30;
  sess.lastCols = cols;
  sess.lastRows = rows;
  sess.passiveAttach = false;
  sess.isOwner = true;
  if (!sess.hydrating && sess.serverPtyCols && (sess.serverPtyCols !== cols || sess.serverPtyRows !== rows)) {
    sess.resizeAwaitingServer = true;
    beginResizeCycle(sess);
  }
  sess.ws.send(JSON.stringify({
    type: 'focus',
    focused: true,
    claim: true,
    cols,
    rows,
  }));
}

// Self-heal if the server reports a PTY size that disagrees with our fitted xterm viewport
// ONLY when this client is the active PTY owner. Never fight another device's ownership.
export function verifyServerPtySize(sess, serverCols, serverRows) {
  if (!sess || !serverCols || !serverRows) return;
  if (state.activeId !== sess.address || sess.hydrating || sess.resizing) return;
  if (!sess.isOwner || sess.passiveAttach) return;
  fitSession(sess, false);
  const wantCols = sess.term.cols || 0;
  const wantRows = sess.term.rows || 0;
  if (wantCols > 0 && wantRows > 0 && (wantCols === serverCols && wantRows === serverRows)) {
    sess.resyncCount = 0;
    return;
  }
  if (wantCols > 0 && wantRows > 0 && sess.ws && sess.ws.readyState === 1 && (sess.resyncCount || 0) < 2) {
    sess.resyncCount = (sess.resyncCount || 0) + 1;
    sess.lastCols = wantCols;
    sess.lastRows = wantRows;
    sess.resizeSeq = (sess.resizeSeq || 0) + 1;
    sess.resizeAwaitingServer = true;
    beginResizeCycle(sess);
    sess.ws.send(JSON.stringify({
      type: 'resize',
      cols: wantCols,
      rows: wantRows,
      seq: sess.resizeSeq,
    }));
  }
}

function onUserChannelActivity() {
  const sess = activeSession();
  if (!sess || sess.hydrating || !sess.ws || sess.ws.readyState !== 1) return;
  if (sess.isOwner !== true || sess.passiveAttach) {
    claimSessionViewport(sess);
  }
}

const IMAGE_EXT_RE = /\.(?:png|jpe?g|webp|gif|bmp)$/i;
function isImageBlob(item) {
  if (!item) return false;
  if (typeof item.type === 'string' && item.type.startsWith('image/')) return true;
  if (typeof item.name === 'string' && IMAGE_EXT_RE.test(item.name)) return true;
  return false;
}

let lastNativePasteTs = 0;

export function extractClipboardImages(dt) {
  if (!dt) return [];
  const blobs = [];
  if (dt.items && dt.items.length) {
    for (const item of dt.items) {
      if (item.kind === 'file') {
        const f = item.getAsFile();
        if (f && (item.type.startsWith('image/') || isImageBlob(f))) blobs.push(f);
      }
    }
  }
  if (blobs.length === 0 && dt.files && dt.files.length) {
    for (const f of dt.files) {
      if (isImageBlob(f)) blobs.push(f);
    }
  }
  return blobs;
}

export async function uploadAndPasteImages(blobs, targetSession = null) {
  const sess = targetSession || activeSession();
  if (!sess || !blobs || blobs.length === 0) return;
  // an agent that takes no pasted image path (TERM_IMAGE_PASTE=none in its agent.conf) gets nothing typed into it
  const pasteTab = state.terminals.find((x) => x.address === sess.address);
  const pasteAgent = state.agentReg.byId.get(pasteTab ? tabAgentKind(pasteTab) : '');
  if (pasteAgent && pasteAgent.term && pasteAgent.term.image_paste === 'none') {
    showTermToast(`${pasteAgent.label || pasteAgent.id} does not take pasted images`, 'error', 3200);
    return;
  }
  showTermToast(blobs.length === 1 ? 'Attaching image…' : `Attaching ${blobs.length} images…`, '', 0);
  const paths = [];
  const names = [];
  try {
    for (const blob of blobs) {
      const r = await fetch('/api/paste-image', {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': blob.type || 'application/octet-stream' },
        body: blob,
      });
      const d = await r.json().catch(() => ({}));
      if (!r.ok || !d.path) {
        throw new Error(d.message || d.error || `HTTP ${r.status}`);
      }
      paths.push(d.path);
      names.push(d.name || d.path);
    }
    if (paths.length > 0) {
      sess.term.paste(paths.join(' ') + ' ');
      focusTerminalIfDesktop();
      showTermToast(
        names.length === 1 ? `✓ Attached ${names[0]}` : `✓ Attached ${names.length} images`,
        'ok',
        2600,
      );
    }
  } catch (err) {
    showTermToast(`Image attach failed: ${err.message || 'error'}`, 'error', 4200);
  }
}

function hasDraggedFiles(e) {
  const types = e.dataTransfer && e.dataTransfer.types;
  if (!types) return false;
  return Array.from(types).includes('Files');
}

// Auto-heal dropped WebSockets when returning to the browser tab or waking from sleep
export function ensureConnectionsAlive() {
  if (!state.eventsWs || state.eventsWs.readyState === 2 || state.eventsWs.readyState === 3) {
    if (typeof actions.connectEvents === 'function') actions.connectEvents();
  }
  const sess = activeSession();
  if (sess && (!sess.ws || sess.ws.readyState === 2 || sess.ws.readyState === 3)) {
    openSessionSocket(sess, { silent: true, reset: true, reconnect: true });
  }
}

export function disposeSession(address) {
  const sess = state.tabSessions.get(address);
  if (!sess) return;
  state.tabSessions.delete(address);
  if (sess.reconnectTimer) { clearTimeout(sess.reconnectTimer); sess.reconnectTimer = null; }
  if (sess.fallbackTimer) { clearTimeout(sess.fallbackTimer); sess.fallbackTimer = null; }
  if (sess.resizeFallbackTimer) { clearTimeout(sess.resizeFallbackTimer); sess.resizeFallbackTimer = null; }
  if (sess.ws) {
    sess.ws.onclose = null;
    sess.ws.onerror = null;
    try { sess.ws.close(); } catch (_) {}
    sess.ws = null;
  }
  try { sess.term.dispose(); } catch (_) {}
  if (sess.paneEl && sess.paneEl.parentNode) sess.paneEl.parentNode.removeChild(sess.paneEl);
}

export const closeTabSession = disposeSession;

export function syncTabSessions(liveAddrs) {
  const keep = liveAddrs instanceof Set ? liveAddrs : new Set(liveAddrs || []);
  for (const addr of Array.from(state.tabSessions.keys())) {
    if (!keep.has(addr)) disposeSession(addr);
  }
}

export function evictOldestSessionIfNeeded() {
  while (state.tabSessions.size >= MAX_TAB_SESSIONS) {
    let oldestAddr = null;
    let oldestTs = Infinity;
    for (const [addr, sess] of state.tabSessions.entries()) {
      if (addr === state.activeId) continue;
      if (sess.lastUsed < oldestTs) {
        oldestTs = sess.lastUsed;
        oldestAddr = addr;
      }
    }
    if (!oldestAddr) break;
    disposeSession(oldestAddr);
  }
}

// Smart terminal selection copy:
// Rejoins lines that were soft-wrapped by xterm, herdr-core attach hydration (\r\n at col N),
// or the padded/bordered/shaded code blocks of the coding agents' TUIs, while preserving
// intentional multi-line scripts, blank lines, lists, prompts, and explicit `\` continuations.
// The prompt and gutter glyphs are the core's, plus any an agent declares (TERM_COPY_*_GLYPHS in its agent.conf).
const RULE_LINE_RE = /^[\s─━═┄┅┈┉\-=_·•]+$/;
let copyReKey = null;
let copyReCache = null;

function copyRe() {
  if (copyReKey === state.agentReg) return copyReCache;
  const esc = (c) => c.replace(/[\\\]^-]/g, '\\$&');
  const extra = (field, base) => {
    const out = new Set();
    for (const a of state.agentReg.list) {
      for (const c of String((a.term && a.term[field]) || '')) {
        if (!base.includes(c) && !/\s/.test(c)) out.add(c);
      }
    }
    return Array.from(out).map(esc).join('');
  };
  const xp = extra('copy_prompt_glyphs', '❯');
  const xg = extra('copy_gutter_glyphs', '│┃║▕▎▏');
  copyReCache = {
    prompt: new RegExp(`^(?:[-*+•]\\s|\\d+[.)]\\s|#{1,6}\\s|>\\s|\\$\\s|[❯${xp}]\\s|>>>\\s)`),
    promptStart: new RegExp(`^(?:\\$|[❯${xp}]|#)\\s`),
    rightBorder: new RegExp(`[│┃║▕${xg}]`),
    leftGutter: new RegExp(`^(\\s*[│┃║▎▏${xg}]\\s?)`),
    rightGutter: new RegExp(`(\\s?[│┃║▕${xg}]\\s*)$`),
  };
  copyReKey = state.agentReg;
  return copyReCache;
}

function countLeadSpaces(s) {
  let n = 0;
  while (n < s.length && s[n] === ' ') n++;
  return n;
}

function detectRowVisualRight(line, cols, contentEndCol) {
  if (!line) return cols;
  const full = line.translateToString(false);
  // 1. Right-side box border (│ ┃ ║ ▕) at or past content end
  for (let c = Math.max(20, contentEndCol - 1); c < full.length; c++) {
    if (copyRe().rightBorder.test(full[c])) {
      return Math.max(20, c - 1);
    }
  }
  // 2. Shaded code-box background ending cleanly before terminal edge
  if (typeof line.getCell === 'function' && contentEndCol >= 20) {
    try {
      const sampleCell = line.getCell(Math.max(0, contentEndCol - 1));
      if (sampleCell && typeof sampleCell.isBgDefault === 'function' && !sampleCell.isBgDefault()) {
        let bgEnd = contentEndCol;
        for (let c = cols - 1; c >= contentEndCol; c--) {
          const cell = line.getCell(c);
          if (cell && !cell.isBgDefault()) {
            bgEnd = c + 1;
            break;
          }
        }
        if (bgEnd >= 40 && bgEnd < cols - 1) return bgEnd;
      }
    } catch (_) {}
  }
  return cols;
}

function detectNearbyTuiWrapCol(buf, startY, endY, cols) {
  const lo = Math.max(0, startY - 12);
  const hi = Math.min(buf.length - 1, endY + 12);
  const lens = [];
  let maxLen = 0;
  for (let y = lo; y <= hi; y++) {
    const ln = buf.getLine(y);
    if (!ln) continue;
    const t = ln.translateToString(true);
    if (!t || RULE_LINE_RE.test(t)) continue;
    lens.push(t.length);
    if (t.length > maxLen) maxLen = t.length;
  }
  if (maxLen >= 50 && maxLen < cols - 12) {
    const nearMax = lens.filter((n) => n >= maxLen - 4).length;
    if (nearMax >= 3) return maxLen + 1;
  }
  return cols;
}

export function looksLikeMidTokenWrap(curText, nextCore) {
  if (!curText || !nextCore) return false;
  if (/\s$/.test(curText)) return false;
  // Don't glue onto explicit flags or shell operators
  if (/^(?:--?[A-Za-z0-9]|\||&&|\|\||;|>|>>|<)/.test(nextCore)) return false;
  // Ends with path/assignment/punctuation continuation (but not " -" or " --")
  if (/(?:\/|:=|=|:|_|@)$/.test(curText)) return true;
  if (/(?<!\s)-$/.test(curText)) return true;
  // Long unbroken URL / path / identifier reaching right to the wrap edge
  const lastTok = (curText.match(/\S+$/) || [''])[0];
  if ((/(?:https?:\/\/|\/[^\s/]+\/)/.test(lastTok) || lastTok.length >= 22) && /^[A-Za-z0-9._/~:?#&=+-]/.test(nextCore)) {
    return true;
  }
  return false;
}

export function getSmartSelection(termObj) {
  const fallback = termObj.getSelection();
  if (!fallback || !fallback.includes('\n')) return fallback;
  const pos = typeof termObj.getSelectionPosition === 'function' ? termObj.getSelectionPosition() : null;
  const buf = termObj.buffer && termObj.buffer.active;
  if (!pos || !buf) return fallback;

  let s = pos.start;
  let e = pos.end;
  if (s.y > e.y || (s.y === e.y && s.x > e.x)) {
    const tmp = s; s = e; e = tmp;
  }
  let endY = e.y;
  let endX = e.x;
  if (endY > s.y && endX === 0) {
    endY -= 1;
    endX = termObj.cols;
  }
  if (s.y >= endY) return fallback;

  const cols = termObj.cols || 80;
  const rows = [];
  for (let y = s.y; y <= endY; y++) {
    const line = buf.getLine(y);
    if (!line) continue;
    const full = line.translateToString(false);
    const fullTrimLen = line.translateToString(true).length;
    const x0 = y === s.y ? s.x : 0;
    const x1 = y === endY ? Math.min(endX, full.length) : full.length;
    const rawSlice = full.slice(x0, x1);
    const trimmedSlice = rawSlice.replace(/\s+$/, '');
    const contentEndCol = x0 + trimmedSlice.length;
    const visualRightCol = detectRowVisualRight(line, cols, contentEndCol);
    rows.push({
      y,
      isWrapped: Boolean(line.isWrapped),
      x0,
      x1,
      rawSlice,
      trimmedSlice,
      contentEndCol,
      visualRightCol,
      fullTrimLen,
      indent: x0 + countLeadSpaces(rawSlice),
    });
  }
  if (rows.length < 2) return fallback;

  // If every non-empty selected row starts with a uniform Unicode box border (│/┃/║/▎/▏), strip the box gutter
  const nonEmpty = rows.filter((r) => r.trimmedSlice.length > 0);
  if (nonEmpty.length >= 2 && nonEmpty.every((r) => copyRe().leftGutter.test(r.trimmedSlice))) {
    const allRightBar = nonEmpty.every((r) => copyRe().rightGutter.test(r.trimmedSlice));
    for (const r of rows) {
      const m = r.rawSlice.match(copyRe().leftGutter);
      if (m) {
        r.x0 += m[1].length;
        r.rawSlice = r.rawSlice.slice(m[1].length);
      }
      if (allRightBar) {
        r.rawSlice = r.rawSlice.replace(copyRe().rightGutter, '');
        r.visualRightCol = Math.max(20, r.x0 + r.rawSlice.length);
      }
      r.trimmedSlice = r.rawSlice.replace(/\s+$/, '');
      r.contentEndCol = r.x0 + r.trimmedSlice.length;
      r.indent = r.x0 + countLeadSpaces(r.rawSlice);
    }
  }

  const nearbyWrapCol = detectNearbyTuiWrapCol(buf, s.y, endY, cols);
  let blockMaxEnd = 0;
  for (const r of rows) {
    if (r.contentEndCol > blockMaxEnd) blockMaxEnd = r.contentEndCol;
  }

  const out = [];
  let current = rows[0].isWrapped ? rows[0].rawSlice : rows[0].trimmedSlice;
  let curRow = rows[0];

  for (let i = 1; i < rows.length; i++) {
    const next = rows[i];
    const curText = curRow.trimmedSlice;
    const nextText = next.trimmedSlice;
    const nextCore = nextText.trimStart();

    // 1. Native xterm.js soft-wrap
    if (next.isWrapped) {
      // Preserve spaces up to terminal edge on wrapped previous row
      if (curRow.x1 >= cols && curRow.rawSlice.length > curRow.trimmedSlice.length) {
        current += curRow.rawSlice.slice(curRow.trimmedSlice.length);
      }
      current += next.rawSlice.replace(/\s+$/, '');
      curRow = next;
      continue;
    }

    // 2. Full-width terminal wrap (e.g. herdr-core hydration emitting \r\n at column `cols`)
    if (
      curRow.x1 >= cols &&
      curRow.fullTrimLen >= cols - 1 &&
      next.x0 === 0 &&
      curText.length > 0 &&
      nextText.length > 0 &&
      !RULE_LINE_RE.test(curText) &&
      !RULE_LINE_RE.test(nextText)
    ) {
      if (curRow.fullTrimLen === cols) {
        current += next.rawSlice.replace(/\s+$/, '');
      } else {
        // Trailing space fell on column `cols - 1` before \r\n
        const nextStartsSpace = /^\s/.test(next.rawSlice);
        current += (nextStartsSpace ? '' : ' ') + next.rawSlice.replace(/\s+$/, '');
      }
      curRow = next;
      continue;
    }

    // 3. AI TUI padded / bordered / shaded soft-wrap (the coding agents)
    const boxRight = Math.min(curRow.visualRightCol, nearbyWrapCol);
    const effectiveWrap =
      blockMaxEnd >= boxRight - 8 && blockMaxEnd < boxRight
        ? Math.min(boxRight, Math.max(blockMaxEnd + 1, boxRight - 6))
        : Math.max(40, boxRight - 2);

    const curStartsPrompt = copyRe().promptStart.test(curText.trimStart());
    const sameIndent = Math.abs(next.indent - curRow.indent) <= 2 || (curStartsPrompt && next.indent <= curRow.indent + 4);
    const nextFirstToken = (nextCore.match(/^\S+/) || [''])[0];
    const endsHardBreak = /(?:\\|;|{|})$/.test(curText) && curRow.contentEndCol < effectiveWrap - 1;

    const tuiWrapped =
      curText.length > 0 &&
      nextCore.length > 0 &&
      !RULE_LINE_RE.test(curText) &&
      !RULE_LINE_RE.test(nextCore) &&
      sameIndent &&
      !copyRe().prompt.test(nextCore) &&
      !endsHardBreak &&
      curRow.contentEndCol >= 36 &&
      (curRow.contentEndCol + 1 + nextFirstToken.length) > effectiveWrap;

    if (tuiWrapped) {
      const hitEdge = curRow.contentEndCol >= effectiveWrap - 1;
      const joiner = hitEdge && looksLikeMidTokenWrap(curText, nextCore) ? '' : ' ';
      current += joiner + nextCore;
      curRow = next;
      continue;
    }

    out.push(current);
    current = next.trimmedSlice;
    curRow = next;
  }
  out.push(current);
  return out.join('\n');
}

function copyTextSilently(text) {
  if (!text) return;
  if (navigator.clipboard?.writeText) {
    navigator.clipboard.writeText(text).catch(() => {});
    return;
  }
  const ta = document.createElement('textarea');
  ta.value = text;
  ta.style.position = 'fixed';
  ta.style.opacity = '0';
  document.body.appendChild(ta);
  ta.select();
  try { document.execCommand('copy'); } catch (_) {}
  document.body.removeChild(ta);
}

async function readClipboardImagesViaApi() {
  if (!navigator.clipboard?.read) return [];
  try {
    const items = await navigator.clipboard.read();
    const blobs = [];
    for (const it of items) {
      const imgType = it.types.find((t) => t.startsWith('image/'));
      if (imgType) blobs.push(await it.getType(imgType));
    }
    return blobs;
  } catch (_) {
    return [];
  }
}

export function createTabSession(address) {
  evictOldestSessionIfNeeded();
  const paneEl = document.createElement('div');
  paneEl.className = 'term-pane hydrating';
  paneEl.dataset.addr = address;
  dom.terminalHostEl.appendChild(paneEl);

  const term = new window.Terminal({
    fontFamily: "'JetBrains Mono', 'SwarmBox Symbols', 'PureNerdFont', ui-monospace, SFMono-Regular, Menlo, Consolas, monospace",
    fontSize: computeFontSize(),
    lineHeight: computeLineHeight(),
    fontWeight: '400',
    fontWeightBold: '600',
    customGlyphs: true,
    cursorStyle: state.cursorStyle,
    cursorBlink: state.cursorBlink,
    scrollback: state.scrollbackLines,
    macOptionIsMeta: true,
    allowProposedApi: true,
    theme: (THEMES[state.currentThemeKey] || THEMES[DEFAULT_THEME]).xterm,
    linkHandler: {
      allowNonHttpProtocols: true,
      activate: (event, uri) => {
        if (/^file:\/\//i.test(uri)) {
          if (event) event.preventDefault();
          const newTab = Boolean(event && (event.button === 1 || event.ctrlKey || event.metaKey));
          openFilePreview(uri, { cwd: terminalCwdFor(address), newTab });
          return;
        }
        if (/^https?:\/\//i.test(uri)) {
          window.open(uri, '_blank', 'noopener,noreferrer');
        }
      },
    },
  });
  const fitAddon = new window.FitAddon.FitAddon();
  term.loadAddon(fitAddon);
  if (typeof term.registerLinkProvider === 'function' && window.PathLinks) {
    term.registerLinkProvider(createTerminalPathLinkProvider(term, address));
  }
  if (typeof term.registerLinkProvider === 'function') {
    term.registerLinkProvider(createWrappedUrlLinkProvider(term));
  }
  if (window.WebLinksAddon) {
    term.loadAddon(new window.WebLinksAddon.WebLinksAddon());
  }
  if (window.Unicode11Addon) {
    try {
      term.loadAddon(new window.Unicode11Addon.Unicode11Addon());
      term.unicode.activeVersion = '11';
    } catch (_) {}
  }
  term.open(paneEl);
  attachCanvasRenderer(term);

  const sess = {
    address,
    paneEl,
    term,
    fitAddon,
    ws: null,
    connected: false,
    hydrating: true,
    hydrationChunks: [],
    fallbackTimer: null,
    resizing: false,
    resizeSeq: 0,
    resizeAwaitingServer: false,
    resizeChunks: [],
    resizeFallbackTimer: null,
    resizeWasAtBottom: true,
    socketGen: 0,
    reconnectTimer: null,
    reconnectDelay: 400,
    pendingInput: [],
    lastCols: 0,
    lastRows: 0,
    needsFit: false,
    lastUsed: Date.now(),
  };

  // OSC 52 clipboard write support (read "?" refused for security)
  if (term.parser && term.parser.registerOscHandler) {
    term.parser.registerOscHandler(52, (data) => {
      const i = data.indexOf(';');
      const payload = i >= 0 ? data.slice(i + 1) : '';
      if (!payload || payload === '?') return true;
      try {
        const bin = atob(payload);
        const bytes = new Uint8Array(bin.length);
        for (let k = 0; k < bin.length; k++) bytes[k] = bin.charCodeAt(k);
        const text = new TextDecoder().decode(bytes);
        navigator.clipboard?.writeText(text).catch(() => {});
      } catch (_) {}
      return true;
    });
  }

  // Intercept Cmd+C / right-click Copy on the terminal so smart unwrap applies everywhere
  paneEl.addEventListener('copy', (ev) => {
    if (!term.hasSelection()) return;
    const text = getSmartSelection(term);
    if (ev.clipboardData) {
      ev.preventDefault();
      ev.stopPropagation();
      ev.clipboardData.setData('text/plain', text);
    }
  }, true);

  // Intercept image paste (Ctrl+V / Cmd+V / right-click Paste): upload binary image to container
  // and paste its path via Bracketed Paste so the agent (or the shell) attaches it.
  paneEl.addEventListener('paste', (ev) => {
    lastNativePasteTs = Date.now();
    const imgs = extractClipboardImages(ev.clipboardData);
    if (imgs.length === 0) return;
    ev.preventDefault();
    ev.stopPropagation();
    uploadAndPasteImages(imgs, sess);
  }, true);

  // Copy/paste & Alt shortcuts:
  // - Ctrl+C / Ctrl+Shift+C copies with smart wrapped-line unwrapping when text is selected.
  // - Ctrl+V lets the browser fire its native `paste` event on xterm-helper-textarea so xterm.js
  //   runs term.paste() with full Bracketed Paste (\x1b[200~ ... \x1b[201~) — and our capture
  //   paste listener above intercepts clipboard images cleanly with zero double-paste. If a browser
  //   suppresses native `paste` on <textarea> for image-only clipboards, a 70ms fallback checks
  //   navigator.clipboard.read() for images.
  // - Ctrl+Shift+V checks Clipboard API for images first, otherwise pastes text via term.paste().
  // - Cmd (macOS) works exactly like Ctrl for all of the above; Cmd+C without a selection does nothing
  //   (it never sends ^C), and Ctrl+C without a selection stays ^C.
  term.attachCustomKeyEventHandler((ev) => {
    if (ev.type !== 'keydown') return true;
    if (typeof actions.matchAltShortcut === 'function' && actions.matchAltShortcut(ev)) return false;
    const key = ev.key.toLowerCase();
    const clipMod = !ev.altKey && (ev.ctrlKey !== ev.metaKey);
    if (clipMod && key === 'c' && term.hasSelection()) {
      ev.preventDefault();
      copyTextSilently(getSmartSelection(term));
      term.clearSelection();
      return false;
    }
    if (clipMod && key === 'v') {
      if (ev.shiftKey && (navigator.clipboard?.read || navigator.clipboard?.readText)) {
        ev.preventDefault();
        (async () => {
          const blobs = await readClipboardImagesViaApi();
          if (blobs.length > 0) {
            await uploadAndPasteImages(blobs, sess);
            return;
          }
          try {
            const txt = await navigator.clipboard?.readText?.();
            if (txt) term.paste(txt);
          } catch (_) {}
        })();
      } else if (navigator.clipboard?.read) {
        const pressTs = Date.now();
        setTimeout(async () => {
          if (lastNativePasteTs >= pressTs) return;
          const blobs = await readClipboardImagesViaApi();
          if (blobs.length > 0) await uploadAndPasteImages(blobs, sess);
        }, 70);
      }
      return false;
    }
    return true;
  });

  term.onData((data) => {
    sendPtyInput(data, sess);
  });

  const onScrollMaybe = () => {
    if (state.activeId === sess.address) syncJumpLive();
  };
  // The scrollbar is an overlay: its thumb shows while you look back through history, for a moment after you
  // scroll, and while the mouse is at the right edge (to grab it); at the live bottom it is hidden. An inline-drawing
  // agent keeps scrollback, so its bar used to be always on, while one in the alternate screen has no scrollback
  // and never had one: now both rest without a bar.
  let sbLinger = 0;
  let sbEdge = false;
  let lastSbShow = false;
  const syncScrollbar = () => {
    let back = false;
    try {
      const buf = term.buffer.active;
      back = buf.type === 'normal' && buf.baseY - buf.viewportY > 0;
    } catch (_) {}
    const show = back || sbEdge || sbLinger !== 0;
    if (show !== lastSbShow) {
      lastSbShow = show;
      paneEl.classList.toggle('sb-show', show);
    }
  };
  sess.pokeScrollbar = () => {
    const buf = term.buffer.active;
    if (buf.type !== 'normal' || buf.baseY <= 0) return;
    clearTimeout(sbLinger);
    sbLinger = setTimeout(() => { sbLinger = 0; syncScrollbar(); }, 1200);
    syncScrollbar();
  };
  paneEl.addEventListener('wheel', sess.pokeScrollbar, { passive: true, capture: true });
  paneEl.addEventListener('mousemove', (e) => {
    const edge = e.clientX >= paneEl.getBoundingClientRect().right - 16;
    if (edge !== sbEdge) { sbEdge = edge; syncScrollbar(); }
  }, { passive: true });
  paneEl.addEventListener('mouseleave', () => { if (sbEdge) { sbEdge = false; syncScrollbar(); } });

  term.onScroll((ydisp) => { touchOffsetOnScroll(sess, ydisp); onScrollMaybe(); syncScrollbar(); });
  term.onRender(() => { touchOffsetOnRender(sess); if (!isTouchActive()) onScrollMaybe(); });
  term.onResize(() => clearTouchOffset(sess));
  const vp = paneEl.querySelector('.xterm-viewport');
  if (vp) vp.addEventListener('scroll', () => { if (!isTouchActive()) { onScrollMaybe(); syncScrollbar(); } }, { passive: true });

  state.tabSessions.set(address, sess);
  return sess;
}

export function finishHydration(sess, ws) {
  if (!sess || !sess.hydrating) return;
  sess.hydrating = false;
  sess.revealPending = true;
  if (sess.fallbackTimer) {
    clearTimeout(sess.fallbackTimer);
    sess.fallbackTimer = null;
  }
  const batch = sess.hydrationChunks;
  sess.hydrationChunks = [];
  const reveal = () => {
    if (ws && sess.ws !== ws) return;
    const vp = sess.paneEl.querySelector('.xterm-viewport');
    try { sess.term.scrollToBottom(); } catch (_) {}
    if (vp) vp.scrollTop = vp.scrollHeight;
    // Two rAFs guarantee xterm.js Viewport._sync() & Canvas2D finish painting BEFORE reveal
    requestAnimationFrame(() => {
      if (ws && sess.ws !== ws) return;
      try { sess.term.scrollToBottom(); } catch (_) {}
      if (vp) vp.scrollTop = vp.scrollHeight;
      requestAnimationFrame(() => {
        if (ws && sess.ws !== ws) return;
        sess.revealPending = false;
        sess.paneEl.classList.remove('hydrating');
        if (state.activeId === sess.address) {
          dom.termWrapEl.classList.remove('term-loading');
          syncStageLoader();
          syncJumpLive();
          focusTerminalIfDesktop();
        }
        dismissBoot();
      });
    });
  };
  if (batch.length > 0) {
    sess.term.write(concatChunks(batch), reveal);
  } else {
    reveal();
  }
}

export function openSessionSocket(sess, opts = {}) {
  if (!sess) return;
  if (sess.reconnectTimer) {
    clearTimeout(sess.reconnectTimer);
    sess.reconnectTimer = null;
  }
  if (sess.fallbackTimer) {
    clearTimeout(sess.fallbackTimer);
    sess.fallbackTimer = null;
  }
  const prevWs = sess.ws;
  sess.ws = null;
  if (prevWs) {
    prevWs.onclose = null;
    prevWs.onerror = null;
    try { prevWs.close(); } catch (_) {}
  }

  sess.connected = false;
  if (state.activeId === sess.address) {
    state.ptyConnected = false;
    syncConnPill();
  }

  // Keep pane invisible while server-coalesced initial history burst hydrates so users never
  // see a fast scroll-from-top-to-bottom replay on initial load, first visit, or reconnect.
  sess.hydrating = true;
  sess.hydrationChunks = [];
  sess.paneEl.classList.add('hydrating');
  if (state.activeId === sess.address) {
    dom.termWrapEl.classList.add('term-loading');
    syncStageLoader();
  }

  if (opts.reset) {
    sess.term.reset();
  }
  const gen = (sess.socketGen || 0) + 1;
  sess.socketGen = gen;

  const startAttach = () => {
    if (sess.socketGen !== gen || state.tabSessions.get(sess.address) !== sess) return;
    try { sess.term.clearTextureAtlas(); } catch (_) {}
    fitSession(sess, false);
    const initCols = sess.term.cols || 100;
    const initRows = sess.term.rows || 30;
    sess.lastCols = initCols;
    sess.lastRows = initRows;

    const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    const isReconnect = Boolean(opts.reconnect);
    const isPassive = Boolean(opts.passive);
    const isActiveFocused = state.activeId === sess.address && !isPassive;
    sess.passiveAttach = isReconnect || !isActiveFocused;
    sess.isOwner = isActiveFocused && !isReconnect;
    sess.resyncCount = 0;
    const reconnectFlag = isReconnect ? '&reconnect=1' : '';
    const focusedFlag = isActiveFocused ? '' : '&focused=0';
    const clientFlag = `&clientId=${encodeURIComponent(STUDIO_CLIENT_ID)}`;
    const wsUrl = `${proto}//${location.host}/ws/pty/${encodeURIComponent(sess.address)}?cols=${initCols}&rows=${initRows}${reconnectFlag}${focusedFlag}${clientFlag}`;
    const ws = new WebSocket(wsUrl);
    ws.binaryType = 'arraybuffer';
    sess.ws = ws;

    const finishThisHydration = () => finishHydration(sess, ws);

    // Safety fallback in case a proxy delays or drops the hydrated control message
    sess.fallbackTimer = setTimeout(finishThisHydration, 2600);

    ws.onopen = () => {
      if (sess.ws !== ws) return;
      sess.connected = true;
      sess.reconnectDelay = 400;
      if (state.activeId === sess.address) {
        state.ptyConnected = true;
        syncConnPill();
        if (isActiveFocused && !isReconnect) {
          ws.send(JSON.stringify({
            type: 'focus',
            focused: true,
            claim: true,
            cols: sess.term.cols || initCols,
            rows: sess.term.rows || initRows,
          }));
        }
      }
      // Only resize if viewport dimensions changed while the WebSocket was opening
      fitSession(sess, true);
      if (sess.pendingInput.length > 0) {
        const queued = sess.pendingInput;
        sess.pendingInput = [];
        for (const chunk of queued) {
          ws.send(JSON.stringify({ type: 'input', data: chunk }));
        }
      }
      if (!sess.hydrating && state.activeId === sess.address) focusTerminalIfDesktop();
    };

    ws.onmessage = (ev) => {
      if (sess.ws !== ws) return;
      if (ev.data instanceof ArrayBuffer) {
        const bytes = new Uint8Array(ev.data);
        if (sess.hydrating) {
          sess.hydrationChunks.push(bytes);
          return;
        }
        if (sess.resizing) {
          sess.resizeChunks.push(bytes);
          return;
        }
        sess.term.write(bytes, () => dismissBoot());
      } else if (typeof ev.data === 'string') {
        try {
          const msg = JSON.parse(ev.data);
          if (typeof msg.tui === 'boolean') {
            sess.serverTui = msg.tui;
            sess.serverFallbackMs = Number(msg.fallback_ms) || 0;
          }
          if (typeof msg.owner === 'boolean') {
            sess.isOwner = msg.owner;
            sess.passiveAttach = !msg.owner;
          }
          if (msg.type === 'hydrated') {
            if (msg.cols && msg.rows) {
              sess.serverPtyCols = Number(msg.cols);
              sess.serverPtyRows = Number(msg.rows);
            }
            finishThisHydration();
            if (msg.cols && msg.rows) {
              setTimeout(() => verifyServerPtySize(sess, Number(msg.cols), Number(msg.rows)), 30);
            }
            return;
          }
          if (msg.type === 'resizing') {
            if (!sess.hydrating) {
              sess.resizeAwaitingServer = true;
              beginResizeCycle(sess);
            }
            return;
          }
          if (msg.type === 'resized') {
            if (msg.cols && msg.rows) {
              sess.serverPtyCols = Number(msg.cols);
              sess.serverPtyRows = Number(msg.rows);
            }
            finishResizeCycle(sess, msg.seq || null);
            if (msg.cols && msg.rows) {
              setTimeout(() => verifyServerPtySize(sess, Number(msg.cols), Number(msg.rows)), 30);
            }
            return;
          }
          finishThisHydration();
          finishResizeCycle(sess);
          if (msg.type === 'error') sess.term.writeln(`\r\n\x1b[31m[error] ${msg.message}\x1b[0m`);
          if (msg.type === 'closed') {
            ws._terminalClosed = true;
            sess.term.writeln(`\r\n\x1b[2m[terminal closed]\x1b[0m`);
          }
        } catch (_) {
          finishThisHydration();
          finishResizeCycle(sess);
          sess.term.write(ev.data);
        }
        dismissBoot();
      }
    };

    ws.onerror = () => {
      if (sess.ws !== ws) return;
      finishThisHydration();
      finishResizeCycle(sess);
    };

    ws.onclose = () => {
      if (sess.ws !== ws) return;
      finishThisHydration();
      finishResizeCycle(sess);
      sess.ws = null;
      sess.connected = false;
      if (state.activeId === sess.address) {
        state.ptyConnected = false;
        syncConnPill();
      }
      if (ws._terminalClosed) return;
      // Skip background reconnects while the browser tab is hidden; visibilitychange will heal on return.
      if (document.visibilityState === 'hidden') return;
      // Auto-reconnect silently as passive (reconnect=1) so an idle window never hijacks another active client's PTY size.
      if (state.tabSessions.get(sess.address) === sess && state.terminals.some((t) => t.address === sess.address)) {
        const delay = sess.reconnectDelay;
        sess.reconnectDelay = Math.min(Math.round(sess.reconnectDelay * 1.6), 3000);
        sess.reconnectTimer = setTimeout(() => {
          sess.reconnectTimer = null;
          if (document.visibilityState === 'hidden') return;
          if (state.tabSessions.get(sess.address) === sess && !sess.ws) {
            openSessionSocket(sess, { silent: true, reset: true, reconnect: true });
          }
        }, delay);
      }
    };
  };

  if (fontsSettled) {
    startAttach();
  } else {
    fontsReadyPromise.then(startAttach);
  }
}

export function connectPty(address, opts = {}) {
  if (!address) return;
  stopTouchCoast('connectPty');
  if (!opts.passive) state.lastLocalTabSwitchMs = Date.now();

  const prevSess = activeSession();
  clearTouchOffset(prevSess);
  if (prevSess && prevSess.address !== address) {
    prevSess.paneEl.classList.remove('active');
    if (prevSess.ws && prevSess.ws.readyState === 1) {
      prevSess.ws.send(JSON.stringify({ type: 'focus', focused: false }));
    }
  }

  state.activeId = address;
  let sess = state.tabSessions.get(address);
  const isNew = !sess;
  if (!sess) {
    sess = createTabSession(address);
  }

  sess.lastUsed = Date.now();
  // Also allow explicit user-initiated tab clicks when the browser window is just gaining focus.
  if (!opts.passive) sess.passiveAttach = false;
  sess.paneEl.classList.add('active');

  if (isNew || opts.forceReconnect || !sess.ws || sess.ws.readyState === 2 || sess.ws.readyState === 3) {
    openSessionSocket(sess, { silent: Boolean(opts.silent), reset: !isNew, passive: Boolean(opts.passive) });
  } else {
    // Instant 0ms tab switch: live terminal & exact scroll position preserved!
    state.ptyConnected = sess.connected;
    syncConnPill();
    if (!sess.hydrating) {
      dom.termWrapEl.classList.remove('term-loading');
    } else {
      dom.termWrapEl.classList.add('term-loading');
    }
    const shouldClaim = !opts.passive;
    if (sess.needsFit) {
      // Pre-mask before fitAddon.fit() when we are about to resize/claim, then send ONE atomic
      // claim+size message instead of racing a resize packet against a focus(claim) packet.
      if (shouldClaim && !sess.hydrating && typeof sess.fitAddon.proposeDimensions === 'function') {
        try {
          const prop = sess.fitAddon.proposeDimensions();
          if (prop && prop.cols && prop.rows && (prop.cols !== sess.lastCols || prop.rows !== sess.lastRows)) {
            sess.resizeAwaitingServer = true;
            beginResizeCycle(sess);
          }
        } catch (_) {}
      }
      fitSession(sess, false);
      sess.lastCols = sess.term.cols;
      sess.lastRows = sess.term.rows;
    } else if (shouldClaim && !sess.hydrating && sess.serverPtyCols && (sess.serverPtyCols !== sess.term.cols || sess.serverPtyRows !== sess.term.rows)) {
      // Another device resized this PTY while the tab was cached: pre-mask at 0ms before claiming
      // so the stale-column buffer never flashes before the server's resizing frame arrives.
      sess.resizeAwaitingServer = true;
      beginResizeCycle(sess);
    }
    syncStageLoader();
    if (shouldClaim) {
      claimSessionViewport(sess);
    }
    syncJumpLive();
    focusTerminalIfDesktop();
  }

  if (typeof actions.renderTabs === 'function') actions.renderTabs(true);
}

export const selectTab = connectPty;

let terminalListenersBound = false;

export function initTerminal() {
  if (terminalListenersBound || typeof window === 'undefined' || typeof document === 'undefined') return;
  terminalListenersBound = true;

  if (dom.btnJumpLive) {
    dom.btnJumpLive.addEventListener('click', () => {
      const sess = activeSession();
      if (!sess) return;
      stopTouchCoast('jumpLive');
      clearTouchOffset(sess);
      sess.term.scrollToBottom();
      const vp = sess.paneEl.querySelector('.xterm-viewport');
      if (vp) vp.scrollTop = vp.scrollHeight;
      syncJumpLive();
      focusTerminalIfDesktop();
    });
  }

  if (typeof ResizeObserver === 'function' && dom.termWrapEl) {
    const ro = new ResizeObserver(scheduleFit);
    ro.observe(dom.termWrapEl);
  }
  window.addEventListener('resize', scheduleFit);

  if (window.visualViewport) {
    window.visualViewport.addEventListener('resize', () => syncViewport(false));
    window.visualViewport.addEventListener('scroll', () => syncViewport(true));
    syncViewport(false);
  }

  document.addEventListener('pointerdown', onUserChannelActivity, { capture: true, passive: true });
  document.addEventListener('keydown', onUserChannelActivity, { capture: true, passive: true });
  document.addEventListener('wheel', onUserChannelActivity, { capture: true, passive: true });

  // Clicking anywhere on the terminal canvas (without a drag selection) restores keyboard focus
  // and recovers a dropped PTY socket immediately.
  if (dom.termWrapEl) {
    dom.termWrapEl.addEventListener('mouseup', () => {
      if (state.settingsOpen) return;
      const sess = activeSession();
      if (!sess || window.innerWidth <= 860) return;
      if (sess.term.hasSelection() || (window.getSelection && window.getSelection().toString())) return;
      sess.term.focus();
      if (!sess.ws || sess.ws.readyState === 2 || sess.ws.readyState === 3) {
        openSessionSocket(sess, { silent: true, reset: true });
      }
    });

    // Drag & drop images directly onto the terminal canvas
    let dragDepth = 0;
    dom.termWrapEl.addEventListener('dragenter', (e) => {
      if (!hasDraggedFiles(e)) return;
      e.preventDefault();
      dragDepth += 1;
      if (dom.termDropOverlayEl) dom.termDropOverlayEl.classList.add('visible');
    });
    dom.termWrapEl.addEventListener('dragover', (e) => {
      if (!hasDraggedFiles(e)) return;
      e.preventDefault();
      if (e.dataTransfer) e.dataTransfer.dropEffect = 'copy';
    });
    dom.termWrapEl.addEventListener('dragleave', (e) => {
      if (!hasDraggedFiles(e)) return;
      dragDepth = Math.max(0, dragDepth - 1);
      if (dragDepth === 0 && dom.termDropOverlayEl) dom.termDropOverlayEl.classList.remove('visible');
    });
    dom.termWrapEl.addEventListener('drop', (e) => {
      dragDepth = 0;
      if (dom.termDropOverlayEl) dom.termDropOverlayEl.classList.remove('visible');
      const imgs = extractClipboardImages(e.dataTransfer);
      if (imgs.length === 0) return;
      e.preventDefault();
      e.stopPropagation();
      uploadAndPasteImages(imgs, activeSession());
    });
  }

  // Fallback paste listener when focus slipped to document.body while pasting a screenshot
  document.addEventListener('paste', (e) => {
    lastNativePasteTs = Date.now();
    if (state.settingsOpen || isRealFormField(e.target)) return;
    const imgs = extractClipboardImages(e.clipboardData);
    if (imgs.length === 0) return;
    e.preventDefault();
    e.stopPropagation();
    uploadAndPasteImages(imgs, activeSession());
  });

  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') {
      ensureConnectionsAlive();
    } else {
      const sess = activeSession();
      if (sess && sess.ws && sess.ws.readyState === 1) {
        sess.ws.send(JSON.stringify({ type: 'focus', focused: false }));
      }
    }
  });
  window.addEventListener('focus', () => {
    ensureConnectionsAlive();
  });
  window.addEventListener('blur', () => {
    const sess = activeSession();
    if (sess && sess.ws && sess.ws.readyState === 1) {
      sess.ws.send(JSON.stringify({ type: 'focus', focused: false }));
    }
  });
  window.addEventListener('online', () => {
    if (document.visibilityState === 'visible') ensureConnectionsAlive();
  });
}
