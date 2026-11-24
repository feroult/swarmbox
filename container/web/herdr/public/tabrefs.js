/* Tab references in the Sysop's replies: every way a reply names a tab becomes the same chip (agent icon + tab name).
 *
 * A model writes a tab as `shop-api`, shop-api, t3, @3, 1:shop-api or "shop-api (t3)". Rendering only some of them (a live id, a name in
 * backticks) made the same reply highlight one tab and print the next one raw. parse() finds them all and resolves each to a tab, live or
 * closed (the page remembers the names of the tabs it has seen), so the panel can draw one chip per reference, dimmed when the tab is gone.
 * It also marks test results ("24 passed", "3 failed") for a quiet colour. Pure: no DOM, so tests run it in Node.
 *
 * parse(text, tabs) -> [{t: 'text', v} | {t: 'tab', tab, raw} | {t: 'code', v} | {t: 'bold', v} | {t: 'ok', v} | {t: 'bad', v}]
 *   tabs: [{address, name, aliases, kind, live}]: name is what the page shows (the chip), aliases the other names a reply may use (the herdr name)
 */
(function (root) {
  'use strict';

  // names that are ordinary words of a reply: only a backticked, numbered (1:shell) or id reference turns them into a tab
  const COMMON = new Set(['shell', 'bash', 'sh', 'zsh', 'fish', 'claude', 'agy', 'codex', 'gemini', 'opencode', 'sysop', 'main', 'tab', 'aba',
    'term', 'terminal', 'test', 'tests', 'home', 'work', 'app', 'api', 'web']);
  const OK_RE = String.raw`\b\d+\s+(?:(?:unit\s+)?tests?\s+|testes?\s+)?(?:passed|passing|pass|passaram|passou|ok)\b`;
  const BAD_RE = String.raw`\b\d+\s+(?:tests?\s+|testes?\s+)?(?:failed|failing|failures?|falharam|falhou|falhas?|errors?|erros?)\b`;

  function escapeRe(s) {
    return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  }

  function resolver(tabs) {
    const list = Array.isArray(tabs) ? tabs.filter((t) => t && t.address) : [];
    return function resolve(token) {
      let s = String(token || '').trim();
      if (!s) return null;
      const hit = (pred) => list.find((t) => t.live && pred(t)) || list.find(pred) || null;
      const byAddr = hit((t) => t.address === s);
      if (byAddr) return byAddr;
      s = s.replace(/^\d{1,3}:/, '');               // 1:shop-api, the numbered label of list_tabs
      const low = s.toLowerCase();
      return hit((t) => t.name === s) || hit((t) => (t.aliases || []).includes(s))
        || hit((t) => [t.name].concat(t.aliases || []).some((n) => String(n || '').toLowerCase() === low));
    };
  }

  function master(tabs) {
    const names = [];
    const seen = new Set();
    for (const t of Array.isArray(tabs) ? tabs : []) {
      for (const raw of [t && t.name].concat((t && t.aliases) || [])) {
        const n = String(raw || '');
        if (n.length >= 3 && !COMMON.has(n.toLowerCase()) && !/^[t@]\d[a-z0-9]{0,3}$/i.test(n) && !seen.has(n)) {
          seen.add(n);
          names.push(n);
        }
      }
    }
    names.sort((a, b) => b.length - a.length);
    const ref = [String.raw`[t@]\d[a-z0-9]{0,3}`, String.raw`\d{1,3}:[\w.-]{1,32}`].concat(names.map(escapeRe)).join('|');
    // a reference stands alone: not inside a path (~/swarmbox), a file name (swarmbox.py) or a longer word
    return new RegExp('`([^`\\n]{1,80})`|\\*\\*([^*\\n]{1,120})\\*\\*|(' + OK_RE + ')|(' + BAD_RE + ')|(^|[^\\w/~.@:-])(' + ref + ')(?![\\w/-])(?!\\.\\w)', 'gi');
  }

  // a tab reference that resolves to no tab this page knows (closed before the page saw it): still a chip, dimmed, with what the reply called it
  function unknownTab(raw) {
    const id = /^[t@]\d[a-z0-9]{0,3}$/i.test(raw);
    const label = /^\d{1,3}:([\w.-]{1,32})$/.exec(raw);
    if (!id && !label) return null;
    return { address: raw, name: label ? label[1] : raw, kind: 'shell', live: false, unknown: true };
  }

  function isNameCase(raw, tab) {
    // bare names match case-sensitively ("SwarmBox" the product is not the tab "swarmbox"); ids and numbered labels in any case
    return /^[t@]\d[a-z0-9]{0,3}$/i.test(raw) || /^\d{1,3}:/.test(raw) || raw === tab.name || (tab.aliases || []).includes(raw);
  }

  function parse(text, tabs) {
    const src = String(text == null ? '' : text);
    const resolve = resolver(tabs);
    const re = master(tabs);
    const out = [];
    const put = (seg) => {
      if (seg.t === 'text') {
        if (!seg.v) return;
        const prev = out[out.length - 1];
        if (prev && prev.t === 'text') {
          prev.v += seg.v;
          return;
        }
      }
      out.push(seg);
    };
    let last = 0;
    let m;
    while ((m = re.exec(src))) {
      if (m[1] !== undefined) {
        put({ t: 'text', v: src.slice(last, m.index) });
        const tab = resolve(m[1]);
        const t2 = tab || unknownTab(m[1].trim());
        put(t2 ? { t: 'tab', tab: t2, raw: m[1] } : { t: 'code', v: m[1] });
        last = m.index + m[0].length;
      } else if (m[2] !== undefined) {
        put({ t: 'text', v: src.slice(last, m.index) });
        const inner = m[2].trim();
        const unwrapped = inner.startsWith('`') && inner.endsWith('`') && inner.length > 2 ? inner.slice(1, -1) : inner;
        const tab = resolve(unwrapped);
        const t2 = (tab && (inner !== unwrapped || isNameCase(unwrapped, tab))) ? tab : unknownTab(unwrapped);
        put(t2 ? { t: 'tab', tab: t2, raw: unwrapped } : { t: 'bold', v: m[2] });
        last = m.index + m[0].length;
      } else if (m[3] !== undefined || m[4] !== undefined) {
        put({ t: 'text', v: src.slice(last, m.index) });
        // "0 failed" is good news: green like a pass
        put({ t: m[3] !== undefined || /^0\s/.test(m[0]) ? 'ok' : 'bad', v: m[0] });
        last = m.index + m[0].length;
      } else {
        const at = m.index + m[5].length;
        const raw = m[6];
        let tab = resolve(raw);
        if (tab && !isNameCase(raw, tab)) tab = null;
        if (!tab) tab = unknownTab(raw);
        if (!tab) continue;
        put({ t: 'text', v: src.slice(last, at) });
        put({ t: 'tab', tab, raw });
        last = at + raw.length;
      }
    }
    put({ t: 'text', v: src.slice(last) });
    return dedupe(out);
  }

  // "shop-api (t3)", "t3 (shop-api)", "`1:shell` (`t2`, active)": the second name of the same tab goes, what else the parenthesis said stays
  function dedupe(segs) {
    const out = segs.slice();
    for (let i = 0; i + 2 < out.length; i++) {
      const a = out[i];
      const open = out[i + 1];
      const b = out[i + 2];
      if (a.t !== 'tab' || open.t !== 'text' || b.t !== 'tab' || a.tab.address !== b.tab.address) continue;
      const om = /\s*\(\s*$/.exec(open.v);
      if (!om) continue;
      const head = open.v.slice(0, om.index);
      const after = out[i + 3] && out[i + 3].t === 'text' ? out[i + 3] : null;
      if (after && /^\s*\)/.test(after.v)) {
        open.v = head;
        after.v = after.v.replace(/^\s*\)/, '');
      } else if (after && /^\s*[,;·-]\s*/.test(after.v)) {
        open.v = head + ' (';
        after.v = after.v.replace(/^\s*[,;·-]\s*/, '');
      } else {
        continue;
      }
      out.splice(i + 2, 1);
    }
    return out.filter((s) => s.t !== 'text' || s.v);
  }

  const api = { parse, COMMON };
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.SbTabRefs = api;
})(typeof window !== 'undefined' ? window : globalThis);
