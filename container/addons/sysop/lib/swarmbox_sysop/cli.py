"""swarmbox-sysop: the command of the sysop addon.

  swarmbox-sysop serve [--log] [--dock] [--watch]   the resident service: reads goals from the bus and runs them, one at a time (prepare.sh starts it).
                                               --watch: it runs as a child of a watcher that starts it again when it dies (a kill, a crash), with a back-off and a
                                               stop after five crashes in a minute (watch.py); a second `serve --watch` tells the first to start it now
                                               --dock: it also keeps the panel in tmux as `sysop.panel` says: up in every window (always), or open while a goal runs (auto), or
                                               never (off); dock.Follower
  swarmbox-sysop goal [--source S] [--wait] [--timeout N] TEXT...    publish a goal on the bus (topic goal); `-` reads the text from stdin;
                                               prints the goal id. --wait follows the goal to its end (exit 0 done, 1 failed or stopped)
  swarmbox-sysop goal              with no text, on a terminal: asks for the goal on one line (the tmux key `g` runs it in a popup)
  swarmbox-sysop veto [KEY OPTIONS]            the veto key: refuses what waits (a countdown is vetoed, an approval is refused)
  swarmbox-sysop approve [KEY OPTIONS]         the approval gesture: opens the panel on the approval prompt and focuses it (keys.py); allows nothing itself
                                               KEY OPTIONS (veto, approve, stop): --socket PATH --window ID --client NAME, as the tmux keys pass them
  swarmbox-sysop status [--json] [-q]          the service and its goals; exit 0 when it runs, 1 when it does not
  swarmbox-sysop stop [GOAL_ID]                the stop key: ends the running goal (and drops the queue), or just GOAL_ID
  swarmbox-sysop mcp                           the MCP server of a goal (the brain's MCP config runs this; SWARMBOX_SYSOP_CONTEXT names the goal)
  swarmbox-sysop panel                         the panel: the goal, the log, the countdown, the approval; g types a goal (run it in a tmux pane)
  swarmbox-sysop dock open|close|toggle|redock|sync [--socket PATH] [--window ID]   the panel in tmux, one per window (the tmux key and the hooks call this)
  swarmbox-sysop --self-test                   checks the install without a model

Settings: SWARMBOX_SYSOP_* (config.py). Exit codes of `goal` follow swarmbox-bus: 3 nobody listens (the service is not running), 4 the bus is not
running, 5 too large, 6 bad request, 7 busy.
"""
import argparse
import json
import os
import re
import signal
import sys
import time

from . import brain, busclient, config, dock, ipc, keys, mcpserver, panel, paths, policy, service, watch

EXIT = {"no_subscriber": 3, "bus_down": 4, "bus_closed": 4, "too_large": 5, "bad_topic": 6, "bad_request": 6, "bad_body": 6, "busy": 7}


def _cfg():
    try:
        return config.load(os.environ)
    except config.ConfigError as e:
        print("swarmbox-sysop: %s" % e, file=sys.stderr)
        raise SystemExit(2)


LOG_MAX = 1 << 20      # serve.log is moved to serve.log.1 past this (one old file), at the start of the service and then every minute while it runs


def _open_log(pth):
    """serve.log, appended, mode 0600: its descriptor (the caller closes it)"""
    return os.open(pth.log, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o600)


def rotate_log(pth):
    """Past LOG_MAX move serve.log to serve.log.1 (the older one is replaced) and point standard output and error at a new serve.log. True when it rotated.
    For the daemon (--log): without this the log of a service that runs for months only grows."""
    try:
        if os.path.getsize(pth.log) <= LOG_MAX:
            return False
        os.replace(pth.log, pth.log + ".1")
        fd = _open_log(pth)
    except OSError:
        return False
    try:
        sys.stdout.flush()
        sys.stderr.flush()
    except (OSError, ValueError):
        pass
    os.dup2(fd, 1)
    os.dup2(fd, 2)
    os.close(fd)
    return True


def _daemonize(pth):
    """What `serve --log` does first: no inherited descriptors (the caller may hold a pipe or a lock), output to serve.log."""
    try:
        os.closerange(3, 256)
    except OSError:
        pass
    pth.make()
    try:
        if os.path.getsize(pth.log) > LOG_MAX:
            os.replace(pth.log, pth.log + ".1")
    except OSError:
        pass
    fd = _open_log(pth)
    null = os.open(os.devnull, os.O_RDONLY)
    os.dup2(null, 0)
    os.dup2(fd, 1)
    os.dup2(fd, 2)
    for x in (fd, null):
        if x > 2:
            os.close(x)


def cmd_watch(args, pth):
    """serve --watch: the watcher (watch.py) runs `serve` (the same options, without --watch) as a child and starts it again when it dies."""
    argv = [sys.executable, "-B", "-m", "swarmbox_sysop", "serve"] + (["--log"] if args.log else []) + (["--dock"] if args.dock else [])
    return watch.Watcher(pth, argv).run()


def cmd_serve(args):
    pth = paths.Paths()
    if args.log:
        _daemonize(pth)       # first: a refused setting is then written to serve.log, where the one who started the service in the background can read it
    if args.watch:
        return cmd_watch(args, pth)
    cfg = _cfg()
    svc = service.Service(cfg, pth)
    if args.log:
        svc.housekeeping = lambda: rotate_log(pth)
    follower = dock.Follower(pth, log=svc.log, mode=cfg.panel_mode).start() if args.dock else None      # off too: its thread only takes away the hooks of an earlier always
    for sg in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sg, lambda *_: svc.shutdown())
    signal.signal(signal.SIGHUP, signal.SIG_IGN)
    try:
        rc = svc.run()
    finally:
        if follower:
            follower.shutdown()
    if rc == 9:
        print("swarmbox-sysop: already running", file=sys.stderr)
        return 0
    return rc


def cmd_goal(args):
    text = " ".join(args.text)
    if not args.text:
        if not sys.stdin.isatty():
            print("swarmbox-sysop: goal: no text", file=sys.stderr)
            return 2
        return keys.prompt(busclient.Bus(), "panel")
    if text == "-":
        text = sys.stdin.read().rstrip("\n")
    if not text.strip():
        print("swarmbox-sysop: goal: no text", file=sys.stderr)
        return 2
    if len(text) > service.MAX_GOAL_TEXT:      # the bus has no ack: the service would drop it silently, so say it here
        print("swarmbox-sysop: goal: %d characters, at most %d" % (len(text), service.MAX_GOAL_TEXT), file=sys.stderr)
        return 2
    if not re.fullmatch(r"[a-z][a-z0-9_-]{0,31}", args.source):
        print("swarmbox-sysop: goal: --source is a short lowercase label (cli, panel, voice)", file=sys.stderr)
        return 2
    try:
        rep = busclient.Bus().pub(config.goal_topic(), {"text": text}, args.source)
    except config.ConfigError as e:
        print("swarmbox-sysop: %s" % e, file=sys.stderr)
        return 2
    except busclient.BusError as e:
        hint = {"no_subscriber": " (is the sysop service running? swarmbox-sysop status)",
                "bus_down": " (the box starts the bus again within seconds, or run: swarmbox-bus restart)",
                "busy": " (the sysop is busy with another goal: try again in a moment)"}.get(e.code, "")
        print("swarmbox-sysop: %s%s" % (e, hint), file=sys.stderr)
        return EXIT.get(e.code, 1)
    gid = service.sanitize(rep.get("id"), "")
    print(gid)
    if not args.wait:
        return 0
    pth = paths.Paths()
    end = time.time() + args.timeout
    said = 0
    while time.time() < end:
        st = ipc.read_json(os.path.join(pth.goal_dir(gid), "state.json"))
        if isinstance(st, dict):
            for s in st.get("say", [])[said:]:
                print("say: %s" % panel.clean(s.get("text")))
            said = len(st.get("say", []))
            if st.get("state") in ("done", "stopped", "failed"):
                print("%s%s" % (st["state"], (": " + panel.clean(st.get("summary") or st.get("error") or "")) if (st.get("summary") or st.get("error")) else ""))
                return 0 if st["state"] == "done" else 1
        time.sleep(0.2)
    print("swarmbox-sysop: goal %s did not end in %d s" % (gid, args.timeout), file=sys.stderr)
    return 1


def cmd_status(args):
    pth = paths.Paths()
    up = service.running(pth)
    st = ipc.read_json(pth.status) if up else None
    if args.json:
        print(json.dumps({"running": up, "status": st, "recent": service.recent_goals(pth, 5)}, indent=2))
    elif not args.quiet:
        if not up:
            crash = ipc.read_text(pth.crashloop)
            if crash:
                print("sysop: not running: %s. Start it again: swarmbox-addon prepare" % panel.clean(crash.strip().rstrip(";.")))
            else:
                print("sysop: not running (the box starts it at boot and again after a crash; by hand: swarmbox-addon prepare)")
        else:
            st = st or {}
            s = st.get("settings", {})
            print("sysop: running (pid %s), bus %s, autonomy %s, countdown %gs, brain %s %s" % (
                st.get("pid", "?"), panel.clean(st.get("bus", "?")), panel.clean(s.get("autonomy")), s.get("countdown", 0), panel.clean(s.get("brain")),
                panel.clean(s.get("model"))))
            print("current: %s" % (st.get("current") or "none"))
            print("queued: %d" % len(st.get("queue", [])))
        for g in service.recent_goals(pth, 3):
            print("  %-22s %-16s %-6s %s" % (panel.clean(g.get("id")), panel.clean(g.get("state")), panel.clean(g.get("source")),
                                                   panel.clean((g.get("text") or "")[:60]).replace("\n", " ")))
    return 0 if up else 1


def _key_tmux(args):
    return dock.Tmux(argv=["tmux", "-S", args.socket]) if getattr(args, "socket", "") else dock.Tmux()


def cmd_stop(args):
    pth = paths.Paths()
    tm = _key_tmux(args) if getattr(args, "client", "") else None
    client = getattr(args, "client", "")
    if not service.running(pth):
        keys._say("the sysop is not running: nothing to stop", tm, client)
        return 1
    ipc.request_stop(pth, args.goal)
    end = time.time() + 5
    while time.time() < end:
        if not os.path.exists(pth.stop_request):
            msg = "stop taken (%s)" % (args.goal or "the running goal and the queue")
            if client:
                keys._say(msg, tm, client)
            else:
                print("swarmbox-sysop: " + msg)
            return 0
        time.sleep(0.05)
    keys._say("stop requested, the service has not taken it yet", tm, client)
    return 1


def cmd_veto(args):
    return keys.veto(paths.Paths(), _key_tmux(args), args.client)


def cmd_approve(args):
    if args.window is not None and not re.fullmatch(r"@[0-9]{1,9}", args.window):
        print("swarmbox-sysop: approve: --window must be a tmux window id such as @3", file=sys.stderr)
        return 2
    return keys.approve(paths.Paths(), dock.default_dock(_key_tmux(args)), args.window, _key_tmux(args), args.client)


def self_test():
    problems = []
    try:
        cfg = config.load(os.environ)
        brain.parse_template(cfg.brain)
    except (config.ConfigError, brain.TemplateError) as e:
        problems.append(str(e))
    if policy.Policy().route(policy.Policy().assess_run({"tab": "@1", "cmd": "bash"}, "rm -rf ~")).action != "approve":
        problems.append("the policy does not hold a high-risk command for approval")
    for p in problems:
        print("swarmbox-sysop: " + p, file=sys.stderr)
    print("swarmbox-sysop: self-test %s" % ("FAILED" if problems else "ok"), file=sys.stderr)
    return 1 if problems else 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="swarmbox-sysop", description=__doc__.split("\n")[0])
    ap.add_argument("--self-test", action="store_true")
    sub = ap.add_subparsers(dest="cmd")
    s = sub.add_parser("serve")
    s.add_argument("--log", action="store_true", help="detached mode: output to serve.log")
    s.add_argument("--dock", action="store_true", help="keep the panel in tmux as sysop.panel says (always, auto, off)")
    s.add_argument("--watch", action="store_true", help="run the service as a child and start it again when it dies (what the box does)")
    s.set_defaults(fn=cmd_serve)
    g = sub.add_parser("goal")
    g.add_argument("--source", default="cli")
    g.add_argument("--wait", action="store_true")
    g.add_argument("--timeout", type=int, default=600)
    g.add_argument("text", nargs="*")
    g.set_defaults(fn=cmd_goal)
    t = sub.add_parser("status")
    t.add_argument("--json", action="store_true")
    t.add_argument("-q", "--quiet", action="store_true")
    t.set_defaults(fn=cmd_status)
    p = sub.add_parser("stop")
    p.add_argument("goal", nargs="?", default=None)
    p.set_defaults(fn=cmd_stop)
    for name, fn in (("veto", cmd_veto), ("approve", cmd_approve)):
        k = sub.add_parser(name)
        k.set_defaults(fn=fn)
    for k in (p, sub.choices["veto"], sub.choices["approve"]):
        k.add_argument("--socket", default="")
        k.add_argument("--window", default=None)
        k.add_argument("--client", default="")
    sub.add_parser("mcp").set_defaults(fn=lambda a: mcpserver.main())
    sub.add_parser("panel").set_defaults(fn=lambda a: panel.run())
    d = sub.add_parser("dock")
    d.add_argument("action", choices=dock.ACTIONS)
    d.add_argument("--socket", default="")
    d.add_argument("--window", default=None)
    d.set_defaults(fn=lambda a: dock.run(a.action, a.socket, a.window))
    args = ap.parse_args(sys.argv[1:] if argv is None else list(argv))
    if args.self_test:
        return self_test()
    if not args.cmd:
        ap.print_help(sys.stderr)
        return 2
    try:
        return args.fn(args)
    except paths.SysopPathError as e:
        print("swarmbox-sysop: %s" % e, file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
