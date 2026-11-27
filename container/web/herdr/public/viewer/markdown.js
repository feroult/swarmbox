/* Lightweight, XSS-safe GitHub Flavored Markdown renderer. */

import {
  encodeRawUrl,
  escHtml,
  isExternalUrl,
  resolveRelativePath,
} from './utils.js';
import { highlightCode } from './highlight.js';

export function renderInlineMd(text, baseDir) {
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

export function renderMarkdown(mdText, baseDir) {
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
      const highlighted = highlightCode(codeStr, lang);
      const langAttr = lang ? ' data-lang="' + escHtml(lang) + '"' : '';
      out.push(
        '<div class="sbv-md-codeblock">' +
        '<div class="sbv-md-codehead">' +
        '<span>' + escHtml(lang || 'code') + '</span>' +
        '<button type="button" class="sbv-mini-btn sbv-copy-code">Copy</button>' +
        '</div>' +
        '<pre><code' + langAttr + '>' + highlighted + '</code></pre>' +
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
