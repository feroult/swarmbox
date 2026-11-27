// Input handling for the SwarmBox Terminal Cockpit:
// Ctrl+A prefix, Alt shortcuts, Goal editor, SGR 1006 mouse & wheel, and PTY forwarding.

export const SGR_MOUSE_RE = /^\x1b\[<(\d+);(\d+);(\d+)([Mm])/;

// The wheel (two fingers on a trackpad). A program that asked for the mouse, or that runs on the alternate screen (Claude Code in
// fullscreen, vim, less), has no history in this buffer and handles scrolling itself: give it the wheel, as a mouse event when it
// asked for the mouse, as arrow keys otherwise (what a terminal does). Anything else scrolls the history kept here.
// dir: 1 = up, -1 = down.
export function handleWheel(ctx, dir, btn, x, y) {
  const term = ctx.xterm;
  if (term && ctx.stream && ctx.focus === 'terminal') {
    const mouse = term.modes && term.modes.mouseTrackingMode && term.modes.mouseTrackingMode !== 'none';
    const alt = term.buffer.active.type === 'alternate';
    if (mouse || alt) {
      const P = ctx.layout().pane;
      const px = x - (P.x + P.pad);
      const py = y - P.y;
      if (px < 0 || py < 0 || px >= P.innerW || py >= P.h) return; // over the sidebar or the Sysop panel: not for the program
      if (mouse) {
        const core = term._core && term._core.coreMouseService;
        const enc = core && core.activeEncoding;
        if (enc && enc !== 'SGR') {
          // an old program without SGR (1006): the classic X10 encoding, one byte per value, offset 32
          if (px + 33 > 255 || py + 33 > 255) return;
          ctx.stream.write(Buffer.from([0x1b, 0x5b, 0x4d, 32 + btn, 33 + px, 33 + py]));
        } else {
          ctx.stream.write(`\x1b[<${btn};${px + 1};${py + 1}M`);
        }
      } else {
        const app = term.modes && term.modes.applicationCursorKeysMode;
        const key = `\x1b${app ? 'O' : '['}${dir > 0 ? 'A' : 'B'}`;
        ctx.stream.write(key.repeat(3));
      }
      return;
    }
  }
  ctx._scroll(dir * 3);
}

export function scrollBuffer(ctx, delta) {
  if (!ctx.xterm) return;
  const maxScroll = ctx.xterm.buffer.active.baseY;
  ctx.scrollOffset = Math.max(0, Math.min(maxScroll, ctx.scrollOffset + delta));
  ctx.scheduleRender();
}

export function handleStdin(ctx, chunk) {
  if (ctx.closed) return;
  let buf = Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk);

  while (buf.length > 0) {
    const str = buf.toString('utf8');
    const m = str.match(SGR_MOUSE_RE);
    if (m) {
      const consumed = Buffer.byteLength(m[0], 'utf8');
      ctx._handleMouse(Number(m[1]), Number(m[2]) - 1, Number(m[3]) - 1, m[4] === 'M');
      buf = buf.subarray(consumed);
      continue;
    }

    if (ctx.helpOpen) {
      ctx.helpOpen = false;
      ctx.prevRows = [];
      ctx.scheduleRender(true);
      return;
    }

    if (ctx.focus === 'goal') {
      ctx._handleGoalKey(buf);
      return;
    }

    if (ctx.prefixMode) {
      ctx._clearPrefix();
      const byte = buf[0];
      const rest = buf.subarray(1);
      ctx._handlePrefixKey(byte);
      buf = rest;
      continue;
    }

    if (str.startsWith('\x1b[5;2~')) {
      ctx._scroll(Math.max(3, Math.floor(ctx.layout().pane.h / 2)));
      buf = buf.subarray(6);
      continue;
    }
    if (str.startsWith('\x1b[6;2~')) {
      ctx._scroll(-Math.max(3, Math.floor(ctx.layout().pane.h / 2)));
      buf = buf.subarray(6);
      continue;
    }

    if (buf.length === 2 && buf[0] === 0x1b) {
      const ch = String.fromCharCode(buf[1]);
      if (ctx._handleAltKey(ch)) return;
    }

    if (buf[0] === 0x01) {
      ctx._enterPrefix();
      buf = buf.subarray(1);
      continue;
    }

    if (ctx.scrollOffset > 0) {
      ctx.scrollOffset = 0;
      ctx.scheduleRender();
    }
    if (ctx.stream) {
      ctx.stream.write(buf);
    }
    return;
  }
}

export function enterPrefix(ctx) {
  ctx.prefixMode = true;
  if (ctx.prefixTimer) clearTimeout(ctx.prefixTimer);
  ctx.prefixTimer = setTimeout(() => {
    ctx.prefixMode = false;
    ctx.prefixTimer = null;
    ctx.scheduleRender();
  }, 3000);
  if (ctx.prefixTimer.unref) ctx.prefixTimer.unref();
  ctx.scheduleRender();
}

export function clearPrefix(ctx) {
  ctx.prefixMode = false;
  if (ctx.prefixTimer) {
    clearTimeout(ctx.prefixTimer);
    ctx.prefixTimer = null;
  }
}

export function handlePrefixKey(ctx, byte) {
  if (byte === 0x01) {
    if (ctx.stream) ctx.stream.write(Buffer.from([0x01]));
    ctx.scheduleRender();
    return;
  }
  if (byte === 0x1b) {
    ctx.scheduleRender();
    return;
  }
  const ch = String.fromCharCode(byte);
  if (ch >= '1' && ch <= '9') {
    ctx._switchIndex(Number(ch) - 1);
  } else if (ch === 'n') {
    ctx._cycleTab(1);
  } else if (ch === 'p') {
    ctx._cycleTab(-1);
  } else if (ch === 'c') {
    ctx._createTab('shell');
  } else if (ch === 'C') {
    ctx._createTab('agent');
  } else if (ch === 'x') {
    ctx._closeActiveTab();
  } else if (ch === 'b') {
    ctx._toggleSidebar();
  } else if (ch === 's') {
    ctx._toggleSysop();
  } else if (ch === 'g') {
    ctx._focusGoal();
  } else if (ch === 'a') {
    ctx._sysopAction('approve');
  } else if (ch === 'v') {
    ctx._sysopAction('veto');
  } else if (ch === 'X') {
    ctx._sysopAction('stop');
  } else if (ch === 't') {
    ctx._cycleTheme();
  } else if (ch === 'd' || ch === 'q') {
    ctx.shutdown(0);
  } else if (ch === '?') {
    ctx.helpOpen = true;
    ctx.prevRows = [];
    ctx.scheduleRender(true);
  } else {
    ctx.scheduleRender();
  }
}

export function handleAltKey(ctx, ch) {
  if (ch >= '1' && ch <= '9') {
    ctx._switchIndex(Number(ch) - 1);
    return true;
  }
  const low = ch.toLowerCase();
  if (low === 'n') { ctx._createTab('shell'); return true; }
  if (low === 'b') { ctx._toggleSidebar(); return true; }
  if (low === 's') { ctx._toggleSysop(); return true; }
  if (low === 'g') { ctx._focusGoal(); return true; }
  if (low === 't') { ctx._cycleTheme(); return true; }
  return false;
}

export function handleGoalKey(ctx, buf) {
  const s = buf.toString('utf8');
  const chars = Array.from(ctx.goalDraft);
  ctx.goalCursor = Math.max(0, Math.min(chars.length, ctx.goalCursor));

  if (s === '\x1b' || s === '\x03') {
    ctx.focus = 'terminal';
    ctx.scheduleRender();
    return;
  }
  if (s === '\r' || s === '\n') {
    ctx._submitGoal();
    return;
  }
  if (s === '\x1b[D') { // Left arrow
    if (ctx.goalCursor > 0) ctx.goalCursor -= 1;
    ctx.scheduleRender();
    return;
  }
  if (s === '\x1b[C') { // Right arrow
    if (ctx.goalCursor < chars.length) ctx.goalCursor += 1;
    ctx.scheduleRender();
    return;
  }
  if (s === '\x1b[H' || s === '\x01') { // Home / Ctrl+A
    ctx.goalCursor = 0;
    ctx.scheduleRender();
    return;
  }
  if (s === '\x1b[F' || s === '\x05') { // End / Ctrl+E
    ctx.goalCursor = chars.length;
    ctx.scheduleRender();
    return;
  }
  if (s === '\x7f' || s === '\x08') { // Backspace
    if (ctx.goalCursor > 0) {
      chars.splice(ctx.goalCursor - 1, 1);
      ctx.goalDraft = chars.join('');
      ctx.goalCursor -= 1;
      ctx.scheduleRender();
    }
    return;
  }
  if (s === '\x1b[3~') { // Delete
    if (ctx.goalCursor < chars.length) {
      chars.splice(ctx.goalCursor, 1);
      ctx.goalDraft = chars.join('');
      ctx.scheduleRender();
    }
    return;
  }
  if (s === '\x15') { // Ctrl+U
    ctx.goalDraft = '';
    ctx.goalCursor = 0;
    ctx.scheduleRender();
    return;
  }
  const printable = s.replace(/\x1b\[[0-9;?]*[ -/]*[@-~]/g, '').replace(/[\x00-\x1f\x7f]/g, '');
  if (printable) {
    const ins = Array.from(printable);
    chars.splice(ctx.goalCursor, 0, ...ins);
    ctx.goalDraft = chars.join('');
    ctx.goalCursor += ins.length;
    ctx.scheduleRender();
  }
}

export function handleMouse(ctx, btn, x, y, press) {
  if (!press) return;
  if ((btn & 64) && !(btn & 32) && (btn & 3) < 2) { ctx._wheel((btn & 3) === 0 ? 1 : -1, btn, x, y); return; }
  if (btn !== 0) return;

  for (const hb of ctx.hitboxes) {
    if (y >= hb.y1 && y <= hb.y2 && x >= hb.x1 && x <= hb.x2) {
      hb.onClick();
      return;
    }
  }

  const L = ctx.layout();
  if (x >= L.pane.x && x < L.pane.x + L.pane.w && y >= L.pane.y && y < L.pane.y + L.pane.h) {
    if (ctx.focus !== 'terminal') {
      ctx.focus = 'terminal';
      ctx.scheduleRender();
    }
  }
}
