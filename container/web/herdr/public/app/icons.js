// SVG icons, pixel sprites, tab metadata formatters, and display path helpers.

import { state, resolveAgentName } from './state.js';

export const PIXEL_SVG = {
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

  // A generic agent (an agent whose addon has no icon.svg): a neutral pixel robot
  agent: '<svg viewBox="0 0 16 16" shape-rendering="crispEdges">' +
    '<rect x="7" y="0" width="2" height="1" fill="#a1a1aa"/>' +
    '<rect x="7" y="1" width="2" height="1" fill="#71717a"/>' +
    '<rect x="3" y="2" width="10" height="8" fill="#3f3f46"/>' +
    '<rect x="4" y="3" width="8" height="6" fill="#18181b"/>' +
    '<rect x="5" y="5" width="2" height="2" fill="#e4e4e7"/>' +
    '<rect x="9" y="5" width="2" height="2" fill="#e4e4e7"/>' +
    '<rect x="6" y="8" width="4" height="1" fill="#71717a"/>' +
    '<rect x="7" y="10" width="2" height="1" fill="#52525b"/>' +
    '<rect x="4" y="11" width="8" height="4" fill="#3f3f46"/>' +
    '<rect x="7" y="12" width="2" height="1" fill="#a1a1aa"/>' +
    '<rect x="4" y="15" width="2" height="1" fill="#27272a"/>' +
    '<rect x="10" y="15" width="2" height="1" fill="#27272a"/>' +
    '</svg>',
};

export const SVG16 = (d) => `<svg viewBox="0 0 16 16" width="11" height="11" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${d}</svg>`;
export const ICO_BRANCH_SVG = '<svg viewBox="0 0 16 16" width="11" height="11" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="4.5" cy="3.5" r="1.8"/><circle cx="11.5" cy="5.5" r="1.8"/><circle cx="4.5" cy="12.5" r="1.8"/><path d="M4.5 5.3v5.4M11.5 7.3c0 2.5-7 1.8-7 3.4"/></svg>';
export const ICO_BOOK_SVG = '<svg viewBox="0 0 16 16" width="11" height="11" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M2.5 3.2c1.9-.6 3.9-.4 5.5.8 1.6-1.2 3.6-1.4 5.5-.8v9.3c-1.9-.6-3.9-.4-5.5.8-1.6-1.2-3.6-1.4-5.5-.8Z"/><path d="M8 4v9.3"/></svg>';
export const ICO_CLOCK_SVG = SVG16('<circle cx="8" cy="8" r="5.8"/><path d="M8 4.6V8l2.3 1.5"/>');
export const ICO_BOLT_SVG = SVG16('<path d="M9 1.8 3.6 9h4l-1 5.2L12.4 7h-4Z"/>');
export const ICO_BELL_SVG = SVG16('<path d="M4.2 11.2V7.4a3.8 3.8 0 0 1 7.6 0v3.8l1.2 1.3H3Z"/><path d="M6.6 13.6a1.5 1.5 0 0 0 2.8 0"/>');
export const ICO_PENCIL_SVG = '<svg viewBox="0 0 16 16" width="11" height="11" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M11.2 2.4a1.6 1.6 0 0 1 2.3 2.3L5.6 12.6 2.5 13.5l.9-3.1 7.8-8Z"/></svg>';
export const ICO_FOLDER_SVG = '<svg viewBox="0 0 16 16" width="11" height="11" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M1.8 4.2c0-.8.6-1.4 1.4-1.4h3l1.5 1.7h5.1c.8 0 1.4.6 1.4 1.4v6.1c0 .8-.6 1.4-1.4 1.4H3.2c-.8 0-1.4-.6-1.4-1.4Z"/></svg>';
export const ICO_CHECK_SVG = '<svg viewBox="0 0 16 16" width="11" height="11" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 8.5l3.2 3L13 4.5"/></svg>';
export const ICO_SEARCH_SVG = '<svg viewBox="0 0 16 16" width="12" height="12" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="7" cy="7" r="4.5"/><path d="M10.5 10.5L14 14"/></svg>';
export const ICO_PLUS_SM_SVG = '<svg viewBox="0 0 16 16" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M8 3.5v9M3.5 8h9"/></svg>';
export const ICO_REFRESH_SVG = '<svg viewBox="0 0 16 16" width="13" height="13" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M13.2 8a5.2 5.2 0 1 1-1.3-3.4"/><path d="M13.2 2.8v2.7h-2.7"/></svg>';

export const REPO_GROUP_ACCENTS = ['#c4b5fd', '#6ee7b7', '#8ad7e6', '#f4a27f', '#fbbf24', '#f472b6'];

export function shortDisplayPath(p) {
  const s = String(p || '');
  const wtMatch = s.match(/\/\.local\/share\/swarmbox\/worktrees\/([^/]+)\/[^/]+(\/.*)?$/);
  if (wtMatch) return `~/${wtMatch[1]}${wtMatch[2] || ''}`;
  if (state.serverHomeDir && (s === state.serverHomeDir || s.startsWith(state.serverHomeDir + '/'))) {
    return '~' + s.slice(state.serverHomeDir.length);
  }
  return s.startsWith('/home/agent') ? '~' + s.slice('/home/agent'.length) : s;
}

export function tabAgentBadge(t) {
  if (!t) return '';
  return resolveAgentName(t.status && t.status.app) || resolveAgentName(t.foreground && t.foreground.name);
}

export function cleanStatusText(raw) {
  return String(raw || '')
    .replace(/\*\*([^*]+)\*\*/g, '$1')
    .replace(/`([^`]+)`/g, '$1')
    .replace(/\s+/g, ' ')
    .trim();
}

export function tabTitleParts(t) {
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
  if (fg && !state.agentReg.shellNames.has(fgLow) && fgLow !== pill) {
    return { title: fg, pill };
  }

  return { title: rawName || 'shell', pill };
}

export function tabDisplayName(t) {
  return tabTitleParts(t).title;
}

export function tabState(t) {
  return (t && t.status && t.status.state) || 'idle';
}

export function tabSubtitle(t) {
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

// The agent a tab runs: live signals, then the swarmbox.agent label while the tab is not a bare login shell
// (its argv is longer than `bash -l`, or its foreground is a program that is no shell). Never the tab name.
export function tabAgentKind(t) {
  const b = tabAgentBadge(t);
  if (b) return b;
  const lblAg = resolveAgentName(t && t.labels && t.labels['swarmbox.agent']);
  if (lblAg) {
    const argv = Array.isArray(t && t.argv) ? t.argv : [];
    const fg = String((t && t.foreground && t.foreground.name) || '').toLowerCase();
    const bareShell = argv.length <= 2 && (!fg || state.agentReg.shellNames.has(fg));
    if (!bareShell) return lblAg;
  }
  return '';
}

// The icon of a kind: shell, sysop, an agent (its own icon, else the generic one) or `agent` (the generic one)
export function pixelIconHtml(kind) {
  if (PIXEL_SVG[kind]) return PIXEL_SVG[kind];
  const a = state.agentReg.byId.get(kind);
  if (a) return a.icon_svg || PIXEL_SVG.agent;
  return PIXEL_SVG.shell;
}

export function makeMiniPixelIcon(kind) {
  const sp = document.createElement('span');
  sp.className = 'px-mini';
  sp.innerHTML = pixelIconHtml(kind);
  return sp;
}

export function stateBadgeText(st, status) {
  if (st === 'working') {
    return status && typeof status.progress === 'number' ? `WORKING ${status.progress}%` : 'WORKING';
  }
  if (st === 'blocked') return 'BLOCKED';
  if (st === 'done') return 'DONE';
  if (st === 'error') return 'ERROR';
  return 'IDLE';
}

export function stateCornerGlyph(st) {
  if (st === 'working') return '⚡';
  if (st === 'blocked') return '!';
  if (st === 'done') return '✓';
  if (st === 'error') return '✕';
  return 'Z';
}
