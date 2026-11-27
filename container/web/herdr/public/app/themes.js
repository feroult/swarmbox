// Web Studio themes (synchronized with cockpit via /api/theme) and live terminal appearance preferences.

import { state, dom, actions } from './state.js';

// Five curated themes synchronized with the cockpit via /api/theme (~/.config/swarmbox/herdr-web-theme).
// Default: Catppuccin Mocha.
export const DEFAULT_THEME = 'catppuccin';
export const THEMES = {
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

export const THEME_KEYS = Object.keys(THEMES);

export const LINE_HEIGHT_PRESETS = { compact: 1.15, studio: 1.26, airy: 1.38 };
export const CURSOR_STYLES = ['block', 'bar', 'underline'];
export const SCROLLBACK_OPTIONS = [1500, 3000, 6000, 10000];

state.currentThemeKey = DEFAULT_THEME;

state.fontOffset = (() => {
  try {
    const v = Number(localStorage.getItem('swarmbox-herdr-font-offset') || '0');
    return Number.isFinite(v) ? Math.max(-4, Math.min(8, v)) : 0;
  } catch (_) { return 0; }
})();

state.lineHeightPreset = (() => {
  try {
    const v = localStorage.getItem('swarmbox-herdr-lh');
    if (v && LINE_HEIGHT_PRESETS[v]) return v;
  } catch (_) {}
  return '';
})();

state.cursorStyle = (() => {
  try {
    const v = localStorage.getItem('swarmbox-herdr-cursor-style');
    if (CURSOR_STYLES.includes(v)) return v;
  } catch (_) {}
  return 'block';
})();

state.cursorBlink = (() => {
  try {
    const v = localStorage.getItem('swarmbox-herdr-cursor-blink');
    if (v === '0') return false;
    if (v === '1') return true;
  } catch (_) {}
  return true;
})();

state.scrollbackLines = (() => {
  try {
    const v = Number(localStorage.getItem('swarmbox-herdr-scrollback') || '3000');
    if (SCROLLBACK_OPTIONS.includes(v)) return v;
  } catch (_) {}
  return 3000;
})();

export const savedTheme = (() => {
  try { return localStorage.getItem('swarmbox-herdr-theme') || DEFAULT_THEME; } catch (_) { return DEFAULT_THEME; }
})();

export function effectiveLineHeightKey() {
  if (state.lineHeightPreset && LINE_HEIGHT_PRESETS[state.lineHeightPreset]) return state.lineHeightPreset;
  return window.innerWidth <= 860 ? 'compact' : 'studio';
}

export function computeLineHeight() {
  return LINE_HEIGHT_PRESETS[effectiveLineHeightKey()] || 1.26;
}

// Dynamic column-aware font sizing:
// Desktop defaults to a comfortable 16.5px (adjustable via Settings or Alt+-/=/0).
// On phones (<= 860px), pick the exact font size so >= 51 columns fit upright (keeping the
// single-line Starship prompt completely unbroken).
export function computeFontSize() {
  const w = window.innerWidth;
  let base;
  if (w > 860) {
    base = 16.5;
  } else {
    const usable = Math.max(240, ((dom.termWrapEl && dom.termWrapEl.clientWidth) || w) - 18);
    const targetCols = w < window.innerHeight ? 51 : 94;
    const raw = usable / (targetCols * 0.605);
    base = Math.max(10.5, Math.min(15, Math.round(raw * 2) / 2));
  }
  return Math.max(9.5, Math.min(26, Math.round((base + state.fontOffset) * 2) / 2));
}

export function formatFontPx(sz) {
  return Number.isInteger(sz) ? `${sz}px` : `${sz.toFixed(1)}px`;
}

export function syncAppearanceControls() {
  if (!state.settingsOpen || state.settingsSection !== 'appearance' || !dom.settingsBodyEl) return;
  const sz = computeFontSize();
  const valEl = dom.settingsBodyEl.querySelector('#s-font-val');
  if (valEl) valEl.textContent = formatFontPx(sz);
  const rangeEl = dom.settingsBodyEl.querySelector('#s-font-range');
  if (rangeEl) rangeEl.value = String(state.fontOffset);
  const prevEl = dom.settingsBodyEl.querySelector('#s-font-preview');
  if (prevEl) {
    prevEl.style.fontSize = `${Math.min(22, Math.max(11, sz))}px`;
    prevEl.style.lineHeight = String(computeLineHeight());
  }
  dom.settingsBodyEl.querySelectorAll('.theme-card').forEach((el) => {
    el.classList.toggle('active', el.dataset.theme === state.currentThemeKey);
  });
}

export function setFontOffset(next) {
  state.fontOffset = Math.max(-4, Math.min(8, Math.round(next * 2) / 2));
  try { localStorage.setItem('swarmbox-herdr-font-offset', String(state.fontOffset)); } catch (_) {}
  if (typeof actions.fitAndResize === 'function') actions.fitAndResize();
  syncAppearanceControls();
}

export function adjustFontOffset(delta) {
  setFontOffset(delta === 0 ? 0 : state.fontOffset + delta);
  if (typeof actions.focusTerminalIfDesktop === 'function') actions.focusTerminalIfDesktop();
}

export function applyTerminalPrefs() {
  const lh = computeLineHeight();
  for (const sess of state.tabSessions.values()) {
    sess.term.options.lineHeight = lh;
    sess.term.options.cursorStyle = state.cursorStyle;
    sess.term.options.cursorBlink = state.cursorBlink;
    sess.term.options.scrollback = state.scrollbackLines;
  }
  if (typeof actions.fitAndResize === 'function') actions.fitAndResize();
  syncAppearanceControls();
}

export function applyTheme(name, persist = false) {
  const key = THEMES[name] ? name : DEFAULT_THEME;
  state.currentThemeKey = key;
  const t = THEMES[key];
  for (const [k, v] of Object.entries(t.css)) {
    document.documentElement.style.setProperty(k, v);
  }
  for (const sess of state.tabSessions.values()) {
    sess.term.options.theme = t.xterm;
  }
  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta) meta.setAttribute('content', t.css['--bg']);
  if (dom.themeSwatchEl) {
    dom.themeSwatchEl.style.background = t.css['--accent'];
    dom.themeSwatchEl.style.boxShadow = `0 0 8px ${t.css['--accent-glow']}`;
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
