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

  // Colorize the BBS ANSI-art SWARMBOX boot splash with alternating per-letter shades + bevel shadow
  (function colorizeBootBbs() {
    const pre = document.getElementById('boot-bbs');
    if (!pre) return;
    // Column end-offsets for the 8 ANSI Shadow letters: S, W, A, R, M, B, O, X
    const stops = [8, 18, 26, 34, 45, 53, 62, 70];
    const lines = (pre.textContent || '').split('\n');
    const frag = document.createDocumentFragment();
    lines.forEach((line, r) => {
      if (r > 0) frag.appendChild(document.createTextNode('\n'));
      let curCls = '';
      let run = '';
      const flush = () => {
        if (!run) return;
        if (!curCls) frag.appendChild(document.createTextNode(run));
        else {
          const sp = document.createElement('span');
          sp.className = curCls;
          sp.textContent = run;
          frag.appendChild(sp);
        }
        run = '';
      };
      for (let c = 0; c < line.length; c++) {
        const ch = line[c];
        let cls = '';
        if (ch === '█') {
          let letterIdx = stops.findIndex((s) => c < s);
          if (letterIdx < 0) letterIdx = stops.length - 1;
          cls = `c${letterIdx % 3}`;
        } else if (ch !== ' ') {
          cls = 'cs';
        }
        if (cls !== curCls) { flush(); curCls = cls; }
        run += ch;
      }
      flush();
    });
    pre.textContent = '';
    pre.appendChild(frag);
  })();

  let bootDismissed = false;
  function dismissBoot() {
    if (bootDismissed) return;
    bootDismissed = true;
    document.documentElement.classList.add('swarmbox-ready');
  }
  setTimeout(dismissBoot, 3000);

  const appEl = document.getElementById('app');
  const sidebarTabsEl = document.getElementById('sidebar-tabs');
  const sidebarAgentsEl = document.getElementById('sidebar-agents');
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
  const mobileSysopDotEl = document.getElementById('mobile-sysop-dot');
  const mobileSysopTextEl = document.getElementById('mobile-sysop-text');
  const mobileKbBtn = document.getElementById('btn-mobile-kb');
  const btnToggleSysop = document.getElementById('btn-toggle-sysop');
  const sysopFeedEl = document.getElementById('sysop-feed');
  const btnSysopStop = document.getElementById('btn-sysop-stop');
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
  const btnTts = document.getElementById('btn-tts');
  const btnMic = document.getElementById('btn-mic');
  const btnMobileMic = document.getElementById('btn-mobile-mic');
  const termWrapEl = document.getElementById('term-wrap');
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
  const MAX_TAB_SESSIONS = 8;

  let terminals = [];
  let activeId = null;
  let currentThemeKey = 'purple-glow';
  const tabSessions = new Map();
  let eventsWs = null;
  let eventsConnected = false;
  let ptyConnected = false;
  let ttsEnabled = false;
  let lastSpokenKey = '';
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

  // Eliminate faint horizontal hairline seams on block-drawing rows (banner.sh half-blocks)
  const BLOCK_RE = /[\u2580-\u259f]/;
  function markBlockRows(rootEl) {
    const scope = rootEl || terminalHostEl;
    if (!scope) return;
    const rows = scope.querySelectorAll('.xterm-rows > div');
    for (const row of rows) {
      const hasBlk = BLOCK_RE.test(row.textContent || '');
      if (hasBlk !== row.classList.contains('sb-blk')) {
        row.classList.toggle('sb-blk', hasBlk);
      }
    }
  }
  function updateBlockScale() {
    const scale = window.innerWidth <= 860 ? 1.18 : 1.28;
    document.documentElement.style.setProperty('--sb-blk-s', String(scale));
  }
  updateBlockScale();

  // Show sleek floating "Jump to live" pill whenever user scrolls up into history
  function syncJumpLive() {
    if (!btnJumpLive) return;
    const sess = activeSession();
    if (!sess || sess.hydrating) {
      btnJumpLive.classList.remove('visible');
      return;
    }
    const buf = sess.term.buffer && sess.term.buffer.active;
    const vp = sess.paneEl.querySelector('.xterm-viewport');
    const bufUp = Boolean(buf && buf.baseY - buf.viewportY > 2);
    const domUp = Boolean(vp && vp.scrollHeight > vp.clientHeight + 48 && (vp.scrollHeight - vp.scrollTop - vp.clientHeight) > 36);
    btnJumpLive.classList.toggle('visible', bufUp || domUp);
  }
  if (btnJumpLive) {
    btnJumpLive.addEventListener('click', () => {
      const sess = activeSession();
      if (!sess) return;
      stopTouchCoast();
      sess.term.scrollToBottom();
      const vp = sess.paneEl.querySelector('.xterm-viewport');
      if (vp) vp.scrollTop = vp.scrollHeight;
      syncJumpLive();
      focusTerminalIfDesktop();
    });
  }

  // Native-feel mobile touch drag + iOS-calibrated momentum inertia scroll
  // (tracks finger directly 1.15:1 while touching so text stays anchored to your thumb, then
  // glides smoothly with UIScrollView-like exponential inertia on flick, stops instantly on touch-catch).
  const TOUCH_DRAG_PX = 6;
  const TOUCH_DRAG_GAIN = 1.15;
  const TOUCH_COAST_GAIN = 1.2;
  const TOUCH_FLICK_MIN = 0.12;   // px/ms
  const TOUCH_FRICTION = 0.955;   // per 16.67ms frame (silky iOS UIScrollView glide)
  const TOUCH_STOP_VEL = 0.02;    // px/ms

  let touchId = null;
  let touchStartY = 0;
  let touchLastY = 0;
  let touchLastX = 0;
  let touchLastT = 0;
  let touchMoved = false;
  let touchVel = 0;
  let touchRaf = 0;
  let touchAltAccum = 0;

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

  function applyTouchScrollPx(deltaPx) {
    const sess = activeSession();
    if (!sess || !deltaPx) return false;
    const vp = sess.paneEl.querySelector('.xterm-viewport');
    const buf = sess.term.buffer && sess.term.buffer.active;
    const maxScroll = vp ? Math.max(0, vp.scrollHeight - vp.clientHeight) : 0;

    if (vp && maxScroll > 2 && (!buf || buf.type === 'normal')) {
      const prev = vp.scrollTop;
      const next = Math.max(0, Math.min(maxScroll, prev + deltaPx));
      vp.scrollTop = next;
      syncJumpLive();
      return Math.abs(next - prev) > 0.25;
    }

    // Alternate screen (vim, less, htop, fullscreen TUI): emit smooth wheel/line steps
    const rh = sessionRowHeight(sess);
    touchAltAccum += deltaPx / rh;
    const lines = Math.trunc(touchAltAccum);
    if (lines !== 0) {
      touchAltAccum -= lines;
      const screenEl = sess.paneEl.querySelector('.xterm-screen');
      if (screenEl && typeof WheelEvent === 'function') {
        screenEl.dispatchEvent(new WheelEvent('wheel', {
          deltaY: lines * rh,
          deltaMode: 0,
          clientX: touchLastX,
          clientY: touchLastY,
          bubbles: true,
          cancelable: true,
        }));
      } else {
        sess.term.scrollLines(lines);
      }
    }
    return true;
  }

  function stopTouchCoast() {
    if (touchRaf) {
      cancelAnimationFrame(touchRaf);
      touchRaf = 0;
    }
    touchVel = 0;
    touchAltAccum = 0;
  }

  function startTouchCoast() {
    if (touchRaf) return;
    let prevT = nowMs();
    const step = () => {
      touchRaf = 0;
      if (touchId !== null) return;
      const t = nowMs();
      const dt = Math.min(48, Math.max(4, t - prevT));
      prevT = t;
      const deltaPx = touchVel * dt * TOUCH_COAST_GAIN;
      const progressed = applyTouchScrollPx(deltaPx);
      touchVel *= Math.pow(TOUCH_FRICTION, dt / 16.67);
      if (progressed && Math.abs(touchVel) >= TOUCH_STOP_VEL) {
        touchRaf = requestAnimationFrame(step);
      } else {
        touchVel = 0;
        touchAltAccum = 0;
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

  termWrapEl.addEventListener('touchstart', (e) => {
    stopTouchCoast();
    if (e.touches.length === 1) {
      const t = e.touches[0];
      touchId = t.identifier;
      touchStartY = t.clientY;
      touchLastY = t.clientY;
      touchLastX = t.clientX;
      touchLastT = nowMs();
      touchMoved = false;
      touchVel = 0;
      touchAltAccum = 0;
    } else {
      touchId = null;
      touchMoved = false;
    }
  }, { passive: true });

  termWrapEl.addEventListener('touchmove', (e) => {
    if (touchId === null || e.touches.length !== 1) {
      touchId = null;
      return;
    }
    const t = findTouchById(e.touches, touchId);
    if (!t) return;
    if (!touchMoved && Math.abs(t.clientY - touchStartY) < TOUCH_DRAG_PX) return;
    touchMoved = true;
    const tt = nowMs();
    const dt = Math.max(1, tt - touchLastT);
    const dy = touchLastY - t.clientY;
    const instV = dy / dt;
    touchVel = touchVel === 0 ? instV : 0.55 * touchVel + 0.45 * instV;
    applyTouchScrollPx(dy * TOUCH_DRAG_GAIN);
    touchLastY = t.clientY;
    touchLastX = t.clientX;
    touchLastT = tt;
    if (e.cancelable) e.preventDefault();
  }, { passive: false });

  termWrapEl.addEventListener('touchcancel', () => {
    touchId = null;
    touchMoved = false;
    stopTouchCoast();
  }, { passive: true });

  termWrapEl.addEventListener('touchend', (e) => {
    if (touchMoved && e.cancelable) e.preventDefault();
    const flick = touchMoved && Math.abs(touchVel) >= TOUCH_FLICK_MIN && (nowMs() - touchLastT) < 90;
    touchId = null;
    touchMoved = false;
    if (flick) startTouchCoast();
    else touchVel = 0;
  }, { passive: false });

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

  function fitSession(sess, sendResize = true) {
    if (!sess) return;
    try {
      const nextFont = computeFontSize();
      const nextLH = computeLineHeight();
      if (sess.term.options.fontSize !== nextFont) sess.term.options.fontSize = nextFont;
      if (sess.term.options.lineHeight !== nextLH) sess.term.options.lineHeight = nextLH;
      updateBlockScale();
      sess.fitAddon.fit();
      markBlockRows(sess.paneEl);
      sess.needsFit = false;
      const changed = sess.term.cols !== sess.lastCols || sess.term.rows !== sess.lastRows;
      if (sendResize && changed && sess.ws && sess.ws.readyState === 1) {
        sess.lastCols = sess.term.cols;
        sess.lastRows = sess.term.rows;
        sess.ws.send(JSON.stringify({ type: 'resize', cols: sess.term.cols, rows: sess.term.rows }));
      }
    } catch (_) {}
  }

  function fitAndResize() {
    syncAppearanceControls();
    const active = activeSession();
    for (const sess of tabSessions.values()) {
      if (sess === active) fitSession(sess, true);
      else sess.needsFit = true;
    }
  }

  // Re-measure terminal cell geometry as soon as self-hosted JetBrains Mono finishes loading
  if (document.fonts && document.fonts.ready) {
    document.fonts.ready.then(() => {
      requestAnimationFrame(() => fitAndResize());
    }).catch(() => {});
  }

  const ro = new ResizeObserver(() => requestAnimationFrame(fitAndResize));
  ro.observe(termWrapEl);
  window.addEventListener('resize', () => requestAnimationFrame(fitAndResize));

  if (window.visualViewport) {
    const syncViewport = () => {
      appEl.style.height = `${Math.round(window.visualViewport.height)}px`;
      requestAnimationFrame(fitAndResize);
    };
    window.visualViewport.addEventListener('resize', syncViewport);
  }

  function focusTerminalIfDesktop() {
    if (settingsOpen) return;
    const sess = activeSession();
    if (sess && window.innerWidth > 860 && document.activeElement !== goalInputEl) {
      sess.term.focus();
    }
  }

  function sendPtyInput(data, targetSession = null) {
    const sess = targetSession || activeSession();
    if (!data || !sess) return;
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
    const rawName = String(t.name || '').trim();
    const isGenericShell = !rawName || /^shell(?:-\d+)?$/i.test(rawName);
    const badge = tabAgentBadge(t);
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
    const shortCwd = cwd.startsWith('/home/agent') ? '~' + cwd.slice('/home/agent'.length) : cwd;

    if (st && st.state === 'blocked') return `blocked · ${msg || st.kind || 'needs input'}`;
    if (st && st.state === 'working') {
      const pct = typeof st.progress === 'number' ? `${st.progress}% ` : '';
      return `${pct}${msg || shortCwd || 'working…'}`;
    }
    if (st && st.state === 'done') return msg ? `✓ ${msg}` : '✓ done';
    if (st && st.state === 'error') return `✕ ${msg || 'error'}`;
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
    if (sess.ws) {
      sess.ws.onclose = null;
      sess.ws.onerror = null;
      try { sess.ws.close(); } catch (_) {}
      sess.ws = null;
    }
    if (sess.blkObserver) {
      try { sess.blkObserver.disconnect(); } catch (_) {}
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
      fontFamily: "'JetBrains Mono', 'JetBrainsMono Nerd Font', 'PureNerdFont', ui-monospace, SFMono-Regular, Menlo, Consolas, monospace",
      fontSize: computeFontSize(),
      lineHeight: computeLineHeight(),
      fontWeight: '400',
      fontWeightBold: '600',
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
    term.open(paneEl);

    const sess = {
      address,
      paneEl,
      term,
      fitAddon,
      blkObserver: null,
      ws: null,
      connected: false,
      hydrating: true,
      hydrationChunks: [],
      fallbackTimer: null,
      reconnectTimer: null,
      reconnectDelay: 400,
      pendingInput: [],
      lastCols: 0,
      lastRows: 0,
      needsFit: false,
      lastUsed: Date.now(),
    };

    // OSC 52 clipboard write support (read "?" refused for security, matching ttyd-clipboard.js)
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
    term.onScroll(onScrollMaybe);
    term.onRender(onScrollMaybe);
    const vp = paneEl.querySelector('.xterm-viewport');
    if (vp) vp.addEventListener('scroll', onScrollMaybe, { passive: true });

    const rowsRoot = paneEl.querySelector('.xterm-rows');
    if (rowsRoot && window.MutationObserver) {
      let blkRaf = 0;
      const scheduleBlk = () => {
        if (blkRaf) return;
        blkRaf = requestAnimationFrame(() => { blkRaf = 0; markBlockRows(paneEl); });
      };
      const obs = new MutationObserver(scheduleBlk);
      obs.observe(rowsRoot, { childList: true, subtree: true, characterData: true });
      sess.blkObserver = obs;
    }

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
    if (activeId === sess.address) termWrapEl.classList.add('term-loading');

    if (opts.reset) {
      sess.term.reset();
    }
    fitSession(sess, false);
    const initCols = sess.term.cols || 100;
    const initRows = sess.term.rows || 30;
    sess.lastCols = initCols;
    sess.lastRows = initRows;

    const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${proto}//${location.host}/ws/pty/${encodeURIComponent(sess.address)}?cols=${initCols}&rows=${initRows}`;
    const ws = new WebSocket(wsUrl);
    ws.binaryType = 'arraybuffer';
    sess.ws = ws;

    const finishHydration = () => {
      if (!sess.hydrating) return;
      sess.hydrating = false;
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
        markBlockRows(sess.paneEl);
        // Two rAFs guarantee xterm.js Viewport._sync() finishes painting at the bottom BEFORE reveal
        requestAnimationFrame(() => {
          if (sess.ws !== ws) return;
          try { sess.term.scrollToBottom(); } catch (_) {}
          if (vp) vp.scrollTop = vp.scrollHeight;
          requestAnimationFrame(() => {
            if (sess.ws !== ws) return;
            sess.paneEl.classList.remove('hydrating');
            if (activeId === sess.address) {
              termWrapEl.classList.remove('term-loading');
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
    sess.fallbackTimer = setTimeout(finishHydration, 1500);

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
        sess.term.write(bytes, () => dismissBoot());
      } else if (typeof ev.data === 'string') {
        try {
          const msg = JSON.parse(ev.data);
          if (msg.type === 'hydrated') {
            finishHydration();
            return;
          }
          finishHydration();
          if (msg.type === 'error') sess.term.writeln(`\r\n\x1b[31m[error] ${msg.message}\x1b[0m`);
          if (msg.type === 'closed') {
            ws._terminalClosed = true;
            sess.term.writeln(`\r\n\x1b[2m[terminal closed]\x1b[0m`);
          }
        } catch (_) {
          finishHydration();
          sess.term.write(ev.data);
        }
        dismissBoot();
      }
    };

    ws.onerror = () => {
      if (sess.ws !== ws) return;
      finishHydration();
    };

    ws.onclose = () => {
      if (sess.ws !== ws) return;
      finishHydration();
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
  }

  function connectPty(address, opts = {}) {
    if (!address) return;
    stopTouchCoast();

    const prevSess = activeSession();
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
  };

  function tabAgentKind(t) {
    const b = tabAgentBadge(t);
    if (b) return b;
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

  function renderTabs() {
    tabCountEl.textContent = String(terminals.length);
    sidebarTabsEl.innerHTML = '';
    if (topbarTabsEl) topbarTabsEl.innerHTML = '';
    if (sidebarAgentsEl) sidebarAgentsEl.innerHTML = '';
    mobileTabsEl.innerHTML = '';

    let agentCount = 0;
    let busyCount = 0;

    terminals.forEach((t, idx) => {
      const state = tabState(t);
      const { title: label, pill } = tabTitleParts(t);
      const agentKind = tabAgentKind(t);
      const iconKind = agentKind || 'shell';
      const isActive = t.address === activeId;
      const subText = tabSubtitle(t);

      // 1. Sidebar compact terminal row
      const btn = document.createElement('div');
      btn.className = `tab-item${isActive ? ' active' : ''}${state === 'blocked' ? ' is-blocked' : ''}${state === 'working' ? ' is-working' : ''}`;
      btn.setAttribute('role', 'tab');
      btn.setAttribute('aria-selected', isActive ? 'true' : 'false');
      btn.title = pill ? `${label} (${pill})` : label;

      const info = document.createElement('div');
      info.className = 'tab-info';
      const titleEl = document.createElement('div');
      titleEl.className = 'tab-title';
      const titleText = document.createElement('span');
      titleText.className = 'tab-title-text';
      titleText.textContent = label;
      titleEl.appendChild(titleText);
      if (pill) {
        const pillEl = document.createElement('span');
        pillEl.className = 'tab-agent-tag';
        pillEl.textContent = pill;
        titleEl.appendChild(pillEl);
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
      if (state === 'working' && t.status && typeof t.status.progress === 'number') {
        const bar = document.createElement('span');
        bar.className = 'tab-progress';
        const fill = document.createElement('i');
        fill.style.width = `${Math.max(4, Math.min(100, t.status.progress))}%`;
        bar.appendChild(fill);
        btn.appendChild(bar);
      }
      btn.addEventListener('click', () => {
        if (activeId !== t.address) connectPty(t.address);
        else focusTerminalIfDesktop();
      });
      sidebarTabsEl.appendChild(btn);

      // 2. Sidebar Pixel-Art Agent Card (for every active agent tab!)
      if (agentKind && sidebarAgentsEl) {
        agentCount += 1;
        if (state === 'working' || state === 'blocked') busyCount += 1;

        const card = document.createElement('button');
        card.type = 'button';
        card.className = `agent-card${isActive ? ' active' : ''}`;
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
        const cIdx = document.createElement('span');
        cIdx.className = 'agent-card-idx';
        cIdx.textContent = `tab ${idx + 1}`;
        cTop.append(cBadge, cIdx);

        const cName = document.createElement('div');
        cName.className = 'agent-card-name';
        cName.textContent = label;

        const cMsg = document.createElement('div');
        cMsg.className = 'agent-card-msg';
        cMsg.textContent = subText || (t.address || '');

        cInfo.append(cTop, cName, cMsg);
        main.append(stage, cInfo);
        card.appendChild(main);

        const foot = document.createElement('div');
        foot.className = 'agent-card-foot';
        const footL = document.createElement('span');
        footL.textContent = `└ ${AGENT_FULL_NAMES[agentKind] || agentKind}`;
        const footR = document.createElement('span');
        footR.textContent = idx < 9 ? `Alt+${idx + 1}` : '';
        foot.append(footL, footR);
        card.appendChild(foot);

        if (state === 'working' && t.status && typeof t.status.progress === 'number') {
          const pBar = document.createElement('div');
          pBar.className = 'agent-card-bar';
          const pFill = document.createElement('i');
          pFill.style.width = `${Math.max(5, Math.min(100, t.status.progress))}%`;
          pBar.appendChild(pFill);
          card.appendChild(pBar);
        }

        card.addEventListener('click', () => {
          if (activeId !== t.address) connectPty(t.address);
          else focusTerminalIfDesktop();
        });
        sidebarAgentsEl.appendChild(card);
      }

      // 3. Informative Horizontal Topbar Tab (Desktop)
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

      // 4. Mobile tab chip (with mini pixel icon!)
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
    if (sidebarAgentsEl && agentCount === 0) {
      const empty = document.createElement('div');
      empty.className = 'agents-empty';
      empty.textContent = 'No active agents yet — run claude, agy, codex, or opencode in any tab.';
      sidebarAgentsEl.appendChild(empty);
    }

    const mPlus = document.createElement('button');
    mPlus.className = 'm-tab m-tab-add';
    mPlus.textContent = '+';
    mPlus.title = 'New terminal tab';
    mPlus.setAttribute('aria-label', 'New terminal tab');
    mPlus.addEventListener('click', () => spawnTab('shell'));
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
      if (termCtxStateEl) {
        termCtxStateEl.dataset.state = aState;
        termCtxStateEl.textContent = stateBadgeText(aState, active.status);
      }
    } else {
      activeDotEl.dataset.state = 'idle';
      activeNameEl.textContent = 'No active tab';
      if (activeAgentEl) activeAgentEl.classList.add('hidden');
      if (activeStatusEl) activeStatusEl.textContent = 'idle';
      if (termCtxIconEl) termCtxIconEl.innerHTML = pixelIconHtml('shell');
      if (termCtxTitleEl) termCtxTitleEl.textContent = 'No active tab';
      if (termCtxStateEl) {
        termCtxStateEl.dataset.state = 'idle';
        termCtxStateEl.textContent = 'IDLE';
      }
    }

    if (statusbarSummaryEl) {
      const tabLabel = terminals.length === 1 ? '1 tab' : `${terminals.length} tabs`;
      const agLabel = agentCount === 1 ? '1 agent' : `${agentCount} agents`;
      const parts = [tabLabel, agLabel];
      if (busyCount > 0) parts.push(`${busyCount} busy`);
      statusbarSummaryEl.textContent = parts.join(' · ');
    }
  }

  function speak(text) {
    if (!ttsEnabled || !('speechSynthesis' in window) || !text) return;
    try {
      window.speechSynthesis.cancel();
      const u = new SpeechSynthesisUtterance(text);
      u.rate = 1.05;
      window.speechSynthesis.speak(u);
    } catch (_) {}
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
      const badge = isVeto ? 'SENDING' : 'ALLOW?';
      approvalBadgeEl.textContent = badge;
      mobileApprovalBadgeEl.textContent = badge;
      const pendingTabObj = pending.tab ? terminals.find((t) => t.address === pending.tab) : null;
      approvalTabEl.textContent = pendingTabObj
        ? `${tabDisplayName(pendingTabObj)} · ${pending.tab}`
        : (pending.tab || pending.risk || 'sysop');
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

      const key = `sysop:${pending.id}`;
      if (key !== lastSpokenKey) {
        lastSpokenKey = key;
        speak(`${isVeto ? 'Sending' : 'Approval required'}: ${pending.text}`);
      }
      requestAnimationFrame(fitAndResize);
      return;
    }

    if (oscBlocked) {
      currentApproval = { kind: 'osc', terminal: oscBlocked.terminal };
      approvalCardEl.classList.remove('hidden');
      mobileApprovalEl.classList.remove('hidden');
      approvalBarEl.classList.add('hidden');
      approvalBadgeEl.textContent = 'ALLOW?';
      mobileApprovalBadgeEl.textContent = 'ALLOW?';
      approvalTabEl.textContent = oscBlocked.name;
      approvalTextEl.textContent = oscBlocked.msg;
      mobileApprovalMsgEl.textContent = `${oscBlocked.name}: ${oscBlocked.msg}`;
      const key = `osc:${oscBlocked.terminal}:${oscBlocked.msg}`;
      if (key !== lastSpokenKey) {
        lastSpokenKey = key;
        speak(`Input needed on ${oscBlocked.name}. ${oscBlocked.msg}`);
      }
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

  function renderSysop(sysop) {
    if (!sysop) return;
    const st = sysop.state || 'off';
    sysopDotEl.dataset.state = st;
    sysopStateEl.dataset.state = st;
    sysopStateEl.textContent = st;
    mobileSysopDotEl.dataset.state = st;
    mobileSysopBtn.dataset.state = st;
    if (btnToggleSysop) btnToggleSysop.dataset.state = st;
    mobileSysopTextEl.textContent = st === 'idle' || st === 'off' ? 'Sysop' : (sysop.sentence || `Sysop · ${st}`);

    const running = st === 'working' || st === 'allow?' || st === 'sending' || st === 'queued';
    btnSysopStop.classList.toggle('hidden', !running);

    renderApprovalCard(sysop);

    sysopFeedEl.innerHTML = '';
    const steps = Array.isArray(sysop.steps) ? sysop.steps : [];
    if (!sysop.up) {
      const box = document.createElement('div');
      box.className = 'feed-empty';
      box.innerHTML = `
        <div class="feed-empty-title"><span class="status-dot" data-state="off"></span><span>Sysop offline</span></div>
        <div>Install the operator addon from Settings or run <code>swarmbox addon install sysop</code>.</div>
      `;
      sysopFeedEl.appendChild(box);
    } else if (steps.length === 0) {
      const box = document.createElement('div');
      box.className = 'feed-empty';
      box.innerHTML = `
        <div class="feed-empty-title"><span class="status-dot" data-state="done"></span><span>Ready</span></div>
        <div>Speak or type a goal — Sysop routes to your active tab and pauses risky actions for approval.</div>
      `;
      sysopFeedEl.appendChild(box);
    } else {
      for (const s of steps) {
        const div = document.createElement('div');
        div.className = `step ${s.kind || 'info'}`;
        const iconEl = document.createElement('span');
        iconEl.className = 'step-icon';
        iconEl.textContent =
          s.kind === 'ok' ? '✓' :
          s.kind === 'goal' ? '❯' :
          s.kind === 'warn' ? '!' :
          s.kind === 'err' ? '✕' : '·';
        const textEl = document.createElement('span');
        textEl.className = 'step-text';
        textEl.textContent = s.text || '';
        div.append(iconEl, textEl);
        sysopFeedEl.appendChild(div);
      }
      sysopFeedEl.scrollTop = sysopFeedEl.scrollHeight;
    }
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
      if (Array.isArray(msg.terminals)) {
        terminals = msg.terminals;
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
      if (msg.sysop) renderSysop(msg.sysop);
    };
  }

  async function spawnTab(preset) {
    const r = await fetch('/api/tabs', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ preset }),
    });
    const data = await r.json().catch(() => ({}));
    const addr = data && data.terminal && data.terminal.address;
    if (addr) setTimeout(() => connectPty(addr), 100);
  }

  async function sendGoal(text) {
    const goal = (text !== undefined ? text : goalInputEl.value).trim();
    if (!goal) return;
    if (text === undefined) goalInputEl.value = '';
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

  // ---- Real Voice Addon (16 kHz mono 16-bit PCM WAV -> /voice/audio) ------------------------
  const VOICE_RATE = 16000;
  let wavRec = null;
  let speechRec = null;

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

  function setMicRecording(on) {
    btnMic.classList.toggle('recording', on);
    btnMobileMic.classList.toggle('recording', on);
    if (micLabelEl) micLabelEl.textContent = on ? 'Listening' : 'Speak';
  }

  async function startWavRecording() {
    if (wavRec) return;
    const md = navigator.mediaDevices;
    const AC = window.AudioContext || window.webkitAudioContext;
    if (!md || !md.getUserMedia || !AC) {
      showVoiceNote(window.isSecureContext === false ? 'Microphone needs HTTPS or localhost.' : 'Browser cannot record audio.', 'error', 6000);
      return;
    }
    try {
      const stream = await md.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true } });
      const ctx = new AC();
      if (ctx.state === 'suspended') await ctx.resume();
      const src = ctx.createMediaStreamSource(stream);
      const proc = ctx.createScriptProcessor(4096, 1, 1);
      const rec = { stream, ctx, src, proc, chunks: [], samples: 0 };
      proc.onaudioprocess = (e) => {
        const ch = e.inputBuffer.getChannelData(0);
        rec.chunks.push(new Float32Array(ch));
        rec.samples += ch.length;
        if (rec.samples / ctx.sampleRate >= 60) finishWavRecording();
      };
      src.connect(proc);
      proc.connect(ctx.destination);
      wavRec = rec;
      setMicRecording(true);
      showVoiceNote('Listening… release to send', '', 0);
    } catch (err) {
      showVoiceNote(`Microphone error: ${err.name || err.message}`, 'error', 6000);
    }
  }

  async function finishWavRecording() {
    const rec = wavRec;
    if (!rec) return;
    wavRec = null;
    setMicRecording(false);
    try { rec.src.disconnect(); rec.proc.disconnect(); } catch (_) {}
    rec.proc.onaudioprocess = null;
    try { rec.stream.getTracks().forEach((t) => t.stop()); } catch (_) {}
    const rate = rec.ctx.sampleRate;
    try { rec.ctx.close(); } catch (_) {}
    if (rec.samples / rate < 0.3) {
      showVoiceNote('Too short — hold the mic while speaking.', 'warn', 3000);
      return;
    }
    const wav = encodeWav(downsample(rec.chunks, rec.samples, rate, VOICE_RATE), VOICE_RATE);
    showVoiceNote('Transcribing via local Whisper…', '', 0);
    try {
      const r = await fetch('/voice/audio', {
        method: 'POST',
        credentials: 'same-origin',
        cache: 'no-store',
        headers: { 'Content-Type': 'audio/wav' },
        body: wav,
      });
      const d = await r.json().catch(() => ({}));
      if (d.ok === true && d.state === 'sent') showVoiceNote('Voice goal sent to Sysop.', 'ok', 2500);
      else if (d.state === 'nothing_heard') showVoiceNote('Nothing heard.', 'warn', 3500);
      else if (d.state === 'no_listener') showVoiceNote('Nobody is listening (is Sysop running?).', 'warn', 6000);
      else showVoiceNote(d.message || d.error || 'Voice service failed.', 'error', 6000);
    } catch (e) {
      showVoiceNote(e.message || 'Voice request failed.', 'error', 6000);
    }
  }

  function toggleBrowserSpeech() {
    const SpeechRec = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRec) {
      showVoiceNote('Install the voice addon (`swarmbox addon install voice`) for local Whisper.', 'warn', 6000);
      goalInputEl.focus();
      return;
    }
    if (speechRec) {
      try { speechRec.stop(); } catch (_) {}
      speechRec = null;
      setMicRecording(false);
      return;
    }
    speechRec = new SpeechRec();
    speechRec.lang = navigator.language || 'en-US';
    speechRec.interimResults = false;
    setMicRecording(true);
    showVoiceNote('Listening (browser speech)…', '', 0);
    speechRec.onresult = (ev) => {
      const txt = ev.results && ev.results[0] && ev.results[0][0] ? ev.results[0][0].transcript : '';
      if (txt) sendGoal(txt);
    };
    speechRec.onend = () => { setMicRecording(false); speechRec = null; voiceNoteEl.classList.add('hidden'); };
    speechRec.onerror = () => { setMicRecording(false); speechRec = null; showVoiceNote('Speech recognition unavailable.', 'warn', 4000); };
    speechRec.start();
  }

  function wireMicButton(btn) {
    btn.addEventListener('pointerdown', (e) => {
      if (e.button !== undefined && e.button !== 0) return;
      if (voiceAddonAvailable) {
        e.preventDefault();
        try { btn.setPointerCapture(e.pointerId); } catch (_) {}
        startWavRecording();
      }
    });
    const release = (e) => {
      if (voiceAddonAvailable && wavRec) {
        e.preventDefault();
        finishWavRecording();
      }
    };
    btn.addEventListener('pointerup', release);
    btn.addEventListener('pointercancel', release);
    btn.addEventListener('click', () => {
      if (!voiceAddonAvailable) toggleBrowserSpeech();
    });
  }

  wireMicButton(btnMic);
  wireMicButton(btnMobileMic);

  // Probe local swarmbox-voice service quietly (no ugly "off" label when absent)
  fetch('/voice/health', { credentials: 'same-origin', cache: 'no-store' })
    .then((r) => {
      if (r.ok) {
        voiceAddonAvailable = true;
        voiceHintEl.textContent = 'hold · whisper';
      } else {
        voiceHintEl.textContent = '';
      }
    })
    .catch(() => { voiceHintEl.textContent = ''; });

  // ---- Layout Controls ----------------------------------------------------------------------
  // Responsive default: keep Sysop closed on narrower desktop/laptop widths (< 1360px) so the
  // terminal gets full room; open automatically on wide screens unless user manually toggled it.
  const SYSOP_WIDE_PX = 1360;
  let sysopUserToggled = false;

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

  function toggleSidebar() {
    appEl.dataset.sidebarOpen = appEl.dataset.sidebarOpen === '1' ? '0' : '1';
    requestAnimationFrame(() => { fitAndResize(); focusTerminalIfDesktop(); });
  }
  function toggleDesktopSysop() {
    sysopUserToggled = true;
    const next = appEl.dataset.sysopOpen === '1' ? '0' : '1';
    appEl.dataset.sysopOpen = next;
    btnToggleSysop.dataset.on = next;
    requestAnimationFrame(() => { fitAndResize(); focusTerminalIfDesktop(); });
  }
  function setMobileSysop(open) {
    const val = open ? '1' : '0';
    appEl.dataset.mobileSysop = val;
    mobileSysopBtn.dataset.on = val;
  }
  function setMobileKeys(open) {
    const val = open ? '1' : '0';
    appEl.dataset.mobileKeys = val;
    mobileKbBtn.dataset.on = val;
    mobileKbBtn.setAttribute('aria-pressed', open ? 'true' : 'false');
    const sess = activeSession();
    if (sess) {
      if (open) sess.term.focus();
      else sess.term.blur();
    }
    requestAnimationFrame(fitAndResize);
  }

  const btnNewShell = document.getElementById('btn-new-shell');
  if (btnNewShell) btnNewShell.addEventListener('click', () => { spawnTab('shell'); focusTerminalIfDesktop(); });
  document.getElementById('btn-sidebar-close').addEventListener('click', () => {
    appEl.dataset.sidebarOpen = '0';
    requestAnimationFrame(() => { fitAndResize(); focusTerminalIfDesktop(); });
  });
  document.getElementById('btn-sidebar-open').addEventListener('click', () => {
    appEl.dataset.sidebarOpen = '1';
    requestAnimationFrame(() => { fitAndResize(); focusTerminalIfDesktop(); });
  });
  btnToggleSysop.addEventListener('click', toggleDesktopSysop);
  document.getElementById('btn-sysop-close').addEventListener('click', () => {
    if (window.innerWidth <= 860) setMobileSysop(false);
    else toggleDesktopSysop();
  });
  mobileSysopBtn.addEventListener('click', () => setMobileSysop(appEl.dataset.mobileSysop !== '1'));
  document.getElementById('sheet-backdrop').addEventListener('click', () => setMobileSysop(false));
  document.getElementById('sheet-handle').addEventListener('click', () => setMobileSysop(false));
  mobileKbBtn.addEventListener('click', () => setMobileKeys(appEl.dataset.mobileKeys !== '1'));

  btnTts.addEventListener('click', () => {
    ttsEnabled = !ttsEnabled;
    btnTts.classList.toggle('active', ttsEnabled);
    if (ttsEnabled) speak('Sysop voice feedback enabled.');
    if (settingsOpen && settingsSection === 'sysop') renderSettingsBody();
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
    btnSendGoal.dataset.ready = goalInputEl.value.trim() ? '1' : '0';
  }
  syncSendReady();
  goalInputEl.addEventListener('input', syncSendReady);
  btnSendGoal.addEventListener('click', () => { sendGoal(); syncSendReady(); });
  goalInputEl.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
      e.preventDefault();
      goalInputEl.blur();
      focusTerminalIfDesktop();
      return;
    }
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendGoal();
      syncSendReady();
      focusTerminalIfDesktop();
    }
  });

  document.getElementById('btn-allow').addEventListener('click', () => { handleApproval('allow'); focusTerminalIfDesktop(); });
  document.getElementById('btn-cancel').addEventListener('click', () => { handleApproval('cancel'); focusTerminalIfDesktop(); });
  document.getElementById('btn-mobile-allow').addEventListener('click', () => handleApproval('allow'));
  document.getElementById('btn-mobile-cancel').addEventListener('click', () => handleApproval('cancel'));

  document.getElementById('touch-keys').addEventListener('click', async (e) => {
    const btn = e.target.closest('button[data-key]');
    if (!btn || !activeId) return;
    await fetch(`/api/tabs/${encodeURIComponent(activeId)}/keys`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ keys: [btn.dataset.key] }),
    });
  });

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
        el('span', { class: 's-stat-v', text: currentHostField('box', 'MUX').value || 'herdr' }),
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

    const CLASSIC_MUX = 'tm' + 'ux';
    const coreCard = el('div', { class: 's-card' }, [
      makeHostSelectRow('box', 'MUX', {
        title: 'Terminal Multiplexer',
        desc: 'Backend powering tabs, Cockpit and Web UI.',
        options: [
          { value: 'herdr', label: 'herdr (native studio)' },
          { value: CLASSIC_MUX, label: `${CLASSIC_MUX} (classic)` },
        ],
      }),
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

    // Live browser TTS toggle (instant)
    const liveCard = el('div', { class: 's-card' }, [
      makeSettingRow({
        title: 'Spoken Feedback (TTS)',
        desc: 'Read approval prompts and blocked agent notices aloud in this browser.',
        badge: { text: 'live', tone: 'ok' },
        control: makeSwitch(ttsEnabled, 'Spoken feedback', (next) => {
          ttsEnabled = next;
          btnTts.classList.toggle('active', ttsEnabled);
          if (ttsEnabled) speak('Sysop voice feedback enabled.');
          renderSettingsBody();
        }),
      }),
    ]);
    frag.appendChild(makeGroup('Browser Controls', null, liveCard));

    // Visual 3-card Autonomy selector
    const curAuto = effectiveHostValue('sysop', 'sysop.autonomy') || 'auto';
    const policies = [
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
      makeHostSelectRow('sysop', 'sysop.panel', {
        title: 'Panel Visibility',
        desc: 'When to show the operator panel automatically.',
        options: [
          { value: 'always', label: 'always' },
          { value: 'auto', label: 'auto (on goal)' },
          { value: 'off', label: 'off' },
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
          ? 'Local Whisper service is online — hold the mic button to transcribe straight to Sysop.'
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
