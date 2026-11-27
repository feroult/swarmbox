// Sysop Events / Automations / Notes tab: view toggle, filters, prefetch groups, autocontext rows, automation rows, and system events.

import { state, dom, actions, isAgentId } from './state.js';
import { ICO_BOOK_SVG, ICO_CLOCK_SVG, ICO_BOLT_SVG, ICO_BELL_SVG, ICO_PENCIL_SVG, tabDisplayName, tabAgentKind } from './icons.js';
import { showTermToast, startInlineRename } from './ui-chrome.js';
import { AUTOCONTEXT_STALE_MS, CTX_REASONS, fmtAgo, plural, ctxRepoByKey, openContextViewer, openRepoContextPopover, rewriteContext } from './sysop-context.js';

let eventsFilter = { kind: 'all', key: '' };
let lastEventsKey = '';
let sysopEventsInitialized = false;

export function setSysopView(view) {
  state.sysopView = view === 'events' ? 'events' : 'chat';
  try { localStorage.setItem('sb.sysopView', state.sysopView); } catch (_) {}
  const ev = state.sysopView === 'events';
  if (dom.sysopTabChatEl) { dom.sysopTabChatEl.classList.toggle('is-on', !ev); dom.sysopTabChatEl.setAttribute('aria-selected', String(!ev)); }
  if (dom.sysopTabEventsEl) { dom.sysopTabEventsEl.classList.toggle('is-on', ev); dom.sysopTabEventsEl.setAttribute('aria-selected', String(ev)); }
  if (dom.sysopFeedEl) dom.sysopFeedEl.classList.toggle('hidden', ev);
  if (dom.sysopEventsEl) dom.sysopEventsEl.classList.toggle('hidden', !ev);
  if (ev && state.lastSysopSnap) { lastEventsKey = ''; renderEvents(state.lastSysopSnap); }
}

// Open the Events tab (filtered to one repository when `key` is given), opening the panel if it is closed
export function showSysopEvents(key = '') {
  eventsFilter = { kind: key ? 'context' : eventsFilter.kind, key: key || '' };
  if (typeof actions.isMobileLayout === 'function' && actions.isMobileLayout()) {
    if (typeof actions.setMobileSysop === 'function') actions.setMobileSysop(true);
  } else if (typeof actions.setDesktopSysop === 'function') {
    actions.setDesktopSysop(true);
  }
  setSysopView('events');
}

// The events the tab shows, newest first: a context call's `started` folds into its `made`/`failed`; the context written for the
// repositories you use when the box started (reason prefetch, within 3 minutes) is one row
function eventItems(evs) {
  const ended = new Set();
  for (const ev of evs) {
    if (ev && ev.kind === 'autocontext' && (ev.phase === 'made' || ev.phase === 'failed')) ended.add(`${ev.key}|${ev.commit}`);
  }
  const shown = evs.filter((ev) => ev && !(ev.kind === 'autocontext' && (ev.phase === 'session'
    || (ev.phase === 'started' && ended.has(`${ev.key}|${ev.commit}`)))));
  const items = [];
  for (const ev of shown) {
    const last = items[items.length - 1];
    const pre = ev.kind === 'autocontext' && ev.reason === 'prefetch' && ev.phase !== 'started';
    if (pre && last && last.group && ev.ts - last.lastTs < 3 * 60 * 1000) {
      last.items.push(ev);
      last.lastTs = ev.ts;
      continue;
    }
    items.push(pre ? { group: true, items: [ev], lastTs: ev.ts, ts: ev.ts } : { ev, ts: ev.ts });
  }
  return items.map((it) => (it.group && it.items.length === 1 ? { ev: it.items[0], ts: it.ts } : it)).reverse();
}

function eventMatches(it) {
  const evs = it.group ? it.items : [it.ev];
  return evs.some((ev) => {
    if (eventsFilter.kind === 'context' && ev.kind !== 'autocontext') return false;
    if (eventsFilter.kind === 'names' && ev.kind !== 'autoname') return false;
    if (eventsFilter.kind === 'auto' && ev.kind !== 'automation' && ev.kind !== 'notify') return false;
    if (eventsFilter.key && ev.key !== eventsFilter.key) return false;
    return true;
  });
}

// "Now": a call running, or a failure the repository still has
function eventIsNow(it) {
  if (it.group) return false;
  const ev = it.ev;
  if (ev.kind !== 'autocontext') return false;
  if (ev.phase === 'started') return Date.now() - (ev.ts || 0) <= AUTOCONTEXT_STALE_MS;
  if (ev.phase === 'failed') {
    const r = ctxRepoByKey(ev.key);
    return Boolean(r && r.state === 'failed' && r.call && r.call.ts === ev.ts);
  }
  return false;
}

export function renderEventsBadge() {
  if (!dom.sysopEventsBadgeEl) return;
  const failed = ((state.sysopContext && state.sysopContext.on && state.sysopContext.repos) || []).filter((r) => r.state === 'failed' || r.state === 'stuck').length;
  dom.sysopEventsBadgeEl.textContent = failed ? String(failed) : '';
  dom.sysopEventsBadgeEl.classList.toggle('hidden', !failed);
  if (dom.sysopTabEventsEl) dom.sysopTabEventsEl.title = failed
    ? `${plural(failed, 'repository context')} failed: see why`
    : 'What the Sysop did by itself: repository context, tab names, schedules and triggers, notifications';
}

function makeChip(label, on, onClick) {
  const b = document.createElement('button');
  b.type = 'button';
  b.className = `sysop-ev-chip${on ? ' is-on' : ''}`;
  b.setAttribute('aria-pressed', String(on));
  b.textContent = label;
  b.addEventListener('click', onClick);
  return b;
}

export function renderEvents(sysop) {
  state.lastSysopSnap = sysop;
  renderEventsBadge();
  if (!dom.sysopEventsEl || state.sysopView !== 'events') return;
  const evs = Array.isArray(sysop.events) ? sysop.events : [];
  const autos = Array.isArray(sysop.automations) ? sysop.automations : [];
  const sysNotes = Array.isArray(sysop.notes) ? sysop.notes : [];
  const key = JSON.stringify([evs, autos, sysNotes, eventsFilter, state.sysopContext && state.sysopContext.repos, state.terminals.map((t) => [t.address, tabDisplayName(t)]),
    Math.floor(Date.now() / 30000)]);
  if (key === lastEventsKey) return;
  lastEventsKey = key;
  dom.sysopEventsEl.innerHTML = '';

  const bar = document.createElement('div');
  bar.className = 'sysop-ev-filters';
  const setKind = (kind) => () => { eventsFilter = { kind, key: kind === 'names' ? '' : eventsFilter.key }; lastEventsKey = ''; renderEvents(sysop); };
  bar.append(makeChip('All', eventsFilter.kind === 'all' && !eventsFilter.key, () => { eventsFilter = { kind: 'all', key: '' }; lastEventsKey = ''; renderEvents(sysop); }),
    makeChip('Context', eventsFilter.kind === 'context', setKind('context')),
    makeChip('Tab names', eventsFilter.kind === 'names', setKind('names')),
    makeChip('Automations', eventsFilter.kind === 'auto', setKind('auto')));
  if (eventsFilter.key) {
    const r = ctxRepoByKey(eventsFilter.key);
    bar.appendChild(makeChip(`${(r && r.repo) || 'repository'} ✕`, true, () => { eventsFilter = { kind: 'context', key: '' }; lastEventsKey = ''; renderEvents(sysop); }));
  }
  dom.sysopEventsEl.appendChild(bar);

  const list = document.createElement('div');
  list.className = 'sysop-ev-list';
  if (eventsFilter.kind === 'all' || eventsFilter.kind === 'auto') renderAutomations(list, autos);
  if (eventsFilter.kind === 'all') renderSysopNotes(list, sysNotes);
  const items = eventItems(evs).filter(eventMatches);
  const now = items.filter(eventIsNow);
  const earlier = items.filter((it) => !eventIsNow(it));
  const latestRenameByTab = new Map();
  for (const ev of evs) if (ev && ev.kind === 'autoname' && ev.tab && !latestRenameByTab.has(ev.tab)) latestRenameByTab.set(ev.tab, null);
  for (const ev of evs) if (ev && ev.kind === 'autoname' && ev.tab) latestRenameByTab.set(ev.tab, ev.id);
  const section = (title, its) => {
    if (!its.length) return;
    const h = document.createElement('div');
    h.className = 'sysop-ev-section';
    h.textContent = title;
    list.appendChild(h);
    for (const it of its) {
      if (it.group) list.appendChild(renderPrefetchGroup(it));
      else if (it.ev.kind === 'autocontext') list.appendChild(renderAutocontextRow(it.ev));
      else list.appendChild(renderSystemEventRow(it.ev, { isLatestForTab: latestRenameByTab.get(it.ev.tab) === it.ev.id }));
    }
  };
  section('Now', now);
  section(now.length ? 'Earlier' : 'Last 12 hours', earlier);
  if (!items.length && !list.querySelector('.sysop-auto, .sysop-note')) {
    const empty = document.createElement('div');
    empty.className = 'sysop-ev-empty';
    empty.textContent = eventsFilter.kind === 'all' && !eventsFilter.key
      ? 'Nothing yet. When the Sysop writes the context of a repository, names a tab, runs a schedule or a trigger, or notifies you, it shows here.'
      : 'Nothing of this kind in the last 12 hours.';
    list.appendChild(empty);
  }
  const foot = document.createElement('div');
  foot.className = 'sysop-ev-foot';
  foot.textContent = 'Each agent session shows its context on its card.';
  list.appendChild(foot);
  dom.sysopEventsEl.appendChild(list);
}

// The schedules and triggers of the Sysop (docs/sysop-automations-design.md 2): what is live, with Pause, Resume and Cancel
export function renderAutomations(list, autos) {
  const live = autos.filter((a) => a.state !== 'ended');
  if (!live.length) return;
  const h = document.createElement('div');
  h.className = 'sysop-ev-section';
  h.textContent = 'Automations';
  list.appendChild(h);
  for (const a of live) {
    const row = document.createElement('div');
    row.className = `sysop-sysev sysop-auto is-${a.state}`;
    const body = document.createElement('div');
    body.className = 'sysop-sysev-body';
    const ico = document.createElement('span');
    ico.className = 'sysop-sysev-ico sysop-auto-ico';
    ico.innerHTML = a.kind === 'trigger' ? ICO_BOLT_SVG : ICO_CLOCK_SVG;
    const text = document.createElement('span');
    text.className = 'sysop-sysev-text';
    const desc = String(a.desc || '').replace(/^a\d+ \[[a-z]+\] /, '');
    const head = desc.split(': ')[0];
    text.append(head || a.kind);
    const sub = document.createElement('span');
    sub.className = 'sysop-sysev-sub';
    sub.textContent = a.prompt;
    sub.title = a.prompt;
    text.appendChild(sub);
    body.append(ico, text);
    const meta = document.createElement('div');
    meta.className = 'sysop-sysev-meta';
    if (a.state === 'paused') {
      const tag = document.createElement('span');
      tag.className = 'sysop-sysev-state';
      tag.textContent = 'paused';
      meta.appendChild(tag);
      meta.appendChild(evButton('Resume', 'Run it again', () => automationAction(a.id, 'resume')));
    } else {
      meta.appendChild(evButton('Pause', 'Keep it, but do not run it', () => automationAction(a.id, 'pause')));
    }
    meta.appendChild(evButton('Cancel', 'End it now', () => automationAction(a.id, 'cancel')));
    row.append(body, meta);
    list.appendChild(row);
  }
}

// What the Sysop keeps across conversations (its notes): shown, and removable, so nothing it remembers is hidden
export function renderSysopNotes(list, items) {
  if (!items.length) return;
  const h = document.createElement('div');
  h.className = 'sysop-ev-section';
  h.textContent = 'Notes';
  h.title = 'What the Sysop keeps across conversations (New conversation keeps them)';
  list.appendChild(h);
  for (const n of items) {
    const row = document.createElement('div');
    row.className = 'sysop-sysev sysop-note';
    const body = document.createElement('div');
    body.className = 'sysop-sysev-body';
    const ico = document.createElement('span');
    ico.className = 'sysop-sysev-ico sysop-auto-ico';
    ico.innerHTML = ICO_PENCIL_SVG;
    const text = document.createElement('span');
    text.className = 'sysop-sysev-text';
    text.append(n.name);
    const sub = document.createElement('span');
    sub.className = 'sysop-sysev-sub';
    sub.textContent = n.preview;
    sub.title = n.preview;
    text.appendChild(sub);
    body.append(ico, text);
    const meta = document.createElement('div');
    meta.className = 'sysop-sysev-meta';
    meta.appendChild(evButton('Delete', 'The Sysop forgets this note', async () => {
      const r = await fetch('/api/sysop/note', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name: n.name, action: 'delete' }) });
      const data = await r.json().catch(() => ({}));
      showTermToast(r.ok ? `Forgot ${n.name}` : (data.message || 'It could not be deleted'), r.ok ? 'ok' : 'error', 2200);
    }));
    const ago = fmtAgo(n.at);
    if (ago) {
      const tm = document.createElement('span');
      tm.className = 'sysop-sysev-time';
      tm.textContent = ago;
      meta.appendChild(tm);
    }
    row.append(body, meta);
    list.appendChild(row);
  }
}

export async function automationAction(id, action) {
  const r = await fetch('/api/sysop/automation', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ id, action }) });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) showTermToast(data.message || 'It could not be changed', 'error', 4000);
  else showTermToast({ pause: 'Paused', resume: 'Resumed', cancel: 'Cancelled' }[action] || 'Done', 'ok', 1800);
}

function evButton(label, title, onClick) {
  const v = document.createElement('button');
  v.type = 'button';
  v.className = 'sysop-sysev-edit';
  v.title = title;
  v.textContent = label;
  v.addEventListener('click', onClick);
  return v;
}

export function renderPrefetchGroup(it) {
  const made = it.items.filter((e) => e.phase === 'made');
  const failed = it.items.filter((e) => e.phase === 'failed');
  const row = document.createElement('div');
  row.className = `sysop-sysev sysop-sysev-ctx is-${failed.length && !made.length ? 'failed' : 'made'}`;
  const body = document.createElement('div');
  body.className = 'sysop-sysev-body';
  const ico = document.createElement('span');
  ico.className = 'sysop-sysev-ico';
  ico.innerHTML = ICO_BOOK_SVG;
  const text = document.createElement('span');
  text.className = 'sysop-sysev-text';
  const took = it.items.reduce((a, e) => a + (e.took || 0), 0);
  text.append(`Prepared the context of ${plural(made.length, 'repository')}`);
  const sub = document.createElement('span');
  sub.className = 'sysop-sysev-sub';
  sub.textContent = `the ones you use, when the box started${took ? ` · ${Math.round(took)}s in all` : ''}${failed.length ? ` · ${failed.length} failed` : ''}`;
  text.appendChild(sub);
  body.append(ico, text);
  const meta = document.createElement('div');
  meta.className = 'sysop-sysev-meta';
  const repos = document.createElement('span');
  repos.className = 'sysop-ev-repos';
  for (const e of it.items) {
    repos.appendChild(evButton(e.repo || 'repo', e.phase === 'made' ? `See the context of ${e.repo}` : `${e.repo}: ${e.error || 'failed'}`,
      () => (e.phase === 'made' ? openContextViewer({ key: e.key }) : openRepoContextPopover(e.key))));
  }
  const tm = document.createElement('span');
  tm.className = 'sysop-sysev-time';
  tm.textContent = fmtAgo(it.lastTs);
  meta.append(repos, tm);
  row.append(body, meta);
  return row;
}

function sysevTabChip(ev, liveTab, name) {
  const known = ev.tab && typeof actions.getKnownTab === 'function' ? actions.getKnownTab(ev.tab) : null;
  const kind = (liveTab && (tabAgentKind(liveTab) || 'shell'))
    || (isAgentId(ev.agent) ? ev.agent : '')
    || (known && known.kind)
    || 'shell';
  const chipObj = {
    address: ev.tab || '',
    name: name || (liveTab ? tabDisplayName(liveTab) : (known && known.name) || ev.tab || 'tab'),
    kind,
    live: Boolean(liveTab),
    unknown: !liveTab && !known,
  };
  if (typeof actions.tabChip === 'function') return actions.tabChip(chipObj);
  const fallback = document.createElement('span');
  fallback.className = 'tab-ref';
  fallback.textContent = chipObj.name;
  return fallback;
}

export function renderAutocontextRow(ev) {
  const liveTab = ev.tab ? state.terminals.find((t) => t.address === ev.tab) : null;
  const stale = ev.phase === 'started' && Date.now() - (ev.ts || 0) > AUTOCONTEXT_STALE_MS;
  const row = document.createElement('div');
  row.className = `sysop-sysev sysop-sysev-ctx is-${stale ? 'stale' : ev.phase || 'made'}`;

  const body = document.createElement('div');
  body.className = 'sysop-sysev-body';
  const ico = document.createElement('span');
  ico.className = 'sysop-sysev-ico';
  ico.innerHTML = ICO_BOOK_SVG;
  const textWrap = document.createElement('span');
  textWrap.className = 'sysop-sysev-text';
  const repo = document.createElement('span');
  repo.className = 'sysop-sysev-repo';
  repo.textContent = ev.repo || 'the repository';
  repo.title = ev.commit ? `${ev.repo} at commit ${ev.commit}` : '';
  const forTab = ev.tab ? [' · for ', sysevTabChip(ev, liveTab)] : [];
  const sub = document.createElement('span');
  sub.className = 'sysop-sysev-sub';
  sub.textContent = CTX_REASONS[ev.reason] || '';
  if (ev.phase === 'started' && !stale) {
    textWrap.append('Writing the context of ', repo, '…', ...forTab);
  } else if (ev.phase === 'started') {
    textWrap.append('The context of ', repo, ' got no answer', ...forTab);
  } else if (ev.phase === 'failed') {
    textWrap.append('Could not write the context of ', repo, ...forTab);
    sub.textContent = `${ev.error || 'failed'}${ev.retry_min ? ` · tries again in ${ev.retry_min} min` : ''}`;
  } else {
    textWrap.append('Wrote the context of ', repo, ...forTab);
    if (ev.took != null) sub.textContent = `${sub.textContent ? `${sub.textContent} · ` : ''}${ev.took}s`;
  }
  if (sub.textContent) textWrap.append(sub);
  body.append(ico, textWrap);

  const meta = document.createElement('div');
  meta.className = 'sysop-sysev-meta';
  if (ev.phase === 'failed' || stale) {
    const r = ctxRepoByKey(ev.key);
    if (r && r.state !== 'writing' && (r.top || ev.top)) meta.appendChild(evButton('Retry now', 'Write the context of this repository again now', () => rewriteContext(ev.key)));
    meta.appendChild(evButton('Settings', 'Sysop settings', () => { if (typeof actions.openSettings === 'function') actions.openSettings('sysop'); }));
  } else if (ev.phase === 'made') {
    meta.appendChild(evButton('View', 'See the context the sysop wrote', () => openContextViewer({ key: ev.key })));
  }
  const ago = fmtAgo(ev.ts);
  if (ago) {
    const tm = document.createElement('span');
    tm.className = 'sysop-sysev-time';
    tm.textContent = ago;
    meta.appendChild(tm);
  }
  row.append(body, meta);
  if (ev.phase === 'started' && !stale) {
    const bar = document.createElement('div');
    bar.className = 'ctx-progress';
    bar.innerHTML = '<i></i>';
    row.appendChild(bar);
  }
  return row;
}

// a notification the Sysop sent you, or a schedule / trigger that ran, was skipped or ended
export function renderAutomationEventRow(ev) {
  const row = document.createElement('div');
  const evPhase = ev.kind === 'notify' ? `notify-${ev.level || 'info'}` : ev.phase || 'fired';
  row.className = `sysop-sysev sysop-auto-ev is-${evPhase}`;
  const body = document.createElement('div');
  body.className = 'sysop-sysev-body';
  const ico = document.createElement('span');
  ico.className = 'sysop-sysev-ico sysop-auto-ico';
  const text = document.createElement('span');
  text.className = 'sysop-sysev-text';
  const sub = document.createElement('span');
  sub.className = 'sysop-sysev-sub';
  const desc = String(ev.text || '').replace(/^a\d+ \[[a-z]+\] /, '');
  if (ev.kind === 'notify') {
    ico.innerHTML = ICO_BELL_SVG;
    text.append(ev.text || 'A notification');
    sub.textContent = ev.level === 'urgent' ? 'urgent notification' : ev.level === 'warn' ? 'warning' : 'notification';
  } else {
    ico.innerHTML = /^a\d+ \[[a-z]+\] when /.test(String(ev.text || '')) ? ICO_BOLT_SVG : ICO_CLOCK_SVG;
    const words = { fired: 'Ran', skipped: 'Skipped a run of', ended: 'Ended' }[ev.phase] || 'Automation';
    text.append(`${words} ${ev.auto || 'an automation'}`);
    sub.textContent = ev.phase === 'fired' ? (ev.reason || desc.split(': ')[0]) : (ev.why || desc.split(': ')[0]);
  }
  if (sub.textContent) text.appendChild(sub);
  body.append(ico, text);
  const meta = document.createElement('div');
  meta.className = 'sysop-sysev-meta';
  const ago = fmtAgo(ev.ts);
  if (ago) {
    const tm = document.createElement('span');
    tm.className = 'sysop-sysev-time';
    tm.textContent = ago;
    meta.appendChild(tm);
  }
  row.append(body, meta);
  return row;
}

export function renderSystemEventRow(ev, opts = {}) {
  if (ev.kind === 'autocontext') return renderAutocontextRow(ev);
  if (ev.kind === 'automation' || ev.kind === 'notify') return renderAutomationEventRow(ev);
  const row = document.createElement('div');
  const liveTab = ev.tab ? state.terminals.find((t) => t.address === ev.tab) : null;
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
    const known = ev.tab && typeof actions.getKnownTab === 'function' ? actions.getKnownTab(ev.tab) : null;
    const chipKind = (liveTab && (tabAgentKind(liveTab) || 'shell'))
      || (isAgentId(ev.agent) ? ev.agent : '')
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

    const chipEl = typeof actions.tabChip === 'function' ? actions.tabChip(chipObj) : document.createTextNode(chipObj.name);
    textWrap.append('Renamed ', oldEl, ' ', arrow, ' ', chipEl);
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

export function initSysopEvents() {
  if (sysopEventsInitialized || typeof document === 'undefined') return;
  sysopEventsInitialized = true;
  try { if (localStorage.getItem('sb.sysopView') === 'events') state.sysopView = 'events'; } catch (_) {}
  if (dom.sysopTabChatEl) dom.sysopTabChatEl.addEventListener('click', () => setSysopView('chat'));
  if (dom.sysopTabEventsEl) dom.sysopTabEventsEl.addEventListener('click', () => setSysopView('events'));
  setSysopView(state.sysopView);
}
