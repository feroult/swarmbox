#!/usr/bin/python3 -S
"""swarmbox-worktree: Git worktree capability for SwarmBox (CLI and library, Python stdlib only).

Manages isolated Git worktrees under $SB_DATA_DIR/worktrees/<repo>/<id> (default ~/.local/share/swarmbox/worktrees)
so multiple coding agents can work concurrently on the same repository without colliding on one working tree.

  swarmbox-worktree inspect DIR
  swarmbox-worktree list [REPO_DIR]
  swarmbox-worktree create DIR [--base REF] [--branch NAME] [--no-copy-env]
  swarmbox-worktree status PATH [--base REF]
  swarmbox-worktree diff PATH [--base REF] [--file FILE]
  swarmbox-worktree sync PATH [--base REF] [--rebase]
  swarmbox-worktree merge PATH [--base REF] [--squash] [--clean]
  swarmbox-worktree remove PATH [--force] [--keep-branch]
  swarmbox-worktree repo-status DIR
  swarmbox-worktree undo-merge DIR
  swarmbox-worktree push DIR
  swarmbox-worktree verify DIR [--cmd CMD]
  swarmbox-worktree prefs [get | set [--mode ask|auto|off] [--copy-env 0|1]]
  swarmbox-worktree guard [DIR] [--agent NAME] [--exclude TAB] [--shell]

Output: JSON on stdout. Failures print {"err": CODE, "msg": TEXT} and exit non-zero (1 failure, 2 usage).
"""
import hashlib
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import time

for _d in (os.path.dirname(os.path.realpath(__file__)), "/usr/local/lib/swarmbox"):
    if os.path.isfile(os.path.join(_d, "swarmbox_agents.py")):
        sys.path.insert(0, _d)
        break
import swarmbox_agents  # noqa: E402  - the agent registry: which programs are agents (docs/agents-design.md)

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
        if not name.endswith(".json") or name.startswith("repo-"):
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


def _purge_pins_for_worktree(wt_path, env=None):
    """Remove any pins in pins.json whose cwd or worktree.path points to wt_path."""
    if not wt_path:
        return
    pfile = os.path.join(config_dir(env), "pins.json")
    try:
        with open(pfile, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return
    if not isinstance(data, dict) or not isinstance(data.get("pins"), list):
        return
    raw_target = str(wt_path).rstrip("/")
    real_target = _real(wt_path).rstrip("/")
    kept = []
    changed = False
    for pin in data["pins"]:
        if not isinstance(pin, dict):
            kept.append(pin)
            continue
        wt = pin.get("worktree") if isinstance(pin.get("worktree"), dict) else {}
        candidates = [pin.get("cwd"), wt.get("path")]
        matched = False
        for c in candidates:
            if not c or not isinstance(c, str):
                continue
            cr = c.rstrip("/")
            if cr == raw_target or cr == real_target or _real(c).rstrip("/") == real_target:
                matched = True
                break
        if matched:
            changed = True
        else:
            kept.append(pin)
    if not changed:
        return
    tmp = "%s.tmp.%d.%s" % (pfile, os.getpid(), secrets.token_hex(2))
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({**data, "pins": kept}, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.chmod(tmp, 0o600)
        os.replace(tmp, pfile)
    except OSError:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def _repo_meta_path(root, repo_root):
    h = hashlib.sha1(_real(repo_root).encode("utf-8")).hexdigest()[:12]
    return os.path.join(_meta_dir(root), "repo-%s.json" % h)


def _load_last_merge(root, repo_root):
    fp = _repo_meta_path(root, repo_root)
    try:
        with open(fp, encoding="utf-8") as f:
            d = json.load(f)
        if isinstance(d, dict) and d.get("pre_sha") and d.get("post_sha"):
            return d
    except (OSError, ValueError):
        pass
    return None


def _save_last_merge(root, repo_root, data):
    mdir = _meta_dir(root)
    os.makedirs(mdir, mode=0o700, exist_ok=True)
    fp = _repo_meta_path(root, repo_root)
    tmp = "%s.tmp.%d" % (fp, os.getpid())
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
    os.chmod(tmp, 0o600)
    os.replace(tmp, fp)
    return fp


def _clear_last_merge(root, repo_root):
    fp = _repo_meta_path(root, repo_root)
    try:
        os.unlink(fp)
    except OSError:
        pass


def _full_head_sha(cwd):
    r = _git(cwd, "rev-parse", "HEAD", check=False)
    return r.stdout.strip() if r.returncode == 0 else ""


def _upstream_status(cwd):
    r = _git(cwd, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}", check=False)
    if r.returncode != 0 or not r.stdout.strip():
        return "", 0, 0
    upstream = r.stdout.strip()
    ahead, behind = _ahead_behind(cwd, upstream, "HEAD")
    return upstream, ahead, behind


def _tail_bytes(text, max_bytes):
    raw = text.encode("utf-8", errors="replace")
    if len(raw) <= max_bytes:
        return text
    return raw[-max_bytes:].decode("utf-8", errors="ignore")


def detect_verify_cmd(repo_root, env=None):
    """Auto-detect a project verification/test command for repo_root."""
    if not repo_root or not os.path.isdir(repo_root):
        return ""
    rr = _real(repo_root)

    # Override file: .swarmbox-check (first non-comment non-empty line)
    override_file = os.path.join(rr, ".swarmbox-check")
    if os.path.isfile(override_file):
        try:
            with open(override_file, encoding="utf-8", errors="replace") as f:
                for raw in f:
                    ln = raw.strip()
                    if ln and not ln.startswith("#"):
                        return ln
        except OSError:
            pass

    # a) dev/check.sh
    if os.path.isfile(os.path.join(rr, "dev", "check.sh")):
        return "sh dev/check.sh"

    # b) Makefile with test: or check: target
    makefile = os.path.join(rr, "Makefile")
    if os.path.isfile(makefile):
        try:
            with open(makefile, encoding="utf-8", errors="replace") as f:
                mk = f.read(65536)
            if re.search(r"^test\s*:(?!=)", mk, re.M):
                return "make test"
            if re.search(r"^check\s*:(?!=)", mk, re.M):
                return "make check"
        except OSError:
            pass

    # c) package.json with scripts.test (ignoring npm init default placeholder)
    pkg_json = os.path.join(rr, "package.json")
    if os.path.isfile(pkg_json):
        try:
            with open(pkg_json, encoding="utf-8", errors="replace") as f:
                pkg = json.load(f)
            if isinstance(pkg, dict):
                scripts = pkg.get("scripts")
                if isinstance(scripts, dict):
                    t = str(scripts.get("test") or "").strip()
                    if t and "no test specified" not in t:
                        return "npm test"
        except (OSError, ValueError):
            pass

    # d) pyproject.toml, pytest.ini, or tests/ dir with .py files
    has_py_tests = (
        os.path.isfile(os.path.join(rr, "pyproject.toml"))
        or os.path.isfile(os.path.join(rr, "pytest.ini"))
    )
    if not has_py_tests:
        tests_dir = os.path.join(rr, "tests")
        if os.path.isdir(tests_dir):
            for _, _, filenames in os.walk(tests_dir):
                if any(fn.endswith(".py") for fn in filenames):
                    has_py_tests = True
                    break
    if has_py_tests:
        path_env = (env.get("PATH") if isinstance(env, dict) else None)
        return "pytest" if shutil.which("pytest", path=path_env) else "python3 -m unittest"

    # e) Cargo.toml
    if os.path.isfile(os.path.join(rr, "Cargo.toml")):
        return "cargo test"

    # f) go.mod
    if os.path.isfile(os.path.join(rr, "go.mod")):
        return "go test ./..."

    return ""


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


def _collect_commits(cwd, base_ref, target_ref, limit=12):
    r = _git(
        cwd,
        "log",
        "--format=%h%x1f%s%x1f%cr",
        "-n",
        str(limit),
        "%s..%s" % (base_ref, target_ref),
        check=False,
    )
    if r.returncode != 0 or not r.stdout:
        return []
    out = []
    for ln in r.stdout.splitlines():
        if not ln:
            continue
        parts = ln.split("\x1f", 2)
        if len(parts) == 3:
            out.append({"sha": parts[0], "subject": parts[1], "rel_time": parts[2]})
    return out


def _collect_diff_files(cwd, base_ref, target_ref, limit=30):
    rng = "%s...%s" % (base_ref, target_ref)
    ns = _git(cwd, "diff", "--name-status", "-z", rng, check=False)
    st_map = {}
    order = []
    if ns.returncode == 0 and ns.stdout:
        toks = ns.stdout.split("\0")
        i = 0
        n = len(toks)
        while i < n:
            code = toks[i]
            if not code:
                i += 1
                continue
            ch = code[0]
            if ch in ("R", "C"):
                if i + 2 < n:
                    path = toks[i + 2]
                    st_map[path] = ch
                    order.append(path)
                i += 3
            else:
                if i + 1 < n:
                    path = toks[i + 1]
                    st_map[path] = ch
                    order.append(path)
                i += 2

    nm = _git(cwd, "diff", "--numstat", "-z", rng, check=False)
    num_map = {}
    if nm.returncode == 0 and nm.stdout:
        toks = nm.stdout.split("\0")
        i = 0
        n = len(toks)
        while i < n:
            tok = toks[i]
            if not tok:
                i += 1
                continue
            parts = tok.split("\t", 2)
            if len(parts) != 3:
                i += 1
                continue
            added = int(parts[0]) if parts[0].isdigit() else 0
            deleted = int(parts[1]) if parts[1].isdigit() else 0
            if parts[2] == "":
                path = toks[i + 2] if i + 2 < n else (toks[i + 1] if i + 1 < n else "")
                i += 3
            else:
                path = parts[2]
                i += 1
            if path:
                num_map[path] = (added, deleted)
                if path not in st_map:
                    st_map[path] = "M"
                    order.append(path)

    entries = []
    total_added = 0
    total_deleted = 0
    for path in order:
        added, deleted = num_map.get(path, (0, 0))
        total_added += added
        total_deleted += deleted
        entries.append({
            "path": path,
            "status": st_map.get(path, "M"),
            "added": added,
            "deleted": deleted,
        })
    diff_stat = {
        "files": len(entries),
        "insertions": total_added,
        "deletions": total_deleted,
    }
    return entries[:limit], diff_stat


def status_worktree(target_path, base=None, env=None):
    """Return full status of a worktree, including in-memory mergeability check."""
    info = inspect_dir(target_path, env=env)
    if not info.get("is_git") or not info.get("is_worktree"):
        raise WorktreeError("not_a_worktree", "path is not a linked git worktree: %s" % target_path)
    wt_path = info["worktree_path"]
    repo_root = info["repo_root"]
    branch = info["branch"]
    base_ref = (base or "").strip() or info["base"] or _default_base(repo_root)
    target_ref = branch or "HEAD"
    ahead, behind = _ahead_behind(wt_path, base_ref, target_ref)
    main_dirty = _porcelain_count(repo_root)
    main_branch = _current_branch(repo_root)
    main_upstream, main_ahead_origin, main_behind_origin = _upstream_status(repo_root)
    can_merge = True
    conflict_files = []
    if ahead > 0 and branch:
        can_merge, conflict_files = _merge_dry_run(repo_root, base_ref, branch)
    commits = _collect_commits(wt_path, base_ref, target_ref, limit=12) if ahead > 0 else []
    files, diff_stat = _collect_diff_files(wt_path, base_ref, target_ref, limit=30) if ahead > 0 else ([], {"files": 0, "insertions": 0, "deletions": 0})
    verify_cmd = detect_verify_cmd(repo_root, env=env)
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
        "main_upstream": main_upstream,
        "main_ahead_origin": main_ahead_origin,
        "main_behind_origin": main_behind_origin,
        "can_merge": can_merge,
        "conflict_files": conflict_files,
        "commits": commits,
        "files": files,
        "diff_stat": diff_stat,
        "verify_cmd": verify_cmd,
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
    pre_sha = _full_head_sha(repo_root)
    commits_list = [c["subject"] for c in st["commits"]]
    changed_files = [f["path"] for f in st["files"]]
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

    post_sha = _full_head_sha(repo_root)
    _save_last_merge(
        worktree_root(env),
        repo_root,
        {
            "pre_sha": pre_sha,
            "post_sha": post_sha,
            "branch": branch,
            "base": base_ref,
            "strategy": strategy,
            "commits": st["ahead"],
            "merged_at": int(time.time()),
        },
    )

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
        "pre_sha": pre_sha,
        "post_sha": post_sha,
        "commits_list": commits_list,
        "files": changed_files,
        "cleaned": cleaned,
    }


def repo_status(repo_dir, env=None):
    """Inspect a repository's main working tree, upstream status, verify cmd, and undo-merge state."""
    info = inspect_dir(repo_dir, env=env)
    if not info.get("is_git"):
        raise WorktreeError("not_a_git_repo", "directory is not inside a git repository: %s" % repo_dir)
    repo_root = info["repo_root"]
    branch = _current_branch(repo_root)
    head = _head_sha(repo_root)
    full_head = _full_head_sha(repo_root)
    dirty_n = _porcelain_count(repo_root)
    dirty = dirty_n > 0
    upstream, ahead_origin, behind_origin = _upstream_status(repo_root)
    verify_cmd = detect_verify_cmd(repo_root, env=env)
    last_merge = _load_last_merge(worktree_root(env), repo_root)
    can_undo = bool(last_merge and not dirty and full_head and full_head == last_merge.get("post_sha"))
    return {
        "ok": True,
        "repo_root": repo_root,
        "repo_name": info["repo_name"],
        "branch": branch,
        "head": head,
        "dirty": dirty,
        "uncommitted_count": dirty_n,
        "upstream": upstream,
        "ahead_origin": ahead_origin,
        "behind_origin": behind_origin,
        "verify_cmd": verify_cmd,
        "can_undo_merge": can_undo,
        "last_merge": last_merge,
    }


def diff_worktree(target_path, base=None, file_path=None, max_bytes=262144, env=None):
    """Return unified diff between base and worktree branch (optionally for a single file)."""
    info = inspect_dir(target_path, env=env)
    if not info.get("is_git") or not info.get("is_worktree"):
        raise WorktreeError("not_a_worktree", "path is not a linked git worktree: %s" % target_path)
    wt_path = info["worktree_path"]
    repo_root = info["repo_root"]
    branch = info["branch"]
    base_ref = (base or "").strip() or info["base"] or _default_base(repo_root)
    target_ref = branch or "HEAD"
    args = ["diff", "%s...%s" % (base_ref, target_ref)]
    if file_path:
        args.extend(["--", file_path])
    r = _git(wt_path, *args)
    raw = r.stdout or ""
    raw_bytes = raw.encode("utf-8", errors="replace")
    truncated = False
    if max_bytes and len(raw_bytes) > max_bytes:
        raw = raw_bytes[:max_bytes].decode("utf-8", errors="ignore")
        truncated = True
    return {
        "ok": True,
        "branch": branch,
        "base": base_ref,
        "file": file_path or "",
        "diff": raw,
        "truncated": truncated,
    }


def sync_worktree(target_path, base=None, rebase=False, env=None):
    """Update a clean worktree from its base branch via merge or rebase; aborts cleanly on conflict."""
    st = status_worktree(target_path, base=base, env=env)
    if st["dirty"]:
        raise WorktreeError(
            "dirty_worktree",
            "worktree has %d uncommitted change(s); commit or stash them first" % st["uncommitted_count"],
            {"uncommitted_count": st["uncommitted_count"]},
        )
    wt_path = st["path"]
    base_ref = st["base"]
    branch = st["branch"]
    mode = "rebase" if rebase else "merge"
    if rebase:
        r = _git(wt_path, "rebase", base_ref, check=False)
    else:
        r = _git(wt_path, "merge", "--no-edit", base_ref, check=False)
    if r.returncode != 0:
        cf = _git(wt_path, "diff", "--name-only", "--diff-filter=U", check=False)
        conflict_files = [ln.strip() for ln in cf.stdout.splitlines() if ln.strip()]
        if not conflict_files:
            for ln in (r.stdout + "\n" + r.stderr).splitlines():
                m = re.search(r"CONFLICT \([^)]+\):.*\bin\s+(.+)$", ln)
                if m:
                    fn = m.group(1).strip()
                    if fn not in conflict_files:
                        conflict_files.append(fn)
        if rebase:
            _git(wt_path, "rebase", "--abort", check=False)
        else:
            _git(wt_path, "merge", "--abort", check=False)
        raise WorktreeError(
            "sync_conflict",
            "sync (%s) conflict with %s in: %s" % (mode, base_ref, ", ".join(conflict_files) or "unknown files"),
            {"conflict_files": conflict_files},
        )
    ahead, behind = _ahead_behind(wt_path, base_ref, branch or "HEAD")
    return {
        "ok": True,
        "branch": branch,
        "base": base_ref,
        "mode": mode,
        "ahead": ahead,
        "behind": behind,
    }


def undo_merge(repo_dir, env=None):
    """Safely undo the last recorded SwarmBox merge on repo_root if HEAD hasn't moved and tree is clean."""
    info = inspect_dir(repo_dir, env=env)
    if not info.get("is_git"):
        raise WorktreeError("not_a_git_repo", "directory is not inside a git repository: %s" % repo_dir)
    repo_root = info["repo_root"]
    root = worktree_root(env)
    last_merge = _load_last_merge(root, repo_root)
    if not last_merge:
        raise WorktreeError("undo_unavailable", "no recent merge recorded for %s" % info["repo_name"])
    dirty_n = _porcelain_count(repo_root)
    if dirty_n > 0:
        raise WorktreeError(
            "dirty_base",
            "main repository (%s) has %d uncommitted change(s); commit or stash first" % (info["repo_name"], dirty_n),
        )
    full_head = _full_head_sha(repo_root)
    if full_head != last_merge.get("post_sha"):
        raise WorktreeError("undo_unavailable", "HEAD has changed since the last merge; cannot safely undo")
    pre_sha = last_merge["pre_sha"]
    _git(repo_root, "reset", "--hard", pre_sha)
    _clear_last_merge(root, repo_root)
    return {
        "ok": True,
        "repo_root": repo_root,
        "restored_sha": pre_sha,
        "undone_branch": last_merge.get("branch", ""),
    }


def push_repo(repo_dir, env=None):
    """Push repo_root's current branch to its upstream (or origin if no upstream yet)."""
    info = inspect_dir(repo_dir, env=env)
    if not info.get("is_git"):
        raise WorktreeError("not_a_git_repo", "directory is not inside a git repository: %s" % repo_dir)
    repo_root = info["repo_root"]
    dirty_n = _porcelain_count(repo_root)
    if dirty_n > 0:
        raise WorktreeError(
            "dirty_base",
            "main repository (%s) has %d uncommitted change(s); commit or stash first" % (info["repo_name"], dirty_n),
        )
    branch = _current_branch(repo_root)
    if not branch:
        raise WorktreeError("detached_head", "repository is on a detached HEAD; checkout a branch before pushing")
    upstream, _, _ = _upstream_status(repo_root)
    if upstream:
        _git(repo_root, "push", timeout=60.0)
    else:
        rem = _git(repo_root, "remote", "get-url", "origin", check=False)
        if rem.returncode != 0:
            raise WorktreeError("no_remote", "no upstream branch or origin remote configured")
        _git(repo_root, "push", "-u", "origin", branch, timeout=60.0)
        upstream = "origin/" + branch
    return {
        "ok": True,
        "repo_root": repo_root,
        "branch": branch,
        "upstream": upstream,
        "head": _head_sha(repo_root),
    }


def verify_repo(repo_dir, cmd=None, timeout=180, env=None):
    """Run verification command in repo_root and return structured result with tail output."""
    info = inspect_dir(repo_dir, env=env)
    if not info.get("is_git"):
        raise WorktreeError("not_a_git_repo", "directory is not inside a git repository: %s" % repo_dir)
    repo_root = info["repo_root"]
    resolved = (cmd or "").strip() or detect_verify_cmd(repo_root, env=env)
    if not resolved:
        raise WorktreeError("no_verify_cmd", "no verification command detected")
    t0 = time.monotonic()
    try:
        p = subprocess.run(
            ["sh", "-lc", resolved],
            cwd=repo_root,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=timeout,
            env=env,
        )
        dur_ms = int((time.monotonic() - t0) * 1000)
        return {
            "ok": p.returncode == 0,
            "exit_code": p.returncode,
            "cmd": resolved,
            "duration_ms": dur_ms,
            "output": _tail_bytes(p.stdout or "", 16 * 1024),
        }
    except subprocess.TimeoutExpired as e:
        dur_ms = int((time.monotonic() - t0) * 1000)
        out = e.stdout or ""
        if isinstance(out, bytes):
            out = out.decode("utf-8", errors="replace")
        return {
            "ok": False,
            "exit_code": 124,
            "cmd": resolved,
            "duration_ms": dur_ms,
            "output": _tail_bytes(out, 16 * 1024),
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
    _purge_pins_for_worktree(wt_path, env=env)

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


def _tabs_cmd(env=None):
    e = os.environ if env is None else env
    override = (e.get("SWARMBOX_TEST_TABS_BIN") or "").strip()
    if override:
        return [override]
    here = os.path.dirname(os.path.abspath(__file__))
    sib = os.path.join(here, "swarmbox-tabs.py")
    if os.path.isfile(sib):
        return [sys.executable, sib]
    return ["swarmbox-tabs"]


def _tab_agent_kind(row, env=None):
    """The agent a swarmbox-tabs list row runs, by the registry's detection order. The swarmbox.agent label (sticky) counts only while
    the foreground is not a plain shell: an agent that runs as `node` is still seen, a tab whose agent has exited is not."""
    return swarmbox_agents.detect(row, env)


def _expand_tab_dir(raw_dir, env=None):
    s = str(raw_dir or "").strip()
    if not s:
        return ""
    e = os.environ if env is None else env
    home = (e.get("HOME") or os.path.expanduser("~")).rstrip("/")
    if s == "~":
        return home
    if s.startswith("~/"):
        return home + s[1:]
    return s


def find_working_tree_collisions(target_dir, exclude_tab=None, env=None):
    """Return collision info if another live agent tab occupies the same Git working tree."""
    e = os.environ if env is None else env
    info = inspect_dir(target_dir, env=e)
    if not info.get("is_git"):
        return None
    target_wt = os.path.realpath(info["worktree_path"])
    excl = str(exclude_tab if exclude_tab is not None else (e.get("HC_TERMINAL_ID") or "")).strip()
    try:
        r = subprocess.run(
            _tabs_cmd(e) + ["list"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=5.0,
            env=e,
        )
        if r.returncode != 0 or not r.stdout.strip():
            return None
        tabs = json.loads(r.stdout)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None
    if not isinstance(tabs, list):
        return None
    colliding = []
    for row in tabs:
        if not isinstance(row, dict):
            continue
        tid = str(row.get("tab") or row.get("id") or "")
        if excl and tid == excl:
            continue
        ag = _tab_agent_kind(row, e)
        if not ag:
            continue
        tcwd = _expand_tab_dir(row.get("dir") or row.get("cwd") or "", env=e)
        if not tcwd or not os.path.isdir(tcwd):
            continue
        treal = os.path.realpath(tcwd)
        if treal == target_wt or treal.startswith(target_wt + os.sep):
            colliding.append({
                "id": tid,
                "name": str(row.get("title") or row.get("name") or tid),
                "agent": ag,
            })
    if not colliding:
        return None
    return {
        "repo_root": info["repo_root"],
        "repo_name": info["repo_name"],
        "branch": info.get("branch") or info.get("base") or "HEAD",
        "worktree_path": target_wt,
        "dirty": bool(info.get("dirty")),
        "active_tabs": colliding,
    }


def _apply_worktree_labels(tab_id, wt, agent="", env=None):
    """Best-effort attach worktree metadata labels to the current terminal tab so Web Studio
    immediately displays the branch chip and topbar Merge button."""
    if not tab_id or not isinstance(wt, dict):
        return
    e = os.environ if env is None else env
    pairs = []
    if wt.get("path"):
        pairs.append("swarmbox.worktree=%s" % wt["path"])
    if wt.get("branch"):
        pairs.append("swarmbox.branch=%s" % wt["branch"])
    if wt.get("base"):
        pairs.append("swarmbox.base=%s" % wt["base"])
    if wt.get("repo_root"):
        pairs.append("swarmbox.repo=%s" % wt["repo_root"])
    if agent:
        pairs.append("swarmbox.agent=%s" % agent)
    if not pairs:
        return
    try:
        subprocess.run(
            _tabs_cmd(e) + ["label", str(tab_id)] + pairs,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=4.0,
            env=e,
        )
    except (OSError, subprocess.TimeoutExpired):
        pass


def guard_shell_launch(target_dir, agent="", exclude_tab=None, env=None):
    """Interactive shell collision guard invoked before launching an agent in a terminal.

    Honors worktree-prefs.json (`ask` | `auto` | `off`):
    - `off` or no collision -> {"action": "same", ...}
    - `auto` -> creates an isolated worktree, labels the current tab, returns {"action": "worktree", "path": ...}
    - `ask` -> prompts on /dev/tty (or stdin in tests) with [W] New worktree / [S] Same folder / [C] Cancel
    """
    e = os.environ if env is None else env
    prefs = read_prefs(env=e)
    if prefs.get("mode") == "off":
        return {"action": "same", "reason": "mode_off"}
    col = find_working_tree_collisions(target_dir, exclude_tab=exclude_tab, env=e)
    if not col:
        return {"action": "same", "reason": "no_collision"}

    tab_id = str(exclude_tab if exclude_tab is not None else (e.get("HC_TERMINAL_ID") or "")).strip()
    names = ", ".join("%s (%s)" % (x["name"], x["agent"]) for x in col["active_tabs"][:3])
    n = len(col["active_tabs"])

    if prefs.get("mode") == "auto":
        wt = create_worktree(target_dir, env=e)
        _apply_worktree_labels(tab_id, wt, agent=agent, env=e)
        sys.stderr.write(
            "\n  \033[1;35mworktree\033[0m: isolated \033[1;36m%s\033[0m into \033[1;36m%s\033[0m (%d active agent in %s)\n"
            % (col["repo_name"], wt["branch"], n, col["branch"])
        )
        sys.stderr.flush()
        return {"action": "worktree", "path": wt["path"], "branch": wt["branch"], "collision": col}

    # Interactive prompt (`ask` mode) — write and read via /dev/tty so stdout stays pure for `--shell`
    use_stdio = e.get("SWARMBOX_TEST_GUARD_STDIN") == "1"
    tty_in = None
    tty_out = None
    try:
        if use_stdio:
            tty_in = sys.stdin
            tty_out = sys.stderr
        else:
            tty_in = open("/dev/tty", "r", encoding="utf-8", errors="replace")
            tty_out = open("/dev/tty", "w", encoding="utf-8", errors="replace")
    except OSError:
        return {"action": "same", "reason": "no_tty", "collision": col}

    try:
        env_note = ", copies .env" if prefs.get("copy_env", True) else ""
        tty_out.write(
            "\n  \033[1;35mCollision in %s (%s)\033[0m — %d active agent%s already here: %s\n"
            "  \033[1;36m[W]\033[0m New worktree (isolated branch%s)   "
            "\033[1m[S]\033[0m Same folder   "
            "\033[2m[C]\033[0m Cancel\n"
            "  Choice [W/s/c]: "
            % (col["repo_name"], col["branch"], n, "s" if n > 1 else "", names, env_note)
        )
        tty_out.flush()
        line = tty_in.readline()
    except KeyboardInterrupt:
        try:
            tty_out.write("\n")
            tty_out.flush()
        except OSError:
            pass
        return {"action": "cancel", "reason": "interrupted", "collision": col}
    finally:
        if not use_stdio:
            try:
                tty_in.close()
            except OSError:
                pass
            try:
                tty_out.close()
            except OSError:
                pass

    if line == "":
        return {"action": "cancel", "reason": "eof", "collision": col}
    ans = line.strip().lower()
    if ans in ("c", "cancel", "q", "quit"):
        return {"action": "cancel", "reason": "user_cancel", "collision": col}
    if ans in ("s", "same"):
        return {"action": "same", "reason": "user_same", "collision": col}
    # Default (Enter or w/worktree/y/yes): create isolated worktree
    wt = create_worktree(target_dir, env=e)
    _apply_worktree_labels(tab_id, wt, agent=agent, env=e)
    try:
        if use_stdio:
            sys.stderr.write("  Isolated in worktree %s (%s)\n" % (wt["branch"], wt["path"]))
            sys.stderr.flush()
        else:
            with open("/dev/tty", "w", encoding="utf-8", errors="replace") as f:
                f.write("  \033[1;32m✓\033[0m Isolated in worktree \033[1;36m%s\033[0m\n" % wt["branch"])
                f.flush()
    except OSError:
        pass
    return {"action": "worktree", "path": wt["path"], "branch": wt["branch"], "collision": col}


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
        raise WorktreeError(
            "usage",
            "command required: inspect, list, create, status, diff, sync, merge, remove, repo-status, undo-merge, push, verify, prefs, guard",
        )
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
    if cmd == "diff":
        opts, rest = _parse_args(a, ("--base", "--file"), ())
        if len(rest) != 1:
            raise WorktreeError("usage", "usage: diff PATH [--base REF] [--file FILE]")
        return diff_worktree(rest[0], base=opts.get("--base"), file_path=opts.get("--file"), env=env)
    if cmd == "sync":
        opts, rest = _parse_args(a, ("--base",), ("--rebase",))
        if len(rest) != 1:
            raise WorktreeError("usage", "usage: sync PATH [--base REF] [--rebase]")
        return sync_worktree(rest[0], base=opts.get("--base"), rebase="--rebase" in opts, env=env)
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
    if cmd == "repo-status":
        _, rest = _parse_args(a)
        if len(rest) != 1:
            raise WorktreeError("usage", "usage: repo-status DIR")
        return repo_status(rest[0], env=env)
    if cmd == "undo-merge":
        _, rest = _parse_args(a)
        if len(rest) != 1:
            raise WorktreeError("usage", "usage: undo-merge DIR")
        return undo_merge(rest[0], env=env)
    if cmd == "push":
        _, rest = _parse_args(a)
        if len(rest) != 1:
            raise WorktreeError("usage", "usage: push DIR")
        return push_repo(rest[0], env=env)
    if cmd == "verify":
        opts, rest = _parse_args(a, ("--cmd",), ())
        if len(rest) != 1:
            raise WorktreeError("usage", "usage: verify DIR [--cmd CMD]")
        return verify_repo(rest[0], cmd=opts.get("--cmd"), env=env)
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
    if cmd == "guard":
        opts, rest = _parse_args(a, ("--agent", "--exclude"), ("--shell",))
        if len(rest) > 1:
            raise WorktreeError("usage", "usage: guard [DIR] [--agent NAME] [--exclude TAB] [--shell]")
        target = rest[0] if rest else os.getcwd()
        res = guard_shell_launch(
            target,
            agent=opts.get("--agent", ""),
            exclude_tab=opts.get("--exclude"),
            env=env,
        )
        if "--shell" in opts:
            return ("__shell__", res)
        return res
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
    if isinstance(out, tuple) and len(out) == 2 and out[0] == "__shell__":
        res = out[1]
        if res.get("action") == "cancel":
            return 130
        if res.get("action") == "worktree" and res.get("path"):
            print(res["path"])
        return 0
    print(json.dumps(out, ensure_ascii=False))
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
