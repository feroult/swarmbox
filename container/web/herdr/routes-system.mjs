// HTTP routes for health, theme, open-url, image paste, agent registry, config/addons,
// touch debug, Sysop controls/context, and read-only local file preview (/api/files/*).

import fs from 'node:fs';
import path from 'node:path';
import { agentIconPath, browserRegistry, resolveAgent } from './agents.mjs';
import {
  ADDON_BIN,
  HERDR_THEMES,
  HOME,
  SB_RUN_DIR,
  SYSOP_BIN,
  contextRepoTop,
  readBoxConfigSnapshot,
  readContextText,
  readSysopSnapshot,
  runCommand,
  runCommandEnv,
  saveTheme,
  startNewConversation,
  writeActiveTab,
} from './hc-client.mjs';
import {
  decodeRawPath,
  listDirectory,
  readTextFile,
  resolveAndStat,
  sandboxHeadersForRaw,
} from './file-preview.mjs';
import {
  MAX_IMAGE_BYTES,
  SECURITY_HEADERS,
  isLoopbackAddress,
  readBinaryBody,
  readBody,
  savePastedImage,
  sendJson,
  serveFile,
  validateOpenUrl,
} from './http-utils.mjs';

export async function handleSystemRoutes(req, res, url, pathname, { hc, hub }) {
  // Health & state
  if (pathname === '/api/health' && req.method === 'GET') {
    const snap = hub.buildSnapshot();
    sendJson(res, 200, {
      ok: true,
      mux: 'herdr',
      herdr: Boolean(hc.proc),
      tabs: snap.terminals.length,
      sysop_up: snap.sysop.up,
      theme: hub.getTheme(),
      home: HOME,
    });
    return true;
  }

  if (pathname === '/api/theme' && req.method === 'GET') {
    const theme = hub.refreshTheme();
    sendJson(res, 200, { theme, themes: Object.keys(HERDR_THEMES) });
    return true;
  }
  if (pathname === '/api/theme' && req.method === 'POST') {
    const body = await readBody(req);
    const name = String(body.theme || '');
    if (!HERDR_THEMES[name]) { sendJson(res, 400, { error: 'unknown_theme' }); return true; }
    hub.setTheme(name);
    saveTheme(name);
    hub.broadcast(hub.buildSnapshot({ type: 'theme' }));
    sendJson(res, 200, { ok: true, theme: hub.getTheme() });
    return true;
  }

  if (pathname === '/api/open-url' && req.method === 'POST') {
    const remote = req.socket && req.socket.remoteAddress;
    if (!isLoopbackAddress(remote)) {
      sendJson(res, 403, { error: 'forbidden', message: 'loopback only' });
      return true;
    }
    const body = await readBody(req, 16 * 1024);
    const targetUrl = validateOpenUrl(body && body.url);
    if (!targetUrl) {
      sendJson(res, 400, { error: 'invalid_url', message: 'only http:// and https:// URLs are supported' });
      return true;
    }
    let delivered = 0;
    for (const ws of hub.eventClients) {
      if (ws.readyState === 1) delivered += 1;
    }
    if (delivered > 0) {
      hub.broadcast({ type: 'open_url', url: targetUrl, ts: Date.now() });
    }
    sendJson(res, 200, { ok: true, delivered });
    return true;
  }

  if (pathname === '/api/paste-image' && req.method === 'POST') {
    let buf;
    try {
      buf = await readBinaryBody(req, MAX_IMAGE_BYTES);
    } catch (err) {
      sendJson(res, err.status || 400, { error: 'upload_failed', message: err.message });
      return true;
    }
    if (!buf || buf.length === 0) {
      sendJson(res, 400, { error: 'empty_image', message: 'no image data received' });
      return true;
    }
    const saved = savePastedImage(buf);
    if (!saved) {
      sendJson(res, 415, { error: 'unsupported_image', message: 'supported formats: PNG, JPEG, WebP, GIF, BMP' });
      return true;
    }
    sendJson(res, 200, { ok: true, ...saved });
    return true;
  }

  // The agent registry for the page (docs/agents-design.md): /agents.js sets window.SWARMBOX_AGENTS before app.js runs, so the first
  // render already knows which tabs are agents; /api/agents refreshes it; /agents/<id>/icon.svg is an agent's icon as a file.
  if (pathname === '/agents.js' && req.method === 'GET') {
    const body = `window.SWARMBOX_AGENTS = ${JSON.stringify(browserRegistry()).replace(/</g, '\\u003c')};\n`;
    res.writeHead(200, { ...SECURITY_HEADERS, 'Content-Type': 'text/javascript; charset=utf-8', 'Cache-Control': 'no-store' });
    res.end(body);
    return true;
  }
  if (pathname === '/api/agents' && req.method === 'GET') {
    sendJson(res, 200, browserRegistry());
    return true;
  }
  {
    const m = /^\/agents\/([a-z0-9][a-z0-9_-]*)\/icon\.svg$/.exec(pathname);
    if (m && req.method === 'GET') {
      const icon = resolveAgent(m[1]) === m[1] ? agentIconPath(m[1]) : '';
      if (!icon) { sendJson(res, 404, { error: 'no_icon', message: 'no such agent or it has no icon' }); return true; }
      serveFile(res, icon, false);
      return true;
    }
  }

  if (pathname === '/api/config' && req.method === 'GET') {
    const theme = hub.refreshTheme();
    const cfg = readBoxConfigSnapshot(hc.listSnapshot());
    cfg.theme = theme;
    sendJson(res, 200, cfg);
    return true;
  }

  // Settings > Addons: install, update (a managed addon installed again: the newest release of a floating one, the version the
  // image names for a pinned one; an addon that updates itself is not offered) and remove (the install only, never its settings).
  const addonMatch = pathname.match(/^\/api\/addons\/([a-z0-9][a-z0-9_-]{0,40})\/(install|update|remove)$/);
  if (addonMatch && req.method === 'POST') {
    const [, addonName, action] = addonMatch;
    const curCfg = readBoxConfigSnapshot(hc.listSnapshot());
    const addon = curCfg.addons.find((a) => a.name === addonName);
    if (!addon) {
      sendJson(res, 404, { error: 'unknown_addon', message: `Addon "${addonName}" not found` });
      return true;
    }
    if ((action === 'update' && !addon.canUpdate) || (action === 'remove' && !addon.canRemove)) {
      sendJson(res, 409, { error: `addon_${action}_refused`, message: `${addonName} cannot be ${action === 'update' ? 'updated' : 'removed'} here` });
      return true;
    }
    const args = { install: ['install', addonName], update: ['install', addonName, '--force'], remove: ['remove', addonName] }[action];
    const r = await runCommand(ADDON_BIN, args, null, 180000);
    if (!r.ok) {
      sendJson(res, 502, {
        error: `addon_${action}_failed`,
        message: r.stderr || r.stdout || `swarmbox-addon ${args.join(' ')} failed`,
      });
      return true;
    }
    if (action !== 'remove') await runCommand(ADDON_BIN, ['prepare'], null, 60000);
    hub.broadcast(hub.buildSnapshot({ type: 'sysop' }));
    sendJson(res, 200, {
      ok: true,
      addon: addonName,
      action,
      message: r.stdout || `${addonName}: ${action} done`,
      config: readBoxConfigSnapshot(hc.listSnapshot()),
    });
    return true;
  }

  // Lightweight mobile touch/scroll/zoom gesture diagnostic log (bounded to 250 lines in SB_RUN_DIR)
  const touchLogPath = path.join(SB_RUN_DIR, 'touch-debug.jsonl');
  if (pathname === '/api/debug/touch' && req.method === 'GET') {
    let lines = [];
    try {
      lines = fs.readFileSync(touchLogPath, 'utf8').split('\n').filter(Boolean).slice(-250).map((l) => {
        try { return JSON.parse(l); } catch (_) { return { raw: l }; }
      });
    } catch (_) {}
    sendJson(res, 200, { path: touchLogPath, count: lines.length, events: lines });
    return true;
  }
  if (pathname === '/api/debug/touch' && req.method === 'POST') {
    const body = await readBody(req, 16 * 1024);
    try {
      fs.mkdirSync(SB_RUN_DIR, { recursive: true, mode: 0o700 });
      const rec = { ts: new Date().toISOString(), ...(body && typeof body === 'object' ? body : {}) };
      let existing = [];
      try { existing = fs.readFileSync(touchLogPath, 'utf8').split('\n').filter(Boolean); } catch (_) {}
      existing.push(JSON.stringify(rec));
      if (existing.length > 250) existing = existing.slice(-250);
      fs.writeFileSync(touchLogPath, existing.join('\n') + '\n', { mode: 0o600 });
    } catch (_) {}
    sendJson(res, 200, { ok: true });
    return true;
  }

  // Real swarmbox-sysop controls
  if (pathname === '/api/sysop/goal' && req.method === 'POST') {
    const body = await readBody(req);
    const goal = String(body.goal || '').trim();
    if (!goal) { sendJson(res, 400, { error: 'empty_goal', message: 'goal cannot be empty' }); return true; }
    if (body.terminal) writeActiveTab(String(body.terminal));
    const r = await runCommand(SYSOP_BIN, ['goal', '--source', 'web', '--', '-'], goal + '\n');
    if (!r.ok) {
      sendJson(res, r.code === 127 ? 503 : 502, {
        error: 'sysop_goal_failed',
        message: r.stderr || r.stdout || `swarmbox-sysop exited ${r.code}`,
      });
      return true;
    }
    hub.broadcast(hub.buildSnapshot({ type: 'sysop' }));
    sendJson(res, 200, { ok: true, goal_id: r.stdout, sysop: readSysopSnapshot(hc.listSnapshot()) });
    return true;
  }

  if (pathname === '/api/sysop/approve' && req.method === 'POST') {
    const r = await runCommand(SYSOP_BIN, ['approve']);
    hub.broadcast(hub.buildSnapshot({ type: 'sysop' }));
    if (!r.ok) { sendJson(res, 409, { error: 'approve_failed', message: r.stderr || r.stdout || 'nothing waiting' }); return true; }
    sendJson(res, 200, { ok: true, message: r.stdout || 'allowed' });
    return true;
  }

  if (pathname === '/api/sysop/veto' && req.method === 'POST') {
    const r = await runCommand(SYSOP_BIN, ['veto']);
    hub.broadcast(hub.buildSnapshot({ type: 'sysop' }));
    if (!r.ok) { sendJson(res, 409, { error: 'veto_failed', message: r.stderr || r.stdout || 'nothing waiting' }); return true; }
    sendJson(res, 200, { ok: true, message: r.stdout || 'cancelled' });
    return true;
  }

  // Repository context (sysop.autocontext): the text a session started with, or the current digest of a repository
  if (pathname === '/api/sysop/context' && req.method === 'GET') {
    const got = readContextText({ tab: url.searchParams.get('tab') || '', key: url.searchParams.get('key') || '' });
    if (!got) { sendJson(res, 404, { error: 'no_context', message: 'no repository context for that' }); return true; }
    sendJson(res, 200, { ok: true, ...got });
    return true;
  }

  // How far the digest is from a folder's commit (the New agent box says whether the session waits for a new one); writes nothing
  if (pathname === '/api/sysop/context/check' && req.method === 'GET') {
    const cwd = url.searchParams.get('cwd') || '';
    if (!cwd.startsWith('/') || !fs.existsSync(cwd)) { sendJson(res, 400, { error: 'bad_arg', message: 'an absolute folder is required' }); return true; }
    const r = await runCommand(SYSOP_BIN, ['context', '--check', cwd], null, 8000);
    let info = null;
    try { info = r.ok ? JSON.parse(r.stdout) : null; } catch (_) { info = null; }
    if (!info || typeof info !== 'object') { sendJson(res, 200, { ok: false }); return true; }
    sendJson(res, 200, {
      ok: true,
      need: typeof info.need === 'string' ? info.need : null,
      wait: info.wait === true,
      changes: Number.isFinite(info.changes) ? info.changes : null,
      at: Number.isFinite(info.at) ? info.at * 1000 : 0,
    });
    return true;
  }

  // Rewrite: the sysop writes the digest of the repository again now (the panel shows the call)
  if (pathname === '/api/sysop/context/rewrite' && req.method === 'POST') {
    const body = await readBody(req);
    const top = contextRepoTop(String(body.key || ''));
    if (!top) { sendJson(res, 404, { error: 'no_repo', message: 'no repository with that digest' }); return true; }
    // the tab that asked rides in the environment: an older sysop ignores it instead of refusing an unknown option
    const tab = String(body.tab || '');
    const env = { ...process.env, SWARMBOX_SYSOP_CONTEXT_TAB: /^[A-Za-z0-9_.:@-]{1,64}$/.test(tab) ? tab : '' };
    runCommandEnv(SYSOP_BIN, ['context', '--force', top], env, 180000).then(() => hub.broadcast(hub.buildSnapshot({ type: 'sysop' })));
    sendJson(res, 202, { ok: true });
    return true;
  }

  // The answer to the question the running goal asks (its brain's `ask`): swarmbox-sysop answer writes it where the goal waits for it
  if (pathname === '/api/sysop/answer' && req.method === 'POST') {
    const body = await readBody(req).catch(() => ({}));
    const answer = String((body && body.answer) || '').trim().slice(0, 1000);
    const qid = String((body && body.id) || '');
    if (!answer) { sendJson(res, 400, { error: 'empty_answer', message: 'the answer is empty' }); return true; }
    const args = ['answer'];
    if (/^q\d{1,6}$/.test(qid)) args.push('--id', qid);
    args.push('--', answer);
    const r = await runCommand(SYSOP_BIN, args);
    hub.broadcast(hub.buildSnapshot({ type: 'sysop' }));
    if (!r.ok) { sendJson(res, 409, { error: 'answer_failed', message: r.stderr || r.stdout || 'no question is waiting' }); return true; }
    sendJson(res, 200, { ok: true });
    return true;
  }

  // Pause, resume or cancel a schedule or a trigger of the sysop
  if (pathname === '/api/sysop/automation' && req.method === 'POST') {
    const body = await readBody(req).catch(() => ({}));
    const id = String((body && body.id) || '');
    const action = String((body && body.action) || '');
    if (!/^a\d{1,6}$/.test(id) || !['pause', 'resume', 'cancel'].includes(action)) {
      sendJson(res, 400, { error: 'bad_arg', message: 'id a<N> and action pause, resume or cancel are required' });
      return true;
    }
    const r = await runCommand(SYSOP_BIN, ['automation', action, id]);
    hub.broadcast(hub.buildSnapshot({ type: 'sysop' }));
    if (!r.ok) { sendJson(res, 409, { error: 'automation_failed', message: r.stderr || r.stdout || 'it could not be changed' }); return true; }
    sendJson(res, 200, { ok: true, message: r.stdout });
    return true;
  }

  if (pathname === '/api/sysop/new' && req.method === 'POST') {
    startNewConversation();
    hub.broadcast(hub.buildSnapshot({ type: 'sysop' }));
    sendJson(res, 200, { ok: true });
    return true;
  }

  if (pathname === '/api/sysop/stop' && req.method === 'POST') {
    const body = await readBody(req).catch(() => ({}));
    const rawId = body && body.goal_id ? String(body.goal_id).trim() : '';
    const goalId = /^[A-Za-z0-9._-]{1,64}$/.test(rawId) ? rawId : '';
    const r = await runCommand(SYSOP_BIN, goalId ? ['stop', goalId] : ['stop']);
    hub.broadcast(hub.buildSnapshot({ type: 'sysop' }));
    if (!r.ok) { sendJson(res, 409, { error: 'stop_failed', message: r.stderr || r.stdout || 'nothing to stop' }); return true; }
    sendJson(res, 200, { ok: true, message: r.stdout || 'stopped' });
    return true;
  }

  // -------------------------------------------------------------------------
  // Local File Preview API (read-only, rooted at HOME and /tmp)
  // -------------------------------------------------------------------------
  if (pathname === '/api/files/stat' && req.method === 'GET') {
    const p = url.searchParams.get('path') || '';
    const cwd = url.searchParams.get('cwd') || '';
    const fallbackDir = url.searchParams.get('fallbackDir') || '';
    const info = resolveAndStat(p, { cwd, fallbackDir, homeDir: HOME });
    if (!info.ok) { sendJson(res, info.status || 404, { ok: false, error: info.error, message: info.message }); return true; }
    sendJson(res, 200, info);
    return true;
  }

  if (pathname === '/api/files/list' && req.method === 'GET') {
    const p = url.searchParams.get('path') || '';
    const cwd = url.searchParams.get('cwd') || '';
    const fallbackDir = url.searchParams.get('fallbackDir') || '';
    const info = resolveAndStat(p, { cwd, fallbackDir, homeDir: HOME });
    if (!info.ok) { sendJson(res, info.status || 404, { ok: false, error: info.error, message: info.message }); return true; }
    if (info.kind !== 'dir') {
      sendJson(res, 400, { ok: false, error: 'not_a_directory', message: 'target is not a directory' });
      return true;
    }
    const listing = listDirectory(info.path, HOME);
    sendJson(res, 200, { ...info, ...listing });
    return true;
  }

  if (pathname === '/api/files/read' && req.method === 'GET') {
    const p = url.searchParams.get('path') || '';
    const cwd = url.searchParams.get('cwd') || '';
    const fallbackDir = url.searchParams.get('fallbackDir') || '';
    const info = resolveAndStat(p, { cwd, fallbackDir, homeDir: HOME });
    if (!info.ok) { sendJson(res, info.status || 404, { ok: false, error: info.error, message: info.message }); return true; }
    if (info.kind !== 'file') {
      sendJson(res, 400, { ok: false, error: 'not_a_file', message: 'target is a directory' });
      return true;
    }
    const read = readTextFile(info.path);
    sendJson(res, 200, { ...info, content: read.content, truncated: read.truncated, binary: read.binary });
    return true;
  }

  if (pathname.startsWith('/api/files/raw/') && (req.method === 'GET' || req.method === 'HEAD')) {
    const decoded = decodeRawPath(pathname.slice('/api/files/raw/'.length));
    const info = resolveAndStat(decoded, { homeDir: HOME });
    if (!info.ok) {
      res.writeHead(info.status || 404, { ...SECURITY_HEADERS, 'Content-Type': 'text/plain; charset=utf-8' });
      res.end(info.message || 'Not found');
      return true;
    }
    if (info.kind !== 'file') {
      res.writeHead(400, { ...SECURITY_HEADERS, 'Content-Type': 'text/plain; charset=utf-8' });
      res.end('Target is a directory');
      return true;
    }
    const forceDownload = url.searchParams.get('download') === '1';
    const headers = {
      ...sandboxHeadersForRaw(info.category, info.name, forceDownload),
      'Content-Type': info.mime || 'application/octet-stream',
      'Accept-Ranges': 'bytes',
    };
    const total = info.size;
    const range = req.headers.range;
    if (range && /^bytes=\d*-\d*$/.test(range) && total > 0) {
      const [startStr, endStr] = range.slice(6).split('-');
      const start = startStr ? parseInt(startStr, 10) : Math.max(0, total - parseInt(endStr, 10));
      const end = endStr ? Math.min(total - 1, parseInt(endStr, 10)) : total - 1;
      if (Number.isNaN(start) || Number.isNaN(end) || start > end || start >= total) {
        res.writeHead(416, { ...headers, 'Content-Range': `bytes */${total}` });
        res.end();
        return true;
      }
      res.writeHead(206, {
        ...headers,
        'Content-Range': `bytes ${start}-${end}/${total}`,
        'Content-Length': String(end - start + 1),
      });
      if (req.method === 'HEAD') { res.end(); return true; }
      fs.createReadStream(info.path, { start, end }).pipe(res);
      return true;
    }
    res.writeHead(200, { ...headers, 'Content-Length': String(total) });
    if (req.method === 'HEAD') { res.end(); return true; }
    fs.createReadStream(info.path).pipe(res);
    return true;
  }

  return false;
}
