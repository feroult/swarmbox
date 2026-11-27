// HTTP routes for tabs (/api/tabs*) and pinned sessions (/api/pins*).

import fs from 'node:fs';
import { getAgent } from './agents.mjs';
import {
  HOME,
  buildAgentArgv,
  buildPinsSnapshot,
  cleanSessionTitle,
  defaultTitleForPath,
  detectTerminalAgent,
  isHiddenTerminal,
  listInstalledAgents,
  makePinId,
  normalizeAgentName,
  noteRecentDir,
  readActiveTab,
  readPins,
  readSessionPrefs,
  readSysopSnapshot,
  readWorktreePrefs,
  resolveDefaultAgent,
  terminalCwd,
  uniqueTabName,
  writeActiveTab,
  writePins,
  writeSessionPrefs,
} from './hc-client.mjs';
import { enrichTerminalsWithRepo, normRealPath } from './repo-discovery.mjs';
import { readBody, resolveWorktreeTarget, sendJson } from './http-utils.mjs';

// The older titles of a tab (swarmbox.past_titles, a JSON list, newest first), as swarmbox-tabs keeps them (past_titles there): a rename
// from the page records the title it replaces, so a name the Sysop's conversation still uses resolves to the renamed tab.
export const PAST_TITLES = 'swarmbox.past_titles';
const MAX_PAST_TITLES = 4;

export function pastTitles(raw) {
  let val = [];
  try { val = typeof raw === 'string' && raw.trim() ? JSON.parse(raw) : []; } catch (_) { return []; }
  const out = [];
  for (const x of Array.isArray(val) ? val : []) {
    const t = typeof x === 'string' ? x.trim().slice(0, 60) : '';
    if (t && !out.includes(t)) out.push(t);
  }
  return out.slice(0, MAX_PAST_TITLES);
}

export function nextPastTitles(raw, oldTitle, newTitle) {
  const old = String(oldTitle || '').trim().slice(0, 60);
  const newLow = String(newTitle || '').trim().toLowerCase();
  const out = old && old.toLowerCase() !== newLow ? [old] : [];
  for (const x of pastTitles(raw)) {
    if (x.toLowerCase() !== newLow && !out.some((o) => o.toLowerCase() === x.toLowerCase())) out.push(x);
  }
  return out.slice(0, MAX_PAST_TITLES);
}

export async function handleTabAndPinRoutes(req, res, url, pathname, { hc, hub, worktreeHub, runWt }) {
  if (pathname === '/api/tabs' && req.method === 'GET') {
    const resList = await hc.call('terminal.list', { all: false });
    const rawTerminals = (resList.terminals || []).filter((t) => t.state === 'live' && !isHiddenTerminal(t));
    const terminals = enrichTerminalsWithRepo(rawTerminals);
    const pins = buildPinsSnapshot(rawTerminals);
    sendJson(res, 200, {
      terminals,
      active: readActiveTab(),
      sysop: readSysopSnapshot(rawTerminals),
      theme: hub.getTheme(),
      pins,
      worktrees: worktreeHub.pendingWorktreesFor(rawTerminals, pins),
      worktree_prefs: readWorktreePrefs(),
      session_prefs: readSessionPrefs(),
      installed_agents: listInstalledAgents(),
      home: HOME,
    });
    return true;
  }

  if (pathname === '/api/tabs' && req.method === 'POST') {
    const body = await readBody(req);
    const preset = String(body.preset || 'shell');
    let cwd = typeof body.cwd === 'string' && body.cwd.startsWith('/') ? body.cwd : HOME;
    const worktreeChoice = String(body.worktree_choice || '').trim().toLowerCase(); // '' | 'new' | 'same'
    const prefs = readWorktreePrefs();
    const liveTerms = hc.listSnapshot();

    let argv = ['/bin/bash', '-l'];
    let prefix = 'shell';
    let agentKind = 'shell';
    if (preset === 'agent') {
      // A named agent, else the default agent of the box, else `yolo` (which explains in the tab that there is none).
      const defaultAgent = resolveDefaultAgent();
      const requested = String(body.agent || '').trim().toLowerCase();
      const named = requested !== 'yolo' ? normalizeAgentName(requested) : '';
      const cmd = named || (!requested && defaultAgent) || 'yolo';
      agentKind = cmd === 'yolo' ? (defaultAgent || 'yolo') : cmd;
      argv = buildAgentArgv(cmd, body.resume === 'continue' ? 'continue' : 'fresh', process.env, { context: body.context !== false });
      prefix = cmd === 'yolo' ? 'agent' : cmd;
    }

    const labels = {};
    if (agentKind && agentKind !== 'shell') labels['swarmbox.agent'] = agentKind;
    if (preset === 'agent' && body.persist === false) labels['swarmbox.persist'] = 'off';
    let createdWorktree = null;
    const requestedCwd = cwd;

    if (preset === 'agent' && worktreeChoice !== 'same') {
      const collision = await worktreeHub.detectWorkingTreeCollision(cwd, liveTerms);
      if (worktreeChoice === 'new' || (collision && prefs.mode === 'auto')) {
        try {
          const wtRes = await runWt(['create', cwd]);
          cwd = wtRes.path;
          createdWorktree = wtRes;
          labels['swarmbox.worktree'] = wtRes.path;
          labels['swarmbox.branch'] = wtRes.branch;
          labels['swarmbox.base'] = wtRes.base;
          labels['swarmbox.repo'] = wtRes.repo_root;
        } catch (err) {
          sendJson(res, 409, { error: err.code || 'worktree_failed', message: err.message });
          return true;
        }
      } else if (collision && prefs.mode === 'ask') {
        sendJson(res, 409, {
          error: 'worktree_collision',
          message: `${collision.repo_name} already has an active agent on ${collision.branch}`,
          cwd,
          preset,
          agent: agentKind,
          collision,
          prefs,
        });
        return true;
      }
    }

    const customTitle = cleanSessionTitle(body.title);
    if (customTitle) {
      labels['swarmbox.title'] = customTitle;
      labels['swarmbox.title_source'] = body.title_source === 'auto' ? 'auto' : 'user';
    }

    // Option 1: auto-persist open agent sessions so they survive restarts/resets automatically
    // according to the global boot_mode setting (autostart by default; closing with X removes them).
    let autoPin = null;
    if (preset === 'agent' && body.persist !== false) {
      const curPins = readPins();
      const pinId = makePinId(curPins);
      const nowSec = Math.floor(Date.now() / 1000);
      const sprefs = readSessionPrefs();
      const title = customTitle || defaultTitleForPath(cwd, agentKind);
      autoPin = {
        id: pinId,
        title,
        title_source: customTitle ? (body.title_source === 'auto' ? 'auto' : 'user') : '',
        agent: agentKind,
        cwd,
        resume: body.resume === 'fresh' ? 'fresh' : 'continue',
        autostart: sprefs.boot_mode === 'autostart',
        auto: true,
        created_at: nowSec,
        updated_at: nowSec,
      };
      // Unticked "Repository context" in the New agent box: a restart of this pin starts without it too
      if (body.context === false) autoPin.context = false;
      if (createdWorktree) {
        autoPin.worktree = {
          path: createdWorktree.path,
          branch: createdWorktree.branch || '',
          base: createdWorktree.base || '',
          repo: createdWorktree.repo_root || '',
        };
      }
      labels['swarmbox.pin_id'] = pinId;
      if (!labels['swarmbox.title']) labels['swarmbox.title'] = title;
      curPins.push(autoPin);
      writePins(curPins);
    }

    const name = uniqueTabName(body.name || customTitle, prefix, Array.from(hc.terminals.values()));
    const runParams = {
      argv,
      name,
      cwd,
      keep: true,
      no_parent: true,
    };
    if (Object.keys(labels).length > 0) runParams.labels = labels;
    const created = await hc.call('terminal.run', runParams);
    const createdTerm = (created && created.terminal) || created;
    const addr = createdTerm && createdTerm.address;
    if (addr) {
      writeActiveTab(addr);
      hc.terminals.set(addr, createdTerm);
    }
    if (body.cwd) noteRecentDir(requestedCwd);
    if (createdWorktree) worktreeHub.refreshPendingWorktrees();
    hub.broadcast(hub.buildSnapshot({ type: 'snapshot' }));
    const resp = { ...(createdTerm || {}), terminal: createdTerm };
    if (createdWorktree) resp.worktree = createdWorktree;
    if (autoPin) resp.pin = autoPin;
    sendJson(res, 201, resp);
    return true;
  }

  const tabMatch = pathname.match(/^\/api\/tabs\/([^/]+)(?:\/(focus|send|keys|interrupt|answer|worktree))?$/);
  if (tabMatch) {
    const termId = decodeURIComponent(tabMatch[1]);
    const action = tabMatch[2];

    if (!action && req.method === 'PATCH') {
      const body = await readBody(req);
      const title = cleanSessionTitle(body.title);
      if (!title) { sendJson(res, 400, { error: 'bad_title', message: 'title cannot be empty' }); return true; }
      const source = body.title_source === 'auto' ? 'auto' : 'user';
      const known = hc.terminals.get(termId);
      const kl = (known && known.labels) || {};
      const past = nextPastTitles(kl[PAST_TITLES], kl['swarmbox.title'], title);
      const labels = { 'swarmbox.title': title, 'swarmbox.title_source': source };
      if (known && JSON.stringify(past) !== JSON.stringify(pastTitles(kl[PAST_TITLES]))) labels[PAST_TITLES] = past.length ? JSON.stringify(past) : '';
      await hc.call('terminal.label', { terminal: termId, labels });
      const t = hc.terminals.get(termId);
      if (t) {
        t.labels = { ...(t.labels || {}), ...labels };
        const pinId = t.labels['swarmbox.pin_id'];
        if (pinId) {
          const pins = readPins();
          const pin = pins.find((p) => p.id === pinId);
          if (pin) {
            pin.title = title;
            pin.title_source = source;
            pin.updated_at = Math.floor(Date.now() / 1000);
            writePins(pins);
          }
        }
      }
      hub.broadcast(hub.buildSnapshot({ type: 'snapshot' }));
      sendJson(res, 200, { ok: true, terminal: termId, title, title_source: source });
      return true;
    }

    if (!action && req.method === 'DELETE') {
      const t = hc.terminals.get(termId);
      const lbls = (t && t.labels) || {};
      const pinId = lbls['swarmbox.pin_id'] || '';
      const wtPath = lbls['swarmbox.worktree'] || '';
      let pinKept = false;
      if (pinId) {
        const pins = readPins();
        const existingPin = pins.find((p) => p.id === pinId);
        const dropRequested = url.searchParams.get('drop_pin') === '1';
        if (existingPin && (existingPin.auto || dropRequested)) {
          writePins(pins.filter((p) => p.id !== pinId));
        } else if (existingPin) {
          pinKept = true;
        }
      }
      const wtHold = wtPath ? normRealPath(wtPath) : '';
      if (wtHold) worktreeHub.closingWorktrees.add(wtHold);
      let autoCleaned = false;
      try {
        await worktreeHub.closeTerminalCleanly(termId);
        // Auto-clean empty managed worktrees on close when no parked pin holds them
        if (!pinKept && wtPath) {
          try {
            const st = await runWt(['status', wtPath]);
            if (st && st.managed && st.empty) {
              await runWt(['remove', wtPath]);
              autoCleaned = true;
              worktreeHub.forgetCachedWorktree(wtPath, wtHold);
            }
          } catch (_) {}
        }
      } finally {
        if (wtHold) worktreeHub.closingWorktrees.delete(wtHold);
      }
      worktreeHub.refreshPendingWorktrees();
      hub.broadcast(hub.buildSnapshot({ type: 'snapshot' }));
      sendJson(res, 200, { ok: true, pinned: pinKept, auto_cleaned_worktree: autoCleaned });
      return true;
    }

    if (action === 'worktree' && req.method === 'GET') {
      const { target, terminal: t } = resolveWorktreeTarget('', termId, hc);
      if (!t) { sendJson(res, 404, { error: 'no_such_tab', message: 'tab not found' }); return true; }
      try {
        const st = await runWt(['status', target]);
        sendJson(res, 200, st);
      } catch (err) {
        sendJson(res, 404, { error: err.code || 'not_a_worktree', message: err.message });
      }
      return true;
    }

    if (action === 'focus' && req.method === 'POST') {
      writeActiveTab(termId);
      sendJson(res, 200, { ok: true, active: termId });
      return true;
    }

    if (action === 'send' && req.method === 'POST') {
      const body = await readBody(req);
      const r = await hc.call('terminal.send', {
        terminal: termId,
        text: String(body.text || ''),
        force: Boolean(body.force),
      });
      sendJson(res, 200, r);
      return true;
    }

    if (action === 'answer' && req.method === 'POST') {
      // The Allow / Cancel card of a blocked agent: the keys its agent.conf declares (ANSWER_ALLOW, ANSWER_DENY: hc key names), pressed
      // as keys. An agent that declares none is answered in its own terminal, never with a guess: a typed `n` and Enter confirm the
      // highlighted option of a menu, which in a permission dialog is the one that allows (measured with Claude Code 2.1).
      const body = await readBody(req);
      if (typeof body.text === 'string') {
        const r = await hc.call('terminal.send', { terminal: termId, text: body.text, force: true });
        sendJson(res, 200, { ok: true, result: r });
        return true;
      }
      const aid = detectTerminalAgent(hc.terminals.get(termId));
      const a = aid ? getAgent(aid) : null;
      const keys = a ? (body.decision === 'allow' ? a.answer.allow : a.answer.deny) : [];
      if (!keys.length) {
        sendJson(res, 409, { error: 'no_answer_keys', message: 'this agent does not say how its dialog is answered: answer it in its terminal' });
        return true;
      }
      const r = await hc.call('terminal.keys', { terminal: termId, keys });
      sendJson(res, 200, { ok: true, result: r, keys });
      return true;
    }

    if (action === 'keys' && req.method === 'POST') {
      const body = await readBody(req);
      const keys = Array.isArray(body.keys) ? body.keys.map(String) : [];
      const r = await hc.call('terminal.keys', { terminal: termId, keys });
      sendJson(res, 200, r);
      return true;
    }

    if (action === 'interrupt' && req.method === 'POST') {
      const r = await hc.call('terminal.interrupt', { terminal: termId, timeout: 2 });
      sendJson(res, 200, r);
      return true;
    }
  }

  // -------------------------------------------------------------------------
  // Pinned Sessions API (/api/pins)
  // -------------------------------------------------------------------------
  if (pathname === '/api/pins' && req.method === 'GET') {
    const pins = buildPinsSnapshot(hc.listSnapshot());
    sendJson(res, 200, { pins });
    return true;
  }

  if (pathname === '/api/pins' && req.method === 'POST') {
    const body = await readBody(req);
    const pins = readPins();
    const nowSec = Math.floor(Date.now() / 1000);
    if (body.terminal) {
      const tid = String(body.terminal);
      const t = hc.terminals.get(tid);
      if (!t) { sendJson(res, 404, { error: 'no_such_tab', message: 'tab not found' }); return true; }
      const lbls = t.labels || {};
      const existingId = lbls['swarmbox.pin_id'];
      if (existingId) {
        const existing = pins.find((p) => p.id === existingId);
        if (existing) { sendJson(res, 200, { ok: true, pin: existing, pins: buildPinsSnapshot(hc.listSnapshot()) }); return true; }
      }
      const cwd = terminalCwd(t);
      const agent = detectTerminalAgent(t) || 'shell';
      const title = cleanSessionTitle(body.title || lbls['swarmbox.title']) || defaultTitleForPath(cwd, agent);
      const titleSource = body.title ? 'user' : (lbls['swarmbox.title_source'] || '');
      const pinId = makePinId(pins);
      const rec = {
        id: pinId,
        title,
        title_source: titleSource,
        agent,
        cwd,
        resume: body.resume === 'fresh' ? 'fresh' : 'continue',
        autostart: Boolean(body.autostart),
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
      } else {
        try {
          const inf = await runWt(['inspect', cwd]);
          if (inf && inf.is_git && inf.is_worktree) {
            rec.worktree = {
              path: inf.worktree_path,
              branch: inf.branch || '',
              base: inf.base || '',
              repo: inf.repo_root || '',
            };
          }
        } catch (_) {}
      }
      pins.push(rec);
      writePins(pins);
      const newLabels = {
        'swarmbox.pin_id': pinId,
        'swarmbox.title': title,
        'swarmbox.agent': agent,
      };
      if (titleSource) newLabels['swarmbox.title_source'] = titleSource;
      if (rec.worktree) {
        newLabels['swarmbox.worktree'] = rec.worktree.path;
        if (rec.worktree.branch) newLabels['swarmbox.branch'] = rec.worktree.branch;
        if (rec.worktree.base) newLabels['swarmbox.base'] = rec.worktree.base;
        if (rec.worktree.repo) newLabels['swarmbox.repo'] = rec.worktree.repo;
      }
      await hc.call('terminal.label', { terminal: tid, labels: newLabels });
      t.labels = { ...(t.labels || {}), ...newLabels };
      hub.broadcast(hub.buildSnapshot({ type: 'snapshot' }));
      sendJson(res, 201, { ok: true, pin: rec, pins: buildPinsSnapshot(hc.listSnapshot()) });
      return true;
    }
    const cwd = typeof body.cwd === 'string' && body.cwd.startsWith('/') ? body.cwd : HOME;
    // an agent is stored by its id; yolo as the default agent it runs (a pin keeps its agent), or as yolo when the box has none
    const agent = normalizeAgentName(body.agent) || (body.agent === 'yolo' ? resolveDefaultAgent() || 'yolo' : 'shell');
    const title = cleanSessionTitle(body.title) || defaultTitleForPath(cwd, agent);
    const rec = {
      id: makePinId(pins),
      title,
      title_source: body.title ? 'user' : '',
      agent,
      cwd,
      resume: body.resume === 'fresh' ? 'fresh' : 'continue',
      autostart: Boolean(body.autostart),
      created_at: nowSec,
      updated_at: nowSec,
    };
    pins.push(rec);
    writePins(pins);
    hub.broadcast(hub.buildSnapshot({ type: 'snapshot' }));
    sendJson(res, 201, { ok: true, pin: rec, pins: buildPinsSnapshot(hc.listSnapshot()) });
    return true;
  }

  if (pathname === '/api/pins/prefs' && req.method === 'GET') {
    sendJson(res, 200, { prefs: readSessionPrefs() });
    return true;
  }
  if (pathname === '/api/pins/prefs' && req.method === 'PATCH') {
    const body = await readBody(req);
    try {
      const prefs = writeSessionPrefs(body);
      hub.broadcast(hub.buildSnapshot({ type: 'snapshot' }));
      sendJson(res, 200, { ok: true, prefs, pins: buildPinsSnapshot(hc.listSnapshot()) });
    } catch (err) {
      sendJson(res, 400, { error: 'bad_prefs', message: err.message });
    }
    return true;
  }

  const pinMatch = pathname.match(/^\/api\/pins\/([^/]+)(?:\/(wake))?$/);
  if (pinMatch) {
    const pinId = decodeURIComponent(pinMatch[1]);
    const pinAction = pinMatch[2];

    if (!pinAction && req.method === 'PATCH') {
      const body = await readBody(req);
      const pins = readPins();
      const pin = pins.find((p) => p.id === pinId);
      if (!pin) { sendJson(res, 404, { error: 'no_such_pin', message: 'pin not found' }); return true; }
      if (body.title !== undefined) {
        const clean = cleanSessionTitle(body.title);
        if (!clean) { sendJson(res, 400, { error: 'bad_title', message: 'title cannot be empty' }); return true; }
        pin.title = clean;
        pin.title_source = body.title_source === 'auto' ? 'auto' : 'user';
      }
      if (body.autostart !== undefined) pin.autostart = Boolean(body.autostart);
      if (body.resume === 'continue' || body.resume === 'fresh') pin.resume = body.resume;
      pin.updated_at = Math.floor(Date.now() / 1000);
      writePins(pins);
      // Sync title to any live terminal bound to this pin
      for (const t of hc.listSnapshot()) {
        if (t.labels && t.labels['swarmbox.pin_id'] === pinId && body.title !== undefined) {
          const upd = { 'swarmbox.title': pin.title, 'swarmbox.title_source': pin.title_source || 'user' };
          hc.call('terminal.label', { terminal: t.address, labels: upd }).catch(() => {});
          t.labels = { ...t.labels, ...upd };
        }
      }
      hub.broadcast(hub.buildSnapshot({ type: 'snapshot' }));
      sendJson(res, 200, { ok: true, pin, pins: buildPinsSnapshot(hc.listSnapshot()) });
      return true;
    }

    if (!pinAction && req.method === 'DELETE') {
      const pins = readPins();
      const kept = pins.filter((p) => p.id !== pinId);
      if (kept.length === pins.length) { sendJson(res, 404, { error: 'no_such_pin', message: 'pin not found' }); return true; }
      writePins(kept);
      for (const t of hc.listSnapshot()) {
        if (t.labels && t.labels['swarmbox.pin_id'] === pinId) {
          hc.call('terminal.label', { terminal: t.address, labels: { 'swarmbox.pin_id': '' } }).catch(() => {});
          delete t.labels['swarmbox.pin_id'];
        }
      }
      hub.broadcast(hub.buildSnapshot({ type: 'snapshot' }));
      sendJson(res, 200, { ok: true, pins: buildPinsSnapshot(hc.listSnapshot()) });
      return true;
    }

    if (pinAction === 'wake' && req.method === 'POST') {
      const body = await readBody(req);
      const pins = readPins();
      const pin = pins.find((p) => p.id === pinId);
      if (!pin) { sendJson(res, 404, { error: 'no_such_pin', message: 'pin not found' }); return true; }
      const liveTerms = hc.listSnapshot();
      const already = liveTerms.find((t) => t.labels && t.labels['swarmbox.pin_id'] === pinId);
      if (already) {
        writeActiveTab(already.address);
        sendJson(res, 200, { ok: true, terminal: already, already_live: true });
        return true;
      }
      let cwd = pin.cwd || HOME;
      if (!fs.existsSync(cwd)) {
        sendJson(res, 409, { error: 'missing_cwd', message: `Directory no longer exists: ${cwd}` });
        return true;
      }
      const worktreeChoice = String(body.worktree_choice || '').trim().toLowerCase();
      const prefs = readWorktreePrefs();
      let resumeMode = pin.resume || 'continue';
      let createdWorktree = null;
      const labels = {
        'swarmbox.pin_id': pin.id,
        'swarmbox.title': pin.title || defaultTitleForPath(cwd, pin.agent),
        'swarmbox.agent': pin.agent || 'shell',
      };
      if (pin.title_source) labels['swarmbox.title_source'] = pin.title_source;
      if (pin.worktree && pin.worktree.path) {
        labels['swarmbox.worktree'] = pin.worktree.path;
        if (pin.worktree.branch) labels['swarmbox.branch'] = pin.worktree.branch;
        if (pin.worktree.base) labels['swarmbox.base'] = pin.worktree.base;
        if (pin.worktree.repo) labels['swarmbox.repo'] = pin.worktree.repo;
      }

      if (pin.agent && pin.agent !== 'shell' && worktreeChoice !== 'same') {
        const collision = await worktreeHub.detectWorkingTreeCollision(cwd, liveTerms);
        if (worktreeChoice === 'new' || (collision && prefs.mode === 'auto')) {
          try {
            const wtRes = await runWt(['create', cwd]);
            cwd = wtRes.path;
            createdWorktree = wtRes;
            // A brand-new worktree path has no prior conversation for --continue
            resumeMode = 'fresh';
            // Open as an isolated tab without overwriting the pin's original binding
            delete labels['swarmbox.pin_id'];
            labels['swarmbox.worktree'] = wtRes.path;
            labels['swarmbox.branch'] = wtRes.branch;
            labels['swarmbox.base'] = wtRes.base;
            labels['swarmbox.repo'] = wtRes.repo_root;
          } catch (err) {
            sendJson(res, 409, { error: err.code || 'worktree_failed', message: err.message });
            return true;
          }
        } else if (collision && prefs.mode === 'ask') {
          sendJson(res, 409, {
            error: 'worktree_collision',
            message: `${collision.repo_name} already has an active agent on ${collision.branch}`,
            pin_id: pin.id,
            cwd,
            collision,
            prefs,
          });
          return true;
        }
      }

      const argv = buildAgentArgv(pin.agent || 'shell', resumeMode, process.env, { context: pin.context !== false });
      const name = uniqueTabName(pin.title, pin.agent || 'pin', Array.from(hc.terminals.values()));
      const created = await hc.call('terminal.run', {
        argv,
        name,
        cwd,
        keep: true,
        no_parent: true,
        labels,
      });
      const createdTerm = (created && created.terminal) || created;
      const addr = createdTerm && createdTerm.address;
      if (addr) {
        writeActiveTab(addr);
        hc.terminals.set(addr, createdTerm);
      }
      if (createdWorktree) worktreeHub.refreshPendingWorktrees();
      hub.broadcast(hub.buildSnapshot({ type: 'snapshot' }));
      const resp = { ...(createdTerm || {}), terminal: createdTerm };
      if (createdWorktree) resp.worktree = createdWorktree;
      sendJson(res, 201, resp);
      return true;
    }
  }

  return false;
}
