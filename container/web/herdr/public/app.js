(() => {
  // Five curated themes synchronized with ~/.config/herdr/config.toml via /api/theme.
  // Default: SwarmBox Purple Glow (exact palette from docs/theme.md).
  const THEMES = {
    'purple-glow': {
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

  // ---- Crisp SVG Boot Splash (exact half-block lettering from container/scripts/banner.sh) ---
  function buildBootSplash() {
    const host = document.getElementById('sb-boot');
    if (!host) return;
    const FONT = [
      '▄▀▀▀▀ █   █ ▄▀▀▀▄ █▀▀▀▄ █▄ ▄█ █▀▀▀▄ ▄▀▀▀▄ ▀▄ ▄▀',
      ' ▀▀▀▄ █▄▀▄█ █▀▀▀█ █▀▀█  █ ▀ █ █▀▀▀▄ █   █  ▄▀▄ ',
      '▀▀▀▀  ▀   ▀ ▀   ▀ ▀   ▀ ▀   ▀ ▀▀▀▀   ▀▀▀  ▀   ▀',
    ];
    const STOPS = [0x3f3f46, 0x6d28d9, 0xa78bfa, 0xffffff, 0xa78bfa, 0x6d28d9, 0x3f3f46];
    const W = FONT[0].length;
    const cellW = 7;
    const cellH = 14;
    const halfH = 7;
    const svgW = W * cellW;
    const svgH = FONT.length * cellH + 14;
    const colorAt = (col) => {
      const segs = STOPS.length - 1;
      const pos = (col / (W - 1)) * segs;
      const s = Math.min(segs - 1, Math.floor(pos));
      const f = pos - s;
      const a = STOPS[s];
      const b = STOPS[s + 1];
      const r = Math.round(((a >> 16) & 255) + (((b >> 16) & 255) - ((a >> 16) & 255)) * f);
      const g = Math.round(((a >> 8) & 255) + (((b >> 8) & 255) - ((a >> 8) & 255)) * f);
      const bl = Math.round((a & 255) + ((b & 255) - (a & 255)) * f);
      return `rgb(${r},${g},${bl})`;
    };
    const NS = 'http://www.w3.org/2000/svg';
    const svg = document.createElementNS(NS, 'svg');
    const dispW = Math.min(340, Math.round(window.innerWidth * 0.64));
    svg.setAttribute('viewBox', `0 0 ${svgW} ${svgH}`);
    svg.setAttribute('width', String(dispW));
    svg.setAttribute('height', String(Math.round((dispW * svgH) / svgW)));
    const rect = (x, y, w, h, fill) => {
      const el = document.createElementNS(NS, 'rect');
      el.setAttribute('x', String(x));
      el.setAttribute('y', String(y));
      el.setAttribute('width', String(w));
      el.setAttribute('height', String(h));
      el.setAttribute('fill', fill);
      svg.appendChild(el);
    };
    for (let row = 0; row < FONT.length; row++) {
      for (let col = 0; col < W; col++) {
        const ch = FONT[row][col];
        if (ch === ' ') continue;
        const fill = colorAt(col);
        const x = col * cellW;
        const y = row * cellH;
        if (ch === '█') rect(x, y, cellW, cellH, fill);
        else if (ch === '▀') rect(x, y, cellW, halfH, fill);
        else if (ch === '▄') rect(x, y + halfH, cellW, halfH, fill);
      }
    }
    // Segmented gradient underline matching banner.sh
    let bc = 0;
    for (const seg of [14, 8, 4, 2]) {
      for (let j = 0; j < seg; j++) {
        rect((bc + j) * cellW, FONT.length * cellH + 9, cellW, 2, colorAt(bc + j));
      }
      bc += seg + 1;
    }
    host.appendChild(svg);
  }
  buildBootSplash();

  let bootDismissed = false;
  function dismissBoot() {
    if (bootDismissed) return;
    bootDismissed = true;
    document.documentElement.classList.add('swarmbox-ready');
  }
  setTimeout(dismissBoot, 3000);

  const appEl = document.getElementById('app');
  const sidebarTabsEl = document.getElementById('sidebar-tabs');
  const mobileTabsEl = document.getElementById('mobile-tabs');
  const tabCountEl = document.getElementById('tab-count');
  const activeDotEl = document.getElementById('active-dot');
  const activeNameEl = document.getElementById('active-name');
  const activeStatusEl = document.getElementById('active-status');
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
  const themeSelectEl = document.getElementById('theme-select');
  const themeSelectMobileEl = document.getElementById('theme-select-mobile');
  const btnTts = document.getElementById('btn-tts');
  const btnMic = document.getElementById('btn-mic');
  const btnMobileMic = document.getElementById('btn-mobile-mic');
  const termWrapEl = document.getElementById('term-wrap');
  const btnJumpLive = document.getElementById('btn-jump-live');

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

  const btnFontDec = document.getElementById('btn-font-dec');
  const btnFontReset = document.getElementById('btn-font-reset');
  const btnFontInc = document.getElementById('btn-font-inc');

  let fontOffset = (() => {
    try {
      const v = Number(localStorage.getItem('swarmbox-herdr-font-offset') || '0');
      return Number.isFinite(v) ? Math.max(-4, Math.min(8, v)) : 0;
    } catch (_) { return 0; }
  })();

  // Dynamic column-aware font sizing:
  // Desktop defaults to a comfortable 16.5px (adjustable via sidebar stepper or Alt+-/=/0).
  // On phones (<= 860px), pick the exact font size so >= 51 columns fit upright (keeping the
  // 49-col SwarmBox banner & single-line Starship prompt completely unbroken).
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

  function syncFontLabel() {
    if (!btnFontReset) return;
    const sz = computeFontSize();
    btnFontReset.textContent = Number.isInteger(sz) ? `${sz}px` : `${sz.toFixed(1)}px`;
  }
  syncFontLabel();

  function adjustFontOffset(delta) {
    fontOffset = delta === 0 ? 0 : Math.max(-4, Math.min(8, fontOffset + delta));
    try { localStorage.setItem('swarmbox-herdr-font-offset', String(fontOffset)); } catch (_) {}
    syncFontLabel();
    fitAndResize();
    focusTerminalIfDesktop();
  }
  if (btnFontDec) btnFontDec.addEventListener('click', () => adjustFontOffset(-1));
  if (btnFontReset) btnFontReset.addEventListener('click', () => adjustFontOffset(0));
  if (btnFontInc) btnFontInc.addEventListener('click', () => adjustFontOffset(1));

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
    themeSelectEl.value = key;
    themeSelectMobileEl.value = key;
    try { localStorage.setItem('swarmbox-herdr-theme', key); } catch (_) {}
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
  themeSelectEl.addEventListener('change', (e) => { applyTheme(e.target.value, true); focusTerminalIfDesktop(); });
  themeSelectMobileEl.addEventListener('change', (e) => applyTheme(e.target.value, true));

  function fitSession(sess, sendResize = true) {
    if (!sess) return;
    try {
      const nextFont = computeFontSize();
      const nextLH = window.innerWidth <= 860 ? 1.12 : 1.24;
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
    syncFontLabel();
    const active = activeSession();
    for (const sess of tabSessions.values()) {
      if (sess === active) fitSession(sess, true);
      else sess.needsFit = true;
    }
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
    const sess = activeSession();
    if (!sess || window.innerWidth <= 860) return;
    if (sess.term.hasSelection() || (window.getSelection && window.getSelection().toString())) return;
    sess.term.focus();
    if (!sess.ws || sess.ws.readyState === 2 || sess.ws.readyState === 3) {
      openSessionSocket(sess, { silent: true, reset: true });
    }
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
    if (code === 'Equal' || code === 'NumpadAdd' || key === '=' || key === '+') return { action: 'font', delta: 1 };
    if (code === 'Minus' || code === 'NumpadSubtract' || key === '-' || key === '_') return { action: 'font', delta: -1 };
    if (code === 'Digit0' || code === 'Numpad0' || key === '0') return { action: 'font', delta: 0 };
    return null;
  }

  function runAltShortcut(sc) {
    if (!sc) return;
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
      const idx = THEME_KEYS.indexOf(themeSelectEl.value);
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

  function tabState(t) {
    return (t && t.status && t.status.state) || 'idle';
  }

  function tabSubtitle(t) {
    const st = t && t.status;
    if (st && st.state === 'blocked') return `blocked · ${st.msg || st.kind || 'needs input'}`;
    if (st && st.state === 'working') {
      const pct = typeof st.progress === 'number' ? `${st.progress}% ` : '';
      return `${pct}${st.msg || 'working…'}`;
    }
    if (st && st.state === 'done' && st.msg) return `✓ ${st.msg}`;
    if (st && st.state === 'error' && st.msg) return `✕ ${st.msg}`;
    const cwd = (t && t.foreground && t.foreground.cwd) || (t && t.cwd) || '';
    if (cwd.startsWith('/home/agent')) return '~' + cwd.slice('/home/agent'.length);
    return (t && t.title) || cwd || (t && t.address) || '';
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
      fontFamily: "'JetBrainsMono Nerd Font', 'JetBrains Mono', 'CaskaydiaCove Nerd Font', 'Cascadia Code', Consolas, Menlo, 'Liberation Mono', monospace",
      fontSize: computeFontSize(),
      lineHeight: window.innerWidth <= 860 ? 1.12 : 1.24,
      cursorBlink: true,
      scrollback: 3000,
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

    // Ctrl+C copies when text is selected; Ctrl+V pastes from clipboard; Alt shortcuts stay in Web UI
    term.attachCustomKeyEventHandler((ev) => {
      if (ev.type !== 'keydown') return true;
      if (matchAltShortcut(ev)) return false;
      if (ev.ctrlKey && !ev.altKey && !ev.metaKey && ev.key.toLowerCase() === 'c' && term.hasSelection()) {
        navigator.clipboard?.writeText(term.getSelection()).catch(() => {});
        term.clearSelection();
        return false;
      }
      if (ev.ctrlKey && !ev.altKey && !ev.metaKey && ev.key.toLowerCase() === 'v') {
        if (navigator.clipboard?.readText) {
          navigator.clipboard.readText().then((txt) => {
            if (txt) sendPtyInput(txt, sess);
          }).catch(() => {});
          return false;
        }
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

  function renderTabs() {
    tabCountEl.textContent = String(terminals.length);
    sidebarTabsEl.innerHTML = '';
    mobileTabsEl.innerHTML = '';

    terminals.forEach((t, idx) => {
      const state = tabState(t);
      const label = t.name || t.address;
      const isActive = t.address === activeId;

      const btn = document.createElement('div');
      btn.className = `tab-item${isActive ? ' active' : ''}${state === 'blocked' ? ' is-blocked' : ''}`;
      btn.setAttribute('role', 'tab');
      btn.setAttribute('aria-selected', isActive ? 'true' : 'false');

      const dot = document.createElement('span');
      dot.className = 'status-dot';
      dot.dataset.state = state;

      const info = document.createElement('div');
      info.className = 'tab-info';
      const titleEl = document.createElement('div');
      titleEl.className = 'tab-title';
      titleEl.textContent = label;
      const subEl = document.createElement('div');
      subEl.className = 'tab-sub';
      subEl.textContent = tabSubtitle(t);
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

      btn.append(dot, info, right);
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

      // Mobile tab chip
      const m = document.createElement('button');
      m.className = `m-tab${isActive ? ' active' : ''}`;
      const mDot = document.createElement('span');
      mDot.className = 'status-dot';
      mDot.dataset.state = state;
      const mName = document.createElement('span');
      mName.textContent = label;
      m.append(mDot, mName);
      m.addEventListener('click', () => {
        if (activeId !== t.address) connectPty(t.address);
      });
      mobileTabsEl.appendChild(m);
    });

    const mPlus = document.createElement('button');
    mPlus.className = 'm-tab m-tab-add';
    mPlus.textContent = '+ Shell';
    mPlus.addEventListener('click', () => spawnTab('shell'));
    mobileTabsEl.appendChild(mPlus);

    const active = terminals.find((t) => t.address === activeId);
    if (active) {
      activeDotEl.dataset.state = tabState(active);
      activeNameEl.textContent = active.name || active.address;
      activeStatusEl.textContent = tabSubtitle(active);
    } else {
      activeDotEl.dataset.state = 'idle';
      activeNameEl.textContent = 'No active tab';
      activeStatusEl.textContent = 'idle';
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
        ? `${pendingTabObj.name || pending.tab} · ${pending.tab}`
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
        <div>Install &amp; start the operator addon to drive terminals by goal or voice:</div>
        <div><code>swarmbox addon install sysop</code></div>
      `;
      sysopFeedEl.appendChild(box);
    } else if (steps.length === 0) {
      const box = document.createElement('div');
      box.className = 'feed-empty';
      box.innerHTML = `
        <div class="feed-empty-title"><span class="status-dot" data-state="done"></span><span>Ready for goals</span></div>
        <div>Speak or type what you want done — Sysop reads the active tab, routes to your agent, and holds risky actions for your approval.</div>
        <div class="shortcut-hints">
          <span class="kbd-chip"><b>Alt+1..9</b> tabs</span>
          <span class="kbd-chip"><b>Alt+N</b> shell</span>
          <span class="kbd-chip"><b>Alt+G</b> goal</span>
          <span class="kbd-chip"><b>Alt+T</b> theme</span>
        </div>
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
      if (msg.theme && THEMES[msg.theme] && msg.theme !== themeSelectEl.value) {
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
  function toggleSidebar() {
    appEl.dataset.sidebarOpen = appEl.dataset.sidebarOpen === '1' ? '0' : '1';
    requestAnimationFrame(() => { fitAndResize(); focusTerminalIfDesktop(); });
  }
  function toggleDesktopSysop() {
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

  document.getElementById('btn-new-shell').addEventListener('click', () => { spawnTab('shell'); focusTerminalIfDesktop(); });
  document.getElementById('btn-new-agent').addEventListener('click', () => { spawnTab('agent'); focusTerminalIfDesktop(); });
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

  connectEvents();
})();
