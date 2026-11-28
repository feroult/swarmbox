#!/usr/bin/env python3
"""The test runner behind tests/run.sh (standard library only; Python 3.6 or newer, so the macOS job can use it).

    sh tests/run.sh [fast|commit|loop|slow|smoke|all|e2e|macos] [-j N] [--area NAME] [--only a.py,b.py] [--fail-fast] [options]

Selectors (see tests/README.md):
    fast    tests/fast/test_*.py   no real multiplexer, browser, podman or network; run in parallel; the default
    commit  alias for fast (the full local suite)
    loop    tests mapped from git changes + static guards; implies --fail-fast unless --no-fail-fast is given
    slow    tests/slow/test_*.py   pty, Chromium, Podman, the image; they skip with a message when a program they need is missing
    smoke   alias for slow
    all     fast, then slow
    e2e     tests/e2e/*.sh         the wrappers that start Podman and run the harnesses with the real claude and the long soak: manual, never part of all
    macos   the fast files named in tests/support/macos.list (the macOS job: /bin/sh is bash 3.2, podman is a fake)
Options:
    -j N          files in parallel (default: fast, loop and macos the CPUs up to 16, slow 3, e2e 1)
    --area NAME   run tests for named area(s) + guards (repeatable or comma-separated)
    --since REF   (with loop) diff changed files against git REF instead of working tree only (alias: --ref REF)
    --fail-fast   stop scheduling new jobs and terminate running jobs on the first failing file
    --no-fail-fast disable --fail-fast (e.g. to override loop's default)
    --only LIST   comma-separated file names (a.py,b.py); they are searched in the folders of the selector (every folder when no
                  selector is given); a name that does not exist is an error
    --list        print the selected files and stop
    --repeat N    run each selected file N times
    --werror      run each file as `python3 -W error`
    --timeout S   seconds one file may run (default: fast 300, slow 900, e2e none); a file over it is killed and reported as FAIL
    --timing N    print the N slowest files at the end (default 10)
    --durations N pass `--durations N` to every file (per-test seconds; Python 3.12 or newer)
    --shuffle [N] run the files in a random order (the seed is printed; N repeats an order)
    --github      for a failed file also print a GitHub `::error` annotation (CI)
Output: one line per finished file "<file> OK|FAIL <n> tests, <k> skipped, <s> s[, reaped <r>]", the tail of every failed file,
then "TOTAL <f> files, <n> tests, <x> failed files, <s> s (wall <w> s)" and the slowest files. Every file runs under a child
subreaper (in-process forked child on Linux, tests/support/reap_run.py otherwise): when it ends, the processes it left behind are
killed by PID and counted as `reaped`.
Exit status: 0 when every run passed, 1 when one failed, 2 on a usage error. Env: SWARMBOX_TESTS_DIR points at another tests folder
(the tests of this runner use it); SWARMBOX_TEST_TIMINGS is the timing cache that plans the units, longest first (default
$XDG_CACHE_HOME/swarmbox-tests/timings.json, empty: off).
"""
import ast
import atexit
import json
import math
import os
import random
import re
import runpy
import selectors
import signal
import subprocess
import sys
import time
import traceback
import warnings

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import areas  # noqa: E402
import reap_run  # noqa: E402

TESTS = os.environ.get("SWARMBOX_TESTS_DIR") or os.path.dirname(HERE)
REAP = os.path.join(HERE, "reap_run.py")
LAYERS = ("fast", "slow", "e2e")
SELECTORS = ("fast", "commit", "loop", "slow", "smoke", "all", "e2e", "macos")
SELECTOR_ALIASES = {"commit": "fast", "smoke": "slow"}
USE_FORK = (
    sys.platform.startswith("linux")
    and hasattr(os, "fork")
    and not os.environ.get("SWARMBOX_RUNNER_SUBPROCESS")
)


def usage(msg):
    sys.stderr.write("run: %s\n" % msg)
    sys.exit(2)


def parse(argv):
    o = {"sel": None, "j": None, "only": None, "area": [], "since": None, "fail_fast": None, "list": False, "repeat": 1,
         "werror": False, "timeout": None, "timing": 10, "durations": None, "github": False, "_note": None}
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

    def pos_float(name, s):
        if not re.match(r"^[0-9]+(?:\.[0-9]+)?$", s) or float(s) <= 0:
            usage("%s needs a positive number" % name)
        return float(s)

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
        elif a == "--area":
            parts = [x.strip() for x in val().split(",") if x.strip()]
            if not parts:
                usage("--area needs a value")
            o["area"].extend(parts)
        elif a in ("--since", "--ref"):
            o["since"] = val()
        elif a == "--fail-fast":
            o["fail_fast"] = True
        elif a == "--no-fail-fast":
            o["fail_fast"] = False
        elif a == "--list":
            o["list"] = True
        elif a == "--repeat":
            o["repeat"] = num("--repeat", val())
        elif a == "--werror":
            o["werror"] = True
        elif a == "--timeout":
            o["timeout"] = pos_float("--timeout", val())
        elif a == "--timing":
            o["timing"] = num("--timing", val(), 0)
        elif a == "--durations":
            o["durations"] = num("--durations", val(), 0)
        elif a == "--github":
            o["github"] = True
        elif a == "--shuffle":
            # --shuffle or --shuffle SEED (a number): the files in a random order, to find a file that needs another to run first
            o["shuffle"] = int(argv[i + 1]) if i + 1 < len(argv) and argv[i + 1].isdigit() else -1
            if o["shuffle"] >= 0:
                i += 1
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
        return sorted(os.path.join(layer, f) for f in os.listdir(d) if f.endswith(".sh"))
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
    sel = SELECTOR_ALIASES.get(o["sel"], o["sel"])
    if o["only"]:
        layers = LAYERS if sel is None else {"all": ("fast", "slow"), "macos": ("fast",), "loop": ("fast",)}.get(sel, (sel,))
        pool = [f for layer in layers for f in folder_files(layer)]
        chosen = []
        for name in o["only"]:
            hit = [f for f in pool if os.path.basename(f) == os.path.basename(name)]
            if not hit:
                usage("no such test file: %s" % name)
            chosen.append(hit[0])
        return chosen
    if o["area"]:
        chosen, unknown = areas.tests_for_areas(o["area"], folder_files("fast"))
        if unknown:
            usage("unknown area %s (available: %s)" % (", ".join(unknown), ", ".join(sorted(areas.AREAS))))
        return chosen
    sel = sel or "fast"
    if sel == "loop":
        fast_files = folder_files("fast")
        repo_root = os.path.dirname(os.path.abspath(TESTS))
        changed, err = areas.git_changed_files(repo_root, since=o["since"])
        if err is not None:
            if o["since"] is not None:
                usage("git diff --since %s failed: %s" % (o["since"], err))
            o["_note"] = "loop: git status unavailable (%s), running full fast suite" % err
            return fast_files
        chosen, note, _ = areas.resolve_changed(changed, fast_files)
        o["_note"] = note
        return chosen
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


def _is_unittest_main_call(stmt):
    """True when stmt is a bare `unittest.main(...)` call with no argv/defaultTest override."""
    if not isinstance(stmt, ast.Expr) or not isinstance(stmt.value, ast.Call):
        return False
    call = stmt.value
    fn = call.func
    if not (isinstance(fn, ast.Attribute) and fn.attr == "main" and isinstance(fn.value, ast.Name) and fn.value.id == "unittest"):
        return False
    if call.args:
        return False
    for kw in call.keywords:
        if kw.arg in ("argv", "defaultTest", None):
            return False
    return True


def _is_main_guard(node):
    """True when node is `if __name__ == "__main__":`."""
    if not isinstance(node, ast.If) or not isinstance(node.test, ast.Compare):
        return False
    t = node.test
    if len(t.ops) != 1 or not isinstance(t.ops[0], ast.Eq) or len(t.comparators) != 1:
        return False
    left, right = t.left, t.comparators[0]
    if isinstance(left, ast.Name) and left.id == "__name__" and isinstance(right, ast.Constant) and right.value == "__main__":
        return True
    if isinstance(right, ast.Name) and right.id == "__name__" and isinstance(left, ast.Constant) and left.value == "__main__":
        return True
    return False


def _base_name(expr):
    if isinstance(expr, ast.Name):
        return expr.id
    if isinstance(expr, ast.Attribute):
        return expr.attr
    return ""


def shard_classes(abs_path, max_shards):
    """Inspect a fast test file's AST and return class-name buckets if safe to shard, else None."""
    if max_shards < 2:
        return None
    table = class_table(abs_path)
    if table is None or len(table) < 2:
        return None
    test_classes = [(name, len(methods)) for name, methods in table]
    k = min(len(test_classes), max_shards)
    buckets = [[] for _ in range(k)]
    loads = [0] * k
    for name, count in sorted(test_classes, key=lambda x: -x[1]):
        idx = min(range(k), key=lambda j: loads[j])
        buckets[idx].append(name)
        loads[idx] += count
    return [b for b in buckets if b]


def class_table(abs_path):
    """The test classes of a file as [(class, [own test_ methods])] in file order when the file is safe to run class by class, else None."""
    try:
        with open(abs_path, encoding="utf-8") as f:
            tree = ast.parse(f.read(), abs_path)
    except (OSError, SyntaxError, UnicodeDecodeError):
        return None
    has_main = False
    classes = {}
    class_order = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name in ("setUpModule", "tearDownModule", "load_tests"):
                return None
        elif isinstance(node, ast.ClassDef):
            methods = [m.name for m in node.body if isinstance(m, ast.FunctionDef) and m.name.startswith("test_")]
            bases = [_base_name(b) for b in node.bases]
            classes[node.name] = (methods, bases)
            class_order.append(node.name)
        elif _is_unittest_main_call(node):
            has_main = True
        elif _is_main_guard(node):
            if len(node.body) != 1 or not _is_unittest_main_call(node.body[0]):
                return None
            has_main = True
    if not has_main:
        return None
    used_as_base = set()
    for _, (_, bases) in classes.items():
        for b in bases:
            if b in classes:
                used_as_base.add(b)
    test_classes = []
    for name in class_order:
        methods, bases = classes[name]
        if methods:
            # If a test class is inherited by another class in the same file, skip sharding.
            if name in used_as_base:
                return None
            test_classes.append((name, methods))
        else:
            # A non-base class inheriting from an imported TestCase-like base might inherit test_ methods.
            if name not in used_as_base and any(("Test" in b or "Case" in b) for b in bases if b not in classes):
                return None
    if len(test_classes) < 2 and not (test_classes and len(test_classes[0][1]) >= 2):
        return None
    return test_classes


TIMINGS_LINE = re.compile(r"^reap_run: timings (\{.*\})\n?", re.M)


def _parse_output(rel, rc, timed_out, t0, raw):
    text = raw.decode("utf-8", "replace")
    timings = None
    found = TIMINGS_LINE.findall(text)
    if found:
        text = TIMINGS_LINE.sub("", text)
        try:
            timings = json.loads(found[-1])
        except ValueError:
            timings = None
    n = re.findall(r"^Ran (\d+) tests? in ", text, re.M)
    k = re.findall(r"^(?:OK|FAILED).*skipped=(\d+)", text, re.M)
    secs = re.findall(r"^reap_run: seconds ([0-9.]+)$", text, re.M)
    reaped = re.findall(r"^reap_run: reaped (\d+)$", text, re.M)
    return {
        "file": rel,
        "rc": 1 if timed_out else rc,
        "timeout": timed_out,
        "ran": int(n[-1]) if n else 0,
        "skipped": int(k[-1]) if k else 0,
        "secs": float(secs[-1]) if secs else round(time.monotonic() - t0, 1),
        "reaped": int(reaped[-1]) if reaped else 0,
        "text": text,
        "start": t0,
        "end": time.monotonic(),
        "timings": None if timed_out else timings,
    }


def _install_timing_hooks(started):
    """In the child: measure the import of the file, each class (its setUpClass included) and each test, for the timing cache.

    Returns the record that _exec_in_child prints as one `reap_run: timings {json}` line (the parent removes it from the output)."""
    import unittest
    rec = {"import": None, "classes": {}}
    state = {"prev_end": None, "last": None, "t": 0.0}
    run_tests = unittest.TestProgram.runTests
    start_test = unittest.TestResult.startTest
    stop_test = unittest.TestResult.stopTest

    def runTests(self, *a, **kw):
        now = time.monotonic()
        rec["import"] = round(now - started, 3)
        state["prev_end"] = now
        return run_tests(self, *a, **kw)

    def split(test):
        parts = test.id().split(".")
        if len(parts) == 3 and parts[0] == "__main__":   # a test of the file itself (not one a test runs inside it)
            return parts[1], parts[2]
        return None, None

    def startTest(self, test):
        cls, _ = split(test)
        if cls is not None:
            now = time.monotonic()
            if cls != state["last"]:
                c = rec["classes"].setdefault(cls, {"begin": state["prev_end"] or now, "tests": {}})
                c.setdefault("begin", state["prev_end"] or now)
            state["t"] = now
        return start_test(self, test)

    def stopTest(self, test):
        stop_test(self, test)
        cls, meth = split(test)
        if cls is not None and cls in rec["classes"]:
            now = time.monotonic()
            c = rec["classes"][cls]
            c["tests"][meth] = round(now - state["t"], 3)
            c["end"] = now
            state["prev_end"] = now
            state["last"] = cls

    unittest.TestProgram.runTests = runTests
    unittest.TestResult.startTest = startTest
    unittest.TestResult.stopTest = stopTest

    def finish():
        out = {"import": rec["import"], "classes": {}}
        for cls, c in rec["classes"].items():
            if "end" in c:
                secs = c["end"] - c["begin"]
                out["classes"][cls] = {"setup": round(max(0.0, secs - sum(c["tests"].values())), 3), "tests": c["tests"]}
        return out
    return finish


def _exit_code(status):
    if os.WIFEXITED(status):
        return os.WEXITSTATUS(status)
    if os.WIFSIGNALED(status):
        return 128 + os.WTERMSIG(status)
    return 1


def _exec_in_child(abs_path, classes, o, close_fds, w_fd):
    """Run one Python test file (or class shard) inside a freshly forked subreaper child."""
    for fd in close_fds:
        try:
            os.close(fd)
        except OSError:
            pass
    if o.get("parallel"):
        os.environ["SWARMBOX_RUNNER_PARALLEL"] = "1"
    else:
        os.environ.pop("SWARMBOX_RUNNER_PARALLEL", None)
    try:
        os.setsid()
    except OSError:
        pass
    # stdin is /dev/null: a file that starts a program which reads or configures "its terminal" (a full-screen panel, stty) must never reach the one
    # the developer is typing in. It left that terminal in raw mode once (the lines of the output no longer returned to the first column).
    devnull = os.open(os.devnull, os.O_RDONLY)
    os.dup2(devnull, 0)
    os.close(devnull)
    os.dup2(w_fd, 1)
    os.dup2(w_fd, 2)
    os.close(w_fd)
    sys.stdout = sys.__stdout__
    sys.stderr = sys.__stderr__
    os.chdir(os.path.dirname(TESTS))
    subreaper = reap_run.set_subreaper()
    reap_run.restore_signals()
    if o["werror"]:
        warnings.simplefilter("error")
    argv = [abs_path]
    if o["durations"] is not None:
        argv += ["--durations", str(o["durations"])]
    if classes:
        argv += list(classes)
    sys.argv = argv
    if sys.path:
        sys.path[0] = os.path.dirname(abs_path)
    else:
        sys.path.insert(0, os.path.dirname(abs_path))
    started = time.time()
    finish_timings = None
    try:
        finish_timings = _install_timing_hooks(time.monotonic())
    except Exception:   # the cache is an optimisation: a file must run the same without it
        finish_timings = None
    rc = 0
    try:
        runpy.run_path(abs_path, run_name="__main__")
    except SystemExit as e:
        if e.code is None:
            rc = 0
        elif isinstance(e.code, int):
            rc = e.code
        else:
            sys.stderr.write("%s\n" % (e.code,))
            rc = 1
    except BaseException:
        traceback.print_exc()
        rc = 1
    try:
        atexit._run_exitfuncs()
    except BaseException:
        traceback.print_exc()
        rc = 1
    reaped, left = reap_run.reap_orphans() if subreaper else (0, [])
    if finish_timings is not None:
        try:
            sys.stderr.write("\nreap_run: timings %s\n" % json.dumps(finish_timings(), separators=(",", ":")))
        except Exception:
            pass
    sys.stderr.write("reap_run: seconds %.1f\n" % (time.time() - started))
    if reaped:
        sys.stderr.write("reap_run: reaped %d\n" % reaped)
        sys.stderr.write("reap_run: left behind: %s\n" % " | ".join(left))
    try:
        sys.stdout.flush()
    except OSError:
        pass
    try:
        sys.stderr.flush()
    except OSError:
        pass
    os._exit(rc)


def _start_task(unit, o, timeout, open_fds):
    rel = unit["file"]
    abs_path = os.path.join(TESTS, rel)
    t0 = time.monotonic()
    deadline = (t0 + timeout) if timeout is not None else None
    if USE_FORK and not rel.endswith(".sh"):
        sys.stdout.flush()
        sys.stderr.flush()
        r_fd, w_fd = os.pipe()
        pid = os.fork()
        if pid == 0:
            _exec_in_child(abs_path, unit["classes"], o, list(open_fds) + [r_fd], w_fd)
        os.close(w_fd)
        os.set_blocking(r_fd, False)
        return {"unit": unit, "pid": pid, "popen": None, "r_fd": r_fd, "chunks": [], "t0": t0, "deadline": deadline, "timed_out": False}
    # e2e (.sh) or non-Linux (macOS): run via reap_run.py subprocess
    interpreter = ["bash"] if rel.endswith(".sh") else [sys.executable]
    cmd = [sys.executable, REAP] + interpreter
    if o["werror"] and not rel.endswith(".sh"):
        cmd += ["-W", "error"]
    cmd.append(abs_path)
    if o["durations"] is not None:
        cmd += ["--durations", str(o["durations"])]
    if unit["classes"]:
        cmd += list(unit["classes"])
    env = dict(os.environ)
    if o.get("parallel"):
        env["SWARMBOX_RUNNER_PARALLEL"] = "1"
    else:
        env.pop("SWARMBOX_RUNNER_PARALLEL", None)
    p = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True,
                         cwd=os.path.dirname(TESTS), env=env)
    r_fd = p.stdout.fileno()
    os.set_blocking(r_fd, False)
    return {"unit": unit, "pid": p.pid, "popen": p, "r_fd": r_fd, "chunks": [], "t0": t0, "deadline": deadline, "timed_out": False}


def _finish_task(task):
    if task["popen"] is not None:
        task["popen"].stdout.close()
        rc = task["popen"].wait()
    else:
        os.close(task["r_fd"])
        _, status = os.waitpid(task["pid"], 0)
        rc = _exit_code(status)
    return _parse_output(task["unit"]["file"], rc, task["timed_out"], task["t0"], b"".join(task["chunks"]))


def _aggregate_shards(rel, shards):
    if len(shards) == 1:
        return shards[0]
    bad = [s for s in shards if s["rc"] != 0]
    timed_out = any(s["timeout"] for s in shards)
    rc = bad[0]["rc"] if bad else 0
    wall = round(max(s["end"] for s in shards) - min(s["start"] for s in shards), 1)
    if bad:
        text = "\n".join(s["text"].rstrip("\n") for s in bad)
    else:
        text = "\n".join(s["text"].rstrip("\n") for s in shards)
    return {
        "file": rel,
        "rc": rc,
        "timeout": timed_out,
        "ran": sum(s["ran"] for s in shards),
        "skipped": sum(s["skipped"] for s in shards),
        "secs": wall,
        "reaped": sum(s["reaped"] for s in shards),
        "text": text,
    }


TIMINGS_VERSION = 1
UNIT_FLOOR_S = 0.5      # a unit shorter than this is never split further (each unit pays a fork, an import, a setUpClass)
UNIT_CAP_SHARE = 0.5    # split a file (by class, then a long class by method) into units of at most this share of one job's work


def timings_path():
    """Where the durations of the last runs are kept: $SWARMBOX_TEST_TIMINGS ("" turns it off), else the cache folder of the user.

    Only for the tests folder of this repository: another one (SWARMBOX_TESTS_DIR, the tests of this runner) is never cached."""
    p = os.environ.get("SWARMBOX_TEST_TIMINGS")
    if p is not None:
        return p or None
    if os.path.realpath(TESTS) != os.path.realpath(os.path.dirname(HERE)):
        return None
    base = os.environ.get("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache")
    return os.path.join(base, "swarmbox-tests", "timings.json")


def load_timings(path):
    if not path:
        return {}
    try:
        with open(path) as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict) or data.get("version") != TIMINGS_VERSION or not isinstance(data.get("files"), dict):
        return {}
    return data["files"]


def merge_timings(files, results):
    """Fold the timings of the units of one run into the cache: per file the import, per class its setup and each of its tests.

    The parts of one file (or of one class split by method) are put together first; a class measured in this run replaces its old
    entry, and a file that ran whole replaces the whole entry (a class that is gone leaves the cache)."""
    seen = {}
    for r in results:
        t = r.get("timings")
        if not isinstance(t, dict) or not isinstance(t.get("classes"), dict):
            continue
        obs = seen.setdefault(r["file"], {"import": None, "classes": {}, "whole": False})
        obs["whole"] = obs["whole"] or not r.get("classes")
        imp = t.get("import")
        if isinstance(imp, (int, float)):
            obs["import"] = imp if obs["import"] is None else min(obs["import"], imp)
        for cls, c in t["classes"].items():
            if not isinstance(c, dict):
                continue
            o = obs["classes"].setdefault(cls, {"setup": None, "tests": {}})
            setup = c.get("setup")
            if isinstance(setup, (int, float)):
                # a class split by method pays its setUpClass in every part: the smallest is the one cost of it
                o["setup"] = setup if o["setup"] is None else min(o["setup"], setup)
            o["tests"].update(c.get("tests") or {})
    for rel, obs in seen.items():
        old = files.get(rel)
        entry = {"import": None, "classes": {}}
        if isinstance(old, dict) and isinstance(old.get("classes"), dict) and not obs["whole"]:
            entry = {"import": old.get("import"), "classes": dict(old["classes"])}
        if obs["import"] is not None:
            entry["import"] = obs["import"]
        for cls, o in obs["classes"].items():
            entry["classes"][cls] = {"setup": o["setup"] or 0.0, "tests": o["tests"]}
        files[rel] = entry
    return files


def save_timings(path, results):
    if not path or not any(r.get("timings") for r in results):
        return
    files = merge_timings(load_timings(path), results)
    tmp = "%s.%d.tmp" % (path, os.getpid())
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(tmp, "w") as f:
            json.dump({"version": TIMINGS_VERSION, "files": files}, f, separators=(",", ":"), sort_keys=True)
        os.replace(tmp, path)
    except OSError:   # a read-only home (the container of dev/test-slow.sh): the next run plans by the size of the files
        try:
            os.unlink(tmp)
        except OSError:
            pass


def _class_secs(c):
    return float(c.get("setup") or 0.0) + sum(float(v) for v in (c.get("tests") or {}).values())


def _lpt(items, k):
    """Longest first into k bins: [(load, [names])] for items [(name, secs)]."""
    bins = [[0.0, []] for _ in range(k)]
    for name, secs in sorted(items, key=lambda x: -x[1]):
        b = min(bins, key=lambda x: x[0])
        b[0] += secs
        b[1].append(name)
    return [b for b in bins if b[1]]


def _plan_file(rel, table, hist, est, cap):
    """Split one file into units of about `cap` seconds from its history: [(classes or None, est)]."""
    imp = float(hist.get("import") or 0.05)
    known = dict((c, v) for c, v in (hist.get("classes") or {}).items() if isinstance(v, dict))
    mean = (sum(_class_secs(v) for v in known.values()) / len(known)) if known else 0.1
    pieces = []
    for cls, methods in table:
        h = known.get(cls)
        secs = _class_secs(h) if h else mean
        tests = (h or {}).get("tests") or {}
        # a long class runs as several parts, by method, but only when the history names exactly the methods of the class: a test it
        # inherits from another module, or one added since the last run, would otherwise not run at all
        if h and secs > cap and len(methods) > 1 and set(tests) == set(methods):
            setup = float(h.get("setup") or 0.0)
            k = min(len(methods), int(math.ceil(secs / cap)))
            for load, names in _lpt([(m, float(tests[m])) for m in methods], k):
                pieces.append((["%s.%s" % (cls, m) for m in names], setup + load))
        else:
            pieces.append(([cls], secs))
    k = min(len(pieces), int(math.ceil(est / cap)))
    if k < 2:
        return [(None, est)]
    out = []
    for load, names in _lpt([(i, s) for i, (_, s) in enumerate(pieces)], k):
        out.append(([n for i in sorted(names) for n in pieces[i][0]], imp + load))
    return out


def _plan_units(work, jobs, allow_shard, timings):
    """The units to run, longest first. A file with a history is estimated (and split) by the durations of its classes and tests; a
    file without one by its size (the old rule)."""
    sizes = dict((rel, os.path.getsize(os.path.join(TESTS, rel))) for rel in set(work))
    est = {}
    for rel in sizes:
        h = timings.get(rel)
        if isinstance(h, dict) and isinstance(h.get("classes"), dict) and h["classes"]:
            est[rel] = float(h.get("import") or 0.0) + sum(_class_secs(c) for c in h["classes"].values() if isinstance(c, dict))
    known = [rel for rel in est if sizes[rel] > 0]
    rate = (sum(est[r] for r in known) / sum(sizes[r] for r in known)) if known else 1e-4
    for rel in sizes:
        est.setdefault(rel, sizes[rel] * rate)
    total = sum(est[rel] for rel in work)
    cap = max(UNIT_FLOOR_S, total / max(1, jobs) * UNIT_CAP_SHARE)
    plans = {}
    units = []
    for run_id, rel in enumerate(work):
        if rel not in plans:
            plan = [(None, est[rel])]
            if allow_shard and rel.startswith("fast/") and rel.endswith(".py"):
                h = timings.get(rel)
                if rel in timings and isinstance(h, dict) and isinstance(h.get("classes"), dict):
                    if est[rel] > cap:
                        table = class_table(os.path.join(TESTS, rel))
                        if table:
                            plan = _plan_file(rel, table, h, est[rel], cap)
                else:
                    buckets = _build_units([rel], len(work), jobs, True)
                    if len(buckets) > 1:
                        plan = [(u["classes"], est[rel] / len(buckets)) for u in buckets]
            plans[rel] = plan
        plan = plans[rel]
        for classes, secs in plan:
            units.append({"run_id": run_id, "file": rel, "classes": classes, "shard_count": len(plan), "est": secs})
    units.sort(key=lambda u: -u["est"])
    return units


def _build_units(work, files_count, jobs, allow_shard):
    units = []
    shard_cache = {}
    for run_id, rel in enumerate(work):
        buckets = None
        if allow_shard and rel.startswith("fast/") and rel.endswith(".py"):
            if rel not in shard_cache:
                abs_path = os.path.join(TESTS, rel)
                size = os.path.getsize(abs_path)
                if files_count <= jobs:
                    max_shards = min(12, max(4, jobs // max(1, files_count)))
                elif size >= 24000:
                    max_shards = 8
                elif size >= 8192:
                    max_shards = 4
                else:
                    max_shards = 1
                shard_cache[rel] = shard_classes(abs_path, max_shards)
            buckets = shard_cache[rel]
        if buckets:
            for cls_list in buckets:
                units.append({"run_id": run_id, "file": rel, "classes": cls_list, "shard_count": len(buckets)})
        else:
            units.append({"run_id": run_id, "file": rel, "classes": None, "shard_count": 1})
    return units


def main(argv):
    o = parse(argv)
    files = select(o)
    if o["list"]:
        for f in files:
            sys.stdout.write("%s\n" % f)
        return 0
    if o["_note"]:
        sys.stdout.write("%s\n" % o["_note"])
        sys.stdout.flush()
    eff_sel = SELECTOR_ALIASES.get(o["sel"], o["sel"])
    if eff_sel == "loop":
        eff_sel = "fast"
    sel = eff_sel or ("all" if o["only"] else "fast")
    fail_fast = o["fail_fast"] if o["fail_fast"] is not None else (o["sel"] == "loop")
    cpus = os.cpu_count() or 2
    default_j = {"fast": min(cpus, 16), "macos": min(cpus, 16), "slow": min(cpus, 3), "all": min(cpus, 16), "e2e": 1}[sel]
    jobs = o["j"] or default_j
    o["parallel"] = jobs > 1
    if o["timeout"]:
        timeouts = dict((k, o["timeout"]) for k in LAYERS)
    else:
        timeouts = {"fast": 300, "slow": 900, "e2e": None}
    work = []
    for f in files:
        for _ in range(o["repeat"]):
            work.append(f)
    tpath = timings_path() if USE_FORK else None
    allow_shard = USE_FORK and jobs > 1 and o.get("shuffle") is None
    if o.get("shuffle") is not None:
        work.sort(key=lambda f: -os.path.getsize(os.path.join(TESTS, f)))
        seed = o["shuffle"] if o["shuffle"] >= 0 else random.SystemRandom().randrange(1, 10**6)
        sys.stdout.write("shuffle seed %d (repeat with --shuffle %d)\n" % (seed, seed))
        random.Random(seed).shuffle(work)
        todo = _build_units(work, len(work), jobs, False)
    else:
        # the longest units first (by the durations of the last runs, else by the size of the file) keep the pool busy to the end
        todo = _plan_units(work, jobs, allow_shard, load_timings(tpath))
    results = []
    unit_results = []
    pending_shards = {}
    wall0 = time.time()
    active = {}
    selector = selectors.DefaultSelector()
    aborted = False

    def abort_running():
        nonlocal aborted
        if aborted:
            return
        aborted = True
        todo.clear()
        for r_fd in list(active):
            t = active.pop(r_fd)
            try:
                selector.unregister(r_fd)
            except (KeyError, ValueError):
                pass
            try:
                os.killpg(t["pid"], signal.SIGKILL)
            except OSError:
                pass
            if t["popen"] is not None:
                try:
                    t["popen"].stdout.close()
                except OSError:
                    pass
                try:
                    t["popen"].wait()
                except OSError:
                    pass
            else:
                try:
                    os.close(t["r_fd"])
                except OSError:
                    pass
                try:
                    os.waitpid(t["pid"], 0)
                except ChildProcessError:
                    pass

    def report_file(r):
        results.append(r)
        name = os.path.basename(r["file"])
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

    def on_unit_done(unit, r):
        r["classes"] = unit["classes"]
        unit_results.append(r)
        if unit["shard_count"] == 1:
            report_file(r)
            if fail_fast and r["rc"] != 0:
                abort_running()
            return
        key = unit["run_id"]
        bucket = pending_shards.setdefault(key, [])
        bucket.append(r)
        if fail_fast and r["rc"] != 0:
            del pending_shards[key]
            report_file(_aggregate_shards(unit["file"], bucket))
            abort_running()
            return
        if len(bucket) == unit["shard_count"]:
            del pending_shards[key]
            report_file(_aggregate_shards(unit["file"], bucket))

    try:
        while todo or active:
            while todo and len(active) < jobs and not aborted:
                unit = todo.pop(0)
                t = _start_task(unit, o, timeouts.get(unit["file"].split("/")[0]), active.keys())
                active[t["r_fd"]] = t
                selector.register(t["r_fd"], selectors.EVENT_READ, t)
            if not active:
                break
            now = time.monotonic()
            wait_s = 0.2
            for t in active.values():
                if t["deadline"] is not None:
                    rem = t["deadline"] - now
                    if rem < wait_s:
                        wait_s = max(0.0, rem)
            events = selector.select(timeout=wait_s)
            for key, _ in events:
                if aborted or key.fd not in active:
                    continue
                t = key.data
                eof = False
                while True:
                    try:
                        chunk = os.read(t["r_fd"], 65536)
                    except BlockingIOError:
                        break
                    except OSError:
                        eof = True
                        break
                    if not chunk:
                        eof = True
                        break
                    t["chunks"].append(chunk)
                if eof:
                    selector.unregister(t["r_fd"])
                    del active[t["r_fd"]]
                    on_unit_done(t["unit"], _finish_task(t))
                    if aborted:
                        break
            if aborted:
                break
            now = time.monotonic()
            for r_fd in list(active):
                if aborted or r_fd not in active:
                    continue
                t = active[r_fd]
                if t["deadline"] is not None and now >= t["deadline"]:
                    if not t["timed_out"]:
                        t["timed_out"] = True
                        try:
                            os.killpg(t["pid"], signal.SIGKILL)
                        except OSError:
                            pass
                    elif now >= t["deadline"] + 0.2:
                        # A detached descendant kept the pipe write end open after SIGKILL; reap anyway.
                        selector.unregister(r_fd)
                        del active[r_fd]
                        on_unit_done(t["unit"], _finish_task(t))
    finally:
        if active:
            abort_running()
        selector.close()
    save_timings(tpath, unit_results)

    bad =[r for r in results if r["rc"] != 0]
    total_s = sum(r["secs"] for r in results)
    if o["repeat"] > 1:
        sys.stdout.write("TOTAL %d runs\n" % len(results))
    sys.stdout.write("TOTAL %d files, %d tests, %d failed files, %.1f s (wall %.1f s, -j %d)\n" % (
        len(files), sum(r["ran"] for r in results), len(bad), total_s, time.time() - wall0, jobs))
    skipped = sum(r["skipped"] for r in results if r["file"].startswith("slow/"))
    if skipped and not os.environ.get("SWARMBOX_TEST_REAL"):
        sys.stdout.write("note: %d slow tests were skipped here (a program they need is missing, or SWARMBOX_TEST_REAL=1 is not set): "
                         "sh dev/test-slow.sh runs them in Podman, where the programs are\n" % skipped)
    if o["timing"] and results:
        sys.stdout.write("slowest files:\n")
        for r in sorted(results, key=lambda r: -r["secs"])[:o["timing"]]:
            sys.stdout.write("  %6.1f s  %s\n" % (r["secs"], r["file"]))
    if o["durations"] is not None:
        for r in results:
            blocks = re.findall(r"Slowest test durations\n-+\n(.*?)\n\n", r["text"], re.S)
            if blocks:
                sys.stdout.write("\n%s\n%s\n" % (r["file"], "\n".join(blocks)))
    sys.stdout.flush()
    return 1 if bad else 0


def main_keeping_the_terminal(argv):
    """The terminal the runner was started in comes back as it was, whatever a test did to it (belt and braces: the files get no terminal at all)."""
    saved = None
    try:
        import termios
        saved = termios.tcgetattr(sys.stdin.fileno()) if sys.stdin.isatty() else None
    except (ImportError, OSError, ValueError, termios.error):
        saved = None
    try:
        return main(argv)
    finally:
        if saved is not None:
            try:
                termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, saved)
            except (OSError, ValueError, termios.error):
                pass


if __name__ == "__main__":
    sys.exit(main_keeping_the_terminal(sys.argv[1:]))
