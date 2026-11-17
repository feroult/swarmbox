"""Support of the browser tests (tests/slow): headless Chromium over the DevTools protocol, a real ttyd that serves the real page, a real tmux.

One Chromium per test class (`Chromium`, started in setUpClass), one tab and one ttyd + tmux per terminal (`WebTerminal`). Nothing here waits
for a fixed time: `wait_until` polls the thing the test needs (the page has a terminal, the pane shows a text, the clipboard has a value).

Gate: everything here starts a real browser, ttyd or tmux, so the tests that use it carry `@browser_tests()`: it skips unless the programs exist and
SWARMBOX_TEST_REAL_TMUX=1 (only a container sets it: `sh dev/test-slow.sh`). The tmux server of a terminal is private (`-L <random>` and a TMUX_TMPDIR in the
test's own folder) and is stopped by that name.
"""
import atexit
import base64
import json
import os
import shutil
import signal
import socket
import struct
import subprocess
import sys
import tempfile
import unittest
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import ROOT  # noqa: E402
from waiting import wait_until  # noqa: E402

BUILD = os.path.join(ROOT, "container", "web", "build-index.sh")
WEB = os.path.join(ROOT, "container", "scripts", "swarmbox-web.sh")
DIRS_SH = os.path.join(ROOT, "container", "scripts", "dirs.sh")
BRIDGE = os.path.join(ROOT, "container", "web", "ttyd-clipboard.js")
STYLE = os.path.join(ROOT, "container", "web", "ttyd-style.css")
NEEDED = ("chromium", "ttyd", "tmux")
CHROMIUM = next((c for c in (shutil.which(n) for n in ("chromium", "chromium-browser", "google-chrome")) if c), None)
REAL = os.environ.get("SWARMBOX_TEST_REAL_TMUX") == "1"

# every message the page sends over the websocket, as text, in window.__tx
SEND_HOOK = """(() => { window.__tx = [];
  const send = WebSocket.prototype.send;
  WebSocket.prototype.send = function (d) {
    window.__tx.push(typeof d === 'string' ? d : Array.from(d).map(b => String.fromCharCode(b)).join(''));
    return send.call(this, d); }; })();"""

SCREEN = "Array.from({length: term.buffer.active.length}, (_, i) => term.buffer.active.getLine(i).translateToString(true)).join('\\n')"


def browser_tests(*programs):
    """Skip a test class unless the browser programs exist and the gate is on (see the top of this file)."""
    have = all(shutil.which(c) for c in NEEDED + tuple(programs))
    return unittest.skipUnless(REAL and have,"needs chromium, ttyd and tmux, and SWARMBOX_TEST_REAL_TMUX=1 (a container: sh dev/test-slow.sh)")


def chromium_tests():
    """The same for a test that needs only the browser (it serves its own page)."""
    return unittest.skipUnless(REAL and CHROMIUM, "needs chromium and SWARMBOX_TEST_REAL_TMUX=1 (a container: sh dev/test-slow.sh)")


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def ws_open(url):
    hostport, path = url[5:].split("/", 1)
    host, port = hostport.split(":")
    s = socket.create_connection((host, int(port)), timeout=30)
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

    def close(self):
        self.s.close()

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

    def wait_js(self, expr, seconds=10.0, step=0.05):
        """Poll a JavaScript expression until it is truthy (the value, or the last falsy one when the time is up)."""
        return wait_until(lambda: self.js(expr), seconds, step)

    # ---- input, as the browser delivers it ------------------------------------------------------
    def mouse(self, kind, x, y, button="left", modifiers=0):
        self.call("Input.dispatchMouseEvent", type=kind, x=x, y=y, button=button, clickCount=1, modifiers=modifiers,
                  buttons=0 if kind in ("mouseReleased", "mouseMoved") else (2 if button == "right" else 1))

    def ctrl_key(self, letter):
        """Ctrl+<letter> as a real key event (Ctrl+V carries the `paste` command that the browser runs unless the page prevents it)."""
        vk, code = ord(letter.upper()), "Key" + letter.upper()
        extra = {"commands": ["paste"]} if letter == "v" else {}
        self.call("Input.dispatchKeyEvent", type="rawKeyDown", key=letter, code=code, windowsVirtualKeyCode=vk, modifiers=2, **extra)
        self.call("Input.dispatchKeyEvent", type="keyUp", key=letter, code=code, windowsVirtualKeyCode=vk, modifiers=2)


def _json(url, method="GET", timeout=2):
    with urllib.request.urlopen(urllib.request.Request(url, method=method), timeout=timeout) as r:
        return json.load(r)


def kill_group(proc):
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except OSError:
        pass
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        pass


class Chromium:
    """One headless Chromium for a test class. `tab()` opens a page; the clipboard permissions are granted per origin through the browser session,
    which has to stay connected (Chromium drops what it granted when the session ends)."""

    def __init__(self, extra=()):
        self.tmp = tempfile.mkdtemp(prefix="swarmbox-test-chromium-")
        self.dbg = free_port()
        self.proc = subprocess.Popen(
            [CHROMIUM, "--headless=new", "--no-sandbox", "--disable-gpu", "--remote-debugging-port=%d" % self.dbg,
             # headless Chromium has no pointing device (pointer: none); a desktop has a mouse, and the page styles a desktop window apart (the touch
             # viewports still turn into pointer: coarse with their touch emulation)
             "--blink-settings=primaryPointerType=4,availablePointerTypes=4,primaryHoverType=2,availableHoverTypes=2",
             "--user-data-dir=" + os.path.join(self.tmp, "chrome"), *extra, "about:blank"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        version = wait_until(lambda: _json("http://127.0.0.1:%d/json/version" % self.dbg, timeout=1), 30, 0.1)
        if not version:
            self.close()
            raise RuntimeError("chromium did not start")
        self.browser = CDP(version["webSocketDebuggerUrl"])

    def tab(self):
        """(page, target id) of a new blank tab."""
        tab = _json("http://127.0.0.1:%d/json/new?about:blank" % self.dbg, method="PUT", timeout=10)
        return CDP(tab["webSocketDebuggerUrl"]), tab["id"]

    def close_tab(self, page, tid):
        page.close()
        try:
            self.browser.call("Target.closeTarget", targetId=tid)
        except (RuntimeError, OSError):
            pass

    def close(self):
        browser = getattr(self, "browser", None)
        if browser is not None:
            browser.close()
        kill_group(self.proc)
        shutil.rmtree(self.tmp, ignore_errors=True)


_STOCK = {}


def stock_page():
    """The page that ttyd itself serves (the input of build-index.sh), fetched once per process from a ttyd that runs `true`."""
    if "path" not in _STOCK:
        tmp = tempfile.mkdtemp(prefix="swarmbox-test-stock-")
        atexit.register(shutil.rmtree, tmp, True)
        port = free_port()
        ttyd = subprocess.Popen(["ttyd", "-p", str(port), "-i", "lo", "true"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                start_new_session=True)
        try:
            def fetch():
                with urllib.request.urlopen("http://127.0.0.1:%d/" % port, timeout=1) as r:
                    return r.read()
            data = wait_until(fetch, 20, 0.1)
        finally:
            kill_group(ttyd)
        assert data, "ttyd did not serve its page"
        _STOCK["path"] = os.path.join(tmp, "stock.html")
        with open(_STOCK["path"], "wb") as f:
            f.write(data)
    return _STOCK["path"]


def build_page(tmp, conf=""):
    """The real build-index.sh on ttyd's page, rendered by the real swarmbox-web with `conf` as web-terminal.conf.
    Returns (the page, the `-t key=value` options that `swarmbox-web run` would give ttyd: font, size, scrollback...)."""
    built = os.path.join(tmp, "built", "index.html")
    r = subprocess.run(["sh", BUILD, stock_page(), BRIDGE, STYLE, built], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    home, lib, run = (os.path.join(tmp, d) for d in ("home", "lib", "run"))
    os.makedirs(os.path.join(home, ".config", "swarmbox"))
    os.makedirs(lib)
    os.symlink(DIRS_SH, os.path.join(lib, "dirs.sh"))
    if conf:
        with open(os.path.join(home, ".config", "swarmbox", "web-terminal.conf"), "w") as f:
            f.write(conf)
    env = {"PATH": "/usr/bin:/bin", "HOME": home, "SWARMBOX_TEST_LIB": lib, "SWARMBOX_TEST_RUN_DIR": run, "SWARMBOX_TEST_WEB_PAGE": built}
    r = subprocess.run(["bash", WEB, "render"], env=env, capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    fake = os.path.join(tmp, "fakebin")      # a ttyd that only writes its arguments down: what swarmbox-web would run
    os.makedirs(fake)
    out = os.path.join(tmp, "ttyd.args")
    with open(os.path.join(fake, "ttyd"), "w") as f:
        f.write('#!/bin/sh\nprintf "%%s\\n" "$@" > "%s"\n' % out)
    os.chmod(os.path.join(fake, "ttyd"), 0o755)
    r = subprocess.run(["bash", WEB, "run"], env=dict(env, PATH=fake + os.pathsep + "/usr/bin:/bin", SWARMBOX_TEST_WEB_IFACE="lo"),
                       capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    with open(out) as f:
        args = f.read().splitlines()
    opts = []
    for i, a in enumerate(args):
        if a == "-t" and i + 1 < len(args) and "=" in args[i + 1]:
            opts += ["-t", args[i + 1]]
    return os.path.join(run, "index.html"), opts


class WebTerminal:
    """A real ttyd serving the real page over a real tmux whose one pane runs `command`, in a tab of `chromium`.

    conf: the text of web-terminal.conf. tmux_conf: the text of the tmux configuration. options: pass ttyd the options swarmbox-web builds (font, scrollback...).
    viewport: (width, height, touch[, device pixel ratio: 2 for a touch screen, 1 otherwise]). init_script: JavaScript that runs before the page's own. env: more environment for ttyd and tmux.
    """

    def __init__(self, chromium, conf="", tmux_conf="set -g mouse on\n", command="bash --norc", options=True, viewport=None, init_script="",
                 env=None, clipboard=True):
        self.chromium = chromium
        self.tmp = tempfile.mkdtemp(prefix="swarmbox-test-web-")
        self.sock = "swbrowser%d_%d" % (os.getpid(), free_port())
        self.env = dict(os.environ, TMUX_TMPDIR=os.path.join(self.tmp, "tmuxtmp"), **(env or {}))
        os.makedirs(self.env["TMUX_TMPDIR"])
        self.ttyd = self.page = self.tid = None
        try:
            self._start(conf, tmux_conf, command, options, viewport, init_script, clipboard)
        except BaseException:
            self.close()
            raise

    def _start(self, conf, tmux_conf, command, options, viewport, init_script, clipboard):
        index, opts = build_page(self.tmp, conf)
        conf_path = os.path.join(self.tmp, "tmux.conf")
        with open(conf_path, "w") as f:
            f.write(tmux_conf)
        port = free_port()
        self.ttyd = subprocess.Popen(
            ["ttyd", "-p", str(port), "-W", "-O", "-i", "lo", "--index", index, *(opts if options else []),
             "tmux", "-L", self.sock, "-f", conf_path, "new", "-A", "-s", "t", command],
            env=self.env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        if clipboard:
            self.chromium.browser.call("Browser.grantPermissions", origin="http://127.0.0.1:%d" % port,
                                       permissions=["clipboardReadWrite", "clipboardSanitizedWrite"])
        self.page, self.tid = self.chromium.tab()
        p = self.page
        p.call("Page.enable")
        p.call("Runtime.enable")
        p.call("Emulation.setFocusEmulationEnabled", enabled=True)
        if viewport:
            width, height, touch = viewport[:3]
            dpr = viewport[3] if len(viewport) > 3 else (2 if touch else 1)
            p.call("Emulation.setDeviceMetricsOverride", width=width, height=height, deviceScaleFactor=dpr, mobile=touch)
            if touch:
                p.call("Emulation.setTouchEmulationEnabled", enabled=True, maxTouchPoints=5)
                p.call("Emulation.setEmulatedMedia", features=[{"name": "pointer", "value": "coarse"}, {"name": "hover", "value": "none"}])
        p.call("Page.addScriptToEvaluateOnNewDocument", source=SEND_HOOK + (init_script or ""))
        p.call("Page.navigate", url="http://127.0.0.1:%d/" % port)
        assert p.wait_js("typeof term === 'object' && term.buffer.active.length > 0", 30), "the page has no terminal: ttyd or the page script failed"
        # tmux has its client and the size of the terminal is the size of the client
        assert wait_until(lambda: self.tmux("list-clients", "-F", "#{client_width}x#{client_height}").strip() ==
                          "%sx%s" % (p.js("term.cols"), p.js("term.rows")), 20, 0.05), "tmux never took the size of the terminal"
        p.js("term.focus()")

    # ---- tmux, the private server -------------------------------------------------------------
    def tmux(self, *args):
        return subprocess.run(["tmux", "-L", self.sock, *args], capture_output=True, text=True, env=self.env).stdout

    def pane_text(self):
        return "".join(self.tmux("capture-pane", "-p", "-J", "-t", "t:").split("\n")).strip()

    # ---- the page ------------------------------------------------------------------------------
    def screen(self):
        return self.page.js(SCREEN)

    def wait_screen(self, text, seconds=15.0):
        return wait_until(lambda: text in self.screen(), seconds, 0.05)

    def wait_line(self, text, seconds=15.0):
        """Wait until a line of the screen is exactly `text` (the output of a command, not the command that printed it)."""
        return self.page.wait_js("Array.from({length: term.buffer.active.length}, (_, i) => term.buffer.active.getLine(i).translateToString(true).trim()).includes(%s)"
                                 % json.dumps(text), seconds)

    def type(self, text):
        """Type as xterm.js does: the text goes over the websocket to ttyd and the pty."""
        self.page.js("term.input(%s, true)" % json.dumps(text))

    def sent(self):
        return "".join(self.page.js("window.__tx.slice()"))

    def clear_sent(self):
        self.page.js("window.__tx.length = 0")

    def clipboard(self):
        return self.page.js("navigator.clipboard.readText()", wait=True)

    def set_clipboard(self, text):
        self.page.js("navigator.clipboard.writeText(%s)" % json.dumps(text), wait=True)

    def close(self):
        if self.page is not None:
            self.chromium.close_tab(self.page, self.tid)
        subprocess.run(["tmux", "-L", self.sock, "kill-server"], capture_output=True, env=self.env)
        if self.ttyd is not None:
            kill_group(self.ttyd)
        shutil.rmtree(self.tmp, ignore_errors=True)


class BrowserCase(unittest.TestCase):
    """A test case with its own folder, a `spawn` that ends every process it started, and the kill of the private tmux server named self.sock.
    The simple base of a test that builds its own browser set-up (tests/slow/test_sysop_web.py); the others use Chromium and WebTerminal above."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.procs = []
        self.addCleanup(self.cleanup)

    def cleanup(self):
        for conn in (getattr(self, "page", None), getattr(self, "browser", None)):
            if conn is not None:
                conn.s.close()
        for p in self.procs:
            kill_group(p)
        if getattr(self, "sock", None):
            # the server was started with the TMUX_TMPDIR of self.env: without it this names another (empty) socket folder and the server leaks
            subprocess.run(["tmux", "-L", self.sock, "kill-server"], capture_output=True, env=getattr(self, "env", None))
        shutil.rmtree(self.tmp, ignore_errors=True)

    def spawn(self, argv, **kw):
        p = subprocess.Popen(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True, **kw)
        self.procs.append(p)
        return p
