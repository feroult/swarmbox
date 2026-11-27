// Session lifecycle, herdr-core attachment, tab/theme/sysop actions, and open-url bridge
// for the SwarmBox Terminal Cockpit.

import fs from 'node:fs';
import path from 'node:path';
import xtermHeadless from '@xterm/headless';
import {
  HERDR_THEMES,
  HOME,
  THEME_ORDER,
  buildAgentArgv,
  readSavedTheme,
  readSysopSnapshot,
  resolveDefaultAgent,
  runCommand,
  saveTheme,
  uniqueTabName,
  writeActiveTab,
} from './hc-client.mjs';
import { ESC, RESET } from './cockpit-ansi.mjs';

const HeadlessTerminal = xtermHeadless.Terminal || xtermHeadless.default?.Terminal;

export function getRunDir() {
  return process.env.SWARMBOX_TEST_RUN_DIR || '/tmp/swarmbox';
}

export function readOpenUrlEvent(ctx) {
  try {
    const raw = fs.readFileSync(path.join(ctx._runDir(), 'open-url.json'), 'utf8');
    const data = JSON.parse(raw);
    if (!data || typeof data.id !== 'string' || typeof data.url !== 'string') return null;
    if (!/^https?:\/\/[^\x00-\x1f\x7f\s]+$/i.test(data.url)) return null;
    return data;
  } catch (_) {
    return null;
  }
}

export function pollOpenUrl(ctx) {
  const ev = ctx._readOpenUrlEvent();
  if (!ev || ev.id === ctx.lastOpenUrlId) return false;
  ctx.lastOpenUrlId = ev.id;
  try {
    const b64 = Buffer.from(ev.url, 'utf8').toString('base64');
    ctx.stdout.write(`\x1b]52;c;${b64}\x07`);
  } catch (_) {}
  let label = ev.url;
  try {
    const u = new URL(ev.url);
    label = u.host + (u.pathname && u.pathname !== '/' ? u.pathname : '');
  } catch (_) {}
  ctx.setToast(`Open ${label} (copied · Cmd/Ctrl+click)`, 12000, ev.url);
  return true;
}

export async function startCockpit(ctx) {
  ctx.hc.on('snapshot', (list) => ctx._onTerminals(list));
  ctx.hc.on('hc-event', ({ terminals }) => ctx._onTerminals(terminals));

  await ctx.hc.start();

  if (ctx.stdin.isTTY && typeof ctx.stdin.setRawMode === 'function') {
    ctx.stdin.setRawMode(true);
  }
  ctx.stdin.resume();
  ctx.stdin.on('data', ctx._onDataBound);
  ctx.stdout.on('resize', ctx._onResizeBound);

  // Enter alternate screen, enable SGR mouse tracking, hide cursor until first paint
  ctx.stdout.write(`${ESC}[?1049h${ESC}[?1000h${ESC}[?1006h${ESC}[?25l${ESC}[2J`);

  ctx.terminals = ctx.hc.listSnapshot();
  await ctx._ensureActiveAttached();

  // Register live cockpit marker for swarmbox-open and seed current open-url id
  try {
    const rdir = ctx._runDir();
    fs.mkdirSync(rdir, { recursive: true });
    ctx._markerPath = path.join(rdir, `cockpit.${process.pid}`);
    fs.writeFileSync(ctx._markerPath, `${process.pid}\n`);
  } catch (_) {
    ctx._markerPath = '';
  }
  const existingOpen = ctx._readOpenUrlEvent();
  if (existingOpen) ctx.lastOpenUrlId = existingOpen.id;

  // Poll real swarmbox-sysop state + shared theme file (stays synced with Web UI)
  let pollTick = 0;
  let lastClockMin = new Date().getMinutes();
  ctx.pollTimer = setInterval(() => {
    if (ctx.closed) return;
    const diskTheme = readSavedTheme();
    let dirty = false;
    if (diskTheme !== ctx.themeName) {
      ctx.themeName = diskTheme;
      ctx.prevRows = [];
      dirty = true;
    }
    const curMin = new Date().getMinutes();
    if (curMin !== lastClockMin) {
      lastClockMin = curMin;
      dirty = true;
    }
    pollTick = (pollTick + 1) % 5;
    if (pollTick === 0 && typeof ctx.hc.refreshTerminals === 'function') {
      ctx.hc.refreshTerminals();
    }
    const nextSysop = readSysopSnapshot(ctx.terminals);
    const prevKey = JSON.stringify({
      up: ctx.sysop.up,
      state: ctx.sysop.state,
      sentence: ctx.sysop.sentence,
      pending: ctx.sysop.pending,
      stepsLen: ctx.sysop.steps.length,
      lastStep: ctx.sysop.steps[ctx.sysop.steps.length - 1]?.text,
      blocked: ctx.sysop.blocked,
    });
    const nextKey = JSON.stringify({
      up: nextSysop.up,
      state: nextSysop.state,
      sentence: nextSysop.sentence,
      pending: nextSysop.pending,
      stepsLen: nextSysop.steps.length,
      lastStep: nextSysop.steps[nextSysop.steps.length - 1]?.text,
      blocked: nextSysop.blocked,
    });
    if (prevKey !== nextKey || Boolean(nextSysop.pending?.deadline)) {
      ctx.sysop = nextSysop;
      dirty = true;
    }
    if (ctx._pollOpenUrl()) dirty = true;
    if (dirty) ctx.scheduleRender();
  }, 500);
  if (ctx.pollTimer.unref) ctx.pollTimer.unref();

  ctx.scheduleRender(true);
}

export function shutdownCockpit(ctx, code = 0) {
  if (ctx.closed) return;
  ctx.closed = true;
  if (ctx.pollTimer) clearInterval(ctx.pollTimer);
  if (ctx.prefixTimer) clearTimeout(ctx.prefixTimer);
  if (ctx.toastTimer) clearTimeout(ctx.toastTimer);
  if (ctx._markerPath) {
    try { fs.unlinkSync(ctx._markerPath); } catch (_) {}
    ctx._markerPath = '';
  }
  ctx.stdin.off('data', ctx._onDataBound);
  ctx.stdout.off('resize', ctx._onResizeBound);
  if (ctx.stream) {
    try { ctx.stream.close(); } catch (_) {}
    ctx.stream = null;
  }
  if (ctx.xterm) {
    try { ctx.xterm.dispose(); } catch (_) {}
    ctx.xterm = null;
  }
  ctx.hc.close();
  if (ctx.stdin.isTTY && typeof ctx.stdin.setRawMode === 'function') {
    try { ctx.stdin.setRawMode(false); } catch (_) {}
  }
  try {
    ctx.stdout.write(`${ESC}[?1006l${ESC}[?1000l${ESC}[?25h${RESET}${ESC}[?1049l`);
  } catch (_) {}
  if (code !== null) process.exit(code);
}

export function syncPaneSize(ctx) {
  const L = ctx.layout();
  const c = L.pane.innerW;
  const r = L.pane.h;
  if (ctx.xterm && (ctx.xtermCols !== c || ctx.xtermRows !== r)) {
    ctx.xtermCols = c;
    ctx.xtermRows = r;
    try { ctx.xterm.resize(c, r); } catch (_) {}
    if (ctx.stream) {
      try { ctx.stream.resize(c, r); } catch (_) {}
    }
  }
}

export function onTerminals(ctx, list) {
  ctx.terminals = Array.isArray(list) ? list : [];
  ctx.sysop = readSysopSnapshot(ctx.terminals);
  const hasActive = ctx.terminals.some((t) => t.address === ctx.activeAddr);
  if (!hasActive) {
    ctx.activeAddr = ctx.terminals[0]?.address || null;
    ctx._ensureActiveAttached().catch(() => {});
  } else if (ctx.attachedAddr !== ctx.activeAddr) {
    ctx._ensureActiveAttached().catch(() => {});
  }
  ctx.scheduleRender();
}

export async function ensureActiveAttached(ctx) {
  if (ctx.closed) return;
  if (ctx.terminals.length === 0) {
    try {
      const created = await ctx.hc.call('terminal.run', {
        argv: ['/bin/bash', '-l'],
        name: uniqueTabName('shell', 'shell', ctx.terminals),
        cwd: HOME,
        keep: true,
        no_parent: true,
      });
      const addr = created?.terminal?.address || created?.address;
      if (addr) {
        ctx.activeAddr = addr;
        ctx.terminals = ctx.hc.listSnapshot();
      }
    } catch (err) {
      ctx.setToast(`Failed to open shell: ${err.message}`);
      return;
    }
  }
  if (!ctx.activeAddr || !ctx.terminals.some((t) => t.address === ctx.activeAddr)) {
    ctx.activeAddr = ctx.terminals[0]?.address || null;
  }
  if (!ctx.activeAddr || ctx.attachedAddr === ctx.activeAddr) return;
  await ctx._attachTo(ctx.activeAddr);
}

export async function attachTo(ctx, addr) {
  if (ctx.closed || !addr) return;
  if (ctx.stream) {
    try { ctx.stream.close(); } catch (_) {}
    ctx.stream = null;
  }
  if (ctx.xterm) {
    try { ctx.xterm.dispose(); } catch (_) {}
    ctx.xterm = null;
  }
  ctx.attachedAddr = addr;
  ctx.activeAddr = addr;
  ctx.scrollOffset = 0;
  writeActiveTab(addr);

  const L = ctx.layout();
  ctx.xtermCols = L.pane.innerW;
  ctx.xtermRows = L.pane.h;
  const term = new HeadlessTerminal({
    cols: ctx.xtermCols,
    rows: ctx.xtermRows,
    scrollback: 2000,
    allowProposedApi: true,
  });
  ctx.xterm = term;
  ctx.prevRows = [];

  try {
    const stream = await ctx.hc.attach(
      addr,
      ctx.xtermCols,
      ctx.xtermRows,
      {
        onData: (buf) => {
          if (ctx.xterm !== term || ctx.closed) return;
          term.write(buf, () => ctx.scheduleRender());
        },
        onClose: () => {
          if (ctx.attachedAddr === addr) {
            ctx.attachedAddr = null;
            ctx.stream = null;
            ctx.scheduleRender();
          }
        },
      },
      400,
    );
    if (ctx.attachedAddr !== addr || ctx.closed) {
      stream.close();
      return;
    }
    ctx.stream = stream;
    stream.focus(true);
    ctx.scheduleRender(true);
  } catch (err) {
    ctx.setToast(`Attach error: ${err.message}`);
  }
}

export async function createTab(ctx, preset) {
  const cwd = HOME;
  let argv = ['/bin/bash', '-l'];
  let prefix = 'shell';
  if (preset === 'agent') {
    const cmd = resolveDefaultAgent() || 'yolo';
    argv = buildAgentArgv(cmd, 'fresh');
    prefix = cmd === 'yolo' ? 'agent' : cmd;
  }
  try {
    const created = await ctx.hc.call('terminal.run', {
      argv,
      name: uniqueTabName(prefix, prefix, ctx.terminals),
      cwd,
      keep: true,
      no_parent: true,
    });
    const addr = created?.terminal?.address || created?.address;
    if (addr) {
      ctx.setToast(`Opened ${(created.terminal && created.terminal.name) || created.name || preset}`);
      await ctx._attachTo(addr);
    }
  } catch (err) {
    ctx.setToast(`New tab failed: ${err.message}`);
  }
}

export async function closeActiveTab(ctx) {
  if (ctx.terminals.length <= 1) {
    ctx.setToast('Last tab — use Ctrl+A d to detach');
    return;
  }
  const target = ctx.activeAddr;
  if (!target) return;
  try {
    await ctx.hc.call('terminal.kill', { terminal: target });
    ctx.hc.call('terminal.rm', { terminal: target }).catch(() => {});
    ctx.setToast(`Closed ${target}`);
  } catch (err) {
    ctx.setToast(`Close failed: ${err.message}`);
  }
}

export function switchIndex(ctx, idx) {
  if (idx < 0 || idx >= ctx.terminals.length) return;
  const t = ctx.terminals[idx];
  if (t && t.address !== ctx.activeAddr) {
    ctx._attachTo(t.address).catch(() => {});
  }
}

export function cycleTab(ctx, delta) {
  if (ctx.terminals.length <= 1) return;
  const cur = Math.max(0, ctx.terminals.findIndex((t) => t.address === ctx.activeAddr));
  const next = (cur + delta + ctx.terminals.length) % ctx.terminals.length;
  ctx._switchIndex(next);
}

export function cycleTheme(ctx) {
  const i = THEME_ORDER.indexOf(ctx.themeName);
  const next = THEME_ORDER[(i + 1) % THEME_ORDER.length];
  ctx.themeName = next;
  saveTheme(next);
  ctx.prevRows = [];
  ctx.setToast(`Theme: ${HERDR_THEMES[next].label}`);
}

export function toggleSidebar(ctx) {
  const cur = ctx.layout().sidebar !== null;
  ctx.sidebarPref = !cur;
  ctx.layoutPriority = 'sidebar';
  ctx.prevRows = [];
  ctx._syncPaneSize();
  ctx.scheduleRender(true);
}

export function toggleSysop(ctx) {
  const cur = ctx.layout().sysop !== null;
  ctx.sysopPref = !cur;
  ctx.layoutPriority = 'sysop';
  if (!ctx.sysopPref && ctx.focus === 'goal') ctx.focus = 'terminal';
  ctx.prevRows = [];
  ctx._syncPaneSize();
  ctx.scheduleRender(true);
}

export function focusGoal(ctx) {
  ctx.sysopPref = true;
  ctx.layoutPriority = 'sysop';
  ctx.focus = 'goal';
  ctx.goalCursor = Array.from(ctx.goalDraft).length;
  ctx.prevRows = [];
  ctx._syncPaneSize();
  ctx.scheduleRender(true);
}

export async function submitGoal(ctx) {
  const goal = ctx.goalDraft.trim();
  ctx.goalDraft = '';
  ctx.goalCursor = 0;
  ctx.focus = 'terminal';
  ctx.scheduleRender();
  if (!goal) return;
  if (ctx.activeAddr) writeActiveTab(ctx.activeAddr);
  ctx.setToast('Sending goal to Sysop…');
  const r = await runCommand(ctx.sysopBin, ['goal', '--source', 'cockpit', '--', '-'], goal + '\n');
  if (r.ok) {
    ctx.setToast(`Goal queued (${r.stdout || 'ok'})`);
  } else {
    ctx.setToast(`Sysop error: ${(r.stderr || r.stdout || 'failed').slice(0, 60)}`);
  }
  ctx.sysop = readSysopSnapshot(ctx.terminals);
  ctx.scheduleRender();
}

export async function sysopAction(ctx, action) {
  if (action === 'approve' && !ctx.sysop.pending && ctx.sysop.blocked.length > 0) {
    const b = ctx.sysop.blocked[0];
    await ctx.hc.call('terminal.send', { terminal: b.terminal, text: 'y', force: true }).catch(() => {});
    ctx.setToast(`Allowed ${b.name}`);
    return;
  }
  if (action === 'veto' && !ctx.sysop.pending && ctx.sysop.blocked.length > 0) {
    const b = ctx.sysop.blocked[0];
    await ctx.hc.call('terminal.send', { terminal: b.terminal, text: 'n', force: true }).catch(() => {});
    ctx.setToast(`Denied ${b.name}`);
    return;
  }
  const r = await runCommand(ctx.sysopBin, [action]);
  ctx.setToast(r.ok ? `Sysop: ${r.stdout || action}` : `Sysop: ${(r.stderr || r.stdout || 'nothing waiting').slice(0, 56)}`);
  ctx.sysop = readSysopSnapshot(ctx.terminals);
  ctx.scheduleRender();
}
