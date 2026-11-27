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
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { WebSocketServer } from 'ws';
import { HC_BIN, HerdrClient, runWorktreeCmd, writeActiveTab } from './hc-client.mjs';
import {
  checkSameOrigin,
  createHttpHandler,
  detectImageFormat,
  isLoopbackAddress,
  validateOpenUrl,
} from './http-routes.mjs';
import {
  discoverProjects,
  listChildDirs,
  listRecentDirs,
  resolveGitRepoInfo,
} from './repo-discovery.mjs';
import {
  createPtyBridge,
  createSyncOutputCoalescer,
  createTermModeTracker,
  isTuiTerminal,
  tuiTimings,
} from './pty-bridge.mjs';
import { createWorktreeHub } from './worktree-ops.mjs';
import { createSessionHub } from './session-hub.mjs';

export {
  HerdrClient,
  checkSameOrigin,
  isLoopbackAddress,
  validateOpenUrl,
  detectImageFormat,
  resolveGitRepoInfo,
  discoverProjects,
  listRecentDirs,
  listChildDirs,
  createSyncOutputCoalescer,
  createTermModeTracker,
  isTuiTerminal,
  tuiTimings,
};

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
// Server factory (also exported for fast unit tests)
// ---------------------------------------------------------------------------
export function createGateway(options = {}) {
  const hc = options.hc || new HerdrClient(options.hcBin || HC_BIN);
  const runWt = options.runWorktreeCmd || runWorktreeCmd;
  const eventClients = new Set();

  // Web UI PTY bridge (/ws/pty/:address)
  const ptyBridge = createPtyBridge({ hc, eventClients, writeActiveTab });

  // Resident box worktree & session hubs
  let hub = null;
  const worktreeHub = createWorktreeHub({
    hc,
    runWt,
    eventClients,
    broadcast: (payload) => hub.broadcast(payload),
    buildSnapshot: (extra) => hub.buildSnapshot(extra),
    typePrompt: ptyBridge.typePrompt,
  });
  hub = createSessionHub({ hc, eventClients, worktreeHub, ptyBridge, options });

  // Web UI HTTP gateway (/api/*, /agents*, /view, static & vendor assets)
  const httpHandler = createHttpHandler({ hc, hub, worktreeHub, ptyBridge, runWt });
  const server = http.createServer(httpHandler);
  const wss = new WebSocketServer({ noServer: true });

  // WebSocket ping/pong keepalive (prevents tunnels/proxies from dropping idle PTY connections)
  const wsPingTimer = setInterval(() => {
    for (const client of wss.clients) {
      if (client.isAlive === false) {
        try { client.terminate(); } catch (_) {}
        continue;
      }
      client.isAlive = false;
      try { client.ping(); } catch (_) {}
    }
  }, 25000);
  if (wsPingTimer.unref) wsPingTimer.unref();

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
    ws.isAlive = true;
    ws.on('pong', () => { ws.isAlive = true; });

    if (url.pathname === '/ws/events') {
      hub.handleEventsConnection(ws, url);
      return;
    }
    await ptyBridge.handlePtyConnection(ws, url);
  });

  function shutdown() {
    hub.stop();
    clearInterval(wsPingTimer);
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
