// Shared reactive state, DOM element cache, late-bound action registry, boot/connection helpers, and agent registry.

export const STUDIO_CLIENT_ID = (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function')
  ? crypto.randomUUID()
  : `sb-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;

export const MAX_TAB_SESSIONS = 8;

const byId = (id) => (typeof document !== 'undefined' ? document.getElementById(id) : null);

export const dom = {
  appEl: byId('app'),
  sidebarTabsEl: byId('sidebar-tabs'),
  sidebarAgentsSectionEl: byId('sidebar-agents-section'),
  sidebarAgentsEl: byId('sidebar-agents'),
  sidebarParkedSectionEl: byId('sidebar-parked-section'),
  sidebarParkedEl: byId('sidebar-parked'),
  parkedCountEl: byId('parked-count'),
  sidebarPendingWtEl: byId('sidebar-pending-wt'),
  pendingWtCountEl: byId('pending-wt-count'),
  sidebarShellsSectionEl: byId('sidebar-shells-section'),
  btnNewAgent: byId('btn-new-agent'),
  topbarWtBtnEl: byId('topbar-wt-btn'),
  topbarCtxBtnEl: byId('topbar-ctx-btn'),
  mobileCtxBtnEl: byId('mobile-ctx-btn'),
  mobileWtBtnEl: byId('mobile-wt-btn'),
  popoverBackdropEl: byId('studio-popover-backdrop'),
  popoverEl: byId('studio-popover'),
  agentsBusyCountEl: byId('agents-busy-count'),
  topbarTabsEl: byId('topbar-tabs'),
  mobileSwitcherBtn: byId('btn-mobile-switcher'),
  mobileSwitcherIcoEl: byId('mobile-switcher-ico'),
  mobileSwitcherCountEl: byId('mobile-switcher-count'),
  sessionsSheetEl: byId('sessions-sheet'),
  sessionsSheetHandleEl: byId('sessions-sheet-handle'),
  sessionsSheetHeadEl: byId('sessions-sheet-head'),
  sessionsSheetBodyEl: byId('sessions-sheet-body'),
  sessionsFilterBarEl: byId('sessions-filter-bar'),
  mobileSessionsBusyEl: byId('mobile-sessions-busy'),
  sfilterCountAllEl: byId('sfilter-count-all'),
  sfilterCountAgentsEl: byId('sfilter-count-agents'),
  sfilterCountShellsEl: byId('sfilter-count-shells'),
  btnSessionsClose: byId('btn-sessions-close'),
  btnMobileNewAgent: byId('btn-mobile-new-agent'),
  btnMobileNewShell: byId('btn-mobile-new-shell'),
  tabCountEl: byId('tab-count'),
  activeDotEl: byId('active-dot'),
  activeNameEl: byId('active-name'),
  activeAgentEl: byId('active-agent'),
  activeStatusEl: byId('active-status'),
  termCtxIconEl: byId('term-ctx-icon'),
  termCtxTitleEl: byId('term-ctx-title'),
  termCtxStateEl: byId('term-ctx-state'),
  statusbarSummaryEl: byId('statusbar-summary'),
  connPillEl: byId('conn-pill'),
  connTextEl: byId('conn-text'),
  sysopDotEl: byId('sysop-dot'),
  mobileSysopBtn: byId('btn-mobile-sysop'),
  mobileSysopTextEl: byId('mobile-sysop-text'),
  btnMobileKeys: byId('btn-mobile-keys'),
  btnSheetMic: byId('btn-sheet-mic'),
  btnSheetSend: byId('btn-sheet-send'),
  btnToggleSysop: byId('btn-toggle-sysop'),
  sysopFeedEl: byId('sysop-feed'),
  sysopEventsEl: byId('sysop-events'),
  sysopTabChatEl: byId('sysop-tab-chat'),
  sysopTabEventsEl: byId('sysop-tab-events'),
  sysopEventsBadgeEl: byId('sysop-events-badge'),
  btnSysopStop: byId('btn-sysop-stop'),
  btnSysopNew: byId('btn-sysop-new'),
  sysopModelPillEl: byId('sysop-model-pill'),
  sysopQueueBarEl: byId('sysop-queue-bar'),
  sysopLiveStripEl: byId('sysop-live-strip'),
  sysopLiveStripTextEl: byId('sysop-live-strip-text'),
  btnMobileLiveStop: byId('btn-mobile-live-stop'),
  btnMobileDockStop: byId('btn-mobile-dock-stop'),
  sendLabelEl: byId('send-label'),
  approvalCardEl: byId('approval-card'),
  approvalBadgeEl: byId('approval-badge'),
  approvalTabEl: byId('approval-tab'),
  approvalTextEl: byId('approval-text'),
  approvalBarEl: byId('approval-bar'),
  approvalBarFillEl: byId('approval-bar-fill'),
  mobileApprovalEl: byId('mobile-approval'),
  mobileApprovalBadgeEl: byId('mobile-approval-badge'),
  mobileApprovalMsgEl: byId('mobile-approval-msg'),
  questionCardEl: byId('question-card'),
  questionTextEl: byId('question-text'),
  questionOptionsEl: byId('question-options'),
  questionLeftEl: byId('question-left'),
  questionFreeEl: byId('question-free'),
  questionInputEl: byId('question-input'),
  voiceNoteEl: byId('voice-note'),
  voiceHintEl: byId('voice-hint'),
  micLabelEl: byId('mic-label'),
  goalInputEl: byId('goal-input'),
  themeSwatchEl: byId('theme-swatch'),
  btnMic: byId('btn-mic'),
  btnMobileMic: byId('btn-mobile-mic'),
  termWrapEl: byId('term-wrap'),
  termStageLoaderEl: byId('term-stage-loader'),
  stageLoaderCtxEl: byId('stage-loader-ctx'),
  stageLoaderCtxTitleEl: byId('stage-loader-ctx-title'),
  stageLoaderCtxSubEl: byId('stage-loader-ctx-sub'),
  stageLoaderCtxSkipEl: byId('stage-loader-ctx-skip'),
  termDropOverlayEl: byId('term-drop-overlay'),
  termToastEl: byId('term-toast'),
  btnJumpLive: byId('btn-jump-live'),
  settingsOverlayEl: byId('settings-overlay'),
  settingsNavEl: byId('settings-nav'),
  settingsVersionEl: byId('settings-version'),
  settingsTitleEl: byId('settings-title'),
  settingsSubEl: byId('settings-sub'),
  settingsBodyEl: byId('settings-body'),
  settingsHostBarEl: byId('settings-host-bar'),
  hostBarCountEl: byId('host-bar-count'),
  hostBarCmdEl: byId('host-bar-cmd'),
  btnHostCopy: byId('btn-host-copy'),
  btnHostDiscard: byId('btn-host-discard'),
  terminalHostEl: byId('terminal'),
  stageEmptyEl: byId('stage-empty'),
  fileDrawerBackdropEl: byId('file-drawer-backdrop'),
  fileDrawerEl: byId('file-drawer'),
  composerEl: byId('sysop-composer'),
  sheetBackdropEl: byId('sheet-backdrop'),
  sheetHandleEl: byId('sheet-handle'),
  sysopPanelEl: byId('sysop-panel'),
  btnSendGoal: byId('btn-send-goal'),
  touchKeysEl: byId('touch-keys'),
  btnInterruptEl: byId('btn-interrupt'),
};

export const state = {
  bootDismissed: false,
  mobileSessionsFilter: 'all',
  sysopRunning: false,
  terminals: [],
  pins: [],
  pendingWorktrees: [],
  repoStatuses: {},
  worktreePrefs: { mode: 'ask', copy_env: true },
  sessionPrefs: { boot_mode: 'autostart' },
  installedAgents: [],
  agentReg: { list: [], byId: new Map(), byName: new Map(), shellNames: new Set() },
  editingTabId: null,
  popoverOpen: false,
  popoverKeyHandler: null,
  // The open git popover's live refresh ({ sig, run }): re-fetches and re-renders only when status changed
  gitPopRefresh: null,
  activeId: null,
  lastServerActive: null,
  lastLocalTabSwitchMs: 0,
  currentThemeKey: 'catppuccin',
  tabSessions: new Map(),
  eventsWs: null,
  eventsConnected: false,
  ptyConnected: false,
  currentApproval: null,
  voiceAddonAvailable: false,
  countdownTimer: null,
  settingsOpen: false,
  settingsSection: 'appearance',
  boxConfig: null,
  boxConfigLoading: false,
  boxConfigError: '',
  stagedHostConfig: new Map(),
  installingAddons: new Set(),
  addonMessages: new Map(),
  fontOffset: 0,
  lineHeightPreset: '',
  cursorStyle: 'block',
  cursorBlink: true,
  scrollbackLines: 3000,
  serverHomeDir: '',
  mobileKeysPinned: false,
  mobileKeysDismissedForKb: false,
  mobileKbOpen: false,
  fileDrawerOpen: false,
  sysopContext: null,
  sysopView: 'chat',
  lastSysopSnap: null,
};

// Late-bound cross-domain callbacks wired by public/app.js so modules form a strict DAG with zero circular imports.
export const actions = {};

export function registerActions(map) {
  Object.assign(actions, map);
}

export function activeSession() {
  return state.activeId ? (state.tabSessions.get(state.activeId) || null) : null;
}

export function syncConnPill() {
  if (!dom.connPillEl || !dom.connTextEl) return;
  if (!state.eventsConnected) {
    dom.connPillEl.className = 'conn-pill err';
    dom.connTextEl.textContent = 'reconnecting…';
  } else if (state.activeId && !state.ptyConnected) {
    dom.connPillEl.className = 'conn-pill warn';
    dom.connTextEl.textContent = 'reconnecting terminal…';
  } else {
    dom.connPillEl.className = 'conn-pill ok';
    dom.connTextEl.textContent = 'herdr-core live';
  }
}

export function dismissBoot() {
  if (state.bootDismissed) return;
  state.bootDismissed = true;
  if (typeof document !== 'undefined') {
    document.documentElement.classList.add('swarmbox-ready');
  }
  if (typeof actions.syncStageLoader === 'function') actions.syncStageLoader();
}

// The agents of the box (the registry, docs/agents-design.md): window.SWARMBOX_AGENTS, set by /agents.js before this script, and
// refreshed from /api/agents. Ids, names, labels, colours and icons come from each agent's addon: nothing in this page names an agent.
export function setAgentRegistry(data) {
  const list = data && Array.isArray(data.agents) ? data.agents.filter((a) => a && typeof a.id === 'string' && a.id) : [];
  const byId = new Map();
  const byName = new Map();
  for (const a of list) { byId.set(a.id, a); byName.set(a.id, a.id); }
  for (const a of list) for (const al of a.aliases || []) if (!byName.has(al)) byName.set(al, a.id);
  const shellNames = new Set(data && Array.isArray(data.shell_names) ? data.shell_names : ['bash', 'sh', 'zsh', 'dash', 'fish', '-bash', '-sh', '-zsh']);
  state.agentReg = { list, byId, byName, shellNames };
}

if (typeof window !== 'undefined') {
  setAgentRegistry(window.SWARMBOX_AGENTS);
}

export function refreshAgentRegistry() {
  return fetch('/api/agents', { cache: 'no-store' })
    .then((r) => (r.ok ? r.json() : null))
    .then((d) => { if (d) { window.SWARMBOX_AGENTS = d; setAgentRegistry(d); } })
    .catch(() => {});
}

// The agent id of a name (an id, a command, an alias such as the OSC 7501 app it reports), or ''
export function resolveAgentName(raw) {
  let n = String(raw || '').trim().toLowerCase();
  n = n.slice(n.lastIndexOf('/') + 1).replace(/^-+/, '');
  return (n && state.agentReg.byName.get(n)) || '';
}

export function isAgentId(id) {
  return Boolean(id) && state.agentReg.byId.has(id);
}

export function agentLabel(id) {
  if (!id || id === 'shell') return 'Shell';
  const a = state.agentReg.byId.get(id);
  return a ? a.label || a.id : id;
}

// The card colours of an agent, from its COLOR: border, strong form, background tint, scene and accent
export function applyAgentColor(el, id) {
  const a = state.agentReg.byId.get(id);
  const m = a && /^#([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(a.color || '');
  for (const v of ['--ac-border', '--ac-strong', '--ac-bg', '--ac-scene', '--ac-accent']) el.style.removeProperty(v);
  if (!m) return;
  const [r, g, b] = [m[1], m[2], m[3]].map((x) => parseInt(x, 16));
  const mix = (c, base, k) => Math.round(base + (c - base) * k);
  el.style.setProperty('--ac-border', `rgba(${r}, ${g}, ${b}, 0.36)`);
  el.style.setProperty('--ac-strong', `rgba(${r}, ${g}, ${b}, 0.74)`);
  el.style.setProperty('--ac-bg', `rgba(${r}, ${g}, ${b}, 0.09)`);
  el.style.setProperty('--ac-scene', `rgb(${mix(r, 12, 0.08)}, ${mix(g, 11, 0.08)}, ${mix(b, 16, 0.08)})`);
  el.style.setProperty('--ac-accent', a.color);
}
