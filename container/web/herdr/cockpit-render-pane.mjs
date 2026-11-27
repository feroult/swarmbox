// Pane & compositor renderers for the SwarmBox Terminal Cockpit:
// center @xterm/headless viewport, right Sysop panel + Goal Composer,
// and synchronized 24-bit frame composition with row diffing.

import {
  ESC,
  RESET,
  SYNC_END,
  SYNC_START,
  bgHex,
  buildRow,
  charDisplayWidth,
  fgHex,
  fitText,
  sysopStyle,
  visibleWidth,
  wrapText,
} from './cockpit-ansi.mjs';

export function buildFrame(ctx) {
  const L = ctx.layout();
  const pal = ctx.palette();
  ctx.hitboxes = [];
  ctx.goalCursorPos = null;
  const rows = new Array(L.H);

  rows[0] = ctx._renderTopBar(L, pal);

  const sidebarLines = L.sidebar ? ctx._renderSidebar(L.sidebar, pal) : null;
  const paneLines = ctx._renderTerminalPane(L.pane, pal);
  const sysopLines = L.sysop ? ctx._renderSysopPanel(L.sysop, pal) : null;
  const divLeft = `${bgHex(pal.bg)}${fgHex(pal.border)}│${RESET}`;
  const divRight = `${bgHex(pal.bg)}${fgHex(ctx.focus === 'goal' ? pal.borderStrong : pal.border)}│${RESET}`;

  for (let i = 0; i < L.bodyH; i++) {
    let line = '';
    if (sidebarLines) line += sidebarLines[i] + divLeft;
    line += paneLines[i];
    if (sysopLines) line += divRight + sysopLines[i];
    rows[L.bodyY + i] = line + RESET;
  }

  rows[L.footerY] = ctx._renderFooter(L, pal);

  if (ctx.helpOpen) {
    ctx._overlayHelp(rows, L, pal);
  }

  return { L, rows };
}

export function renderFrame(ctx) {
  const { L, rows } = ctx.buildFrame();

  let out = SYNC_START + `${ESC}[?25l`;
  for (let r = 0; r < L.H; r++) {
    if (ctx.prevRows[r] !== rows[r]) {
      out += `${ESC}[${r + 1};1H${rows[r]}`;
      ctx.prevRows[r] = rows[r];
    }
  }

  // Position real 1-indexed terminal cursor accurately
  if (!ctx.helpOpen) {
    if (ctx.focus === 'goal' && ctx.goalCursorPos) {
      out += `${ESC}[${ctx.goalCursorPos.y + 1};${ctx.goalCursorPos.x + 1}H${ESC}[?25h`;
    } else if (ctx.xterm && ctx.scrollOffset === 0) {
      const b = ctx.xterm.buffer.active;
      const cx = Math.min(L.pane.innerW - 1, Math.max(0, b.cursorX));
      const cy = Math.min(L.pane.h - 1, Math.max(0, b.cursorY));
      out += `${ESC}[${L.pane.y + cy + 1};${L.pane.x + L.pane.pad + cx + 1}H${ESC}[?25h`;
    }
  }

  out += SYNC_END;
  ctx.stdout.write(out);
}

export function cellSgr(cell, pal) {
  let fg = '';
  let bg = '';
  const ansi16 = pal.ansi16;
  if (cell.isFgDefault()) {
    fg = fgHex(pal.termFg);
  } else if (cell.isFgRGB()) {
    const c = cell.getFgColor();
    fg = `\x1b[38;2;${(c >> 16) & 255};${(c >> 8) & 255};${c & 255}m`;
  } else {
    const idx = cell.getFgColor();
    fg = ansi16 && idx >= 0 && idx < 16 ? fgHex(ansi16[idx]) : `\x1b[38;5;${idx}m`;
  }

  if (cell.isBgDefault()) {
    bg = bgHex(pal.bg);
  } else if (cell.isBgRGB()) {
    const c = cell.getBgColor();
    bg = `\x1b[48;2;${(c >> 16) & 255};${(c >> 8) & 255};${c & 255}m`;
  } else {
    const idx = cell.getBgColor();
    bg = ansi16 && idx >= 0 && idx < 16 ? bgHex(ansi16[idx]) : `\x1b[48;5;${idx}m`;
  }

  let attr = '\x1b[0m';
  if (cell.isBold()) attr += '\x1b[1m';
  if (cell.isDim()) attr += '\x1b[2m';
  if (cell.isItalic()) attr += '\x1b[3m';
  if (cell.isUnderline()) attr += '\x1b[4m';
  if (cell.isInverse()) attr += '\x1b[7m';
  return attr + fg + bg;
}

export function renderTerminalPane(ctx, box, pal) {
  const bgDefault = bgHex(pal.bg);
  const fgDefault = fgHex(pal.termFg);
  const padStr = box.pad > 0 ? `${bgDefault}${' '.repeat(box.pad)}` : '';
  const emptyRow = `${bgDefault}${fgDefault}${' '.repeat(box.w)}${RESET}`;

  if (!ctx.xterm) {
    const lines = new Array(box.h).fill(emptyRow);
    if (box.h > 2) {
      lines[Math.floor(box.h / 2)] = buildRow(box.w, bgDefault, [
        { text: '  Connecting to herdr-core…', style: fgHex(pal.dim) },
      ]);
    }
    return lines;
  }

  const buf = ctx.xterm.buffer.active;
  const baseRow = Math.max(0, buf.viewportY - ctx.scrollOffset);
  const cell = buf.getNullCell();
  const out = [];

  for (let y = 0; y < box.h; y++) {
    const line = buf.getLine(baseRow + y);
    if (!line) {
      out.push(emptyRow);
      continue;
    }

    let rowStr = padStr;
    let lastStyle = '';
    let col = 0;

    while (col < box.innerW) {
      line.getCell(col, cell);
      const w = cell.getWidth();
      if (w === 0) {
        col += 1;
        continue;
      }
      let ch = cell.getChars();
      if (!ch || cell.isInvisible()) ch = ' ';
      if (ch.length === 1 && ch.charCodeAt(0) < 0x20) ch = ' ';

      const style = ctx._cellSgr(cell, pal);
      if (style !== lastStyle) {
        rowStr += style;
        lastStyle = style;
      }
      if (w === 2 && col + 1 >= box.innerW) {
        rowStr += ' ';
        col += 1;
      } else {
        rowStr += ch;
        col += w;
      }
    }
    if (box.pad > 0) rowStr += padStr;
    out.push(rowStr + RESET);
  }
  return out;
}

export function renderSysopPanel(ctx, box, pal) {
  const bgS = bgHex(pal.surface);
  const bg2 = bgHex(pal.surface2);
  const bgBand = bgHex(pal.band);
  const ss = sysopStyle(ctx.sysop.state, pal);
  const out = [];

  // Header row + subtle hairline divider (matching left sidebar & Web UI)
  const headLeft = ' ● SYSOP';
  const headRight = `${ss.pill} `;
  const hGap = Math.max(1, box.w - visibleWidth(headLeft) - visibleWidth(headRight));
  out.push(
    buildRow(box.w, bgS, [
      { text: headLeft, style: `${fgHex(ss.color)}\x1b[1m` },
      { text: ' '.repeat(hGap), style: '' },
      { text: headRight, style: `${fgHex(ss.color)}\x1b[1m` },
    ]),
  );
  out.push(buildRow(box.w, bgS, [{ text: '─'.repeat(box.w), style: fgHex(pal.border) }]));

  // 3-row framed Goal Composer pinned cleanly at bottom of Sysop panel
  const composerRows = 3;
  const feedArea = Math.max(1, box.h - 2 - composerRows);
  const body = [];

  const makeDecisionButtonsRow = (denyLabel) => {
    const allowLbl = box.w >= 28 ? ' Allow ^Aa ' : ' Allow ';
    const vetoLbl = box.w >= 28 ? ` ${denyLabel} ^Av ` : ` ${denyLabel} `;
    const rowStr = buildRow(box.w, bgBand, [
      { text: '▌', style: fgHex(pal.amber) },
      { text: ' ', style: '' },
      { text: allowLbl, style: `${bgHex(pal.accentDeep)}${fgHex(pal.text)}\x1b[1m` },
      { text: ' ', style: '' },
      { text: vetoLbl, style: `${bgHex(pal.surface2)}${fgHex(pal.red)}` },
    ]);
    const allowStart = 2;
    const allowEnd = allowStart + visibleWidth(allowLbl) - 1;
    const vetoStart = allowEnd + 2;
    const vetoEnd = vetoStart + visibleWidth(vetoLbl) - 1;
    return {
      raw: rowStr,
      onHit: (rowY) => {
        ctx.hitboxes.push({ x1: box.x + allowStart, x2: box.x + allowEnd, y1: rowY, y2: rowY, onClick: () => ctx._sysopAction('approve') });
        ctx.hitboxes.push({ x1: box.x + vetoStart, x2: box.x + vetoEnd, y1: rowY, y2: rowY, onClick: () => ctx._sysopAction('veto') });
      },
    };
  };

  if (ctx.sysop.pending) {
    const p = ctx.sysop.pending;
    const secs = typeof p.deadline === 'number' ? Math.max(0, Math.ceil(p.deadline - Date.now() / 1000)) : null;
    const tabObj = p.tab ? ctx.terminals.find((t) => t.address === p.tab) : null;
    const tabTag = tabObj ? (tabObj.name || p.tab) : (p.tab || '');
    const title = p.mode === 'veto' ? `SENDING${secs !== null ? ` · ${secs}s` : ''}` : `ALLOW?${secs !== null ? ` · ${secs}s` : ''}`;
    const rightTag = tabTag ? `${tabTag} ` : '';
    const tGap = Math.max(1, box.w - 3 - visibleWidth(title) - visibleWidth(rightTag));
    body.push({
      raw: buildRow(box.w, bgBand, [
        { text: '▌ ', style: fgHex(pal.amber) },
        { text: '◆ ', style: fgHex(pal.amber) },
        { text: title, style: `${fgHex(pal.amber)}\x1b[1m` },
        { text: ' '.repeat(Math.max(1, tGap - 1)), style: '' },
        { text: rightTag, style: fgHex(pal.muted) },
      ]),
    });
    for (const ln of wrapText(p.text || 'pending action', box.w - 4, 3)) {
      body.push({
        raw: buildRow(box.w, bgBand, [
          { text: '▌ ', style: fgHex(pal.amber) },
          { text: ln, style: fgHex(pal.text) },
        ]),
      });
    }
    if (secs !== null) {
      const barW = Math.max(8, Math.min(24, box.w - 4));
      const ratio = Math.max(0, Math.min(1, secs / Math.max(secs, 30)));
      const fill = Math.max(1, Math.round(ratio * barW));
      body.push({
        raw: buildRow(box.w, bgBand, [
          { text: '▌ ', style: fgHex(pal.amber) },
          { text: '▰'.repeat(fill), style: fgHex(pal.amber) },
          { text: '▱'.repeat(barW - fill), style: fgHex(pal.border) },
        ]),
      });
    }
    body.push(makeDecisionButtonsRow('Veto'));
    body.push({ raw: buildRow(box.w, bgS, [{ text: '─'.repeat(box.w), style: fgHex(pal.border) }]) });
    body.push({ raw: buildRow(box.w, bgS, []) });
  } else if (ctx.sysop.blocked.length > 0) {
    const b = ctx.sysop.blocked[0];
    body.push({
      raw: buildRow(box.w, bgBand, [
        { text: '▌ ', style: fgHex(pal.amber) },
        { text: `◆ BLOCKED · ${b.name}`, style: `${fgHex(pal.amber)}\x1b[1m` },
      ]),
    });
    for (const ln of wrapText(b.msg, box.w - 4, 2)) {
      body.push({
        raw: buildRow(box.w, bgBand, [
          { text: '▌ ', style: fgHex(pal.amber) },
          { text: ln, style: fgHex(pal.text) },
        ]),
      });
    }
    body.push(makeDecisionButtonsRow('Deny'));
    body.push({ raw: buildRow(box.w, bgS, [{ text: '─'.repeat(box.w), style: fgHex(pal.border) }]) });
    body.push({ raw: buildRow(box.w, bgS, []) });
  }

  // Activity feed
  const stepLines = [];
  if (!ctx.sysop.up) {
    stepLines.push({ raw: buildRow(box.w, bgS, [{ text: ' Sysop service is offline.', style: fgHex(pal.dim) }]) });
    stepLines.push({ raw: buildRow(box.w, bgS, [{ text: ' Install with:', style: fgHex(pal.dim) }]) });
    stepLines.push({ raw: buildRow(box.w, bgS, [{ text: ' swarmbox addon install sysop', style: fgHex(pal.muted) }]) });
  } else if (ctx.sysop.steps.length === 0) {
    stepLines.push({ raw: buildRow(box.w, bgS, [{ text: ' Ready for goals.', style: fgHex(pal.muted) }]) });
    for (const ln of wrapText('Press ^A g or Alt+G to ask Sysop to work on the active tab or route to your agent.', box.w - 2, 4)) {
      stepLines.push({ raw: buildRow(box.w, bgS, [{ text: ` ${ln}`, style: fgHex(pal.dim) }]) });
    }
  } else {
    for (const st of ctx.sysop.steps) {
      const icon = st.kind === 'goal' ? '❯' : st.kind === 'ok' ? '✓' : st.kind === 'err' ? '!' : '·';
      const col = st.kind === 'goal' ? pal.accentBright : st.kind === 'ok' ? pal.green : st.kind === 'err' ? pal.red : pal.muted;
      const wrapped = wrapText(st.text, box.w - 4, 3);
      wrapped.forEach((ln, idx) => {
        stepLines.push({
          raw: buildRow(box.w, bgS, [
            { text: ` ${idx === 0 ? icon : ' '} `, style: fgHex(col) },
            { text: ln, style: `${fgHex(col)}${st.kind === 'goal' && idx === 0 ? '\x1b[1m' : ''}` },
          ]),
        });
      });
    }
  }

  const availFeed = Math.max(0, feedArea - body.length);
  const leadingSpacer = body.length === 0 && stepLines.length > 0 && availFeed > stepLines.length
    ? [{ raw: buildRow(box.w, bgS, []) }]
    : [];
  const combined = [...body, ...leadingSpacer, ...stepLines.slice(-Math.max(0, availFeed - leadingSpacer.length))];

  for (let i = 0; i < feedArea; i++) {
    const item = combined[i];
    const rowY = box.y + 2 + i;
    if (!item) {
      out.push(buildRow(box.w, bgS, []));
    } else {
      out.push(item.raw);
      if (item.onHit) item.onHit(rowY);
    }
  }

  // Framed 3-row Goal Composer (outer │ keeps panel bgS so rounded corners are razor-clean!)
  const isGoal = ctx.focus === 'goal';
  const borderCol = isGoal ? pal.accentBright : pal.border;
  const innerBg = isGoal ? bgBand : bg2;
  const frameW = Math.max(10, box.w - 2); // 1-col margin left + right
  const innerW = frameW - 2;              // inside │ ... │
  const composerTopY = box.y + 2 + feedArea;

  // Top border: " ╭─ Goal ────────╮ "
  const topLabel = isGoal ? '─ Goal ' : '─ Ask Sysop ';
  const topFill = Math.max(0, innerW - visibleWidth(topLabel));
  out.push(
    buildRow(box.w, bgS, [
      { text: ' ', style: '' },
      { text: '╭', style: fgHex(borderCol) },
      { text: topLabel, style: isGoal ? `${fgHex(pal.accentBright)}\x1b[1m` : fgHex(pal.dim) },
      { text: '─'.repeat(topFill), style: fgHex(borderCol) },
      { text: '╮', style: fgHex(borderCol) },
      { text: ' ', style: '' },
    ]),
  );

  // Input row: " │ ❯ <draft> │ " (symmetric 1-col left & right inner padding)
  const textAreaW = Math.max(3, innerW - 4); // ' ❯ '(3) + textAreaW + ' '(1)
  const draftChars = Array.from(ctx.goalDraft);
  const curIdx = Math.max(0, Math.min(draftChars.length, ctx.goalCursor));

  let shownDraft = '';
  let cursorOffsetCols = 0;
  if (!isGoal && draftChars.length === 0) {
    shownDraft = fitText('Type a goal…', textAreaW);
  } else {
    // Scroll window around cursor so typing never clips past right border
    let start = 0;
    let widthToCursor = 0;
    for (let k = 0; k < curIdx; k++) widthToCursor += charDisplayWidth(draftChars[k]);
    while (widthToCursor > Math.max(0, textAreaW - 1) && start < curIdx) {
      widthToCursor -= charDisplayWidth(draftChars[start]);
      start += 1;
    }
    let slice = '';
    let sw = 0;
    for (let k = start; k < draftChars.length; k++) {
      const cw = charDisplayWidth(draftChars[k]);
      if (sw + cw > textAreaW) break;
      slice += draftChars[k];
      sw += cw;
    }
    shownDraft = fitText(slice, textAreaW);
    cursorOffsetCols = widthToCursor;
  }

  out.push(
    buildRow(box.w, bgS, [
      { text: ' ', style: '' },
      { text: '│', style: fgHex(borderCol) },
      { text: ' ❯ ', style: `${innerBg}${isGoal ? fgHex(pal.accentBright) : fgHex(pal.dim)}` },
      { text: shownDraft, style: `${innerBg}${isGoal ? fgHex(pal.text) : fgHex(pal.dim)}` },
      { text: ' ', style: innerBg },
      { text: '│', style: fgHex(borderCol) },
      { text: ' ', style: '' },
    ]),
  );

  if (isGoal) {
    ctx.goalCursorPos = {
      x: box.x + 1 + 1 + 3 + Math.min(textAreaW - 1, cursorOffsetCols),
      y: composerTopY + 1,
    };
  }

  // Bottom border: " ╰─ Enter · Esc ─╯ "
  const botLabel = isGoal ? '─ ↵ send · Esc ' : '─ ^A g · Alt+G ';
  const botFill = Math.max(0, innerW - visibleWidth(botLabel));
  out.push(
    buildRow(box.w, bgS, [
      { text: ' ', style: '' },
      { text: '╰', style: fgHex(borderCol) },
      { text: botLabel, style: fgHex(pal.dim) },
      { text: '─'.repeat(botFill), style: fgHex(borderCol) },
      { text: '╯', style: fgHex(borderCol) },
      { text: ' ', style: '' },
    ]),
  );

  ctx.hitboxes.push({
    x1: box.x,
    x2: box.x + box.w - 1,
    y1: composerTopY,
    y2: composerTopY + 2,
    onClick: () => ctx._focusGoal(),
  });

  return out.slice(0, box.h);
}
