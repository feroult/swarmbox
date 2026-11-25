/* SwarmBox Shared File Viewer (used by both the slide-over Drawer in index.html
 * and the standalone fullscreen /view?path=... page).
 * Zero external dependencies, XSS-safe Markdown GFM renderer, sandboxed HTML preview,
 * folder gallery + lightbox, and code viewer with line highlight.
 */
(function (root) {
  'use strict';

  function escHtml(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function fmtBytes(n) {
    const v = Number(n) || 0;
    if (v < 1024) return v + ' B';
    if (v < 1024 * 1024) return (v / 1024).toFixed(1) + ' KB';
    if (v < 1024 * 1024 * 1024) return (v / (1024 * 1024)).toFixed(1) + ' MB';
    return (v / (1024 * 1024 * 1024)).toFixed(2) + ' GB';
  }

  function encodeRawUrl(absPath) {
    return '/api/files/raw/' + String(absPath || '').replace(/^\/+/, '').split('/').map(encodeURIComponent).join('/');
  }

  function resolveRelativePath(baseDir, rel) {
    const s = String(rel || '').trim();
    if (!s) return baseDir;
    if (/^file:\/\//i.test(s)) {
      try { return decodeURIComponent(new URL(s).pathname || ''); } catch (_) { return s.replace(/^file:\/\//i, ''); }
    }
    if (s.startsWith('/') || s.startsWith('~/')) return s;
    const parts = String(baseDir || '').replace(/\/+$/, '').split('/').filter(Boolean);
    for (const seg of s.split('/')) {
      if (!seg || seg === '.') continue;
      if (seg === '..') {
        if (parts.length > 0) parts.pop();
      } else {
        parts.push(seg);
      }
    }
    return '/' + parts.join('/');
  }

  function isExternalUrl(href) {
    return /^(?:https?:|mailto:|tel:)/i.test(String(href || '').trim());
  }

  // -------------------------------------------------------------------------
  // Lightweight, XSS-safe GitHub Flavored Markdown renderer
  // -------------------------------------------------------------------------
  function renderInlineMd(text, baseDir) {
    const tokens = [];
    const stash = (html) => {
      const idx = tokens.length;
      tokens.push(html);
      return '\u0000T' + idx + '\u0000';
    };

    let s = String(text || '');

    // Inline code spans first so contents are never parsed as markdown
    s = s.replace(/`([^`\n]+)`/g, (_, code) => stash('<code>' + escHtml(code) + '</code>'));

    // Images: ![alt](src "title")
    s = s.replace(/!\[([^\]]*)\]\(([^)\s]+)(?:\s+"([^"]*)")?\)/g, (_, alt, src, title) => {
      const rawSrc = src.trim();
      let imgUrl = '';
      let resolvedPath = '';
      if (isExternalUrl(rawSrc) || rawSrc.startsWith('data:image/')) {
        imgUrl = rawSrc;
      } else {
        resolvedPath = resolveRelativePath(baseDir, rawSrc);
        imgUrl = encodeRawUrl(resolvedPath);
      }
      const attrs = resolvedPath ? ' data-preview-path="' + escHtml(resolvedPath) + '"' : '';
      const titleAttr = title ? ' title="' + escHtml(title) + '"' : '';
      return stash(
        '<span class="sbv-md-img-wrap">' +
        '<img class="sbv-md-img" src="' + escHtml(imgUrl) + '" alt="' + escHtml(alt) + '"' + titleAttr + attrs + ' loading="lazy">' +
        (alt ? '<span class="sbv-md-img-cap">' + escHtml(alt) + '</span>' : '') +
        '</span>'
      );
    });

    // Links: [label](href)
    s = s.replace(/\[([^\]]+)\]\(([^)\s]+)(?:\s+"([^"]*)")?\)/g, (_, label, href, title) => {
      const rawHref = href.trim();
      const titleAttr = title ? ' title="' + escHtml(title) + '"' : '';
      if (isExternalUrl(rawHref)) {
        return stash('<a href="' + escHtml(rawHref) + '" target="_blank" rel="noopener noreferrer"' + titleAttr + '>' + renderInlineMd(label, baseDir) + '</a>');
      }
      if (rawHref.startsWith('#')) {
        return stash('<a href="' + escHtml(rawHref) + '"' + titleAttr + '>' + renderInlineMd(label, baseDir) + '</a>');
      }
      const resolved = resolveRelativePath(baseDir, rawHref);
      return stash('<a href="#" class="sbv-md-local-link" data-local-path="' + escHtml(resolved) + '"' + titleAttr + '>' + renderInlineMd(label, baseDir) + '</a>');
    });

    // Escape remaining HTML
    s = escHtml(s);

    // Bold, italic, strikethrough
    s = s.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
    s = s.replace(/__([^_]+)__/g, '<strong>$1</strong>');
    s = s.replace(/~~([^~]+)~~/g, '<del>$1</del>');
    s = s.replace(/(^|[\s(])\*([^*\n]+)\*(?=[\s).,;:!?]|$)/g, '$1<em>$2</em>');

    // Bare https:// autolinks
    s = s.replace(/(^|[\s(])(https?:\/\/[^\s<)]+)/g, '$1<a href="$2" target="_blank" rel="noopener noreferrer">$2</a>');

    return s.replace(/\u0000T(\d+)\u0000/g, (_, idx) => tokens[Number(idx)] || '');
  }

  function renderMarkdown(mdText, baseDir) {
    const lines = String(mdText || '').replace(/\r\n/g, '\n').split('\n');
    const out = [];
    let i = 0;

    const isTableSep = (line) => /^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$/.test(line);
    const splitRow = (line) => {
      let t = line.trim();
      if (t.startsWith('|')) t = t.slice(1);
      if (t.endsWith('|')) t = t.slice(0, -1);
      return t.split('|').map((c) => c.trim());
    };

    while (i < lines.length) {
      const line = lines[i];

      // Blank line
      if (/^\s*$/.test(line)) {
        i++;
        continue;
      }

      // Fenced code block (``` or ````)
      const fence = line.match(/^(`{3,}|~{3,})\s*([^\s`~]*)/);
      if (fence) {
        const delim = fence[1];
        const lang = fence[2] || '';
        const buf = [];
        i++;
        while (i < lines.length && !lines[i].startsWith(delim)) {
          buf.push(lines[i]);
          i++;
        }
        if (i < lines.length) i++;
        const codeStr = buf.join('\n');
        out.push(
          '<div class="sbv-md-codeblock">' +
          '<div class="sbv-md-codehead">' +
          '<span>' + escHtml(lang || 'code') + '</span>' +
          '<button type="button" class="sbv-mini-btn sbv-copy-code">Copy</button>' +
          '</div>' +
          '<pre><code>' + escHtml(codeStr) + '</code></pre>' +
          '</div>'
        );
        continue;
      }

      // Headings
      const h = line.match(/^(#{1,6})\s+(.+?)\s*#*$/);
      if (h) {
        const lvl = h[1].length;
        const slug = h[2].toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
        out.push('<h' + lvl + ' id="' + escHtml(slug) + '">' + renderInlineMd(h[2], baseDir) + '</h' + lvl + '>');
        i++;
        continue;
      }

      // Horizontal rule
      if (/^\s*(?:---+|\*\*\*+|___+)\s*$/.test(line)) {
        out.push('<hr>');
        i++;
        continue;
      }

      // Blockquote / GitHub Alert
      if (/^\s*>\s?/.test(line)) {
        const qLines = [];
        while (i < lines.length && /^\s*>\s?/.test(lines[i])) {
          qLines.push(lines[i].replace(/^\s*>\s?/, ''));
          i++;
        }
        const alertMatch = qLines[0] && qLines[0].match(/^\[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION)\]\s*(.*)$/i);
        if (alertMatch) {
          const kind = alertMatch[1].toLowerCase();
          const rest = [alertMatch[2]].concat(qLines.slice(1)).filter(Boolean).join('\n');
          out.push(
            '<div class="sbv-md-alert sbv-md-alert-' + kind + '">' +
            '<div class="sbv-md-alert-title">' + escHtml(alertMatch[1].toUpperCase()) + '</div>' +
            '<div class="sbv-md-alert-body">' + renderMarkdown(rest, baseDir) + '</div>' +
            '</div>'
          );
        } else {
          out.push('<blockquote>' + renderMarkdown(qLines.join('\n'), baseDir) + '</blockquote>');
        }
        continue;
      }

      // GFM Table
      if (line.includes('|') && i + 1 < lines.length && isTableSep(lines[i + 1])) {
        const headers = splitRow(line);
        i += 2;
        const rows = [];
        while (i < lines.length && lines[i].includes('|') && !/^\s*$/.test(lines[i])) {
          rows.push(splitRow(lines[i]));
          i++;
        }
        let html = '<div class="sbv-md-table-wrap"><table><thead><tr>';
        for (const c of headers) html += '<th>' + renderInlineMd(c, baseDir) + '</th>';
        html += '</tr></thead><tbody>';
        for (const r of rows) {
          html += '<tr>';
          for (let ci = 0; ci < headers.length; ci++) {
            html += '<td>' + renderInlineMd(r[ci] || '', baseDir) + '</td>';
          }
          html += '</tr>';
        }
        html += '</tbody></table></div>';
        out.push(html);
        continue;
      }

      // Lists (unordered & ordered)
      const ulMatch = line.match(/^(\s*)[-*+•]\s+(.*)$/);
      const olMatch = !ulMatch && line.match(/^(\s*)\d+[.)]\s+(.*)$/);
      if (ulMatch || olMatch) {
        const tag = ulMatch ? 'ul' : 'ol';
        const items = [];
        while (i < lines.length) {
          const m = tag === 'ul' ? lines[i].match(/^(\s*)[-*+•]\s+(.*)$/) : lines[i].match(/^(\s*)\d+[.)]\s+(.*)$/);
          if (!m) break;
          let itemText = m[2];
          i++;
          while (i < lines.length && /^\s{2,}\S/.test(lines[i]) && !/^\s*(?:[-*+•]|\d+[.)])\s+/.test(lines[i])) {
            itemText += ' ' + lines[i].trim();
            i++;
          }
          const task = itemText.match(/^\[([ xX])\]\s+(.*)$/);
          if (task) {
            const checked = task[1].toLowerCase() === 'x';
            items.push('<li class="sbv-task"><input type="checkbox" disabled' + (checked ? ' checked' : '') + '> <span>' + renderInlineMd(task[2], baseDir) + '</span></li>');
          } else {
            items.push('<li>' + renderInlineMd(itemText, baseDir) + '</li>');
          }
        }
        out.push('<' + tag + '>' + items.join('') + '</' + tag + '>');
        continue;
      }

      // Paragraph
      const pLines = [];
      while (
        i < lines.length &&
        !/^\s*$/.test(lines[i]) &&
        !/^(?:`{3,}|~{3,}|#{1,6}\s|\s*>\s?|\s*(?:---+|\*\*\*+|___+)\s*$|\s*[-*+•]\s+|\s*\d+[.)]\s+)/.test(lines[i])
      ) {
        if (lines[i].includes('|') && i + 1 < lines.length && isTableSep(lines[i + 1])) break;
        pLines.push(lines[i]);
        i++;
      }
      out.push('<p>' + renderInlineMd(pLines.join(' '), baseDir) + '</p>');
    }

    return out.join('\n');
  }

  // -------------------------------------------------------------------------
  // Shared Viewer Controller
  // -------------------------------------------------------------------------
  function createViewer(opts) {
    const container = opts.container;
    const mode = opts.mode || 'drawer'; // 'drawer' | 'standalone'
    const onClose = opts.onClose || null;
    const onToast = opts.onToast || (() => {});

    let state = {
      path: '',
      displayPath: '',
      info: null,
      siblingImages: [],
      siblingIdx: -1,
      zoom: 'fit', // 'fit' | number
      mdRaw: false,
      htmlSource: false,
      jsonPretty: true,
      codeWrap: false,
      expanded: false,
    };

    container.innerHTML =
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
                '<button type="button" class="sbv-icon-btn" data-act="close" title="Close (Esc)" aria-label="Close">' +
                  '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M18 6L6 18M6 6l12 12"/></svg>' +
                '</button>'
              : '') +
          '</div>' +
        '</header>' +
        '<div class="sbv-subbar hidden" data-role="subbar"></div>' +
        '<div class="sbv-body" data-role="body"></div>' +
      '</div>';

    const badgeEl = container.querySelector('[data-role="badge"]');
    const crumbsEl = container.querySelector('[data-role="crumbs"]');
    const metaEl = container.querySelector('[data-role="meta"]');
    const subbarEl = container.querySelector('[data-role="subbar"]');
    const bodyEl = container.querySelector('[data-role="body"]');
    const dlLink = container.querySelector('[data-act="download"]');
    const newTabLink = container.querySelector('[data-act="new-tab"]');

    function viewUrlFor(p, line) {
      const qs = new URLSearchParams();
      qs.set('path', p);
      if (line) qs.set('line', String(line));
      return '/view?' + qs.toString();
    }

    function renderCrumbs(absPath, displayPath) {
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
          btn.addEventListener('click', () => open(targetAbs));
          crumbsEl.appendChild(btn);
        }
      });
      requestAnimationFrame(() => { crumbsEl.scrollLeft = crumbsEl.scrollWidth; });
    }

    function setSubbar(buttons) {
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

    function renderCodeBlock(content, info, isJson) {
      let text = content;
      if (isJson && state.jsonPretty) {
        try {
          text = JSON.stringify(JSON.parse(content), null, 2);
        } catch (_) {}
      }
      const lines = text.replace(/\r\n/g, '\n').split('\n');
      const targetStart = info.line ? Number(info.line) : null;
      const targetEnd = info.endLine ? Number(info.endLine) : targetStart;

      const wrap = document.createElement('div');
      wrap.className = 'sbv-code-view' + (state.codeWrap ? ' wrap' : '');
      const table = document.createElement('table');
      table.className = 'sbv-code-table';
      const tbody = document.createElement('tbody');
      let targetRow = null;

      lines.forEach((ln, idx) => {
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
        tdCode.textContent = ln || ' ';
        tr.appendChild(tdNum);
        tr.appendChild(tdCode);
        tbody.appendChild(tr);
      });
      table.appendChild(tbody);
      wrap.appendChild(table);
      bodyEl.innerHTML = '';
      if (info.truncated) {
        const note = document.createElement('div');
        note.className = 'sbv-notice';
        note.textContent = 'Showing first 2 MB of ' + fmtBytes(info.size) + '. Use Download for the full file.';
        bodyEl.appendChild(note);
      }
      bodyEl.appendChild(wrap);
      if (targetRow) {
        requestAnimationFrame(() => targetRow.scrollIntoView({ block: 'center', behavior: 'instant' }));
      }
    }

    function renderImageView(info) {
      const hasSibs = state.siblingImages.length > 1 && state.siblingIdx >= 0;
      const buttons = [
        { label: 'Fit', active: state.zoom === 'fit', onClick: () => { state.zoom = 'fit'; renderImageView(info); } },
        { label: '100%', active: state.zoom === 1, onClick: () => { state.zoom = 1; renderImageView(info); } },
        { label: '−', onClick: () => { state.zoom = Math.max(0.25, (typeof state.zoom === 'number' ? state.zoom : 1) - 0.25); renderImageView(info); } },
        { label: '+', onClick: () => { state.zoom = Math.min(4, (typeof state.zoom === 'number' ? state.zoom : 1) + 0.25); renderImageView(info); } },
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
      setSubbar(buttons);

      bodyEl.innerHTML = '';
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
          metaEl.textContent = img.naturalWidth + '×' + img.naturalHeight + ' · ' + fmtBytes(info.size);
        }
      });
      img.addEventListener('click', () => {
        state.zoom = state.zoom === 'fit' ? 1 : 'fit';
        renderImageView(info);
      });
      stage.appendChild(img);
      bodyEl.appendChild(stage);
    }

    function renderDirView(data) {
      setSubbar([
        { labelOnly: true, label: (data.items || []).length + ' items' + (data.truncated ? ' (first 500)' : '') },
      ]);
      bodyEl.innerHTML = '';
      const wrap = document.createElement('div');
      wrap.className = 'sbv-dir-view';

      const items = data.items || [];
      const images = items.filter((it) => it.category === 'image');
      const others = items.filter((it) => it.category !== 'image');

      if (!items.length) {
        wrap.innerHTML = '<div class="sbv-empty">This directory is empty.</div>';
        bodyEl.appendChild(wrap);
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

      bodyEl.appendChild(wrap);
    }

    function renderMarkdownView(data) {
      setSubbar([
        { label: 'Rendered', active: !state.mdRaw, onClick: () => { state.mdRaw = false; renderMarkdownView(data); } },
        { label: 'Raw', active: state.mdRaw, onClick: () => { state.mdRaw = true; renderMarkdownView(data); } },
        { spacer: true },
        {
          label: 'Copy Markdown',
          onClick: () => {
            navigator.clipboard?.writeText(data.content || '').then(() => onToast('Markdown copied')).catch(() => {});
          },
        },
      ]);

      if (state.mdRaw) {
        renderCodeBlock(data.content || '', data, false);
        return;
      }
      bodyEl.innerHTML = '';
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
      bodyEl.appendChild(article);
    }

    async function renderHtmlView(info) {
      setSubbar([
        { label: 'Preview', active: !state.htmlSource, onClick: () => { state.htmlSource = false; renderHtmlView(info); } },
        { label: 'Source', active: state.htmlSource, onClick: () => { state.htmlSource = true; renderHtmlView(info); } },
        { spacer: true },
        { labelOnly: true, label: 'Sandboxed preview' },
      ]);

      if (state.htmlSource) {
        const res = await fetch('/api/files/read?path=' + encodeURIComponent(info.path));
        const data = await res.json();
        renderCodeBlock(data.content || '', data, false);
        return;
      }
      bodyEl.innerHTML = '';
      const frame = document.createElement('iframe');
      frame.className = 'sbv-iframe';
      frame.setAttribute('sandbox', 'allow-scripts');
      frame.src = info.rawUrl + '?t=' + Date.now();
      bodyEl.appendChild(frame);
    }

    async function open(targetPath, openOpts = {}) {
      const qs = new URLSearchParams();
      qs.set('path', targetPath);
      if (openOpts.cwd) qs.set('cwd', openOpts.cwd);
      if (openOpts.fallbackDir) qs.set('fallbackDir', openOpts.fallbackDir);

      state.zoom = 'fit';
      state.mdRaw = false;
      state.htmlSource = false;
      bodyEl.innerHTML = '<div class="sbv-loading">Loading preview…</div>';
      setSubbar([]);

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
      renderCrumbs(stat.path, stat.displayPath);
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
        renderDirView(data);
        return true;
      }

      if (stat.category === 'image') {
        await loadSiblingImages(stat);
        renderImageView(stat);
        return true;
      }

      if (stat.category === 'html') {
        await renderHtmlView(stat);
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
          renderMarkdownView(data);
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
          setSubbar(btns);
          renderCodeBlock(data.content || '', data, isJson);
        };
        renderText();
        return true;
      }

      // Binary fallback
      bodyEl.innerHTML =
        '<div class="sbv-binary-card">' +
          '<div class="sbv-binary-name">' + escHtml(stat.name) + '</div>' +
          '<div class="sbv-binary-meta">' + escHtml(stat.mime) + ' · ' + escHtml(fmtBytes(stat.size)) + '</div>' +
          '<a class="sbv-primary-btn" href="' + escHtml(stat.rawUrl + '?download=1') + '" download="' + escHtml(stat.name) + '">Download file</a>' +
        '</div>';
      return true;
    }

    // Header actions
    container.querySelector('[data-act="refresh"]')?.addEventListener('click', () => {
      if (state.path) open(state.path, { line: state.info?.line });
    });
    container.querySelector('[data-act="copy-path"]')?.addEventListener('click', () => {
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
      handleKey,
      getPath: () => state.path,
      viewUrlFor,
    };
  }

  const api = { createViewer, renderMarkdown, resolveRelativePath, encodeRawUrl };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.SwarmBoxViewer = api;
})(typeof globalThis !== 'undefined' ? globalThis : window);
