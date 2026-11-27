// First-class Settings panel (Appearance + SwarmBox / Sysop / Voice / Addons & System configs),
// staged host config bar, live addon actions, and About popover.

import { state, dom, actions, refreshAgentRegistry } from './state.js';
import {
  DEFAULT_THEME,
  THEMES,
  THEME_KEYS,
  SCROLLBACK_OPTIONS,
  effectiveLineHeightKey,
  computeLineHeight,
  computeFontSize,
  formatFontPx,
  setFontOffset,
  applyTerminalPrefs,
  applyTheme,
} from './themes.js';
import { openPopover } from './ui-chrome.js';

export const SECTION_META = {
  appearance: { title: 'Appearance', sub: 'Themes, typography & terminal canvas (applies live)' },
  box: { title: 'SwarmBox', sub: 'Container runtime, multiplexer & host integration' },
  sysop: { title: 'Sysop', sub: 'Autonomous operator policy, model & safety guardrails' },
  voice: { title: 'Voice', sub: 'Local Whisper speech-to-text & microphone routing' },
  system: { title: 'Addons & System', sub: 'Installed addons, MCP servers, SSH identity & shortcuts' },
};

export function el(tag, attrs = null, children = []) {
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

export function shellQuote(val) {
  const s = String(val ?? '');
  if (s === '') return '""';
  if (/^[A-Za-z0-9_./:@+-]+$/.test(s)) return s;
  return "'" + s.replace(/'/g, "'\\''") + "'";
}

export function currentHostField(group, key) {
  if (!state.boxConfig) return { value: '', default: '', custom: false };
  const src = group === 'box'
    ? state.boxConfig.box
    : group === 'sysop'
      ? (state.boxConfig.sysop && state.boxConfig.sysop.settings)
      : (state.boxConfig.voice && state.boxConfig.voice.settings);
  return (src && src[key]) || { value: '', default: '', custom: false };
}

export function effectiveHostValue(group, key) {
  if (state.stagedHostConfig.has(key)) return state.stagedHostConfig.get(key);
  return currentHostField(group, key).value;
}

export function stageHostSetting(group, key, nextVal) {
  const val = String(nextVal ?? '').trim();
  const live = currentHostField(group, key).value;
  if (val === live) state.stagedHostConfig.delete(key);
  else state.stagedHostConfig.set(key, val);
  syncHostBar();
}

export function buildHostApplyCommand() {
  if (state.stagedHostConfig.size === 0) return '';
  const parts = [];
  for (const [k, v] of state.stagedHostConfig.entries()) {
    parts.push(`swarmbox config set ${k} ${shellQuote(v)}`);
  }
  parts.push('swarmbox reset');
  return parts.join(' && \\\n  ');
}

export function syncHostBar() {
  if (!dom.settingsHostBarEl) return;
  const n = state.stagedHostConfig.size;
  dom.settingsHostBarEl.classList.toggle('hidden', n === 0);
  if (n === 0) return;
  dom.hostBarCountEl.textContent = n === 1 ? '1 pending change' : `${n} pending changes`;
  dom.hostBarCmdEl.textContent = buildHostApplyCommand();
}

export async function copyTextWithFeedback(text, btn, idleLabel) {
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

// About (the SWARMBOX title, or the version at the foot of Settings): the version and the commit the image was built from
const REPO_URL = 'https://github.com/feroult/swarmbox';
export function splitCommit(raw) {
  const m = /^([0-9a-f]{7,40})(-dirty)?$/.exec(String(raw || '').trim());
  return m ? { sha: m[1], dirty: Boolean(m[2]) } : null;
}
export function aboutVersionLine(cfg) {
  const c = splitCommit(cfg && cfg.commit);
  const v = `SwarmBox v${(cfg && cfg.version) || 'dev'}`;
  return c ? `${v} (${c.sha.slice(0, 7)}${c.dirty ? '-dirty' : ''})` : v;
}
export async function openAboutPopover() {
  if (!state.boxConfig) await loadBoxConfig();
  const cfg = state.boxConfig || {};
  const version = cfg.version || 'dev';
  const c = splitCommit(cfg.commit);
  const isRelease = /^\d+\.\d+\.\d+/.test(version);
  const frag = document.createDocumentFragment();
  const head = el('div', { class: 'spop-head' }, [
    el('span', { class: 'about-title' }, [el('span', { class: 'brand-mark', 'aria-hidden': 'true' }), el('span', { text: 'SWARMBOX' })]),
  ]);
  const sub = el('div', { class: 'spop-sub', text: 'Persistent box for AI coding agents.' });
  const commitNode = c
    ? el('span', {}, [
      c.dirty
        ? el('span', { text: c.sha.slice(0, 12), title: c.sha })
        : el('a', { href: `${REPO_URL}/commit/${c.sha}`, target: '_blank', rel: 'noopener', text: c.sha.slice(0, 12), title: c.sha }),
      c.dirty ? el('span', { class: 'about-dirty', text: 'dirty', title: 'built from a checkout with uncommitted changes' }) : null,
    ])
    : el('span', { class: 'about-k', text: 'unknown' });
  const grid = el('div', { class: 'about-grid' }, [
    el('span', { class: 'about-k', text: 'Version' }),
    el('span', { class: 'about-v' }, [isRelease
      ? el('a', { href: `${REPO_URL}/releases/tag/v${version}`, target: '_blank', rel: 'noopener', text: `v${version}` })
      : el('span', { text: version })]),
    el('span', { class: 'about-k', text: 'Commit' }),
    el('span', { class: 'about-v' }, [commitNode]),
  ]);
  const line = aboutVersionLine(cfg);
  const copyBtn = el('button', { type: 'button', class: 'spop-link-btn', text: 'Copy version' });
  copyBtn.addEventListener('click', () => copyTextWithFeedback(line, copyBtn, 'Copy version'));
  const links = el('div', { class: 'spop-links' }, [
    el('span', { class: 'spop-links-group' }, [
      el('a', { class: 'spop-link-btn', href: REPO_URL, target: '_blank', rel: 'noopener', text: 'GitHub' }),
      el('a', { class: 'spop-link-btn', href: `${REPO_URL}/releases`, target: '_blank', rel: 'noopener', text: 'Releases' }),
    ]),
    copyBtn,
  ]);
  frag.append(head, sub, grid, links);
  openPopover(frag);
}

export async function loadBoxConfig(force = false) {
  if (state.boxConfigLoading && !force) return;
  state.boxConfigLoading = true;
  state.boxConfigError = '';
  try {
    const r = await fetch('/api/config', { cache: 'no-store' });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    state.boxConfig = await r.json();
    await refreshAgentRegistry();   // the Default Agent choices and the placeholders come from it
    if (state.boxConfig && state.boxConfig.session_prefs) state.sessionPrefs = state.boxConfig.session_prefs;
    if (state.boxConfig && Array.isArray(state.boxConfig.installed_agents)) state.installedAgents = state.boxConfig.installed_agents;
    if (dom.settingsVersionEl && state.boxConfig.version) {
      dom.settingsVersionEl.textContent = aboutVersionLine(state.boxConfig);
    }
  } catch (err) {
    state.boxConfigError = err.message || 'Could not load box config';
  } finally {
    state.boxConfigLoading = false;
    if (state.settingsOpen && state.settingsSection !== 'appearance') renderSettingsBody();
  }
}

export function makeGroup(label, rightNode, contentNode) {
  return el('section', { class: 's-group' }, [
    el('div', { class: 's-group-head' }, [
      el('span', { class: 's-group-label', text: label }),
      rightNode || null,
    ]),
    contentNode,
  ]);
}

export function makeSettingRow({ title, keyBadge, desc, badge, control, stacked = false }) {
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

export function makeSegmented(options, current, onSelect) {
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

export function makeSwitch(checked, ariaLabel, onToggle) {
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

export function makeHostFieldBadge(group, key) {
  if (state.stagedHostConfig.has(key)) return { text: 'edited', tone: '' };
  const f = currentHostField(group, key);
  if (f.custom) return { text: 'custom', tone: 'ok' };
  return null;
}

export function makeHostSelectRow(group, key, { title, desc, options }) {
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

export function makeHostToggleRow(group, key, { title, desc }) {
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

export function makeHostInputRow(group, key, { title, desc, placeholder = '', type = 'text', wide = false }) {
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

export function renderAppearanceSection() {
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
      class: `theme-card${key === state.currentThemeKey ? ' active' : ''}`,
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
    el('span', { class: 's-sync-note' }, [
      el('i', { class: 's-sync-dot', 'aria-hidden': 'true' }),
      el('span', { text: 'Synced with Cockpit' }),
    ]),
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
    value: String(state.fontOffset),
    'aria-label': 'Terminal font size offset',
    onInput: (e) => setFontOffset(Number(e.target.value)),
  });
  const stepper = el('div', { class: 's-stepper' }, [
    el('button', { type: 'button', class: 's-step-btn', text: '−', title: 'Smaller (Alt+-)', onClick: () => setFontOffset(state.fontOffset - 0.5) }),
    el('button', { id: 's-font-val', type: 'button', class: 's-step-val', text: formatFontPx(sz), title: 'Reset font size (Alt+0)', onClick: () => setFontOffset(0) }),
    el('button', { type: 'button', class: 's-step-btn', text: '+', title: 'Larger (Alt+=)', onClick: () => setFontOffset(state.fontOffset + 0.5) }),
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
    el('span', { class: 'fp-dim', text: window.innerWidth <= 860 ? 'JetBrains Mono' : 'JetBrains Mono + Nerd Font glyphs' }),
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
        state.lineHeightPreset = val;
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
      state.fontOffset = 0;
      state.lineHeightPreset = '';
      state.cursorStyle = 'block';
      state.cursorBlink = true;
      state.scrollbackLines = 3000;
      try {
        localStorage.removeItem('swarmbox-herdr-font-offset');
        localStorage.removeItem('swarmbox-herdr-lh');
        localStorage.removeItem('swarmbox-herdr-cursor-style');
        localStorage.removeItem('swarmbox-herdr-cursor-blink');
        localStorage.removeItem('swarmbox-herdr-scrollback');
      } catch (_) {}
      applyTheme(DEFAULT_THEME, true);
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
          { value: 'underline', label: 'Underline' },
        ],
        state.cursorStyle,
        (val) => {
          state.cursorStyle = val;
          try { localStorage.setItem('swarmbox-herdr-cursor-style', val); } catch (_) {}
          applyTerminalPrefs();
          renderSettingsBody();
        },
      ),
    }),
    makeSettingRow({
      title: 'Cursor Blink',
      desc: 'Pulse the terminal cursor when focused.',
      control: makeSwitch(state.cursorBlink, 'Cursor blink', (next) => {
        state.cursorBlink = next;
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
        state.scrollbackLines,
        (val) => {
          state.scrollbackLines = Number(val);
          try { localStorage.setItem('swarmbox-herdr-scrollback', String(state.scrollbackLines)); } catch (_) {}
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
  if (state.boxConfigError) {
    return el('div', { class: 's-note' }, [
      el('span', { class: 'status-dot', 'data-state': 'error' }),
      el('span', { text: `Could not read box config (${state.boxConfigError}).` }),
      el('button', { type: 'button', class: 'sbtn-ghost', text: 'Retry', onClick: () => loadBoxConfig(true) }),
    ]);
  }
  return el('div', { class: 's-note', text: 'Loading live SwarmBox configuration…' });
}

export function renderBoxSection() {
  if (!state.boxConfig) return renderLoadingOrError();
  const frag = document.createDocumentFragment();
  const healthCount = Array.isArray(state.boxConfig.health) ? state.boxConfig.health.length : 0;

  const stats = el('div', { class: 's-stat-grid' }, [
    el('div', { class: 's-stat is-link', role: 'button', tabindex: '0', title: 'About SwarmBox', onclick: () => openAboutPopover(),
      onkeydown: (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); openAboutPopover(); } } }, [
      el('span', { class: 's-stat-k', text: 'Version' }),
      el('span', { class: 's-stat-v', text: aboutVersionLine(state.boxConfig).replace(/^SwarmBox /, '') }),
    ]),
    el('div', { class: 's-stat' }, [
      el('span', { class: 's-stat-k', text: 'Multiplexer' }),
      el('span', { class: 's-stat-v', text: 'herdr' }),
    ]),
    el('div', { class: 's-stat' }, [
      el('span', { class: 's-stat-k', text: 'Health' }),
      healthCount === 0
        ? el('span', { class: 's-stat-v' }, [el('span', { class: 's-health-ok', text: '✓' }), el('span', { text: ' All green' })])
        : el('span', { class: 's-stat-v', text: `${healthCount} notice${healthCount > 1 ? 's' : ''}` }),
    ]),
  ]);
  frag.appendChild(makeGroup('Environment Summary', el('span', { class: 's-badge muted', text: `box: ${currentHostField('box', 'NAME').value}` }), stats));

  if (healthCount > 0) {
    frag.appendChild(el('div', { class: 's-note' }, [
      el('span', { class: 'status-dot', 'data-state': 'blocked' }),
      el('span', { text: state.boxConfig.health.join(' · ') }),
    ]));
  }

  const coreCard = el('div', { class: 's-card' }, [
    makeHostSelectRow('box', 'AGENT', {
      title: 'Default Agent',
      desc: 'Agent launched automatically when running swarmbox.',
      options: [{ value: '', label: 'None (interactive shell)' }]
        .concat(state.agentReg.list.map((a) => ({ value: a.id, label: `${a.label || a.id} (${a.cmd || a.id})` }))),
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

  const sessPrefs = (state.boxConfig && state.boxConfig.session_prefs) || state.sessionPrefs;
  const saveSessPrefs = async (patch) => {
    const r = await fetch('/api/pins/prefs', {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(patch),
    }).catch(() => null);
    if (r && r.ok) {
      const d = await r.json().catch(() => ({}));
      if (d.prefs) {
        state.sessionPrefs = d.prefs;
        if (state.boxConfig) state.boxConfig.session_prefs = d.prefs;
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

  const wtPrefs = (state.boxConfig && state.boxConfig.worktree_prefs) || state.worktreePrefs;
  const saveWtPrefs = async (patch) => {
    const r = await fetch('/api/worktrees/prefs', {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(patch),
    }).catch(() => null);
    if (r && r.ok) {
      const d = await r.json().catch(() => ({}));
      if (d.prefs) {
        state.worktreePrefs = d.prefs;
        if (state.boxConfig) state.boxConfig.worktree_prefs = d.prefs;
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
      placeholder: ['sysop', 'voice'].concat(state.agentReg.list.slice(0, 1).map((a) => a.addon || a.id)).join(','),
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

export function renderSysopSection() {
  if (!state.boxConfig) return renderLoadingOrError();
  const frag = document.createDocumentFragment();
  const up = Boolean(state.boxConfig.sysop && state.boxConfig.sysop.up);
  const st = (state.boxConfig.sysop && state.boxConfig.sysop.state) || 'off';

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
    { value: 'full-auto', title: 'full-auto', desc: 'Runs immediately without waiting for Allow (default).' },
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
    state.stagedHostConfig.has('sysop.autonomy') ? el('span', { class: 's-badge', text: 'edited' }) : null,
    policyGrid,
  ));

  // Notifications of the Sysop (its brain's notify): the browser shows them when the page is not in front
  const canNotify = 'Notification' in window;
  const perm = canNotify ? Notification.permission : 'unsupported';
  frag.appendChild(makeGroup('Notifications', null, el('div', { class: 's-card' }, [
    el('div', { class: 's-row' }, [
      el('div', { class: 's-row-info' }, [
        el('div', { class: 's-row-title', text: 'Browser notifications' }),
        el('div', {
          class: 's-row-desc',
          text: perm === 'granted' ? 'On: what the Sysop notifies you of shows even when this page is in the background.'
            : perm === 'denied' ? 'Blocked by the browser for this site: allow notifications in the site settings of the browser.'
              : perm === 'unsupported' ? 'This browser has no notifications (a page served over plain HTTP from another machine has none either).'
                : 'Let the Sysop reach you when this page is in the background (it always shows a toast in an open page).',
        }),
      ]),
      perm === 'default' ? el('button', {
        type: 'button',
        class: 'sbtn-primary',
        text: 'Allow',
        onClick: () => { Notification.requestPermission().then(() => renderSettingsBody()).catch(() => {}); },
      }) : null,
    ]),
  ])));

  // Brain, model & guardrails
  const guardCard = el('div', { class: 's-card' }, [
    makeHostToggleRow('sysop', 'sysop.autoname', {
      title: 'Automatic Tab Naming',
      desc: 'Name agent tabs after your requests in 1–3 short words, renaming as the goal gets clearer (never overwrites manual renames).',
    }),
    makeHostToggleRow('sysop', 'sysop.autocontext', {
      title: 'Repository Context',
      desc: 'Write a short orientation of each repository an agent works in, and start new agent sessions with it, so a new worktree needs no "understand the repo" (off removes them).',
    }),
    makeHostInputRow('sysop', 'sysop.brain', {
      title: 'Operator Brain',
      desc: 'CLI brain used to plan actions: auto (the brain an agent of the box declares), an agent name, or a command with {mcp_config}.',
      placeholder: 'auto',
    }),
    makeHostSelectRow('sysop', 'sysop.model', {
      title: 'Operator Model',
      desc: 'Model alias forwarded to the brain.',
      options: [
        { value: 'auto', label: "auto (the brain agent's default)" },
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
      desc: '0 = unlimited (use Stop). Set 1–500 to cap tool calls per goal.',
      type: 'number',
      placeholder: '0',
    }),
    makeHostInputRow('sysop', 'sysop.max_seconds', {
      title: 'Goal Time Budget (sec)',
      desc: '0 = unlimited (use Stop). Set 10–3600 to cap runtime per goal.',
      type: 'number',
      placeholder: '0',
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

export function renderVoiceSection() {
  if (!state.boxConfig) return renderLoadingOrError();
  const frag = document.createDocumentFragment();

  frag.appendChild(el('div', { class: 's-note' }, [
    el('span', { class: 'status-dot', 'data-state': state.voiceAddonAvailable ? 'done' : 'off' }),
    el('span', {
      text: state.voiceAddonAvailable
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

// Settings > Addons: install, update (a managed addon installed again) and remove (the install only: logins and settings stay).
const ADDON_ACTION_TEXT = {
  install: { busy: 'Installing…', done: 'Installed!', failed: 'Install failed' },
  update: { busy: 'Updating…', done: 'Updated!', failed: 'Update failed' },
  remove: { busy: 'Removing…', done: 'Removed', failed: 'Remove failed' },
};
const addonRemoveArmed = new Map();   // name -> timer: Remove asks for a second click before it runs

export async function addonActionLive(name, action) {
  if (state.installingAddons.has(name)) return;
  const text = ADDON_ACTION_TEXT[action];
  state.installingAddons.add(name);
  state.addonMessages.set(name, { tone: '', text: text.busy, action });
  renderSettingsBody();
  try {
    const r = await fetch(`/api/addons/${encodeURIComponent(name)}/${action}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: '{}',
    });
    const d = await r.json().catch(() => ({}));
    if (r.ok && d.ok) {
      if (d.config) state.boxConfig = d.config;
      state.addonMessages.set(name, { tone: 'ok', text: text.done });
    } else {
      state.addonMessages.set(name, { tone: 'warn', text: d.message || d.error || text.failed, title: d.message || '' });
    }
  } catch (err) {
    state.addonMessages.set(name, { tone: 'warn', text: err.message || 'Network error' });
  } finally {
    state.installingAddons.delete(name);
    renderSettingsBody();
  }
}

export function armAddonRemove(name) {
  if (addonRemoveArmed.has(name)) {
    clearTimeout(addonRemoveArmed.get(name));
    addonRemoveArmed.delete(name);
    addonActionLive(name, 'remove');
    return;
  }
  addonRemoveArmed.set(name, setTimeout(() => { addonRemoveArmed.delete(name); renderSettingsBody(); }, 4000));
  renderSettingsBody();
}

export function renderSystemSection() {
  if (!state.boxConfig) return renderLoadingOrError();
  const frag = document.createDocumentFragment();

  // 1. Addons list with live 1-click install
  const addons = Array.isArray(state.boxConfig.addons) ? state.boxConfig.addons : [];
  const addonList = el('div', { class: 's-card addon-list' });
  if (addons.length === 0) {
    addonList.appendChild(el('div', { class: 'addon-row' }, [
      el('div', { class: 'addon-desc', text: 'No addon manifests found in this image.' }),
    ]));
  } else {
    for (const a of addons) {
      const busy = state.installingAddons.has(a.name);
      const msg = state.addonMessages.get(a.name);
      const rowActions = [];
      if (msg && msg.text && !busy) {
        rowActions.push(el('span', { class: `s-badge ${msg.tone || 'muted'}`.trim(), text: msg.text.slice(0, 32), title: msg.title || null }));
      }
      if (busy) {
        rowActions.push(el('button', { type: 'button', class: 'sbtn-ghost', text: (msg && msg.text) || 'Working…', disabled: 'disabled' }));
      } else if (a.installed) {
        // the version its program reports for a floating install (`latest`); an addon that updates itself says so
        if (a.selfUpdate) {
          rowActions.push(el('span', { class: 's-badge muted', text: 'auto-update', title: 'Updates itself; the version is read from the program' }));
        }
        rowActions.push(el('span', {
          class: 's-badge ok',
          text: a.installedVersion ? `installed · ${a.installedVersion}` : 'installed',
          title: a.channel === 'latest' ? 'Installed from the latest release' : null,
        }));
        if (a.canUpdate) {
          rowActions.push(el('button', {
            type: 'button',
            class: 'sbtn-primary',
            text: 'Update',
            title: a.updateAvailable ? `Install ${a.manifestVersion}, the version this image names` : 'Install the newest release again',
            onClick: () => addonActionLive(a.name, 'update'),
          }));
        }
        if (a.canRemove) {
          const armed = addonRemoveArmed.has(a.name);
          rowActions.push(el('button', {
            type: 'button',
            class: armed ? 'sbtn-ghost sbtn-danger' : 'sbtn-ghost',
            text: armed ? 'Confirm' : 'Remove',
            title: 'Remove the install; logins and settings stay. Running sessions keep running.',
            onClick: () => armAddonRemove(a.name),
          }));
        }
      } else {
        rowActions.push(el('button', {
          type: 'button',
          class: 'sbtn-primary',
          text: 'Install',
          onClick: () => addonActionLive(a.name, 'install'),
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
        el('div', { class: 'addon-actions' }, rowActions),
      ]));
    }
  }
  frag.appendChild(makeGroup('Addons & Agents', el('span', { class: 's-badge muted', text: `${addons.filter((a) => a.installed).length}/${addons.length} active` }), addonList));

  // 2. MCP Servers
  const mcps = Array.isArray(state.boxConfig.mcp) ? state.boxConfig.mcp : [];
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
  const pubkey = state.boxConfig.pubkey || '';
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
    ['New agent (project picker)', 'Alt+A'],
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

export function renderSettingsBody() {
  if (!dom.settingsBodyEl) return;
  const meta = SECTION_META[state.settingsSection] || SECTION_META.appearance;
  if (dom.settingsTitleEl) dom.settingsTitleEl.textContent = meta.title;
  if (dom.settingsSubEl) dom.settingsSubEl.textContent = meta.sub;
  if (dom.settingsNavEl) {
    dom.settingsNavEl.querySelectorAll('.snav-item').forEach((btn) => {
      btn.classList.toggle('active', btn.dataset.section === state.settingsSection);
    });
  }
  dom.settingsBodyEl.innerHTML = '';
  if (state.settingsSection === 'appearance') dom.settingsBodyEl.appendChild(renderAppearanceSection());
  else if (state.settingsSection === 'box') dom.settingsBodyEl.appendChild(renderBoxSection());
  else if (state.settingsSection === 'sysop') dom.settingsBodyEl.appendChild(renderSysopSection());
  else if (state.settingsSection === 'voice') dom.settingsBodyEl.appendChild(renderVoiceSection());
  else dom.settingsBodyEl.appendChild(renderSystemSection());
  syncHostBar();
}

export function openSettings(section = null) {
  if (section && SECTION_META[section]) state.settingsSection = section;
  if (dom.appEl && dom.appEl.dataset.mobileSysop === '1') {
    if (typeof actions.setMobileSysop === 'function') actions.setMobileSysop(false);
  }
  state.settingsOpen = true;
  dom.settingsOverlayEl.classList.add('open');
  dom.settingsOverlayEl.setAttribute('aria-hidden', 'false');
  renderSettingsBody();
  loadBoxConfig(true);
}

export function closeSettings() {
  if (!state.settingsOpen) return;
  state.settingsOpen = false;
  dom.settingsOverlayEl.classList.remove('open');
  dom.settingsOverlayEl.setAttribute('aria-hidden', 'true');
  if (typeof actions.focusTerminalIfDesktop === 'function') actions.focusTerminalIfDesktop();
}

export function toggleSettings() {
  if (state.settingsOpen) closeSettings();
  else openSettings();
}

export function initSettings() {
  const btnAbout = document.getElementById('btn-about');
  if (btnAbout) btnAbout.addEventListener('click', () => { openAboutPopover(); });
  if (dom.settingsVersionEl) dom.settingsVersionEl.addEventListener('click', () => { openAboutPopover(); });
  const btnSidebarSettings = document.getElementById('btn-sidebar-settings');
  const btnTopbarSettings = document.getElementById('btn-topbar-settings');
  const btnSettingsClose = document.getElementById('btn-settings-close');
  const settingsHandleEl = document.getElementById('settings-handle');
  if (btnSidebarSettings) btnSidebarSettings.addEventListener('click', () => openSettings());
  if (btnTopbarSettings) btnTopbarSettings.addEventListener('click', () => openSettings());
  if (btnSettingsClose) btnSettingsClose.addEventListener('click', closeSettings);
  if (settingsHandleEl) settingsHandleEl.addEventListener('click', closeSettings);
  if (dom.settingsOverlayEl) {
    dom.settingsOverlayEl.addEventListener('click', (e) => {
      if (e.target === dom.settingsOverlayEl) closeSettings();
    });
  }
  if (dom.settingsNavEl) {
    dom.settingsNavEl.addEventListener('click', (e) => {
      const btn = e.target.closest('.snav-item[data-section]');
      if (!btn) return;
      state.settingsSection = btn.dataset.section;
      dom.settingsBodyEl.scrollTop = 0;
      renderSettingsBody();
      if (state.settingsSection !== 'appearance' && !state.boxConfig) loadBoxConfig(true);
    });
  }
  if (dom.btnHostCopy) {
    dom.btnHostCopy.addEventListener('click', () => {
      copyTextWithFeedback(buildHostApplyCommand(), dom.btnHostCopy, 'Copy command');
    });
  }
  if (dom.btnHostDiscard) {
    dom.btnHostDiscard.addEventListener('click', () => {
      state.stagedHostConfig.clear();
      syncHostBar();
      renderSettingsBody();
    });
  }
}
