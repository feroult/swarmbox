#!/usr/bin/python3 -S
"""swarmbox-worktree: Git worktree capability for SwarmBox (CLI and library, Python stdlib only).

Manages isolated Git worktrees under $SB_DATA_DIR/worktrees/<repo>/<id> (default ~/.local/share/swarmbox/worktrees)
so multiple coding agents can work concurrently on the same repository without colliding on one working tree.

  swarmbox-worktree inspect DIR
  swarmbox-worktree list [REPO_DIR]
  swarmbox-worktree create DIR [--base REF] [--branch NAME] [--no-copy-env]
  swarmbox-worktree status PATH [--base REF]
  swarmbox-worktree merge PATH [--base REF] [--squash] [--clean]
  swarmbox-worktree remove PATH [--force] [--keep-branch]
  swarmbox-worktree prefs [get | set [--mode ask|auto|off] [--copy-env 0|1]]

Output: JSON on stdout. Failures print {"err": CODE, "msg": TEXT} and exit non-zero (1 failure, 2 usage).
"""
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import time

GIT_TIMEOUT = 20.0
MAX_ENV_BYTES = 64 * 1024
SKIP_ENV_NAMES = frozenset({".env.example", ".env.sample", ".env.template", ".env.dist"})
VALID_MODES = ("ask", "auto", "off")
EXIT = {"usage": 2, "bad_arg": 2}


class WorktreeError(Exception):
    def __init__(self, code, message="", extra=None):
        super().__init__("%s: %s" % (code, message) if message else code)
        self.code = code
        self.message = message
        self.extra = extra or {}


def _xdg_root(var, fallback):
    v = (os.environ.get(var) or "").strip()
    if v.startswith("/"):
        return v.rstrip("/") or "/"
    return fallback


def config_dir(env=None):
    e = os.environ if env is None else env
    home = e.get("HOME") or os.path.expanduser("~")
    v = (e.get("XDG_CONFIG_HOME") or "").strip()
    base = (v.rstrip("/") or "/") if v.startswith("/") else os.path.join(home, ".config")
    return os.path.join(base, "swarmbox")


def data_dir(env=None):
    e = os.environ if env is None else env
    home = e.get("HOME") or os.path.expanduser("~")
    v = (e.get("XDG_DATA_HOME") or "").strip()
    base = (v.rstrip("/") or "/") if v.startswith("/") else os.path.join(home, ".local", "share")
    return os.path.join(base, "swarmbox")


def worktree_root(env=None):
    e = os.environ if env is None else env
    override = (e.get("SB_WORKTREE_ROOT") or "").strip()
    if override:
        return os.path.abspath(override)
    return os.path.join(data_dir(e), "worktrees")


def _meta_dir(root):
    return os.path.join(root, ".meta")


def prefs_path(env=None):
    return os.path.join(config_dir(env), "worktree-prefs.json")


def read_prefs(env=None):
    p = prefs_path(env)
    out = {"mode": "ask", "copy_env": True}
    try:
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
        if isinstance(d, dict):
            if d.get("mode") in VALID_MODES:
                out["mode"] = d["mode"]
            if isinstance(d.get("copy_env"), bool):
                out["copy_env"] = d["copy_env"]
    except (OSError, ValueError):
        pass
    return out


def write_prefs(mode=None, copy_env=None, env=None):
    cur = read_prefs(env)
    if mode is not None:
        if mode not in VALID_MODES:
            raise WorktreeError("bad_arg", "mode must be one of: %s" % ", ".join(VALID_MODES))
        cur["mode"] = mode
    if copy_env is not None:
        cur["copy_env"] = bool(copy_env)
    p = prefs_path(env)
    os.makedirs(os.path.dirname(p), mode=0o700, exist_ok=True)
    tmp = "%s.tmp.%d" % (p, os.getpid())
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cur, f, indent=2)
        f.write("\n")
    os.chmod(tmp, 0o600)
    os.replace(tmp, p)
    return cur


def _git(cwd, *args, check=True, timeout=GIT_TIMEOUT):
    try:
        p = subprocess.run(
            ["git", *args],
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError:
        raise WorktreeError("no_git", "git is not installed")
    except subprocess.TimeoutExpired:
        raise WorktreeError("timeout", "git %s timed out" % (args[0] if args else ""))
    except OSError as e:
        raise WorktreeError("git_error", str(e))
    if check and p.returncode != 0:
        msg = (p.stderr or p.stdout or "git failed").strip().splitlines()[-1]
        raise WorktreeError("git_error", msg)
    return p


def _slug(text, fallback="repo", limit=28):
    s = re.sub(r"[^A-Za-z0-9._-]+", "-", str(text or "")).strip(".-").lower()
    return (s[:limit].strip(".-")) or fallback


def _real(p):
    return os.path.realpath(os.path.expanduser(str(p)))


def _load_all_meta(root):
    mdir = _meta_dir(root)
    out = {}
    try:
        names = sorted(os.listdir(mdir))
    except OSError:
        return out
    for name in names:
        if not name.endswith(".json"):
            continue
        fp = os.path.join(mdir, name)
        try:
            with open(fp, encoding="utf-8") as f:
                d = json.load(f)
            if isinstance(d, dict) and d.get("path"):
                d["_meta_file"] = fp
                out[_real(d["path"])] = d
        except (OSError, ValueError):
            continue
    return out


def _save_meta(root, rec):
    mdir = _meta_dir(root)
    os.makedirs(mdir, mode=0o700, exist_ok=True)
    fp = os.path.join(mdir, "%s.json" % rec["id"])
    tmp = "%s.tmp.%d" % (fp, os.getpid())
    data = {k: v for k, v in rec.items() if not k.startswith("_")}
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
    os.chmod(tmp, 0o600)
    os.replace(tmp, fp)
    return fp


def _delete_meta(root, wt_path):
    meta = _load_all_meta(root).get(_real(wt_path))
    if meta and meta.get("_meta_file"):
        try:
            os.unlink(meta["_meta_file"])
        except OSError:
            pass


def _is_under(path, root):
    rp, rr = _real(path), _real(root)
    return rp == rr or rp.startswith(rr + os.sep)


def _porcelain_count(cwd):
    r = _git(cwd, "status", "--porcelain", check=False)
    if r.returncode != 0:
        return 0
    return sum(1 for ln in r.stdout.splitlines() if ln.strip())


def _current_branch(cwd):
    r = _git(cwd, "symbolic-ref", "--quiet", "--short", "HEAD", check=False)
    if r.returncode == 0 and r.stdout.strip():
        return r.stdout.strip()
    return ""


def _head_sha(cwd):
    r = _git(cwd, "rev-parse", "--short", "HEAD", check=False)
    return r.stdout.strip() if r.returncode == 0 else ""


def _default_base(repo_root):
    cur = _current_branch(repo_root)
    if cur:
        return cur
    for cand in ("main", "master"):
        r = _git(repo_root, "show-ref", "--verify", "--quiet", "refs/heads/" + cand, check=False)
        if r.returncode == 0:
            return cand
    return "HEAD"


def inspect_dir(target, env=None):
    """Inspect a directory for Git repository & worktree membership."""
    if not target or not os.path.isdir(os.path.expanduser(str(target))):
        return {"is_git": False, "path": str(target or "")}
    cwd = _real(target)
    top = _git(cwd, "rev-parse", "--show-toplevel", check=False)
    if top.returncode != 0 or not top.stdout.strip():
        return {"is_git": False, "path": cwd}
    wt_path = _real(top.stdout.strip())
    common = _git(wt_path, "rev-parse", "--path-format=absolute", "--git-common-dir", check=False)
    gdir = _git(wt_path, "rev-parse", "--path-format=absolute", "--git-dir", check=False)
    common_abs = _real(common.stdout.strip()) if common.returncode == 0 and common.stdout.strip() else ""
    git_abs = _real(gdir.stdout.strip()) if gdir.returncode == 0 and gdir.stdout.strip() else ""
    is_wt = bool(common_abs and git_abs and common_abs != git_abs)
    # Main repository root is the parent of common .git dir when in a linked worktree
    repo_root = _real(os.path.dirname(common_abs)) if is_wt and os.path.basename(common_abs) == ".git" else wt_path
    repo_name = os.path.basename(repo_root) or "repo"
    branch = _current_branch(wt_path)
    head = _head_sha(wt_path)
    dirty_n = _porcelain_count(wt_path)
    root = worktree_root(env)
    meta = _load_all_meta(root).get(wt_path)
    managed = bool(meta) or (is_wt and _is_under(wt_path, root))
    base = (meta or {}).get("base") or (_default_base(repo_root) if is_wt else branch)
    return {
        "is_git": True,
        "path": cwd,
        "worktree_path": wt_path,
        "repo_root": repo_root,
        "repo_name": repo_name,
        "is_worktree": is_wt,
        "managed": managed,
        "branch": branch,
        "base": base,
        "head": head,
        "dirty": dirty_n > 0,
        "uncommitted_count": dirty_n,
        "id": (meta or {}).get("id", ""),
    }


def _copy_local_files(src_root, dst_root, copy_env=True):
    """Copy root .env* files (mode 0600, <= 64 KiB) and optional .swarmbox-worktree entries."""
    copied = []
    src_real = _real(src_root)
    dst_real = _real(dst_root)

    def copy_one(rel_path):
        rel = rel_path.strip().lstrip("/")
        if not rel or ".." in rel.split("/") or rel.startswith(".git"):
            return
        sp = os.path.join(src_real, rel)
        dp = os.path.join(dst_real, rel)
        if not os.path.isfile(sp) or os.path.islink(sp):
            return
        if not _is_under(sp, src_real):
            return
        if os.path.exists(dp):
            return
        try:
            st = os.stat(sp)
            if st.st_size > MAX_ENV_BYTES:
                return
            os.makedirs(os.path.dirname(dp), exist_ok=True)
            shutil.copyfile(sp, dp)
            os.chmod(dp, 0o600 if os.path.basename(rel).startswith(".env") else (st.st_mode & 0o777))
            copied.append(rel)
        except OSError:
            pass

    if copy_env:
        try:
            for name in sorted(os.listdir(src_real)):
                if (name == ".env" or name.startswith(".env.")) and name not in SKIP_ENV_NAMES:
                    copy_one(name)
        except OSError:
            pass

    manifest = os.path.join(src_real, ".swarmbox-worktree")
    if os.path.isfile(manifest) and not os.path.islink(manifest):
        try:
            with open(manifest, encoding="utf-8") as f:
                for raw in f:
                    ln = raw.split("#", 1)[0].strip()
                    if ln:
                        copy_one(ln)
        except OSError:
            pass
    return copied


def create_worktree(target_dir, base=None, branch=None, copy_env=None, env=None):
    """Create a new isolated Git worktree from target_dir's current HEAD (or explicit base)."""
    info = inspect_dir(target_dir, env=env)
    if not info.get("is_git"):
        raise WorktreeError("not_a_git_repo", "directory is not inside a git repository: %s" % target_dir)
    if not info.get("head"):
        raise WorktreeError("no_commits", "repository has no commits yet; make an initial commit first")

    repo_root = info["repo_root"]
    source_wt = info["worktree_path"]
    repo_name = info["repo_name"]
    base_ref = (base or "").strip() or info["branch"] or _default_base(repo_root)
    start_point = (base or "").strip() or "HEAD"

    # Verify start_point resolves to a commit
    chk = _git(source_wt, "rev-parse", "--verify", start_point + "^{commit}", check=False)
    if chk.returncode != 0:
        raise WorktreeError("bad_base", "cannot resolve base ref %r" % start_point)

    root = worktree_root(env)
    repo_dir = os.path.join(root, _slug(repo_name, "repo", 32))
    os.makedirs(repo_dir, mode=0o700, exist_ok=True)

    wt_id = None
    wt_branch = None
    wt_path = None
    for _ in range(12):
        tok = secrets.token_hex(2)
        cand_id = "wt-" + tok
        cand_branch = branch.strip() if branch else ("sb/" + cand_id)
        if not re.fullmatch(r"[A-Za-z0-9._/-]{1,64}", cand_branch) or ".." in cand_branch or cand_branch.startswith("-"):
            raise WorktreeError("bad_arg", "invalid branch name: %r" % cand_branch)
        cand_path = os.path.join(repo_dir, _slug(cand_branch.replace("/", "-"), cand_id, 36))
        if os.path.exists(cand_path):
            if branch:
                cand_path = "%s-%s" % (cand_path, tok)
            else:
                continue
        ref_chk = _git(repo_root, "show-ref", "--verify", "--quiet", "refs/heads/" + cand_branch, check=False)
        if ref_chk.returncode == 0:
            if branch:
                raise WorktreeError("branch_exists", "branch already exists: %s" % cand_branch)
            continue
        wt_id, wt_branch, wt_path = cand_id, cand_branch, cand_path
        break
    if not wt_path:
        raise WorktreeError("git_error", "could not allocate unique worktree path")

    _git(source_wt, "worktree", "add", "-b", wt_branch, wt_path, start_point)

    prefs = read_prefs(env)
    do_copy = prefs["copy_env"] if copy_env is None else bool(copy_env)
    copied = _copy_local_files(source_wt, wt_path, copy_env=do_copy)

    rec = {
        "id": wt_id,
        "path": _real(wt_path),
        "repo_root": repo_root,
        "repo_name": repo_name,
        "branch": wt_branch,
        "base": base_ref,
        "created_at": int(time.time()),
    }
    _save_meta(root, rec)
    return {
        "ok": True,
        **rec,
        "copied_files": copied,
        "uncommitted_in_source": bool(info.get("dirty")),
    }


def _merge_dry_run(repo_root, base_ref, branch):
    """Run in-memory `git merge-tree --write-tree` to detect conflicts without touching working trees."""
    r = _git(repo_root, "merge-tree", "--write-tree", "--name-only", base_ref, branch, check=False)
    if r.returncode == 0:
        return True, []
    # Output format when conflicted: tree oid, blank or conflict filenames, then informational lines
    files = []
    lines = r.stdout.splitlines()
    for ln in lines[1:]:
        s = ln.strip()
        if not s:
            break
        if s not in files:
            files.append(s)
    # Fallback parse for "CONFLICT (...): ... in <file>"
    if not files:
        for ln in lines:
            m = re.search(r"CONFLICT \([^)]+\):.*\bin\s+(.+)$", ln)
            if m:
                fn = m.group(1).strip()
                if fn not in files:
                    files.append(fn)
    return False, files[:20]


def _ahead_behind(repo_root, base_ref, branch):
    r = _git(repo_root, "rev-list", "--left-right", "--count", "%s...%s" % (base_ref, branch), check=False)
    if r.returncode != 0:
        return 0, 0
    parts = r.stdout.strip().split()
    if len(parts) != 2:
        return 0, 0
    try:
        return int(parts[1]), int(parts[0])  # ahead (right), behind (left)
    except ValueError:
        return 0, 0


def status_worktree(target_path, base=None, env=None):
    """Return full status of a worktree, including in-memory mergeability check."""
    info = inspect_dir(target_path, env=env)
    if not info.get("is_git") or not info.get("is_worktree"):
        raise WorktreeError("not_a_worktree", "path is not a linked git worktree: %s" % target_path)
    wt_path = info["worktree_path"]
    repo_root = info["repo_root"]
    branch = info["branch"]
    base_ref = (base or "").strip() or info["base"] or _default_base(repo_root)
    ahead, behind = _ahead_behind(repo_root, base_ref, branch or "HEAD")
    main_dirty = _porcelain_count(repo_root)
    main_branch = _current_branch(repo_root)
    can_merge = True
    conflict_files = []
    if ahead > 0 and branch:
        can_merge, conflict_files = _merge_dry_run(repo_root, base_ref, branch)
    empty = (not info["dirty"]) and ahead == 0
    return {
        "ok": True,
        "id": info["id"],
        "path": wt_path,
        "repo_root": repo_root,
        "repo_name": info["repo_name"],
        "branch": branch,
        "base": base_ref,
        "head": info["head"],
        "managed": info["managed"],
        "dirty": info["dirty"],
        "uncommitted_count": info["uncommitted_count"],
        "ahead": ahead,
        "behind": behind,
        "main_dirty": main_dirty > 0,
        "main_uncommitted_count": main_dirty,
        "main_branch": main_branch,
        "can_merge": can_merge,
        "conflict_files": conflict_files,
        "empty": empty,
    }


def list_worktrees(repo_filter=None, env=None):
    """List managed worktrees (and optionally filter by repo_root)."""
    root = worktree_root(env)
    meta_map = _load_all_meta(root)
    filter_real = None
    if repo_filter:
        inf = inspect_dir(repo_filter, env=env)
        filter_real = inf.get("repo_root") if inf.get("is_git") else _real(repo_filter)

    out = []
    for wt_path, meta in sorted(meta_map.items(), key=lambda kv: kv[1].get("created_at", 0)):
        if filter_real and _real(meta.get("repo_root", "")) != filter_real:
            continue
        if not os.path.isdir(wt_path):
            # Prune stale metadata whose folder no longer exists
            _delete_meta(root, wt_path)
            continue
        try:
            st = status_worktree(wt_path, base=meta.get("base"), env=env)
            st["created_at"] = meta.get("created_at", 0)
            out.append(st)
        except WorktreeError:
            continue
    return out


def merge_worktree(target_path, base=None, squash=False, clean=False, env=None):
    """Cleanly merge a worktree branch into its base branch, refusing dirty or conflicted merges."""
    st = status_worktree(target_path, base=base, env=env)
    if st["dirty"]:
        raise WorktreeError(
            "dirty_worktree",
            "worktree has %d uncommitted change(s); commit them first" % st["uncommitted_count"],
            {"uncommitted_count": st["uncommitted_count"]},
        )
    if not st["branch"]:
        raise WorktreeError("detached_head", "worktree is on a detached HEAD; create a branch before merging")
    if st["ahead"] == 0:
        raise WorktreeError("nothing_to_merge", "worktree branch %s has no commits ahead of %s" % (st["branch"], st["base"]))
    if st["main_dirty"]:
        raise WorktreeError(
            "dirty_base",
            "main repository (%s) has %d uncommitted change(s); commit or stash there first, or open a PR"
            % (st["repo_name"], st["main_uncommitted_count"]),
        )
    if st["main_branch"] != st["base"]:
        raise WorktreeError(
            "base_not_checked_out",
            "main repository is on branch %r, not %r; switch branch there or open a PR"
            % (st["main_branch"] or "HEAD", st["base"]),
        )
    if not st["can_merge"]:
        raise WorktreeError(
            "merge_conflict",
            "merge conflict with %s in: %s" % (st["base"], ", ".join(st["conflict_files"]) or "unknown files"),
            {"conflict_files": st["conflict_files"]},
        )

    repo_root = st["repo_root"]
    branch = st["branch"]
    base_ref = st["base"]
    if squash:
        _git(repo_root, "merge", "--squash", branch)
        _git(repo_root, "commit", "-m", "Merge worktree %s into %s" % (branch, base_ref))
        strategy = "squash"
    else:
        ff = _git(repo_root, "merge", "--ff-only", branch, check=False)
        if ff.returncode == 0:
            strategy = "fast-forward"
        else:
            _git(repo_root, "merge", "--no-edit", branch)
            strategy = "merge"

    cleaned = False
    if clean:
        remove_worktree(st["path"], force=False, keep_branch=False, env=env)
        cleaned = True

    return {
        "ok": True,
        "branch": branch,
        "base": base_ref,
        "repo_root": repo_root,
        "strategy": strategy,
        "commits": st["ahead"],
        "cleaned": cleaned,
    }


def remove_worktree(target_path, force=False, keep_branch=False, env=None):
    """Remove a worktree safely; refuses dirty or unmerged worktrees unless force=True."""
    st = status_worktree(target_path, env=env)
    if not force:
        if st["dirty"]:
            raise WorktreeError("dirty_worktree", "worktree has uncommitted changes (pass --force to discard)")
        if st["ahead"] > 0:
            raise WorktreeError("unmerged_commits", "worktree has %d unmerged commit(s) ahead of %s (merge first or pass --force)" % (st["ahead"], st["base"]))

    repo_root = st["repo_root"]
    wt_path = st["path"]
    branch = st["branch"]
    root = worktree_root(env)

    args = ["worktree", "remove"]
    if force:
        args.append("--force")
    args.append(wt_path)
    _git(repo_root, *args)
    _git(repo_root, "worktree", "prune", check=False)
    _delete_meta(root, wt_path)

    branch_deleted = False
    if branch and not keep_branch and (branch.startswith("sb/") or force):
        flag = "-D" if force else "-d"
        r = _git(repo_root, "branch", flag, branch, check=False)
        branch_deleted = r.returncode == 0

    return {
        "ok": True,
        "path": wt_path,
        "branch": branch,
        "branch_deleted": branch_deleted,
    }


def _parse_args(argv, takes=(), flags=()):
    opts, rest, i = {}, [], 0
    while i < len(argv):
        x = argv[i]
        if x in takes:
            if i + 1 >= len(argv):
                raise WorktreeError("usage", "%s takes a value" % x)
            opts[x] = argv[i + 1]
            i += 2
        elif x in flags:
            opts[x] = True
            i += 1
        elif x.startswith("-"):
            raise WorktreeError("usage", "unknown option %s" % x)
        else:
            rest.append(x)
            i += 1
    return opts, rest


def run_cli(argv, env=None):
    if not argv:
        raise WorktreeError("usage", "command required: inspect, list, create, status, merge, remove, prefs")
    cmd, a = argv[0], argv[1:]
    if cmd == "inspect":
        _, rest = _parse_args(a)
        if len(rest) != 1:
            raise WorktreeError("usage", "usage: inspect DIR")
        return inspect_dir(rest[0], env=env)
    if cmd == "list":
        _, rest = _parse_args(a)
        if len(rest) > 1:
            raise WorktreeError("usage", "usage: list [REPO_DIR]")
        return list_worktrees(rest[0] if rest else None, env=env)
    if cmd == "create":
        opts, rest = _parse_args(a, ("--base", "--branch"), ("--no-copy-env",))
        if len(rest) != 1:
            raise WorktreeError("usage", "usage: create DIR [--base REF] [--branch NAME] [--no-copy-env]")
        return create_worktree(
            rest[0],
            base=opts.get("--base"),
            branch=opts.get("--branch"),
            copy_env=False if "--no-copy-env" in opts else None,
            env=env,
        )
    if cmd == "status":
        opts, rest = _parse_args(a, ("--base",), ())
        if len(rest) != 1:
            raise WorktreeError("usage", "usage: status PATH [--base REF]")
        return status_worktree(rest[0], base=opts.get("--base"), env=env)
    if cmd == "merge":
        opts, rest = _parse_args(a, ("--base",), ("--squash", "--clean"))
        if len(rest) != 1:
            raise WorktreeError("usage", "usage: merge PATH [--base REF] [--squash] [--clean]")
        return merge_worktree(rest[0], base=opts.get("--base"), squash="--squash" in opts, clean="--clean" in opts, env=env)
    if cmd == "remove":
        opts, rest = _parse_args(a, (), ("--force", "--keep-branch"))
        if len(rest) != 1:
            raise WorktreeError("usage", "usage: remove PATH [--force] [--keep-branch]")
        return remove_worktree(rest[0], force="--force" in opts, keep_branch="--keep-branch" in opts, env=env)
    if cmd == "prefs":
        if not a or a[0] == "get":
            return read_prefs(env=env)
        if a[0] == "set":
            opts, rest = _parse_args(a[1:], ("--mode", "--copy-env"), ())
            if rest:
                raise WorktreeError("usage", "usage: prefs set [--mode ask|auto|off] [--copy-env 0|1]")
            ce = None
            if "--copy-env" in opts:
                raw = opts["--copy-env"].strip().lower()
                if raw in ("1", "true", "yes", "on"):
                    ce = True
                elif raw in ("0", "false", "no", "off"):
                    ce = False
                else:
                    raise WorktreeError("bad_arg", "--copy-env expects 0 or 1")
            return write_prefs(mode=opts.get("--mode"), copy_env=ce, env=env)
        raise WorktreeError("usage", "usage: prefs [get | set ...]")
    raise WorktreeError("usage", "unknown command %s" % cmd)


def main(argv):
    if argv[:1] in (["-h"], ["--help"], ["help"]):
        print(__doc__)
        return 0
    try:
        out, rc = run_cli(argv), 0
    except WorktreeError as e:
        out = {"err": e.code, "msg": e.message}
        out.update(e.extra)
        rc = EXIT.get(e.code, 1)
    print(json.dumps(out, ensure_ascii=False))
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
