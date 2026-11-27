// Sidebar, topbar, mobile sessions sheet, and active tab status bar rendering.

import { state, dom, actions, isAgentId, agentLabel, applyAgentColor } from './state.js';
import {
  ICO_BRANCH_SVG,
  ICO_BOOK_SVG,
  ICO_PLUS_SM_SVG,
  REPO_GROUP_ACCENTS,
  shortDisplayPath,
  tabTitleParts,
  tabState,
  tabSubtitle,
  tabAgentKind,
  pixelIconHtml,
  makeMiniPixelIcon,
  stateBadgeText,
  stateCornerGlyph,
} from './icons.js';
import {
  closeCardMenu,
  openCardMenu,
  startInlineRename,
  commitInlineRename,
  unpinById,
} from './ui-chrome.js';
import { openNewAgentPopover } from './new-agent.js';
import {
  terminalRepoGroupInfo,
  openWorktreePopover,
  openRepoWorktreesPopover,
  wakePin,
} from './worktrees.js';

// Never wipe sidebar/tab DOM mid-click: defer background snapshot re-renders while a pointer
// is pressed on any tab bar so a live status tick between mousedown and mouseup never swallows clicks.
let tabBarPointerHeld = false;
let tabBarRenderDeferred = false;
let tabBarPointerTimer = null;
let tabsListenersBound = false;

export function releaseTabBarPointer() {
  if (tabBarPointerTimer) { clearTimeout(tabBarPointerTimer); tabBarPointerTimer = null; }
  if (!tabBarPointerHeld) return;
  tabBarPointerHeld = false;
  if (tabBarRenderDeferred) {
    tabBarRenderDeferred = false;
    setTimeout(() => { if (!tabBarPointerHeld) renderTabs(true); }, 0);
  }
}

export function initTabs() {
  if (tabsListenersBound || typeof window === 'undefined') return;
  tabsListenersBound = true;
  for (const el of [dom.sidebarAgentsEl, dom.sidebarTabsEl, dom.topbarTabsEl, dom.sessionsSheetBodyEl]) {
    if (!el) continue;
    el.addEventListener('pointerdown', () => {
      tabBarPointerHeld = true;
      if (tabBarPointerTimer) clearTimeout(tabBarPointerTimer);
      tabBarPointerTimer = setTimeout(releaseTabBarPointer, 600);
    }, { passive: true, capture: true });
  }
  window.addEventListener('pointerup', releaseTabBarPointer, { passive: true, capture: true });
  window.addEventListener('pointercancel', releaseTabBarPointer, { passive: true, capture: true });
  if (dom.sidebarAgentsEl && typeof ResizeObserver === 'function') {
    new ResizeObserver(() => fitRepoCtxPills()).observe(dom.sidebarAgentsEl);
  }
}

export function buildMobileSessionRow(t, isAgent) {
  const tState = tabState(t);
  const { title: label } = tabTitleParts(t);
  const agentKind = isAgent ? (tabAgentKind(t) || 'shell') : 'shell';
  const isActive = t.address === state.activeId;
  const subText = tabSubtitle(t);
  const wtBranch = t.labels && t.labels['swarmbox.worktree'] ? (t.labels['swarmbox.branch'] || 'worktree') : '';
  const shortBranch = wtBranch ? wtBranch.replace(/^sb\//, '') : '';
  const repoBranch = (!wtBranch && t.repo && t.repo.branch) ? t.repo.branch : '';

  const row = document.createElement('div');
  row.className = `ms-row${isActive ? ' active' : ''}${tState === 'blocked' ? ' is-blocked' : ''}`;
  row.setAttribute('role', 'option');
  row.setAttribute('aria-selected', isActive ? 'true' : 'false');
  if (isAgent) applyAgentColor(row, agentKind);

  const ico = document.createElement('div');
  ico.className = 'ms-ico';
  if (isAgent) {
    ico.innerHTML = pixelIconHtml(agentKind);
  } else {
    ico.innerHTML = '<span class="ms-ico-shell">&gt;_</span>';
  }

  const info = document.createElement('div');
  info.className = 'ms-info';

  const top = document.createElement('div');
  top.className = 'ms-top';
  const titleEl = document.createElement('span');
  titleEl.className = 'ms-title';
  titleEl.textContent = label;
  top.appendChild(titleEl);
  if (isAgent) {
    const tag = document.createElement('span');
    tag.className = 'ms-tag';
    tag.textContent = agentLabel(agentKind);
    top.appendChild(tag);
  }

  const sub = document.createElement('div');
  sub.className = 'ms-sub';
  if (isAgent) {
    const dot = document.createElement('span');
    dot.className = 'status-dot';
    dot.dataset.state = tState;
    const st = document.createElement('span');
    st.className = 'ms-state';
    st.dataset.state = tState;
    st.textContent = stateBadgeText(tState, t.status);
    const meta = document.createElement('span');
    meta.className = 'ms-meta-text';
    const detail = shortBranch || repoBranch || subText || '';
    meta.textContent = detail ? `· ${detail}` : '';
    sub.append(dot, st, meta);
  } else {
    const meta = document.createElement('span');
    meta.className = 'ms-meta-text';
    meta.textContent = subText ? `Shell · ${subText}` : 'Shell';
    sub.appendChild(meta);
  }

  info.append(top, sub);

  const acts = document.createElement('div');
  acts.className = 'ms-acts';

  const moreBtn = document.createElement('button');
  moreBtn.type = 'button';
  moreBtn.className = 'ms-act-btn';
  moreBtn.title = 'Session actions (Rename, Worktree, Copy path, Close)';
  moreBtn.setAttribute('aria-label', `Actions for ${label}`);
  moreBtn.textContent = '⋯';
  moreBtn.addEventListener('click', (e) => {
    e.stopPropagation();
    if (row.dataset.menuOpen === '1') closeCardMenu();
    else openCardMenu(t, moreBtn, row);
  });

  const closeBtn = document.createElement('button');
  closeBtn.type = 'button';
  closeBtn.className = 'ms-act-btn ms-close-btn';
  closeBtn.title = 'Close tab';
  closeBtn.setAttribute('aria-label', `Close ${label}`);
  closeBtn.textContent = '✕';
  closeBtn.addEventListener('click', async (e) => {
    e.stopPropagation();
    closeCardMenu();
    await fetch(`/api/tabs/${encodeURIComponent(t.address)}`, { method: 'DELETE' });
  });

  acts.append(moreBtn, closeBtn);
  row.append(ico, info, acts);

  row.addEventListener('click', (e) => {
    if (e.target && e.target.closest('button')) return;
    closeCardMenu();
    if (state.activeId !== t.address) {
      if (typeof actions.connectPty === 'function') actions.connectPty(t.address);
    }
    if (typeof actions.setMobileSessions === 'function') actions.setMobileSessions(false);
  });
  return row;
}

export function renderMobileSessions(repoGroups, shellTerms, parkedPins) {
  if (!dom.sessionsSheetBodyEl) return;
  dom.sessionsSheetBodyEl.innerHTML = '';

  const showAgents = state.mobileSessionsFilter === 'all' || state.mobileSessionsFilter === 'agents';
  const showShells = state.mobileSessionsFilter === 'all' || state.mobileSessionsFilter === 'shells';
  let renderedCount = 0;

  if (showAgents && repoGroups.length > 0) {
    for (const grp of repoGroups) {
      const groupEl = document.createElement('div');
      groupEl.className = 'ms-group';

      const headEl = document.createElement('div');
      headEl.className = 'ms-group-head';
      headEl.style.setProperty('--rg-accent', grp.accent);

      const titleEl = document.createElement('div');
      titleEl.className = 'ms-group-title';
      titleEl.innerHTML = `${grp.isGit ? ICO_BRANCH_SVG : ''}<span></span>`;
      titleEl.querySelector('span').textContent = grp.name;

      const actsEl = document.createElement('div');
      actsEl.className = 'ms-group-acts';

      const wtTotal = grp.activeWorktrees.length + grp.pendingWorktrees.length;
      if (grp.isGit && wtTotal > 0) {
        const hasWarn = grp.pendingWorktrees.some((w) => w.dirty || !w.can_merge)
          || grp.activeWorktrees.some((t) => tabState(t) === 'blocked');
        const wtPill = document.createElement('button');
        wtPill.type = 'button';
        wtPill.className = 'repo-wt-pill';
        wtPill.title = `${wtTotal} worktree${wtTotal === 1 ? '' : 's'} in ${grp.name}`;
        wtPill.innerHTML = `<span class="repo-wt-dot" data-tone="${hasWarn ? 'warn' : 'ok'}"></span>${ICO_BRANCH_SVG}<span>${wtTotal}</span>`;
        wtPill.addEventListener('click', (e) => {
          e.stopPropagation();
          closeCardMenu();
          openRepoWorktreesPopover(grp);
        });
        actsEl.appendChild(wtPill);
      }

      const addBtn = document.createElement('button');
      addBtn.type = 'button';
      addBtn.className = 'ms-group-add';
      addBtn.title = `New agent in ${grp.name}`;
      addBtn.setAttribute('aria-label', `New agent in ${grp.name}`);
      addBtn.innerHTML = ICO_PLUS_SM_SVG;
      addBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        closeCardMenu();
        if (typeof actions.setMobileSessions === 'function') actions.setMobileSessions(false);
        openNewAgentPopover(false, grp.cwd);
      });
      actsEl.appendChild(addBtn);

      headEl.append(titleEl, actsEl);
      groupEl.appendChild(headEl);

      for (const t of grp.terms) {
        groupEl.appendChild(buildMobileSessionRow(t, true));
        renderedCount += 1;
      }
      dom.sessionsSheetBodyEl.appendChild(groupEl);
    }
  }

  if (showShells && shellTerms.length > 0) {
    const groupEl = document.createElement('div');
    groupEl.className = 'ms-group';
    if (state.mobileSessionsFilter === 'all' && repoGroups.length > 0) {
      const headEl = document.createElement('div');
      headEl.className = 'ms-group-head';
      const titleEl = document.createElement('div');
      titleEl.className = 'ms-group-title';
      titleEl.textContent = 'Shells';
      headEl.appendChild(titleEl);
      groupEl.appendChild(headEl);
    }
    for (const t of shellTerms) {
      groupEl.appendChild(buildMobileSessionRow(t, false));
      renderedCount += 1;
    }
    dom.sessionsSheetBodyEl.appendChild(groupEl);
  }

  if (showAgents && parkedPins.length > 0) {
    const groupEl = document.createElement('div');
    groupEl.className = 'ms-group';
    const headEl = document.createElement('div');
    headEl.className = 'ms-group-head';
    const titleEl = document.createElement('div');
    titleEl.className = 'ms-group-title';
    titleEl.textContent = 'Pinned · Parked';
    headEl.appendChild(titleEl);
    groupEl.appendChild(headEl);

    for (const pin of parkedPins) {
      const pKind = isAgentId(pin.agent) ? pin.agent : 'shell';
      const row = document.createElement('div');
      row.className = 'ms-row is-parked';
      applyAgentColor(row, pKind);

      const ico = document.createElement('div');
      ico.className = 'ms-ico';
      ico.innerHTML = pixelIconHtml(pKind);

      const info = document.createElement('div');
      info.className = 'ms-info';
      const top = document.createElement('div');
      top.className = 'ms-top';
      const titleTxt = document.createElement('span');
      titleTxt.className = 'ms-title';
      titleTxt.textContent = pin.title || shortDisplayPath(pin.cwd) || 'pinned';
      top.appendChild(titleTxt);

      const sub = document.createElement('div');
      sub.className = 'ms-sub';
      const wakePill = document.createElement('span');
      wakePill.className = 'ms-wake-pill';
      wakePill.textContent = pin.missing_cwd ? 'Missing dir' : 'PARKED · ▶ Wake';
      sub.appendChild(wakePill);
      info.append(top, sub);

      const acts = document.createElement('div');
      acts.className = 'ms-acts';
      const dismissBtn = document.createElement('button');
      dismissBtn.type = 'button';
      dismissBtn.className = 'ms-act-btn ms-close-btn';
      dismissBtn.title = 'Dismiss saved session';
      dismissBtn.setAttribute('aria-label', `Dismiss ${pin.title || 'session'}`);
      dismissBtn.textContent = '✕';
      dismissBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        unpinById(pin.id);
      });
      acts.appendChild(dismissBtn);

      row.append(ico, info, acts);
      row.addEventListener('click', (e) => {
        if (e.target && e.target.closest('button')) return;
        if (!pin.missing_cwd) {
          wakePin(pin.id);
          if (typeof actions.setMobileSessions === 'function') actions.setMobileSessions(false);
        }
      });
      groupEl.appendChild(row);
      renderedCount += 1;
    }
    dom.sessionsSheetBodyEl.appendChild(groupEl);
  }

  if (renderedCount === 0) {
    const empty = document.createElement('div');
    empty.className = 'ms-empty';
    empty.textContent = state.mobileSessionsFilter === 'agents'
      ? 'No agents running yet'
      : state.mobileSessionsFilter === 'shells'
        ? 'No shells open yet'
        : 'No active sessions';
    dom.sessionsSheetBodyEl.appendChild(empty);
  }
}

// a looping animation keeps its phase across redraws (sidebar cards and the running sysop turn are drawn again on events): start it where the clock is
export const phase = (el, ms) => { if (el) el.style.animationDelay = `-${Date.now() % ms}ms`; return el; };

let lastTabsRenderKey = '';

export function tabsRenderKey() {
  return JSON.stringify({
    activeId: state.activeId,
    editingTabId: state.editingTabId,
    mobileSessionsFilter: state.mobileSessionsFilter,
    ctx: typeof actions.getLastCtxTabsKey === 'function' ? actions.getLastCtxTabsKey() : '',
    pins: state.pins,
    pendingWorktrees: state.pendingWorktrees,
    repoStatuses: state.repoStatuses,
    terminals: state.terminals.map((t) => [
      t.address,
      tabState(t),
      t.status && t.status.msg,
      t.status && t.status.progress,
      t.status && t.status.kind,
      tabTitleParts(t),
      tabAgentKind(t),
      tabSubtitle(t),
      t.labels,
      t.repo,
      terminalRepoGroupInfo(t).key,
    ]),
  });
}

export function renderTabs(force = false) {
  if (tabBarPointerHeld && !force) {
    tabBarRenderDeferred = true;
    return;
  }
  tabBarRenderDeferred = false;
  const renderKey = tabsRenderKey();
  if (!force && renderKey === lastTabsRenderKey) return;
  lastTabsRenderKey = renderKey;
  if (dom.sidebarTabsEl) dom.sidebarTabsEl.innerHTML = '';
  if (dom.topbarTabsEl) dom.topbarTabsEl.innerHTML = '';
  if (dom.sidebarAgentsEl) dom.sidebarAgentsEl.innerHTML = '';

  let agentCount = 0;
  let shellCount = 0;
  let busyCount = 0;
  const repoGroups = [];
  const repoGroupMap = new Map();
  const shellTerms = [];

  state.terminals.forEach((t, idx) => {
    const tState = tabState(t);
    const { title: label } = tabTitleParts(t);
    const agentKind = tabAgentKind(t);
    const iconKind = agentKind || 'shell';
    const isActive = t.address === state.activeId;
    const subText = tabSubtitle(t);

    // 1. Sidebar: zero duplication — agents live in repo-grouped Pixel-Art Agent Cards; plain shells live in Shells list
    if (agentKind && dom.sidebarAgentsEl) {
      agentCount += 1;
      if (tState === 'working' || tState === 'blocked') busyCount += 1;

      const gInfo = terminalRepoGroupInfo(t);
      let grp = repoGroupMap.get(gInfo.key);
      if (!grp) {
        grp = { ...gInfo, accent: REPO_GROUP_ACCENTS[repoGroups.length % REPO_GROUP_ACCENTS.length], cards: [], terms: [], activeWorktrees: [], pendingWorktrees: [] };
        repoGroupMap.set(gInfo.key, grp);
        repoGroups.push(grp);
      }
      if (t.labels && t.labels['swarmbox.worktree']) grp.activeWorktrees.push(t);
      grp.terms.push(t);

      const card = document.createElement('div');
      card.className = `agent-card${isActive ? ' active' : ''}`;
      card.setAttribute('role', 'tab');
      card.setAttribute('tabindex', '0');
      card.setAttribute('aria-selected', isActive ? 'true' : 'false');
      card.dataset.agent = agentKind;
      applyAgentColor(card, agentKind);
      card.dataset.state = tState;
      card.title = `${label} — ${agentLabel(agentKind)} (${tState})`;

      const main = document.createElement('div');
      main.className = 'agent-card-main';

      const stage = document.createElement('div');
      stage.className = 'pixel-stage';
      stage.innerHTML = pixelIconHtml(agentKind);
      if (tState === 'working') phase(stage.querySelector('svg'), 900);
      else if (tState === 'blocked') phase(stage.querySelector('svg'), 550);
      const corner = document.createElement('span');
      corner.className = 'pixel-corner';
      corner.textContent = stateCornerGlyph(tState);
      stage.appendChild(corner);

      const cInfo = document.createElement('div');
      cInfo.className = 'agent-card-info';
      const cTop = document.createElement('div');
      cTop.className = 'agent-card-top';
      const cBadge = document.createElement('span');
      cBadge.className = 'agent-state-box';
      cBadge.textContent = stateBadgeText(tState, t.status);

      const cRight = document.createElement('div');
      cRight.className = 'agent-card-right';
      const pinId = t.labels && t.labels['swarmbox.pin_id'];
      const pinObj = pinId ? state.pins.find((p) => p.id === pinId) : null;
      const cIdx = document.createElement('span');
      cIdx.className = 'agent-card-idx';
      cIdx.textContent = `tab ${idx + 1}`;
      const cTopActs = document.createElement('div');
      cTopActs.className = 'agent-card-top-acts';
      const cMore = document.createElement('button');
      cMore.type = 'button';
      cMore.className = 'agent-card-more';
      cMore.title = 'Session actions (Merge, Rename, Close)';
      cMore.setAttribute('aria-label', `Actions for ${label}`);
      cMore.textContent = '⋯';
      cMore.addEventListener('click', (e) => {
        e.stopPropagation();
        if (card.dataset.menuOpen === '1') closeCardMenu();
        else openCardMenu(t, cMore, card);
      });
      const cClose = document.createElement('button');
      cClose.type = 'button';
      cClose.className = 'agent-card-close';
      cClose.title = (pinObj && !pinObj.auto) ? 'Close tab (pin stays parked)' : 'Close tab';
      cClose.setAttribute('aria-label', `Close ${label}`);
      cClose.textContent = '✕';
      cClose.addEventListener('click', async (e) => {
        e.stopPropagation();
        closeCardMenu();
        await fetch(`/api/tabs/${encodeURIComponent(t.address)}`, { method: 'DELETE' });
      });
      cTopActs.append(cMore, cClose);
      cRight.append(cIdx, cTopActs);
      cTop.append(cBadge, cRight);

      const isEditing = state.editingTabId === t.address;
      const cName = document.createElement('div');
      cName.className = `agent-card-name${isEditing ? ' is-editing' : ''}`;
      if (isEditing) {
        const inp = document.createElement('input');
        inp.type = 'text';
        inp.className = 'inline-rename-input';
        inp.dataset.tab = t.address;
        inp.value = label;
        inp.maxLength = 60;
        inp.addEventListener('click', (e) => e.stopPropagation());
        inp.addEventListener('keydown', (e) => {
          e.stopPropagation();
          if (e.key === 'Enter') { e.preventDefault(); commitInlineRename(t.address, inp.value); }
          else if (e.key === 'Escape') {
            e.preventDefault();
            state.editingTabId = null;
            renderTabs();
            if (typeof actions.focusTerminalIfDesktop === 'function') actions.focusTerminalIfDesktop();
          }
        });
        inp.addEventListener('blur', () => {
          if (state.editingTabId === t.address) commitInlineRename(t.address, inp.value);
        });
        cName.appendChild(inp);
      } else {
        const nameSpan = document.createElement('span');
        nameSpan.className = 'agent-card-name-text';
        nameSpan.textContent = label;
        cName.appendChild(nameSpan);
        const isAutoNamed = t.labels && t.labels['swarmbox.title_source'] === 'auto';
        cName.title = isAutoNamed
          ? `${label} (auto-named by Sysop · double-click or Alt+R to rename)`
          : `${label} (double-click or Alt+R to rename)`;
        cName.addEventListener('dblclick', (e) => {
          e.stopPropagation();
          startInlineRename(t.address);
        });
      }

      const cMsg = document.createElement('div');
      cMsg.className = 'agent-card-msg';
      cMsg.textContent = subText || (t.address || '');

      // its launcher waits for the first context of the repository: the card says so, and counts
      const ctxSess = typeof actions.ctxSessionFor === 'function' ? actions.ctxSessionFor(t) : null;
      const ctxWaiting = Boolean(ctxSess && ctxSess.waiting);
      if (ctxWaiting) {
        cBadge.textContent = 'STARTING';
        cBadge.classList.add('is-ctx-wait');
        cMsg.className = 'agent-card-msg is-ctx-wait';
        cMsg.innerHTML = ICO_BOOK_SVG;
        phase(cMsg.querySelector('svg'), 1400);
        const since = document.createElement('span');
        since.dataset.ctxSince = String(ctxSess.at || Date.now());
        since.textContent = `preparing context · ${Math.max(0, Math.round((Date.now() - (ctxSess.at || Date.now())) / 1000))}s`;
        cMsg.appendChild(since);
        if (typeof actions.ctxSessionWhy === 'function') cMsg.title = actions.ctxSessionWhy(ctxSess);
      }

      cInfo.append(cTop, cName, cMsg);
      main.append(stage, cInfo);
      card.appendChild(main);
      if (ctxWaiting) {
        const bar = document.createElement('div');
        bar.className = 'ctx-progress';
        bar.innerHTML = '<i></i>';
        phase(bar.querySelector('i'), 1600);
        card.appendChild(bar);
      }

      const foot = document.createElement('div');
      foot.className = 'agent-card-foot';
      const wtBranch = t.labels && t.labels['swarmbox.worktree'] ? (t.labels['swarmbox.branch'] || 'worktree') : '';
      const wtBase = (t.labels && t.labels['swarmbox.base']) || 'main';
      const shortBranch = wtBranch ? wtBranch.replace(/^sb\//, '') : '';
      const repoBranch = (!wtBranch && t.repo && t.repo.branch) ? t.repo.branch : '';

      const footL = document.createElement('div');
      footL.className = 'agent-card-foot-l';
      const footAg = document.createElement('span');
      footAg.className = 'agent-card-foot-ag';
      footAg.textContent = `└ ${agentLabel(agentKind)}`;
      footL.appendChild(footAg);
      if (wtBranch) {
        const wtSep = document.createElement('span');
        wtSep.className = 'agent-wt-sep';
        wtSep.textContent = '·';
        const wtLink = document.createElement('button');
        wtLink.type = 'button';
        wtLink.className = 'agent-wt-link';
        wtLink.innerHTML = `${ICO_BRANCH_SVG}<span>${shortBranch}</span>`;
        wtLink.title = `Worktree ${wtBranch} → ${wtBase} · click to merge or inspect`;
        wtLink.addEventListener('click', (e) => {
          e.stopPropagation();
          closeCardMenu();
          openWorktreePopover(t.address);
        });
        footL.append(wtSep, wtLink);
      } else if (repoBranch) {
        const brSep = document.createElement('span');
        brSep.className = 'agent-wt-sep';
        brSep.textContent = '·';
        const brTxt = document.createElement('span');
        brTxt.className = 'agent-card-foot-ag agent-card-foot-br';
        brTxt.textContent = repoBranch;
        brTxt.title = repoBranch;
        footL.append(brSep, brTxt);
      }
      const footR = document.createElement('span');
      footR.className = 'agent-card-foot-r';
      if (ctxSess && !ctxWaiting && typeof actions.makeCtxChip === 'function') {
        footR.appendChild(actions.makeCtxChip(t, ctxSess, true));
      }
      if (idx < 9) footR.append(`Alt+${idx + 1}`);
      foot.append(footL, footR);
      card.appendChild(foot);

      card.addEventListener('contextmenu', (e) => {
        e.preventDefault();
        e.stopPropagation();
        openCardMenu(t, { x: e.clientX, y: e.clientY }, card);
      });

      if (tState === 'working' && t.status && typeof t.status.progress === 'number') {
        const pBar = document.createElement('div');
        pBar.className = 'agent-card-bar';
        const pFill = document.createElement('i');
        pFill.style.width = `${Math.max(5, Math.min(100, t.status.progress))}%`;
        pBar.appendChild(pFill);
        card.appendChild(pBar);
      }

      const activateCard = () => {
        if (state.activeId !== t.address) {
          if (typeof actions.connectPty === 'function') actions.connectPty(t.address);
        } else if (typeof actions.focusTerminalIfDesktop === 'function') {
          actions.focusTerminalIfDesktop();
        }
      };
      card.addEventListener('mousedown', (e) => {
        if (e.button !== 0 || e.detail > 1) return;
        if (e.target && e.target.closest('button, input')) return;
        activateCard();
      });
      card.addEventListener('click', (e) => {
        if (e.target && e.target.closest('button, input')) return;
        activateCard();
      });
      card.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          activateCard();
        }
      });
      grp.cards.push(card);
    } else {
      shellCount += 1;
      shellTerms.push(t);
      const btn = document.createElement('div');
      btn.className = `tab-item${isActive ? ' active' : ''}${tState === 'blocked' ? ' is-blocked' : ''}${tState === 'working' ? ' is-working' : ''}`;
      btn.setAttribute('role', 'tab');
      btn.setAttribute('aria-selected', isActive ? 'true' : 'false');
      btn.title = label;

      const info = document.createElement('div');
      info.className = 'tab-info';
      const titleEl = document.createElement('div');
      titleEl.className = 'tab-title';
      if (state.editingTabId === t.address) {
        const inp = document.createElement('input');
        inp.type = 'text';
        inp.className = 'inline-rename-input';
        inp.dataset.tab = t.address;
        inp.value = label;
        inp.maxLength = 60;
        inp.addEventListener('click', (e) => e.stopPropagation());
        inp.addEventListener('keydown', (e) => {
          e.stopPropagation();
          if (e.key === 'Enter') { e.preventDefault(); commitInlineRename(t.address, inp.value); }
          else if (e.key === 'Escape') {
            e.preventDefault();
            state.editingTabId = null;
            renderTabs();
            if (typeof actions.focusTerminalIfDesktop === 'function') actions.focusTerminalIfDesktop();
          }
        });
        inp.addEventListener('blur', () => {
          if (state.editingTabId === t.address) commitInlineRename(t.address, inp.value);
        });
        titleEl.appendChild(inp);
      } else {
        const titleText = document.createElement('span');
        titleText.className = 'tab-title-text';
        titleText.textContent = label;
        titleText.addEventListener('dblclick', (e) => { e.stopPropagation(); startInlineRename(t.address); });
        titleEl.appendChild(titleText);
      }
      const subEl = document.createElement('div');
      subEl.className = 'tab-sub';
      subEl.textContent = subText;
      info.append(titleEl, subEl);

      const right = document.createElement('div');
      right.className = 'tab-right';
      const idxEl = document.createElement('span');
      idxEl.className = 'tab-idx';
      idxEl.textContent = idx < 9 ? `Alt+${idx + 1}` : '';
      const closeBtn = document.createElement('button');
      closeBtn.className = 'tab-close';
      closeBtn.title = 'Close tab';
      closeBtn.setAttribute('aria-label', `Close ${label}`);
      closeBtn.textContent = '✕';
      closeBtn.addEventListener('click', async (e) => {
        e.stopPropagation();
        await fetch(`/api/tabs/${encodeURIComponent(t.address)}`, { method: 'DELETE' });
      });
      right.append(idxEl, closeBtn);

      btn.append(makeMiniPixelIcon(iconKind), info, right);
      const activateShellTab = () => {
        if (state.activeId !== t.address) {
          if (typeof actions.connectPty === 'function') actions.connectPty(t.address);
        } else if (typeof actions.focusTerminalIfDesktop === 'function') {
          actions.focusTerminalIfDesktop();
        }
      };
      btn.addEventListener('mousedown', (e) => {
        if (e.button !== 0 || e.detail > 1) return;
        if (e.target && e.target.closest('button, input')) return;
        activateShellTab();
      });
      btn.addEventListener('click', (e) => {
        if (e.target && e.target.closest('button, input')) return;
        activateShellTab();
      });
      if (dom.sidebarTabsEl) dom.sidebarTabsEl.appendChild(btn);
    }

    // 2. Informative Horizontal Topbar Tab (Desktop — auto-shown when sidebar is collapsed via Alt+B)
    if (dom.topbarTabsEl) {
      const tt = document.createElement('div');
      tt.className = `top-tab${isActive ? ' active' : ''}`;
      tt.setAttribute('role', 'tab');
      tt.setAttribute('aria-selected', isActive ? 'true' : 'false');
      tt.title = `${label} — ${subText || tState}`;

      const ttName = document.createElement('span');
      ttName.className = 'top-tab-name';
      ttName.textContent = label;
      const ttNum = document.createElement('span');
      ttNum.className = 'top-tab-num';
      ttNum.textContent = idx < 9 ? String(idx + 1) : '';
      const ttClose = document.createElement('button');
      ttClose.type = 'button';
      ttClose.className = 'top-tab-close';
      ttClose.title = 'Close tab';
      ttClose.setAttribute('aria-label', `Close ${label}`);
      ttClose.textContent = '×';
      ttClose.addEventListener('click', async (e) => {
        e.stopPropagation();
        await fetch(`/api/tabs/${encodeURIComponent(t.address)}`, { method: 'DELETE' });
      });

      tt.append(makeMiniPixelIcon(iconKind), ttName, ttNum);
      if (tState === 'working' || tState === 'blocked' || tState === 'done') {
        const td = document.createElement('span');
        td.className = 'status-dot';
        td.dataset.state = tState;
        if (tState === 'working') phase(td, 1400);
        else if (tState === 'blocked') phase(td, 950);
        tt.appendChild(td);
      }
      tt.appendChild(ttClose);
      tt.addEventListener('click', () => {
        if (state.activeId !== t.address) {
          if (typeof actions.connectPty === 'function') actions.connectPty(t.address);
        } else if (typeof actions.focusTerminalIfDesktop === 'function') {
          actions.focusTerminalIfDesktop();
        }
      });
      dom.topbarTabsEl.appendChild(tt);
    }
  });

  if (dom.tabCountEl) dom.tabCountEl.textContent = String(shellCount);

  // 4. Parked Pinned Sessions (desktop sidebar + mobile tab strip)
  const parkedPins = (Array.isArray(state.pins) ? state.pins : []).filter((p) => p && p.parked);
  if (dom.sidebarParkedSectionEl && dom.sidebarParkedEl) {
    dom.sidebarParkedSectionEl.classList.toggle('hidden', parkedPins.length === 0);
    if (dom.parkedCountEl) dom.parkedCountEl.textContent = String(parkedPins.length);
    dom.sidebarParkedEl.innerHTML = '';
    for (const pin of parkedPins) {
      const pKind = isAgentId(pin.agent) ? pin.agent : 'shell';
      const card = document.createElement('div');
      card.className = 'agent-card is-parked';
      card.dataset.agent = pKind;
      applyAgentColor(card, pKind);
      card.title = pin.missing_cwd
        ? `Directory missing: ${pin.cwd}`
        : `Click to wake ${pin.title} (${pin.agent || 'shell'} · ${pin.resume || 'continue'})`;

      const main = document.createElement('div');
      main.className = 'agent-card-main';
      const stage = document.createElement('div');
      stage.className = 'pixel-stage';
      stage.innerHTML = pixelIconHtml(pKind);
      const info = document.createElement('div');
      info.className = 'agent-card-info';
      const top = document.createElement('div');
      top.className = 'agent-card-top';
      const badge = document.createElement('span');
      badge.className = 'agent-state-box';
      badge.textContent = pin.missing_cwd ? 'MISSING' : 'PARKED';
      const right = document.createElement('div');
      right.className = 'agent-card-right';
      const dismissBtn = document.createElement('button');
      dismissBtn.type = 'button';
      dismissBtn.className = 'agent-card-close';
      dismissBtn.title = 'Dismiss saved session';
      dismissBtn.setAttribute('aria-label', `Dismiss ${pin.title || 'session'}`);
      dismissBtn.textContent = '✕';
      dismissBtn.addEventListener('click', (e) => { e.stopPropagation(); unpinById(pin.id); });
      right.append(dismissBtn);
      top.append(badge, right);

      const nm = document.createElement('div');
      nm.className = 'agent-card-name';
      nm.textContent = pin.title || shortDisplayPath(pin.cwd) || 'pinned';
      const msg = document.createElement('div');
      msg.className = 'agent-card-msg';
      msg.textContent = pin.worktree && pin.worktree.branch
        ? `${shortDisplayPath(pin.cwd)} · ${pin.worktree.branch}`
        : shortDisplayPath(pin.cwd);
      info.append(top, nm, msg);
      main.append(stage, info);

      const foot = document.createElement('div');
      foot.className = 'agent-card-foot';
      const fl = document.createElement('span');
      fl.textContent = `${agentLabel(pKind)} · ${pin.resume === 'fresh' ? 'fresh' : '--continue'}`;
      const wake = document.createElement('span');
      wake.className = `wake-pill${pin.missing_cwd ? ' is-missing' : ''}`;
      wake.textContent = pin.missing_cwd ? 'Missing dir' : '▶ Wake';
      foot.append(fl, wake);
      card.append(main, foot);

      card.addEventListener('click', () => { if (!pin.missing_cwd) wakePin(pin.id); });
      dom.sidebarParkedEl.appendChild(card);
    }
  }

  // Pending worktrees pill in sidebar
  if (dom.sidebarPendingWtEl) {
    const pCount = Array.isArray(state.pendingWorktrees) ? state.pendingWorktrees.length : 0;
    dom.sidebarPendingWtEl.classList.toggle('hidden', pCount === 0);
    if (dom.pendingWtCountEl) dom.pendingWtCountEl.textContent = String(pCount);
  }

  if (dom.topbarTabsEl) {
    const tPlus = document.createElement('button');
    tPlus.type = 'button';
    tPlus.className = 'top-tab top-tab-add';
    tPlus.textContent = '+';
    tPlus.title = 'New terminal tab (Alt+N)';
    tPlus.setAttribute('aria-label', 'New terminal tab');
    tPlus.addEventListener('click', () => {
      if (typeof actions.spawnTab === 'function') actions.spawnTab('shell');
      if (typeof actions.focusTerminalIfDesktop === 'function') actions.focusTerminalIfDesktop();
    });
    dom.topbarTabsEl.appendChild(tPlus);
  }

  if (dom.sidebarAgentsEl && repoGroups.length > 0) {
    const pWts = Array.isArray(state.pendingWorktrees) ? state.pendingWorktrees : [];
    for (const grp of repoGroups) {
      if (grp.isGit) {
        grp.pendingWorktrees = pWts.filter((w) =>
          (grp.root && w.repo_root && w.repo_root === grp.root) ||
          (!w.repo_root && w.repo_name && w.repo_name === grp.name),
        );
      }
      const groupEl = document.createElement('div');
      groupEl.className = 'repo-group';

      const headEl = document.createElement('div');
      headEl.className = 'repo-group-head';
      headEl.style.setProperty('--rg-accent', grp.accent);

      const titleEl = document.createElement('div');
      titleEl.className = 'repo-group-title';
      titleEl.title = shortDisplayPath(grp.cwd) || grp.name;
      titleEl.innerHTML = `${grp.isGit ? ICO_BRANCH_SVG : ''}<span></span>`;
      titleEl.querySelector('span').textContent = grp.name;
      const ctxRepo = typeof actions.ctxRepoForGroup === 'function' ? actions.ctxRepoForGroup(grp) : null;
      if (ctxRepo && typeof actions.makeRepoCtxPill === 'function') titleEl.appendChild(actions.makeRepoCtxPill(ctxRepo));

      const actsEl = document.createElement('div');
      actsEl.className = 'repo-group-acts';

      const rs = (grp.isGit && grp.root && state.repoStatuses[grp.root]) ? state.repoStatuses[grp.root] : null;
      if (rs) {
        let mainPillText = '';
        let mainPillCls = '';
        let mainPillTitle = '';
        const brName = rs.branch || 'main';
        if (rs.verify_job && rs.verify_job.state === 'running') {
          mainPillText = 'checking…';
          mainPillCls = 'is-running';
          mainPillTitle = `Running ${rs.verify_job.cmd || 'checks'} on ${brName} — click to manage`;
        } else if (rs.verify_job && rs.verify_job.state === 'failed') {
          mainPillText = 'check failed';
          mainPillCls = 'is-failed';
          mainPillTitle = `Check failed on ${brName} — click to inspect`;
        } else if (rs.ahead_origin > 0) {
          mainPillText = `↑${rs.ahead_origin}`;
          mainPillCls = 'is-ahead';
          mainPillTitle = `${brName} is ${rs.ahead_origin} commit(s) ahead of ${rs.upstream || 'origin'} — click to manage`;
        } else if (rs.dirty) {
          mainPillText = `● ${rs.uncommitted_count || 1}`;
          mainPillCls = 'is-dirty';
          mainPillTitle = `${brName} has uncommitted changes — click to manage`;
        }
        if (mainPillText) {
          const mainPill = document.createElement('button');
          mainPill.type = 'button';
          mainPill.className = `repo-main-pill ${mainPillCls}`;
          if (mainPillCls === 'is-running') phase(mainPill, 1300);
          mainPill.textContent = mainPillText;
          mainPill.title = mainPillTitle;
          mainPill.addEventListener('click', (e) => {
            e.stopPropagation();
            closeCardMenu();
            openRepoWorktreesPopover(grp);
          });
          actsEl.appendChild(mainPill);
        }
      }

      const wtTotal = grp.activeWorktrees.length + grp.pendingWorktrees.length;
      if (grp.isGit && wtTotal > 0) {
        const hasWarn = grp.pendingWorktrees.some((w) => w.dirty || !w.can_merge)
          || grp.activeWorktrees.some((t) => tabState(t) === 'blocked');
        const wtPill = document.createElement('button');
        wtPill.type = 'button';
        wtPill.className = 'repo-wt-pill';
        wtPill.title = `${wtTotal} worktree${wtTotal === 1 ? '' : 's'} in ${grp.name} · click to compare & reconcile`;
        wtPill.innerHTML = `<span class="repo-wt-dot" data-tone="${hasWarn ? 'warn' : 'ok'}"></span>${ICO_BRANCH_SVG}<span>${wtTotal}</span>`;
        wtPill.addEventListener('click', (e) => {
          e.stopPropagation();
          closeCardMenu();
          openRepoWorktreesPopover(grp);
        });
        actsEl.appendChild(wtPill);
      }

      const addBtn = document.createElement('button');
      addBtn.type = 'button';
      addBtn.className = 'icon-btn icon-btn-sm repo-add-btn';
      addBtn.title = `New agent in ${grp.name}`;
      addBtn.setAttribute('aria-label', `New agent in ${grp.name}`);
      addBtn.innerHTML = ICO_PLUS_SM_SVG;
      addBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        closeCardMenu();
        openNewAgentPopover(false, grp.cwd);
      });
      actsEl.appendChild(addBtn);

      headEl.append(titleEl, actsEl);
      const cardsWrap = document.createElement('div');
      cardsWrap.className = 'repo-group-cards';
      for (const c of grp.cards) cardsWrap.appendChild(c);

      groupEl.append(headEl, cardsWrap);
      dom.sidebarAgentsEl.appendChild(groupEl);
    }
  }

  if (dom.agentsBusyCountEl) {
    dom.agentsBusyCountEl.textContent = `${busyCount} busy`;
    dom.agentsBusyCountEl.classList.toggle('has-busy', busyCount > 0);
    dom.agentsBusyCountEl.classList.toggle('hidden', busyCount === 0);
  }
  if (dom.btnNewAgent) {
    dom.btnNewAgent.classList.remove('hidden');
    dom.btnNewAgent.title = 'New agent in any project (Alt+A)';
  }
  if (dom.sidebarAgentsSectionEl) {
    dom.sidebarAgentsSectionEl.classList.toggle('is-empty', agentCount === 0);
    dom.sidebarAgentsSectionEl.classList.toggle('hidden', agentCount === 0);
  }
  if (dom.sidebarShellsSectionEl) {
    dom.sidebarShellsSectionEl.classList.toggle('hidden', shellCount === 0 && agentCount === 0);
  }

  // Mobile Switcher Pill counter + Thumb-Zone Sessions Bottom Sheet
  const totalMobileCount = state.terminals.length;
  const hasBgAttention = state.terminals.some((t) => t.address !== state.activeId && tabState(t) === 'blocked');
  if (dom.mobileSwitcherCountEl) {
    dom.mobileSwitcherCountEl.textContent = String(totalMobileCount);
    dom.mobileSwitcherCountEl.classList.toggle('has-attention', hasBgAttention);
  }
  if (dom.mobileSessionsBusyEl) {
    dom.mobileSessionsBusyEl.textContent = `${busyCount} busy`;
    dom.mobileSessionsBusyEl.classList.toggle('has-busy', busyCount > 0);
    dom.mobileSessionsBusyEl.classList.toggle('hidden', busyCount === 0);
  }
  if (dom.sfilterCountAllEl) dom.sfilterCountAllEl.textContent = String(state.terminals.length + parkedPins.length);
  if (dom.sfilterCountAgentsEl) dom.sfilterCountAgentsEl.textContent = String(agentCount);
  if (dom.sfilterCountShellsEl) dom.sfilterCountShellsEl.textContent = String(shellCount);
  renderMobileSessions(repoGroups, shellTerms, parkedPins);

  const active = state.terminals.find((t) => t.address === state.activeId);
  const termCtxSepEl = document.querySelector('.term-ctx-sep');
  if (dom.btnInterruptEl) {
    dom.btnInterruptEl.disabled = !active;
    dom.btnInterruptEl.classList.toggle('is-disabled', !active);
  }
  if (active) {
    const aParts = tabTitleParts(active);
    const aState = tabState(active);
    const aKind = tabAgentKind(active) || 'shell';
    const aSub = tabSubtitle(active);
    if (dom.activeDotEl) dom.activeDotEl.dataset.state = aState;
    if (dom.activeNameEl) dom.activeNameEl.textContent = aParts.title;
    if (dom.mobileSwitcherIcoEl) {
      dom.mobileSwitcherIcoEl.innerHTML = '';
      dom.mobileSwitcherIcoEl.appendChild(makeMiniPixelIcon(aKind));
    }
    if (dom.activeAgentEl) {
      dom.activeAgentEl.textContent = aParts.pill;
      dom.activeAgentEl.classList.toggle('hidden', !aParts.pill);
    }
    if (termCtxSepEl) termCtxSepEl.classList.toggle('hidden', !aSub);
    if (dom.activeStatusEl) {
      dom.activeStatusEl.textContent = aSub;
      dom.activeStatusEl.classList.toggle('hidden', !aSub);
    }
    if (dom.termCtxIconEl) dom.termCtxIconEl.innerHTML = pixelIconHtml(aKind);
    if (dom.termCtxTitleEl) dom.termCtxTitleEl.textContent = aParts.pill ? `${aParts.title} (${agentLabel(aParts.pill)})` : aParts.title;
    const isLiveWt = Boolean(active.labels && active.labels['swarmbox.worktree'] && (!active.repo || active.repo.is_worktree));
    const aWtBranch = isLiveWt ? (active.labels['swarmbox.branch'] || 'worktree') : '';
    const aWtBase = (active.labels && active.labels['swarmbox.base']) || 'main';
    if (dom.topbarWtBtnEl) {
      dom.topbarWtBtnEl.classList.toggle('hidden', !aWtBranch);
      if (aWtBranch) dom.topbarWtBtnEl.innerHTML = `${ICO_BRANCH_SVG}<span>${aWtBranch} → ${aWtBase} ▾</span>`;
    }
    if (dom.mobileWtBtnEl) {
      dom.mobileWtBtnEl.classList.toggle('hidden', !aWtBranch);
      if (aWtBranch) dom.mobileWtBtnEl.innerHTML = `${ICO_BRANCH_SVG}<span>${aWtBranch.replace(/^sb\//, '')}</span>`;
    }
    if (typeof actions.renderTopbarCtx === 'function') actions.renderTopbarCtx(active);
    if (dom.termCtxStateEl) {
      dom.termCtxStateEl.classList.remove('hidden');
      dom.termCtxStateEl.dataset.state = aState;
      dom.termCtxStateEl.textContent = stateBadgeText(aState, active.status);
    }
  } else {
    const hasParked = parkedPins.length > 0;
    if (dom.activeDotEl) dom.activeDotEl.dataset.state = 'idle';
    if (dom.activeNameEl) dom.activeNameEl.textContent = hasParked ? 'Sessions parked' : 'No active tab';
    if (dom.mobileSwitcherIcoEl) dom.mobileSwitcherIcoEl.innerHTML = '';
    if (dom.activeAgentEl) dom.activeAgentEl.classList.add('hidden');
    if (dom.topbarWtBtnEl) dom.topbarWtBtnEl.classList.add('hidden');
    if (dom.mobileWtBtnEl) dom.mobileWtBtnEl.classList.add('hidden');
    if (typeof actions.renderTopbarCtx === 'function') actions.renderTopbarCtx(null);
    if (termCtxSepEl) termCtxSepEl.classList.toggle('hidden', !hasParked);
    if (dom.activeStatusEl) {
      dom.activeStatusEl.textContent = hasParked ? `${parkedPins.length} parked` : '';
      dom.activeStatusEl.classList.toggle('hidden', !hasParked);
    }
    if (dom.termCtxIconEl) dom.termCtxIconEl.innerHTML = pixelIconHtml('shell');
    if (dom.termCtxTitleEl) dom.termCtxTitleEl.textContent = hasParked ? 'Sessions parked' : 'No active tab';
    if (dom.termCtxStateEl) {
      dom.termCtxStateEl.dataset.state = 'idle';
      dom.termCtxStateEl.textContent = hasParked ? 'PARKED' : '';
      dom.termCtxStateEl.classList.toggle('hidden', !hasParked);
    }
  }

  if (dom.stageEmptyEl) {
    if (state.terminals.length > 0) {
      dom.stageEmptyEl.classList.add('hidden');
      dom.stageEmptyEl.innerHTML = '';
    } else {
      dom.stageEmptyEl.classList.remove('hidden');
      dom.stageEmptyEl.innerHTML = '';
      const card = document.createElement('div');
      card.className = 'stage-empty-card';
      const title = document.createElement('div');
      title.className = 'stage-empty-title';
      title.textContent = parkedPins.length > 0 ? 'Sessions parked' : 'No active sessions';
      const sub = document.createElement('div');
      sub.className = 'stage-empty-sub';
      sub.textContent = parkedPins.length > 0
        ? 'Wake a pinned session to resume where you left off, or start a fresh agent or shell.'
        : 'Open a new agent or shell tab to get started.';
      card.append(title, sub);
      if (parkedPins.length > 0) {
        const list = document.createElement('div');
        list.className = 'stage-empty-list';
        for (const pin of parkedPins) {
          const pKind = isAgentId(pin.agent) ? pin.agent : 'shell';
          const row = document.createElement('button');
          row.type = 'button';
          row.className = 'stage-empty-pin';
          row.disabled = Boolean(pin.missing_cwd);
          const left = document.createElement('span');
          left.className = 'stage-empty-pin-left';
          const meta = document.createElement('span');
          meta.className = 'stage-empty-pin-meta';
          const nm = document.createElement('span');
          nm.className = 'stage-empty-pin-name';
          nm.textContent = pin.title || shortDisplayPath(pin.cwd) || 'pinned';
          const pt = document.createElement('span');
          pt.className = 'stage-empty-pin-path';
          pt.textContent = `${agentLabel(pKind)} · ${shortDisplayPath(pin.cwd)}`;
          meta.append(nm, pt);
          left.append(makeMiniPixelIcon(pKind), meta);
          const pill = document.createElement('span');
          pill.className = `wake-pill${pin.missing_cwd ? ' is-missing' : ''}`;
          pill.textContent = pin.missing_cwd ? 'Missing dir' : '▶ Wake';
          row.append(left, pill);
          row.addEventListener('click', () => { if (!pin.missing_cwd) wakePin(pin.id); });
          list.appendChild(row);
        }
        card.appendChild(list);
      }
      const actionsEl = document.createElement('div');
      actionsEl.className = 'stage-empty-actions';
      const btnAg = document.createElement('button');
      btnAg.type = 'button';
      btnAg.className = 'stage-empty-btn';
      btnAg.textContent = '+ New agent';
      btnAg.addEventListener('click', () => openNewAgentPopover());
      const btnSh = document.createElement('button');
      btnSh.type = 'button';
      btnSh.className = 'stage-empty-btn';
      btnSh.textContent = '+ New shell';
      btnSh.addEventListener('click', () => { if (typeof actions.spawnTab === 'function') actions.spawnTab('shell'); });
      actionsEl.append(btnAg, btnSh);
      card.appendChild(actionsEl);
      dom.stageEmptyEl.appendChild(card);
    }
  }

  if (dom.statusbarSummaryEl) {
    const tabLabel = state.terminals.length === 1 ? '1 tab' : `${state.terminals.length} tabs`;
    const agLabel = agentCount === 1 ? '1 agent' : `${agentCount} agents`;
    const parts = [tabLabel, agLabel];
    if (parkedPins.length > 0) parts.push(`${parkedPins.length} parked`);
    if (busyCount > 0) parts.push(`${busyCount} busy`);
    dom.statusbarSummaryEl.textContent = parts.join(' · ');
  }
  fitRepoCtxPills();
}

// A repository group's name keeps the room: when it does not fit beside the context mark, the mark drops its age and keeps the
// book (its color still tells ready, writing or failed; the age is in its tooltip and card). Measured, so any name length works.
export function fitRepoCtxPills() {
  if (!dom.sidebarAgentsEl) return;
  for (const pill of dom.sidebarAgentsEl.querySelectorAll('.repo-ctx-pill')) {
    pill.classList.remove('is-tight');
    const name = pill.parentElement && pill.parentElement.querySelector(':scope > span');
    if (name && name.scrollWidth > name.clientWidth + 1) pill.classList.add('is-tight');
  }
}
