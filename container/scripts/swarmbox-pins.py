#!/usr/bin/python3 -S
"""swarmbox-pins: persistent pinned sessions for SwarmBox (CLI and library, Python stdlib only).

Stores pinned sessions in $SB_CONFIG_DIR/pins.json (default ~/.config/swarmbox/pins.json) so they
survive `swarmbox stop`, host reboots, `swarmbox reset`, and image updates.

  swarmbox-pins list
  swarmbox-pins add --cwd DIR [--agent AGENT] [--title TITLE] [--resume continue|fresh] [--autostart]
  swarmbox-pins update PIN_ID [--title TITLE] [--cwd DIR] [--agent AGENT] [--resume continue|fresh] [--autostart 0|1]
  swarmbox-pins rm PIN_ID
  swarmbox-pins restore [--boot]         reconcile autostart=true pins into herdr-core (called at box boot)

Output: JSON on stdout. Failures print {"err": CODE, "msg": TEXT} and exit non-zero.
"""
import json
import os
import re
import secrets
import shlex
import subprocess
import sys
import time

SCHEMA = 1
ALLOWED_AGENTS = frozenset({"shell", "claude", "agy", "opencode", "gemini", "codex", "yolo"})
CONTINUE_AGENTS = frozenset({"claude", "agy", "opencode"})
VALID_RESUME = frozenset({"continue", "fresh"})
EXIT = {"usage": 2, "bad_arg": 2}


class PinsError(Exception):
    def __init__(self, code, message=""):
        super().__init__("%s: %s" % (code, message) if message else code)
        self.code = code
        self.message = message


def config_dir(env=None):
    e = os.environ if env is None else env
    home = e.get("HOME") or os.path.expanduser("~")
    v = (e.get("XDG_CONFIG_HOME") or "").strip()
    base = (v.rstrip("/") or "/") if v.startswith("/") else os.path.join(home, ".config")
    return os.path.join(base, "swarmbox")


def pins_path(env=None):
    return os.path.join(config_dir(env), "pins.json")


def _clean_title(raw):
    s = "".join(c if c.isprintable() else " " for c in str(raw or "")).strip()
    s = re.sub(r"\s+", " ", s)
    return s[:60]


def _slug(raw, fallback="pin"):
    s = re.sub(r"[^a-z0-9_-]+", "-", str(raw or "").lower()).strip("-")[:28].strip("-")
    if not s or re.fullmatch(r"t\d+", s):
        return fallback
    return s


def load_pins(env=None):
    """Read pins.json preserving any unknown keys on each pin record."""
    p = pins_path(env)
    try:
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return []
    if not isinstance(data, dict) or not isinstance(data.get("pins"), list):
        return []
    out = []
    for item in data["pins"]:
        if isinstance(item, dict) and isinstance(item.get("id"), str) and item["id"]:
            out.append(dict(item))
    return out


def save_pins(pins, env=None):
    """Write pins.json atomically (temp + rename, mode 0600)."""
    p = pins_path(env)
    os.makedirs(os.path.dirname(p), mode=0o700, exist_ok=True)
    tmp = "%s.tmp.%d.%s" % (p, os.getpid(), secrets.token_hex(2))
    payload = {"schema": SCHEMA, "pins": list(pins)}
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
        f.write("\n")
    os.chmod(tmp, 0o600)
    os.replace(tmp, p)
    return pins


def default_title_for(cwd, agent="shell", env=None):
    e = os.environ if env is None else env
    home = (e.get("HOME") or os.path.expanduser("~")).rstrip("/")
    clean = str(cwd or "").rstrip("/")
    if clean and clean != "/" and clean != home:
        base = os.path.basename(clean)
        if base:
            return _clean_title(base)
    return agent if agent and agent != "shell" else "shell"


def add_pin(cwd, agent="shell", title="", title_source="", resume="continue", autostart=False,
            worktree=None, pin_id=None, env=None):
    ag = (agent or "shell").strip().lower()
    if ag not in ALLOWED_AGENTS:
        raise PinsError("bad_arg", "unknown agent %r" % ag)
    res = (resume or "continue").strip().lower()
    if res not in VALID_RESUME:
        raise PinsError("bad_arg", "resume must be continue or fresh")
    clean_cwd = os.path.expanduser(str(cwd or "").strip())
    if not clean_cwd or not clean_cwd.startswith("/"):
        raise PinsError("bad_arg", "cwd must be an absolute path")
    clean_t = _clean_title(title) or default_title_for(clean_cwd, ag, env=env)
    now = int(time.time())
    pins = load_pins(env=env)
    used_ids = {x["id"] for x in pins}
    pid = pin_id if (pin_id and pin_id not in used_ids) else None
    while not pid or pid in used_ids:
        pid = "p_" + secrets.token_hex(3)
    rec = {
        "id": pid,
        "title": clean_t,
        "title_source": title_source if title_source in ("user", "auto", "") else "",
        "agent": ag,
        "cwd": clean_cwd,
        "resume": res,
        "autostart": bool(autostart),
        "created_at": now,
        "updated_at": now,
    }
    if isinstance(worktree, dict) and worktree.get("path"):
        rec["worktree"] = dict(worktree)
    pins.append(rec)
    save_pins(pins, env=env)
    return rec


def update_pin(pin_id, title=None, title_source=None, cwd=None, agent=None, resume=None,
               autostart=None, worktree=None, env=None):
    pins = load_pins(env=env)
    hit = None
    for rec in pins:
        if rec.get("id") == pin_id:
            hit = rec
            break
    if hit is None:
        raise PinsError("no_such_pin", "no pin %r" % pin_id)
    if title is not None:
        ct = _clean_title(title)
        if not ct:
            raise PinsError("bad_arg", "title cannot be empty")
        hit["title"] = ct
    if title_source is not None:
        if title_source not in ("user", "auto", ""):
            raise PinsError("bad_arg", "title_source must be user, auto, or empty")
        hit["title_source"] = title_source
    if cwd is not None:
        cc = os.path.expanduser(str(cwd).strip())
        if not cc.startswith("/"):
            raise PinsError("bad_arg", "cwd must be an absolute path")
        hit["cwd"] = cc
    if agent is not None:
        ag = str(agent).strip().lower()
        if ag not in ALLOWED_AGENTS:
            raise PinsError("bad_arg", "unknown agent %r" % ag)
        hit["agent"] = ag
    if resume is not None:
        res = str(resume).strip().lower()
        if res not in VALID_RESUME:
            raise PinsError("bad_arg", "resume must be continue or fresh")
        hit["resume"] = res
    if autostart is not None:
        hit["autostart"] = bool(autostart)
    if worktree is not None:
        if worktree == {}:
            hit.pop("worktree", None)
        elif isinstance(worktree, dict):
            hit["worktree"] = dict(worktree)
    hit["updated_at"] = int(time.time())
    save_pins(pins, env=env)
    return hit


def remove_pin(pin_id, env=None):
    pins = load_pins(env=env)
    kept = [p for p in pins if p.get("id") != pin_id]
    if len(kept) == len(pins):
        raise PinsError("no_such_pin", "no pin %r" % pin_id)
    save_pins(kept, env=env)
    return {"ok": True, "id": pin_id}


def build_agent_argv(agent, resume="continue"):
    """Build herdr-core argv for launching an agent with safe --continue fallback."""
    ag = (agent or "shell").strip().lower()
    if ag == "shell" or ag not in ALLOWED_AGENTS:
        return ["/bin/bash", "-l"]
    if resume == "continue" and ag in CONTINUE_AGENTS:
        # Only fall back to a fresh session if --continue exits non-zero almost immediately (< 4s),
        # which indicates no prior conversation exists in this directory.
        script = (
            "_sb_t0=$(date +%s); "
            f"{ag} --continue; _sb_rc=$?; "
            "if [ \"$_sb_rc\" -ne 0 ] && [ $(( $(date +%s) - _sb_t0 )) -lt 4 ]; then "
            f"{ag}; fi; exec /bin/bash -l"
        )
        return ["/bin/bash", "-lic", script]
    return ["/bin/bash", "-lic", f"{ag}; exec /bin/bash -l"]


SHELL_NAMES = frozenset({"bash", "sh", "zsh", "dash", "fish", "ash", "ksh", "nu", "nushell", ""})


def _is_shell_only(term):
    """Return True when a live herdr-core terminal is not running an active agent:
    either it is pending `--keep` recovery after `swarmbox reset` (`reason == "stopped_by_restart"`
    or `pid is None`), or it is only running a bare login shell."""
    if not isinstance(term, dict):
        return True
    if str(term.get("reason") or "") == "stopped_by_restart":
        return True
    if "pid" in term and term.get("pid") is None:
        return True
    st = term.get("status")
    if isinstance(st, dict) and str(st.get("app") or "").strip():
        return False
    fg = term.get("foreground")
    if isinstance(fg, dict):
        fg_name = os.path.basename(str(fg.get("name") or "")).lower().lstrip("-")
        return fg_name in SHELL_NAMES
    ag = os.path.basename(str(term.get("agent") or "")).lower().lstrip("-")
    if ag and ag not in SHELL_NAMES:
        return False
    argv = term.get("argv")
    if isinstance(argv, list) and len(argv) >= 3 and argv[1] in ("-lic", "-lc", "-ic", "-c"):
        return False
    return True


def _close_terminal(hc, addr, env):
    """Cancel `--keep` recovery, end, and remove a terminal cleanly."""
    if not addr:
        return False
    try:
        subprocess.run([hc, "keep", "--off", str(addr)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=5.0, env=env)
        subprocess.run([hc, "kill", str(addr)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=5.0, env=env)
        subprocess.run([hc, "rm", str(addr)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=5.0, env=env)
        return True
    except (OSError, subprocess.TimeoutExpired):
        return False


def restore_autostart_pins(hc_bin=None, run_dir=None, env=None, on_boot=False):
    """Reconcile pinned sessions into herdr-core.

    - Spawns pins with autostart=true that have no live terminal.
    - For autostart=true agent pins whose terminal was resurrected by `herdr-core --keep` as a
      bare recovery shell after `swarmbox reset` / restart, replaces the empty shell with the
      configured agent command (e.g. `agy --continue`).
    - When on_boot=True, parks (closes) bare `--keep` recovery shells belonging to autostart=false
      pins so they appear cleanly under PINNED · PARKED instead of as empty shells.
    - Never fails boot on missing cwd and never touches unpinned terminals.
    """
    e = os.environ if env is None else env
    hc = hc_bin or e.get("SWARMBOX_TEST_HC_BIN") or "hc"
    rdir = run_dir or e.get("SB_RUN_DIR") or e.get("SWARMBOX_TEST_RUN_DIR") or "/tmp/swarmbox"
    pins = load_pins(env=e)
    spawned = []
    parked = []
    skipped = []
    used_names = set()

    # Read currently live terminals and full details so restore is idempotent and detects --keep shells
    existing_by_pin = {}
    try:
        ls = subprocess.run([hc, "ls", "--json"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=5.0, env=e)
        if ls.returncode == 0 and ls.stdout.strip():
            data = json.loads(ls.stdout)
            for t in (data.get("terminals") or []):
                if isinstance(t, dict) and t.get("state", "live") == "live":
                    if t.get("name"):
                        used_names.add(str(t["name"]).lower())
                    addr = t.get("address")
                    detail = dict(t)
                    if addr and (not isinstance(detail.get("labels"), dict) or "foreground" not in detail):
                        gr = subprocess.run([hc, "get", "--json", str(addr)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=5.0, env=e)
                        if gr.returncode == 0 and gr.stdout.strip():
                            try:
                                gd = json.loads(gr.stdout)
                                if isinstance(gd, dict):
                                    detail.update(gd)
                            except ValueError:
                                pass
                    lbls = detail.get("labels") if isinstance(detail.get("labels"), dict) else {}
                    if lbls.get("swarmbox.pin_id"):
                        existing_by_pin[str(lbls["swarmbox.pin_id"])] = detail
    except (OSError, ValueError, subprocess.TimeoutExpired):
        pass

    replaced_addrs = set()
    for pin in pins:
        pid = pin["id"]
        existing = existing_by_pin.get(pid)
        if not pin.get("autostart"):
            if on_boot and existing and _is_shell_only(existing):
                old_addr = str(existing.get("address") or "")
                old_name = str(existing.get("name") or "").lower()
                if old_addr and _close_terminal(hc, old_addr, e):
                    used_names.discard(old_name)
                    parked.append({"id": pid, "closed": old_addr})
            continue

        ag = (pin.get("agent") or "shell").strip().lower()
        replaced = ""
        if existing:
            # Already live: keep as-is for shell pins or when the agent is genuinely running.
            if ag == "shell" or not _is_shell_only(existing):
                continue
            # herdr-core --keep resurrected a bare login shell after restart; replace it with the agent.
            old_addr = str(existing.get("address") or "")
            old_name = str(existing.get("name") or "").lower()
            if old_addr:
                _close_terminal(hc, old_addr, e)
                used_names.discard(old_name)
                replaced = old_addr
                replaced_addrs.add(old_addr)

        cwd = pin.get("cwd") or ""
        if not cwd or not os.path.isdir(cwd):
            skipped.append({"id": pid, "reason": "missing_cwd", "cwd": cwd})
            continue
        base_name = _slug(pin.get("title") or pin.get("agent") or "pin", "pin")
        name = base_name
        n = 2
        while name in used_names:
            name = "%s-%d" % (base_name[:24], n)
            n += 1
        used_names.add(name)

        argv = build_agent_argv(ag, pin.get("resume") or "continue")
        cmd = [
            hc, "run", "--bg", "--keep", "--no-parent", "--json",
            "--name", name,
            "--cwd", cwd,
            "--label", "swarmbox.pin_id=%s" % pid,
            "--label", "swarmbox.title=%s" % _clean_title(pin.get("title") or name),
            "--label", "swarmbox.agent=%s" % ag,
        ]
        if pin.get("title_source"):
            cmd += ["--label", "swarmbox.title_source=%s" % pin["title_source"]]
        wt = pin.get("worktree")
        if isinstance(wt, dict) and wt.get("path"):
            cmd += ["--label", "swarmbox.worktree=%s" % wt["path"]]
            if wt.get("repo"):
                cmd += ["--label", "swarmbox.repo=%s" % wt["repo"]]
            if wt.get("branch"):
                cmd += ["--label", "swarmbox.branch=%s" % wt["branch"]]
            if wt.get("base"):
                cmd += ["--label", "swarmbox.base=%s" % wt["base"]]
        cmd += ["--"] + argv
        try:
            r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=10.0, env=e)
            if r.returncode == 0:
                addr = ""
                try:
                    res = json.loads(r.stdout)
                    addr = str(res.get("address") or (res.get("terminal") or {}).get("address") or "")
                except ValueError:
                    pass
                rec = {"id": pid, "address": addr, "name": name}
                if replaced:
                    rec["replaced"] = replaced
                spawned.append(rec)
            else:
                skipped.append({"id": pid, "reason": "hc_failed", "msg": (r.stderr or r.stdout).strip()[:160]})
        except (OSError, subprocess.TimeoutExpired) as exc:
            skipped.append({"id": pid, "reason": "hc_error", "msg": str(exc)})

    if spawned and spawned[0].get("address"):
        try:
            os.makedirs(rdir, mode=0o700, exist_ok=True)
            marker = os.path.join(rdir, "herdr-active-tab")
            cur_active = ""
            if os.path.exists(marker):
                with open(marker, encoding="utf-8") as f:
                    cur_active = f.read().strip()
            if not cur_active or cur_active in replaced_addrs:
                with open(marker, "w", encoding="utf-8") as f:
                    f.write(spawned[0]["address"] + "\n")
        except OSError:
            pass

    return {"ok": True, "spawned": spawned, "parked": parked, "skipped": skipped}


def _parse_args(argv, takes=(), flags=()):
    opts, rest, i = {}, [], 0
    while i < len(argv):
        x = argv[i]
        if x in takes:
            if i + 1 >= len(argv):
                raise PinsError("usage", "%s takes a value" % x)
            opts[x] = argv[i + 1]
            i += 2
        elif x in flags:
            opts[x] = True
            i += 1
        elif x.startswith("-"):
            raise PinsError("usage", "unknown option %s" % x)
        else:
            rest.append(x)
            i += 1
    return opts, rest


def _parse_bool(raw, flag):
    s = str(raw).strip().lower()
    if s in ("1", "true", "yes", "on"):
        return True
    if s in ("0", "false", "no", "off"):
        return False
    raise PinsError("bad_arg", "%s expects 0 or 1" % flag)


def run_cli(argv, env=None):
    if not argv:
        raise PinsError("usage", "command required: list, add, update, rm, restore")
    cmd, a = argv[0], argv[1:]
    if cmd == "list":
        pins = load_pins(env=env)
        for p in pins:
            p["missing_cwd"] = not os.path.isdir(p.get("cwd") or "")
        return pins
    if cmd == "add":
        opts, rest = _parse_args(a, ("--cwd", "--agent", "--title", "--title-source", "--resume"), ("--autostart",))
        if rest or "--cwd" not in opts:
            raise PinsError("usage", "usage: add --cwd DIR [--agent AGENT] [--title TITLE] [--resume continue|fresh] [--autostart]")
        return add_pin(
            cwd=opts["--cwd"],
            agent=opts.get("--agent", "shell"),
            title=opts.get("--title", ""),
            title_source=opts.get("--title-source", "user" if "--title" in opts else ""),
            resume=opts.get("--resume", "continue"),
            autostart="--autostart" in opts,
            env=env,
        )
    if cmd == "update":
        opts, rest = _parse_args(a, ("--title", "--title-source", "--cwd", "--agent", "--resume", "--autostart"), ())
        if len(rest) != 1:
            raise PinsError("usage", "usage: update PIN_ID [--title TITLE] [--cwd DIR] [--agent AGENT] [--resume continue|fresh] [--autostart 0|1]")
        return update_pin(
            rest[0],
            title=opts.get("--title"),
            title_source=opts.get("--title-source"),
            cwd=opts.get("--cwd"),
            agent=opts.get("--agent"),
            resume=opts.get("--resume"),
            autostart=_parse_bool(opts["--autostart"], "--autostart") if "--autostart" in opts else None,
            env=env,
        )
    if cmd == "rm":
        _, rest = _parse_args(a)
        if len(rest) != 1:
            raise PinsError("usage", "usage: rm PIN_ID")
        return remove_pin(rest[0], env=env)
    if cmd == "restore":
        opts, rest = _parse_args(a, (), ("--boot",))
        if rest:
            raise PinsError("usage", "usage: restore [--boot]")
        return restore_autostart_pins(env=env, on_boot="--boot" in opts)
    raise PinsError("usage", "unknown command %s" % cmd)


def main(argv):
    if argv[:1] in (["-h"], ["--help"], ["help"]):
        print(__doc__)
        return 0
    try:
        out, rc = run_cli(argv), 0
    except PinsError as e:
        out, rc = {"err": e.code, "msg": e.message}, EXIT.get(e.code, 1)
    print(json.dumps(out, ensure_ascii=False))
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
