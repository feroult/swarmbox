// Repository context (sysop.autocontext): on repository headers, agent cards, title bar, context popovers, and context viewer.

import { state, dom, actions, activeSession, agentLabel } from './state.js';
import { ICO_BOOK_SVG, ICO_CHECK_SVG, ICO_REFRESH_SVG, tabDisplayName, tabAgentKind } from './icons.js';
import { closeCardMenu, openPopover, closePopover, showTermToast } from './ui-chrome.js';

// A sysop digest call that started more than this long ago and never ended (the service was killed) is shown as without answer
export const AUTOCONTEXT_STALE_MS = 5 * 60 * 1000;
// A launcher waits 30 s at most: a waiting record older than this belongs to a launcher that is gone (Ctrl+C)
export const CTX_WAIT_MAX_MS = 45 * 1000;
export const CTX_REASONS = {
  new: 'first time in this repository',
  prefetch: 'a repository you use, when the box started',
  behind: 'its docs or many files changed since the last one',
  stale: 'the last one was over 6 hours old',
  changed: 'many files changed',
  manual: 'you asked',
};

let lastCtxTabsKey = '';
export function getLastCtxTabsKey() { return lastCtxTabsKey; }
// A rewrite asked from a context card or the viewer: until the snapshot says the repository is writing, it counts as busy here
const ctxPending = new Map();   // key -> when the rewrite was asked
const ctxJustDone = new Map();  // key -> when a rewrite seen here ended with a new context (a check for a few seconds)
let ctxPopKey = '';             // the repository whose context card is open
let ctxPopSig = '';
let ctxViewer = null;           // { kind: 'repo'|'session', key, tab, at } of the context in the file drawer
let sysopContextInitialized = false;

export const phase = (el, ms) => {
  if (el) el.style.animationDelay = `-${Date.now() % ms}ms`;
  return el;
};

export function fmtAgo(ms) {
  if (!ms) return '';
  const m = Math.floor((Date.now() - ms) / 60000);
  if (m < 1) return 'now';
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  return h < 24 ? `${h}h ago` : `${Math.floor(h / 24)}d ago`;
}

export function fmtClock(ms) {
  if (!ms) return '';
  const d = new Date(ms);
  const sameDay = new Date().toDateString() === d.toDateString();
  const hm = d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  return sameDay ? hm : `${d.toLocaleDateString([], { month: 'short', day: 'numeric' })} ${hm}`;
}

export function fmtAge(ms) {
  if (!ms) return '';
  const s = Math.max(0, Math.round((Date.now() - ms) / 1000));
  if (s < 60) return 'just now';
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  return `${Math.floor(s / 86400)} d ago`;
}

export function fmtShortAge(ms) {
  const s = Math.max(0, Math.round((Date.now() - (ms || 0)) / 1000));
  if (s < 60) return '<1m';
  if (s < 3600) return `${Math.floor(s / 60)}m`;
  if (s < 86400) return `${Math.floor(s / 3600)}h`;
  return `${Math.floor(s / 86400)}d`;
}

export function plural(n, word) {
  if (n === 1) return `${n} ${word}`;
  return `${n} ${/[^aeiou]y$/.test(word) ? `${word.slice(0, -1)}ies` : `${word}s`}`;
}

// "written 10:22 at 78ef75d · 9 files changed since" (what a session got, from the time it started)
export function ctxProvenance(s) {
  const parts = [];
  if (s.base_at) parts.push(`written ${fmtClock(s.base_at)}${s.base ? ` at ${s.base.slice(0, 7)}` : ''}`);
  if (s.base && s.commit && s.base.slice(0, 7) !== s.commit.slice(0, 7)) {
    parts.push(s.changes ? `${plural(s.changes, 'file')} changed since` : 'carried to this commit');
  } else if (s.base) {
    parts.push('for this exact commit');
  }
  return parts.join(' · ');
}

// The session of the agent running in `t` and what it started with (null for a shell, or a session the launcher did not report)
export function ctxSessionFor(t) {
  if (!t || !state.sysopContext || !state.sysopContext.on || !state.sysopContext.sessions) return null;
  if (!tabAgentKind(t)) return null;
  const s = state.sysopContext.sessions[t.address] || null;
  if (s && s.waiting && Date.now() - (s.at || 0) > CTX_WAIT_MAX_MS) return null;
  return s;
}

export function ctxRepoByKey(key) {
  const repos = (state.sysopContext && state.sysopContext.on && state.sysopContext.repos) || [];
  return repos.find((r) => r.key === key) || null;
}

// The context of a sidebar repository group: the repository its agents' sessions name, else the one of the same name
export function ctxRepoForGroup(grp) {
  if (!grp || !grp.isGit || !state.sysopContext || !state.sysopContext.on) return null;
  for (const t of grp.terms || []) {
    const s = state.sysopContext.sessions && state.sysopContext.sessions[t.address];
    const r = s && s.key ? ctxRepoByKey(s.key) : null;
    if (r) return r;
  }
  return ((state.sysopContext.repos || []).find((r) => r.repo === grp.name)) || null;
}

// The context the sysop has for a folder: the repository whose top holds it, else the one of its name
export function ctxRepoForCwd(cwd) {
  if (!cwd || !state.sysopContext || !state.sysopContext.on) return null;
  const repos = state.sysopContext.repos || [];
  const byTop = repos.filter((r) => r.top && (cwd === r.top || cwd.startsWith(`${r.top}/`)))
    .sort((a, b) => b.top.length - a.top.length)[0];
  if (byTop) return byTop;
  const base = cwd.replace(/\/+$/, '').split('/').pop();
  return repos.find((r) => r.repo === base) || null;
}

// The "Repository context" row of the New agent box (a Git folder, autocontext on): ticked, the session starts with the sysop's
// context of the repository (and waits for the first one, or for a new one when the last is far behind the folder's commit: the
// sysop's check says so); unticked, without it. null when autocontext is off.
export function makeNewAgentCtxRow(cwd, get, set) {
  if (!state.sysopContext || !state.sysopContext.on) return null;
  const repo = ctxRepoForCwd(cwd);
  let check = null;
  const row = document.createElement('button');
  row.type = 'button';
  row.className = 'newag-ctx';
  row.setAttribute('role', 'switch');
  const box = document.createElement('span');
  box.className = 'newag-ctx-box';
  const label = document.createElement('span');
  label.className = 'newag-ctx-label';
  label.innerHTML = `${ICO_BOOK_SVG}<span>Repository context</span>`;
  const meta = document.createElement('span');
  meta.className = 'newag-ctx-meta';
  const kbd = document.createElement('span');
  kbd.className = 'wt-kbd desktop-only';
  kbd.title = 'Press C to toggle the repository context';
  kbd.textContent = 'C';
  // far behind the folder's commit: a second line says that the session waits for a new context (the meta keeps its age)
  const note = document.createElement('span');
  note.className = 'newag-ctx-note';
  note.hidden = true;
  row.append(box, label, meta, kbd, note);
  const update = () => {
    const on = get();
    row.classList.toggle('is-on', on);
    row.setAttribute('aria-checked', on ? 'true' : 'false');
    const behind = Boolean(on && check && check.need === 'behind' && !(repo && repo.state === 'writing'));
    meta.textContent = !on ? 'starts without it'
      : repo && repo.state === 'writing' ? 'being written now'
        : behind ? `written ${fmtAge(check.at)}`
          : repo && repo.at ? `written ${fmtAge(repo.at)}`
            : 'written now, ~10 s';
    note.hidden = !behind;
    note.textContent = behind
      ? `${check.changes ? plural(check.changes, 'file') : 'Its docs'} changed since: rewritten before the agent starts, ~10 s`
      : '';
    row.classList.toggle('is-behind', behind);
    row.title = on
      ? 'The session starts with the sysop\'s orientation to this repository in its system prompt. Click (or C) to start without it.'
      : 'The session starts without the sysop\'s repository context. Click (or C) to start with it.';
  };
  row.addEventListener('click', () => { set(!get()); update(); });
  update();
  if (cwd) {
    fetch(`/api/sysop/context/check?cwd=${encodeURIComponent(cwd)}`, { cache: 'no-store' })
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => { if (d && d.ok) { check = d; update(); } })
      .catch(() => {});
  }
  return { el: row, update };
}

export function ctxSessionWhy(s) {
  const repo = ctxRepoByKey(s.key);
  if (s.waiting && s.reason === 'behind') {
    return `Its launcher waits for a new context of ${s.repo} (about 10 s): ${s.changes ? `${plural(s.changes, 'file')} changed` : 'its docs changed'} since the last one; Enter in the terminal starts it with the last one.`;
  }
  if (s.waiting) return `Its launcher waits for the first context of ${s.repo} (about 10 s); Enter in the terminal starts it without.`;
  if (s.context) return `Started with the context of ${s.repo}: ${ctxProvenance(s)}.`;
  if (s.off) return `Started without context: you unticked "Repository context" when you created it.`;
  if (s.skipped) return `Started without context: you started it without waiting. The next session in ${s.repo} gets it.`;
  if (s.failed || (repo && repo.state === 'failed')) {
    return `Started without context: the sysop could not write it${repo && repo.call && repo.call.error ? ` (${repo.call.error})` : ''}.`;
  }
  if (repo && repo.state === 'writing') return `Started without context: the sysop is writing it; the next session in ${s.repo} gets it.`;
  return `Started without context: there was none for ${s.repo} yet.`;
}

// The mark of a session's context: a book (pulsing: preparing; green: it started with it; amber: without), with words unless
// `compact`. A click opens the session's context card.
export function makeCtxChip(t, s, compact = false, el = null) {
  const b = el || document.createElement('button');
  const clsState = s.waiting ? 'is-wait' : s.context ? '' : s.off ? 'is-off' : 'is-none';
  b.type = 'button';
  b.className = `${el ? el.className.replace(/\s*(is-none|is-wait|is-off|hidden)\b/g, '') : `agent-ctx-chip${compact ? ' is-compact' : ''}`}${clsState ? ` ${clsState}` : ''}`;
  const label = s.waiting ? 'preparing context…' : s.context ? 'context' : s.off ? 'context off' : 'no context';
  b.innerHTML = compact ? ICO_BOOK_SVG : `${ICO_BOOK_SVG}<span>${label}</span>`;
  b.title = `${ctxSessionWhy(s)} Click for details.`;
  b.setAttribute('aria-label', b.title);
  b.onclick = (e) => {
    e.stopPropagation();
    closeCardMenu();
    openSessionContextPopover(t.address);
  };
  return b;
}

// The context of the active tab's session in the title bar (desktop: book and words; mobile: the book)
export function renderTopbarCtx(active) {
  const s = active ? ctxSessionFor(active) : null;
  for (const [btn, compact] of [[dom.topbarCtxBtnEl, false], [dom.mobileCtxBtnEl, true]]) {
    if (!btn) continue;
    if (!s) {
      btn.classList.add('hidden');
      btn.onclick = null;
      continue;
    }
    makeCtxChip(active, s, compact, btn);
    btn.classList.remove('hidden');
  }
}

// The pill of a repository header: ready (its age), writing (pulses), failed or no answer (amber)
export function makeRepoCtxPill(repo) {
  const b = document.createElement('button');
  b.type = 'button';
  b.className = 'repo-ctx-pill';
  b.dataset.state = repo.state;
  const word = repo.state === 'writing' ? 'writing' : repo.state === 'failed' ? 'failed' : repo.state === 'stuck' ? 'no answer'
    : fmtShortAge(repo.at);
  b.innerHTML = `${ICO_BOOK_SVG}<span>${word}</span>`;
  if (repo.state === 'writing') phase(b.querySelector('svg'), 1400);
  b.title = repo.state === 'writing'
    ? `The sysop is writing the context of ${repo.repo} (${CTX_REASONS[repo.call && repo.call.reason] || 'in the background'})`
    : repo.state === 'failed' ? `The context of ${repo.repo} failed: ${(repo.call && repo.call.error) || 'see Events'}${repo.at ? ` (new sessions still get the one written ${fmtAge(repo.at)})` : ''}`
      : repo.state === 'stuck' ? `The context call of ${repo.repo} never ended`
        : `Context of ${repo.repo}: written ${fmtAge(repo.at)}${repo.base ? ` at ${repo.base.slice(0, 7)}` : ''}; new agent sessions start with it`;
  b.setAttribute('aria-label', b.title);
  b.addEventListener('click', (e) => {
    e.stopPropagation();
    closeCardMenu();
    openRepoContextPopover(repo.key);
  });
  return b;
}

function ctxKv(rows) {
  const g = document.createElement('div');
  g.className = 'ctx-kv';
  for (const [k, v] of rows) {
    if (!v) continue;
    const a = document.createElement('span');
    a.className = 'ctx-kv-k';
    a.textContent = k;
    const b = document.createElement('span');
    b.className = 'ctx-kv-v';
    b.textContent = v;
    g.append(a, b);
  }
  return g;
}

function ctxPopHead(title, tone) {
  const head = document.createElement('div');
  head.className = `spop-head ctx-pop-head${tone ? ` is-${tone}` : ''}`;
  const t = document.createElement('span');
  t.className = 'ctx-pop-title';
  t.innerHTML = ICO_BOOK_SVG;
  const words = document.createElement('span');
  words.textContent = title;
  t.appendChild(words);
  head.appendChild(t);
  return head;
}

function ctxPopButton(label, kind, onClick) {
  const b = document.createElement('button');
  b.type = 'button';
  b.className = `spop-btn ${kind}`;
  b.textContent = label;
  b.addEventListener('click', onClick);
  return b;
}

export function openSessionContextPopover(address) {
  const t = state.terminals.find((x) => x.address === address);
  const s = t ? ctxSessionFor(t) : null;
  if (!t || !s) return;
  const repo = ctxRepoByKey(s.key);
  const frag = document.createDocumentFragment();
  const title = s.waiting ? `${s.reason === 'behind' ? 'Rewriting' : 'Preparing'} the context of ${s.repo}` : s.context ? `Started with the context of ${s.repo}` : `Started without context`;
  const head = ctxPopHead(title, s.waiting ? 'wait' : s.context ? 'ok' : s.off ? '' : 'warn');
  // The same ↻ as the repository's card; the repository's card then opens to show the sysop writing
  if (repo && repo.top) {
    head.appendChild(ctxRefreshButton(repo, { busy: ctxBusy(repo), onClick: () => { rewriteContext(repo.key, address); openRepoContextPopover(repo.key); } }));
  }
  frag.appendChild(head);
  const sub = document.createElement('div');
  sub.className = 'spop-sub';
  sub.textContent = s.context
    ? 'It is in the agent\'s system prompt since the session started. A rewrite reaches the next sessions, not this one.'
    : ctxSessionWhy(s);
  frag.appendChild(sub);
  frag.appendChild(ctxKv([
    ['session', `${tabDisplayName(t)} · ${agentLabel(s.agent)} · started ${fmtClock(s.at)}`],
    ['at commit', String(s.commit || '').slice(0, 7)],
    ['written', s.context && s.base_at ? `${fmtClock(s.base_at)} at ${String(s.base || '').slice(0, 7)}` : ''],
    ['changed since', s.context && s.base && s.commit && s.base.slice(0, 7) !== s.commit.slice(0, 7) ? plural(s.changes || 0, 'file') : ''],
  ]));
  const acts = document.createElement('div');
  acts.className = 'ctx-pop-acts';
  if (s.context) acts.appendChild(ctxPopButton('See what it got', 'primary', () => { closePopover(); openContextViewer({ tab: address }); }));
  acts.appendChild(ctxPopButton('Events', 'secondary', () => { closePopover(); if (typeof actions.showSysopEvents === 'function') actions.showSysopEvents(s.key); }));
  frag.appendChild(acts);
  openPopover(frag);
}

export function ctxBusy(repo) {
  if (!repo) return false;
  if (repo.state === 'writing') return true;
  const t = ctxPending.get(repo.key);
  return Boolean(t && Date.now() - t < 30000);
}

function capFirst(t) {
  return t ? t.charAt(0).toUpperCase() + t.slice(1) : t;
}

export function ctxRepoSig(repo) {
  if (!repo) return '';
  return [repo.state, repo.at, repo.call && repo.call.phase, repo.call && repo.call.ts, ctxBusy(repo), ctxJustDone.has(repo.key)].join('|');
}

// The ↻ in a context card's head: the same button on the repository's card and on an agent's
export function ctxRefreshButton(repo, { busy, done = false, onClick }) {
  const rb = document.createElement('button');
  rb.type = 'button';
  rb.className = `ctx-refresh${busy ? ' is-spinning' : ''}${done ? ' is-done' : ''}`;
  rb.innerHTML = done ? ICO_CHECK_SVG : ICO_REFRESH_SVG;
  rb.disabled = busy;
  rb.title = busy ? 'The sysop is writing it' : done ? 'Rewritten just now' : repo.at ? 'Rewrite the context now' : 'Write the context now';
  rb.setAttribute('aria-label', rb.title);
  rb.addEventListener('click', (e) => { e.stopPropagation(); onClick(); });
  return rb;
}

export function openRepoContextPopover(key) {
  const repo = ctxRepoByKey(key);
  if (!repo) return;
  const busy = ctxBusy(repo);
  const done = !busy && ctxJustDone.has(key) && Date.now() - ctxJustDone.get(key) < 4000;
  const sessions = Object.values((state.sysopContext && state.sysopContext.sessions) || {})
    .filter((s) => s.key === key && !s.waiting && state.terminals.some((x) => x.address === s.tab));
  const withIt = sessions.filter((s) => s.context).length;
  const frag = document.createDocumentFragment();
  const tone = busy ? 'wait' : repo.state === 'ready' ? 'ok' : 'warn';
  const head = ctxPopHead(busy ? `Writing the context of ${repo.repo}…` : `Context of ${repo.repo}`, tone);
  head.dataset.ctxKey = key;
  // ↻ rewrites it here: the card stays open, the arrow turns while the sysop writes, a check when the new one is in
  if (repo.top) head.appendChild(ctxRefreshButton(repo, { busy, done, onClick: () => rewriteContext(key) }));
  frag.appendChild(head);
  const sub = document.createElement('div');
  sub.className = 'spop-sub';
  sub.textContent = busy
    ? (repo.state === 'writing'
      ? `${capFirst(CTX_REASONS[repo.call && repo.call.reason] || 'in the background')}; started ${fmtAge(repo.call && repo.call.ts)}. New agent sessions get it as soon as it is written.`
      : 'Asking the sysop to write it…')
    : done ? 'Rewritten just now: new agent sessions in it start with this one.'
      : repo.state === 'failed' ? `The last call failed: ${(repo.call && repo.call.error) || 'no reason given'}.${repo.call && repo.call.retry_min ? ` It tries again by itself in ${repo.call.retry_min} min.` : ''}${repo.at ? ` New sessions still get the context written ${fmtAge(repo.at)}.` : ''}`
        : repo.state === 'stuck' ? 'The last call never ended (the sysop was stopped?).'
          : 'The sysop\'s orientation to this repository: new agent sessions in it start with it in their system prompt.';
  frag.appendChild(sub);
  if (busy) {
    const bar = document.createElement('div');
    bar.className = 'ctx-progress';
    bar.innerHTML = '<i></i>';
    frag.appendChild(bar);
  }
  frag.appendChild(ctxKv([
    ['written', repo.at ? `${fmtAge(repo.at)}${repo.base ? ` at ${repo.base.slice(0, 7)}` : ''}` : ''],
    ['why', repo.call && repo.call.phase === 'made' ? CTX_REASONS[repo.call.reason] || '' : ''],
    ['sessions with it', sessions.length ? `${withIt} of ${sessions.length} open` : ''],
  ]));
  const acts = document.createElement('div');
  acts.className = 'ctx-pop-acts';
  if (!busy && (repo.state === 'failed' || repo.state === 'stuck') && repo.top) {
    acts.appendChild(ctxPopButton('Retry now', 'primary', () => rewriteContext(key)));
  }
  if (repo.at) acts.appendChild(ctxPopButton('View', repo.state === 'failed' || repo.state === 'stuck' ? 'secondary' : 'primary', () => { closePopover(); openContextViewer({ key }); }));
  acts.appendChild(ctxPopButton('Events', 'secondary', () => { closePopover(); if (typeof actions.showSysopEvents === 'function') actions.showSysopEvents(key); }));
  frag.appendChild(acts);
  ctxPopKey = key;
  ctxPopSig = ctxRepoSig(repo);
  openPopover(frag);
}

// The context card of this repository is still the open popover
export function ctxPopIsOpen(key) {
  return Boolean(state.popoverOpen && dom.popoverEl && key && dom.popoverEl.querySelector(`.ctx-pop-head[data-ctx-key="${CSS.escape(key)}"]`));
}

// Rewrite a repository's context. `stay` (the card, the viewer): the place it was asked from shows the work; otherwise a toast.
export async function rewriteContext(key, tab = '', { stay = true } = {}) {
  const repo = ctxRepoByKey(key);
  ctxPending.set(key, Date.now());
  ctxJustDone.delete(key);
  syncCtxSurfaces();
  try {
    const r = await fetch('/api/sysop/context/rewrite', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ key, tab }),
    });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(d.message || `HTTP ${r.status}`);
    if (!stay) showTermToast(`Sysop is writing the context of ${(repo && repo.repo) || 'the repository'}`, 'ok');
  } catch (e) {
    ctxPending.delete(key);
    syncCtxSurfaces();
    showTermToast(`Cannot write the context: ${e.message || e}`, 'error', 4000);
  }
}

// The context card and the viewer follow the repository's state while open (writing, then the new context or the failure)
export function syncCtxSurfaces() {
  if (typeof actions.syncStageLoader === 'function') actions.syncStageLoader();
  for (const [key, t] of ctxPending) {
    const repo = ctxRepoByKey(key);
    const seen = repo && (repo.state === 'writing' || (repo.call && repo.call.ts >= t - 2000 && repo.call.phase !== 'started'));
    if (seen || Date.now() - t > 30000) ctxPending.delete(key);
  }
  if (ctxPopKey && ctxPopIsOpen(ctxPopKey)) {
    const repo = ctxRepoByKey(ctxPopKey);
    if (repo && ctxRepoSig(repo) !== ctxPopSig) openRepoContextPopover(ctxPopKey);
  } else {
    ctxPopKey = '';
  }
  if (ctxViewer && ctxViewer.kind === 'repo') {
    const fv = typeof actions.getFileViewer === 'function' ? actions.getFileViewer() : null;
    const open = state.fileDrawerOpen && fv && typeof fv.getInlineTag === 'function' && fv.getInlineTag() === `ctx:${ctxViewer.key}`;
    if (!open) {
      ctxViewer = null;
    } else {
      const repo = ctxRepoByKey(ctxViewer.key);
      if (typeof fv.setInlineBusy === 'function') fv.setInlineBusy(ctxBusy(repo));
      if (repo && !ctxBusy(repo) && repo.at && repo.at !== ctxViewer.at) openContextViewer({ key: ctxViewer.key });
    }
  }
}

// A rewrite seen to end with a new context: the check on the card for a few seconds
export function noteCtxDone(prev, next) {
  const before = new Map((prev || []).map((r) => [r.key, r]));
  for (const r of next || []) {
    const p = before.get(r.key);
    if (p && p.state === 'writing' && r.state === 'ready' && r.at && r.at !== p.at) {
      ctxJustDone.set(r.key, Date.now());
      setTimeout(() => { ctxJustDone.delete(r.key); syncCtxSurfaces(); }, 4000);
    }
  }
}

export async function openContextViewer({ tab = '', key = '' } = {}) {
  const qs = new URLSearchParams();
  if (tab) qs.set('tab', tab);
  else qs.set('key', key);
  let d = null;
  try {
    const r = await fetch(`/api/sysop/context?${qs.toString()}`, { cache: 'no-store' });
    d = await r.json().catch(() => null);
    if (!r.ok) d = null;
  } catch (_) { d = null; }
  if (!d || d.text == null) {
    ctxViewer = null;
    if (typeof actions.openFileDrawerInline === 'function') {
      actions.openFileDrawerInline({ title: 'Repository context', subtitle: '', content: '', note: 'There is no repository context for this.', noteTone: 'warn', kind: 'md', badge: 'CTX' });
    }
    return;
  }
  const m = d.meta || {};
  const repoKey = String(m.key || key || '');
  const settings = {
    label: 'Settings',
    onClick: () => {
      if (typeof actions.closeFileDrawer === 'function') actions.closeFileDrawer();
      if (typeof actions.openSettings === 'function') actions.openSettings('sysop');
    },
  };
  if (d.kind === 'session') {
    const s = { ...m, base_at: Number(m.base_at || 0) * 1000, at: Number(m.at || 0) * 1000 };
    const live = state.terminals.find((x) => x.address === tab);
    ctxViewer = { kind: 'session', key: repoKey, tab };
    // What a session got does not change: no refresh here; the repository's current context is one click away
    const drawerActions = repoKey && ctxRepoByKey(repoKey) && ctxRepoByKey(repoKey).at
      ? [{ label: 'See current context', onClick: () => openContextViewer({ key: repoKey }) }, settings] : [settings];
    if (typeof actions.openFileDrawerInline === 'function') {
      actions.openFileDrawerInline({
        title: `${live ? tabDisplayName(live) : tab} · context of ${s.repo}`,
        subtitle: `${agentLabel(s.agent)} session started ${fmtClock(s.at)} at ${String(s.commit || '').slice(0, 7)}`,
        note: `This is exactly what the agent got in its system prompt when the session started ${fmtAge(s.at)}: the sysop's context of ${s.repo}, ${ctxProvenance(s)}. A rewrite later reaches new sessions, not this one.`,
        content: d.text,
        kind: 'md',
        badge: 'CTX',
        tag: `ctx-session:${tab}`,
        actions: drawerActions,
      });
    }
    return;
  }
  const at = Number(m.at || 0) * 1000;
  const repo = ctxRepoByKey(repoKey);
  ctxViewer = { kind: 'repo', key: repoKey, at: repo ? repo.at : at };
  if (typeof actions.openFileDrawerInline === 'function') {
    actions.openFileDrawerInline({
      title: `Context of ${m.repo || 'the repository'}`,
      subtitle: `written ${fmtClock(at)} at ${String(m.base || '').slice(0, 7)}`,
      note: `The current context of ${m.repo}, written by the sysop ${fmtAge(at)}${m.base ? ` at commit ${String(m.base).slice(0, 7)}` : ''}. New agent sessions in it start with this, plus the list of files changed since.`,
      content: d.text || '',
      kind: 'md',
      badge: 'CTX',
      tag: `ctx:${repoKey}`,
      refresh: repoKey && repo && repo.top
        ? { title: 'Rewrite the context now (the view reloads when the new one is in)', busy: ctxBusy(repo), onClick: () => rewriteContext(repoKey) }
        : null,
      actions: [settings],
    });
  }
}

export function tickCtxSince() {
  if (dom.termStageLoaderEl && dom.termStageLoaderEl.classList.contains('is-ctx')) {
    if (typeof actions.syncStageLoader === 'function') actions.syncStageLoader();
  }
  for (const el of document.querySelectorAll('[data-ctx-since]')) {
    const secs = Math.max(0, Math.round((Date.now() - Number(el.dataset.ctxSince || 0)) / 1000));
    el.textContent = `preparing context · ${secs}s`;
  }
}

export function syncContext(sysop) {
  const prevRepos = state.sysopContext && state.sysopContext.repos;
  state.sysopContext = (sysop && sysop.context) || null;
  noteCtxDone(prevRepos, state.sysopContext && state.sysopContext.repos);
  const k = JSON.stringify([state.sysopContext && state.sysopContext.on, state.sysopContext && state.sysopContext.sessions,
    state.sysopContext && (state.sysopContext.repos || []).map((r) => [r.key, r.state, Math.floor((r.at || 0) / 60000), Math.floor(Date.now() / 60000)])]);
  if (k !== lastCtxTabsKey) {
    lastCtxTabsKey = k;
    if (typeof actions.renderTabs === 'function') actions.renderTabs();
  }
  syncCtxSurfaces();
}

export function initSysopContext() {
  if (sysopContextInitialized || typeof document === 'undefined') return;
  sysopContextInitialized = true;
  // "preparing context · 6s" counts while a launcher waits (the snapshot only comes when something changes)
  if (dom.stageLoaderCtxSkipEl) {
    dom.stageLoaderCtxSkipEl.addEventListener('click', () => {
      const sess = activeSession();
      if (sess) {
        if (typeof actions.sendPtyInput === 'function') actions.sendPtyInput('\r', sess);
        try { sess.term.focus(); } catch (_) {}
      }
    });
  }
  setInterval(tickCtxSince, 1000);
}
