// Git worktree status, repo grouping, collision/worktree/pending/repo popovers, merge/verify/push actions, and pin wake.

import { state, dom, actions } from './state.js';
import { ICO_BRANCH_SVG, tabDisplayName } from './icons.js';
import { openPopover, closePopover, showTermToast, gitPopSig } from './ui-chrome.js';

export function openCollisionPopover(ctx) {
  const col = ctx.collision || {};
  const frag = document.createDocumentFragment();
  const head = document.createElement('div');
  head.className = 'spop-head';
  head.innerHTML = `<span style="display:inline-flex;align-items:center;gap:6px">${ICO_BRANCH_SVG}<span>Collision in ${col.repo_name || 'repo'}</span></span><span class="spop-badge">${col.branch || 'HEAD'}</span>`;
  const sub = document.createElement('div');
  sub.className = 'spop-sub';
  const n = (col.active_tabs && col.active_tabs.length) || 1;
  sub.textContent = `${n} active agent${n > 1 ? 's' : ''} already using this folder. How should this session open?`;

  const btnWt = document.createElement('button');
  btnWt.type = 'button';
  btnWt.className = 'spop-btn primary';
  btnWt.innerHTML = `<span style="display:inline-flex;align-items:center;gap:7px">${ICO_BRANCH_SVG}<span>New worktree</span></span><span class="spop-hint">Enter ↵</span>`;
  btnWt.addEventListener('click', () => {
    closePopover();
    if (ctx.kind === 'pin') wakePin(ctx.pinId, 'new');
    else if (typeof actions.spawnTab === 'function') actions.spawnTab(ctx.preset || 'agent', { cwd: ctx.cwd, agent: ctx.agent, worktree_choice: 'new', context: ctx.context });
  });

  const meta = document.createElement('div');
  meta.className = 'spop-meta';
  meta.textContent = ctx.kind === 'pin'
    ? `isolated branch from ${col.branch || 'HEAD'} · starts fresh session`
    : `isolated branch from ${col.branch || 'HEAD'}${state.worktreePrefs.copy_env ? ' · copies root .env' : ''}`;

  const btnSame = document.createElement('button');
  btnSame.type = 'button';
  btnSame.className = 'spop-btn secondary';
  btnSame.innerHTML = `<span>Same folder</span><span class="spop-hint">${ctx.kind === 'pin' ? '--continue' : 'share'}</span>`;
  btnSame.addEventListener('click', () => {
    closePopover();
    if (ctx.kind === 'pin') wakePin(ctx.pinId, 'same');
    else if (typeof actions.spawnTab === 'function') actions.spawnTab(ctx.preset || 'agent', { cwd: ctx.cwd, agent: ctx.agent, worktree_choice: 'same', context: ctx.context });
  });

  const links = document.createElement('div');
  links.className = 'spop-links';
  links.innerHTML = `<span>Mode: <strong>${state.worktreePrefs.mode}</strong></span>`;
  const cfgLink = document.createElement('button');
  cfgLink.type = 'button';
  cfgLink.className = 'spop-link-btn';
  cfgLink.textContent = 'Change in Settings';
  cfgLink.addEventListener('click', () => {
    closePopover();
    if (typeof actions.openSettings === 'function') actions.openSettings('box');
  });
  links.appendChild(cfgLink);

  frag.append(head, sub, btnWt, meta, btnSame, links);
  openPopover(frag);
}

export const MERGE_PREFS_KEY = 'swarmbox.mergePrefs.v1';

export function loadMergePrefs() {
  const def = { afterMerge: 'verify', squash: false, clean: true };
  try {
    const raw = localStorage.getItem(MERGE_PREFS_KEY);
    if (!raw) return def;
    const d = JSON.parse(raw);
    if (d && typeof d === 'object') {
      if (d.afterMerge === 'verify' || d.afterMerge === 'verify_push' || d.afterMerge === 'none') {
        def.afterMerge = d.afterMerge;
      }
      if (typeof d.squash === 'boolean') def.squash = d.squash;
      if (typeof d.clean === 'boolean') def.clean = d.clean;
    }
  } catch (_) {}
  return def;
}

export function saveMergePrefs(next) {
  try {
    localStorage.setItem(MERGE_PREFS_KEY, JSON.stringify({
      afterMerge: next.afterMerge,
      squash: Boolean(next.squash),
      clean: Boolean(next.clean),
    }));
  } catch (_) {}
}

export function buildAfterMergeSeg(initialVal, onChange) {
  const row = document.createElement('div');
  row.className = 'spop-seg-row';
  const lbl = document.createElement('span');
  lbl.className = 'spop-seg-label';
  lbl.textContent = 'After merge';
  const seg = document.createElement('div');
  seg.className = 'spop-seg';
  seg.setAttribute('role', 'radiogroup');
  seg.setAttribute('aria-label', 'After merge action');
  const items = [
    { val: 'verify', label: 'Verify' },
    { val: 'verify_push', label: 'Verify & Push' },
    { val: 'none', label: 'None' },
  ];
  let cur = initialVal;
  const btns = [];
  const syncUi = () => {
    for (const b of btns) {
      const active = b.dataset.val === cur;
      b.classList.toggle('is-active', active);
      b.setAttribute('aria-checked', active ? 'true' : 'false');
    }
  };
  for (const it of items) {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'spop-seg-btn';
    b.dataset.val = it.val;
    b.setAttribute('role', 'radio');
    b.textContent = it.label;
    b.addEventListener('click', () => {
      if (cur === it.val) return;
      cur = it.val;
      syncUi();
      if (onChange) onChange(cur);
    });
    btns.push(b);
    seg.appendChild(b);
  }
  syncUi();
  row.append(lbl, seg);
  return { row, getVal: () => cur };
}

export function formatHandoffToast(data, fallback) {
  const h = data && data.handoff;
  if (!h) return fallback;
  const willPush = h.push !== false;
  if (h.mode === 'agent') {
    return willPush
      ? `Sent test & push to ${h.title || 'main agent'}`
      : `Sent verification to ${h.title || 'main agent'}`;
  }
  if (h.mode === 'backend_verify') {
    return willPush
      ? `Running ${h.cmd || 'checks'} before push…`
      : `Running ${h.cmd || 'checks'} on main…`;
  }
  if (h.mode === 'manual_push') {
    return h.message || fallback;
  }
  return fallback;
}

export async function runMainRepoAction(repoRoot, action, okMsg) {
  const r = await fetch('/api/worktrees/main/action', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ repo: repoRoot, action }),
  });
  const d = await r.json().catch(() => ({}));
  if (!r.ok) {
    showTermToast(d.message || d.error || `Action ${action} failed`, 'error');
    return null;
  }
  const msg = typeof okMsg === 'function' ? okMsg(d) : okMsg;
  if (msg) showTermToast(msg, 'ok');
  return d;
}

export async function openWorktreePopover(termId, opts = {}) {
  const refresh = opts.refresh || null;
  const t = state.terminals.find((x) => x.address === termId);
  if (!t) return;
  if (!refresh) {
    const loading = document.createElement('div');
    loading.className = 'spop-sub';
    loading.textContent = 'Checking Git worktree status…';
    openPopover(loading);
  }

  let st;
  try {
    const r = await fetch(`/api/tabs/${encodeURIComponent(termId)}/worktree`);
    st = await r.json();
    if (!r.ok) throw new Error(st.message || 'Not a Git worktree');
  } catch (err) {
    if (refresh) return;
    const box = document.createDocumentFragment();
    const errHead = document.createElement('div');
    errHead.className = 'spop-head';
    errHead.innerHTML = `<span style="display:inline-flex;align-items:center;gap:6px">${ICO_BRANCH_SVG}<span>Worktree unavailable</span></span><span class="wt-kbd desktop-only">Esc</span>`;
    const m = document.createElement('div');
    m.className = 'spop-sub';
    m.textContent = err.message || 'This session is not running inside a linked Git worktree.';
    const c = document.createElement('button');
    c.type = 'button';
    c.className = 'spop-btn secondary';
    c.textContent = 'Close';
    c.addEventListener('click', closePopover);
    box.append(errHead, m, c);
    openPopover(box);
    return;
  }

  let repoSt = (st.repo_root && state.repoStatuses[st.repo_root]) || null;
  if (st.repo_root) {
    try {
      const rr = await fetch(`/api/worktrees/repo-status?repo=${encodeURIComponent(st.repo_root)}`, { cache: 'no-store' });
      if (rr.ok) repoSt = await rr.json();
    } catch (_) {}
  }
  const sig = gitPopSig([st, repoSt]);
  if (refresh && (state.gitPopRefresh !== refresh || !state.popoverOpen || refresh.sig === sig)) return;
  const mainAgent = (repoSt && repoSt.main_agent) || null;
  const verifyCmd = st.verify_cmd || (repoSt && repoSt.verify_cmd) || '';
  const behindSuffix = (!st.dirty && st.behind > 0) ? ` · ${st.behind} behind ${st.base}` : '';

  const frag = document.createDocumentFragment();
  const head = document.createElement('div');
  head.className = 'spop-head';
  const badgeCls = st.dirty || !st.can_merge || st.main_dirty ? 'warn' : 'ok';
  const badgeTxt = st.dirty ? 'DIRTY' : !st.can_merge ? 'CONFLICT' : st.ahead > 0 ? 'CLEAN' : 'EMPTY';
  const headLeft = document.createElement('span');
  headLeft.style.cssText = 'display:inline-flex;align-items:center;gap:6px;min-width:0';
  headLeft.innerHTML = `${ICO_BRANCH_SVG}<span></span>`;
  headLeft.querySelector('span').textContent = `${st.branch} → ${st.base}`;
  const headBadge = document.createElement('span');
  headBadge.className = `spop-badge ${badgeCls}`;
  headBadge.textContent = badgeTxt;
  head.append(headLeft, headBadge);

  const sub = document.createElement('div');
  sub.className = 'spop-sub';
  if (st.dirty) {
    sub.textContent = `${st.uncommitted_count} uncommitted change${st.uncommitted_count === 1 ? '' : 's'} in this worktree.`;
  } else if (st.ahead === 0) {
    sub.textContent = `No commits ahead of ${st.base}${behindSuffix}. Safe to close and remove.`;
  } else if (!st.can_merge) {
    sub.textContent = `${st.ahead} commit${st.ahead === 1 ? '' : 's'} ahead${behindSuffix} · conflict with ${st.base} in ${(st.conflict_files || []).join(', ') || 'files'}.`;
  } else if (st.main_dirty) {
    sub.textContent = `${st.ahead} commit${st.ahead === 1 ? '' : 's'} ahead${behindSuffix} · ${st.base} has uncommitted changes.`;
  } else {
    sub.textContent = `${st.ahead} commit${st.ahead === 1 ? '' : 's'} ahead${behindSuffix} · 0 conflicts.`;
  }

  frag.append(head, sub);

  // Rich preview block (commits + diff stat + View diff) when ahead > 0
  if (st.ahead > 0 && ((Array.isArray(st.commits) && st.commits.length > 0) || st.diff_stat)) {
    const preview = document.createElement('div');
    preview.className = 'spop-wt-preview';

    if (Array.isArray(st.commits) && st.commits.length > 0) {
      const cList = document.createElement('div');
      cList.className = 'spop-commit-list';
      const shown = st.commits.slice(0, 4);
      for (const c of shown) {
        const row = document.createElement('div');
        row.className = 'spop-commit-row';
        const sha = document.createElement('span');
        sha.className = 'spop-commit-sha';
        sha.textContent = String(c.sha || '').slice(0, 7);
        const subj = document.createElement('span');
        subj.className = 'spop-commit-subj';
        subj.textContent = c.subject || '';
        subj.title = c.subject || '';
        row.append(sha, subj);
        if (c.rel_time) {
          const tm = document.createElement('span');
          tm.className = 'spop-commit-time';
          tm.textContent = c.rel_time;
          row.appendChild(tm);
        }
        cList.appendChild(row);
      }
      if (st.commits.length > 4) {
        const more = document.createElement('div');
        more.className = 'spop-commit-more';
        more.textContent = `+${st.commits.length - 4} more commit${st.commits.length - 4 === 1 ? '' : 's'}`;
        cList.appendChild(more);
      }
      preview.appendChild(cList);
    }

    const statRow = document.createElement('div');
    statRow.className = 'spop-diff-stat';
    const statTxt = document.createElement('span');
    const ds = st.diff_stat;
    if (ds && typeof ds.files === 'number') {
      const filesLabel = `${ds.files} file${ds.files === 1 ? '' : 's'}`;
      statTxt.innerHTML = `${filesLabel} · <span class="spop-stat-add">+${ds.insertions || 0}</span> <span class="spop-stat-del">-${ds.deletions || 0}</span>`;
    } else {
      statTxt.textContent = `${st.ahead} commit${st.ahead === 1 ? '' : 's'} ahead`;
    }
    const diffBtn = document.createElement('button');
    diffBtn.type = 'button';
    diffBtn.className = 'spop-link-btn';
    diffBtn.textContent = 'View diff';
    diffBtn.addEventListener('click', () => {
      closePopover();
      if (typeof actions.openDiffInDrawer === 'function') actions.openDiffInDrawer(st.path, `${st.branch} vs ${st.base}`);
    });
    statRow.append(statTxt, diffBtn);
    preview.appendChild(statRow);
    frag.appendChild(preview);
  }

  let squashChk = null;

  if (st.dirty) {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'spop-btn primary';
    btn.innerHTML = '<span>Ask agent to commit</span><span class="spop-hint">in this tab</span>';
    btn.addEventListener('click', async () => {
      closePopover();
      await fetch('/api/worktrees/commit', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ terminal: termId }),
      });
      showTermToast('Asked agent to commit changes');
    });
    frag.appendChild(btn);
  } else if (st.ahead > 0 && !st.can_merge) {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'spop-btn amber';
    btn.innerHTML = '<span>Resolve conflict with agent</span><span class="spop-hint">in worktree</span>';
    btn.addEventListener('click', async () => {
      closePopover();
      await fetch('/api/worktrees/resolve-conflict', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ terminal: termId, base: st.base }),
      });
      showTermToast(`Asked agent to merge ${st.base} & resolve conflict inside worktree`);
    });
    frag.appendChild(btn);
  } else if (st.ahead > 0 && st.main_dirty) {
    if (mainAgent && st.repo_root) {
      const btnCommitMain = document.createElement('button');
      btnCommitMain.type = 'button';
      btnCommitMain.className = 'spop-btn primary';
      btnCommitMain.innerHTML = '<span>Ask main agent to commit</span><span class="spop-hint"></span>';
      btnCommitMain.querySelector('.spop-hint').textContent = mainAgent.title || st.base;
      btnCommitMain.addEventListener('click', async () => {
        closePopover();
        await runMainRepoAction(st.repo_root, 'commit', `Asked ${mainAgent.title || 'main agent'} to commit`);
      });
      const btnFocusMain = document.createElement('button');
      btnFocusMain.type = 'button';
      btnFocusMain.className = 'spop-btn secondary';
      btnFocusMain.innerHTML = `<span>Focus ${st.base}</span><span class="spop-hint">switch tab</span>`;
      btnFocusMain.addEventListener('click', () => {
        closePopover();
        if (state.activeId !== mainAgent.address) {
          if (typeof actions.connectPty === 'function') actions.connectPty(mainAgent.address);
        } else if (typeof actions.focusTerminalIfDesktop === 'function') {
          actions.focusTerminalIfDesktop();
        }
      });
      frag.append(btnCommitMain, btnFocusMain);
    } else {
      const mainTerm = state.terminals.find((x) =>
        x.repo && x.repo.root === st.repo_root && !(x.labels && x.labels['swarmbox.worktree']),
      );
      if (mainTerm) {
        const btnFocusMain = document.createElement('button');
        btnFocusMain.type = 'button';
        btnFocusMain.className = 'spop-btn primary';
        btnFocusMain.innerHTML = `<span>Focus ${st.base}</span><span class="spop-hint">commit there first</span>`;
        btnFocusMain.addEventListener('click', () => {
          closePopover();
          if (state.activeId !== mainTerm.address) {
            if (typeof actions.connectPty === 'function') actions.connectPty(mainTerm.address);
          } else if (typeof actions.focusTerminalIfDesktop === 'function') {
            actions.focusTerminalIfDesktop();
          }
        });
        frag.appendChild(btnFocusMain);
      }
    }
  } else if (st.ahead > 0 && st.can_merge && !st.main_dirty) {
    const mPrefs = loadMergePrefs();
    const optsBox = document.createElement('div');
    optsBox.className = 'spop-merge-opts';

    const btnExec = document.createElement('button');
    btnExec.type = 'button';
    btnExec.className = 'spop-btn green';
    btnExec.innerHTML = '<span class="spop-btn-lbl"></span><span class="spop-hint"></span>';
    const lblEl = btnExec.querySelector('.spop-btn-lbl');
    const hintEl = btnExec.querySelector('.spop-hint');

    const updatePrimaryBtn = () => {
      const verb = mPrefs.squash ? 'Squash' : 'Merge';
      if (mPrefs.afterMerge === 'verify') {
        lblEl.textContent = `${verb} → Verify`;
        hintEl.textContent = mainAgent ? 'via main agent' : (verifyCmd ? 'run check' : st.base);
      } else if (mPrefs.afterMerge === 'verify_push') {
        lblEl.textContent = `${verb} → Verify & Push`;
        hintEl.textContent = mainAgent ? 'via main agent' : (verifyCmd ? 'check + push' : 'merge + push');
      } else {
        lblEl.textContent = `${verb} into ${st.base}`;
        hintEl.textContent = mPrefs.clean ? 'local only' : 'keep tab';
      }
    };

    const segCtrl = buildAfterMergeSeg(mPrefs.afterMerge, (val) => {
      mPrefs.afterMerge = val;
      saveMergePrefs(mPrefs);
      updatePrimaryBtn();
    });

    const checksRow = document.createElement('div');
    checksRow.className = 'spop-opts-row';

    const squashLabel = document.createElement('label');
    squashLabel.className = 'spop-check';
    squashChk = document.createElement('input');
    squashChk.type = 'checkbox';
    squashChk.checked = mPrefs.squash;
    squashChk.addEventListener('change', () => {
      mPrefs.squash = squashChk.checked;
      saveMergePrefs(mPrefs);
      updatePrimaryBtn();
    });
    const squashSpan = document.createElement('span');
    squashSpan.textContent = 'Squash';
    squashLabel.append(squashChk, squashSpan);

    const cleanLabel = document.createElement('label');
    cleanLabel.className = 'spop-check';
    const cleanChk = document.createElement('input');
    cleanChk.type = 'checkbox';
    cleanChk.checked = mPrefs.clean;
    cleanChk.addEventListener('change', () => {
      mPrefs.clean = cleanChk.checked;
      saveMergePrefs(mPrefs);
      updatePrimaryBtn();
    });
    const cleanSpan = document.createElement('span');
    cleanSpan.textContent = 'Close & remove';
    cleanLabel.append(cleanChk, cleanSpan);

    checksRow.append(squashLabel, cleanLabel);
    optsBox.append(segCtrl.row, checksRow);
    updatePrimaryBtn();

    btnExec.addEventListener('click', async () => {
      const doVerify = mPrefs.afterMerge === 'verify' || mPrefs.afterMerge === 'verify_push';
      const doPush = mPrefs.afterMerge === 'verify_push';
      closePopover();
      const r = await fetch('/api/worktrees/merge', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          terminal: termId,
          path: st.path,
          clean: mPrefs.clean,
          squash: mPrefs.squash,
          verify: doVerify,
          push: doPush,
        }),
      });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) {
        showTermToast(d.message || d.error || 'Merge failed', 'error');
        return;
      }
      const fallback = mPrefs.clean
        ? `Merged ${st.branch} into ${st.base} & cleaned worktree`
        : `Merged ${st.branch} into ${st.base}`;
      showTermToast(formatHandoffToast(d, fallback), 'ok', 3600);
    });

    frag.append(optsBox, btnExec);
  } else if (st.ahead === 0 && !st.dirty) {
    const btnClean = document.createElement('button');
    btnClean.type = 'button';
    btnClean.className = 'spop-btn secondary';
    btnClean.textContent = 'Close & remove worktree';
    btnClean.addEventListener('click', async () => {
      closePopover();
      await fetch('/api/worktrees/remove', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: st.path, terminal: termId }),
      });
      showTermToast('Removed empty worktree');
    });
    frag.appendChild(btnClean);
  }

  // Sync with base button when clean and behind
  if (!st.dirty && st.behind > 0) {
    const syncSlot = document.createElement('div');
    syncSlot.className = 'spop-sync-slot';
    const btnSync = document.createElement('button');
    btnSync.type = 'button';
    btnSync.className = 'spop-btn secondary';
    btnSync.innerHTML = `<span>Sync with ${st.base}</span><span class="spop-hint">${st.behind} behind</span>`;
    btnSync.addEventListener('click', async () => {
      btnSync.disabled = true;
      btnSync.querySelector('.spop-hint').textContent = 'syncing…';
      try {
        const r = await fetch('/api/worktrees/sync', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ path: st.path, terminal: termId }),
        });
        const d = await r.json().catch(() => ({}));
        if (r.status === 409 && d.error === 'sync_conflict') {
          const cFiles = (d.conflict_files || []).join(', ');
          showTermToast(`Sync conflict${cFiles ? ` in ${cFiles}` : ''}`, 'error', 3600);
          syncSlot.innerHTML = '';
          const btnRes = document.createElement('button');
          btnRes.type = 'button';
          btnRes.className = 'spop-btn amber';
          btnRes.innerHTML = '<span>Resolve conflict with agent</span><span class="spop-hint">in worktree</span>';
          btnRes.addEventListener('click', async () => {
            closePopover();
            await fetch('/api/worktrees/resolve-conflict', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ terminal: termId, base: st.base }),
            });
            showTermToast(`Asked agent to merge ${st.base} & resolve conflict inside worktree`);
          });
          syncSlot.appendChild(btnRes);
          return;
        }
        if (!r.ok) {
          btnSync.disabled = false;
          btnSync.querySelector('.spop-hint').textContent = `${st.behind} behind`;
          showTermToast(d.message || d.error || 'Sync failed', 'error');
          return;
        }
        showTermToast(`Synced ${st.branch} with ${st.base}`, 'ok');
        openWorktreePopover(termId);
      } catch (_) {
        btnSync.disabled = false;
        btnSync.querySelector('.spop-hint').textContent = `${st.behind} behind`;
        showTermToast('Sync failed', 'error');
      }
    });
    syncSlot.appendChild(btnSync);
    frag.appendChild(syncSlot);
  }

  const links = document.createElement('div');
  links.className = 'spop-links';
  const leftLinks = document.createElement('div');
  leftLinks.className = 'spop-links-group';

  const prBtn = document.createElement('button');
  prBtn.type = 'button';
  prBtn.className = 'spop-link-btn';
  prBtn.textContent = 'Push / Open PR';
  prBtn.addEventListener('click', async () => {
    closePopover();
    await fetch(`/api/tabs/${encodeURIComponent(termId)}/send`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: `Push branch ${st.branch} and open a Pull Request targeting ${st.base}.`, force: true }),
    });
    showTermToast('Asked agent to push & open PR');
  });
  leftLinks.appendChild(prBtn);

  const closeLink = document.createElement('button');
  closeLink.type = 'button';
  closeLink.className = 'spop-link-btn';
  closeLink.textContent = 'Keep worktree';
  closeLink.addEventListener('click', closePopover);
  links.append(leftLinks, closeLink);
  frag.appendChild(links);
  openPopover(frag);
  state.gitPopRefresh = { sig, run: (r) => openWorktreePopover(termId, { refresh: r }) };
}

export function openPendingWorktreesPopover() {
  const frag = document.createDocumentFragment();
  const head = document.createElement('div');
  head.className = 'spop-head';
  head.innerHTML = `<span style="display:inline-flex;align-items:center;gap:6px">${ICO_BRANCH_SVG}<span>Pending worktrees</span></span><span class="spop-badge warn">${state.pendingWorktrees.length}</span>`;
  const sub = document.createElement('div');
  sub.className = 'spop-sub';
  sub.textContent = 'Closed worktrees kept safe because they still have uncommitted changes or unmerged commits.';
  const list = document.createElement('div');
  list.className = 'spop-wt-list';

  for (const w of state.pendingWorktrees) {
    const row = document.createElement('div');
    row.className = 'spop-wt-row';
    const top = document.createElement('div');
    top.className = 'spop-wt-row-top';
    top.innerHTML = `<span>${w.repo_name} · <strong>${w.branch}</strong></span><span class="spop-badge ${w.dirty || !w.can_merge ? 'warn' : 'ok'}">${w.dirty ? `${w.uncommitted_count} dirty` : `${w.ahead} ahead`}</span>`;
    const btns = document.createElement('div');
    btns.className = 'spop-wt-row-btns';
    const bOpen = document.createElement('button');
    bOpen.type = 'button';
    bOpen.textContent = 'Reopen';
    bOpen.addEventListener('click', async () => {
      closePopover();
      const r = await fetch('/api/worktrees/open', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: w.path }),
      });
      const d = await r.json().catch(() => ({}));
      const addr = (d && d.terminal && d.terminal.address) || (d && d.address);
      if (addr) setTimeout(() => { if (typeof actions.connectPty === 'function') actions.connectPty(addr); }, 100);
    });
    const bRm = document.createElement('button');
    bRm.type = 'button';
    bRm.textContent = 'Discard & remove';
    bRm.addEventListener('click', async () => {
      await fetch('/api/worktrees/remove', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: w.path, force: true }),
      });
      closePopover();
      showTermToast(`Removed worktree ${w.branch}`);
    });
    btns.append(bOpen, bRm);
    row.append(top, btns);
    list.appendChild(row);
  }

  const foot = document.createElement('div');
  foot.className = 'spop-links';
  const doneBtn = document.createElement('button');
  doneBtn.type = 'button';
  doneBtn.className = 'spop-link-btn';
  doneBtn.textContent = 'Close';
  doneBtn.addEventListener('click', closePopover);
  foot.appendChild(doneBtn);
  frag.append(head, sub, list, foot);
  openPopover(frag);
}

export function buildSysopMergeAllLabel({ repoName, targetBranch, total, afterMerge }) {
  const target = targetBranch || 'main';
  const suffix = afterMerge === 'verify_push'
    ? ' → Verify & Push'
    : afterMerge === 'verify'
      ? ' → Verify'
      : '';
  return `Merge ${total} worktree${total === 1 ? '' : 's'} · ${repoName} → ${target}${suffix}`;
}

export function buildSysopMergeAllGoal({ repoName, repoRoot, targetBranch, mainDirty, activeWorktrees, pendingWorktrees, afterMerge }) {
  const target = targetBranch || 'main';
  const items = [];
  for (const { t, st } of (activeWorktrees || [])) {
    const br = (st && st.branch) || (t && t.labels && t.labels['swarmbox.branch']) || 'worktree';
    const tabRef = (t && t.address) ? `${t.address} (${tabDisplayName(t)})` : '';
    const flags = [];
    if (!st) {
      flags.push('status unknown');
    } else {
      if (st.dirty) flags.push(`${st.uncommitted_count || 1} uncommitted`);
      if (st.ahead > 0) flags.push(`${st.ahead} ahead`);
      else flags.push('0 ahead');
      if (st.behind > 0) flags.push(`${st.behind} behind`);
      if (st.ahead > 0 && !st.can_merge) flags.push('conflict');
    }
    items.push(`- active tab ${tabRef}: branch ${br} [${flags.join(', ')}]`);
  }
  for (const w of (pendingWorktrees || [])) {
    const br = w.branch || w.id || w.path || 'worktree';
    const flags = ['parked'];
    if (w.dirty) flags.push(`${w.uncommitted_count || 1} uncommitted`);
    if (w.ahead > 0) flags.push(`${w.ahead} ahead`);
    if (w.ahead > 0 && w.can_merge === false) flags.push('conflict');
    items.push(`- parked worktree ${w.id || br} (${w.path || br}): branch ${br} [${flags.join(', ')}]`);
  }

  const postStep = afterMerge === 'verify_push'
    ? `After all worktrees are merged and cleaned, run the repo's verification checks on "${target}" and push to origin only if checks pass.`
    : afterMerge === 'verify'
      ? `After all worktrees are merged and cleaned, run the repo's verification checks on "${target}" (do not push).`
      : `Do NOT push to origin; leave "${target}" clean locally.`;

  return [
    `Consolidate ALL worktrees of repository "${repoName}" (${repoRoot}) into branch "${target}" until ONLY "${target}" remains with zero active or parked worktrees for this repo.`,
    `Scope: ONLY repository "${repoName}" at "${repoRoot}". Do NOT touch tabs, branches, or worktrees belonging to other repositories.`,
    '',
    `Current state (${mainDirty ? `"${target}" is currently DIRTY` : `"${target}" is clean`}):`,
    ...items,
    '',
    'Required workflow — go ALL THE WAY to completion:',
    `1. Do NOT call done after merely queuing messages to agents. Wait for each agent to finish (using wait, read_tab, and worktree status), then merge and clean it, and keep going until every worktree of "${repoName}" is resolved.`,
    `2. If "${target}" itself has uncommitted changes, inspect/commit them first (via the main agent if one is open, or safely in the repo) so merges are unblocked.`,
    `3. Merge already-clean, conflict-free worktrees first with worktree(action="merge", clean=true).`,
    `4. Remove empty clean worktrees (0 ahead, not dirty) with worktree(action="remove") and close their tabs.`,
    `5. For any dirty worktree: ask its agent to review and commit all work (never discard uncommitted changes without permission), wait until it is clean, re-check worktree status, then merge with clean=true. For parked dirty/conflicted worktrees, wake/open or inspect them safely before merging.`,
    `6. For any worktree with merge conflicts against "${target}": ask its agent to rebase/merge "${target}" and resolve conflicts, wait until clean and conflict-free, re-check status, then merge with clean=true.`,
    `7. After each merge, refresh with box_state / worktree status because merging one branch can create conflicts in another. Repeat until zero active or parked worktrees remain for "${repoName}".`,
    `8. Narrate progress briefly with say after each milestone (merged, waiting on agent, conflict resolution, or blocker).`,
    `9. ${postStep}`,
    `10. Stop early ONLY if you hit a real blocker, user dialog, or denied approval; otherwise finish completely and summarize every merged/removed worktree in done.`,
  ].join('\n');
}

export async function openRepoWorktreesPopover(group, opts = {}) {
  const refresh = opts.refresh || null;
  if (!group) return;
  const activeWts = (group.activeWorktrees || []);
  const pendingWts = (group.pendingWorktrees || []);
  const total = activeWts.length + pendingWts.length;
  const cachedRs = (group.root && state.repoStatuses[group.root]) || null;
  if (total === 0 && !cachedRs && !group.root) return;

  const loading = document.createElement('div');
  loading.className = 'spop-sub';
  loading.textContent = `Loading ${group.name} status…`;
  if (!refresh) openPopover(loading);

  const [fetchedRs, statuses] = await Promise.all([
    group.root
      ? fetch(`/api/worktrees/repo-status?repo=${encodeURIComponent(group.root)}`, { cache: 'no-store' })
          .then((r) => (r.ok ? r.json() : null))
          .catch(() => null)
      : Promise.resolve(null),
    Promise.all(activeWts.map(async (t) => {
      try {
        const r = await fetch(`/api/worktrees/status?terminal=${encodeURIComponent(t.address)}`, { cache: 'no-store' });
        if (!r.ok) return { t, st: null };
        return { t, st: await r.json() };
      } catch (_) {
        return { t, st: null };
      }
    })),
  ]);
  const rs = fetchedRs || cachedRs;
  const sig = gitPopSig([rs, statuses.map(({ st }) => st), pendingWts]);
  if (refresh && (state.gitPopRefresh !== refresh || !state.popoverOpen || refresh.sig === sig)) return;

  const frag = document.createDocumentFragment();
  const head = document.createElement('div');
  head.className = 'spop-head';
  const titleEl = document.createElement('span');
  titleEl.style.cssText = 'display:inline-flex;align-items:center;gap:6px';
  titleEl.innerHTML = `${ICO_BRANCH_SVG}<span></span>`;
  titleEl.querySelector('span').textContent = total > 0
    ? `${group.name} · ${total} worktree${total === 1 ? '' : 's'}`
    : `${group.name} · ${(rs && rs.branch) || 'main'}`;
  const escBadge = document.createElement('span');
  escBadge.className = 'wt-kbd desktop-only';
  escBadge.textContent = 'Esc';
  head.append(titleEl, escBadge);
  frag.appendChild(head);

  // Top Card: main branch control
  if (rs) {
    const mainCard = document.createElement('div');
    mainCard.className = 'spop-main-card';

    const mTop = document.createElement('div');
    mTop.className = 'spop-main-top';
    const mLeft = document.createElement('div');
    mLeft.className = 'spop-main-branch';
    mLeft.textContent = rs.branch || 'main';

    const vj = rs.verify_job || null;
    const mBadge = document.createElement('span');
    if (vj && vj.state === 'running') {
      mBadge.className = 'spop-badge checking';
      mBadge.textContent = 'CHECKING';
    } else if (vj && vj.state === 'failed') {
      mBadge.className = 'spop-badge err';
      mBadge.textContent = 'CHECK FAILED';
    } else if (rs.dirty) {
      mBadge.className = 'spop-badge warn';
      mBadge.textContent = 'DIRTY';
    } else {
      mBadge.className = 'spop-badge ok';
      mBadge.textContent = 'CLEAN';
    }
    mTop.append(mLeft, mBadge);

    const mSync = document.createElement('div');
    mSync.className = 'spop-main-sync';
    const syncParts = [];
    if (rs.dirty) {
      syncParts.push(`${rs.uncommitted_count || 1} uncommitted change${(rs.uncommitted_count || 1) === 1 ? '' : 's'}`);
    }
    if (rs.ahead_origin > 0) {
      syncParts.push(`↑${rs.ahead_origin} ahead of ${rs.upstream || 'origin'}`);
    }
    if (rs.behind_origin > 0) {
      syncParts.push(`↓${rs.behind_origin} behind`);
    }
    if (!syncParts.length) {
      syncParts.push(rs.upstream ? `synced with ${rs.upstream}` : 'working tree clean');
    }
    mSync.textContent = syncParts.join(' · ');
    mainCard.append(mTop, mSync);

    if (vj && (vj.state === 'running' || vj.state === 'failed' || vj.state === 'pushed' || vj.state === 'passed')) {
      const strip = document.createElement('div');
      strip.className = `spop-verify-strip is-${vj.state}`;
      const stripTxt = document.createElement('span');
      if (vj.state === 'running') {
        stripTxt.textContent = `Running ${vj.cmd || 'verification'}…`;
      } else if (vj.state === 'failed') {
        stripTxt.textContent = `Check failed${vj.exit_code != null ? ` (exit ${vj.exit_code})` : ''}`;
      } else if (vj.state === 'pushed') {
        stripTxt.textContent = 'Verified & pushed';
      } else {
        stripTxt.textContent = 'Checks passed';
      }
      strip.appendChild(stripTxt);
      if (vj.state === 'failed' || vj.output || vj.error) {
        const logBtn = document.createElement('button');
        logBtn.type = 'button';
        logBtn.className = 'spop-link-btn';
        logBtn.textContent = 'View log';
        logBtn.addEventListener('click', () => {
          closePopover();
          if (typeof actions.openLogInDrawer === 'function') {
            actions.openLogInDrawer(
              `${group.name} · ${vj.state === 'failed' ? 'check failed' : 'check output'}`,
              vj.cmd || '',
              vj.output || vj.error || 'No output recorded.',
            );
          }
        });
        strip.appendChild(logBtn);
      }
      mainCard.appendChild(strip);
    }

    const mActs = document.createElement('div');
    mActs.className = 'spop-main-acts';
    if (rs.dirty && rs.main_agent) {
      const bCommit = document.createElement('button');
      bCommit.type = 'button';
      bCommit.className = 'spop-btn primary spop-btn-sm';
      bCommit.innerHTML = '<span>Commit main</span><span class="spop-hint">via agent</span>';
      bCommit.addEventListener('click', async () => {
        closePopover();
        await runMainRepoAction(group.root, 'commit', 'Asked main agent to commit');
      });
      const bFocus = document.createElement('button');
      bFocus.type = 'button';
      bFocus.className = 'spop-btn secondary spop-btn-sm spop-btn-fit';
      bFocus.textContent = 'Focus';
      bFocus.addEventListener('click', () => {
        closePopover();
        if (state.activeId !== rs.main_agent.address) {
          if (typeof actions.connectPty === 'function') actions.connectPty(rs.main_agent.address);
        } else if (typeof actions.focusTerminalIfDesktop === 'function') {
          actions.focusTerminalIfDesktop();
        }
      });
      mActs.append(bCommit, bFocus);
    } else if (!rs.dirty && rs.ahead_origin > 0) {
      const bTestPush = document.createElement('button');
      bTestPush.type = 'button';
      bTestPush.className = 'spop-btn green spop-btn-sm';
      const hint = rs.main_agent ? 'via main agent' : (rs.verify_cmd ? 'check + push' : 'push');
      bTestPush.innerHTML = `<span>Test &amp; Push</span><span class="spop-hint">${hint}</span>`;
      bTestPush.addEventListener('click', async () => {
        closePopover();
        await runMainRepoAction(group.root, 'verify_and_push', (d) => formatHandoffToast(d, 'Started verify & push on main'));
      });
      const bPush = document.createElement('button');
      bPush.type = 'button';
      bPush.className = 'spop-btn secondary spop-btn-sm spop-btn-fit';
      bPush.textContent = 'Push now';
      bPush.addEventListener('click', async () => {
        closePopover();
        await runMainRepoAction(group.root, 'push', `Pushed ${rs.branch || 'main'} to origin`);
      });
      mActs.append(bTestPush, bPush);
    }
    if (mActs.childNodes.length > 0) mainCard.appendChild(mActs);

    if (rs.can_undo_merge) {
      const undoRow = document.createElement('div');
      undoRow.className = 'spop-main-undo';
      const undoBtn = document.createElement('button');
      undoBtn.type = 'button';
      undoBtn.className = 'spop-link-btn';
      undoBtn.textContent = 'Undo last merge';
      undoBtn.title = 'Reset main back to the commit before the last worktree merge';
      undoBtn.addEventListener('click', async () => {
        closePopover();
        await runMainRepoAction(group.root, 'undo_merge', `Undid last merge on ${rs.branch || 'main'}`);
      });
      undoRow.appendChild(undoBtn);
      mainCard.appendChild(undoRow);
    }

    frag.appendChild(mainCard);
  }

  // Batch merge bar: deterministic Merge all (when >= 2 ready) and/or Ask Sysop to merge all (when Sysop is up)
  const repoMergePrefs = loadMergePrefs();
  const readyCount = statuses.filter(({ st }) => st && !st.dirty && st.ahead > 0 && st.can_merge && !st.main_dirty).length;
  const sysopUp = Boolean(state.lastSysopSnap && state.lastSysopSnap.up);
  const targetBranch = (rs && rs.branch) || 'main';
  const showDeterministicBatch = readyCount >= 2 && Boolean(group.root);
  const showSysopMergeAll = sysopUp && total >= 1 && Boolean(group.root);
  const rowMergeBtns = [];
  const syncBatchLabels = () => {
    const m = repoMergePrefs.afterMerge;
    for (const b of rowMergeBtns) {
      b.textContent = m === 'verify' ? 'Merge & verify' : m === 'verify_push' ? 'Merge & push' : 'Merge';
    }
  };
  if (showDeterministicBatch || showSysopMergeAll) {
    const batchBox = document.createElement('div');
    batchBox.className = 'spop-merge-opts';
    let mAllLbl = null;
    let sysopMergeLbl = null;
    const updateBatchBtn = () => {
      const m = repoMergePrefs.afterMerge;
      if (mAllLbl) {
        mAllLbl.textContent = m === 'verify'
          ? `Merge all (${readyCount}) → Verify`
          : m === 'verify_push'
            ? `Merge all (${readyCount}) → Verify & Push`
            : `Merge all (${readyCount})`;
      }
      if (sysopMergeLbl) {
        const base = total === 1 ? 'Ask Sysop to merge' : `Ask Sysop to merge all (${total})`;
        sysopMergeLbl.textContent = m === 'verify'
          ? `${base} → Verify`
          : m === 'verify_push'
            ? `${base} → Verify & Push`
            : base;
      }
      syncBatchLabels();
    };
    const segCtrl = buildAfterMergeSeg(repoMergePrefs.afterMerge, (val) => {
      repoMergePrefs.afterMerge = val;
      saveMergePrefs(repoMergePrefs);
      updateBatchBtn();
    });
    batchBox.appendChild(segCtrl.row);

    if (showDeterministicBatch) {
      const mergeAllBtn = document.createElement('button');
      mergeAllBtn.type = 'button';
      mergeAllBtn.className = 'spop-btn green spop-btn-sm';
      mergeAllBtn.innerHTML = '<span class="spop-btn-lbl"></span><span class="spop-hint">batch</span>';
      mAllLbl = mergeAllBtn.querySelector('.spop-btn-lbl');
      mergeAllBtn.addEventListener('click', async () => {
        const doVerify = repoMergePrefs.afterMerge === 'verify' || repoMergePrefs.afterMerge === 'verify_push';
        const doPush = repoMergePrefs.afterMerge === 'verify_push';
        closePopover();
        const r = await fetch('/api/worktrees/merge-all', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ repo: group.root, clean: true, verify: doVerify, push: doPush }),
        });
        const d = await r.json().catch(() => ({}));
        if (!r.ok) {
          showTermToast(d.message || d.error || 'Batch merge failed', 'error');
          return;
        }
        const mLen = Array.isArray(d.merged) ? d.merged.length : readyCount;
        const fLen = Array.isArray(d.failed) ? d.failed.length : 0;
        const baseMsg = `Merged ${mLen} worktree${mLen === 1 ? '' : 's'}${fLen ? ` (${fLen} failed)` : ''}`;
        showTermToast(formatHandoffToast(d, baseMsg), fLen ? '' : 'ok', 3800);
      });
      batchBox.appendChild(mergeAllBtn);
    }

    if (showSysopMergeAll) {
      const sysopMergeBtn = document.createElement('button');
      sysopMergeBtn.type = 'button';
      sysopMergeBtn.className = 'spop-btn primary spop-btn-sm';
      const lblSpan = document.createElement('span');
      lblSpan.className = 'spop-btn-lbl';
      const hintSpan = document.createElement('span');
      hintSpan.className = 'spop-hint';
      hintSpan.textContent = `→ ${targetBranch}`;
      sysopMergeBtn.append(lblSpan, hintSpan);
      sysopMergeBtn.title = `Ask Sysop to commit, resolve conflicts, merge, and clean all worktrees of ${group.name} into ${targetBranch}`;
      sysopMergeLbl = lblSpan;
      sysopMergeBtn.addEventListener('click', () => {
        const goal = buildSysopMergeAllGoal({
          repoName: group.name,
          repoRoot: group.root,
          targetBranch,
          mainDirty: Boolean(rs && rs.dirty),
          activeWorktrees: statuses,
          pendingWorktrees: pendingWts,
          afterMerge: repoMergePrefs.afterMerge,
        });
        closePopover();
        const isMob = typeof actions.isMobileLayout === 'function' ? actions.isMobileLayout() : false;
        if (!isMob && dom.appEl && dom.appEl.dataset.sysopOpen !== '1') {
          if (typeof actions.setDesktopSysop === 'function') actions.setDesktopSysop(true);
        }
        if (typeof actions.sendGoal === 'function') {
          const label = buildSysopMergeAllLabel({
            repoName: group.name,
            targetBranch,
            total,
            afterMerge: repoMergePrefs.afterMerge,
          });
          actions.sendGoal(goal, {
            source: 'ui',
            label,
            lang: typeof navigator !== 'undefined' ? (navigator.language || '') : '',
          });
        }
        showTermToast(
          `Asked Sysop to merge ${total} worktree${total === 1 ? '' : 's'} into ${targetBranch}`,
          'ok',
          3200,
        );
      });
      batchBox.appendChild(sysopMergeBtn);
    }

    updateBatchBtn();
    frag.appendChild(batchBox);
  }

  if (total > 0) {
    const list = document.createElement('div');
    list.className = 'spop-rec-list';

    for (const { t, st } of statuses) {
      const row = document.createElement('div');
      row.className = 'spop-rec-row';
      const info = document.createElement('div');
      info.className = 'spop-rec-info';

      const rawBr = (st && st.branch) || (t.labels && t.labels['swarmbox.branch']) || 'worktree';
      const base = (st && st.base) || (t.labels && t.labels['swarmbox.base']) || 'main';
      const shortBr = rawBr.replace(/^sb\//, '');
      const behindTxt = (st && st.behind > 0) ? ` · ${st.behind} behind` : '';

      const brBtn = document.createElement('button');
      brBtn.type = 'button';
      brBtn.className = 'spop-rec-branch';
      brBtn.textContent = `${shortBr} → ${base}`;
      brBtn.title = `Focus ${tabDisplayName(t)} (${rawBr})`;
      brBtn.addEventListener('click', () => {
        closePopover();
        if (state.activeId !== t.address) {
          if (typeof actions.connectPty === 'function') actions.connectPty(t.address);
        } else if (typeof actions.focusTerminalIfDesktop === 'function') {
          actions.focusTerminalIfDesktop();
        }
      });

      const meta = document.createElement('div');
      meta.className = 'spop-rec-meta';
      const rowActs = document.createElement('div');
      rowActs.className = 'spop-rec-acts';
      const actBtn = document.createElement('button');
      actBtn.type = 'button';
      actBtn.className = 'spop-rec-act';
      let needsInspectBtn = true;

      if (!st) {
        meta.textContent = 'status unavailable';
        actBtn.textContent = 'Inspect';
        needsInspectBtn = false;
        actBtn.addEventListener('click', () => {
          closePopover();
          openWorktreePopover(t.address);
        });
      } else if (st.dirty) {
        const n = st.uncommitted_count || 0;
        meta.textContent = `${st.ahead > 0 ? `${st.ahead} ahead · ` : ''}${n ? `${n} dirty` : 'dirty'}${behindTxt}`;
        meta.classList.add('is-warn');
        actBtn.textContent = 'Ask to commit';
        actBtn.addEventListener('click', async () => {
          closePopover();
          await fetch('/api/worktrees/commit', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ terminal: t.address }),
          });
          showTermToast(`Asked agent on ${shortBr} to commit`);
        });
      } else if (st.ahead > 0 && !st.can_merge) {
        meta.textContent = `${st.ahead} ahead${behindTxt} · conflict`;
        meta.classList.add('is-warn');
        actBtn.classList.add('amber');
        actBtn.textContent = 'Resolve';
        actBtn.addEventListener('click', async () => {
          closePopover();
          await fetch('/api/worktrees/resolve-conflict', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ terminal: t.address, base }),
          });
          showTermToast(`Asked agent on ${shortBr} to resolve conflict`);
        });
      } else if (st.ahead > 0 && st.can_merge && !st.main_dirty) {
        meta.textContent = `${st.ahead} ahead${behindTxt} · clean`;
        meta.classList.add('is-ok');
        actBtn.classList.add('green');
        actBtn.textContent = repoMergePrefs.afterMerge === 'verify'
          ? 'Merge & verify'
          : repoMergePrefs.afterMerge === 'verify_push'
            ? 'Merge & push'
            : 'Merge';
        rowMergeBtns.push(actBtn);
        actBtn.title = `Merge ${shortBr} into ${base} using your selected After merge mode`;
        actBtn.addEventListener('click', async () => {
          const doVerify = repoMergePrefs.afterMerge === 'verify' || repoMergePrefs.afterMerge === 'verify_push';
          const doPush = repoMergePrefs.afterMerge === 'verify_push';
          closePopover();
          const r = await fetch('/api/worktrees/merge', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ terminal: t.address, path: st.path, clean: true, verify: doVerify, push: doPush }),
          });
          const d = await r.json().catch(() => ({}));
          if (!r.ok) {
            showTermToast(d.message || d.error || 'Merge failed', 'error');
            return;
          }
          showTermToast(formatHandoffToast(d, `Merged ${shortBr} into ${base} & closed tab`), 'ok', 3600);
        });
      } else if (st.ahead > 0 && st.main_dirty) {
        meta.textContent = `${st.ahead} ahead${behindTxt} · ${base} dirty`;
        meta.classList.add('is-warn');
        actBtn.textContent = 'Inspect';
        needsInspectBtn = false;
        actBtn.addEventListener('click', () => {
          closePopover();
          openWorktreePopover(t.address);
        });
      } else {
        meta.textContent = `0 ahead${behindTxt} · empty`;
        actBtn.textContent = 'Close & clean';
        actBtn.title = `Close agent tab and remove empty worktree ${shortBr}`;
        actBtn.addEventListener('click', async () => {
          closePopover();
          const r = await fetch('/api/worktrees/remove', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ path: st.path, terminal: t.address }),
          });
          const d = await r.json().catch(() => ({}));
          showTermToast(r.ok ? `Closed tab & removed empty worktree ${shortBr}` : (d.message || 'Remove failed'));
        });
      }

      if (needsInspectBtn) {
        const inspBtn = document.createElement('button');
        inspBtn.type = 'button';
        inspBtn.className = 'spop-rec-insp';
        inspBtn.textContent = 'Inspect';
        inspBtn.title = `Inspect commits & diff for ${shortBr}`;
        inspBtn.addEventListener('click', () => {
          closePopover();
          openWorktreePopover(t.address);
        });
        rowActs.appendChild(inspBtn);
      }
      rowActs.appendChild(actBtn);
      info.append(brBtn, meta);
      row.append(info, rowActs);
      list.appendChild(row);
    }

    for (const w of pendingWts) {
      const row = document.createElement('div');
      row.className = 'spop-rec-row';
      const info = document.createElement('div');
      info.className = 'spop-rec-info';
      const shortBr = String(w.branch || 'worktree').replace(/^sb\//, '');
      const brEl = document.createElement('div');
      brEl.className = 'spop-rec-branch';
      brEl.style.cursor = 'default';
      brEl.textContent = `${shortBr} · parked`;
      const meta = document.createElement('div');
      meta.className = `spop-rec-meta${w.dirty || !w.can_merge ? ' is-warn' : ' is-ok'}`;
      meta.textContent = w.dirty ? `${w.uncommitted_count || 1} dirty` : `${w.ahead || 0} ahead`;
      const reopenBtn = document.createElement('button');
      reopenBtn.type = 'button';
      reopenBtn.className = 'spop-rec-act';
      reopenBtn.textContent = 'Reopen';
      reopenBtn.addEventListener('click', async () => {
        closePopover();
        const r = await fetch('/api/worktrees/open', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ path: w.path }),
        });
        const d = await r.json().catch(() => ({}));
        const addr = (d && d.terminal && d.terminal.address) || (d && d.address);
        if (addr) setTimeout(() => { if (typeof actions.connectPty === 'function') actions.connectPty(addr); }, 100);
      });
      info.append(brEl, meta);
      row.append(info, reopenBtn);
      list.appendChild(row);
    }

    frag.appendChild(list);
  }

  const foot = document.createElement('div');
  foot.className = 'spop-links spop-links-end';
  const doneBtn = document.createElement('button');
  doneBtn.type = 'button';
  doneBtn.className = 'spop-ghost-btn';
  doneBtn.textContent = 'Close';
  doneBtn.addEventListener('click', closePopover);
  foot.appendChild(doneBtn);
  frag.appendChild(foot);
  openPopover(frag);
  state.gitPopRefresh = { sig, run: (r) => openRepoWorktreesPopover(group, { refresh: r }) };
}

export async function wakePin(pinId, worktreeChoice = '') {
  const body = worktreeChoice ? { worktree_choice: worktreeChoice } : {};
  const r = await fetch(`/api/pins/${encodeURIComponent(pinId)}/wake`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  const data = await r.json().catch(() => ({}));
  if (r.status === 409 && data.error === 'worktree_collision') {
    openCollisionPopover({ kind: 'pin', pinId, collision: data.collision });
    return;
  }
  if (!r.ok) {
    showTermToast(data.message || 'Could not wake pinned session');
    return;
  }
  const addr = (data && data.terminal && data.terminal.address) || (data && data.address);
  if (addr) setTimeout(() => { if (typeof actions.connectPty === 'function') actions.connectPty(addr); }, 100);
  if (data.worktree) {
    showTermToast(`Opened in worktree ${data.worktree.branch}`);
  }
}

export function terminalRepoGroupInfo(t) {
  if (t && t.repo && t.repo.root) {
    return {
      key: `repo:${t.repo.root}`,
      isGit: true,
      root: t.repo.root,
      name: t.repo.name || t.repo.root.split('/').pop() || 'repo',
      cwd: t.repo.root,
    };
  }
  const lblRepo = t && t.labels && t.labels['swarmbox.repo'];
  if (lblRepo) {
    return {
      key: `repo:${lblRepo}`,
      isGit: true,
      root: lblRepo,
      name: String(lblRepo).replace(/\/+$/, '').split('/').pop() || 'repo',
      cwd: lblRepo,
    };
  }
  const rawCwd = String((t && t.foreground && t.foreground.cwd) || (t && t.cwd) || '').replace(/\/+$/, '');
  if (rawCwd && rawCwd !== '/home/agent' && rawCwd !== '/') {
    const base = rawCwd.slice(rawCwd.lastIndexOf('/') + 1) || rawCwd;
    return { key: `dir:${rawCwd}`, isGit: false, root: '', name: base, cwd: rawCwd };
  }
  return { key: 'dir:~', isGit: false, root: '', name: '~', cwd: rawCwd || '/home/agent' };
}
