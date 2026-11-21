#!/usr/bin/env node
// SwarmBox × herdr-core Web Gateway.
//
// Multiplexes a single framed binary JSON-RPC 2.0 connection (`hc connect`) to serve:
//   - Live xterm.js PTY streams (/ws/pty/:address) with CREDIT flow control & zero node-pty
//   - Live OSC 7501 terminal status + real swarmbox-sysop state events (/ws/events)
//   - Tab lifecycle, active-tab tracking, theme synchronization, and real Sysop controls (/api/*)
//
// Accepts `-p PORT` / `-i IFACE` so `swarmbox-voice front` can sit transparently in front
// of it when the voice addon is installed, handling /voice/* and proxying everything else.

import http from 'node:http';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { spawn } from 'node:child_process';
import { EventEmitter } from 'node:events';
import { fileURLToPath } from 'node:url';
import { WebSocketServer } from 'ws';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const PUBLIC_DIR = path.join(__dirname, 'public');
const NODE_MODULES = path.join(__dirname, 'node_modules');

// Frame kinds from the herdr-core framed protocol
const FRAME_DATA = 0;
const FRAME_CREDIT = 1;
const FRAME_CLOSE = 2;
const FRAME_RESIZE = 3;
const FRAME_FOCUS = 4;

const HOME = process.env.HOME || os.homedir() || '/home/agent';
const HC_BIN = process.env.SWARMBOX_TEST_HC_BIN || 'hc';
const SYSOP_BIN = process.env.SWARMBOX_TEST_SYSOP_BIN || 'swarmbox-sysop';
const SB_RUN_DIR = process.env.SB_RUN_DIR || process.env.SWARMBOX_TEST_RUN_DIR || '/tmp/swarmbox';
const SB_STATE_DIR = resolveXdg(process.env.XDG_STATE_HOME, path.join(HOME, '.local', 'state'), 'swarmbox');
const SB_CONFIG_DIR = resolveXdg(process.env.XDG_CONFIG_HOME, path.join(HOME, '.config'), 'swarmbox');
const XDG_CONFIG_ROOT = isAbs(process.env.XDG_CONFIG_HOME) ? process.env.XDG_CONFIG_HOME.replace(/\/+$/, '') : path.join(HOME, '.config');

function isAbs(p) {
  return typeof p === 'string' && p.startsWith('/');
}

function resolveXdg(xdgVar, fallback, sub) {
  const base = isAbs(xdgVar) ? xdgVar.replace(/\/+$/, '') : fallback;
  return path.join(base, sub);
}

export function parseCliArgs(argv) {
  let port = Number(process.env.SWARMBOX_WEB_PORT || 7681);
  let iface = process.env.SWARMBOX_WEB_IFACE || '0.0.0.0';
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if ((a === '-p' || a === '--port') && i + 1 < argv.length) {
      port = Number(argv[++i]);
    } else if (a.startsWith('--port=')) {
      port = Number(a.slice('--port='.length));
    } else if ((a === '-i' || a === '--interface') && i + 1 < argv.length) {
      iface = argv[++i];
    } else if (a.startsWith('--interface=')) {
      iface = a.slice('--interface='.length);
    }
  }
  if (iface === 'lo') iface = '127.0.0.1';
  if (!Number.isInteger(port) || port < 1 || port > 65535) port = 7681;
  return { port, iface };
}

// ---------------------------------------------------------------------------
// Theme registry (synchronized between Web UI and ~/.config/herdr/config.toml)
// ---------------------------------------------------------------------------
const HERDR_THEMES = {
  'purple-glow': {
    name: 'catppuccin',
    custom: {
      panel_bg: '#0c0b10',
      sidebar_bg: '#14121b',
      active_row_bg: '#27222f',
      selection_bg: '#6d28d9',
      accent: '#a78bfa',
      red: '#ff6b78',
      green: '#4ade80',
    },
  },
  catppuccin: { name: 'catppuccin', custom: null },
  'tokyo-night': { name: 'tokyo-night', custom: null },
  nord: { name: 'nord', custom: null },
  'rose-pine': { name: 'rose-pine', custom: null },
};

const THEME_FILE = path.join(SB_CONFIG_DIR, 'herdr-web-theme');

function readSavedTheme() {
  try {
    const t = fs.readFileSync(THEME_FILE, 'utf8').trim();
    if (HERDR_THEMES[t]) return t;
  } catch (_) {}
  return 'purple-glow';
}

function saveTheme(themeName) {
  if (!HERDR_THEMES[themeName]) return false;
  try {
    fs.mkdirSync(SB_CONFIG_DIR, { recursive: true });
    fs.writeFileSync(THEME_FILE, themeName + '\n', 'utf8');
  } catch (_) {}
  syncHerdrTomlTheme(themeName);
  return true;
}

function syncHerdrTomlTheme(themeName) {
  const spec = HERDR_THEMES[themeName];
  if (!spec) return;
  const herdrDir = path.join(XDG_CONFIG_ROOT, 'herdr');
  const tomlPath = path.join(herdrDir, 'config.toml');
  try {
    fs.mkdirSync(herdrDir, { recursive: true });
    const lines = [
      '# SwarmBox herdr theme configuration (synced with Web UI).',
      'onboarding = false',
      '',
      '[theme]',
      `name = "${spec.name}"`,
    ];
    if (spec.custom) {
      lines.push('', '[theme.custom]');
      for (const [k, v] of Object.entries(spec.custom)) {
        lines.push(`${k} = "${v}"`);
      }
    }
    lines.push('', '[terminal]', 'default_shell = "/bin/bash"', '');
    fs.writeFileSync(tomlPath, lines.join('\n'), 'utf8');
    // Best-effort live reload if herdr server happens to be running
    const p = spawn('herdr', ['server', 'reload-config'], { stdio: 'ignore' });
    p.on('error', () => {});
  } catch (_) {}
}

// ---------------------------------------------------------------------------
// Active tab tracking (consumed by swarmbox-tabs active and swarmbox-sysop)
// ---------------------------------------------------------------------------
function writeActiveTab(addr) {
  if (!addr || typeof addr !== 'string') return;
  try {
    fs.mkdirSync(SB_RUN_DIR, { recursive: true });
    fs.writeFileSync(path.join(SB_RUN_DIR, 'herdr-active-tab'), addr + '\n', 'utf8');
  } catch (_) {}
}

function readActiveTab() {
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
  constructor(hcBin = HC_BIN) {
    super();
    this.hcBin = hcBin;
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
          console.error(`[herdr-web] hc connect exited (code=${code} sig=${sig}); reconnecting in ${this.reconnectDelay}ms`);
          this.reconnectTimer = setTimeout(() => {
            this.reconnectTimer = null;
            this.start().catch((err) => console.error('[herdr-web] reconnect failed:', err.message));
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
          t.status = data?.status ?? data ?? null;
          t.reported = true;
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
      .filter((t) => t.state === 'live')
      .sort((a, b) => (a.created_ms || 0) - (b.created_ms || 0));
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

  attach(terminal, cols, rows, handlers) {
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
              b.writeUInt16LE(Math.max(8, Math.min(200, Number(r) || 30)), 2);
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
            rows: Math.max(8, Math.min(200, Number(rows) || 30)),
            history: 500,
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
  const tab = String(a.tab || '').slice(0, 16);
  if (fn === 'list_tabs') return 'look at the tabs';
  if (fn === 'read_tab') return tab ? `read tab ${tab}` : 'read a tab';
  if (fn === 'run') return `run: ${String(a.command || '').replace(/\s+/g, ' ').trim().slice(0, 180)}`;
  if (fn === 'input') return `type: ${String(a.text || '').replace(/\s+/g, ' ').trim().slice(0, 180)}`;
  if (fn === 'wait') return 'wait';
  return fn || 'step';
}

let lastSysopGid = '';

function readSysopSnapshot(terminals) {
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

  if (up && gid) {
    const gdir = path.join(stateSysop, 'goals', gid);
    goal = readJsonSafe(path.join(gdir, 'state.json'));
    if (goal && typeof goal === 'object') {
      const running = Boolean(cur && !TERMINAL_STATES.has(goal.state));
      const calls = running ? readJsonlSafe(path.join(gdir, 'calls.jsonl'), 30) : (Array.isArray(goal.calls) ? goal.calls : []);
      const says = running ? readJsonlSafe(path.join(gdir, 'say.jsonl'), 20) : (Array.isArray(goal.say) ? goal.say : []);
      if (running) {
        const p = readJsonSafe(path.join(gdir, 'pending_action.json'));
        if (p && typeof p === 'object' && p.id) pending = p;
      }
      if (goal.text) {
        steps.push({ ts: (goal.started || 0) * 1000, kind: 'goal', text: String(goal.text) });
      }
      const events = [];
      for (const c of calls) {
        if (c && c[FN_KEY] !== 'done') {
          events.push({ ts: (c.t || 0) * 1000, kind: c.ok === false ? 'err' : 'info', text: formatCallStep(c) });
        }
      }
      for (const s of says) {
        if (s && s.text) {
          events.push({ ts: (s.t || 0) * 1000, kind: 'ok', text: String(s.text) });
        }
      }
      events.sort((a, b) => a.ts - b.ts);
      steps.push(...events);
      if (TERMINAL_STATES.has(goal.state)) {
        const msg = goal.summary || goal.error || goal.state;
        steps.push({
          ts: (goal.ended || Date.now() / 1000) * 1000,
          kind: goal.state === 'done' ? 'ok' : goal.state === 'stopped' ? 'warn' : 'err',
          text: String(msg),
        });
      }
    }
  }

  const queue = up && Array.isArray(status.queue) ? status.queue : [];
  let state = 'off';
  let sentence = '';
  const nowSec = Date.now() / 1000;

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
        const last = steps.length ? steps[steps.length - 1].text : (goal.text || '');
        sentence = String(last).slice(0, 160);
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
    .filter((t) => t.status && t.status.state === 'blocked')
    .map((t) => ({
      terminal: t.address,
      name: t.name || t.address,
      msg: t.status.msg || 'Program is waiting for input',
      kind: t.status.kind || 'permission',
    }));

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
    steps: steps.slice(-40),
    blocked,
    settings: up && status.settings && typeof status.settings === 'object' ? status.settings : {},
  };
}

function runCommand(bin, args, stdinText = null, timeoutMs = 15000) {
  return new Promise((resolve) => {
    const p = spawn(bin, args, {
      stdio: ['pipe', 'pipe', 'pipe'],
      env: process.env,
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
// Security & HTTP helpers
// ---------------------------------------------------------------------------
const SECURITY_HEADERS = {
  'Content-Security-Policy': "frame-ancestors 'self'",
  'X-Frame-Options': 'SAMEORIGIN',
  'X-Content-Type-Options': 'nosniff',
};

const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.js': 'application/javascript; charset=utf-8',
  '.mjs': 'application/javascript; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.svg': 'image/svg+xml',
};

export function checkSameOrigin(req) {
  const origin = req.headers.origin;
  if (!origin) return true;
  const host = (req.headers.host || '').trim().toLowerCase();
  if (!host) return false;
  try {
    return new URL(origin).host.toLowerCase() === host;
  } catch (_) {
    return false;
  }
}

function sendJson(res, code, data) {
  res.writeHead(code, {
    ...SECURITY_HEADERS,
    'Content-Type': 'application/json; charset=utf-8',
    'Cache-Control': 'no-store',
  });
  res.end(JSON.stringify(data));
}

function readBody(req, limit = 256 * 1024) {
  return new Promise((resolve, reject) => {
    let data = '';
    req.on('data', (c) => {
      data += c;
      if (data.length > limit) {
        reject(new Error('body too large'));
        req.destroy();
      }
    });
    req.on('end', () => {
      if (!data) return resolve({});
      try {
        resolve(JSON.parse(data));
      } catch (e) {
        reject(new Error('invalid JSON body'));
      }
    });
    req.on('error', reject);
  });
}

function serveFile(res, filePath, cacheable = false) {
  fs.readFile(filePath, (err, content) => {
    if (err) {
      res.writeHead(404, SECURITY_HEADERS);
      res.end('Not found');
      return;
    }
    const ext = path.extname(filePath);
    res.writeHead(200, {
      ...SECURITY_HEADERS,
      'Content-Type': MIME[ext] || 'application/octet-stream',
      'Cache-Control': cacheable ? 'public, max-age=3600' : 'no-store',
    });
    res.end(content);
  });
}

function sanitizeTabName(raw, prefix = 'tab') {
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

const ALLOWED_AGENT_CMDS = new Set(['yolo', 'claude', 'agy', 'gemini', 'opencode', 'codex']);

// ---------------------------------------------------------------------------
// Server factory (also exported for fast unit tests)
// ---------------------------------------------------------------------------
export function createGateway(options = {}) {
  const hc = options.hc || new HerdrClient(options.hcBin || HC_BIN);
  const eventClients = new Set();
  let currentTheme = readSavedTheme();
  let lastBroadcastHash = '';

  function buildSnapshot(extra = {}) {
    const terminals = hc.listSnapshot();
    const sysop = readSysopSnapshot(terminals);
    return {
      ...extra,
      terminals,
      active: readActiveTab(),
      sysop,
      theme: currentTheme,
    };
  }

  function broadcast(payload) {
    const raw = JSON.stringify(payload);
    for (const ws of eventClients) {
      if (ws.readyState === 1) ws.send(raw);
    }
  }

  hc.on('snapshot', () => {
    const snap = buildSnapshot({ type: 'snapshot' });
    lastBroadcastHash = JSON.stringify(snap.sysop);
    broadcast(snap);
  });

  hc.on('hc-event', ({ event }) => {
    const snap = buildSnapshot({ type: 'event', event });
    lastBroadcastHash = JSON.stringify(snap.sysop);
    broadcast(snap);
  });

  // Poll real swarmbox-sysop state files; broadcast only on actual state changes
  const sysopTimer = setInterval(() => {
    if (eventClients.size === 0) return;
    const snap = buildSnapshot({ type: 'sysop' });
    const h = JSON.stringify(snap.sysop);
    if (h !== lastBroadcastHash) {
      lastBroadcastHash = h;
      broadcast(snap);
    }
  }, 600);
  if (sysopTimer.unref) sysopTimer.unref();

  const server = http.createServer(async (req, res) => {
    const url = new URL(req.url, `http://${req.headers.host || 'localhost'}`);
    const pathname = url.pathname;

    try {
      // Origin guard on all mutating API routes
      if (pathname.startsWith('/api/') && req.method !== 'GET' && req.method !== 'HEAD') {
        if (!checkSameOrigin(req)) {
          return sendJson(res, 403, { error: 'bad_origin', message: 'cross-origin calls are not allowed' });
        }
      }

      // Local xterm.js vendor bundles (zero CDN dependency)
      if (pathname === '/vendor/xterm.js') return serveFile(res, path.join(NODE_MODULES, '@xterm/xterm/lib/xterm.js'), true);
      if (pathname === '/vendor/xterm.css') return serveFile(res, path.join(NODE_MODULES, '@xterm/xterm/css/xterm.css'), true);
      if (pathname === '/vendor/addon-fit.js') return serveFile(res, path.join(NODE_MODULES, '@xterm/addon-fit/lib/addon-fit.js'), true);
      if (pathname === '/vendor/addon-web-links.js') return serveFile(res, path.join(NODE_MODULES, '@xterm/addon-web-links/lib/addon-web-links.js'), true);

      // Health & state
      if (pathname === '/api/health' && req.method === 'GET') {
        const snap = buildSnapshot();
        return sendJson(res, 200, {
          ok: true,
          mux: 'herdr',
          herdr: Boolean(hc.proc),
          tabs: snap.terminals.length,
          sysop_up: snap.sysop.up,
          theme: currentTheme,
        });
      }

      if (pathname === '/api/theme' && req.method === 'GET') {
        return sendJson(res, 200, { theme: currentTheme, themes: Object.keys(HERDR_THEMES) });
      }
      if (pathname === '/api/theme' && req.method === 'POST') {
        const body = await readBody(req);
        const name = String(body.theme || '');
        if (!HERDR_THEMES[name]) return sendJson(res, 400, { error: 'unknown_theme' });
        currentTheme = name;
        saveTheme(name);
        broadcast(buildSnapshot({ type: 'theme' }));
        return sendJson(res, 200, { ok: true, theme: currentTheme });
      }

      if (pathname === '/api/tabs' && req.method === 'GET') {
        const resList = await hc.call('terminal.list', { all: false });
        const terminals = (resList.terminals || []).filter((t) => t.state === 'live');
        return sendJson(res, 200, {
          terminals,
          active: readActiveTab(),
          sysop: readSysopSnapshot(terminals),
          theme: currentTheme,
        });
      }

      if (pathname === '/api/tabs' && req.method === 'POST') {
        const body = await readBody(req);
        const preset = String(body.preset || 'shell');
        const cwd = typeof body.cwd === 'string' && body.cwd.startsWith('/') ? body.cwd : HOME;
        let argv = ['/bin/bash', '-l'];
        let prefix = 'shell';
        if (preset === 'agent') {
          const requested = String(body.agent || process.env.SWARMBOX_AGENT || 'yolo').trim();
          const cmd = ALLOWED_AGENT_CMDS.has(requested) ? requested : 'yolo';
          argv = ['/bin/bash', '-lc', `exec ${cmd}`];
          prefix = cmd === 'yolo' ? 'agent' : cmd;
        }
        const name = sanitizeTabName(body.name, prefix);
        const created = await hc.call('terminal.run', {
          argv,
          name,
          cwd,
          keep: true,
          no_parent: true,
        });
        const addr = created && created.terminal && created.terminal.address;
        if (addr) writeActiveTab(addr);
        return sendJson(res, 201, created);
      }

      const tabMatch = pathname.match(/^\/api\/tabs\/([^/]+)(?:\/(focus|send|keys|interrupt|answer))?$/);
      if (tabMatch) {
        const termId = decodeURIComponent(tabMatch[1]);
        const action = tabMatch[2];

        if (!action && req.method === 'DELETE') {
          await hc.call('terminal.kill', { terminal: termId });
          hc.call('terminal.rm', { terminal: termId }).catch(() => {});
          return sendJson(res, 200, { ok: true });
        }
        if (action === 'focus' && req.method === 'POST') {
          writeActiveTab(termId);
          return sendJson(res, 200, { ok: true, active: termId });
        }
        if (action === 'send' && req.method === 'POST') {
          const body = await readBody(req);
          const r = await hc.call('terminal.send', {
            terminal: termId,
            text: String(body.text || ''),
            force: Boolean(body.force),
          });
          return sendJson(res, 200, r);
        }
        if (action === 'answer' && req.method === 'POST') {
          const body = await readBody(req);
          const decision = body.decision === 'allow' ? 'y' : 'n';
          const r = await hc.call('terminal.send', {
            terminal: termId,
            text: typeof body.text === 'string' ? body.text : decision,
            force: true,
          });
          return sendJson(res, 200, { ok: true, result: r });
        }
        if (action === 'keys' && req.method === 'POST') {
          const body = await readBody(req);
          const keys = Array.isArray(body.keys) ? body.keys.map(String) : [];
          const r = await hc.call('terminal.keys', { terminal: termId, keys });
          return sendJson(res, 200, r);
        }
        if (action === 'interrupt' && req.method === 'POST') {
          const r = await hc.call('terminal.interrupt', { terminal: termId, timeout: 2 });
          return sendJson(res, 200, r);
        }
      }

      // Real swarmbox-sysop controls
      if (pathname === '/api/sysop/goal' && req.method === 'POST') {
        const body = await readBody(req);
        const goal = String(body.goal || '').trim();
        if (!goal) return sendJson(res, 400, { error: 'empty_goal', message: 'goal cannot be empty' });
        if (body.terminal) writeActiveTab(String(body.terminal));
        const r = await runCommand(SYSOP_BIN, ['goal', '--source', 'web', '--', '-'], goal + '\n');
        if (!r.ok) {
          return sendJson(res, r.code === 127 ? 503 : 502, {
            error: 'sysop_goal_failed',
            message: r.stderr || r.stdout || `swarmbox-sysop exited ${r.code}`,
          });
        }
        broadcast(buildSnapshot({ type: 'sysop' }));
        return sendJson(res, 200, { ok: true, goal_id: r.stdout, sysop: readSysopSnapshot(hc.listSnapshot()) });
      }

      if (pathname === '/api/sysop/approve' && req.method === 'POST') {
        const r = await runCommand(SYSOP_BIN, ['approve']);
        broadcast(buildSnapshot({ type: 'sysop' }));
        if (!r.ok) return sendJson(res, 409, { error: 'approve_failed', message: r.stderr || r.stdout || 'nothing waiting' });
        return sendJson(res, 200, { ok: true, message: r.stdout || 'allowed' });
      }

      if (pathname === '/api/sysop/veto' && req.method === 'POST') {
        const r = await runCommand(SYSOP_BIN, ['veto']);
        broadcast(buildSnapshot({ type: 'sysop' }));
        if (!r.ok) return sendJson(res, 409, { error: 'veto_failed', message: r.stderr || r.stdout || 'nothing waiting' });
        return sendJson(res, 200, { ok: true, message: r.stdout || 'cancelled' });
      }

      if (pathname === '/api/sysop/stop' && req.method === 'POST') {
        const r = await runCommand(SYSOP_BIN, ['stop']);
        broadcast(buildSnapshot({ type: 'sysop' }));
        if (!r.ok) return sendJson(res, 409, { error: 'stop_failed', message: r.stderr || r.stdout || 'nothing to stop' });
        return sendJson(res, 200, { ok: true, message: r.stdout || 'stopped' });
      }

      // Static frontend assets
      const rel = pathname === '/' ? 'index.html' : pathname.replace(/^\/+/, '');
      const safePath = path.normalize(path.join(PUBLIC_DIR, rel));
      if (safePath !== PUBLIC_DIR && !safePath.startsWith(PUBLIC_DIR + path.sep)) {
        res.writeHead(403, SECURITY_HEADERS);
        return res.end('Forbidden');
      }
      return serveFile(res, safePath, false);
    } catch (err) {
      return sendJson(res, 500, { error: 'internal', message: err.message });
    }
  });

  const wss = new WebSocketServer({ noServer: true });

  server.on('upgrade', (req, socket, head) => {
    if (!checkSameOrigin(req)) {
      socket.write('HTTP/1.1 403 Forbidden\r\nConnection: close\r\n\r\n');
      socket.destroy();
      return;
    }
    const url = new URL(req.url, `http://${req.headers.host || 'localhost'}`);
    if (url.pathname === '/ws/events' || url.pathname.startsWith('/ws/pty/')) {
      wss.handleUpgrade(req, socket, head, (ws) => {
        wss.emit('connection', ws, req, url);
      });
    } else {
      socket.destroy();
    }
  });

  wss.on('connection', async (ws, _req, url) => {
    if (url.pathname === '/ws/events') {
      eventClients.add(ws);
      ws.send(JSON.stringify(buildSnapshot({ type: 'snapshot' })));
      ws.on('close', () => eventClients.delete(ws));
      return;
    }

    const termId = decodeURIComponent(url.pathname.slice('/ws/pty/'.length));
    const cols = Number(url.searchParams.get('cols') || 100);
    const rows = Number(url.searchParams.get('rows') || 30);
    writeActiveTab(termId);

    let stream = null;
    try {
      stream = await hc.attach(termId, cols, rows, {
        onData: (buf) => {
          if (ws.readyState === 1) ws.send(buf);
        },
        onClose: (info) => {
          if (ws.readyState === 1) {
            ws.send(JSON.stringify({ type: 'closed', info }));
            ws.close();
          }
        },
      });
    } catch (err) {
      if (ws.readyState === 1) {
        ws.send(JSON.stringify({ type: 'error', message: err.message }));
        ws.close();
      }
      return;
    }

    ws.on('message', (data, isBinary) => {
      if (!stream) return;
      if (isBinary) {
        stream.write(Buffer.from(data));
        return;
      }
      const text = data.toString('utf8');
      if (text.startsWith('{')) {
        try {
          const msg = JSON.parse(text);
          if (msg.type === 'resize') {
            stream.resize(msg.cols, msg.rows);
            return;
          }
          if (msg.type === 'focus') {
            if (msg.focused) writeActiveTab(termId);
            stream.focus(Boolean(msg.focused));
            return;
          }
          if (msg.type === 'input' && typeof msg.data === 'string') {
            stream.write(Buffer.from(msg.data, 'utf8'));
            return;
          }
        } catch (_) {}
      }
      stream.write(Buffer.from(text, 'utf8'));
    });

    ws.on('close', () => {
      if (stream) {
        stream.close();
        stream = null;
      }
    });
  });

  function shutdown() {
    clearInterval(sysopTimer);
    for (const ws of eventClients) {
      try { ws.close(); } catch (_) {}
    }
    wss.close();
    server.close();
    hc.close();
  }

  return { server, wss, hc, shutdown };
}

// Direct CLI entry point
if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const { port, iface } = parseCliArgs(process.argv.slice(2));
  const gw = createGateway();

  const onSignal = () => {
    gw.shutdown();
    process.exit(0);
  };
  process.on('SIGTERM', onSignal);
  process.on('SIGINT', onSignal);

  gw.hc
    .start()
    .then(() => {
      gw.server.listen(port, iface, () => {
        console.log(`swarmbox-herdr-web: listening on http://${iface}:${port}`);
      });
    })
    .catch((err) => {
      console.error('swarmbox-herdr-web: failed to connect to herdr-core:', err.message);
      process.exit(1);
    });
}
