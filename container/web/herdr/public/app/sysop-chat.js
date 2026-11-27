// Sysop chat panel: approval & question cards, notifications, tab-ref chips, markdown reply renderer, live goal streaming & BBS glow, feed, queue, and status strip.

import { state, dom, actions } from './state.js';
import { ICO_CLOCK_SVG, ICO_BOLT_SVG, tabDisplayName, tabAgentKind, pixelIconHtml, makeMiniPixelIcon } from './icons.js';
import { showTermToast } from './ui-chrome.js';
import { phase, fmtAgo, syncContext } from './sysop-context.js';
import { showSysopEvents, renderEvents } from './sysop-events.js';

const requestFitAndResize = () => {
  requestAnimationFrame(() => {
    if (typeof actions.fitAndResize === 'function') actions.fitAndResize();
  });
};

export function stopCountdownTimer() {
  if (state.countdownTimer) {
    clearInterval(state.countdownTimer);
    state.countdownTimer = null;
  }
}

export function renderApprovalCard(sysop) {
  stopCountdownTimer();
  const pending = sysop && sysop.pending;

  if (pending) {
    const isVeto = pending.mode === 'veto';
    state.currentApproval = { kind: 'sysop', deadline: pending.deadline };
    dom.approvalCardEl.classList.remove('hidden');
    dom.mobileApprovalEl.classList.remove('hidden');
    const badge = isVeto ? 'Sending…' : 'Confirm action';
    dom.approvalBadgeEl.textContent = badge;
    dom.mobileApprovalBadgeEl.textContent = badge;
    const pendingTabObj = pending.tab ? state.terminals.find((t) => t.address === pending.tab) : null;
    dom.approvalTabEl.textContent = pendingTabObj ? tabDisplayName(pendingTabObj) : (pending.label || pending.tab || 'sysop');
    dom.approvalTextEl.textContent = pending.text || 'Pending action';
    dom.mobileApprovalMsgEl.textContent = pending.text || 'Pending action';

    if (pending.deadline) {
      const rem = Math.max(0, pending.deadline - Date.now() / 1000);
      const total = Math.max(rem, 4);
      dom.approvalBarEl.classList.remove('hidden');
      const tick = () => {
        const left = Math.max(0, pending.deadline - Date.now() / 1000);
        dom.approvalBarFillEl.style.width = `${Math.min(100, (left / total) * 100)}%`;
        if (left <= 0) stopCountdownTimer();
      };
      tick();
      state.countdownTimer = setInterval(tick, 150);
    } else {
      dom.approvalBarEl.classList.add('hidden');
    }

    requestFitAndResize();
    return;
  }

  const wasVisible = !dom.mobileApprovalEl.classList.contains('hidden');
  state.currentApproval = null;
  dom.approvalCardEl.classList.add('hidden');
  dom.mobileApprovalEl.classList.add('hidden');
  dom.approvalBarEl.classList.add('hidden');
  if (wasVisible) requestFitAndResize();
}

// ---- A question of the Sysop (its brain's `ask`, docs/sysop-automations-design.md 4): a button per option, or an answer of your own
let shownQuestionId = '';
let questionTimer = null;

export function renderQuestionCard(sysop) {
  if (!dom.questionCardEl) return;
  const q = sysop && sysop.question;
  if (!q) {
    if (shownQuestionId) {
      shownQuestionId = '';
      dom.questionCardEl.classList.add('hidden');
      clearInterval(questionTimer);
      requestFitAndResize();
    }
    return;
  }
  if (q.id === shownQuestionId && !dom.questionCardEl.classList.contains('hidden')) return;
  shownQuestionId = q.id;
  dom.questionTextEl.textContent = q.question;
  dom.questionOptionsEl.innerHTML = '';
  for (const opt of q.options || []) {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'question-opt';
    b.textContent = opt;
    b.addEventListener('click', () => sendAnswer(q.id, opt));
    dom.questionOptionsEl.appendChild(b);
  }
  dom.questionOptionsEl.classList.toggle('hidden', !(q.options || []).length);
  dom.questionInputEl.value = '';
  dom.questionCardEl.classList.remove('hidden');
  clearInterval(questionTimer);
  const tick = () => {
    const left = Math.max(0, Math.round(q.deadline - Date.now() / 1000));
    dom.questionLeftEl.textContent = left > 90 ? `${Math.ceil(left / 60)} min left` : `${left}s left`;
    if (left <= 0) clearInterval(questionTimer);
  };
  tick();
  questionTimer = setInterval(tick, 1000);
  if (typeof actions.isMobileLayout === 'function' && actions.isMobileLayout()) {
    if (typeof actions.setMobileSysop === 'function') actions.setMobileSysop(true);
  }
  requestFitAndResize();
}

export async function sendAnswer(id, text) {
  const answer = String(text || '').trim();
  if (!answer) return;
  const r = await fetch('/api/sysop/answer', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ id, answer }) });
  if (!r.ok) {
    const data = await r.json().catch(() => ({}));
    showTermToast(data.message || 'The question is no longer waiting', 'error', 4000);
    return;
  }
  dom.questionCardEl.classList.add('hidden');
  shownQuestionId = id;      // hidden until the snapshot drops it (or a new question comes)
  clearInterval(questionTimer);
  requestFitAndResize();
}

// ---- Notifications of the Sysop (its brain's `notify`): a toast in every open Web Studio, and the browser's notification when it is allowed
// (Settings -> Sysop) and the page is not in front. Each one once per page: the newest time seen is kept in this browser.
const NOTIFY_SEEN_KEY = 'sb.sysop.notifySeen';
let notifySeen = -1;
try { notifySeen = Number(localStorage.getItem(NOTIFY_SEEN_KEY) || '-1'); } catch (_) { notifySeen = -1; }

export function handleNotifications(sysop) {
  const evs = (Array.isArray(sysop && sysop.events) ? sysop.events : []).filter((e) => e && e.kind === 'notify');
  if (!evs.length) return;
  const newest = Math.max(...evs.map((e) => e.ts || 0));
  // the first look of this browser shows only what is very recent, not the backlog of the last hours
  const floor = notifySeen < 0 ? Date.now() - 2 * 60 * 1000 : notifySeen;
  const fresh = evs.filter((e) => (e.ts || 0) > floor && Date.now() - (e.ts || 0) < 10 * 60 * 1000).sort((a, b) => a.ts - b.ts);
  if (newest > notifySeen) {
    notifySeen = newest;
    try { localStorage.setItem(NOTIFY_SEEN_KEY, String(newest)); } catch (_) {}
  }
  for (const ev of fresh) showSysopNotice(ev);
}

export function showSysopNotice(ev) {
  const urgent = ev.level === 'urgent';
  showTermToast(`Sysop: ${ev.text}`, urgent ? 'error' : (ev.level === 'warn' ? 'warn' : 'ok'), urgent ? 0 : 9000);
  try {
    if ('Notification' in window && Notification.permission === 'granted' && (document.hidden || !document.hasFocus())) {
      const n = new Notification('Sysop', { body: ev.text, tag: ev.id, requireInteraction: urgent });
      n.onclick = () => { window.focus(); showSysopEvents(); n.close(); };
    }
  } catch (_) {}
}

// ---- Sysop conversation (V2): one turn per goal, no nested boxes. The user's words in a bubble, the sysop's reply as plain text under a
// "Sysop · N actions" line, and an action that waits for the user as a calm confirmation card inside the conversation.
const openTurnActions = new Set();   // turn ids whose action list the user expanded (survives the 600 ms re-renders)
let lastFeedKey = '';
const SYSOP_SUGGESTIONS = ["What's running across my tabs?", 'Summarize the active agent', 'Check git status & tests'];
const STATE_WORDS = { idle: 'ready', 'allow?': 'confirm', sending: 'sending', working: 'working', queued: 'queued', done: 'ready', failed: 'failed', stopped: 'ready', off: 'off' };
const MIC_SVG = '<svg viewBox="0 0 24 24" width="11" height="11" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/></svg>';

// Every tab a reply names (`shop-api`, t3, 1:shop-api, "shop-api (t3)") becomes the same chip: the agent's pixel icon and the tab's name.
// tabrefs.js finds them; a tab that has closed since keeps its name (the page remembers the tabs it saw) and is drawn dimmed, without a link.
const KNOWN_TABS_KEY = 'sb.sysop.knownTabs';
let knownTabs = {};
try { knownTabs = JSON.parse(localStorage.getItem(KNOWN_TABS_KEY) || '{}') || {}; } catch (_) { knownTabs = {}; }

export function getKnownTab(addr) {
  return addr ? (knownTabs[addr] || null) : null;
}

export function rememberTabs() {
  let changed = false;
  for (const t of state.terminals) {
    if (!t || !t.address) continue;
    const rec = { name: tabDisplayName(t), alias: String(t.name || ''), kind: tabAgentKind(t) || 'shell' };
    const old = knownTabs[t.address];
    if (!old || old.name !== rec.name || old.kind !== rec.kind || old.alias !== rec.alias) {
      knownTabs[t.address] = rec;
      changed = true;
    }
  }
  if (!changed) return;
  const keys = Object.keys(knownTabs);
  for (const k of keys.slice(0, Math.max(0, keys.length - 80))) delete knownTabs[k];
  try { localStorage.setItem(KNOWN_TABS_KEY, JSON.stringify(knownTabs)); } catch (_) {}
}

export function tabRefContext() {
  const live = new Set();
  const out = [];
  for (const t of state.terminals) {
    if (!t || !t.address) continue;
    live.add(t.address);
    out.push({ address: t.address, name: tabDisplayName(t), aliases: t.name ? [String(t.name)] : [], kind: tabAgentKind(t) || 'shell', live: true });
  }
  for (const [address, rec] of Object.entries(knownTabs)) {
    if (!live.has(address)) out.push({ address, name: rec.name, aliases: rec.alias ? [rec.alias] : [], kind: rec.kind, live: false });
  }
  return out;
}

export function tabChip(tab) {
  const chip = document.createElement('span');
  chip.className = `tab-ref${tab.live ? '' : ' closed'}`;
  chip.appendChild(makeMiniPixelIcon(tab.kind || 'shell'));
  const name = document.createElement('span');
  name.className = 'tab-ref-name';
  name.textContent = tab.name;
  chip.appendChild(name);
  if (!tab.live) {
    chip.title = tab.unknown ? 'Tab no longer open' : `${tab.name} is closed`;
    return chip;
  }
  chip.title = `Switch to ${tab.name}`;
  chip.setAttribute('role', 'button');
  chip.tabIndex = 0;
  const go = () => {
    if (state.activeId !== tab.address) {
      if (typeof actions.connectPty === 'function') actions.connectPty(tab.address);
    } else if (typeof actions.focusTerminalIfDesktop === 'function') {
      actions.focusTerminalIfDesktop();
    }
  };
  chip.addEventListener('click', go);
  chip.addEventListener('keydown', (ev) => {
    if (ev.key === 'Enter' || ev.key === ' ') {
      ev.preventDefault();
      go();
    }
  });
  return chip;
}

export function linkTabs(text) {
  const frag = document.createDocumentFragment();
  const segs = window.SbTabRefs ? window.SbTabRefs.parse(text, tabRefContext()) : [{ t: 'text', v: String(text || '') }];
  const getCwd = () => (typeof actions.terminalCwdFor === 'function' ? actions.terminalCwdFor(state.activeId) : '');
  for (let i = 0; i < segs.length; i++) {
    const seg = segs[i];
    if (seg.t === 'tab') {
      // a parenthesis around a chip stays on its line: "(" + chip + ")" never breaks apart
      const prev = frag.lastChild;
      const next = segs[i + 1];
      const glue = document.createElement('span');
      glue.className = 'tab-ref-glue';
      if (prev && prev.nodeType === 3 && /\($/.test(prev.data)) {
        prev.data = prev.data.slice(0, -1);
        glue.append('(');
      }
      glue.appendChild(tabChip(seg.tab));
      if (next && next.t === 'text' && /^[),.;:]/.test(next.v)) {
        glue.append(next.v[0]);
        next.v = next.v.slice(1);
      }
      frag.appendChild(glue.childNodes.length > 1 ? glue : glue.firstChild);
    } else if (seg.t === 'text') {
      if (window.PathLinks) {
        const pMatches = window.PathLinks.extractPathMatches(seg.v);
        if (pMatches.length) {
          let pos = 0;
          for (const pm of pMatches) {
            if (pm.start > pos) frag.append(seg.v.slice(pos, pm.start));
            const chip = document.createElement('button');
            chip.type = 'button';
            chip.className = 'sysop-file-chip';
            chip.textContent = pm.text;
            chip.title = 'Preview ' + pm.text + ' (Ctrl/Cmd+Click for new tab)';
            chip.addEventListener('click', (ev) => {
              ev.preventDefault();
              if (typeof actions.openFilePreview === 'function') {
                actions.openFilePreview(pm.text, { cwd: getCwd(), newTab: Boolean(ev.ctrlKey || ev.metaKey || ev.button === 1) });
              }
            });
            frag.appendChild(chip);
            pos = pm.end;
          }
          if (pos < seg.v.length) frag.append(seg.v.slice(pos));
          continue;
        }
      }
      frag.append(seg.v);
    } else if (seg.t === 'code' && window.PathLinks && window.PathLinks.extractPathMatches(seg.v).length === 1 && window.PathLinks.extractPathMatches(seg.v)[0].text === seg.v.trim()) {
      const chip = document.createElement('button');
      chip.type = 'button';
      chip.className = 'sysop-file-chip';
      chip.textContent = seg.v;
      chip.title = 'Preview ' + seg.v + ' (Ctrl/Cmd+Click for new tab)';
      chip.addEventListener('click', (ev) => {
        ev.preventDefault();
        if (typeof actions.openFilePreview === 'function') {
          actions.openFilePreview(seg.v.trim(), { cwd: getCwd(), newTab: Boolean(ev.ctrlKey || ev.metaKey || ev.button === 1) });
        }
      });
      frag.appendChild(chip);
    } else {
      const tag = seg.t === 'code' ? 'code' : seg.t === 'bold' ? 'strong' : 'span';
      const el = document.createElement(tag);
      if (tag === 'span') el.className = `tr-${seg.t}`;
      el.textContent = seg.v;
      frag.appendChild(el);
    }
  }
  return frag;
}

// Rich Markdown rendering: fenced code blocks, headings, "- item" lists (with agent pixel icons), inline bold/code & clickable tab chips
export function renderReplyText(text, streaming = false) {
  const wrap = document.createElement('div');
  wrap.className = 'turn-reply';
  let list = null;
  let inFence = false;
  let fenceLines = [];
  const flushFence = () => {
    if (!fenceLines.length) return;
    const pre = document.createElement('pre');
    const code = document.createElement('code');
    code.textContent = fenceLines.join('\n');
    pre.appendChild(code);
    wrap.appendChild(pre);
    fenceLines = [];
  };
  for (const raw of String(text || '').split('\n')) {
    const trimmed = raw.trim();
    if (trimmed.startsWith('```')) {
      list = null;
      if (inFence) {
        flushFence();
        inFence = false;
      } else {
        inFence = true;
        fenceLines = [];
      }
      continue;
    }
    if (inFence) {
      fenceLines.push(raw);
      continue;
    }
    const line = trimmed;
    if (!line) {
      list = null;
      continue;
    }
    const heading = /^#{1,4}\s+(.*)$/.exec(line);
    if (heading) {
      list = null;
      const h = document.createElement('h4');
      h.appendChild(linkTabs(heading[1]));
      wrap.appendChild(h);
      continue;
    }
    const bullet = /^[-•*]\s+(.*)$/.exec(line);
    if (bullet) {
      if (!list) {
        list = document.createElement('ul');
        wrap.appendChild(list);
      }
      const li = document.createElement('li');
      const frag = linkTabs(bullet[1].replace(/^(`[^`]+`|[t@]\d[a-z0-9]{0,3}|\d+:[\w.-]+)\s*:\s*/i, '$1 '));
      let first = frag.firstChild;
      if (first && first.nodeType === 1 && first.classList.contains('tab-ref-glue') && first.firstChild && first.firstChild.nodeType === 1
        && first.firstChild.classList.contains('tab-ref') && /^[:–—-]?$/.test(first.textContent.slice(first.firstChild.textContent.length))) {
        const chip = first.firstChild;
        frag.replaceChild(chip, first);       // "chip:" at the head of a row: the row is the chip, the colon goes
        first = chip;
      }
      const lead = first && first.nodeType === 1 && first.classList.contains('tab-ref') ? first : null;
      const rest = document.createElement('span');     // one flex item, so inline code in it flows with the text
      if (lead) {
        li.appendChild(lead);
        // "`name` (t3): text" left a colon behind the chip: the row already says whose it is
        const t0 = frag.firstChild;
        if (t0 && t0.nodeType === 3) t0.data = t0.data.replace(/^\s*[:–—-]\s*/, ' ').replace(/^\s+/, '');
      }
      rest.appendChild(frag);
      li.appendChild(rest);
      list.appendChild(li);
    } else {
      list = null;
      const pEl = document.createElement('p');
      pEl.appendChild(linkTabs(line));
      wrap.appendChild(pEl);
    }
  }
  if (inFence) flushFence();
  if (streaming) {
    const cur = document.createElement('span');
    cur.className = 'turn-stream-cursor';
    cur.setAttribute('aria-hidden', 'true');
    const last = wrap.lastElementChild;
    if (last && (last.tagName === 'P' || last.tagName === 'H4')) last.appendChild(cur);
    else if (last && last.tagName === 'UL' && last.lastElementChild) last.lastElementChild.appendChild(cur);
    else wrap.appendChild(cur);
  }
  return wrap;
}

// ---- The running goal, live (docs/sysop-brain-design.md 4.5): a reducer over the goal's events (sysop_events from the gateway, in seq
// order), drawn into the running turn only. What the model chose, typed, waits for and wrote shows as it happens; a burst of text is
// revealed at a steady pace that catches up within a few hundred milliseconds. The snapshot keeps the finished turns.
const Live = typeof window !== 'undefined' ? window.SbSysopLive : null;          // public/sysoplive.js: the reducer (pure, tested in Node)
const BBS_GLOW_MS = 560;
const liveGoals = new Map();     // gid -> the reducer's state of that goal
const liveGlow = new Map();      // `${gid}:note:${i}` | `${gid}:reply` -> { len, spans: [{ from, to, at }] }
const liveGlowReplay = new Set(); // gids whose next render skips glow (replay on connect)
const lastTurns = new Map();     // gid -> the snapshot's turn (prompt, started) for a redraw between snapshots
const liveTurnParts = (g, turn) => Live.parts(g, turn && turn.live_action);
const liveLine = (g, turn) => Live.line(g, turn && turn.live_action);

function clearLiveGlow(gid) {
  const prefix = `${gid}:`;
  for (const k of Array.from(liveGlow.keys())) {
    if (k.startsWith(prefix)) liveGlow.delete(k);
  }
  liveGlowReplay.delete(gid);
}

// BBS Afterglow: wrap freshly revealed text ranges in .bbs-glow with negative animation-delay so the 3-stage
// phosphor decay (#fff -> --accent-bright -> normal) runs smoothly across Markdown redraws and leaves cooled text as plain text nodes.
export function applyBbsGlow(root, key, skip) {
  if (!root) return;
  const now = performance.now();
  const totalLen = root.textContent.length;
  const entry = Live.glowStep(liveGlow.get(key), totalLen, now, BBS_GLOW_MS, skip || document.visibilityState === 'hidden');
  liveGlow.set(key, entry);
  if (!entry.spans.length) return;

  const nodes = [];
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  let cur;
  while ((cur = walker.nextNode())) {
    if (cur.parentElement && cur.parentElement.classList.contains('turn-stream-cursor')) continue;
    if (cur.nodeValue) nodes.push(cur);
  }

  let pos = 0;
  for (const tn of nodes) {
    const txt = tn.nodeValue;
    const start = pos;
    const end = start + txt.length;
    pos = end;

    let overlaps = null;
    for (const s of entry.spans) {
      const a = Math.max(start, s.from);
      const b = Math.min(end, s.to);
      if (a < b) {
        if (!overlaps) overlaps = [];
        overlaps.push({ a: a - start, b: b - start, at: s.at });
      }
    }
    if (!overlaps) continue;

    const frag = document.createDocumentFragment();
    let idx = 0;
    for (const ov of overlaps) {
      if (ov.a > idx) frag.appendChild(document.createTextNode(txt.slice(idx, ov.a)));
      const span = document.createElement('span');
      span.className = 'bbs-glow';
      span.style.animationDelay = `${-Math.max(0, now - ov.at).toFixed(1)}ms`;
      span.textContent = txt.slice(ov.a, ov.b);
      frag.appendChild(span);
      idx = ov.b;
    }
    if (idx < txt.length) frag.appendChild(document.createTextNode(txt.slice(idx)));
    tn.replaceWith(frag);
  }
}

let livePaceRaf = 0;
export function paceLive() {
  livePaceRaf = 0;
  let more = false;
  const hidden = document.visibilityState === 'hidden';
  for (const [gid, g] of liveGoals) {
    const r = Live.pace(g, hidden);
    if (r.more) more = true;
    if (r.changed) redrawLiveTurn(gid);
  }
  if (more) livePaceRaf = requestAnimationFrame(paceLive);
}

export function scheduleLive(gid) {
  redrawLiveTurn(gid);
  if (!livePaceRaf) livePaceRaf = requestAnimationFrame(paceLive);
}

export function onSysopEvents(msg) {
  const gid = String(msg.gid || '');
  if (!gid || !Array.isArray(msg.events)) return;
  if (msg.replay || !liveGoals.has(gid)) {
    liveGoals.set(gid, Live.goal());
    clearLiveGlow(gid);
  }
  const g = liveGoals.get(gid);
  const before = g.seq;
  for (const ev of msg.events) Live.apply(g, ev);
  if (msg.replay) {
    Live.showAll(g);     // what already happened is shown at once
    liveGlowReplay.add(gid);
  }
  if (g.seq !== before || msg.replay) scheduleLive(gid);
}

// draw the running turn of `gid` again, in place (the approval card, which lives inside it, is moved into the new one)
export function redrawLiveTurn(gid) {
  if (!dom.sysopFeedEl) return;
  const old = Array.from(dom.sysopFeedEl.querySelectorAll('.turn.running')).find((el) => el.dataset.gid === gid);
  const turn = lastTurns.get(gid);
  if (!old || !turn) return;
  const nearBottom = dom.sysopFeedEl.scrollHeight - dom.sysopFeedEl.scrollTop - dom.sysopFeedEl.clientHeight < 48;
  const fresh = renderTurn(turn);
  const hadCard = dom.approvalCardEl && old.contains(dom.approvalCardEl);
  old.replaceWith(fresh);
  if (hadCard) {
    const host = fresh.querySelector('.turn-sysop');
    if (host) host.appendChild(dom.approvalCardEl);
  }
  if (nearBottom) dom.sysopFeedEl.scrollTop = dom.sysopFeedEl.scrollHeight;
  const g = liveGoals.get(gid);
  if (g && dom.sysopLiveStripTextEl && state.sysopRunning) {
    const elapsed = turn.started ? Math.max(0, Math.floor((Date.now() - turn.started) / 1000)) : 0;
    dom.sysopLiveStripTextEl.textContent = stripText(liveLine(g, turn), elapsed);
  }
}

function streamCursor() {
  const cur = document.createElement('span');
  cur.className = 'turn-stream-cursor';
  cur.setAttribute('aria-hidden', 'true');
  return cur;
}

// the phone's strip by the Stop button: only the state and the time (what it does is the last line of the turn, right above it)
const stripText = (line, secs) => {
  const word = /^Waiting for you/.test(line || '') ? 'Waiting for you' : 'Working';
  return secs >= 1 ? `${word} · ${fmtDur(secs)}` : word;
};
const fmtDur = (secs) => (secs < 60 ? `${secs}s` : `${Math.floor(secs / 60)}m ${String(secs % 60).padStart(2, '0')}s`);

// the last line of a turn, always one line high: what the Sysop is doing while it runs, then how the goal ended and how long it took.
// It is the same slot before and after, so nothing above or below it moves when the goal ends.
export function renderTurnFoot(turn, live) {
  const foot = document.createElement('div');
  foot.className = 'turn-foot';
  const mark = document.createElement('span');
  mark.className = 'turn-foot-mark';
  const txt = document.createElement('span');
  txt.className = 'turn-foot-text';
  const time = document.createElement('span');
  time.className = 'turn-foot-time';
  let secs = 0;
  if (turn.running) {
    foot.dataset.state = 'running';
    secs = turn.started ? Math.max(0, Math.floor((Date.now() - turn.started) / 1000)) : 0;
    txt.textContent = live ? live.line : (turn.live_action || 'Thinking…');
    phase(mark, 1100);
    phase(txt, 2200);
  } else {
    const st = turn.state === 'failed' || turn.state === 'stopped' ? turn.state : 'done';
    foot.dataset.state = st;
    secs = turn.started && turn.ended > turn.started ? Math.round((turn.ended - turn.started) / 1000) : 0;
    txt.textContent = st === 'stopped' ? 'Stopped · session kept' : (st === 'failed' ? 'Failed' : 'Done');
  }
  txt.title = txt.textContent;
  time.textContent = secs >= 1 ? fmtDur(secs) : '';
  foot.append(mark, txt, time);
  return foot;
}

export function renderTurn(turn) {
  const el = document.createElement('div');
  el.className = `turn${turn.running ? ' running' : ''}`;
  el.dataset.state = turn.state || '';
  el.dataset.gid = turn.id || '';

  if (turn.source === 'schedule' || turn.source === 'trigger') {
    // a goal the Sysop started itself (one of its automations): a line of its own, not a bubble of the user's words
    const row = document.createElement('div');
    row.className = 'turn-auto';
    const ico = document.createElement('span');
    ico.className = 'turn-auto-ico';
    ico.innerHTML = turn.source === 'trigger' ? ICO_BOLT_SVG : ICO_CLOCK_SVG;
    const txt = document.createElement('div');
    txt.className = 'turn-auto-text';
    const head = document.createElement('div');
    head.className = 'turn-auto-head';
    const m = /^(a\d+) \((.*)$/.exec(turn.auto_head || '');
    head.textContent = `${turn.source === 'trigger' ? 'Trigger' : 'Schedule'} ${m ? m[1] : (turn.automation || '')} · ${m ? m[2].replace(/\)(: |$)/, '$1') : 'ran'}`;
    const body = document.createElement('div');
    body.className = 'turn-auto-prompt';
    body.textContent = turn.prompt;
    txt.append(head, body);
    const meta = document.createElement('div');
    meta.className = 'turn-meta';
    meta.append(fmtAgo(turn.started));
    row.append(ico, txt);
    el.append(row, meta);
  } else if (turn.prompt) {
    const ask = document.createElement('div');
    ask.className = 'turn-ask';
    const bubble = document.createElement('div');
    bubble.className = 'turn-ask-bubble';
    bubble.textContent = turn.prompt;
    const meta = document.createElement('div');
    meta.className = 'turn-meta';
    if (turn.source === 'voice') meta.insertAdjacentHTML('beforeend', MIC_SVG);
    meta.append(fmtAgo(turn.started));
    ask.append(bubble, meta);
    el.appendChild(ask);
  }

  const said = document.createElement('div');
  said.className = 'turn-sysop';
  const head = document.createElement('div');
  head.className = 'turn-sysop-head';
  head.appendChild(makeMiniPixelIcon('sysop'));
  const who = document.createElement('span');
  who.className = 'turn-who';
  who.textContent = 'Sysop';
  head.appendChild(who);
  const lg = turn.running ? liveGoals.get(turn.id) : null;
  const live = lg ? liveTurnParts(lg, turn) : null;
  const acts = live ? live.acts : (Array.isArray(turn.actions) ? turn.actions : []);
  let list = null;
  if (acts.length) {
    const failed = acts.filter((a) => !a.ok).length;
    const open = openTurnActions.has(turn.id);
    const tog = document.createElement('button');
    tog.type = 'button';
    tog.className = 'turn-acts-toggle';
    tog.setAttribute('aria-expanded', String(open));
    tog.textContent = `${open ? '▾' : '▸'} ${acts.length} action${acts.length === 1 ? '' : 's'}${failed ? ` · ${failed} failed` : ''}`;
    list = document.createElement('ol');
    list.className = 'turn-acts';
    list.hidden = !open;
    for (const a of acts) {
      const li = document.createElement('li');
      const pending = a.state === 'chosen' || a.state === 'running' || a.state === 'waiting';
      li.className = pending ? 'live' : (a.ok ? 'ok' : 'err');
      if (a.state) li.dataset.state = a.state;
      const mark = document.createElement('span');
      mark.className = 'turn-act-mark';
      mark.textContent = pending ? (a.state === 'waiting' ? '⏸' : '…') : (a.ok ? '✓' : '✕');
      li.append(mark, linkTabs(a.label || a.fn || 'step'));
      list.appendChild(li);
    }
    tog.addEventListener('click', () => {
      const now = list.hidden;
      list.hidden = !now;
      if (now) openTurnActions.add(turn.id);
      else openTurnActions.delete(turn.id);
      tog.setAttribute('aria-expanded', String(now));
      tog.textContent = tog.textContent.replace(/^[▸▾]/, now ? '▾' : '▸');
    });
    const dot = document.createElement('span');
    dot.className = 'turn-sep';
    dot.textContent = '·';
    head.append(dot, tog);
  }
  said.appendChild(head);
  if (list) said.appendChild(list);

  const skipGlow = Boolean(lg && liveGlowReplay.has(turn.id));
  const noteList = live ? live.notes : (Array.isArray(turn.notes) ? turn.notes : []).map((n) => ({ text: String(n), streaming: false }));
  for (let ni = 0; ni < noteList.length; ni++) {
    const n = noteList[ni];
    const note = document.createElement('div');
    note.className = 'turn-note';
    note.appendChild(linkTabs(n.text));
    if (lg) applyBbsGlow(note, `${turn.id}:note:${ni}`, skipGlow);
    if (n.streaming) {
      note.dataset.state = 'streaming';
      note.appendChild(streamCursor());
    }
    said.appendChild(note);
  }
  const reply = turn.running ? (live && live.reply && live.reply.text ? live.reply : null) : (turn.reply ? { text: turn.reply, streaming: false } : null);
  if (reply) {
    const rep = renderReplyText(reply.text, reply.streaming);
    if (lg) applyBbsGlow(rep, `${turn.id}:reply`, skipGlow);
    rep.dataset.state = turn.running ? (reply.streaming ? 'streaming' : 'running') : (turn.state || 'done');
    said.appendChild(rep);
  }
  if (skipGlow) liveGlowReplay.delete(turn.id);
  said.appendChild(renderTurnFoot(turn, live));
  el.appendChild(said);
  return el;
}

export function renderSysopEmpty(sysop) {
  const box = document.createElement('div');
  box.className = 'sysop-empty';
  const icon = document.createElement('div');
  icon.className = 'sysop-empty-icon';
  icon.innerHTML = pixelIconHtml('sysop');
  const title = document.createElement('div');
  title.className = 'sysop-empty-title';
  title.textContent = sysop.up ? 'Sysop Operator' : 'Sysop is offline';
  const desc = document.createElement('p');
  desc.className = 'sysop-empty-desc';
  box.append(icon, title, desc);
  if (!sysop.up) {
    desc.innerHTML = 'Install it from Settings › Addons, or run <code>swarmbox addon install sysop</code>.';
    const cta = document.createElement('button');
    cta.type = 'button';
    cta.className = 'sysop-offline-cta';
    cta.textContent = 'Open Addons Settings →';
    cta.addEventListener('click', () => { if (typeof actions.openSettings === 'function') actions.openSettings('system'); });
    box.appendChild(cta);
    return box;
  }
  const policy = (sysop.settings && sysop.settings.autonomy) || '';
  desc.textContent = policy === 'full-auto'
    ? "Ask what's happening in your box or direct your agents — what you ask, it does."
    : "Ask what's happening in your box or direct your agents — risky actions pause for you.";
  if (policy) {
    const pol = document.createElement('div');
    pol.className = 'sysop-empty-policy';
    pol.textContent = `policy · ${policy}`;
    box.appendChild(pol);
  }
  const sugg = document.createElement('div');
  sugg.className = 'sysop-suggest';
  for (const text of SYSOP_SUGGESTIONS) {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'sysop-suggest-btn';
    const label = document.createElement('span');
    label.textContent = text;
    const ret = document.createElement('span');
    ret.className = 'sysop-suggest-ret';
    ret.textContent = '↵';
    b.append(label, ret);
    b.addEventListener('click', () => { if (typeof actions.sendGoal === 'function') actions.sendGoal(text); });
    sugg.appendChild(b);
  }
  box.appendChild(sugg);
  return box;
}

// The Chat tab: you and the sysop (what it does by itself is in the Events tab)
export function renderSysopFeed(sysop) {
  const turns = Array.isArray(sysop.turns) ? sysop.turns : null;
  const steps = Array.isArray(sysop.steps) ? sysop.steps : [];
  const hasTurns = turns ? turns.length > 0 : steps.length > 0;
  dom.sysopFeedEl.classList.toggle('is-empty', !hasTurns || !sysop.up);
  const keyHint = window.innerWidth <= 860 ? '' : ' (Alt+G)';
  if (state.sysopRunning) {
    dom.goalInputEl.placeholder = (window.innerWidth <= 860 ? 'Redirect or queue…' : 'Redirect or queue instruction…') + keyHint;
  } else {
    dom.goalInputEl.placeholder = (!hasTurns ? (window.innerWidth <= 860 ? 'Ask Sysop…' : 'Ask Sysop or direct an agent…') : 'Ask a follow-up…') + keyHint;
  }
  dom.btnSysopNew.classList.toggle('hidden', !hasTurns || !sysop.up);
  // the running turn drawn from its live events: the snapshot gives its prompt and start; a goal that ended leaves the live state
  const runningIds = new Set();
  for (const t of turns || []) {
    lastTurns.set(t.id, t);
    if (t.running) runningIds.add(t.id);
  }
  for (const gid of Array.from(liveGoals.keys())) {
    if (!runningIds.has(gid) && (turns || []).some((t) => t.id === gid)) {
      liveGoals.delete(gid);
      clearLiveGlow(gid);
    }
  }
  for (const gid of Array.from(lastTurns.keys())) {
    if (!(turns || []).some((t) => t.id === gid)) lastTurns.delete(gid);
  }
  const keyTurns = (turns || []).map((t) => (t.running && liveGoals.has(t.id) ? { id: t.id, prompt: t.prompt, running: true, started: t.started, source: t.source } : t));
  // the snapshot comes every 600 ms: rebuild only when something shown changed (per-second tick while running keeps elapsed live)
  const tickBucket = state.sysopRunning ? Math.floor(Date.now() / 1000) : Math.floor(Date.now() / 60000);
  const key = JSON.stringify([sysop.up, sysop.settings && sysop.settings.autonomy, turns ? keyTurns : null, turns ? null : steps,
    state.terminals.map((t) => [t.address, tabDisplayName(t), tabAgentKind(t)]), tickBucket]);
  if (key !== lastFeedKey) {
    lastFeedKey = key;
    const nearBottom = dom.sysopFeedEl.scrollHeight - dom.sysopFeedEl.scrollTop - dom.sysopFeedEl.clientHeight < 48;
    dom.sysopFeedEl.innerHTML = '';
    if (!sysop.up || !hasTurns) {
      dom.sysopFeedEl.appendChild(renderSysopEmpty(sysop));
    } else if (turns) {
      for (const t of turns) dom.sysopFeedEl.appendChild(renderTurn(t));
    } else {
      // an older gateway without turns: the flat steps of the current goal
      for (const s of steps) {
        const div = document.createElement('div');
        div.className = `step ${s.kind || 'info'}`;
        div.textContent = s.text || '';
        dom.sysopFeedEl.appendChild(div);
      }
    }
    if (nearBottom || !dom.sysopFeedEl.dataset.seen) dom.sysopFeedEl.scrollTop = dom.sysopFeedEl.scrollHeight;
    dom.sysopFeedEl.dataset.seen = '1';
  }
  // the confirmation lives in the conversation, right under the turn that waits for it
  const host = dom.sysopFeedEl.querySelector('.turn.running .turn-sysop') || dom.sysopFeedEl;
  if (dom.approvalCardEl.parentNode !== host) host.appendChild(dom.approvalCardEl);
  if (!dom.approvalCardEl.classList.contains('hidden')) dom.sysopFeedEl.scrollTop = dom.sysopFeedEl.scrollHeight;
}

export function stopSysop(goalId = null) {
  const payload = goalId ? { goal_id: String(goalId) } : {};
  return fetch('/api/sysop/stop', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  }).catch(() => {});
}

export function renderSysopQueue(queue) {
  if (!dom.sysopQueueBarEl) return;
  const list = Array.isArray(queue) ? queue : [];
  dom.sysopQueueBarEl.classList.toggle('hidden', !list.length);
  if (!list.length) {
    dom.sysopQueueBarEl.innerHTML = '';
    return;
  }
  dom.sysopQueueBarEl.innerHTML = '';
  for (const q of list.slice(0, 3)) {
    const row = document.createElement('div');
    row.className = 'sysop-queue-item';
    const tag = document.createElement('span');
    tag.className = 'sysop-queue-tag';
    tag.textContent = 'Queued:';
    const txt = document.createElement('span');
    txt.className = 'sysop-queue-text';
    txt.textContent = String(q.text || '').trim();
    const cancel = document.createElement('button');
    cancel.type = 'button';
    cancel.className = 'sysop-queue-cancel';
    cancel.title = 'Remove from queue';
    cancel.setAttribute('aria-label', 'Remove from queue');
    cancel.textContent = '×';
    cancel.addEventListener('click', () => stopSysop(q.id));
    row.append(tag, txt, cancel);
    dom.sysopQueueBarEl.appendChild(row);
  }
}

// the phone's strip by the Stop button: there while a goal runs; when it ends it says so for a moment, then folds away slowly
// (it is above the composer: gone at once, the conversation would jump down by its height)
let stripWasRunning = false;
let stripTimer = null;
export function syncLiveStrip(running, turns, liveAction, elapsed) {
  const el = dom.sysopLiveStripEl;
  if (running) {
    clearTimeout(stripTimer);
    stripTimer = null;
    el.classList.remove('hidden', 'folding');
    el.dataset.state = 'running';
    if (dom.sysopLiveStripTextEl) dom.sysopLiveStripTextEl.textContent = stripText(liveAction, elapsed);
  } else if (stripWasRunning) {
    const last = turns.length ? turns[turns.length - 1] : null;
    const st = last && (last.state === 'failed' || last.state === 'stopped') ? last.state : 'done';
    const secs = last && last.started && last.ended > last.started ? Math.round((last.ended - last.started) / 1000) : 0;
    el.dataset.state = st;
    if (dom.sysopLiveStripTextEl) {
      const word = st === 'stopped' ? 'Stopped' : (st === 'failed' ? 'Failed' : 'Done');
      dom.sysopLiveStripTextEl.textContent = secs >= 1 ? `${word} · ${fmtDur(secs)}` : word;
    }
    clearTimeout(stripTimer);
    stripTimer = setTimeout(() => {
      el.classList.add('folding');
      stripTimer = setTimeout(() => { el.classList.add('hidden'); el.classList.remove('folding'); stripTimer = null; }, 260);
    }, 1600);
  } else if (!stripTimer) {
    el.classList.add('hidden');
  }
  stripWasRunning = running;
}

export function renderSysop(sysop) {
  if (!sysop) return;
  if (dom.appEl) dom.appEl.dataset.sysopUp = sysop.up ? '1' : '0';
  const st = sysop.state || 'off';
  const stWord = STATE_WORDS[st] || st;
  const running = st === 'working' || st === 'allow?' || st === 'sending' || st === 'queued';
  state.sysopRunning = running;

  if (dom.sysopDotEl) {
    dom.sysopDotEl.dataset.state = st;
    dom.sysopDotEl.title = `Sysop: ${stWord}`;
    dom.sysopDotEl.setAttribute('aria-label', `Sysop: ${stWord}`);
  }
  const turns = Array.isArray(sysop.turns) ? sysop.turns : [];
  const activeTurn = turns.find((t) => t && t.running) || null;
  const activeLive = activeTurn ? liveGoals.get(activeTurn.id) : null;
  const liveAction = activeLive ? liveLine(activeLive, activeTurn) : ((activeTurn && activeTurn.live_action) || sysop.sentence || 'Working…');
  const elapsed = activeTurn && activeTurn.started ? Math.max(0, Math.floor((Date.now() - activeTurn.started) / 1000)) : 0;

  if (dom.mobileSysopBtn) dom.mobileSysopBtn.dataset.state = st;
  if (dom.mobileSysopTextEl) {
    if (st === 'idle' || st === 'off') {
      dom.mobileSysopTextEl.textContent = 'Sysop';
    } else if (running) {
      const shortAct = liveAction.replace(/^run → /, '').replace(/…$/, '');
      dom.mobileSysopTextEl.textContent = elapsed >= 1 ? `Sysop · ${shortAct} · ${elapsed}s` : `Sysop · ${shortAct}`;
    } else {
      dom.mobileSysopTextEl.textContent = `Sysop · ${sysop.sentence || st}`;
    }
  }
  if (dom.btnToggleSysop) dom.btnToggleSysop.dataset.state = st;
  if (dom.composerEl) dom.composerEl.dataset.running = running ? '1' : '0';
  if (dom.sendLabelEl) dom.sendLabelEl.textContent = running ? 'Queue' : 'Send';

  if (dom.btnSysopStop) dom.btnSysopStop.classList.toggle('hidden', !running);
  if (dom.btnMobileDockStop) dom.btnMobileDockStop.classList.toggle('hidden', !running);
  if (dom.sysopLiveStripEl) syncLiveStrip(running, turns, liveAction, elapsed);
  if (dom.sysopModelPillEl) {
    const m = sysop.settings && sysop.settings.model && sysop.settings.model !== 'auto' ? String(sysop.settings.model) : '';
    dom.sysopModelPillEl.textContent = m;
    dom.sysopModelPillEl.classList.toggle('hidden', !sysop.up || !m);
  }

  // Highlight sidebar card if Sysop is actively targeting a tab
  const liveTarget = (activeTurn && activeTurn.live_target) ? String(activeTurn.live_target).toLowerCase() : '';
  document.querySelectorAll('.tab-card[data-sysop-target="1"]').forEach((el) => { el.dataset.sysopTarget = '0'; });
  if (running && liveTarget) {
    for (const t of state.terminals) {
      const name = tabDisplayName(t).toLowerCase();
      if (t.address.toLowerCase() === liveTarget || name === liveTarget) {
        const card = document.querySelector(`.tab-card[data-addr="${CSS.escape(t.address)}"]`);
        if (card) card.dataset.sysopTarget = '1';
        break;
      }
    }
  }

  renderSysopQueue(sysop.queue);
  renderApprovalCard(sysop);
  renderQuestionCard(sysop);
  handleNotifications(sysop);
  renderSysopFeed(sysop);
  syncContext(sysop);   // sets state.sysopContext (it compares with the last one: a rewrite seen to end)
  renderEvents(sysop);
}

let noteTimer = null;
export function showVoiceNote(msg, tone = '', ms = 4000) {
  clearTimeout(noteTimer);
  if (!msg) {
    dom.voiceNoteEl.classList.add('hidden');
    return;
  }
  dom.voiceNoteEl.textContent = msg;
  dom.voiceNoteEl.dataset.tone = tone;
  dom.voiceNoteEl.classList.remove('hidden');
  if (ms) noteTimer = setTimeout(() => dom.voiceNoteEl.classList.add('hidden'), ms);
}

export function clearOpenTurnActions() {
  openTurnActions.clear();
}

let sysopChatInitialized = false;
export function initSysopChat() {
  if (sysopChatInitialized || typeof document === 'undefined') return;
  sysopChatInitialized = true;
  if (dom.questionFreeEl) {
    dom.questionFreeEl.addEventListener('submit', (e) => {
      e.preventDefault();
      if (shownQuestionId) sendAnswer(shownQuestionId, dom.questionInputEl.value);
    });
  }
}
