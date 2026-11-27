"""The sysop's use of the box capabilities: `swarmbox-tabs`, `swarmbox-state`, `swarmbox-worktree`, and `swarmbox-pins`
(all run as child commands with JSON output, never imported by path from host files).

  box_state(section)           -> {"schema": 2, "active", "folders": [...], "shells": [...], "parked": [...], ...}
  list_tabs()                  -> [{"tab": "t3", "label": "1:api", "index", "name", "dir", "cmd", "pane", "panes", "active"}]
  screen(tab, lines=None)      -> {"tab", "pane", "text", "cursor", "alternate", "in_mode", "mode", "size", "lines"}
  send(tab, run=T | input=T)   -> {"ok": true, "tab", "pane", "submitted"} (+ "verified" for a text submitted to an agent)
  open_tab(...) / focus_tab / rename_tab / close_tab / wake_pin / worktree

A failure is TabsError(code, msg), with the command's {"err", "msg"} or tabs_unavailable / tabs_timeout / tabs_protocol.
"""
import json
import os
import shlex
import shutil
import signal
import subprocess
import sys

READ_TIMEOUT = 20.0        # list, screen, state: hc calls have a timeout of 5 s each inside the command
SEND_TIMEOUT = 120.0       # send: the lock wait (30 s), the pauses between keys and the check that the text left the input box
MAX_OUT = 4 << 20
ENV_CMD = "SWARMBOX_SYSOP_TABS_CMD"
ENV_STATE_CMD = "SWARMBOX_SYSOP_STATE_CMD"
ENV_WORKTREE_CMD = "SWARMBOX_SYSOP_WORKTREE_CMD"
ENV_PINS_CMD = "SWARMBOX_SYSOP_PINS_CMD"

# swarmbox-state (it runs swarmbox-tabs list itself) reports what failed under its own words; the sysop's tools speak the tabs' words.
_STATE_ERR = {"unavailable": "tabs_unavailable", "protocol": "tabs_protocol", "timeout": "tabs_timeout"}
# The checkout's swarmbox-state, for a sysop run from the repository (the tests): in the box the command is on PATH.
_STATE_SIBLING = os.path.join(os.path.dirname(os.path.abspath(__file__)), *[os.pardir] * 4, "scripts", "swarmbox-state.py")


class TabsError(Exception):
    """code is the command's err word, or tabs_unavailable / tabs_timeout / tabs_protocol."""

    def __init__(self, code, msg=""):
        Exception.__init__(self, "%s: %s" % (code, msg) if msg else code)
        self.code, self.msg = code, msg


class Tabs:
    def __init__(self, cmd=None, env=None, read_timeout=READ_TIMEOUT, send_timeout=SEND_TIMEOUT):
        e = os.environ if env is None else env
        self.cmd = list(cmd) if cmd else shlex.split(e.get(ENV_CMD) or "swarmbox-tabs")
        self.env = dict(e)
        self.read_timeout, self.send_timeout = read_timeout, send_timeout

    def _run_json(self, argv, stdin=None, timeout=None, label="swarmbox-tabs", env=None):
        timeout = timeout or self.read_timeout
        try:
            # its own process group, so a timeout also ends what the command started (swarmbox-state runs swarmbox-tabs)
            p = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                 env=self.env if env is None else env, start_new_session=True)
        except OSError as e:
            raise TabsError("tabs_unavailable", "cannot run %s: %s" % (argv[0], e.strerror or e))
        try:
            stdout, stderr = p.communicate(stdin.encode("utf-8", "replace") if stdin is not None else b"", timeout=timeout)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(p.pid, signal.SIGKILL)
            except OSError:
                pass
            p.communicate()
            raise TabsError("tabs_timeout", "%s did not answer in %g s" % (label, timeout))
        out = stdout[:MAX_OUT]
        try:
            obj = json.loads(out.decode("utf-8", "replace"))
        except ValueError:
            tail = stderr.decode("utf-8", "replace").strip().splitlines()[-1:] or ["no output"]
            raise TabsError("tabs_protocol", "%s exited %d and printed no JSON (%s)" % (label, p.returncode, tail[0][:200]))
        if isinstance(obj, dict) and "err" in obj:
            raise TabsError(str(obj["err"]), str(obj.get("msg", "")))
        if p.returncode != 0:
            raise TabsError("tabs_protocol", "%s exited %d without an error object" % (label, p.returncode))
        return obj

    def call(self, args, stdin=None, timeout=None):
        """Run swarmbox-tabs; return parsed JSON or raise TabsError."""
        return self._run_json(self.cmd + list(args), stdin=stdin, timeout=timeout, label="swarmbox-tabs")

    def _state_cmd(self):
        explicit = self.env.get(ENV_STATE_CMD)
        if explicit:
            return shlex.split(explicit)
        if shutil.which("swarmbox-state", path=self.env.get("PATH")):
            return ["swarmbox-state"]
        if os.path.isfile(_STATE_SIBLING):
            return [sys.executable, "-S", _STATE_SIBLING]
        raise TabsError("tabs_unavailable", "swarmbox-state is not installed")

    def box_state(self, section="workspace"):
        """The box's world model from swarmbox-state, which reads the tabs through this client's swarmbox-tabs command."""
        sec = str(section or "workspace").strip().lower()
        env = dict(self.env, SWARMBOX_STATE_TABS_CMD=shlex.join(self.cmd))
        try:
            return self._run_json(self._state_cmd() + ["--section", sec], timeout=self.read_timeout, label="swarmbox-state", env=env)
        except TabsError as e:
            if e.code in _STATE_ERR:
                raise TabsError(_STATE_ERR[e.code], e.msg)
            raise

    def list_tabs(self):
        res = self.call(["list"])
        if not isinstance(res, list):
            raise TabsError("tabs_protocol", "list did not give a list")
        return [t for t in res if isinstance(t, dict) and isinstance(t.get("tab"), str)]

    def screen(self, tab, lines=None):
        args = ["screen", tab]
        if lines:
            args += ["--lines", str(int(lines))]
        res = self.call(args)
        if not isinstance(res, dict) or not isinstance(res.get("text"), str):
            raise TabsError("tabs_protocol", "screen did not give a screen")
        return res

    def redact(self, text):
        """The text with the secrets removed, by the one filter of the box (`swarmbox-tabs redact`, the one every screen passes)."""
        res = self.call(["redact"], stdin=text + "\n")
        if not isinstance(res, dict) or not isinstance(res.get("text"), str):
            raise TabsError("tabs_protocol", "redact did not give a text")
        return res["text"]

    def send(self, tab, run=None, input=None):
        """Type `run` and press Enter, or type `input` as it is ({Esc} {C-c} {Enter} ... are keys). A `run` is always sent with --queue."""
        if (run is None) == (input is None):
            raise TabsError("usage", "send takes run or input")
        text = run if run is not None else input
        args = ["send", tab, "--run" if run is not None else "--input", "-"] + (["--queue"] if run is not None else [])
        return self.call(args, stdin=text + "\n", timeout=self.send_timeout)

    def open_tab(self, name=None, cwd=None, agent=None, worktree=False, title=None, pin_id=None):
        args = ["open"]
        if name:
            args += ["--name", str(name)]
        if cwd:
            args += ["--cwd", str(cwd)]
        if agent:
            args += ["--agent", str(agent)]
        if title:
            args += ["--title", str(title)]
        if pin_id:
            args += ["--pin-id", str(pin_id)]
        if worktree:
            args += ["--worktree"]
        return self.call(args)

    def rename_tab(self, tab, title, source="auto"):
        return self.call(["rename", str(tab), str(title), "--source", str(source)])

    def list_pins(self):
        pcmd = shlex.split(self.env.get(ENV_PINS_CMD) or "swarmbox-pins")
        try:
            res = self._run_json(pcmd + ["list"], timeout=5.0, label="swarmbox-pins")
            return res if isinstance(res, list) else []
        except TabsError:
            return []

    def worktree(self, action, path=None, clean=False, force=False):
        wt_cmd = shlex.split(self.env.get(ENV_WORKTREE_CMD) or "swarmbox-worktree")
        args = [str(action)]
        if path is not None:
            args.append(str(path))
        if action == "merge" and clean:
            args.append("--clean")
        if action == "remove" and force:
            args.append("--force")
        return self._run_json(wt_cmd + args, timeout=self.read_timeout, label="swarmbox-worktree")

    def focus_tab(self, tab):
        return self.call(["focus", str(tab)])

    def close_tab(self, tab):
        return self.call(["close", str(tab)])
