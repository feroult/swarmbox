"""The sysop's use of the tabs of the box: it runs the command `swarmbox-tabs` (a capability of the host, never a bus topic) and parses its JSON.

  list_tabs()                  -> [{"tab": "@3", "label": "1:api", "index", "name", "dir", "cmd", "pane", "panes", "active"}]
  screen(tab, lines=None)      -> {"tab", "pane", "text", "cursor", "alternate", "in_mode", "mode", "size", "lines"}
  send(tab, run=T | input=T)   -> {"ok": true, "tab", "pane", "submitted"}

A failure is TabsError(code, msg), with the words of the command ({"err", "msg"} on its stdout: dialog_open, busy_tab, slash_refused, no_such_tab,
ambiguous_tab, not_submitted, backend_error, unsupported, lock_error, no_backend, no_session, timeout, bad_body, usage) or one of these of this file:
tabs_unavailable (the command cannot be started: nothing was typed), tabs_timeout (it did not answer in time: it may have typed part of the text),
tabs_protocol (it printed something that is not its JSON).

Command or library.  container/scripts/swarmbox-tabs.py can be run, or imported by path. This runs it, as its docstring recommends:
  * the command is the contract: its JSON, its exit codes, its lock per tab and its timeouts are the same for every caller, and nothing here
    imports a file of the host (a rename or a move of it cannot break the import of the sysop);
  * a failure stays in a child: the MCP server of a goal is a long-lived process that holds the policy's state, and a bug or a hang in herdr-core
    code must not take it down (a hung call is killed at the timeout and becomes an error the model can read);
  * the cost is one Python start (15 to 25 ms) per call. The settled-screen polling reads every 0.1 s, so a poll costs a fifth of its period;
    that is cheaper than the 0.5 s of quiet it waits for. Sending text puts the text on stdin (`--run -`, `--input -`), never in the command line:
    no limit of size, no NUL or leading dash to quote, and nothing in `ps`.
The command is found as `swarmbox-tabs` on PATH, or as the command in SWARMBOX_SYSOP_TABS_CMD (a program path, a test's stand-in).
The settled-screen polling (reading until the screen did not change) stays in the sysop (mcpserver.py): the command has no notion of "settled".
"""
import json
import os
import shlex
import subprocess

READ_TIMEOUT = 20.0        # list, screen: hc calls have a timeout of 5 s each inside the command
SEND_TIMEOUT = 120.0       # send: the lock wait (30 s), the pauses between keys and the check that the text left the input box
MAX_OUT = 4 << 20
ENV_CMD = "SWARMBOX_SYSOP_TABS_CMD"
ENV_WORKTREE_CMD = "SWARMBOX_SYSOP_WORKTREE_CMD"


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

    def call(self, args, stdin=None, timeout=None):
        """Run the command; the object it printed. TabsError for {"err"} (whatever the exit code) and for everything that is not its answer."""
        try:
            p = subprocess.run(self.cmd + list(args), input=(stdin.encode("utf-8", "replace") if stdin is not None else b""), env=self.env,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout or self.read_timeout)
        except subprocess.TimeoutExpired:
            raise TabsError("tabs_timeout", "swarmbox-tabs did not answer in %g s" % (timeout or self.read_timeout))
        except OSError as e:
            raise TabsError("tabs_unavailable", "cannot run %s: %s" % (self.cmd[0], e.strerror or e))
        out = p.stdout[:MAX_OUT]
        try:
            obj = json.loads(out.decode("utf-8", "replace"))
        except ValueError:
            tail = p.stderr.decode("utf-8", "replace").strip().splitlines()[-1:] or ["no output"]
            raise TabsError("tabs_protocol", "swarmbox-tabs exited %d and printed no JSON (%s)" % (p.returncode, tail[0][:200]))
        if isinstance(obj, dict) and "err" in obj:
            raise TabsError(str(obj["err"]), str(obj.get("msg", "")))
        if p.returncode != 0:
            raise TabsError("tabs_protocol", "swarmbox-tabs exited %d without an error object" % p.returncode)
        return obj

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

    def send(self, tab, run=None, input=None):
        """Type `run` and press Enter, or type `input` as it is ({Esc} {C-c} {Enter} ... are keys). A `run` is always sent with --queue: an agent that is busy
        queues what is typed (the user's message waits its turn), so a busy agent is no reason to refuse; a dialog still is (dialog_open). Never --slash: a text that
        starts with / or ! is refused (slash_refused). `input` (keys) is never queued."""
        if (run is None) == (input is None):
            raise TabsError("usage", "send takes run or input")
        text = run if run is not None else input
        # the command drops ONE trailing newline of stdin: add one so the text is typed as it is
        args = ["send", tab, "--run" if run is not None else "--input", "-"] + (["--queue"] if run is not None else [])
        return self.call(args, stdin=text + "\n", timeout=self.send_timeout)

    def open_tab(self, name=None, cwd=None, agent=None, worktree=False):
        args = ["open"]
        if name:
            args += ["--name", str(name)]
        if cwd:
            args += ["--cwd", str(cwd)]
        if agent:
            args += ["--agent", str(agent)]
        if worktree:
            args += ["--worktree"]
        return self.call(args)

    def rename_tab(self, tab, title, source="auto"):
        return self.call(["rename", str(tab), str(title), "--source", str(source)])

    def worktree(self, action, path, clean=False, force=False):
        wt_cmd = shlex.split(self.env.get(ENV_WORKTREE_CMD) or "swarmbox-worktree")
        args = [str(action), str(path)]
        if action == "merge" and clean:
            args.append("--clean")
        if action == "remove" and force:
            args.append("--force")
        try:
            p = subprocess.run(wt_cmd + args, input=b"", env=self.env,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=self.read_timeout)
        except subprocess.TimeoutExpired:
            raise TabsError("tabs_timeout", "swarmbox-worktree did not answer in %g s" % self.read_timeout)
        except OSError as e:
            raise TabsError("tabs_unavailable", "cannot run %s: %s" % (wt_cmd[0], e.strerror or e))
        out = p.stdout[:MAX_OUT]
        try:
            obj = json.loads(out.decode("utf-8", "replace"))
        except ValueError:
            tail = p.stderr.decode("utf-8", "replace").strip().splitlines()[-1:] or ["no output"]
            raise TabsError("tabs_protocol", "swarmbox-worktree exited %d (%s)" % (p.returncode, tail[0][:200]))
        if isinstance(obj, dict) and "err" in obj:
            raise TabsError(str(obj["err"]), str(obj.get("msg", "")))
        if p.returncode != 0:
            raise TabsError("tabs_protocol", "swarmbox-worktree exited %d without an error object" % p.returncode)
        return obj

    def focus_tab(self, tab):
        return self.call(["focus", str(tab)])

    def close_tab(self, tab):
        return self.call(["close", str(tab)])
