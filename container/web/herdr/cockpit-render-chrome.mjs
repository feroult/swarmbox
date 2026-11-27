// Chrome renderers for the SwarmBox Terminal Cockpit:
// top bar, left sidebar, bottom footer, and keyboard shortcuts help overlay.

import { DEFAULT_THEME, HERDR_THEMES, HOME } from './hc-client.mjs';
import {
  bgHex,
  buildRow,
  cleanStatusText,
  clipText,
  fgHex,
  fitText,
  smartTabName,
  smartTabParts,
  statusMeta,
  sysopStyle,
  visibleWidth,
} from './cockpit-ansi.mjs';

export function renderTopBar(ctx, L, pal) {
  const bgS = bgHex(pal.surface);
  const active = ctx.terminals.find((t) => t.address === ctx.activeAddr);
  const activeName = smartTabName(active);
  const sm = statusMeta(active, pal);
  const ss = sysopStyle(ctx.sysop.state, pal);
  const themeLabel = (HERDR_THEMES[ctx.themeName] || HERDR_THEMES[DEFAULT_THEME]).label;
  const now = new Date();
  const clock = `${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}`;

  const rightSegments = [];
  let rightW = 0;
  const urgentSysop = ctx.sysop.state === 'allow?' || ctx.sysop.state === 'sending';
  const showTopSysop = !L.sysop || urgentSysop;
  const sysopSeg = urgentSysop
    ? [
        { text: '◆ ', style: fgHex(ss.color) },
        { text: `SYSOP · ${ss.pill}`, style: `${fgHex(ss.color)}\x1b[1m` },
      ]
    : [
        { text: '● ', style: fgHex(ss.color) },
        { text: 'SYSOP', style: fgHex(pal.muted) },
        { text: ' · ', style: fgHex(pal.dim) },
        { text: ss.pill, style: `${fgHex(ss.color)}\x1b[1m` },
      ];
  if (L.W >= 96) {
    if (showTopSysop) {
      rightSegments.push(...sysopSeg, { text: '  ·  ', style: fgHex(pal.dim) });
    }
    rightSegments.push(
      { text: '◐ ', style: fgHex(pal.accent) },
      { text: themeLabel, style: fgHex(pal.muted) },
    );
    if (L.W >= 112) {
      rightSegments.push(
        { text: '  ·  ', style: fgHex(pal.dim) },
        { text: clock, style: fgHex(pal.dim) },
      );
    }
    rightSegments.push(
      { text: '  ·  ', style: fgHex(pal.dim) },
      { text: '^A?', style: fgHex(pal.accent) },
      { text: ' ', style: '' },
    );
  } else if (L.W >= 68) {
    rightSegments.push(
      ...sysopSeg,
      { text: '  ·  ', style: fgHex(pal.dim) },
      { text: '^A? ', style: fgHex(pal.accent) },
    );
  } else {
    rightSegments.push(...sysopSeg, { text: ' ', style: '' });
  }
  for (const seg of rightSegments) rightW += visibleWidth(seg.text);

  const maxLeft = Math.max(12, L.W - rightW - 1);
  const leftSegments = [
    { text: ' ● ', style: `${fgHex(pal.accentBright)}\x1b[1m` },
    { text: 'SWARMBOX', style: `${fgHex(pal.text)}\x1b[1m` },
    { text: ' · ', style: fgHex(pal.dim) },
    { text: 'herdr', style: fgHex(pal.accent) },
  ];
  let leftW = leftSegments.reduce((a, s) => a + visibleWidth(s.text), 0);

  const crumbBudget = maxLeft - leftW;
  if (crumbBudget > 8) {
    const rawCwd = String((active && active.foreground && active.foreground.cwd) || (active && active.cwd) || '');
    const shortCwd = rawCwd === HOME ? '~' : (rawCwd.startsWith(HOME + '/') ? '~' + rawCwd.slice(HOME.length) : rawCwd);
    const hasRichStatus = active && active.status && typeof active.status === 'object' && active.status.state;
    const suffixText = hasRichStatus
      ? ` · ${sm.label}`
      : (shortCwd && shortCwd !== activeName ? ` · ${clipText(shortCwd, 22)}` : '');
    const suffixStyle = hasRichStatus ? fgHex(sm.color) : fgHex(pal.dim);
    const nameRoom = Math.max(4, crumbBudget - 5 - visibleWidth(suffixText));
    const shownName = clipText(activeName, nameRoom);
    leftSegments.push(
      { text: '  ›  ', style: fgHex(pal.dim) },
      { text: shownName, style: `${fgHex(pal.text)}\x1b[1m` },
    );
    leftW += 5 + visibleWidth(shownName);
    if (suffixText && leftW + visibleWidth(suffixText) <= maxLeft) {
      leftSegments.push({ text: suffixText, style: suffixStyle });
      leftW += visibleWidth(suffixText);
    }
  }

  const gap = Math.max(1, L.W - leftW - rightW);
  const allSegments = [...leftSegments, { text: ' '.repeat(gap), style: '' }, ...rightSegments];

  ctx.hitboxes.push({
    x1: Math.max(0, L.W - rightW),
    x2: Math.max(0, L.W - 1),
    y1: 0,
    y2: 0,
    onClick: () => ctx._toggleSysop(),
  });
  ctx.hitboxes.push({
    x1: 0,
    x2: 18,
    y1: 0,
    y2: 0,
    onClick: () => ctx._toggleSidebar(),
  });
  return buildRow(L.W, bgS, allSegments);
}

export function renderSidebar(ctx, box, pal) {
  const out = [];
  const bgS = bgHex(pal.surface);
  const bgBand = bgHex(pal.band);
  const bgBtn = bgHex(pal.surface2);

  // Header: " TERMINALS" left + count pill right + subtle hairline divider
  const countStr = String(ctx.terminals.length);
  const headLeft = ' TERMINALS';
  const headGap = Math.max(1, box.w - visibleWidth(headLeft) - countStr.length - 1);
  out.push(
    buildRow(box.w, bgS, [
      { text: headLeft, style: `${fgHex(pal.dim)}\x1b[1m` },
      { text: ' '.repeat(headGap), style: '' },
      { text: countStr, style: `${fgHex(pal.accent)}\x1b[1m` },
      { text: ' ', style: '' },
    ]),
  );
  out.push(buildRow(box.w, bgS, [{ text: '─'.repeat(box.w), style: fgHex(pal.border) }]));

  const footerRows = 3; // hairline + [+ New tab] + [Theme]
  const listMax = Math.max(1, box.h - 2 - footerRows);
  const renderedTabRows = [];
  const allowSubRows = listMax >= ctx.terminals.length * 2;

  for (let i = 0; i < ctx.terminals.length && renderedTabRows.length < listMax; i++) {
    const t = ctx.terminals[i];
    const isAct = t.address === ctx.activeAddr;
    const sm = statusMeta(t, pal);
    const { title: tabTitle, pill } = smartTabParts(t);
    const rowY = box.y + 2 + renderedTabRows.length;
    const onSelect = () => ctx._attachTo(t.address).catch(() => {});

    const idxStr = i < 9 ? `${i + 1}` : '·';
    const pct = t.status && t.status.state === 'working' && typeof t.status.progress === 'number'
      ? Math.max(0, Math.min(100, Math.round(t.status.progress)))
      : null;
    const pctStr = pct !== null ? `${pct}% ` : '';
    const pillStr = pill ? ` ${pill}` : '';
    const rowBg = isAct ? bgBand : bgS;
    const rightMetaW = visibleWidth(pillStr) + visibleWidth(pctStr) + visibleWidth(idxStr) + 2;
    const nameBudget = Math.max(3, box.w - 4 - rightMetaW);
    const shown = pill ? clipText(tabTitle, nameBudget) : fitText(tabTitle, nameBudget);
    const padAfterPill = pill ? ' '.repeat(Math.max(0, nameBudget - visibleWidth(shown))) : '';

    ctx.hitboxes.push({ x1: box.x, x2: box.x + box.w - 1, y1: rowY, y2: rowY, onClick: onSelect });
    renderedTabRows.push(
      buildRow(box.w, rowBg, [
        { text: isAct ? '▌' : ' ', style: isAct ? fgHex(pal.accentBright) : '' },
        { text: ' ', style: '' },
        { text: sm.dot, style: fgHex(sm.color) },
        { text: ' ', style: '' },
        { text: shown, style: isAct ? `${fgHex(pal.text)}\x1b[1m` : fgHex(pal.muted) },
        ...(pill ? [{ text: pillStr, style: fgHex(pal.accent) }, { text: padAfterPill, style: '' }] : []),
        { text: ' ', style: '' },
        ...(pctStr ? [{ text: pctStr, style: fgHex(pal.accent) }] : []),
        { text: idxStr, style: isAct ? fgHex(pal.accent) : fgHex(pal.dim) },
        { text: ' ', style: '' },
      ]),
    );

    // Optional rich OSC 7501 sub-row (SwarmBox ▰▱ progress bar or blocked message) when space allows
    if (allowSubRows && renderedTabRows.length < listMax && t.status && typeof t.status === 'object') {
      const subY = box.y + 2 + renderedTabRows.length;
      const cleanMsg = cleanStatusText(t.status.msg);
      if (t.status.state === 'working' && (pct !== null || cleanMsg)) {
        const barLen = 6;
        const filled = pct !== null ? Math.round((pct / 100) * barLen) : 3;
        const barSegs = pct !== null
          ? [
              { text: '▰'.repeat(filled), style: fgHex(pal.accent) },
              { text: '▱'.repeat(barLen - filled), style: fgHex(pal.border) },
              { text: ' ', style: '' },
            ]
          : [];
        const msgBudget = Math.max(4, box.w - 5 - (pct !== null ? barLen + 1 : 0));
        const msgTxt = clipText(cleanMsg || 'working…', msgBudget);
        ctx.hitboxes.push({ x1: box.x, x2: box.x + box.w - 1, y1: subY, y2: subY, onClick: onSelect });
        renderedTabRows.push(
          buildRow(box.w, rowBg, [
            { text: isAct ? '▌' : ' ', style: isAct ? fgHex(pal.accent) : '' },
            { text: '   ', style: '' },
            ...barSegs,
            { text: msgTxt, style: fgHex(pal.dim) },
          ]),
        );
      } else if (t.status.state === 'blocked' && cleanMsg) {
        ctx.hitboxes.push({ x1: box.x, x2: box.x + box.w - 1, y1: subY, y2: subY, onClick: onSelect });
        renderedTabRows.push(
          buildRow(box.w, rowBg, [
            { text: isAct ? '▌' : ' ', style: isAct ? fgHex(pal.amber) : '' },
            { text: '   ↳ ', style: fgHex(pal.amber) },
            { text: clipText(cleanMsg, Math.max(4, box.w - 6)), style: fgHex(pal.amber) },
          ]),
        );
      }
    }
  }

  while (renderedTabRows.length < listMax) renderedTabRows.push(buildRow(box.w, bgS, []));
  out.push(...renderedTabRows);

  const actY = box.y + 2 + listMax;
  out.push(buildRow(box.w, bgS, [{ text: '─'.repeat(box.w), style: fgHex(pal.border) }]));

  const actionRow = (bg, iconCol, leftTxt, hintTxt) => {
    const rightW = visibleWidth(hintTxt) + 1;
    const leftBudget = Math.max(4, box.w - rightW - 1);
    const leftFit = fitText(leftTxt, leftBudget);
    return buildRow(box.w, bg, [
      { text: ' ', style: '' },
      { text: leftFit, style: iconCol },
      { text: hintTxt, style: fgHex(pal.dim) },
      { text: ' ', style: '' },
    ]);
  };

  out.push(actionRow(bgBtn, `${fgHex(pal.accentBright)}\x1b[1m`, '+ New tab', '^Ac'));
  ctx.hitboxes.push({ x1: box.x, x2: box.x + box.w - 1, y1: actY + 1, y2: actY + 1, onClick: () => ctx._createTab('shell') });

  const tLabel = (HERDR_THEMES[ctx.themeName] || HERDR_THEMES[DEFAULT_THEME]).label;
  out.push(actionRow(bgS, fgHex(pal.muted), `◐ ${tLabel}`, '^At'));
  ctx.hitboxes.push({ x1: box.x, x2: box.x + box.w - 1, y1: actY + 2, y2: actY + 2, onClick: () => ctx._cycleTheme() });

  while (out.length < box.h) out.push(buildRow(box.w, bgS, []));
  return out.slice(0, box.h);
}

export function renderFooter(ctx, L, pal) {
  const bgS = bgHex(pal.surface);
  if (ctx.prefixMode) {
    return buildRow(L.W, bgHex(pal.accentDeep), [
      { text: ' ^A PREFIX ', style: `${fgHex(pal.text)}\x1b[1m` },
      { text: ' 1-9 tab · n/p cycle · c shell · C agent · x close · b sidebar · s sysop · g goal · a allow · v veto · t theme · d detach · ? help', style: fgHex(pal.text) },
    ]);
  }
  if (ctx.focus === 'goal') {
    return buildRow(L.W, bgHex(pal.band), [
      { text: ' SYSOP GOAL ', style: `${fgHex(pal.accentBright)}\x1b[1m` },
      { text: ' Enter send · Esc return to terminal · ←/→ edit · Ctrl+U clear', style: fgHex(pal.muted) },
    ]);
  }
  if (ctx.toast) {
    return buildRow(L.W, bgHex(pal.band), [
      {
        text: ` ✦ ${ctx.toast}`,
        style: ctx.toastHref ? `${fgHex(pal.accentBright)}\x1b[4m` : fgHex(pal.accentBright),
        href: ctx.toastHref || undefined,
      },
    ]);
  }
  if (ctx.scrollOffset > 0) {
    return buildRow(L.W, bgHex(pal.band), [
      { text: ` SCROLL +${ctx.scrollOffset} lines · Shift+PgUp/PgDn or wheel · press any key to return live`, style: fgHex(pal.amber) },
    ]);
  }
  const hints = [
    ['^A', ' prefix'],
    ['Alt+1-9', ' tabs'],
    ['Alt+N', ' shell'],
    ['Alt+B', ' sidebar'],
    ['Alt+S', ' sysop'],
    ['Alt+G', ' goal'],
    ['Alt+T', ' theme'],
    ['^A d', ' detach'],
  ];
  const segs = [{ text: ' ', style: '' }];
  let used = 1;
  for (let i = 0; i < hints.length; i++) {
    const [key, desc] = hints[i];
    const sep = i === 0 ? '' : ' · ';
    const needed = visibleWidth(sep) + visibleWidth(key) + visibleWidth(desc);
    if (used + needed > L.W - 1) break;
    if (sep) segs.push({ text: sep, style: fgHex(pal.dim) });
    segs.push({ text: key, style: i === 0 ? fgHex(pal.accent) : fgHex(pal.muted) });
    segs.push({ text: desc, style: fgHex(pal.dim) });
    used += needed;
  }
  return buildRow(L.W, bgS, segs);
}

export function overlayHelp(rows, L, pal) {
  const entries = [
    ['Ctrl+A c / Alt+N', 'New shell tab'],
    ['Ctrl+A C', 'New agent tab'],
    ['Ctrl+A 1..9 / Alt+#', 'Switch tab'],
    ['Ctrl+A n / p', 'Next / previous tab'],
    ['Ctrl+A x', 'Close active tab'],
    ['Ctrl+A b / Alt+B', 'Toggle left sidebar'],
    ['Ctrl+A s / Alt+S', 'Toggle Sysop panel'],
    ['Ctrl+A g / Alt+G', 'Ask Sysop (goal input)'],
    ['Ctrl+A a / v / X', 'Sysop Allow / Veto / Stop'],
    ['Ctrl+A t / Alt+T', 'Cycle 5 synced themes'],
    ['Ctrl+A Ctrl+A', 'Send literal Ctrl+A'],
    ['Ctrl+A d', 'Detach (keeps terminals)'],
    ['Shift+PgUp / PgDn', 'Scroll terminal history'],
  ];
  const boxW = Math.min(L.W - 4, 54);
  const innerW = boxW - 4;
  const boxH = Math.min(L.H - 2, entries.length + 6);
  const top = Math.max(1, Math.floor((L.H - boxH) / 2));
  const left = Math.max(1, Math.floor((L.W - boxW) / 2));
  const right = Math.max(0, L.W - left - boxW);
  const bgOuter = bgHex(pal.bg);
  const bgB = bgHex(pal.surface2);
  const bgHead = bgHex(pal.band);
  const bd = fgHex(pal.accent);

  rows[top] = buildRow(L.W, bgOuter, [
    { text: ' '.repeat(left), style: '' },
    { text: `╭${'─'.repeat(boxW - 2)}╮`, style: `${bgHead}${bd}` },
    { text: ' '.repeat(right), style: '' },
  ]);
  rows[top + 1] = buildRow(L.W, bgOuter, [
    { text: ' '.repeat(left), style: '' },
    { text: '│', style: `${bgHead}${bd}` },
    { text: ` ${fitText('● SWARMBOX Terminal Cockpit · Shortcuts', innerW)} `, style: `${bgHead}${fgHex(pal.accentBright)}\x1b[1m` },
    { text: '│', style: `${bgHead}${bd}` },
    { text: ' '.repeat(right), style: '' },
  ]);
  rows[top + 2] = buildRow(L.W, bgOuter, [
    { text: ' '.repeat(left), style: '' },
    { text: '├', style: `${bgB}${bd}` },
    { text: '─'.repeat(boxW - 2), style: `${bgB}${fgHex(pal.border)}` },
    { text: '┤', style: `${bgB}${bd}` },
    { text: ' '.repeat(right), style: '' },
  ]);
  const keyW = Math.min(21, Math.floor(innerW * 0.45));
  const descW = Math.max(8, innerW - keyW - 1);
  const maxItems = Math.max(1, boxH - 6);
  for (let i = 0; i < maxItems; i++) {
    const pair = entries[i];
    if (!pair) continue;
    rows[top + 3 + i] = buildRow(L.W, bgOuter, [
      { text: ' '.repeat(left), style: '' },
      { text: '│', style: `${bgB}${bd}` },
      { text: ` ${fitText(pair[0], keyW)} `, style: `${bgB}${fgHex(pal.accentBright)}` },
      { text: `${fitText(pair[1], descW)} `, style: `${bgB}${fgHex(pal.text)}` },
      { text: '│', style: `${bgB}${bd}` },
      { text: ' '.repeat(right), style: '' },
    ]);
  }
  rows[top + boxH - 3] = buildRow(L.W, bgOuter, [
    { text: ' '.repeat(left), style: '' },
    { text: '├', style: `${bgB}${bd}` },
    { text: '─'.repeat(boxW - 2), style: `${bgB}${fgHex(pal.border)}` },
    { text: '┤', style: `${bgB}${bd}` },
    { text: ' '.repeat(right), style: '' },
  ]);
  rows[top + boxH - 2] = buildRow(L.W, bgOuter, [
    { text: ' '.repeat(left), style: '' },
    { text: '│', style: `${bgB}${bd}` },
    { text: ` ${fitText('Press any key to close', innerW)} `, style: `${bgB}${fgHex(pal.dim)}` },
    { text: '│', style: `${bgB}${bd}` },
    { text: ' '.repeat(right), style: '' },
  ]);
  rows[top + boxH - 1] = buildRow(L.W, bgOuter, [
    { text: ' '.repeat(left), style: '' },
    { text: `╰${'─'.repeat(boxW - 2)}╯`, style: `${bgB}${bd}` },
    { text: ' '.repeat(right), style: '' },
  ]);
}
