// Web UI PTY bridge (/ws/pty/:address): viewport ownership, DEC 2026 synchronized output
// coalescing, terminal mode tracking, SIGWINCH resize masking, and direct prompt typing.

import { TERM_DEFAULTS, getAgent } from './agents.mjs';
import { detectTerminalAgent } from './hc-client.mjs';

// Terminal protocol replies & mouse-tracking motion/hover reports that xterm.js emits
// automatically (not user keystrokes) — these must never abort an active resize mask.
const NON_TYPING_INPUT_RE = /^(?:\x1b\[<[0-9;]+[Mm]|\x1b\[M[\s\S]{3}|\x1b\[[IO]|\x1b\[[0-9;]*R|\x1b\[\?[0-9;]*c|\x1b\](?:10|11);[^\x07\x1b]*(?:\x07|\x1b\\))+$/;

// DEC Mode 2026 Synchronized Output markers (\x1b[?2026h begin, \x1b[?2026l end).
// xterm.js 5.5.0 ignores DEC 2026, so TUIs (Antigravity was measured) that clear and redraw inside
// synchronized frames split across multiple PTY chunks would otherwise flash/reflow
// intermediate partial frames. Coalescing at the gateway makes every DEC 2026 frame atomic.
const SYNC_BEGIN_BUF = Buffer.from('\x1b[?2026h');
const SYNC_END_BUF = Buffer.from('\x1b[?2026l');
const CLEAR_SCREEN_BUF = Buffer.from('\x1b[2J');
const CLEAR_SCROLLBACK_BUF = Buffer.from('\x1b[3J');
const MAX_SYNC_FRAME_BYTES = 512 * 1024;
const MAX_SYNC_FRAME_MS = 120;

export function createSyncOutputCoalescer(onEmit, opts = {}) {
  const maxMs = Number(opts.maxMs) || MAX_SYNC_FRAME_MS;
  const maxBytes = Number(opts.maxBytes) || MAX_SYNC_FRAME_BYTES;
  let inSync = false;
  let chunks = [];
  let totalBytes = 0;
  let timer = null;

  const flush = () => {
    if (timer) { clearTimeout(timer); timer = null; }
    inSync = false;
    if (!chunks.length) return;
    const merged = chunks.length === 1 ? chunks[0] : Buffer.concat(chunks, totalBytes);
    chunks = [];
    totalBytes = 0;
    onEmit(merged);
  };

  const push = (rawBuf) => {
    const buf = Buffer.isBuffer(rawBuf) ? rawBuf : Buffer.from(rawBuf);
    if (!buf.length) return;
    const lastBegin = buf.lastIndexOf(SYNC_BEGIN_BUF);
    const lastEnd = buf.lastIndexOf(SYNC_END_BUF);

    if (!inSync) {
      if (lastBegin === -1 || lastEnd > lastBegin) {
        // Complete or non-synchronized chunk: pass straight through with 0ms latency
        onEmit(buf);
        return;
      }
      // Opened a synchronized frame that does not close in this chunk: buffer until \x1b[?2026l
      inSync = true;
      chunks = [buf];
      totalBytes = buf.length;
      timer = setTimeout(flush, maxMs);
      if (timer.unref) timer.unref();
      return;
    }

    chunks.push(buf);
    totalBytes += buf.length;
    const closed = lastEnd !== -1 && lastEnd > lastBegin;
    if (closed || totalBytes >= maxBytes) {
      flush();
    }
  };

  const reset = () => {
    if (timer) { clearTimeout(timer); timer = null; }
    inSync = false;
    chunks = [];
    totalBytes = 0;
  };

  return {
    push,
    flush,
    reset,
    isBuffering: () => inSync,
  };
}

// The modes a program set in its PTY stream, which say it is a full-screen TUI (docs/agents-design.md 3.4): the alternate screen
// (DECSET 47, 1047, 1049) and mouse reporting (9, 1000, 1001, 1002, 1003; 1005/1006/1015 only pick an encoding). A full reset (ESC c)
// clears both. A sequence split across two chunks is completed with the next one. The gateway feeds every chunk of a terminal to
// its tracker, the hydration replay included.
const MODE_SEQ_RE = /\x1b\[\?([0-9;]*)([hl])|\x1bc/g;
const ALT_MODES = new Set([47, 1047, 1049]);
const MOUSE_MODES = new Set([9, 1000, 1001, 1002, 1003]);

export function createTermModeTracker() {
  let alt = false;
  const mouse = new Set();
  let tail = '';
  return {
    push(chunk) {
      const s = tail + (Buffer.isBuffer(chunk) ? chunk.toString('latin1') : String(chunk || ''));
      tail = '';
      MODE_SEQ_RE.lastIndex = 0;
      let m;
      while ((m = MODE_SEQ_RE.exec(s))) {
        if (m[0] === '\x1bc') { alt = false; mouse.clear(); continue; }
        const on = m[2] === 'h';
        for (const p of m[1].split(';')) {
          const n = Number(p);
          if (ALT_MODES.has(n)) alt = on;
          else if (MOUSE_MODES.has(n)) { if (on) mouse.add(n); else mouse.delete(n); }
        }
      }
      // an escape sequence cut at the end of the chunk: keep it for the next one
      const esc = s.lastIndexOf('\x1b');
      if (esc !== -1 && s.length - esc < 32 && /^\x1b(?:\[\??[0-9;]*)?$/.test(s.slice(esc))) tail = s.slice(esc);
    },
    state() {
      return { alt, mouse: mouse.size > 0 };
    },
  };
}

// The timings of a plain terminal (a shell, a command printing lines): short masks, nothing to wait for.
const PLAIN_TIMINGS = Object.freeze({
  resize_quiet_ms: 110, resize_cap_ms: 350, resize_client_fallback_ms: 600, hydrate_flush_ms: 75, hydrate_initial_ms: 110,
  hydrate_cap_ms: 350, settle_ms: 85,
});

// isTuiTerminal(term, modes): a full-screen program by the terminal's own signals: the alternate screen or mouse reporting in its
// stream, or a status it reports with OSC 7501 (the coding agents). Never by its name or a label.
export function isTuiTerminal(term, modes) {
  if (modes && (modes.alt || modes.mouse)) return true;
  const app = term && term.status && term.status.app;
  return typeof app === 'string' && app.trim() !== '';
}

// tuiTimings(term): the core's TUI profile, with the TERM_* keys of the agent the terminal runs (its agent.conf) over it.
export function tuiTimings(term) {
  const id = detectTerminalAgent(term);
  const a = id ? getAgent(id) : null;
  return a ? a.term : TERM_DEFAULTS;
}

const PROMPT_ENTER_GAP_MS = 150;

export function createPtyBridge({ hc, eventClients, writeActiveTab }) {
  // Per-terminal viewport ownership + global last-active client tracking so only the last
  // channel with real user activity (keyboard/pointer/wheel/explicit tab action) sizes the PTY.
  const ptyRooms = new Map();
  let lastActiveClientId = null;

  function hasLiveClientWithId(cid) {
    if (!cid) return false;
    for (const ws of eventClients) {
      if (ws && ws._clientId === cid && ws.readyState === 1) return true;
    }
    for (const room of ptyRooms.values()) {
      for (const c of room.clients) {
        if (c && c.clientId === cid && c.ws && c.ws.readyState === 1) return true;
      }
    }
    return false;
  }

  function clampCols(c) {
    return Math.max(20, Math.min(400, Number(c) || 100));
  }
  function clampRows(r) {
    return Math.max(6, Math.min(200, Number(r) || 30));
  }
  function getPtyRoom(termId) {
    let room = ptyRooms.get(termId);
    if (!room) {
      room = { clients: new Set(), owner: null, ptyCols: 0, ptyRows: 0 };
      ptyRooms.set(termId, room);
    }
    return room;
  }
  function getCurrentPtySize(termId, fallbackCols, fallbackRows) {
    const room = ptyRooms.get(termId);
    if (room && room.owner && room.owner.streamCols > 0 && room.owner.streamRows > 0) {
      return { cols: room.owner.streamCols, rows: room.owner.streamRows };
    }
    if (room && room.ptyCols > 0 && room.ptyRows > 0) {
      return { cols: room.ptyCols, rows: room.ptyRows };
    }
    const t = hc.terminals.get(termId);
    if (t && Number(t.cols) > 0 && Number(t.rows) > 0) {
      return { cols: clampCols(t.cols), rows: clampRows(t.rows) };
    }
    return { cols: clampCols(fallbackCols), rows: clampRows(fallbackRows) };
  }
  // herdr-core sizes a PTY from its attached streams: an attach or a resize frame applies that stream's size,
  // and so does focus(true) (it re-applies the size that stream last sent), and closing a stream applies a
  // remaining one's. So every stream must always have told hc its client's current size, or a later focus(true)
  // re-applies a stale size (a SIGWINCH and a full redraw nobody masked).
  function sendStreamSize(rec) {
    if (!rec.stream) return;
    rec.stream.resize(rec.wantCols, rec.wantRows);
    rec.streamCols = rec.wantCols;
    rec.streamRows = rec.wantRows;
    const room = ptyRooms.get(rec.termId);
    if (room) {
      room.ptyCols = rec.wantCols;
      room.ptyRows = rec.wantRows;
    }
    const t = hc.terminals.get(rec.termId);
    if (t) {
      t.cols = rec.wantCols;
      t.rows = rec.wantRows;
    }
  }
  // A PTY resize redraws the program for EVERY client attached to it, not only the one that asked: mask the
  // redraw on the others too, so a second window or device never paints the reflow without the loader.
  function maskRoomPeers(room, rec) {
    for (const peer of room.clients) {
      if (peer !== rec && typeof peer.onPeerResize === 'function') peer.onPeerResize();
    }
  }
  // The modes each terminal's program set (createTermModeTracker), fed by the attach streams of this gateway.
  const termModes = new Map();
  function modesOf(termId) {
    let tr = termModes.get(termId);
    if (!tr) { tr = createTermModeTracker(); termModes.set(termId, tr); }
    return tr;
  }
  function isTuiTerm(termId) {
    const tr = termModes.get(termId);
    return isTuiTerminal(hc.terminals.get(termId), tr ? tr.state() : null);
  }
  function claimPtyOwnership(room, rec, opts = {}) {
    if (opts.cols && opts.rows) {
      rec.wantCols = clampCols(opts.cols);
      rec.wantRows = clampRows(opts.rows);
    }
    const cur = getCurrentPtySize(rec.termId, room.ptyCols || rec.wantCols, room.ptyRows || rec.wantRows);
    room.owner = rec;
    if (rec.clientId) lastActiveClientId = rec.clientId;
    rec.lastActiveMs = Date.now();
    if (opts.syncSize === false || !rec.stream) return false;
    if (cur.cols !== rec.wantCols || cur.rows !== rec.wantRows) {
      room.ptyCols = rec.wantCols;
      room.ptyRows = rec.wantRows;
      maskRoomPeers(room, rec);
      sendStreamSize(rec);
      return true;
    }
    // The PTY already has this size (another stream set it): still refresh this stream's size in hc,
    // which changes nothing now (same size, no SIGWINCH) but keeps a later focus(true) from going stale.
    if (rec.streamCols !== rec.wantCols || rec.streamRows !== rec.wantRows) sendStreamSize(rec);
    room.ptyCols = cur.cols;
    room.ptyRows = cur.rows;
    return false;
  }

  // A button of the Studio (Ask to commit, Resolve, Commit main, a verify hand-off) types its prompt straight into the
  // agent's PTY through an attach stream, not with hc's terminal.send: that one holds a delivery while a person was
  // active in the terminal (about 3 s after a mouse report, which xterm emits as the pointer crosses the terminal on its
  // way to the button, and up to `draft_wait`, 60 s, with text in the input box). The click is the person, so it must
  // not wait. The text goes first and the Enter as its own write after a pause: text and Enter in one burst reach a TUI
  // as a paste and the Enter becomes a line break (docs/spikes/enter.md: 50 ms was the smallest passing pause, 150 ms chosen).
  async function typePrompt(termId, text) {
    const room = ptyRooms.get(termId);
    const live = room ? [room.owner, ...room.clients].find((c) => c && c.stream) : null;
    let own = null;
    try {
      if (!live) {
        // No browser is on this terminal: attach at its current size (an attach applies its size in herdr-core).
        const size = getCurrentPtySize(termId, 100, 30);
        own = await hc.attach(termId, size.cols, size.rows, {}, 0);
      }
    } catch (_) {
      own = null;
    }
    const stream = live ? live.stream : own;
    if (!stream) {
      // Attach failed: the queued delivery of hc is still better than nothing.
      return hc.call('terminal.send', { terminal: termId, text, force: true });
    }
    try {
      stream.write(Buffer.from(text, 'utf8'));
      await new Promise((r) => setTimeout(r, PROMPT_ENTER_GAP_MS));
      stream.write(Buffer.from('\r'));
    } finally {
      if (own) setTimeout(() => own.close(), 300);
    }
    return { ok: true, typed: true };
  }

  function onSizeEvent(event) {
    if (event && event.type === 'size' && event.terminal && event.data) {
      const room = ptyRooms.get(event.terminal);
      if (room) {
        if (Number(event.data.cols) > 0) room.ptyCols = clampCols(event.data.cols);
        if (Number(event.data.rows) > 0) room.ptyRows = clampRows(event.data.rows);
      }
    }
  }

  async function handlePtyConnection(ws, url) {
    const termId = decodeURIComponent(url.pathname.slice('/ws/pty/'.length));
    const cols = clampCols(url.searchParams.get('cols') || 100);
    const rows = clampRows(url.searchParams.get('rows') || 30);
    const clientId = (url.searchParams.get('clientId') || '').slice(0, 64) || null;
    const isReconnect = url.searchParams.get('reconnect') === '1';
    const isPassiveAttach = isReconnect || url.searchParams.get('focused') === '0';
    const modes = modesOf(termId);
    // TUI-ness is decided by the terminal's signals as they arrive (the replay of the attach carries the modes the program set)
    const tuiNow = () => isTuiTerm(termId);
    const timingsNow = () => (tuiNow() ? tuiTimings(hc.terminals.get(termId)) : PLAIN_TIMINGS);

    const room = getPtyRoom(termId);
    const clientRec = {
      ws,
      clientId,
      termId,
      wantCols: cols,
      wantRows: rows,
      stream: null,
      focused: !isPassiveAttach,
      lastActiveMs: isPassiveAttach ? 0 : Date.now(),
    };
    room.clients.add(clientRec);
    const hasOtherOwner = Boolean(room.owner && room.owner !== clientRec && room.clients.has(room.owner));
    const sameActiveChannel = Boolean(clientId && lastActiveClientId && clientId === lastActiveClientId);
    const otherActiveChannel = Boolean(lastActiveClientId && clientId !== lastActiveClientId && hasLiveClientWithId(lastActiveClientId));
    const claimOnAttach = !isPassiveAttach
      || (isReconnect && sameActiveChannel)
      || (!hasOtherOwner && !otherActiveChannel);
    // The size the PTY has right now. The owner's stream is exact (this gateway set it); hc's cached
    // size can lag a resize by a refresh, and attaching at a stale size would resize the PTY itself.
    const ownerRec = hasOtherOwner ? room.owner : null;
    const ptyNow = ownerRec && ownerRec.streamCols
      ? { cols: ownerRec.streamCols, rows: ownerRec.streamRows }
      : getCurrentPtySize(termId, cols, rows);
    let attachCols = cols;
    let attachRows = rows;
    if (claimOnAttach) {
      room.owner = clientRec;
      if (clientId) lastActiveClientId = clientId;
      room.ptyCols = cols;
      room.ptyRows = rows;
      writeActiveTab(termId);
    } else {
      // A passive attach (a background window, a reconnect) must never change the PTY: join at its current size.
      attachCols = ptyNow.cols;
      attachRows = ptyNow.rows;
    }
    // In herdr-core an attach applies its size: when that changes the PTY, the program redraws for every
    // client. Mask it for the others now, and for this one right after its hydration (the SIGWINCH redraw
    // of a TUI tends to land after the replay that hydration releases).
    const attachResizesPty = clampCols(attachCols) !== ptyNow.cols || clampRows(attachRows) !== ptyNow.rows;
    if (attachResizesPty) maskRoomPeers(room, clientRec);
    if (typeof hc.refreshTerminals === 'function') hc.refreshTerminals();

    let stream = null;
    let hydrating = true;
    const attachStartMs = Date.now();
    let initLastChunkMs = 0;
    let initPostReplayBytes = 0;
    let initSawPostReplay = false;
    let initChunks = [];
    let hydrateCapIsTui = false;
    let flushTimer = null;
    let capTimer = null;
    let resizing = false;
    let resizeSeq = 0;
    let resizeBytes = 0;
    let resizeIsTui = false;
    let resizeTimings = PLAIN_TIMINGS;
    let lastResizeAtMs = 0;
    let lateRedrawCaught = false;
    let resizeChunks = [];
    let resizeQuietTimer = null;
    let resizeCapTimer = null;
    const syncCoalescer = createSyncOutputCoalescer((frame) => {
      if (ws.readyState === 1) ws.send(frame);
    });

    const clearHydrationTimers = () => {
      if (flushTimer) { clearTimeout(flushTimer); flushTimer = null; }
      if (capTimer) { clearTimeout(capTimer); capTimer = null; }
    };

    const clearResizeTimers = () => {
      if (resizeQuietTimer) { clearTimeout(resizeQuietTimer); resizeQuietTimer = null; }
      if (resizeCapTimer) { clearTimeout(resizeCapTimer); resizeCapTimer = null; }
    };

    const startResizeMask = (seqVal, opts = {}) => {
      if (hydrating) return;
      syncCoalescer.flush();
      clearResizeTimers();
      resizing = true;
      if (opts.isLateRedraw) {
        lateRedrawCaught = true;
      } else {
        lastResizeAtMs = Date.now();
        lateRedrawCaught = false;
      }
      resizeSeq = Number(seqVal) || (resizeSeq + 1);
      resizeBytes = 0;
      resizeIsTui = tuiNow();
      resizeTimings = timingsNow();
      // A TUI re-lays out after SIGWINCH and may stream a long history (Antigravity: ~600-850 ms before its clear+redraw burst, up to
      // 2-3 s for the history): the profile's quiet window and cap (an agent may tune them in its agent.conf). A plain terminal
      // is released shortly after its burst.
      resizeQuietTimer = setTimeout(flushResize, resizeTimings.resize_quiet_ms);
      resizeCapTimer = setTimeout(flushResize, resizeTimings.resize_cap_ms);
    };
    // what the page needs to know of this terminal for its own resize fallback (it never guesses TUI-ness by a name)
    const tuiInfo = () => ({ tui: resizeIsTui || tuiNow(), fallback_ms: (resizeIsTui || tuiNow() ? timingsNow() : PLAIN_TIMINGS).resize_client_fallback_ms });

    const flushInitial = () => {
      if (!hydrating) return;
      hydrating = false;
      clearHydrationTimers();
      if (ws.readyState !== 1) {
        initChunks = [];
        return;
      }
      if (initChunks.length > 0) {
        const merged = initChunks.length === 1 ? initChunks[0] : Buffer.concat(initChunks);
        initChunks = [];
        ws.send(merged);
      }
      const isOwner = room.owner === clientRec;
      ws.send(JSON.stringify({
        type: 'hydrated',
        cols: room.ptyCols || clampCols(attachCols),
        rows: room.ptyRows || clampRows(attachRows),
        owner: isOwner,
        ...tuiInfo(),
      }));
      if (attachResizesPty && tuiNow()) {
        startResizeMask(0);
        ws.send(JSON.stringify({ type: 'resizing', seq: resizeSeq, owner: isOwner, ...tuiInfo() }));
      }
    };

    const flushResize = () => {
      if (!resizing) return;
      resizing = false;
      const doneSeq = resizeSeq;
      clearResizeTimers();
      if (ws.readyState !== 1) {
        resizeChunks = [];
        return;
      }
      if (resizeChunks.length > 0) {
        const merged = resizeChunks.length === 1 ? resizeChunks[0] : Buffer.concat(resizeChunks);
        resizeChunks = [];
        ws.send(merged);
      }
      ws.send(JSON.stringify({ type: 'resized', seq: doneSeq, cols: room.ptyCols || clientRec.streamCols || clientRec.wantCols, rows: room.ptyRows || clientRec.streamRows || clientRec.wantRows, owner: room.owner === clientRec }));
    };

    try {
      stream = await hc.attach(termId, attachCols, attachRows, {
        onData: (buf) => {
          modes.push(buf);
          if (hydrating) {
            const now = Date.now();
            initChunks.push(Buffer.from(buf));
            if (tuiNow()) {
              const tm = timingsNow();
              if (!hydrateCapIsTui) {
                // the replay showed a TUI: give the hydration the TUI cap, counted from the attach
                hydrateCapIsTui = true;
                if (capTimer) clearTimeout(capTimer);
                capTimer = setTimeout(flushInitial, Math.max(0, tm.hydrate_cap_ms - (now - attachStartMs)));
              }
              const elapsed = now - attachStartMs;
              const gap = initLastChunkMs > 0 ? now - initLastChunkMs : 0;
              // Distinguish the initial history replay from the post-attach SIGWINCH TUI redraw:
              // require an actual inter-burst pause (not just a large replay taking >65ms) and
              // substantial redraw bytes so a tiny spinner/status tick never ends hydration early.
              if (gap >= tm.hydrate_gap_ms || (elapsed >= 160 && gap >= 40)) {
                initPostReplayBytes += buf.length;
                if (initPostReplayBytes >= tm.hydrate_min_bytes) initSawPostReplay = true;
              }
              initLastChunkMs = now;
              if (flushTimer) clearTimeout(flushTimer);
              flushTimer = setTimeout(flushInitial, initSawPostReplay ? 160 : tm.hydrate_flush_ms);
            } else {
              initLastChunkMs = now;
              if (flushTimer) clearTimeout(flushTimer);
              flushTimer = setTimeout(flushInitial, PLAIN_TIMINGS.hydrate_flush_ms);
            }
            return;
          }
          if (!resizing && !lateRedrawCaught && lastResizeAtMs > 0 && (Date.now() - lastResizeAtMs) <= resizeTimings.late_redraw_ms) {
            // Catch at most ONE late full-screen/scrollback clear+redraw pass from heavy TUIs (e.g. Antigravity
            // re-rendering a long conversation >900ms after SIGWINCH) BEFORE the clear hits xterm.
            // Never reset lastResizeAtMs here so periodic TUI redraws cannot loop the loading mask.
            const hasFullClear = buf.includes(CLEAR_SCROLLBACK_BUF) || buf.includes(CLEAR_SCREEN_BUF);
            if (hasFullClear && (resizeIsTui || tuiNow())) {
              startResizeMask(0, { isLateRedraw: true });
              if (ws.readyState === 1) ws.send(JSON.stringify({ type: 'resizing', seq: resizeSeq, owner: room.owner === clientRec, ...tuiInfo() }));
            }
          }
          if (resizing) {
            resizeChunks.push(Buffer.from(buf));
            resizeBytes += buf.length;
            if (resizeQuietTimer) clearTimeout(resizeQuietTimer);
            // If the TUI opened a DEC 2026 synchronized frame that has not closed yet,
            // give it extra breathing room before declaring the redraw settled.
            const lb = buf.lastIndexOf(SYNC_BEGIN_BUF);
            const le = buf.lastIndexOf(SYNC_END_BUF);
            const openSync = lb !== -1 && lb > le;
            const quietMs = openSync
              ? 420
              : ((resizeIsTui && resizeBytes < 512) ? resizeTimings.settle_ms : (resizeIsTui ? 320 : PLAIN_TIMINGS.settle_ms));
            resizeQuietTimer = setTimeout(flushResize, quietMs);
            return;
          }
          syncCoalescer.push(Buffer.from(buf));
        },
        onClose: (info) => {
          flushInitial();
          flushResize();
          syncCoalescer.flush();
          if (ws.readyState === 1) {
            ws.send(JSON.stringify({ type: 'closed', info }));
            ws.close();
          }
        },
      });
      clientRec.stream = stream;
      clientRec.streamCols = clampCols(attachCols);
      clientRec.streamRows = clampRows(attachRows);
      clientRec.onPeerResize = () => {
        if (hydrating || ws.readyState !== 1) return;
        startResizeMask(0);
        ws.send(JSON.stringify({ type: 'resizing', seq: resizeSeq, owner: false, ...tuiInfo() }));
      };
    } catch (err) {
      clearHydrationTimers();
      clearResizeTimers();
      room.clients.delete(clientRec);
      if (room.owner === clientRec) room.owner = null;
      if (room.clients.size === 0) ptyRooms.delete(termId);
      if (ws.readyState === 1) {
        ws.send(JSON.stringify({ type: 'error', message: err.message }));
        ws.close();
      }
      return;
    }

    // Coalesce initial replay + post-attach TUI SIGWINCH redraw into one atomic hydrated frame.
    if (hydrating) {
      const tui0 = tuiNow();
      hydrateCapIsTui = tui0;
      const tm0 = tui0 ? timingsNow() : PLAIN_TIMINGS;
      if (!flushTimer) flushTimer = setTimeout(flushInitial, tui0 ? tm0.hydrate_flush_ms : PLAIN_TIMINGS.hydrate_initial_ms);
      if (!capTimer) capTimer = setTimeout(flushInitial, tm0.hydrate_cap_ms);
    }

    ws.on('message', (data, isBinary) => {
      if (!stream) return;
      if (isBinary) {
        const buf = Buffer.from(data);
        if (!NON_TYPING_INPUT_RE.test(buf.toString('utf8'))) {
          if (room.owner !== clientRec) {
            claimPtyOwnership(room, clientRec);
            writeActiveTab(termId);
            stream.focus(true);
          } else {
            claimPtyOwnership(room, clientRec);
          }
        }
        stream.write(buf);
        return;
      }
      const text = data.toString('utf8');
      if (text.startsWith('{')) {
        try {
          const msg = JSON.parse(text);
          if (msg.type === 'resize') {
            clientRec.wantCols = clampCols(msg.cols);
            clientRec.wantRows = clampRows(msg.rows);
            const canResize = !room.owner || room.owner === clientRec || Boolean(msg.claim);
            if (!canResize) {
              if (ws.readyState === 1) {
                ws.send(JSON.stringify({
                  type: 'resized',
                  seq: Number(msg.seq) || 0,
                  cols: room.ptyCols || clientRec.streamCols || clientRec.wantCols,
                  rows: room.ptyRows || clientRec.streamRows || clientRec.wantRows,
                  owner: false,
                }));
              }
              return;
            }
            const before = getCurrentPtySize(termId, room.ptyCols || clientRec.wantCols, room.ptyRows || clientRec.wantRows);
            room.owner = clientRec;
            if (clientId) lastActiveClientId = clientId;
            room.ptyCols = clientRec.wantCols;
            room.ptyRows = clientRec.wantRows;
            clientRec.lastActiveMs = Date.now();
            const sizeChanged = before.cols !== clientRec.wantCols || before.rows !== clientRec.wantRows;
            if (!sizeChanged) {
              if (clientRec.streamCols !== clientRec.wantCols || clientRec.streamRows !== clientRec.wantRows) {
                sendStreamSize(clientRec);
              }
              if (!hydrating && !resizing && ws.readyState === 1) {
                ws.send(JSON.stringify({
                  type: 'resized',
                  seq: Number(msg.seq) || 0,
                  cols: room.ptyCols,
                  rows: room.ptyRows,
                  owner: true,
                }));
              }
              return;
            }
            // Coalesce SIGWINCH full-screen TUI repaint bursts into one atomic frame
            // (covering debounced & multi-pass TUIs such as OpenCode, Claude, AGY, and Gemini).
            startResizeMask(msg.seq);
            maskRoomPeers(room, clientRec);
            sendStreamSize(clientRec);
            return;
          }
          if (msg.type === 'focus') {
            if (msg.cols && msg.rows) {
              clientRec.wantCols = clampCols(msg.cols);
              clientRec.wantRows = clampRows(msg.rows);
            }
            if (msg.focused) {
              const wasOwner = room.owner === clientRec;
              const wasFocused = Boolean(clientRec.focused);
              const shouldClaim = Boolean(msg.claim) || !room.owner || wasOwner;
              if (shouldClaim) {
                const cur = getCurrentPtySize(termId, room.ptyCols || clientRec.wantCols, room.ptyRows || clientRec.wantRows);
                const willResize = cur.cols !== clientRec.wantCols || cur.rows !== clientRec.wantRows;
                if (willResize && !hydrating) {
                  startResizeMask(0);
                  if (ws.readyState === 1) ws.send(JSON.stringify({ type: 'resizing', seq: resizeSeq, owner: true, ...tuiInfo() }));
                }
                claimPtyOwnership(room, clientRec, { cols: msg.cols, rows: msg.rows });
                clientRec.focused = true;
                if (!wasOwner || !wasFocused) {
                  writeActiveTab(termId);
                  stream.focus(true);
                }
                if (!willResize && !hydrating && !resizing && ws.readyState === 1) {
                  ws.send(JSON.stringify({
                    type: 'resized',
                    seq: 0,
                    cols: room.ptyCols || clientRec.wantCols,
                    rows: room.ptyRows || clientRec.wantRows,
                    owner: true,
                  }));
                }
              }
            } else {
              clientRec.focused = false;
              stream.focus(false);
            }
            return;
          }
          if (msg.type === 'input' && typeof msg.data === 'string') {
            const isRealInput = !NON_TYPING_INPUT_RE.test(msg.data);
            if (isRealInput) {
              if (resizing) flushResize();
              const wasOwner = room.owner === clientRec;
              claimPtyOwnership(room, clientRec);
              if (!wasOwner) {
                writeActiveTab(termId);
                stream.focus(true);
              }
            }
            stream.write(Buffer.from(msg.data, 'utf8'));
            return;
          }
        } catch (_) {}
      }
      if (resizing) flushResize();
      if (!NON_TYPING_INPUT_RE.test(text)) {
        const wasOwner = room.owner === clientRec;
        claimPtyOwnership(room, clientRec);
        if (!wasOwner) {
          writeActiveTab(termId);
          stream.focus(true);
        }
      }
      stream.write(Buffer.from(text, 'utf8'));
    });

    ws.on('close', () => {
      clearHydrationTimers();
      clearResizeTimers();
      syncCoalescer.reset();
      initChunks = [];
      resizeChunks = [];
      hydrating = false;
      resizing = false;
      room.clients.delete(clientRec);
      if (room.owner === clientRec) room.owner = null;
      if (room.clients.size === 0) ptyRooms.delete(termId);
      // Closing this stream makes herdr-core apply a remaining stream's size: when that differs, the
      // program redraws for the clients still attached, so mask it for them.
      else if ([...room.clients].some((c) => c.streamCols && (c.streamCols !== clientRec.streamCols || c.streamRows !== clientRec.streamRows))) {
        maskRoomPeers(room, clientRec);
      }
      clientRec.onPeerResize = null;
      clientRec.stream = null;
      if (stream) {
        stream.close();
        stream = null;
      }
    });
  }

  return {
    typePrompt,
    onSizeEvent,
    handlePtyConnection,
  };
}
