"""Where the sysop keeps its files, with the same rules as dirs.sh (SB_RUN_DIR, SB_STATE_DIR, XDG_STATE_HOME, HOME).

  run   <SB_RUN_DIR>/sysop      (tmpfs in the box, regenerated at every start)  serve.lock serve.pid status.json stop.request
  state <SB_STATE_DIR>/sysop    (the workspace, survives a restart)             events.jsonl (the audit file) serve.log goals/<id>/...

Both folders are private: made with mode 0700, owned by the user, not a symbolic link, and put back to 0700 when something loosened them.
The files in them are 0600. A folder that belongs to someone else, or is a link, is refused (SysopPathError) instead of used.
"""
import os
import stat


class SysopPathError(OSError):
    pass


def _env(env):
    return os.environ if env is None else env


def run_root(env=None):
    e = _env(env)
    return e.get("SB_RUN_DIR") or "/tmp/swarmbox"


def state_root(env=None):
    e = _env(env)
    if e.get("SB_STATE_DIR"):
        return e["SB_STATE_DIR"]
    xdg = e.get("XDG_STATE_HOME", "")
    base = xdg if xdg.startswith("/") else os.path.join(e.get("HOME") or os.path.expanduser("~"), ".local", "state")
    return os.path.join(base.rstrip("/") or "/", "swarmbox")


def bus_socket(env=None):
    e = _env(env)
    return e.get("SB_BUS_SOCKET") or os.path.join(run_root(e), "bus.sock")


def private_dir(path):
    """Make `path` (and its missing parents) and return it, mode 0700, a real folder of this user."""
    parent = os.path.dirname(path.rstrip("/")) or "/"
    if not os.path.isdir(parent):
        os.makedirs(parent, mode=0o700, exist_ok=True)
    try:
        os.mkdir(path, 0o700)
    except FileExistsError:
        pass
    st = os.lstat(path)
    if not stat.S_ISDIR(st.st_mode):
        raise SysopPathError("%s is not a folder (a link or a file is in the way)" % path)
    if st.st_uid != os.geteuid():
        raise SysopPathError("%s belongs to another user" % path)
    if stat.S_IMODE(st.st_mode) != 0o700:
        os.chmod(path, 0o700)
    return path


class Paths:
    """The folders of one service, made on demand."""

    def __init__(self, env=None):
        self.env = _env(env)
        self.run = os.path.join(run_root(self.env), "sysop")
        self.state = os.path.join(state_root(self.env), "sysop")
        self.goals = os.path.join(self.state, "goals")
        self.socket = bus_socket(self.env)

    def make(self):
        for d in (self.run, self.state, self.goals):
            private_dir(d)
        return self

    # the files
    lock = property(lambda self: os.path.join(self.run, "serve.lock"))
    pidfile = property(lambda self: os.path.join(self.run, "serve.pid"))
    status = property(lambda self: os.path.join(self.run, "status.json"))
    stop_request = property(lambda self: os.path.join(self.run, "stop.request"))
    audit = property(lambda self: os.path.join(self.state, "events.jsonl"))
    log = property(lambda self: os.path.join(self.state, "serve.log"))

    def goal_dir(self, goal_id):
        return os.path.join(self.goals, goal_id)
