// Web Studio composition root: wires all ES modules under ./app/, layout controls, shortcuts, gestures, and events WebSocket.

import {
  STUDIO_CLIENT_ID,
  dom,
  state,
  registerActions,
  activeSession,
  syncConnPill,
  dismissBoot,
  refreshAgentRegistry,
} from './app/state.js';
import {
  THEMES,
  THEME_KEYS,
  savedTheme,
  adjustFontOffset,
  applyTheme,
} from './app/themes.js';
import {
  showTermToast,
  onOpenUrlEvent,
  startInlineRename,
  closeCardMenu,
  initUiChrome,
  closePopover,
} from './app/ui-chrome.js';
import {
  getFileViewer,
  closeFileDrawer,
  initFilePreview,
  terminalCwdFor,
  openFilePreview,
  openFileDrawerInline,
  openLogInDrawer,
  openDiffInDrawer,
} from './app/file-preview.js';
import { attachTouchScroll } from './app/touch-scroll.js';
import {
  syncJumpLive,
  syncStageLoader,
  beginResizeCycle,
  fitAndResize,
  scheduleFit,
  syncMobileKeys,
  syncViewport,
  focusTerminalIfDesktop,
  sendPtyInput,
  disposeSession,
  connectPty,
  initTerminal,
} from './app/terminal.js';
import { openNewAgentPopover } from './app/new-agent.js';
import {
  openCollisionPopover,
  openWorktreePopover,
  openPendingWorktreesPopover,
} from './app/worktrees.js';
import { initTabs, renderTabs } from './app/tabs.js';
import {
  getLastCtxTabsKey,
  ctxSessionFor,
  ctxRepoForGroup,
  makeNewAgentCtxRow,
  ctxSessionWhy,
  makeCtxChip,
  renderTopbarCtx,
  makeRepoCtxPill,
  initSysopContext,
} from './app/sysop-context.js';
import {
  setSysopView,
  showSysopEvents,
  initSysopEvents,
} from './app/sysop-events.js';
import {
  getKnownTab,
  rememberTabs,
  tabChip,
  onSysopEvents,
  stopSysop,
  renderSysop,
  showVoiceNote,
  clearOpenTurnActions,
  initSysopChat,
} from './app/sysop-chat.js';
import { initVoice } from './app/voice.js';
import {
  openSettings,
  closeSettings,
  toggleSettings,
  initSettings,
} from './app/settings.js';

const {
  appEl,
  sidebarPendingWtEl,
  btnNewAgent,
  topbarWtBtnEl,
  mobileWtBtnEl,
  popoverBackdropEl,
  popoverEl,
  mobileSwitcherBtn,
  sessionsSheetEl,
  sessionsSheetHandleEl,
  sessionsSheetHeadEl,
  sessionsFilterBarEl,
  btnSessionsClose,
  btnMobileNewAgent,
  btnMobileNewShell,
  mobileSysopBtn,
  btnMobileKeys,
  btnSheetSend,
  btnToggleSysop,
  sysopFeedEl,
  btnSysopStop,
  btnSysopNew,
  btnMobileLiveStop,
  btnMobileDockStop,
  goalInputEl,
  termWrapEl,
  composerEl,
  sheetBackdropEl,
  sheetHandleEl,
  sysopPanelEl,
  btnSendGoal,
  touchKeysEl,
} = dom;

// ---- Global Keyboard Shortcuts --------------------------------------------------------------
function matchAltShortcut(e) {
  if (!e || !e.altKey || e.ctrlKey || e.metaKey) return null;
  const code = e.code || '';
  const key = e.key || '';
  const low = key.toLowerCase();

  if (/^Digit[1-9]$/.test(code)) return { action: 'tab', idx: Number(code.slice(5)) - 1 };
  if (/^Numpad[1-9]$/.test(code)) return { action: 'tab', idx: Number(code.slice(6)) - 1 };
  if (key >= '1' && key <= '9') return { action: 'tab', idx: Number(key) - 1 };

  if (code === 'KeyN' || low === 'n') return { action: 'new-shell' };
  if (code === 'KeyA' || low === 'a') return { action: 'new-agent' };
  if (code === 'KeyR' || low === 'r') return { action: 'rename' };
  if (code === 'KeyS' || low === 's') return { action: 'sysop' };
  if (code === 'KeyB' || low === 'b') return { action: 'sidebar' };
  if (code === 'KeyG' || low === 'g') return { action: 'goal' };
  if (code === 'KeyT' || low === 't') return { action: 'theme' };
  if (code === 'Comma' || key === ',') return { action: 'settings' };
  if (code === 'Equal' || code === 'NumpadAdd' || key === '=' || key === '+') return { action: 'font', delta: 1 };
  if (code === 'Minus' || code === 'NumpadSubtract' || key === '-' || key === '_') return { action: 'font', delta: -1 };
  if (code === 'Digit0' || code === 'Numpad0' || key === '0') return { action: 'font', delta: 0 };
  return null;
}

function runAltShortcut(sc) {
  if (!sc) return;
  if (sc.action === 'settings') { toggleSettings(); return; }
  if (state.settingsOpen) return;
  if (sc.action === 'tab') {
    if (state.terminals[sc.idx]) {
      if (state.activeId !== state.terminals[sc.idx].address) connectPty(state.terminals[sc.idx].address);
      else focusTerminalIfDesktop();
    }
    return;
  }
  if (sc.action === 'new-shell') { spawnTab('shell'); return; }
  if (sc.action === 'new-agent') { openNewAgentPopover(false, '', { showProjectPicker: true }); return; }
  if (sc.action === 'rename') { if (state.activeId) startInlineRename(state.activeId); return; }
  if (sc.action === 'sysop') { toggleDesktopSysop(); return; }
  if (sc.action === 'sidebar') { toggleSidebar(); return; }
  if (sc.action === 'goal') {
    if (window.innerWidth > 860 && appEl.dataset.sysopOpen !== '1') toggleDesktopSysop();
    else if (window.innerWidth <= 860) setMobileSysop(true);
    goalInputEl.focus();
    return;
  }
  if (sc.action === 'theme') {
    const idx = THEME_KEYS.indexOf(state.currentThemeKey);
    applyTheme(THEME_KEYS[(idx + 1) % THEME_KEYS.length], true);
    focusTerminalIfDesktop();
    return;
  }
  if (sc.action === 'font') {
    adjustFontOffset(sc.delta);
  }
}

function isRealFormField(el) {
  if (!el || !el.tagName) return false;
  if (el.tagName === 'TEXTAREA') return !el.classList?.contains('xterm-helper-textarea');
  return el.tagName === 'INPUT' || el.tagName === 'SELECT';
}

window.addEventListener('keydown', (e) => {
  if (state.fileDrawerOpen) {
    if (e.key === 'Escape') {
      e.preventDefault();
      e.stopPropagation();
      closeFileDrawer();
      return;
    }
    const viewer = getFileViewer();
    if (viewer) viewer.handleKey(e);
    return;
  }
  if (state.popoverOpen) {
    if (e.key === 'Escape') {
      e.preventDefault();
      e.stopPropagation();
      closePopover();
      return;
    }
    if (state.popoverKeyHandler && state.popoverKeyHandler(e) === true) {
      return;
    }
    return;
  }
  if (state.settingsOpen) {
    if (e.key === 'Escape') {
      e.preventDefault();
      e.stopPropagation();
      closeSettings();
      return;
    }
    if (e.altKey && !e.ctrlKey && !e.metaKey) {
      const sc = matchAltShortcut(e);
      if (sc && sc.action === 'settings') {
        e.preventDefault();
        e.stopPropagation();
        closeSettings();
      }
    }
    return;
  }

  const inUiField = isRealFormField(e.target);
  if (e.altKey && !e.ctrlKey && !e.metaKey) {
    if (inUiField) return;
    const sc = matchAltShortcut(e);
    if (sc) {
      e.preventDefault();
      e.stopPropagation();
      runAltShortcut(sc);
    }
    return;
  }

  // Gentle focus-rescue on desktop: if focus slipped to document.body (e.g. clicked empty chrome),
  // rescue regular typing straight back into the terminal without losing the keystroke.
  if (window.innerWidth > 860 && !inUiField && !e.metaKey && !e.altKey && document.activeElement === document.body) {
    if (e.ctrlKey && (e.key.toLowerCase() === 'c' || e.key.toLowerCase() === 'v')) return;
    if (e.key.length === 1 || e.key === 'Enter' || e.key === 'Backspace') {
      const sess = activeSession();
      if (sess) sess.term.focus();
    }
  }
}, true);

// ---- Gateway Events WebSocket & Core Actions ------------------------------------------------
function connectEvents() {
  if (state.eventsWs && (state.eventsWs.readyState === 0 || state.eventsWs.readyState === 1)) return;
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  const ws = new WebSocket(`${proto}//${location.host}/ws/events?clientId=${encodeURIComponent(STUDIO_CLIENT_ID)}`);
  state.eventsWs = ws;

  ws.onopen = () => {
    if (state.eventsWs !== ws) return;
    state.eventsConnected = true;
    syncConnPill();
  };
  ws.onclose = () => {
    if (state.eventsWs !== ws) return;
    state.eventsWs = null;
    state.eventsConnected = false;
    syncConnPill();
    setTimeout(connectEvents, 1200);
  };
  ws.onmessage = (ev) => {
    if (state.eventsWs !== ws) return;
    let msg;
    try { msg = JSON.parse(ev.data); } catch (_) { return; }
    if (msg && msg.type === 'sysop_events') { onSysopEvents(msg); return; }
    if (msg && msg.type === 'open_url') { onOpenUrlEvent(msg.url); return; }
    if (msg.theme && THEMES[msg.theme] && msg.theme !== state.currentThemeKey) {
      applyTheme(msg.theme, false);
    }
    if (Array.isArray(msg.pins)) state.pins = msg.pins;
    if (Array.isArray(msg.worktrees)) state.pendingWorktrees = msg.worktrees;
    if (msg.repo_statuses && typeof msg.repo_statuses === 'object') state.repoStatuses = msg.repo_statuses;
    if (msg.worktree_prefs && typeof msg.worktree_prefs === 'object') state.worktreePrefs = msg.worktree_prefs;
    if (msg.session_prefs && typeof msg.session_prefs === 'object') state.sessionPrefs = msg.session_prefs;
    if (Array.isArray(msg.installed_agents)) {
      state.installedAgents = msg.installed_agents;
      // an agent addon installed since the page loaded: fetch the registry again (its name, colour, icon)
      if (state.installedAgents.some((a) => a && a.id && !state.agentReg.byId.has(a.id))) {
        refreshAgentRegistry().then(() => renderTabs(true));
      }
    }
    if (typeof msg.home === 'string' && msg.home) state.serverHomeDir = msg.home;
    if (Array.isArray(msg.terminals)) {
      state.terminals = msg.terminals;
      rememberTabs();
      const liveAddrs = new Set(state.terminals.map((t) => t.address));
      for (const addr of Array.from(state.tabSessions.keys())) {
        if (!liveAddrs.has(addr)) disposeSession(addr);
      }
      if (!state.activeId || !liveAddrs.has(state.activeId)) {
        const preferred = msg.active && liveAddrs.has(msg.active)
          ? msg.active
          : (state.terminals[0] && state.terminals[0].address);
        if (preferred) connectPty(preferred, { passive: document.visibilityState === 'hidden' });
        else { state.activeId = null; state.ptyConnected = false; syncConnPill(); renderTabs(); dismissBoot(); }
      } else {
        // If events reconnected after a brief blip and the active PTY socket died, heal it automatically
        const sess = activeSession();
        if (!sess || !sess.ws || sess.ws.readyState === 2 || sess.ws.readyState === 3) {
          connectPty(state.activeId, { silent: true, forceReconnect: true });
        } else {
          renderTabs();
        }
      }
    }
    // The active tab moved elsewhere (the Sysop's focus_tab, the cockpit, another browser): follow it. Only a CHANGE of the server's
    // active tab counts, so a snapshot sent before this browser's own click (still naming the old tab) never pulls it back.
    if (typeof msg.active === 'string' && msg.active) {
      const changed = state.lastServerActive !== null && msg.active !== state.lastServerActive;
      state.lastServerActive = msg.active;
      const recentlySwitchedLocally = (Date.now() - state.lastLocalTabSwitchMs) < 1200;
      if (changed && !recentlySwitchedLocally && msg.active !== state.activeId && state.terminals.some((t) => t.address === msg.active)) {
        connectPty(msg.active, { passive: true });
      }
    }
    if (msg.sysop) renderSysop(msg.sysop);
  };
}

async function spawnTab(preset, opts = {}) {
  const payload = { preset };
  if (opts.cwd) {
    payload.cwd = opts.cwd;
  } else if (preset === 'agent') {
    const cur = state.terminals.find((t) => t.address === state.activeId);
    const curCwd = (cur && cur.foreground && cur.foreground.cwd) || (cur && cur.cwd) || '';
    if (curCwd && curCwd.startsWith('/')) payload.cwd = curCwd;
  }
  if (opts.agent) payload.agent = opts.agent;
  if (opts.worktree_choice) payload.worktree_choice = opts.worktree_choice;
  if (opts.context === false) payload.context = false;

  const r = await fetch('/api/tabs', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  const data = await r.json().catch(() => ({}));
  if (r.status === 409 && data.error === 'worktree_collision') {
    openCollisionPopover({
      kind: 'tab',
      preset,
      agent: data.agent || opts.agent,
      cwd: data.cwd || payload.cwd,
      collision: data.collision,
      context: payload.context,
    });
    return;
  }
  const addr = (data && data.terminal && data.terminal.address) || (data && data.address);
  if (addr) setTimeout(() => connectPty(addr), 100);
  if (data && data.worktree) {
    const note = data.worktree.uncommitted_in_source ? ' (uncommitted edits stayed in source folder)' : '';
    showTermToast(`Isolated in worktree ${data.worktree.branch}${note}`);
  }
}

async function sendGoal(text) {
  const goal = (text !== undefined ? text : goalInputEl.value).trim();
  if (!goal) return;
  if (text === undefined) goalInputEl.value = '';
  setSysopView('chat');
  showSysopReplyOnMobile();
  const r = await fetch('/api/sysop/goal', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ goal, terminal: state.activeId }),
  });
  if (!r.ok) {
    const data = await r.json().catch(() => ({}));
    showVoiceNote(data.message || 'Could not send goal to Sysop.', 'error', 6000);
  }
}

async function handleApproval(decision) {
  if (!state.currentApproval) return;
  const route = decision === 'allow' ? '/api/sysop/approve' : '/api/sysop/veto';
  await fetch(route, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });
}

// ---- Layout Controls ----------------------------------------------------------------------
// Responsive default: keep Sysop closed on narrower desktop/laptop widths (< 1360px) so the
// terminal gets full room; open automatically on wide screens unless user manually toggled it.
// Persist explicit desktop panel visibility across reloads so refresh keeps exact PTY width.
const SYSOP_WIDE_PX = 1360;
const SIDEBAR_OPEN_KEY = 'swarmbox-herdr-sidebar-open';
const SYSOP_OPEN_KEY = 'swarmbox-herdr-sysop-open';
let sysopUserToggled = false;

(() => {
  try {
    const savedSb = localStorage.getItem(SIDEBAR_OPEN_KEY);
    if (savedSb === '0' || savedSb === '1') {
      appEl.dataset.sidebarOpen = savedSb;
    }
    const savedSys = localStorage.getItem(SYSOP_OPEN_KEY);
    if (savedSys === '0' || savedSys === '1') {
      sysopUserToggled = true;
      appEl.dataset.sysopOpen = savedSys;
      if (btnToggleSysop) btnToggleSysop.dataset.on = savedSys;
    }
  } catch (_) {}
})();

function applyResponsiveSysopDefault() {
  if (sysopUserToggled || window.innerWidth <= 860) return;
  const want = window.innerWidth >= SYSOP_WIDE_PX ? '1' : '0';
  if (appEl.dataset.sysopOpen !== want) {
    appEl.dataset.sysopOpen = want;
    btnToggleSysop.dataset.on = want;
  }
}
applyResponsiveSysopDefault();
window.addEventListener('resize', () => {
  const before = appEl.dataset.sysopOpen;
  applyResponsiveSysopDefault();
  if (appEl.dataset.sysopOpen !== before) scheduleFit();
});

function applyDesktopPanelToggle(applyDomChange) {
  const active = activeSession();
  const canMask = Boolean(
    active &&
    !active.hydrating &&
    window.innerWidth > 860 &&
    active.ws &&
    active.ws.readyState === 1
  );
  if (canMask) {
    // Instant 0ms SwarmBox stage loader BEFORE changing grid columns so zero stale-width frames paint
    beginResizeCycle(active);
  }
  applyDomChange();
  if (canMask) {
    // Synchronously lay out & dispatch resize on the exact same click tick (zero 1-frame gap)
    void termWrapEl.offsetWidth;
    fitAndResize();
  } else {
    scheduleFit();
  }
  requestAnimationFrame(focusTerminalIfDesktop);
}

function setDesktopSidebar(open) {
  const next = open ? '1' : '0';
  if (appEl.dataset.sidebarOpen === next) {
    requestAnimationFrame(focusTerminalIfDesktop);
    return;
  }
  try { localStorage.setItem(SIDEBAR_OPEN_KEY, next); } catch (_) {}
  applyDesktopPanelToggle(() => {
    appEl.dataset.sidebarOpen = next;
  });
}

function toggleSidebar() {
  setDesktopSidebar(appEl.dataset.sidebarOpen !== '1');
}

function setDesktopSysop(open) {
  sysopUserToggled = true;
  const next = open ? '1' : '0';
  if (appEl.dataset.sysopOpen === next) {
    requestAnimationFrame(focusTerminalIfDesktop);
    return;
  }
  try { localStorage.setItem(SYSOP_OPEN_KEY, next); } catch (_) {}
  applyDesktopPanelToggle(() => {
    appEl.dataset.sysopOpen = next;
    btnToggleSysop.dataset.on = next;
  });
}

function toggleDesktopSysop() {
  setDesktopSysop(appEl.dataset.sysopOpen !== '1');
}

function setMobileSessions(open) {
  const val = open ? '1' : '0';
  if (open && appEl.dataset.mobileSysop === '1') setMobileSysop(false);
  if (!open) closeCardMenu();
  appEl.dataset.mobileSessions = val;
  if (mobileSwitcherBtn) mobileSwitcherBtn.setAttribute('aria-expanded', open ? 'true' : 'false');
  if (sessionsSheetEl) sessionsSheetEl.setAttribute('aria-hidden', open ? 'false' : 'true');
}

function setMobileSysop(open) {
  const val = open ? '1' : '0';
  if (open && appEl.dataset.mobileSessions === '1') setMobileSessions(false);
  appEl.dataset.mobileSysop = val;
  if (mobileSysopBtn) mobileSysopBtn.dataset.on = val;
  if (!open && document.activeElement === goalInputEl) goalInputEl.blur();
  syncMobileKeys();
  if (open) requestAnimationFrame(() => { sysopFeedEl.scrollTop = sysopFeedEl.scrollHeight; });
  requestAnimationFrame(scheduleFit);
}

// Mobile V5: Terminal dock keeps [Sysop ⌃] + [Speak] (unmistakably Sysop, never confused with the
// active agent prompt); pulling Sysop up covers the dock to bottom: 0 with a WhatsApp-style composer.
const mobileMq = window.matchMedia('(max-width: 860px)');
function isMobileLayout() { return mobileMq.matches; }
function autosizeGoalInput() {
  if (!isMobileLayout()) { goalInputEl.style.height = ''; return; }
  goalInputEl.style.height = 'auto';
  goalInputEl.style.height = `${Math.min(goalInputEl.scrollHeight, 108)}px`;
}
function syncComposerLayout() {
  goalInputEl.rows = isMobileLayout() ? 1 : 2;
  autosizeGoalInput();
  syncMobileKeys();
}
// On mobile a goal sent by text or voice opens the sheet in full; the keyboard drops.
function showSysopReplyOnMobile() {
  if (!isMobileLayout()) return;
  if (document.activeElement === goalInputEl) goalInputEl.blur();
  setMobileSysop(true);
}

// ---- Register Cross-Module Actions (strict DAG wiring) -------------------------------------
registerActions({
  closeFileDrawer,
  connectEvents,
  connectPty,
  ctxRepoForGroup,
  ctxSessionFor,
  ctxSessionWhy,
  fitAndResize,
  focusTerminalIfDesktop,
  getFileViewer,
  getKnownTab,
  getLastCtxTabsKey,
  isMobileLayout,
  makeCtxChip,
  makeNewAgentCtxRow,
  makeRepoCtxPill,
  matchAltShortcut,
  openDiffInDrawer,
  openFileDrawerInline,
  openFilePreview,
  openLogInDrawer,
  openSettings,
  openWorktreePopover,
  renderTabs,
  renderTopbarCtx,
  sendGoal,
  sendPtyInput,
  setDesktopSidebar,
  setDesktopSysop,
  setMobileSessions,
  setMobileSysop,
  showSysopEvents,
  showSysopReplyOnMobile,
  spawnTab,
  syncJumpLive,
  syncStageLoader,
  tabChip,
  terminalCwdFor,
});

// ---- Initialize Modules & Bind Top-Level Chrome Controls -----------------------------------
setTimeout(dismissBoot, 4500);
applyTheme(savedTheme, false);
initUiChrome();
initFilePreview();
attachTouchScroll();
initTerminal();
initTabs();
initSysopContext();
initSysopEvents();
initSysopChat();
initVoice();
initSettings();

syncComposerLayout();
if (mobileMq.addEventListener) mobileMq.addEventListener('change', () => { syncComposerLayout(); scheduleFit(); });
goalInputEl.addEventListener('focus', () => syncViewport());
goalInputEl.addEventListener('blur', () => setTimeout(syncViewport, 60));

// Topbar minimalist keys toggle: pins/unpins Esc·Tab·^C·arrows cleanly without stealing focus.
if (btnMobileKeys) {
  btnMobileKeys.addEventListener('pointerdown', (e) => e.preventDefault());
  btnMobileKeys.addEventListener('mousedown', (e) => e.preventDefault());
  btnMobileKeys.addEventListener('click', () => {
    if (appEl.dataset.mobileSysop === '1') setMobileSysop(false);
    const currentlyShown = appEl.dataset.mobileKeys === '1';
    if (currentlyShown) {
      state.mobileKeysPinned = false;
      if (state.mobileKbOpen) state.mobileKeysDismissedForKb = true;
    } else {
      state.mobileKeysPinned = true;
      state.mobileKeysDismissedForKb = false;
    }
    syncMobileKeys();
    requestAnimationFrame(scheduleFit);
  });
}

const btnNewShell = document.getElementById('btn-new-shell');
if (btnNewShell) btnNewShell.addEventListener('click', () => { spawnTab('shell'); focusTerminalIfDesktop(); });
if (btnNewAgent) btnNewAgent.addEventListener('click', () => { openNewAgentPopover(false, '', { showProjectPicker: true }); });
if (sidebarPendingWtEl) sidebarPendingWtEl.addEventListener('click', openPendingWorktreesPopover);
if (topbarWtBtnEl) topbarWtBtnEl.addEventListener('click', () => { if (state.activeId) openWorktreePopover(state.activeId); });
if (mobileWtBtnEl) mobileWtBtnEl.addEventListener('click', () => { if (state.activeId) openWorktreePopover(state.activeId); });
if (popoverBackdropEl) {
  popoverBackdropEl.addEventListener('click', (e) => {
    if (e.target === popoverBackdropEl) closePopover();
  });
}

// Swipe-to-dismiss on the mobile popover sheet (from its drag handle or its header).
if (popoverBackdropEl && popoverEl) {
  let pDrag = null;

  const endPDrag = (cancel) => {
    if (!pDrag) return;
    const d = pDrag;
    pDrag = null;
    popoverEl.classList.remove('is-dragging');
    popoverEl.style.transform = '';
    popoverBackdropEl.style.opacity = '';
    if (!d.moved) return;
    const dismissDist = Math.min(110, d.sheetH * 0.26);
    const freshVy = (performance.now() - d.lastT) < 90 ? d.vy : 0;
    if (!cancel && (d.offset > dismissDist || (freshVy > 0.45 && d.offset > 30))) closePopover();
  };

  popoverEl.addEventListener('pointerdown', (e) => {
    if (!isMobileLayout() || !state.popoverOpen) return;
    if (e.button !== undefined && e.button !== 0) return;
    const t = e.target;
    if (!t || !t.closest) return;
    if (t.closest('button, a, input, textarea, select, [contenteditable="true"]')) return;
    const zone = t.closest('.spop-handle, .spop-head');
    if (!zone || !popoverEl.contains(zone)) return;
    const now = performance.now();
    pDrag = {
      id: e.pointerId,
      startY: e.clientY,
      lastY: e.clientY,
      lastT: now,
      offset: 0,
      vy: 0,
      moved: false,
      sheetH: popoverEl.getBoundingClientRect().height || 360,
    };
    try { popoverEl.setPointerCapture(e.pointerId); } catch (_) {}
  });

  popoverEl.addEventListener('pointermove', (e) => {
    if (!pDrag || e.pointerId !== pDrag.id) return;
    const dy = e.clientY - pDrag.startY;
    if (!pDrag.moved) {
      if (Math.abs(dy) < 6) return;
      pDrag.moved = true;
      popoverEl.classList.add('is-dragging');
    }
    const now = performance.now();
    const dt = Math.max(1, now - pDrag.lastT);
    pDrag.vy = (e.clientY - pDrag.lastY) / dt;
    pDrag.lastY = e.clientY;
    pDrag.lastT = now;
    pDrag.offset = dy >= 0 ? dy : dy * 0.18;
    popoverEl.style.transform = `translateY(${Math.round(pDrag.offset)}px)`;
    const p = Math.max(0, Math.min(1, pDrag.offset / Math.max(160, pDrag.sheetH)));
    popoverBackdropEl.style.opacity = String(1 - p * 0.85);
  });

  const onPUp = (e) => {
    if (!pDrag || e.pointerId !== pDrag.id) return;
    endPDrag(e.type === 'pointercancel');
    try { popoverEl.releasePointerCapture(e.pointerId); } catch (_) {}
  };
  popoverEl.addEventListener('pointerup', onPUp);
  popoverEl.addEventListener('pointercancel', onPUp);
  // Hiding the sheet mid-drag (Esc, an action that closes it) drops the capture without a pointerup:
  // reset, or the next popover opens shifted.
  popoverEl.addEventListener('lostpointercapture', (e) => {
    if (pDrag && e.pointerId === pDrag.id) endPDrag(true);
  });
}

document.getElementById('btn-sidebar-close').addEventListener('click', () => {
  setDesktopSidebar(false);
});
document.getElementById('btn-sidebar-open').addEventListener('click', () => {
  setDesktopSidebar(true);
});
btnToggleSysop.addEventListener('click', toggleDesktopSysop);
document.getElementById('btn-sysop-close').addEventListener('click', () => {
  if (window.innerWidth <= 860) setMobileSysop(false);
  else toggleDesktopSysop();
});
mobileSysopBtn.addEventListener('click', () => setMobileSysop(appEl.dataset.mobileSysop !== '1'));
const sysopHeadEl = sysopPanelEl ? sysopPanelEl.querySelector('.sysop-head') : null;
if (sheetBackdropEl) {
  sheetBackdropEl.addEventListener('click', () => {
    setMobileSysop(false);
    setMobileSessions(false);
  });
}

// Mobile Switcher Pill: tap opens thumb-zone Sessions sheet; horizontal swipe switches adjacent tabs!
if (mobileSwitcherBtn) {
  let pillSwipe = null;
  let suppressPillClick = false;
  mobileSwitcherBtn.addEventListener('pointerdown', (e) => {
    if (!isMobileLayout() || (e.button !== undefined && e.button !== 0)) return;
    pillSwipe = { id: e.pointerId, startX: e.clientX, startY: e.clientY, handled: false };
  });
  mobileSwitcherBtn.addEventListener('pointermove', (e) => {
    if (!pillSwipe || e.pointerId !== pillSwipe.id || pillSwipe.handled) return;
    const dx = e.clientX - pillSwipe.startX;
    const dy = e.clientY - pillSwipe.startY;
    if (Math.abs(dx) >= 36 && Math.abs(dx) > Math.abs(dy) * 1.4 && state.terminals.length > 1) {
      pillSwipe.handled = true;
      suppressPillClick = true;
      setTimeout(() => { suppressPillClick = false; }, 260);
      const curIdx = state.terminals.findIndex((t) => t.address === state.activeId);
      const base = curIdx >= 0 ? curIdx : 0;
      const nextIdx = dx < 0
        ? (base + 1) % state.terminals.length
        : (base - 1 + state.terminals.length) % state.terminals.length;
      const target = state.terminals[nextIdx];
      if (target && target.address !== state.activeId) {
        connectPty(target.address);
      }
    }
  });
  const clearPillSwipe = () => { pillSwipe = null; };
  mobileSwitcherBtn.addEventListener('pointerup', clearPillSwipe);
  mobileSwitcherBtn.addEventListener('pointercancel', clearPillSwipe);
  mobileSwitcherBtn.addEventListener('click', () => {
    if (suppressPillClick) return;
    setMobileSessions(appEl.dataset.mobileSessions !== '1');
  });
}
if (btnSessionsClose) {
  btnSessionsClose.addEventListener('click', () => setMobileSessions(false));
}
if (sessionsFilterBarEl) {
  sessionsFilterBarEl.addEventListener('click', (e) => {
    const btn = e.target && e.target.closest('.sfilter-pill[data-filter]');
    if (!btn) return;
    const next = btn.dataset.filter;
    if (!next || next === state.mobileSessionsFilter) return;
    state.mobileSessionsFilter = next;
    for (const p of sessionsFilterBarEl.querySelectorAll('.sfilter-pill')) {
      const on = p.dataset.filter === next;
      p.classList.toggle('is-on', on);
      p.setAttribute('aria-selected', on ? 'true' : 'false');
    }
    renderTabs(true);
  });
}
if (btnMobileNewAgent) {
  btnMobileNewAgent.addEventListener('click', () => {
    setMobileSessions(false);
    openNewAgentPopover(false);
  });
}
if (btnMobileNewShell) {
  btnMobileNewShell.addEventListener('click', () => {
    setMobileSessions(false);
    spawnTab('shell');
  });
}
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape' && appEl.dataset.mobileSessions === '1') {
    e.preventDefault();
    setMobileSessions(false);
  }
});

// Native-feeling swipe-to-dismiss on mobile Sessions sheet (from top drag handle or header bar).
if (sessionsSheetEl && sessionsSheetHandleEl) {
  let sDrag = null;
  let suppressSHandleClick = false;
  const sGrabZones = [sessionsSheetHandleEl, sessionsSheetHeadEl].filter(Boolean);

  const endSDrag = (cancel) => {
    if (!sDrag) return;
    const d = sDrag;
    sDrag = null;
    sessionsSheetEl.classList.remove('is-dragging');
    if (sheetBackdropEl) {
      sheetBackdropEl.classList.remove('is-dragging');
      sheetBackdropEl.style.opacity = '';
    }
    sessionsSheetEl.style.transform = '';
    if (!d.moved) return;
    suppressSHandleClick = true;
    setTimeout(() => { suppressSHandleClick = false; }, 220);
    const dismissDist = Math.min(120, d.sheetH * 0.26);
    const freshVy = (performance.now() - d.lastT) < 90 ? d.vy : 0;
    const shouldClose = !cancel && (d.offset > dismissDist || (freshVy > 0.45 && d.offset > 30));
    if (shouldClose) setMobileSessions(false);
  };

  const onSDown = (e) => {
    if (!isMobileLayout() || appEl.dataset.mobileSessions !== '1') return;
    if (e.button !== undefined && e.button !== 0) return;
    if (e.target && e.target.closest('button')) return;
    const now = performance.now();
    sDrag = {
      id: e.pointerId,
      target: e.currentTarget,
      startY: e.clientY,
      lastY: e.clientY,
      lastT: now,
      offset: 0,
      vy: 0,
      moved: false,
      sheetH: sessionsSheetEl.getBoundingClientRect().height || 460,
    };
    try { e.currentTarget.setPointerCapture(e.pointerId); } catch (_) {}
  };

  const onSMove = (e) => {
    if (!sDrag || e.pointerId !== sDrag.id) return;
    const dy = e.clientY - sDrag.startY;
    if (!sDrag.moved) {
      if (Math.abs(dy) < 6) return;
      sDrag.moved = true;
      sessionsSheetEl.classList.add('is-dragging');
      if (sheetBackdropEl) sheetBackdropEl.classList.add('is-dragging');
    }
    const now = performance.now();
    const dt = Math.max(1, now - sDrag.lastT);
    sDrag.vy = (e.clientY - sDrag.lastY) / dt;
    sDrag.lastY = e.clientY;
    sDrag.lastT = now;
    sDrag.offset = dy >= 0 ? dy : dy * 0.18;
    sessionsSheetEl.style.transform = `translateY(${Math.round(sDrag.offset)}px)`;
    if (sheetBackdropEl) {
      const p = Math.max(0, Math.min(1, sDrag.offset / Math.max(160, sDrag.sheetH)));
      sheetBackdropEl.style.opacity = String(1 - p * 0.85);
    }
  };

  const onSUp = (e) => {
    if (!sDrag || e.pointerId !== sDrag.id) return;
    try { sDrag.target.releasePointerCapture(e.pointerId); } catch (_) {}
    endSDrag(e.type === 'pointercancel');
  };

  for (const zone of sGrabZones) {
    zone.addEventListener('pointerdown', onSDown);
    zone.addEventListener('pointermove', onSMove);
    zone.addEventListener('pointerup', onSUp);
    zone.addEventListener('pointercancel', onSUp);
  }
  sessionsSheetHandleEl.addEventListener('click', () => {
    if (suppressSHandleClick) return;
    setMobileSessions(false);
  });
}

// Native-feeling swipe-to-dismiss on mobile Sysop sheet (from top drag handle or header bar).
if (sysopPanelEl && sheetHandleEl) {
  let drag = null;
  let suppressHandleClick = false;
  const grabZones = [sheetHandleEl, sysopHeadEl].filter(Boolean);

  const endDrag = (cancel) => {
    if (!drag) return;
    const d = drag;
    drag = null;
    sysopPanelEl.classList.remove('is-dragging');
    if (sheetBackdropEl) {
      sheetBackdropEl.classList.remove('is-dragging');
      sheetBackdropEl.style.opacity = '';
    }
    sysopPanelEl.style.transform = '';
    if (!d.moved) return;
    suppressHandleClick = true;
    setTimeout(() => { suppressHandleClick = false; }, 220);
    const dismissDist = Math.min(130, d.sheetH * 0.28);
    const freshVy = (performance.now() - d.lastT) < 90 ? d.vy : 0;
    const shouldClose = !cancel && (d.offset > dismissDist || (freshVy > 0.45 && d.offset > 32));
    if (shouldClose) setMobileSysop(false);
  };

  const onDown = (e) => {
    if (!isMobileLayout() || appEl.dataset.mobileSysop !== '1') return;
    if (e.button !== undefined && e.button !== 0) return;
    if (e.target && e.target.closest('button')) return;
    const now = performance.now();
    drag = {
      id: e.pointerId,
      target: e.currentTarget,
      startY: e.clientY,
      lastY: e.clientY,
      lastT: now,
      offset: 0,
      vy: 0,
      moved: false,
      sheetH: sysopPanelEl.getBoundingClientRect().height || 500,
    };
    try { e.currentTarget.setPointerCapture(e.pointerId); } catch (_) {}
  };

  const onMove = (e) => {
    if (!drag || e.pointerId !== drag.id) return;
    const dy = e.clientY - drag.startY;
    if (!drag.moved) {
      if (Math.abs(dy) < 6) return;
      drag.moved = true;
      sysopPanelEl.classList.add('is-dragging');
      if (sheetBackdropEl) sheetBackdropEl.classList.add('is-dragging');
    }
    const now = performance.now();
    const dt = Math.max(1, now - drag.lastT);
    drag.vy = (e.clientY - drag.lastY) / dt;
    drag.lastY = e.clientY;
    drag.lastT = now;
    drag.offset = dy >= 0 ? dy : dy * 0.18;
    sysopPanelEl.style.transform = `translateY(${Math.round(drag.offset)}px)`;
    if (sheetBackdropEl) {
      const p = Math.max(0, Math.min(1, drag.offset / Math.max(180, drag.sheetH)));
      sheetBackdropEl.style.opacity = String(1 - p * 0.85);
    }
  };

  const onUp = (e) => {
    if (!drag || e.pointerId !== drag.id) return;
    try { drag.target.releasePointerCapture(e.pointerId); } catch (_) {}
    endDrag(e.type === 'pointercancel');
  };

  for (const zone of grabZones) {
    zone.addEventListener('pointerdown', onDown);
    zone.addEventListener('pointermove', onMove);
    zone.addEventListener('pointerup', onUp);
    zone.addEventListener('pointercancel', onUp);
  }
  sheetHandleEl.addEventListener('click', () => {
    if (suppressHandleClick) return;
    setMobileSysop(false);
  });
}

btnSysopNew.addEventListener('click', async () => {
  clearOpenTurnActions();
  await fetch('/api/sysop/new', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' }).catch(() => {});
});

if (btnSysopStop) btnSysopStop.addEventListener('click', () => stopSysop());
if (btnMobileLiveStop) btnMobileLiveStop.addEventListener('click', () => stopSysop());
if (btnMobileDockStop) btnMobileDockStop.addEventListener('click', () => stopSysop());

document.getElementById('btn-interrupt').addEventListener('click', async () => {
  if (!state.activeId) return;
  await fetch(`/api/tabs/${encodeURIComponent(state.activeId)}/interrupt`, { method: 'POST' });
  focusTerminalIfDesktop();
});

function syncSendReady() {
  const ready = goalInputEl.value.trim() ? '1' : '0';
  btnSendGoal.dataset.ready = ready;
  if (composerEl) composerEl.dataset.ready = ready;
}
syncSendReady();
goalInputEl.addEventListener('input', () => { syncSendReady(); autosizeGoalInput(); });
btnSendGoal.addEventListener('click', () => { sendGoal(); syncSendReady(); autosizeGoalInput(); });
if (btnSheetSend) {
  btnSheetSend.addEventListener('pointerdown', (e) => e.preventDefault());
  btnSheetSend.addEventListener('click', () => { sendGoal(); syncSendReady(); autosizeGoalInput(); });
}
goalInputEl.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') {
    e.preventDefault();
    if (state.sysopRunning && !goalInputEl.value.trim()) {
      stopSysop();
      return;
    }
    if (isMobileLayout()) { goalInputEl.value = ''; syncSendReady(); autosizeGoalInput(); }
    goalInputEl.blur();
    focusTerminalIfDesktop();
    return;
  }
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    sendGoal();
    syncSendReady();
    autosizeGoalInput();
    focusTerminalIfDesktop();
  }
});

document.getElementById('btn-allow').addEventListener('click', () => { handleApproval('allow'); focusTerminalIfDesktop(); });
document.getElementById('btn-cancel').addEventListener('click', () => { handleApproval('cancel'); focusTerminalIfDesktop(); });
document.getElementById('btn-mobile-allow').addEventListener('click', () => handleApproval('allow'));
document.getElementById('btn-mobile-cancel').addEventListener('click', () => handleApproval('cancel'));

if (touchKeysEl) {
  // Prevent tapping Esc/Tab/^C/arrows from blurring the terminal or collapsing the OS keyboard.
  touchKeysEl.addEventListener('pointerdown', (e) => e.preventDefault());
  touchKeysEl.addEventListener('mousedown', (e) => e.preventDefault());
  touchKeysEl.addEventListener('click', async (e) => {
    const btn = e.target.closest('button[data-key]');
    if (!btn || !state.activeId) return;
    await fetch(`/api/tabs/${encodeURIComponent(state.activeId)}/keys`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ keys: [btn.dataset.key] }),
    });
  });
}

connectEvents();
