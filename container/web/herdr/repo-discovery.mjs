// Repository discovery and directory browsing for the SwarmBox Web Studio.
// Zero-subprocess Git repo resolver (cached 2s per cwd) and folder listings.

import fs from 'node:fs';
import path from 'node:path';
import { HOME, detectTerminalAgent, terminalCwd } from './hc-client.mjs';

export function normRealPath(p) {
  if (!p || typeof p !== 'string') return '';
  try { return fs.realpathSync(p); } catch (_) { return p.replace(/\/+$/, '') || '/'; }
}

// Fast, zero-subprocess Git repository resolver (cached 2s per cwd) so Web UI can group
// main-checkout and worktree agent tabs under their parent repository cleanly.
const repoInfoCache = new Map();
const REPO_CACHE_TTL_MS = 2000;

export function resolveGitRepoInfo(cwd) {
  if (!cwd || typeof cwd !== 'string' || !cwd.startsWith('/')) return null;
  const now = Date.now();
  const cached = repoInfoCache.get(cwd);
  if (cached && (now - cached.ts) < REPO_CACHE_TTL_MS) return cached.val;

  let result = null;
  try {
    let dir = cwd.replace(/\/+$/, '') || '/';
    for (let depth = 0; depth < 24; depth++) {
      const gitPath = path.join(dir, '.git');
      let st = null;
      try { st = fs.statSync(gitPath); } catch (_) {}
      if (st) {
        if (st.isDirectory()) {
          let branch = '';
          try {
            const head = fs.readFileSync(path.join(gitPath, 'HEAD'), 'utf8').trim();
            if (head.startsWith('ref: refs/heads/')) branch = head.slice('ref: refs/heads/'.length);
          } catch (_) {}
          result = { root: dir, name: path.basename(dir) || dir, branch, is_worktree: false };
        } else if (st.isFile()) {
          const raw = fs.readFileSync(gitPath, 'utf8').trim();
          const m = raw.match(/^gitdir:\s*(.+)$/i);
          if (m) {
            const gitDir = path.resolve(dir, m[1].trim());
            let branch = '';
            try {
              const head = fs.readFileSync(path.join(gitDir, 'HEAD'), 'utf8').trim();
              if (head.startsWith('ref: refs/heads/')) branch = head.slice('ref: refs/heads/'.length);
            } catch (_) {}
            let root = dir;
            try {
              const commonRaw = fs.readFileSync(path.join(gitDir, 'commondir'), 'utf8').trim();
              if (commonRaw) {
                const commonDir = path.resolve(gitDir, commonRaw);
                root = path.basename(commonDir) === '.git' ? path.dirname(commonDir) : commonDir;
              }
            } catch (_) {
              const idx = gitDir.indexOf(`${path.sep}.git${path.sep}worktrees${path.sep}`);
              if (idx > 0) root = gitDir.slice(0, idx);
            }
            result = { root, name: path.basename(root) || root, branch, is_worktree: true };
          }
        }
        break;
      }
      const parent = path.dirname(dir);
      if (parent === dir) break;
      dir = parent;
    }
  } catch (_) {}

  if (repoInfoCache.size > 128) repoInfoCache.clear();
  repoInfoCache.set(cwd, { ts: now, val: result });
  return result;
}

export function enrichTerminalsWithRepo(terminals) {
  return (terminals || []).map((t) => {
    const lbls = (t && t.labels) || {};
    if (lbls['swarmbox.repo']) {
      const root = String(lbls['swarmbox.repo']);
      return {
        ...t,
        repo: {
          root,
          name: path.basename(root) || root,
          branch: String(lbls['swarmbox.branch'] || ''),
          is_worktree: Boolean(lbls['swarmbox.worktree']),
        },
      };
    }
    const repo = resolveGitRepoInfo(terminalCwd(t));
    return repo ? { ...t, repo } : t;
  });
}

const SKIP_SCAN_DIRS = new Set(['node_modules', '.git', 'venv', '.venv', 'dist', 'build', 'target', '__pycache__']);

export function discoverProjects(terminals = [], pins = [], homeDir = HOME) {
  const byReal = new Map();
  const activeCounts = new Map();

  const normAbs = (p) => (typeof p === 'string' && p.startsWith('/') ? normRealPath(p) : '');

  const enriched = enrichTerminalsWithRepo(terminals);
  for (const t of enriched) {
    if (!detectTerminalAgent(t)) continue;
    const root = (t.repo && t.repo.root) || (t.labels && t.labels['swarmbox.repo']) || '';
    const rp = normAbs(root);
    if (rp) activeCounts.set(rp, (activeCounts.get(rp) || 0) + 1);
  }

  const addRepoDir = (dirPath) => {
    const rp = normAbs(dirPath);
    if (!rp || byReal.has(rp)) return;
    const info = resolveGitRepoInfo(dirPath);
    if (!info || info.is_worktree) return;
    const rootReal = normAbs(info.root);
    if (!rootReal || byReal.has(rootReal)) return;
    byReal.set(rootReal, {
      path: info.root,
      name: info.name,
      branch: info.branch || 'main',
      is_git: true,
      active_count: activeCounts.get(rootReal) || 0,
    });
  };

  // 1. Scan HOME (depth 1..2) for Git repositories (skipping hidden dot-directories)
  if (homeDir && fs.existsSync(homeDir)) {
    const scanLevel = (base, depth) => {
      let entries;
      try { entries = fs.readdirSync(base, { withFileTypes: true }); } catch (_) { return; }
      for (const ent of entries) {
        if (!ent.isDirectory() && !ent.isSymbolicLink()) continue;
        const name = ent.name;
        if (!name || name.startsWith('.') || SKIP_SCAN_DIRS.has(name)) continue;
        const full = path.join(base, name);
        let isDir = ent.isDirectory();
        if (!isDir) {
          try { isDir = fs.statSync(full).isDirectory(); } catch (_) { continue; }
        }
        if (!isDir) continue;
        let hasGitDir = false;
        try { hasGitDir = fs.statSync(path.join(full, '.git')).isDirectory(); } catch (_) {}
        if (hasGitDir) {
          addRepoDir(full);
        } else if (depth < 2) {
          scanLevel(full, depth + 1);
        }
      }
    };
    scanLevel(homeDir, 1);
  }

  // 2. Include any active terminal repos and pinned repos even if outside HOME depth 2
  for (const t of enriched) {
    const root = (t.repo && t.repo.root) || (t.labels && t.labels['swarmbox.repo']) || '';
    if (root) addRepoDir(root);
  }
  for (const pin of pins || []) {
    const root = (pin && pin.worktree && pin.worktree.repo) || (pin && pin.cwd) || '';
    if (root) addRepoDir(root);
  }

  return Array.from(byReal.values()).sort((a, b) => a.name.localeCompare(b.name, undefined, { sensitivity: 'base' }));
}

// Describe one folder for the New agent picker: a Git checkout (repo name and branch) or a plain folder.
// Only a `.git` directly in `dir` makes it a repo row, so a plain subfolder of a repo stays a folder.
export function describeDir(dir) {
  const name = path.basename(dir) || dir;
  let hasGit = false;
  try { fs.statSync(path.join(dir, '.git')); hasGit = true; } catch (_) {}
  const info = hasGit ? resolveGitRepoInfo(dir) : null;
  if (info) return { path: dir, name, is_git: true, is_worktree: Boolean(info.is_worktree), branch: info.branch || '' };
  return { path: dir, name, is_git: false, is_worktree: false, branch: '' };
}

// Recently used folders, newest first: launches from the Web Studio, then the folders of live tabs (shells
// included, so a folder you cd'd into shows up), then pinned sessions. Missing folders and managed
// worktrees (reached through their repo) are left out.
export function listRecentDirs(terminals = [], pins = [], recent = [], limit = 6) {
  const out = [];
  const seen = new Set();
  const add = (p) => {
    if (out.length >= limit || typeof p !== 'string' || !p.startsWith('/')) return;
    let real = p;
    try { real = fs.realpathSync(p); } catch (_) { return; }
    if (seen.has(real)) return;
    try { if (!fs.statSync(real).isDirectory()) return; } catch (_) { return; }
    seen.add(real);
    const d = describeDir(p.replace(/\/+$/, '') || '/');
    if (d.is_worktree) return;
    out.push(d);
  };
  for (const r of recent || []) add(r && r.path);
  const live = (terminals || []).slice().sort((a, b) => (b.created_ms || 0) - (a.created_ms || 0));
  for (const t of live) if (!(t.labels && t.labels['swarmbox.worktree'])) add(terminalCwd(t));
  for (const pin of pins || []) if (!pin.worktree) add(pin.cwd);
  return out;
}

const LIST_DIRS_MAX = 400;

// The subfolders of `dir` for the picker's folder browser: hidden folders and build/dependency folders skipped,
// symlinks to folders followed, repos flagged. Returns null when `dir` is not a readable folder.
export function listChildDirs(dir) {
  if (typeof dir !== 'string' || !dir.startsWith('/')) return null;
  const clean = path.resolve(dir);
  let entries;
  try { entries = fs.readdirSync(clean, { withFileTypes: true }); } catch (_) { return null; }
  const out = [];
  for (const ent of entries) {
    const name = ent.name;
    if (!name || name.startsWith('.') || SKIP_SCAN_DIRS.has(name)) continue;
    const full = path.join(clean, name);
    let isDir = ent.isDirectory();
    if (!isDir && ent.isSymbolicLink()) {
      try { isDir = fs.statSync(full).isDirectory(); } catch (_) { isDir = false; }
    }
    if (!isDir) continue;
    out.push(describeDir(full));
    if (out.length >= LIST_DIRS_MAX) break;
  }
  out.sort((a, b) => a.name.localeCompare(b.name, undefined, { sensitivity: 'base' }));
  return { path: clean, parent: clean === '/' ? null : path.dirname(clean), entries: out, truncated: out.length >= LIST_DIRS_MAX };
}
