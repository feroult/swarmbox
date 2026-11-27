"""Tests for the browser-open bridge: swarmbox-open, server.mjs /api/open-url, and cockpit.mjs OSC 52/8.

Run: python3 -W error tests/fast/test_open_url.py
"""
import base64
import glob
import http.server
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "support"))
from helpers import ROOT  # noqa: E402

OPEN_SCRIPT = os.path.join(ROOT, "container", "scripts", "swarmbox-open.py")
WEB_DIR = os.path.join(ROOT, "container", "web", "herdr")
MODULES = [
    p
    for p in ("/usr/local/share/swarmbox/herdr-web/node_modules", os.path.join(WEB_DIR, "node_modules"))
    if os.path.isdir(os.path.join(p, "@xterm", "headless"))
]


class _FakeWebHandler(http.server.BaseHTTPRequestHandler):
    received = []
    delivered = 1

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length).decode("utf-8", errors="replace")
        try:
            body = json.loads(raw)
        except ValueError:
            body = None
        type(self).received.append((self.path, body))
        resp = json.dumps({"ok": True, "delivered": type(self).delivered}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(resp)))
        self.end_headers()
        self.wfile.write(resp)

    def log_message(self, format, *args):
        pass


class SwarmboxOpenTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _FakeWebHandler)
        cls._web_port = cls._srv.server_address[1]
        cls._srv_thread = threading.Thread(target=cls._srv.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
        cls._srv_thread.start()
        cls.addClassCleanup(lambda: (cls._srv.shutdown(), cls._srv.server_close()))

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="swarmbox-open-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.run_dir = os.path.join(self.tmp, "run")
        os.makedirs(self.run_dir, exist_ok=True)
        self.tty = os.path.join(self.tmp, "tty")

    def run_open(self, args, port=1, extra_env=None):
        env = dict(os.environ)
        env["SWARMBOX_TEST_WEB_HOST"] = "127.0.0.1"
        env["SWARMBOX_TEST_WEB_PORT"] = str(port)
        env["SWARMBOX_TEST_RUN_DIR"] = self.run_dir
        env["SWARMBOX_TEST_TTY"] = self.tty
        if extra_env:
            env.update(extra_env)
        return subprocess.run(
            [sys.executable, OPEN_SCRIPT] + list(args),
            env=env,
            capture_output=True,
            text=True,
            timeout=10,
        )

    def start_fake_web(self, delivered=1):
        _FakeWebHandler.received = []
        _FakeWebHandler.delivered = delivered
        return self._web_port

    def test_rejects_missing_or_disallowed_urls(self):
        for args in (
            [],
            ["javascript:alert(1)"],
            ["file:///etc/passwd"],
            ["data:text/html,hi"],
            ["https://example.com/a b"],
            ["https://example.com/\x1b]0;pwn\x07"],
            ["https://example.com/" + "a" * 4100],
        ):
            with self.subTest(args=args):
                r = self.run_open(args)
                self.assertEqual(r.returncode, 2, r.stderr)

    def test_delivers_to_web_studio_and_exits_zero(self):
        port = self.start_fake_web(delivered=1)
        url = "https://claude.ai/artifact/EXDjozHoQwYhTXcFEpELaK"
        r = self.run_open(["--", url], port=port)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(_FakeWebHandler.received, [("/api/open-url", {"url": url})])
        self.assertFalse(os.path.exists(self.tty))

    def test_delivers_to_live_cockpit_when_no_web_client_connected(self):
        port = self.start_fake_web(delivered=0)
        marker = os.path.join(self.run_dir, f"cockpit.{os.getpid()}")
        with open(marker, "w", encoding="utf-8") as fh:
            fh.write(f"{os.getpid()}\n")
        url = "https://example.com/docs?q=1"
        r = self.run_open([url], port=port)
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(os.path.join(self.run_dir, "open-url.json"), encoding="utf-8") as fh:
            ev = json.load(fh)
        self.assertEqual(ev["url"], url)
        self.assertTrue(ev["id"])

    def test_plain_terminal_fallback_writes_osc52_and_exits_nonzero(self):
        # Stale cockpit marker should be cleaned up and not count as live.
        dead = subprocess.Popen(["true"])
        dead.wait()
        stale = os.path.join(self.run_dir, f"cockpit.{dead.pid}")
        with open(stale, "w", encoding="utf-8") as fh:
            fh.write(f"{dead.pid}\n")

        port = self.start_fake_web(delivered=0)
        url = "https://example.com/login"
        r = self.run_open([url], port=port)
        self.assertEqual(r.returncode, 1)
        self.assertFalse(os.path.exists(stale))
        with open(self.tty, "rb") as fh:
            raw = fh.read()
        expected = f"\x1b]52;c;{base64.b64encode(url.encode('utf-8')).decode('ascii')}\x07".encode("ascii")
        self.assertEqual(raw, expected)


@unittest.skipUnless(shutil.which("node") and MODULES, "node or @xterm/headless is not installed")
class ServerAndCockpitOpenUrlTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="open-url-js-")
        cls.addClassCleanup(shutil.rmtree, cls.tmp, True)
        for f in glob.glob(os.path.join(WEB_DIR, "*.mjs")):
            shutil.copy(f, cls.tmp)
        os.symlink(MODULES[0], os.path.join(cls.tmp, "node_modules"))

    def test_server_url_and_loopback_validators(self):
        script = r"""
import { validateOpenUrl, isLoopbackAddress } from './server.mjs';
const out = {
  okHttps: validateOpenUrl('https://claude.ai/artifact/abc'),
  okHttp: validateOpenUrl('http://127.0.0.1:3000/cb'),
  badJs: validateOpenUrl('javascript:alert(1)'),
  badFile: validateOpenUrl('file:///etc/passwd'),
  badCtrl: validateOpenUrl('https://example.com/\x1b]0;x'),
  loopV4: isLoopbackAddress('127.0.0.1'),
  loopV6: isLoopbackAddress('::1'),
  loopMapped: isLoopbackAddress('::ffff:127.0.0.1'),
  nonLoop: isLoopbackAddress('192.168.1.5'),
};
console.log(JSON.stringify(out));
"""
        path = os.path.join(self.tmp, "check_server.mjs")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(script)
        r = subprocess.run(["node", path], cwd=self.tmp, capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout.strip().splitlines()[-1])
        self.assertEqual(out["okHttps"], "https://claude.ai/artifact/abc")
        self.assertEqual(out["okHttp"], "http://127.0.0.1:3000/cb")
        self.assertIsNone(out["badJs"])
        self.assertIsNone(out["badFile"])
        self.assertIsNone(out["badCtrl"])
        self.assertTrue(out["loopV4"])
        self.assertTrue(out["loopV6"])
        self.assertTrue(out["loopMapped"])
        self.assertFalse(out["nonLoop"])

    def test_cockpit_polls_open_url_and_emits_osc52_and_osc8(self):
        run_dir = os.path.join(self.tmp, "run")
        os.makedirs(run_dir, exist_ok=True)
        script = r"""
import fs from 'node:fs';
import path from 'node:path';
import { Cockpit } from './cockpit.mjs';
const writes = [];
const c = new Cockpit({
  stdin: { on() {}, setRawMode() {}, resume() {} },
  stdout: { write(s) { writes.push(String(s)); }, columns: 120, rows: 30, on() {} },
  hc: { on() {}, listSnapshot() { return []; } },
});
c.scheduleRender = () => {};
const url = 'https://claude.ai/artifact/EXDjozHoQwYhTXcFEpELaK';
fs.writeFileSync(path.join(process.env.SWARMBOX_TEST_RUN_DIR, 'open-url.json'), JSON.stringify({ id: 'evt1', url, ts: Date.now() }));
const first = c._pollOpenUrl();
const second = c._pollOpenUrl();
const footer = c._renderFooter(c.layout(), c.palette());
// Malicious URL must be ignored
fs.writeFileSync(path.join(process.env.SWARMBOX_TEST_RUN_DIR, 'open-url.json'), JSON.stringify({ id: 'evt2', url: 'javascript:alert(1)', ts: Date.now() }));
const bad = c._pollOpenUrl();
console.log(JSON.stringify({ first, second, bad, writes, footer, toastHref: c.toastHref }));
"""
        path = os.path.join(self.tmp, "check_cockpit.mjs")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(script)
        env = dict(os.environ, HOME=self.tmp, SWARMBOX_TEST_RUN_DIR=run_dir)
        r = subprocess.run(["node", path], cwd=self.tmp, env=env, capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout.strip().splitlines()[-1])
        url = "https://claude.ai/artifact/EXDjozHoQwYhTXcFEpELaK"
        expected_osc52 = f"\x1b]52;c;{base64.b64encode(url.encode('utf-8')).decode('ascii')}\x07"
        self.assertTrue(out["first"])
        self.assertFalse(out["second"])
        self.assertFalse(out["bad"])
        self.assertEqual(out["writes"], [expected_osc52])
        self.assertEqual(out["toastHref"], url)
        self.assertIn(f"\x1b]8;;{url}\x1b\\", out["footer"])


if __name__ == "__main__":
    unittest.main()
