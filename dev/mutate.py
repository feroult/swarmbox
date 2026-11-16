#!/usr/bin/env python3
"""mutate.py: a small mutation-testing harness, the safety net for changes to the test suite.

A mutant is the product code with ONE small change (a comparison flipped, a condition negated, a constant moved by one, an exit code
changed, a call dropped, `and` swapped with `or`, a case branch that never matches, ...). The harness applies one mutant at a time to
a private copy of the repository, runs the test files that cover that product file and records the mutant as

    killed     at least one test file failed (the suite notices the change: good)
    timeout    no test failed but a file hit its time limit (counted as killed: a hang is noticed)
    survived   every selected test file passed (no test checks that behaviour: look at it)
    no-tests   no test file refers to the product file

Standard library only (Python 3.9+). It starts nothing but the test files and never touches the working tree: the mutants live in
copies under $TMPDIR. A test that needs real tmux must be run where tmux is (see "Where to run it").

Commands
    mutate.py plan   [--count N] [--seed S] [--file F ...] [--out plan.json]   choose the mutants, write the plan, print a summary
    mutate.py run    [--plan plan.json | plan options] [-j N] [--timeout S] [--results r.jsonl] [--limit K] [--shard K/N] [--all-tests] [--layer fast|slow|all]
                     run the mutants of the plan (a new one is planned when --plan is absent); every result is appended to the
                     results file at once, so a stopped run continues where it stopped when it is started again with the same files
    mutate.py report --plan plan.json --results r.jsonl [--matrix m.json] [--md out.md]
                     the summary, the survivors and, with --matrix, the kill matrix {mutant: {killed_by: [test files]}}
    mutate.py tests  FILE...                                                    the test files that cover a product file

Choice of mutants: ~250 by default, spread over the product files in TARGETS in proportion to the weight of each (the logic that can
regress: risk classifier and policy, the bus, tabs guards and redaction, the host settings and create-flags, the addon manager, the
entrypoint, the web strip, the voice routing, the release scripts), by a seeded random choice: the same seed and the same sources give
the same plan. A plan file records each mutant as an exact text replacement, so `run --plan plan.json` replays the SAME mutants later
(after the suite was reorganised): a mutant whose original text is no longer in the file is reported as stale and skipped.

Which tests cover a product file: the test files (tests/**/test_*.py, never tests/e2e) whose text refers to the product file by name
(`swarmbox-tabs.py`, `entrypoint.sh`) or, for a module of a Python package, to the package and the module (`swarmbox_sysop` and
`risk`). A file with no reference falls back to every fast test file, with a cap. `--tests a.py,b.py` overrides all of it.
By default the files of one mutant run in the order of --durations (a baseline JSON of seconds per file) or file size, and the mutant
stops at the first failing file; --all-tests runs every selected file (needed for the kill matrix).

Where to run it: tests that start tmux, ttyd or Chromium must not run on a machine whose tmux server matters. Run the harness in the
test image, offline (the same pattern as dev/test-slow.sh):
    podman run --rm --init --pids-limit 0 --network none --userns=keep-id:uid=1000,gid=1000 -v "$PWD":/src:ro -v /some/out:/out \\
        --tmpfs /work:rw,exec,mode=1777,size=6g IMAGE sh -c 'cp -r /src /work/repo && mkdir -p /work/home && cd /work/repo && HOME=/work/home \\
        python3 dev/mutate.py run -j 12 --all-tests --results /out/r.jsonl --plan /out/plan.json'
Use --init: the tests leave orphans (tmux servers) that the harness kills, and without a reaper as PID 1 they pile up as zombies.
The tests of one mutant get a private TMPDIR and HOME; processes they leave behind are found by that TMPDIR in their environment and
killed (never by a name pattern).
"""
import argparse
import ast
import concurrent.futures
import fnmatch
import glob
import hashlib
import json
import os
import queue
import random
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
SYSOP = "container/addons/sysop/lib/swarmbox_sysop/"
VOICE = "container/addons/voice/lib/swarmbox_voice/"

# (product file, weight). The number of mutants of a file is count * weight / sum(weights), at most the number of sites it has.
TARGETS = [
    (SYSOP + "risk.py", 30), (SYSOP + "policy.py", 20), (SYSOP + "brain.py", 8), (SYSOP + "service.py", 10),
    (SYSOP + "mcpserver.py", 10), (SYSOP + "panel.py", 10), (SYSOP + "dock.py", 8), (SYSOP + "watch.py", 6),
    (SYSOP + "audit.py", 8), (SYSOP + "ipc.py", 3), (SYSOP + "keys.py", 6), (SYSOP + "config.py", 3),
    (SYSOP + "busclient.py", 3), (SYSOP + "tabsclient.py", 3), (SYSOP + "cli.py", 4),
    ("container/scripts/swarmbox-bus.py", 25), ("container/scripts/swarmbox-tabs.py", 35),
    ("container/host/swarmbox-host", 28), ("container/scripts/swarmbox-addon.sh", 25), ("container/entrypoint.sh", 22),
    ("container/scripts/swarmbox-web.sh", 7), ("container/scripts/swarmbox-attach.sh", 6), ("container/scripts/swarmbox-shim.sh", 2),
    ("container/scripts/swarmbox-install.sh", 3), ("container/scripts/swarmbox-mcp.sh", 3), ("container/scripts/banner.sh", 2),
    ("container/scripts/swarmbox-statusline.sh", 2), ("container/web/build-index.sh", 2),
    ("container/web/ttyd-clipboard.js", 3), ("container/addons/voice/web/page.js", 4),
    (VOICE + "front.py", 15), (VOICE + "server.py", 8), (VOICE + "stt.py", 5), (VOICE + "config.py", 2),
    ("dev/release.sh", 5), ("dev/release-check.sh", 4), ("dev/release-version.sh", 2), ("dev/record-checksums.sh", 2),
    ("install.sh", 4), ("cloudflare-setup.py", 5),
]

# How likely each kind of mutation is chosen among the sites of a file.
KIND_WEIGHT = {
    "compare": 3, "negate-cond": 3, "boolop": 3, "exit-code": 3, "bool-const": 2, "const": 1, "drop-call": 2,
    "not-removed": 2, "return-none": 1, "arith": 1, "loop-ctl": 1,
    "sh-cmp": 3, "sh-and-or": 3, "sh-str-eq": 2, "sh-negate": 3, "sh-case": 3, "sh-delete": 1, "sh-const": 1, "sh-test-flag": 2,
    "sh-or-true": 2, "js-cmp": 3, "js-andor": 3, "js-const": 1, "js-negate": 3, "js-bool": 2,
}
FALLBACK_CAP = 40
SLOW_HINT = ("real", "browser", "soak", "image", "container", "e2e")


# ---------------------------------------------------------------- mutation sites

def offsets_of_lines(text):
    offs = [0]
    for line in text.splitlines(keepends=True):
        offs.append(offs[-1] + len(line))
    return offs


def mk(kind, text, start, end, new, desc):
    old = text[start:end]
    if new == old:
        return None
    line = text.count("\n", 0, start) + 1
    return {"kind": kind, "start": start, "end": end, "old": old, "new": new, "line": line, "desc": desc}


CMP_SWAP = {ast.Eq: ast.NotEq, ast.NotEq: ast.Eq, ast.Lt: ast.LtE, ast.LtE: ast.Lt, ast.Gt: ast.GtE, ast.GtE: ast.Gt,
            ast.In: ast.NotIn, ast.NotIn: ast.In, ast.Is: ast.IsNot, ast.IsNot: ast.Is}
CMP_INVERT = {ast.Lt: ast.GtE, ast.LtE: ast.Gt, ast.Gt: ast.LtE, ast.GtE: ast.Lt}


def py_sites(text):
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []
    offs = offsets_of_lines(text)
    lines = text.splitlines(keepends=True)

    def pos(lineno, col):   # col is a UTF-8 byte offset
        raw = lines[lineno - 1].encode("utf-8")
        return offs[lineno - 1] + len(raw[:col].decode("utf-8", "ignore"))

    def span(node):
        return pos(node.lineno, node.col_offset), pos(node.end_lineno, node.end_col_offset)

    out = []

    def add(kind, node, new_node_or_text, desc):
        s, e = span(node)
        new = new_node_or_text if isinstance(new_node_or_text, str) else ast.unparse(new_node_or_text)
        m = mk(kind, text, s, e, new, desc)
        if m:
            out.append(m)

    parents = {}
    for p in ast.walk(tree):
        for c in ast.iter_child_nodes(p):
            parents[c] = p

    def exit_context(node):
        p = parents.get(node)
        if isinstance(p, ast.Return):
            return "return"
        if isinstance(p, ast.Call):
            f = p.func
            name = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")
            if name in ("exit", "_exit"):
                return "exit"
        return None

    for node in ast.walk(tree):
        if isinstance(node, ast.Compare):
            for i, op in enumerate(node.ops):
                for table, label in ((CMP_SWAP, "flip"), (CMP_INVERT, "invert")):
                    if type(op) in table:
                        new = ast.Compare(left=node.left, ops=list(node.ops), comparators=list(node.comparators))
                        new.ops[i] = table[type(op)]()
                        add("compare", node, new, "%s %s -> %s" % (label, type(op).__name__, table[type(op)].__name__))
        elif isinstance(node, (ast.If, ast.While, ast.IfExp)):
            t = node.test
            if not (isinstance(t, ast.Constant) or (isinstance(t, ast.UnaryOp) and isinstance(t.op, ast.Not))):
                add("negate-cond", t, "not (%s)" % ast.unparse(t), "negate the condition")
        elif isinstance(node, ast.BoolOp):
            new = ast.BoolOp(op=ast.Or() if isinstance(node.op, ast.And) else ast.And(), values=list(node.values))
            add("boolop", node, new, "%s -> %s" % (type(node.op).__name__, type(new.op).__name__))
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            add("not-removed", node, "(%s)" % ast.unparse(node.operand), "remove a not")
        elif isinstance(node, ast.Constant):
            v = node.value
            ctx = exit_context(node)
            if isinstance(v, bool):
                add("bool-const", node, repr(not v), "%r -> %r" % (v, not v))
            elif isinstance(v, int):
                if ctx:
                    add("exit-code", node, "0" if v else "1", "%s %d -> %d" % (ctx, v, 0 if v else 1))
                elif abs(v) < 10 ** 6:
                    add("const", node, str(v + 1), "constant %d -> %d" % (v, v + 1))
        elif isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
            add("drop-call", node, "pass", "drop the call")
        elif isinstance(node, ast.Return) and node.value is not None and not isinstance(node.value, ast.Constant):
            add("return-none", node, "return None", "return None")
        elif isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub)):
            def numeric(n):
                return (isinstance(n, ast.Constant) and isinstance(n.value, (int, float)) and not isinstance(n.value, bool)) or \
                    (isinstance(n, ast.Call) and getattr(n.func, "id", "") == "len")
            if numeric(node.left) or numeric(node.right):
                new = ast.BinOp(left=node.left, op=ast.Sub() if isinstance(node.op, ast.Add) else ast.Add(), right=node.right)
                add("arith", node, new, "+/-")
        elif isinstance(node, (ast.Break, ast.Continue)):
            add("loop-ctl", node, "continue" if isinstance(node, ast.Break) else "break", "break/continue swapped")
    return out


# shell and JS: line-level mutations ---------------------------------------------------------------------------------------

def quote_state_before(line, idx):
    """True when position idx of the line is inside quotes (a crude scan; good enough to skip `&&` inside strings)."""
    q = None
    i = 0
    while i < idx:
        c = line[i]
        if c == "\\" and q != "'":
            i += 2
            continue
        if q is None and c in "'\"":
            q = c
        elif q == c:
            q = None
        i += 1
    return q is not None


def shell_lines(text):
    """(start offset, line without newline) of the lines a line-level mutation may touch: not comments, not heredoc bodies, not the
    inside of a multi-line single-quoted string, not a continuation of the previous line."""
    res = []
    pos = 0
    heredoc = None
    in_sq = False
    prev_cont = False
    for raw in text.split("\n"):
        line = raw
        start = pos
        pos += len(raw) + 1
        if heredoc is not None:
            if line.strip() == heredoc:
                heredoc = None
            continue
        if in_sq:
            if line.count("'") % 2 == 1:
                in_sq = False
            continue
        stripped = line.strip()
        cont = stripped.endswith("\\")
        skip = prev_cont
        prev_cont = cont
        m = re.search(r"<<-?\s*['\"]?([A-Za-z_][A-Za-z0-9_]*)['\"]?", line)
        if m and not stripped.startswith("#"):
            heredoc = m.group(1)
            continue
        plain = re.sub(r'"(?:\\.|[^"\\])*"', '""', line)
        if plain.count("'") % 2 == 1:
            in_sq = True
            continue
        if not stripped or stripped.startswith("#") or skip:
            continue
        res.append((start, line))
    return res


SH_CMP = {"-eq": "-ne", "-ne": "-eq", "-lt": "-ge", "-le": "-gt", "-gt": "-le", "-ge": "-lt"}
SH_KEYWORD = re.compile(r"^(if|then|else|elif|fi|for|while|until|do|done|case|esac|function|in|\{|\}|\(|\)|;;|local|readonly|export|set|trap|"
                        r"return|exit|break|continue|shift|echo|printf|cat|log|say|ok|fail|usage|die)\b")


def sh_sites(text):
    out = []
    in_case = 0
    lines = shell_lines(text)
    for start, line in lines:
        st = line.strip()
        ind = start + (len(line) - len(line.lstrip()))
        if re.match(r"case\b.*\bin\b\s*$", st):
            in_case += 1
        elif st == "esac" or st.startswith("esac "):
            in_case = max(0, in_case - 1)
        # comparison operators and -z / -n
        for m in re.finditer(r"(?<=\s)(-eq|-ne|-lt|-le|-gt|-ge)(?=\s)", line):
            if not quote_state_before(line, m.start()):
                out.append(mk("sh-cmp", text, start + m.start(), start + m.end(), SH_CMP[m.group(1)], "%s -> %s" % (m.group(1), SH_CMP[m.group(1)])))
        for m in re.finditer(r"(?<=\[ )(-z|-n)(?= )", line):
            new = "-n" if m.group(1) == "-z" else "-z"
            out.append(mk("sh-test-flag", text, start + m.start(), start + m.end(), new, "%s -> %s" % (m.group(1), new)))
        for m in re.finditer(r"(?<=\[ )(-f|-d|-e|-x|-s|-r)(?= )", line):
            out.append(mk("sh-test-flag", text, start + m.start(), start + m.end(), "! " + m.group(1), "negate the file test %s" % m.group(1)))
        for m in re.finditer(r"(?<=\s)(=|==|!=)(?=\s)", line):
            if "[" in line[:m.start()] and "]" in line[m.end():] and not quote_state_before(line, m.start()):
                new = "!=" if m.group(1) in ("=", "==") else "="
                out.append(mk("sh-str-eq", text, start + m.start(), start + m.end(), new, "%s -> %s" % (m.group(1), new)))
        for m in re.finditer(r"(?<=\s)(&&|\|\|)(?=\s)", line):
            if not quote_state_before(line, m.start()):
                new = "||" if m.group(1) == "&&" else "&&"
                out.append(mk("sh-and-or", text, start + m.start(), start + m.end(), new, "%s -> %s" % (m.group(1), new)))
        for m in re.finditer(r"\b(exit|return) (\d+)\b", line):
            v = int(m.group(2))
            new = "%s %d" % (m.group(1), 0 if v else 1)
            out.append(mk("exit-code", text, start + m.start(), start + m.end(), new, "%s -> %s" % (m.group(0), new)))
        for m in re.finditer(r"(-eq|-ne|-lt|-le|-gt|-ge) (\d+)\b", line):
            n = int(m.group(2))
            out.append(mk("sh-const", text, start + m.start(2), start + m.end(2), str(n + 1), "bound %d -> %d" % (n, n + 1)))
        for m in re.finditer(r"\s*\|\| true\b", line):
            if not quote_state_before(line, m.start()):
                out.append(mk("sh-or-true", text, start + m.start(), start + m.end(), "", "drop '|| true'"))
        # a negated condition
        m = re.match(r"(\s*)(if|elif|while|until)\s+(?!!)(\S.*?);\s*(then|do)\b", line)
        if m:
            s = start + m.start(3)
            out.append(mk("sh-negate", text, s, s, "! ", "negate the %s condition" % m.group(2)))
        m = re.match(r"(\s*)(\[\[? |test )", line)
        if m and ("&&" in line or "||" in line):
            s = start + m.start(2)
            out.append(mk("sh-negate", text, s, s, "! ", "negate a guard"))
        # a case branch that never matches
        if in_case:
            m = re.match(r"(\s*)([A-Za-z0-9_./*\"'$@{}:+-]+(?:\|[A-Za-z0-9_./*\"'$@{}:+-]+)*)\)(\s|$)", line)
            if m and ";;" not in line.split(")", 1)[0] and not st.startswith("("):
                out.append(mk("sh-case", text, start + m.start(2), start + m.end(2), "'__mutated_never__'", "the branch %s never matches" % m.group(2)))
        # a dropped command: a plain one-line command that is not control flow
        if (not SH_KEYWORD.match(st) and not st.endswith(("\\", "{", "(", "&&", "||", "|", ";;", "then", "do", "else")) and ";;" not in st
                and not re.match(r"[A-Za-z_][A-Za-z0-9_]*\(\)", st) and not re.match(r"\S+\)\s", st) and "<<" not in st
                and not st.endswith(")") and not st.startswith(("}", ")"))):
            out.append(mk("sh-delete", text, ind, start + len(line.rstrip()), ":", "drop the line"))
    return [m for m in out if m]


def js_sites(text):
    out = []
    pos = 0
    in_block = False
    for line in text.split("\n"):
        start = pos
        pos += len(line) + 1
        st = line.strip()
        if in_block:
            in_block = "*/" not in st
            continue
        if st.startswith("/*"):
            in_block = "*/" not in st
            continue
        if not st or st.startswith("//") or st.startswith("*"):
            continue
        code = line.split("//")[0] if "//" in line and "http" not in line and not quote_state_before(line, line.index("//")) else line
        for m in re.finditer(r"(===|!==|<=|>=|(?<![<>=!])<(?![<=])|(?<![<>=!-])>(?![>=]))", code):
            swap = {"===": "!==", "!==": "===", "<=": "<", ">=": ">", "<": "<=", ">": ">="}[m.group(1)]
            if not quote_state_before(code, m.start()):
                out.append(mk("js-cmp", text, start + m.start(), start + m.end(), swap, "%s -> %s" % (m.group(1), swap)))
        for m in re.finditer(r"(&&|\|\|)", code):
            if not quote_state_before(code, m.start()):
                new = "||" if m.group(1) == "&&" else "&&"
                out.append(mk("js-andor", text, start + m.start(), start + m.end(), new, "%s -> %s" % (m.group(1), new)))
        for m in re.finditer(r"(?<![\w.$\"'#-])(\d+)(?![\w.\"'%px])", code):
            n = int(m.group(1))
            if not quote_state_before(code, m.start()) and n < 10 ** 6:
                out.append(mk("js-const", text, start + m.start(), start + m.end(), str(n + 1), "constant %d -> %d" % (n, n + 1)))
        m = re.match(r"(\s*(?:\} else )?if \()(.*)(\) \{\s*)$", code)
        if m:
            out.append(mk("js-negate", text, start + m.end(1), start + m.start(3), "!(" + m.group(2) + ")", "negate the condition"))
        for m in re.finditer(r"\b(true|false)\b", code):
            if not quote_state_before(code, m.start()):
                new = "false" if m.group(1) == "true" else "true"
                out.append(mk("js-bool", text, start + m.start(), start + m.end(), new, "%s -> %s" % (m.group(1), new)))
    return [m for m in out if m]


def sites_for(path, text):
    if path.endswith(".py"):
        return py_sites(text)
    if path.endswith(".js"):
        return js_sites(text)
    return sh_sites(text)


def valid(path, new_text):
    """True when the mutated file still parses (a mutant that does not parse is a useless one, not a kill)."""
    try:
        if path.endswith(".py"):
            compile(new_text, path, "exec")
            return True
        with tempfile.NamedTemporaryFile("w", suffix=os.path.splitext(path)[1] or ".sh", delete=False) as f:
            f.write(new_text)
            tmp = f.name
        try:
            if path.endswith(".js"):
                node = shutil.which("node")
                return True if not node else subprocess.run([node, "--check", tmp], capture_output=True).returncode == 0
            first = new_text.split("\n", 1)[0]
            shell = "bash" if "bash" in first else "sh"
            return subprocess.run([shell, "-n", tmp], capture_output=True).returncode == 0
        finally:
            os.unlink(tmp)
    except Exception:
        return False


# ---------------------------------------------------------------- the plan

def mutant_id(path, m):
    h = hashlib.sha1(("%s|%s|%d|%d|%s|%s" % (path, m["kind"], m["line"], m["start"], m["old"], m["new"])).encode()).hexdigest()[:8]
    return "%s:%d:%s:%s" % (os.path.basename(path), m["line"], m["kind"], h)


def make_plan(root, count, seed, only):
    targets = [(p, w) for p, w in TARGETS if os.path.isfile(os.path.join(root, p)) and w > 0]
    if only:
        targets = [(p, w) for p, w in targets if any(fnmatch.fnmatch(p, o) or p.endswith(o) for o in only)] or \
            [(o, 1) for o in only if os.path.isfile(os.path.join(root, o))]
    total_w = float(sum(w for _, w in targets)) or 1.0
    plan = []
    for path, w in targets:
        with open(os.path.join(root, path), encoding="utf-8") as f:
            text = f.read()
        cands = [m for m in sites_for(path, text)]
        rnd = random.Random(int(hashlib.md5(("%s|%s" % (seed, path)).encode()).hexdigest()[:12], 16))
        quota = max(1, int(round(count * w / total_w))) if not only else count
        chosen, per_line = [], {}
        pool = list(cands)
        rnd.shuffle(pool)
        # weighted order: repeatedly take by kind weight, at most two mutants on one line, and only those that still parse
        while pool and len(chosen) < quota:
            weights = [KIND_WEIGHT.get(m["kind"], 1) for m in pool]
            i = rnd.choices(range(len(pool)), weights=weights)[0]
            m = pool.pop(i)
            if per_line.get(m["line"], 0) >= 2:
                continue
            if not valid(path, text[:m["start"]] + m["new"] + text[m["end"]:]):
                continue
            per_line[m["line"]] = per_line.get(m["line"], 0) + 1
            m = dict(m, file=path)
            m["id"] = mutant_id(path, m)
            chosen.append(m)
        chosen.sort(key=lambda m: m["start"])
        plan.extend(chosen)
    return plan


# ---------------------------------------------------------------- which tests cover a product file

def test_files(root):
    found = []
    for p in sorted(glob.glob(os.path.join(root, "tests", "**", "test_*.py"), recursive=True)):
        rel = os.path.relpath(p, root)
        if rel.split(os.sep)[1] == "e2e":
            continue
        found.append(rel)
    return found


def read(root, rel):
    try:
        with open(os.path.join(root, rel), encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return ""


IMPORT = re.compile(r"^\s*(?:from|import)\s+([A-Za-z_]\w*)", re.M)


def text_with_helpers(root, rel, cache):
    """The text of a test file and of the helper modules it imports (tests/support/*.py, or another tests/ file), transitively: the shared
    fakes live in tests/support, so a product file is often named there and not in the test file that uses it."""
    if rel in cache:
        return cache[rel]
    cache[rel] = ""   # a cycle ends here
    text = read(root, rel)
    parts = [text]
    for mod in sorted(set(IMPORT.findall(text))):
        if mod == "helpers":   # every test imports it, and it names the host script: following it would select every file
            continue
        for folder in ("tests/support", "tests/fast", "tests/slow"):
            cand = "%s/%s.py" % (folder, mod)
            if cand != rel and os.path.isfile(os.path.join(root, cand)):
                parts.append(text_with_helpers(root, cand, cache))
                break
    cache[rel] = "\n".join(parts)
    return cache[rel]


def covering_tests(root, product, durations=None, override=None):
    all_tests = test_files(root)
    if override:
        names = set(override)
        return [t for t in all_tests if os.path.basename(t) in names]
    cache = {}
    base = os.path.basename(product)
    stem = os.path.splitext(base)[0]
    pkg = None
    parts = product.split("/")
    if "lib" in parts and product.endswith(".py"):
        pkg = parts[parts.index("lib") + 1]
    pat_name = re.compile(r"(?<![\w-])%s(?![\w-])" % re.escape(base))
    pat_mod = re.compile(r"\b%s\b" % re.escape(stem))
    hits = []
    for t in all_tests:
        text = text_with_helpers(root, t, cache)
        if pat_name.search(text) or (pkg and pkg in text and pat_mod.search(text) and not stem in ("config", "cli")) \
                or (pkg and stem in ("config", "cli") and re.search(r"(from|import) %s\.?\s*(import )?[\w, ]*\b%s\b" % (pkg, stem), text)):
            hits.append(t)
    if not hits:
        hits = [t for t in all_tests if not any(h in os.path.basename(t) for h in SLOW_HINT)][:FALLBACK_CAP]
    d = durations or {}
    hits.sort(key=lambda t: (d.get(os.path.basename(t), 1e9) if d else os.path.getsize(os.path.join(root, t)), t))
    return hits


# ---------------------------------------------------------------- running

def reap_slot(tmpdir):
    """Kill the processes whose environment says TMPDIR=<tmpdir> (what the tests of one mutant left behind). Linux only."""
    needle = ("TMPDIR=%s" % tmpdir).encode()
    me = os.getpid()
    for name in os.listdir("/proc") if os.path.isdir("/proc") else []:
        if not name.isdigit() or int(name) == me:
            continue
        try:
            with open("/proc/%s/environ" % name, "rb") as f:
                env = f.read().split(b"\0")
        except OSError:
            continue
        if needle in env:
            try:
                os.kill(int(name), signal.SIGKILL)
            except OSError:
                pass


def run_test_file(slot, rel, timeout, extra_env):
    repo, tmp = slot["repo"], slot["tmp"]
    reap = None
    for cand in ("tests/support/reap_run.py", "tests/reap_run.py"):
        if os.path.isfile(os.path.join(repo, cand)):
            reap = os.path.join(repo, cand)
            break
    cmd = [sys.executable] + ([reap, sys.executable] if reap else []) + [os.path.join(repo, rel)]
    env = dict(os.environ, TMPDIR=tmp, HOME=slot["home"], PYTHONDONTWRITEBYTECODE="1", LANG=os.environ.get("LANG", "C.UTF-8"))
    env.update(extra_env)
    t0 = time.time()
    p = subprocess.Popen(cmd, cwd=repo, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True)
    try:
        out, _ = p.communicate(timeout=timeout)
        status = "pass" if p.returncode == 0 else "fail"
    except subprocess.TimeoutExpired:
        try:
            os.killpg(p.pid, signal.SIGKILL)
        except OSError:
            pass
        out, _ = p.communicate()
        status = "timeout"
    text = (out or b"").decode("utf-8", "replace")
    ran = re.findall(r"^Ran (\d+) tests? in", text, re.M)
    skipped = re.findall(r"skipped=(\d+)", text)
    return {"file": rel, "status": status, "secs": round(time.time() - t0, 1), "ran": int(ran[-1]) if ran else 0,
            "skipped": int(skipped[-1]) if skipped else 0, "tail": text[-400:] if status != "pass" else ""}


def run_mutant(slot, m, tests, args, extra_env):
    path = os.path.join(slot["repo"], m["file"])
    with open(path, encoding="utf-8") as f:
        orig = f.read()
    res = {"id": m["id"], "file": m["file"], "line": m["line"], "kind": m["kind"], "desc": m["desc"], "tests": [], "killed_by": []}
    if m["kind"] != "control" and orig[m["start"]:m["end"]] != m["old"]:
        i = orig.find(m["old"])
        if i < 0 or orig.count(m["old"]) != 1:
            # a comment above changed the offsets: the same text on the same line is still the mutant
            lines = orig.split("\n")
            ls = sum(len(x) + 1 for x in lines[:m["line"] - 1])
            le = ls + len(lines[m["line"] - 1]) if 0 < m["line"] <= len(lines) else ls
            i = orig.find(m["old"], ls)
            if i < 0 or i >= le or orig.count(m["old"], ls, le + len(m["old"])) != 1:
                res["status"] = "stale"
                return res
        m = dict(m, start=i, end=i + len(m["old"]))
    if not tests:
        res["status"] = "no-tests"
        return res
    t0 = time.time()
    deadline = t0 + args.timeout
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(orig[:m["start"]] + m["new"] + orig[m["end"]:])
        timed_out = False
        for rel in tests:
            left = deadline - time.time()
            if left <= 1:
                timed_out = True
                break
            r = run_test_file(slot, rel, min(left, args.file_timeout), extra_env)
            if r["status"] == "fail" and args.confirm:
                # a test that fails under load and passes again is a flaky test, not a kill
                r2 = run_test_file(slot, rel, min(max(left, 30), args.file_timeout), extra_env)
                if r2["status"] == "pass":
                    r2["flaky"] = True
                    r = r2
            res["tests"].append(r)
            if r["status"] != "pass":
                res["killed_by"].append(rel)
                if not args.all_tests:
                    break
    finally:
        with open(path, "w", encoding="utf-8") as f:
            f.write(orig)
        reap_slot(slot["tmp"])
    fails = [r for r in res["tests"] if r["status"] == "fail"]
    if fails:
        res["status"] = "killed"
    elif res["killed_by"]:
        res["status"] = "timeout"
    elif timed_out:
        res["status"] = "incomplete"   # the time of the mutant ran out before every file ran: not judged
    else:
        res["status"] = "survived"
    res["secs"] = round(time.time() - t0, 1)
    for r in res["tests"]:
        r.pop("tail", None) if r["status"] == "pass" else None
    return res


def make_slots(root, n, work):
    slots = queue.Queue()
    ignore = shutil.ignore_patterns(".work", ".claude", "__pycache__", "node_modules", "*.pyc")
    for i in range(n):
        base = os.path.join(work, "slot%d" % i)
        repo = os.path.join(base, "repo")
        shutil.copytree(root, repo, ignore=ignore, symlinks=True)
        os.makedirs(os.path.join(base, "tmp"), exist_ok=True)
        os.makedirs(os.path.join(base, "home"), exist_ok=True)
        slots.put({"repo": repo, "tmp": os.path.join(base, "tmp"), "home": os.path.join(base, "home")})
    return slots


def cmd_plan(args):
    plan = make_plan(args.root, args.count, args.seed, args.file)
    if args.out:
        with open(args.out, "w") as f:
            json.dump({"seed": args.seed, "count": args.count, "mutants": plan}, f, indent=1)
    by = {}
    for m in plan:
        by.setdefault(m["file"], []).append(m)
    for p, ms in by.items():
        kinds = {}
        for m in ms:
            kinds[m["kind"]] = kinds.get(m["kind"], 0) + 1
        print("%4d  %-62s %s" % (len(ms), p, " ".join("%s=%d" % kv for kv in sorted(kinds.items()))))
    print("%4d  mutants in %d files (seed %s)" % (len(plan), len(by), args.seed))
    if args.verbose:
        for m in plan:
            print("%s  %s:%d  %s" % (m["id"], m["file"], m["line"], m["desc"]))
    return 0


def load_plan(args):
    if args.plan and os.path.exists(args.plan):
        with open(args.plan) as f:
            return json.load(f)["mutants"]
    plan = make_plan(args.root, args.count, args.seed, args.file)
    if args.plan:
        with open(args.plan, "w") as f:
            json.dump({"seed": args.seed, "count": args.count, "mutants": plan}, f, indent=1)
    return plan


def load_results(path):
    done = {}
    if path and os.path.exists(path):
        with open(path) as f:
            for line in f:
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                done[r["id"]] = r
    return done


def cmd_run(args):
    plan = load_plan(args)
    if args.limit:
        plan = plan[:args.limit]
    done = load_results(args.results)
    if args.control:
        plan = [{"id": "control:" + f, "file": f, "line": 0, "kind": "control", "desc": "no mutation", "start": 0, "end": 0, "old": "", "new": ""}
                for f in sorted(set(m["file"] for m in plan))] + plan
    if args.shard:
        k, n = (int(x) for x in args.shard.split("/"))
        plan = [m for i, m in enumerate(plan) if i % n == k]
    todo = [m for m in plan if m["id"] not in done]
    durations = None
    if args.durations:
        with open(args.durations) as f:
            durations = {os.path.basename(k): (v["wall"] if isinstance(v, dict) else v) for k, v in json.load(f).items()}
    override = [t.strip() for t in args.tests.split(",")] if args.tests else None
    mapping = {}
    for m in plan:
        if m["file"] not in mapping:
            mapping[m["file"]] = [t for t in covering_tests(args.root, m["file"], durations, override)
                                  if args.layer == "all" or t.split("/")[1] == args.layer]
    extra_env = dict(kv.split("=", 1) for kv in args.env)
    print("%d mutants planned, %d already done, %d to run, %d jobs" % (len(plan), len(done), len(todo), args.jobs), flush=True)
    if not todo:
        return 0
    if args.results:
        try:
            open(args.results, "a").close()   # fail now, not after the first mutant has run
        except OSError as e:
            print("mutate: cannot write the results file %s: %s" % (args.results, e), file=sys.stderr)
            return 2
    work = tempfile.mkdtemp(prefix="swarmbox-mutate.")
    lock = threading.Lock()
    counter = [0]
    try:
        slots = make_slots(args.root, min(args.jobs, len(todo)), work)

        def one(m):
            slot = slots.get()
            try:
                r = run_mutant(slot, m, mapping[m["file"]], args, extra_env)
            finally:
                slots.put(slot)
            with lock:
                counter[0] += 1
                if args.results:
                    with open(args.results, "a") as f:
                        f.write(json.dumps(r) + "\n")
                print("[%d/%d] %-9s %s  %s  (%s s)" % (counter[0], len(todo), r["status"], r["id"], r["desc"], r.get("secs", "-")), flush=True)
            return r

        # slow files first keeps the pool busy to the end
        todo.sort(key=lambda m: -len(mapping[m["file"]]))
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as ex:
            list(ex.map(one, todo))
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return 0


def cmd_report(args):
    with open(args.plan) as f:
        plan = json.load(f)["mutants"]
    done = load_results(args.results)
    rows = [done[m["id"]] for m in plan if m["id"] in done]
    controls = [r for k, r in done.items() if k.startswith("control:")]
    lines = []
    count = {}
    for r in rows:
        count[r["status"]] = count.get(r["status"], 0) + 1
    killed = count.get("killed", 0) + count.get("timeout", 0)
    judged = killed + count.get("survived", 0)
    lines.append("mutants run: %d of %d planned" % (len(rows), len(plan)))
    lines.append("by status: " + ", ".join("%s %d" % kv for kv in sorted(count.items())))
    if judged:
        lines.append("kill rate: %d of %d judged = %.0f %%" % (killed, judged, 100.0 * killed / judged))
    per = {}
    for r in rows:
        d = per.setdefault(r["file"], {"killed": 0, "survived": 0, "other": 0})
        k = "killed" if r["status"] in ("killed", "timeout") else "survived" if r["status"] == "survived" else "other"
        d[k] += 1
    if controls:
        bad = [c for c in controls if c["status"] != "survived"]
        lines.append("controls (no mutation): %d run, %d failed%s" % (len(controls), len(bad), "".join("\n  FLAKY %s: %s" % (c["file"], ", ".join(c["killed_by"])) for c in bad)))
    lines.append("")
    lines.append("per product file (killed / survived / other):")
    for p, d in sorted(per.items()):
        lines.append("  %-62s %3d / %3d / %d" % (p, d["killed"], d["survived"], d["other"]))
    lines.append("")
    lines.append("survivors (no test noticed the change):")
    for r in rows:
        if r["status"] == "survived":
            ran = sum(t["ran"] for t in r["tests"])
            skipped = sum(t["skipped"] for t in r["tests"])
            lines.append("  %s:%d  [%s] %s   (%d test files, %d tests run, %d skipped)" % (r["file"], r["line"], r["kind"], r["desc"], len(r["tests"]), ran, skipped))
    for r in rows:
        if r["status"] in ("no-tests", "stale"):
            lines.append("  %s:%d  [%s] %s  -> %s" % (r["file"], r["line"], r["kind"], r["desc"], r["status"]))
    text = "\n".join(lines)
    print(text)
    if args.matrix:
        matrix = {r["id"]: {"file": r["file"], "line": r["line"], "kind": r["kind"], "desc": r["desc"], "status": r["status"],
                            "killed_by": [os.path.basename(x) for x in r["killed_by"]], "ran": [os.path.basename(t["file"]) for t in r["tests"]]}
                  for r in rows}
        with open(args.matrix, "w") as f:
            json.dump(matrix, f, indent=1)
    if args.md:
        with open(args.md, "w") as f:
            f.write(text + "\n")
    return 0


def cmd_tests(args):
    for p in args.files:
        print("%s:" % p)
        for t in covering_tests(args.root, p):
            print("  " + t)
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0], formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__.split("\n\n", 1)[1])
    ap.add_argument("--root", default=ROOT, help="the repository to mutate (default: this one)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def plan_opts(p):
        p.add_argument("--count", type=int, default=250, help="about this many mutants in all (default 250)")
        p.add_argument("--seed", default="1", help="seed of the random choice (default: 1)")
        p.add_argument("--file", action="append", default=[], help="only this product file (repeatable; a path, a suffix or a glob)")

    p = sub.add_parser("plan", help="choose the mutants")
    plan_opts(p)
    p.add_argument("--out", help="write the plan here")
    p.add_argument("-v", "--verbose", action="store_true", help="list every mutant")
    p.set_defaults(fn=cmd_plan)
    p = sub.add_parser("run", help="run the mutants")
    plan_opts(p)
    p.add_argument("--plan", help="the plan file: read when it exists, written when it does not")
    p.add_argument("--results", default="mutate-results.jsonl", help="one JSON line per finished mutant (also the resume file)")
    p.add_argument("-j", "--jobs", type=int, default=max(1, (os.cpu_count() or 2) // 2), help="mutants in parallel (default: half the CPUs)")
    p.add_argument("--timeout", type=int, default=600, help="seconds for all test files of one mutant (default 600)")
    p.add_argument("--file-timeout", type=int, default=240, help="seconds for one test file (default 240)")
    p.add_argument("--all-tests", action="store_true", help="run every selected test file even after a kill (the kill matrix needs it)")
    p.add_argument("--tests", help="comma-separated test file names that replace the automatic choice")
    p.add_argument("--layer", choices=("all", "fast", "slow"), default="all",
                   help="only the test files of this folder (fast first is cheap: run the survivors again with slow to see which mutants only slow tests kill)")
    p.add_argument("--durations", help="a JSON of seconds per test file (a baseline): the fastest files run first")
    p.add_argument("--limit", type=int, help="run only the first K mutants of the plan")
    p.add_argument("--shard", metavar="K/N", help="run only every N-th mutant, starting with the K-th (0 based): to split a plan over several containers; give each its own --results")
    p.add_argument("--confirm", action="store_true", help="run a failing test file once more on the same mutant; a file that then passes is flaky, not a kill")
    p.add_argument("--control", action="store_true", help="also run each product file's tests with NO mutation: a control that is 'killed' names a flaky test")
    p.add_argument("--env", action="append", default=[], metavar="K=V", help="an environment variable for the tests (repeatable)")
    p.set_defaults(fn=cmd_run)
    p = sub.add_parser("report", help="summary, survivors, kill matrix")
    p.add_argument("--plan", required=True)
    p.add_argument("--results", required=True)
    p.add_argument("--matrix", help="write {mutant: {killed_by: [...]}} here")
    p.add_argument("--md", help="write the text summary here")
    p.set_defaults(fn=cmd_report)
    p = sub.add_parser("tests", help="the test files that cover a product file")
    p.add_argument("files", nargs="+")
    p.set_defaults(fn=cmd_tests)
    args = ap.parse_args(argv)
    args.root = os.path.abspath(args.root)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
