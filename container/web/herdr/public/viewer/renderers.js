/* DOM view renderers for the SwarmBox File Viewer (shell, crumbs, subbar, code, image, dir, markdown, HTML, diff, log, inline, binary). */

import { escHtml, fmtBytes } from './utils.js';
import { highlightLines } from './highlight.js';
import { renderMarkdown } from './markdown.js';

export function buildShellHtml(mode) {
  return (
    '<div class="sbv-shell">' +
      '<header class="sbv-head">' +
        '<div class="sbv-head-left">' +
          '<span class="sbv-kind-badge" data-role="badge">FILE</span>' +
          '<nav class="sbv-crumbs" data-role="crumbs" aria-label="Path breadcrumb"></nav>' +
        '</div>' +
        '<div class="sbv-head-actions">' +
          '<span class="sbv-meta" data-role="meta"></span>' +
          '<button type="button" class="sbv-icon-btn" data-act="refresh" title="Refresh (R)" aria-label="Refresh">' +
            '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12a9 9 0 1 1-2.64-6.36L21 8"/><path d="M21 3v5h-5"/></svg>' +
          '</button>' +
          '<button type="button" class="sbv-icon-btn" data-act="copy-path" title="Copy path" aria-label="Copy path">' +
            '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>' +
          '</button>' +
          '<a class="sbv-icon-btn hidden" data-act="download" title="Download" aria-label="Download">' +
            '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>' +
          '</a>' +
          (mode === 'drawer'
            ? '<button type="button" class="sbv-icon-btn desktop-only" data-act="expand" title="Toggle wide view" aria-label="Toggle wide view">' +
                '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="15 3 21 3 21 9"/><polyline points="9 21 3 21 3 15"/><line x1="21" y1="3" x2="14" y2="10"/><line x1="3" y1="21" x2="10" y2="14"/></svg>' +
              '</button>' +
              '<a class="sbv-icon-btn" data-act="new-tab" target="_blank" rel="noopener noreferrer" title="Open fullscreen in new tab" aria-label="Open in new tab">' +
                '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>' +
              '</a>' +
              '<button type="button" class="esc-close" data-act="close" title="Close (Esc)" aria-label="Close"><span class="esc-close-key">Esc</span><span class="esc-close-x" aria-hidden="true">×</span></button>'
            : '') +
        '</div>' +
      '</header>' +
      '<div class="sbv-subbar hidden" data-role="subbar"></div>' +
      '<div class="sbv-body" data-role="body"></div>' +
    '</div>'
  );
}

export function renderCrumbs(crumbsEl, absPath, displayPath, onOpen) {
  crumbsEl.innerHTML = '';
  const disp = displayPath || absPath;
  const isHome = disp.startsWith('~/') || disp === '~';
  const rawSegs = disp.split('/').filter(Boolean);
  const absSegs = absPath.split('/').filter(Boolean);
  const homeDepth = isHome ? (absSegs.length - (rawSegs.length - 1)) : 0;

  rawSegs.forEach((seg, idx) => {
    if (idx > 0) {
      const sep = document.createElement('span');
      sep.className = 'sbv-crumb-sep';
      sep.textContent = '/';
      crumbsEl.appendChild(sep);
    }
    const targetAbs = isHome
      ? (idx === 0 ? '/' + absSegs.slice(0, homeDepth).join('/') : '/' + absSegs.slice(0, homeDepth + idx).join('/'))
      : '/' + absSegs.slice(0, idx + 1).join('/');
    const isLast = idx === rawSegs.length - 1;
    if (isLast) {
      const sp = document.createElement('span');
      sp.className = 'sbv-crumb-cur';
      sp.textContent = seg;
      sp.title = displayPath;
      crumbsEl.appendChild(sp);
    } else {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'sbv-crumb-btn';
      btn.textContent = seg;
      btn.title = targetAbs;
      btn.addEventListener('click', () => onOpen(targetAbs));
      crumbsEl.appendChild(btn);
    }
  });
  requestAnimationFrame(() => { crumbsEl.scrollLeft = crumbsEl.scrollWidth; });
}

export function setSubbar(subbarEl, buttons) {
  if (!buttons || !buttons.length) {
    subbarEl.classList.add('hidden');
    subbarEl.innerHTML = '';
    return;
  }
  subbarEl.classList.remove('hidden');
  subbarEl.innerHTML = '';
  for (const b of buttons) {
    if (b.spacer) {
      const sp = document.createElement('span');
      sp.className = 'sbv-subbar-spacer';
      subbarEl.appendChild(sp);
      continue;
    }
    if (b.labelOnly) {
      const sp = document.createElement('span');
      sp.className = 'sbv-subbar-label';
      sp.textContent = b.label;
      subbarEl.appendChild(sp);
      continue;
    }
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'sbv-pill-btn' + (b.active ? ' active' : '');
    btn.textContent = b.label;
    if (b.disabled) btn.disabled = true;
    btn.addEventListener('click', b.onClick);
    subbarEl.appendChild(btn);
  }
}

export function renderCodeBlock(ctx, content, info, isJson, langOverride) {
  const { state, dom } = ctx;
  let text = content;
  if (isJson && state.jsonPretty) {
    try {
      text = JSON.stringify(JSON.parse(content), null, 2);
    } catch (_) {}
  }
  const langHint = langOverride || (isJson ? 'json' : (info && (info.name || info.path)) || '');
  const highlightedLines = highlightLines(text, langHint);
  const targetStart = info.line ? Number(info.line) : null;
  const targetEnd = info.endLine ? Number(info.endLine) : targetStart;

  const wrap = document.createElement('div');
  wrap.className = 'sbv-code-view' + (state.codeWrap ? ' wrap' : '');
  const table = document.createElement('table');
  table.className = 'sbv-code-table';
  const tbody = document.createElement('tbody');
  let targetRow = null;

  highlightedLines.forEach((lnHtml, idx) => {
    const num = idx + 1;
    const tr = document.createElement('tr');
    if (targetStart && num >= targetStart && num <= (targetEnd || targetStart)) {
      tr.className = 'sbv-line-hit';
      if (!targetRow) targetRow = tr;
    }
    const tdNum = document.createElement('td');
    tdNum.className = 'sbv-ln';
    tdNum.textContent = String(num);
    const tdCode = document.createElement('td');
    tdCode.className = 'sbv-lc';
    tdCode.innerHTML = lnHtml || ' ';
    tr.appendChild(tdNum);
    tr.appendChild(tdCode);
    tbody.appendChild(tr);
  });
  table.appendChild(tbody);
  wrap.appendChild(table);
  dom.bodyEl.innerHTML = '';
  if (info.truncated) {
    const note = document.createElement('div');
    note.className = 'sbv-notice';
    note.textContent = 'Showing first 2 MB of ' + fmtBytes(info.size) + '. Use Download for the full file.';
    dom.bodyEl.appendChild(note);
  }
  dom.bodyEl.appendChild(wrap);
  if (targetRow) {
    requestAnimationFrame(() => targetRow.scrollIntoView({ block: 'center', behavior: 'instant' }));
  }
}

export function renderImageView(ctx, info) {
  const { state, dom, open } = ctx;
  const hasSibs = state.siblingImages.length > 1 && state.siblingIdx >= 0;
  const buttons = [
    { label: 'Fit', active: state.zoom === 'fit', onClick: () => { state.zoom = 'fit'; renderImageView(ctx, info); } },
    { label: '100%', active: state.zoom === 1, onClick: () => { state.zoom = 1; renderImageView(ctx, info); } },
    { label: '−', onClick: () => { state.zoom = Math.max(0.25, (typeof state.zoom === 'number' ? state.zoom : 1) - 0.25); renderImageView(ctx, info); } },
    { label: '+', onClick: () => { state.zoom = Math.min(4, (typeof state.zoom === 'number' ? state.zoom : 1) + 0.25); renderImageView(ctx, info); } },
  ];
  if (hasSibs) {
    buttons.push({ spacer: true });
    buttons.push({
      label: '← Prev',
      disabled: state.siblingIdx <= 0,
      onClick: () => open(state.siblingImages[state.siblingIdx - 1].path),
    });
    buttons.push({ labelOnly: true, label: (state.siblingIdx + 1) + ' / ' + state.siblingImages.length });
    buttons.push({
      label: 'Next →',
      disabled: state.siblingIdx >= state.siblingImages.length - 1,
      onClick: () => open(state.siblingImages[state.siblingIdx + 1].path),
    });
  }
  setSubbar(dom.subbarEl, buttons);

  dom.bodyEl.innerHTML = '';
  const stage = document.createElement('div');
  stage.className = 'sbv-img-stage' + (state.zoom === 'fit' ? ' fit' : ' zoomed');
  const img = document.createElement('img');
  img.src = info.rawUrl + '?t=' + Date.now();
  img.alt = info.name;
  if (typeof state.zoom === 'number') {
    img.style.transform = 'scale(' + state.zoom + ')';
    img.style.transformOrigin = 'top left';
  }
  img.addEventListener('load', () => {
    if (img.naturalWidth && img.naturalHeight) {
      dom.metaEl.textContent = img.naturalWidth + '×' + img.naturalHeight + ' · ' + fmtBytes(info.size);
    }
  });
  img.addEventListener('click', () => {
    state.zoom = state.zoom === 'fit' ? 1 : 'fit';
    renderImageView(ctx, info);
  });
  stage.appendChild(img);
  dom.bodyEl.appendChild(stage);
}

export function renderDirView(ctx, data) {
  const { dom, open } = ctx;
  setSubbar(dom.subbarEl, [
    { labelOnly: true, label: (data.items || []).length + ' items' + (data.truncated ? ' (first 500)' : '') },
  ]);
  dom.bodyEl.innerHTML = '';
  const wrap = document.createElement('div');
  wrap.className = 'sbv-dir-view';

  const items = data.items || [];
  const images = items.filter((it) => it.category === 'image');
  const others = items.filter((it) => it.category !== 'image');

  if (!items.length) {
    wrap.innerHTML = '<div class="sbv-empty">This directory is empty.</div>';
    dom.bodyEl.appendChild(wrap);
    return;
  }

  if (images.length) {
    const h = document.createElement('div');
    h.className = 'sbv-sec-title';
    h.textContent = 'Images (' + images.length + ')';
    wrap.appendChild(h);

    const grid = document.createElement('div');
    grid.className = 'sbv-img-grid';
    for (const it of images) {
      const card = document.createElement('button');
      card.type = 'button';
      card.className = 'sbv-thumb-card';
      card.innerHTML =
        '<div class="sbv-thumb-img"><img src="' + escHtml(it.rawUrl) + '" alt="' + escHtml(it.name) + '" loading="lazy"></div>' +
        '<div class="sbv-thumb-meta">' +
          '<span class="sbv-thumb-name" title="' + escHtml(it.name) + '">' + escHtml(it.name) + '</span>' +
          '<span class="sbv-thumb-size">' + escHtml(fmtBytes(it.size)) + '</span>' +
        '</div>';
      card.addEventListener('click', () => open(it.path));
      grid.appendChild(card);
    }
    wrap.appendChild(grid);
  }

  if (others.length) {
    if (images.length) {
      const h = document.createElement('div');
      h.className = 'sbv-sec-title';
      h.textContent = 'Files & Folders (' + others.length + ')';
      wrap.appendChild(h);
    }
    const list = document.createElement('div');
    list.className = 'sbv-file-list';
    for (const it of others) {
      const row = document.createElement('button');
      row.type = 'button';
      row.className = 'sbv-file-row';
      const icon = it.kind === 'dir' ? '📁' : (it.category === 'markdown' ? '📝' : it.category === 'html' ? '🌐' : it.category === 'pdf' ? '📄' : '⌘');
      row.innerHTML =
        '<span class="sbv-file-ico">' + icon + '</span>' +
        '<span class="sbv-file-name">' + escHtml(it.name) + (it.kind === 'dir' ? '/' : '') + '</span>' +
        '<span class="sbv-file-cat">' + escHtml(it.kind === 'dir' ? 'dir' : it.category) + '</span>' +
        '<span class="sbv-file-size">' + escHtml(it.kind === 'dir' ? '' : fmtBytes(it.size)) + '</span>';
      row.addEventListener('click', () => open(it.path));
      list.appendChild(row);
    }
    wrap.appendChild(list);
  }

  dom.bodyEl.appendChild(wrap);
}

export function renderMarkdownView(ctx, data) {
  const { state, dom, open, onToast } = ctx;
  setSubbar(dom.subbarEl, [
    { label: 'Rendered', active: !state.mdRaw, onClick: () => { state.mdRaw = false; renderMarkdownView(ctx, data); } },
    { label: 'Raw', active: state.mdRaw, onClick: () => { state.mdRaw = true; renderMarkdownView(ctx, data); } },
    { spacer: true },
    {
      label: 'Copy Markdown',
      onClick: () => {
        navigator.clipboard?.writeText(data.content || '').then(() => onToast('Markdown copied')).catch(() => {});
      },
    },
  ]);

  if (state.mdRaw) {
    renderCodeBlock(ctx, data.content || '', data, false, 'md');
    return;
  }
  dom.bodyEl.innerHTML = '';
  const article = document.createElement('article');
  article.className = 'sbv-md';
  article.innerHTML = renderMarkdown(data.content || '', data.dir);

  article.querySelectorAll('.sbv-md-local-link').forEach((a) => {
    a.addEventListener('click', (ev) => {
      ev.preventDefault();
      const p = a.getAttribute('data-local-path');
      if (p) open(p);
    });
  });
  article.querySelectorAll('.sbv-md-img[data-preview-path]').forEach((img) => {
    img.addEventListener('click', () => {
      const p = img.getAttribute('data-preview-path');
      if (p) open(p);
    });
  });
  article.querySelectorAll('.sbv-copy-code').forEach((btn) => {
    btn.addEventListener('click', () => {
      const pre = btn.closest('.sbv-md-codeblock')?.querySelector('pre');
      if (!pre) return;
      navigator.clipboard?.writeText(pre.textContent || '').then(() => {
        btn.textContent = 'Copied';
        setTimeout(() => { btn.textContent = 'Copy'; }, 1200);
      }).catch(() => {});
    });
  });
  dom.bodyEl.appendChild(article);
}

export async function renderHtmlView(ctx, info) {
  const { state, dom } = ctx;
  setSubbar(dom.subbarEl, [
    { label: 'Preview', active: !state.htmlSource, onClick: () => { state.htmlSource = false; renderHtmlView(ctx, info); } },
    { label: 'Source', active: state.htmlSource, onClick: () => { state.htmlSource = true; renderHtmlView(ctx, info); } },
    { spacer: true },
    { labelOnly: true, label: 'Sandboxed preview' },
  ]);

  if (state.htmlSource) {
    const res = await fetch('/api/files/read?path=' + encodeURIComponent(info.path));
    const data = await res.json();
    renderCodeBlock(ctx, data.content || '', data, false, 'html');
    return;
  }
  dom.bodyEl.innerHTML = '';
  const frame = document.createElement('iframe');
  frame.className = 'sbv-iframe';
  frame.setAttribute('sandbox', 'allow-scripts');
  frame.src = info.rawUrl + '?t=' + Date.now();
  dom.bodyEl.appendChild(frame);
}

export function renderDiffContent(ctx, text) {
  const { state, dom } = ctx;
  dom.bodyEl.innerHTML = '';
  if (!text || !text.trim()) {
    dom.bodyEl.innerHTML = '<div class="sbv-empty">No diff changes to display.</div>';
    return;
  }
  const lines = String(text).replace(/\r\n/g, '\n').split('\n');
  const wrap = document.createElement('div');
  wrap.className = 'sbv-diff-view' + (state.codeWrap ? ' wrap' : '');
  const parts = [];
  for (const ln of lines) {
    let cls = 'sbv-diff-line';
    if (ln.startsWith('diff --git ')) {
      cls += ' sbv-diff-file';
    } else if (ln.startsWith('@@')) {
      cls += ' sbv-diff-hunk';
    } else if (
      ln.startsWith('+++ ') ||
      ln.startsWith('--- ') ||
      ln.startsWith('index ') ||
      ln.startsWith('new file mode') ||
      ln.startsWith('deleted file mode') ||
      ln.startsWith('rename ')
    ) {
      cls += ' sbv-diff-meta';
    } else if (ln.startsWith('+')) {
      cls += ' sbv-diff-add';
    } else if (ln.startsWith('-')) {
      cls += ' sbv-diff-del';
    }
    parts.push('<div class="' + cls + '">' + escHtml(ln || ' ') + '</div>');
  }
  wrap.innerHTML = parts.join('');
  dom.bodyEl.appendChild(wrap);
}

export function renderLogContent(ctx, text) {
  const { state, dom } = ctx;
  dom.bodyEl.innerHTML = '';
  if (!text) {
    dom.bodyEl.innerHTML = '<div class="sbv-empty">No output recorded.</div>';
    return;
  }
  const pre = document.createElement('pre');
  pre.className = 'sbv-log-view' + (state.codeWrap ? ' wrap' : '');
  pre.textContent = String(text);
  dom.bodyEl.appendChild(pre);
}

export function renderInlineView(ctx) {
  const { state, dom, onToast } = ctx;
  const inl = state.inline;
  if (!inl) return;
  if (inl.kind === 'md') {
    const acts = (inl.actions || []).map((a) => ({ label: a.label, onClick: a.onClick }));
    setSubbar(dom.subbarEl, [
      { label: 'Rendered', active: !state.mdRaw, onClick: () => { state.mdRaw = false; renderInlineView(ctx); } },
      { label: 'Raw', active: state.mdRaw, onClick: () => { state.mdRaw = true; renderInlineView(ctx); } },
      { spacer: true },
      ...acts,
      {
        label: 'Copy',
        onClick: () => {
          navigator.clipboard?.writeText(inl.content || '').then(() => onToast('Copied to clipboard')).catch(() => {});
        },
      },
    ]);
    dom.bodyEl.innerHTML = '';
    if (inl.note) {
      const note = document.createElement('div');
      note.className = 'sbv-inline-note';
      if (inl.noteTone) note.dataset.tone = inl.noteTone;
      note.textContent = inl.note;
      dom.bodyEl.appendChild(note);
    }
    if (state.mdRaw) {
      const pre = document.createElement('pre');
      pre.className = 'sbv-log-view wrap';
      pre.textContent = inl.content || '';
      dom.bodyEl.appendChild(pre);
      return;
    }
    const article = document.createElement('article');
    article.className = 'sbv-md';
    article.innerHTML = renderMarkdown(inl.content || '', '');
    dom.bodyEl.appendChild(article);
    return;
  }
  setSubbar(dom.subbarEl, [
    { label: 'Wrap', active: state.codeWrap, onClick: () => { state.codeWrap = !state.codeWrap; renderInlineView(ctx); } },
    { spacer: true },
    {
      label: 'Copy',
      onClick: () => {
        navigator.clipboard?.writeText(inl.content || '').then(() => onToast('Copied to clipboard')).catch(() => {});
      },
    },
  ]);
  if (inl.kind === 'diff') {
    renderDiffContent(ctx, inl.content);
  } else {
    renderLogContent(ctx, inl.content);
  }
}

export function renderBinaryCard(bodyEl, stat) {
  bodyEl.innerHTML =
    '<div class="sbv-binary-card">' +
      '<div class="sbv-binary-name">' + escHtml(stat.name) + '</div>' +
      '<div class="sbv-binary-meta">' + escHtml(stat.mime) + ' · ' + escHtml(fmtBytes(stat.size)) + '</div>' +
      '<a class="sbv-primary-btn" href="' + escHtml(stat.rawUrl + '?download=1') + '" download="' + escHtml(stat.name) + '">Download file</a>' +
    '</div>';
}
