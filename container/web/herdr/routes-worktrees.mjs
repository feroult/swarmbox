// HTTP routes for Git worktrees (/api/worktrees/*), projects (/api/projects), and folder browsing (/api/dirs).

import fs from 'node:fs';
import path from 'node:path';
import {
  HOME,
  buildAgentArgv,
  normalizeAgentName,
  readPins,
  readRecentDirs,
  readWorktreePrefs,
  resolveDefaultAgent,
  terminalCwd,
  uniqueTabName,
  writeActiveTab,
  writeWorktreePrefs,
} from './hc-client.mjs';
import {
  describeDir,
  discoverProjects,
  listChildDirs,
  listRecentDirs,
  normRealPath,
} from './repo-discovery.mjs';
import { readBody, resolveWorktreeTarget, sendJson } from './http-utils.mjs';

export async function handleWorktreeRoutes(req, res, url, pathname, { hc, hub, worktreeHub, ptyBridge, runWt }) {
  if (pathname === '/api/worktrees' && req.method === 'GET') {
    try {
      const list = await runWt(['list']);
      const worktrees = worktreeHub.setCachedWorktrees(list);
      sendJson(res, 200, {
        worktrees,
        pending: worktreeHub.pendingWorktreesFor(hc.listSnapshot(), readPins()),
        prefs: readWorktreePrefs(),
      });
    } catch (err) {
      sendJson(res, 500, { error: err.code || 'worktree_error', message: err.message });
    }
    return true;
  }

  if (pathname === '/api/projects' && req.method === 'GET') {
    const live = hc.listSnapshot();
    const pinsNow = readPins();
    const projects = discoverProjects(live, pinsNow);
    const recent = listRecentDirs(live, pinsNow, readRecentDirs());
    sendJson(res, 200, { projects, recent, home: HOME });
    return true;
  }

  if (pathname === '/api/dirs' && req.method === 'GET') {
    const raw = url.searchParams.get('path') || HOME;
    const listing = listChildDirs(raw.startsWith('/') ? raw : HOME);
    if (!listing) { sendJson(res, 404, { error: 'not_a_dir', message: `Not a readable folder: ${raw}` }); return true; }
    sendJson(res, 200, { ...listing, home: HOME, self: describeDir(listing.path) });
    return true;
  }

  if (pathname === '/api/worktrees/check' && req.method === 'GET') {
    const rawCwd = url.searchParams.get('cwd') || '';
    const cwd = rawCwd && rawCwd.startsWith('/') ? rawCwd : HOME;
    const info = await worktreeHub.inspectWorkingTreeForCwd(cwd, hc.listSnapshot());
    sendJson(res, 200, info);
    return true;
  }

  if (pathname === '/api/worktrees/prefs' && req.method === 'PATCH') {
    const body = await readBody(req);
    try {
      const prefs = writeWorktreePrefs(body);
      hub.broadcast(hub.buildSnapshot({ type: 'snapshot' }));
      sendJson(res, 200, { ok: true, prefs });
    } catch (err) {
      sendJson(res, 400, { error: 'bad_prefs', message: err.message });
    }
    return true;
  }

  if (pathname === '/api/worktrees/status' && req.method === 'GET') {
    const { target } = resolveWorktreeTarget(url.searchParams.get('path'), url.searchParams.get('terminal') || '', hc);
    if (!target) { sendJson(res, 400, { error: 'bad_arg', message: 'path or terminal required' }); return true; }
    try {
      const st = await runWt(['status', target]);
      sendJson(res, 200, st);
    } catch (err) {
      sendJson(res, 404, { error: err.code || 'not_a_worktree', message: err.message });
    }
    return true;
  }

  if (pathname === '/api/worktrees/repo-status' && req.method === 'GET') {
    const repo = url.searchParams.get('repo') || '';
    if (!repo) { sendJson(res, 400, { error: 'bad_arg', message: 'repo required' }); return true; }
    try {
      const st = await worktreeHub.refreshRepoStatus(repo, { throwOnError: true });
      const mainTerm = worktreeHub.findMainAgentTerminal((st && st.repo_root) || repo, hc.listSnapshot());
      sendJson(res, 200, {
        ...(st || {}),
        main_agent: worktreeHub.formatMainAgent(mainTerm),
      });
    } catch (err) {
      sendJson(res, 404, { error: err.code || 'repo_status_error', message: err.message });
    }
    return true;
  }

  if (pathname === '/api/worktrees/diff' && req.method === 'GET') {
    const { target: wtPath } = resolveWorktreeTarget(url.searchParams.get('path'), url.searchParams.get('terminal') || '', hc);
    if (!wtPath) { sendJson(res, 400, { error: 'bad_arg', message: 'path or terminal required' }); return true; }
    const file = url.searchParams.get('file') || '';
    try {
      const diffRes = await runWt(['diff', wtPath, ...(file ? ['--file', file] : [])]);
      sendJson(res, 200, diffRes);
    } catch (err) {
      sendJson(res, 404, { error: err.code || 'diff_error', message: err.message });
    }
    return true;
  }

  if (pathname === '/api/worktrees/sync' && req.method === 'POST') {
    const body = await readBody(req);
    const tid = body.terminal ? String(body.terminal) : '';
    const { target: wtPath, terminal: t } = resolveWorktreeTarget(body.path, tid, hc);
    if (!wtPath) { sendJson(res, 400, { error: 'bad_arg', message: 'path or terminal required' }); return true; }
    const args = ['sync', wtPath];
    if (body.rebase) args.push('--rebase');
    try {
      const resSync = await runWt(args);
      const repoRoot = (resSync && resSync.repo_root) || (t && t.labels && t.labels['swarmbox.repo']) || '';
      if (repoRoot) await worktreeHub.refreshRepoStatus(repoRoot).catch(() => {});
      worktreeHub.refreshPendingWorktrees();
      hub.broadcast(hub.buildSnapshot({ type: 'snapshot' }));
      sendJson(res, 200, resSync);
    } catch (err) {
      sendJson(res, 409, { error: err.code || 'sync_failed', message: err.message, ...(err.data || {}) });
    }
    return true;
  }

  if (pathname === '/api/worktrees/merge' && req.method === 'POST') {
    const body = await readBody(req);
    const tid = body.terminal ? String(body.terminal) : '';
    const { target: wtPath, terminal: t } = resolveWorktreeTarget(body.path, tid, hc);
    if (!wtPath) { sendJson(res, 400, { error: 'bad_arg', message: 'path or terminal required' }); return true; }
    const args = ['merge', wtPath];
    if (body.squash) args.push('--squash');
    if (body.clean) args.push('--clean');
    try {
      const resMerge = await runWt(args);
      if (body.clean) {
        const pinId = (t && t.labels && t.labels['swarmbox.pin_id']) || '';
        worktreeHub.purgePinsForWorktree(wtPath, pinId);
        worktreeHub.forgetCachedWorktree(wtPath);
        if (tid) await worktreeHub.closeTerminalCleanly(tid);
      }
      const repoRoot = (resMerge && resMerge.repo_root) || (t && t.labels && t.labels['swarmbox.repo']) || '';
      if (repoRoot) await worktreeHub.refreshRepoStatus(repoRoot).catch(() => {});
      const doVerify = Boolean(body.verify || body.verify_and_push);
      const doPush = Boolean(body.push || body.verify_and_push);
      let handoff = null;
      if (doVerify && repoRoot) {
        handoff = await worktreeHub.runHybridVerifyAndPush(repoRoot, {
          mergedBranches: resMerge && resMerge.branch ? [resMerge.branch] : [],
          commitsSummary: (resMerge && Array.isArray(resMerge.commits_list)) ? resMerge.commits_list : [],
          files: (resMerge && Array.isArray(resMerge.files)) ? resMerge.files : [],
          push: doPush,
        });
      }
      worktreeHub.refreshPendingWorktrees();
      hub.broadcast(hub.buildSnapshot({ type: 'snapshot' }));
      sendJson(res, 200, handoff ? { ...resMerge, handoff } : resMerge);
    } catch (err) {
      sendJson(res, 409, { error: err.code || 'merge_failed', message: err.message, ...(err.data || {}) });
    }
    return true;
  }

  if (pathname === '/api/worktrees/merge-all' && req.method === 'POST') {
    const body = await readBody(req);
    const repo = String(body.repo || '');
    if (!repo) { sendJson(res, 400, { error: 'bad_arg', message: 'repo required' }); return true; }
    const repoReal = normRealPath(repo);
    let list = [];
    try {
      const rawList = await runWt(['list', repo]);
      list = Array.isArray(rawList) ? rawList : [];
    } catch (err) {
      sendJson(res, 500, { error: err.code || 'list_failed', message: err.message });
      return true;
    }

    const liveTerms = hc.listSnapshot();
    const termByWtPath = new Map();
    for (const t of liveTerms) {
      const p = (t.labels && t.labels['swarmbox.worktree']) || terminalCwd(t);
      if (p) {
        const rp = normRealPath(p);
        if (!termByWtPath.has(rp)) termByWtPath.set(rp, []);
        termByWtPath.get(rp).push(t);
      }
    }

    const candidates = list.filter((w) => {
      if (!w || !w.path) return false;
      if (w.repo_root && normRealPath(w.repo_root) !== repoReal) return false;
      return !w.dirty && Number(w.ahead) > 0 && Boolean(w.can_merge);
    });

    const merged = [];
    const failed = [];
    const mergedBranches = [];
    const commitsSummary = [];
    const filesSet = new Set();

    for (const w of candidates) {
      const args = ['merge', w.path];
      if (body.squash) args.push('--squash');
      if (body.clean) args.push('--clean');
      try {
        const resMerge = await runWt(args);
        merged.push({ ...resMerge, path: w.path, branch: (resMerge && resMerge.branch) || w.branch });
        if ((resMerge && resMerge.branch) || w.branch) {
          mergedBranches.push((resMerge && resMerge.branch) || w.branch);
        }
        if (resMerge && Array.isArray(resMerge.commits_list)) {
          commitsSummary.push(...resMerge.commits_list);
        }
        if (resMerge && Array.isArray(resMerge.files)) {
          for (const f of resMerge.files) filesSet.add(f);
        }
        if (body.clean) {
          worktreeHub.forgetCachedWorktree(w.path);
          const matchingTerms = termByWtPath.get(normRealPath(w.path)) || [];
          if (matchingTerms.length > 0) {
            for (const mt of matchingTerms) {
              const pinId = (mt.labels && mt.labels['swarmbox.pin_id']) || '';
              worktreeHub.purgePinsForWorktree(w.path, pinId);
              await worktreeHub.closeTerminalCleanly(mt.address);
            }
          } else {
            worktreeHub.purgePinsForWorktree(w.path, '');
          }
        }
      } catch (err) {
        failed.push({
          path: w.path,
          branch: w.branch,
          error: err.code || 'merge_failed',
          message: err.message,
          ...(err.data || {}),
        });
        break;
      }
    }

    await worktreeHub.refreshRepoStatus(repo).catch(() => {});
    const doVerifyAll = Boolean(body.verify || body.verify_and_push);
    const doPushAll = Boolean(body.push || body.verify_and_push);
    let handoff = null;
    if (merged.length > 0 && doVerifyAll) {
      handoff = await worktreeHub.runHybridVerifyAndPush(repo, {
        mergedBranches,
        commitsSummary,
        files: Array.from(filesSet),
        push: doPushAll,
      });
    }
    worktreeHub.refreshPendingWorktrees();
    hub.broadcast(hub.buildSnapshot({ type: 'snapshot' }));
    sendJson(res, 200, { ok: true, merged, failed, handoff });
    return true;
  }

  if (pathname === '/api/worktrees/main/action' && req.method === 'POST') {
    const body = await readBody(req);
    const repo = String(body.repo || '');
    const action = String(body.action || '');
    if (!repo || !action) {
      sendJson(res, 400, { error: 'bad_arg', message: 'repo and action required' });
      return true;
    }
    const key = repo.replace(/\/+$/, '') || repo;

    if (action === 'commit') {
      const mainTerm = worktreeHub.findMainAgentTerminal(key, hc.listSnapshot());
      if (!mainTerm) {
        sendJson(res, 409, { error: 'no_main_agent', message: 'No active agent terminal on main for this repository' });
        return true;
      }
      const prompt = 'Review the uncommitted changes on main, run relevant tests if needed, and create a clean git commit.';
      const r = await ptyBridge.typePrompt(mainTerm.address, prompt);
      sendJson(res, 200, { ok: true, action: 'commit', terminal: mainTerm.address, result: r });
      return true;
    }

    if (action === 'verify' || action === 'verify_and_push') {
      await worktreeHub.refreshRepoStatus(key).catch(() => {});
      const handoff = await worktreeHub.runHybridVerifyAndPush(key, {
        mergedBranches: [],
        push: action === 'verify_and_push',
      });
      sendJson(res, 200, { ok: true, action, handoff });
      return true;
    }

    if (action === 'push') {
      try {
        const r = await runWt(['push', key]);
        const curJob = worktreeHub.verifyJobs.get(key);
        if (curJob && curJob.state === 'passed') {
          worktreeHub.verifyJobs.set(key, { ...curJob, state: 'pushed', error: null, finished_at: Date.now() });
        }
        await worktreeHub.refreshRepoStatus(key).catch(() => {});
        hub.broadcast(hub.buildSnapshot({ type: 'snapshot' }));
        sendJson(res, 200, { ok: true, ...(r || {}) });
      } catch (err) {
        sendJson(res, 409, { error: err.code || 'push_failed', message: err.message, ...(err.data || {}) });
      }
      return true;
    }

    if (action === 'undo_merge') {
      try {
        const r = await runWt(['undo-merge', key]);
        const curJob = worktreeHub.verifyJobs.get(key);
        if (curJob && curJob.state === 'failed') worktreeHub.verifyJobs.delete(key);
        const rKey = (r && r.repo_root && String(r.repo_root).replace(/\/+$/, '')) || '';
        if (rKey && worktreeHub.verifyJobs.get(rKey) && worktreeHub.verifyJobs.get(rKey).state === 'failed') {
          worktreeHub.verifyJobs.delete(rKey);
        }
        await worktreeHub.refreshRepoStatus(key).catch(() => {});
        hub.broadcast(hub.buildSnapshot({ type: 'snapshot' }));
        sendJson(res, 200, { ok: true, ...(r || {}) });
      } catch (err) {
        sendJson(res, 409, { error: err.code || 'undo_merge_failed', message: err.message, ...(err.data || {}) });
      }
      return true;
    }

    sendJson(res, 400, { error: 'unknown_action', message: `unsupported action: ${action}` });
    return true;
  }

  if (pathname === '/api/worktrees/remove' && req.method === 'POST') {
    const body = await readBody(req);
    const wtPath = String(body.path || '');
    if (!wtPath) { sendJson(res, 400, { error: 'bad_arg', message: 'path required' }); return true; }
    const args = ['remove', wtPath];
    if (body.force) args.push('--force');
    try {
      const r = await runWt(args);
      const tid = body.terminal ? String(body.terminal) : '';
      const t = tid ? hc.terminals.get(tid) : null;
      const pinId = (t && t.labels && t.labels['swarmbox.pin_id']) || '';
      worktreeHub.purgePinsForWorktree(wtPath, pinId);
      worktreeHub.forgetCachedWorktree(wtPath);
      if (tid) await worktreeHub.closeTerminalCleanly(tid);
      const repoRoot = (r && r.repo_root) || (t && t.labels && t.labels['swarmbox.repo']) || '';
      if (repoRoot) await worktreeHub.refreshRepoStatus(repoRoot).catch(() => {});
      worktreeHub.refreshPendingWorktrees();
      hub.broadcast(hub.buildSnapshot({ type: 'snapshot' }));
      sendJson(res, 200, r);
    } catch (err) {
      sendJson(res, 409, { error: err.code || 'remove_failed', message: err.message });
    }
    return true;
  }

  if (pathname === '/api/worktrees/open' && req.method === 'POST') {
    const body = await readBody(req);
    const wtPath = String(body.path || '');
    if (!wtPath || !fs.existsSync(wtPath)) {
      sendJson(res, 404, { error: 'missing_path', message: 'worktree folder does not exist' });
      return true;
    }
    const st = await runWt(['status', wtPath]).catch(() => null);
    // The agent asked for, else the default agent of the box, else a shell: never an agent the box may not have.
    const reqAgent = String(body.agent || '').trim().toLowerCase();
    const cmd = normalizeAgentName(reqAgent) || resolveDefaultAgent() || (reqAgent === 'yolo' ? 'yolo' : '') || 'shell';
    const argv = buildAgentArgv(cmd, 'continue');
    const labels = {
      'swarmbox.agent': cmd,
      'swarmbox.worktree': wtPath,
    };
    if (st) {
      if (st.branch) labels['swarmbox.branch'] = st.branch;
      if (st.base) labels['swarmbox.base'] = st.base;
      if (st.repo_root) labels['swarmbox.repo'] = st.repo_root;
    }
    const name = uniqueTabName(st && st.branch ? st.branch.replace(/^sb\//, '') : path.basename(wtPath), cmd, Array.from(hc.terminals.values()));
    const created = await hc.call('terminal.run', { argv, name, cwd: wtPath, keep: true, no_parent: true, labels });
    const createdTerm = (created && created.terminal) || created;
    const addr = createdTerm && createdTerm.address;
    if (addr) {
      writeActiveTab(addr);
      hc.terminals.set(addr, createdTerm);
    }
    worktreeHub.refreshPendingWorktrees();
    hub.broadcast(hub.buildSnapshot({ type: 'snapshot' }));
    sendJson(res, 201, { ...(createdTerm || {}), terminal: createdTerm });
    return true;
  }

  if ((pathname === '/api/worktrees/commit' || pathname === '/api/worktrees/resolve-conflict') && req.method === 'POST') {
    const body = await readBody(req);
    const tid = String(body.terminal || '');
    if (!tid) { sendJson(res, 400, { error: 'bad_arg', message: 'terminal required' }); return true; }
    const base = String(body.base || 'main');
    const prompt = pathname.endsWith('/commit')
      ? 'Review our uncommitted changes in this worktree, run tests if relevant, and create a clean git commit.'
      : `Pull ${base} into this worktree branch (git merge ${base}), resolve any merge conflicts preserving both intents, run tests, and commit the resolution.`;
    const r = await ptyBridge.typePrompt(tid, prompt);
    sendJson(res, 200, { ok: true, result: r });
    return true;
  }

  return false;
}
