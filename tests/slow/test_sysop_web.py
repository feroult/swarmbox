#!/usr/bin/env python3
"""The sysop panel and its keys through the WEB TERMINAL: a real ttyd attached to a real tmux (the box's tmux.conf), driven in headless Chromium over the
DevTools protocol, so keys and mouse arrive the way a browser sends them (xterm.js -> websocket -> ttyd -> pty -> tmux). The same claims as class NoFocus
of test_sysop_dock.py (a pty client): keys typed in the tab while a goal arrives never reach the panel, Ctrl+A then V / X / a / g work, a click on the
panel focuses it and then its own keys work, and the approval gesture allows in ONE step (no typed word, no focus). The panel is the real program; the service is the files of
ss.FakeService.

Podman only (like the real tmux tests): it skips unless chromium, ttyd and tmux exist AND SWARMBOX_TEST_REAL_TMUX=1 is set.

  podman run --rm -e SWARMBOX_TEST_REAL_TMUX=1 --userns=keep-id:uid=1000,gid=1000 -v $PWD:/src:ro --tmpfs /work:rw,exec,mode=1777,size=2g IMAGE \\
      bash -c 'cp -r /src /work/repo && cd /work/repo && HOME=/work/home python3 tests/slow/test_sysop_web.py'
"""
import json
import os
import subprocess
import sys
import time
import unittest
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "support"))
import sysop_support as ss  # noqa: E402
import browser_support as bs  # noqa: E402
from helpers import ROOT  # noqa: E402

from swarmbox_sysop import dock, paths  # noqa: E402

TMUX_CONF = os.path.join(ROOT, "container", "config", "tmux.conf")
LAUNCHER = '#!/bin/sh\nexec "%s" -B -m swarmbox_sysop "$@"\n' % sys.executable


@bs.browser_tests()
class WebKeys(bs.BrowserCase):
    def setUp(self):
        super().setUp()
        t = self.tmp
        self.bin = os.path.join(t, "bin")
        os.mkdir(self.bin)
        with open(os.path.join(self.bin, "swarmbox-sysop"), "w") as f:
            f.write(LAUNCHER)
        os.chmod(os.path.join(self.bin, "swarmbox-sysop"), 0o755)
        self.env = {"PATH": self.bin + os.pathsep + os.environ.get("PATH", "/usr/bin:/bin"), "HOME": t, "TMUX_TMPDIR": t, "TERM": "xterm-256color",
                    "PYTHONPATH": ss.LIB, "TMPDIR": t, "SB_RUN_DIR": os.path.join(t, "run"), "SB_STATE_DIR": os.path.join(t, "state"), "LANG": "C.UTF-8"}
        saved = dict(os.environ)
        self.addCleanup(lambda: (os.environ.clear(), os.environ.update(saved)))
        os.environ.update(self.env)
        os.environ.pop("TMUX", None)
        os.environ.pop("SB_TABS_SOCKET", None)
        self.pth = paths.Paths(self.env)
        self.svc = ss.FakeService(self.pth)
        self.addCleanup(self.svc.close)
        self.sock = "sbweb%d_%d" % (os.getpid() % 100000, bs.free_port())
        self.tm = dock.Tmux(argv=["tmux", "-L", self.sock], env=self.env)
        r = subprocess.run(["tmux", "-L", self.sock, "-f", TMUX_CONF, "new-session", "-d", "-s", "main", "-x", "160", "-y", "50", "cat -v"], env=self.env,
                           capture_output=True, text=True, timeout=20)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.user = self.tm.run("list-panes", "-t", "=main", "-F", "#{pane_id}").out.split()[0]
        self.open_page()
        self.follower = dock.Follower(self.pth, dock=dock.default_dock(self.tm), grace=3.0)

    def open_page(self):
        port = bs.free_port()
        self.spawn(["ttyd", "-p", str(port), "-W", "-i", "lo", "tmux", "-L", self.sock, "attach", "-t", "main"], env=self.env)
        dbg = bs.free_port()
        self.spawn(["chromium", "--headless=new", "--no-sandbox", "--disable-gpu", "--remote-debugging-port=%d" % dbg, "--window-size=1100,800",
                    "--user-data-dir=" + os.path.join(self.tmp, "chrome"), "about:blank"])
        version = None
        for _ in range(80):
            try:
                with urllib.request.urlopen("http://127.0.0.1:%d/json/version" % dbg, timeout=1) as r:
                    version = json.load(r)
                break
            except OSError:
                time.sleep(0.25)
        self.assertIsNotNone(version, "chromium did not start")
        self.browser = bs.CDP(version["webSocketDebuggerUrl"])
        req = urllib.request.Request("http://127.0.0.1:%d/json/new?about:blank" % dbg, method="PUT")
        with urllib.request.urlopen(req, timeout=10) as r:
            tab = json.load(r)
        self.page = bs.CDP(tab["webSocketDebuggerUrl"])
        self.page.call("Page.enable")
        self.page.call("Runtime.enable")
        self.page.call("Emulation.setFocusEmulationEnabled", enabled=True)
        self.page.call("Page.navigate", url="http://127.0.0.1:%d/" % port)
        for _ in range(60):
            time.sleep(0.25)
            if self.page.js("typeof term === 'object' && term.buffer.active.length > 0"):
                break
        time.sleep(1.0)
        self.page.js("term.focus()")

    # ---- helpers ------------------------------------------------------------------------------------------------------------------------
    def tmux(self, *a):
        return self.tm.run(*a).out

    def panels(self):
        out = []
        for line in self.tmux("list-panes", "-s", "-t", "=main", "-F", "#{pane_id} #{pane_left} #{pane_top} #{pane_width} #{pane_height} #{pane_active} #{@swarmbox_sysop_panel}").splitlines():
            p = line.split(" ")
            if p[6] == "1":
                out.append({"id": p[0], "left": int(p[1]), "top": int(p[2]), "w": int(p[3]), "h": int(p[4]), "active": p[5] == "1"})
        return out

    def active(self):
        return self.tmux("display-message", "-p", "-t", "=main:", "#{pane_id}").strip()

    def screen(self, pane):
        return self.tmux("capture-pane", "-p", "-t", pane)

    def user_text(self):
        return self.tmux("capture-pane", "-p", "-J", "-S", "-", "-t", self.user)

    def wait(self, fn, what, timeout=8.0):
        end = time.time() + timeout
        while time.time() < end:
            v = fn()
            if v:
                return v
            time.sleep(0.1)
        self.fail("timed out waiting for " + what)

    def send(self, text):
        self.page.js("term.input(%s, true)" % json.dumps(text))

    def real_key(self, ch):
        """one key as the browser sends it: key events, not term.input"""
        if ch == "\r":
            kw = dict(key="Enter", code="Enter", windowsVirtualKeyCode=13, text="\r")
        else:
            kw = dict(key=ch, code="Key" + ch.upper(), windowsVirtualKeyCode=ord(ch.upper()), text=ch)
        self.page.call("Input.dispatchKeyEvent", type="keyDown", **kw)
        self.page.call("Input.dispatchKeyEvent", type="keyUp", key=kw["key"], code=kw["code"], windowsVirtualKeyCode=kw["windowsVirtualKeyCode"])
        time.sleep(0.05)

    def click_cell(self, col, row):
        """a real mouse click on a cell (0-based) of the terminal"""
        r = self.page.js("(() => { const e = document.querySelector('.xterm-screen').getBoundingClientRect();"
                         " return [e.x, e.y, e.width / term.cols, e.height / term.rows]; })()")
        x, y = r[0] + (col + 0.5) * r[2], r[1] + (row + 0.5) * r[3]
        common = dict(x=x, y=y, button="left", clickCount=1)
        self.page.call("Input.dispatchMouseEvent", type="mouseMoved", x=x, y=y)
        self.page.call("Input.dispatchMouseEvent", type="mousePressed", buttons=1, **common)
        self.page.call("Input.dispatchMouseEvent", type="mouseReleased", buttons=0, **common)

    def open_panel(self, **pending):
        self.svc.goal()
        if pending:
            self.svc.pending(**pending)
        self.follower.step()
        return self.wait(self.panels, "the panel")[0]

    # ---- the tests ----------------------------------------------------------------------------------------------------------------------
    def test_keys_typed_in_the_browser_while_a_goal_arrives_never_reach_the_panel(self):
        sent = 0
        for i in range(30):
            self.send("xcgxqrXG")
            sent += 1
            if i == 6:
                self.svc.goal()
                self.svc.pending(mode="approve", risk="high", text="rm -rf ~/x")
                self.follower.step()
            time.sleep(0.08)
        panel, = self.wait(self.panels, "the panel")
        time.sleep(0.6)
        self.assertFalse(self.panels()[0]["active"], "the panel did not take the focus")
        self.assertEqual(self.active(), self.user)
        self.assertEqual(self.user_text().count("x"), 2 * sent, "every key reached the tab")
        self.assertFalse(os.path.exists(self.pth.stop_request))
        self.assertIsNone(self.svc.decision())
        self.assertIn("allow?", self.screen(panel["id"]))

    def test_the_sysop_keys_work_from_the_browser(self):
        self.open_panel(mode="veto")
        self.send("\x01")                                    # the prefix, then the key as a key event
        time.sleep(0.3)
        self.real_key("V")
        d = self.wait(self.svc.decision, "the veto")
        self.assertEqual((d["decision"], d["by"]), ("veto", "key"))
        self.send("\x01")
        time.sleep(0.3)
        self.real_key("X")
        self.wait(lambda: os.path.exists(self.pth.stop_request), "the stop request")
        self.assertEqual(self.active(), self.user)

    def test_a_mouse_click_on_the_panel_focuses_it_and_its_keys_work(self):
        panel = self.open_panel(mode="veto")
        time.sleep(0.8)
        self.real_key("x")                                    # unfocused: the tab gets it
        time.sleep(0.4)
        self.assertFalse(os.path.exists(self.pth.stop_request))
        self.click_cell(panel["left"] + 3, panel["top"] + 1)     # the head row of the panel
        self.wait(lambda: self.active() == panel["id"], "the click to focus the panel")
        time.sleep(0.8)
        self.real_key("x")
        self.wait(lambda: os.path.exists(self.pth.stop_request), "x in the panel to stop the goal")

    def test_the_approval_gesture_allows_in_one_step_from_the_browser(self):
        panel = self.open_panel(mode="approve", risk="high", text="rm -rf ~/x")
        time.sleep(0.8)
        for ch in "run\r":                                    # before the gesture: for the tab, they allow nothing
            self.real_key(ch)
        time.sleep(0.5)
        self.assertIsNone(self.svc.decision())
        self.assertEqual(self.active(), self.user)
        self.send("\x01")
        time.sleep(0.3)                                       # a key event right behind term.input is sometimes dropped by xterm.js (seen 3 of 4)
        self.real_key("a")
        d = self.wait(self.svc.decision, "the decision")
        self.assertEqual((d["decision"], d["by"], d["word"]), ("approve", "key", "run"), "one gesture, no typed word")
        self.assertEqual(self.active(), self.user, "the gesture did not take the focus")
        self.assertFalse(self.panels()[0]["active"])

    def test_a_click_on_the_allow_button_of_the_panel_allows(self):
        panel = self.open_panel(mode="approve", risk="high", text="rm -rf ~/x")
        time.sleep(0.8)

        def button(label):
            for r, line in enumerate(self.screen(panel["id"]).splitlines()):
                if " %s " % label in line:                        # a filled block of colour: " Allow "
                    return panel["left"] + line.index(" %s " % label) + 2, panel["top"] + r
            return None
        pos = self.wait(lambda: button("Allow"), "the Allow button")
        self.click_cell(*pos)                                 # the first click gives the panel the focus: it is not a click on the button
        self.wait(lambda: self.active() == panel["id"], "the click to focus the panel")
        time.sleep(0.8)
        self.assertIsNone(self.svc.decision())
        self.click_cell(*pos)
        d = self.wait(self.svc.decision, "the decision")
        self.assertEqual((d["decision"], d["by"], d["word"]), ("approve", "panel", "run"))

if __name__ == "__main__":
    unittest.main()
