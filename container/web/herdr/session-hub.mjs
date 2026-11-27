// Resident event hub & session keeper: auto-pinning agent sessions, bus tab events,
// snapshot broadcasting, sysop/theme polling, and live goal event streaming (/ws/events).

import fs from 'node:fs';
import path from 'node:path';
import {
  HOME,
  buildPinsSnapshot,
  cleanSessionTitle,
  compactEvents,
  defaultTitleForPath,
  detectLiveAgent,
  detectTerminalAgent,
  isHiddenTerminal,
  listInstalledAgents,
  makePinId,
  publishTabEvent,
  readActiveTab,
  readPins,
  readSavedTheme,
  readSessionPrefs,
  readSysopSnapshot,
  readWorktreePrefs,
  syncPinsFromTerminals,
  sysopLiveTail,
  terminalCwd,
  writePins,
} from './hc-client.mjs';
import { enrichTerminalsWithRepo } from './repo-discovery.mjs';

export function createSessionHub({ hc, eventClients = new Set(), worktreeHub, ptyBridge, options = {} }) {
  let currentTheme = readSavedTheme();
  let lastBroadcastHash = '';
  const lastTabCwd = new Map();
  const lastTabState = new Map();

  function buildSnapshot(extra = {}) {
    const rawTerminals = hc.listSnapshot();
    const terminals = enrichTerminalsWithRepo(rawTerminals);
    const sysop = readSysopSnapshot(rawTerminals);
    const pins = buildPinsSnapshot(rawTerminals);
    const worktrees = worktreeHub.pendingWorktreesFor(rawTerminals, pins);
    const worktree_prefs = readWorktreePrefs();
    const session_prefs = readSessionPrefs();
    const installed_agents = listInstalledAgents();
    const repo_statuses = worktreeHub.buildRepoStatusesSnapshot(rawTerminals);
    return {
      ...extra,
      terminals,
      active: readActiveTab(),
      sysop,
      theme: currentTheme,
      pins,
      worktrees,
      repo_statuses,
      worktree_prefs,
      session_prefs,
      installed_agents,
      home: HOME,
    };
  }

  function broadcast(payload) {
    const raw = JSON.stringify(payload);
    for (const ws of eventClients) {
      if (ws.readyState === 1) ws.send(raw);
    }
  }

  function emitBusTabEvents(ev, terminals) {
    const type = ev && ev.type;
    const addr = ev && ev.terminal;
    if (addr) {
      const t = (terminals || []).find((x) => x.address === addr);
      if (!t) return;
      const lbls = (t && t.labels) || {};
      const st = (t.status && t.status.state) || 'idle';
      const prevSt = lastTabState.get(addr) || '';
      lastTabState.set(addr, st);
      const cwd = terminalCwd(t);
      lastTabCwd.set(addr, cwd);
      const isTurn = type === 'turn';
      const isFinishedWork = type === 'status' && prevSt === 'working' && (st === 'done' || st === 'idle');
      // A tab that starts working is the user who just sent a request: the auto-namer names it a few seconds later
      // (when the request was not cancelled), instead of at the end of a turn that may take minutes.
      const isStart = type === 'status' && st === 'working' && prevSt !== 'working';
      if (isTurn || isFinishedWork || isStart) {
        publishTabEvent({
          event: isTurn ? 'turn' : isStart ? 'start' : 'status',
          tab: addr,
          cwd,
          agent: detectTerminalAgent(t) || 'shell',
          state: st,
          title: lbls['swarmbox.title'] || '',
          title_source: lbls['swarmbox.title_source'] || '',
        });
      }
      return;
    }
    for (const t of terminals || []) {
      const cwd = terminalCwd(t);
      const prevCwd = lastTabCwd.get(t.address);
      lastTabCwd.set(t.address, cwd);
      if (prevCwd && prevCwd !== cwd) {
        const lbls = (t && t.labels) || {};
        publishTabEvent({
          event: 'cwd',
          tab: t.address,
          cwd,
          agent: detectTerminalAgent(t) || 'shell',
          state: (t.status && t.status.state) || 'idle',
          title: lbls['swarmbox.title'] || '',
          title_source: lbls['swarmbox.title_source'] || '',
        });
      }
    }
  }

  // Every agent session persists until its tab is closed, however it was started: an agent typed into a
  // shell tab (the usual way into a folder without a repo), a cockpit or Sysop tab, a worktree opened from
  // its badge. The first time a terminal without a pin is seen running a known agent it gets an `auto` pin,
  // exactly like an agent tab opened with POST /api/tabs. `swarmbox.persist=off` (persist: false) opts out.
  const autoPinPending = new Set();
  function autoPinAgentTerminals(terms) {
    let pins = null;
    const added = [];
    for (const t of terms || []) {
      if (!t || !t.address || (t.state && t.state !== 'live') || isHiddenTerminal(t)) continue;
      const lbls = t.labels || {};
      if (lbls['swarmbox.pin_id'] || lbls['swarmbox.persist'] === 'off' || autoPinPending.has(t.address)) continue;
      const agent = detectLiveAgent(t);
      if (!agent) continue;
      if (!pins) pins = readPins();
      const cwd = terminalCwd(t);
      const nowSec = Math.floor(Date.now() / 1000);
      const labelTitle = cleanSessionTitle(lbls['swarmbox.title']);
      const labelSource = lbls['swarmbox.title_source'] === 'user' || lbls['swarmbox.title_source'] === 'auto' ? lbls['swarmbox.title_source'] : '';
      const rec = {
        id: makePinId(pins),
        title: labelTitle || defaultTitleForPath(cwd, agent),
        title_source: labelTitle ? labelSource : '',
        agent,
        cwd,
        resume: 'continue',
        autostart: readSessionPrefs().boot_mode === 'autostart',
        auto: true,
        created_at: nowSec,
        updated_at: nowSec,
      };
      if (lbls['swarmbox.worktree']) {
        rec.worktree = {
          path: String(lbls['swarmbox.worktree']),
          branch: String(lbls['swarmbox.branch'] || ''),
          base: String(lbls['swarmbox.base'] || ''),
          repo: String(lbls['swarmbox.repo'] || ''),
        };
      }
      pins.push(rec);
      added.push({ term: t, rec });
    }
    if (added.length === 0) return false;
    try { writePins(pins); } catch (_) { return false; }
    for (const { term, rec } of added) {
      const newLabels = { 'swarmbox.pin_id': rec.id, 'swarmbox.agent': rec.agent };
      if (!(term.labels && term.labels['swarmbox.title'])) newLabels['swarmbox.title'] = rec.title;
      term.labels = { ...(term.labels || {}), ...newLabels };
      autoPinPending.add(term.address);
      hc.call('terminal.label', { terminal: term.address, labels: newLabels })
        .catch(() => {
          // The label did not stick: drop the pin so the next snapshot can try again instead of leaving an orphan.
          try { writePins(readPins().filter((p) => p.id !== rec.id)); } catch (_) {}
          if (term.labels) delete term.labels['swarmbox.pin_id'];
        })
        .finally(() => autoPinPending.delete(term.address));
    }
    return true;
  }

  function snapshotHash(snap) {
    return JSON.stringify({
      sysop: snap.sysop,
      theme: snap.theme,
      active: snap.active,
      pins: snap.pins,
      worktrees: snap.worktrees,
      repo_statuses: snap.repo_statuses,
      session_prefs: snap.session_prefs,
    });
  }

  hc.on('snapshot', () => {
    const terms = hc.listSnapshot();
    autoPinAgentTerminals(terms);
    syncPinsFromTerminals(terms);
    emitBusTabEvents(null, terms);
    const snap = buildSnapshot({ type: 'snapshot' });
    lastBroadcastHash = snapshotHash(snap);
    broadcast(snap);
  });

  hc.on('hc-event', ({ event }) => {
    if (ptyBridge && typeof ptyBridge.onSizeEvent === 'function') {
      ptyBridge.onSizeEvent(event);
    }
    const terms = hc.listSnapshot();
    autoPinAgentTerminals(terms);
    syncPinsFromTerminals(terms);
    emitBusTabEvents(event, terms);
    const snap = buildSnapshot({ type: 'event', event });
    lastBroadcastHash = snapshotHash(snap);
    broadcast(snap);
  });

  // Poll real swarmbox-sysop state files & shared theme file; broadcast only on actual changes.
  // Every 4th tick (~2.4s) when a browser is open, also refresh live foreground cwd/metadata.
  let pollTick = 0;
  const sysopTimer = setInterval(() => {
    const diskTheme = readSavedTheme();
    const themeChanged = diskTheme !== currentTheme;
    if (themeChanged) currentTheme = diskTheme;
    if (eventClients.size === 0) return;
    pollTick = (pollTick + 1) % 8;
    if (pollTick % 4 === 0 && typeof hc.refreshTerminals === 'function') {
      hc.refreshTerminals();
    }
    if (pollTick === 0) {
      worktreeHub.refreshPendingWorktrees();
      worktreeHub.refreshAllRepoStatuses(hc.listSnapshot(), readPins());
    }
    const snap = buildSnapshot({ type: themeChanged ? 'theme' : 'sysop' });
    const h = snapshotHash(snap);
    if (h !== lastBroadcastHash) {
      lastBroadcastHash = h;
      broadcast(snap);
    }
  }, options.sysopPollMs || 600);
  if (sysopTimer.unref) sysopTimer.unref();

  // The sysop's live events (docs/sysop-brain-design.md 4.4): the goal's events.jsonl is the broker. inotify (fs.watch) wakes the pump the
  // moment the service appends a line; a slow timer is the fallback where inotify does not fire, and notices a new goal. Each new batch
  // goes to every page as one `sysop_events` message; a page that connects gets the goal's events so far (compacted) after its snapshot.
  // An event that changes what the snapshot shows (a state, an approval, the end of a call, a say, done) brings the snapshot at once.
  const LIVE_BACKLOG = 1 << 20;          // bytes a page may have queued before its events are held and coalesced
  let liveWatcher = null;
  let liveWatchGid = '';
  let liveSnapTimer = null;
  const SNAP_TYPES = new Set(['state', 'approval', 'call.end', 'say', 'done', 'call']);

  function sendLive(ws, msg) {
    if (ws.readyState !== 1) return;
    if (ws.bufferedAmount > LIVE_BACKLOG || (ws._livePending && ws._livePending.length)) {
      // a slow page: hold its events and send them coalesced when its buffer drains (never block, never grow without bound)
      ws._livePending = compactEvents([...(ws._livePending || []), ...msg.events]).slice(-5000);
      ws._liveGid = msg.gid;
      if (!ws._liveRetry) {
        ws._liveRetry = setInterval(() => {
          if (ws.readyState !== 1) { clearInterval(ws._liveRetry); ws._liveRetry = null; return; }
          if (ws.bufferedAmount > LIVE_BACKLOG) return;
          const events = ws._livePending;
          ws._livePending = null;
          clearInterval(ws._liveRetry);
          ws._liveRetry = null;
          if (events && events.length) ws.send(JSON.stringify({ type: 'sysop_events', gid: ws._liveGid, events }));
        }, 100);
        if (ws._liveRetry.unref) ws._liveRetry.unref();
      }
      return;
    }
    ws.send(JSON.stringify(msg));
  }

  function pumpLive(force = false) {
    if (eventClients.size === 0 && !force) return;
    let tail = null;
    try { tail = sysopLiveTail(); } catch (_) { tail = null; }
    if (!tail) return;
    if (tail.gid !== liveWatchGid) watchLive(tail);
    const fresh = tail.poll();
    if (!fresh.length) return;
    const msg = { type: 'sysop_events', gid: tail.gid, events: fresh };
    for (const ws of eventClients) sendLive(ws, msg);
    if (fresh.some((e) => SNAP_TYPES.has(e.type)) && !liveSnapTimer) {
      liveSnapTimer = setTimeout(() => {
        liveSnapTimer = null;
        const snap = buildSnapshot({ type: 'sysop' });
        const h = snapshotHash(snap);
        if (h !== lastBroadcastHash) {
          lastBroadcastHash = h;
          broadcast(snap);
        }
      }, 25);
    }
  }

  function watchLive(tail) {
    if (liveWatcher) { try { liveWatcher.close(); } catch (_) {} liveWatcher = null; }
    liveWatchGid = tail.gid;
    const dir = path.dirname(tail.file);
    try {
      // the folder, not the file: the file may not exist yet when the goal starts
      liveWatcher = fs.watch(dir, { persistent: false }, (_ev, name) => {
        if (!name || name === 'events.jsonl') setImmediate(pumpLive);
      });
      liveWatcher.on('error', () => { try { liveWatcher.close(); } catch (_) {} liveWatcher = null; });
    } catch (_) {
      liveWatcher = null;
    }
  }

  const liveTimer = setInterval(pumpLive, options.liveFallbackMs || 1000);
  if (liveTimer.unref) liveTimer.unref();

  function handleEventsConnection(ws, url) {
    ws._clientId = (url.searchParams.get('clientId') || '').slice(0, 64) || null;
    try { pumpLive(true); } catch (_) {}     // what arrived since the last pump goes to the other pages; this one gets it in its replay
    eventClients.add(ws);
    ws.send(JSON.stringify(buildSnapshot({ type: 'snapshot' })));
    try {
      const tail = sysopLiveTail();
      if (tail) {
        const events = tail.replay(0);
        if (events.length) ws.send(JSON.stringify({ type: 'sysop_events', gid: tail.gid, events, replay: true }));
      }
    } catch (_) {}
    if (typeof hc.refreshTerminals === 'function') hc.refreshTerminals();
    ws.on('close', () => eventClients.delete(ws));
  }

  function stop() {
    clearInterval(sysopTimer);
    clearInterval(liveTimer);
    if (liveSnapTimer) { clearTimeout(liveSnapTimer); liveSnapTimer = null; }
    if (liveWatcher) { try { liveWatcher.close(); } catch (_) {} liveWatcher = null; }
    for (const ws of eventClients) {
      try { ws.close(); } catch (_) {}
    }
  }

  return {
    eventClients,
    getTheme: () => currentTheme,
    setTheme: (name) => { currentTheme = name; },
    refreshTheme: () => { currentTheme = readSavedTheme(); return currentTheme; },
    buildSnapshot,
    broadcast,
    handleEventsConnection,
    stop,
  };
}
