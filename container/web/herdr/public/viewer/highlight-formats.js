/* Specialized syntax tokenizers for diff, HTML/XML, CSS, YAML/TOML, and raw Markdown. */

export function tokenizeDiff(text) {
  const tokens = [];
  const lines = text.split('\n');
  for (let i = 0; i < lines.length; i++) {
    const ln = lines[i];
    let type = 'plain';
    if (ln.startsWith('diff --git ') || ln.startsWith('+++ ') || ln.startsWith('--- ') || ln.startsWith('index ')) {
      type = 'cmt';
    } else if (ln.startsWith('@@')) {
      type = 'hunk';
    } else if (ln.startsWith('+')) {
      type = 'add';
    } else if (ln.startsWith('-')) {
      type = 'del';
    }
    if (ln) tokens.push({ type, value: ln });
    if (i < lines.length - 1) tokens.push({ type: 'plain', value: '\n' });
  }
  return tokens;
}

export function tokenizeHtml(text) {
  const tokens = [];
  let i = 0;
  const n = text.length;
  while (i < n) {
    if (text.startsWith('<!--', i)) {
      const end = text.indexOf('-->', i + 4);
      const stop = end === -1 ? n : end + 3;
      tokens.push({ type: 'cmt', value: text.slice(i, stop) });
      i = stop;
      continue;
    }
    if (text.startsWith('<!', i)) {
      const end = text.indexOf('>', i + 2);
      const stop = end === -1 ? n : end + 1;
      tokens.push({ type: 'cmt', value: text.slice(i, stop) });
      i = stop;
      continue;
    }
    if (text[i] === '<') {
      const tagMatch = text.slice(i).match(/^<\/?([A-Za-z][A-Za-z0-9:._-]*)/);
      if (tagMatch) {
        const prefix = text[i + 1] === '/' ? '</' : '<';
        tokens.push({ type: 'op', value: prefix });
        tokens.push({ type: 'tag', value: tagMatch[1] });
        i += tagMatch[0].length;
        while (i < n && text[i] !== '>') {
          if (text.startsWith('/>', i)) {
            tokens.push({ type: 'op', value: '/>' });
            i += 2;
            break;
          }
          const ws = text.slice(i).match(/^\s+/);
          if (ws) {
            tokens.push({ type: 'plain', value: ws[0] });
            i += ws[0].length;
            continue;
          }
          const attr = text.slice(i).match(/^[A-Za-z_:][A-Za-z0-9_.:-]*/);
          if (attr) {
            tokens.push({ type: 'attr', value: attr[0] });
            i += attr[0].length;
            continue;
          }
          if (text[i] === '=') {
            tokens.push({ type: 'op', value: '=' });
            i++;
            continue;
          }
          if (text[i] === '"' || text[i] === "'") {
            const q = text[i];
            let j = i + 1;
            while (j < n && text[j] !== q) j++;
            if (j < n) j++;
            tokens.push({ type: 'str', value: text.slice(i, j) });
            i = j;
            continue;
          }
          tokens.push({ type: 'plain', value: text[i] });
          i++;
        }
        if (i < n && text[i] === '>') {
          tokens.push({ type: 'op', value: '>' });
          i++;
        }
        continue;
      }
    }
    const nextTag = text.indexOf('<', i + 1);
    const stop = nextTag === -1 ? n : nextTag;
    tokens.push({ type: 'plain', value: text.slice(i, stop) });
    i = stop;
  }
  return tokens;
}

export function tokenizeCss(text) {
  const tokens = [];
  let i = 0;
  const n = text.length;
  while (i < n) {
    if (text.startsWith('/*', i)) {
      const end = text.indexOf('*/', i + 2);
      const stop = end === -1 ? n : end + 2;
      tokens.push({ type: 'cmt', value: text.slice(i, stop) });
      i = stop;
      continue;
    }
    if (text[i] === '"' || text[i] === "'") {
      const q = text[i];
      let j = i + 1;
      while (j < n && text[j] !== q) {
        if (text[j] === '\\' && j + 1 < n) j += 2;
        else j++;
      }
      if (j < n) j++;
      tokens.push({ type: 'str', value: text.slice(i, j) });
      i = j;
      continue;
    }
    const rest = text.slice(i);
    let m;
    if ((m = rest.match(/^@[A-Za-z-]+/))) {
      tokens.push({ type: 'kw', value: m[0] });
      i += m[0].length;
      continue;
    }
    if ((m = rest.match(/^--[A-Za-z0-9_-]+/))) {
      tokens.push({ type: 'var', value: m[0] });
      i += m[0].length;
      continue;
    }
    if ((m = rest.match(/^#[0-9a-fA-F]{3,8}\b/))) {
      tokens.push({ type: 'num', value: m[0] });
      i += m[0].length;
      continue;
    }
    if ((m = rest.match(/^[+-]?(?:\d+\.?\d*|\.\d+)(?:%|px|em|rem|vh|vw|vmin|vmax|ch|ex|fr|deg|rad|ms|s)?\b/))) {
      tokens.push({ type: 'num', value: m[0] });
      i += m[0].length;
      continue;
    }
    if ((m = rest.match(/^([A-Za-z-]+)(?=\s*:)/))) {
      tokens.push({ type: 'key', value: m[1] });
      i += m[1].length;
      continue;
    }
    if ((m = rest.match(/^([A-Za-z_-][A-Za-z0-9_-]*)(?=\s*\()/))) {
      tokens.push({ type: 'fn', value: m[1] });
      i += m[1].length;
      continue;
    }
    if ((m = rest.match(/^[.#][A-Za-z_-][A-Za-z0-9_-]*/))) {
      tokens.push({ type: 'tag', value: m[0] });
      i += m[0].length;
      continue;
    }
    if ((m = rest.match(/^!important\b/))) {
      tokens.push({ type: 'kw', value: m[0] });
      i += m[0].length;
      continue;
    }
    tokens.push({ type: 'plain', value: text[i] });
    i++;
  }
  return tokens;
}

function tokenizeGenericValue(seg) {
  const out = [];
  let i = 0;
  const n = seg.length;
  while (i < n) {
    if (seg[i] === '#' && (i === 0 || /\s/.test(seg[i - 1]))) {
      out.push({ type: 'cmt', value: seg.slice(i) });
      break;
    }
    if (seg[i] === '"' || seg[i] === "'") {
      const q = seg[i];
      let j = i + 1;
      while (j < n && seg[j] !== q) {
        if (q === '"' && seg[j] === '\\' && j + 1 < n) j += 2;
        else j++;
      }
      if (j < n) j++;
      out.push({ type: 'str', value: seg.slice(i, j) });
      i = j;
      continue;
    }
    const rest = seg.slice(i);
    let m;
    if ((m = rest.match(/^(?:true|false|null|yes|no|on|off)\b/i))) {
      out.push({ type: 'bool', value: m[0] });
      i += m[0].length;
      continue;
    }
    if ((m = rest.match(/^-?(?:0x[0-9a-fA-F]+|\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)\b/))) {
      out.push({ type: 'num', value: m[0] });
      i += m[0].length;
      continue;
    }
    out.push({ type: 'plain', value: seg[i] });
    i++;
  }
  return out;
}

export function tokenizeYamlOrToml(text, lang) {
  const tokens = [];
  const lines = text.split('\n');
  for (let li = 0; li < lines.length; li++) {
    const ln = lines[li];
    if (lang === 'toml' && /^\s*\[+[^\]]+\]+\s*$/.test(ln)) {
      tokens.push({ type: 'tag', value: ln });
    } else if (/^\s*#/.test(ln)) {
      tokens.push({ type: 'cmt', value: ln });
    } else {
      const keyRe = lang === 'yaml'
        ? /^(\s*(?:-\s+)?)([A-Za-z0-9_.-]+|"[^"]+"|'[^']+')(\s*:)(.*)$/
        : /^(\s*)([A-Za-z0-9_.-]+|"[^"]+")(\s*=)(.*)$/;
      const km = ln.match(keyRe);
      if (km) {
        if (km[1]) tokens.push({ type: 'plain', value: km[1] });
        tokens.push({ type: 'key', value: km[2] });
        tokens.push({ type: 'op', value: km[3] });
        if (km[4]) tokens.push(...tokenizeGenericValue(km[4]));
      } else {
        tokens.push(...tokenizeGenericValue(ln));
      }
    }
    if (li < lines.length - 1) tokens.push({ type: 'plain', value: '\n' });
  }
  return tokens;
}

export function tokenizeMarkdownRaw(text) {
  const tokens = [];
  const lines = text.split('\n');
  let inFence = false;
  for (let li = 0; li < lines.length; li++) {
    const ln = lines[li];
    if (/^\s*(?:```|~~~)/.test(ln)) {
      inFence = !inFence;
      tokens.push({ type: 'kw', value: ln });
    } else if (inFence) {
      tokens.push({ type: 'str', value: ln });
    } else if (/^#{1,6}\s/.test(ln)) {
      tokens.push({ type: 'tag', value: ln });
    } else if (/^\s*>\s?/.test(ln)) {
      tokens.push({ type: 'cmt', value: ln });
    } else {
      let i = 0;
      const n = ln.length;
      while (i < n) {
        const rest = ln.slice(i);
        let m;
        if ((m = rest.match(/^`[^`]+`/))) {
          tokens.push({ type: 'str', value: m[0] });
          i += m[0].length;
          continue;
        }
        if ((m = rest.match(/^!\[[^\]]*\]\([^)]+\)|^\[[^\]]+\]\([^)]+\)/))) {
          tokens.push({ type: 'fn', value: m[0] });
          i += m[0].length;
          continue;
        }
        if ((m = rest.match(/^\*\*[^*]+\*\*|^__[^_]+__/))) {
          tokens.push({ type: 'kw', value: m[0] });
          i += m[0].length;
          continue;
        }
        tokens.push({ type: 'plain', value: ln[i] });
        i++;
      }
    }
    if (li < lines.length - 1) tokens.push({ type: 'plain', value: '\n' });
  }
  return tokens;
}
