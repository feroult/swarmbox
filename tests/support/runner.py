#!/usr/bin/env python3
"""The test runner behind tests/run.sh (standard library only; Python 3.6 or newer, so the macOS job can use it).

    sh tests/run.sh [fast|slow|all|e2e|macos] [-j N] [--only a.py,b.py] [--list] [--repeat N] [--werror] [options]

Selectors (a folder each, see tests/README.md):
    fast    tests/fast/test_*.py   no real tmux, browser, podman or network; run in parallel; the default
    slow    tests/slow/test_*.py   real tmux, pty, ttyd, Chromium, Podman, the image; they skip with a message when a program they need is missing
    all     fast, then slow
    e2e     tests/e2e/*.py         the harnesses with the real claude and the long soak: manual, never part of all
    macos   the fast files named in tests/support/macos.list (the macOS job: /bin/sh is bash 3.2, podman is a fake)
Options:
    -j N          files in parallel (default: fast and macos the CPUs up to 8, slow 3, e2e 1)
    --only LIST   comma-separated file names (a.py,b.py); they are searched in the folders of the selector (every folder when no
                  selector is given); a name that does not exist is an error
    --list        print the selected files and stop
    --repeat N    run each selected file N times
    --werror      run each file as `python3 -W error`
    --timeout S   seconds one file may run (default: fast 300, slow 900, e2e none); a file over it is killed and reported as FAIL
    --timing N    print the N slowest files at the end (default 10)
    --durations N pass `--durations N` to every file (per-test seconds; Python 3.12 or newer)
    --github      for a failed file also print a GitHub `::error` annotation (CI)
Output: one line per finished file "<file> OK|FAIL <n> tests, <k> skipped, <s> s[, reaped <r>]", the tail of every failed file,
then "TOTAL <f> files, <n> tests, <x> failed files, <s> s (wall <w> s)" and the slowest files. Every file runs under
tests/support/reap_run.py: when it ends, the processes it left behind are killed by PID and counted as `reaped`.
Exit status: 0 when every run passed, 1 when one failed, 2 on a usage error. Env: SWARMBOX_TESTS_DIR points at another tests folder
(the tests of this runner use it).
"""
import os
import re
import subprocess
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
TESTS = os.environ.get("SWARMBOX_TESTS_DIR") or os.path.dirname(HERE)
REAP = os.path.join(HERE, "reap_run.py")
LAYERS = ("fast", "slow", "e2e")
SELECTORS = ("fast", "slow", "all", "e2e", "macos")


def usage(msg):
    sys.stderr.write("run: %s\n" % msg)
    sys.exit(2)


def parse(argv):
    o = {"sel": None, "j": None, "only": None, "list": False, "repeat": 1, "werror": False, "timeout": None, "timing": 10,
         "durations": None, "github": False}
    i = 0

    def val():
        nonlocal i
        if i + 1 >= len(argv):
            usage("%s needs a value" % argv[i])
        i += 1
        return argv[i]

    def num(name, s, minimum=1):
        if not re.match(r"^[0-9]+$", s) or int(s) < minimum:
            usage("%s needs a positive number" % name)
        return int(s)

    while i < len(argv):
        a = argv[i]
        if a in SELECTORS and o["sel"] is None:
            o["sel"] = a
        elif a == "-j":
            o["j"] = num("-j", val())
        elif a.startswith("-j") and a[2:].isdigit():
            o["j"] = num("-j", a[2:])
        elif a == "--only":
            o["only"] = [x for x in val().split(",") if x]
        elif a == "--list":
            o["list"] = True
        elif a == "--repeat":
            o["repeat"] = num("--repeat", val())
        elif a == "--werror":
            o["werror"] = True
        elif a == "--timeout":
            o["timeout"] = num("--timeout", val())
        elif a == "--timing":
            o["timing"] = num("--timing", val(), 0)
        elif a == "--durations":
            o["durations"] = num("--durations", val(), 0)
        elif a == "--github":
            o["github"] = True
        elif a in ("-h", "--help"):
            sys.stdout.write(__doc__)
            sys.exit(0)
        else:
            usage("unknown option %s" % a)
        i += 1
    return o


def folder_files(layer):
    d = os.path.join(TESTS, layer)
    if not os.path.isdir(d):
        return []
    if layer == "e2e":
        return sorted(os.path.join(layer, f) for f in os.listdir(d) if f.endswith(".py") and not f.startswith("_"))
    return sorted(os.path.join(layer, f) for f in os.listdir(d) if re.match(r"test_.*\.py$", f))


def macos_names():
    p = os.path.join(TESTS, "support", "macos.list")
    names = []
    with open(p) as f:
        for line in f:
            line = line.split("#", 1)[0].strip()
            if line:
                names.append(line)
    return names


def select(o):
    sel = o["sel"]
    if o["only"]:
        layers = LAYERS if sel is None else {"all": ("fast", "slow"), "macos": ("fast",)}.get(sel, (sel,))
        pool = [f for layer in layers for f in folder_files(layer)]
        chosen = []
        for name in o["only"]:
            hit = [f for f in pool if os.path.basename(f) == os.path.basename(name)]
            if not hit:
                usage("no such test file: %s" % name)
            chosen.append(hit[0])
        return chosen
    sel = sel or "fast"
    if sel == "all":
        return folder_files("fast") + folder_files("slow")
    if sel == "macos":
        fast = dict((os.path.basename(f), f) for f in folder_files("fast"))
        out = []
        for n in macos_names():
            if n not in fast:
                usage("tests/support/macos.list names %s, which is not in tests/fast" % n)
            out.append(fast[n])
        return out
    return folder_files(sel)


def run_one(rel, o, timeout):
    cmd = [sys.executable, REAP, sys.executable]
    if o["werror"]:
        cmd += ["-W", "error"]
    cmd.append(os.path.join(TESTS, rel))
    if o["durations"] is not None:
        cmd += ["--durations", str(o["durations"])]
    t0 = time.time()
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True,
                         cwd=os.path.dirname(TESTS))
    timed_out = False
    try:
        out = p.communicate(timeout=timeout)[0]
    except subprocess.TimeoutExpired:
        timed_out = True
        try:
            os.killpg(p.pid, 9)
        except OSError:
            pass
        out = p.communicate()[0]
    text = out.decode("utf-8", "replace")
    n = re.findall(r"^Ran (\d+) tests? in ", text, re.M)
    k = re.findall(r"^(?:OK|FAILED).*skipped=(\d+)", text, re.M)
    secs = re.findall(r"^reap_run: seconds ([0-9.]+)$", text, re.M)
    reaped = re.findall(r"^reap_run: reaped (\d+)$", text, re.M)
    return {"file": rel, "rc": 1 if timed_out else p.returncode, "timeout": timed_out, "ran": int(n[-1]) if n else 0,
            "skipped": int(k[-1]) if k else 0, "secs": float(secs[-1]) if secs else round(time.time() - t0, 1),
            "reaped": int(reaped[-1]) if reaped else 0, "text": text}


def main(argv):
    o = parse(argv)
    files = select(o)
    if o["list"]:
        for f in files:
            sys.stdout.write("%s\n" % f)
        return 0
    sel = o["sel"] or ("all" if o["only"] else "fast")
    cpus = os.cpu_count() or 2
    default_j = {"fast": min(cpus, 8), "macos": min(cpus, 8), "slow": min(cpus, 3), "all": min(cpus, 8), "e2e": 1}[sel]
    jobs = o["j"] or default_j
    if o["timeout"]:
        timeouts = dict((k, o["timeout"]) for k in LAYERS)
    else:
        timeouts = {"fast": 300, "slow": 900, "e2e": None}
    work = []
    for f in files:
        for _ in range(o["repeat"]):
            work.append(f)
    # the longest files first (by the name of the layer, then the size of the file) keeps the pool busy to the end
    work.sort(key=lambda f: -os.path.getsize(os.path.join(TESTS, f)))
    results = []
    lock = threading.Lock()
    todo = list(work)
    wall0 = time.time()

    def worker():
        while True:
            with lock:
                if not todo:
                    return
                rel = todo.pop(0)
            r = run_one(rel, o, timeouts.get(rel.split("/")[0]))
            with lock:
                results.append(r)
                name = os.path.basename(rel)
                extra = ", reaped %d" % r["reaped"] if r["reaped"] else ""
                sys.stdout.write("%s %s %d tests, %d skipped, %.1f s%s\n" % (name, "OK" if r["rc"] == 0 else "FAIL", r["ran"], r["skipped"], r["secs"], extra))
                if r["rc"] != 0:
                    lines = r["text"].splitlines()
                    if r["timeout"]:
                        lines.append("run: the file was killed after its time limit")
                    for ln in lines[-15:]:
                        sys.stdout.write("    | %s\n" % ln)
                    if o["github"]:
                        msg = "%0A".join(x.replace("%", "%25").replace("\r", "%0D") for x in r["text"].splitlines()[-40:])
                        sys.stdout.write("::error title=%s failed::%s\n" % (name, msg[-6000:]))
                sys.stdout.flush()

    threads = [threading.Thread(target=worker) for _ in range(max(1, min(jobs, len(work) or 1)))]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    bad = [r for r in results if r["rc"] != 0]
    total_s = sum(r["secs"] for r in results)
    if o["repeat"] > 1:
        sys.stdout.write("TOTAL %d runs\n" % len(results))
    sys.stdout.write("TOTAL %d files, %d tests, %d failed files, %.1f s (wall %.1f s, -j %d)\n" % (
        len(files), sum(r["ran"] for r in results), len(bad), total_s, time.time() - wall0, jobs))
    skipped = sum(r["skipped"] for r in results if r["file"].startswith("slow/"))
    if skipped and not os.environ.get("SWARMBOX_TEST_REAL_TMUX"):
        sys.stdout.write("note: %d slow tests were skipped here (a program they need is missing, or SWARMBOX_TEST_REAL_TMUX=1 is not set): "
                         "sh dev/test-slow.sh runs them in Podman, where the programs are\n" % skipped)
    if o["timing"] and results:
        sys.stdout.write("slowest files:\n")
        for r in sorted(results, key=lambda r: -r["secs"])[:o["timing"]]:
            sys.stdout.write("  %6.1f s  %s\n" % (r["secs"], r["file"]))
    if o["durations"] is not None:
        for r in results:
            m = re.search(r"Slowest test durations\n-+\n(.*?)\n\n", r["text"], re.S)
            if m:
                sys.stdout.write("\n%s\n%s\n" % (r["file"], m.group(1)))
    sys.stdout.flush()
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
