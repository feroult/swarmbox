"""Host-computed risk. Never taken from the planner.

classify_command(text)        -> (level, reasons)   level is "low", "medium" or "high"
action_risk(action, panes)    -> (level, reasons)   panes: {pane_id: pane dict} (the input panes); may be empty
plan_risk(plan, panes)        -> {"level", "reasons", "needs_confirmation", "actions": [{"level", "reasons"}]}

The text of a send_text is treated as shell input unless the target pane is known to run an agent (claude, gemini, ...),
where it is only prompt text. enter=false does not lower the risk: the text is still in the line buffer. The analysis is
deliberately conservative (it flags quoted separators too) and best effort: it is not a sandbox, the confirmation card is.
needs_confirmation is True for every plan in this phase (ALWAYS_CONFIRM); a later allow-list of low-risk actions would
change only that function.
"""
import os
import re
import shlex
import unicodedata

LEVELS = ("low", "medium", "high")
ALWAYS_CONFIRM = True
AGENT_COMMANDS = ("claude", "gemini", "opencode", "codex", "aider")
SHELLS = ("sh", "bash", "zsh", "dash", "ksh", "fish", "ash", "busybox")
_MAX_DEPTH = 4

_WRAPPERS = ("env", "command", "builtin", "exec", "nohup", "time", "nice", "ionice", "stdbuf", "timeout", "setsid",
             "xargs", "busybox", "watch", "chronic")
_HIGH_CMDS = {
    "rm": "rm deletes files", "shred": "shred destroys files", "dd": "dd writes raw data", "wipefs": "wipefs erases disks",
    "fdisk": "partitioning", "parted": "partitioning", "sfdisk": "partitioning", "shutdown": "shuts the machine down",
    "reboot": "reboots the machine", "halt": "halts the machine", "poweroff": "powers the machine off",
    "sudo": "sudo runs as root", "su": "su switches user", "doas": "doas runs as root", "pkexec": "pkexec runs as root",
    "eval": "eval runs built text", "crontab": "crontab changes scheduled jobs",
}
_MEDIUM_CMDS = {
    "mv": "mv overwrites files", "cp": "cp overwrites files", "ln": "ln changes links", "tee": "tee writes files",
    "truncate": "truncate changes files", "kill": "kill stops processes", "pkill": "pkill stops processes",
    "killall": "killall stops processes", "chmod": "chmod changes permissions", "chown": "chown changes owners",
    "chgrp": "chgrp changes groups", "ssh": "ssh reaches another machine", "scp": "scp copies to or from another machine",
    "rsync": "rsync copies files", "source": "source runs a script", ".": "source runs a script",
    "unlink": "unlink deletes a file", "rmdir": "rmdir deletes a directory", "install": "install writes files",
    "systemctl": "systemctl changes services", "service": "service changes services", "mount": "mount changes mounts",
    "umount": "umount changes mounts", "iptables": "firewall", "useradd": "users", "userdel": "users", "passwd": "users",
}
_INTERPRETERS = ("sh", "bash", "zsh", "dash", "ksh", "fish", "ash", "python", "python3", "perl", "ruby", "node", "php",
                 "eval", "source", ".", "sudo", "su", "doas")
_SENSITIVE_TARGET = re.compile(r"^(/dev/(?!null$|stdout$|stderr$|tty$)|/etc/|/boot/|/usr/|/bin/|/sbin/|/lib|/var/|/sys/|/proc/|/root)")
_SENSITIVE_NAME = re.compile(r"(^|/)(\.bashrc|\.zshrc|\.profile|\.bash_profile|\.ssh(/|$)|authorized_keys|\.gitconfig|\.npmrc|\.netrc|\.env)$")
_ASSIGN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_REDIRECT = re.compile(r"^(\d*)(>>|>\||>|&>>|&>)$")


def _max(a, b):
    return a if LEVELS.index(a) >= LEVELS.index(b) else b


class _Acc:
    def __init__(self):
        self.level = "low"
        self.reasons = []
        self.budget = 200   # analysed strings left (nested code can multiply)

    def add(self, level, reason):
        self.level = _max(self.level, level)
        if reason not in self.reasons:
            self.reasons.append(reason)


def _normalize(text):
    text = unicodedata.normalize("NFKC", text)
    return "".join(" " if unicodedata.category(c) in ("Zs", "Zl", "Zp") else c
                   for c in text if unicodedata.category(c) != "Cf")


def _tokens(line):
    """Tokens of one line with ; & | < > ( ) as separate tokens, or None when the quoting is broken."""
    try:
        lex = shlex.shlex(line, posix=True, punctuation_chars=True)
        lex.whitespace_split = True
        lex.commenters = ""
        return list(lex)
    except ValueError:
        return None


def _fallback_tokens(line):
    spaced = re.sub(r"([;&|()<>])", r" \1 ", line.replace("'", " ").replace('"', " "))
    return spaced.split()


def _segments(text, acc):
    """Split text into command segments (lists of words), handling redirects. Records chaining and redirect risk."""
    segs, cur = [], []
    lines = text.replace("\r", "\n").replace("`", " ; ").split("\n")
    if len(lines) > 1 or "`" in text:
        acc.add("medium", "several commands in one text")
    for line in lines:
        toks = _tokens(line)
        if toks is None:
            acc.add("medium", "unbalanced quotes")
            toks = _fallback_tokens(line)
        i = 0
        while i < len(toks):
            tok = toks[i]
            if tok and set(tok) <= set(";&|()"):
                acc.add("medium", "chained or grouped commands (%s)" % tok)
                if cur:
                    segs.append(cur)
                cur = []
                if tok in ("|", "|&", "&&", "||", ";", "&"):
                    segs.append(["\x00" + tok])
            elif tok in ("<", "<<", "<<<", "<(", ">("):
                if tok in ("<(", ">("):
                    acc.add("medium", "process substitution")
                i += 1  # the target word
            elif _REDIRECT.match(tok):
                target = toks[i + 1] if i + 1 < len(toks) else ""
                _redirect(acc, target, append=">>" in tok)
                i += 1
            elif tok in (">&", "<&", "2>&1"):
                i += 1
            else:
                cur.append(tok)
            i += 1
        if cur:
            segs.append(cur)
            cur = []
    return segs


def _redirect(acc, target, append):
    t = target.lower()
    if t in ("/dev/null", "/dev/stdout", "/dev/stderr") or t.isdigit():
        return
    if _SENSITIVE_TARGET.match(target) or _SENSITIVE_NAME.search(target) or ".." in target.split("/"):
        acc.add("high", "redirect to a sensitive path (%s)" % target[:40])
    elif append:
        acc.add("medium", "redirect appends to a file")
    else:
        acc.add("medium", "redirect overwrites a file")


def _is_dynamic(word):
    return any(c in word for c in "$*?[{") or any(ord(c) > 127 for c in word)


# options of a wrapper that take a separate argument (the next word is not the command)
_WRAPPER_ARGS = {
    "env": ("-u", "--unset", "-C", "--chdir"), "nice": ("-n", "--adjustment"), "ionice": ("-c", "-n", "-p", "-P", "-t"),
    "stdbuf": ("-i", "-o", "-e", "--input", "--output", "--error"), "timeout": ("-s", "--signal", "-k", "--kill-after"),
    "xargs": ("-I", "-L", "-n", "-P", "-s", "-E", "-d", "-a", "-l", "--max-args", "--max-procs", "--delimiter", "--arg-file",
              "--max-lines", "--max-chars", "--replace"),
    "exec": ("-a",), "time": ("-f", "-o", "--format", "--output"), "watch": ("-n", "-d", "--interval"),
}
# words that only introduce a command in shell syntax: `! cmd`, `do cmd`, `then cmd`, `coproc cmd`, `{ cmd; }`
_PREFIXES = ("!", "coproc", "do", "then", "else", "elif", "if", "while", "until", "{", "function")


def _strip_wrappers(words):
    """Drop env assignments, shell keywords and wrapper commands from the front; return the remaining words."""
    guard = 0
    while words and guard < 20:
        guard += 1
        w = words[0]
        if _ASSIGN.match(w):
            words = words[1:]
            continue
        if w in _PREFIXES:
            words = words[1:]
            continue
        base = os.path.basename(w.lstrip("\\")).lower()
        if base in _WRAPPERS:
            rest = words[1:]
            takes = _WRAPPER_ARGS.get(base, ())
            while rest and (rest[0].startswith("-") or _ASSIGN.match(rest[0]) or
                            (base in ("timeout", "nice", "ionice", "watch") and re.fullmatch(r"[0-9.]+[smhd]?", rest[0]))):
                if base == "env" and rest[0] in ("-S", "--split-string") and len(rest) > 1:
                    try:
                        rest = shlex.split(rest[1]) + rest[2:]
                    except ValueError:
                        rest = rest[2:]
                elif rest[0] in takes and len(rest) > 1:
                    rest = rest[2:]
                else:
                    rest = rest[1:]
            words = rest
            continue
        break
    return words


def _git(words, acc):
    args = []
    i = 1
    while i < len(words):
        if words[i] == "-c" and i + 1 < len(words) and re.match(r"(?i)alias\.[^=]*=\s*!", words[i + 1]):
            acc.add("high", "git -c defines a shell alias")
        if words[i] in ("-C", "-c", "--git-dir", "--work-tree", "--namespace") and i + 1 < len(words):
            i += 2
        elif words[i].startswith("-"):
            i += 1
        else:
            args = words[i:]
            break
    if not args:
        return
    sub, rest = args[0], args[1:]
    force = any(a in ("-f", "--force", "--force-with-lease", "--mirror", "--delete", "-d") or a.startswith("--force")
                or (a.startswith("+") and len(a) > 1) for a in rest)
    if sub == "push":
        acc.add("high", "git push FORCE" if force else "git push")
    elif sub == "reset" and "--hard" in rest:
        acc.add("high", "git reset --hard discards work")
    elif sub == "clean":
        acc.add("high", "git clean deletes files")
    elif sub == "branch" and any(a in ("-D", "--delete", "-d") for a in rest):
        acc.add("high", "git branch delete")
    elif sub in ("filter-branch", "filter-repo", "update-ref", "reflog") or (sub == "stash" and rest[:1] in (["drop"], ["clear"])):
        acc.add("high", "git %s rewrites or drops history" % sub)
    elif sub in ("checkout", "restore", "switch", "rebase", "merge", "pull", "revert", "cherry-pick", "rm", "mv", "am", "apply"):
        acc.add("medium", "git %s changes the working tree" % sub)


def _segment(words, acc, depth, after_pipe):
    words = _strip_wrappers(words)
    if not words:
        return
    first = words[0].lstrip("\\")
    cmd = os.path.basename(first).lower()
    if _is_dynamic(first):
        acc.add("high", "the command name is built at run time or is not plain ASCII")
        return
    if after_pipe and cmd in _INTERPRETERS:
        acc.add("high", "piped into %s" % cmd)
    if cmd in _HIGH_CMDS:
        acc.add("high", _HIGH_CMDS[cmd])
    elif cmd.startswith("mkfs") or cmd in ("mke2fs", "mkswap"):
        acc.add("high", "mkfs formats a disk")
    elif cmd in _MEDIUM_CMDS:
        acc.add("medium", _MEDIUM_CMDS[cmd])
    rest = words[1:]
    if cmd in ("chmod", "chown", "chgrp") and any(a in ("-R", "-r", "--recursive") or (a.startswith("-") and not a.startswith("--") and "R" in a)
                                                   for a in rest):
        acc.add("high", "%s -R changes a whole tree" % cmd)
    if cmd == "rsync" and any(a.startswith("--delete") for a in rest):
        acc.add("high", "rsync --delete")
    if cmd == "git":
        _git(words, acc)
    if cmd == "find":
        if "-delete" in rest:
            acc.add("high", "find -delete")
        for j, a in enumerate(rest):
            if a in ("-exec", "-execdir", "-ok", "-okdir"):
                inner = []
                for b in rest[j + 1:]:
                    if b in (";", "+"):
                        break
                    inner.append(b)
                _segment(inner, acc, depth, False)
    if ((cmd in ("npm", "yarn", "pnpm") and rest[:1] == ["publish"]) or
            (cmd in ("twine", "cargo", "gem") and rest[:1] in (["upload"], ["publish"], ["push"]))):
        acc.add("high", "publishes a package")
    if cmd in ("npm", "pnpm", "yarn", "pip", "pip3", "apt", "apt-get", "brew", "cargo", "gem") and rest[:1] and rest[0] in ("install", "add", "i", "uninstall", "remove"):
        acc.add("medium", "installs or removes packages")
    if cmd in ("docker", "podman") and rest[:1] and rest[0] in ("rm", "rmi", "run", "system", "volume", "kill", "stop", "exec", "prune"):
        acc.add("medium", "%s changes containers" % cmd)
    if cmd in ("curl", "wget") and any(a in ("-o", "-O", "--output", "-T", "--upload-file", "-d", "--data", "-X") or a.startswith("--data") for a in rest):
        acc.add("medium", "%s writes a file or sends data" % cmd)
    if cmd in ("nc", "ncat", "netcat") and any(a in ("-e", "-c", "--exec", "--sh-exec") for a in rest):
        acc.add("high", "%s runs a program on a connection" % cmd)
    if cmd in ("curl", "wget") and any(a in ("-F", "--form", "--post-file", "--post-data") or a.startswith("--form") for a in rest):
        acc.add("medium", "%s sends data" % cmd)
    if ((cmd == "gh" and rest[:2] in (["pr", "merge"], ["repo", "delete"], ["release", "delete"], ["repo", "archive"])) or
            (cmd == "kubectl" and rest[:1] == ["delete"]) or (cmd in ("terraform", "tofu") and rest[:1] in (["destroy"], ["apply"])) or
            (cmd == "aws" and rest[:2] in (["s3", "rm"], ["s3", "rb"], ["s3", "sync"]))):
        acc.add("high", "%s %s is destructive or public" % (cmd, " ".join(rest[:2])))
    if cmd == "sed" and any(a.startswith("-i") or a == "--in-place" for a in rest):
        acc.add("medium", "sed -i edits files")
    # nested code: analyse the string given to -c / -e
    if cmd in SHELLS or cmd in ("python", "python3", "perl", "ruby", "node", "php"):
        for j, a in enumerate(rest):
            if a in ("-c", "-e", "--eval") or (a.startswith("-") and not a.startswith("--") and a.endswith("c") and cmd in SHELLS):
                acc.add("medium", "%s runs a code string" % cmd)
                if j + 1 < len(rest) and depth < _MAX_DEPTH:
                    _analyse(rest[j + 1], acc, depth + 1)
                break
        else:
            if cmd in SHELLS and cmd != "busybox":
                acc.add("medium", "%s runs a script or shell" % cmd)
    if cmd == "eval" and depth < _MAX_DEPTH:
        _analyse(" ".join(rest), acc, depth + 1)


def _substitutions(text):
    """The code inside $( ... ) (balanced) and between backticks, even when it is inside double quotes."""
    found = []
    i = 0
    while True:
        i = text.find("$(", i)
        if i < 0:
            break
        depth, j = 0, i + 1
        while j < len(text):
            if text[j] == "(":
                depth += 1
            elif text[j] == ")":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        found.append(text[i + 2:j])
        i = j + 1   # top level only: the inner text is analysed again, with its own substitutions
    parts = text.split("`")
    found.extend(parts[k] for k in range(1, len(parts), 2))
    return found


def _analyse(text, acc, depth):
    acc.budget -= 1
    if acc.budget < 0:
        acc.add("high", "too much nested code to analyse")
        return
    text = _normalize(text)
    if depth < _MAX_DEPTH:
        for inner in _substitutions(text):
            if inner.strip():
                acc.add("medium", "command substitution")
                _analyse(inner, acc, depth + 1)
    segs = _segments(text, acc)
    after_pipe = False
    for seg in segs:
        if seg and seg[0].startswith("\x00"):
            after_pipe = seg[0] in ("\x00|", "\x00|&")
            continue
        _segment(seg, acc, depth, after_pipe)
        after_pipe = False


def classify_command(text):
    """(level, reasons) of a text typed into a shell."""
    acc = _Acc()
    if not isinstance(text, str):
        return "high", ["the text is not a string"]
    _analyse(text, acc, 0)
    if not acc.reasons:
        acc.reasons.append("no risky pattern found")
    return acc.level, acc.reasons


def action_risk(action, panes=None):
    panes = panes or {}
    kind = action.get("type") if isinstance(action, dict) else None
    if kind == "select_pane":
        return "low", ["moves focus only"]
    if kind == "new_window":
        return "low", ["opens a window"]
    if kind != "send_text":
        return "high", ["unknown action"]
    pane = panes.get(action.get("pane")) or {}
    cmd = os.path.basename(str(pane.get("command", ""))).lower()
    level, reasons = classify_command(action.get("text", ""))
    if cmd in AGENT_COMMANDS:
        # prompt text for an agent, except `!` (the agent runs the rest in a shell) and `/` (slash commands)
        body = _normalize(action.get("text", "")).lstrip()
        if body.startswith("!"):
            lv, rs = classify_command(body[1:])
            return _max(lv, "medium"), ["%s runs text starting with ! as a shell command" % cmd] + rs
        if body.startswith("/"):
            return "medium", ["slash command for %s" % cmd]
        return "low", ["prompt text for %s" % cmd]
    if action.get("enter") is True:
        reasons = reasons + ["Enter is pressed"]
    return level, reasons


def plan_risk(plan, panes=None):
    if panes is not None and not isinstance(panes, dict):
        panes = {p["id"]: p for p in panes}
    level, reasons, per = "low", [], []
    typed = {}   # pane -> everything typed into it so far by this plan (a command may be split across actions)
    for action in plan.get("actions", []):
        lv, rs = action_risk(action, panes)
        if isinstance(action, dict) and action.get("type") == "send_text" and isinstance(action.get("text"), str):
            pane = action.get("pane")
            typed[pane] = typed.get(pane, "") + action["text"]
            if typed[pane] != action["text"]:
                total = dict(action, text=typed[pane])
                tl, trs = action_risk(total, panes)
                if LEVELS.index(tl) > LEVELS.index(lv):
                    lv, rs = tl, trs + ["the text is typed in several parts"]
        per.append({"level": lv, "reasons": rs})
        level = _max(level, lv)
        reasons.extend(r for r in rs if r not in reasons)
    return {"level": level, "reasons": reasons, "needs_confirmation": ALWAYS_CONFIRM, "actions": per}
