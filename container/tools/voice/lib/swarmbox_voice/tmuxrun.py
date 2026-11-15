"""A thin, substitutable way to call tmux.

Tmux(argv=...) is the hook for tests: argv is the command prefix (default ["tmux"], or the words of the
SWARMBOX_TEST_TMUX variable, e.g. "tmux -L swarmbox-test-1234" to use a private server). `run` never raises: a missing
binary gives rc 127, a timeout rc 124. TMUX is removed from the environment so the default socket is used and a nested
client never confuses the target.
"""
import os
import shlex
import subprocess
from collections import namedtuple

Result = namedtuple("Result", "rc out err")

# Field separator of the -F formats. NOT a tab: tmux 3.6 and later prints control characters of a list as `_` when it has no terminal.
SEP = "@@sb@@"

# The panel (dock.py, panel.py) is a pane of the shared session marked with this pane option. It is never a target of a plan and its text
# is never given to a planner: context.snapshot and executor.session_panes leave marked panes out.
PANEL_OPTION = "@swarmbox_voice_panel"
PANEL_MARK = "1"
PANEL_COMMAND = "SWARMBOX_VOICE_PANEL=1"   # an argument of the panel's start command (dock.py): a second way to recognise it, for the instant before the option is set


class Tmux:
    def __init__(self, argv=None, env=None, timeout=5.0):
        if argv is None:
            argv = shlex.split(os.environ.get("SWARMBOX_TEST_TMUX", "")) or ["tmux"]
        self.argv = list(argv)
        base = dict(os.environ if env is None else env)
        base.pop("TMUX", None)
        self.env = base
        self.timeout = timeout

    def run(self, *args):
        cmd = self.argv + [str(a) for a in args]
        try:
            p = subprocess.run(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               env=self.env, timeout=self.timeout)
        except FileNotFoundError:
            return Result(127, "", "tmux not found")
        except subprocess.TimeoutExpired:
            return Result(124, "", "tmux timed out")
        except OSError as e:
            return Result(126, "", str(e))
        return Result(p.returncode, p.stdout.decode("utf-8", "replace"), p.stderr.decode("utf-8", "replace"))
