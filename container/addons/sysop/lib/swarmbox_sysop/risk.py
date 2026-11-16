"""Host-computed risk of a text typed into a shell. Never taken from the brain (the model that drives the sysop).

classify_command(text) -> (level, reasons)   level is "low", "medium" or "high"

Adapted from container/addons/voice/lib/swarmbox_voice/risk.py (the sysop takes it over from voice): the analysis of a shell text is the same,
with more high-risk patterns (writes to sensitive paths by cp/mv/tee/install/chmod/sed -i/truncate, a command given to ssh, code strings that
delete or run programs, the fork bomb). What a tab runs, what is typed in several parts and the autonomy levels are in policy.py.
The analysis is deliberately conservative (it flags quoted separators too) and best effort: it is not a sandbox. The countdown, the approval
and the audit file are what stands between the brain and the box; this only decides which of them applies.
"""
import os
import re
import shlex
import unicodedata

LEVELS = ("low", "medium", "high")
AGENT_COMMANDS = ("claude", "gemini", "opencode", "codex", "aider")
SHELLS = ("sh", "bash", "zsh", "dash", "ksh", "fish", "ash", "busybox")
_MAX_DEPTH = 4

_WRAPPERS = ("env", "command", "builtin", "exec", "nohup", "time", "nice", "ionice", "stdbuf", "timeout", "setsid",
             "xargs", "busybox", "watch", "chronic", "strace", "ltrace", "unshare", "systemd-run", "nsenter", "fakeroot", "unbuffer")
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
_SENSITIVE_NAME = re.compile(r"(^|/)(\.bashrc|\.zshrc|\.profile|\.bash_profile|authorized_keys|\.gitconfig|\.npmrc|\.netrc|\.env)$|(^|/)\.(ssh|gnupg|aws)(/|$)")
# What reaches the box's own controls: the files of the sysop (an approval is a file any process of the user can write), tmux (it types into
# any pane, the panel's included, and kills the session), swarmbox-tabs (it types into any tab: `swarmbox tabs send @2 --run ls`), the bus and the sysop commands.
# Matched on the text as a whole, quoted or not, so a payload in a quoted argument does not hide.
_SELF = re.compile(r"(?i)decision\.json|pending_action|events\.jsonl|stop\.request|/sysop\b|\bsysop/|swarmbox[-_ ]?sysop|(?<![\w-])tmux(?![\w-])|"
                   r"swarmbox[-_ ]?tabs|SB_TABS_|swarmbox[-_]bus|swarmbox\s+bus\b|\bbus\s+(pub|sub|serve|stop|tabs|screen)\b|bus\.sock")
# files that hold secrets: reading them is at least medium (a screen is redacted by patterns only)
_SECRET = re.compile(r"(?i)(^|[/=~])\.(ssh|gnupg|aws|docker|kube)(/|$)|(^|/)id_(rsa|dsa|ecdsa|ed25519)|\.(pem|key|p12|pfx|kdbx)$|(^|/)\.(env|netrc|pgpass|npmrc|git-credentials)\b|"
                     r"(^|/)(credentials|secrets?)(\.[a-z]+)?$|(^|/)\.config/(gh|gcloud)(/|$)|^/proc/(\d+|self|thread-self|\*)/(environ|cmdline|mem|fd(/|$))|^/proc/self/")
_ASSIGN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*\+?=")
# variables whose value is run as code or changes what runs (the shell runs PROMPT_COMMAND before every prompt, BASH_ENV in every script...)
_HOOK_VARS = ("PROMPT_COMMAND", "PS0", "PS1", "PS2", "PS4", "BASH_ENV", "ENV", "LD_PRELOAD", "LD_LIBRARY_PATH", "LD_AUDIT", "SHELLOPTS", "BASHOPTS",
              "PYTHONSTARTUP", "PYTHONPATH", "NODE_OPTIONS", "GIT_SSH_COMMAND", "GIT_ASKPASS", "SSH_ASKPASS", "EDITOR", "VISUAL", "PAGER")
_VAR_SETTERS = ("export", "declare", "typeset", "readonly", "local")
# the login of Claude Code lives in the environment of process 1, readable by every process of the user
_SECRET_ENV = re.compile(r"(?i)CLAUDE_CODE_OAUTH_TOKEN|ANTHROPIC_API_KEY")
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
                target = toks[i + 1] if i + 1 < len(toks) else ""
                if tok == "<<<":
                    cur.append("\x01" + target)      # the text a command reads is code when the command is a shell or an interpreter (see _segment)
                elif tok == "<" and _SECRET.search(target):
                    acc.add("medium", "reads a file that holds secrets (%s)" % target[:40])
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
    "strace": ("-o", "-e", "-p", "-s", "-u", "-E"), "ltrace": ("-o", "-e", "-p", "-s", "-u"), "systemd-run": ("-u", "--unit", "-p", "--property", "--description", "--slice"),
    "nsenter": ("-t", "--target"),
}
# words that only introduce a command in shell syntax: `! cmd`, `do cmd`, `then cmd`, `coproc cmd`, `{ cmd; }`
_PREFIXES = ("!", "coproc", "do", "then", "else", "elif", "if", "while", "until", "{", "function")


def _hook_assignment(word, acc, depth):
    """NAME=value where NAME is a hook or a state variable of the shell: the quoted value is code (or a path that code is loaded from)."""
    m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\+?=(.*)$", word, re.S)
    if not m:
        return
    name, value = m.group(1), m.group(2)
    if name in _HOOK_VARS:
        acc.add("high", "sets %s, which makes the shell run or load code later" % name)
        if depth < _MAX_DEPTH and value.strip():
            _analyse(value, acc, depth + 1)
    elif name == "PATH":
        acc.add("medium", "changes PATH, so other programs run under the same names")


def _strip_wrappers(words, acc=None, depth=0):
    """Drop env assignments, shell keywords and wrapper commands from the front; return the remaining words."""
    guard = 0
    while words and guard < 20:
        guard += 1
        w = words[0]
        if _ASSIGN.match(w):
            if acc is not None:
                _hook_assignment(w, acc, depth)
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
                    if acc is not None and _ASSIGN.match(rest[0]):
                        _hook_assignment(rest[0], acc, depth)
                    rest = rest[1:]
            words = rest
            continue
        break
    return words


def _git(words, acc):
    args = []
    i = 1
    while i < len(words):
        if words[i] == "-c" and i + 1 < len(words) and (re.match(r"(?i)alias\.[^=]*=\s*!", words[i + 1]) or _GIT_PROGRAM.match(words[i + 1])):
            acc.add("high", "git -c sets a program that git then runs")
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


_WRITERS = ("cp", "mv", "ln", "tee", "install", "truncate", "chmod", "chown", "chgrp", "sed", "rsync", "scp", "unlink", "rmdir", "touch")
_CODE_DANGER = re.compile(r"(?i)os\s*\.\s*(system|popen|remove|unlink|rmdir|exec|spawn)|subprocess|rmtree|shutil|child_process|\beval\b|\bexec\b|"
                          r"__import__|\bsystem\s*\(|\bunlink\b|`|\bpopen\b|File\s*\.\s*(delete|write)|fs\s*\.\s*(rm|unlink|write)")
_SSH_ARGS = ("-p", "-i", "-l", "-o", "-F", "-J", "-L", "-R", "-D", "-b", "-c", "-e", "-m", "-w", "-W", "-E", "-S", "-B", "-Q", "-I", "-O")


def _ssh_remote(rest):
    """The words after the host of an ssh command line (the remote command), or []."""
    i = 0
    while i < len(rest):
        a = rest[i]
        if a in _SSH_ARGS:
            i += 2
        elif a.startswith("-"):
            i += 1
        else:
            return rest[i + 1:]       # rest[i] is the host
    return []


_EDITOR_SHELL = re.compile(r"(^|[:\s|])!\s*(\S.*)")
_CODE_READERS = ("python", "python3", "perl", "ruby", "node", "php", "awk", "gawk", "mawk")
_GIT_PROGRAM = re.compile(r"(?i)^(core\.(pager|editor|sshcommand|fsmonitor|askpass|hookspath)|pager\.|sequence\.editor|credential\.helper|diff\.external|gpg\.program|alias\.)")


_LIST_ONLY = ("-l", "-p", "-P", "-v", "-V", "-s", "-S", "-a", "-f", "-r")


def _shell_state(cmd, rest, acc, depth):
    """Builtins that make the shell run text later or change what runs: an alias, a trap, a key binding, a completion command, a variable that
    is a hook. The text they hold is code that runs without another Enter, so it is high and it is analysed too."""
    args = [a for a in rest if not a.startswith("-")]
    code = None
    if cmd == "alias" and args:
        acc.add("high", "alias redefines a command name: what runs later is not what is typed")
        code = [a.split("=", 1)[1] for a in args if "=" in a]
    elif cmd == "trap" and args and not (len(args) == 1 and "-l" in rest) and args[0] != "-" and rest[:1] != ["-p"]:
        acc.add("high", "trap runs a command when a signal or an event happens")
        code = args[:1]
    elif cmd == "bind" and any(a == "-x" or (a.startswith("-") and not a.startswith("--") and "x" in a) for a in rest) or \
            (cmd == "bind" and any(":" in a for a in args)):
        acc.add("high", "bind attaches a command or a macro to a key")
        code = args
    elif cmd in ("complete", "compgen") and any(a in ("-C", "-F") or (a.startswith("-") and not a.startswith("--") and ("C" in a or "F" in a)) for a in rest):
        acc.add("high", "%s runs a command or a function" % cmd)
        code = args
    elif cmd == "enable" and any(a == "-f" for a in rest):
        acc.add("high", "enable -f loads a compiled builtin")
    elif cmd in _VAR_SETTERS or cmd in ("set", "unset"):
        for a in rest:
            _hook_assignment(a, acc, depth)
    elif cmd in ("printenv", "env") and not args:
        acc.add("medium", "%s prints the environment, where the login of the box lives" % cmd)
    if code and depth < _MAX_DEPTH:
        for c in code:
            if c.strip():
                _analyse(c, acc, depth + 1)


def _segment(words, acc, depth, after_pipe):
    here = [w[1:] for w in words if w.startswith("\x01")]
    raw = [w for w in words if not w.startswith("\x01")]
    words = _strip_wrappers(raw, acc, depth)
    if not words:
        if raw and os.path.basename(raw[0]).lower() == "env" and not any(_ASSIGN.match(w) for w in raw):
            acc.add("medium", "env prints the environment, where the login of the box lives")
        return
    if re.search(r"\s", words[0]) and depth < _MAX_DEPTH:
        # a command "name" with blanks is a whole command line in one quoted string (`watch -n1 'rm -rf x'`): the wrappers run it through a shell
        acc.add("medium", "a command line given as one quoted string")
        _analyse(words[0] + " " + " ".join(words[1:]), acc, depth + 1)
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
    for a in rest:
        if _SECRET.search(a):
            acc.add("medium", "touches a file that holds secrets (%s)" % a[:40])
            break
    if here and depth < _MAX_DEPTH:
        if cmd in SHELLS or cmd in ("at", "batch", "ex", "vi", "vim", "nvim") or cmd in _CODE_READERS:
            acc.add("medium", "%s reads the text it runs from the command line" % cmd)
            for h in here:
                if cmd not in SHELLS and _CODE_DANGER.search(h):
                    acc.add("high", "%s code that deletes files or runs programs" % cmd)
                if cmd in SHELLS or cmd in ("at", "batch"):
                    _analyse(h, acc, depth + 1)
    _shell_state(cmd, rest, acc, depth)
    if cmd in ("exit", "logout"):
        acc.add("medium", "%s ends the shell of the tab" % cmd)
    if cmd == "script" and "-c" in rest and rest.index("-c") + 1 < len(rest) and depth < _MAX_DEPTH:
        acc.add("medium", "script runs a command")
        _analyse(rest[rest.index("-c") + 1], acc, depth + 1)
    if cmd in ("awk", "gawk", "mawk") and any(re.search(r'system\s*\(|\|\s*"|\|&', a) for a in rest):
        acc.add("high", "awk runs a command")
    if cmd in ("vim", "vi", "ex", "view", "nvim", "less", "man"):
        for a in rest:
            m = _EDITOR_SHELL.search(a)
            if m and depth < _MAX_DEPTH:
                acc.add("medium", "%s runs a shell command" % cmd)
                _analyse(m.group(2), acc, depth + 1)
    if cmd in _WRITERS:
        for a in rest:
            if not a.startswith("-") and (_SENSITIVE_TARGET.match(a) or _SENSITIVE_NAME.search(a)):
                acc.add("high", "%s writes a sensitive path (%s)" % (cmd, a[:40]))
                break
    if cmd in ("ssh", "autossh", "mosh") and depth < _MAX_DEPTH:
        remote = _ssh_remote(rest)
        if remote:
            acc.add("medium", "%s runs a command on another machine" % cmd)
            _analyse(" ".join(remote), acc, depth + 1)
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
    elif (cmd in ("nc", "ncat", "netcat", "socat", "telnet") and any(not a.startswith("-") for a in rest)) or \
            (cmd == "openssl" and rest[:1] in (["s_client"], ["s_server"])):
        acc.add("medium", "%s opens a network connection" % cmd)
    if cmd == "tar" and any((a.startswith("-") and not a.startswith("--") and "x" in a) or a in ("x", "--extract", "--get") or (not a.startswith("-") and a[:1] == "x") for a in rest[:2]):
        acc.add("medium", "tar extracts files")
        for j, a in enumerate(rest):
            tgt = a.split("=", 1)[1] if a.startswith("--directory=") else (rest[j + 1] if a in ("-C", "--directory") and j + 1 < len(rest) else None)
            if tgt is not None and (tgt == "/" or _SENSITIVE_TARGET.match(tgt.rstrip("/") + "/") or ".." in tgt.split("/")):
                acc.add("high", "tar extracts into a system folder")
    if cmd in ("curl", "wget") and any(a.split("=", 1)[0] in ("-F", "--form", "--post-file", "--post-data", "--body-file") or a.startswith("--form") for a in rest):
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
                    if cmd not in SHELLS and _CODE_DANGER.search(rest[j + 1]):
                        acc.add("high", "%s code that deletes files or runs programs" % cmd)
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
    text = re.sub(r"\\\r?\n", "", _normalize(text))        # a backslash before a line break joins the lines in a shell
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


_FORK_BOMB = re.compile(r"(?s):\s*\(\s*\)\s*\{.*:\s*\|\s*:|\b(\w+)\s*\(\s*\)\s*\{[^}]*\b\1\b[^}]*\|[^}]*\b\1\b[^}]*&")


def classify_command(text):
    """(level, reasons) of a text typed into a shell."""
    acc = _Acc()
    if not isinstance(text, str):
        return "high", ["the text is not a string"]
    if _FORK_BOMB.search(text):
        acc.add("high", "a function that calls itself in the background (fork bomb)")
    flat = re.sub(r"\\\r?\n", "", _normalize(text))
    if _SELF.search(flat) or _SELF.search(flat.replace("\\", "").replace("'", "").replace('"', "")):
        acc.add("high", "touches the controls of the box or of the sysop itself (tmux, the bus, the sysop's files)")
    if _SECRET_ENV.search(flat):
        acc.add("medium", "names the login of the box (an environment variable that holds a token)")
    if re.search(r"/dev/(tcp|udp)/", flat):
        acc.add("medium", "opens a network connection from the shell")
    _analyse(text, acc, 0)
    if not acc.reasons:
        acc.reasons.append("no risky pattern found")
    return acc.level, acc.reasons
