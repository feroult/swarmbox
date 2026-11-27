/* Shared Viewer Controller (drawer in index.html & standalone /view?path=... page). */

import { escHtml, fmtBytes } from './utils.js';
import {
  buildShellHtml,
  renderBinaryCard,
  renderCodeBlock,
  renderCrumbs,
  renderDirView,
  renderHtmlView,
  renderImageView,
  renderInlineView,
  renderMarkdownView,
  setSubbar,
} from './renderers.js';

export function createViewer(opts) {
  const container = opts.container;
  const mode = opts.mode || 'drawer'; // 'drawer' | 'standalone'
  const onClose = opts.onClose || null;
  const onToast = opts.onToast || (() => {});

  const state = {
    path: '',
    displayPath: '',
    info: null,
    inline: null, // { title, subtitle, content, kind }
    siblingImages: [],
    siblingIdx: -1,
    zoom: 'fit', // 'fit' | number
    mdRaw: false,
    htmlSource: false,
    jsonPretty: true,
    codeWrap: false,
    expanded: false,
  };

  container.innerHTML = buildShellHtml(mode);

  const badgeEl = container.querySelector('[data-role="badge"]');
  const crumbsEl = container.querySelector('[data-role="crumbs"]');
  const metaEl = container.querySelector('[data-role="meta"]');
  const subbarEl = container.querySelector('[data-role="subbar"]');
  const bodyEl = container.querySelector('[data-role="body"]');
  const refreshBtn = container.querySelector('[data-act="refresh"]');
  const dlLink = container.querySelector('[data-act="download"]');
  const newTabLink = container.querySelector('[data-act="new-tab"]');

  const dom = { badgeEl, crumbsEl, metaEl, subbarEl, bodyEl, refreshBtn, dlLink, newTabLink };

  function viewUrlFor(p, line) {
    const qs = new URLSearchParams();
    qs.set('path', p);
    if (line) qs.set('line', String(line));
    return '/view?' + qs.toString();
  }

  async function loadSiblingImages(info) {
    state.siblingImages = [];
    state.siblingIdx = -1;
    try {
      const res = await fetch('/api/files/list?path=' + encodeURIComponent(info.dir));
      if (!res.ok) return;
      const data = await res.json();
      const imgs = (data.items || []).filter((it) => it.category === 'image');
      state.siblingImages = imgs;
      state.siblingIdx = imgs.findIndex((it) => it.path === info.path);
    } catch (_) {}
  }

  // setInlineBusy(on): the refresh button of an inline view spins (and does not take a second click) while its work runs
  function setInlineBusy(on) {
    if (!refreshBtn) return;
    refreshBtn.classList.toggle('is-spinning', Boolean(on));
    refreshBtn.disabled = Boolean(on);
  }

  const ctx = { state, dom, open, onToast };

  function openInline(inlineOpts = {}) {
    const title = String(inlineOpts.title || '');
    const subtitle = String(inlineOpts.subtitle || '');
    const content = String(inlineOpts.content == null ? '' : inlineOpts.content);
    const kind = inlineOpts.kind === 'diff' ? 'diff' : inlineOpts.kind === 'md' ? 'md' : 'log';

    state.path = '';
    state.displayPath = title;
    state.info = null;
    state.mdRaw = false;
    state.inline = {
      title, subtitle, content, kind,
      actions: Array.isArray(inlineOpts.actions) ? inlineOpts.actions : [],
      note: String(inlineOpts.note || ''),
      noteTone: String(inlineOpts.noteTone || ''),
      tag: String(inlineOpts.tag || ''),
      refresh: inlineOpts.refresh && typeof inlineOpts.refresh.onClick === 'function' ? inlineOpts.refresh : null,
    };

    badgeEl.textContent = inlineOpts.badge ? String(inlineOpts.badge) : kind === 'diff' ? 'DIFF' : kind === 'md' ? 'MD' : 'LOG';
    crumbsEl.innerHTML = '';
    const sp = document.createElement('span');
    sp.className = 'sbv-crumb-cur';
    sp.textContent = title || (kind === 'diff' ? 'Diff' : 'Output');
    if (subtitle) sp.title = subtitle;
    crumbsEl.appendChild(sp);
    metaEl.textContent = subtitle;

    dlLink.classList.add('hidden');
    if (newTabLink) newTabLink.classList.add('hidden');
    if (refreshBtn) {
      // An inline view with `refresh` ({ title, onClick, busy }) shows the header's refresh button for it (spinning while busy)
      const r = state.inline.refresh;
      refreshBtn.classList.toggle('hidden', !r);
      refreshBtn.title = r ? String(r.title || 'Refresh') : 'Refresh (R)';
      refreshBtn.setAttribute('aria-label', refreshBtn.title);
      setInlineBusy(Boolean(r && r.busy));
    }

    renderInlineView(ctx);
    return true;
  }

  async function open(targetPath, openOpts = {}) {
    const qs = new URLSearchParams();
    qs.set('path', targetPath);
    if (openOpts.cwd) qs.set('cwd', openOpts.cwd);
    if (openOpts.fallbackDir) qs.set('fallbackDir', openOpts.fallbackDir);

    state.inline = null;
    if (newTabLink) newTabLink.classList.remove('hidden');
    if (refreshBtn) {
      refreshBtn.classList.remove('hidden');
      refreshBtn.title = 'Refresh (R)';
      refreshBtn.setAttribute('aria-label', 'Refresh');
      setInlineBusy(false);
    }
    state.zoom = 'fit';
    state.mdRaw = false;
    state.htmlSource = false;
    bodyEl.innerHTML = '<div class="sbv-loading">Loading preview…</div>';
    setSubbar(subbarEl, []);

    let stat;
    try {
      const res = await fetch('/api/files/stat?' + qs.toString());
      stat = await res.json();
      if (!res.ok || !stat.ok) {
        badgeEl.textContent = 'ERROR';
        crumbsEl.textContent = targetPath;
        metaEl.textContent = '';
        dlLink.classList.add('hidden');
        bodyEl.innerHTML = '<div class="sbv-error">' + escHtml(stat.message || 'Unable to open path') + '</div>';
        return false;
      }
    } catch (err) {
      bodyEl.innerHTML = '<div class="sbv-error">Failed to reach SwarmBox file server.</div>';
      return false;
    }

    if (openOpts.line && !stat.line) stat.line = Number(openOpts.line) || null;
    state.path = stat.path;
    state.displayPath = stat.displayPath;
    state.info = stat;

    badgeEl.textContent = stat.category.toUpperCase();
    renderCrumbs(crumbsEl, stat.path, stat.displayPath, open);
    metaEl.textContent = stat.kind === 'dir' ? 'Directory' : fmtBytes(stat.size);

    if (stat.kind === 'file' && stat.rawUrl) {
      dlLink.href = stat.rawUrl + '?download=1';
      dlLink.setAttribute('download', stat.name);
      dlLink.classList.remove('hidden');
    } else {
      dlLink.classList.add('hidden');
    }
    if (newTabLink) {
      newTabLink.href = viewUrlFor(stat.path, stat.line);
    }
    if (mode === 'standalone') {
      document.title = stat.name + ' — SwarmBox Viewer';
      const nextUrl = viewUrlFor(stat.path, stat.line);
      if (window.location.pathname + window.location.search !== nextUrl) {
        window.history.replaceState(null, '', nextUrl);
      }
    }

    if (stat.kind === 'dir') {
      const res = await fetch('/api/files/list?path=' + encodeURIComponent(stat.path));
      const data = await res.json();
      renderDirView(ctx, data);
      return true;
    }

    if (stat.category === 'image') {
      await loadSiblingImages(stat);
      renderImageView(ctx, stat);
      return true;
    }

    if (stat.category === 'html') {
      await renderHtmlView(ctx, stat);
      return true;
    }

    if (stat.category === 'pdf') {
      bodyEl.innerHTML = '';
      const frame = document.createElement('iframe');
      frame.className = 'sbv-iframe';
      frame.src = stat.rawUrl;
      bodyEl.appendChild(frame);
      return true;
    }

    if (stat.category === 'video') {
      bodyEl.innerHTML = '<div class="sbv-media-stage"><video controls src="' + escHtml(stat.rawUrl) + '"></video></div>';
      return true;
    }

    if (stat.category === 'audio') {
      bodyEl.innerHTML = '<div class="sbv-media-stage"><audio controls src="' + escHtml(stat.rawUrl) + '"></audio></div>';
      return true;
    }

    if (stat.category === 'markdown' || stat.category === 'json' || stat.category === 'code') {
      const res = await fetch('/api/files/read?path=' + encodeURIComponent(stat.path));
      const data = await res.json();
      data.line = stat.line;
      data.endLine = stat.endLine;
      if (stat.category === 'markdown') {
        renderMarkdownView(ctx, data);
        return true;
      }
      const isJson = stat.category === 'json';
      const renderText = () => {
        const btns = [];
        if (isJson) {
          btns.push({ label: 'Formatted', active: state.jsonPretty, onClick: () => { state.jsonPretty = true; renderText(); } });
          btns.push({ label: 'Raw', active: !state.jsonPretty, onClick: () => { state.jsonPretty = false; renderText(); } });
        }
        btns.push({ label: 'Wrap', active: state.codeWrap, onClick: () => { state.codeWrap = !state.codeWrap; renderText(); } });
        btns.push({ spacer: true });
        btns.push({
          label: 'Copy',
          onClick: () => {
            navigator.clipboard?.writeText(data.content || '').then(() => onToast('Copied to clipboard')).catch(() => {});
          },
        });
        setSubbar(subbarEl, btns);
        renderCodeBlock(ctx, data.content || '', data, isJson);
      };
      renderText();
      return true;
    }

    // Binary fallback
    renderBinaryCard(bodyEl, stat);
    return true;
  }

  // Header actions
  container.querySelector('[data-act="refresh"]')?.addEventListener('click', () => {
    if (state.inline) {
      if (state.inline.refresh) state.inline.refresh.onClick();
      return;
    }
    if (state.path) open(state.path, { line: state.info?.line });
  });
  container.querySelector('[data-act="copy-path"]')?.addEventListener('click', () => {
    if (state.inline) {
      navigator.clipboard?.writeText(state.inline.content || '').then(() => onToast('Copied to clipboard')).catch(() => {});
      return;
    }
    if (!state.displayPath) return;
    navigator.clipboard?.writeText(state.displayPath).then(() => onToast('Path copied')).catch(() => {});
  });
  container.querySelector('[data-act="expand"]')?.addEventListener('click', () => {
    state.expanded = !state.expanded;
    container.classList.toggle('expanded', state.expanded);
  });
  container.querySelector('[data-act="close"]')?.addEventListener('click', () => {
    if (onClose) onClose();
  });

  // Keyboard navigation when viewer is active
  function handleKey(ev) {
    if (ev.key === 'ArrowLeft' && state.info?.category === 'image' && state.siblingIdx > 0) {
      ev.preventDefault();
      open(state.siblingImages[state.siblingIdx - 1].path);
    } else if (ev.key === 'ArrowRight' && state.info?.category === 'image' && state.siblingIdx >= 0 && state.siblingIdx < state.siblingImages.length - 1) {
      ev.preventDefault();
      open(state.siblingImages[state.siblingIdx + 1].path);
    }
  }

  return {
    open,
    openInline,
    setInlineBusy,
    getInlineTag: () => (state.inline ? state.inline.tag : ''),
    handleKey,
    getPath: () => state.path,
    viewUrlFor,
  };
}
