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

  let terminals = [];
  let activeId = null;
  let ptyWs = null;
  let eventsWs = null;
  let eventsConnected = false;
  let ptyConnected = false;
  let ptyReconnectTimer = null;
  let ptyReconnectDelay = 400;
  let pendingInput = [];
  let ttsEnabled = false;
  let lastSpokenKey = '';
  let currentApproval = null;
  let voiceAddonAvailable = false;
  let countdownTimer = null;

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

  // Dynamic column-aware font sizing:
  // On phones (<= 860px), pick the exact font size so >= 56 columns fit upright (keeping the
  // 49-col SwarmBox banner & Starship prompt completely unbroken, mirroring ttyd-clipboard.js).
  function computeFontSize() {
    const w = window.innerWidth;
    if (w > 860) return 15;
    const usable = Math.max(240, (termWrapEl.clientWidth || w) - 18);
    const targetCols = w < window.innerHeight ? 56 : 104;
    const raw = usable / (targetCols * 0.605);
    return Math.max(9.5, Math.min(13.5, Math.round(raw * 2) / 2));
  }

  const term = new window.Terminal({
    fontFamily: "'JetBrainsMono Nerd Font', 'JetBrains Mono', 'CaskaydiaCove Nerd Font', 'Cascadia Code', Consolas, Menlo, 'Liberation Mono', monospace",
    fontSize: computeFontSize(),
    lineHeight: window.innerWidth <= 860 ? 1.12 : 1.24,
    cursorBlink: true,
    scrollback: 3000,
    macOptionIsMeta: true,
    allowProposedApi: true,
  });
  const fitAddon = new window.FitAddon.FitAddon();
  term.loadAddon(fitAddon);
  if (window.WebLinksAddon) {
    term.loadAddon(new window.WebLinksAddon.WebLinksAddon());
  }
  term.open(document.getElementById('terminal'));

  // Show sleek floating "Jump to live" pill whenever user scrolls up into history
  const xtermViewportEl = document.querySelector('#terminal .xterm-viewport');
  function syncJumpLive() {
    if (!btnJumpLive) return;
    const buf = term.buffer && term.buffer.active;
    const vp = xtermViewportEl || document.querySelector('#terminal .xterm-viewport');
    const bufUp = Boolean(buf && buf.baseY - buf.viewportY > 2);
    const domUp = Boolean(vp && vp.scrollHeight > vp.clientHeight + 48 && (vp.scrollHeight - vp.scrollTop - vp.clientHeight) > 36);
    btnJumpLive.classList.toggle('visible', bufUp || domUp);
  }
  term.onScroll(syncJumpLive);
  term.onRender(syncJumpLive);
  if (xtermViewportEl) {
    xtermViewportEl.addEventListener('scroll', syncJumpLive, { passive: true });
  }
  if (btnJumpLive) {
    btnJumpLive.addEventListener('click', () => {
      term.scrollToBottom();
      const vp = xtermViewportEl || document.querySelector('#terminal .xterm-viewport');
      if (vp) vp.scrollTop = vp.scrollHeight;
      syncJumpLive();
      focusTerminalIfDesktop();
    });
  }

  // Eliminate faint horizontal hairline seams on block-drawing rows (banner.sh half-blocks)
  const BLOCK_RE = /[\u2580-\u259f]/;
  function markBlockRows() {
    const rows = document.querySelectorAll('#terminal .xterm-rows > div');
    for (const row of rows) {
      const hasBlk = BLOCK_RE.test(row.textContent || '');
      if (hasBlk !== row.classList.contains('sb-blk')) {
        row.classList.toggle('sb-blk', hasBlk);
      }
    }
  }
  const rowsRoot = document.querySelector('#terminal .xterm-rows');
  if (rowsRoot && window.MutationObserver) {
    let blkRaf = 0;
    const scheduleBlk = () => {
      if (blkRaf) return;
      blkRaf = requestAnimationFrame(() => { blkRaf = 0; markBlockRows(); });
    };
    new MutationObserver(scheduleBlk).observe(rowsRoot, { childList: true, subtree: true, characterData: true });
  }
  function updateBlockScale() {
    const scale = window.innerWidth <= 860 ? 1.18 : 1.28;
    document.documentElement.style.setProperty('--sb-blk-s', String(scale));
  }
  updateBlockScale();

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

  // Ctrl+C copies when text is selected; Ctrl+V pastes from clipboard
  term.attachCustomKeyEventHandler((ev) => {
    if (ev.type !== 'keydown') return true;
    if (ev.ctrlKey && !ev.altKey && !ev.metaKey && ev.key.toLowerCase() === 'c' && term.hasSelection()) {
      navigator.clipboard?.writeText(term.getSelection()).catch(() => {});
      term.clearSelection();
      return false;
    }
    if (ev.ctrlKey && !ev.altKey && !ev.metaKey && ev.key.toLowerCase() === 'v') {
      if (navigator.clipboard?.readText) {
        navigator.clipboard.readText().then((txt) => {
          if (txt) sendPtyInput(txt);
        }).catch(() => {});
        return false;
      }
    }
    return true;
  });

  // Smooth touch drag-scroll over the terminal canvas on phones (leaving pinch-zoom intact)
  let touchStartY = null;
  let touchAccum = 0;
  termWrapEl.addEventListener('touchstart', (e) => {
    if (e.touches.length === 1) {
      touchStartY = e.touches[0].clientY;
      touchAccum = 0;
    } else {
      touchStartY = null;
    }
  }, { passive: true });
  termWrapEl.addEventListener('touchmove', (e) => {
    if (e.touches.length !== 1 || touchStartY === null) return;
    const y = e.touches[0].clientY;
    const dy = touchStartY - y;
    touchStartY = y;
    touchAccum += dy;
    const lines = Math.trunc(touchAccum / 18);
    if (lines !== 0) {
      touchAccum -= lines * 18;
      term.scrollLines(lines);
    }
  }, { passive: true });
  termWrapEl.addEventListener('touchend', () => { touchStartY = null; }, { passive: true });

  function applyTheme(name, persist = false) {
    const key = THEMES[name] ? name : 'purple-glow';
    const t = THEMES[key];
    for (const [k, v] of Object.entries(t.css)) {
      document.documentElement.style.setProperty(k, v);
    }
    term.options.theme = t.xterm;
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

  function fitAndResize() {
    try {
      const nextFont = computeFontSize();
      const nextLH = window.innerWidth <= 860 ? 1.12 : 1.24;
      if (term.options.fontSize !== nextFont) term.options.fontSize = nextFont;
      if (term.options.lineHeight !== nextLH) term.options.lineHeight = nextLH;
      updateBlockScale();
      fitAddon.fit();
      markBlockRows();
      if (ptyWs && ptyWs.readyState === 1) {
        ptyWs.send(JSON.stringify({ type: 'resize', cols: term.cols, rows: term.rows }));
      }
    } catch (_) {}
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
    if (window.innerWidth > 860 && document.activeElement !== goalInputEl) {
      term.focus();
    }
  }

  function sendPtyInput(data) {
    if (!data) return;
    if (ptyWs && ptyWs.readyState === 1) {
      ptyWs.send(JSON.stringify({ type: 'input', data }));
      return;
    }
    // Never silently drop keystrokes when the PTY socket dipped or is reconnecting:
    // buffer the input and immediately re-attach to the active terminal.
    pendingInput.push(data);
    if (pendingInput.length > 64) pendingInput = pendingInput.slice(-64);
    if (activeId && (!ptyWs || ptyWs.readyState === 2 || ptyWs.readyState === 3)) {
      connectPty(activeId, { silent: true });
    }
  }

  term.onData((data) => {
    sendPtyInput(data);
  });

  // Clicking anywhere on the terminal canvas (without a drag selection) restores keyboard focus
  // and recovers a dropped PTY socket immediately.
  termWrapEl.addEventListener('mouseup', () => {
    if (window.innerWidth <= 860) return;
    if (term.hasSelection() || (window.getSelection && window.getSelection().toString())) return;
    term.focus();
    if (activeId && (!ptyWs || ptyWs.readyState === 2 || ptyWs.readyState === 3)) {
      connectPty(activeId, { silent: true });
    }
  });

  // Auto-heal dropped WebSockets when returning to the browser tab or waking from sleep
  function ensureConnectionsAlive() {
    if (!eventsWs || eventsWs.readyState === 2 || eventsWs.readyState === 3) {
      connectEvents();
    }
    if (activeId && (!ptyWs || ptyWs.readyState === 2 || ptyWs.readyState === 3)) {
      connectPty(activeId, { silent: true });
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
  // Alt+1..9 tabs, Alt+N shell, Alt+B sidebar, Alt+S Sysop, Alt+G goal, Alt+T cycle theme)
  // Plus gentle desktop focus-rescue: typing when focus landed on <body> routes cleanly into xterm.
  const THEME_KEYS = Object.keys(THEMES);
  window.addEventListener('keydown', (e) => {
    const tag = e.target && e.target.tagName;
    const inField = tag === 'TEXTAREA' || tag === 'INPUT' || tag === 'SELECT';
    if (e.altKey && !e.ctrlKey && !e.metaKey) {
      if (inField) return;
      if (e.key >= '1' && e.key <= '9') {
        const idx = Number(e.key) - 1;
        if (terminals[idx]) {
          e.preventDefault();
          if (activeId !== terminals[idx].address) connectPty(terminals[idx].address);
          else focusTerminalIfDesktop();
        }
        return;
      }
      const low = e.key.toLowerCase();
      if (low === 'n') { e.preventDefault(); spawnTab('shell'); }
      else if (low === 's') { e.preventDefault(); toggleDesktopSysop(); }
      else if (low === 'b') { e.preventDefault(); toggleSidebar(); }
      else if (low === 'g') {
        e.preventDefault();
        if (window.innerWidth > 860 && appEl.dataset.sysopOpen !== '1') toggleDesktopSysop();
        else if (window.innerWidth <= 860) setMobileSysop(true);
        goalInputEl.focus();
      } else if (low === 't') {
        e.preventDefault();
        const idx = THEME_KEYS.indexOf(themeSelectEl.value);
        applyTheme(THEME_KEYS[(idx + 1) % THEME_KEYS.length], true);
        focusTerminalIfDesktop();
      }
      return;
    }

    // Gentle focus-rescue on desktop: if focus slipped to document.body (e.g. clicked empty chrome),
    // rescue regular typing straight back into the terminal without losing the keystroke.
    if (window.innerWidth > 860 && !inField && !e.metaKey && !e.altKey && document.activeElement === document.body) {
      if (e.ctrlKey && (e.key.toLowerCase() === 'c' || e.key.toLowerCase() === 'v')) return;
      if (e.key.length === 1 || e.key === 'Enter' || e.key === 'Backspace') {
        term.focus();
      }
    }
  });

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

  function connectPty(address, opts = {}) {
    if (!address) return;
    if (ptyReconnectTimer) {
      clearTimeout(ptyReconnectTimer);
      ptyReconnectTimer = null;
    }
    const prevWs = ptyWs;
    ptyWs = null;
    if (prevWs) {
      prevWs.onclose = null;
      prevWs.onerror = null;
      try { prevWs.close(); } catch (_) {}
    }

    const switching = activeId !== address;
    activeId = address;
    ptyConnected = false;
    syncConnPill();
    if (switching) pendingInput = [];

    // Hide terminal canvas while initial history burst hydrates so users never see
    // a chaotic 500-line scroll-to-bottom replay animation on load, tab switch, or reconnect.
    let hydrating = true;
    let hydrationChunks = [];
    let settleTimer = null;
    let capTimer = null;

    termWrapEl.classList.add('term-loading');
    term.reset();
    fitAndResize();

    const finishHydration = () => {
      if (!hydrating) return;
      hydrating = false;
      if (settleTimer) { clearTimeout(settleTimer); settleTimer = null; }
      if (capTimer) { clearTimeout(capTimer); capTimer = null; }
      const batch = hydrationChunks;
      hydrationChunks = [];
      const reveal = () => {
        if (ptyWs !== ws) return;
        try { term.scrollToBottom(); } catch (_) {}
        markBlockRows();
        requestAnimationFrame(() => {
          termWrapEl.classList.remove('term-loading');
          dismissBoot();
          focusTerminalIfDesktop();
        });
      };
      if (batch.length > 0) {
        term.write(concatChunks(batch), reveal);
      } else {
        reveal();
      }
    };

    const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${proto}//${location.host}/ws/pty/${encodeURIComponent(address)}?cols=${term.cols}&rows=${term.rows}`;
    const ws = new WebSocket(wsUrl);
    ws.binaryType = 'arraybuffer';
    ptyWs = ws;

    if (hydrating) {
      // Fallback cap in case the terminal has no initial output at all
      capTimer = setTimeout(finishHydration, 360);
    }

    ws.onopen = () => {
      if (ptyWs !== ws) return;
      ptyConnected = true;
      ptyReconnectDelay = 400;
      syncConnPill();
      ws.send(JSON.stringify({ type: 'focus', focused: true }));
      fitAndResize();
      if (pendingInput.length > 0) {
        const queued = pendingInput;
        pendingInput = [];
        for (const chunk of queued) {
          ws.send(JSON.stringify({ type: 'input', data: chunk }));
        }
      }
      if (!hydrating) focusTerminalIfDesktop();
    };

    ws.onmessage = (ev) => {
      if (ptyWs !== ws) return;
      if (ev.data instanceof ArrayBuffer) {
        const bytes = new Uint8Array(ev.data);
        if (hydrating) {
          hydrationChunks.push(bytes);
          if (settleTimer) clearTimeout(settleTimer);
          // Once chunks arrive, wait 45ms of quiet for the history burst to finish
          settleTimer = setTimeout(finishHydration, 45);
          // Tighten max cap to 220ms after first byte so reveal is always snappy
          if (!ws._firstByteSeen) {
            ws._firstByteSeen = true;
            if (capTimer) clearTimeout(capTimer);
            capTimer = setTimeout(finishHydration, 220);
          }
          return;
        }
        term.write(bytes, () => dismissBoot());
      } else if (typeof ev.data === 'string') {
        finishHydration();
        try {
          const msg = JSON.parse(ev.data);
          if (msg.type === 'error') term.writeln(`\r\n\x1b[31m[error] ${msg.message}\x1b[0m`);
          if (msg.type === 'closed') {
            ws._terminalClosed = true;
            term.writeln(`\r\n\x1b[2m[terminal closed]\x1b[0m`);
          }
        } catch (_) {
          term.write(ev.data);
        }
        dismissBoot();
      }
    };

    ws.onerror = () => {
      if (ptyWs !== ws) return;
      finishHydration();
    };

    ws.onclose = () => {
      if (ptyWs !== ws) return;
      finishHydration();
      ptyWs = null;
      ptyConnected = false;
      syncConnPill();
      if (ws._terminalClosed) return;
      // Auto-reconnect silently if this tab is still live so keyboard input never freezes
      if (activeId === address && terminals.some((t) => t.address === address)) {
        const delay = ptyReconnectDelay;
        ptyReconnectDelay = Math.min(Math.round(ptyReconnectDelay * 1.6), 3000);
        ptyReconnectTimer = setTimeout(() => {
          ptyReconnectTimer = null;
          if (activeId === address && !ptyWs) {
            connectPty(address, { silent: true });
          }
        }, delay);
      }
    };

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
        if (!activeId || !terminals.some((t) => t.address === activeId)) {
          const preferred = msg.active && terminals.some((t) => t.address === msg.active)
            ? msg.active
            : (terminals[0] && terminals[0].address);
          if (preferred) connectPty(preferred);
          else { activeId = null; renderTabs(); dismissBoot(); }
        } else {
          // If events reconnected after a brief blip and PTY socket died, heal PTY automatically
          if (!ptyWs || ptyWs.readyState === 2 || ptyWs.readyState === 3) {
            connectPty(activeId, { silent: true });
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
    if (open) term.focus();
    else term.blur();
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
