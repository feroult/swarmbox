"""swarmbox-voice: the command of the voice addon. Voice is an input: it turns audio into a goal on the bus and does nothing else.

  swarmbox-voice serve [--listen 127.0.0.1:17682] [--allow-host NAME ...]   the HTTP service (loopback only)
  swarmbox-voice front [--listen 0.0.0.0:7681] -- SERVER ARGS...            health and audio on the web port, the web server behind
  swarmbox-voice model list | fetch NAME                                    the multilingual Whisper models
  swarmbox-voice say TEXT...                                                publish a goal on the bus, as if it was spoken (no microphone)
  swarmbox-voice --self-test                                                checks the install without a model

Settings come from SWARMBOX_VOICE_* (see config.py). Nothing here runs on its own: `swarmbox addon install voice` installs it.
"""
import argparse
import os
import signal
import sys

from . import config as vconfig
from . import front, models, server, stt

DEFAULT_LISTEN = "127.0.0.1:17682"


def _cfg():
    try:
        return vconfig.load(os.environ)
    except vconfig.ConfigError as e:
        print("swarmbox-voice: %s" % e, file=sys.stderr)
        raise SystemExit(2)


def cmd_front(args, server_args):
    return front.run(args, server_args)


def _on_term(*_):
    """SIGTERM ends the service through KeyboardInterrupt, ONCE. The front sends one SIGTERM and, when it exits, the kernel sends a second (--die-with-parent): the
    second one used to arrive while the first was being handled, or while the interpreter was shutting down, and raised KeyboardInterrupt there (a traceback in
    web-terminal.log, found by the soak test)."""
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    raise KeyboardInterrupt


def cmd_serve(args):
    if args.die_with_parent:
        front.pdeathsig()
    host, _, port = args.listen.rpartition(":")
    try:
        svc = server.Service(_cfg())
        httpd = server.make_server(svc, host or "127.0.0.1", int(port), args.allow_host)
    except (ValueError, OSError) as e:
        print("swarmbox-voice: %s" % e, file=sys.stderr)
        return 2
    signal.signal(signal.SIGTERM, _on_term)
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


def cmd_say(args):
    """A typed goal, published like the one a spoken request becomes (to try the path without a microphone)."""
    text = " ".join(args.text)
    svc = server.Service(_cfg())
    name = svc.goal(text)
    if name == "sent":
        print("swarmbox-voice: goal sent", file=sys.stderr)
        return 0
    print("swarmbox-voice: %s" % server.STATES[name][1], file=sys.stderr)
    return {"nothing_heard": 2, "no_listener": 3, "busy": 7}.get(name, 4)


def self_test():
    cfg = _cfg()
    problems = []
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
    f = sub.add_parser("front", help="serve the voice routes on the web port, with the web server command after --")
    front.add_arguments(f)
    sy = sub.add_parser("say", help="publish a goal on the bus, as if it was spoken",
                        description="Publish TEXT as a goal on the bus (the topic of voice.topic, source voice), as a spoken request would; no microphone needed.")
    sy.add_argument("text", nargs="+")
    sy.set_defaults(fn=cmd_say)
    argv = sys.argv[1:] if argv is None else list(argv)
    argv, server_args = front.split_command(argv) if "front" in argv[:1] else (argv, [])
    args = ap.parse_args(argv)
    if args.self_test:
        return self_test()
    if not args.cmd:
        ap.print_help(sys.stderr)
        return 2
    if args.cmd == "front":
        return cmd_front(args, server_args)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
