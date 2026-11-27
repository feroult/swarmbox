// New-agent picker, project/folder browser popover, and workspace isolation selector.

import { state, dom, actions, isAgentId, agentLabel } from './state.js';
import {
  ICO_BRANCH_SVG,
  ICO_FOLDER_SVG,
  ICO_CHECK_SVG,
  ICO_SEARCH_SVG,
  shortDisplayPath,
  pixelIconHtml,
} from './icons.js';
import { openPopover, closePopover } from './ui-chrome.js';

export async function openNewAgentPopover(includeShell = false, targetCwd = '', opts = {}) {
  const showProjectPicker = Boolean(opts && opts.showProjectPicker);
  const cur = state.terminals.find((t) => t.address === state.activeId);
  let selectedCwd = (typeof targetCwd === 'string' && targetCwd.startsWith('/'))
    ? targetCwd
    : ((cur && cur.foreground && cur.foreground.cwd) || (cur && cur.cwd) || '');

  let list = Array.isArray(state.installedAgents) ? state.installedAgents : [];
  const checkUrl = selectedCwd && selectedCwd.startsWith('/')
    ? `/api/worktrees/check?cwd=${encodeURIComponent(selectedCwd)}`
    : '/api/worktrees/check';

  const [cfgData, initialWtInfo, projData] = await Promise.all([
    list.length === 0
      ? fetch('/api/config', { cache: 'no-store' }).then((r) => (r.ok ? r.json() : null)).catch(() => null)
      : Promise.resolve(null),
    fetch(checkUrl, { cache: 'no-store' }).then((r) => (r.ok ? r.json() : null)).catch(() => null),
    showProjectPicker
      ? fetch('/api/projects', { cache: 'no-store' }).then((r) => (r.ok ? r.json() : null)).catch(() => null)
      : Promise.resolve(null),
  ]);

  if (cfgData && Array.isArray(cfgData.installed_agents)) {
    state.installedAgents = cfgData.installed_agents;
    list = state.installedAgents;
  }
  if (initialWtInfo && initialWtInfo.prefs) {
    state.worktreePrefs = initialWtInfo.prefs;
  }

  const projects = (projData && Array.isArray(projData.projects)) ? projData.projects : [];
  const recent = (projData && Array.isArray(projData.recent)) ? projData.recent : [];
  const homeDir = ((projData && projData.home) || '/home/agent').replace(/\/+$/, '') || '/';

  if (showProjectPicker && !selectedCwd) {
    if (recent.length > 0) selectedCwd = recent[0].path;
    else if (projects.length > 0) selectedCwd = projects[0].path;
  }

  let wtInfo = initialWtInfo;
  if (showProjectPicker && selectedCwd && (!initialWtInfo || initialWtInfo.cwd !== selectedCwd)) {
    wtInfo = await fetch(`/api/worktrees/check?cwd=${encodeURIComponent(selectedCwd)}`, { cache: 'no-store' })
      .then((r) => (r.ok ? r.json() : null))
      .catch(() => initialWtInfo);
  }

  let isGit = Boolean(wtInfo && wtInfo.is_git);
  let col = (wtInfo && wtInfo.collision) || null;
  let hasCollision = Boolean(col);
  let prefs = (wtInfo && wtInfo.prefs) || state.worktreePrefs || { mode: 'ask', copy_env: true };
  let branch = (wtInfo && wtInfo.branch) || (col && col.branch) || 'HEAD';

  if (!includeShell && !showProjectPicker && list.length === 0) {
    if (typeof actions.spawnTab === 'function') actions.spawnTab('agent', { cwd: selectedCwd || undefined });
    return;
  }
  if (!includeShell && !showProjectPicker && list.length === 1 && (!hasCollision || prefs.mode !== 'ask')) {
    if (typeof actions.spawnTab === 'function') actions.spawnTab('agent', { agent: list[0].id, cwd: selectedCwd || undefined });
    return;
  }

  let wtChoice = hasCollision ? (prefs.mode === 'off' ? 'same' : 'new') : 'same';
  let wtCheckGen = 0;
  // "Repository context": ticked for every new agent (the choice is not remembered); unticked, the session starts without it
  let ctxChoice = true;
  let updateCtxUi = null;

  const frag = document.createDocumentFragment();
  const head = document.createElement('div');
  head.className = 'spop-head';
  const titleSpan = document.createElement('span');
  titleSpan.textContent = 'New agent';
  const headRight = document.createElement('span');
  headRight.className = 'spop-head-right';
  const escBadge = document.createElement('span');
  escBadge.className = 'wt-kbd desktop-only';
  escBadge.textContent = 'Esc';
  headRight.appendChild(escBadge);
  head.append(titleSpan, headRight);
  frag.appendChild(head);

  if (!showProjectPicker) {
    const targetBar = document.createElement('div');
    targetBar.className = 'spop-target-bar';
    const cwdBtn = document.createElement('button');
    cwdBtn.type = 'button';
    cwdBtn.className = 'spop-badge spop-badge-btn';
    cwdBtn.textContent = `${shortDisplayPath(selectedCwd) || '~'} ▾`;
    cwdBtn.title = 'Switch project or folder';
    cwdBtn.addEventListener('click', () => {
      openNewAgentPopover(includeShell, selectedCwd, { showProjectPicker: true });
    });
    targetBar.appendChild(cwdBtn);
    if (isGit && branch) {
      const brBadge = document.createElement('span');
      brBadge.className = 'spop-badge branch';
      brBadge.innerHTML = `${ICO_BRANCH_SVG}<span></span>`;
      brBadge.querySelector('span').textContent = branch;
      targetBar.appendChild(brBadge);
    }
    frag.appendChild(targetBar);
  }

  // Dynamic Workspace container (re-rendered whenever the selected project changes)
  const wtContainer = document.createElement('div');
  let updateWtUi = null;

  function renderWorkspaceBox() {
    wtContainer.innerHTML = '';
    updateWtUi = null;
    if (!isGit) {
      if (!showProjectPicker) {
        const sub = document.createElement('div');
        sub.className = 'spop-sub';
        sub.textContent = includeShell
          ? 'Launch an installed coding agent or a fresh shell.'
          : 'Pick an installed coding agent to launch in this folder.';
        wtContainer.appendChild(sub);
      }
      return;
    }
    const folderLabel = shortDisplayPath(selectedCwd) || '~';
    const nActive = (col && col.active_tabs && col.active_tabs.length) || 0;
    const wtBox = document.createElement('div');
    wtBox.className = `wt-box${hasCollision ? ' is-collision' : ''}`;

    const wtHead = document.createElement('div');
    wtHead.className = 'wt-box-head';
    if (hasCollision) {
      const note = document.createElement('span');
      note.className = 'wt-collision-note';
      const dot = document.createElement('span');
      dot.className = 'wt-collision-dot';
      const txt = document.createElement('span');
      txt.textContent = `${nActive} active agent${nActive === 1 ? '' : 's'} already on ${branch}`;
      note.append(dot, txt);
      wtHead.appendChild(note);
    } else {
      const note = document.createElement('span');
      note.className = 'wt-clean-note';
      note.textContent = 'Workspace';
      wtHead.appendChild(note);
    }
    const kbd = document.createElement('span');
    kbd.className = 'wt-kbd desktop-only';
    kbd.title = 'Press W to toggle workspace';
    kbd.textContent = 'W';
    wtHead.appendChild(kbd);

    const seg = document.createElement('div');
    seg.className = 'wt-seg';
    seg.setAttribute('role', 'radiogroup');
    seg.setAttribute('aria-label', 'Workspace isolation');

    const btnNew = document.createElement('button');
    btnNew.type = 'button';
    btnNew.setAttribute('role', 'radio');
    btnNew.className = 'wt-seg-btn';
    btnNew.dataset.choice = 'new';
    btnNew.innerHTML = `${ICO_BRANCH_SVG}<span>New worktree</span>`;

    const btnSame = document.createElement('button');
    btnSame.type = 'button';
    btnSame.setAttribute('role', 'radio');
    btnSame.className = 'wt-seg-btn';
    btnSame.dataset.choice = 'same';
    btnSame.textContent = 'Same folder';

    seg.append(btnNew, btnSame);

    const meta = document.createElement('div');
    meta.className = 'wt-meta';

    updateWtUi = () => {
      const isNew = wtChoice === 'new';
      btnNew.classList.toggle('active-wt', isNew);
      btnNew.setAttribute('aria-checked', isNew ? 'true' : 'false');
      btnSame.classList.toggle('active-same', !isNew);
      btnSame.setAttribute('aria-checked', !isNew ? 'true' : 'false');
      if (isNew) {
        meta.innerHTML = '';
        const sp = document.createElement('span');
        sp.append('isolated branch from ');
        const st = document.createElement('strong');
        st.textContent = branch;
        sp.append(st);
        if (prefs.copy_env) sp.append(' · copies .env');
        meta.appendChild(sp);
      } else if (hasCollision) {
        meta.textContent = `shares working tree with ${nActive} active agent${nActive === 1 ? '' : 's'}`;
      } else {
        meta.textContent = `opens directly in ${folderLabel} · no active collision`;
      }
    };

    btnNew.addEventListener('click', () => {
      wtChoice = 'new';
      updateWtUi();
    });
    btnSame.addEventListener('click', () => {
      wtChoice = 'same';
      updateWtUi();
    });

    updateWtUi();
    wtBox.append(wtHead, seg, meta);
    const ctxRow = typeof actions.makeNewAgentCtxRow === 'function'
      ? actions.makeNewAgentCtxRow(selectedCwd, () => ctxChoice, (v) => { ctxChoice = v; })
      : null;
    if (ctxRow) {
      updateCtxUi = ctxRow.update;
      wtBox.appendChild(ctxRow.el);
    } else {
      updateCtxUi = null;
    }
    wtContainer.appendChild(wtBox);
  }

  async function selectProjectPath(nextPath) {
    if (!nextPath || nextPath === selectedCwd) return;
    selectedCwd = nextPath;
    const myGen = ++wtCheckGen;
    const nextInfo = await fetch(`/api/worktrees/check?cwd=${encodeURIComponent(nextPath)}`, { cache: 'no-store' })
      .then((r) => (r.ok ? r.json() : null))
      .catch(() => null);
    if (myGen !== wtCheckGen || !state.popoverOpen) return;
    wtInfo = nextInfo;
    isGit = Boolean(wtInfo && wtInfo.is_git);
    col = (wtInfo && wtInfo.collision) || null;
    hasCollision = Boolean(col);
    prefs = (wtInfo && wtInfo.prefs) || state.worktreePrefs || { mode: 'ask', copy_env: true };
    branch = (wtInfo && wtInfo.branch) || (col && col.branch) || 'HEAD';
    wtChoice = hasCollision ? (prefs.mode === 'off' ? 'same' : 'new') : 'same';
    renderWorkspaceBox();
  }

  let projInputEl = null;
  if (showProjectPicker) {
    const projSec = document.createElement('div');
    projSec.className = 'proj-section';

    const pHead = document.createElement('div');
    pHead.className = 'proj-head';
    const pLbl = document.createElement('span');
    pLbl.textContent = 'Folder';
    const pCnt = document.createElement('span');
    pCnt.textContent = `${projects.length} repo${projects.length === 1 ? '' : 's'}`;
    pHead.append(pLbl, pCnt);

    const pWrap = document.createElement('div');
    pWrap.className = 'proj-input-wrap';
    const pIco = document.createElement('span');
    pIco.className = 'proj-input-ico';
    pIco.innerHTML = ICO_SEARCH_SVG;
    projInputEl = document.createElement('input');
    projInputEl.type = 'text';
    projInputEl.className = 'proj-input';
    projInputEl.placeholder = 'Filter repos and folders…';
    projInputEl.setAttribute('aria-label', 'Filter repos and folders, or enter a folder path');
    pWrap.append(pIco, projInputEl);

    const pList = document.createElement('div');
    pList.className = 'proj-list proj-list-browse';

    const expandUserPath = (raw) => {
      const s = String(raw || '').trim();
      if (!s) return '';
      if (s === '~') return homeDir;
      if (s.startsWith('~/')) return `${homeDir}/${s.slice(2)}`.replace(/\/+/g, '/').replace(/\/+$/, '');
      if (s.startsWith('/')) return s.replace(/\/+$/, '') || '/';
      return '';
    };
    const underHome = (p) => p === homeDir || String(p || '').startsWith(homeDir + '/');
    const parentOf = (p) => {
      const s = String(p || '').replace(/\/+$/, '');
      const i = s.lastIndexOf('/');
      return i <= 0 ? '/' : s.slice(0, i);
    };

    // Folder browser state: start beside the selected folder so its siblings are one click away.
    let browseDir = (selectedCwd && underHome(selectedCwd) && selectedCwd !== homeDir) ? parentOf(selectedCwd) : homeDir;
    let browseEntries = [];
    let browseGen = 0;

    const makeRow = ({ kind, name, sub, branch, active, enter, onClick }) => {
      const row = document.createElement('button');
      row.type = 'button';
      row.className = `proj-row${active ? ' active' : ''}${kind === 'use' ? ' is-use' : ''}`;
      const left = document.createElement('span');
      left.className = 'proj-row-left';
      const icon = kind === 'repo' ? ICO_BRANCH_SVG : (kind === 'use' ? ICO_CHECK_SVG : ICO_FOLDER_SVG);
      left.innerHTML = `${icon}<span class="proj-row-name"></span><span class="proj-row-path"></span>`;
      left.querySelector('.proj-row-name').textContent = name;
      left.querySelector('.proj-row-path').textContent = sub || '';
      const right = document.createElement('span');
      right.className = 'proj-row-right';
      if (branch) {
        const br = document.createElement('span');
        br.className = 'proj-branch-pill';
        br.textContent = branch;
        right.appendChild(br);
      }
      if (enter) {
        const go = document.createElement('span');
        go.className = 'proj-row-go';
        go.setAttribute('aria-hidden', 'true');
        go.textContent = '›';
        right.appendChild(go);
      }
      row.append(left, right);
      row.addEventListener('click', onClick);
      return row;
    };

    const groupLabel = (text) => {
      const el = document.createElement('div');
      el.className = 'proj-group-label';
      el.textContent = text;
      return el;
    };

    const pick = (p) => {
      selectProjectPath(p);
      renderProjectRows();
    };
    // Entering a folder also selects it: the agent opens where you are browsing.
    const enterDir = (p) => {
      selectProjectPath(p);
      loadBrowse(p);
    };

    const renderCrumbs = () => {
      const bar = document.createElement('div');
      bar.className = 'proj-crumbs';
      const parts = [];
      if (underHome(browseDir)) {
        parts.push({ label: '~', path: homeDir });
        const rest = browseDir.slice(homeDir.length).split('/').filter(Boolean);
        let acc = homeDir;
        for (const seg of rest) { acc = `${acc}/${seg}`; parts.push({ label: seg, path: acc }); }
      } else {
        parts.push({ label: '/', path: '/' });
        let acc = '';
        for (const seg of browseDir.split('/').filter(Boolean)) { acc = `${acc}/${seg}`; parts.push({ label: seg, path: acc }); }
      }
      parts.forEach((pt, i) => {
        if (i > 0) {
          const sep = document.createElement('span');
          sep.className = 'proj-crumb-sep';
          sep.textContent = '/';
          bar.appendChild(sep);
        }
        const b = document.createElement('button');
        b.type = 'button';
        b.className = `proj-crumb${i === parts.length - 1 ? ' current' : ''}`;
        b.textContent = pt.label;
        b.addEventListener('click', () => enterDir(pt.path));
        bar.appendChild(b);
      });
      return bar;
    };

    const rowFor = (d, sub) => (d.is_git
      ? makeRow({ kind: 'repo', name: d.name, sub, branch: d.branch, active: selectedCwd === d.path, onClick: () => pick(d.path) })
      : makeRow({ kind: 'folder', name: d.name, sub, active: selectedCwd === d.path, enter: true, onClick: () => enterDir(d.path) }));

    const renderProjectRows = () => {
      pList.innerHTML = '';
      const q = projInputEl.value.trim();
      if (q) {
        // Filtering searches everything the picker knows: recent folders, every discovered repo, this folder.
        const qLow = q.toLowerCase();
        const pool = new Map();
        for (const d of recent) pool.set(d.path, d);
        for (const p of projects) if (!pool.has(p.path)) pool.set(p.path, { path: p.path, name: p.name, is_git: true, branch: p.branch });
        for (const d of browseEntries) if (!pool.has(d.path)) pool.set(d.path, d);
        const customPath = expandUserPath(q);
        for (const d of pool.values()) {
          if (!d.name.toLowerCase().includes(qLow) && !shortDisplayPath(d.path).toLowerCase().includes(qLow)) continue;
          pList.appendChild(rowFor(d, shortDisplayPath(d.path)));
        }
        if (customPath && !pool.has(customPath)) {
          pList.appendChild(makeRow({
            kind: 'folder', name: 'Open folder', sub: shortDisplayPath(customPath), enter: true,
            active: selectedCwd === customPath, onClick: () => { projInputEl.value = ''; enterDir(customPath); },
          }));
        }
        if (pList.children.length === 0) {
          const empty = document.createElement('div');
          empty.className = 'spop-sub';
          empty.textContent = 'No match — type a path like ~/my-folder';
          pList.appendChild(empty);
        }
        return;
      }

      if (recent.length > 0) {
        pList.appendChild(groupLabel('Recent'));
        for (const d of recent) pList.appendChild(rowFor(d, shortDisplayPath(parentOf(d.path))));
      }
      pList.appendChild(renderCrumbs());
      pList.appendChild(makeRow({
        kind: 'use', name: 'Use this folder', sub: shortDisplayPath(browseDir) || '/',
        active: selectedCwd === browseDir, onClick: () => pick(browseDir),
      }));
      for (const d of browseEntries) pList.appendChild(rowFor(d, ''));
      if (browseEntries.length === 0) {
        const empty = document.createElement('div');
        empty.className = 'proj-empty';
        empty.textContent = 'No subfolders';
        pList.appendChild(empty);
      }
    };

    async function loadBrowse(dir) {
      const myGen = ++browseGen;
      const data = await fetch(`/api/dirs?path=${encodeURIComponent(dir)}`, { cache: 'no-store' })
        .then((r) => (r.ok ? r.json() : null))
        .catch(() => null);
      if (myGen !== browseGen || !state.popoverOpen) return;
      if (data && Array.isArray(data.entries)) {
        browseDir = data.path;
        browseEntries = data.entries;
      }
      renderProjectRows();
      const crumbs = pList.querySelector('.proj-crumbs');
      if (crumbs && dir !== homeDir) crumbs.scrollIntoView({ block: 'nearest' });
    }

    projInputEl.addEventListener('input', () => renderProjectRows());
    projInputEl.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        e.preventDefault();
        const firstRow = pList.querySelector('.proj-row:not(.is-use)') || pList.querySelector('.proj-row');
        if (firstRow) firstRow.click();
        const primary = dom.popoverEl && dom.popoverEl.querySelector('.agent-pick-btn.is-default, .agent-pick-btn');
        if (primary) primary.focus();
      } else if (e.key === 'Backspace' && projInputEl.value === '' && browseDir !== '/') {
        // Backspace on an empty filter walks up one folder, like a path bar.
        e.preventDefault();
        enterDir(parentOf(browseDir));
      }
    });

    renderProjectRows();
    loadBrowse(browseDir);
    projSec.append(pHead, pWrap, pList);
    frag.appendChild(projSec);
  }

  renderWorkspaceBox();
  frag.appendChild(wtContainer);

  const secHead = document.createElement('div');
  secHead.className = 'pick-section-head';
  const secLeft = document.createElement('span');
  secLeft.textContent = 'Launch agent';
  const secRight = document.createElement('span');
  secRight.className = 'desktop-only';
  secRight.textContent = '1 click · Enter ↵';
  secHead.append(secLeft, secRight);
  frag.appendChild(secHead);

  const pickList = document.createElement('div');
  pickList.className = 'agent-pick-list';
  const hasDefault = list.some((a) => a.default);
  for (let i = 0; i < list.length; i += 1) {
    const ag = list[i];
    const isPrimary = ag.default || (!hasDefault && i === 0);
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = `agent-pick-btn${isPrimary ? ' is-default' : ''}`;
    btn.dataset.agent = ag.id;
    const ico = document.createElement('span');
    ico.className = 'agent-pick-ico';
    ico.innerHTML = pixelIconHtml(isAgentId(ag.id) ? ag.id : 'agent');
    const info = document.createElement('span');
    info.className = 'agent-pick-info';
    const nm = document.createElement('span');
    nm.className = 'agent-pick-name';
    nm.textContent = ag.name || agentLabel(ag.id);
    const cmd = document.createElement('span');
    cmd.className = 'agent-pick-cmd';
    cmd.textContent = ag.id;
    info.append(nm, cmd);
    btn.append(ico, info);
    if (ag.default || isPrimary) {
      const right = document.createElement('span');
      right.className = 'agent-pick-right';
      if (ag.default) {
        const def = document.createElement('span');
        def.className = 'agent-pick-def';
        def.textContent = 'default';
        right.appendChild(def);
      }
      if (isPrimary) {
        const ent = document.createElement('span');
        ent.className = 'agent-pick-enter desktop-only';
        ent.textContent = '↵';
        right.appendChild(ent);
      }
      btn.appendChild(right);
    }
    btn.addEventListener('click', () => {
      const chosenWt = isGit ? wtChoice : '';
      const noCtx = Boolean(updateCtxUi) && !ctxChoice;
      closePopover();
      if (typeof actions.spawnTab === 'function') {
        actions.spawnTab('agent', {
          agent: ag.id,
          cwd: selectedCwd || undefined,
          worktree_choice: chosenWt || undefined,
          context: noCtx ? false : undefined,
        });
      }
    });
    pickList.appendChild(btn);
  }

  if (includeShell) {
    const shBtn = document.createElement('button');
    shBtn.type = 'button';
    shBtn.className = `agent-pick-btn${isGit ? ' is-shell' : ''}`;
    shBtn.dataset.agent = 'shell';
    const ico = document.createElement('span');
    ico.className = 'agent-pick-ico';
    ico.innerHTML = pixelIconHtml('shell');
    const info = document.createElement('span');
    info.className = 'agent-pick-info';
    const nm = document.createElement('span');
    nm.className = 'agent-pick-name';
    nm.textContent = 'Shell';
    const cmd = document.createElement('span');
    cmd.className = 'agent-pick-cmd';
    cmd.textContent = 'bash';
    info.append(nm, cmd);
    shBtn.append(ico, info);
    if (isGit) {
      const tag = document.createElement('span');
      tag.className = 'shell-tag';
      tag.textContent = 'same folder';
      shBtn.appendChild(tag);
    }
    shBtn.addEventListener('click', () => {
      closePopover();
      if (typeof actions.spawnTab === 'function') actions.spawnTab('shell', { cwd: selectedCwd || undefined });
    });
    pickList.appendChild(shBtn);
  }

  frag.appendChild(pickList);

  if (isGit) {
    const links = document.createElement('div');
    links.className = 'spop-links';
    const modeSpan = document.createElement('span');
    modeSpan.append('Mode: ');
    const modeStrong = document.createElement('strong');
    modeStrong.textContent = prefs.mode || 'ask';
    modeSpan.appendChild(modeStrong);
    const cfgLink = document.createElement('button');
    cfgLink.type = 'button';
    cfgLink.className = 'spop-link-btn';
    cfgLink.textContent = 'Change in Settings';
    cfgLink.addEventListener('click', () => {
      closePopover();
      if (typeof actions.openSettings === 'function') actions.openSettings('box');
    });
    links.append(modeSpan, cfgLink);
    frag.appendChild(links);
  }

  openPopover(frag, (e) => {
    if (e.ctrlKey || e.metaKey || e.altKey) return false;
    const inInput = document.activeElement && document.activeElement.tagName === 'INPUT';
    if (!inInput && isGit && updateWtUi && (e.key === 'w' || e.key === 'W')) {
      e.preventDefault();
      e.stopPropagation();
      wtChoice = wtChoice === 'new' ? 'same' : 'new';
      updateWtUi();
      return true;
    }
    if (!inInput && updateCtxUi && (e.key === 'c' || e.key === 'C')) {
      e.preventDefault();
      e.stopPropagation();
      ctxChoice = !ctxChoice;
      updateCtxUi();
      return true;
    }
    if (!inInput && (e.key === 'ArrowDown' || e.key === 'ArrowUp')) {
      const btns = dom.popoverEl ? Array.from(dom.popoverEl.querySelectorAll('.agent-pick-btn')) : [];
      if (btns.length === 0) return false;
      e.preventDefault();
      e.stopPropagation();
      const idx = btns.indexOf(document.activeElement);
      const next = e.key === 'ArrowDown'
        ? (idx < 0 ? 0 : (idx + 1) % btns.length)
        : (idx <= 0 ? btns.length - 1 : idx - 1);
      btns[next].focus();
      return true;
    }
    return false;
  });
  if (showProjectPicker && projInputEl) {
    requestAnimationFrame(() => projInputEl.focus());
  }
}
