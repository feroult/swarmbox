"""Run one command and, when it ends, kill the processes it left behind (used by tests/run.sh).

Usage: python3 tests/support/reap_run.py COMMAND [ARGS...]

This process becomes a child subreaper (Linux prctl), so every process of the command that is orphaned is adopted by it and not by
PID 1. When the command exits, the adopted processes (and only those: the ones whose parent is this process) are killed by PID
and reaped; "reap_run: seconds S" and, when N is not zero, "reap_run: reaped N" go to stderr. Exit status: the command's. Without prctl (not Linux) it
just runs the command.
"""
import ctypes
import os
import signal
import subprocess
import sys
import time

PR_SET_CHILD_SUBREAPER = 36


def children_of(pid):
    found = []
    for name in os.listdir("/proc"):
        if not name.isdigit():
            continue
        try:
            with open("/proc/%s/stat" % name) as f:
                stat = f.read()
        except OSError:
            continue
        # the command name may contain spaces and parentheses: the fields after the last ")" are fixed
        rest = stat[stat.rindex(")") + 2:].split()
        if int(rest[1]) == pid:
            found.append((int(name), rest[0]))   # (pid, state)
    return found


def cmdline(pid):
    try:
        with open("/proc/%d/cmdline" % pid, "rb") as f:
            return f.read().replace(b"\0", b" ").decode("utf-8", "replace").strip()[:70] or "?"
    except OSError:
        return "?"


def main(argv):
    if not argv:
        print(__doc__, file=sys.stderr)
        return 2
    subreaper = False
    try:
        subreaper = ctypes.CDLL(None, use_errno=True).prctl(PR_SET_CHILD_SUBREAPER, 1, 0, 0, 0) == 0
    except (OSError, AttributeError):
        pass
    # A runner started with nohup, setsid wrappers or a CI agent can hand down SIGHUP/SIGINT/SIGTERM as ignored; an ignored signal
    # stays ignored through exec and a shell cannot trap it, so the tests that signal a helper would wait for their timeout.
    # Give the command the default dispositions (the test files do the same for themselves, see restore_signals in them).
    for sig in (signal.SIGHUP, signal.SIGTERM, signal.SIGQUIT):
        signal.signal(sig, signal.SIG_DFL)
    signal.signal(signal.SIGINT, signal.default_int_handler)
    started = time.time()
    p = subprocess.Popen(argv)
    try:
        rc = p.wait()
    except KeyboardInterrupt:
        p.send_signal(signal.SIGINT)
        rc = p.wait()
    reaped = 0
    left = []
    if subreaper:
        me = os.getpid()
        for _ in range(5):
            kids = children_of(me)
            if not kids:
                break
            for pid, state in kids:
                if state == "Z":   # already dead, only waiting to be collected
                    continue
                try:
                    left.append(cmdline(pid))
                    os.kill(pid, signal.SIGKILL)
                    reaped += 1
                except OSError:
                    pass
            time.sleep(0.05)
            while True:
                try:
                    pid, _ = os.waitpid(-1, os.WNOHANG)
                except ChildProcessError:
                    break
                if pid == 0:
                    break
    print("reap_run: seconds %.1f" % (time.time() - started), file=sys.stderr)
    if reaped:
        print("reap_run: reaped %d" % reaped, file=sys.stderr)
        print("reap_run: left behind: %s" % " | ".join(left), file=sys.stderr)   # which test leaks: the first words of each command
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
