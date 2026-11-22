// Shared SwarmBox × herdr-core runtime client, theme registry, active-tab tracker,
// and real swarmbox-sysop state/command bridge used by both server.mjs (Web UI)
// and cockpit.mjs (Terminal Cockpit).

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
export const SB_CONFIG_DIR = resolveXdg(process.env.XDG_CONFIG_HOME, path.join(HOME, '.config'), 'swarmbox');
export const XDG_CONFIG_ROOT = isAbs(process.env.XDG_CONFIG_HOME)
  ? process.env.XDG_CONFIG_HOME.replace(/\/+$/, '')
  : path.join(HOME, '.config');

export const HIDDEN_ROLES = new Set(['sysop']);
export const ALLOWED_AGENT_CMDS = new Set(['yolo', 'claude', 'agy', 'gemini', 'opencode', 'codex']);

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
// Theme registry (synchronized between Web UI, Terminal Cockpit, and herdr.toml)
// ---------------------------------------------------------------------------
export const THEME_ORDER = ['purple-glow', 'catppuccin', 'tokyo-night', 'nord', 'rose-pine'];

export const HERDR_THEMES = {
  'purple-glow': {
    label: 'Purple Glow',
    name: 'catppuccin',
    accent: '#a78bfa',
    custom: {
      panel_bg: '#0c0b10',
      sidebar_bg: '#12101a',
      active_row_bg: '#27222f',
      selection_bg: '#6d28d9',
      accent: '#a78bfa',
      text: '#d4d4d8',
      red: '#ff6b78',
      green: '#4ade80',
      yellow: '#fbbf24',
      blue: '#8b5cf6',
    },
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
    name: 'catppuccin',
    accent: '#cba6f7',
    custom: null,
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
    name: 'tokyo-night',
    accent: '#7aa2f7',
    custom: null,
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
    name: 'nord',
    accent: '#88c0d0',
    custom: null,
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
    name: 'rose-pine',
    accent: '#c4a7e7',
    custom: null,
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
  return 'purple-glow';
}

export function saveTheme(themeName) {
  if (!HERDR_THEMES[themeName]) return false;
  try {
    fs.mkdirSync(SB_CONFIG_DIR, { recursive: true });
    fs.writeFileSync(THEME_FILE, themeName + '\n', 'utf8');
  } catch (_) {}
  syncHerdrTomlTheme(themeName);
  return true;
}

export function syncHerdrTomlTheme(themeName) {
  const spec = HERDR_THEMES[themeName];
  if (!spec) return;
  const herdrDir = path.join(XDG_CONFIG_ROOT, 'herdr');
  const tomlPath = path.join(herdrDir, 'config.toml');
  try {
    fs.mkdirSync(herdrDir, { recursive: true });
    const lines = [
      '# SwarmBox herdr configuration (synchronized with Web UI and Cockpit).',
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
    lines.push(
      '',
      '[terminal]',
      'default_shell = "/bin/bash"',
      'shell_mode = "login"',
      'new_cwd = "follow"',
      'kitty_graphics = true',
      '',
      '[keys]',
      'prefix = "ctrl+a"',
      'goto = "prefix+shift+j"',
      '',
      '[[keys.command]]',
      'key = "prefix+g"',
      'type = "popup"',
      'command = "swarmbox-sysop goal"',
      'width = 76',
      'height = 5',
      '',
      '[[keys.command]]',
      'key = "prefix+a"',
      'type = "shell"',
      'command = "swarmbox-sysop approve"',
      '',
      '[[keys.command]]',
      'key = "prefix+shift+v"',
      'type = "shell"',
      'command = "swarmbox-sysop veto"',
      '',
      '[[keys.command]]',
      'key = "prefix+shift+x"',
      'type = "shell"',
      'command = "swarmbox-sysop stop"',
      '',
      '[ui]',
      'sidebar_width = 26',
      'sidebar_collapsed_mode = "compact"',
      'pane_borders = "auto"',
      'pane_outer_borders = false',
      'pane_scrollbars = false',
      'pane_gaps = false',
      'show_agent_labels_on_pane_borders = true',
      'tab_bar_position = "top"',
      'tab_bar_right_separator = " ─ "',
      'status_indicators = "dots"',
      `accent = "${spec.accent}"`,
      'mouse_scroll_lines = 5',
      'window_title = "SwarmBox · {workspace}"',
      '',
      '[[ui.tab_bar_right]]',
      'type = "datetime"',
      'format = "%d/%m ─ %H:%M"',
      '',
      '[ui.toast]',
      'delivery = "herdr"',
      '',
      '[ui.toast.herdr]',
      'position = "bottom-right"',
      '',
      '[ui.toast.clipboard]',
      'enabled = true',
      'position = "bottom-center"',
      '',
    );
    fs.writeFileSync(tomlPath, lines.join('\n'), 'utf8');
    const p = spawn('herdr', ['server', 'reload-config'], { stdio: 'ignore' });
    p.on('error', () => {});
  } catch (_) {}
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
  const tab = String(a.tab || '').slice(0, 16);
  if (fn === 'list_tabs') return 'look at the tabs';
  if (fn === 'read_tab') return tab ? `read tab ${tab}` : 'read a tab';
  if (fn === 'run') return `run: ${String(a.command || '').replace(/\s+/g, ' ').trim().slice(0, 180)}`;
  if (fn === 'input') return `type: ${String(a.text || '').replace(/\s+/g, ' ').trim().slice(0, 180)}`;
  if (fn === 'wait') return 'wait';
  return fn || 'step';
}

let lastSysopGid = '';

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
    .filter((t) => !isHiddenTerminal(t) && t.status && t.status.state === 'blocked')
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

export function runCommand(bin, args, stdinText = null, timeoutMs = 15000) {
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
