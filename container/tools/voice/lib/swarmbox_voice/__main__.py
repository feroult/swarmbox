"""swarmbox-voice: the command of the voice tool.

  swarmbox-voice serve [--listen 127.0.0.1:17682] [--allow-host NAME ...]   the HTTP service (loopback only)
  swarmbox-voice front [--listen 0.0.0.0:7681] -- ttyd ARGS...              the page and the service on the web terminal port, ttyd behind
  swarmbox-voice model list | fetch NAME                                    the multilingual Whisper models
  swarmbox-voice planners                                                   built-in and user planners
  swarmbox-voice plan TEXT...                                               a typed request: the service makes it the pending plan
  swarmbox-voice panel [--service HOST:PORT]                                the panel: shows the pending plan, you run, edit or cancel it
  swarmbox-voice dock open|close|toggle|redock [--socket PATH] [--window ID] the panel pane in tmux (the tmux key and the hook call this)
  swarmbox-voice --self-test                                                checks the install without a model

Settings come from SWARMBOX_VOICE_* (see config.py). Nothing here runs on its own: `swarmbox tool install voice` installs it.
"""
import argparse
import json
import os
import re
import signal
import sys

from . import config as vconfig
from . import dock, front, models, panel, planners, server, store, stt
from .tmuxrun import Tmux

DEFAULT_LISTEN = "127.0.0.1:17682"


def service_addr(args):
    """Where the panel and the CLI find the service: --service, SWARMBOX_TEST_VOICE_SERVICE (tests), else the box's loopback address."""
    return getattr(args, "service", None) or os.environ.get("SWARMBOX_TEST_VOICE_SERVICE") or DEFAULT_LISTEN


def _cfg():
    try:
        return vconfig.load(os.environ)
    except vconfig.ConfigError as e:
        print("swarmbox-voice: %s" % e, file=sys.stderr)
        raise SystemExit(2)


def cmd_front(args, ttyd_args):
    return front.run(args, ttyd_args)


def cmd_serve(args):
    if args.die_with_parent:
        front.pdeathsig()
    host, _, port = args.listen.rpartition(":")
    try:
        # SWARMBOX_TEST_VOICE_TTL (seconds): test-only, to see a plan expire without waiting two minutes
        ttl = float(os.environ.get("SWARMBOX_TEST_VOICE_TTL") or store.TTL)
        svc = server.Service(_cfg(), store=store.PlanStore(ttl=ttl), dock=dock.default_dock(Tmux(), "%s:%s" % (host or "127.0.0.1", port)))
        httpd = server.make_server(svc, host or "127.0.0.1", int(port), args.allow_host)
    except (ValueError, OSError) as e:
        print("swarmbox-voice: %s" % e, file=sys.stderr)
        return 2
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    print("swarmbox-voice: listening on http://%s:%d/voice/" % httpd.server_address[:2], file=sys.stderr)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
    return 0


def cmd_model(args):
    folder = stt.models_dir()
    if args.action == "list":
        have = models.installed(folder)
        for name, (size, _) in models.MODELS.items():
            print("%-15s %5d MB  %s" % (name, size // 1000000, "installed" if name in have else "-"))
        return 0
    if not args.name:
        print("swarmbox-voice: model fetch needs a name", file=sys.stderr)
        return 2
    try:
        path = models.fetch(args.name, folder, progress=lambda d, t: print("\r%3d%%" % (100 * d // t), end="", file=sys.stderr))
    except models.ModelError as e:
        print("\nswarmbox-voice: %s" % e, file=sys.stderr)
        return 1
    print("\n" + path, file=sys.stderr)
    return 0


def cmd_planners(_args):
    for name, p in sorted(planners.discover().items()):
        print("%-16s %-8s %s" % (name, p.source, p.path))
    return 0


def cmd_plan(args):
    """A typed request goes to the running service, so that the plan is THE pending plan and the panel shows it."""
    client = panel.Client(service_addr(args))
    body = {"utterance": " ".join(args.text)}
    if args.pane:
        body["pane"] = args.pane
    try:
        out = client.post("/voice/plan", body)
    except panel.ServiceError as e:
        print("swarmbox-voice: %s" % e.message, file=sys.stderr)
        return 1
    except panel.ServiceDown as e:
        print("swarmbox-voice: the voice service is not answering at %s (%s)" % (client.addr, e), file=sys.stderr)
        return 1
    print(json.dumps(out, indent=2))
    return 0


def cmd_panel(args):
    return panel.run(service_addr(args))


def cmd_dock(args):
    if args.window is not None and not re.fullmatch(r"@[0-9]{1,9}", args.window):
        print("swarmbox-voice: --window must be a tmux window id such as @3", file=sys.stderr)
        return 2
    tmux = Tmux(argv=["tmux", "-S", args.socket]) if args.socket else Tmux()
    d = dock.default_dock(tmux, service_addr(args))
    try:
        if args.action == "open":
            out = d.open(window=args.window)
        elif args.action == "close":
            out = "closed %d" % d.close()
        elif args.action == "toggle":
            out = d.toggle(window=args.window)
        else:
            out = d.redock()
    except dock.DockError as e:
        print("swarmbox-voice: %s" % e, file=sys.stderr)
        return 1
    if args.action != "redock":
        print("swarmbox-voice: panel %s" % out, file=sys.stderr)
    return 0


def self_test():
    cfg = _cfg()
    problems = []
    if planners.find(cfg.planner) is None:
        problems.append("no planner called %r" % cfg.planner)
    if planners.find("passthrough") is None:
        problems.append("the passthrough planner is missing")
    exe = stt.whisper_bin()
    if not os.access(exe, os.X_OK):
        problems.append("whisper-cli is missing: %s" % exe)
    if not os.path.isfile(stt.model_path(cfg.stt_model)):
        problems.append("the model %s is not downloaded (swarmbox-voice model fetch %s)" % (cfg.stt_model, cfg.stt_model))
    for p in problems:
        print("swarmbox-voice: " + p, file=sys.stderr)
    print("swarmbox-voice: self-test %s" % ("FAILED" if problems else "ok"), file=sys.stderr)
    return 1 if problems else 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="swarmbox-voice", description=__doc__.split("\n")[0])
    ap.add_argument("--self-test", action="store_true")
    sub = ap.add_subparsers(dest="cmd")
    s = sub.add_parser("serve")
    s.add_argument("--listen", default=DEFAULT_LISTEN)
    s.add_argument("--allow-host", action="append", default=[])
    s.add_argument("--die-with-parent", action="store_true", help=argparse.SUPPRESS)
    s.set_defaults(fn=cmd_serve)
    m = sub.add_parser("model")
    m.add_argument("action", choices=("list", "fetch"))
    m.add_argument("name", nargs="?")
    m.set_defaults(fn=cmd_model)
    f = sub.add_parser("front", help="serve the page and the service on the web terminal port, with ttyd after --")
    front.add_arguments(f)
    sub.add_parser("planners").set_defaults(fn=cmd_planners)
    pl = sub.add_parser("plan")
    pl.add_argument("text", nargs="+")
    pl.add_argument("--pane", default="")
    pl.add_argument("--service", default="")
    pl.set_defaults(fn=cmd_plan)
    pn = sub.add_parser("panel")
    pn.add_argument("--service", default="")
    pn.set_defaults(fn=cmd_panel)
    dk = sub.add_parser("dock")
    dk.add_argument("action", choices=("open", "close", "toggle", "redock"))
    dk.add_argument("--socket", default="")
    dk.add_argument("--window", default=None)
    dk.add_argument("--service", default="")
    dk.set_defaults(fn=cmd_dock)
    argv = sys.argv[1:] if argv is None else list(argv)
    argv, ttyd_args = front.split_command(argv) if "front" in argv[:1] else (argv, [])
    args = ap.parse_args(argv)
    if args.self_test:
        return self_test()
    if not args.cmd:
        ap.print_help(sys.stderr)
        return 2
    if args.cmd == "front":
        return cmd_front(args, ttyd_args)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
