"""swarmbox-sysop: the command of the sysop addon.

  swarmbox-sysop serve [--log] [--dock] [--watch]   the resident service: reads goals from the bus and runs them, one at a time (prepare.sh starts it).
                                               --watch: it runs as a child of a watcher that starts it again when it dies (a kill, a crash), with a back-off and a
                                               stop after five crashes in a minute (watch.py); a second `serve --watch` tells the first to start it now
                                               --dock: start the UI helpers (the herdr agent bridge; skipped when SWARMBOX_MUX=none)
  swarmbox-sysop goal [--source S] [--wait] [--timeout N] TEXT...    publish a goal on the bus (topic goal); `-` reads the text from stdin;
                                               prints the goal id. --wait follows the goal to its end (exit 0 done, 1 failed or stopped)
  swarmbox-sysop goal              with no text, on a terminal: asks for the goal on one line (the popup of Ctrl+A then g in herdr)
  swarmbox-sysop veto                          the veto key: refuses what waits (a countdown is vetoed, an approval is refused)
  swarmbox-sysop approve                       allow what waits
  swarmbox-sysop status [--json] [-q]          the service and its goals; exit 0 when it runs, 1 when it does not
  swarmbox-sysop stop [GOAL_ID]                the stop key: ends the running goal (and drops the queue), or just GOAL_ID
  swarmbox-sysop mcp                           the MCP server of a goal (the brain's MCP config runs this; SWARMBOX_SYSOP_CONTEXT names the goal)
  swarmbox-sysop agent                         interactive OSC 7501 agent bridge for herdr-core / herdr-app (hidden from normal tabs)
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

from . import actions, brain, busclient, config, ipc, mcpserver, paths, policy, service, state, ui_host, watch

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
    ui = ui_host.start_ui(pth, cfg, log=svc.log, enabled=args.dock)
    for sg in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sg, lambda *_: svc.shutdown())
    signal.signal(signal.SIGHUP, signal.SIG_IGN)
    rc = None
    try:
        rc = svc.run()
    finally:
        ui.shutdown(unset=rc != 9)      # 9: another service is running and keeps the UI state
    if rc == 9:
        print("swarmbox-sysop: already running", file=sys.stderr)
        return 0
    return rc


def prompt_goal(bus, source="panel", inp=None, out=None, topic=None):
    """`goal` with no text on a terminal (the popup of Ctrl+A then g in herdr): ask for a goal on one line and publish it. 0 sent, 1 empty (cancel),
    2 too long, 3 not sent."""
    inp, out = inp or sys.stdin, out or sys.stderr
    out.write("Goal for the sysop (Enter sends it, empty cancels): ")
    out.flush()
    text = inp.readline().strip()
    if not text:
        return 1
    if len(text) > service.MAX_GOAL_TEXT:
        out.write("too long: %d characters, at most %d. Press Enter." % (len(text), service.MAX_GOAL_TEXT))
        inp.readline()
        return 2
    try:
        actions.publish_goal(bus, text, source=source, topic=topic)
    except (busclient.BusError, config.ConfigError) as e:
        out.write("the goal was not sent: %s. Press Enter." % busclient.words(e))
        out.flush()
        inp.readline()
        return 3
    return 0


def cmd_goal(args):
    text = " ".join(args.text)
    if not args.text:
        if not sys.stdin.isatty():
            print("swarmbox-sysop: goal: no text", file=sys.stderr)
            return 2
        return prompt_goal(busclient.Bus(), "panel")
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
        gid, _ = actions.publish_goal(busclient.Bus(), text, source=args.source)
    except config.ConfigError as e:
        print("swarmbox-sysop: %s" % e, file=sys.stderr)
        return 2
    except busclient.BusError as e:
        hint = {"no_subscriber": " (is the sysop service running? swarmbox-sysop status)",
                "bus_down": " (the box starts the bus again within seconds, or run: swarmbox-bus restart)",
                "busy": " (the sysop is busy with another goal: try again in a moment)"}.get(e.code, "")
        print("swarmbox-sysop: %s%s" % (e, hint), file=sys.stderr)
        return EXIT.get(e.code, 1)
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
                print("say: %s" % state.clean(s.get("text")))
            said = len(st.get("say", []))
            if st.get("state") in state.TERMINAL:
                summary = st.get("summary") or st.get("error") or ""
                print("%s%s" % (st["state"], (": " + state.clean(summary)) if summary else ""))
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
                print("sysop: not running: %s. Start it again: swarmbox-addon prepare" % state.clean(crash.strip().rstrip(";.")))
            else:
                print("sysop: not running (the box starts it at boot and again after a crash; by hand: swarmbox-addon prepare)")
        else:
            st = st or {}
            s = st.get("settings", {})
            print("sysop: running (pid %s), bus %s, autonomy %s, countdown %gs, brain %s %s" % (
                st.get("pid", "?"), state.clean(st.get("bus", "?")), state.clean(s.get("autonomy")), s.get("countdown", 0), state.clean(s.get("brain")),
                state.clean(s.get("model"))))
            print("current: %s" % (st.get("current") or "none"))
            print("queued: %d" % len(st.get("queue", [])))
        for g in service.recent_goals(pth, 3):
            print("  %-22s %-16s %-6s %s" % (state.clean(g.get("id")), state.clean(g.get("state")), state.clean(g.get("source")),
                                                   state.clean((g.get("text") or "")[:60]).replace("\n", " ")))
    return 0 if up else 1


def cmd_stop(args):
    res = actions.stop(paths.Paths(), goal_id=args.goal)
    if res.ok:
        print("swarmbox-sysop: " + res.message)
    else:
        ui_host.notify(res.message)
    return res.rc


def cmd_veto(args):
    """Cancel: refuse what waits; with nothing waiting, stop the goal that runs (one button for "no" and for "enough")."""
    pth = paths.Paths()
    gid, p = actions.pending_of(pth)
    if gid and not (p and actions.is_live(p)):
        args.goal = None
        return cmd_stop(args)
    res = actions.veto(pth, by="key")
    ui_host.notify(res.message)
    return res.rc


def cmd_approve(_args):
    res = actions.approve(paths.Paths(), by="key")
    ui_host.notify(res.message)
    return res.rc


def _cmd_agent(_args):
    from . import agent
    return agent.run_agent()


def self_test():
    problems = []
    try:
        cfg = config.load(os.environ)
        brain.parse_template(cfg.brain)
    except (config.ConfigError, brain.TemplateError) as e:
        problems.append(str(e))
    gated = policy.Policy(autonomy="auto")
    verdict = gated.assess_run({"tab": "@1", "cmd": "bash"}, "rm -rf ~")
    if verdict.level != "high" or gated.route(verdict).action != "approve":
        problems.append("the policy does not hold a high-risk command for approval (autonomy auto)")
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
    s.add_argument("--dock", action="store_true", help="start the UI helpers (the herdr agent bridge)")
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
    sub.add_parser("mcp").set_defaults(fn=lambda a: mcpserver.main())
    sub.add_parser("agent").set_defaults(fn=_cmd_agent)
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
