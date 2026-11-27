// Shared UI chrome: terminal toasts, open-url toast, popovers, inline/popover rename, and card context menu.

import { state, dom, actions } from './state.js';
import { ICO_BRANCH_SVG, ICO_PENCIL_SVG, tabDisplayName, shortDisplayPath } from './icons.js';

let termToastTimer = null;
export function showTermToast(msg, tone = '', ms = 2600) {
  if (!dom.termToastEl) return;
  clearTimeout(termToastTimer);
  dom.termToastEl.classList.remove('interactive');
  if (!msg) {
    dom.termToastEl.classList.remove('visible');
    return;
  }
  dom.termToastEl.textContent = msg;
  dom.termToastEl.dataset.tone = tone;
  dom.termToastEl.classList.add('visible');
  if (ms > 0) {
    termToastTimer = setTimeout(() => dom.termToastEl.classList.remove('visible'), ms);
  }
}

let lastOpenUrl = '';
let lastOpenUrlMs = 0;
export function showOpenUrlToast(url) {
  if (!dom.termToastEl) return;
  clearTimeout(termToastTimer);
  let label = url;
  try {
    const u = new URL(url);
    label = u.host + (u.pathname && u.pathname !== '/' ? u.pathname : '');
  } catch (_) {}
  if (label.length > 52) label = label.slice(0, 51) + '…';

  dom.termToastEl.textContent = '';
  dom.termToastEl.dataset.tone = '';
  dom.termToastEl.classList.add('interactive', 'visible');

  const text = document.createElement('span');
  text.className = 'term-toast-label';
  text.textContent = label;
  text.title = url;

  const openLink = document.createElement('a');
  openLink.className = 'term-toast-btn term-toast-btn-primary';
  openLink.href = url;
  openLink.target = '_blank';
  openLink.rel = 'noopener noreferrer';
  openLink.textContent = 'Open';
  openLink.addEventListener('click', () => {
    dom.termToastEl.classList.remove('visible', 'interactive');
  });

  const copyBtn = document.createElement('button');
  copyBtn.type = 'button';
  copyBtn.className = 'term-toast-btn';
  copyBtn.textContent = 'Copy';
  copyBtn.addEventListener('click', () => {
    navigator.clipboard?.writeText(url).then(() => showTermToast('Link copied', 'ok', 1800)).catch(() => {});
  });

  const closeBtn = document.createElement('button');
  closeBtn.type = 'button';
  closeBtn.className = 'term-toast-close';
  closeBtn.setAttribute('aria-label', 'Dismiss');
  closeBtn.textContent = '×';
  closeBtn.addEventListener('click', () => {
    clearTimeout(termToastTimer);
    dom.termToastEl.classList.remove('visible', 'interactive');
  });

  dom.termToastEl.append(text, openLink, copyBtn, closeBtn);
  termToastTimer = setTimeout(() => {
    dom.termToastEl.classList.remove('visible', 'interactive');
  }, 15000);
}

export function onOpenUrlEvent(url) {
  if (typeof url !== 'string' || !/^https?:\/\//i.test(url)) return;
  const now = Date.now();
  if (url === lastOpenUrl && now - lastOpenUrlMs < 400) return;
  lastOpenUrl = url;
  lastOpenUrlMs = now;
  if (document.visibilityState === 'hidden') return;
  let opened = null;
  try {
    opened = window.open(url, '_blank', 'noopener,noreferrer');
  } catch (_) {}
  if (opened) {
    let host = url;
    try { host = new URL(url).host; } catch (_) {}
    showTermToast(`Opened ${host}`, 'ok', 2200);
  } else {
    showOpenUrlToast(url);
  }
}

export function openRenamePopover(address) {
  const term = state.terminals.find((t) => t.address === address);
  if (!term) return;
  const current = tabDisplayName(term);
  const wrap = document.createElement('div');
  wrap.style.display = 'flex';
  wrap.style.flexDirection = 'column';
  wrap.style.gap = '10px';

  const head = document.createElement('div');
  head.className = 'spop-head';
  head.innerHTML = `<span style="display:inline-flex;align-items:center;gap:6px">${ICO_PENCIL_SVG}<span>Rename session</span></span>`;

  const inp = document.createElement('input');
  inp.type = 'text';
  inp.className = 'spop-rename-input';
  inp.value = current;
  inp.maxLength = 60;
  inp.placeholder = 'Session title…';

  const rowActions = document.createElement('div');
  rowActions.className = 'spop-rename-actions';
  const cancelBtn = document.createElement('button');
  cancelBtn.type = 'button';
  cancelBtn.className = 'spop-btn secondary';
  cancelBtn.textContent = 'Cancel';
  const saveBtn = document.createElement('button');
  saveBtn.type = 'button';
  saveBtn.className = 'spop-btn primary';
  saveBtn.textContent = 'Save';

  const submit = () => {
    const val = inp.value.trim();
    closePopover();
    if (val && val !== current) commitInlineRename(address, val);
  };
  cancelBtn.addEventListener('click', closePopover);
  saveBtn.addEventListener('click', submit);
  inp.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') { e.preventDefault(); submit(); }
    else if (e.key === 'Escape') { e.preventDefault(); closePopover(); }
  });

  rowActions.append(cancelBtn, saveBtn);
  wrap.append(head, inp, rowActions);
  openPopover(wrap);
  requestAnimationFrame(() => {
    inp.focus();
    inp.select();
  });
}

export function startInlineRename(address) {
  if (!address || !state.terminals.some((t) => t.address === address)) return;
  if (window.innerWidth <= 860) {
    openRenamePopover(address);
    return;
  }
  if (dom.appEl && dom.appEl.dataset.sidebarOpen !== '1') {
    if (typeof actions.setDesktopSidebar === 'function') actions.setDesktopSidebar(true);
  }
  state.editingTabId = address;
  if (typeof actions.renderTabs === 'function') actions.renderTabs();
  requestAnimationFrame(() => {
    const inp = document.querySelector(`.inline-rename-input[data-tab="${CSS.escape(address)}"]`);
    if (inp) {
      inp.focus();
      inp.select();
    }
  });
}

export async function commitInlineRename(address, nextTitle) {
  const clean = String(nextTitle || '').trim();
  state.editingTabId = null;
  if (typeof actions.renderTabs === 'function') actions.renderTabs();
  if (!clean) {
    if (typeof actions.focusTerminalIfDesktop === 'function') actions.focusTerminalIfDesktop();
    return;
  }
  await fetch(`/api/tabs/${encodeURIComponent(address)}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ title: clean, title_source: 'user' }),
  }).catch(() => {});
  if (typeof actions.focusTerminalIfDesktop === 'function') actions.focusTerminalIfDesktop();
}

export async function unpinById(pinId) {
  await fetch(`/api/pins/${encodeURIComponent(pinId)}`, { method: 'DELETE' }).catch(() => {});
  showTermToast('Removed pin');
}

let openCardMenuEl = null;
let openCardMenuCard = null;
let cardMenuListenersBound = false;

export function closeCardMenu() {
  if (openCardMenuEl) {
    openCardMenuEl.remove();
    openCardMenuEl = null;
  }
  if (openCardMenuCard) {
    delete openCardMenuCard.dataset.menuOpen;
    openCardMenuCard = null;
  }
}

export function initUiChrome() {
  if (cardMenuListenersBound || typeof document === 'undefined') return;
  cardMenuListenersBound = true;
  document.addEventListener('pointerdown', (e) => {
    if (openCardMenuEl && !openCardMenuEl.contains(e.target)) closeCardMenu();
  }, true);
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && openCardMenuEl) {
      e.stopPropagation();
      closeCardMenu();
    }
  }, true);
  window.addEventListener('resize', closeCardMenu);
  if (dom.sidebarAgentsEl && dom.sidebarAgentsEl.parentElement && dom.sidebarAgentsEl.parentElement.parentElement) {
    dom.sidebarAgentsEl.parentElement.parentElement.addEventListener('scroll', closeCardMenu, { passive: true });
  }
}

export function openCardMenu(term, anchor, cardEl = null) {
  closeCardMenu();
  if (!term || !term.address) return;
  const wtBranch = term.labels && term.labels['swarmbox.worktree'] ? (term.labels['swarmbox.branch'] || 'worktree') : '';
  const wtBase = (term.labels && term.labels['swarmbox.base']) || 'main';
  const menu = document.createElement('div');
  menu.className = 'card-ctx-menu';
  menu.setAttribute('role', 'menu');

  if (wtBranch) {
    const head = document.createElement('div');
    head.className = 'card-ctx-head';
    head.innerHTML = '<span>Worktree</span><span class="card-ctx-branch"></span>';
    head.querySelector('.card-ctx-branch').textContent = `${wtBranch} → ${wtBase}`;
    menu.appendChild(head);

    const mItem = document.createElement('button');
    mItem.type = 'button';
    mItem.className = 'card-ctx-item is-wt';
    mItem.setAttribute('role', 'menuitem');
    mItem.innerHTML = `<span class="card-ctx-item-l">${ICO_BRANCH_SVG}<span>Merge &amp; status…</span></span><span class="card-ctx-kbd">↵</span>`;
    mItem.addEventListener('click', (e) => {
      e.stopPropagation();
      closeCardMenu();
      if (typeof actions.openWorktreePopover === 'function') actions.openWorktreePopover(term.address);
    });
    menu.appendChild(mItem);
  }

  const rItem = document.createElement('button');
  rItem.type = 'button';
  rItem.className = 'card-ctx-item';
  rItem.setAttribute('role', 'menuitem');
  rItem.innerHTML = `<span class="card-ctx-item-l">${ICO_PENCIL_SVG}<span>Rename</span></span><span class="card-ctx-kbd">Alt+R</span>`;
  rItem.addEventListener('click', (e) => {
    e.stopPropagation();
    closeCardMenu();
    startInlineRename(term.address);
  });
  menu.appendChild(rItem);

  if (term.cwd) {
    const pItem = document.createElement('button');
    pItem.type = 'button';
    pItem.className = 'card-ctx-item';
    pItem.setAttribute('role', 'menuitem');
    pItem.innerHTML = '<span class="card-ctx-item-l"><svg viewBox="0 0 16 16" width="11" height="11" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="5" y="5" width="8.5" height="8.5" rx="1.6"/><path d="M11 5V3.6A1.6 1.6 0 0 0 9.4 2H3.6A1.6 1.6 0 0 0 2 3.6v5.8A1.6 1.6 0 0 0 3.6 11H5"/></svg><span>Copy path</span></span>';
    pItem.addEventListener('click', async (e) => {
      e.stopPropagation();
      closeCardMenu();
      try { await navigator.clipboard.writeText(term.cwd); } catch (_) {}
      showTermToast(`Copied ${shortDisplayPath(term.cwd)}`);
    });
    menu.appendChild(pItem);
  }

  const sep = document.createElement('div');
  sep.className = 'card-ctx-sep';
  menu.appendChild(sep);

  const cItem = document.createElement('button');
  cItem.type = 'button';
  cItem.className = 'card-ctx-item is-danger';
  cItem.setAttribute('role', 'menuitem');
  cItem.innerHTML = '<span class="card-ctx-item-l"><span class="card-ctx-x">✕</span><span>Close tab</span></span>';
  cItem.addEventListener('click', async (e) => {
    e.stopPropagation();
    closeCardMenu();
    await fetch(`/api/tabs/${encodeURIComponent(term.address)}`, { method: 'DELETE' });
  });
  menu.appendChild(cItem);

  document.body.appendChild(menu);
  openCardMenuEl = menu;
  openCardMenuCard = cardEl;
  if (cardEl) cardEl.dataset.menuOpen = '1';

  const mw = menu.offsetWidth || 214;
  const mh = menu.offsetHeight || 140;
  let x = 12;
  let y = 12;
  if (cardEl && window.innerWidth > 860 && anchor && typeof anchor.getBoundingClientRect === 'function') {
    const sbEl = document.getElementById('sidebar');
    const cardRect = cardEl.getBoundingClientRect();
    const sbRect = sbEl ? sbEl.getBoundingClientRect() : cardRect;
    x = sbRect.right + 6;
    y = cardRect.top;
  } else if (anchor && typeof anchor.getBoundingClientRect === 'function') {
    const rect = anchor.getBoundingClientRect();
    x = rect.right - mw + 6;
    y = rect.bottom + 6;
    if (x < 10) x = rect.left;
  } else if (anchor && typeof anchor.x === 'number') {
    x = anchor.x;
    y = anchor.y;
  }
  x = Math.max(8, Math.min(x, window.innerWidth - mw - 8));
  y = Math.max(8, Math.min(y, window.innerHeight - mh - 8));
  menu.style.left = `${Math.round(x)}px`;
  menu.style.top = `${Math.round(y)}px`;
}

export function closePopover() {
  if (!dom.popoverBackdropEl) return;
  state.popoverOpen = false;
  state.popoverKeyHandler = null;
  dom.popoverBackdropEl.classList.add('hidden');
  dom.popoverBackdropEl.setAttribute('aria-hidden', 'true');
  if (dom.popoverEl) dom.popoverEl.innerHTML = '';
  if (typeof actions.focusTerminalIfDesktop === 'function') actions.focusTerminalIfDesktop();
}

// Every popover closes from one control at the right of its head: the Esc capsule is a button (Esc × on desktop, × on mobile)
export function makeEscClose(onClick) {
  const btn = document.createElement('button');
  btn.type = 'button';
  btn.className = 'esc-close';
  btn.title = 'Close (Esc)';
  btn.setAttribute('aria-label', 'Close');
  btn.innerHTML = '<span class="esc-close-key">Esc</span><span class="esc-close-x" aria-hidden="true">×</span>';
  btn.addEventListener('click', (e) => { e.stopPropagation(); onClick(); });
  return btn;
}

export function addPopoverEscBadge() {
  const head = dom.popoverEl && dom.popoverEl.querySelector('.spop-head');
  if (!head || head.querySelector('.esc-close')) return;
  const btn = makeEscClose(closePopover);
  const hint = Array.from(head.querySelectorAll('.wt-kbd')).find((k) => k.textContent.trim() === 'Esc');
  if (hint) { hint.replaceWith(btn); return; }
  let right = head.querySelector(':scope > .spop-head-right');
  if (!right) {
    right = document.createElement('span');
    right.className = 'spop-head-right';
    while (head.children.length > 1) right.appendChild(head.children[1]);
    head.appendChild(right);
  }
  right.appendChild(btn);
}

// What a git popover shows, for its live refresh to tell a change: a commit's "12 seconds ago" moves on every fetch and is no change
export function gitPopSig(value) {
  return JSON.stringify(value, (k, v) => (k === 'rel_time' ? undefined : v));
}

export function refreshGitPopover() {
  const r = state.gitPopRefresh;
  if (!r || !state.popoverOpen || r.busy || document.visibilityState !== 'visible') return;
  const ae = document.activeElement;
  if (ae && dom.popoverEl && dom.popoverEl.contains(ae) && ae.matches('input, textarea, select')) return;
  r.busy = true;
  Promise.resolve().then(() => r.run(r)).catch(() => {}).finally(() => { r.busy = false; });
}

export function openPopover(node, onKeyDown = null) {
  if (!dom.popoverBackdropEl || !dom.popoverEl) return;
  dom.popoverEl.innerHTML = '';
  const handle = document.createElement('div');
  handle.className = 'sheet-handle mobile-only spop-handle';
  handle.setAttribute('aria-hidden', 'true');
  handle.innerHTML = '<span></span>';
  dom.popoverEl.appendChild(handle);
  dom.popoverEl.appendChild(node);
  addPopoverEscBadge();
  state.gitPopRefresh = null;
  state.popoverOpen = true;
  state.popoverKeyHandler = typeof onKeyDown === 'function' ? onKeyDown : null;
  dom.popoverBackdropEl.classList.remove('hidden');
  dom.popoverBackdropEl.setAttribute('aria-hidden', 'false');
  requestAnimationFrame(() => {
    const primary = dom.popoverEl.querySelector('.agent-pick-btn.is-default, .spop-btn.primary, .spop-btn.green, .spop-btn.amber, .agent-pick-btn');
    if (primary) primary.focus();
  });
}
