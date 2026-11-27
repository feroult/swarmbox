// Resident worktree state, repository status polling, collision detection, and hybrid verify/push hub.

import fs from 'node:fs';
import path from 'node:path';
import {
  detectTerminalAgent,
  isHiddenTerminal,
  normalizeAgentName,
  readPins,
  readWorktreePrefs,
  terminalCwd,
  writePins,
} from './hc-client.mjs';
import { enrichTerminalsWithRepo, normRealPath, resolveGitRepoInfo } from './repo-discovery.mjs';

export function createWorktreeHub({ hc, runWt, eventClients, broadcast, buildSnapshot, typePrompt }) {
  let cachedWorktrees = [];
  let wtRefreshing = false;
  let repoStatusRefreshing = false;
  const repoStatuses = new Map();
  const verifyJobs = new Map();

  // Worktrees whose tab is being closed. Between the kill and the auto-clean decision the hc events broadcast
  // snapshots in which the worktree has no live terminal; without this hold it shows as pending for a moment and
  // the sidebar flickers (the pending pill appears and goes). Keys are real paths taken while the folder exists.
  const closingWorktrees = new Set();

  // Drop a worktree that was just removed from the cached list, so no snapshot sent before the next `list` refresh
  // reports it as pending. Pass the real path too when it was taken before the folder went away.
  function forgetCachedWorktree(...paths) {
    const gone = new Set();
    for (const p of paths) {
      const raw = String(p || '').replace(/\/+$/, '');
      if (raw) { gone.add(raw); gone.add(normRealPath(raw)); }
    }
    if (gone.size === 0) return;
    cachedWorktrees = cachedWorktrees.filter((w) => {
      const wp = String((w && w.path) || '').replace(/\/+$/, '');
      return !gone.has(wp) && !gone.has(normRealPath(wp));
    });
  }

  function formatMainAgent(term) {
    if (!term) return null;
    return {
      address: term.address,
      title: (term.labels && term.labels['swarmbox.title']) || term.name || 'main',
    };
  }

  function findMainAgentTerminal(repoRoot, rawTerminals) {
    const targetReal = normRealPath(repoRoot);
    if (!targetReal) return null;
    for (const t of rawTerminals || []) {
      if (!t || isHiddenTerminal(t)) continue;
      if (t.state && t.state !== 'live') continue;
      const lbls = t.labels || {};
      if (lbls['swarmbox.worktree']) continue;
      const lblAgent = String(lbls['swarmbox.agent'] || '').toLowerCase().trim();
      const detected = detectTerminalAgent(t);
      const hasAgent = Boolean(detected) || Boolean(normalizeAgentName(lblAgent));
      if (!hasAgent) continue;

      const cwd = terminalCwd(t);
      if (cwd) {
        const info = resolveGitRepoInfo(cwd);
        if (info) {
          if (info.is_worktree) continue;
          if (normRealPath(info.root) === targetReal) return t;
          continue;
        }
      }
      const lblRepo = lbls['swarmbox.repo'] ? normRealPath(String(lbls['swarmbox.repo'])) : '';
      if (lblRepo && lblRepo === targetReal) return t;
      const cwdReal = normRealPath(cwd);
      if (cwdReal && (cwdReal === targetReal || cwdReal.startsWith(targetReal + path.sep))) {
        return t;
      }
    }
    return null;
  }

  function buildRepoStatusesSnapshot(rawTerminals) {
    const repo_statuses = {};
    for (const [k, st] of repoStatuses.entries()) {
      const mainTerm = findMainAgentTerminal(k, rawTerminals);
      repo_statuses[k] = {
        ...st,
        verify_job: verifyJobs.get(k) || null,
        main_agent: formatMainAgent(mainTerm),
      };
    }
    return repo_statuses;
  }

  async function refreshRepoStatus(repoRoot, opts = {}) {
    if (!repoRoot) return null;
    const rawKey = String(repoRoot).replace(/\/+$/, '') || String(repoRoot);
    try {
      const st = await runWt(['repo-status', rawKey]);
      if (!st || typeof st !== 'object') return null;
      const key = (st.repo_root && String(st.repo_root).replace(/\/+$/, '')) || rawKey;
      const prev = repoStatuses.get(key);
      const mainTerm = findMainAgentTerminal(key, hc.listSnapshot());
      const merged = {
        ...st,
        verify_job: verifyJobs.get(key) || verifyJobs.get(rawKey) || null,
        main_agent: formatMainAgent(mainTerm),
      };
      repoStatuses.set(key, merged);
      if (eventClients.size > 0 && JSON.stringify(prev || null) !== JSON.stringify(merged)) {
        broadcast(buildSnapshot({ type: 'snapshot' }));
      }
      return merged;
    } catch (err) {
      if (opts.throwOnError) throw err;
      return null;
    }
  }

  function refreshAllRepoStatuses(rawTerminals, pins) {
    if (repoStatusRefreshing) return;
    const roots = new Set();
    const enriched = enrichTerminalsWithRepo(rawTerminals || []);
    for (const t of enriched) {
      const r = (t.repo && t.repo.root) || (t.labels && t.labels['swarmbox.repo']) || '';
      if (r) roots.add(String(r).replace(/\/+$/, '') || String(r));
    }
    for (const pin of pins || []) {
      const r = (pin && pin.worktree && pin.worktree.repo) || '';
      if (r) {
        roots.add(String(r).replace(/\/+$/, '') || String(r));
      } else if (pin && pin.cwd) {
        const info = resolveGitRepoInfo(pin.cwd);
        if (info && info.root) roots.add(String(info.root).replace(/\/+$/, '') || String(info.root));
      }
    }
    for (const w of cachedWorktrees || []) {
      if (w && w.repo_root) roots.add(String(w.repo_root).replace(/\/+$/, '') || String(w.repo_root));
    }
    if (roots.size === 0) return;

    repoStatusRefreshing = true;
    Promise.allSettled(
      Array.from(roots).map(async (root) => {
        const st = await runWt(['repo-status', root]);
        if (!st || typeof st !== 'object') return false;
        const key = (st.repo_root && String(st.repo_root).replace(/\/+$/, '')) || root;
        const prev = repoStatuses.get(key);
        const mainTerm = findMainAgentTerminal(key, hc.listSnapshot());
        const merged = {
          ...st,
          verify_job: verifyJobs.get(key) || verifyJobs.get(root) || null,
          main_agent: formatMainAgent(mainTerm),
        };
        repoStatuses.set(key, merged);
        return JSON.stringify(prev || null) !== JSON.stringify(merged);
      })
    )
      .then((results) => {
        const changed = results.some((r) => r.status === 'fulfilled' && r.value === true);
        if (changed && eventClients.size > 0) {
          broadcast(buildSnapshot({ type: 'snapshot' }));
        }
      })
      .finally(() => {
        repoStatusRefreshing = false;
      });
  }

  function buildVerifyHandoffPrompt(context = {}, verifyCmd = '') {
    const branches = Array.isArray(context.mergedBranches) ? context.mergedBranches.filter(Boolean) : [];
    const commits = Array.isArray(context.commitsSummary) ? context.commitsSummary.filter(Boolean) : [];
    const files = Array.isArray(context.files) ? context.files.filter(Boolean) : [];
    const parts = [];
    if (branches.length === 1) {
      parts.push(`Merged branch ${branches[0]} into main.`);
    } else if (branches.length > 1) {
      parts.push(`Merged branches ${branches.join(', ')} into main.`);
    } else {
      parts.push('Local commits on main are ready for verification.');
    }
    if (commits.length > 0) {
      const sample = commits.slice(0, 6).join('; ');
      parts.push(`Commits: ${sample}${commits.length > 6 ? ` (+${commits.length - 6} more)` : ''}.`);
    }
    if (files.length > 0) {
      const sample = files.slice(0, 8).join(', ');
      parts.push(`Changed files: ${sample}${files.length > 8 ? ` (+${files.length - 8} more)` : ''}.`);
    }
    const shouldPush = context.push !== undefined ? Boolean(context.push) : true;
    if (shouldPush) {
      if (verifyCmd) {
        parts.push(`Please run the project verification (\`${verifyCmd}\`) and any relevant tests. If everything passes, push main to origin. If anything fails, fix or report the failure before pushing.`);
      } else {
        parts.push('Please run the project verification/tests. If everything passes, push main to origin. If anything fails, fix or report the failure before pushing.');
      }
    } else if (verifyCmd) {
      parts.push(`Please run the project verification (\`${verifyCmd}\`) and any relevant tests to confirm integration on main. Do not push yet; report the result (or fix any failure) so the user can review and push when ready.`);
    } else {
      parts.push('Please run the project verification/tests to confirm integration on main. Do not push yet; report the result (or fix any failure) so the user can review and push when ready.');
    }
    return parts.join(' ');
  }

  async function runHybridVerifyAndPush(repoRoot, context = {}) {
    const shouldPush = context.push !== undefined ? Boolean(context.push) : true;
    const rawKey = String(repoRoot || '').replace(/\/+$/, '') || String(repoRoot || '');
    const rawTerminals = hc.listSnapshot();
    const mainTerm = findMainAgentTerminal(rawKey, rawTerminals);
    let repoSt = repoStatuses.get(rawKey) || null;
    if (!repoSt && !context.verifyCmd && rawKey) {
      repoSt = await refreshRepoStatus(rawKey).catch(() => null);
    }
    const key = (repoSt && repoSt.repo_root && String(repoSt.repo_root).replace(/\/+$/, '')) || rawKey;
    const verifyCmd = String(context.verifyCmd || (repoSt && repoSt.verify_cmd) || '').trim();

    if (mainTerm) {
      const prompt = buildVerifyHandoffPrompt({ ...context, push: shouldPush }, verifyCmd);
      await typePrompt(mainTerm.address, prompt);
      return {
        mode: 'agent',
        push: shouldPush,
        terminal: mainTerm.address,
        title: (mainTerm.labels && mainTerm.labels['swarmbox.title']) || mainTerm.name || 'main',
      };
    }

    if (verifyCmd) {
      const job = {
        state: 'running',
        cmd: verifyCmd,
        push: shouldPush,
        started_at: Date.now(),
        finished_at: null,
        exit_code: null,
        output: '',
        error: null,
        merged_branches: Array.isArray(context.mergedBranches) ? [...context.mergedBranches] : [],
      };
      verifyJobs.set(key, job);
      if (repoSt) {
        repoStatuses.set(key, { ...repoSt, verify_job: job });
      }
      broadcast(buildSnapshot({ type: 'snapshot' }));

      Promise.resolve()
        .then(async () => {
          let verifyRes = null;
          try {
            verifyRes = await runWt(['verify', key], 190000);
          } catch (err) {
            const d = (err && err.data) || {};
            verifyJobs.set(key, {
              ...job,
              state: 'failed',
              finished_at: Date.now(),
              exit_code: d.exit_code != null ? d.exit_code : 1,
              output: d.output || err.message || '',
              error: err.message || 'verification failed',
            });
            return;
          }

          if (verifyRes && verifyRes.ok === true) {
            if (!shouldPush) {
              verifyJobs.set(key, {
                ...job,
                state: 'passed',
                finished_at: Date.now(),
                exit_code: verifyRes.exit_code != null ? verifyRes.exit_code : 0,
                output: verifyRes.output || '',
                error: null,
              });
              return;
            }
            try {
              await runWt(['push', key]);
              verifyJobs.set(key, {
                ...job,
                state: 'pushed',
                finished_at: Date.now(),
                exit_code: verifyRes.exit_code != null ? verifyRes.exit_code : 0,
                output: verifyRes.output || '',
                error: null,
              });
            } catch (pushErr) {
              verifyJobs.set(key, {
                ...job,
                state: 'passed',
                finished_at: Date.now(),
                exit_code: verifyRes.exit_code != null ? verifyRes.exit_code : 0,
                output: verifyRes.output || '',
                error: pushErr.message || 'push failed',
              });
            }
          } else {
            verifyJobs.set(key, {
              ...job,
              state: 'failed',
              finished_at: Date.now(),
              exit_code: (verifyRes && verifyRes.exit_code != null) ? verifyRes.exit_code : 1,
              output: (verifyRes && verifyRes.output) || '',
              error: (verifyRes && (verifyRes.msg || verifyRes.error)) || 'verification failed',
            });
          }
        })
        .finally(async () => {
          await refreshRepoStatus(key).catch(() => {});
          broadcast(buildSnapshot({ type: 'snapshot' }));
        });

      return { mode: 'backend_verify', push: shouldPush, cmd: verifyCmd, state: 'running' };
    }

    return {
      mode: 'manual_push',
      push: shouldPush,
      message: 'Merged locally. No agent on main or check script detected; verify and push when ready.',
    };
  }

  function refreshPendingWorktrees() {
    if (wtRefreshing) return;
    wtRefreshing = true;
    runWt(['list'])
      .then((list) => {
        if (Array.isArray(list)) {
          const prev = JSON.stringify(cachedWorktrees);
          cachedWorktrees = list;
          if (JSON.stringify(cachedWorktrees) !== prev && eventClients.size > 0) {
            broadcast(buildSnapshot({ type: 'worktrees' }));
          }
        }
      })
      .catch(() => {})
      .finally(() => {
        wtRefreshing = false;
      });
  }

  function purgePinsForWorktree(wtPath, pinId = '') {
    let wtReal = wtPath || '';
    if (wtReal) {
      try { wtReal = fs.realpathSync(wtReal); } catch (_) {}
    }
    const curPins = readPins();
    const kept = curPins.filter((p) => {
      if (!p) return false;
      if (pinId && p.id === pinId) return false;
      if (wtReal) {
        const pPaths = [p.cwd, p.worktree && p.worktree.path].filter(Boolean);
        for (const pp of pPaths) {
          let rp = pp;
          try { rp = fs.realpathSync(pp); } catch (_) {}
          if (rp === wtReal || pp === wtPath) return false;
        }
      }
      return true;
    });
    if (kept.length !== curPins.length) writePins(kept);
  }

  async function closeTerminalCleanly(tid) {
    if (!tid) return;
    await hc.call('terminal.keep', { terminal: tid, keep: false }).catch(() => {});
    await hc.call('terminal.kill', { terminal: tid }).catch(() => {});
    hc.call('terminal.rm', { terminal: tid }).catch(() => {});
    hc.terminals.delete(tid);
  }

  function pendingWorktreesFor(terminals, pins) {
    const livePaths = new Set();
    for (const t of terminals || []) {
      const p = (t.labels && t.labels['swarmbox.worktree']) || terminalCwd(t);
      if (p) {
        try { livePaths.add(fs.realpathSync(p)); } catch (_) { livePaths.add(p); }
      }
    }
    const pinnedPaths = new Set();
    for (const pin of pins || []) {
      const p = (pin.worktree && pin.worktree.path) || pin.cwd;
      if (p) {
        try { pinnedPaths.add(fs.realpathSync(p)); } catch (_) { pinnedPaths.add(p); }
      }
    }
    return cachedWorktrees.filter((w) => {
      let rp = w.path;
      try { rp = fs.realpathSync(w.path); } catch (_) {}
      return !livePaths.has(rp) && !pinnedPaths.has(rp) && !closingWorktrees.has(rp) && !closingWorktrees.has(w.path);
    });
  }

  async function inspectWorkingTreeForCwd(targetCwd, terminals, excludeAddr = null) {
    const prefs = readWorktreePrefs();
    const empty = {
      cwd: targetCwd || '',
      is_git: false,
      repo_root: null,
      repo_name: null,
      branch: null,
      worktree_path: null,
      dirty: false,
      collision: null,
      prefs,
    };
    if (!targetCwd || !fs.existsSync(targetCwd)) return empty;
    let targetInfo;
    try {
      targetInfo = await runWt(['inspect', targetCwd]);
    } catch (_) {
      return empty;
    }
    if (!targetInfo || !targetInfo.is_git) return empty;
    const targetWt = targetInfo.worktree_path;
    const branch = targetInfo.branch || targetInfo.base || 'HEAD';
    const colliding = [];
    for (const t of terminals || []) {
      if (excludeAddr && t.address === excludeAddr) continue;
      const agentKind = detectTerminalAgent(t);
      if (!agentKind) continue;
      const tCwd = terminalCwd(t);
      if (!tCwd) continue;
      let tReal = tCwd;
      try { tReal = fs.realpathSync(tCwd); } catch (_) {}
      if (tReal === targetWt || tReal.startsWith(targetWt + path.sep)) {
        colliding.push({
          address: t.address,
          name: (t.labels && t.labels['swarmbox.title']) || t.name || t.address,
          agent: agentKind,
        });
      }
    }
    const collision = colliding.length > 0 ? {
      repo_root: targetInfo.repo_root,
      repo_name: targetInfo.repo_name,
      branch,
      worktree_path: targetWt,
      dirty: Boolean(targetInfo.dirty),
      active_tabs: colliding,
    } : null;
    return {
      cwd: targetCwd,
      is_git: true,
      repo_root: targetInfo.repo_root,
      repo_name: targetInfo.repo_name,
      branch,
      worktree_path: targetWt,
      dirty: Boolean(targetInfo.dirty),
      collision,
      prefs,
    };
  }

  async function detectWorkingTreeCollision(targetCwd, terminals, excludeAddr = null) {
    const info = await inspectWorkingTreeForCwd(targetCwd, terminals, excludeAddr);
    return info.collision;
  }

  return {
    closingWorktrees,
    verifyJobs,
    setCachedWorktrees(list) {
      cachedWorktrees = Array.isArray(list) ? list : [];
      return cachedWorktrees;
    },
    getCachedWorktrees() {
      return cachedWorktrees;
    },
    forgetCachedWorktree,
    formatMainAgent,
    findMainAgentTerminal,
    buildRepoStatusesSnapshot,
    refreshRepoStatus,
    refreshAllRepoStatuses,
    buildVerifyHandoffPrompt,
    runHybridVerifyAndPush,
    refreshPendingWorktrees,
    purgePinsForWorktree,
    closeTerminalCleanly,
    pendingWorktreesFor,
    inspectWorkingTreeForCwd,
    detectWorkingTreeCollision,
  };
}
