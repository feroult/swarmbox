(() => {
  // Five curated themes synchronized with ~/.config/herdr/config.toml via /api/theme.
  // Default: SwarmBox Purple Glow (exact palette from docs/theme.md).
  const THEMES = {
    'purple-glow': {
      label: 'Purple Glow',
      css: {
        '--bg': '#0c0b10',
        '--surface': '#12101a',
        '--sheet': '#15121d',
        '--band': '#27222f',
        '--surface-2': '#1b1726',
        '--surface-hover': '#241e33',
        '--border': 'rgba(167, 139, 250, 0.13)',
        '--border-strong': 'rgba(167, 139, 250, 0.34)',
        '--hair-1': '#6d28d9',
        '--hair-2': '#a78bfa',
        '--text': '#f4f4f5',
        '--text-muted': '#a1a1aa',
        '--text-dim': '#71717a',
        '--accent': '#a78bfa',
        '--accent-bright': '#c4b5fd',
        '--accent-deep': '#6d28d9',
        '--accent-bg': 'rgba(167, 139, 250, 0.14)',
        '--accent-glow': 'rgba(167, 139, 250, 0.42)',
        '--btn-grad-1': '#7c3aed',
        '--btn-grad-2': '#5b21b6',
        '--btn-text': '#ffffff',
      },
      xterm: {
        background: '#0c0b10',
        foreground: '#d4d4d8',
        cursor: '#c4b5fd',
        cursorAccent: '#0c0b10',
        selectionBackground: '#6d28d9',
        selectionForeground: '#fafafa',
        black: '#1c1a24',
        red: '#e5484d',
        green: '#3dba7a',
        yellow: '#d9a441',
        blue: '#8b5cf6',
        magenta: '#d946ef',
        cyan: '#5eb5c9',
        white: '#d4d4d8',
        brightBlack: '#71717a',
        brightRed: '#ff6b78',
        brightGreen: '#4ade80',
        brightYellow: '#fbbf24',
        brightBlue: '#a78bfa',
        brightMagenta: '#e879f9',
        brightCyan: '#8ad7e6',
        brightWhite: '#fafafa',
      },
    },
    catppuccin: {
      label: 'Catppuccin',
      css: {
        '--bg': '#11111b',
        '--surface': '#181825',
        '--sheet': '#1a1a28',
        '--band': '#29293e',
        '--surface-2': '#1e1e2e',
        '--surface-hover': '#2a2b3d',
        '--border': 'rgba(203, 166, 247, 0.14)',
        '--border-strong': 'rgba(203, 166, 247, 0.34)',
        '--hair-1': '#8839ef',
        '--hair-2': '#cba6f7',
        '--text': '#cdd6f4',
        '--text-muted': '#a6adc8',
        '--text-dim': '#6c7086',
        '--accent': '#cba6f7',
        '--accent-bright': '#f5c2e7',
        '--accent-deep': '#8839ef',
        '--accent-bg': 'rgba(203, 166, 247, 0.14)',
        '--accent-glow': 'rgba(203, 166, 247, 0.38)',
        '--btn-grad-1': '#9c6ade',
        '--btn-grad-2': '#7448b5',
        '--btn-text': '#ffffff',
      },
      xterm: {
        background: '#11111b',
        foreground: '#cdd6f4',
        cursor: '#f5e0dc',
        selectionBackground: 'rgba(203, 166, 247, 0.28)',
        black: '#45475a',
        red: '#f38ba8',
        green: '#a6e3a1',
        yellow: '#f9e2af',
        blue: '#89b4fa',
        magenta: '#f5c2e7',
        cyan: '#94e2d5',
        white: '#bac2de',
      },
    },
    'tokyo-night': {
      label: 'Tokyo Night',
      css: {
        '--bg': '#16161e',
        '--surface': '#1a1b26',
        '--sheet': '#1d1f2c',
        '--band': '#282d42',
        '--surface-2': '#24283b',
        '--surface-hover': '#2f3549',
        '--border': 'rgba(122, 162, 247, 0.15)',
        '--border-strong': 'rgba(122, 162, 247, 0.36)',
        '--hair-1': '#3d59a1',
        '--hair-2': '#7aa2f7',
        '--text': '#c0caf5',
        '--text-muted': '#9aa5ce',
        '--text-dim': '#565f89',
        '--accent': '#7aa2f7',
        '--accent-bright': '#bb9af7',
        '--accent-deep': '#3d59a1',
        '--accent-bg': 'rgba(122, 162, 247, 0.14)',
        '--accent-glow': 'rgba(122, 162, 247, 0.38)',
        '--btn-grad-1': '#5b82e0',
        '--btn-grad-2': '#3d59a1',
        '--btn-text': '#ffffff',
      },
      xterm: {
        background: '#16161e',
        foreground: '#c0caf5',
        cursor: '#c0caf5',
        selectionBackground: 'rgba(122, 162, 247, 0.28)',
        black: '#15161e',
        red: '#f7768e',
        green: '#9ece6a',
        yellow: '#e0af68',
        blue: '#7aa2f7',
        magenta: '#bb9af7',
        cyan: '#7dcfff',
        white: '#a9b1d6',
      },
    },
    nord: {
      label: 'Nord',
      css: {
        '--bg': '#242933',
        '--surface': '#2e3440',
        '--sheet': '#313846',
        '--band': '#3e4759',
        '--surface-2': '#3b4252',
        '--surface-hover': '#434c5e',
        '--border': 'rgba(136, 192, 208, 0.16)',
        '--border-strong': 'rgba(136, 192, 208, 0.38)',
        '--hair-1': '#5e81ac',
        '--hair-2': '#88c0d0',
        '--text': '#eceff4',
        '--text-muted': '#d8dee9',
        '--text-dim': '#8190a8',
        '--accent': '#88c0d0',
        '--accent-bright': '#8fbcbb',
        '--accent-deep': '#5e81ac',
        '--accent-bg': 'rgba(136, 192, 208, 0.14)',
        '--accent-glow': 'rgba(136, 192, 208, 0.36)',
        '--btn-grad-1': '#6fa8ba',
        '--btn-grad-2': '#4c7399',
        '--btn-text': '#ffffff',
      },
      xterm: {
        background: '#242933',
        foreground: '#eceff4',
        cursor: '#88c0d0',
        selectionBackground: 'rgba(136, 192, 208, 0.28)',
        black: '#3b4252',
        red: '#bf616a',
        green: '#a3be8c',
        yellow: '#ebcb8b',
        blue: '#81a1c1',
        magenta: '#b48ead',
        cyan: '#88c0d0',
        white: '#e5e9f0',
      },
    },
    'rose-pine': {
      label: 'Rosé Pine',
      css: {
        '--bg': '#191724',
        '--surface': '#1f1d2e',
        '--sheet': '#221f32',
        '--band': '#2e2a45',
        '--surface-2': '#26233a',
        '--surface-hover': '#312c49',
        '--border': 'rgba(196, 167, 231, 0.15)',
        '--border-strong': 'rgba(196, 167, 231, 0.36)',
        '--hair-1': '#907aa9',
        '--hair-2': '#c4a7e7',
        '--text': '#e0def4',
        '--text-muted': '#908caa',
        '--text-dim': '#6e6a86',
        '--accent': '#c4a7e7',
        '--accent-bright': '#ebbcba',
        '--accent-deep': '#907aa9',
        '--accent-bg': 'rgba(196, 167, 231, 0.14)',
        '--accent-glow': 'rgba(196, 167, 231, 0.38)',
        '--btn-grad-1': '#9c7cc4',
        '--btn-grad-2': '#6d5191',
        '--btn-text': '#ffffff',
      },
      xterm: {
        background: '#191724',
        foreground: '#e0def4',
        cursor: '#ebbcba',
        selectionBackground: 'rgba(196, 167, 231, 0.28)',
        black: '#26233a',
        red: '#eb6f92',
        green: '#31748f',
        yellow: '#f6c177',
        blue: '#9ccfd8',
        magenta: '#c4a7e7',
        cyan: '#ebbcba',
        white: '#e0def4',
      },
    },
  };

  let bootDismissed = false;
  function dismissBoot() {
    if (bootDismissed) return;
    bootDismissed = true;
    document.documentElement.classList.add('swarmbox-ready');
    if (typeof syncStageLoader === 'function') syncStageLoader();
  }
  setTimeout(dismissBoot, 4500);

  const appEl = document.getElementById('app');
  const sidebarTabsEl = document.getElementById('sidebar-tabs');
  const sidebarAgentsSectionEl = document.getElementById('sidebar-agents-section');
  const sidebarAgentsEl = document.getElementById('sidebar-agents');
  const sidebarParkedSectionEl = document.getElementById('sidebar-parked-section');
  const sidebarParkedEl = document.getElementById('sidebar-parked');
  const parkedCountEl = document.getElementById('parked-count');
  const sidebarPendingWtEl = document.getElementById('sidebar-pending-wt');
  const pendingWtCountEl = document.getElementById('pending-wt-count');
  const btnNewAgent = document.getElementById('btn-new-agent');
  const topbarWtBtnEl = document.getElementById('topbar-wt-btn');
  const mobileWtBtnEl = document.getElementById('mobile-wt-btn');
  const popoverBackdropEl = document.getElementById('studio-popover-backdrop');
  const popoverEl = document.getElementById('studio-popover');
  const agentsBusyCountEl = document.getElementById('agents-busy-count');
  const topbarTabsEl = document.getElementById('topbar-tabs');
  const mobileTabsEl = document.getElementById('mobile-tabs');
  const tabCountEl = document.getElementById('tab-count');
  const activeDotEl = document.getElementById('active-dot');
  const activeNameEl = document.getElementById('active-name');
  const activeAgentEl = document.getElementById('active-agent');
  const activeStatusEl = document.getElementById('active-status');
  const termCtxIconEl = document.getElementById('term-ctx-icon');
  const termCtxTitleEl = document.getElementById('term-ctx-title');
  const termCtxStateEl = document.getElementById('term-ctx-state');
  const statusbarSummaryEl = document.getElementById('statusbar-summary');
  const connPillEl = document.getElementById('conn-pill');
  const connTextEl = document.getElementById('conn-text');
  const sysopDotEl = document.getElementById('sysop-dot');
  const sysopStateEl = document.getElementById('sysop-state');
  const mobileSysopBtn = document.getElementById('btn-mobile-sysop');
  const mobileSysopTextEl = document.getElementById('mobile-sysop-text');
  const btnMobileKeys = document.getElementById('btn-mobile-keys');
  const btnSheetMic = document.getElementById('btn-sheet-mic');
  const btnSheetSend = document.getElementById('btn-sheet-send');
  const btnToggleSysop = document.getElementById('btn-toggle-sysop');
  const sysopFeedEl = document.getElementById('sysop-feed');
  const btnSysopStop = document.getElementById('btn-sysop-stop');
  const btnSysopNew = document.getElementById('btn-sysop-new');
  const approvalCardEl = document.getElementById('approval-card');
  const approvalBadgeEl = document.getElementById('approval-badge');
  const approvalTabEl = document.getElementById('approval-tab');
  const approvalTextEl = document.getElementById('approval-text');
  const approvalBarEl = document.getElementById('approval-bar');
  const approvalBarFillEl = document.getElementById('approval-bar-fill');
  const mobileApprovalEl = document.getElementById('mobile-approval');
  const mobileApprovalBadgeEl = document.getElementById('mobile-approval-badge');
  const mobileApprovalMsgEl = document.getElementById('mobile-approval-msg');
  const voiceNoteEl = document.getElementById('voice-note');
  const voiceHintEl = document.getElementById('voice-hint');
  const micLabelEl = document.getElementById('mic-label');
  const goalInputEl = document.getElementById('goal-input');
  const themeSwatchEl = document.getElementById('theme-swatch');
  const btnMic = document.getElementById('btn-mic');
  const btnMobileMic = document.getElementById('btn-mobile-mic');
  const termWrapEl = document.getElementById('term-wrap');
  const termStageLoaderEl = document.getElementById('term-stage-loader');
  const termDropOverlayEl = document.getElementById('term-drop-overlay');
  const termToastEl = document.getElementById('term-toast');
  const btnJumpLive = document.getElementById('btn-jump-live');
  const settingsOverlayEl = document.getElementById('settings-overlay');
  const settingsNavEl = document.getElementById('settings-nav');
  const settingsVersionEl = document.getElementById('settings-version');
  const settingsTitleEl = document.getElementById('settings-title');
  const settingsSubEl = document.getElementById('settings-sub');
  const settingsBodyEl = document.getElementById('settings-body');
  const settingsHostBarEl = document.getElementById('settings-host-bar');
  const hostBarCountEl = document.getElementById('host-bar-count');
  const hostBarCmdEl = document.getElementById('host-bar-cmd');
  const btnHostCopy = document.getElementById('btn-host-copy');
  const btnHostDiscard = document.getElementById('btn-host-discard');

  const terminalHostEl = document.getElementById('terminal');
  const stageEmptyEl = document.getElementById('stage-empty');
  const MAX_TAB_SESSIONS = 8;

  let terminals = [];
  let pins = [];
  let pendingWorktrees = [];
  let worktreePrefs = { mode: 'ask', copy_env: true };
  let sessionPrefs = { boot_mode: 'autostart' };
  let installedAgents = [];
  let editingTabId = null;
  let popoverOpen = false;
  let popoverKeyHandler = null;
  let activeId = null;
  let lastServerActive = null;   // the active tab the gateway reported last (the herdr-active-tab marker)
  let currentThemeKey = 'purple-glow';
  const tabSessions = new Map();
  let eventsWs = null;
  let eventsConnected = false;
  let ptyConnected = false;
  let currentApproval = null;
  let voiceAddonAvailable = false;
  let countdownTimer = null;
  let settingsOpen = false;
  let settingsSection = 'appearance';
  let boxConfig = null;
  let boxConfigLoading = false;
  let boxConfigError = '';
  const stagedHostConfig = new Map();
  const installingAddons = new Set();
  const addonMessages = new Map();

  function activeSession() {
    return activeId ? (tabSessions.get(activeId) || null) : null;
  }

  function syncConnPill() {
    if (!eventsConnected) {
      connPillEl.className = 'conn-pill err';
      connTextEl.textContent = 'reconnecting…';
    } else if (activeId && !ptyConnected) {
      connPillEl.className = 'conn-pill warn';
      connTextEl.textContent = 'reconnecting terminal…';
    } else {
      connPillEl.className = 'conn-pill ok';
      connTextEl.textContent = 'herdr-core live';
    }
  }

  const LINE_HEIGHT_PRESETS = { compact: 1.15, studio: 1.26, airy: 1.38 };
  const CURSOR_STYLES = ['block', 'bar', 'underline'];
  const SCROLLBACK_OPTIONS = [1500, 3000, 6000, 10000];

  let fontOffset = (() => {
    try {
      const v = Number(localStorage.getItem('swarmbox-herdr-font-offset') || '0');
      return Number.isFinite(v) ? Math.max(-4, Math.min(8, v)) : 0;
    } catch (_) { return 0; }
  })();

  let lineHeightPreset = (() => {
    try {
      const v = localStorage.getItem('swarmbox-herdr-lh');
      if (v && LINE_HEIGHT_PRESETS[v]) return v;
    } catch (_) {}
    return '';
  })();

  let cursorStyle = (() => {
    try {
      const v = localStorage.getItem('swarmbox-herdr-cursor-style');
      if (CURSOR_STYLES.includes(v)) return v;
    } catch (_) {}
    return 'block';
  })();

  let cursorBlink = (() => {
    try {
      const v = localStorage.getItem('swarmbox-herdr-cursor-blink');
      if (v === '0') return false;
      if (v === '1') return true;
    } catch (_) {}
    return true;
  })();

  let scrollbackLines = (() => {
    try {
      const v = Number(localStorage.getItem('swarmbox-herdr-scrollback') || '3000');
      if (SCROLLBACK_OPTIONS.includes(v)) return v;
    } catch (_) {}
    return 3000;
  })();

  function effectiveLineHeightKey() {
    if (lineHeightPreset && LINE_HEIGHT_PRESETS[lineHeightPreset]) return lineHeightPreset;
    return window.innerWidth <= 860 ? 'compact' : 'studio';
  }

  function computeLineHeight() {
    return LINE_HEIGHT_PRESETS[effectiveLineHeightKey()] || 1.26;
  }

  // Dynamic column-aware font sizing:
  // Desktop defaults to a comfortable 16.5px (adjustable via Settings or Alt+-/=/0).
  // On phones (<= 860px), pick the exact font size so >= 51 columns fit upright (keeping the
  // single-line Starship prompt completely unbroken).
  function computeFontSize() {
    const w = window.innerWidth;
    let base;
    if (w > 860) {
      base = 16.5;
    } else {
      const usable = Math.max(240, (termWrapEl.clientWidth || w) - 18);
      const targetCols = w < window.innerHeight ? 51 : 94;
      const raw = usable / (targetCols * 0.605);
      base = Math.max(10.5, Math.min(15, Math.round(raw * 2) / 2));
    }
    return Math.max(9.5, Math.min(26, Math.round((base + fontOffset) * 2) / 2));
  }

  function formatFontPx(sz) {
    return Number.isInteger(sz) ? `${sz}px` : `${sz.toFixed(1)}px`;
  }

  function syncAppearanceControls() {
    if (!settingsOpen || settingsSection !== 'appearance') return;
    const sz = computeFontSize();
    const valEl = settingsBodyEl.querySelector('#s-font-val');
    if (valEl) valEl.textContent = formatFontPx(sz);
    const rangeEl = settingsBodyEl.querySelector('#s-font-range');
    if (rangeEl) rangeEl.value = String(fontOffset);
    const prevEl = settingsBodyEl.querySelector('#s-font-preview');
    if (prevEl) {
      prevEl.style.fontSize = `${Math.min(22, Math.max(11, sz))}px`;
      prevEl.style.lineHeight = String(computeLineHeight());
    }
    settingsBodyEl.querySelectorAll('.theme-card').forEach((el) => {
      el.classList.toggle('active', el.dataset.theme === currentThemeKey);
    });
  }

  function setFontOffset(next) {
    fontOffset = Math.max(-4, Math.min(8, Math.round(next * 2) / 2));
    try { localStorage.setItem('swarmbox-herdr-font-offset', String(fontOffset)); } catch (_) {}
    fitAndResize();
    syncAppearanceControls();
  }

  function adjustFontOffset(delta) {
    setFontOffset(delta === 0 ? 0 : fontOffset + delta);
    focusTerminalIfDesktop();
  }

  function applyTerminalPrefs() {
    const lh = computeLineHeight();
    for (const sess of tabSessions.values()) {
      sess.term.options.lineHeight = lh;
      sess.term.options.cursorStyle = cursorStyle;
      sess.term.options.cursorBlink = cursorBlink;
      sess.term.options.scrollback = scrollbackLines;
    }
    fitAndResize();
    syncAppearanceControls();
  }

  // Pixel-perfect block-drawing & box-drawing glyphs are rendered procedurally by
  // @xterm/addon-canvas (customGlyphs: true) across full cell height (including lineHeight).
  function attachCanvasRenderer(term) {
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
  function syncJumpLive() {
    if (!btnJumpLive) return;
    const sess = activeSession();
    if (!sess || sess.hydrating) {
      if (lastJumpVisible) {
        lastJumpVisible = false;
        btnJumpLive.classList.remove('visible');
      }
      return;
    }
    const buf = sess.term.buffer && sess.term.buffer.active;
    const up = Boolean(buf && buf.type === 'normal' && buf.baseY - buf.viewportY > 2);
    if (up !== lastJumpVisible) {
      lastJumpVisible = up;
      btnJumpLive.classList.toggle('visible', up);
    }
  }
  if (btnJumpLive) {
    btnJumpLive.addEventListener('click', () => {
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

  // Responsive mobile touch drag + iOS-like momentum scroll.
  // Uses a sub-row pixel accumulator feeding relative term.scrollLines() (zero translate3d/onRender
  // phase-mismatch jitter, zero bottom blank-gap flicker, and immune to ring-buffer baseY churn).
  const TOUCH_DRAG_PX = 4;
  const TOUCH_DRAG_GAIN = 1.8;
  const TOUCH_COAST_GAIN = 1.8;
  const TOUCH_FLICK_MIN = 0.08;   // px/ms
  const TOUCH_FRICTION = 0.968;   // per 16.67ms frame (silky iOS glide)
  const TOUCH_STOP_VEL = 0.02;    // px/ms
  const TOUCH_VEL_WINDOW = 70;    // ms of active drag samples used for flick speed
  const TOUCH_MAX_VEL = 18;       // px/ms cap for chained fast flicks

  let touchId = null;
  let touchStartY = 0;
  let touchLastY = 0;
  let touchLastX = 0;
  let touchLastT = 0;
  let touchMoved = false;
  let touchStoppedCoast = false;
  let touchVel = 0;
  let touchCoastDir = 0;
  let touchChainBoost = 1;
  let touchChainT = 0;
  let touchRaf = 0;
  let touchAltAccum = 0;
  let touchSamples = [];
  let touchPendingPx = 0;
  let touchMoveRaf = 0;
  let touchSettleRaf = 0;

  function nowMs() {
    return window.performance ? performance.now() : Date.now();
  }

  function sessionRowHeight(sess) {
    try {
      const h = sess.term._core?._renderService?.dimensions?.css?.cell?.height;
      if (h && h > 4) return h;
    } catch (_) {}
    return Math.max(10, (sess.term.options.fontSize || 12) * (sess.term.options.lineHeight || 1.15));
  }

  function clearTouchOffset(sess) {
    if (!sess) return;
    sess.touchRowAccum = 0;
  }

  function touchOffsetOnScroll() {}
  function touchOffsetOnRender() {}

  // Lightweight mobile touch & optical-zoom diagnostic telemetry (fires only once per gesture / zoom settle).
  let touchDbgGesture = null;
  let touchDbgCoast = null;
  let touchDbgZoomTimer = 0;
  let touchDbgSeq = 0;
  let zoomCooldownUntil = 0;
  let zoomCooldownTimer = 0;
  let multiTouchActive = false;

  function isOpticalZoomed() {
    return Boolean(window.visualViewport && Number(window.visualViewport.scale || 1) > 1.02);
  }

  function isViewportPinchingOrBouncing() {
    const vv = window.visualViewport;
    if (!vv) return false;
    const scale = Number(vv.scale || 1);
    if (scale > 1.02 || scale < 0.99) return true;
    const layoutW = document.documentElement.clientWidth || 0;
    if ((vv.offsetTop || 0) < -1 || (vv.offsetLeft || 0) < -1) return true;
    if (layoutW > 0 && vv.width > layoutW + 2) return true;
    return false;
  }

  function sessionMouseMode(sess) {
    try {
      const m = sess && sess.term && sess.term._core && sess.term._core.coreMouseService && sess.term._core.coreMouseService.activeProtocol;
      return m ? String(m) : 'NONE';
    } catch (_) {
      return 'UNKNOWN';
    }
  }

  const TOUCH_DEBUG_ENABLED = (() => {
    try {
      return new URLSearchParams(window.location.search).get('debug_touch') === '1'
        || localStorage.getItem('swarmbox-debug-touch') === '1';
    } catch (_) {
      return false;
    }
  })();

  function logTouchDebug(kind, data) {
    if (!TOUCH_DEBUG_ENABLED) return;
    if (window.innerWidth > 960 && !(navigator.maxTouchPoints > 0)) return;
    touchDbgSeq += 1;
    const dockEl = document.querySelector('.mobile-dock');
    const vv = window.visualViewport;
    const payload = {
      seq: touchDbgSeq,
      kind,
      tab: activeId || '',
      vvScale: vv ? Number((vv.scale || 1).toFixed(3)) : 1,
      vvH: vv ? Math.round(vv.height) : window.innerHeight,
      vvW: vv ? Math.round(vv.width) : window.innerWidth,
      winH: window.innerHeight,
      layoutH: document.documentElement.clientHeight || 0,
      dockH: dockEl ? Math.round(dockEl.getBoundingClientRect().height) : 0,
      ...data,
    };
    try {
      fetch('/api/debug/touch', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
        keepalive: true,
      }).catch(() => {});
    } catch (_) {}
  }

  function applyTouchScrollPx(deltaPx) {
    const sess = activeSession();
    if (!sess || !deltaPx) return false;
    const buf = sess.term.buffer && sess.term.buffer.active;
    const mouseMode = sessionMouseMode(sess);
    const appWantsWheel = mouseMode !== 'NONE' && mouseMode !== 'UNKNOWN';

    if (buf && buf.type === 'normal' && buf.baseY > 0 && !appWantsWheel) {
      const rh = sessionRowHeight(sess);
      const prevVpY = buf.viewportY;
      // Boundary check before accumulating so coast terminates cleanly at top/bottom
      if ((deltaPx < 0 && prevVpY <= 0) || (deltaPx > 0 && prevVpY >= buf.baseY)) {
        sess.touchRowAccum = 0;
        return false;
      }
      sess.touchRowAccum = (sess.touchRowAccum || 0) + (deltaPx / rh);
      const lines = Math.trunc(sess.touchRowAccum);
      if (lines !== 0) {
        sess.touchRowAccum -= lines;
        sess.term.scrollLines(lines);
        syncJumpLive();
      }
      return true;
    }

    // Alternate screen or mouse-tracked TUI (agy, Claude Code fullscreen, vim, less, htop):
    // dispatch line-mode WheelEvents with coords clamped inside .xterm-screen so xterm's
    // CoreMouseService always resolves valid (col, row) coordinates and delivers every tick.
    const rh = sessionRowHeight(sess);
    touchAltAccum += deltaPx / Math.max(8, rh * 0.55);
    const lines = Math.trunc(touchAltAccum);
    if (lines !== 0) {
      touchAltAccum -= lines;
      const screenEl = sess.paneEl.querySelector('.xterm-screen');
      const dir = Math.sign(lines);
      const count = Math.min(12, Math.abs(lines));
      if (touchDbgGesture) touchDbgGesture.wheelSent += count;
      if (touchDbgCoast) touchDbgCoast.wheelSent += count;
      if (screenEl && typeof WheelEvent === 'function') {
        const rect = screenEl.getBoundingClientRect();
        const cx = rect.width > 16
          ? Math.max(rect.left + 8, Math.min(rect.right - 8, touchLastX || (rect.left + rect.width * 0.5)))
          : (rect.left + rect.width * 0.5);
        const cy = rect.height > 16
          ? Math.max(rect.top + 8, Math.min(rect.bottom - 8, touchLastY || (rect.top + rect.height * 0.45)))
          : (rect.top + rect.height * 0.5);
        for (let i = 0; i < count; i++) {
          screenEl.dispatchEvent(new WheelEvent('wheel', {
            deltaY: dir * 3,
            deltaMode: 1,
            clientX: cx,
            clientY: cy,
            bubbles: true,
            cancelable: true,
          }));
        }
      } else {
        sess.term.scrollLines(lines);
      }
    }
    return true;
  }

  function queueTouchScrollPx(deltaPx) {
    touchPendingPx += deltaPx;
    if (touchMoveRaf) return;
    touchMoveRaf = requestAnimationFrame(() => {
      touchMoveRaf = 0;
      const d = touchPendingPx;
      touchPendingPx = 0;
      applyTouchScrollPx(d);
    });
  }

  function flushTouchScroll() {
    if (touchMoveRaf) {
      cancelAnimationFrame(touchMoveRaf);
      touchMoveRaf = 0;
    }
    const d = touchPendingPx;
    touchPendingPx = 0;
    if (d) applyTouchScrollPx(d);
  }

  function settleTouchScroll() {
    const sess = activeSession();
    if (sess) {
      sess.touchRowAccum = 0;
      if (sess.pokeScrollbar) sess.pokeScrollbar();
    }
  }

  function flushCoastDebug(reason) {
    if (!touchDbgCoast) return;
    const sess = activeSession();
    const buf = sess && sess.term && sess.term.buffer && sess.term.buffer.active;
    const c = touchDbgCoast;
    touchDbgCoast = null;
    logTouchDebug('coast_end', {
      reason,
      frames: c.frames,
      totalPx: Math.round(c.totalPx),
      wheelSent: c.wheelSent,
      startVpY: c.startVpY,
      endVpY: buf ? buf.viewportY : -1,
      baseY: buf ? buf.baseY : -1,
      bufType: buf ? buf.type : 'none',
    });
  }

  function stopTouchCoast(caller = 'unknown') {
    if (touchRaf) {
      cancelAnimationFrame(touchRaf);
      touchRaf = 0;
      flushCoastDebug(`interrupted:${caller}`);
    }
    if (touchSettleRaf) {
      cancelAnimationFrame(touchSettleRaf);
      touchSettleRaf = 0;
    }
    touchVel = 0;
    touchAltAccum = 0;
  }

  function startTouchCoast() {
    if (touchRaf) return;
    const sess0 = activeSession();
    const buf0 = sess0 && sess0.term && sess0.term.buffer && sess0.term.buffer.active;
    touchDbgCoast = {
      frames: 0,
      totalPx: 0,
      wheelSent: 0,
      startVpY: buf0 ? buf0.viewportY : -1,
    };
    let prevT = nowMs();
    const step = () => {
      touchRaf = 0;
      if (touchId !== null) {
        flushCoastDebug('new_touch');
        return;
      }
      const t = nowMs();
      const dt = Math.min(48, Math.max(4, t - prevT));
      prevT = t;
      const deltaPx = touchVel * dt * TOUCH_COAST_GAIN;
      const progressed = applyTouchScrollPx(deltaPx);
      if (touchDbgCoast) {
        touchDbgCoast.frames += 1;
        touchDbgCoast.totalPx += deltaPx;
      }
      touchVel *= Math.pow(TOUCH_FRICTION, dt / 16.67);
      if (progressed && Math.abs(touchVel) >= TOUCH_STOP_VEL) {
        touchRaf = requestAnimationFrame(step);
      } else {
        const dir = Math.sign(touchVel);
        touchVel = 0;
        touchAltAccum = 0;
        flushCoastDebug(progressed ? 'stopped' : 'boundary');
        settleTouchScroll(dir);
      }
    };
    touchRaf = requestAnimationFrame(step);
  }

  function findTouchById(list, id) {
    for (let i = 0; i < list.length; i++) {
      if (list[i].identifier === id) return list[i];
    }
    return null;
  }

  // Speed (px/ms, positive = towards the bottom) over the last TOUCH_VEL_WINDOW ms of active drag,
  // resisting stationary touchstart dwell and final thumb-lift micro-slowdown.
  function touchFlickVelocity() {
    if (touchSamples.length < 2) return 0;
    const last = touchSamples[touchSamples.length - 1];
    let first = last;
    for (let i = touchSamples.length - 2; i >= 0; i--) {
      if (last.t - touchSamples[i].t > TOUCH_VEL_WINDOW) break;
      first = touchSamples[i];
    }
    const dt = last.t - first.t;
    const winVel = dt > 0 ? (first.y - last.y) / dt : 0;
    // Also inspect the sharpest recent segment in the same direction (in case thumb slowed on lift)
    let peakVel = winVel;
    const dir = Math.sign(winVel);
    for (let i = touchSamples.length - 1; i >= Math.max(1, touchSamples.length - 3); i--) {
      const a = touchSamples[i - 1];
      const b = touchSamples[i];
      const sdt = b.t - a.t;
      if (sdt >= 4 && sdt <= 65) {
        const sv = (a.y - b.y) / sdt;
        if ((dir === 0 || Math.sign(sv) === dir) && Math.abs(sv) > Math.abs(peakVel)) {
          peakVel = sv;
        }
      }
    }
    return Math.abs(peakVel) > Math.abs(winVel) ? (winVel * 0.45 + peakVel * 0.55) : winVel;
  }

  // Capture-phase touch interception on termWrapEl:
  // xterm.js registers its own bubble-phase touchstart/touchmove handlers on `.xterm` that call
  // stopPropagation() (swallowing 1-finger momentum scrolls in the middle of scrollback) and
  // preventDefault() without checking touches.length === 1 (killing iOS 2-finger pinch-zoom!).
  // Intercepting in CAPTURE phase and calling stopPropagation() completely bypasses xterm's
  // primitive touch handler so:
  //   - 2-finger pinch-zoom & zoomed 1-finger pans go 100% natively to the browser compositor
  //   - 1-finger scrolls run our sub-row GPU + iOS momentum engine everywhere in the buffer
  //   - single taps still open the keyboard (except tapping to stop an active coast!)
  window.addEventListener('touchend', (e) => {
    if (e.touches.length === 0) multiTouchActive = false;
  }, { passive: true });
  window.addEventListener('touchcancel', () => {
    multiTouchActive = false;
  }, { passive: true });

  termWrapEl.addEventListener('touchstart', (e) => {
    if (e.target && e.target.closest && e.target.closest('button, a, input, textarea')) return;
    // Block xterm's built-in touchstart/touchmove handler (which otherwise swallows scrolls and kills pinch).
    e.stopPropagation();
    const wasCoasting = Boolean(touchRaf);
    stopTouchCoast('touchstart');
    if (e.touches.length >= 2) {
      if (touchMoved) { flushTouchScroll(); settleTouchScroll(); }
      touchId = null;
      touchMoved = false;
      touchStoppedCoast = false;
      multiTouchActive = true;
      zoomCooldownUntil = Date.now() + 650;
      touchDbgGesture = null;
      return;
    }
    // Fresh 1-finger touch: never allow a stale multiTouchActive flag from a Safari pinch to stick.
    multiTouchActive = false;
    touchStoppedCoast = wasCoasting;
    if (isOpticalZoomed() || isViewportPinchingOrBouncing()) {
      touchId = null;
      touchMoved = false;
      touchDbgGesture = null;
      return;
    }
    if (e.touches.length === 1) {
      const t = e.touches[0];
      const sess = activeSession();
      const buf = sess && sess.term && sess.term.buffer && sess.term.buffer.active;
      const curTab = terminals.find((x) => x.address === activeId);
      touchId = t.identifier;
      touchStartY = t.clientY;
      touchLastY = t.clientY;
      touchLastX = t.clientX;
      touchLastT = nowMs();
      touchMoved = false;
      touchVel = 0;
      touchAltAccum = 0;
      touchSamples = [{ t: touchLastT, y: t.clientY }];
      touchDbgGesture = {
        startT: touchLastT,
        startY: t.clientY,
        moves: 0,
        nonCancelable: 0,
        wheelSent: 0,
        bufType: buf ? buf.type : 'none',
        baseY: buf ? buf.baseY : -1,
        startVpY: buf ? buf.viewportY : -1,
        mouseMode: sessionMouseMode(sess),
        agent: (curTab && curTab.labels && curTab.labels['swarmbox.agent']) || (curTab && curTab.agent) || '',
      };
    } else {
      touchId = null;
      touchMoved = false;
    }
  }, { capture: true, passive: true });

  termWrapEl.addEventListener('touchmove', (e) => {
    if (e.target && e.target.closest && e.target.closest('button, a, input, textarea')) return;
    // Always stop propagation so xterm's built-in handleTouchMove NEVER runs (neither on scroll nor on pinch!).
    e.stopPropagation();
    if (e.touches.length >= 2) {
      multiTouchActive = true;
      zoomCooldownUntil = Date.now() + 650;
      touchId = null;
      return;
    }
    if (multiTouchActive || isOpticalZoomed() || isViewportPinchingOrBouncing()) {
      touchId = null;
      return;
    }
    if (touchId === null || e.touches.length !== 1) {
      touchId = null;
      return;
    }
    const t = findTouchById(e.touches, touchId);
    if (!t) return;
    if (touchDbgGesture) {
      touchDbgGesture.moves += 1;
      if (!e.cancelable) touchDbgGesture.nonCancelable += 1;
    }
    // Wait until vertical motion exceeds TOUCH_DRAG_PX BEFORE calling preventDefault() so
    // finger-1 micro-jitter while finger-2 lands never aborts native iOS pinch-zoom!
    if (!touchMoved) {
      if (Math.abs(t.clientY - touchStartY) < TOUCH_DRAG_PX) return;
      touchMoved = true;
      touchSamples = [{ t: touchLastT, y: touchLastY }];
    }
    if (e.cancelable) e.preventDefault();
    const tt = nowMs();
    const dy = touchLastY - t.clientY;
    touchSamples.push({ t: tt, y: t.clientY });
    while (touchSamples.length > 2 && tt - touchSamples[0].t > TOUCH_VEL_WINDOW * 2) touchSamples.shift();
    applyTouchScrollPx(dy * TOUCH_DRAG_GAIN);
    touchLastY = t.clientY;
    touchLastX = t.clientX;
    touchLastT = tt;
  }, { capture: true, passive: false });

  termWrapEl.addEventListener('touchcancel', () => {
    const g = touchDbgGesture;
    touchDbgGesture = null;
    multiTouchActive = false;
    touchId = null;
    touchMoved = false;
    touchStoppedCoast = false;
    stopTouchCoast('touchcancel');
    flushTouchScroll();
    settleTouchScroll();
    if (g && g.moves > 0) {
      const sess = activeSession();
      const buf = sess && sess.term && sess.term.buffer && sess.term.buffer.active;
      logTouchDebug('scroll_cancel', {
        agent: g.agent,
        bufType: g.bufType,
        baseY: g.baseY,
        startVpY: g.startVpY,
        endVpY: buf ? buf.viewportY : -1,
        mouseMode: g.mouseMode,
        moves: g.moves,
        nonCancelable: g.nonCancelable,
        wheelSent: g.wheelSent,
        dt: Math.round(nowMs() - g.startT),
      });
    }
  }, { capture: true, passive: true });

  termWrapEl.addEventListener('touchend', (e) => {
    if (e.target && e.target.closest && e.target.closest('button, a, input, textarea')) return;
    if (multiTouchActive) {
      e.stopPropagation();
      if (e.touches.length === 0) multiTouchActive = false;
      return;
    }
    const stoppedCoast = touchStoppedCoast;
    touchStoppedCoast = false;
    if ((touchMoved || stoppedCoast) && e.cancelable) {
      e.preventDefault();
      e.stopPropagation();
    }
    const moved = touchMoved;
    const now = nowMs();
    const rawVel = moved ? touchFlickVelocity() : 0;
    const flick = moved && Math.abs(rawVel) >= TOUCH_FLICK_MIN && (now - touchLastT) < 110;
    const g = touchDbgGesture;
    touchDbgGesture = null;
    touchId = null;
    touchMoved = false;
    flushTouchScroll();
    let appliedVel = 0;
    if (flick) {
      const dir = Math.sign(rawVel);
      // Chained flicks in the same direction within 700ms build speed naturally (like iOS/Android)
      if (dir === touchCoastDir && (now - touchChainT) < 700) {
        touchChainBoost = Math.min(2.5, touchChainBoost + 0.45);
      } else {
        touchChainBoost = 1;
      }
      touchCoastDir = dir;
      touchChainT = now;
      const speed = Math.abs(rawVel);
      const accel = 1.2 + Math.min(2.4, Math.max(0, speed - 0.15) * 1.15);
      touchVel = Math.max(-TOUCH_MAX_VEL, Math.min(TOUCH_MAX_VEL, rawVel * accel * touchChainBoost));
      appliedVel = touchVel;
      startTouchCoast();
    } else {
      touchVel = 0;
      touchChainBoost = 1;
      if (moved) settleTouchScroll();
    }
    if (g && (moved || g.moves >= 1)) {
      const sess = activeSession();
      const buf = sess && sess.term && sess.term.buffer && sess.term.buffer.active;
      logTouchDebug('scroll_end', {
        agent: g.agent,
        bufType: g.bufType,
        baseY: g.baseY,
        startVpY: g.startVpY,
        endVpY: buf ? buf.viewportY : -1,
        mouseMode: g.mouseMode,
        dy: Math.round(g.startY - touchLastY),
        dt: Math.round(now - g.startT),
        moves: g.moves,
        nonCancelable: g.nonCancelable,
        rawVel: Number(rawVel.toFixed(3)),
        appliedVel: Number(appliedVel.toFixed(3)),
        flick,
        chainBoost: Number(touchChainBoost.toFixed(2)),
        wheelSent: g.wheelSent,
      });
    }
  }, { capture: true, passive: false });

  function applyTheme(name, persist = false) {
    const key = THEMES[name] ? name : 'purple-glow';
    currentThemeKey = key;
    const t = THEMES[key];
    for (const [k, v] of Object.entries(t.css)) {
      document.documentElement.style.setProperty(k, v);
    }
    for (const sess of tabSessions.values()) {
      sess.term.options.theme = t.xterm;
    }
    const meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.setAttribute('content', t.css['--bg']);
    if (themeSwatchEl) {
      themeSwatchEl.style.background = t.css['--accent'];
      themeSwatchEl.style.boxShadow = `0 0 8px ${t.css['--accent-glow']}`;
    }
    try { localStorage.setItem('swarmbox-herdr-theme', key); } catch (_) {}
    syncAppearanceControls();
    if (persist) {
      fetch('/api/theme', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ theme: key }),
      }).catch(() => {});
    }
  }

  const savedTheme = (() => {
    try { return localStorage.getItem('swarmbox-herdr-theme') || 'purple-glow'; } catch (_) { return 'purple-glow'; }
  })();
  applyTheme(savedTheme, false);

  function isSessionAtBottom(sess) {
    if (!sess) return true;
    try {
      const buf = sess.term.buffer && sess.term.buffer.active;
      if (buf && typeof buf.baseY === 'number' && typeof buf.viewportY === 'number') {
        return (buf.baseY - buf.viewportY) <= 1;
      }
    } catch (_) {}
    return true;
  }

  function syncStageLoader() {
    if (!termStageLoaderEl) return;
    const sess = activeSession();
    const busy = Boolean(sess && (sess.resizing || sess.hydrating || sess.revealPending));
    // During initial page load, #sb-boot already covers the viewport; once dismissed,
    // use the stage-scoped SwarmBox loader whenever a resize or cold tab hydration runs.
    const show = bootDismissed && (busy || termWrapEl.classList.contains('term-loading'));
    termStageLoaderEl.classList.toggle('visible', show);
  }

  function isSessionTui(sess) {
    if (!sess) return false;
    try {
      const buf = sess.term && sess.term.buffer && sess.term.buffer.active;
      if (buf && buf.type === 'alternate') return true;
    } catch (_) {}
    const t = terminals.find((x) => x.address === sess.address);
    if (!t) return false;
    if (tabAgentBadge(t)) return true;
    const fg = String((t.foreground && t.foreground.name) || '').toLowerCase().trim();
    if (fg && !SHELL_NAMES.has(fg)) return true;
    const nm = String(t.name || '').toLowerCase();
    if (/^(?:claude|agy|antigravity|opencode|gemini|codex)\b/.test(nm)) return true;
    return false;
  }

  function finishResizeCycle(sess, seq = null) {
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
          if (activeId === sess.address) {
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

  function beginResizeCycle(sess) {
    if (!sess || sess.hydrating) return;
    if (!sess.resizing) {
      sess.resizeWasAtBottom = isSessionAtBottom(sess);
      sess.resizeChunks = [];
      sess.resizing = true;
      sess.revealPending = false;
      sess.paneEl.classList.add('resizing');
    }
    if (activeId === sess.address) syncStageLoader();
    if (sess.resizeFallbackTimer) clearTimeout(sess.resizeFallbackTimer);
    const fallbackMs = isSessionTui(sess) ? 1800 : 600;
    sess.resizeFallbackTimer = setTimeout(() => finishResizeCycle(sess), fallbackMs);
  }

  function fitSession(sess, sendResize = true) {
    if (!sess) return;
    if (isViewportPinchingOrBouncing() || multiTouchActive || Date.now() < zoomCooldownUntil) {
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
      sess.fitAddon.fit();
      sess.needsFit = false;
      const changed = sess.term.cols !== sess.lastCols || sess.term.rows !== sess.lastRows;
      if (sendResize && changed && sess.ws && sess.ws.readyState === 1) {
        const prevCols = sess.lastCols;
        const prevRows = sess.lastRows;
        sess.lastCols = sess.term.cols;
        sess.lastRows = sess.term.rows;
        const isTui = isSessionTui(sess);
        sess.resizeSeq = (sess.resizeSeq || 0) + 1;
        if (!sess.hydrating) {
          sess.resizeWasAtBottom = wasAtBottom;
          sess.resizeLinesFromBottom = linesFromBottom;
          sess.resizeAwaitingServer = true;
          beginResizeCycle(sess);
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
          tui: isTui,
        }));
      } else if (sendResize && !changed && sess.resizing && !sess.resizeAwaitingServer) {
        // Pre-armed resize cycle (e.g. panel toggle) produced identical cols/rows: reveal cleanly.
        finishResizeCycle(sess);
      }
    } catch (_) {}
  }

  let fitRaf = 0;
  let mobileFitDebounce = 0;
  function fitAndResize() {
    if (isViewportPinchingOrBouncing() || multiTouchActive || Date.now() < zoomCooldownUntil) return;
    syncAppearanceControls();
    const active = activeSession();
    for (const sess of tabSessions.values()) {
      if (sess === active) fitSession(sess, true);
      else sess.needsFit = true;
    }
  }
  function scheduleFit() {
    if (isViewportPinchingOrBouncing() || multiTouchActive || Date.now() < zoomCooldownUntil) return;
    if (window.innerWidth <= 860) {
      // Debounce all mobile fit triggers (ResizeObserver, window.resize, keyboard slide animation)
      // so a 250ms iOS keyboard slide sends 1 clean final SIGWINCH instead of 5 intermediate ones.
      clearTimeout(mobileFitDebounce);
      mobileFitDebounce = setTimeout(() => {
        mobileFitDebounce = 0;
        if (!isViewportPinchingOrBouncing() && !multiTouchActive && Date.now() >= zoomCooldownUntil) {
          fitAndResize();
        }
      }, 160);
      return;
    }
    if (fitRaf) return;
    fitRaf = requestAnimationFrame(() => {
      fitRaf = 0;
      fitAndResize();
    });
  }

  // Wait for self-hosted JetBrains Mono before the first PTY attach so initial cols/rows
  // match exact glyph metrics on frame 0 (eliminating post-boot font-metric reflow).
  let fontsSettled = false;
  function flushAllTextureAtlases() {
    for (const s of tabSessions.values()) {
      try { s.term.clearTextureAtlas(); } catch (_) {}
    }
  }
  const fontsReadyPromise = (document.fonts && document.fonts.ready)
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
  if (document.fonts && typeof document.fonts.addEventListener === 'function') {
    document.fonts.addEventListener('loadingdone', () => {
      flushAllTextureAtlases();
    });
  }

  const ro = new ResizeObserver(scheduleFit);
  ro.observe(termWrapEl);
  window.addEventListener('resize', scheduleFit);

  // Mobile keyboard & terminal-keys state: user-pinned keys never disappear mid-tap, and the
  // open Sysop sheet tracks visualViewport height/offsetTop cleanly when the OS keyboard rises.
  let mobileKeysPinned = false;
  let mobileKeysDismissedForKb = false;
  let mobileKbOpen = false;

  function syncMobileKeys() {
    const isMob = window.innerWidth <= 860;
    const sheetOpen = appEl.dataset.mobileSysop === '1';
    const focusSysop = document.activeElement === goalInputEl;
    const kbTerm = isMob && mobileKbOpen && !sheetOpen && !focusSysop;
    const kbSysop = isMob && mobileKbOpen && (sheetOpen || focusSysop);
    appEl.dataset.kbTerm = kbTerm ? '1' : '0';
    appEl.dataset.kbSysop = kbSysop ? '1' : '0';
    const showKeys = isMob && !sheetOpen && (mobileKeysPinned || (kbTerm && !mobileKeysDismissedForKb));
    appEl.dataset.mobileKeys = showKeys ? '1' : '0';
    if (btnMobileKeys) btnMobileKeys.dataset.on = showKeys ? '1' : '0';
  }

  let baseMobileH = document.documentElement.clientHeight || window.innerHeight || 0;
  let lastAppliedVvH = 0;
  let lastLoggedZoomScale = 1;
  function syncViewport(fromScroll = false) {
    if (!window.visualViewport) {
      syncMobileKeys();
      return;
    }
    const vv = window.visualViewport;
    const vvScale = Number(vv.scale || 1);
    const zoomed = vvScale > 1.02;
    const pinchingOrBouncing = isViewportPinchingOrBouncing();
    appEl.dataset.zoomed = zoomed ? '1' : '0';
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
      zoomCooldownUntil = Date.now() + 650;
      mobileKbOpen = false;
      syncMobileKeys();
      clearTimeout(zoomCooldownTimer);
      zoomCooldownTimer = setTimeout(() => syncViewport(false), 680);
      return;
    }
    const layoutH = document.documentElement.clientHeight || window.innerHeight || 0;
    const vvH = layoutH > 0 ? Math.min(layoutH, Math.round(vv.height)) : Math.round(vv.height);
    const vvTop = Math.max(0, Math.round(vv.offsetTop || 0));
    appEl.style.setProperty('--vv-h', `${vvH}px`);
    appEl.style.setProperty('--vv-top', `${vvTop}px`);
    appEl.style.height = `${vvH}px`;
    if (window.innerWidth <= 860) {
      if (layoutH > 0 && vvH >= layoutH - 20) baseMobileH = layoutH;
      else if (vvH > baseMobileH && (layoutH === 0 || vvH <= layoutH)) baseMobileH = vvH;
      const wasKb = mobileKbOpen;
      mobileKbOpen = (baseMobileH - vvH) > 110;
      if (wasKb && !mobileKbOpen) mobileKeysDismissedForKb = false;
    } else {
      mobileKbOpen = false;
      mobileKeysDismissedForKb = false;
    }
    syncMobileKeys();
    if (appEl.dataset.kbSysop === '1' && appEl.dataset.mobileSysop === '1') {
      requestAnimationFrame(() => { sysopFeedEl.scrollTop = sysopFeedEl.scrollHeight; });
    }
    const hChanged = Math.abs(vvH - lastAppliedVvH) >= 2;
    lastAppliedVvH = vvH;
    if (!fromScroll && hChanged && Date.now() >= zoomCooldownUntil) {
      scheduleFit();
    }
  }
  if (window.visualViewport) {
    window.visualViewport.addEventListener('resize', () => syncViewport(false));
    window.visualViewport.addEventListener('scroll', () => syncViewport(true));
    syncViewport(false);
  }

  function focusTerminalIfDesktop() {
    if (settingsOpen) return;
    const sess = activeSession();
    if (sess && window.innerWidth > 860 && document.activeElement !== goalInputEl) {
      sess.term.focus();
    }
  }

  const MOUSE_MOTION_INPUT_RE = /^(?:\x1b\[<[0-9;]+[Mm]|\x1b\[M[\s\S]{3})+$/;

  function sendPtyInput(data, targetSession = null) {
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

  // Clicking anywhere on the terminal canvas (without a drag selection) restores keyboard focus
  // and recovers a dropped PTY socket immediately.
  termWrapEl.addEventListener('mouseup', () => {
    if (settingsOpen) return;
    const sess = activeSession();
    if (!sess || window.innerWidth <= 860) return;
    if (sess.term.hasSelection() || (window.getSelection && window.getSelection().toString())) return;
    sess.term.focus();
    if (!sess.ws || sess.ws.readyState === 2 || sess.ws.readyState === 3) {
      openSessionSocket(sess, { silent: true, reset: true });
    }
  });

  let termToastTimer = null;
  function showTermToast(msg, tone = '', ms = 2600) {
    if (!termToastEl) return;
    clearTimeout(termToastTimer);
    if (!msg) {
      termToastEl.classList.remove('visible');
      return;
    }
    termToastEl.textContent = msg;
    termToastEl.dataset.tone = tone;
    termToastEl.classList.add('visible');
    if (ms > 0) {
      termToastTimer = setTimeout(() => termToastEl.classList.remove('visible'), ms);
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

  function extractClipboardImages(dt) {
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

  async function uploadAndPasteImages(blobs, targetSession = null) {
    const sess = targetSession || activeSession();
    if (!sess || !blobs || blobs.length === 0) return;
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

  // Drag & drop images directly onto the terminal canvas
  let dragDepth = 0;
  function hasDraggedFiles(e) {
    const types = e.dataTransfer && e.dataTransfer.types;
    if (!types) return false;
    return Array.from(types).includes('Files');
  }
  termWrapEl.addEventListener('dragenter', (e) => {
    if (!hasDraggedFiles(e)) return;
    e.preventDefault();
    dragDepth += 1;
    if (termDropOverlayEl) termDropOverlayEl.classList.add('visible');
  });
  termWrapEl.addEventListener('dragover', (e) => {
    if (!hasDraggedFiles(e)) return;
    e.preventDefault();
    if (e.dataTransfer) e.dataTransfer.dropEffect = 'copy';
  });
  termWrapEl.addEventListener('dragleave', (e) => {
    if (!hasDraggedFiles(e)) return;
    dragDepth = Math.max(0, dragDepth - 1);
    if (dragDepth === 0 && termDropOverlayEl) termDropOverlayEl.classList.remove('visible');
  });
  termWrapEl.addEventListener('drop', (e) => {
    dragDepth = 0;
    if (termDropOverlayEl) termDropOverlayEl.classList.remove('visible');
    const imgs = extractClipboardImages(e.dataTransfer);
    if (imgs.length === 0) return;
    e.preventDefault();
    e.stopPropagation();
    uploadAndPasteImages(imgs, activeSession());
  });

  // Fallback paste listener when focus slipped to document.body while pasting a screenshot
  document.addEventListener('paste', (e) => {
    lastNativePasteTs = Date.now();
    if (settingsOpen || isRealFormField(e.target)) return;
    const imgs = extractClipboardImages(e.clipboardData);
    if (imgs.length === 0) return;
    e.preventDefault();
    e.stopPropagation();
    uploadAndPasteImages(imgs, activeSession());
  });

  // Auto-heal dropped WebSockets when returning to the browser tab or waking from sleep
  function ensureConnectionsAlive() {
    if (!eventsWs || eventsWs.readyState === 2 || eventsWs.readyState === 3) {
      connectEvents();
    }
    const sess = activeSession();
    if (sess && (!sess.ws || sess.ws.readyState === 2 || sess.ws.readyState === 3)) {
      openSessionSocket(sess, { silent: true, reset: true });
    }
  }
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') ensureConnectionsAlive();
  });
  window.addEventListener('focus', () => {
    ensureConnectionsAlive();
  });
  window.addEventListener('online', () => {
    ensureConnectionsAlive();
  });

  // Desktop keyboard shortcuts (100% aligned with Terminal Cockpit:
  // Alt+1..9 tabs, Alt+N shell, Alt+B sidebar, Alt+S Sysop, Alt+G goal, Alt+T cycle theme, Alt+-/=/0 font)
  // Matches e.code first so macOS Option symbols (¡™£˜∫ß©†) and non-US layouts work reliably.
  const THEME_KEYS = Object.keys(THEMES);

  function matchAltShortcut(e) {
    if (!e || !e.altKey || e.ctrlKey || e.metaKey) return null;
    const code = e.code || '';
    const key = e.key || '';
    const low = key.toLowerCase();

    if (/^Digit[1-9]$/.test(code)) return { action: 'tab', idx: Number(code.slice(5)) - 1 };
    if (/^Numpad[1-9]$/.test(code)) return { action: 'tab', idx: Number(code.slice(6)) - 1 };
    if (key >= '1' && key <= '9') return { action: 'tab', idx: Number(key) - 1 };

    if (code === 'KeyN' || low === 'n') return { action: 'new-shell' };
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
    if (settingsOpen) return;
    if (sc.action === 'tab') {
      if (terminals[sc.idx]) {
        if (activeId !== terminals[sc.idx].address) connectPty(terminals[sc.idx].address);
        else focusTerminalIfDesktop();
      }
      return;
    }
    if (sc.action === 'new-shell') { spawnTab('shell'); return; }
    if (sc.action === 'rename') { if (activeId) startInlineRename(activeId); return; }
    if (sc.action === 'sysop') { toggleDesktopSysop(); return; }
    if (sc.action === 'sidebar') { toggleSidebar(); return; }
    if (sc.action === 'goal') {
      if (window.innerWidth > 860 && appEl.dataset.sysopOpen !== '1') toggleDesktopSysop();
      else if (window.innerWidth <= 860) setMobileSysop(true);
      goalInputEl.focus();
      return;
    }
    if (sc.action === 'theme') {
      const idx = THEME_KEYS.indexOf(currentThemeKey);
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
    if (popoverOpen) {
      if (e.key === 'Escape') {
        e.preventDefault();
        e.stopPropagation();
        closePopover();
        return;
      }
      if (popoverKeyHandler && popoverKeyHandler(e) === true) {
        return;
      }
      return;
    }
    if (settingsOpen) {
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

  const AGENT_APP_LABELS = {
    antigravity: 'agy',
    agy: 'agy',
    claude: 'claude',
    'claude-code': 'claude',
    codex: 'codex',
    opencode: 'opencode',
    gemini: 'gemini',
  };
  const SHELL_NAMES = new Set(['bash', 'sh', 'zsh', 'dash', 'fish', '-bash', '-sh', '-zsh']);

  function tabAgentBadge(t) {
    if (!t) return '';
    const app = String((t.status && t.status.app) || '').toLowerCase();
    if (AGENT_APP_LABELS[app]) return AGENT_APP_LABELS[app];
    const fg = String((t.foreground && t.foreground.name) || '').toLowerCase();
    if (AGENT_APP_LABELS[fg]) return AGENT_APP_LABELS[fg];
    return '';
  }

  function cleanStatusText(raw) {
    return String(raw || '')
      .replace(/\*\*([^*]+)\*\*/g, '$1')
      .replace(/`([^`]+)`/g, '$1')
      .replace(/\s+/g, ' ')
      .trim();
  }

  function tabTitleParts(t) {
    if (!t) return { title: 'shell', pill: '' };
    const customTitle = String((t.labels && t.labels['swarmbox.title']) || '').trim();
    const rawName = String(t.name || '').trim();
    const isGenericShell = !rawName || /^shell(?:-\d+)?$/i.test(rawName);
    const badge = tabAgentBadge(t);
    if (customTitle) {
      const pill = badge && !customTitle.toLowerCase().includes(badge) ? badge : '';
      return { title: customTitle, pill };
    }
    const pill = badge && (isGenericShell || !rawName.toLowerCase().includes(badge)) ? badge : '';

    if (!isGenericShell) {
      return { title: rawName, pill };
    }

    const cwd = String((t.foreground && t.foreground.cwd) || t.cwd || '').replace(/\/+$/, '');
    if (cwd && cwd !== '/home/agent' && cwd !== '/') {
      const base = cwd.slice(cwd.lastIndexOf('/') + 1);
      if (base) return { title: base, pill };
    }

    const fg = String((t.foreground && t.foreground.name) || '').trim();
    const fgLow = fg.toLowerCase();
    if (fg && !SHELL_NAMES.has(fgLow) && fgLow !== pill) {
      return { title: fg, pill };
    }

    return { title: rawName || 'shell', pill };
  }

  function tabDisplayName(t) {
    return tabTitleParts(t).title;
  }

  function tabState(t) {
    return (t && t.status && t.status.state) || 'idle';
  }

  function tabSubtitle(t) {
    const st = t && t.status;
    const msg = cleanStatusText(st && st.msg);
    const cwd = (t && t.foreground && t.foreground.cwd) || (t && t.cwd) || '';
    const shortCwd = shortDisplayPath(cwd);

    if (st && st.state === 'blocked') return `blocked · ${msg || st.kind || 'needs input'}`;
    if (st && st.state === 'working') {
      const pct = typeof st.progress === 'number' ? `${st.progress}% ` : '';
      return `${pct}${msg || shortCwd || 'working…'}`;
    }
    if (st && st.state === 'done') return msg ? `✓ ${msg}` : '✓ done';
    if (st && st.state === 'error') return `✕ ${msg || 'error'}`;
    if (msg) return msg;
    if (shortCwd) return shortCwd;
    return (t && t.title) || (t && t.address) || '';
  }

  function concatChunks(chunks) {
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

  function disposeSession(address) {
    const sess = tabSessions.get(address);
    if (!sess) return;
    tabSessions.delete(address);
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

  function evictOldestSessionIfNeeded() {
    while (tabSessions.size >= MAX_TAB_SESSIONS) {
      let oldestAddr = null;
      let oldestTs = Infinity;
      for (const [addr, sess] of tabSessions.entries()) {
        if (addr === activeId) continue;
        if (sess.lastUsed < oldestTs) {
          oldestTs = sess.lastUsed;
          oldestAddr = addr;
        }
      }
      if (!oldestAddr) break;
      disposeSession(oldestAddr);
    }
  }

  function createTabSession(address) {
    evictOldestSessionIfNeeded();
    const paneEl = document.createElement('div');
    paneEl.className = 'term-pane hydrating';
    paneEl.dataset.addr = address;
    terminalHostEl.appendChild(paneEl);

    const term = new window.Terminal({
      fontFamily: "'JetBrains Mono', 'SwarmBox Symbols', 'PureNerdFont', ui-monospace, SFMono-Regular, Menlo, Consolas, monospace",
      fontSize: computeFontSize(),
      lineHeight: computeLineHeight(),
      fontWeight: '400',
      fontWeightBold: '600',
      customGlyphs: true,
      cursorStyle,
      cursorBlink,
      scrollback: scrollbackLines,
      macOptionIsMeta: true,
      allowProposedApi: true,
      theme: (THEMES[currentThemeKey] || THEMES['purple-glow']).xterm,
    });
    const fitAddon = new window.FitAddon.FitAddon();
    term.loadAddon(fitAddon);
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

    // Smart terminal selection copy:
    // Rejoins lines that were soft-wrapped by xterm, herdr-core attach hydration (\r\n at col N),
    // or AI TUI padded/bordered/shaded code blocks (agy, claude, codex, opencode), while preserving
    // intentional multi-line scripts, blank lines, lists, prompts, and explicit `\` continuations.
    const RULE_LINE_RE = /^[\s─━═┄┅┈┉\-=_·•]+$/;
    const LIST_OR_PROMPT_RE = /^(?:[-*+•]\s|\d+[.)]\s|#{1,6}\s|>\s|\$\s|❯\s|>>>\s)/;
    const RIGHT_BORDER_RE = /[│┃║▕]/;
    const UNIFORM_LEFT_GUTTER_RE = /^(\s*[│┃║▎▏]\s?)/;
    const UNIFORM_RIGHT_GUTTER_RE = /(\s?[│┃║▕]\s*)$/;

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
        if (RIGHT_BORDER_RE.test(full[c])) {
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

    function looksLikeMidTokenWrap(curText, nextCore) {
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

    function getSmartSelection(termObj) {
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
      if (nonEmpty.length >= 2 && nonEmpty.every((r) => UNIFORM_LEFT_GUTTER_RE.test(r.trimmedSlice))) {
        const allRightBar = nonEmpty.every((r) => UNIFORM_RIGHT_GUTTER_RE.test(r.trimmedSlice));
        for (const r of rows) {
          const m = r.rawSlice.match(UNIFORM_LEFT_GUTTER_RE);
          if (m) {
            r.x0 += m[1].length;
            r.rawSlice = r.rawSlice.slice(m[1].length);
          }
          if (allRightBar) {
            r.rawSlice = r.rawSlice.replace(UNIFORM_RIGHT_GUTTER_RE, '');
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

        // 3. AI TUI padded / bordered / shaded soft-wrap (agy, claude, codex, opencode)
        const boxRight = Math.min(curRow.visualRightCol, nearbyWrapCol);
        const effectiveWrap =
          blockMaxEnd >= boxRight - 8 && blockMaxEnd < boxRight
            ? Math.min(boxRight, Math.max(blockMaxEnd + 1, boxRight - 6))
            : Math.max(40, boxRight - 2);

        const curStartsPrompt = /^(?:\$|❯|#)\s/.test(curText.trimStart());
        const sameIndent = Math.abs(next.indent - curRow.indent) <= 2 || (curStartsPrompt && next.indent <= curRow.indent + 4);
        const nextFirstToken = (nextCore.match(/^\S+/) || [''])[0];
        const endsHardBreak = /(?:\\|;|{|})$/.test(curText) && curRow.contentEndCol < effectiveWrap - 1;

        const tuiWrapped =
          curText.length > 0 &&
          nextCore.length > 0 &&
          !RULE_LINE_RE.test(curText) &&
          !RULE_LINE_RE.test(nextCore) &&
          sameIndent &&
          !LIST_OR_PROMPT_RE.test(nextCore) &&
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
    // and paste its path via Bracketed Paste so Claude Code, agy, OpenCode, Codex, and bash attach it.
    paneEl.addEventListener('paste', (ev) => {
      lastNativePasteTs = Date.now();
      const imgs = extractClipboardImages(ev.clipboardData);
      if (imgs.length === 0) return;
      ev.preventDefault();
      ev.stopPropagation();
      uploadAndPasteImages(imgs, sess);
    }, true);

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

    // Copy/paste & Alt shortcuts:
    // - Ctrl+C / Ctrl+Shift+C copies with smart wrapped-line unwrapping when text is selected.
    // - Ctrl+V lets the browser fire its native `paste` event on xterm-helper-textarea so xterm.js
    //   runs term.paste() with full Bracketed Paste (\x1b[200~ ... \x1b[201~) — and our capture
    //   paste listener above intercepts clipboard images cleanly with zero double-paste. If a browser
    //   suppresses native `paste` on <textarea> for image-only clipboards, a 70ms fallback checks
    //   navigator.clipboard.read() for images.
    // - Ctrl+Shift+V checks Clipboard API for images first, otherwise pastes text via term.paste().
    term.attachCustomKeyEventHandler((ev) => {
      if (ev.type !== 'keydown') return true;
      if (matchAltShortcut(ev)) return false;
      const key = ev.key.toLowerCase();
      if (ev.ctrlKey && !ev.altKey && !ev.metaKey && key === 'c' && term.hasSelection()) {
        ev.preventDefault();
        copyTextSilently(getSmartSelection(term));
        term.clearSelection();
        return false;
      }
      if (ev.ctrlKey && !ev.altKey && !ev.metaKey && key === 'v') {
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
      if (activeId === sess.address) syncJumpLive();
    };
    // The scrollbar is an overlay: its thumb shows while you look back through history, for a moment after you
    // scroll, and while the mouse is at the right edge (to grab it); at the live bottom it is hidden. A program that
    // draws inline (AGY) keeps scrollback, so its bar used to be always on, while one in the alternate screen
    // (Claude Code) has no scrollback and never had one: now both rest without a bar.
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
    term.onRender(() => { touchOffsetOnRender(sess); if (touchId === null && !touchRaf) onScrollMaybe(); });
    term.onResize(() => clearTouchOffset(sess));
    const vp = paneEl.querySelector('.xterm-viewport');
    if (vp) vp.addEventListener('scroll', () => { if (touchId === null && !touchRaf) { onScrollMaybe(); syncScrollbar(); } }, { passive: true });

    tabSessions.set(address, sess);
    return sess;
  }

  function openSessionSocket(sess, opts = {}) {
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
    if (activeId === sess.address) {
      ptyConnected = false;
      syncConnPill();
    }

    // Keep pane invisible while server-coalesced initial history burst hydrates so users never
    // see a fast scroll-from-top-to-bottom replay on initial load, first visit, or reconnect.
    sess.hydrating = true;
    sess.hydrationChunks = [];
    sess.paneEl.classList.add('hydrating');
    if (activeId === sess.address) {
      termWrapEl.classList.add('term-loading');
      syncStageLoader();
    }

    if (opts.reset) {
      sess.term.reset();
    }
    const gen = (sess.socketGen || 0) + 1;
    sess.socketGen = gen;

    const startAttach = () => {
      if (sess.socketGen !== gen || tabSessions.get(sess.address) !== sess) return;
      try { sess.term.clearTextureAtlas(); } catch (_) {}
      fitSession(sess, false);
      const initCols = sess.term.cols || 100;
      const initRows = sess.term.rows || 30;
      sess.lastCols = initCols;
      sess.lastRows = initRows;

      const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
      const tuiFlag = isSessionTui(sess) ? '&tui=1' : '';
      const wsUrl = `${proto}//${location.host}/ws/pty/${encodeURIComponent(sess.address)}?cols=${initCols}&rows=${initRows}${tuiFlag}`;
      const ws = new WebSocket(wsUrl);
      ws.binaryType = 'arraybuffer';
      sess.ws = ws;

      const finishHydration = () => {
        if (!sess.hydrating) return;
        sess.hydrating = false;
        sess.revealPending = true;
        if (sess.fallbackTimer) {
          clearTimeout(sess.fallbackTimer);
          sess.fallbackTimer = null;
        }
        const batch = sess.hydrationChunks;
        sess.hydrationChunks = [];
        const reveal = () => {
          if (sess.ws !== ws) return;
          const vp = sess.paneEl.querySelector('.xterm-viewport');
          try { sess.term.scrollToBottom(); } catch (_) {}
          if (vp) vp.scrollTop = vp.scrollHeight;
          // Two rAFs guarantee xterm.js Viewport._sync() & Canvas2D finish painting BEFORE reveal
          requestAnimationFrame(() => {
            if (sess.ws !== ws) return;
            try { sess.term.scrollToBottom(); } catch (_) {}
            if (vp) vp.scrollTop = vp.scrollHeight;
            requestAnimationFrame(() => {
              if (sess.ws !== ws) return;
              sess.revealPending = false;
              sess.paneEl.classList.remove('hydrating');
              if (activeId === sess.address) {
                termWrapEl.classList.remove('term-loading');
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
      };

      // Safety fallback in case a proxy delays or drops the hydrated control message
      sess.fallbackTimer = setTimeout(finishHydration, 2600);

      ws.onopen = () => {
        if (sess.ws !== ws) return;
        sess.connected = true;
        sess.reconnectDelay = 400;
        if (activeId === sess.address) {
          ptyConnected = true;
          syncConnPill();
          ws.send(JSON.stringify({ type: 'focus', focused: true }));
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
        if (!sess.hydrating && activeId === sess.address) focusTerminalIfDesktop();
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
            if (msg.type === 'hydrated') {
              finishHydration();
              return;
            }
            if (msg.type === 'resized') {
              finishResizeCycle(sess, msg.seq || null);
              return;
            }
            finishHydration();
            finishResizeCycle(sess);
            if (msg.type === 'error') sess.term.writeln(`\r\n\x1b[31m[error] ${msg.message}\x1b[0m`);
            if (msg.type === 'closed') {
              ws._terminalClosed = true;
              sess.term.writeln(`\r\n\x1b[2m[terminal closed]\x1b[0m`);
            }
          } catch (_) {
            finishHydration();
            finishResizeCycle(sess);
            sess.term.write(ev.data);
          }
          dismissBoot();
        }
      };

      ws.onerror = () => {
        if (sess.ws !== ws) return;
        finishHydration();
        finishResizeCycle(sess);
      };

      ws.onclose = () => {
        if (sess.ws !== ws) return;
        finishHydration();
        finishResizeCycle(sess);
        sess.ws = null;
        sess.connected = false;
        if (activeId === sess.address) {
          ptyConnected = false;
          syncConnPill();
        }
        if (ws._terminalClosed) return;
        // Auto-reconnect silently if this tab is still live so keyboard input never freezes
        if (tabSessions.get(sess.address) === sess && terminals.some((t) => t.address === sess.address)) {
          const delay = sess.reconnectDelay;
          sess.reconnectDelay = Math.min(Math.round(sess.reconnectDelay * 1.6), 3000);
          sess.reconnectTimer = setTimeout(() => {
            sess.reconnectTimer = null;
            if (tabSessions.get(sess.address) === sess && !sess.ws) {
              openSessionSocket(sess, { silent: true, reset: true });
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

  function connectPty(address, opts = {}) {
    if (!address) return;
    stopTouchCoast('connectPty');

    const prevSess = activeSession();
    clearTouchOffset(prevSess);
    if (prevSess && prevSess.address !== address) {
      prevSess.paneEl.classList.remove('active');
      if (prevSess.ws && prevSess.ws.readyState === 1) {
        prevSess.ws.send(JSON.stringify({ type: 'focus', focused: false }));
      }
    }

    activeId = address;
    let sess = tabSessions.get(address);
    const isNew = !sess;
    if (!sess) {
      sess = createTabSession(address);
    }

    sess.lastUsed = Date.now();
    sess.paneEl.classList.add('active');

    if (isNew || opts.forceReconnect || !sess.ws || sess.ws.readyState === 2 || sess.ws.readyState === 3) {
      openSessionSocket(sess, { silent: Boolean(opts.silent), reset: !isNew });
    } else {
      // Instant 0ms tab switch: live terminal & exact scroll position preserved!
      ptyConnected = sess.connected;
      syncConnPill();
      if (!sess.hydrating) {
        termWrapEl.classList.remove('term-loading');
      } else {
        termWrapEl.classList.add('term-loading');
      }
      if (sess.needsFit) fitSession(sess, true);
      syncStageLoader();
      if (sess.ws && sess.ws.readyState === 1) {
        sess.ws.send(JSON.stringify({ type: 'focus', focused: true }));
      }
      syncJumpLive();
      focusTerminalIfDesktop();
    }

    renderTabs();
  }

  // Hand-crafted 16x16 crisp pixel-art mascots for agents & shells (inline SVG, zero external assets)
  const AGENT_FULL_NAMES = {
    agy: 'Antigravity',
    claude: 'Claude Code',
    codex: 'OpenAI Codex',
    opencode: 'OpenCode',
    gemini: 'Gemini CLI',
    shell: 'Shell',
  };

  const PIXEL_SVG = {
    // Antigravity (agy): Cosmic violet space-owl / visor bot floating over a dark desk
    agy: '<svg viewBox="0 0 16 16" shape-rendering="crispEdges">' +
      '<rect x="2" y="2" width="1" height="1" fill="#c4b5fd" opacity=".55"/>' +
      '<rect x="13" y="3" width="1" height="1" fill="#8ad7e6" opacity=".65"/>' +
      '<rect x="7" y="1" width="2" height="1" fill="#c4b5fd"/>' +
      '<rect x="5" y="2" width="6" height="1" fill="#a78bfa"/>' +
      '<rect x="4" y="3" width="8" height="2" fill="#8b5cf6"/>' +
      '<rect x="3" y="5" width="10" height="4" fill="#7c3aed"/>' +
      '<rect x="5" y="5" width="6" height="3" fill="#18122b"/>' +
      '<rect x="6" y="6" width="1" height="1" fill="#67e8f9"/>' +
      '<rect x="9" y="6" width="1" height="1" fill="#67e8f9"/>' +
      '<rect x="4" y="9" width="8" height="2" fill="#a78bfa"/>' +
      '<rect x="2" y="7" width="1" height="3" fill="#c4b5fd"/>' +
      '<rect x="13" y="7" width="1" height="3" fill="#c4b5fd"/>' +
      '<rect x="5" y="11" width="2" height="1" fill="#6d28d9"/>' +
      '<rect x="9" y="11" width="2" height="1" fill="#6d28d9"/>' +
      '<rect x="1" y="12" width="14" height="2" fill="#3b2763"/>' +
      '<rect x="2" y="14" width="2" height="2" fill="#261842"/>' +
      '<rect x="12" y="14" width="2" height="2" fill="#261842"/>' +
      '</svg>',

    // Claude Code: Iconic warm terracotta blocky pixel critter at a cozy desk
    claude: '<svg viewBox="0 0 16 16" shape-rendering="crispEdges">' +
      '<rect x="2" y="2" width="1" height="1" fill="#fbbf24" opacity=".5"/>' +
      '<rect x="4" y="3" width="8" height="1" fill="#e89274"/>' +
      '<rect x="3" y="4" width="10" height="5" fill="#d97757"/>' +
      '<rect x="2" y="6" width="1" height="2" fill="#d97757"/>' +
      '<rect x="13" y="6" width="1" height="2" fill="#d97757"/>' +
      '<rect x="5" y="5" width="1" height="2" fill="#1a1110"/>' +
      '<rect x="10" y="5" width="1" height="2" fill="#1a1110"/>' +
      '<rect x="4" y="9" width="8" height="1" fill="#b85c3e"/>' +
      '<rect x="4" y="10" width="1" height="2" fill="#d97757"/>' +
      '<rect x="6" y="10" width="1" height="2" fill="#d97757"/>' +
      '<rect x="9" y="10" width="1" height="2" fill="#d97757"/>' +
      '<rect x="11" y="10" width="1" height="2" fill="#d97757"/>' +
      '<rect x="1" y="12" width="14" height="2" fill="#5c3626"/>' +
      '<rect x="2" y="14" width="2" height="2" fill="#3d2217"/>' +
      '<rect x="12" y="14" width="2" height="2" fill="#3d2217"/>' +
      '</svg>',

    // OpenAI Codex: Charming mint pixel frog at a dark desk
    codex: '<svg viewBox="0 0 16 16" shape-rendering="crispEdges">' +
      '<rect x="3" y="2" width="3" height="2" fill="#4ade80"/>' +
      '<rect x="10" y="2" width="3" height="2" fill="#4ade80"/>' +
      '<rect x="4" y="3" width="1" height="1" fill="#ffffff"/>' +
      '<rect x="5" y="3" width="1" height="1" fill="#0c1a12"/>' +
      '<rect x="10" y="3" width="1" height="1" fill="#ffffff"/>' +
      '<rect x="11" y="3" width="1" height="1" fill="#0c1a12"/>' +
      '<rect x="3" y="4" width="10" height="4" fill="#4ade80"/>' +
      '<rect x="4" y="6" width="1" height="1" fill="#166534"/>' +
      '<rect x="11" y="6" width="1" height="1" fill="#166534"/>' +
      '<rect x="5" y="7" width="6" height="1" fill="#14532d"/>' +
      '<rect x="4" y="8" width="8" height="3" fill="#22c55e"/>' +
      '<rect x="6" y="8" width="4" height="3" fill="#bbf7d0"/>' +
      '<rect x="3" y="10" width="2" height="2" fill="#4ade80"/>' +
      '<rect x="11" y="10" width="2" height="2" fill="#4ade80"/>' +
      '<rect x="1" y="12" width="14" height="2" fill="#1f4d3a"/>' +
      '<rect x="2" y="14" width="2" height="2" fill="#133326"/>' +
      '<rect x="12" y="14" width="2" height="2" fill="#133326"/>' +
      '</svg>',

    // OpenCode: Cozy golden pixel duck at a warm desk
    opencode: '<svg viewBox="0 0 16 16" shape-rendering="crispEdges">' +
      '<rect x="6" y="2" width="4" height="1" fill="#fde047"/>' +
      '<rect x="5" y="3" width="6" height="4" fill="#facc15"/>' +
      '<rect x="6" y="4" width="1" height="1" fill="#18181b"/>' +
      '<rect x="3" y="5" width="2" height="1" fill="#fb923c"/>' +
      '<rect x="4" y="6" width="1" height="1" fill="#f97316"/>' +
      '<rect x="4" y="7" width="8" height="4" fill="#eab308"/>' +
      '<rect x="6" y="8" width="4" height="2" fill="#fde047"/>' +
      '<rect x="12" y="8" width="1" height="2" fill="#facc15"/>' +
      '<rect x="6" y="11" width="2" height="1" fill="#f97316"/>' +
      '<rect x="9" y="11" width="2" height="1" fill="#f97316"/>' +
      '<rect x="1" y="12" width="14" height="2" fill="#6b4423"/>' +
      '<rect x="2" y="14" width="2" height="2" fill="#422915"/>' +
      '<rect x="12" y="14" width="2" height="2" fill="#422915"/>' +
      '</svg>',

    // Gemini CLI: Sky-blue twin-star pixel fox
    gemini: '<svg viewBox="0 0 16 16" shape-rendering="crispEdges">' +
      '<rect x="3" y="2" width="2" height="2" fill="#7aa2f7"/>' +
      '<rect x="11" y="2" width="2" height="2" fill="#7aa2f7"/>' +
      '<rect x="4" y="4" width="8" height="4" fill="#60a5fa"/>' +
      '<rect x="5" y="5" width="1" height="1" fill="#ffffff"/>' +
      '<rect x="10" y="5" width="1" height="1" fill="#ffffff"/>' +
      '<rect x="6" y="7" width="4" height="1" fill="#dbeafe"/>' +
      '<rect x="5" y="8" width="6" height="3" fill="#818cf8"/>' +
      '<rect x="7" y="9" width="2" height="1" fill="#e0f2fe"/>' +
      '<rect x="1" y="12" width="14" height="2" fill="#273966"/>' +
      '<rect x="2" y="14" width="2" height="2" fill="#182442"/>' +
      '<rect x="12" y="14" width="2" height="2" fill="#182442"/>' +
      '</svg>',

    // Plain shell: Crisp retro pixel >_ CRT icon
    shell: '<svg viewBox="0 0 16 16" shape-rendering="crispEdges">' +
      '<rect x="1" y="2" width="14" height="11" fill="#27222f"/>' +
      '<rect x="2" y="3" width="12" height="9" fill="#0c0b10"/>' +
      '<rect x="4" y="5" width="1" height="1" fill="#a78bfa"/>' +
      '<rect x="5" y="6" width="1" height="1" fill="#a78bfa"/>' +
      '<rect x="6" y="7" width="1" height="1" fill="#c4b5fd"/>' +
      '<rect x="5" y="8" width="1" height="1" fill="#a78bfa"/>' +
      '<rect x="4" y="9" width="1" height="1" fill="#a78bfa"/>' +
      '<rect x="8" y="9" width="4" height="1" fill="#a1a1aa"/>' +
      '<rect x="5" y="13" width="6" height="1" fill="#3f3a4d"/>' +
      '</svg>',

    // Sysop: Autonomous mission-control operator bot with headset, radar antenna & reactive visor
    sysop: '<svg viewBox="0 0 16 16" shape-rendering="crispEdges">' +
      '<rect x="2" y="2" width="1" height="1" fill="#c4b5fd" opacity=".45"/>' +
      '<rect x="13" y="1" width="1" height="1" fill="#67e8f9" opacity=".55"/>' +
      '<rect class="sys-ant" x="7" y="0" width="2" height="1"/>' +
      '<rect x="7" y="1" width="1" height="2" fill="#7c3aed"/>' +
      '<rect x="5" y="3" width="6" height="1" fill="#c4b5fd"/>' +
      '<rect x="4" y="4" width="8" height="5" fill="#6d28d9"/>' +
      '<rect x="2" y="5" width="2" height="3" fill="#a78bfa"/>' +
      '<rect x="12" y="5" width="2" height="3" fill="#a78bfa"/>' +
      '<rect x="3" y="8" width="2" height="1" fill="#67e8f9"/>' +
      '<rect x="5" y="5" width="6" height="3" fill="#120e21"/>' +
      '<rect class="sys-eye" x="6" y="6" width="1" height="1"/>' +
      '<rect class="sys-eye" x="9" y="6" width="1" height="1"/>' +
      '<rect class="sys-wave" x="7" y="7" width="2" height="1"/>' +
      '<rect x="4" y="9" width="8" height="3" fill="#4c1d95"/>' +
      '<rect x="6" y="9" width="4" height="1" fill="#a78bfa"/>' +
      '<rect class="sys-led" x="6" y="10" width="1" height="1"/>' +
      '<rect x="9" y="10" width="1" height="1" fill="#c4b5fd"/>' +
      '<rect x="1" y="12" width="14" height="2" fill="#2b1f47"/>' +
      '<rect x="4" y="12" width="8" height="1" fill="#5b21b6"/>' +
      '<rect x="2" y="14" width="2" height="2" fill="#1a132c"/>' +
      '<rect x="12" y="14" width="2" height="2" fill="#1a132c"/>' +
      '</svg>',
  };

  // Mount crisp pixel-art Sysop mascot in header, mobile capsule & operator hero card
  if (sysopDotEl) sysopDotEl.innerHTML = PIXEL_SVG.sysop;

  function tabAgentKind(t) {
    const b = tabAgentBadge(t);
    if (b) return b;
    const lblAg = String((t && t.labels && t.labels['swarmbox.agent']) || '').toLowerCase();
    if (AGENT_APP_LABELS[lblAg]) {
      // Only trust the sticky swarmbox.agent label if the terminal was launched with an agent argv
      // (not an unpinned tab replaced with a bare login shell by herdr-core --keep recovery).
      const argv = Array.isArray(t && t.argv) ? t.argv : [];
      const fg = String((t && t.foreground && t.foreground.name) || '').toLowerCase();
      const bareShell = argv.length <= 2 && (!fg || SHELL_NAMES.has(fg));
      if (!bareShell) return AGENT_APP_LABELS[lblAg];
    }
    const raw = String((t && t.name) || '').toLowerCase();
    for (const key of Object.keys(AGENT_APP_LABELS)) {
      if (raw === key || raw.startsWith(key + '-')) return AGENT_APP_LABELS[key];
    }
    return '';
  }

  function pixelIconHtml(kind) {
    return PIXEL_SVG[kind] || PIXEL_SVG.shell;
  }

  function makeMiniPixelIcon(kind) {
    const sp = document.createElement('span');
    sp.className = 'px-mini';
    sp.innerHTML = pixelIconHtml(kind);
    return sp;
  }

  function stateBadgeText(state, status) {
    if (state === 'working') {
      return status && typeof status.progress === 'number' ? `WORKING ${status.progress}%` : 'WORKING';
    }
    if (state === 'blocked') return 'BLOCKED';
    if (state === 'done') return 'DONE';
    if (state === 'error') return 'ERROR';
    return 'IDLE';
  }

  function stateCornerGlyph(state) {
    if (state === 'working') return '⚡';
    if (state === 'blocked') return '!';
    if (state === 'done') return '✓';
    if (state === 'error') return '✕';
    return 'Z';
  }

  const ICO_PIN_SVG = '<svg viewBox="0 0 16 16" width="11" height="11" fill="currentColor" aria-hidden="true"><path d="M9.8 1.5l4.7 4.7-1.1 1.1-1.3-.3-2.5 2.5.4 2.1-1.1 1.1-2.5-2.5L3 13.6l-.6-.6 3.4-3.4-2.5-2.5 1.1-1.1 2.1.4L9 3.9l-.3-1.3 1.1-1.1z"/></svg>';
  const ICO_BOLT_SVG = '<svg viewBox="0 0 16 16" width="10" height="10" fill="currentColor" aria-hidden="true"><path d="M9.2 1L3 9h4.4l-.8 6L13 7H8.6l.6-6z"/></svg>';
  const ICO_BRANCH_SVG = '<svg viewBox="0 0 16 16" width="11" height="11" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="4.5" cy="3.5" r="1.8"/><circle cx="11.5" cy="5.5" r="1.8"/><circle cx="4.5" cy="12.5" r="1.8"/><path d="M4.5 5.3v5.4M11.5 7.3c0 2.5-7 1.8-7 3.4"/></svg>';
  const ICO_PENCIL_SVG = '<svg viewBox="0 0 16 16" width="11" height="11" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M11.2 2.4a1.6 1.6 0 0 1 2.3 2.3L5.6 12.6 2.5 13.5l.9-3.1 7.8-8Z"/></svg>';

  function shortDisplayPath(p) {
    const s = String(p || '');
    const wtMatch = s.match(/\/\.local\/share\/swarmbox\/worktrees\/([^/]+)\/[^/]+(\/.*)?$/);
    if (wtMatch) return `~/${wtMatch[1]}${wtMatch[2] || ''}`;
    return s.startsWith('/home/agent') ? '~' + s.slice('/home/agent'.length) : s;
  }

  function openRenamePopover(address) {
    const term = terminals.find((t) => t.address === address);
    if (!term) return;
    const current = tabDisplayName(term);
    const wrap = document.createElement('div');
    wrap.style.display = 'flex';
    wrap.style.flexDirection = 'column';
    wrap.style.gap = '10px';

    const head = document.createElement('div');
    head.className = 'spop-head';
    head.innerHTML = `<span style="display:inline-flex;align-items:center;gap:6px">${ICO_PENCIL_SVG}<span>Rename session</span></span>`;

    const inp = document.createElement('input');
    inp.type = 'text';
    inp.className = 'spop-rename-input';
    inp.value = current;
    inp.maxLength = 60;
    inp.placeholder = 'Session title…';

    const actions = document.createElement('div');
    actions.className = 'spop-rename-actions';
    const cancelBtn = document.createElement('button');
    cancelBtn.type = 'button';
    cancelBtn.className = 'spop-btn secondary';
    cancelBtn.textContent = 'Cancel';
    const saveBtn = document.createElement('button');
    saveBtn.type = 'button';
    saveBtn.className = 'spop-btn primary';
    saveBtn.textContent = 'Save';

    const submit = () => {
      const val = inp.value.trim();
      closePopover();
      if (val && val !== current) commitInlineRename(address, val);
    };
    cancelBtn.addEventListener('click', closePopover);
    saveBtn.addEventListener('click', submit);
    inp.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') { e.preventDefault(); submit(); }
      else if (e.key === 'Escape') { e.preventDefault(); closePopover(); }
    });

    actions.append(cancelBtn, saveBtn);
    wrap.append(head, inp, actions);
    openPopover(wrap);
    requestAnimationFrame(() => {
      inp.focus();
      inp.select();
    });
  }

  function startInlineRename(address) {
    if (!address || !terminals.some((t) => t.address === address)) return;
    if (window.innerWidth <= 860) {
      openRenamePopover(address);
      return;
    }
    if (appEl.dataset.sidebarOpen !== '1') {
      setDesktopSidebar(true);
    }
    editingTabId = address;
    renderTabs();
    requestAnimationFrame(() => {
      const inp = document.querySelector(`.inline-rename-input[data-tab="${CSS.escape(address)}"]`);
      if (inp) {
        inp.focus();
        inp.select();
      }
    });
  }

  async function commitInlineRename(address, nextTitle) {
    const clean = String(nextTitle || '').trim();
    editingTabId = null;
    renderTabs();
    if (!clean) {
      focusTerminalIfDesktop();
      return;
    }
    await fetch(`/api/tabs/${encodeURIComponent(address)}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title: clean, title_source: 'user' }),
    }).catch(() => {});
    focusTerminalIfDesktop();
  }

  async function togglePinForTab(t) {
    const pinId = t && t.labels && t.labels['swarmbox.pin_id'];
    if (pinId) {
      await fetch(`/api/pins/${encodeURIComponent(pinId)}`, { method: 'DELETE' }).catch(() => {});
      showTermToast('Unpinned session');
      return;
    }
    const r = await fetch('/api/pins', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ terminal: t.address }),
    }).catch(() => null);
    if (r && r.ok) showTermToast('Pinned session (auto-follows folder & agent)');
  }

  async function togglePinAutostart(pin) {
    if (!pin || !pin.id) return;
    const next = !pin.autostart;
    const r = await fetch(`/api/pins/${encodeURIComponent(pin.id)}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ autostart: next }),
    }).catch(() => null);
    if (r && r.ok) showTermToast(next ? 'Autostart on boot enabled' : 'Autostart disabled (parked on boot)');
  }

  async function unpinById(pinId) {
    await fetch(`/api/pins/${encodeURIComponent(pinId)}`, { method: 'DELETE' }).catch(() => {});
    showTermToast('Removed pin');
  }

  let openCardMenuEl = null;
  let openCardMenuCard = null;

  function closeCardMenu() {
    if (openCardMenuEl) {
      openCardMenuEl.remove();
      openCardMenuEl = null;
    }
    if (openCardMenuCard) {
      delete openCardMenuCard.dataset.menuOpen;
      openCardMenuCard = null;
    }
  }

  document.addEventListener('pointerdown', (e) => {
    if (openCardMenuEl && !openCardMenuEl.contains(e.target)) closeCardMenu();
  }, true);
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && openCardMenuEl) {
      e.stopPropagation();
      closeCardMenu();
    }
  }, true);
  window.addEventListener('resize', closeCardMenu);
  if (sidebarAgentsEl && sidebarAgentsEl.parentElement && sidebarAgentsEl.parentElement.parentElement) {
    sidebarAgentsEl.parentElement.parentElement.addEventListener('scroll', closeCardMenu, { passive: true });
  }

  function openCardMenu(term, anchor, cardEl = null) {
    closeCardMenu();
    if (!term || !term.address) return;
    const wtBranch = term.labels && term.labels['swarmbox.worktree'] ? (term.labels['swarmbox.branch'] || 'worktree') : '';
    const wtBase = (term.labels && term.labels['swarmbox.base']) || 'main';
    const menu = document.createElement('div');
    menu.className = 'card-ctx-menu';
    menu.setAttribute('role', 'menu');

    if (wtBranch) {
      const head = document.createElement('div');
      head.className = 'card-ctx-head';
      head.innerHTML = `<span>Worktree</span><span class="card-ctx-branch"></span>`;
      head.querySelector('.card-ctx-branch').textContent = `${wtBranch} → ${wtBase}`;
      menu.appendChild(head);

      const mItem = document.createElement('button');
      mItem.type = 'button';
      mItem.className = 'card-ctx-item is-wt';
      mItem.setAttribute('role', 'menuitem');
      mItem.innerHTML = `<span class="card-ctx-item-l">${ICO_BRANCH_SVG}<span>Merge &amp; status…</span></span><span class="card-ctx-kbd">↵</span>`;
      mItem.addEventListener('click', (e) => {
        e.stopPropagation();
        closeCardMenu();
        openWorktreePopover(term.address);
      });
      menu.appendChild(mItem);
    }

    const rItem = document.createElement('button');
    rItem.type = 'button';
    rItem.className = 'card-ctx-item';
    rItem.setAttribute('role', 'menuitem');
    rItem.innerHTML = `<span class="card-ctx-item-l">${ICO_PENCIL_SVG}<span>Rename</span></span><span class="card-ctx-kbd">Alt+R</span>`;
    rItem.addEventListener('click', (e) => {
      e.stopPropagation();
      closeCardMenu();
      startInlineRename(term.address);
    });
    menu.appendChild(rItem);

    const sep = document.createElement('div');
    sep.className = 'card-ctx-sep';
    menu.appendChild(sep);

    const cItem = document.createElement('button');
    cItem.type = 'button';
    cItem.className = 'card-ctx-item is-danger';
    cItem.setAttribute('role', 'menuitem');
    cItem.innerHTML = `<span class="card-ctx-item-l"><span class="card-ctx-x">✕</span><span>Close tab</span></span>`;
    cItem.addEventListener('click', async (e) => {
      e.stopPropagation();
      closeCardMenu();
      await fetch(`/api/tabs/${encodeURIComponent(term.address)}`, { method: 'DELETE' });
    });
    menu.appendChild(cItem);

    document.body.appendChild(menu);
    openCardMenuEl = menu;
    openCardMenuCard = cardEl;
    if (cardEl) cardEl.dataset.menuOpen = '1';

    const mw = menu.offsetWidth || 214;
    const mh = menu.offsetHeight || 140;
    let x = 12;
    let y = 12;
    if (anchor && typeof anchor.getBoundingClientRect === 'function') {
      const rect = anchor.getBoundingClientRect();
      x = rect.right - mw + 6;
      y = rect.bottom + 6;
      if (x < 10) x = rect.left;
    } else if (anchor && typeof anchor.x === 'number') {
      x = anchor.x;
      y = anchor.y;
    }
    x = Math.max(8, Math.min(x, window.innerWidth - mw - 8));
    y = Math.max(8, Math.min(y, window.innerHeight - mh - 8));
    menu.style.left = `${Math.round(x)}px`;
    menu.style.top = `${Math.round(y)}px`;
  }

  function closePopover() {
    if (!popoverBackdropEl) return;
    popoverOpen = false;
    popoverKeyHandler = null;
    popoverBackdropEl.classList.add('hidden');
    popoverBackdropEl.setAttribute('aria-hidden', 'true');
    if (popoverEl) popoverEl.innerHTML = '';
    focusTerminalIfDesktop();
  }

  function openPopover(node, onKeyDown = null) {
    if (!popoverBackdropEl || !popoverEl) return;
    popoverEl.innerHTML = '';
    popoverEl.appendChild(node);
    popoverOpen = true;
    popoverKeyHandler = typeof onKeyDown === 'function' ? onKeyDown : null;
    popoverBackdropEl.classList.remove('hidden');
    popoverBackdropEl.setAttribute('aria-hidden', 'false');
    requestAnimationFrame(() => {
      const primary = popoverEl.querySelector('.agent-pick-btn.is-default, .spop-btn.primary, .spop-btn.green, .spop-btn.amber, .agent-pick-btn');
      if (primary) primary.focus();
    });
  }

  async function openNewAgentPopover(includeShell = false) {
    const cur = terminals.find((t) => t.address === activeId);
    const curCwd = (cur && cur.foreground && cur.foreground.cwd) || (cur && cur.cwd) || '';

    let list = Array.isArray(installedAgents) ? installedAgents : [];
    const checkUrl = curCwd && curCwd.startsWith('/')
      ? `/api/worktrees/check?cwd=${encodeURIComponent(curCwd)}`
      : '/api/worktrees/check';

    const [cfgData, wtInfo] = await Promise.all([
      list.length === 0
        ? fetch('/api/config', { cache: 'no-store' }).then((r) => (r.ok ? r.json() : null)).catch(() => null)
        : Promise.resolve(null),
      fetch(checkUrl, { cache: 'no-store' }).then((r) => (r.ok ? r.json() : null)).catch(() => null),
    ]);

    if (cfgData && Array.isArray(cfgData.installed_agents)) {
      installedAgents = cfgData.installed_agents;
      list = installedAgents;
    }
    if (wtInfo && wtInfo.prefs) {
      worktreePrefs = wtInfo.prefs;
    }

    const isGit = Boolean(wtInfo && wtInfo.is_git);
    const col = (wtInfo && wtInfo.collision) || null;
    const hasCollision = Boolean(col);
    const prefs = (wtInfo && wtInfo.prefs) || worktreePrefs || { mode: 'ask', copy_env: true };
    const branch = (wtInfo && wtInfo.branch) || (col && col.branch) || 'HEAD';

    if (!includeShell && list.length === 0) {
      spawnTab('agent');
      return;
    }
    if (!includeShell && list.length === 1 && (!hasCollision || prefs.mode !== 'ask')) {
      spawnTab('agent', { agent: list[0].id, cwd: curCwd || undefined });
      return;
    }

    const folderLabel = shortDisplayPath(curCwd) || '~';
    let wtChoice = hasCollision ? (prefs.mode === 'off' ? 'same' : 'new') : 'same';

    const frag = document.createDocumentFragment();
    const head = document.createElement('div');
    head.className = 'spop-head';
    const titleSpan = document.createElement('span');
    titleSpan.textContent = includeShell ? 'New tab' : 'New agent';
    const headRight = document.createElement('span');
    headRight.className = 'spop-head-right';
    const cwdBadge = document.createElement('span');
    cwdBadge.className = 'spop-badge';
    cwdBadge.textContent = folderLabel;
    headRight.appendChild(cwdBadge);
    if (isGit && branch) {
      const brBadge = document.createElement('span');
      brBadge.className = 'spop-badge branch';
      brBadge.innerHTML = `${ICO_BRANCH_SVG}<span></span>`;
      brBadge.querySelector('span').textContent = branch;
      headRight.appendChild(brBadge);
    }
    head.append(titleSpan, headRight);
    frag.appendChild(head);

    let updateWtUi = null;
    if (isGit) {
      const nActive = (col && col.active_tabs && col.active_tabs.length) || 0;
      const wtBox = document.createElement('div');
      wtBox.className = `wt-box${hasCollision ? ' is-collision' : ''}`;

      const wtHead = document.createElement('div');
      wtHead.className = 'wt-box-head';
      if (hasCollision) {
        const note = document.createElement('span');
        note.className = 'wt-collision-note';
        const dot = document.createElement('span');
        dot.className = 'wt-collision-dot';
        const txt = document.createElement('span');
        txt.textContent = `${nActive} active agent${nActive === 1 ? '' : 's'} already on ${branch}`;
        note.append(dot, txt);
        wtHead.appendChild(note);
      } else {
        const note = document.createElement('span');
        note.className = 'wt-clean-note';
        note.textContent = 'Workspace';
        wtHead.appendChild(note);
      }
      const kbd = document.createElement('span');
      kbd.className = 'wt-kbd desktop-only';
      kbd.title = 'Press W to toggle workspace';
      kbd.textContent = 'W';
      wtHead.appendChild(kbd);

      const seg = document.createElement('div');
      seg.className = 'wt-seg';
      seg.setAttribute('role', 'radiogroup');
      seg.setAttribute('aria-label', 'Workspace isolation');

      const btnNew = document.createElement('button');
      btnNew.type = 'button';
      btnNew.setAttribute('role', 'radio');
      btnNew.className = 'wt-seg-btn';
      btnNew.dataset.choice = 'new';
      btnNew.innerHTML = `${ICO_BRANCH_SVG}<span>New worktree</span>`;

      const btnSame = document.createElement('button');
      btnSame.type = 'button';
      btnSame.setAttribute('role', 'radio');
      btnSame.className = 'wt-seg-btn';
      btnSame.dataset.choice = 'same';
      btnSame.textContent = 'Same folder';

      seg.append(btnNew, btnSame);

      const meta = document.createElement('div');
      meta.className = 'wt-meta';

      updateWtUi = () => {
        const isNew = wtChoice === 'new';
        btnNew.classList.toggle('active-wt', isNew);
        btnNew.setAttribute('aria-checked', isNew ? 'true' : 'false');
        btnSame.classList.toggle('active-same', !isNew);
        btnSame.setAttribute('aria-checked', !isNew ? 'true' : 'false');
        if (isNew) {
          meta.innerHTML = '';
          const sp = document.createElement('span');
          sp.append('isolated branch from ');
          const st = document.createElement('strong');
          st.textContent = branch;
          sp.append(st);
          if (prefs.copy_env) sp.append(' · copies .env');
          meta.appendChild(sp);
        } else if (hasCollision) {
          meta.textContent = `shares working tree with ${nActive} active agent${nActive === 1 ? '' : 's'}`;
        } else {
          meta.textContent = `opens directly in ${folderLabel} · no active collision`;
        }
      };

      btnNew.addEventListener('click', () => {
        wtChoice = 'new';
        updateWtUi();
      });
      btnSame.addEventListener('click', () => {
        wtChoice = 'same';
        updateWtUi();
      });

      updateWtUi();
      wtBox.append(wtHead, seg, meta);
      frag.appendChild(wtBox);

      const secHead = document.createElement('div');
      secHead.className = 'pick-section-head';
      const secLeft = document.createElement('span');
      secLeft.textContent = 'Launch agent';
      const secRight = document.createElement('span');
      secRight.className = 'desktop-only';
      secRight.textContent = '1 click · Enter ↵';
      secHead.append(secLeft, secRight);
      frag.appendChild(secHead);
    } else {
      const sub = document.createElement('div');
      sub.className = 'spop-sub';
      sub.textContent = includeShell
        ? 'Launch an installed coding agent or a fresh shell.'
        : 'Pick an installed coding agent to launch in this folder.';
      frag.appendChild(sub);
    }

    const pickList = document.createElement('div');
    pickList.className = 'agent-pick-list';
    const hasDefault = list.some((a) => a.default);
    for (let i = 0; i < list.length; i += 1) {
      const ag = list[i];
      const isPrimary = ag.default || (!hasDefault && i === 0);
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = `agent-pick-btn${isPrimary ? ' is-default' : ''}`;
      btn.dataset.agent = ag.id;
      const ico = document.createElement('span');
      ico.className = 'agent-pick-ico';
      ico.innerHTML = pixelIconHtml(PIXEL_SVG[ag.id] ? ag.id : 'agent');
      const info = document.createElement('span');
      info.className = 'agent-pick-info';
      const nm = document.createElement('span');
      nm.className = 'agent-pick-name';
      nm.textContent = ag.name || AGENT_FULL_NAMES[ag.id] || ag.id;
      const cmd = document.createElement('span');
      cmd.className = 'agent-pick-cmd';
      cmd.textContent = ag.id;
      info.append(nm, cmd);
      btn.append(ico, info);
      if (ag.default || isPrimary) {
        const right = document.createElement('span');
        right.className = 'agent-pick-right';
        if (ag.default) {
          const def = document.createElement('span');
          def.className = 'agent-pick-def';
          def.textContent = 'default';
          right.appendChild(def);
        }
        if (isPrimary) {
          const ent = document.createElement('span');
          ent.className = 'agent-pick-enter desktop-only';
          ent.textContent = '↵';
          right.appendChild(ent);
        }
        btn.appendChild(right);
      }
      btn.addEventListener('click', () => {
        const chosenWt = isGit ? wtChoice : '';
        closePopover();
        spawnTab('agent', {
          agent: ag.id,
          cwd: curCwd || undefined,
          worktree_choice: chosenWt || undefined,
        });
      });
      pickList.appendChild(btn);
    }

    if (includeShell) {
      const shBtn = document.createElement('button');
      shBtn.type = 'button';
      shBtn.className = `agent-pick-btn${isGit ? ' is-shell' : ''}`;
      shBtn.dataset.agent = 'shell';
      const ico = document.createElement('span');
      ico.className = 'agent-pick-ico';
      ico.innerHTML = pixelIconHtml('shell');
      const info = document.createElement('span');
      info.className = 'agent-pick-info';
      const nm = document.createElement('span');
      nm.className = 'agent-pick-name';
      nm.textContent = 'Shell';
      const cmd = document.createElement('span');
      cmd.className = 'agent-pick-cmd';
      cmd.textContent = 'bash';
      info.append(nm, cmd);
      shBtn.append(ico, info);
      if (isGit) {
        const tag = document.createElement('span');
        tag.className = 'shell-tag';
        tag.textContent = 'same folder';
        shBtn.appendChild(tag);
      }
      shBtn.addEventListener('click', () => {
        closePopover();
        spawnTab('shell');
      });
      pickList.appendChild(shBtn);
    }

    frag.appendChild(pickList);

    if (isGit) {
      const links = document.createElement('div');
      links.className = 'spop-links';
      const modeSpan = document.createElement('span');
      modeSpan.append('Mode: ');
      const modeStrong = document.createElement('strong');
      modeStrong.textContent = prefs.mode || 'ask';
      modeSpan.appendChild(modeStrong);
      const cfgLink = document.createElement('button');
      cfgLink.type = 'button';
      cfgLink.className = 'spop-link-btn';
      cfgLink.textContent = 'Change in Settings';
      cfgLink.addEventListener('click', () => { closePopover(); openSettings('box'); });
      links.append(modeSpan, cfgLink);
      frag.appendChild(links);
    }

    openPopover(frag, (e) => {
      if (e.ctrlKey || e.metaKey || e.altKey) return false;
      if (isGit && updateWtUi && (e.key === 'w' || e.key === 'W')) {
        e.preventDefault();
        e.stopPropagation();
        wtChoice = wtChoice === 'new' ? 'same' : 'new';
        updateWtUi();
        return true;
      }
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
        const btns = Array.from(popoverEl.querySelectorAll('.agent-pick-btn'));
        if (btns.length === 0) return false;
        e.preventDefault();
        e.stopPropagation();
        const idx = btns.indexOf(document.activeElement);
        const next = e.key === 'ArrowDown'
          ? (idx < 0 ? 0 : (idx + 1) % btns.length)
          : (idx <= 0 ? btns.length - 1 : idx - 1);
        btns[next].focus();
        return true;
      }
      return false;
    });
  }

  function openCollisionPopover(ctx) {
    const col = ctx.collision || {};
    const frag = document.createDocumentFragment();
    const head = document.createElement('div');
    head.className = 'spop-head';
    head.innerHTML = `<span style="display:inline-flex;align-items:center;gap:6px">${ICO_BRANCH_SVG}<span>Collision in ${col.repo_name || 'repo'}</span></span><span class="spop-badge">${col.branch || 'HEAD'}</span>`;
    const sub = document.createElement('div');
    sub.className = 'spop-sub';
    const n = (col.active_tabs && col.active_tabs.length) || 1;
    sub.textContent = `${n} active agent${n > 1 ? 's' : ''} already using this folder. How should this session open?`;

    const btnWt = document.createElement('button');
    btnWt.type = 'button';
    btnWt.className = 'spop-btn primary';
    btnWt.innerHTML = `<span style="display:inline-flex;align-items:center;gap:7px">${ICO_BRANCH_SVG}<span>New worktree</span></span><span class="spop-hint">Enter ↵</span>`;
    btnWt.addEventListener('click', () => {
      closePopover();
      if (ctx.kind === 'pin') wakePin(ctx.pinId, 'new');
      else spawnTab(ctx.preset || 'agent', { cwd: ctx.cwd, agent: ctx.agent, worktree_choice: 'new' });
    });

    const meta = document.createElement('div');
    meta.className = 'spop-meta';
    meta.textContent = ctx.kind === 'pin'
      ? `isolated branch from ${col.branch || 'HEAD'} · starts fresh session`
      : `isolated branch from ${col.branch || 'HEAD'}${worktreePrefs.copy_env ? ' · copies root .env' : ''}`;

    const btnSame = document.createElement('button');
    btnSame.type = 'button';
    btnSame.className = 'spop-btn secondary';
    btnSame.innerHTML = `<span>Same folder</span><span class="spop-hint">${ctx.kind === 'pin' ? '--continue' : 'share'}</span>`;
    btnSame.addEventListener('click', () => {
      closePopover();
      if (ctx.kind === 'pin') wakePin(ctx.pinId, 'same');
      else spawnTab(ctx.preset || 'agent', { cwd: ctx.cwd, agent: ctx.agent, worktree_choice: 'same' });
    });

    const links = document.createElement('div');
    links.className = 'spop-links';
    links.innerHTML = `<span>Mode: <strong>${worktreePrefs.mode}</strong></span>`;
    const cfgLink = document.createElement('button');
    cfgLink.type = 'button';
    cfgLink.className = 'spop-link-btn';
    cfgLink.textContent = 'Change in Settings';
    cfgLink.addEventListener('click', () => { closePopover(); openSettings('box'); });
    links.appendChild(cfgLink);

    frag.append(head, sub, btnWt, meta, btnSame, links);
    openPopover(frag);
  }

  async function openWorktreePopover(termId) {
    const t = terminals.find((x) => x.address === termId);
    if (!t) return;
    const loading = document.createElement('div');
    loading.className = 'spop-sub';
    loading.textContent = 'Checking Git worktree status…';
    openPopover(loading);

    let st;
    try {
      const r = await fetch(`/api/tabs/${encodeURIComponent(termId)}/worktree`);
      st = await r.json();
      if (!r.ok) throw new Error(st.message || 'Not a Git worktree');
    } catch (err) {
      const box = document.createDocumentFragment();
      const m = document.createElement('div');
      m.className = 'spop-sub';
      m.textContent = err.message || 'Unable to inspect worktree.';
      const c = document.createElement('button');
      c.type = 'button';
      c.className = 'spop-btn secondary';
      c.textContent = 'Close';
      c.addEventListener('click', closePopover);
      box.append(m, c);
      openPopover(box);
      return;
    }

    const frag = document.createDocumentFragment();
    const head = document.createElement('div');
    head.className = 'spop-head';
    const badgeCls = st.dirty || !st.can_merge || st.main_dirty ? 'warn' : 'ok';
    const badgeTxt = st.dirty ? 'DIRTY' : !st.can_merge ? 'CONFLICT' : st.ahead > 0 ? 'CLEAN' : 'EMPTY';
    head.innerHTML = `<span style="display:inline-flex;align-items:center;gap:6px">${ICO_BRANCH_SVG}<span>${st.branch} → ${st.base}</span></span><span class="spop-badge ${badgeCls}">${badgeTxt}</span>`;

    const sub = document.createElement('div');
    sub.className = 'spop-sub';
    if (st.dirty) {
      sub.textContent = `${st.uncommitted_count} uncommitted change${st.uncommitted_count === 1 ? '' : 's'} in this worktree.`;
    } else if (st.ahead === 0) {
      sub.textContent = `No commits ahead of ${st.base}. Safe to close and remove.`;
    } else if (!st.can_merge) {
      sub.textContent = `${st.ahead} commit${st.ahead === 1 ? '' : 's'} ahead · conflict with ${st.base} in ${(st.conflict_files || []).join(', ') || 'files'}.`;
    } else if (st.main_dirty) {
      sub.textContent = `${st.ahead} commit${st.ahead === 1 ? '' : 's'} ahead · main repo has uncommitted changes (commit there first or open a PR).`;
    } else {
      sub.textContent = `${st.ahead} commit${st.ahead === 1 ? '' : 's'} ahead · 0 conflicts (checked via git merge-tree).`;
    }

    frag.append(head, sub);

    if (st.dirty) {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'spop-btn primary';
      btn.innerHTML = '<span>Ask agent to commit</span><span class="spop-hint">in this tab</span>';
      btn.addEventListener('click', async () => {
        closePopover();
        await fetch('/api/worktrees/commit', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ terminal: termId }),
        });
        showTermToast('Asked agent to commit changes');
      });
      frag.appendChild(btn);
    } else if (st.ahead > 0 && !st.can_merge) {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'spop-btn amber';
      btn.innerHTML = '<span>Resolve conflict with agent</span><span class="spop-hint">in worktree</span>';
      btn.addEventListener('click', async () => {
        closePopover();
        await fetch('/api/worktrees/resolve-conflict', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ terminal: termId, base: st.base }),
        });
        showTermToast(`Asked agent to merge ${st.base} & resolve conflict inside worktree`);
      });
      frag.appendChild(btn);
    } else if (st.ahead > 0 && st.can_merge && !st.main_dirty) {
      const btnMerge = document.createElement('button');
      btnMerge.type = 'button';
      btnMerge.className = 'spop-btn green';
      btnMerge.innerHTML = `<span>Merge into ${st.base} &amp; clean</span><span class="spop-hint">1 click</span>`;
      btnMerge.addEventListener('click', async () => {
        closePopover();
        const r = await fetch('/api/worktrees/merge', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ terminal: termId, path: st.path, clean: true }),
        });
        const d = await r.json().catch(() => ({}));
        showTermToast(r.ok ? `Merged ${st.branch} into ${st.base} & cleaned worktree` : (d.message || 'Merge failed'));
      });
      const btnKeep = document.createElement('button');
      btnKeep.type = 'button';
      btnKeep.className = 'spop-btn secondary';
      btnKeep.innerHTML = `<span>Merge &amp; keep tab</span><span class="spop-hint">${st.base}</span>`;
      btnKeep.addEventListener('click', async () => {
        closePopover();
        const r = await fetch('/api/worktrees/merge', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ terminal: termId, path: st.path, clean: false }),
        });
        const d = await r.json().catch(() => ({}));
        showTermToast(r.ok ? `Merged ${st.branch} into ${st.base}` : (d.message || 'Merge failed'));
      });
      frag.append(btnMerge, btnKeep);
    } else if (st.ahead === 0 && !st.dirty) {
      const btnClean = document.createElement('button');
      btnClean.type = 'button';
      btnClean.className = 'spop-btn secondary';
      btnClean.textContent = 'Close & remove worktree';
      btnClean.addEventListener('click', async () => {
        closePopover();
        await fetch('/api/worktrees/remove', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ path: st.path, terminal: termId }),
        });
        showTermToast('Removed empty worktree');
      });
      frag.appendChild(btnClean);
    }

    const links = document.createElement('div');
    links.className = 'spop-links';
    const prBtn = document.createElement('button');
    prBtn.type = 'button';
    prBtn.className = 'spop-link-btn';
    prBtn.textContent = 'Push / Open PR';
    prBtn.addEventListener('click', async () => {
      closePopover();
      await fetch(`/api/tabs/${encodeURIComponent(termId)}/send`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text: `Push branch ${st.branch} and open a Pull Request targeting ${st.base}.`, force: true }),
      });
      showTermToast('Asked agent to push & open PR');
    });
    const closeLink = document.createElement('button');
    closeLink.type = 'button';
    closeLink.className = 'spop-link-btn';
    closeLink.textContent = 'Keep worktree';
    closeLink.addEventListener('click', closePopover);
    links.append(prBtn, closeLink);
    frag.appendChild(links);
    openPopover(frag);
  }

  function openPendingWorktreesPopover() {
    const frag = document.createDocumentFragment();
    const head = document.createElement('div');
    head.className = 'spop-head';
    head.innerHTML = `<span style="display:inline-flex;align-items:center;gap:6px">${ICO_BRANCH_SVG}<span>Pending worktrees</span></span><span class="spop-badge warn">${pendingWorktrees.length}</span>`;
    const sub = document.createElement('div');
    sub.className = 'spop-sub';
    sub.textContent = 'Closed worktrees kept safe because they still have uncommitted changes or unmerged commits.';
    const list = document.createElement('div');
    list.className = 'spop-wt-list';

    for (const w of pendingWorktrees) {
      const row = document.createElement('div');
      row.className = 'spop-wt-row';
      const top = document.createElement('div');
      top.className = 'spop-wt-row-top';
      top.innerHTML = `<span>${w.repo_name} · <strong>${w.branch}</strong></span><span class="spop-badge ${w.dirty || !w.can_merge ? 'warn' : 'ok'}">${w.dirty ? `${w.uncommitted_count} dirty` : `${w.ahead} ahead`}</span>`;
      const btns = document.createElement('div');
      btns.className = 'spop-wt-row-btns';
      const bOpen = document.createElement('button');
      bOpen.type = 'button';
      bOpen.textContent = 'Reopen';
      bOpen.addEventListener('click', async () => {
        closePopover();
        const r = await fetch('/api/worktrees/open', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ path: w.path }),
        });
        const d = await r.json().catch(() => ({}));
        const addr = (d && d.terminal && d.terminal.address) || (d && d.address);
        if (addr) setTimeout(() => connectPty(addr), 100);
      });
      const bRm = document.createElement('button');
      bRm.type = 'button';
      bRm.textContent = 'Discard & remove';
      bRm.addEventListener('click', async () => {
        await fetch('/api/worktrees/remove', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ path: w.path, force: true }),
        });
        closePopover();
        showTermToast(`Removed worktree ${w.branch}`);
      });
      btns.append(bOpen, bRm);
      row.append(top, btns);
      list.appendChild(row);
    }

    const foot = document.createElement('div');
    foot.className = 'spop-links';
    const doneBtn = document.createElement('button');
    doneBtn.type = 'button';
    doneBtn.className = 'spop-link-btn';
    doneBtn.textContent = 'Close';
    doneBtn.addEventListener('click', closePopover);
    foot.appendChild(doneBtn);
    frag.append(head, sub, list, foot);
    openPopover(frag);
  }

  async function wakePin(pinId, worktreeChoice = '') {
    const body = worktreeChoice ? { worktree_choice: worktreeChoice } : {};
    const r = await fetch(`/api/pins/${encodeURIComponent(pinId)}/wake`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    const data = await r.json().catch(() => ({}));
    if (r.status === 409 && data.error === 'worktree_collision') {
      openCollisionPopover({ kind: 'pin', pinId, collision: data.collision });
      return;
    }
    if (!r.ok) {
      showTermToast(data.message || 'Could not wake pinned session');
      return;
    }
    const addr = (data && data.terminal && data.terminal.address) || (data && data.address);
    if (addr) setTimeout(() => connectPty(addr), 100);
    if (data.worktree) {
      showTermToast(`Opened in worktree ${data.worktree.branch}`);
    }
  }

  function renderTabs() {
    sidebarTabsEl.innerHTML = '';
    if (topbarTabsEl) topbarTabsEl.innerHTML = '';
    if (sidebarAgentsEl) sidebarAgentsEl.innerHTML = '';
    mobileTabsEl.innerHTML = '';

    let agentCount = 0;
    let shellCount = 0;
    let busyCount = 0;

    terminals.forEach((t, idx) => {
      const state = tabState(t);
      const { title: label, pill } = tabTitleParts(t);
      const agentKind = tabAgentKind(t);
      const iconKind = agentKind || 'shell';
      const isActive = t.address === activeId;
      const subText = tabSubtitle(t);

      // 1. Sidebar: zero duplication — agents live in rich Pixel-Art Agent Cards; plain shells live in Shells list
      if (agentKind && sidebarAgentsEl) {
        agentCount += 1;
        if (state === 'working' || state === 'blocked') busyCount += 1;

        const card = document.createElement('div');
        card.className = `agent-card${isActive ? ' active' : ''}`;
        card.setAttribute('role', 'tab');
        card.setAttribute('tabindex', '0');
        card.setAttribute('aria-selected', isActive ? 'true' : 'false');
        card.dataset.agent = agentKind;
        card.dataset.state = state;
        card.title = `${label} — ${AGENT_FULL_NAMES[agentKind] || agentKind} (${state})`;

        const main = document.createElement('div');
        main.className = 'agent-card-main';

        const stage = document.createElement('div');
        stage.className = 'pixel-stage';
        stage.innerHTML = pixelIconHtml(agentKind);
        const corner = document.createElement('span');
        corner.className = 'pixel-corner';
        corner.textContent = stateCornerGlyph(state);
        stage.appendChild(corner);

        const cInfo = document.createElement('div');
        cInfo.className = 'agent-card-info';
        const cTop = document.createElement('div');
        cTop.className = 'agent-card-top';
        const cBadge = document.createElement('span');
        cBadge.className = 'agent-state-box';
        cBadge.textContent = stateBadgeText(state, t.status);

        const cRight = document.createElement('div');
        cRight.className = 'agent-card-right';
        const pinId = t.labels && t.labels['swarmbox.pin_id'];
        const pinObj = pinId ? pins.find((p) => p.id === pinId) : null;
        const cIdx = document.createElement('span');
        cIdx.className = 'agent-card-idx';
        cIdx.textContent = `tab ${idx + 1}`;
        const cTopActs = document.createElement('div');
        cTopActs.className = 'agent-card-top-acts';
        const cMore = document.createElement('button');
        cMore.type = 'button';
        cMore.className = 'agent-card-more';
        cMore.title = 'Session actions (Merge, Rename, Close)';
        cMore.setAttribute('aria-label', `Actions for ${label}`);
        cMore.textContent = '⋯';
        cMore.addEventListener('click', (e) => {
          e.stopPropagation();
          if (openCardMenuCard === card) closeCardMenu();
          else openCardMenu(t, cMore, card);
        });
        const cClose = document.createElement('button');
        cClose.type = 'button';
        cClose.className = 'agent-card-close';
        cClose.title = (pinObj && !pinObj.auto) ? 'Close tab (pin stays parked)' : 'Close tab';
        cClose.setAttribute('aria-label', `Close ${label}`);
        cClose.textContent = '✕';
        cClose.addEventListener('click', async (e) => {
          e.stopPropagation();
          closeCardMenu();
          await fetch(`/api/tabs/${encodeURIComponent(t.address)}`, { method: 'DELETE' });
        });
        cTopActs.append(cMore, cClose);
        cRight.append(cIdx, cTopActs);
        cTop.append(cBadge, cRight);

        const isEditing = editingTabId === t.address;
        const cName = document.createElement('div');
        cName.className = `agent-card-name${isEditing ? ' is-editing' : ''}`;
        if (isEditing) {
          const inp = document.createElement('input');
          inp.type = 'text';
          inp.className = 'inline-rename-input';
          inp.dataset.tab = t.address;
          inp.value = label;
          inp.maxLength = 60;
          inp.addEventListener('click', (e) => e.stopPropagation());
          inp.addEventListener('keydown', (e) => {
            e.stopPropagation();
            if (e.key === 'Enter') { e.preventDefault(); commitInlineRename(t.address, inp.value); }
            else if (e.key === 'Escape') { e.preventDefault(); editingTabId = null; renderTabs(); focusTerminalIfDesktop(); }
          });
          inp.addEventListener('blur', () => {
            if (editingTabId === t.address) commitInlineRename(t.address, inp.value);
          });
          cName.appendChild(inp);
        } else {
          const nameSpan = document.createElement('span');
          nameSpan.className = 'agent-card-name-text';
          nameSpan.textContent = label;
          cName.appendChild(nameSpan);
          const isAutoNamed = t.labels && t.labels['swarmbox.title_source'] === 'auto';
          cName.title = isAutoNamed
            ? `${label} (auto-named by Sysop · double-click or Alt+R to rename)`
            : `${label} (double-click or Alt+R to rename)`;
          cName.addEventListener('dblclick', (e) => {
            e.stopPropagation();
            startInlineRename(t.address);
          });
        }

        const cMsg = document.createElement('div');
        cMsg.className = 'agent-card-msg';
        cMsg.textContent = subText || (t.address || '');

        cInfo.append(cTop, cName, cMsg);
        main.append(stage, cInfo);
        card.appendChild(main);

        const foot = document.createElement('div');
        foot.className = 'agent-card-foot';
        const wtBranch = t.labels && t.labels['swarmbox.worktree'] ? (t.labels['swarmbox.branch'] || 'worktree') : '';
        const wtBase = (t.labels && t.labels['swarmbox.base']) || 'main';
        const shortBranch = wtBranch ? wtBranch.replace(/^sb\//, '') : '';

        const footL = document.createElement('div');
        footL.className = 'agent-card-foot-l';
        const footAg = document.createElement('span');
        footAg.className = 'agent-card-foot-ag';
        footAg.textContent = `└ ${AGENT_FULL_NAMES[agentKind] || agentKind}`;
        footL.appendChild(footAg);
        if (wtBranch) {
          const wtSep = document.createElement('span');
          wtSep.className = 'agent-wt-sep';
          wtSep.textContent = '·';
          const wtLink = document.createElement('button');
          wtLink.type = 'button';
          wtLink.className = 'agent-wt-link';
          wtLink.innerHTML = `${ICO_BRANCH_SVG}<span>${shortBranch}</span>`;
          wtLink.title = `Worktree ${wtBranch} → ${wtBase} · click to merge or inspect`;
          wtLink.addEventListener('click', (e) => {
            e.stopPropagation();
            closeCardMenu();
            openWorktreePopover(t.address);
          });
          footL.append(wtSep, wtLink);
        }
        const footR = document.createElement('span');
        footR.className = 'agent-card-foot-r';
        footR.textContent = idx < 9 ? `Alt+${idx + 1}` : '';
        foot.append(footL, footR);
        card.appendChild(foot);

        card.addEventListener('contextmenu', (e) => {
          e.preventDefault();
          e.stopPropagation();
          openCardMenu(t, { x: e.clientX, y: e.clientY }, card);
        });

        if (state === 'working' && t.status && typeof t.status.progress === 'number') {
          const pBar = document.createElement('div');
          pBar.className = 'agent-card-bar';
          const pFill = document.createElement('i');
          pFill.style.width = `${Math.max(5, Math.min(100, t.status.progress))}%`;
          pBar.appendChild(pFill);
          card.appendChild(pBar);
        }

        const activateCard = () => {
          if (activeId !== t.address) connectPty(t.address);
          else focusTerminalIfDesktop();
        };
        card.addEventListener('click', activateCard);
        card.addEventListener('keydown', (e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            activateCard();
          }
        });
        sidebarAgentsEl.appendChild(card);
      } else {
        shellCount += 1;
        const btn = document.createElement('div');
        btn.className = `tab-item${isActive ? ' active' : ''}${state === 'blocked' ? ' is-blocked' : ''}${state === 'working' ? ' is-working' : ''}`;
        btn.setAttribute('role', 'tab');
        btn.setAttribute('aria-selected', isActive ? 'true' : 'false');
        btn.title = label;

        const info = document.createElement('div');
        info.className = 'tab-info';
        const titleEl = document.createElement('div');
        titleEl.className = 'tab-title';
        if (editingTabId === t.address) {
          const inp = document.createElement('input');
          inp.type = 'text';
          inp.className = 'inline-rename-input';
          inp.dataset.tab = t.address;
          inp.value = label;
          inp.maxLength = 60;
          inp.addEventListener('click', (e) => e.stopPropagation());
          inp.addEventListener('keydown', (e) => {
            e.stopPropagation();
            if (e.key === 'Enter') { e.preventDefault(); commitInlineRename(t.address, inp.value); }
            else if (e.key === 'Escape') { e.preventDefault(); editingTabId = null; renderTabs(); focusTerminalIfDesktop(); }
          });
          inp.addEventListener('blur', () => {
            if (editingTabId === t.address) commitInlineRename(t.address, inp.value);
          });
          titleEl.appendChild(inp);
        } else {
          const titleText = document.createElement('span');
          titleText.className = 'tab-title-text';
          titleText.textContent = label;
          titleText.addEventListener('dblclick', (e) => { e.stopPropagation(); startInlineRename(t.address); });
          titleEl.appendChild(titleText);
        }
        const subEl = document.createElement('div');
        subEl.className = 'tab-sub';
        subEl.textContent = subText;
        info.append(titleEl, subEl);

        const right = document.createElement('div');
        right.className = 'tab-right';
        const idxEl = document.createElement('span');
        idxEl.className = 'tab-idx';
        idxEl.textContent = idx < 9 ? String(idx + 1) : '';
        const closeBtn = document.createElement('button');
        closeBtn.className = 'tab-close';
        closeBtn.title = 'Close tab';
        closeBtn.setAttribute('aria-label', `Close ${label}`);
        closeBtn.textContent = '✕';
        closeBtn.addEventListener('click', async (e) => {
          e.stopPropagation();
          await fetch(`/api/tabs/${encodeURIComponent(t.address)}`, { method: 'DELETE' });
        });
        right.append(idxEl, closeBtn);

        btn.append(makeMiniPixelIcon(iconKind), info, right);
        btn.addEventListener('click', () => {
          if (activeId !== t.address) connectPty(t.address);
          else focusTerminalIfDesktop();
        });
        sidebarTabsEl.appendChild(btn);
      }

      // 2. Informative Horizontal Topbar Tab (Desktop — auto-shown when sidebar is collapsed via Alt+B)
      if (topbarTabsEl) {
        const tt = document.createElement('div');
        tt.className = `top-tab${isActive ? ' active' : ''}`;
        tt.setAttribute('role', 'tab');
        tt.setAttribute('aria-selected', isActive ? 'true' : 'false');
        tt.title = `${label} — ${subText || state}`;

        const ttName = document.createElement('span');
        ttName.className = 'top-tab-name';
        ttName.textContent = label;
        const ttNum = document.createElement('span');
        ttNum.className = 'top-tab-num';
        ttNum.textContent = idx < 9 ? String(idx + 1) : '';
        const ttClose = document.createElement('button');
        ttClose.type = 'button';
        ttClose.className = 'top-tab-close';
        ttClose.title = 'Close tab';
        ttClose.setAttribute('aria-label', `Close ${label}`);
        ttClose.textContent = '×';
        ttClose.addEventListener('click', async (e) => {
          e.stopPropagation();
          await fetch(`/api/tabs/${encodeURIComponent(t.address)}`, { method: 'DELETE' });
        });

        tt.append(makeMiniPixelIcon(iconKind), ttName, ttNum);
        if (state === 'working' || state === 'blocked' || state === 'done') {
          const td = document.createElement('span');
          td.className = 'status-dot';
          td.dataset.state = state;
          tt.appendChild(td);
        }
        tt.appendChild(ttClose);
        tt.addEventListener('click', () => {
          if (activeId !== t.address) connectPty(t.address);
          else focusTerminalIfDesktop();
        });
        topbarTabsEl.appendChild(tt);
      }

      // 3. Mobile tab chip (with mini pixel icon!)
      const m = document.createElement('button');
      m.className = `m-tab${isActive ? ' active' : ''}`;
      const mName = document.createElement('span');
      mName.className = 'm-tab-name';
      mName.textContent = label.length > 14 ? label.slice(0, 13) + '…' : label;
      m.append(makeMiniPixelIcon(iconKind), mName);
      if (state === 'working' || state === 'blocked' || state === 'done') {
        const mDot = document.createElement('span');
        mDot.className = 'status-dot';
        mDot.dataset.state = state;
        m.appendChild(mDot);
      }
      m.addEventListener('click', () => {
        if (activeId !== t.address) connectPty(t.address);
      });
      mobileTabsEl.appendChild(m);
    });

    tabCountEl.textContent = String(shellCount);

    // 4. Parked Pinned Sessions (desktop sidebar + mobile tab strip)
    const parkedPins = (Array.isArray(pins) ? pins : []).filter((p) => p && p.parked);
    if (sidebarParkedSectionEl && sidebarParkedEl) {
      sidebarParkedSectionEl.classList.toggle('hidden', parkedPins.length === 0);
      if (parkedCountEl) parkedCountEl.textContent = String(parkedPins.length);
      sidebarParkedEl.innerHTML = '';
      for (const pin of parkedPins) {
        const pKind = pin.agent && PIXEL_SVG[pin.agent] ? pin.agent : 'shell';
        const card = document.createElement('div');
        card.className = 'agent-card is-parked';
        card.dataset.agent = pKind;
        card.title = pin.missing_cwd
          ? `Directory missing: ${pin.cwd}`
          : `Click to wake ${pin.title} (${pin.agent || 'shell'} · ${pin.resume || 'continue'})`;

        const main = document.createElement('div');
        main.className = 'agent-card-main';
        const stage = document.createElement('div');
        stage.className = 'pixel-stage';
        stage.innerHTML = pixelIconHtml(pKind);
        const info = document.createElement('div');
        info.className = 'agent-card-info';
        const top = document.createElement('div');
        top.className = 'agent-card-top';
        const badge = document.createElement('span');
        badge.className = 'agent-state-box';
        badge.textContent = pin.missing_cwd ? 'MISSING' : 'PARKED';
        const right = document.createElement('div');
        right.className = 'agent-card-right';
        const dismissBtn = document.createElement('button');
        dismissBtn.type = 'button';
        dismissBtn.className = 'agent-card-close';
        dismissBtn.title = 'Dismiss saved session';
        dismissBtn.setAttribute('aria-label', `Dismiss ${pin.title || 'session'}`);
        dismissBtn.textContent = '✕';
        dismissBtn.addEventListener('click', (e) => { e.stopPropagation(); unpinById(pin.id); });
        right.append(dismissBtn);
        top.append(badge, right);

        const nm = document.createElement('div');
        nm.className = 'agent-card-name';
        nm.textContent = pin.title || shortDisplayPath(pin.cwd) || 'pinned';
        const msg = document.createElement('div');
        msg.className = 'agent-card-msg';
        msg.textContent = pin.worktree && pin.worktree.branch
          ? `${shortDisplayPath(pin.cwd)} · ${pin.worktree.branch}`
          : shortDisplayPath(pin.cwd);
        info.append(top, nm, msg);
        main.append(stage, info);

        const foot = document.createElement('div');
        foot.className = 'agent-card-foot';
        const fl = document.createElement('span');
        fl.textContent = `${AGENT_FULL_NAMES[pKind] || pKind} · ${pin.resume === 'fresh' ? 'fresh' : '--continue'}`;
        const wake = document.createElement('span');
        wake.className = `wake-pill${pin.missing_cwd ? ' is-missing' : ''}`;
        wake.textContent = pin.missing_cwd ? 'Missing dir' : '▶ Wake';
        foot.append(fl, wake);
        card.append(main, foot);

        card.addEventListener('click', () => { if (!pin.missing_cwd) wakePin(pin.id); });
        sidebarParkedEl.appendChild(card);
      }
    }

    // Parked chips on mobile tab strip (1 tap wakes!)
    for (const pin of parkedPins) {
      const pKind = pin.agent && PIXEL_SVG[pin.agent] ? pin.agent : 'shell';
      const mp = document.createElement('button');
      mp.className = 'm-tab is-parked';
      const mpName = document.createElement('span');
      mpName.className = 'm-tab-name';
      const lbl = pin.title || 'pin';
      mpName.textContent = (lbl.length > 11 ? lbl.slice(0, 10) + '…' : lbl) + ' ▶';
      mp.append(makeMiniPixelIcon(pKind), mpName);
      mp.title = `Wake pinned session ${lbl}`;
      mp.addEventListener('click', () => wakePin(pin.id));
      mobileTabsEl.appendChild(mp);
    }

    // Pending worktrees pill in sidebar
    if (sidebarPendingWtEl) {
      const pCount = Array.isArray(pendingWorktrees) ? pendingWorktrees.length : 0;
      sidebarPendingWtEl.classList.toggle('hidden', pCount === 0);
      if (pendingWtCountEl) pendingWtCountEl.textContent = String(pCount);
    }

    if (topbarTabsEl) {
      const tPlus = document.createElement('button');
      tPlus.type = 'button';
      tPlus.className = 'top-tab top-tab-add';
      tPlus.textContent = '+';
      tPlus.title = 'New terminal tab (Alt+N)';
      tPlus.setAttribute('aria-label', 'New terminal tab');
      tPlus.addEventListener('click', () => { spawnTab('shell'); focusTerminalIfDesktop(); });
      topbarTabsEl.appendChild(tPlus);
    }

    if (agentsBusyCountEl) {
      agentsBusyCountEl.textContent = `${busyCount} busy`;
      agentsBusyCountEl.classList.toggle('has-busy', busyCount > 0);
    }
    if (sidebarAgentsSectionEl) {
      sidebarAgentsSectionEl.classList.toggle('is-empty', agentCount === 0);
    }
    if (sidebarAgentsEl && agentCount === 0) {
      const empty = document.createElement('div');
      empty.className = 'agents-empty';
      empty.textContent = 'Run claude, agy, codex, or opencode in a shell to spawn an agent card.';
      sidebarAgentsEl.appendChild(empty);
    }

    const mPlus = document.createElement('button');
    mPlus.className = 'm-tab m-tab-add';
    mPlus.textContent = '+';
    mPlus.title = 'New agent or shell tab';
    mPlus.setAttribute('aria-label', 'New agent or shell tab');
    mPlus.addEventListener('click', () => openNewAgentPopover(true));
    mobileTabsEl.appendChild(mPlus);

    const active = terminals.find((t) => t.address === activeId);
    if (active) {
      const aParts = tabTitleParts(active);
      const aState = tabState(active);
      const aKind = tabAgentKind(active) || 'shell';
      const aSub = tabSubtitle(active);
      activeDotEl.dataset.state = aState;
      activeNameEl.textContent = aParts.title;
      if (activeAgentEl) {
        activeAgentEl.textContent = aParts.pill;
        activeAgentEl.classList.toggle('hidden', !aParts.pill);
      }
      if (activeStatusEl) activeStatusEl.textContent = aSub;
      if (termCtxIconEl) termCtxIconEl.innerHTML = pixelIconHtml(aKind);
      if (termCtxTitleEl) termCtxTitleEl.textContent = aParts.pill ? `${aParts.title} (${AGENT_FULL_NAMES[aParts.pill] || aParts.pill})` : aParts.title;
      const aWtBranch = active.labels && active.labels['swarmbox.worktree'] ? (active.labels['swarmbox.branch'] || 'worktree') : '';
      const aWtBase = (active.labels && active.labels['swarmbox.base']) || 'main';
      if (topbarWtBtnEl) {
        topbarWtBtnEl.classList.toggle('hidden', !aWtBranch);
        if (aWtBranch) topbarWtBtnEl.innerHTML = `${ICO_BRANCH_SVG}<span>${aWtBranch} → ${aWtBase} ▾</span>`;
      }
      if (mobileWtBtnEl) {
        mobileWtBtnEl.classList.toggle('hidden', !aWtBranch);
        if (aWtBranch) mobileWtBtnEl.innerHTML = `${ICO_BRANCH_SVG}<span>${aWtBranch.replace(/^sb\//, '')}</span>`;
      }
      if (termCtxStateEl) {
        termCtxStateEl.dataset.state = aState;
        termCtxStateEl.textContent = stateBadgeText(aState, active.status);
      }
    } else {
      const hasParked = parkedPins.length > 0;
      activeDotEl.dataset.state = 'idle';
      activeNameEl.textContent = hasParked ? 'Sessions parked' : 'No active tab';
      if (activeAgentEl) activeAgentEl.classList.add('hidden');
      if (topbarWtBtnEl) topbarWtBtnEl.classList.add('hidden');
      if (mobileWtBtnEl) mobileWtBtnEl.classList.add('hidden');
      if (activeStatusEl) activeStatusEl.textContent = hasParked ? `${parkedPins.length} parked` : 'idle';
      if (termCtxIconEl) termCtxIconEl.innerHTML = pixelIconHtml('shell');
      if (termCtxTitleEl) termCtxTitleEl.textContent = hasParked ? 'Sessions parked' : 'No active tab';
      if (termCtxStateEl) {
        termCtxStateEl.dataset.state = 'idle';
        termCtxStateEl.textContent = hasParked ? 'PARKED' : 'IDLE';
      }
    }

    if (stageEmptyEl) {
      if (terminals.length > 0) {
        stageEmptyEl.classList.add('hidden');
        stageEmptyEl.innerHTML = '';
      } else {
        stageEmptyEl.classList.remove('hidden');
        stageEmptyEl.innerHTML = '';
        const card = document.createElement('div');
        card.className = 'stage-empty-card';
        const title = document.createElement('div');
        title.className = 'stage-empty-title';
        title.textContent = parkedPins.length > 0 ? 'Sessions parked' : 'No active sessions';
        const sub = document.createElement('div');
        sub.className = 'stage-empty-sub';
        sub.textContent = parkedPins.length > 0
          ? 'Wake a pinned session to resume where you left off, or start a fresh agent or shell.'
          : 'Open a new agent or shell tab to get started.';
        card.append(title, sub);
        if (parkedPins.length > 0) {
          const list = document.createElement('div');
          list.className = 'stage-empty-list';
          for (const pin of parkedPins) {
            const pKind = pin.agent && PIXEL_SVG[pin.agent] ? pin.agent : 'shell';
            const row = document.createElement('button');
            row.type = 'button';
            row.className = 'stage-empty-pin';
            row.disabled = Boolean(pin.missing_cwd);
            const left = document.createElement('span');
            left.className = 'stage-empty-pin-left';
            const meta = document.createElement('span');
            meta.className = 'stage-empty-pin-meta';
            const nm = document.createElement('span');
            nm.className = 'stage-empty-pin-name';
            nm.textContent = pin.title || shortDisplayPath(pin.cwd) || 'pinned';
            const pt = document.createElement('span');
            pt.className = 'stage-empty-pin-path';
            pt.textContent = `${AGENT_FULL_NAMES[pKind] || pKind} · ${shortDisplayPath(pin.cwd)}`;
            meta.append(nm, pt);
            left.append(makeMiniPixelIcon(pKind), meta);
            const pill = document.createElement('span');
            pill.className = `wake-pill${pin.missing_cwd ? ' is-missing' : ''}`;
            pill.textContent = pin.missing_cwd ? 'Missing dir' : '▶ Wake';
            row.append(left, pill);
            row.addEventListener('click', () => { if (!pin.missing_cwd) wakePin(pin.id); });
            list.appendChild(row);
          }
          card.appendChild(list);
        }
        const actions = document.createElement('div');
        actions.className = 'stage-empty-actions';
        const btnAg = document.createElement('button');
        btnAg.type = 'button';
        btnAg.className = 'stage-empty-btn';
        btnAg.textContent = '+ New agent';
        btnAg.addEventListener('click', () => openNewAgentPopover());
        const btnSh = document.createElement('button');
        btnSh.type = 'button';
        btnSh.className = 'stage-empty-btn';
        btnSh.textContent = '+ New shell';
        btnSh.addEventListener('click', () => spawnTab('shell'));
        actions.append(btnAg, btnSh);
        card.appendChild(actions);
        stageEmptyEl.appendChild(card);
      }
    }

    if (statusbarSummaryEl) {
      const tabLabel = terminals.length === 1 ? '1 tab' : `${terminals.length} tabs`;
      const agLabel = agentCount === 1 ? '1 agent' : `${agentCount} agents`;
      const parts = [tabLabel, agLabel];
      if (parkedPins.length > 0) parts.push(`${parkedPins.length} parked`);
      if (busyCount > 0) parts.push(`${busyCount} busy`);
      statusbarSummaryEl.textContent = parts.join(' · ');
    }
  }

  function stopCountdownTimer() {
    if (countdownTimer) {
      clearInterval(countdownTimer);
      countdownTimer = null;
    }
  }

  function renderApprovalCard(sysop) {
    stopCountdownTimer();
    const pending = sysop && sysop.pending;
    const oscBlocked = sysop && Array.isArray(sysop.blocked) && sysop.blocked.length ? sysop.blocked[0] : null;

    if (pending) {
      const isVeto = pending.mode === 'veto';
      currentApproval = { kind: 'sysop', deadline: pending.deadline };
      approvalCardEl.classList.remove('hidden');
      mobileApprovalEl.classList.remove('hidden');
      const badge = isVeto ? 'Sending…' : 'Confirm action';
      approvalBadgeEl.textContent = badge;
      mobileApprovalBadgeEl.textContent = badge;
      const pendingTabObj = pending.tab ? terminals.find((t) => t.address === pending.tab) : null;
      approvalTabEl.textContent = pendingTabObj ? tabDisplayName(pendingTabObj) : (pending.label || pending.tab || 'sysop');
      approvalTextEl.textContent = pending.text || 'Pending action';
      mobileApprovalMsgEl.textContent = pending.text || 'Pending action';

      if (pending.deadline) {
        const rem = Math.max(0, pending.deadline - Date.now() / 1000);
        const total = Math.max(rem, 4);
        approvalBarEl.classList.remove('hidden');
        const tick = () => {
          const left = Math.max(0, pending.deadline - Date.now() / 1000);
          approvalBarFillEl.style.width = `${Math.min(100, (left / total) * 100)}%`;
          if (left <= 0) stopCountdownTimer();
        };
        tick();
        countdownTimer = setInterval(tick, 150);
      } else {
        approvalBarEl.classList.add('hidden');
      }

      requestAnimationFrame(fitAndResize);
      return;
    }

    if (oscBlocked) {
      currentApproval = { kind: 'osc', terminal: oscBlocked.terminal };
      approvalCardEl.classList.remove('hidden');
      mobileApprovalEl.classList.remove('hidden');
      approvalBarEl.classList.add('hidden');
      approvalBadgeEl.textContent = 'Agent asks';
      mobileApprovalBadgeEl.textContent = 'Agent asks';
      approvalTabEl.textContent = oscBlocked.name;
      approvalTextEl.textContent = oscBlocked.msg;
      mobileApprovalMsgEl.textContent = `${oscBlocked.name}: ${oscBlocked.msg}`;
      requestAnimationFrame(fitAndResize);
      return;
    }

    const wasVisible = !mobileApprovalEl.classList.contains('hidden');
    currentApproval = null;
    approvalCardEl.classList.add('hidden');
    mobileApprovalEl.classList.add('hidden');
    approvalBarEl.classList.add('hidden');
    if (wasVisible) requestAnimationFrame(fitAndResize);
  }

  // ---- Sysop conversation (V2): one turn per goal, no nested boxes. The user's words in a bubble, the sysop's reply as plain text under a
  // "Sysop · N actions" line, and an action that waits for the user as a calm confirmation card inside the conversation.
  const openTurnActions = new Set();   // turn ids whose action list the user expanded (survives the 600 ms re-renders)
  let lastFeedKey = '';
  const SYSOP_SUGGESTIONS = ["What's running across my tabs?", 'Summarize the active agent', 'Check git status & tests'];
  const STATE_WORDS = { idle: 'ready', 'allow?': 'confirm', sending: 'sending', working: 'working', queued: 'queued', done: 'ready', failed: 'failed', stopped: 'ready', off: 'off' };
  const MIC_SVG = '<svg viewBox="0 0 24 24" width="11" height="11" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/></svg>';

  // Every tab a reply names (`shop-api`, t3, 1:shop-api, "shop-api (t3)") becomes the same chip: the agent's pixel icon and the tab's name.
  // tabrefs.js finds them; a tab that has closed since keeps its name (the page remembers the tabs it saw) and is drawn dimmed, without a link.
  const KNOWN_TABS_KEY = 'sb.sysop.knownTabs';
  let knownTabs = {};
  try { knownTabs = JSON.parse(localStorage.getItem(KNOWN_TABS_KEY) || '{}') || {}; } catch (_) { knownTabs = {}; }

  function rememberTabs() {
    let changed = false;
    for (const t of terminals) {
      if (!t || !t.address) continue;
      const rec = { name: tabDisplayName(t), alias: String(t.name || ''), kind: tabAgentKind(t) || 'shell' };
      const old = knownTabs[t.address];
      if (!old || old.name !== rec.name || old.kind !== rec.kind || old.alias !== rec.alias) {
        knownTabs[t.address] = rec;
        changed = true;
      }
    }
    if (!changed) return;
    const keys = Object.keys(knownTabs);
    for (const k of keys.slice(0, Math.max(0, keys.length - 80))) delete knownTabs[k];
    try { localStorage.setItem(KNOWN_TABS_KEY, JSON.stringify(knownTabs)); } catch (_) {}
  }

  function tabRefContext() {
    const live = new Set();
    const out = [];
    for (const t of terminals) {
      if (!t || !t.address) continue;
      live.add(t.address);
      out.push({ address: t.address, name: tabDisplayName(t), aliases: t.name ? [String(t.name)] : [], kind: tabAgentKind(t) || 'shell', live: true });
    }
    for (const [address, rec] of Object.entries(knownTabs)) {
      if (!live.has(address)) out.push({ address, name: rec.name, aliases: rec.alias ? [rec.alias] : [], kind: rec.kind, live: false });
    }
    return out;
  }

  function tabChip(tab) {
    const chip = document.createElement('span');
    chip.className = `tab-ref${tab.live ? '' : ' closed'}`;
    chip.appendChild(makeMiniPixelIcon(tab.kind || 'shell'));
    const name = document.createElement('span');
    name.className = 'tab-ref-name';
    name.textContent = tab.name;
    chip.appendChild(name);
    if (!tab.live) {
      chip.title = tab.unknown ? 'Tab no longer open' : `${tab.name} is closed`;
      return chip;
    }
    chip.title = `Switch to ${tab.name}`;
    chip.setAttribute('role', 'button');
    chip.tabIndex = 0;
    const go = () => {
      if (activeId !== tab.address) connectPty(tab.address);
      else focusTerminalIfDesktop();
    };
    chip.addEventListener('click', go);
    chip.addEventListener('keydown', (ev) => {
      if (ev.key === 'Enter' || ev.key === ' ') {
        ev.preventDefault();
        go();
      }
    });
    return chip;
  }

  function linkTabs(text) {
    const frag = document.createDocumentFragment();
    const segs = window.SbTabRefs ? window.SbTabRefs.parse(text, tabRefContext()) : [{ t: 'text', v: String(text || '') }];
    for (let i = 0; i < segs.length; i++) {
      const seg = segs[i];
      if (seg.t === 'tab') {
        // a parenthesis around a chip stays on its line: "(" + chip + ")" never breaks apart
        const prev = frag.lastChild;
        const next = segs[i + 1];
        const glue = document.createElement('span');
        glue.className = 'tab-ref-glue';
        if (prev && prev.nodeType === 3 && /\($/.test(prev.data)) {
          prev.data = prev.data.slice(0, -1);
          glue.append('(');
        }
        glue.appendChild(tabChip(seg.tab));
        if (next && next.t === 'text' && /^[),.;:]/.test(next.v)) {
          glue.append(next.v[0]);
          next.v = next.v.slice(1);
        }
        frag.appendChild(glue.childNodes.length > 1 ? glue : glue.firstChild);
      } else if (seg.t === 'text') frag.append(seg.v);
      else {
        const tag = seg.t === 'code' ? 'code' : seg.t === 'bold' ? 'strong' : 'span';
        const el = document.createElement(tag);
        if (tag === 'span') el.className = `tr-${seg.t}`;
        el.textContent = seg.v;
        frag.appendChild(el);
      }
    }
    return frag;
  }

  // "- item" lines become rows (a tab named first gets its agent's pixel icon); any other line is a paragraph
  function renderReplyText(text) {
    const wrap = document.createElement('div');
    wrap.className = 'turn-reply';
    let list = null;
    for (const raw of String(text || '').split('\n')) {
      const line = raw.trim();
      if (!line) {
        list = null;
        continue;
      }
      const bullet = /^[-•*]\s+(.*)$/.exec(line);
      if (bullet) {
        if (!list) {
          list = document.createElement('ul');
          wrap.appendChild(list);
        }
        const li = document.createElement('li');
        const frag = linkTabs(bullet[1].replace(/^(`[^`]+`|[t@]\d[a-z0-9]{0,3}|\d+:[\w.-]+)\s*:\s*/i, '$1 '));
        let first = frag.firstChild;
        if (first && first.nodeType === 1 && first.classList.contains('tab-ref-glue') && first.firstChild && first.firstChild.nodeType === 1
          && first.firstChild.classList.contains('tab-ref') && /^[:–—-]?$/.test(first.textContent.slice(first.firstChild.textContent.length))) {
          const chip = first.firstChild;
          frag.replaceChild(chip, first);       // "chip:" at the head of a row: the row is the chip, the colon goes
          first = chip;
        }
        const lead = first && first.nodeType === 1 && first.classList.contains('tab-ref') ? first : null;
        const rest = document.createElement('span');     // one flex item, so inline code in it flows with the text
        if (lead) {
          li.appendChild(lead);
          // "`name` (t3): text" left a colon behind the chip: the row already says whose it is
          const t0 = frag.firstChild;
          if (t0 && t0.nodeType === 3) t0.data = t0.data.replace(/^\s*[:–—-]\s*/, ' ').replace(/^\s+/, '');
        }
        rest.appendChild(frag);
        li.appendChild(rest);
        list.appendChild(li);
      } else {
        list = null;
        const pEl = document.createElement('p');
        pEl.appendChild(linkTabs(line));
        wrap.appendChild(pEl);
      }
    }
    return wrap;
  }

  function fmtAgo(ms) {
    if (!ms) return '';
    const m = Math.floor((Date.now() - ms) / 60000);
    if (m < 1) return 'now';
    if (m < 60) return `${m}m ago`;
    const h = Math.floor(m / 60);
    return h < 24 ? `${h}h ago` : `${Math.floor(h / 24)}d ago`;
  }

  function renderTurn(turn) {
    const el = document.createElement('div');
    el.className = `turn${turn.running ? ' running' : ''}`;
    el.dataset.state = turn.state || '';

    if (turn.prompt) {
      const ask = document.createElement('div');
      ask.className = 'turn-ask';
      const bubble = document.createElement('div');
      bubble.className = 'turn-ask-bubble';
      bubble.textContent = turn.prompt;
      const meta = document.createElement('div');
      meta.className = 'turn-meta';
      if (turn.source === 'voice') meta.insertAdjacentHTML('beforeend', MIC_SVG);
      meta.append(fmtAgo(turn.started));
      ask.append(bubble, meta);
      el.appendChild(ask);
    }

    const said = document.createElement('div');
    said.className = 'turn-sysop';
    const head = document.createElement('div');
    head.className = 'turn-sysop-head';
    head.appendChild(makeMiniPixelIcon('sysop'));
    const who = document.createElement('span');
    who.className = 'turn-who';
    who.textContent = 'Sysop';
    head.appendChild(who);
    const acts = Array.isArray(turn.actions) ? turn.actions : [];
    let list = null;
    if (acts.length) {
      const failed = acts.filter((a) => !a.ok).length;
      const open = openTurnActions.has(turn.id);
      const tog = document.createElement('button');
      tog.type = 'button';
      tog.className = 'turn-acts-toggle';
      tog.setAttribute('aria-expanded', String(open));
      tog.textContent = `${open ? '▾' : '▸'} ${acts.length} action${acts.length === 1 ? '' : 's'}${failed ? ` · ${failed} failed` : ''}`;
      list = document.createElement('ol');
      list.className = 'turn-acts';
      list.hidden = !open;
      for (const a of acts) {
        const li = document.createElement('li');
        li.className = a.ok ? 'ok' : 'err';
        const mark = document.createElement('span');
        mark.className = 'turn-act-mark';
        mark.textContent = a.ok ? '✓' : '✕';
        li.append(mark, linkTabs(a.label || a.fn || 'step'));
        list.appendChild(li);
      }
      tog.addEventListener('click', () => {
        const now = list.hidden;
        list.hidden = !now;
        if (now) openTurnActions.add(turn.id);
        else openTurnActions.delete(turn.id);
        tog.setAttribute('aria-expanded', String(now));
        tog.textContent = tog.textContent.replace(/^[▸▾]/, now ? '▾' : '▸');
      });
      const dot = document.createElement('span');
      dot.className = 'turn-sep';
      dot.textContent = '·';
      head.append(dot, tog);
    }
    said.appendChild(head);
    if (list) said.appendChild(list);

    for (const n of Array.isArray(turn.notes) ? turn.notes : []) {
      const note = document.createElement('div');
      note.className = 'turn-note';
      note.appendChild(linkTabs(String(n)));
      said.appendChild(note);
    }
    if (turn.running) {
      const live = document.createElement('div');
      live.className = 'turn-live';
      const dot = document.createElement('span');
      dot.className = 'turn-live-dot';
      const txt = document.createElement('span');
      txt.textContent = turn.live_action || 'Thinking…';
      live.append(dot, txt);
      said.appendChild(live);
    } else if (turn.reply) {
      const rep = renderReplyText(turn.reply);
      rep.dataset.state = turn.state || 'done';
      said.appendChild(rep);
    }
    el.appendChild(said);
    return el;
  }

  function renderSysopEmpty(sysop) {
    const box = document.createElement('div');
    box.className = 'sysop-empty';
    const icon = document.createElement('div');
    icon.className = 'sysop-empty-icon';
    icon.innerHTML = pixelIconHtml('sysop');
    const title = document.createElement('div');
    title.className = 'sysop-empty-title';
    title.textContent = sysop.up ? 'Sysop Operator' : 'Sysop is offline';
    const desc = document.createElement('p');
    desc.className = 'sysop-empty-desc';
    box.append(icon, title, desc);
    if (!sysop.up) {
      desc.innerHTML = 'Install it from Settings › Addons, or run <code>swarmbox addon install sysop</code>.';
      return box;
    }
    const policy = (sysop.settings && sysop.settings.autonomy) || '';
    desc.textContent = policy === 'full-auto'
      ? "Ask what's happening in your box or direct your agents — what you ask, it does."
      : "Ask what's happening in your box or direct your agents — risky actions pause for you.";
    if (policy) {
      const pol = document.createElement('div');
      pol.className = 'sysop-empty-policy';
      pol.textContent = `policy · ${policy}`;
      box.appendChild(pol);
    }
    const sugg = document.createElement('div');
    sugg.className = 'sysop-suggest';
    for (const text of SYSOP_SUGGESTIONS) {
      const b = document.createElement('button');
      b.type = 'button';
      b.className = 'sysop-suggest-btn';
      const label = document.createElement('span');
      label.textContent = text;
      const ret = document.createElement('span');
      ret.className = 'sysop-suggest-ret';
      ret.textContent = '↵';
      b.append(label, ret);
      b.addEventListener('click', () => sendGoal(text));
      sugg.appendChild(b);
    }
    box.appendChild(sugg);
    return box;
  }

  function renderSystemEventRow(ev, opts = {}) {
    const row = document.createElement('div');
    const liveTab = ev.tab ? terminals.find((t) => t.address === ev.tab) : null;
    const isLive = Boolean(liveTab);
    const canRename = Boolean(ev.kind === 'autoname' && isLive && opts.isLatestForTab);
    row.className = `sysop-sysev${isLive ? '' : ' is-closed'}`;

    const body = document.createElement('div');
    body.className = 'sysop-sysev-body';

    if (ev.kind === 'autoname') {
      const ico = document.createElement('span');
      ico.className = 'sysop-sysev-ico';
      ico.innerHTML = ICO_PENCIL_SVG;

      const textWrap = document.createElement('span');
      textWrap.className = 'sysop-sysev-text';
      const oldS = String(ev.old_title || ev.tab || 'tab');
      const newS = String(ev.new_title || '');
      const known = ev.tab ? knownTabs[ev.tab] : null;
      const chipKind = (liveTab && (tabAgentKind(liveTab) || 'shell'))
        || (ev.agent && PIXEL_SVG[ev.agent] ? ev.agent : '')
        || (known && known.kind)
        || 'shell';
      const chipObj = {
        address: ev.tab || '',
        name: newS || (liveTab ? tabDisplayName(liveTab) : oldS),
        kind: chipKind,
        live: isLive,
        unknown: !isLive && !known,
      };

      const oldEl = document.createElement('span');
      oldEl.className = 'sysop-sysev-old';
      oldEl.textContent = oldS;
      const arrow = document.createElement('span');
      arrow.className = 'sysop-sysev-arrow';
      arrow.textContent = '→';

      textWrap.append('Renamed ', oldEl, ' ', arrow, ' ', tabChip(chipObj));
      body.append(ico, textWrap);
    } else {
      const textWrap = document.createElement('span');
      textWrap.className = 'sysop-sysev-text';
      textWrap.textContent = ev.text || ev.kind;
      body.appendChild(textWrap);
    }

    const meta = document.createElement('div');
    meta.className = 'sysop-sysev-meta';
    if (ev.kind === 'autoname' && !isLive) {
      const closedTag = document.createElement('span');
      closedTag.className = 'sysop-sysev-state';
      closedTag.textContent = 'closed';
      meta.appendChild(closedTag);
    }
    const ago = fmtAgo(ev.ts);
    if (ago) {
      const tm = document.createElement('span');
      tm.className = 'sysop-sysev-time';
      tm.textContent = ago;
      meta.appendChild(tm);
    }
    if (canRename) {
      const editBtn = document.createElement('button');
      editBtn.type = 'button';
      editBtn.className = 'sysop-sysev-edit';
      editBtn.title = 'Rename this tab';
      editBtn.setAttribute('aria-label', `Rename ${ev.new_title || ev.tab}`);
      editBtn.innerHTML = `${ICO_PENCIL_SVG}<span>Rename</span>`;
      editBtn.addEventListener('click', () => startInlineRename(ev.tab));
      meta.appendChild(editBtn);
    }

    row.append(body, meta);
    return row;
  }

  function renderSysopFeed(sysop) {
    const turns = Array.isArray(sysop.turns) ? sysop.turns : null;
    const sysEvents = Array.isArray(sysop.system_events) ? sysop.system_events : [];
    const steps = Array.isArray(sysop.steps) ? sysop.steps : [];
    const hasTurns = turns ? turns.length > 0 : steps.length > 0;
    const empty = !hasTurns && sysEvents.length === 0;
    sysopFeedEl.classList.toggle('is-empty', !hasTurns || !sysop.up);
    const keyHint = window.innerWidth <= 860 ? '' : ' (Alt+G)';
    goalInputEl.placeholder = (!hasTurns ? (window.innerWidth <= 860 ? 'Ask Sysop…' : 'Ask Sysop or direct an agent…') : 'Ask a follow-up…') + keyHint;
    btnSysopNew.classList.toggle('hidden', empty || !sysop.up);
    // the snapshot comes every 600 ms: rebuild only when something shown changed (the minute keeps "3m ago" true)
    const key = JSON.stringify([sysop.up, sysop.settings && sysop.settings.autonomy, turns, sysEvents, turns ? null : steps,
      terminals.map((t) => [t.address, tabDisplayName(t), tabAgentKind(t)]), Math.floor(Date.now() / 60000)]);
    if (key !== lastFeedKey) {
      lastFeedKey = key;
      const nearBottom = sysopFeedEl.scrollHeight - sysopFeedEl.scrollTop - sysopFeedEl.clientHeight < 48;
      sysopFeedEl.innerHTML = '';
      // Track the most recent autoname event per live tab so only the current name offers a Rename button
      const latestRenameByTab = new Map();
      for (const ev of sysEvents) {
        if (ev && ev.kind === 'autoname' && ev.tab) {
          latestRenameByTab.set(ev.tab, ev.id);
        }
      }
      if (!sysop.up || empty) {
        sysopFeedEl.appendChild(renderSysopEmpty(sysop));
      } else if (turns && !hasTurns) {
        // Background auto-renames alone never hide Sysop's welcome & starter prompts
        sysopFeedEl.appendChild(renderSysopEmpty(sysop));
        const grp = document.createElement('div');
        grp.className = 'sysop-sysev-group sysop-sysev-recent';
        for (const ev of sysEvents.slice(-4)) {
          grp.appendChild(renderSystemEventRow(ev, { isLatestForTab: latestRenameByTab.get(ev.tab) === ev.id }));
        }
        sysopFeedEl.appendChild(grp);
      } else if (turns) {
        const timeline = [
          ...turns.map((t) => ({ kind: 'turn', ts: t.started || 0, item: t })),
          ...sysEvents.map((e) => ({ kind: 'sysev', ts: e.ts || 0, item: e })),
        ].sort((a, b) => a.ts - b.ts);
        let sysevGroup = null;
        for (const entry of timeline) {
          if (entry.kind === 'turn') {
            sysevGroup = null;
            sysopFeedEl.appendChild(renderTurn(entry.item));
          } else {
            if (!sysevGroup) {
              sysevGroup = document.createElement('div');
              sysevGroup.className = 'sysop-sysev-group';
              sysopFeedEl.appendChild(sysevGroup);
            }
            const ev = entry.item;
            sysevGroup.appendChild(renderSystemEventRow(ev, { isLatestForTab: latestRenameByTab.get(ev.tab) === ev.id }));
          }
        }
      } else {
        // an older gateway without turns: the flat steps of the current goal
        for (const s of steps) {
          const div = document.createElement('div');
          div.className = `step ${s.kind || 'info'}`;
          div.textContent = s.text || '';
          sysopFeedEl.appendChild(div);
        }
      }
      if (nearBottom || !sysopFeedEl.dataset.seen) sysopFeedEl.scrollTop = sysopFeedEl.scrollHeight;
      sysopFeedEl.dataset.seen = '1';
    }
    // the confirmation lives in the conversation, right under the turn that waits for it
    const host = sysopFeedEl.querySelector('.turn.running .turn-sysop') || sysopFeedEl;
    if (approvalCardEl.parentNode !== host) host.appendChild(approvalCardEl);
    if (!approvalCardEl.classList.contains('hidden')) sysopFeedEl.scrollTop = sysopFeedEl.scrollHeight;
  }

  function renderSysop(sysop) {
    if (!sysop) return;
    const st = sysop.state || 'off';
    if (sysopDotEl) sysopDotEl.dataset.state = st;
    sysopStateEl.dataset.state = st;
    sysopStateEl.textContent = STATE_WORDS[st] || st;
    if (mobileSysopBtn) mobileSysopBtn.dataset.state = st;
    if (mobileSysopTextEl) mobileSysopTextEl.textContent = st === 'idle' || st === 'off' ? 'Sysop' : (sysop.sentence || `Sysop · ${st}`);
    if (btnToggleSysop) btnToggleSysop.dataset.state = st;

    const running = st === 'working' || st === 'allow?' || st === 'sending' || st === 'queued';
    btnSysopStop.classList.toggle('hidden', !running);

    renderApprovalCard(sysop);
    renderSysopFeed(sysop);
  }

  let noteTimer = null;
  function showVoiceNote(msg, tone = '', ms = 4000) {
    clearTimeout(noteTimer);
    if (!msg) {
      voiceNoteEl.classList.add('hidden');
      return;
    }
    voiceNoteEl.textContent = msg;
    voiceNoteEl.dataset.tone = tone;
    voiceNoteEl.classList.remove('hidden');
    if (ms) noteTimer = setTimeout(() => voiceNoteEl.classList.add('hidden'), ms);
  }

  function connectEvents() {
    if (eventsWs && (eventsWs.readyState === 0 || eventsWs.readyState === 1)) return;
    const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    const ws = new WebSocket(`${proto}//${location.host}/ws/events`);
    eventsWs = ws;

    ws.onopen = () => {
      if (eventsWs !== ws) return;
      eventsConnected = true;
      syncConnPill();
    };
    ws.onclose = () => {
      if (eventsWs !== ws) return;
      eventsWs = null;
      eventsConnected = false;
      syncConnPill();
      setTimeout(connectEvents, 1200);
    };
    ws.onmessage = (ev) => {
      if (eventsWs !== ws) return;
      let msg;
      try { msg = JSON.parse(ev.data); } catch (_) { return; }
      if (msg.theme && THEMES[msg.theme] && msg.theme !== currentThemeKey) {
        applyTheme(msg.theme, false);
      }
      if (Array.isArray(msg.pins)) pins = msg.pins;
      if (Array.isArray(msg.worktrees)) pendingWorktrees = msg.worktrees;
      if (msg.worktree_prefs && typeof msg.worktree_prefs === 'object') worktreePrefs = msg.worktree_prefs;
      if (msg.session_prefs && typeof msg.session_prefs === 'object') sessionPrefs = msg.session_prefs;
      if (Array.isArray(msg.installed_agents)) installedAgents = msg.installed_agents;
      if (Array.isArray(msg.terminals)) {
        terminals = msg.terminals;
        rememberTabs();
        const liveAddrs = new Set(terminals.map((t) => t.address));
        for (const addr of Array.from(tabSessions.keys())) {
          if (!liveAddrs.has(addr)) disposeSession(addr);
        }
        if (!activeId || !liveAddrs.has(activeId)) {
          const preferred = msg.active && liveAddrs.has(msg.active)
            ? msg.active
            : (terminals[0] && terminals[0].address);
          if (preferred) connectPty(preferred);
          else { activeId = null; ptyConnected = false; syncConnPill(); renderTabs(); dismissBoot(); }
        } else {
          // If events reconnected after a brief blip and the active PTY socket died, heal it automatically
          const sess = activeSession();
          if (!sess || !sess.ws || sess.ws.readyState === 2 || sess.ws.readyState === 3) {
            connectPty(activeId, { silent: true, forceReconnect: true });
          } else {
            renderTabs();
          }
        }
      }
      // The active tab moved elsewhere (the Sysop's focus_tab, the cockpit, another browser): follow it. Only a CHANGE of the server's
      // active tab counts, so a snapshot sent before this browser's own click (still naming the old tab) never pulls it back.
      if (typeof msg.active === 'string' && msg.active) {
        const changed = lastServerActive !== null && msg.active !== lastServerActive;
        lastServerActive = msg.active;
        if (changed && msg.active !== activeId && terminals.some((t) => t.address === msg.active)) connectPty(msg.active);
      }
      if (msg.sysop) renderSysop(msg.sysop);
    };
  }

  async function spawnTab(preset, opts = {}) {
    const payload = { preset };
    if (opts.cwd) {
      payload.cwd = opts.cwd;
    } else if (preset === 'agent') {
      const cur = terminals.find((t) => t.address === activeId);
      const curCwd = (cur && cur.foreground && cur.foreground.cwd) || (cur && cur.cwd) || '';
      if (curCwd && curCwd.startsWith('/')) payload.cwd = curCwd;
    }
    if (opts.agent) payload.agent = opts.agent;
    if (opts.worktree_choice) payload.worktree_choice = opts.worktree_choice;

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
    showSysopReplyOnMobile();
    const r = await fetch('/api/sysop/goal', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ goal, terminal: activeId }),
    });
    if (!r.ok) {
      const data = await r.json().catch(() => ({}));
      showVoiceNote(data.message || 'Could not send goal to Sysop.', 'error', 6000);
    }
  }

  async function handleApproval(decision) {
    if (!currentApproval) return;
    if (currentApproval.kind === 'osc' && currentApproval.terminal) {
      await fetch(`/api/tabs/${encodeURIComponent(currentApproval.terminal)}/answer`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ decision }),
      });
      return;
    }
    const route = decision === 'allow' ? '/api/sysop/approve' : '/api/sysop/veto';
    await fetch(route, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });
  }

  // ---- Real Voice Addon — WhatsApp-style Tap-to-Record -> Live Waveform -> Send / Discard ----
  const VOICE_RATE = 16000;
  let wavRec = null;
  let speechRec = null;
  let recTimerHandle = null;
  let recStartMs = 0;

  const mobileVoiceTimerEl = document.getElementById('mobile-voice-timer');
  const sheetVoiceTimerEl = document.getElementById('sheet-voice-timer');
  const desktopVoiceTimerEl = document.getElementById('desktop-voice-timer');
  const mobileVoiceBars = Array.from(document.querySelectorAll('#mobile-voice-bars > i'));
  const sheetVoiceBars = Array.from(document.querySelectorAll('#sheet-voice-bars > i'));
  const desktopVoiceBars = Array.from(document.querySelectorAll('#desktop-voice-bars > i'));
  const btnMobileRecCancel = document.getElementById('btn-mobile-rec-cancel');
  const btnMobileRecSend = document.getElementById('btn-mobile-rec-send');
  const btnSheetRecCancel = document.getElementById('btn-sheet-rec-cancel');
  const btnSheetRecSend = document.getElementById('btn-sheet-rec-send');
  const btnDesktopRecCancel = document.getElementById('btn-desktop-rec-cancel');
  const btnDesktopRecSend = document.getElementById('btn-desktop-rec-send');

  function formatRecTime(ms) {
    const totalSec = Math.max(0, Math.floor(ms / 1000));
    const m = Math.floor(totalSec / 60);
    const s = totalSec % 60;
    return `${m}:${s < 10 ? '0' : ''}${s}`;
  }

  function updateVoiceTimers(text) {
    if (mobileVoiceTimerEl) mobileVoiceTimerEl.textContent = text;
    if (sheetVoiceTimerEl) sheetVoiceTimerEl.textContent = text;
    if (desktopVoiceTimerEl) desktopVoiceTimerEl.textContent = text;
  }

  function updateVoiceBars(level) {
    const norm = Math.max(0, Math.min(1, level));
    const now = Date.now() / 135;
    const paint = (bars, maxH) => {
      const mid = (bars.length - 1) / 2;
      bars.forEach((bar, i) => {
        const u = (i - mid) / (mid + 0.6);
        const bell = Math.exp(-u * u * 1.6);
        const wave = 0.5 + 0.35 * Math.sin(now + i * 0.65) + 0.15 * Math.sin(now * 1.7 - i * 0.4);
        const h = Math.round(4 + (maxH - 4) * bell * Math.max(0.22, norm * 0.88 + 0.16) * wave);
        bar.style.height = `${h}px`;
      });
    };
    paint(mobileVoiceBars, 24);
    paint(sheetVoiceBars, 24);
    paint(desktopVoiceBars, 18);
  }

  function resetVoiceBars() {
    for (const b of mobileVoiceBars) b.style.height = '5px';
    for (const b of sheetVoiceBars) b.style.height = '5px';
    for (const b of desktopVoiceBars) b.style.height = '5px';
  }

  function showVoiceFeedback(msg, tone = '', ms = 3500) {
    showVoiceNote(msg, tone, ms);
    const sysopVisible = window.innerWidth <= 860
      ? appEl.dataset.mobileSysop === '1'
      : appEl.dataset.sysopOpen === '1';
    if (!sysopVisible && msg) {
      showTermToast(msg, tone === 'error' ? 'error' : (tone === 'ok' ? 'ok' : ''), ms || 3500);
    }
  }

  function setVoiceState(state) {
    appEl.dataset.voiceState = state;
    const isRec = state === 'recording';
    btnMic.classList.toggle('recording', isRec);
    btnMobileMic.classList.toggle('recording', isRec);
    if (micLabelEl) micLabelEl.textContent = isRec ? 'Listening' : 'Speak';
    if (!isRec) {
      clearInterval(recTimerHandle);
      recTimerHandle = null;
      resetVoiceBars();
    }
    requestAnimationFrame(fitAndResize);
  }

  function downsample(chunks, total, from, to) {
    const all = new Float32Array(total);
    let off = 0;
    for (const c of chunks) { all.set(c, off); off += c.length; }
    if (from <= to) return all;
    const ratio = from / to;
    const n = Math.floor(total / ratio);
    const out = new Float32Array(n);
    for (let j = 0; j < n; j++) {
      const a = Math.floor(j * ratio);
      const b = Math.min(total, Math.floor((j + 1) * ratio));
      let s = 0;
      for (let k = a; k < b; k++) s += all[k];
      out[j] = b > a ? s / (b - a) : 0;
    }
    return out;
  }

  function encodeWav(samples, rate) {
    const buf = new ArrayBuffer(44 + samples.length * 2);
    const v = new DataView(buf);
    const tag = (o, s) => { for (let i = 0; i < s.length; i++) v.setUint8(o + i, s.charCodeAt(i)); };
    tag(0, 'RIFF'); v.setUint32(4, 36 + samples.length * 2, true); tag(8, 'WAVE');
    tag(12, 'fmt '); v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, 1, true);
    v.setUint32(24, rate, true); v.setUint32(28, rate * 2, true); v.setUint16(32, 2, true); v.setUint16(34, 16, true);
    tag(36, 'data'); v.setUint32(40, samples.length * 2, true);
    for (let i = 0; i < samples.length; i++) {
      const x = Math.max(-1, Math.min(1, samples[i]));
      v.setInt16(44 + i * 2, x < 0 ? x * 0x8000 : x * 0x7fff, true);
    }
    return new Blob([buf], { type: 'audio/wav' });
  }

  function releaseWavHandle(rec) {
    if (!rec) return;
    try { rec.src.disconnect(); rec.proc.disconnect(); } catch (_) {}
    rec.proc.onaudioprocess = null;
    try { rec.stream.getTracks().forEach((t) => t.stop()); } catch (_) {}
    try { rec.ctx.close(); } catch (_) {}
  }

  async function startWavRecording() {
    if (wavRec || appEl.dataset.voiceState === 'sending') return;
    const md = navigator.mediaDevices;
    const AC = window.AudioContext || window.webkitAudioContext;
    if (!md || !md.getUserMedia || !AC) {
      showVoiceFeedback(window.isSecureContext === false ? 'Microphone needs HTTPS or localhost.' : 'Browser cannot record audio.', 'error', 6000);
      return;
    }
    try {
      const stream = await md.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true } });
      const ctx = new AC();
      if (ctx.state === 'suspended') await ctx.resume();
      const src = ctx.createMediaStreamSource(stream);
      const proc = ctx.createScriptProcessor(4096, 1, 1);
      const rec = { stream, ctx, src, proc, chunks: [], samples: 0, lastPaint: 0 };
      proc.onaudioprocess = (e) => {
        const ch = e.inputBuffer.getChannelData(0);
        rec.chunks.push(new Float32Array(ch));
        rec.samples += ch.length;
        const now = performance.now();
        if (now - rec.lastPaint >= 55) {
          rec.lastPaint = now;
          let sumSq = 0;
          for (let i = 0; i < ch.length; i += 4) sumSq += ch[i] * ch[i];
          const rms = Math.sqrt(sumSq / Math.max(1, ch.length / 4));
          updateVoiceBars(Math.min(1, rms * 5.2));
        }
        if (rec.samples / ctx.sampleRate >= 60) finishWavRecording(true);
      };
      src.connect(proc);
      proc.connect(ctx.destination);
      wavRec = rec;
      recStartMs = Date.now();
      updateVoiceTimers('0:00');
      setVoiceState('recording');
      recTimerHandle = setInterval(() => {
        updateVoiceTimers(formatRecTime(Date.now() - recStartMs));
      }, 250);
    } catch (err) {
      setVoiceState('idle');
      showVoiceFeedback(`Microphone error: ${err.name || err.message}`, 'error', 6000);
    }
  }

  async function finishWavRecording(shouldSend = true) {
    const rec = wavRec;
    if (!rec) return;
    wavRec = null;
    const rate = rec.ctx.sampleRate;
    releaseWavHandle(rec);
    if (!shouldSend) {
      setVoiceState('idle');
      showVoiceFeedback('Recording discarded.', '', 1800);
      return;
    }
    if (rec.samples / rate < 0.25) {
      setVoiceState('idle');
      showVoiceFeedback('Too short — tap Speak, talk, then tap Send.', 'warn', 3200);
      return;
    }
    setVoiceState('sending');
    showSysopReplyOnMobile();
    const wav = encodeWav(downsample(rec.chunks, rec.samples, rate, VOICE_RATE), VOICE_RATE);
    try {
      const r = await fetch('/voice/audio', {
        method: 'POST',
        credentials: 'same-origin',
        cache: 'no-store',
        headers: { 'Content-Type': 'audio/wav' },
        body: wav,
      });
      const d = await r.json().catch(() => ({}));
      setVoiceState('idle');
      if (d.ok === true && d.state === 'sent') showVoiceFeedback('Voice goal sent to Sysop.', 'ok', 2800);
      else if (d.state === 'nothing_heard') showVoiceFeedback('Nothing heard.', 'warn', 3500);
      else if (d.state === 'no_listener') showVoiceFeedback('Nobody is listening (is Sysop running?).', 'warn', 6000);
      else showVoiceFeedback(d.message || d.error || 'Voice service failed.', 'error', 6000);
    } catch (e) {
      setVoiceState('idle');
      showVoiceFeedback(e.message || 'Voice request failed.', 'error', 6000);
    }
  }

  function startBrowserSpeech() {
    const SpeechRec = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRec) {
      showVoiceFeedback('Install the voice addon (`swarmbox addon install voice`) for local Whisper.', 'warn', 5500);
      if (window.innerWidth > 860) goalInputEl.focus();
      return;
    }
    if (speechRec) return;
    speechRec = new SpeechRec();
    speechRec.lang = navigator.language || 'en-US';
    speechRec.interimResults = false;
    speechRec._discard = false;
    recStartMs = Date.now();
    updateVoiceTimers('0:00');
    setVoiceState('recording');
    recTimerHandle = setInterval(() => {
      updateVoiceTimers(formatRecTime(Date.now() - recStartMs));
      updateVoiceBars(0.35 + Math.random() * 0.35);
    }, 180);
    speechRec.onresult = (ev) => {
      if (speechRec && speechRec._discard) return;
      const txt = ev.results && ev.results[0] && ev.results[0][0] ? ev.results[0][0].transcript : '';
      if (txt) {
        sendGoal(txt);
        showVoiceFeedback('Voice goal sent to Sysop.', 'ok', 2600);
      }
    };
    speechRec.onend = () => { setVoiceState('idle'); speechRec = null; };
    speechRec.onerror = () => { setVoiceState('idle'); speechRec = null; showVoiceFeedback('Speech recognition unavailable.', 'warn', 4000); };
    speechRec.start();
  }

  function finishBrowserSpeech(shouldSend = true) {
    if (!speechRec) return;
    speechRec._discard = !shouldSend;
    try {
      if (shouldSend) speechRec.stop();
      else speechRec.abort();
    } catch (_) {}
    if (!shouldSend) {
      speechRec = null;
      setVoiceState('idle');
      showVoiceFeedback('Recording discarded.', '', 1800);
    }
  }

  function startVoiceCapture() {
    if (voiceAddonAvailable) startWavRecording();
    else startBrowserSpeech();
  }

  function stopVoiceCapture(shouldSend) {
    if (wavRec) finishWavRecording(shouldSend);
    else if (speechRec) finishBrowserSpeech(shouldSend);
    else setVoiceState('idle');
  }

  btnMic.addEventListener('click', () => startVoiceCapture());
  if (btnMobileMic) btnMobileMic.addEventListener('click', () => startVoiceCapture());
  if (btnSheetMic) btnSheetMic.addEventListener('click', () => startVoiceCapture());
  if (btnMobileRecCancel) btnMobileRecCancel.addEventListener('click', () => stopVoiceCapture(false));
  if (btnMobileRecSend) btnMobileRecSend.addEventListener('click', () => stopVoiceCapture(true));
  if (btnSheetRecCancel) btnSheetRecCancel.addEventListener('click', () => stopVoiceCapture(false));
  if (btnSheetRecSend) btnSheetRecSend.addEventListener('click', () => stopVoiceCapture(true));
  if (btnDesktopRecCancel) btnDesktopRecCancel.addEventListener('click', () => stopVoiceCapture(false));
  if (btnDesktopRecSend) btnDesktopRecSend.addEventListener('click', () => stopVoiceCapture(true));

  // Probe local swarmbox-voice service quietly (no ugly "off" label when absent)
  fetch('/voice/health', { credentials: 'same-origin', cache: 'no-store' })
    .then((r) => {
      if (r.ok) {
        voiceAddonAvailable = true;
        voiceHintEl.textContent = 'tap · whisper';
      } else {
        voiceHintEl.textContent = '';
      }
    })
    .catch(() => { voiceHintEl.textContent = ''; });

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
    if (appEl.dataset.sysopOpen !== before) requestAnimationFrame(fitAndResize);
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
  function setMobileSysop(open) {
    const val = open ? '1' : '0';
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
  const composerEl = document.getElementById('sysop-composer');
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
  syncComposerLayout();
  if (mobileMq.addEventListener) mobileMq.addEventListener('change', () => { syncComposerLayout(); scheduleFit(); });
  goalInputEl.addEventListener('focus', () => syncViewport());
  goalInputEl.addEventListener('blur', () => setTimeout(syncViewport, 60));
  // On mobile a goal sent by text or voice opens the sheet in full; the keyboard drops.
  function showSysopReplyOnMobile() {
    if (!isMobileLayout()) return;
    if (document.activeElement === goalInputEl) goalInputEl.blur();
    setMobileSysop(true);
  }

  // Topbar minimalist keys toggle: pins/unpins Esc·Tab·^C·arrows cleanly without stealing focus.
  if (btnMobileKeys) {
    btnMobileKeys.addEventListener('pointerdown', (e) => e.preventDefault());
    btnMobileKeys.addEventListener('mousedown', (e) => e.preventDefault());
    btnMobileKeys.addEventListener('click', () => {
      if (appEl.dataset.mobileSysop === '1') setMobileSysop(false);
      const currentlyShown = appEl.dataset.mobileKeys === '1';
      if (currentlyShown) {
        mobileKeysPinned = false;
        if (mobileKbOpen) mobileKeysDismissedForKb = true;
      } else {
        mobileKeysPinned = true;
        mobileKeysDismissedForKb = false;
      }
      syncMobileKeys();
      requestAnimationFrame(scheduleFit);
    });
  }

  const btnNewShell = document.getElementById('btn-new-shell');
  if (btnNewShell) btnNewShell.addEventListener('click', () => { spawnTab('shell'); focusTerminalIfDesktop(); });
  if (btnNewAgent) btnNewAgent.addEventListener('click', () => { openNewAgentPopover(); });
  if (sidebarPendingWtEl) sidebarPendingWtEl.addEventListener('click', openPendingWorktreesPopover);
  if (topbarWtBtnEl) topbarWtBtnEl.addEventListener('click', () => { if (activeId) openWorktreePopover(activeId); });
  if (mobileWtBtnEl) mobileWtBtnEl.addEventListener('click', () => { if (activeId) openWorktreePopover(activeId); });
  if (popoverBackdropEl) {
    popoverBackdropEl.addEventListener('click', (e) => {
      if (e.target === popoverBackdropEl) closePopover();
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
  const sheetBackdropEl = document.getElementById('sheet-backdrop');
  const sheetHandleEl = document.getElementById('sheet-handle');
  const sysopPanelEl = document.getElementById('sysop-panel');
  const sysopHeadEl = sysopPanelEl ? sysopPanelEl.querySelector('.sysop-head') : null;
  if (sheetBackdropEl) sheetBackdropEl.addEventListener('click', () => setMobileSysop(false));

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
    openTurnActions.clear();
    await fetch('/api/sysop/new', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' }).catch(() => {});
  });

  btnSysopStop.addEventListener('click', () => {
    fetch('/api/sysop/stop', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });
  });

  document.getElementById('btn-interrupt').addEventListener('click', async () => {
    if (!activeId) return;
    await fetch(`/api/tabs/${encodeURIComponent(activeId)}/interrupt`, { method: 'POST' });
    focusTerminalIfDesktop();
  });

  const btnSendGoal = document.getElementById('btn-send-goal');
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

  const touchKeysEl = document.getElementById('touch-keys');
  if (touchKeysEl) {
    // Prevent tapping Esc/Tab/^C/arrows from blurring the terminal or collapsing the OS keyboard.
    touchKeysEl.addEventListener('pointerdown', (e) => e.preventDefault());
    touchKeysEl.addEventListener('mousedown', (e) => e.preventDefault());
    touchKeysEl.addEventListener('click', async (e) => {
      const btn = e.target.closest('button[data-key]');
      if (!btn || !activeId) return;
      await fetch(`/api/tabs/${encodeURIComponent(activeId)}/keys`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ keys: [btn.dataset.key] }),
      });
    });
  }

  // ---- First-Class Settings Panel (Appearance + All SwarmBox Configs) ----------------------
  const SECTION_META = {
    appearance: { title: 'Appearance', sub: 'Themes, typography & terminal canvas (applies live)' },
    box: { title: 'SwarmBox', sub: 'Container runtime, multiplexer & host integration' },
    sysop: { title: 'Sysop', sub: 'Autonomous operator policy, model & safety guardrails' },
    voice: { title: 'Voice', sub: 'Local Whisper speech-to-text & microphone routing' },
    system: { title: 'Addons & System', sub: 'Installed addons, MCP servers, SSH identity & shortcuts' },
  };

  function el(tag, attrs = null, children = []) {
    const node = document.createElement(tag);
    if (attrs) {
      for (const [k, v] of Object.entries(attrs)) {
        if (v === undefined || v === null) continue;
        if (k === 'class') node.className = v;
        else if (k === 'text') node.textContent = String(v);
        else if (k === 'style' && typeof v === 'object') Object.assign(node.style, v);
        else if (k.startsWith('on') && typeof v === 'function') node.addEventListener(k.slice(2).toLowerCase(), v);
        else node.setAttribute(k, String(v));
      }
    }
    for (const c of Array.isArray(children) ? children : [children]) {
      if (c === null || c === undefined || c === false) continue;
      node.appendChild(typeof c === 'string' ? document.createTextNode(c) : c);
    }
    return node;
  }

  function shellQuote(val) {
    const s = String(val ?? '');
    if (s === '') return '""';
    if (/^[A-Za-z0-9_./:@+-]+$/.test(s)) return s;
    return "'" + s.replace(/'/g, "'\\''") + "'";
  }

  function currentHostField(group, key) {
    if (!boxConfig) return { value: '', default: '', custom: false };
    const src = group === 'box'
      ? boxConfig.box
      : group === 'sysop'
        ? (boxConfig.sysop && boxConfig.sysop.settings)
        : (boxConfig.voice && boxConfig.voice.settings);
    return (src && src[key]) || { value: '', default: '', custom: false };
  }

  function effectiveHostValue(group, key) {
    if (stagedHostConfig.has(key)) return stagedHostConfig.get(key);
    return currentHostField(group, key).value;
  }

  function stageHostSetting(group, key, nextVal) {
    const val = String(nextVal ?? '').trim();
    const live = currentHostField(group, key).value;
    if (val === live) stagedHostConfig.delete(key);
    else stagedHostConfig.set(key, val);
    syncHostBar();
  }

  function buildHostApplyCommand() {
    if (stagedHostConfig.size === 0) return '';
    const parts = [];
    for (const [k, v] of stagedHostConfig.entries()) {
      parts.push(`swarmbox config set ${k} ${shellQuote(v)}`);
    }
    parts.push('swarmbox reset');
    return parts.join(' && \\\n  ');
  }

  function syncHostBar() {
    if (!settingsHostBarEl) return;
    const n = stagedHostConfig.size;
    settingsHostBarEl.classList.toggle('hidden', n === 0);
    if (n === 0) return;
    hostBarCountEl.textContent = n === 1 ? '1 pending change' : `${n} pending changes`;
    hostBarCmdEl.textContent = buildHostApplyCommand();
  }

  async function copyTextWithFeedback(text, btn, idleLabel) {
    if (!text) return;
    try {
      await navigator.clipboard.writeText(text);
    } catch (_) {
      const ta = document.createElement('textarea');
      ta.value = text;
      ta.style.position = 'fixed';
      ta.style.opacity = '0';
      document.body.appendChild(ta);
      ta.select();
      try { document.execCommand('copy'); } catch (_e) {}
      document.body.removeChild(ta);
    }
    if (btn) {
      btn.textContent = '✓ Copied';
      setTimeout(() => { btn.textContent = idleLabel; }, 1600);
    }
  }

  async function loadBoxConfig(force = false) {
    if (boxConfigLoading && !force) return;
    boxConfigLoading = true;
    boxConfigError = '';
    try {
      const r = await fetch('/api/config', { cache: 'no-store' });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      boxConfig = await r.json();
      if (boxConfig && boxConfig.session_prefs) sessionPrefs = boxConfig.session_prefs;
      if (boxConfig && Array.isArray(boxConfig.installed_agents)) installedAgents = boxConfig.installed_agents;
      if (settingsVersionEl && boxConfig.version) {
        settingsVersionEl.textContent = `SwarmBox v${boxConfig.version}`;
      }
    } catch (err) {
      boxConfigError = err.message || 'Could not load box config';
    } finally {
      boxConfigLoading = false;
      if (settingsOpen && settingsSection !== 'appearance') renderSettingsBody();
    }
  }

  function makeGroup(label, rightNode, contentNode) {
    return el('section', { class: 's-group' }, [
      el('div', { class: 's-group-head' }, [
        el('span', { class: 's-group-label', text: label }),
        rightNode || null,
      ]),
      contentNode,
    ]);
  }

  function makeSettingRow({ title, keyBadge, desc, badge, control, stacked = false }) {
    const titleChildren = [el('span', { text: title })];
    if (keyBadge) titleChildren.push(el('span', { class: 's-row-key', text: keyBadge }));
    if (badge) titleChildren.push(el('span', { class: `s-badge ${badge.tone || ''}`.trim(), text: badge.text }));
    return el('div', { class: `s-row${stacked ? ' s-row-col' : ''}` }, [
      el('div', { class: 's-row-info' }, [
        el('div', { class: 's-row-title' }, titleChildren),
        desc ? el('div', { class: 's-row-desc', text: desc }) : null,
      ]),
      control,
    ]);
  }

  function makeSegmented(options, current, onSelect) {
    const wrap = el('div', { class: 's-seg' });
    for (const opt of options) {
      const val = typeof opt === 'object' ? opt.value : opt;
      const lbl = typeof opt === 'object' ? opt.label : String(opt);
      const btn = el('button', {
        type: 'button',
        class: String(val) === String(current) ? 'active' : '',
        text: lbl,
        onClick: () => onSelect(val),
      });
      wrap.appendChild(btn);
    }
    return wrap;
  }

  function makeSwitch(checked, ariaLabel, onToggle) {
    const btn = el('button', {
      type: 'button',
      class: 's-switch',
      role: 'switch',
      'aria-checked': checked ? 'true' : 'false',
      'aria-label': ariaLabel,
      onClick: () => onToggle(!checked),
    });
    return btn;
  }

  function makeHostFieldBadge(group, key) {
    if (stagedHostConfig.has(key)) return { text: 'edited', tone: '' };
    const f = currentHostField(group, key);
    if (f.custom) return { text: 'custom', tone: 'ok' };
    return null;
  }

  function makeHostSelectRow(group, key, { title, desc, options }) {
    const cur = effectiveHostValue(group, key);
    const hasCur = options.some((o) => o.value === cur);
    const list = hasCur ? options : [{ value: cur, label: cur || 'default' }, ...options];
    const sel = el('select', {
      class: 's-select',
      'aria-label': title,
      onChange: (e) => {
        stageHostSetting(group, key, e.target.value);
        renderSettingsBody();
      },
    }, list.map((o) => {
      const opt = el('option', { value: o.value, text: o.label });
      if (o.value === cur) opt.selected = true;
      return opt;
    }));
    return makeSettingRow({
      title,
      keyBadge: key,
      desc,
      badge: makeHostFieldBadge(group, key),
      control: sel,
    });
  }

  function makeHostToggleRow(group, key, { title, desc }) {
    const on = effectiveHostValue(group, key) === '1';
    return makeSettingRow({
      title,
      keyBadge: key,
      desc,
      badge: makeHostFieldBadge(group, key),
      control: makeSwitch(on, title, (next) => {
        stageHostSetting(group, key, next ? '1' : '0');
        renderSettingsBody();
      }),
    });
  }

  function makeHostInputRow(group, key, { title, desc, placeholder = '', type = 'text', wide = false }) {
    const cur = effectiveHostValue(group, key);
    const inp = el('input', {
      class: `s-input${wide ? ' wide' : ''}`,
      type,
      value: cur,
      placeholder,
      'aria-label': title,
      onInput: (e) => {
        stageHostSetting(group, key, e.target.value);
      },
    });
    return makeSettingRow({
      title,
      keyBadge: key,
      desc,
      badge: makeHostFieldBadge(group, key),
      control: inp,
      stacked: wide,
    });
  }

  function renderAppearanceSection() {
    const frag = document.createDocumentFragment();

    // 1. Visual 5-theme mini-terminal cards
    const themeGrid = el('div', { class: 'theme-grid' });
    for (const key of THEME_KEYS) {
      const t = THEMES[key];
      const mini = el('div', {
        class: 'theme-mini',
        style: { background: t.css['--bg'], color: t.css['--text'] },
      }, [
        el('div', { class: 'theme-mini-side', style: { background: t.css['--surface'] } }, [
          el('span', { class: 'theme-mini-bar', style: { background: t.css['--accent'], width: '85%' } }),
          el('span', { class: 'theme-mini-bar', style: { background: t.css['--band'], width: '70%' } }),
          el('span', { class: 'theme-mini-bar', style: { background: t.css['--band'], width: '58%' } }),
        ]),
        el('div', { class: 'theme-mini-main' }, [
          el('div', { class: 'theme-mini-dots' }, [
            el('i', { style: { background: t.xterm.red } }),
            el('i', { style: { background: t.xterm.yellow } }),
            el('i', { style: { background: t.xterm.green } }),
          ]),
          el('div', { class: 'theme-mini-prompt', style: { color: t.css['--accent-bright'] }, text: '❯ swarmbox' }),
        ]),
      ]);
      const card = el('button', {
        type: 'button',
        class: `theme-card${key === currentThemeKey ? ' active' : ''}`,
        'data-theme': key,
        onClick: () => applyTheme(key, true),
      }, [
        mini,
        el('div', { class: 'theme-card-foot' }, [
          el('span', { class: 'theme-card-name', text: t.label || key }),
          el('span', { class: 'theme-card-check', text: '✓' }),
        ]),
      ]);
      themeGrid.appendChild(card);
    }
    frag.appendChild(makeGroup(
      'Theme Palette',
      el('span', { class: 's-badge', text: 'Synced with Cockpit' }),
      themeGrid,
    ));

    // 2. Typography card: Font size slider + stepper + live JetBrains Mono preview + line height
    const sz = computeFontSize();
    const rangeEl = el('input', {
      id: 's-font-range',
      class: 's-range',
      type: 'range',
      min: '-4',
      max: '8',
      step: '0.5',
      value: String(fontOffset),
      'aria-label': 'Terminal font size offset',
      onInput: (e) => setFontOffset(Number(e.target.value)),
    });
    const stepper = el('div', { class: 's-stepper' }, [
      el('button', { type: 'button', class: 's-step-btn', text: '−', title: 'Smaller (Alt+-)', onClick: () => setFontOffset(fontOffset - 0.5) }),
      el('button', { id: 's-font-val', type: 'button', class: 's-step-val', text: formatFontPx(sz), title: 'Reset font size (Alt+0)', onClick: () => setFontOffset(0) }),
      el('button', { type: 'button', class: 's-step-btn', text: '+', title: 'Larger (Alt+=)', onClick: () => setFontOffset(fontOffset + 0.5) }),
    ]);
    const preview = el('div', {
      id: 's-font-preview',
      class: 'font-preview',
      style: { fontSize: `${Math.min(22, Math.max(11, sz))}px`, lineHeight: String(computeLineHeight()) },
    }, [
      el('span', { class: 'fp-band', text: '~/swarmbox' }),
      el('span', { class: 'fp-branch', text: 'main ' }),
      el('span', { class: 'fp-dirty', text: '● ' }),
      el('span', { text: '❯ ' }),
      el('span', { class: 'fp-dim', text: 'JetBrains Mono + Nerd Font glyphs' }),
    ]);

    const fontRow = el('div', { class: 's-row s-row-col' }, [
      el('div', { class: 's-row-info' }, [
        el('div', { class: 's-row-title' }, [
          el('span', { text: 'Terminal Font Size' }),
          el('span', { class: 's-row-key', text: 'JetBrains Mono' }),
        ]),
        el('div', { class: 's-row-desc', text: 'Adjusts live across every open terminal tab (Alt+- / Alt+= / Alt+0).' }),
      ]),
      el('div', { class: 'font-control-row' }, [rangeEl, stepper]),
      preview,
    ]);

    const lhRow = makeSettingRow({
      title: 'Line Height Density',
      desc: 'Controls vertical breathing room between terminal lines.',
      control: makeSegmented(
        [
          { value: 'compact', label: 'Compact' },
          { value: 'studio', label: 'Studio' },
          { value: 'airy', label: 'Airy' },
        ],
        effectiveLineHeightKey(),
        (val) => {
          lineHeightPreset = val;
          try { localStorage.setItem('swarmbox-herdr-lh', val); } catch (_) {}
          applyTerminalPrefs();
          renderSettingsBody();
        },
      ),
    });

    frag.appendChild(makeGroup('Typography', null, el('div', { class: 's-card' }, [fontRow, lhRow])));

    // 3. Terminal Canvas card: Cursor style, cursor blink, scrollback buffer
    const resetBtn = el('button', {
      type: 'button',
      class: 'sbtn-ghost',
      text: 'Reset appearance',
      onClick: () => {
        fontOffset = 0;
        lineHeightPreset = '';
        cursorStyle = 'block';
        cursorBlink = true;
        scrollbackLines = 3000;
        try {
          localStorage.removeItem('swarmbox-herdr-font-offset');
          localStorage.removeItem('swarmbox-herdr-lh');
          localStorage.removeItem('swarmbox-herdr-cursor-style');
          localStorage.removeItem('swarmbox-herdr-cursor-blink');
          localStorage.removeItem('swarmbox-herdr-scrollback');
        } catch (_) {}
        applyTheme('purple-glow', true);
        applyTerminalPrefs();
        renderSettingsBody();
      },
    });

    const canvasCard = el('div', { class: 's-card' }, [
      makeSettingRow({
        title: 'Cursor Style',
        desc: 'Shape of the active terminal cursor.',
        control: makeSegmented(
          [
            { value: 'block', label: 'Block' },
            { value: 'bar', label: 'Bar' },
            { value: 'underline', label: 'Line' },
          ],
          cursorStyle,
          (val) => {
            cursorStyle = val;
            try { localStorage.setItem('swarmbox-herdr-cursor-style', val); } catch (_) {}
            applyTerminalPrefs();
            renderSettingsBody();
          },
        ),
      }),
      makeSettingRow({
        title: 'Cursor Blink',
        desc: 'Pulse the terminal cursor when focused.',
        control: makeSwitch(cursorBlink, 'Cursor blink', (next) => {
          cursorBlink = next;
          try { localStorage.setItem('swarmbox-herdr-cursor-blink', next ? '1' : '0'); } catch (_) {}
          applyTerminalPrefs();
          renderSettingsBody();
        }),
      }),
      makeSettingRow({
        title: 'Scrollback Buffer',
        desc: 'Lines retained in browser scroll history per tab.',
        control: makeSegmented(
          SCROLLBACK_OPTIONS.map((n) => ({ value: n, label: n >= 1000 ? `${n / 1000}k` : String(n) })),
          scrollbackLines,
          (val) => {
            scrollbackLines = Number(val);
            try { localStorage.setItem('swarmbox-herdr-scrollback', String(scrollbackLines)); } catch (_) {}
            applyTerminalPrefs();
            renderSettingsBody();
          },
        ),
      }),
    ]);

    frag.appendChild(makeGroup('Terminal Canvas', resetBtn, canvasCard));
    return frag;
  }

  function renderLoadingOrError() {
    if (boxConfigError) {
      return el('div', { class: 's-note' }, [
        el('span', { class: 'status-dot', 'data-state': 'error' }),
        el('span', { text: `Could not read box config (${boxConfigError}).` }),
        el('button', { type: 'button', class: 'sbtn-ghost', text: 'Retry', onClick: () => loadBoxConfig(true) }),
      ]);
    }
    return el('div', { class: 's-note', text: 'Loading live SwarmBox configuration…' });
  }

  function renderBoxSection() {
    if (!boxConfig) return renderLoadingOrError();
    const frag = document.createDocumentFragment();
    const healthCount = Array.isArray(boxConfig.health) ? boxConfig.health.length : 0;

    const stats = el('div', { class: 's-stat-grid' }, [
      el('div', { class: 's-stat' }, [
        el('span', { class: 's-stat-k', text: 'Version' }),
        el('span', { class: 's-stat-v', text: `v${boxConfig.version || 'dev'}` }),
      ]),
      el('div', { class: 's-stat' }, [
        el('span', { class: 's-stat-k', text: 'Multiplexer' }),
        el('span', { class: 's-stat-v', text: 'herdr' }),
      ]),
      el('div', { class: 's-stat' }, [
        el('span', { class: 's-stat-k', text: 'Health' }),
        el('span', { class: 's-stat-v', text: healthCount === 0 ? '✓ All green' : `${healthCount} notice${healthCount > 1 ? 's' : ''}` }),
      ]),
    ]);
    frag.appendChild(makeGroup('Environment Summary', el('span', { class: 's-badge muted', text: `box: ${currentHostField('box', 'NAME').value}` }), stats));

    if (healthCount > 0) {
      frag.appendChild(el('div', { class: 's-note' }, [
        el('span', { class: 'status-dot', 'data-state': 'blocked' }),
        el('span', { text: boxConfig.health.join(' · ') }),
      ]));
    }

    const coreCard = el('div', { class: 's-card' }, [
      makeHostSelectRow('box', 'AGENT', {
        title: 'Default Agent',
        desc: 'Agent launched automatically when running swarmbox.',
        options: [
          { value: '', label: 'None (interactive shell)' },
          { value: 'claude', label: 'Claude Code (claude)' },
          { value: 'codex', label: 'OpenAI Codex (codex)' },
          { value: 'opencode', label: 'OpenCode (opencode)' },
          { value: 'agy', label: 'Antigravity (agy)' },
        ],
      }),
      makeHostToggleRow('box', 'YOLO', {
        title: 'YOLO Mode',
        desc: 'Run agents with full sandbox autonomy (skip container confirmation prompts).',
      }),
      makeHostToggleRow('box', 'WEB', {
        title: 'Web Terminal Gateway',
        desc: 'Expose the browser UI on the configured local port.',
      }),
      makeHostInputRow('box', 'WEB_PORT', {
        title: 'Web Port',
        desc: 'Host loopback port mapped to the web gateway.',
        placeholder: '7681',
      }),
    ]);
    frag.appendChild(makeGroup('Runtime & Web', null, coreCard));

    const sessPrefs = (boxConfig && boxConfig.session_prefs) || sessionPrefs;
    const saveSessPrefs = async (patch) => {
      const r = await fetch('/api/pins/prefs', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(patch),
      }).catch(() => null);
      if (r && r.ok) {
        const d = await r.json().catch(() => ({}));
        if (d.prefs) {
          sessionPrefs = d.prefs;
          if (boxConfig) boxConfig.session_prefs = d.prefs;
          renderSettingsBody();
        }
      }
    };
    const bootModeSeg = el('div', { class: 's-seg' }, [
      { id: 'autostart', label: 'Auto-start' },
      { id: 'parked', label: 'Parked' },
    ].map((opt) => el('button', {
      type: 'button',
      class: `s-seg-btn${(sessPrefs.boot_mode || 'autostart') === opt.id ? ' active' : ''}`,
      text: opt.label,
      onClick: () => saveSessPrefs({ boot_mode: opt.id }),
    })));
    const sessCard = el('div', { class: 's-card' }, [
      el('div', { class: 's-row' }, [
        el('div', { class: 's-row-info' }, [
          el('div', { class: 's-row-title', text: 'Restore Sessions on Restart' }),
          el('div', { class: 's-row-desc', text: 'Open agent tabs persist automatically. Choose whether they auto-start on boot or wait parked until you click Wake.' }),
        ]),
        bootModeSeg,
      ]),
    ]);
    frag.appendChild(makeGroup('Sessions', el('span', { class: 's-badge', text: 'live' }), sessCard));

    const wtPrefs = (boxConfig && boxConfig.worktree_prefs) || worktreePrefs;
    const saveWtPrefs = async (patch) => {
      const r = await fetch('/api/worktrees/prefs', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(patch),
      }).catch(() => null);
      if (r && r.ok) {
        const d = await r.json().catch(() => ({}));
        if (d.prefs) {
          worktreePrefs = d.prefs;
          if (boxConfig) boxConfig.worktree_prefs = d.prefs;
          renderSettingsBody();
        }
      }
    };
    const wtModeSeg = el('div', { class: 's-seg' }, ['ask', 'auto', 'off'].map((m) => el('button', {
      type: 'button',
      class: `s-seg-btn${(wtPrefs.mode || 'ask') === m ? ' active' : ''}`,
      text: m,
      onClick: () => saveWtPrefs({ mode: m }),
    })));
    const wtEnvSw = el('button', {
      type: 'button',
      class: `s-switch${wtPrefs.copy_env !== false ? ' on' : ''}`,
      role: 'switch',
      'aria-checked': wtPrefs.copy_env !== false ? 'true' : 'false',
      onClick: () => saveWtPrefs({ copy_env: wtPrefs.copy_env === false }),
    }, [el('i')]);
    const wtCard = el('div', { class: 's-card' }, [
      el('div', { class: 's-row' }, [
        el('div', { class: 's-row-info' }, [
          el('div', { class: 's-row-title', text: 'Worktree on Repo Collision' }),
          el('div', { class: 's-row-desc', text: 'Ask (2-button popover), Auto (isolate immediately), or Off (always share folder). Applies live.' }),
        ]),
        wtModeSeg,
      ]),
      el('div', { class: 's-row' }, [
        el('div', { class: 's-row-info' }, [
          el('div', { class: 's-row-title', text: 'Copy Root .env Files' }),
          el('div', { class: 's-row-desc', text: 'Automatically copy root .env / .env.* (mode 0600, <= 64 KiB) into new worktrees.' }),
        ]),
        wtEnvSw,
      ]),
    ]);
    frag.appendChild(makeGroup('Git Worktrees', el('span', { class: 's-badge', text: 'live' }), wtCard));

    const envCard = el('div', { class: 's-card' }, [
      makeHostInputRow('box', 'TZ', {
        title: 'Timezone',
        desc: 'IANA timezone name or "local" to mirror host clock.',
        placeholder: 'local',
      }),
      makeHostInputRow('box', 'HOSTNAME', {
        title: 'Container Hostname',
        desc: 'Hostname reported inside the sandbox.',
        placeholder: 'swarmbox',
      }),
      makeHostInputRow('box', 'WITH', {
        title: 'Provisioned Addons',
        desc: 'Comma-separated addon list installed automatically on startup.',
        placeholder: 'sysop,voice,agy',
      }),
      makeHostInputRow('box', 'BROWSER_URL', {
        title: 'Host Browser CDP URL',
        desc: 'Optional remote debugging URL for browser automation.',
        placeholder: 'http://host.containers.internal:9222',
        wide: true,
      }),
    ]);
    frag.appendChild(makeGroup('Host Integration', null, envCard));

    return frag;
  }

  function renderSysopSection() {
    if (!boxConfig) return renderLoadingOrError();
    const frag = document.createDocumentFragment();
    const up = Boolean(boxConfig.sysop && boxConfig.sysop.up);
    const st = (boxConfig.sysop && boxConfig.sysop.state) || 'off';

    const statusBanner = el('div', { class: 's-note' }, [
      el('span', { class: 'status-dot', 'data-state': up ? (st === 'idle' ? 'done' : st) : 'off' }),
      el('span', {
        text: up
          ? `Sysop daemon is live (state: ${st}). Goal routing & safety approvals active.`
          : 'Sysop daemon is currently offline. Install the sysop addon in Addons & System to enable it.',
      }),
    ]);
    frag.appendChild(statusBanner);

    // Visual 4-card Autonomy selector (full-auto is the default)
    const curAuto = effectiveHostValue('sysop', 'sysop.autonomy') || 'full-auto';
    const policies = [
      { value: 'full-auto', title: 'full-auto', desc: 'Everything you ask runs right away, nothing waits for Allow (default).' },
      { value: 'auto', title: 'auto', desc: 'Safe commands run right away; risky ones wait for Allow.' },
      { value: 'confirm-risky', title: 'confirm-risky', desc: 'Medium & high risk actions pause with countdown or Allow.' },
      { value: 'confirm-all', title: 'confirm-all', desc: 'Every shell command waits for your explicit Allow click.' },
    ];
    const policyGrid = el('div', { class: 'policy-grid' }, policies.map((p) => el('button', {
      type: 'button',
      class: `policy-card${curAuto === p.value ? ' active' : ''}`,
      onClick: () => {
        stageHostSetting('sysop', 'sysop.autonomy', p.value);
        renderSettingsBody();
      },
    }, [
      el('span', { class: 'policy-card-title', text: p.title }),
      el('span', { class: 'policy-card-desc', text: p.desc }),
    ])));
    frag.appendChild(makeGroup(
      'Autonomy Policy',
      stagedHostConfig.has('sysop.autonomy') ? el('span', { class: 's-badge', text: 'edited' }) : null,
      policyGrid,
    ));

    // Brain, model & guardrails
    const guardCard = el('div', { class: 's-card' }, [
      makeHostToggleRow('sysop', 'sysop.autoname', {
        title: 'Automatic Tab Naming',
        desc: 'React to tab.events to give unnamed agent tabs concise 2–4 word titles (never overwrites manual renames).',
      }),
      makeHostInputRow('sysop', 'sysop.brain', {
        title: 'Operator Brain',
        desc: 'CLI brain used to plan actions (e.g. claude or custom command).',
        placeholder: 'claude',
      }),
      makeHostSelectRow('sysop', 'sysop.model', {
        title: 'Operator Model',
        desc: 'Model alias forwarded to the brain.',
        options: [
          { value: 'haiku', label: 'haiku (fast)' },
          { value: 'sonnet', label: 'sonnet (balanced)' },
          { value: 'opus', label: 'opus (deep)' },
        ],
      }),
      makeHostInputRow('sysop', 'sysop.countdown', {
        title: 'Veto Countdown (sec)',
        desc: 'Seconds to cancel before a countdown action fires.',
        type: 'number',
        placeholder: '4',
      }),
      makeHostInputRow('sysop', 'sysop.max_steps', {
        title: 'Max Steps per Goal',
        desc: 'Upper bound on operator turns for a single goal.',
        type: 'number',
        placeholder: '20',
      }),
      makeHostInputRow('sysop', 'sysop.max_seconds', {
        title: 'Goal Time Budget (sec)',
        desc: 'Maximum runtime per goal before automatic stop.',
        type: 'number',
        placeholder: '300',
      }),
      makeHostInputRow('sysop', 'sysop.topic', {
        title: 'Bus Topic',
        desc: 'Event bus topic Sysop subscribes to for goals.',
        placeholder: 'goal',
      }),
      makeHostInputRow('sysop', 'sysop.group', {
        title: 'Consumer Group',
        desc: 'Bus consumer group name.',
        placeholder: 'sysop',
      }),
    ]);
    frag.appendChild(makeGroup('Brain & Guardrails', null, guardCard));
    return frag;
  }

  function renderVoiceSection() {
    if (!boxConfig) return renderLoadingOrError();
    const frag = document.createDocumentFragment();

    frag.appendChild(el('div', { class: 's-note' }, [
      el('span', { class: 'status-dot', 'data-state': voiceAddonAvailable ? 'done' : 'off' }),
      el('span', {
        text: voiceAddonAvailable
          ? 'Local Whisper service is online — tap Speak to record and send straight to Sysop.'
          : 'Local Whisper service is not active. Install the voice addon (Addons & System) for offline Whisper transcription.',
      }),
    ]));

    const card = el('div', { class: 's-card' }, [
      makeHostToggleRow('voice', 'voice.web', {
        title: 'Web Voice Front',
        desc: 'Proxy the web UI through swarmbox-voice for local WAV upload.',
      }),
      makeHostSelectRow('voice', 'voice.stt.model', {
        title: 'Whisper Model',
        desc: 'Larger models improve accuracy at the cost of RAM & latency.',
        options: [
          { value: 'tiny', label: 'tiny (fastest)' },
          { value: 'base', label: 'base' },
          { value: 'small', label: 'small (default)' },
          { value: 'medium', label: 'medium' },
          { value: 'large-v3', label: 'large-v3 (highest accuracy)' },
        ],
      }),
      makeHostInputRow('voice', 'voice.language', {
        title: 'Spoken Language',
        desc: 'ISO-639-1 code (e.g. en, pt, es) or "auto" for automatic detection.',
        placeholder: 'auto',
      }),
      makeHostInputRow('voice', 'voice.topic', {
        title: 'Publish Topic',
        desc: 'Event bus topic where transcribed voice goals are sent.',
        placeholder: 'goal',
      }),
      makeHostInputRow('voice', 'voice.stt.vocabulary', {
        title: 'Custom Vocabulary Hint',
        desc: 'Optional domain terms (repo names, commands, acronyms) to bias Whisper.',
        placeholder: 'SwarmBox, herdr, Sysop, Podman',
        wide: true,
      }),
    ]);
    frag.appendChild(makeGroup('Whisper Speech-to-Text', null, card));
    return frag;
  }

  async function installAddonLive(name) {
    if (installingAddons.has(name)) return;
    installingAddons.add(name);
    addonMessages.set(name, { tone: '', text: 'Installing…' });
    renderSettingsBody();
    try {
      const r = await fetch(`/api/addons/${encodeURIComponent(name)}/install`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: '{}',
      });
      const d = await r.json().catch(() => ({}));
      if (r.ok && d.ok) {
        if (d.config) boxConfig = d.config;
        addonMessages.set(name, { tone: 'ok', text: 'Installed!' });
      } else {
        addonMessages.set(name, { tone: 'warn', text: d.stderr || d.error || 'Install failed' });
      }
    } catch (err) {
      addonMessages.set(name, { tone: 'warn', text: err.message || 'Network error' });
    } finally {
      installingAddons.delete(name);
      renderSettingsBody();
    }
  }

  function renderSystemSection() {
    if (!boxConfig) return renderLoadingOrError();
    const frag = document.createDocumentFragment();

    // 1. Addons list with live 1-click install
    const addons = Array.isArray(boxConfig.addons) ? boxConfig.addons : [];
    const addonList = el('div', { class: 's-card addon-list' });
    if (addons.length === 0) {
      addonList.appendChild(el('div', { class: 'addon-row' }, [
        el('div', { class: 'addon-desc', text: 'No addon manifests found in this image.' }),
      ]));
    } else {
      for (const a of addons) {
        const busy = installingAddons.has(a.name);
        const msg = addonMessages.get(a.name);
        const actions = [];
        if (msg && msg.text && !busy) {
          actions.push(el('span', { class: `s-badge ${msg.tone || 'muted'}`.trim(), text: msg.text.slice(0, 32) }));
        }
        if (a.installed) {
          actions.push(el('span', { class: 's-badge ok', text: a.installedVersion ? `installed · ${a.installedVersion}` : 'installed' }));
        } else {
          actions.push(el('button', {
            type: 'button',
            class: 'sbtn-primary',
            text: busy ? 'Installing…' : 'Install',
            disabled: busy ? 'disabled' : null,
            onClick: () => installAddonLive(a.name),
          }));
        }
        addonList.appendChild(el('div', { class: 'addon-row' }, [
          el('div', { class: 's-row-info' }, [
            el('div', { class: 's-row-title' }, [
              el('span', { class: 'addon-name', text: a.name }),
              a.level === 'user' ? el('span', { class: 's-badge muted', text: 'user' }) : null,
            ]),
            a.description ? el('div', { class: 'addon-desc', text: a.description }) : null,
          ]),
          el('div', { class: 'addon-actions' }, actions),
        ]));
      }
    }
    frag.appendChild(makeGroup('Addons & Agents', el('span', { class: 's-badge muted', text: `${addons.filter((a) => a.installed).length}/${addons.length} active` }), addonList));

    // 2. MCP Servers
    const mcps = Array.isArray(boxConfig.mcp) ? boxConfig.mcp : [];
    const mcpCard = el('div', { class: 's-card' }, [
      el('div', { class: 's-row' }, [
        el('div', { class: 's-row-info' }, [
          el('div', { class: 's-row-title', text: 'Configured MCP Servers' }),
          el('div', { class: 's-row-desc', text: mcps.length ? mcps.join(', ') : 'None configured yet (add under ~/.config/swarmbox/mcp/<name>/config.json).' }),
        ]),
        el('span', { class: `s-badge ${mcps.length ? 'ok' : 'muted'}`, text: `${mcps.length} active` }),
      ]),
    ]);
    frag.appendChild(makeGroup('MCP Integrations', null, mcpCard));

    // 3. Git SSH public key
    const pubkey = boxConfig.pubkey || '';
    const copyKeyBtn = pubkey
      ? el('button', {
          type: 'button',
          class: 'sbtn-ghost',
          text: 'Copy public key',
          onClick: (e) => copyTextWithFeedback(pubkey, e.currentTarget, 'Copy public key'),
        })
      : null;
    const keyCard = el('div', { class: 's-card' }, [
      el('div', { class: 's-row s-row-col' }, [
        el('div', { class: 's-row-desc', text: pubkey ? 'Add this SSH public key to GitHub / GitLab for keyless push from the box.' : 'No SSH keypair generated yet inside ~/.ssh.' }),
        pubkey ? el('pre', { class: 'code-box', text: pubkey }) : null,
      ]),
    ]);
    frag.appendChild(makeGroup('Git SSH Identity', copyKeyBtn, keyCard));

    // 4. Keyboard shortcuts cheat sheet
    const shortcuts = [
      ['Switch terminal tab', 'Alt+1..9'],
      ['Rename active tab', 'Alt+R'],
      ['Open new terminal tab', 'Alt+N'],
      ['Open / close Settings', 'Alt+,'],
      ['Toggle left sidebar', 'Alt+B'],
      ['Toggle Sysop panel', 'Alt+S'],
      ['Focus Sysop goal box', 'Alt+G'],
      ['Cycle color theme', 'Alt+T'],
      ['Font size − / + / reset', 'Alt+- / = / 0'],
    ];
    const kbdCard = el('div', { class: 's-card' }, [
      el('div', { class: 'kbd-grid' }, shortcuts.map(([lbl, keys]) => el('div', { class: 'kbd-row' }, [
        el('span', { text: lbl }),
        el('kbd', { text: keys }),
      ]))),
    ]);
    frag.appendChild(makeGroup('Keyboard Shortcuts', null, kbdCard));

    return frag;
  }

  function renderSettingsBody() {
    if (!settingsBodyEl) return;
    const meta = SECTION_META[settingsSection] || SECTION_META.appearance;
    if (settingsTitleEl) settingsTitleEl.textContent = meta.title;
    if (settingsSubEl) settingsSubEl.textContent = meta.sub;
    if (settingsNavEl) {
      settingsNavEl.querySelectorAll('.snav-item').forEach((btn) => {
        btn.classList.toggle('active', btn.dataset.section === settingsSection);
      });
    }
    settingsBodyEl.innerHTML = '';
    if (settingsSection === 'appearance') settingsBodyEl.appendChild(renderAppearanceSection());
    else if (settingsSection === 'box') settingsBodyEl.appendChild(renderBoxSection());
    else if (settingsSection === 'sysop') settingsBodyEl.appendChild(renderSysopSection());
    else if (settingsSection === 'voice') settingsBodyEl.appendChild(renderVoiceSection());
    else settingsBodyEl.appendChild(renderSystemSection());
    syncHostBar();
  }

  function openSettings(section = null) {
    if (section && SECTION_META[section]) settingsSection = section;
    if (appEl.dataset.mobileSysop === '1') setMobileSysop(false);
    settingsOpen = true;
    settingsOverlayEl.classList.add('open');
    settingsOverlayEl.setAttribute('aria-hidden', 'false');
    renderSettingsBody();
    loadBoxConfig(true);
  }

  function closeSettings() {
    if (!settingsOpen) return;
    settingsOpen = false;
    settingsOverlayEl.classList.remove('open');
    settingsOverlayEl.setAttribute('aria-hidden', 'true');
    focusTerminalIfDesktop();
  }

  function toggleSettings() {
    if (settingsOpen) closeSettings();
    else openSettings();
  }

  const btnSidebarSettings = document.getElementById('btn-sidebar-settings');
  const btnTopbarSettings = document.getElementById('btn-topbar-settings');
  const btnSettingsClose = document.getElementById('btn-settings-close');
  const settingsHandleEl = document.getElementById('settings-handle');
  if (btnSidebarSettings) btnSidebarSettings.addEventListener('click', () => openSettings());
  if (btnTopbarSettings) btnTopbarSettings.addEventListener('click', () => openSettings());
  if (btnSettingsClose) btnSettingsClose.addEventListener('click', closeSettings);
  if (settingsHandleEl) settingsHandleEl.addEventListener('click', closeSettings);
  if (settingsOverlayEl) {
    settingsOverlayEl.addEventListener('click', (e) => {
      if (e.target === settingsOverlayEl) closeSettings();
    });
  }
  if (settingsNavEl) {
    settingsNavEl.addEventListener('click', (e) => {
      const btn = e.target.closest('.snav-item[data-section]');
      if (!btn) return;
      settingsSection = btn.dataset.section;
      settingsBodyEl.scrollTop = 0;
      renderSettingsBody();
      if (settingsSection !== 'appearance' && !boxConfig) loadBoxConfig(true);
    });
  }
  if (btnHostCopy) {
    btnHostCopy.addEventListener('click', () => {
      copyTextWithFeedback(buildHostApplyCommand(), btnHostCopy, 'Copy command');
    });
  }
  if (btnHostDiscard) {
    btnHostDiscard.addEventListener('click', () => {
      stagedHostConfig.clear();
      syncHostBar();
      renderSettingsBody();
    });
  }

  connectEvents();
})();
