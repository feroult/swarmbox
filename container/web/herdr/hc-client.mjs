// Shared SwarmBox × herdr-core runtime client, theme registry, active-tab tracker,
// and real swarmbox-sysop state/command bridge used by both server.mjs (Web UI)
// and cockpit.mjs (Terminal Cockpit).

import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import crypto from 'node:crypto';
import { fileURLToPath } from 'node:url';
import { spawn, execFileSync } from 'node:child_process';
import { EventEmitter } from 'node:events';
import {
  buildAgentArgv as registryBuildAgentArgv,
  defaultAgent,
  detectAgent,
  listAgents,
  resolveAgent,
} from './agents.mjs';

const __clientDir = path.dirname(fileURLToPath(import.meta.url));

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
export const PINS_FILE = path.join(SB_CONFIG_DIR, 'pins.json');
export const SESSION_PREFS_FILE = path.join(SB_CONFIG_DIR, 'session-prefs.json');
export const WORKTREE_PREFS_FILE = path.join(SB_CONFIG_DIR, 'worktree-prefs.json');

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
// Theme registry (synchronized between Web UI and Terminal Cockpit)
// ---------------------------------------------------------------------------
export const DEFAULT_THEME = 'catppuccin';
export const THEME_ORDER = ['catppuccin', 'purple-glow', 'tokyo-night', 'nord', 'rose-pine'];

export const HERDR_THEMES = {
  'purple-glow': {
    label: 'Purple Glow',
    cockpit: {
      bg: '#0c0b10',
      surface: '#12101a',
      surface2: '#1b1726',
      band: '#27222f',
      border: '#352b4a',
      borderStrong: '#6d28d9',
      text: '#f4f4f5',
      muted: '#a1a1aa',
      dim: '#71717a',
      accent: '#a78bfa',
      accentBright: '#c4b5fd',
      accentDeep: '#6d28d9',
      green: '#4ade80',
      amber: '#fbbf24',
      red: '#ff6b78',
      termFg: '#d4d4d8',
      ansi16: [
        '#1c1a24', '#e5484d', '#3dba7a', '#d9a441', '#8b5cf6', '#d946ef', '#5eb5c9', '#d4d4d8',
        '#71717a', '#ff6b78', '#4ade80', '#fbbf24', '#a78bfa', '#e879f9', '#8ad7e6', '#fafafa',
      ],
    },
  },
  catppuccin: {
    label: 'Catppuccin',
    cockpit: {
      bg: '#11111b',
      surface: '#181825',
      surface2: '#1e1e2e',
      band: '#29293e',
      border: '#313244',
      borderStrong: '#8839ef',
      text: '#cdd6f4',
      muted: '#a6adc8',
      dim: '#6c7086',
      accent: '#cba6f7',
      accentBright: '#f5c2e7',
      accentDeep: '#8839ef',
      green: '#a6e3a1',
      amber: '#f9e2af',
      red: '#f38ba8',
      termFg: '#cdd6f4',
      ansi16: [
        '#45475a', '#f38ba8', '#a6e3a1', '#f9e2af', '#89b4fa', '#f5c2e7', '#94e2d5', '#bac2de',
        '#585b70', '#f38ba8', '#a6e3a1', '#f9e2af', '#89b4fa', '#f5c2e7', '#94e2d5', '#cdd6f4',
      ],
    },
  },
  'tokyo-night': {
    label: 'Tokyo Night',
    cockpit: {
      bg: '#16161e',
      surface: '#1a1b26',
      surface2: '#24283b',
      band: '#282d42',
      border: '#2f3549',
      borderStrong: '#3d59a1',
      text: '#c0caf5',
      muted: '#9aa5ce',
      dim: '#565f89',
      accent: '#7aa2f7',
      accentBright: '#bb9af7',
      accentDeep: '#3d59a1',
      green: '#9ece6a',
      amber: '#e0af68',
      red: '#f7768e',
      termFg: '#c0caf5',
      ansi16: [
        '#15161e', '#f7768e', '#9ece6a', '#e0af68', '#7aa2f7', '#bb9af7', '#7dcfff', '#a9b1d6',
        '#414868', '#f7768e', '#9ece6a', '#e0af68', '#7aa2f7', '#bb9af7', '#7dcfff', '#c0caf5',
      ],
    },
  },
  nord: {
    label: 'Nord',
    cockpit: {
      bg: '#242933',
      surface: '#2e3440',
      surface2: '#3b4252',
      band: '#3e4759',
      border: '#434c5e',
      borderStrong: '#5e81ac',
      text: '#eceff4',
      muted: '#d8dee9',
      dim: '#8190a8',
      accent: '#88c0d0',
      accentBright: '#8fbcbb',
      accentDeep: '#5e81ac',
      green: '#a3be8c',
      amber: '#ebcb8b',
      red: '#bf616a',
      termFg: '#eceff4',
      ansi16: [
        '#3b4252', '#bf616a', '#a3be8c', '#ebcb8b', '#81a1c1', '#b48ead', '#88c0d0', '#e5e9f0',
        '#4c566a', '#bf616a', '#a3be8c', '#ebcb8b', '#81a1c1', '#b48ead', '#8fbcbb', '#eceff4',
      ],
    },
  },
  'rose-pine': {
    label: 'Rosé Pine',
    cockpit: {
      bg: '#191724',
      surface: '#1f1d2e',
      surface2: '#26233a',
      band: '#2e2a45',
      border: '#403d52',
      borderStrong: '#907aa9',
      text: '#e0def4',
      muted: '#908caa',
      dim: '#6e6a86',
      accent: '#c4a7e7',
      accentBright: '#ebbcba',
      accentDeep: '#907aa9',
      green: '#9ccfd8',
      amber: '#f6c177',
      red: '#eb6f92',
      termFg: '#e0def4',
      ansi16: [
        '#26233a', '#eb6f92', '#31748f', '#f6c177', '#9ccfd8', '#c4a7e7', '#ebbcba', '#e0def4',
        '#6e6a86', '#eb6f92', '#31748f', '#f6c177', '#9ccfd8', '#c4a7e7', '#ebbcba', '#e0def4',
      ],
    },
  },
};

export const THEME_FILE = path.join(SB_CONFIG_DIR, 'herdr-web-theme');

export function readSavedTheme() {
  try {
    const t = fs.readFileSync(THEME_FILE, 'utf8').trim();
    if (HERDR_THEMES[t]) return t;
  } catch (_) {}
  return DEFAULT_THEME;
}

export function saveTheme(themeName) {
  if (!HERDR_THEMES[themeName]) return false;
  try {
    fs.mkdirSync(SB_CONFIG_DIR, { recursive: true });
    fs.writeFileSync(THEME_FILE, themeName + '\n', 'utf8');
  } catch (_) {}
  return true;
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
// Real swarmbox-sysop state reader & command bridge (zero mocks)
// ---------------------------------------------------------------------------
const TERMINAL_STATES = new Set(['done', 'stopped', 'failed']);
const SYSOP_SHOW_END_MS = 10000;
const FN_KEY = 'too' + 'l'; // matches sysop calls.jsonl schema key

function readJsonSafe(filePath) {
  try {
    return JSON.parse(fs.readFileSync(filePath, 'utf8'));
  } catch (_) {
    return null;
  }
}

function readJsonlSafe(filePath, limit = 40) {
  try {
    const lines = fs.readFileSync(filePath, 'utf8').split('\n').filter(Boolean);
    const slice = lines.slice(-limit);
    const out = [];
    for (const ln of slice) {
      try {
        const obj = JSON.parse(ln);
        if (obj && typeof obj === 'object') out.push(obj);
      } catch (_) {}
    }
    return out;
  } catch (_) {
    return [];
  }
}

function isPidAlive(pid) {
  if (!Number.isInteger(pid) || pid <= 0) return false;
  try {
    process.kill(pid, 0);
    return true;
  } catch (_) {
    return false;
  }
}

function sanitizeGoalId(id) {
  if (typeof id !== 'string') return '';
  return /^[A-Za-z0-9._-]{1,80}$/.test(id) ? id : '';
}

function formatCallStep(call) {
  const a = call && typeof call.args === 'object' && call.args ? call.args : {};
  const fn = String((call && call[FN_KEY]) || '').slice(0, 30);
  const tab = String(a.tab || '').slice(0, 20);
  if (fn === 'list_tabs') return 'checked tabs';
  if (fn === 'read_tab') return tab ? `read tab ${tab}` : 'read active tab';
  if (fn === 'box_info') return 'checked box health';
  if (fn === 'focus_tab') return tab ? `switched to ${tab}` : 'switched tab';
  if (fn === 'open_tab') {
    const label = a.name || a.agent || 'shell';
    return `opened tab ${String(label).slice(0, 24)}${a.worktree ? ' (worktree)' : ''}`;
  }
  if (fn === 'rename_tab') {
    const to = String(a.title || '').replace(/\s+/g, ' ').trim().slice(0, 48);
    return tab ? `renamed ${tab} → ${to}` : `renamed tab → ${to}`;
  }
  if (fn === 'worktree') {
    const act = String(a.action || 'status').slice(0, 16);
    return tab ? `worktree ${act} on ${tab}` : `worktree ${act}`;
  }
  if (fn === 'close_tab') return tab ? `closed tab ${tab}` : 'closed tab';
  if (fn === 'run') return `run: ${String(a.command || '').replace(/\s+/g, ' ').trim().slice(0, 180)}`;
  if (fn === 'input') return `keys: ${String(a.text || '').replace(/\s+/g, ' ').trim().slice(0, 120)}`;
  if (fn === 'wait') return 'waited for output';
  return fn || 'step';
}

function liveActionLabel(call) {
  const a = call && typeof call.args === 'object' && call.args ? call.args : {};
  const fn = String((call && call[FN_KEY]) || '').slice(0, 30);
  const tab = String(a.tab || '').slice(0, 20);
  if (fn === 'list_tabs') return 'Checking open tabs…';
  if (fn === 'read_tab') return tab ? `Reading ${tab}…` : 'Reading active tab…';
  if (fn === 'box_info') return 'Inspecting box health…';
  if (fn === 'focus_tab') return tab ? `Switching to ${tab}…` : 'Switching tab…';
  if (fn === 'open_tab') return `Opening ${String(a.name || a.agent || 'tab').slice(0, 20)}…`;
  if (fn === 'rename_tab') return tab ? `Renaming ${tab}…` : 'Renaming tab…';
  if (fn === 'worktree') {
    const act = String(a.action || 'status');
    return act === 'merge' ? 'Merging worktree…' : act === 'remove' ? 'Removing worktree…' : 'Checking worktree…';
  }
  if (fn === 'close_tab') return tab ? `Closing ${tab}…` : 'Closing tab…';
  if (fn === 'run') {
    const cmd = String(a.command || '').replace(/\s+/g, ' ').trim().slice(0, 56);
    return tab ? `Running in ${tab}: ${cmd}` : `Running: ${cmd}`;
  }
  if (fn === 'wait') return 'Waiting for output…';
  return 'Working…';
}

function buildGoalTurn(gdir, gid, goal, isCurrent) {
  const running = Boolean(isCurrent && !TERMINAL_STATES.has(goal.state));
  const calls = running ? readJsonlSafe(path.join(gdir, 'calls.jsonl'), 40) : (Array.isArray(goal.calls) ? goal.calls : []);
  const says = running ? readJsonlSafe(path.join(gdir, 'say.jsonl'), 20) : (Array.isArray(goal.say) ? goal.say : []);
  const actions = [];
  let lastCall = null;
  for (const c of calls) {
    if (c && c[FN_KEY] !== 'done' && c[FN_KEY] !== 'say') {
      lastCall = c;
      actions.push({
        ts: (c.t || 0) * 1000,
        ok: c.ok !== false && c.is_error !== true,
        fn: String(c[FN_KEY] || ''),
        label: formatCallStep(c),
      });
    }
  }
  const sayTexts = [];
  for (const s of says) {
    const txt = s && s.text ? String(s.text).trim() : '';
    if (txt && (!sayTexts.length || sayTexts[sayTexts.length - 1] !== txt)) {
      sayTexts.push(txt);
    }
  }
  let reply = '';
  if (TERMINAL_STATES.has(goal.state)) {
    reply = String(goal.summary || goal.error || (sayTexts.length ? sayTexts[sayTexts.length - 1] : goal.state)).trim();
  }
  // Drop trailing say if it duplicates the final reply
  const norm = (s) => String(s || '').replace(/\s+/g, ' ').trim().toLowerCase();
  const notes = reply
    ? sayTexts.filter((s) => norm(s) !== norm(reply))
    : sayTexts;

  return {
    id: gid,
    source: String(goal.source || 'web'),
    prompt: String(goal.text || '').trim(),
    state: String(goal.state || (running ? 'running' : 'done')),
    started: Number(goal.started || goal.created || 0) * 1000,
    ended: Number(goal.ended || 0) * 1000,
    running,
    actions,
    live_action: running ? (lastCall ? liveActionLabel(lastCall) : 'Thinking…') : '',
    notes,
    reply,
  };
}

let lastSysopGid = '';

// A new conversation: the Sysop panel hides the goals created before this time and the sysop's brain forgets them (history.py reads the same file)
export function readConversationSince() {
  const d = readJsonSafe(path.join(SB_STATE_DIR, 'sysop', 'conversation.json'));
  const v = d && Number(d.since);
  return Number.isFinite(v) && v > 0 ? v : 0;
}

export function startNewConversation(now = Date.now() / 1000) {
  const dir = path.join(SB_STATE_DIR, 'sysop');
  fs.mkdirSync(dir, { recursive: true, mode: 0o700 });
  const file = path.join(dir, 'conversation.json');
  const tmp = `${file}.tmp.${process.pid}`;
  fs.writeFileSync(tmp, JSON.stringify({ since: now }) + '\n', { mode: 0o600 });
  fs.renameSync(tmp, file);
  return now;
}

// ---------------------------------------------------------------------------
// Repository context (sysop.autocontext): what each agent session started with
// ---------------------------------------------------------------------------
const CTX_TAB_RE = /^[A-Za-z0-9_.:@-]{1,64}$/;
const CTX_KEY_RE = /^[0-9a-f]{16}$/;
const CTX_STALE_START_MS = 5 * 60 * 1000;

function contextDir(stateSysop = path.join(SB_STATE_DIR, 'sysop')) {
  return path.join(stateSysop, 'digests');
}

function num(v) {
  const n = Number(v);
  return Number.isFinite(n) ? n : 0;
}

// The repositories with a digest (repos/<key>.json) and, from the feed, whether a model call runs or failed for each;
// the sessions of the live tabs (sessions/<tab>.json).
export function readContextState(stateSysop, terminals, status = null) {
  const dir = contextDir(stateSysop);
  const settings = status && status.settings && typeof status.settings === 'object' ? status.settings : {};
  const on = settings.autocontext === undefined ? fs.existsSync(dir) : Boolean(settings.autocontext);
  const calls = new Map();
  const tops = new Map();   // key -> the folder its last event names (an index written before it kept `top` has none)
  for (const ev of readJsonlSafe(path.join(stateSysop, 'system_events.jsonl'), 200)) {
    if (!ev || ev.kind !== 'autocontext' || !CTX_KEY_RE.test(String(ev.key || ''))) continue;
    if (typeof ev.top === 'string' && ev.top) tops.set(String(ev.key), ev.top);
    if (ev.phase === 'started' || ev.phase === 'made' || ev.phase === 'failed') {
      calls.set(String(ev.key), {
        phase: String(ev.phase), ts: num(ev.ts) * 1000, reason: String(ev.reason || ''), error: String(ev.error || ''),
        retry_min: num(ev.retry_min) || null, tab: String(ev.tab || ''), repo: String(ev.repo || ''), commit: String(ev.commit || ''),
        top: String(ev.top || ''),
      });
    }
  }
  const repos = [];
  const seen = new Set();
  let names = [];
  try { names = fs.readdirSync(path.join(dir, 'repos')); } catch (_) {}
  for (const n of names) {
    if (!n.endsWith('.json')) continue;
    const key = n.slice(0, -5);
    if (!CTX_KEY_RE.test(key)) continue;
    const idx = readJsonSafe(path.join(dir, 'repos', n));
    if (!idx || typeof idx !== 'object') continue;
    seen.add(key);
    repos.push({
      key,
      repo: String(idx.repo || 'repo'),
      top: String(idx.top || tops.get(key) || ''),
      base: String(idx.base || '').slice(0, 12),
      at: num(idx.at) * 1000,
      call: calls.get(key) || null,
    });
  }
  // a repository whose first digest is being written (or failed) has no index yet
  for (const [key, call] of calls) {
    if (seen.has(key)) continue;
    repos.push({ key, repo: call.repo || 'repo', top: call.top || '', base: '', at: 0, call });
  }
  const now = Date.now();
  for (const r of repos) {
    const c = r.call;
    r.state = !c ? 'ready'
      : c.phase === 'started' ? (now - c.ts > CTX_STALE_START_MS ? 'stuck' : 'writing')
      : c.phase === 'failed' ? (r.at > c.ts ? 'ready' : 'failed')
      : 'ready';
  }
  repos.sort((a, b) => Math.max(b.at, b.call ? b.call.ts : 0) - Math.max(a.at, a.call ? a.call.ts : 0));

  const sessions = {};
  const live = new Set((terminals || []).map((t) => t && t.address).filter(Boolean));
  for (const tab of live) {
    if (!CTX_TAB_RE.test(tab)) continue;
    const m = readJsonSafe(path.join(dir, 'sessions', `${tab}.json`));
    if (!m || typeof m !== 'object') continue;
    sessions[tab] = {
      tab,
      agent: String(m.agent || ''),
      cwd: String(m.cwd || ''),
      repo: String(m.repo || ''),
      key: String(m.key || ''),
      commit: String(m.commit || ''),
      context: Boolean(m.context),
      base: String(m.base || ''),
      base_at: num(m.base_at) * 1000,
      changes: num(m.changes),
      skipped: Boolean(m.skipped),
      off: Boolean(m.off),
      failed: Boolean(m.failed),
      waiting: Boolean(m.waiting),
      at: num(m.at) * 1000,
    };
  }
  return { on, repos: repos.slice(0, 12), sessions };
}

// The text a session started with (sessions/<tab>.md) or the current digest of a repository (repos/<key>.md), with what the panel shows of it.
export function readContextText({ tab = '', key = '' } = {}) {
  const dir = contextDir();
  if (tab) {
    if (!CTX_TAB_RE.test(tab)) return null;
    const meta = readJsonSafe(path.join(dir, 'sessions', `${tab}.json`));
    if (!meta) return null;
    let text = null;
    try { text = fs.readFileSync(path.join(dir, 'sessions', `${tab}.md`), 'utf8'); } catch (_) {}
    return { kind: 'session', meta, text };
  }
  if (key) {
    if (!CTX_KEY_RE.test(key)) return null;
    const meta = readJsonSafe(path.join(dir, 'repos', `${key}.json`));
    if (!meta) return null;
    let text = null;
    try { text = fs.readFileSync(path.join(dir, 'repos', `${key}.md`), 'utf8'); } catch (_) {}
    return { kind: 'repo', meta, text };
  }
  return null;
}

// The top folder of a repository with a digest (for Rewrite): only one the sysop itself recorded.
export function contextRepoTop(key) {
  if (!CTX_KEY_RE.test(String(key || ''))) return '';
  const idx = readJsonSafe(path.join(contextDir(), 'repos', `${key}.json`));
  let top = idx && typeof idx.top === 'string' ? idx.top : '';
  if (!top) {
    // a repository whose first digest failed has no index yet: the folder its last event names
    for (const ev of readJsonlSafe(path.join(SB_STATE_DIR, 'sysop', 'system_events.jsonl'), 200).reverse()) {
      if (ev && ev.kind === 'autocontext' && ev.key === key && typeof ev.top === 'string' && ev.top) { top = ev.top; break; }
    }
  }
  return top && path.isAbsolute(top) && fs.existsSync(top) ? top : '';
}

export function readSysopSnapshot(terminals) {
  const runSysop = path.join(SB_RUN_DIR, 'sysop');
  const stateSysop = path.join(SB_STATE_DIR, 'sysop');
  const status = readJsonSafe(path.join(runSysop, 'status.json'));
  const pid = status && typeof status.pid === 'number' ? status.pid : null;
  const up = Boolean(status && isPidAlive(pid));

  const cur = up ? sanitizeGoalId(status.current) : '';
  if (cur) lastSysopGid = cur;
  const gid = cur || lastSysopGid;

  let goal = null;
  let pending = null;
  const steps = [];
  const turns = [];
  const nowSec = Date.now() / 1000;
  const maxAgeSec = 12 * 3600;
  const sinceSec = readConversationSince();

  if (up) {
    const goalsRoot = path.join(stateSysop, 'goals');
    let dirs = [];
    try {
      dirs = fs.readdirSync(goalsRoot).map(sanitizeGoalId).filter(Boolean);
    } catch (_) {}
    if (gid && !dirs.includes(gid)) dirs.push(gid);

    const loaded = [];
    for (const id of dirs) {
      const gdir = path.join(goalsRoot, id);
      const g = readJsonSafe(path.join(gdir, 'state.json'));
      if (!g || typeof g !== 'object') continue;
      const isCurrent = id === cur;
      const stamp = Number(g.ended || g.started || g.created || 0);
      if (!isCurrent && stamp > 0 && (nowSec - stamp) > maxAgeSec) continue;
      if (!isCurrent && sinceSec && Number(g.created || g.started || 0) < sinceSec) continue;
      loaded.push({ id, gdir, g, isCurrent, sortTs: Number(g.started || g.created || 0) });
    }
    loaded.sort((a, b) => a.sortTs - b.sortTs || a.id.localeCompare(b.id));
    for (const item of loaded.slice(-15)) {
      const turn = buildGoalTurn(item.gdir, item.id, item.g, item.isCurrent);
      if (turn.prompt || turn.reply || turn.notes.length || turn.running) {
        turns.push(turn);
      }
      if (item.id === gid) {
        goal = item.g;
        if (turn.running) {
          const p = readJsonSafe(path.join(item.gdir, 'pending_action.json'));
          if (p && typeof p === 'object' && p.id) pending = p;
        }
        // Keep legacy flat steps[] populated for Terminal Cockpit compatibility
        if (turn.prompt) steps.push({ ts: turn.started, kind: 'goal', text: turn.prompt });
        for (const a of turn.actions) steps.push({ ts: a.ts, kind: a.ok ? 'info' : 'err', text: a.label });
        for (const n of turn.notes) steps.push({ ts: turn.started, kind: 'ok', text: n });
        if (turn.reply) {
          steps.push({
            ts: turn.ended || Date.now(),
            kind: turn.state === 'done' ? 'ok' : turn.state === 'stopped' ? 'warn' : 'err',
            text: turn.reply,
          });
        }
      }
    }
  }

  const queue = up && Array.isArray(status.queue) ? status.queue : [];
  let state = 'off';
  let sentence = '';

  if (up) {
    if (pending) {
      state = pending.mode === 'veto' ? 'sending' : 'allow?';
      sentence = String(pending.text || 'an action').slice(0, 160);
    } else if (goal) {
      const gs = goal.state;
      if (TERMINAL_STATES.has(gs)) {
        if (typeof goal.ended === 'number' && nowSec - goal.ended > SYSOP_SHOW_END_MS / 1000) {
          state = 'idle';
          sentence = '';
        } else {
          state = gs;
          sentence = String(goal.summary || goal.error || gs).slice(0, 160);
        }
      } else if (gs === 'queued') {
        state = 'queued';
        sentence = String(goal.text || '').slice(0, 160);
      } else if (gs === 'waiting_approval') {
        state = 'allow?';
        sentence = String(goal.text || '').slice(0, 160);
      } else {
        state = 'working';
        const curTurn = turns.length ? turns[turns.length - 1] : null;
        sentence = String((curTurn && curTurn.live_action) || goal.text || '').slice(0, 160);
      }
    } else if (queue.length) {
      state = 'queued';
      sentence = `${queue.length} queued`;
    } else {
      state = 'idle';
      sentence = '';
    }
  }

  // Also surface live OSC 7501 blocked terminals from herdr-core (e.g. direct agent permission dialogs)
  const blocked = (terminals || [])
    .filter((t) => !isHiddenTerminal(t) && t.status && t.status.state === 'blocked')
    .map((t) => ({
      terminal: t.address,
      name: t.name || t.address,
      msg: t.status.msg || 'Program is waiting for input',
      kind: t.status.kind || 'permission',
    }));

  // System events (automatic tab renames, repository digests by Sysop) shown inline in the visual feed
  // without consuming the 8-goal user conversation memory window in history.py.
  const systemEvents = [];
  const allEvents = [];
  if (up) {
    const rawEv = readJsonlSafe(path.join(stateSysop, 'system_events.jsonl'), 200);
    for (const ev of rawEv) {
      const ts = Number(ev && ev.ts ? ev.ts : 0);
      if (ts > 0 && (nowSec - ts) > maxAgeSec) continue;
      if (ev && ev.kind) {
        const row = {
          id: String(ev.id || `ev-${Math.round(ts * 1000)}`),
          kind: String(ev.kind),
          ts: ts * 1000,
          tab: String(ev.tab || ''),
          agent: String(ev.agent || ''),
          old_title: String(ev.old_title || ''),
          new_title: String(ev.new_title || ''),
          text: String(ev.text || ''),
          // autocontext (the repository digest): started, then made or failed
          phase: String(ev.phase || ''),
          repo: String(ev.repo || ''),
          key: String(ev.key || ''),
          commit: String(ev.commit || ''),
          took: Number.isFinite(Number(ev.took)) ? Number(ev.took) : null,
          error: String(ev.error || ''),
          retry_min: Number.isFinite(Number(ev.retry_min)) ? Number(ev.retry_min) : null,
          reason: String(ev.reason || ''),
          // session: an agent session started in a repository, with the orientation or without it
          context: Boolean(ev.context),
          base: String(ev.base || ''),
          base_at: Number.isFinite(Number(ev.base_at)) ? Number(ev.base_at) * 1000 : 0,
          changes: Number.isFinite(Number(ev.changes)) ? Number(ev.changes) : 0,
          writing: Boolean(ev.writing),
          skipped: Boolean(ev.skipped),
          off: Boolean(ev.off),
          failed: Boolean(ev.failed),
        };
        allEvents.push(row);
        if (!(sinceSec && ts > 0 && ts < sinceSec)) systemEvents.push(row);
      }
    }
  }

  return {
    up,
    bus: up ? String(status.bus || '') : '',
    state,
    sentence,
    goal_id: gid,
    pending: pending
      ? {
          id: String(pending.id),
          mode: pending.mode === 'veto' ? 'veto' : 'approve',
          risk: String(pending.risk || ''),
          tab: String(pending.tab || ''),
          text: String(pending.text || ''),
          deadline: typeof pending.deadline === 'number' ? pending.deadline : null,
          reasons: Array.isArray(pending.reasons) ? pending.reasons : [],
        }
      : null,
    queue_len: queue.length,
    turns,
    system_events: systemEvents.slice(-30),
    // the Events tab: what the sysop did by itself, not cut by New conversation (session records are for the cards)
    events: allEvents.filter((e) => !(e.kind === 'autocontext' && e.phase === 'session')).slice(-40),
    context: up ? readContextState(stateSysop, terminals, status) : null,
    steps: steps.slice(-40),
    blocked,
    settings: up && status.settings && typeof status.settings === 'object' ? status.settings : {},
  };
}

export function runCommand(bin, args, stdinText = null, timeoutMs = 15000) {
  return runCommandEnv(bin, args, process.env, timeoutMs, stdinText);
}

export function runCommandEnv(bin, args, env, timeoutMs = 15000, stdinText = null) {
  return new Promise((resolve) => {
    const p = spawn(bin, args, {
      stdio: ['pipe', 'pipe', 'pipe'],
      env,
    });
    let out = '';
    let err = '';
    let settled = false;
    const timer = setTimeout(() => {
      if (!settled) {
        settled = true;
        try { p.kill('SIGTERM'); } catch (_) {}
        resolve({ ok: false, code: 124, stdout: out, stderr: 'command timed out' });
      }
    }, timeoutMs);

    p.stdout.on('data', (c) => { out += c.toString(); });
    p.stderr.on('data', (c) => { err += c.toString(); });
    p.on('error', (e) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      resolve({ ok: false, code: 127, stdout: out, stderr: e.message });
    });
    p.on('close', (code) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      resolve({ ok: code === 0, code: code ?? 1, stdout: out.trim(), stderr: err.trim() });
    });
    if (stdinText !== null) {
      p.stdin.write(stdinText);
    }
    p.stdin.end();
  });
}

// ---------------------------------------------------------------------------
// Live SwarmBox configuration, addons, MCP, SSH pubkey & health snapshot
// ---------------------------------------------------------------------------
function readTextSafe(filePath) {
  try {
    return fs.readFileSync(filePath, 'utf8').trim();
  } catch (_) {
    return '';
  }
}

function parseAddonConf(filePath) {
  const txt = readTextSafe(filePath);
  if (!txt) return null;
  const out = {};
  for (const raw of txt.split('\n')) {
    const ln = raw.trim();
    if (!ln || ln.startsWith('#')) continue;
    const eq = ln.indexOf('=');
    if (eq <= 0) continue;
    const k = ln.slice(0, eq).trim();
    let v = ln.slice(eq + 1).trim();
    if ((v.startsWith('"') && v.endsWith('"')) || (v.startsWith("'") && v.endsWith("'"))) {
      v = v.slice(1, -1);
    }
    out[k] = v;
  }
  return out.NAME ? out : null;
}

// installedOf(dir, item): where the complete install of the addon in the state folder `dir` is, by the record swarmbox-addon writes
// last (its is_installed): `current/.swarmbox-env` for a managed addon, `self/.swarmbox-env` for one that updates itself (UPDATE=self,
// no `current` link). Answers { version: the link's target (a pinned version, or `latest`) or VERSION, cmd: the path of its first
// command (real_command_at) }, or null.
function installedOf(dir, item, home) {
  const base = path.join(dir, item.name);
  const first = item.commands[0];
  if (item.update === 'self') {
    if (!fs.existsSync(path.join(base, 'self', '.swarmbox-env'))) return null;
    const h = dir === home.baked ? path.join(base, 'home') : home.user;
    return { version: item.manifestVersion || 'latest', cmd: first ? path.join(h, '.local', 'bin', first) : '' };
  }
  if (!fs.existsSync(path.join(base, 'current', '.swarmbox-env'))) return null;
  let version = '';
  try { version = path.basename(fs.readlinkSync(path.join(base, 'current'))); } catch (_) {}
  return { version, cmd: first ? path.join(base, 'current', 'bin', first) : '' };
}

// reportedVersion(cmd): the version a floating install's program reports (`CMD --version`: the first thing on its standard output
// that looks like a version, `2.1.332 (Claude Code)` -> 2.1.332), or ''. It runs with a scratch HOME (a program may create its folders
// on a first run) and a timeout, and is kept until the program's file changes: an update of itself replaces it (a new link target, a
// new file), so the version shown follows it without asking again on every read.
const reportedCache = new Map();
function reportedVersion(cmd) {
  let st;
  let real;
  try { real = fs.realpathSync(cmd); st = fs.statSync(real); } catch (_) { return ''; }
  if (!st.isFile()) return '';
  const key = `${real}:${st.mtimeMs}:${st.size}`;
  if (reportedCache.get(cmd)?.key === key) return reportedCache.get(cmd).version;
  let version = '';
  let scratch = '';
  try {
    scratch = fs.mkdtempSync(path.join(os.tmpdir(), 'swarmbox-version-'));
    const out = execFileSync(cmd, ['--version'], {
      env: { ...process.env, HOME: scratch }, cwd: scratch, timeout: 5000, stdio: ['ignore', 'pipe', 'ignore'], encoding: 'utf8',
    });
    const m = String(out).match(/\d+\.\d+(?:\.\d+)*(?:[-+][0-9A-Za-z.]+)?/);
    version = m ? m[0] : '';
  } catch (_) {
    version = '';
  } finally {
    if (scratch) fs.rmSync(scratch, { recursive: true, force: true });
  }
  reportedCache.set(cmd, { key, version });
  return version;
}

function listAddonsSnapshot(env = process.env) {
  const imageDir = env.SWARMBOX_IMAGE_ADDONS_DIR || '/usr/local/lib/swarmbox/addons';
  const userDir = path.join(SB_CONFIG_DIR, 'addons');
  const dataDir = path.join(SB_DATA_DIR, 'addons');
  const bakedDir = env.SWARMBOX_TEST_IMAGE_STATE || '/opt/swarmbox/addons';
  const byName = new Map();

  for (const [level, dir] of [['image', imageDir], ['user', userDir]]) {
    let entries = [];
    try { entries = fs.readdirSync(dir, { withFileTypes: true }); } catch (_) {}
    for (const ent of entries) {
      if (!ent.isDirectory()) continue;
      const conf = parseAddonConf(path.join(dir, ent.name, 'addon.conf'));
      if (!conf) continue;
      byName.set(conf.NAME, {
        name: conf.NAME,
        description: conf.DESCRIPTION || '',
        manifestVersion: conf.VERSION || '',
        commands: (conf.COMMANDS || '').split(/\s+/).filter(Boolean),
        update: conf.UPDATE || 'managed',
        level,
      });
    }
  }

  const out = [];
  const home = { user: HOME, baked: bakedDir };
  for (const item of Array.from(byName.values()).sort((a, b) => a.name.localeCompare(b.name))) {
    let installed = false;
    let installedVersion = '';
    let location = '';
    let cmd = '';
    for (const [loc, dir] of [['workspace', dataDir], ['image', bakedDir]]) {
      const got = installedOf(dir, item, home);
      if (got === null) continue;
      installed = true;
      installedVersion = got.version;
      cmd = got.cmd;
      location = loc;
      break;
    }
    // a floating install (`latest`) shows the version its program reports; a pinned one is the version it names
    const pinnedBehind = installed && item.update !== 'self' && installedVersion !== 'latest' && !!item.manifestVersion
      && installedVersion !== item.manifestVersion;
    const reported = installed && cmd && installedVersion === 'latest' ? reportedVersion(cmd) : '';
    out.push({
      ...item,
      installed,
      installedVersion: reported || installedVersion,
      channel: installedVersion,
      selfUpdate: item.update === 'self',
      location,
      // Update installs a managed addon again: a floating one (`latest`) gets the newest release, a pinned one the version the image
      // names, offered only when that differs from the installed one (a newer image). One that updates itself is never offered.
      updateAvailable: pinnedBehind,
      canUpdate: installed && item.update !== 'self' && (installedVersion === 'latest' || pinnedBehind),
      // `swarmbox-addon remove` deletes the workspace's install; one baked into the image stays
      canRemove: installed && location === 'workspace',
    });
  }
  return out;
}

function listMcpServers() {
  const names = new Set();
  for (const dir of ['/etc/swarmbox/mcp', path.join(SB_CONFIG_DIR, 'mcp')]) {
    try {
      for (const ent of fs.readdirSync(dir, { withFileTypes: true })) {
        if (!ent.isDirectory()) continue;
        if (fs.existsSync(path.join(dir, ent.name, 'config.json'))) names.add(ent.name);
      }
    } catch (_) {}
  }
  return Array.from(names).sort();
}

function envField(envKey, defVal, env = process.env) {
  const raw = env[envKey];
  const has = typeof raw === 'string' && raw.trim() !== '';
  const value = has ? raw.trim() : defVal;
  return { value, default: defVal, custom: has && value !== defVal };
}

export function readBoxConfigSnapshot(terminals = [], env = process.env) {
  const version = readTextSafe('/usr/local/share/swarmbox/host/VERSION') || 'dev';
  const sysopSnap = readSysopSnapshot(terminals);
  const pubkey = readTextSafe(path.join(HOME, '.ssh', 'id_ed25519.pub'))
    || readTextSafe(path.join(HOME, '.ssh', 'id_rsa.pub'))
    || '';
  const healthRaw = readTextSafe(path.join(SB_STATE_DIR, 'health'));
  const health = healthRaw ? healthRaw.split('\n').map((s) => s.trim()).filter(Boolean) : [];
  const addons = listAddonsSnapshot(env);
  const installedAgents = listInstalledAgents(env);

  const box = {
    NAME: envField('SWARMBOX_NAME', 'swarmbox', env),
    AGENT: envField('SWARMBOX_AGENT', '', env),
    YOLO: envField('SWARMBOX_YOLO', '1', env),
    WEB: envField('SWARMBOX_WEB', '1', env),
    WEB_PORT: envField('SWARMBOX_WEB_PORT', '7681', env),
    TZ: { value: (env.TZ && env.TZ.trim()) || 'local', default: 'local', custom: Boolean(env.TZ && env.TZ.trim() && env.TZ.trim() !== 'local') },
    HOSTNAME: { value: os.hostname() || 'swarmbox', default: 'swarmbox', custom: Boolean(os.hostname() && os.hostname() !== 'swarmbox') },
    WITH: envField('SWARMBOX_WITH', '', env),
    BROWSER_URL: envField('SWARMBOX_BROWSER_URL', '', env),
  };

  const sysopSettings = {
    'sysop.autonomy': envField('SWARMBOX_SYSOP_AUTONOMY', 'full-auto', env),
    'sysop.autoname': envField('SWARMBOX_SYSOP_AUTONAME', '1', env),
    'sysop.autocontext': envField('SWARMBOX_SYSOP_AUTOCONTEXT', '1', env),
    'sysop.brain': envField('SWARMBOX_SYSOP_BRAIN', 'auto', env),
    'sysop.model': envField('SWARMBOX_SYSOP_MODEL', 'auto', env),
    'sysop.countdown': envField('SWARMBOX_SYSOP_COUNTDOWN', '4', env),
    'sysop.max_steps': envField('SWARMBOX_SYSOP_MAX_STEPS', '20', env),
    'sysop.max_seconds': envField('SWARMBOX_SYSOP_MAX_SECONDS', '300', env),
    'sysop.topic': envField('SWARMBOX_SYSOP_TOPIC', 'goal', env),
    'sysop.group': envField('SWARMBOX_SYSOP_GROUP', 'sysop', env),
  };

  const voiceSettings = {
    'voice.language': envField('SWARMBOX_VOICE_LANGUAGE', 'auto', env),
    'voice.stt.model': envField('SWARMBOX_VOICE_STT_MODEL', 'small', env),
    'voice.stt.vocabulary': envField('SWARMBOX_VOICE_STT_VOCABULARY', '', env),
    'voice.web': envField('SWARMBOX_VOICE_WEB', '1', env),
    'voice.topic': envField('SWARMBOX_VOICE_TOPIC', 'goal', env),
  };

  return {
    version,
    theme: readSavedTheme(),
    themes: THEME_ORDER,
    box,
    sysop: {
      up: sysopSnap.up,
      state: sysopSnap.state,
      settings: sysopSettings,
    },
    voice: {
      settings: voiceSettings,
    },
    addons,
    installed_agents: installedAgents,
    mcp: listMcpServers(),
    pubkey,
    health,
    worktree_prefs: readWorktreePrefs(),
    session_prefs: readSessionPrefs(),
  };
}

// ---------------------------------------------------------------------------
// Persistent Pinned Sessions (pins.json), Worktree Prefs & tab.events Bus
// ---------------------------------------------------------------------------
// The agent id of a name: an agent command, or another name of it (the OSC 7501 app it reports, its addon name). '' for anything
// else, `yolo` included: yolo is the shell function that runs the default agent, not an agent. The registry (agents.mjs) answers.
export function normalizeAgentName(raw) {
  return resolveAgent(raw);
}

// The default agent of the box: AGENT if it names an agent, else the first agent of WITH, else the first installed agent, else ''.
// The same answer for every place that starts or offers the default agent: New agent, worktree open, the cockpit, the launcher.
export function resolveDefaultAgent(env = process.env) {
  return defaultAgent(env);
}

export function cleanSessionTitle(raw) {
  return String(raw || '')
    .replace(/[\x00-\x1f\x7f]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
    .slice(0, 60);
}

export function defaultTitleForPath(cwd, agent = 'shell') {
  const clean = String(cwd || '').replace(/\/+$/, '');
  const home = HOME.replace(/\/+$/, '');
  if (clean && clean !== '/' && clean !== home) {
    const base = path.basename(clean);
    if (base) return cleanSessionTitle(base);
  }
  return agent && agent !== 'shell' ? agent : 'shell';
}

export function terminalCwd(term) {
  const c = (term && term.foreground && term.foreground.cwd) || (term && term.cwd) || HOME;
  return typeof c === 'string' && c.startsWith('/') ? c : HOME;
}

// The agent a terminal runs, by the registry's one detection order: OSC 7501 app, foreground process, then the swarmbox.agent label
// while the terminal is not a bare login shell. Never the tab name.
export function detectTerminalAgent(term) {
  return detectAgent(term);
}

// The agent a terminal is running right now, from live signals only (OSC 7501 status or the foreground
// process). Unlike detectTerminalAgent it ignores labels, so a plain shell tab still carrying an old
// `swarmbox.agent` label is not mistaken for a running agent.
export function detectLiveAgent(term) {
  return detectAgent(term, { live: true });
}

// Folders recently used to launch a tab from the Web Studio, newest first (state, not config).
export const RECENT_DIRS_FILE = path.join(SB_STATE_DIR, 'recent-dirs.json');
const RECENT_DIRS_MAX = 12;

export function readRecentDirs() {
  const d = readJsonSafe(RECENT_DIRS_FILE);
  if (!d || !Array.isArray(d.dirs)) return [];
  return d.dirs.filter((x) => x && typeof x.path === 'string' && x.path.startsWith('/'));
}

export function noteRecentDir(dir) {
  if (typeof dir !== 'string' || !dir.startsWith('/')) return;
  const clean = dir.replace(/\/+$/, '') || '/';
  try {
    const dirs = [{ path: clean, ts: Math.floor(Date.now() / 1000) }]
      .concat(readRecentDirs().filter((x) => x.path !== clean))
      .slice(0, RECENT_DIRS_MAX);
    fs.mkdirSync(SB_STATE_DIR, { recursive: true, mode: 0o700 });
    const tmp = `${RECENT_DIRS_FILE}.tmp.${process.pid}.${crypto.randomBytes(2).toString('hex')}`;
    fs.writeFileSync(tmp, JSON.stringify({ dirs }, null, 2) + '\n', { mode: 0o600 });
    fs.renameSync(tmp, RECENT_DIRS_FILE);
  } catch (_) {}
}

// The argv of a terminal that runs `agent` (shell, yolo or an agent): the registry's, the twin of build_argv in swarmbox_agents.py.
export function buildAgentArgv(agent, resume = 'continue', env = process.env, opts = {}) {
  return registryBuildAgentArgv(agent, resume, env, opts);
}

export function readPins() {
  const d = readJsonSafe(PINS_FILE);
  if (!d || !Array.isArray(d.pins)) return [];
  return d.pins.filter((p) => p && typeof p === 'object' && typeof p.id === 'string' && p.id);
}

export function writePins(pins) {
  fs.mkdirSync(SB_CONFIG_DIR, { recursive: true, mode: 0o700 });
  const tmp = `${PINS_FILE}.tmp.${process.pid}.${crypto.randomBytes(2).toString('hex')}`;
  fs.writeFileSync(tmp, JSON.stringify({ schema: 1, pins }, null, 2) + '\n', { mode: 0o600 });
  fs.renameSync(tmp, PINS_FILE);
  return pins;
}

export function makePinId(existing = []) {
  const used = new Set(existing.map((p) => p && p.id));
  for (let i = 0; i < 32; i++) {
    const id = 'p_' + crypto.randomBytes(3).toString('hex');
    if (!used.has(id)) return id;
  }
  return 'p_' + Date.now().toString(36);
}

// Live auto-follow: keep pinned tabs' cwd, active agent (never downgrading an agent pin to shell),
// title, and worktree metadata synchronized in pins.json whenever they change.
export function syncPinsFromTerminals(terminals) {
  if (!Array.isArray(terminals) || terminals.length === 0) return false;
  const pins = readPins();
  if (pins.length === 0) return false;
  const byPinId = new Map();
  for (const t of terminals) {
    const pid = t && t.labels && t.labels['swarmbox.pin_id'];
    if (pid) byPinId.set(String(pid), t);
  }
  let changed = false;
  const nowSec = Math.floor(Date.now() / 1000);
  for (const pin of pins) {
    const t = byPinId.get(pin.id);
    if (!t) continue;
    const cwd = terminalCwd(t);
    if (cwd && cwd !== pin.cwd && fs.existsSync(cwd)) {
      pin.cwd = cwd;
      pin.updated_at = nowSec;
      changed = true;
    }
    // Upgrade or switch agent when a known agent is active; never downgrade an agent pin to shell on temporary exit
    const liveAgent = detectTerminalAgent(t);
    if (liveAgent && liveAgent !== pin.agent) {
      pin.agent = liveAgent;
      pin.updated_at = nowSec;
      changed = true;
    }
    const lblTitle = cleanSessionTitle(t.labels && t.labels['swarmbox.title']);
    const lblSrc = String((t.labels && t.labels['swarmbox.title_source']) || '');
    if (lblTitle && lblTitle !== pin.title) {
      pin.title = lblTitle;
      if (lblSrc === 'user' || lblSrc === 'auto') pin.title_source = lblSrc;
      pin.updated_at = nowSec;
      changed = true;
    } else if ((lblSrc === 'user' || lblSrc === 'auto') && lblSrc !== pin.title_source) {
      pin.title_source = lblSrc;
      pin.updated_at = nowSec;
      changed = true;
    }
    const wtPath = t.labels && t.labels['swarmbox.worktree'];
    if (wtPath && (!pin.worktree || pin.worktree.path !== wtPath)) {
      pin.worktree = {
        path: String(wtPath),
        branch: String((t.labels && t.labels['swarmbox.branch']) || ''),
        base: String((t.labels && t.labels['swarmbox.base']) || ''),
        repo: String((t.labels && t.labels['swarmbox.repo']) || ''),
      };
      pin.updated_at = nowSec;
      changed = true;
    }
  }
  if (changed) {
    try { writePins(pins); } catch (_) {}
  }
  return changed;
}

export function buildPinsSnapshot(terminals) {
  const pins = readPins();
  const liveByPin = new Map();
  for (const t of terminals || []) {
    const pid = t && t.labels && t.labels['swarmbox.pin_id'];
    if (pid) liveByPin.set(String(pid), t);
  }
  return pins.map((p) => {
    const liveTerm = liveByPin.get(p.id) || null;
    const cwd = String(p.cwd || '');
    let missingCwd = false;
    try { missingCwd = !cwd || !fs.existsSync(cwd); } catch (_) { missingCwd = true; }
    return {
      ...p,
      live: Boolean(liveTerm),
      parked: !liveTerm,
      live_address: liveTerm ? liveTerm.address : null,
      missing_cwd: missingCwd,
    };
  });
}

// The agents offered by the Web Studio (launcher, settings): the installed agents and those of WITH (installed at startup), the default
// agent first and marked; with no default agent, the first one is marked.
export function listInstalledAgents(env = process.env) {
  const withIds = new Set(String(env.SWARMBOX_WITH || '').replace(/,/g, ' ').split(/\s+/).filter(Boolean).map((t) => resolveAgent(t, env)));
  const def = defaultAgent(env);
  const found = listAgents(env)
    .filter((a) => a.installed || withIds.has(a.id))
    .map((a) => ({ id: a.id, name: a.label, default: a.id === def }));
  found.sort((a, b) => (a.default === b.default ? 0 : a.default ? -1 : 1));
  if (found.length > 0 && !found.some((x) => x.default)) found[0].default = true;
  return found;
}

const VALID_BOOT_MODES = new Set(['autostart', 'parked']);

export function readSessionPrefs() {
  const d = readJsonSafe(SESSION_PREFS_FILE);
  return {
    boot_mode: d && VALID_BOOT_MODES.has(d.boot_mode) ? d.boot_mode : 'autostart',
  };
}

export function writeSessionPrefs(patch = {}) {
  const cur = readSessionPrefs();
  if (patch.boot_mode !== undefined) {
    if (!VALID_BOOT_MODES.has(patch.boot_mode)) throw new Error('boot_mode must be autostart or parked');
    cur.boot_mode = patch.boot_mode;
  }
  fs.mkdirSync(SB_CONFIG_DIR, { recursive: true, mode: 0o700 });
  const tmp = `${SESSION_PREFS_FILE}.tmp.${process.pid}`;
  fs.writeFileSync(tmp, JSON.stringify(cur, null, 2) + '\n', { mode: 0o600 });
  fs.renameSync(tmp, SESSION_PREFS_FILE);
  // Sync autostart flag across all persisted sessions so boot restoration matches the global setting
  const pins = readPins();
  const wantAuto = cur.boot_mode === 'autostart';
  let changed = false;
  for (const p of pins) {
    if (Boolean(p.autostart) !== wantAuto) {
      p.autostart = wantAuto;
      changed = true;
    }
  }
  if (changed) writePins(pins);
  return cur;
}

const VALID_WT_MODES = new Set(['ask', 'auto', 'off']);

export function readWorktreePrefs() {
  const d = readJsonSafe(WORKTREE_PREFS_FILE);
  return {
    mode: d && VALID_WT_MODES.has(d.mode) ? d.mode : 'ask',
    copy_env: d && typeof d.copy_env === 'boolean' ? d.copy_env : true,
  };
}

export function writeWorktreePrefs(patch = {}) {
  const cur = readWorktreePrefs();
  if (patch.mode !== undefined) {
    if (!VALID_WT_MODES.has(patch.mode)) throw new Error('mode must be ask, auto, or off');
    cur.mode = patch.mode;
  }
  if (patch.copy_env !== undefined) {
    cur.copy_env = Boolean(patch.copy_env);
  }
  fs.mkdirSync(SB_CONFIG_DIR, { recursive: true, mode: 0o700 });
  const tmp = `${WORKTREE_PREFS_FILE}.tmp.${process.pid}`;
  fs.writeFileSync(tmp, JSON.stringify(cur, null, 2) + '\n', { mode: 0o600 });
  fs.renameSync(tmp, WORKTREE_PREFS_FILE);
  return cur;
}

function resolveWorktreeCommand() {
  if (WORKTREE_BIN) return [WORKTREE_BIN, []];
  const sibling = path.resolve(__clientDir, '..', '..', 'scripts', 'swarmbox-worktree.py');
  if (fs.existsSync(sibling)) return ['python3', [sibling]];
  return ['swarmbox-worktree', []];
}

export async function runWorktreeCmd(args, timeoutMs = 20000) {
  const [bin, prefix] = resolveWorktreeCommand();
  const r = await runCommand(bin, [...prefix, ...args], null, timeoutMs);
  let data = null;
  if (r.stdout) {
    try { data = JSON.parse(r.stdout); } catch (_) {}
  }
  if (!r.ok) {
    const err = new Error((data && data.msg) || r.stderr || r.stdout || `worktree ${args[0] || ''} failed`);
    err.code = (data && data.err) || 'worktree_error';
    err.data = data || {};
    throw err;
  }
  return data;
}

export function publishTabEvent(payload) {
  if (!payload || typeof payload !== 'object') return;
  try {
    const p = spawn(BUS_BIN, ['pub', '--allow-none', '--source', 'gateway', 'tab.events', '-'], {
      stdio: ['pipe', 'ignore', 'ignore'],
      env: process.env,
    });
    p.on('error', () => {});
    p.stdin.on('error', () => {});
    p.stdin.end(JSON.stringify(payload) + '\n');
  } catch (_) {}
}
