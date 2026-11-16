import sys


def _redock(argv):
    """The hook of a resize, `dock redock --socket S --window @N`, runs once per resize event: dozens a second while a browser window is dragged. It imports
    only the dock (a Python start of about 15 ms and 9 MiB instead of 28 ms and 15 MiB with the whole command line), so a burst costs the box less.
    None when the arguments are anything else: cli.main understands them."""
    if argv[:2] != ["dock", "redock"] or len(argv) % 2:
        return None
    opts = {argv[i]: argv[i + 1] for i in range(2, len(argv), 2)}
    if len(opts) != (len(argv) - 2) // 2 or any(k not in ("--socket", "--window") for k in opts):
        return None
    from . import dock
    return dock.run("redock", opts.get("--socket", ""), opts.get("--window"))


if __name__ == "__main__":
    rc = _redock(sys.argv[1:])
    if rc is None:
        from .cli import main
        rc = main()
    sys.exit(rc)
