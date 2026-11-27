/* Zero-dependency, XSS-safe Syntax Highlighter (for Code Viewer & Markdown). */

import { escHtml } from './utils.js';
import {
  BOOL_WORDS,
  BUILTIN_TYPES,
  KW_SETS,
  MAX_HIGHLIGHT_CHARS,
  detectLanguage,
} from './highlight-langs.js';
import {
  tokenizeCss,
  tokenizeDiff,
  tokenizeHtml,
  tokenizeMarkdownRaw,
  tokenizeYamlOrToml,
} from './highlight-formats.js';

export { detectLanguage };

export function tokenizeCode(text, lang) {
  if (lang === 'diff') return tokenizeDiff(text);
  if (lang === 'html') return tokenizeHtml(text);
  if (lang === 'css') return tokenizeCss(text);
  if (lang === 'yaml' || lang === 'toml') return tokenizeYamlOrToml(text, lang);
  if (lang === 'md') return tokenizeMarkdownRaw(text);

  const kws = KW_SETS[lang] || null;
  const isSql = lang === 'sql';
  const isDocker = lang === 'dockerfile';
  const isHashComment = lang === 'py' || lang === 'sh' || lang === 'rb' || lang === 'dockerfile' || lang === 'makefile' || lang === 'php';
  const isSlashComment = lang === 'js' || lang === 'ts' || lang === 'go' || lang === 'rust' || lang === 'c' || lang === 'java' || lang === 'php' || lang === 'json';
  const isDashComment = lang === 'sql';
  const isBacktickStr = lang === 'js' || lang === 'ts' || lang === 'go' || lang === 'sh' || lang === 'sql';
  const isTripleStr = lang === 'py';
  const isShellVar = lang === 'sh' || lang === 'php' || lang === 'makefile';
  const isJson = lang === 'json';

  const tokens = [];
  let i = 0;
  const n = text.length;

  while (i < n) {
    const ch = text[i];

    // Block comment /* ... */
    if (isSlashComment && ch === '/' && text[i + 1] === '*') {
      const end = text.indexOf('*/', i + 2);
      const stop = end === -1 ? n : end + 2;
      tokens.push({ type: 'cmt', value: text.slice(i, stop) });
      i = stop;
      continue;
    }

    // Line comment // ...
    if (isSlashComment && ch === '/' && text[i + 1] === '/') {
      const nl = text.indexOf('\n', i + 2);
      const stop = nl === -1 ? n : nl;
      tokens.push({ type: 'cmt', value: text.slice(i, stop) });
      i = stop;
      continue;
    }

    // Line comment -- ... (SQL)
    if (isDashComment && ch === '-' && text[i + 1] === '-') {
      const nl = text.indexOf('\n', i + 2);
      const stop = nl === -1 ? n : nl;
      tokens.push({ type: 'cmt', value: text.slice(i, stop) });
      i = stop;
      continue;
    }

    // Line comment # ...
    if (isHashComment && ch === '#') {
      const nl = text.indexOf('\n', i + 1);
      const stop = nl === -1 ? n : nl;
      tokens.push({ type: 'cmt', value: text.slice(i, stop) });
      i = stop;
      continue;
    }

    // C preprocessor directives (#include, #define, ...)
    if (lang === 'c' && ch === '#' && (i === 0 || text[i - 1] === '\n')) {
      const m = text.slice(i).match(/^#\s*[A-Za-z_]\w*/);
      if (m) {
        tokens.push({ type: 'kw', value: m[0] });
        i += m[0].length;
        continue;
      }
    }

    // Python triple-quoted strings
    if (isTripleStr && (text.startsWith('"""', i) || text.startsWith("'''", i))) {
      const q3 = text.slice(i, i + 3);
      let j = i + 3;
      while (j < n && !text.startsWith(q3, j)) {
        if (text[j] === '\\' && j + 1 < n) j += 2;
        else j++;
      }
      if (j < n) j += 3;
      tokens.push({ type: 'str', value: text.slice(i, j) });
      i = j;
      continue;
    }

    // Strings ("...", '...', `...`)
    if (ch === '"' || ch === "'" || (isBacktickStr && ch === '`')) {
      // Rust lifetimes like 'a should not eat until the next apostrophe
      if (lang === 'rust' && ch === "'" && /^'[A-Za-z_]\w*(?!')/.test(text.slice(i))) {
        const lm = text.slice(i).match(/^'[A-Za-z_]\w*/);
        tokens.push({ type: 'attr', value: lm[0] });
        i += lm[0].length;
        continue;
      }
      let j = i + 1;
      while (j < n && text[j] !== ch) {
        if (text[j] === '\\' && j + 1 < n) {
          j += 2;
          continue;
        }
        if (ch !== '`' && text[j] === '\n') break;
        j++;
      }
      if (j < n && text[j] === ch) j++;
      const rawStr = text.slice(i, j);
      if (isJson && ch === '"' && /^\s*:/.test(text.slice(j))) {
        tokens.push({ type: 'key', value: rawStr });
      } else {
        tokens.push({ type: 'str', value: rawStr });
      }
      i = j;
      continue;
    }

    // Shell / PHP / Makefile variables ($VAR, ${VAR}, $(VAR))
    if (isShellVar && ch === '$') {
      const vm = text.slice(i).match(/^\$(?:\{[^}\n]+\}|\([^)\n]+\)|[A-Za-z_][A-Za-z0-9_]*|[0-9@#?$!*-])/);
      if (vm) {
        tokens.push({ type: 'var', value: vm[0] });
        i += vm[0].length;
        continue;
      }
    }

    // Decorators / attributes (@decorator, #[attr])
    if ((lang === 'py' || lang === 'ts' || lang === 'js' || lang === 'java') && ch === '@') {
      const dm = text.slice(i).match(/^@[A-Za-z_][A-Za-z0-9_.]*/);
      if (dm) {
        tokens.push({ type: 'attr', value: dm[0] });
        i += dm[0].length;
        continue;
      }
    }

    // Numbers
    if (/[0-9]/.test(ch) && (i === 0 || !/[A-Za-z0-9_$]/.test(text[i - 1]))) {
      const nm = text.slice(i).match(/^(?:0[xX][0-9a-fA-F_]+|0[bB][01_]+|0[oO][0-7_]+|\d[\d_]*(?:\.[\d_]+)?(?:[eE][+-]?\d+)?)[uUlLfFnN]?/);
      if (nm) {
        tokens.push({ type: 'num', value: nm[0] });
        i += nm[0].length;
        continue;
      }
    }

    // Identifiers / Keywords / Types / Function calls
    if (/[A-Za-z_]/.test(ch)) {
      const im = text.slice(i).match(/^[A-Za-z_][A-Za-z0-9_]*/);
      const word = im[0];
      const nextIdx = i + word.length;
      const lower = word.toLowerCase();

      if (isJson) {
        if (word === 'true' || word === 'false' || word === 'null') {
          tokens.push({ type: 'bool', value: word });
        } else {
          tokens.push({ type: 'plain', value: word });
        }
      } else if (kws && (kws.has(word) || ((isSql || isDocker) && kws.has(lower)))) {
        tokens.push({ type: 'kw', value: word });
      } else if (BOOL_WORDS.has(word)) {
        tokens.push({ type: 'bool', value: word });
      } else if (BUILTIN_TYPES.has(word)) {
        tokens.push({ type: 'type', value: word });
      } else if (text[nextIdx] === '(') {
        tokens.push({ type: 'fn', value: word });
      } else if (/^[A-Z][A-Za-z0-9_]*$/.test(word) && /[a-z]/.test(word)) {
        tokens.push({ type: 'type', value: word });
      } else {
        tokens.push({ type: 'plain', value: word });
      }
      i = nextIdx;
      continue;
    }

    // Plain character run (batch whitespace/punctuation for speed)
    let j = i + 1;
    while (j < n && !/[A-Za-z0-9_"'`/#@$<>-]/.test(text[j])) j++;
    tokens.push({ type: 'plain', value: text.slice(i, j) });
    i = j;
  }

  return tokens;
}

function renderTokenHtml(type, value) {
  const safe = escHtml(value);
  if (!type || type === 'plain') return safe;
  return '<span class="sbv-tok-' + type + '">' + safe + '</span>';
}

export function highlightCode(text, langHint) {
  const src = String(text == null ? '' : text);
  const lang = detectLanguage(langHint);
  if (!lang || !src || src.length > MAX_HIGHLIGHT_CHARS) {
    return escHtml(src);
  }
  const tokens = tokenizeCode(src, lang);
  let out = '';
  for (let i = 0; i < tokens.length; i++) {
    out += renderTokenHtml(tokens[i].type, tokens[i].value);
  }
  return out;
}

export function highlightLines(text, langHint) {
  const src = String(text == null ? '' : text).replace(/\r\n/g, '\n');
  const lang = detectLanguage(langHint);
  if (!lang || src.length > MAX_HIGHLIGHT_CHARS) {
    return src.split('\n').map((ln) => escHtml(ln));
  }
  const tokens = tokenizeCode(src, lang);
  const lines = [''];
  for (let i = 0; i < tokens.length; i++) {
    const tok = tokens[i];
    if (!tok.value.includes('\n')) {
      lines[lines.length - 1] += renderTokenHtml(tok.type, tok.value);
    } else {
      const parts = tok.value.split('\n');
      for (let p = 0; p < parts.length; p++) {
        if (p > 0) lines.push('');
        if (parts[p]) lines[lines.length - 1] += renderTokenHtml(tok.type, parts[p]);
      }
    }
  }
  return lines;
}
