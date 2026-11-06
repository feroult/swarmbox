#!/usr/bin/env python3
"""End-to-end tests for the browser bridge (container/ttyd-clipboard.js: clipboard, right click) in a real browser.

Run:  python3 tests/test_clipboard_bridge.py        (needs chromium, ttyd and tmux; skipped otherwise)

The page is built by the real container/scripts/web-terminal.sh (a fake ttyd only records the --index it
was given), then served by a REAL ttyd running a real tmux, and driven in headless Chromium over the
DevTools protocol. Selections are made with the SGR mouse sequences xterm.js sends, the keys with real
key events, and the clipboard is read back with navigator.clipboard.
"""
import base64
import json
import os
import shutil
import signal
import socket
import stat
import struct
import subprocess
import tempfile
import time
import unittest
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
SCRIPT = os.path.join(ROOT, "container", "scripts", "web-terminal.sh")
BRIDGE = os.path.join(ROOT, "container", "ttyd-clipboard.js")
STYLE = os.path.join(ROOT, "container", "ttyd-style.css")
NEEDED = ("chromium", "ttyd", "tmux")

HOOK = """(() => { window.__tx = [];
  const send = WebSocket.prototype.send;
  WebSocket.prototype.send = function (d) {
    window.__tx.push(typeof d === 'string' ? d : Array.from(d).map(b => String.fromCharCode(b)).join(''));
    return send.call(this, d); }; })();"""


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def ws_open(url):
    hostport, path = url[5:].split("/", 1)
    host, port = hostport.split(":")
    s = socket.create_connection((host, int(port)), timeout=15)
    key = base64.b64encode(os.urandom(16)).decode()
    s.sendall(("GET /%s HTTP/1.1\r\nHost: %s\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
               "Sec-WebSocket-Key: %s\r\nSec-WebSocket-Version: 13\r\n\r\n" % (path, hostport, key)).encode())
    buf = b""
    while b"\r\n\r\n" not in buf:
        buf += s.recv(4096)
    return s, buf.split(b"\r\n\r\n", 1)[1]


class CDP:
    """Just enough of the Chrome DevTools protocol over a websocket."""

    def __init__(self, url):
        self.s, self.buf = ws_open(url)
        self.n = 0

    def _send(self, obj):
        p = json.dumps(obj).encode()
        m = os.urandom(4)
        n = len(p)
        head = bytes([0x81]) + (bytes([0x80 | n]) if n < 126 else
                                bytes([0xFE]) + struct.pack(">H", n) if n < 65536 else
                                bytes([0xFF]) + struct.pack(">Q", n))
        self.s.sendall(head + m + bytes(b ^ m[i % 4] for i, b in enumerate(p)))

    def _recv(self):
        def need(k):
            while len(self.buf) < k:
                self.buf += self.s.recv(65536)
        need(2)
        ln, i = self.buf[1] & 0x7F, 2
        if ln == 126:
            need(4)
            ln, i = struct.unpack(">H", self.buf[2:4])[0], 4
        elif ln == 127:
            need(10)
            ln, i = struct.unpack(">Q", self.buf[2:10])[0], 10
        need(i + ln)
        data, self.buf = self.buf[i:i + ln], self.buf[i + ln:]
        return json.loads(data.decode())

    def call(self, method, **params):
        self.n += 1
        mid = self.n
        self._send({"id": mid, "method": method, "params": params})
        while True:
            r = self._recv()
            if r.get("id") == mid:
                if "error" in r:
                    raise RuntimeError("%s: %s" % (method, r["error"]))
                return r.get("result", {})

    def js(self, expr, wait=False):
        r = self.call("Runtime.evaluate", expression=expr, returnByValue=True, awaitPromise=wait)
        if "exceptionDetails" in r:
            raise RuntimeError(r["exceptionDetails"].get("exception", {}).get("description", "js error"))
        return r.get("result", {}).get("value")


@unittest.skipUnless(all(shutil.which(c) for c in NEEDED), "needs chromium, ttyd and tmux")
class ClipboardBridge(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.procs = []
        self.addCleanup(self.cleanup)

    def cleanup(self):
        for conn in (getattr(self, "page", None), getattr(self, "browser", None)):
            if conn is not None:
                conn.s.close()
        for p in self.procs:
            try:
                os.killpg(p.pid, signal.SIGKILL)
            except OSError:
                pass
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
        subprocess.run(["tmux", "-L", self.sock, "kill-server"], capture_output=True)
        shutil.rmtree(self.tmp, ignore_errors=True)

    # ---- building blocks -----------------------------------------------------------------------
    def spawn(self, argv, **kw):
        p = subprocess.Popen(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True, **kw)
        self.procs.append(p)
        return p

    def build_index(self, conf=""):
        """Run the real web-terminal.sh against ttyd's own page and return the page it builds."""
        port = free_port()
        stock = os.path.join(self.tmp, "stock.html")
        ttyd = self.spawn(["ttyd", "-p", str(port), "-i", "lo", "true"])
        for _ in range(40):
            try:
                with urllib.request.urlopen("http://127.0.0.1:%d/" % port, timeout=1) as r, open(stock, "wb") as f:
                    f.write(r.read())
                break
            except OSError:
                time.sleep(0.2)
        os.killpg(ttyd.pid, signal.SIGKILL)
        ttyd.wait(timeout=5)
        home = os.path.join(self.tmp, "home")
        os.makedirs(os.path.join(home, ".swarmbox"), exist_ok=True)
        if conf:
            with open(os.path.join(home, ".swarmbox", "web-terminal.conf"), "w") as f:
                f.write(conf)
        shim_dir = os.path.join(self.tmp, "shim")
        os.makedirs(shim_dir, exist_ok=True)
        shim = os.path.join(shim_dir, "ttyd")
        with open(shim, "w") as f:
            f.write('#!/bin/sh\nfor a in "$@"; do printf "%s\\n" "$a"; done > "$OUT"\nsleep 1\n')
        os.chmod(shim, os.stat(shim).st_mode | stat.S_IXUSR)
        out = os.path.join(self.tmp, "args.txt")
        env = {"HOME": home, "PATH": shim_dir + os.pathsep + os.environ["PATH"], "OUT": out, "SWARMBOX_WEB": "1",
               "SWARMBOX_WEB_PORT": str(free_port()), "SWARMBOX_TTYD_STOCK": stock, "SWARMBOX_TTYD_BRIDGE": BRIDGE,
               "SWARMBOX_TTYD_STYLE": STYLE}
        subprocess.run(["bash", SCRIPT], env=env, check=True, timeout=20)
        for _ in range(40):
            if os.path.exists(out):
                break
            time.sleep(0.1)
        time.sleep(0.2)
        with open(out) as f:
            args = f.read().splitlines()
        return args[args.index("--index") + 1]

    def open_terminal(self, conf=""):
        index = self.build_index(conf)
        self.sock = "clipb%d_%d" % (os.getpid(), free_port())
        tmux_conf = os.path.join(self.tmp, "tmux.conf")
        with open(tmux_conf, "w") as f:
            f.write("set -g mouse on\n")
        port = free_port()
        self.spawn(["ttyd", "-p", str(port), "-W", "-O", "-i", "lo", "--index", index,
                    "tmux", "-L", self.sock, "-f", tmux_conf, "new", "-A", "-s", "t", "bash --norc"])
        dbg = free_port()
        self.spawn(["chromium", "--headless=new", "--no-sandbox", "--disable-gpu", "--remote-debugging-port=%d" % dbg,
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
        # keep this session open: Chromium drops the permissions it granted when the session disconnects
        self.browser = CDP(version["webSocketDebuggerUrl"])
        self.browser.call("Browser.grantPermissions", origin="http://127.0.0.1:%d" % port,
                     permissions=["clipboardReadWrite", "clipboardSanitizedWrite"])
        req = urllib.request.Request("http://127.0.0.1:%d/json/new?about:blank" % dbg, method="PUT")
        with urllib.request.urlopen(req, timeout=10) as r:
            tab = json.load(r)
        self.page = CDP(tab["webSocketDebuggerUrl"])
        self.page.call("Page.enable")
        self.page.call("Runtime.enable")
        self.page.call("Emulation.setFocusEmulationEnabled", enabled=True)
        self.page.call("Page.addScriptToEvaluateOnNewDocument", source=HOOK)
        self.page.call("Page.navigate", url="http://127.0.0.1:%d/" % port)
        for _ in range(60):
            time.sleep(0.25)
            if self.page.js("typeof term === 'object' && term.buffer.active.length > 0"):
                break
        time.sleep(1.0)
        self.page.js("term.focus()")
        self.type("echo SELECT-ME-PLEASE\r")
        time.sleep(0.6)

    def type(self, text):
        self.page.js("term.input(%s, true)" % json.dumps(text))
        time.sleep(0.35)

    def clipboard(self):
        return self.page.js("navigator.clipboard.readText()", wait=True)

    def set_clipboard(self, text):
        self.page.js("navigator.clipboard.writeText(%s)" % json.dumps(text), wait=True)

    def sent(self):
        return "".join(self.page.js("window.__tx.slice()"))

    def clear_sent(self):
        self.page.js("window.__tx.length = 0")

    def ctrl(self, letter):
        vk, code = ord(letter.upper()), "Key" + letter.upper()
        extra = {"commands": ["paste"]} if letter == "v" else {}  # what the browser does for Ctrl+V if not prevented
        self.page.call("Input.dispatchKeyEvent", type="rawKeyDown", key=letter, code=code,
                       windowsVirtualKeyCode=vk, modifiers=2, **extra)
        self.page.call("Input.dispatchKeyEvent", type="keyUp", key=letter, code=code, windowsVirtualKeyCode=vk, modifiers=2)
        time.sleep(0.6)

    # ---- copying out of tmux -------------------------------------------------------------------
    def test_a_mouse_selection_in_tmux_reaches_the_browser_clipboard(self):
        self.open_terminal()
        self.set_clipboard("BEFORE")
        for seq in ("\x1b[<0;1;2M", "\x1b[<32;8;2M", "\x1b[<32;16;2M", "\x1b[<0;16;2m"):  # press, drag, release
            self.type(seq)
        time.sleep(1.2)
        self.assertIn("SELECT-ME", self.clipboard())
        buf = subprocess.run(["tmux", "-L", self.sock, "show-buffer"], capture_output=True, text=True).stdout
        self.assertIn("SELECT-ME", buf, "tmux itself did copy")

    def test_set_buffer_with_w_also_reaches_the_clipboard(self):
        self.open_terminal()
        self.set_clipboard("BEFORE")
        subprocess.run(["tmux", "-L", self.sock, "set-buffer", "-w", "from-tmux-é-ç"], check=True)
        time.sleep(1.0)
        self.assertEqual(self.clipboard(), "from-tmux-é-ç")

    def test_an_osc52_read_request_is_never_answered(self):
        self.open_terminal()
        self.set_clipboard("SECRET-FROM-ELSEWHERE")
        self.clear_sent()
        self.page.js("term.write('\\x1b]52;c;?\\x07')")
        time.sleep(0.6)
        self.assertNotIn("52", self.sent(), "nothing may be sent back")
        self.assertNotIn("SECRET", self.sent())
        self.assertEqual(self.clipboard(), "SECRET-FROM-ELSEWHERE", "and a read request must not change it")

    # ---- Ctrl+V / Ctrl+C -----------------------------------------------------------------------
    def test_ctrl_v_pastes_instead_of_sending_a_control_character(self):
        self.open_terminal()
        self.set_clipboard("PASTE-ME-42")
        self.clear_sent()
        self.ctrl("v")
        self.assertIn("PASTE-ME-42", self.sent())
        self.assertNotIn("\x16", self.sent())

    def test_ctrl_c_copies_a_selection_without_interrupting(self):
        self.open_terminal()
        self.set_clipboard("BEFORE")
        self.page.js("term.select(0, 0, 8)")
        self.clear_sent()
        self.ctrl("c")
        self.assertEqual(self.clipboard(), "bash-5.2")
        self.assertNotIn("\x03", self.sent(), "a copy must not also send ^C")

    def test_ctrl_c_without_a_selection_is_still_an_interrupt(self):
        self.open_terminal()
        self.page.js("term.clearSelection()")
        self.clear_sent()
        self.ctrl("c")
        self.assertIn("\x03", self.sent())

    # ---- right click -----------------------------------------------------------------------------
    def right_click(self, shift=False):
        """Right click in the middle of the terminal; return what the page saw: was the browser menu prevented?"""
        self.page.js("window.__ctx = []; window.addEventListener('contextmenu', e => window.__ctx.push(e.defaultPrevented));")
        rect = self.page.js("(() => { const r = term.element.getBoundingClientRect(); return [r.x + r.width / 2, r.y + r.height / 2]; })()")
        self.clear_sent()
        common = dict(x=rect[0], y=rect[1], button="right", clickCount=1, modifiers=8 if shift else 0)
        self.page.call("Input.dispatchMouseEvent", type="mousePressed", buttons=2, **common)
        self.page.call("Input.dispatchMouseEvent", type="mouseReleased", buttons=0, **common)
        time.sleep(0.6)
        return self.page.js("window.__ctx.slice()")

    def test_right_click_opens_only_tmuxs_menu_while_tmux_captures_the_mouse(self):
        self.open_terminal()
        self.assertNotEqual(self.page.js("term.modes.mouseTrackingMode"), "none", "tmux mouse mode is on")
        prevented = self.right_click()
        self.assertEqual(prevented, [True], "the browser's menu must be suppressed")
        self.assertIn("\x1b[<2;", self.sent(), "and the right click still reaches tmux")

    def test_shift_right_click_still_opens_the_browsers_menu(self):
        self.open_terminal()
        self.assertEqual(self.right_click(shift=True), [False])

    def test_right_click_keeps_the_browsers_menu_when_nothing_captures_the_mouse(self):
        self.open_terminal()
        subprocess.run(["tmux", "-L", self.sock, "set", "-g", "mouse", "off"], check=True)
        for _ in range(20):
            if self.page.js("term.modes.mouseTrackingMode") == "none":
                break
            time.sleep(0.2)
        self.assertEqual(self.page.js("term.modes.mouseTrackingMode"), "none")
        self.assertEqual(self.right_click(), [False], "a plain shell keeps the browser menu (copy/paste)")

    # ---- the opt-outs --------------------------------------------------------------------------
    def test_ctrl_v_can_be_left_as_a_control_character(self):
        self.open_terminal(conf="ctrlVPaste=false\n")
        self.set_clipboard("PASTE-ME-42")
        self.clear_sent()
        self.ctrl("v")
        self.assertIn("\x16", self.sent())
        self.assertNotIn("PASTE-ME-42", self.sent())

    def test_ctrl_c_can_always_interrupt(self):
        self.open_terminal(conf="ctrlCCopy=false\n")
        self.set_clipboard("BEFORE")
        self.page.js("term.select(0, 0, 8)")
        self.clear_sent()
        self.ctrl("c")
        self.assertIn("\x03", self.sent())


if __name__ == "__main__":
    unittest.main(verbosity=2)
