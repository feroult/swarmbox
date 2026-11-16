#!/usr/bin/env python3
"""End to end proof of version 1 FROM THE MICROPHONE IN A BROWSER TO THE ANSWER IN A REAL CLAUDE CODE TAB, inside a container. NOT part of the fast gate.

Every piece is the real one: the voice addon installed by the real swarmbox-addon (whisper.cpp built from source, model small; the install is cached in a
mounted folder and copied from it), the web terminal started as the box starts it (container/scripts/swarmbox-web.sh run: the voice front on 7681, ttyd
attached to the real tmux session through swarmbox-attach, the voice service), the real swarmbox-bus under a supervisor like the entrypoint's, the sysop
installed and started by swarmbox-addon, swarmbox-tabs, `claude -p` (haiku) as the brain, a second real Claude Code in a tab (auto-approve flag), and a
headless Chromium whose fake microphone plays WAVs made here with espeak-ng, driven over the DevTools protocol: the mouse presses the microphone button,
the keys are real key events into the terminal of the page. The only browser client of tmux is the web terminal. The tmux server is the container's own
(a private TMUX_TMPDIR; the program refuses to run outside a container).

Run it with tests/e2e/e2e_voice.sh (it starts the container and passes the login). Inside the container:

    python3 tests/e2e/e2e_voice.py [--only 1,3,4] [--runs 5] [--list]

Scenarios: 1 the path of version 1 (the microphone to the answer, 5 runs: 4 Portuguese and 1 English), 2 topics are settings (a changed topic, a mismatch,
two sysops in a group, a plain watcher), 3 no sysop, sysop stopped, bus down, 4 the panel inside the browser terminal (landscape and portrait) and its keys,
5 the path of a tunnel (another host name): only the four routes, a cross-origin POST, 6 a goal that needs approval, 7 the screens never pass through the bus,
8 the microphone never over the status bar and its clock (desktop, phone portrait, phone landscape; bounding boxes and a screenshot of each), 9 the thumb path on a phone (tap Panel,
tap Esc, hold the microphone; the panel in portrait is 30 %, typing along never reaches it, the idle screen), 10 a new window with the panel always up (Alt+N, the + button).
The 14 scenarios of the sysop itself (the last three: the panel always up, auto and off) are tests/e2e/e2e_sysop.py (tests/e2e/e2e_sysop.sh).
Every check prints PASS or FAIL; the exit status is 1 when one failed. Screens, screenshots, audit files and a JSON report go to $E2E_RESULTS.

The login (CLAUDE_CODE_OAUTH_TOKEN) is only read from the environment, handed to the box's processes as they would have it, never to the browser, and
scrubbed from everything printed or written here.
"""
import argparse
import base64
import http.client
import json
import os
import re
import shutil
import signal
import socket
import statistics
import subprocess
import sys
import threading
import time
import urllib.request
import wave

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "slow"))      # CDP, the browser driver of tests/slow/test_clipboard_bridge.py
sys.path.insert(0, os.path.join(HERE, "..", "support"))
import e2e_sysop as E  # noqa: E402  (the Box of the sysop's harness, its checks and its helpers)
from test_clipboard_bridge import CDP  # noqa: E402

E.SOCK = "default"       # the server of this container, in a private TMUX_TMPDIR: swarmbox-attach (which ttyd runs) finds it without options
E.TOPIC = "goal"         # the default topic: voice.topic and sysop.topic are not set unless a scenario sets them
log, check, info, wait_for, scrub = E.log, E.check, E.info, E.wait_for, E.scrub

REPO = E.REPO
WORK = E.WORK
RESULTS = E.RESULTS
CACHE = os.environ.get("E2E_WS_CACHE", "/ws-cache")
WAVS = os.environ.get("E2E_WAVS") or os.path.join(WORK, "wavs")
CHROMIUM = next((c for c in (shutil.which(n) for n in ("chromium", "chromium-browser", "google-chrome")) if c), None)
WEB_SH = os.path.join(REPO, "container", "scripts", "swarmbox-web.sh")
ATTACH_SH = os.path.join(REPO, "container", "scripts", "swarmbox-attach.sh")
PORT = 7681
TUNNEL = "tunnel.example.test"          # a host name that is not localhost, mapped to 127.0.0.1 inside the browser only
EVIL = "evil.example.test"
FINAL_LIGHTS = ("sent", "nothing", "nolistener", "busy", "error")
SPEECH = {            # name: (espeak-ng voice, speed, text). Whisper small hears espeak's English well and its Portuguese badly ("responda exatamente PONG nove"
                      # came out as "Responda exatamente com 9", "por novi" ...; with the language left on auto, as "Pongnobbi" and worse), so the sentences are the ones it
                      # transcribes right: the transcript of every run is printed
    "pt-pong": ("pt-br+f3", 130, "responda exatamente com a palavra pong"),
    "en-banana": ("en-us", 130, "reply with exactly banana nine"),
    "en-hello": ("en-us", 130, "say hello in the panel and finish"),
    "en-rm": ("en-us", 130, "delete the build folder"),
    "pt-rm": ("pt-br+f3", 130, "apaga a pasta build"),
    "pt-yes": ("pt-br+f3", 130, "sim aprovo"),
}
ANSWER_PT = re.compile(r'^[●⏺]\s*["“\']?PON', re.M | re.I)                       # "PONG" (Whisper writes the word it hears from espeak as PON)
ANSWER_ANY = re.compile(r"^[●⏺]\s*\S", re.M)                     # an answer of Claude Code to what was typed (a fresh tab has none)
ANSWER_EN = re.compile(r"^[●⏺]\s*banana[\s\-:.,]*(9|nine)\b", re.M | re.I)
TYPED = re.compile(r"^❯ (?!Try )\S", re.M)          # a prompt in the input box or echoed in the history of Claude Code
SECRET = "sk-ant-api03-FAKEFAKEFAKEFAKEFAKEFAKEFAKE0123"          # a pattern the filter of swarmbox-tabs knows; not a real key
TIMES = []          # seconds from the release of the button to the answer, the runs of scenario 1
V1 = []
TOPICS_USED = {"goal", "hello", "a", "b"}      # the topics the scenarios use (goal; hello, a and b in scenario 2)


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def make_wavs():
    """the spoken goals: espeak-ng, 48 kHz mono 16-bit, 0.5 s of silence before and 1 s after (the fake microphone loops the file, so the button is
    released before the end)"""
    import array
    import io
    os.makedirs(WAVS, exist_ok=True)
    for name, (voice, speed, text) in SPEECH.items():
        path = os.path.join(WAVS, name + ".wav")
        if os.path.exists(path):
            continue
        raw = subprocess.run(["espeak-ng", "-v", voice, "-s", str(speed), "-p", "50", "-g", "4", "--stdout", text], capture_output=True, check=True).stdout
        w = wave.open(io.BytesIO(raw))
        sr = w.getframerate()
        a = array.array("h")
        a.frombytes(w.readframes(w.getnframes()))
        rate = 48000
        ratio = sr / rate
        out = array.array("h")
        for i in range(int(len(a) / ratio)):
            p = i * ratio
            j = int(p)
            f = p - j
            out.append(int(a[j] * (1 - f) + a[min(j + 1, len(a) - 1)] * f))
        peak = max(1, max(abs(x) for x in out))
        out = array.array("h", [int(x * 20000 / peak) for x in out])
        full = array.array("h", [0] * int(rate * 0.5)) + out + array.array("h", [0] * int(rate * 1.0))
        with wave.open(path, "wb") as o:
            o.setnchannels(1)
            o.setsampwidth(2)
            o.setframerate(rate)
            o.writeframes(full.tobytes())


def wav_seconds(name):
    with wave.open(os.path.join(WAVS, name + ".wav")) as w:
        return w.getnframes() / w.getframerate()


# ====================================================================================================================== the browser
class Browser:
    """headless Chromium with a fake microphone that plays WAV, one page, driven over the DevTools protocol"""

    def __init__(self, box, wav, viewport=(1600, 900), host=None, secure=False, tag="b"):
        self.box = box
        self.tag = tag
        self.host = host or "127.0.0.1"
        self.viewport = viewport
        self.secure = secure
        self.wav = wav
        self.path = "/"
        self.page = None
        self.browser = None
        self.proc = None
        self.tmp = None
        self.touch = False          # a phone: mobile viewport, touch events, (pointer: coarse); set before open()
        self.dsf = 1
        self.launch()

    def launch(self):
        self.tmp = os.path.join(WORK, "chrome-%s-%d" % (self.tag, int(time.time() * 1000) % 100000))
        os.makedirs(self.tmp, exist_ok=True)
        self.dbg = free_port()
        args = [CHROMIUM, "--headless=new", "--no-sandbox", "--disable-gpu", "--remote-debugging-port=%d" % self.dbg,
                "--user-data-dir=" + os.path.join(self.tmp, "profile"), "--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream",
                "--use-file-for-fake-audio-capture=" + os.path.join(WAVS, self.wav + ".wav"), "--autoplay-policy=no-user-gesture-required"]
        if self.host != "127.0.0.1":
            args.append("--host-resolver-rules=MAP %s 127.0.0.1, MAP %s 127.0.0.1" % (TUNNEL, EVIL))
        if self.secure:      # a tunnel is https (a secure context, where the microphone works); here it is plain http on another name
            args.append("--unsafely-treat-insecure-origin-as-secure=http://%s:%d" % (self.host, PORT))
        args.append("about:blank")
        env = {"PATH": "/usr/bin:/bin", "HOME": self.tmp, "LANG": "C.UTF-8"}      # never the login of the box
        self.proc = subprocess.Popen(args, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        version = None
        for _ in range(100):
            try:
                with urllib.request.urlopen("http://127.0.0.1:%d/json/version" % self.dbg, timeout=1) as r:
                    version = json.load(r)
                break
            except OSError:
                time.sleep(0.2)
        if version is None:
            raise RuntimeError("chromium did not start")
        self.browser = CDP(version["webSocketDebuggerUrl"])
        self.page = None

    def use_wav(self, wav):
        """The fake microphone plays the file it was started with: another sentence needs another start. The page is opened again where it was."""
        if wav == self.wav:
            return
        self.close()
        self.wav = wav
        self.launch()
        self.open(self.path)

    def open(self, path="/", wait_term=True, wait_mic=True):
        self.path = path
        if self.page is not None:
            self.page.s.close()
        req = urllib.request.Request("http://127.0.0.1:%d/json/new?about:blank" % self.dbg, method="PUT")
        with urllib.request.urlopen(req, timeout=10) as r:
            tab = json.load(r)
        self.page = CDP(tab["webSocketDebuggerUrl"])
        p = self.page
        p.call("Page.enable")
        p.call("Runtime.enable")
        p.call("Emulation.setFocusEmulationEnabled", enabled=True)
        self.resize(*self.viewport, mobile=self.touch)
        if self.touch:
            p.call("Emulation.setTouchEmulationEnabled", enabled=True, maxTouchPoints=5)
            p.call("Emulation.setEmulatedMedia", features=[{"name": "pointer", "value": "coarse"}, {"name": "hover", "value": "none"}])
        p.call("Page.navigate", url="http://%s:%d%s" % (self.host, PORT, path))
        ok = True
        if wait_term:
            ok = wait_for(lambda: self.js("typeof term === 'object' && term.buffer.active.length > 0 && term.cols > 0"), 40, 0.25) is not None
        if wait_term and wait_mic:
            ok = ok and wait_for(lambda: self.js("!!document.getElementById('swarmbox-voice-mic')"), 20, 0.25) is not None
        time.sleep(0.6)
        if wait_term:
            self.js("term.focus()")
        return ok

    def resize(self, w, h, mobile=False):
        self.viewport = (w, h)
        self.page.call("Emulation.setDeviceMetricsOverride", width=w, height=h, deviceScaleFactor=self.dsf if mobile else 1, mobile=mobile)

    def device(self, kind):
        """desktop 1600x900, phone portrait 390x844, phone landscape 844x390 (touch, coarse pointer), the page opened again. The device scale stays 1: headless
        Chromium with an EMULATED scale factor of 2 draws the canvas text of xterm.js twice as large as its grid (a screenshot shows the top left quarter of the
        terminal), and the same page with a real --force-device-scale-factor=2 is right, so the emulated scale would only make the screenshots lie"""
        w, h, touch = {"desktop": (1600, 900, False), "portrait": (390, 844, True), "landscape": (844, 390, True)}[kind]
        self.touch, self.dsf = touch, 1
        self.viewport = (w, h)
        return self.open(self.path)

    def js(self, expr, wait=False):
        return self.page.js(expr, wait=wait)

    def close(self):
        for c in (self.page, self.browser):
            try:
                c.s.close()
            except Exception:
                pass
        self.page = self.browser = None
        try:
            os.killpg(self.proc.pid, signal.SIGKILL)
            self.proc.wait(timeout=10)
        except Exception:
            pass
        shutil.rmtree(self.tmp, ignore_errors=True)

    # ---- the page
    def term_text(self):
        return self.js("(() => { const b = term.buffer.active, r = []; for (let i = 0; i < b.length; i++) { const l = b.getLine(i); if (l) r.push(l.translateToString(true, 0, term.cols)); } return r.join('\\n'); })()") or ""

    def term_size(self):
        return tuple(self.js("[term.cols, term.rows]") or (0, 0))

    def light(self):
        # the button of the microphone carries the state; the sentence is said through the controls strip of the host page
        return self.js("(() => { const r = document.getElementById('swarmbox-voice-mic'); if (!r) return ['none', '']; "
                       "const n = document.querySelector('#swarmbox-strip .sb-note'); return [r.getAttribute('data-state'), n && !n.hidden ? n.textContent : '']; })()")

    def voice_text(self):
        return self.js("(document.getElementById('swarmbox-strip') || {textContent: ''}).textContent")

    def screenshot(self, name):
        r = self.page.call("Page.captureScreenshot", format="png")
        path = os.path.join(RESULTS, self.box.scenario, name + ".png")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(base64.b64decode(r["data"]))
        return path

    # ---- the hands
    def mouse(self, kind, x, y, button="left"):
        self.page.call("Input.dispatchMouseEvent", type=kind, x=x, y=y, button=button if kind != "mouseMoved" else "none",
                       buttons=1 if kind == "mousePressed" else 0, clickCount=1 if kind != "mouseMoved" else 0)

    def mic_center(self):
        r = self.js("(() => { const b = document.getElementById('swarmbox-voice-mic').getBoundingClientRect(); return [b.left + b.width / 2, b.top + b.height / 2]; })()")
        return r[0], r[1]

    def tap(self, x, y, hold=0.06):
        """a finger: touchStart, touchEnd (the strip sends a tap on release)"""
        self.page.call("Input.dispatchTouchEvent", type="touchStart", touchPoints=[{"x": x, "y": y}])
        time.sleep(hold)
        self.page.call("Input.dispatchTouchEvent", type="touchEnd", touchPoints=[])

    def strip_button(self, text):
        """centre of a key button of the strip by its label"""
        r = self.js("(() => { const b = Array.from(document.querySelectorAll('#swarmbox-strip .sb-key')).find(e => e.textContent === %s); "
                    "if (!b) return null; const r = b.getBoundingClientRect(); return [r.left + r.width / 2, r.top + r.height / 2]; })()" % json.dumps(text))
        return tuple(r) if r else None

    def tap_key(self, text):
        c = self.strip_button(text)
        if c is None:
            raise RuntimeError("no key button %r in the strip" % text)
        self.tap(*c)

    def hold(self, seconds, final_timeout=120, finger=False):
        """hold the microphone button for `seconds` (the mouse, as a person), release, follow the light until it shows an end state.
        Returns {press, release, timeline: [(abs time, state, note)], final}"""
        x, y = self.mic_center()
        tl = []

        def poll():
            s = tuple(self.light())
            if not tl or tl[-1][1:] != s:
                tl.append((time.time(),) + s)
            return s[0]
        if finger:
            press = time.time()
            self.page.call("Input.dispatchTouchEvent", type="touchStart", touchPoints=[{"x": x, "y": y}])
        else:
            self.mouse("mouseMoved", x, y)
            press = time.time()
            self.mouse("mousePressed", x, y)
        end = press + seconds
        while time.time() < end:
            poll()
            time.sleep(0.05)
        release = time.time()
        if finger:
            self.page.call("Input.dispatchTouchEvent", type="touchEnd", touchPoints=[])
        else:
            self.mouse("mouseReleased", x, y)
        final = None
        while time.time() - release < final_timeout:
            st = poll()
            if st in FINAL_LIGHTS and tl[-1][0] >= release - 0.001 and any(t[1] == "sending" for t in tl):
                final = tl[-1]
                break
            time.sleep(0.05)
        return {"press": press, "release": release, "timeline": tl, "final": final}

    def key(self, key, code=None, vk=None, mods=0, text=None):
        code = code or ("Key" + key.upper() if len(key) == 1 and key.isalpha() else key)
        vk = vk if vk is not None else (ord(key.upper()) if len(key) == 1 else 0)
        self.page.call("Input.dispatchKeyEvent", type="rawKeyDown", key=key, code=code, windowsVirtualKeyCode=vk, modifiers=mods)
        if text:
            self.page.call("Input.dispatchKeyEvent", type="char", key=key, code=code, text=text, windowsVirtualKeyCode=vk, modifiers=mods)
        self.page.call("Input.dispatchKeyEvent", type="keyUp", key=key, code=code, windowsVirtualKeyCode=vk, modifiers=mods)

    def send_keys(self, data, gap=0.03):
        """what the user types: \\x01..\\x1a are Ctrl+letter, \\r Enter, \\x1b Escape, anything else is the character"""
        for ch in data:
            o = ord(ch)
            if ch == "\r":
                self.key("Enter", "Enter", 13, text="\r")
            elif ch == "\x1b":
                self.key("Escape", "Escape", 27)
            elif 1 <= o <= 26:
                self.key(chr(o + 96), mods=2)
            else:
                shift = ch.isupper() or ch in '~!@#$%^&*()_+{}|:"<>?'
                self.key(ch, code=("Key" + ch.upper()) if ch.isalpha() else ("Digit" + ch if ch.isdigit() else "Unidentified"),
                         vk=ord(ch.upper()) if ch.isalnum() else ord(ch), mods=8 if shift else 0, text=ch)
            time.sleep(gap)

    def cell(self):
        return self.js("(() => { const s = document.querySelector('.xterm-screen').getBoundingClientRect(); "
                       "return [s.left, s.top, s.width / term.cols, s.height / term.rows]; })()")

    def click_cell(self, col, row):
        left, top, cw, ch = self.cell()
        x, y = left + (col + 0.5) * cw, top + (row + 0.5) * ch
        self.mouse("mouseMoved", x, y)
        self.mouse("mousePressed", x, y)
        time.sleep(0.05)
        self.mouse("mouseReleased", x, y)

    def fetch(self, url, method="GET", body=None, headers=None, mode="cors"):
        """fetch() from the page: {status, type, text, err}"""
        opts = {"method": method, "mode": mode, "cache": "no-store", "headers": headers or {}}
        if body is not None:
            opts["body"] = "__BODY__"
        js = ("(async () => { try { const o = %s; %s const r = await fetch(%s, o); const t = await r.text(); "
              "return {status: r.status, type: r.type, text: t.slice(0, 300)}; } catch (e) { return {err: String(e)}; } })()"
              % (json.dumps(opts), "o.body = new Blob([Uint8Array.from(atob(%s), c => c.charCodeAt(0))], {type: 'audio/wav'});" % json.dumps(body)
                 if body is not None else "", json.dumps(url)))
        return self.js(js, wait=True)


# ====================================================================================================================== the box with the web terminal
class VBox(E.Box):
    def __init__(self, model="haiku"):
        super().__init__(model)
        self.web_proc = None
        self.web_log = None
        self.bus_thread = None
        self.page_file = None
        self.br = None
        self.watch_proc = None
        self.env["SWARMBOX_VOICE_TOPIC"] = E.TOPIC          # what the host passes for voice.topic (the same name as sysop.topic by default)

    # the browser is the only client: what the harness "types" goes through its terminal
    def keys(self, data):
        self.br.send_keys(data if isinstance(data, str) else data.decode())

    def click_panel(self):
        p = next(x for x in self.tmux("list-panes", "-s", "-t", "main", "-F", "#{pane_left}|#{pane_top}|#{@swarmbox_sysop_panel}").splitlines() if x.endswith("|1"))
        self.br.click_cell(int(p.split("|")[0]) + 4, int(p.split("|")[1]) + 1)

    def attach_client(self):
        pass

    def start_bus(self):
        self.bus_run = True

        def sup():
            logf = open(os.path.join(self.state_dir, "bus.log"), "ab")
            while self.bus_run:
                self.bus_proc = subprocess.Popen(["swarmbox-bus", "serve"], env=self.env, stdout=logf, stderr=logf, stdin=subprocess.DEVNULL, start_new_session=True)
                self.bus_proc.wait()
                if not self.bus_run:
                    return
                self.bus_restarts += 1
                time.sleep(1.5)
        self.bus_thread = threading.Thread(target=sup, daemon=True)
        self.bus_thread.start()

    def stop_bus(self):
        self.bus_run = False
        if self.bus_proc and self.bus_proc.poll() is None:
            self.kill_group(self.bus_proc)
        if self.bus_thread:
            self.bus_thread.join(10)

    def setup(self):
        if not os.path.exists("/run/.containerenv") and not os.path.exists("/.dockerenv"):
            raise SystemExit("e2e_voice: this harness runs a tmux server of its own: run it in a container (tests/e2e/e2e_voice.sh)")
        for d in (self.home, self.bin, self.run_dir, self.tmux_tmp, self.proj, self.throw, self.state_dir, os.path.join(self.home, ".claude"), RESULTS):
            os.makedirs(d, exist_ok=True)
        os.chmod(self.run_dir, 0o700)
        os.chmod(self.tmux_tmp, 0o700)
        projects = {d: {"hasTrustDialogAccepted": True, "allowedTools": []} for d in (self.proj, self.throw, self.home)}
        with open(os.path.join(self.home, ".claude.json"), "w") as f:
            json.dump({"hasCompletedOnboarding": True, "theme": "dark", "projects": projects}, f)
        with open(os.path.join(self.home, ".claude", "settings.json"), "w") as f:
            json.dump({"skipDangerousModePermissionPrompt": True}, f)
        addons = self.env["SWARMBOX_TEST_IMAGE_ADDONS"]
        shutil.rmtree(addons, ignore_errors=True)
        os.makedirs(addons)
        for t in ("sysop", "voice"):
            shutil.copytree(os.path.join(REPO, "container", "addons", t), os.path.join(addons, t), ignore=shutil.ignore_patterns("__pycache__"))
        for name, body in (("swarmbox-bus", 'exec /usr/bin/python3 -S "%s/container/scripts/swarmbox-bus.py" "$@"' % REPO),
                           ("swarmbox-tabs", 'exec /usr/bin/python3 -S "%s/container/scripts/swarmbox-tabs.py" "$@"' % REPO),
                           ("swarmbox-addon", 'exec bash "%s/container/scripts/swarmbox-addon.sh" "$@"' % REPO),
                           ("swarmbox-attach", 'SWARMBOX_TEST_RUN_DIR="%s" exec bash "%s" "$@"' % (self.run_dir, ATTACH_SH))):
            p = os.path.join(self.bin, name)
            with open(p, "w") as f:
                f.write("#!/bin/sh\n" + body + "\n")
            os.chmod(p, 0o755)
        info("versions", "tmux %s; claude %s; chromium %s" % (self.sh(["tmux", "-V"]).stdout.strip(), self.sh(["claude", "--version"]).stdout.strip(),
                                                              self.sh([CHROMIUM, "--version"]).stdout.strip()))
        make_wavs()
        self.start_tmux()
        self.start_bus()
        check("setup: the bus answers", wait_for(lambda: self.sh(["swarmbox-bus", "ping"]).returncode == 0, 15) is not None)
        self.install_voice()
        self.voice_launcher()
        r = self.sh(["swarmbox-addon", "install", "sysop"], timeout=90)
        check("setup: swarmbox-addon install sysop (install.sh, self-test, prepare.sh)", r.returncode == 0, r.stderr.strip().replace("\n", " | ")[-300:])
        self.sysop_launcher()
        check("setup: the sysop service runs and is connected to the bus", self.wait_service(30))
        self.build_page()
        with open(os.path.join(self.run_dir, "ready"), "w") as f:      # the readiness marker `serve` writes (swarmbox-attach waits for it)
            f.write("ready\n")
        self.start_web()
        self.br = Browser(self, "en-banana")
        ok = self.br.open()
        check("setup: the web terminal in the browser shows tmux and the microphone button", ok, self.br.term_text()[-200:])
        self.save("setup-terminal.txt", self.br.term_text())
        self.br.screenshot("setup-page")

    def voice_launcher(self):
        """the shim `swarmbox-voice` of the box's PATH (swarmbox-addon link): here a launcher of the installed copy"""
        with open(os.path.join(self.bin, "swarmbox-voice"), "w") as f:
            f.write('#!/bin/sh\nexec "%s" "$@"\n' % os.path.join(self.voice_prefix(), "current", "bin", "swarmbox-voice"))
        os.chmod(os.path.join(self.bin, "swarmbox-voice"), 0o755)

    def goal_events(self):
        """how many goals the audit has (each goal event is one goal; the other events of a goal that is ending are not counted)"""
        return len([e for e in self.audit() if e.get("event") == "goal"])

    def sysop_launcher(self):
        with open(os.path.join(self.bin, "swarmbox-sysop"), "w") as f:
            f.write('#!/bin/sh\nexec "%s" "$@"\n' % self.sysop_bin())
        os.chmod(os.path.join(self.bin, "swarmbox-sysop"), 0o755)

    def voice_prefix(self):
        return os.path.join(self.home, ".local", "share", "swarmbox", "addons", "voice")

    def install_voice(self):
        """the voice addon: copied from the cache folder when it has the install (whisper.cpp built, the model), else installed by swarmbox-addon and put there"""
        dest = self.voice_prefix()
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        cached = os.path.join(CACHE, "home", ".local", "share", "swarmbox", "addons", "voice")
        t = time.time()
        if os.path.isdir(os.path.join(cached, "1.9.5", "models")) and os.path.exists(os.path.join(cached, "current")):
            shutil.copytree(cached, dest, symlinks=True)
            info("voice", "install copied from the cache in %.1fs" % (time.time() - t))
        r = self.sh(["swarmbox-addon", "install", "voice"], timeout=1500)
        check("setup: swarmbox-addon install voice (whisper.cpp, model small, self-test)", r.returncode == 0 and
              os.path.exists(os.path.join(dest, "1.9.5", "models", "ggml-small.bin")), r.stderr.strip().replace("\n", " | ")[-300:])
        if os.path.isdir(CACHE) and not os.path.isdir(os.path.join(cached, "1.9.5", "models")):
            try:
                os.makedirs(os.path.dirname(cached), exist_ok=True)
                shutil.copytree(dest, cached, symlinks=True)
            except OSError as e:
                info("voice", "the cache could not be written: %s" % e)
        r = self.sh(["swarmbox-addon", "prepare"], timeout=60)
        info("voice prepare", r.stderr.strip().replace("\n", " | ")[-200:])

    def build_page(self):
        """the page of the box: ttyd's own page, the clipboard bridge and the style (build-index.sh), as the image builds it; swarmbox-web renders and tags it"""
        port = free_port()
        stock = os.path.join(WORK, "stock.html")
        ttyd = subprocess.Popen(["ttyd", "-p", str(port), "-i", "lo", "true"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        try:
            for _ in range(50):
                try:
                    with urllib.request.urlopen("http://127.0.0.1:%d/" % port, timeout=1) as r, open(stock, "wb") as f:
                        f.write(r.read())
                    break
                except OSError:
                    time.sleep(0.2)
        finally:
            os.killpg(ttyd.pid, signal.SIGKILL)
            ttyd.wait(timeout=5)
        self.page_file = os.path.join(WORK, "built", "index.html")
        web = os.path.join(REPO, "container", "web")
        r = subprocess.run(["sh", os.path.join(web, "build-index.sh"), stock, os.path.join(web, "ttyd-clipboard.js"), os.path.join(web, "ttyd-style.css"), self.page_file],
                           capture_output=True, text=True)
        check("setup: build-index.sh built the page", r.returncode == 0, r.stderr.strip())

    def web_url_ok(self):
        try:
            with urllib.request.urlopen("http://127.0.0.1:%d/voice/health" % PORT, timeout=2) as r:
                return r.status == 200 and json.load(r).get("ok") is True
        except (OSError, ValueError):
            return False

    def start_web(self, **extra):
        """swarmbox-web run, as the box's supervisor runs it: renders the page with the voice tags and execs the front (ttyd and the voice service behind it).
        extra are environment variables the host passes (SWARMBOX_VOICE_TOPIC, SWARMBOX_VOICE_LANGUAGE ...)"""
        self.stop_web()
        e = dict(self.env)
        e.update({"SWARMBOX_TEST_RUN_DIR": self.run_dir, "SWARMBOX_TEST_WEB_PAGE": self.page_file})
        e.update(extra)
        self.web_log = open(os.path.join(self.state_dir, "web.log"), "ab")
        self.web_proc = subprocess.Popen(["bash", WEB_SH, "run"], env=e, stdout=self.web_log, stderr=self.web_log, stdin=subprocess.DEVNULL, start_new_session=True)
        ok = wait_for(self.web_url_ok, 30, 0.25)
        if not ok:
            log("the web terminal did not come up: %s" % self.read(os.path.join(self.state_dir, "web.log"))[-600:])
        return ok is not None

    def stop_web(self):
        if self.web_proc and self.web_proc.poll() is None:
            self.kill_group(self.web_proc, signal.SIGTERM)
            try:
                self.web_proc.wait(8)
            except subprocess.TimeoutExpired:
                pass
            self.kill_group(self.web_proc)
        # the children (ttyd, the voice service) are in the same group; wait for the port
        wait_for(lambda: not self.listening(PORT), 10, 0.2)

    @staticmethod
    def listening(port):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return True
        except OSError:
            return False

    @staticmethod
    def read(path):
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                return f.read()
        except OSError:
            return ""

    def stop_all(self):
        try:
            if self.br:
                self.br.close()
        except Exception:
            pass
        self.watch_stop()
        self.stop_web()
        super().stop_all()

    # ---- watchers on the bus
    def watch_start(self, argv, name):
        path = os.path.join(WORK, name + ".out")
        f = open(path, "wb")
        p = subprocess.Popen(argv, env=self.env, stdout=f, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, start_new_session=True)
        return p, path

    def watch_stop(self):
        if self.watch_proc:
            self.kill_group(self.watch_proc[0])
            self.watch_proc = None

    @staticmethod
    def lines(path):
        out = []
        for line in VBox.read(path).splitlines():
            try:
                out.append(json.loads(line))
            except ValueError:
                pass
        return out

    # ---- goals made by voice
    def voice_goals(self, since=0.0, audit_dir=None):
        """the 'goal' events of the audit from the voice, after the time `since`: [(goal id, text, time)]"""
        out = []
        for e in self.audit():
            if e.get("event") == "goal" and e.get("source") == "voice" and e.get("t", 0) >= since:
                out.append((e["goal"], e.get("text", ""), e.get("t")))
        return out

    def topics(self):
        r = self.sh(["swarmbox-bus", "topics"])
        try:
            return json.loads(r.stdout)
        except ValueError:
            return []


def shell_secret(box, win):
    box.type_line(win, "export DEMO_KEY=%s; echo key is $DEMO_KEY" % SECRET)
    time.sleep(0.5)


# ====================================================================================================================== scenario 1
def v1_run(box, br, wav, label, answer_re, claude=True, save=True):
    """One run: hold, speak, release; the path to the answer in a fresh Claude Code tab. Returns the measures."""
    tabs = box.reset_tabs(claude=True, extra=())
    cw = tabs["claude"]
    shell_secret(box, tabs["shell"])
    box.select(cw)
    time.sleep(1.2)
    before = box.cap(cw)
    since = time.time()
    dur = wav_seconds(wav)
    ev = {"wav": wav}
    h = br.hold(max(1.0, dur - 0.4))
    rel = h["release"]
    states = [t[1] for t in h["timeline"]]
    ev["light"] = states
    ev["note"] = [t[2] for t in h["timeline"] if t[2]][-1:] or [""]
    ev["whisper_and_publish_s"] = round(h["final"][0] - rel, 2) if h["final"] else None
    seen = {}
    gid = None

    def tick():
        t = time.time() - rel
        nonlocal gid
        if gid is None:
            g = box.voice_goals(since)
            if g:
                gid = g[0][0]
                seen["goal"] = t
        p = box.panel()
        if p and "panel" not in seen:
            seen["panel"] = t
            seen["panel_win"] = p["win"]
            seen["panel_focus"] = p["active"] == "1" and p["winactive"] == "1"
            seen["names"] = {w["id"]: w["name"] for w in box.windows()}
        if p and "countdown" not in seen and "unless you veto it" in box.panel_text():
            seen["countdown"] = t
            seen["panel_text"] = box.panel_text()
            seen["term_with_panel"] = br.term_text()
        s = box.cap(cw)
        if "typed" not in seen and TYPED.search(s) and s != before:
            seen["typed"] = t
        if answer_re.search(s):
            seen["answer"] = t
            return True
        st = box.goal_state(gid) if gid else None
        return bool(st and st.get("state") in ("failed", "stopped"))
    r = wait_for(tick, 120, 0.1)
    st = box.wait_goal(gid, 60) if gid else None
    ev.update({k: round(v, 2) for k, v in seen.items() if k in ("goal", "panel", "countdown", "typed", "answer")})
    ev["state"] = (st or {}).get("state")
    calls = box.calls(gid) if gid else []
    ev["calls"] = [c["tool"] for c in calls]
    text = next((g[1] for g in box.voice_goals(since)), None)
    ev["transcript"] = text
    ev["gid"] = gid
    if save:
        box.save("%s-terminal.txt" % label, br.term_text())
        if gid:
            box.save_goal(label, gid)
        box.save("%s-claude-tab.txt" % label, box.cap(cw))
    check("%s: the light went recording, sending, sent" % label,
          "recording" in states and "sending" in states and states.index("sending") < len(states) - 1 and h["final"] is not None and h["final"][1] == "sent", states)
    check("%s: the page shows no transcript or goal text (only the fixed light sentences)" % label,
          (text or "~~").lower()[:12] not in br.voice_text().lower() and len(br.voice_text()) < 60, br.voice_text())
    check("%s: the goal reached the sysop, source voice, with the transcript" % label, bool(gid) and bool(text), "transcript: %r" % text)
    check("%s: the panel opened in the window of the claude tab" % label, seen.get("panel_win") == cw, seen.get("panel_win"))
    check("%s: the panel did NOT take the focus when it opened" % label, seen.get("panel_focus") is False, seen.get("panel_focus"))
    check("%s: the panel showed the countdown" % label, "countdown" in seen, (seen.get("panel_text") or "")[-200:])
    check("%s: the prompt was typed in the claude tab and the answer appeared" % label, "typed" in seen and "answer" in seen,
          "typed %s, answer %s; tab: %s" % (seen.get("typed"), seen.get("answer"), box.cap(cw)[-400:] if "answer" not in seen else ""))
    check("%s: the goal ended done" % label, ev["state"] == "done", (st or {}).get("error"))
    ev["to_answer_s"] = ev.get("answer")
    ev["claude_answer"] = (re.search(r"^[●⏺].*$", box.cap(cw), re.M) or [None])[0]
    ev["exact_word"] = bool(ANSWER_PT.search(box.cap(cw)) or ANSWER_EN.search(box.cap(cw)))
    info(label + " what Claude Code answered", repr(ev["claude_answer"]) + (" (the exact word)" if ev["exact_word"] else " (not the exact word: Whisper heard something else)"))
    return ev


def s1(box, runs):
    box.scenario = "s1-path"
    box.configure()
    box.start_web()
    box.br.open()
    box.watch_proc = box.watch_start(["swarmbox-bus", "watch"], "watch-s1")        # scenario 7 reads this file
    res = []
    plan = [("pt-pong", "pt"), ("en-banana", "en"), ("pt-pong", "pt"), ("en-banana", "en"), ("pt-pong", "pt")]
    for i, (wav, lang) in enumerate(plan[:runs]):
        label = "s1 run %d (%s)" % (i + 1, lang)
        box.start_web(**({"SWARMBOX_VOICE_LANGUAGE": "pt"} if lang == "pt" else {}))        # voice.language: pt for Portuguese (the documented setting), auto for English
        box.br.close()
        box.br = Browser(box, wav)
        box.br.open()
        ev = v1_run(box, box.br, wav, label.replace(" ", "_").replace("(", "").replace(")", ""), ANSWER_ANY if lang == "pt" else ANSWER_EN)
        for k in ("transcript",):
            info(label + " Whisper transcript", repr(ev.get(k)))
        res.append(ev)
        log("%s: %s" % (label, json.dumps(ev, ensure_ascii=False)))
        if i == 0:
            box.br.screenshot("page-after-run-1")
        if ev.get("answer"):
            TIMES.append(ev["answer"])
            V1.append(ev)
    ok = sum(1 for e in res if "answer" in e and e.get("state") == "done")
    check("s1: successes %d of %d" % (ok, len(res)), ok == len(res))
    E.REPORT["s1"] = res
    box.br.close()
    box.br = Browser(box, "en-banana")
    box.br.open()


# ====================================================================================================================== scenario 2
def speak_and_end(box, br, wav, wait_goal=True, since=None, timeout=60):
    since = since or time.time()
    br.use_wav(wav)
    h = br.hold(max(1.0, wav_seconds(wav) - 0.4))
    last = h["final"]
    return h, (last[1] if last else None), (last[2] if last else ""), since


def s2(box):
    box.scenario = "s2-topics"
    # 2a: a changed topic, on both sides
    box.configure(topic="hello")
    box.start_web(SWARMBOX_VOICE_TOPIC="hello")
    br = box.br
    br.open()
    tabs = box.reset_tabs(claude=True)
    cw = tabs["claude"]
    tp = box.topics()
    check("s2a: the bus shows the sysop on 'hello' and nobody on 'goal'", any(t["topic"] == "hello" for t in tp) and not any(t["topic"] == "goal" for t in tp), tp)
    since = time.time()
    h, state, note, _ = speak_and_end(box, br, "en-banana")
    ok = wait_for(lambda: ANSWER_EN.search(box.cap(cw)), 120)
    g = box.voice_goals(since)
    check("s2a: voice.topic=hello and sysop.topic=hello: sent, the sysop got the goal and Claude answered", state == "sent" and bool(g) and ok is not None,
          (state, g[:1], box.cap(cw)[-300:] if ok is None else ""))
    box.wait_goal(g[0][0], 60) if g else None
    box.save("2a-claude-tab.txt", box.cap(cw))
    # 2b: a mismatch: voice on 'a', the sysop on 'b'
    box.configure(topic="b")
    box.start_web(SWARMBOX_VOICE_TOPIC="a")
    br.open()
    tabs = box.reset_tabs(claude=True)
    cw = tabs["claude"]
    n_goals = box.goal_events()
    tp = box.topics()
    check("s2b: the bus has the sysop on 'b' and nobody on 'a'", any(t["topic"] == "b" for t in tp) and not any(t["topic"] == "a" for t in tp), tp)
    h, state, note, since = speak_and_end(box, br, "en-banana")
    time.sleep(3.5)
    br.screenshot("2b-page-nobody-listening")
    check("s2b: the page says 'Nobody is listening' (amber light, state nolistener)", state == "nolistener" and "Nobody is listening" in (note or ""), (state, note))
    check("s2b: nothing was typed in the claude tab, the sysop saw no goal and its panel (always up) is still idle", not TYPED.search(box.cap(cw)) and box.goal_events() == n_goals
          and "no goal." in box.panel_text() and "unless you veto it" not in box.panel_text(), (box.goal_events() - n_goals, box.panel_text()[-200:]))
    check("s2b: the page does not name the topic", "'a'" not in br.voice_text() and " b" not in br.voice_text().lower().replace("nobody", ""), br.voice_text())
    # 2c: two sysops in one group: a goal is handled once
    box.configure()                              # the default topic again, on both sides
    box.start_web()
    br.open()
    box.reset_tabs(claude=False)
    second = second_sysop(box)
    tp = box.topics()
    check("s2c: two subscribers of the topic goal in the group sysop", any(t["topic"] == "goal" and t.get("groups", {}).get("sysop") == 2 for t in tp), tp)
    since = time.time()
    h, state, note, _ = speak_and_end(box, br, "en-hello")
    box.sh(["swarmbox-voice", "say", "say hello again in the panel and finish"], env={"SWARMBOX_VOICE_TOPIC": "goal"})
    wait_for(lambda: len(box.voice_goals(since)) + len(second_goals(second, since)) >= 2, 20)
    time.sleep(1.5)
    a, b = box.voice_goals(since), second_goals(second, since)
    texts = [x[1] for x in a + b]
    check("s2c: the spoken goal and the next one were each handled exactly once, one by each sysop (round robin)", state == "sent" and len(a) == 1 and len(b) == 1 and len(set(texts)) == 2,
          (state, [x[1] for x in a], [x[1] for x in b]))
    wait_for(lambda: box.idle(1) and second_idle(second), 90)
    stop_second(second)
    # 2d: a plain watcher (no group) sees the goal too and does not take it from the sysop
    box.configure()
    box.reset_tabs(claude=False)
    w, path = box.watch_start(["swarmbox-bus", "sub", "goal"], "plain-watcher")
    wait_for(lambda: any(t["topic"] == "goal" and t["subscribers"] == 2 for t in box.topics()), 8, 0.1)       # the watcher needs a moment to start python and subscribe
    tp = box.topics()
    check("s2d: the plain watcher is a subscriber without a group next to the sysop", any(t["topic"] == "goal" and t["subscribers"] == 2 for t in tp), tp)
    since = time.time()
    h, state, note, _ = speak_and_end(box, br, "en-hello")
    wait_for(lambda: box.voice_goals(since), 20)
    time.sleep(1.0)
    got = box.lines(path)
    gs = box.voice_goals(since)
    check("s2d: the watcher saw the goal (source voice, body text) and the sysop handled it too", state == "sent" and len(got) == 1 and (got[0].get("body") or {}).get("text") and got[0].get("source") == "voice" and len(gs) == 1,
          (state, got, gs))
    box.kill_group(w)
    if gs:
        box.wait_goal(gs[0][0], 60)
    box.idle(60)


SECOND = {}


def second_sysop(box):
    """a second resident sysop on the same bus and topic, its own run and state folders (so the single-instance lock is its own)"""
    run = os.path.join(WORK, "run-b")
    state = os.path.join(WORK, "state-b")
    for d in (run, state):
        os.makedirs(d, exist_ok=True)
    os.chmod(run, 0o700)
    env = dict(box.env)
    env.update({"SB_RUN_DIR": run, "SB_STATE_DIR": state, "SB_BUS_SOCKET": box.sock, "SWARMBOX_SYSOP_MODEL": box.model, "SWARMBOX_SYSOP_COUNTDOWN": "2"})
    log_f = open(os.path.join(state, "serve.out"), "ab")
    p = subprocess.Popen([box.sysop_bin(), "serve", "--log"], env=env, stdout=log_f, stderr=log_f, stdin=subprocess.DEVNULL, start_new_session=True)
    SECOND.update({"proc": p, "state": state, "run": run, "env": env})
    wait_for(lambda: len([t for t in box.topics() if t["topic"] == "goal" and t.get("groups", {}).get("sysop") == 2]) == 1, 20)
    return SECOND


def second_goals(second, since):
    out = []
    try:
        with open(os.path.join(second["state"], "sysop", "events.jsonl"), encoding="utf-8", errors="replace") as f:
            for line in f:
                try:
                    e = json.loads(line)
                except ValueError:
                    continue
                if e.get("event") == "goal" and e.get("source") == "voice" and e.get("t", 0) >= since:
                    out.append((e["goal"], e.get("text", ""), e.get("t")))
    except OSError:
        pass
    return out


def second_idle(second):
    try:
        with open(os.path.join(second["run"], "sysop", "status.json")) as f:
            st = json.load(f)
        return st.get("current") is None and not st.get("queue")
    except (OSError, ValueError):
        return False


def stop_second(second):
    p = second.get("proc")
    if p and p.poll() is None:
        try:
            os.killpg(p.pid, signal.SIGTERM)
            p.wait(8)
        except Exception:
            try:
                os.killpg(p.pid, signal.SIGKILL)
            except OSError:
                pass


# ====================================================================================================================== scenario 3
def s3(box):
    box.scenario = "s3-states"
    box.configure()
    box.start_web()
    br = box.br
    br.open()
    # 3a: the sysop is stopped
    box.stop_service()
    h, state, note, _ = speak_and_end(box, br, "en-hello")
    br.screenshot("3a-sysop-stopped")
    check("s3a: sysop stopped: the page says 'Nobody is listening' and the terminal still works", state == "nolistener" and "Nobody is listening" in note and br.term_size()[0] > 0, (state, note))
    # 3b: the sysop is not installed
    r = box.sh(["swarmbox-addon", "remove", "sysop"], timeout=60)
    check("s3b: swarmbox-addon remove sysop", r.returncode == 0, r.stderr.strip()[-200:])
    time.sleep(0.5)
    h, state, note, _ = speak_and_end(box, br, "en-hello")
    check("s3b: no sysop installed: the same clean state, 'Nobody is listening'", state == "nolistener" and "Nobody is listening" in note, (state, note))
    # 3c: the bus is down
    box.stop_bus()
    check("s3c: the bus is down (no answer on the socket)", wait_for(lambda: box.sh(["swarmbox-bus", "ping"]).returncode != 0, 5) is not None)
    h, state, note, _ = speak_and_end(box, br, "en-hello")
    br.screenshot("3c-bus-down")
    check("s3c: bus down: the page says the bus is not answering (red light), no crash", state == "error" and "bus of the box is not answering" in note, (state, note))
    ok = br.js("document.getElementById('swarmbox-voice-mic') !== null")
    check("s3c: the microphone button and the terminal are still there", ok and br.term_size()[0] > 0)
    # 3d: everything comes back: bus, sysop install and start, then the full path again
    box.start_bus()
    check("s3d: the bus is back", wait_for(lambda: box.sh(["swarmbox-bus", "ping"]).returncode == 0, 15) is not None)
    r = box.sh(["swarmbox-addon", "install", "sysop"], timeout=90)
    check("s3d: swarmbox-addon install sysop again (prepare starts the service)", r.returncode == 0, r.stderr.strip()[-200:])
    box.sysop_launcher()
    check("s3d: the service is connected to the bus", box.wait_service(30))
    tabs = box.reset_tabs(claude=True)
    cw = tabs["claude"]
    since = time.time()
    h, state, note, _ = speak_and_end(box, br, "en-banana")
    ok = wait_for(lambda: ANSWER_EN.search(box.cap(cw)), 120)
    g = box.voice_goals(since)
    check("s3d: after the restart the microphone path works again: sent, and Claude answered", state == "sent" and ok is not None, (state, note, box.cap(cw)[-300:] if ok is None else ""))
    if g:
        box.wait_goal(g[0][0], 60)
    box.save("3d-claude-tab.txt", box.cap(cw))


# ====================================================================================================================== scenario 4
def term_has(br, text):
    return text in br.term_text()


def s4(box):
    box.scenario = "s4-panel-in-browser"
    box.configure()
    box.start_web()
    br = box.br
    br.open()
    # 4a landscape: the panel in the browser terminal, the veto key typed in the browser
    br.resize(1600, 900)
    time.sleep(1.5)
    tabs = box.reset_tabs(claude=True)
    cw = tabs["claude"]
    before = box.cap(cw)
    cols, rows = br.term_size()
    info("s4a landscape terminal", "%dx%d cells" % (cols, rows))
    since = time.time()
    h, state, note, _ = speak_and_end(box, br, "en-banana")
    ok = wait_for(lambda: "unless you veto it" in br.term_text(), 40, 0.1)
    check("s4a landscape: the panel is in the browser terminal with the countdown", ok is not None and state == "sent", (state, br.term_text()[-300:]))
    p = box.panel()
    geo = box.tmux("list-panes", "-s", "-t", "main", "-F", "#{pane_id} #{@swarmbox_sysop_panel} #{pane_left},#{pane_top} #{pane_width}x#{pane_height} window #{window_width}x#{window_height}")
    box.save("4a-geometry.txt", geo)
    pw, ph, ww, wh = [int(x) for x in re.search(r"1 \d+,\d+ (\d+)x(\d+) window (\d+)x(\d+)", geo).groups()] if re.search(r"1 \d+,\d+ (\d+)x(\d+) window", geo) else (0, 0, 0, 0)
    check("s4a landscape: the panel fits the window (%dx%d in %dx%d) and does not have the focus" % (pw, ph, ww, wh), p is not None and 0 < pw < ww and 0 < ph <= wh and p["active"] == "0", geo)
    br.screenshot("4a-landscape-panel-countdown")
    box.save("4a-landscape-terminal.txt", br.term_text())
    time.sleep(0.8)
    t = time.time()
    br.send_keys("\x01V")           # Ctrl+A then V, typed in the browser
    ok = wait_for(lambda: any(d.get("decision") == "vetoed" for g in box.voice_goals(since) for d in box.decisions(g[0])), 8)
    check("s4a: Ctrl+A V typed in the web terminal vetoes the action (audit says vetoed)", ok is not None, "%.2fs" % (time.time() - t))
    g = box.voice_goals(since)
    if g:
        box.wait_goal(g[0][0], 60)
    check("s4a: nothing was typed in the claude tab after the veto", "banana" not in box.cap(cw), box.cap(cw)[-300:])
    # 4b portrait: a phone-like terminal, the stop key
    box.idle(60)
    br.resize(520, 960, mobile=False)
    time.sleep(2.0)
    cols, rows = br.term_size()
    info("s4b portrait terminal", "%dx%d cells" % (cols, rows))
    tabs = box.reset_tabs(claude=True)
    cw = tabs["claude"]
    since = time.time()
    h, state, note, _ = speak_and_end(box, br, "en-banana")
    ok = wait_for(lambda: "unless you veto it" in br.term_text(), 60, 0.1)
    txt = br.term_text()
    br.screenshot("4b-portrait-panel-countdown")
    check("s4b portrait (%dx%d cells): the panel is in the browser terminal with the countdown" % (cols, rows), ok is not None and state == "sent", txt[-400:])
    geo = box.tmux("list-panes", "-s", "-t", "main", "-F", "#{pane_id} #{@swarmbox_sysop_panel} #{pane_left},#{pane_top} #{pane_width}x#{pane_height} window #{window_width}x#{window_height}")
    box.save("4b-geometry.txt", geo)
    m = re.search(r"1 \d+,\d+ (\d+)x(\d+) window (\d+)x(\d+)", geo)
    check("s4b portrait: the panel fits (no line wider than the terminal) and is inside the window", bool(m) and int(m.group(1)) <= int(m.group(3)) and max((len(x) for x in txt.splitlines()), default=0) <= cols, geo)
    box.save("4b-portrait-terminal.txt", txt)
    time.sleep(0.8)
    br.send_keys("\x01X")           # the stop key
    g = box.voice_goals(since)
    gid = g[0][0] if g else None
    st = box.wait_goal(gid, 30) if gid else None
    check("s4b: Ctrl+A X typed in the web terminal stops the goal (state stopped)", (st or {}).get("state") == "stopped", (st or {}).get("state"))
    check("s4b: nothing was typed in the claude tab", "banana" not in box.cap(cw), box.cap(cw)[-200:])
    br.resize(1600, 900)
    time.sleep(2.0)
    # 4c: typing in the claude tab while a goal arrives does not hit the panel. The user is in the claude tab (the active one) and types along; the goal is for the shell tab.
    box.idle(60)
    tabs = box.reset_tabs(claude=True)
    cw, sw = tabs["claude"], tabs["shell"]
    box.select(cw)
    time.sleep(1.4)
    br.js("term.focus()")
    since = time.time()
    rc, gid_pub, _ = box.pub("in the tab named shell run the command: echo hello-4c", "voice")
    actives = []
    for ch in "cxgqcxgqcxgq":                          # what a user typing along would send: veto, stop, goal, close
        br.send_keys(ch, gap=0)
        p = box.panel()
        if p:
            actives.append(p["active"] == "1")
        time.sleep(0.35)
    ok = wait_for(lambda: "hello-4c" in box.cap(sw).replace("echo hello-4c", ""), 120)
    st = box.wait_goal(gid_pub, 60)
    decisions = [d.get("decision") for d in box.decisions(gid_pub)]
    claude_box = box.cap(cw)
    box.save("4c-claude-tab.txt", claude_box)
    box.save("4c-terminal.txt", br.term_text())
    check("s4c: the panel opened while the user typed in the claude tab (seen %d times) and never had the focus" % len(actives), len(actives) > 0 and not any(actives), actives)
    check("s4c: the keys c x g q went to the input box of Claude Code, not to the panel", "cxgqcxgqcxgq" in claude_box.replace("\n", ""), claude_box[-300:])
    check("s4c: no veto, no stop, no new goal from those keys; the goal ended done and the shell tab ran the command", ok is not None and (st or {}).get("state") == "done"
          and "vetoed" not in decisions and "stop" not in decisions, (decisions, (st or {}).get("state"), box.cap(sw)[-200:]))
    box.tmux("send-keys", "-t", box.pane_of(cw), "C-c")          # clear the draft of the user (the box is not empty: one C-c, never two)
    # 4d: a click on the panel focuses it; then its own keys work
    box.idle(60)
    time.sleep(3.6)
    tabs = box.reset_tabs(claude=True)
    cw = tabs["claude"]
    br.js("term.focus()")
    since = time.time()
    rc, gid2, _ = box.pub('type the prompt "reply with exactly PONG-5" in the claude tab and send it', "voice")
    ok = wait_for(lambda: "unless you veto it" in br.term_text(), 60, 0.1)
    p = box.panel()
    check("s4d: the panel is open and not focused before the click", ok is not None and p is not None and p["active"] == "0", p)
    time.sleep(0.8)
    br.screenshot("4d-before-click")
    box.click_panel()
    ok = wait_for(lambda: (box.panel() or {}).get("active") == "1", 5, 0.1)
    check("s4d: a mouse click on the panel in the browser focuses it", ok is not None, box.panel())
    br.screenshot("4d-after-click-focused")
    time.sleep(0.3)
    br.send_keys("c")                 # the key of the focused panel
    ok = wait_for(lambda: any(d.get("decision") == "vetoed" for d in box.decisions(gid2)), 8)
    check("s4d: then its own key c vetoes the action", ok is not None, box.decisions(gid2))
    box.wait_goal(gid2, 60)
    box.tmux("select-pane", "-t", box.pane_of(cw))


# ====================================================================================================================== scenario 5
def raw(path, method="GET", headers=None, body=None, host=None, port=PORT):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=15)
    h = {"Host": host or "%s:%d" % (TUNNEL, PORT)}
    h.update(headers or {})
    try:
        c.request(method, path, body=body, headers=h)
        r = c.getresponse()
        data = r.read(2000)
        return r.status, data
    except OSError as e:
        return 0, repr(e).encode()
    finally:
        c.close()


def listeners():
    """TCP listeners of the container: [(address, port)]"""
    out = []
    for fn in ("/proc/net/tcp", "/proc/net/tcp6"):
        try:
            with open(fn) as f:
                for line in list(f)[1:]:
                    p = line.split()
                    if p[3] != "0A":
                        continue
                    a, port = p[1].rsplit(":", 1)
                    loop = a in ("0100007F", "00000000000000000000000001000000")
                    anyaddr = set(a) == {"0"}
                    out.append(("loopback" if loop else "any" if anyaddr else a, int(port, 16)))
        except OSError:
            pass
    return sorted(set(out))


def s5(box):
    box.scenario = "s5-tunnel"
    box.configure()
    box.start_web()
    box.br.close()
    br = Browser(box, "en-hello", host=TUNNEL, secure=True, tag="tunnel")
    box.br = br
    ok = br.open()
    check("s5: the page loads through another host name (%s) and shows the button" % TUNNEL, ok, br.term_text()[-200:])
    br.screenshot("5-tunnel-page")
    w = box.watch_start(["swarmbox-bus", "sub", "goal"], "tunnel-watcher")
    wait_for(lambda: any(t["topic"] == "goal" and t["subscribers"] == 2 for t in box.topics()), 8, 0.1)
    since = time.time()
    h, state, note, _ = speak_and_end(box, br, "en-hello")
    time.sleep(1.0)
    gs = box.voice_goals(since)
    check("s5: speaking through the tunnel-like host works: sent, the sysop got the goal", state == "sent" and len(gs) == 1, (state, gs))
    if gs:
        box.wait_goal(gs[0][0], 60)
    # the four routes
    f = lambda p, **k: br.fetch("http://%s:%d%s" % (TUNNEL, PORT, p), **k)       # noqa: E731
    r = {p: f(p) for p in ("/voice/page.js", "/voice/page.css", "/voice/health")}
    check("s5: GET /voice/page.js, /voice/page.css, /voice/health answer 200 from the page", all(x.get("status") == 200 for x in r.values()), r)
    check("s5: /voice/health gives only {ok}", json.loads(r["/voice/health"]["text"]) == {"ok": True}, r["/voice/health"])
    wavb64 = base64.b64encode(open(os.path.join(WAVS, "en-hello.wav"), "rb").read()).decode()
    silent = base64.b64encode(silence_wav()).decode()
    g_before = box.goal_events()
    ra = f("/voice/audio", method="POST", body=silent, headers={"Content-Type": "audio/wav"})
    time.sleep(0.5)
    check("s5: POST /voice/audio with a second of silence: answered with a state only, nothing_heard, and NO goal (the real Whisper writes 'you' for silence: the gate in voice)",
          ra.get("status") == 200 and json.loads(ra["text"]).get("state") == "nothing_heard" and set(json.loads(ra["text"])) <= {"ok", "state", "message"}
          and box.goal_events() == g_before, (ra, box.goal_events() - g_before))
    others = ["/voice/", "/voice", "/voice/state", "/voice/goal", "/voice/goals", "/voice/bus", "/voice/pub", "/voice/sub", "/voice/tabs", "/voice/tab",
              "/voice/approve", "/voice/sysop", "/voice/panel", "/voice/models", "/voice/config", "/voice/%2e%2e/health", "/voice/../health",
              "/voice/page.js/../audio", "/voice//audio", "/voice/AUDIO", "/voice/audio/", "/voice/health/x", "/voice/audio?x=1/../state"]
    codes = {p: raw(p, headers={"Origin": "http://%s:%d" % (TUNNEL, PORT)})[0] for p in others}
    check("s5: every other path under /voice/ is 404 (or 405 for audio), never 200", all(c in (404, 405, 400) for c in codes.values()), codes)
    bad_methods = {m: raw("/voice/audio", method=m, headers={"Origin": "http://%s:%d" % (TUNNEL, PORT)})[0] for m in ("GET", "PUT", "DELETE", "OPTIONS")}
    bad_methods["POST /voice/health"] = raw("/voice/health", method="POST", headers={"Origin": "http://%s:%d" % (TUNNEL, PORT), "Content-Length": "0"})[0]
    check("s5: wrong methods on the listed paths are 405 (OPTIONS too), never 200", all(c in (404, 405) for c in bad_methods.values()), bad_methods)
    # nothing of the box answers on the web: the bus, the tabs, the sysop
    web = {p: raw(p, headers={"Origin": "http://%s:%d" % (TUNNEL, PORT)}) for p in ("/bus", "/tabs", "/sysop", "/api/goal", "/goal", "/topics", "/swarmbox-bus", "/tmp/swarmbox/bus.sock")}
    leaked = {p: v[1][:80] for p, v in web.items() if b"subscribers" in v[1] or b"receivers" in v[1] or b'"tab"' in v[1] or b"sysop" in v[1].lower()}
    check("s5: the bus, the tabs and the sysop are not reachable from the web (no such route; ttyd answers 404 or its page)", not leaked, leaked or {p: v[0] for p, v in web.items()})
    ls = [x for x in listeners() if x[1] != br.dbg]        # not the debugging port of the test's own browser
    nonloop = [x for x in ls if x[0] != "loopback"]
    check("s5: the only listener that is not on the loopback address is the web port %d (the one the box publishes)" % PORT, [x[1] for x in nonloop] == [PORT], ls)
    check("s5: the bus is a unix socket (no TCP listener for it): listeners are ttyd, the voice service and the front only", sorted(x[1] for x in ls) == sorted([PORT, 7680, 17682]), ls)
    # the service behind the front refuses another Host and an Origin (DNS rebinding, a page of another site)
    s_host = raw("/voice/health", host="%s:17682" % TUNNEL, port=17682)[0]
    check("s5: the voice service itself refuses a Host that is not loopback", s_host in (400, 403, 404), s_host)
    # a cross-origin POST of audio
    st1 = raw("/voice/audio", method="POST", headers={"Content-Type": "audio/wav", "Origin": "http://%s:8099" % EVIL}, body=silence_wav())[0]
    st2 = raw("/voice/audio", method="POST", headers={"Content-Type": "audio/wav", "Origin": "null"}, body=silence_wav())[0]
    st3 = raw("/voice/audio", method="POST", headers={"Content-Type": "text/plain", "Origin": "http://%s:%d" % (TUNNEL, PORT)}, body=silence_wav())[0]
    st4 = raw("/voice/audio", method="POST", headers={"Content-Type": "audio/wav", "Origin": "http://%s:%d" % (TUNNEL, PORT)}, body=silence_wav())[0]
    check("s5: a POST with the Origin of another site, with Origin null, or without the WAV content type is refused (%s, %s, %s); the same site is served (%s)" % (st1, st2, st3, st4),
          st1 == 403 and st2 == 403 and st3 in (400, 403, 415) and st4 == 200, (st1, st2, st3, st4))
    # the same from a real page of another site
    n0 = len(box.lines(w[1]))
    g0 = box.goal_events()
    evil = EvilSite(wavb64)
    br2 = Browser(box, "en-hello", host=TUNNEL, tag="evil")
    try:
        br2.open_plain("http://%s:%d/" % (EVIL, evil.port))
        res = wait_for(lambda: br2.js("window.__res || null"), 20, 0.3)
        time.sleep(1.5)
        r1 = (res[1] if res else None) or {}
        box.save("5-cross-origin-result.json", r1)
        check("s5: a page of another site cannot POST audio (cors: the fetch fails; no-cors: the front refuses it)", r1.get("cors", {}).get("err") and r1.get("nocors", {}).get("err") is not None
              or (r1.get("nocors") and r1["nocors"].get("type") == "opaque"), r1)
    finally:
        br2.close()
        evil.close()
    check("s5: and no goal came out of it: nothing reached the bus or the sysop", len(box.lines(w[1])) == n0 and box.goal_events() == g0, (len(box.lines(w[1])) - n0, box.goal_events() - g0))
    box.kill_group(w[0])
    box.br.close()
    box.br = Browser(box, "en-banana")
    box.br.open()


def silence_wav(seconds=1.0):
    import io
    b = io.BytesIO()
    with wave.open(b, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"\x00\x00" * int(16000 * seconds))
    return b.getvalue()


class EvilSite:
    """a web page of ANOTHER site (another host name and port) that tries to POST audio to the tunnel host"""

    def __init__(self, wavb64):
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        target = "http://%s:%d/voice/audio" % (TUNNEL, PORT)
        page = ("<!doctype html><title>other site</title><script>(async () => { const r = {}; "
                "const wav = await (await fetch('/w.wav')).blob(); "
                "try { const x = await fetch('%s', {method: 'POST', headers: {'Content-Type': 'audio/wav'}, body: wav}); r.cors = {status: x.status}; } catch (e) { r.cors = {err: String(e)}; } "
                "try { const x = await fetch('%s', {method: 'POST', mode: 'no-cors', body: wav}); r.nocors = {type: x.type, status: x.status}; } catch (e) { r.nocors = {err: String(e)}; } "
                "window.__res = r; })()</script>" % (target, target)).encode()
        wav = base64.b64decode(wavb64)

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                body, ct = (wav, "audio/wav") if self.path == "/w.wav" else (page, "text/html")
                self.send_response(200)
                self.send_header("Content-Type", ct)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


def _open_plain(self, url):
    if self.page is not None:
        self.page.s.close()
    req = urllib.request.Request("http://127.0.0.1:%d/json/new?about:blank" % self.dbg, method="PUT")
    with urllib.request.urlopen(req, timeout=10) as r:
        tab = json.load(r)
    self.page = CDP(tab["webSocketDebuggerUrl"])
    self.page.call("Page.enable")
    self.page.call("Runtime.enable")
    self.page.call("Page.navigate", url=url)


Browser.open_plain = _open_plain


# ====================================================================================================================== scenario 6
def approve_in_browser(box, br):
    """what the user does for an approval: Ctrl+A a (opens the prompt, gives the panel the focus), then the word run and Enter"""
    br.send_keys("\x01a")
    wait_for(lambda: (box.panel() or {}).get("active") == "1", 5, 0.1)
    time.sleep(0.8)
    br.send_keys("run\r")


def await_rm_approval(box, br, gid, others, timeout=150):
    """Waits for the approval of the `rm`. An exploratory command the brain types first (`ls`, `pwd`) may be held for approval too: the user approves it (typed in the
    panel, as for any approval) and its text is added to `others`. Returns the decision of the rm, or None."""
    end = time.time() + timeout
    seen = set()
    while time.time() < end:
        st = box.goal_state(gid) or {}
        if st.get("state") in ("done", "failed", "stopped"):
            return None
        if "NOT sent unless you allow it" in box.panel_text():
            waiting = [d for d in box.decisions(gid) if d.get("decision") == "waiting" and d.get("mode") == "approve"]
            if waiting:
                last = waiting[-1]
                if re.search(r"\brm\b", last.get("text", "")):
                    return last
                if last["id"] not in seen:
                    seen.add(last["id"])
                    others.append(last.get("text", ""))
                    time.sleep(1.0)
                    approve_in_browser(box, br)
        time.sleep(0.3)
    return None


def s6(box):
    box.scenario = "s6-approval"
    box.configure(approval_timeout=90)
    box.start_web()
    br = box.br
    br.open()
    br.resize(1600, 900)
    time.sleep(1.5)
    tabs = box.reset_tabs(claude=False)
    sw = tabs["shell"]
    E.mkbuild(box)
    box.type_line(sw, "ls")
    time.sleep(0.6)
    build = os.path.join(box.throw, "build")
    # 6a: spoken ('delete the build folder'); nothing runs without the approval typed in the panel
    since = time.time()
    h, state, note, _ = speak_and_end(box, br, "en-rm")
    g = wait_for(lambda: box.voice_goals(since), 30)
    g = g[1] if g else []
    gid = g[0][0] if g else None
    info("s6a Whisper transcript", repr(g[0][1] if g else None))
    others = []
    rm = await_rm_approval(box, br, gid, others) if gid else None
    ok = rm
    check("s6a: the spoken goal reached the sysop and the approval prompt of the rm is in the panel (state %s)" % state, state == "sent" and rm is not None and gid is not None, box.panel_text()[-400:])
    info("s6a commands approved before the rm (held as medium: chained)", repr(others))
    txt = box.panel_text()
    box.save("6a-panel-approval.txt", txt)
    br.screenshot("6a-approval-in-browser")
    check("s6a: the action waiting is `%s`, rated HIGH by the host" % (rm or {}).get("text"), "HIGH" in txt and bool(rm) and rm.get("verdict", {}).get("level") == "high", txt[-300:])
    time.sleep(6)
    check("s6a: 6 seconds later nothing ran: the directory build exists and the shell tab shows no rm", os.path.isdir(build) and "rm " not in box.cap(sw).split("ls")[-1], box.cap(sw)[-300:])
    # the browser cannot approve: another spoken sentence, and every call the page can make
    h2, state2, note2, _ = speak_and_end(box, br, "pt-yes")
    tries = {p: br.fetch("/voice/" + p, method="POST", body=base64.b64encode(silence_wav()).decode(), headers={"Content-Type": "audio/wav"}) for p in ("approve", "run", "allow", "sysop/approve")}
    tries["GET /approve"] = br.fetch("/approve")
    time.sleep(1.0)
    check("s6a: speaking 'sim, aprova' (a new goal) and the page's own calls do not approve: the directory still exists, the approval still waits",
          state2 in ("sent", "busy") and os.path.isdir(build) and "NOT sent unless you allow it" in box.panel_text() and all(v.get("status") in (404, 405) for k, v in tries.items() if k != "GET /approve"),
          (state2, os.path.isdir(build), {k: v.get("status") for k, v in tries.items()}))
    decisions = [d.get("decision") for d in box.decisions(gid)]
    check("s6a: the audit has no approval so far", "approved" not in decisions, decisions)
    # the user approves in the panel, from the web terminal: Ctrl+A a, then the word run and Enter
    t = time.time()
    br.send_keys("\x01a")
    ok = wait_for(lambda: (box.panel() or {}).get("active") == "1", 5, 0.1)
    check("s6a: Ctrl+A a typed in the web terminal opens the approval prompt and gives the panel the focus", ok is not None, box.panel())
    time.sleep(0.8)
    br.send_keys("run\r")
    ok = wait_for(lambda: not os.path.isdir(build), 40, 0.2)
    check("s6a: after `run` and Enter typed in the panel the command ran: the directory build is gone", ok is not None, "%.1fs" % (time.time() - t))
    decisions = [d.get("decision") for d in box.decisions(gid)]
    check("s6a: the audit says approved", "approved" in decisions, decisions)
    box.save_goal("6a", gid)
    br.send_keys("\x01X")             # the second goal (the spoken 'sim, aprova') and any queue: stop
    time.sleep(1.0)
    box.wait_goal(gid, 60)
    time.sleep(2.0)
    box.tmux("send-keys", "-t", box.pane_of(sw), "Escape")
    # 6b: the same goal, refused with the veto key
    box.idle(90)
    time.sleep(3.6)
    tabs = box.reset_tabs(claude=False)
    sw = tabs["shell"]
    E.mkbuild(box)
    box.type_line(sw, "ls")
    time.sleep(0.6)
    since = time.time()
    h, state, note, _ = speak_and_end(box, br, "en-rm")
    g = wait_for(lambda: box.voice_goals(since), 30)
    g = g[1] if g else []
    gid = g[0][0] if g else None
    rm = await_rm_approval(box, br, gid, []) if gid else None
    ok = rm
    time.sleep(1.0)
    br.send_keys("\x01V")
    ok2 = wait_for(lambda: any(d.get("decision") in ("denied", "refused", "vetoed") and d.get("id") == rm.get("id") for d in box.decisions(gid)), 10) if gid and rm else None
    box.wait_goal(gid, 60) if gid else None
    check("s6b: Ctrl+A V from the web terminal refuses the approval; the directory build is still there", ok is not None and ok2 is not None and os.path.isdir(build),
          (box.decisions(gid)[-3:] if gid else None, os.path.isdir(build)))


    # 6c: the same sentence in Portuguese, as the task words it ('apaga a pasta build'). Whisper small does not hear espeak's Portuguese 'build' (it writes 'Will',
    # 'buiude'...), so what the brain makes of it is not guaranteed: what is checked is the safety, never the outcome. A command that is typed waits for the approval.
    box.idle(90)
    time.sleep(3.6)
    tabs = box.reset_tabs(claude=False)
    sw = tabs["shell"]
    E.mkbuild(box)
    box.type_line(sw, "ls")
    time.sleep(0.6)
    br.js("term.focus()")
    since = time.time()
    h, state, note, _ = speak_and_end(box, br, "pt-rm")
    g = box.voice_goals(since)
    gid = g[0][0] if g else None
    info("s6c Whisper transcript", repr(g[0][1] if g else None))
    end = time.time() + 90
    asked = False
    while time.time() < end and gid:
        st = box.goal_state(gid) or {}
        if "NOT sent unless you allow it" in box.panel_text():
            asked = True
            break
        if st.get("state") in ("done", "failed", "stopped"):
            break
        time.sleep(0.3)
    ran = not os.path.isdir(build) or "rm " in box.cap(sw).split("ls")[-1]
    info("s6c outcome", "approval asked: %s; the goal state: %s" % (asked, (box.goal_state(gid) or {}).get("state")))
    check("s6c: the Portuguese sentence: sent, and nothing was removed without an approval (the directory is there while the approval waits or the goal ended)", state == "sent" and (asked or not ran) and os.path.isdir(build),
          (state, asked, ran, box.cap(sw)[-200:]))
    if asked:
        br.send_keys("\x01V")
        box.wait_goal(gid, 60)
    else:
        box.wait_goal(gid, 90) if gid else None
    check("s6c: the directory build is still there at the end", os.path.isdir(build))


# ====================================================================================================================== scenario 7
def s7(box):
    box.scenario = "s7-screens-not-on-the-bus"
    box.configure()
    box.start_web()
    box.br.open()
    path = os.path.join(WORK, "watch-s1.out")
    if not box.watch_proc:      # scenario 1 did not run in this process: watch from here
        box.watch_proc = box.watch_start(["swarmbox-bus", "watch"], "watch-s1")
        path = box.watch_proc[1]
    tabs = box.reset_tabs(claude=True)
    sw, cw = tabs["shell"], tabs["claude"]
    shell_secret(box, sw)
    box.select(sw)
    time.sleep(1.4)
    since = time.time()
    h, state, note, _ = speak_and_end(box, box.br, "en-hello")        # a spoken goal; its words do not matter, so the typed goal below says what to read
    time.sleep(0.5)
    rc, gid, _ = box.pub("read the screen of the tab named shell and tell me, with say, what is on its last lines; then finish", "voice")
    st = box.wait_goal(gid, 90)
    box.idle(60)
    reads = [c for c in box.calls(gid) if c["tool"] in ("read_tab", "list_tabs")]
    read_shell = [c for c in reads if c["tool"] == "read_tab"]
    msgs = box.lines(path)
    raw = box.read(path)
    pubs = [m for m in msgs if m.get("kind") == "pub"]
    audit_text = json.dumps([e for e in box.audit(gid)], ensure_ascii=False)
    box.save("7-bus-watch.jsonl", raw)
    box.save("7-reads.json", [{"tool": c["tool"], "args": c["args"], "text": c["text"][:600]} for c in reads])
    check("s7: the sysop read the shell tab (read_tab) during the goal", bool(read_shell), [c["tool"] for c in box.calls(gid)])
    def body_ok(m):
        b = m["envelope"].get("body")
        return isinstance(b, str) or (isinstance(b, dict) and set(b) <= {"text"})
    check("s7: the bus carried only goal messages (a topic of the run, a body that is the text or {text}, source voice or cli), nothing else",
          bool(pubs) and len(pubs) == len(msgs) and all(m["topic"] in TOPICS_USED and body_ok(m) and m["envelope"].get("source") in ("voice", "cli") for m in pubs), (len(pubs), len(msgs)))
    check("s7: no secret on the bus (the planted fake key, any 'sk-' string)", SECRET not in raw and "sk-ant" not in raw and "DEMO_KEY" not in raw, "")
    seen = [w for w in ("bypass permissions", "esc to interrupt", "unless you veto it", "NOT sent unless", "Claude Code", "PS1", "$ export", "/work/throw", "/work/proj", "❯", "DEMO_KEY") if w in raw]
    check("s7: no screen text, no tab content, no path of a tab, no panel text on the bus", not seen, seen)
    reply_text = " ".join(c["text"] for c in read_shell)
    check("s7: what the sysop read had the secret removed (the filter of swarmbox-tabs): the screen it got and the audit have no key", SECRET not in reply_text and SECRET not in audit_text and "FAKEFAKE" not in audit_text,
          reply_text[:300])
    check("s7: the shell tab itself shows the key (so the filter, not luck, is what hid it)", "FAKEFAKE" in box.cap(sw).replace("\n", ""), box.cap(sw)[-200:])
    transcripts = [m["envelope"]["body"].get("text", "") if isinstance(m["envelope"].get("body"), dict) else m["envelope"].get("body") for m in pubs]
    info("s7 the messages that passed", json.dumps(transcripts, ensure_ascii=False))
    E.REPORT["s7"] = {"messages": len(msgs), "texts": transcripts}


# ====================================================================================================================== scenarios 8 to 10: the new page and the always-up panel
PROBE = """(() => {
  const R = e => { if (!e) return null; const b = e.getBoundingClientRect(); return {left: b.left, top: b.top, right: b.right, bottom: b.bottom, w: b.width, h: b.height}; };
  const q = s => document.querySelector(s);
  const scr = q('.xterm-screen').getBoundingClientRect();
  const ch = scr.height / term.rows, cw = scr.width / term.cols;
  const b = term.buffer.active, line = b.getLine(b.baseY + term.rows - 1), txt = line ? line.translateToString(true) : '';
  const m = /\\d\\d:\\d\\d/.exec(txt);
  const status = {left: scr.left, right: scr.right, top: scr.top + (term.rows - 1) * ch, bottom: scr.bottom}; status.w = status.right - status.left; status.h = status.bottom - status.top;
  const clock = m ? {left: scr.left + m.index * cw, right: scr.left + (m.index + 5) * cw, top: status.top, bottom: status.bottom} : null;
  let covered = null;
  if (clock) { const e = document.elementFromPoint((clock.left + clock.right) / 2, (clock.top + clock.bottom) / 2); covered = e ? (e.closest('#swarmbox-strip') ? 'strip' : 'terminal') : 'nothing'; }
  const note = q('#swarmbox-strip .sb-note');
  return {win: [innerWidth, innerHeight], docw: document.documentElement.scrollWidth, rows: term.rows, cols: term.cols, status: status, statusText: txt, clock: clock, covered: covered,
          strip: R(q('#swarmbox-strip')), stripShown: !!q('#swarmbox-strip') && !q('#swarmbox-strip').hidden, container: R(q('#terminal-container')), screen: R(q('.xterm-screen')),
          mic: R(q('#swarmbox-voice-mic')), note: note && !note.hidden ? R(note) : null, coarse: matchMedia('(pointer: coarse)').matches,
          keys: Array.from(document.querySelectorAll('#swarmbox-strip .sb-key')).map(e => Object.assign({t: e.textContent}, R(e))).filter(k => k.w > 0),
          render: {dpr: devicePixelRatio, scale: window.visualViewport ? visualViewport.scale : null, fontSize: term.options.fontSize, vvw: window.visualViewport ? visualViewport.width : null,
                   canvases: Array.from(document.querySelectorAll('.xterm-screen canvas')).map(c => [c.width, c.height, c.style.width, c.style.height]),
                   cell: [scr.width / term.cols, scr.height / term.rows]}};
})()"""


def overlap(a, b, eps=0.5):
    """True when two bounding boxes share area"""
    return bool(a and b and a["left"] < b["right"] - eps and b["left"] < a["right"] - eps and a["top"] < b["bottom"] - eps and b["top"] < a["bottom"] - eps)


def phone(box, kind="portrait", wav="en-banana"):
    """a new browser (the fake microphone plays `wav`) as a phone: portrait 390x844 or landscape 844x390, touch, coarse pointer; or desktop"""
    if box.br:
        box.br.close()
    box.br = Browser(box, wav, tag=kind)
    ok = box.br.device(kind)
    time.sleep(1.5)
    return box.br, ok


def s8(box):
    """(a) the microphone never lies over the status bar of tmux and its clock: bounding boxes at desktop, phone portrait and phone landscape, a screenshot of each"""
    box.scenario = "s8-geometry"
    box.configure()
    box.start_web()
    tabs = box.reset_tabs(claude=False, extra=("two",))
    box.select(tabs["shell"])
    for kind in ("desktop", "portrait", "landscape"):
        br, ok = phone(box, kind)
        check("s8 %s: the page loads with the terminal and the microphone" % kind, ok, br.term_text()[-200:])
        time.sleep(1.5)
        g = br.js(PROBE)
        box.save("8-%s-probe.json" % kind, g)
        br.screenshot("8-%s-idle" % kind)
        mic, strip, st, ck = g["mic"], g["strip"], g["status"], g["clock"]
        check("s8 %s: the controls strip is there (%s keys, coarse pointer %s)" % (kind, len(g["keys"]), g["coarse"]), g["stripShown"] and g["coarse"] == (kind != "desktop")
              and (len(g["keys"]) == 0) == (kind == "desktop"), (g["stripShown"], g["coarse"], len(g["keys"])))
        check("s8 %s: the microphone is inside the strip, inside the window and at least 44 px (%.0fx%.0f)" % (kind, mic["w"], mic["h"]),
              mic["w"] >= 43.9 and mic["h"] >= 43.9 and mic["left"] >= strip["left"] - 0.5 and mic["right"] <= strip["right"] + 0.5 and mic["top"] >= strip["top"] - 0.5
              and mic["bottom"] <= strip["bottom"] + 0.5 and mic["right"] <= g["win"][0] + 0.5 and mic["bottom"] <= g["win"][1] + 0.5, (mic, strip, g["win"]))
        check("s8 %s: the microphone does not overlap the status bar of tmux (its last row)" % kind, not overlap(mic, st), (mic, st))
        check("s8 %s: the clock of the status bar is on its row (%r) and nothing of the strip is over it" % (kind, g["statusText"].strip()[-18:]), ck is not None and g["covered"] == "terminal"
              and not overlap(mic, ck) and not overlap(strip, ck), (ck, g["covered"], g["statusText"]))
        check("s8 %s: the whole strip is below the last row of the terminal and the terminal ends where the strip begins" % kind,
              g["screen"]["bottom"] <= strip["top"] + 0.5 and g["container"]["bottom"] <= strip["top"] + 0.5 and strip["bottom"] <= g["win"][1] + 0.5, (g["screen"], g["container"], strip))
        check("s8 %s: the microphone overlaps no key button and there is no horizontal scroll" % kind, not any(overlap(mic, k) for k in g["keys"]) and g["docw"] <= g["win"][0], (mic, g["docw"]))
        rows = wait_for(lambda: box.tmux("list-clients", "-F", "#{client_height}").split()[:1] == [str(g["rows"])], 8, 0.25)
        check("s8 %s: tmux sees exactly the %d rows xterm shows (the strip took its place out of the window)" % (kind, g["rows"]), rows is not None, box.tmux("list-clients", "-F", "#{client_width}x#{client_height}"))
        # a sentence of the voice page: it covers the keys and ends where the microphone begins
        br.js("window.swarmboxStrip.note('Nobody is listening', 'warn')")
        time.sleep(0.3)
        g2 = br.js(PROBE)
        br.screenshot("8-%s-note" % kind)
        check("s8 %s: the sentence of the strip ends before the microphone (no overlap) and is inside the strip" % kind,
              g2["note"] is not None and not overlap(g2["note"], g2["mic"]) and g2["note"]["right"] <= g2["mic"]["left"] + 0.5 and g2["note"]["bottom"] <= g2["strip"]["bottom"] + 0.5, (g2["note"], g2["mic"]))
        br.js("window.swarmboxStrip.note('')")
        # the microphone while recording: its glow is a box-shadow and the strip does not grow
        x, y = br.mic_center()
        before = g["strip"]["h"]
        if kind != "desktop":
            br.page.call("Input.dispatchTouchEvent", type="touchStart", touchPoints=[{"x": x, "y": y}])
        else:
            br.mouse("mouseMoved", x, y)
            br.mouse("mousePressed", x, y)
        wait_for(lambda: br.light()[0] == "recording", 3, 0.02)
        g3 = br.js(PROBE)
        br.screenshot("8-%s-recording" % kind)
        state = br.light()[0]
        if kind != "desktop":
            br.page.call("Input.dispatchTouchEvent", type="touchEnd", touchPoints=[])
        else:
            br.mouse("mouseReleased", x, y)
        check("s8 %s: recording (state %s): the strip keeps its height and the microphone its place, clear of the status bar" % (kind, state),
              state in ("recording", "starting") and abs(g3["strip"]["h"] - before) < 1 and not overlap(g3["mic"], g3["status"]) and abs(g3["mic"]["left"] - mic["left"]) < 1, (state, before, g3["strip"]))
        wait_for(lambda: br.light()[0] in FINAL_LIGHTS or br.light()[0] == "idle", 20, 0.2)
        box.sh(["swarmbox-sysop", "stop"])          # the first half second of the file is silence, so nothing should be published; if a goal was made anyway it ends here
        box.idle(30)
        E.REPORT.setdefault("s8", {})[kind] = {"viewport": g["win"], "cells": [g["cols"], g["rows"]], "strip_h": round(g["strip"]["h"], 1), "mic": [round(mic["w"]), round(mic["h"])],
                                              "status_row": [round(st["top"], 1), round(st["bottom"], 1)], "mic_top": round(mic["top"], 1)}
        info("s8 %s" % kind, "viewport %dx%d, terminal %dx%d cells, strip %.0f px high, status row y %.0f..%.0f, microphone y %.0f..%.0f x %.0f..%.0f; render %s"
             % (g["win"][0], g["win"][1], g["cols"], g["rows"], g["strip"]["h"], st["top"], st["bottom"], mic["top"], mic["bottom"], mic["left"], mic["right"], json.dumps(g["render"])))
    phone(box, "desktop")


def panel_rows(box, win=None):
    """[(panel pane height, width, window height, window width, pane_top)] of the panels (of one window)"""
    out = []
    for row in box.tmux("list-panes", "-s", "-t", "main", "-F", "#{window_id}|#{@swarmbox_sysop_panel}|#{pane_height}|#{pane_width}|#{window_height}|#{window_width}|#{pane_top}|#{pane_active}").splitlines():
        w, mark, ph, pw, wh, ww, top, act = row.split("|")
        if mark == "1" and (win is None or w == win):
            out.append((int(ph), int(pw), int(wh), int(ww), int(top), act == "1"))
    return out


def s9(box):
    """(b) the thumb path on a phone: tap Panel (hide, show), tap Esc to interrupt a busy Claude Code tab, hold the microphone and speak, see the panel idle, the goal and the answer;
    (c) the panel in portrait is 30 % and fits; (d) typing in the Claude tab while a goal arrives never reaches the panel; (e) the idle panel and the last goal"""
    box.scenario = "s9-thumb"
    box.configure(countdown=2)
    box.start_web()
    tabs = box.reset_tabs(claude=True)
    cw, sw = tabs["claude"], tabs["shell"]
    br, ok = phone(box, "portrait", "en-banana")
    check("s9: the phone page (390x844, touch) loads with the strip, the keys and the microphone", ok and br.strip_button("Esc") is not None and br.strip_button("Panel") is not None, br.term_text()[-200:])
    box.select(cw)
    time.sleep(1.5)
    br.js("term.focus()")
    cols, rows = br.term_size()
    info("s9 terminal on the phone", "%dx%d cells" % (cols, rows))
    # (c) and (e): the panel in portrait
    wait_for(lambda: "no goal." in br.term_text(), 15, 0.3)
    txt = br.term_text()
    br.screenshot("9-1-idle-portrait")
    box.save("9-1-idle-terminal.txt", txt)
    pr = panel_rows(box, cw)
    ph, pw, wh, ww, top, act = pr[0] if pr else (0, 0, 0, 0, 0, True)
    want = wh * 30 // 100
    want = want if want >= 8 else max(1, min(8, wh // 2))
    check("s9c: the panel of the window in portrait is at the bottom, 30%% of its height (%d of %d lines, expected about %d), at least 8 and no more than half" % (ph, wh, want),
          bool(pr) and abs(ph - want) <= 1 and ph >= min(8, wh // 2) and ph <= wh // 2 + 1 and top > wh // 2 - 1 and pw == ww, pr)
    check("s9c: the panel fits in %d columns: its head, the idle line and the key line are on the screen, nothing wider than the terminal" % cols,
          all(x in txt for x in ("no goal.", "Ctrl+A")) and max((len(x) for x in txt.splitlines()), default=0) <= cols and not act, txt[-500:])
    check("s9e: the idle panel has its head with IDLE or the last result, 'no goal', and the key line [g] Goal [q] Hide (a pane of 8 lines at 28 columns drops the long lines first)",
          ("IDLE" in txt or "DONE" in txt or "FAILED" in txt or "STOPPED" in txt) and "SYSOP" in txt and "[g] Goal" in txt, txt[-500:])
    ptxt = box.panel_text()
    box.save("9-1-idle-panel.txt", ptxt)
    # (b1) Panel hides and shows
    n0 = len(panel_rows(box))
    t = time.time()
    br.tap_key("Panel")
    gone = wait_for(lambda: not panel_rows(box), 8, 0.1)
    t_hide = time.time() - t
    time.sleep(0.5)
    br.screenshot("9-2-panel-hidden")
    check("s9b: tapping Panel hides the panels of all windows (%d before, %.1f s)" % (n0, t_hide), gone is not None and "no goal." not in br.term_text(), (panel_rows(box), br.term_text()[-200:]))
    t = time.time()
    br.tap_key("Panel")
    up = wait_for(lambda: box.panels_up() and "no goal." in br.term_text(), 15, 0.1)
    t_show = time.time() - t
    check("s9b: tapping Panel again shows them in every window and the idle screen is back in the browser (%.1f s)" % t_show, up is not None, (panel_rows(box), br.term_text()[-200:]))
    check("s9b: the focus stayed in the Claude tab through both taps (the panel is not active, the Claude pane is)",
          all(not r[5] for r in panel_rows(box)) and box.tmux("display-message", "-p", "-t", box.pane_of(cw), "#{pane_active}") == "1", panel_rows(box))
    # (b2) Esc interrupts a busy Claude Code
    br.send_keys("write an essay of 3000 words on the history of lighthouses, no tools, no preamble\r", gap=0.01)
    def streaming():
        # at this width (28 columns) Claude Code's footer shows no `esc to interrupt` and no `·` at all, so busy is seen by the screen moving
        a = box.cap(cw)
        time.sleep(0.8)
        b = box.cap(cw)
        return a != b and re.search(r"^❯\s*$", b, re.M) is not None        # the screen moves and the prompt has left the input box: Claude is working on it
    busy = wait_for(streaming, 60, 0.1)
    check("s9b: Claude Code in the tab is busy (typed on the phone keyboard; its screen is streaming)", busy is not None, box.cap(cw)[-300:])
    t = time.time()
    br.tap_key("Esc")

    def stopped_now():
        c = box.cap(cw)
        if "Interrup" not in c and not re.search(r"^❯\s+write an essay", c, re.M):         # "Interrupted" is cut at 28 columns; an Esc before the first words
            return False                          # arrive gives the prompt back in the input box instead
        a = box.cap(cw)
        time.sleep(1.0)
        return a == box.cap(cw)
    stopped = wait_for(stopped_now, 15, 0.1)
    t_esc = time.time() - t
    box.save("9-3-claude-after-esc.txt", box.cap(cw))
    br.screenshot("9-3-after-esc")
    check("s9b: tapping Esc interrupts the busy Claude Code tab (%.1f s)" % t_esc, stopped is not None, box.cap(cw)[-400:])
    check("s9b: the Esc went to the Claude pane, not to the panel (the panel is idle, not focused)", "no goal." in box.panel_text() and not any(r[5] for r in panel_rows(box)), box.panel_text()[-200:])
    # (d) typing along while a goal arrives, on the phone
    since = time.time()
    rc, gid_d, _ = box.pub("in the tab named shell run the command: echo hello-9d", "voice")
    actives, seen_goal = [], False
    for ch in "cxgqcxgqcxgq":
        br.send_keys(ch, gap=0)
        actives += [r[5] for r in panel_rows(box, cw)]
        seen_goal = seen_goal or "unless you veto it" in br.term_text()
        time.sleep(0.35)
    ok = wait_for(lambda: "hello-9d" in box.cap(sw).replace("echo hello-9d", ""), 120)
    st = box.wait_goal(gid_d, 60)
    decisions = [d.get("decision") for d in box.decisions(gid_d)]
    claude_box = box.cap(cw)
    box.save("9-4-claude-tab.txt", claude_box)
    check("s9d: the goal arrived while the user typed on the phone (panel seen %d times) and the panel never had the focus" % len(actives), len(actives) > 0 and not any(actives), actives)
    check("s9d: the keys c x g q went to the input box of Claude Code, not to the panel", "cxgqcxgqcxgq" in claude_box.replace("\n", ""), claude_box[-300:])
    check("s9d: no veto, no stop, no new goal from those keys; the goal ended done and the shell tab ran the command", ok is not None and (st or {}).get("state") == "done"
          and "vetoed" not in decisions and "stop" not in decisions, (decisions, (st or {}).get("state"), box.cap(sw)[-200:]))
    br.tap_key("^C")            # the thumb clears the draft
    cleared = wait_for(lambda: "cxgq" not in box.cap(cw), 5, 0.2)
    check("s9b: tapping ^C clears the draft of the Claude tab", cleared is not None, box.cap(cw)[-200:])
    box.idle(60)
    box.select(cw)
    time.sleep(1.4)
    # (b3) hold the microphone with a finger and speak: the panel idle, then the goal, then the answer
    before_panel = box.panel_text()
    before = box.cap(cw)
    since = time.time()
    dur = wav_seconds("en-banana")
    seen = {}
    h = br.hold(max(1.0, dur - 0.4), finger=True)
    rel = h["release"]
    gid = None
    snaps = []

    def tick():
        nonlocal gid
        t = time.time() - rel
        if gid is None:
            g = box.voice_goals(since)
            if g:
                gid = g[0][0]
                seen["goal"] = t
        pt = box.panel_text()
        if "unless you veto it" in " ".join(pt.split()) and "countdown" not in seen:
            seen["countdown"] = t
            snaps.append(br.term_text())
            br.screenshot("9-5-countdown")
        s = box.cap(cw)
        if "typed" not in seen and TYPED.search(s) and s != before:
            seen["typed"] = t
        if ANSWER_EN.search(s):
            seen["answer"] = t
            return True
        st = box.goal_state(gid) if gid else None
        return bool(st and st.get("state") in ("failed", "stopped"))
    wait_for(tick, 120, 0.1)
    st = box.wait_goal(gid, 60) if gid else None
    states = [t[1] for t in h["timeline"]]
    br.screenshot("9-6-answer")
    box.save("9-6-claude-tab.txt", box.cap(cw))
    check("s9b: holding the microphone with a finger: the light went recording, sending, sent", "recording" in states and "sending" in states and h["final"] is not None and h["final"][1] == "sent", states)
    check("s9b: the panel was idle before the goal ('no goal.')", "no goal." in before_panel, before_panel[-200:])
    check("s9b: the goal reached the sysop, the countdown showed in the phone terminal and the panel never had the focus", bool(gid) and "countdown" in seen and not any(r[5] for r in panel_rows(box)), (seen, panel_rows(box)))
    check("s9b: the prompt was typed in the Claude tab and the answer appeared", "typed" in seen and "answer" in seen, "%s; tab: %s" % (seen, box.cap(cw)[-300:]))
    check("s9b: the goal ended done", (st or {}).get("state") == "done", (st or {}).get("error"))
    # (e) the idle panel after the goal
    wait_for(lambda: "last goal (voice" in box.panel_text(), 15, 0.3)
    wait_for(lambda: "no goal." in br.term_text(), 15, 0.3)
    after = box.panel_text()
    br.screenshot("9-7-idle-after-goal")
    box.save("9-7-panel-after-goal.txt", after)
    box.save("9-7-terminal-after-goal.txt", br.term_text())
    check("s9e: after the goal the panel is idle again and shows the last goal (source voice) with its result", "no goal." in after and "last goal (voice" in after and ("done:" in after or "DONE" in after or "failed:" in after), after[-600:])
    check("s9e: the idle panel keeps its head, 'no goal' and the key line after the goal", all(x in after for x in ("SYSOP", "no goal.", "[g] Goal")), after[-600:])
    summary = ((st or {}).get("summary") or "").split()
    check("s9e: the END of the result of the goal ('%s') is on the 8-line panel of the phone, not only the DONE badge and the goal text" % " ".join(summary[-2:]),
          len(summary) >= 2 and " ".join(summary[-2:]) in " ".join(after.split()), (summary, after[-500:]))
    info("s9 path", "release -> goal %.1fs, countdown shown %.1fs, prompt typed %.1fs, answer %.1fs (countdown 2 s, whisper small, haiku); Esc %.1fs; Panel hide %.1fs show %.1fs"
         % (seen.get("goal", -1), seen.get("countdown", -1), seen.get("typed", -1), seen.get("answer", -1), t_esc, t_hide, t_show))
    E.REPORT["s9"] = {"seen": {k: round(v, 2) for k, v in seen.items()}, "esc_s": round(t_esc, 2), "panel_hide_s": round(t_hide, 2), "panel_show_s": round(t_show, 2), "terminal_cells": [cols, rows],
                      "panel": pr}
    if seen.get("answer"):
        TIMES.append(seen["answer"])
    phone(box, "desktop")


def s10(box):
    """(f) a window created while the panel is always up gets its own panel and is not listed as a tab; the browser makes the window (Alt+N and the + button)"""
    box.scenario = "s10-new-window"
    box.configure()
    box.start_web()
    tabs = box.reset_tabs(claude=False, extra=("two",))
    br, ok = phone(box, "desktop")
    box.select(tabs["shell"])
    time.sleep(1.4)
    br.js("term.focus()")
    n0 = len(box.windows())
    wait_for(box.panels_up, 10)

    def listed():
        r = box.sh(["swarmbox-tabs", "list"])
        try:
            d = json.loads(r.stdout)
        except ValueError:
            return []
        return d.get("tabs", d) if isinstance(d, dict) else d
    check("s10: before: %d windows, each with a panel, and swarmbox-tabs lists %d tabs" % (n0, n0), box.panels_up() and len(listed()) == n0, (box.panes(), listed()))
    t = time.time()
    br.key("n", mods=1)            # Alt+N: a new window, from the browser
    got = wait_for(lambda: len(box.windows()) == n0 + 1 and box.panels_up(), 15, 0.1)
    t_panel = time.time() - t
    check("s10: Alt+N in the browser made a window and its panel is up (%.1f s)" % t_panel, got is not None, (box.windows(), box.panes()))
    tl = listed()
    panel_panes = {p["pane"] for p in box.panes() if p["panel"] == "1"}
    check("s10: the new window is a tab and its panel is not: %d tabs listed for %d windows, none of them is a panel pane, one pane each" % (len(tl), n0 + 1),
          len(tl) == n0 + 1 and not any(x.get("pane") in panel_panes for x in tl) and all(len(x.get("panes") or []) == 1 for x in tl), tl)
    check("s10: the panel of the new window is idle, unfocused, and the new window's own pane is the active one",
          all(p["active"] == "0" for p in box.panes() if p["panel"] == "1") and "no goal." in box.panel_text(), box.panes())
    time.sleep(1.0)
    br.screenshot("10-new-window")
    box.save("10-terminal.txt", br.term_text())
    names = [w["name"] for w in box.windows()]
    check("s10: no window is named after the panel (python3 or swarmbox-sysop) and the status bar lists %d windows" % (n0 + 1), not any("python" in n or "sysop" in n for n in names), names)
    # the + button of the status bar (a click on its cells) makes another one
    txt = br.term_text().splitlines()
    n1 = len(box.windows())
    status = next((l for l in reversed(txt) if "+" in l and ":" in l), "")
    col = status.find("+")
    if col >= 0:
        br.click_cell(col, br.term_size()[1] - 1)
        got = wait_for(lambda: len(box.windows()) == n1 + 1 and box.panels_up(), 15, 0.2)
        check("s10: the + button of the status bar makes a window with its panel", got is not None, (box.windows(), status))
    else:
        info("s10", "the + button is not in the status row; skipped: %r" % status)
    tl = listed()
    check("s10: after both, every window has exactly one panel and the tabs listed are the windows", box.panels_up() and len(tl) == len(box.windows()), (len(tl), len(box.windows())))
    # closing the new windows leaves the rest with their panels
    for w in [w["id"] for w in box.windows()][n0:]:
        box.tmux("kill-window", "-t", w)
    check("s10: closing them leaves the first windows with their panels", wait_for(lambda: len(box.windows()) == n0 and box.panels_up(), 10) is not None, (box.windows(), box.panes()))


# ====================================================================================================================== main
SCENARIOS = {1: ("the path of version 1", s1), 2: ("topics are settings", s2), 3: ("no sysop, stopped, bus down", s3), 4: ("the panel in the browser terminal", s4),
             5: ("the path of a tunnel", s5), 6: ("a goal that needs approval", s6), 7: ("screens never pass through the bus", s7),
             8: ("the microphone and the status bar: desktop, phone portrait and landscape", s8), 9: ("the thumb path on a phone", s9), 10: ("a new window with the panel always up", s10)}


def summary():
    log("=" * 70)
    if TIMES:
        info("release of the button -> the answer on the screen, n=%d (countdown 4 s, Whisper small on this CPU, haiku)" % len(TIMES),
             "min %.1f  p50 %.1f  max %.1f  mean %.1f" % (min(TIMES), E.pct(TIMES, 50), max(TIMES), statistics.mean(TIMES)))
        for e in V1:
            info("run", "%s: transcript %r, goal %.1fs, panel %.1fs, typed %.1fs, answer %.1fs, light %s" % (
                e["wav"], e.get("transcript"), e.get("goal", -1), e.get("panel", -1), e.get("typed", -1), e.get("answer", -1), e.get("light")))
        E.REPORT["latency"] = {"release_to_answer_s": TIMES}
    log("%d check(s) failed%s" % (len(FAILED_REF()), ": " + "; ".join(FAILED_REF()) if FAILED_REF() else ""))
    os.makedirs(RESULTS, exist_ok=True)
    with open(os.path.join(RESULTS, "report.json"), "w") as f:
        f.write(scrub(json.dumps({"failed": FAILED_REF(), "report": E.REPORT}, indent=1, ensure_ascii=False)))


def FAILED_REF():
    return E.FAILED


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="", help="scenario numbers, e.g. 1,3,4 (default all)")
    ap.add_argument("--runs", type=int, default=5, help="runs of scenario 1 (the last one is in English)")
    ap.add_argument("--model", default="haiku")
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()
    if a.list:
        for k, (n, _) in SCENARIOS.items():
            print(k, n)
        return 0
    want = [int(x) for x in a.only.split(",") if x] or sorted(SCENARIOS)
    box = VBox(a.model)
    try:
        box.setup()
        for n in want:
            log("=" * 20 + " scenario %d: %s" % (n, SCENARIOS[n][0]))
            try:
                if n == 1:
                    s1(box, a.runs)
                else:
                    SCENARIOS[n][1](box)
            except Exception as e:       # a bug of the harness or a crash is a failure, and the next scenario still runs
                import traceback
                check("scenario %d ran to its end" % n, False, repr(e))
                log(scrub(traceback.format_exc()))
    finally:
        box.scenario = "all"
        box.save_servelog()
        box.save("bus.log", box.read(os.path.join(box.state_dir, "bus.log")))
        box.save("web.log", box.read(os.path.join(box.state_dir, "web.log")))
        summary()
        stop_second(SECOND)
        box.stop_all()
    return 1 if E.FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
