// Shared SwarmBox × herdr-core runtime client, active-tab tracker, and facade
// re-exporting themes, sysop store, box config, and pins/prefs helpers used by
// both server.mjs (Web UI) and cockpit.mjs (Terminal Cockpit).

import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { spawn } from 'node:child_process';
import { EventEmitter } from 'node:events';

// Frame kinds from the herdr-core framed binary JSON-RPC 2.0 protocol
export const FRAME_DATA = 0;
export const FRAME_CREDIT = 1;
export const FRAME_CLOSE = 2;
export const FRAME_RESIZE = 3;
export const FRAME_FOCUS = 4;

export const HOME = process.env.HOME || os.homedir() || '/home/agent';
export const HC_BIN = process.env.SWARMBOX_TEST_HC_BIN || 'hc';
export const SYSOP_BIN = process.env.SWARMBOX_TEST_SYSOP_BIN || 'swarmbox-sysop';
export const SB_RUN_DIR = process.env.SB_RUN_DIR || process.env.SWARMBOX_TEST_RUN_DIR || '/tmp/swarmbox';
export const SB_STATE_DIR = resolveXdg(process.env.XDG_STATE_HOME, path.join(HOME, '.local', 'state'), 'swarmbox');
export const SB_DATA_DIR = resolveXdg(process.env.XDG_DATA_HOME, path.join(HOME, '.local', 'share'), 'swarmbox');
export const SB_CONFIG_DIR = resolveXdg(process.env.XDG_CONFIG_HOME, path.join(HOME, '.config'), 'swarmbox');
export const ADDON_BIN = process.env.SWARMBOX_TEST_ADDON_BIN || 'swarmbox-addon';
export const BUS_BIN = process.env.SWARMBOX_TEST_BUS_BIN || 'swarmbox-bus';
export const WORKTREE_BIN = process.env.SWARMBOX_TEST_WORKTREE_BIN || '';

export const HIDDEN_ROLES = new Set(['sysop']);

export function isAbs(p) {
  return typeof p === 'string' && p.startsWith('/');
}

export function resolveXdg(xdgVar, fallback, sub) {
  const base = isAbs(xdgVar) ? xdgVar.replace(/\/+$/, '') : fallback;
  return path.join(base, sub);
}

export function isHiddenTerminal(term) {
  if (!term || typeof term !== 'object') return false;
  const labels = term.labels;
  if (!labels || typeof labels !== 'object') return false;
  const role = labels['swarmbox.role'];
  return typeof role === 'string' && HIDDEN_ROLES.has(role);
}

export function sanitizeTabName(raw, prefix = 'tab') {
  const clean = String(raw || '')
    .toLowerCase()
    .replace(/[^a-z0-9._-]+/g, '-')
    .replace(/^[^a-z0-9]+/, '')
    .slice(0, 28);
  if (!clean || /^t\d+$/.test(clean)) {
    return `${prefix}-${Math.floor(Math.random() * 900 + 100)}`;
  }
  return clean;
}

export function uniqueTabName(raw, prefix = 'tab', existing = []) {
  const base = sanitizeTabName(raw || prefix, prefix);
  const used = new Set(
    (Array.isArray(existing) ? existing : [])
      .map((t) => String((t && t.name) || '').toLowerCase())
      .filter(Boolean),
  );
  if (!used.has(base)) return base;
  for (let n = 2; n < 1000; n++) {
    const cand = `${base.slice(0, 24)}-${n}`;
    if (!used.has(cand)) return cand;
  }
  return `${prefix}-${Math.floor(Math.random() * 9000 + 1000)}`;
}

// ---------------------------------------------------------------------------
// Active tab tracking (consumed by swarmbox-tabs active and swarmbox-sysop)
// ---------------------------------------------------------------------------
export function writeActiveTab(addr) {
  if (!addr || typeof addr !== 'string') return;
  try {
    fs.mkdirSync(SB_RUN_DIR, { recursive: true });
    fs.writeFileSync(path.join(SB_RUN_DIR, 'herdr-active-tab'), addr + '\n', 'utf8');
  } catch (_) {}
}

export function readActiveTab() {
  try {
    return fs.readFileSync(path.join(SB_RUN_DIR, 'herdr-active-tab'), 'utf8').trim() || null;
  } catch (_) {
    return null;
  }
}

// ---------------------------------------------------------------------------
// Framed JSON-RPC 2.0 client over `hc connect`
// ---------------------------------------------------------------------------
export class HerdrClient extends EventEmitter {
  constructor(hcBin = HC_BIN, options = {}) {
    super();
    this.hcBin = hcBin;
    this.quiet = Boolean(options.quiet);
    this.proc = null;
    this.framed = false;
    this.closing = false;
    this.nextId = 1;
    this.pending = new Map();
    this.channels = new Map();
    this.buf = Buffer.alloc(0);
    this.readyPromise = null;
    this.terminals = new Map();
    this.reconnectDelay = 500;
    this.reconnectTimer = null;
  }

  async start() {
    if (this.readyPromise) return this.readyPromise;
    this.readyPromise = this._connect();
    return this.readyPromise;
  }

  close() {
    this.closing = true;
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    if (this.proc) {
      try { this.proc.kill('SIGTERM'); } catch (_) {}
      this.proc = null;
    }
  }

  _connect() {
    return new Promise((resolve, reject) => {
      const proc = spawn(this.hcBin, ['connect'], {
        stdio: ['pipe', 'pipe', 'pipe'],
        env: process.env,
      });
      this.proc = proc;
      this.framed = false;
      this.buf = Buffer.alloc(0);

      proc.on('error', (err) => {
        this.proc = null;
        this.readyPromise = null;
        reject(err);
      });

      proc.stderr.on('data', (chunk) => {
        if (this.quiet) return;
        const msg = chunk.toString().trim();
        if (msg) console.error('[hc]', msg);
      });

      proc.on('exit', (code, sig) => {
        for (const [, p] of this.pending) p.reject(new Error('hc disconnected'));
        this.pending.clear();
        for (const [, ch] of this.channels) ch.onClose?.({ reason: 'core_disconnected' });
        this.channels.clear();
        this.proc = null;
        this.readyPromise = null;
        if (!this.closing) {
          if (!this.quiet) {
            console.error(`[herdr-client] hc connect exited (code=${code} sig=${sig}); reconnecting in ${this.reconnectDelay}ms`);
          }
          this.reconnectTimer = setTimeout(() => {
            this.reconnectTimer = null;
            this.start().catch((err) => {
              if (!this.quiet) console.error('[herdr-client] reconnect failed:', err.message);
            });
          }, this.reconnectDelay);
          this.reconnectDelay = Math.min(this.reconnectDelay * 1.5, 3000);
        }
      });

      proc.stdout.on('data', (chunk) => this._onStdout(chunk));

      const id = this.nextId++;
      this.pending.set(id, {
        resolve: async (res) => {
          this.framed = true;
          this.reconnectDelay = 500;
          try {
            const sub = await this.call('events.subscribe', {});
            this.terminals.clear();
            for (const t of sub.terminals || []) {
              this.terminals.set(t.address, t);
            }
            if (typeof sub.channel === 'number' && sub.channel > 0) {
              this.channels.set(sub.channel, {
                onData: (payload) => {
                  const raw = payload.toString('utf8');
                  for (const line of raw.split('\n')) {
                    const trimmed = line.trim();
                    if (trimmed) this._handleRpc(trimmed);
                  }
                },
                onClose: () => {},
              });
            }
            this.emit('snapshot', this.listSnapshot());
            resolve(res);
          } catch (err) {
            reject(err);
          }
        },
        reject,
      });

      const hello = JSON.stringify({
        jsonrpc: '2.0',
        id,
        method: 'hello',
        params: { framed: true, generation: 1 },
      }) + '\n';
      proc.stdin.write(hello);
    });
  }

  _onStdout(chunk) {
    this.buf = Buffer.concat([this.buf, chunk]);
    if (!this.framed) {
      const nl = this.buf.indexOf(0x0a);
      if (nl === -1) return;
      const line = this.buf.subarray(0, nl).toString('utf8');
      this.buf = this.buf.subarray(nl + 1);
      this._handleRpc(line);
      if (!this.framed) return;
    }

    while (this.buf.length >= 9) {
      const channel = this.buf.readUInt32LE(0);
      const kind = this.buf.readUInt8(4);
      const len = this.buf.readUInt32LE(5);
      if (this.buf.length < 9 + len) break;
      const payload = this.buf.subarray(9, 9 + len);
      this.buf = this.buf.subarray(9 + len);
      this._handleFrame(channel, kind, payload);
    }
  }

  _handleFrame(channel, kind, payload) {
    if (channel === 0 && kind === FRAME_DATA) {
      this._handleRpc(payload.toString('utf8'));
      return;
    }
    const ch = this.channels.get(channel);
    if (!ch) return;

    if (kind === FRAME_DATA) {
      ch.onData?.(payload);
      if (payload.length > 0) {
        const credit = Buffer.alloc(4);
        credit.writeUInt32LE(payload.length, 0);
        this.sendFrame(channel, FRAME_CREDIT, credit);
      }
    } else if (kind === FRAME_CLOSE) {
      let info = {};
      try {
        if (payload.length) info = JSON.parse(payload.toString('utf8'));
      } catch (_) {}
      this.channels.delete(channel);
      ch.onClose?.(info);
    }
  }

  _handleRpc(text) {
    let msg;
    try {
      msg = JSON.parse(text);
    } catch (_) {
      return;
    }

    if (msg.id !== undefined && this.pending.has(msg.id)) {
      const p = this.pending.get(msg.id);
      this.pending.delete(msg.id);
      if (msg.error) {
        const e = new Error(msg.error.message || 'rpc error');
        e.data = msg.error.data;
        p.reject(e);
      } else {
        p.resolve(msg.result);
      }
      return;
    }

    if (msg.method === 'event' && msg.params) {
      this._applyEvent(msg.params);
      return;
    }
    if (msg.type && (msg.seq !== undefined || msg.terminal !== undefined)) {
      this._applyEvent(msg);
    }
  }

  _applyEvent(ev) {
    const type = ev.type;
    const addr = ev.terminal;
    const data = ev.data;

    if (type === 'created' && data) {
      this.terminals.set(data.address || addr, data);
    } else if (type === 'removed' && addr) {
      this.terminals.delete(addr);
    } else if (type === 'missed') {
      this.call('terminal.list', { all: false })
        .then((res) => {
          this.terminals.clear();
          for (const t of res.terminals || []) this.terminals.set(t.address, t);
          this.emit('snapshot', this.listSnapshot());
        })
        .catch(() => {});
      return;
    } else if (addr) {
      const t = this.terminals.get(addr);
      if (t) {
        if (type === 'status') {
          if (data && typeof data === 'object' && Object.prototype.hasOwnProperty.call(data, 'status')) {
            t.status = data.status;
          } else {
            t.status = data ?? null;
          }
          t.reported = Boolean(t.status);
          t.status_ms = Date.now();
        } else if (type === 'title') {
          t.title = typeof data === 'string' ? data : (data?.title ?? t.title);
        } else if (type === 'turn') {
          t.turn = data?.turn ?? ((t.turn || 0) + 1);
        } else if (type === 'size' && data) {
          if (data.cols) t.cols = data.cols;
          if (data.rows) t.rows = data.rows;
        } else if (type === 'labels' && data) {
          t.labels = data.labels ?? data;
        } else if (type === 'finished') {
          t.state = 'finished';
          t.exit_code = data?.exit_code ?? null;
          t.status = null;
        } else if (type === 'restarted' && data) {
          this.terminals.set(addr, { ...t, ...data, state: 'live' });
        }
      } else {
        this.call('terminal.get', { terminal: addr })
          .then((res) => {
            if (res) {
              this.terminals.set(res.address, res);
              this.emit('snapshot', this.listSnapshot());
            }
          })
          .catch(() => {});
      }
    }

    this.emit('hc-event', { event: ev, terminals: this.listSnapshot() });
  }

  listSnapshot() {
    return Array.from(this.terminals.values())
      .filter((t) => t.state === 'live' && !isHiddenTerminal(t))
      .sort((a, b) => (a.created_ms || 0) - (b.created_ms || 0));
  }

  _snapshotFingerprint(list) {
    return list
      .map((t) => [
        t.address,
        t.name || '',
        t.title || '',
        (t.foreground && t.foreground.name) || '',
        (t.foreground && t.foreground.cwd) || t.cwd || '',
        (t.status && t.status.app) || '',
        (t.status && t.status.state) || '',
        (t.status && t.status.msg) || '',
        (t.status && t.status.progress) ?? '',
        (t.labels && t.labels['swarmbox.title']) || '',
        (t.labels && t.labels['swarmbox.title_source']) || '',
        (t.labels && t.labels['swarmbox.pin_id']) || '',
        (t.labels && t.labels['swarmbox.worktree']) || '',
        (t.labels && t.labels['swarmbox.branch']) || '',
      ].join('\x1f'))
      .join('\x1e');
  }

  refreshTerminals() {
    if (this._refreshing || !this.proc || !this.proc.stdin.writable) return Promise.resolve(false);
    this._refreshing = true;
    const before = this._snapshotFingerprint(this.listSnapshot());
    return this.call('terminal.list', { all: false })
      .then((res) => {
        if (!res || !Array.isArray(res.terminals)) return false;
        this.terminals.clear();
        for (const t of res.terminals) this.terminals.set(t.address, t);
        const list = this.listSnapshot();
        if (this._snapshotFingerprint(list) !== before) {
          this.emit('snapshot', list);
          return true;
        }
        return false;
      })
      .catch(() => false)
      .finally(() => {
        this._refreshing = false;
      });
  }

  sendFrame(channel, kind, payload = Buffer.alloc(0)) {
    if (!this.proc || !this.proc.stdin.writable) return;
    const hdr = Buffer.alloc(9);
    hdr.writeUInt32LE(channel, 0);
    hdr.writeUInt8(kind, 4);
    hdr.writeUInt32LE(payload.length, 5);
    this.proc.stdin.write(Buffer.concat([hdr, payload]));
  }

  call(method, params = {}) {
    return new Promise((resolve, reject) => {
      if (!this.proc || !this.proc.stdin.writable) {
        reject(new Error('herdr-core is not connected'));
        return;
      }
      const id = this.nextId++;
      this.pending.set(id, { resolve, reject });
      const payload = Buffer.from(JSON.stringify({ jsonrpc: '2.0', id, method, params }), 'utf8');
      if (this.framed) {
        this.sendFrame(0, FRAME_DATA, payload);
      } else {
        this.proc.stdin.write(Buffer.concat([payload, Buffer.from('\n')]));
      }
    });
  }

  attach(terminal, cols, rows, handlers, history = 500) {
    return new Promise((resolve, reject) => {
      if (!this.proc || !this.proc.stdin.writable) {
        reject(new Error('herdr-core is not connected'));
        return;
      }
      const id = this.nextId++;
      this.pending.set(id, {
        resolve: (res) => {
          const channel = res.channel;
          // Register synchronously inside _onStdout before the next frame is parsed.
          this.channels.set(channel, handlers);
          resolve({
            channel,
            terminal: res.terminal,
            write: (buf) => this.sendFrame(channel, FRAME_DATA, Buffer.isBuffer(buf) ? buf : Buffer.from(buf)),
            resize: (c, r) => {
              const b = Buffer.alloc(4);
              b.writeUInt16LE(Math.max(20, Math.min(400, Number(c) || 100)), 0);
              b.writeUInt16LE(Math.max(6, Math.min(200, Number(r) || 30)), 2);
              this.sendFrame(channel, FRAME_RESIZE, b);
            },
            focus: (focused) => {
              this.sendFrame(channel, FRAME_FOCUS, Buffer.from([focused ? 1 : 0]));
            },
            close: () => {
              if (this.channels.has(channel)) {
                this.channels.delete(channel);
                this.sendFrame(channel, FRAME_CLOSE);
              }
            },
          });
        },
        reject,
      });

      const payload = Buffer.from(
        JSON.stringify({
          jsonrpc: '2.0',
          id,
          method: 'terminal.attach',
          params: {
            terminal,
            cols: Math.max(20, Math.min(400, Number(cols) || 100)),
            rows: Math.max(6, Math.min(200, Number(rows) || 30)),
            history,
          },
        }),
        'utf8',
      );
      this.sendFrame(0, FRAME_DATA, payload);
    });
  }
}

// ---------------------------------------------------------------------------
// Re-exports from split sibling modules (preserving full 68-export API)
// ---------------------------------------------------------------------------
export {
  DEFAULT_THEME,
  THEME_ORDER,
  HERDR_THEMES,
  THEME_FILE,
  readSavedTheme,
  saveTheme,
} from './themes.mjs';

export {
  compactEvents,
  GoalEventsTail,
  sysopLiveTail,
  readConversationSince,
  startNewConversation,
  readContextState,
  readContextText,
  contextRepoTop,
  readSysopSnapshot,
  runCommand,
  runCommandEnv,
} from './sysop-store.mjs';

export { readBoxConfigSnapshot } from './box-config.mjs';

export {
  PINS_FILE,
  SESSION_PREFS_FILE,
  WORKTREE_PREFS_FILE,
  RECENT_DIRS_FILE,
  normalizeAgentName,
  resolveDefaultAgent,
  cleanSessionTitle,
  defaultTitleForPath,
  terminalCwd,
  detectTerminalAgent,
  detectLiveAgent,
  readRecentDirs,
  noteRecentDir,
  buildAgentArgv,
  readPins,
  writePins,
  makePinId,
  syncPinsFromTerminals,
  buildPinsSnapshot,
  listInstalledAgents,
  readSessionPrefs,
  writeSessionPrefs,
  readWorktreePrefs,
  writeWorktreePrefs,
  runWorktreeCmd,
  publishTabEvent,
} from './pins-store.mjs';
