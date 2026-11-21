(() => {
  // Five curated themes synchronized with ~/.config/herdr/config.toml via /api/theme.
  // Default: SwarmBox Purple Glow (exact palette from docs/theme.md).
  const THEMES = {
    'purple-glow': {
      css: {
        '--bg': '#0c0b10',
        '--surface': '#14121b',
        '--surface-2': '#1c1926',
        '--surface-hover': '#27222f',
        '--border': 'rgba(167, 139, 250, 0.16)',
        '--border-strong': 'rgba(167, 139, 250, 0.38)',
        '--text': '#f4f4f5',
        '--text-muted': '#a1a1aa',
        '--text-dim': '#71717a',
        '--accent': '#a78bfa',
        '--accent-bright': '#c4b5fd',
        '--accent-bg': 'rgba(167, 139, 250, 0.14)',
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
        '--surface-2': '#1e1e2e',
        '--surface-hover': '#2a2b3d',
        '--border': 'rgba(203, 166, 247, 0.16)',
        '--border-strong': 'rgba(203, 166, 247, 0.36)',
        '--text': '#cdd6f4',
        '--text-muted': '#a6adc8',
        '--text-dim': '#6c7086',
        '--accent': '#cba6f7',
        '--accent-bright': '#f5c2e7',
        '--accent-bg': 'rgba(203, 166, 247, 0.14)',
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
        '--surface-2': '#24283b',
        '--surface-hover': '#2f3549',
        '--border': 'rgba(122, 162, 247, 0.18)',
        '--border-strong': 'rgba(122, 162, 247, 0.40)',
        '--text': '#c0caf5',
        '--text-muted': '#9aa5ce',
        '--text-dim': '#565f89',
        '--accent': '#7aa2f7',
        '--accent-bright': '#bb9af7',
        '--accent-bg': 'rgba(122, 162, 247, 0.14)',
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
        '--surface-2': '#3b4252',
        '--surface-hover': '#434c5e',
        '--border': 'rgba(136, 192, 208, 0.18)',
        '--border-strong': 'rgba(136, 192, 208, 0.42)',
        '--text': '#eceff4',
        '--text-muted': '#d8dee9',
        '--text-dim': '#8190a8',
        '--accent': '#88c0d0',
        '--accent-bright': '#8fbcbb',
        '--accent-bg': 'rgba(136, 192, 208, 0.15)',
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
        '--surface-2': '#26233a',
        '--surface-hover': '#312c49',
        '--border': 'rgba(196, 167, 231, 0.18)',
        '--border-strong': 'rgba(196, 167, 231, 0.40)',
        '--text': '#e0def4',
        '--text-muted': '#908caa',
        '--text-dim': '#6e6a86',
        '--accent': '#c4a7e7',
        '--accent-bright': '#ebbcba',
        '--accent-bg': 'rgba(196, 167, 231, 0.15)',
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
  const mobileSysopDotEl = document.getElementById('mobile-sysop-dot');
  const mobileSysopStateEl = document.getElementById('mobile-sysop-state');
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
  const goalInputEl = document.getElementById('goal-input');
  const themeSelectEl = document.getElementById('theme-select');
  const themeSelectMobileEl = document.getElementById('theme-select-mobile');
  const btnTts = document.getElementById('btn-tts');
  const btnMic = document.getElementById('btn-mic');
  const btnMobileMic = document.getElementById('btn-mobile-mic');

  let terminals = [];
  let activeId = null;
  let ptyWs = null;
  let ttsEnabled = false;
  let lastSpokenKey = '';
  let currentApproval = null; // { kind: 'sysop' | 'osc', terminal?, deadline?, totalMs? }
  let voiceAddonAvailable = false;
  let countdownTimer = null;

  // Initialize xterm.js
  const term = new window.Terminal({
    fontFamily: "'JetBrainsMono Nerd Font', 'JetBrains Mono', 'CaskaydiaCove Nerd Font', 'Cascadia Code', Consolas, Menlo, monospace",
    fontSize: window.innerWidth <= 860 ? 13 : 14.5,
    lineHeight: 1.25,
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
          if (txt && ptyWs && ptyWs.readyState === 1) {
            ptyWs.send(JSON.stringify({ type: 'input', data: txt }));
          }
        }).catch(() => {});
        return false;
      }
    }
    return true;
  });

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
  themeSelectEl.addEventListener('change', (e) => applyTheme(e.target.value, true));
  themeSelectMobileEl.addEventListener('change', (e) => applyTheme(e.target.value, true));

  function fitAndResize() {
    try {
      fitAddon.fit();
      if (ptyWs && ptyWs.readyState === 1) {
        ptyWs.send(JSON.stringify({ type: 'resize', cols: term.cols, rows: term.rows }));
      }
    } catch (_) {}
  }

  const ro = new ResizeObserver(() => requestAnimationFrame(fitAndResize));
  ro.observe(document.getElementById('term-wrap'));

  // Adapt to mobile virtual keyboard smoothly
  if (window.visualViewport) {
    const syncViewport = () => {
      appEl.style.height = `${Math.round(window.visualViewport.height)}px`;
      requestAnimationFrame(fitAndResize);
    };
    window.visualViewport.addEventListener('resize', syncViewport);
  }

  term.onData((data) => {
    if (ptyWs && ptyWs.readyState === 1) {
      ptyWs.send(JSON.stringify({ type: 'input', data }));
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
    return t.title || t.cwd || t.address;
  }

  function connectPty(address) {
    if (!address) return;
    if (ptyWs) {
      try { ptyWs.close(); } catch (_) {}
      ptyWs = null;
    }
    activeId = address;
    term.reset();
    fitAddon.fit();

    const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${proto}//${location.host}/ws/pty/${encodeURIComponent(address)}?cols=${term.cols}&rows=${term.rows}`;
    const ws = new WebSocket(wsUrl);
    ws.binaryType = 'arraybuffer';
    ptyWs = ws;

    ws.onopen = () => {
      if (ptyWs !== ws) return;
      ws.send(JSON.stringify({ type: 'focus', focused: true }));
      fitAndResize();
      term.focus();
    };
    ws.onmessage = (ev) => {
      if (ptyWs !== ws) return;
      if (ev.data instanceof ArrayBuffer) {
        term.write(new Uint8Array(ev.data));
      } else if (typeof ev.data === 'string') {
        try {
          const msg = JSON.parse(ev.data);
          if (msg.type === 'error') term.writeln(`\r\n\x1b[31m[error] ${msg.message}\x1b[0m`);
          if (msg.type === 'closed') term.writeln(`\r\n\x1b[2m[terminal closed]\x1b[0m`);
        } catch (_) {
          term.write(ev.data);
        }
      }
    };
    renderTabs();
  }

  function renderTabs() {
    tabCountEl.textContent = String(terminals.length);
    sidebarTabsEl.innerHTML = '';
    mobileTabsEl.innerHTML = '';

    for (const t of terminals) {
      const state = tabState(t);
      const label = t.name || t.address;
      const isActive = t.address === activeId;

      const btn = document.createElement('div');
      btn.className = `tab-item${isActive ? ' active' : ''}`;
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

      const closeBtn = document.createElement('button');
      closeBtn.className = 'tab-close';
      closeBtn.title = 'Close tab';
      closeBtn.setAttribute('aria-label', `Close ${label}`);
      closeBtn.textContent = '✕';
      closeBtn.addEventListener('click', async (e) => {
        e.stopPropagation();
        await fetch(`/api/tabs/${encodeURIComponent(t.address)}`, { method: 'DELETE' });
      });

      btn.append(dot, info, closeBtn);
      btn.addEventListener('click', () => {
        if (activeId !== t.address) connectPty(t.address);
      });
      sidebarTabsEl.appendChild(btn);

      // Mobile chip
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
    }

    const mPlus = document.createElement('button');
    mPlus.className = 'm-tab';
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
      approvalTabEl.textContent = pending.tab || pending.risk || 'sysop';
      approvalTextEl.textContent = pending.text || 'Pending action';
      mobileApprovalMsgEl.textContent = pending.text || 'Pending action';

      if (pending.deadline) {
        const now = Date.now() / 1000;
        const rem = Math.max(0, pending.deadline - now);
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
      return;
    }

    currentApproval = null;
    approvalCardEl.classList.add('hidden');
    mobileApprovalEl.classList.add('hidden');
    approvalBarEl.classList.add('hidden');
  }

  function renderSysop(sysop) {
    if (!sysop) return;
    const st = sysop.state || 'off';
    sysopDotEl.dataset.state = st;
    sysopStateEl.textContent = st;
    mobileSysopDotEl.dataset.state = st;
    mobileSysopStateEl.textContent = st;

    const running = st === 'working' || st === 'allow?' || st === 'sending' || st === 'queued';
    btnSysopStop.classList.toggle('hidden', !running);

    renderApprovalCard(sysop);

    sysopFeedEl.innerHTML = '';
    const steps = Array.isArray(sysop.steps) ? sysop.steps : [];
    if (!sysop.up) {
      const box = document.createElement('div');
      box.className = 'feed-empty';
      box.innerHTML = 'Sysop service is not running.<br>Install &amp; start it with:<br><code>swarmbox addon install sysop</code>';
      sysopFeedEl.appendChild(box);
    } else if (steps.length === 0) {
      const box = document.createElement('div');
      box.className = 'feed-empty';
      box.textContent = 'Sysop is ready. Type or speak a goal below to drive your terminals.';
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
    const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    const ws = new WebSocket(`${proto}//${location.host}/ws/events`);

    ws.onopen = () => {
      connPillEl.className = 'conn-pill ok';
      connTextEl.textContent = 'herdr-core live';
    };
    ws.onclose = () => {
      connPillEl.className = 'conn-pill err';
      connTextEl.textContent = 'reconnecting…';
      setTimeout(connectEvents, 1200);
    };
    ws.onmessage = (ev) => {
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
          else { activeId = null; renderTabs(); }
        } else {
          renderTabs();
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

  // -------------------------------------------------------------------------
  // Real voice addon integration (16 kHz mono 16-bit PCM WAV -> /voice/audio)
  // Falls back cleanly to Web Speech API if the voice addon is not installed.
  // -------------------------------------------------------------------------
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
      showVoiceNote('Install the voice addon (`swarmbox addon install voice`) for local Whisper speech.', 'warn', 6000);
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

  // Probe local swarmbox-voice service via /voice/health
  fetch('/voice/health', { credentials: 'same-origin', cache: 'no-store' })
    .then((r) => {
      if (r.ok) {
        voiceAddonAvailable = true;
        voiceHintEl.textContent = 'hold mic · whisper';
      } else {
        voiceHintEl.textContent = 'voice addon off';
      }
    })
    .catch(() => { voiceHintEl.textContent = ''; });

  // UI Wiring
  document.getElementById('btn-new-shell').addEventListener('click', () => spawnTab('shell'));
  document.getElementById('btn-new-agent').addEventListener('click', () => spawnTab('agent'));

  document.getElementById('btn-sidebar-close').addEventListener('click', () => {
    appEl.dataset.sidebarOpen = '0';
    requestAnimationFrame(fitAndResize);
  });
  document.getElementById('btn-sidebar-open').addEventListener('click', () => {
    appEl.dataset.sidebarOpen = '1';
    requestAnimationFrame(fitAndResize);
  });
  document.getElementById('btn-toggle-sysop').addEventListener('click', () => {
    appEl.dataset.sysopOpen = appEl.dataset.sysopOpen === '1' ? '0' : '1';
    requestAnimationFrame(fitAndResize);
  });
  document.getElementById('btn-sysop-close').addEventListener('click', () => {
    if (window.innerWidth <= 860) {
      appEl.dataset.mobileSysop = '0';
    } else {
      appEl.dataset.sysopOpen = '0';
      requestAnimationFrame(fitAndResize);
    }
  });
  document.getElementById('btn-mobile-sysop').addEventListener('click', () => {
    appEl.dataset.mobileSysop = appEl.dataset.mobileSysop === '1' ? '0' : '1';
  });

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
  });

  document.getElementById('btn-send-goal').addEventListener('click', () => sendGoal());
  goalInputEl.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendGoal();
    }
  });

  document.getElementById('btn-allow').addEventListener('click', () => handleApproval('allow'));
  document.getElementById('btn-cancel').addEventListener('click', () => handleApproval('cancel'));
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
