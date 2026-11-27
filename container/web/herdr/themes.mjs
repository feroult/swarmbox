// Theme registry (synchronized between Web UI and Terminal Cockpit).

import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const HOME = process.env.HOME || os.homedir() || '/home/agent';

function resolveXdg(xdgVar, fallback, sub) {
  const base = typeof xdgVar === 'string' && xdgVar.startsWith('/') ? xdgVar.replace(/\/+$/, '') : fallback;
  return path.join(base, sub);
}

const SB_CONFIG_DIR = resolveXdg(process.env.XDG_CONFIG_HOME, path.join(HOME, '.config'), 'swarmbox');

export const DEFAULT_THEME = 'catppuccin';
export const THEME_ORDER = ['catppuccin', 'purple-glow', 'tokyo-night', 'nord', 'rose-pine'];

export const HERDR_THEMES = {
  'purple-glow': {
    label: 'Purple Glow',
    cockpit: {
      bg: '#0c0b10',
      surface: '#12101a',
      surface2: '#1b1726',
      band: '#27222f',
      border: '#352b4a',
      borderStrong: '#6d28d9',
      text: '#f4f4f5',
      muted: '#a1a1aa',
      dim: '#71717a',
      accent: '#a78bfa',
      accentBright: '#c4b5fd',
      accentDeep: '#6d28d9',
      green: '#4ade80',
      amber: '#fbbf24',
      red: '#ff6b78',
      termFg: '#d4d4d8',
      ansi16: [
        '#1c1a24', '#e5484d', '#3dba7a', '#d9a441', '#8b5cf6', '#d946ef', '#5eb5c9', '#d4d4d8',
        '#71717a', '#ff6b78', '#4ade80', '#fbbf24', '#a78bfa', '#e879f9', '#8ad7e6', '#fafafa',
      ],
    },
  },
  catppuccin: {
    label: 'Catppuccin',
    cockpit: {
      bg: '#11111b',
      surface: '#181825',
      surface2: '#1e1e2e',
      band: '#29293e',
      border: '#313244',
      borderStrong: '#8839ef',
      text: '#cdd6f4',
      muted: '#a6adc8',
      dim: '#6c7086',
      accent: '#cba6f7',
      accentBright: '#f5c2e7',
      accentDeep: '#8839ef',
      green: '#a6e3a1',
      amber: '#f9e2af',
      red: '#f38ba8',
      termFg: '#cdd6f4',
      ansi16: [
        '#45475a', '#f38ba8', '#a6e3a1', '#f9e2af', '#89b4fa', '#f5c2e7', '#94e2d5', '#bac2de',
        '#585b70', '#f38ba8', '#a6e3a1', '#f9e2af', '#89b4fa', '#f5c2e7', '#94e2d5', '#cdd6f4',
      ],
    },
  },
  'tokyo-night': {
    label: 'Tokyo Night',
    cockpit: {
      bg: '#16161e',
      surface: '#1a1b26',
      surface2: '#24283b',
      band: '#282d42',
      border: '#2f3549',
      borderStrong: '#3d59a1',
      text: '#c0caf5',
      muted: '#9aa5ce',
      dim: '#565f89',
      accent: '#7aa2f7',
      accentBright: '#bb9af7',
      accentDeep: '#3d59a1',
      green: '#9ece6a',
      amber: '#e0af68',
      red: '#f7768e',
      termFg: '#c0caf5',
      ansi16: [
        '#15161e', '#f7768e', '#9ece6a', '#e0af68', '#7aa2f7', '#bb9af7', '#7dcfff', '#a9b1d6',
        '#414868', '#f7768e', '#9ece6a', '#e0af68', '#7aa2f7', '#bb9af7', '#7dcfff', '#c0caf5',
      ],
    },
  },
  nord: {
    label: 'Nord',
    cockpit: {
      bg: '#242933',
      surface: '#2e3440',
      surface2: '#3b4252',
      band: '#3e4759',
      border: '#434c5e',
      borderStrong: '#5e81ac',
      text: '#eceff4',
      muted: '#d8dee9',
      dim: '#8190a8',
      accent: '#88c0d0',
      accentBright: '#8fbcbb',
      accentDeep: '#5e81ac',
      green: '#a3be8c',
      amber: '#ebcb8b',
      red: '#bf616a',
      termFg: '#eceff4',
      ansi16: [
        '#3b4252', '#bf616a', '#a3be8c', '#ebcb8b', '#81a1c1', '#b48ead', '#88c0d0', '#e5e9f0',
        '#4c566a', '#bf616a', '#a3be8c', '#ebcb8b', '#81a1c1', '#b48ead', '#8fbcbb', '#eceff4',
      ],
    },
  },
  'rose-pine': {
    label: 'Rosé Pine',
    cockpit: {
      bg: '#191724',
      surface: '#1f1d2e',
      surface2: '#26233a',
      band: '#2e2a45',
      border: '#403d52',
      borderStrong: '#907aa9',
      text: '#e0def4',
      muted: '#908caa',
      dim: '#6e6a86',
      accent: '#c4a7e7',
      accentBright: '#ebbcba',
      accentDeep: '#907aa9',
      green: '#9ccfd8',
      amber: '#f6c177',
      red: '#eb6f92',
      termFg: '#e0def4',
      ansi16: [
        '#26233a', '#eb6f92', '#31748f', '#f6c177', '#9ccfd8', '#c4a7e7', '#ebbcba', '#e0def4',
        '#6e6a86', '#eb6f92', '#31748f', '#f6c177', '#9ccfd8', '#c4a7e7', '#ebbcba', '#e0def4',
      ],
    },
  },
};

export const THEME_FILE = path.join(SB_CONFIG_DIR, 'herdr-web-theme');

export function readSavedTheme() {
  try {
    const t = fs.readFileSync(THEME_FILE, 'utf8').trim();
    if (HERDR_THEMES[t]) return t;
  } catch (_) {}
  return DEFAULT_THEME;
}

export function saveTheme(themeName) {
  if (!HERDR_THEMES[themeName]) return false;
  try {
    fs.mkdirSync(SB_CONFIG_DIR, { recursive: true });
    fs.writeFileSync(THEME_FILE, themeName + '\n', 'utf8');
  } catch (_) {}
  return true;
}
