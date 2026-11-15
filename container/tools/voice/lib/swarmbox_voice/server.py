"""The voice HTTP service: audio -> text -> plan (PENDING) -> confirmed in the tmux panel -> tmux. Stdlib only, loopback only.

Endpoints (all under /voice/, answers are JSON, no caching). One name per operation:
  GET  /voice/health                       {"ok": true, "planner", "language", "model", "pending"}
  POST /voice/audio                        body: 16 kHz mono 16-bit WAV (Content-Type audio/wav). Transcribes, plans, stores the plan as the
                                           PENDING plan and opens the panel. The answer is minimal and NEVER carries the transcript, the plan or
                                           pane text: {"ok": true, "state": "pending"} or {"ok": true, "state": "nothing_heard"}.
  GET  /voice/pending[?wait=S&since=ID]    the pending plan {"pending": {"id","text","say","actions","risk","expires_in"}} or {"pending": null}.
                                           With wait, a long poll: it answers when the pending plan is not `since` ("" = none), or after S seconds.
  POST /voice/plan   {"utterance", "pane"?} the same for a typed request: stores the PENDING plan, opens the panel, answers the plan.
  POST /voice/edit   {"id", "edits": {"<action index>": text}}  replaces the pending plan by one with the edited send_text texts, a new id
                                           and a risk computed again here; the old id is dropped (in one step: there is no moment without a plan).
  POST /voice/run    {"id"}                executes the stored plan through the executor, once: {"ok", "results"}.
  POST /voice/cancel {"id"}                drops the plan.
Only /voice/health and /voice/audio (and the two page files) are reachable from the web: the front forwards nothing else. The panel and the
CLI use the rest, on 127.0.0.1 inside the box. There is no /voice/transcribe (nothing needs text without a plan).
Errors: {"error": code, "message": text} with 400 (bad request), 403 (host or origin), 404 (unknown plan), 409 (plan already used, cancelled
or replaced, or tmux refused), 410 (plan expired), 413, 415, 422 (planner failed, or the audio could not be recognized), 502 (tmux or
recognizer missing). The messages of /voice/audio are fixed texts, so an error cannot carry the transcript or text from a pane either.

There is ONE pending plan: a new plan replaces (cancels) an older one. It targets a pane: the `pane` of a typed request when it is a pane of
the session, else the ACTIVE PANE of the window the session shows (the one the user looks at; the voice panel is never a candidate: when it
has the focus, the pane that was active before it is used). Rules: the plan is stored here and run executes THAT plan (the client sends
only an id); the risk is computed by the host (risk.plan_risk), re-checked at run, and the planner's own opinion is ignored; Enter is
pressed only when an action says enter=true and the plan was run (the passthrough planner never does); a plan expires after two minutes.
The listener binds only to a loopback address. Every request needs a Host of a loopback name (or one given in allow_hosts) and, when it has
an Origin, an Origin whose host is the Host (no cross-site calls, no DNS rebinding); POST needs the JSON or audio content type, which a
cross-site form cannot send, and OPTIONS is refused, so a page of another origin cannot even preflight.
"""
import json
import os
import re
import sys
import tempfile
import threading
import unicodedata
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from . import config as vconfig
from . import context, contract, executor, planners, risk, stt
from .store import PlanError, PlanStore
from .tmuxrun import SEP, Tmux

MAX_JSON = 64 * 1024
MAX_WAIT = 55.0
AUDIO_TYPES = ("audio/wav", "audio/x-wav", "audio/wave")
# what /voice/audio says when it fails: fixed texts by error code, never the text of the error itself (it could hold the transcript or pane text)
AUDIO_MESSAGES = {"stt_bad_audio": "The audio could not be read.", "stt_too_large": "The recording is too long.",
                  "stt_no_whisper": "The speech recognizer is not installed.", "stt_no_model": "The speech model is missing.",
                  "stt_failed": "The speech recognizer failed.", "stt_timeout": "The speech recognizer took too long.",
                  "no_tmux": "The terminal session is not available.", "no_planner": "The planner is not installed."}
LOOPBACK = ("127.0.0.1", "localhost", "[::1]", "::1")
STATUS = {"unknown": 404, "used": 409, "cancelled": 409, "expired": 410}


class HttpError(Exception):
    def __init__(self, status, code, message):
        Exception.__init__(self, message)
        self.status, self.code, self.message = status, code, message


class Service:
    """The logic, without HTTP. Every outside dependency can be replaced (tests do): tmux, the recognizer, the planner folders."""

    def __init__(self, cfg=None, tmux=None, transcribe=None, store=None, session="main", base_env=None, user_planners=None,
                 builtin_planners=None, planner_timeout=planners.TIMEOUT, dock=None, log=None):
        self.cfg = cfg or vconfig.load(os.environ)
        self.tmux = tmux or Tmux()
        self.transcribe_fn = transcribe or stt.transcribe
        self.store = store or PlanStore()
        self.session = session
        self.base_env = base_env
        self.user_planners, self.builtin_planners = user_planners, builtin_planners
        self.planner_timeout = planner_timeout
        self.exec_lock = threading.Lock()
        self.dock = dock          # opens the panel when a plan becomes pending (dock.Dock); None: no panel (tests, the CLI without tmux)
        self.log = log or (lambda text: print("swarmbox-voice: " + text, file=sys.stderr, flush=True))

    def settings(self):
        c = self.cfg
        return {"SWARMBOX_VOICE_LANGUAGE": c.language, "SWARMBOX_VOICE_STT_MODEL": c.stt_model,
                "SWARMBOX_VOICE_STT_VOCABULARY": c.stt_vocabulary, "SWARMBOX_VOICE_PLANNER": c.planner,
                "SWARMBOX_VOICE_PLANNER_MODEL": c.planner_model}

    def health(self):
        return {"ok": True, "planner": self.cfg.planner, "language": self.cfg.language, "model": self.cfg.stt_model,
                "pending": self.store.pending()}

    def transcribe(self, wav):
        """WAV bytes -> text. The audio lives in a private temporary folder only while the recognizer runs."""
        try:
            stt.check_wav(wav)
            with tempfile.TemporaryDirectory(prefix="swarmbox-voice-") as folder:
                path = os.path.join(folder, "audio.wav")
                with open(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as f:
                    f.write(wav)
                return self.transcribe_fn(path, self.cfg.language, self.cfg.stt_model, self.cfg.stt_vocabulary)
        except stt.SttError as e:
            status = {"too_large": 413, "bad_audio": 400, "no_speech": 422, "no_whisper": 502, "no_model": 502}.get(e.code, 422)
            raise HttpError(status, "stt_" + e.code, e.message) from None

    def audio(self, wav, pane=None):
        """WAV -> text -> pending plan, one call. Returns {"ok": True, "state": "pending"|"nothing_heard"}, nothing else."""
        try:
            text = self.transcribe(wav)
        except HttpError as e:
            if e.code == "stt_no_speech":
                return {"ok": True, "state": "nothing_heard"}
            raise HttpError(e.status, e.code, AUDIO_MESSAGES.get(e.code, "The speech could not be recognized.")) from None
        try:
            self.plan(text, pane)
        except HttpError as e:
            if e.code == "bad_request":     # nothing left of the text once invisible characters were removed
                return {"ok": True, "state": "nothing_heard"}
            self.log("audio: planning failed (%s)" % e.code)
            raise HttpError(e.status, e.code, AUDIO_MESSAGES.get(e.code, "The planner could not make a plan from that.")) from None
        return {"ok": True, "state": "pending"}

    def plan(self, utterance, pane=None):
        if not isinstance(utterance, str) or not utterance.strip():
            raise HttpError(400, "bad_request", "utterance must be a non-empty string")
        # invisible format characters (zero-width, direction marks, ZWJ) are common in transcripts; the contract refuses them
        utterance = "".join(c for c in utterance if unicodedata.category(c) != "Cf")
        if not utterance.strip():
            raise HttpError(400, "bad_request", "utterance must be a non-empty string")
        raw = context.snapshot(self.tmux, self.session)
        if not raw:
            raise HttpError(502, "no_tmux", "the tmux session %r is not available" % self.session)
        if not (isinstance(pane, str) and any(p["id"] == pane for p in raw)):
            pane = next((p["id"] for p in raw if p.get("active")), raw[0]["id"])
        data = context.build_input(utterance.strip(), pane, raw)
        found = planners.find(self.cfg.planner, self.user_planners, self.builtin_planners)
        if found is None:
            raise HttpError(422, "no_planner", "there is no planner called %r" % self.cfg.planner)
        res = planners.run_planner(found, data, base_env=self.base_env, settings=self.settings(), timeout=self.planner_timeout)
        if not res.ok:
            raise HttpError(422, "planner_" + str(res.code), res.error)
        rating = risk.plan_risk(res.plan, data["panes"])
        pid = self.store.replace(res.plan, text=utterance.strip(), risk=rating)    # an older pending plan is cancelled: one at a time
        self._open_panel()
        return {"id": pid, "text": utterance.strip(), "say": res.plan["say"], "actions": res.plan["actions"], "risk": rating,
                "expires_in": int(self.store.ttl)}

    def _open_panel(self):
        """The plan is pending: show it. Docking trouble is logged and never fails the request (the plan is still pending)."""
        if self.dock is None:
            return
        try:
            self.dock.open()
        except Exception as e:   # DockError, or anything else
            self.log("could not open the panel: %s" % e)

    def pending(self, wait=0.0, since=""):
        """The pending plan as the panel shows it ({"pending": plan or None}); a long poll when wait > 0 (see the module doc)."""
        wait = min(max(0.0, wait), MAX_WAIT)
        cur = self.store.wait_change(since, wait) if wait else self.store.current()
        if cur is None:
            return {"pending": None}
        pid, entry = cur
        return {"pending": {"id": pid, "text": entry.get("text", ""), "say": entry["plan"]["say"], "actions": entry["plan"]["actions"],
                            "risk": entry.get("risk"), "expires_in": self.store.remaining(entry)}}

    def _risk_now(self, plan):
        """The risk of the plan with the commands the panes run NOW, or None when tmux cannot say."""
        res = self.tmux.run("list-panes", "-s", "-t", "=" + self.session, "-F", SEP.join(["#{pane_id}", "#{pane_current_command}"]))
        if res.rc != 0:
            return None
        panes = {}
        for line in res.out.splitlines():
            pane_id, _, command = line.partition(SEP)
            panes[pane_id] = {"id": pane_id, "command": command}
        return risk.plan_risk(plan, panes)

    def confirm(self, pid):
        entry = self.store.peek(pid)
        if entry is not None and entry.get("risk"):
            now = self._risk_now(entry["plan"])
            if now is not None and risk.LEVELS.index(now["level"]) > risk.LEVELS.index(entry["risk"]["level"]):
                # a pane changed what it runs since the plan was rated (an agent exited, a shell took over)
                try:
                    self.store.take(pid, "cancelled")
                except PlanError:
                    pass
                raise HttpError(409, "plan_risk_changed", "a pane changed since the plan was made and it is now riskier; ask again")
        try:
            entry = self.store.take(pid, "used")
        except PlanError as e:
            raise HttpError(STATUS[e.code], "plan_" + e.code, e.message) from None
        with self.exec_lock:
            try:
                results = executor.execute(entry["plan"]["actions"], True, tmux=self.tmux, session=self.session)
            except executor.ExecutorError as e:
                raise HttpError(409, "not_executed", str(e)) from None
        return {"ok": all(r["ok"] for r in results), "results": results}

    def edit(self, pid, edits):
        """The user edited the text of send_text actions: replace the stored plan by a revalidated one with a new id and a new risk."""
        if not isinstance(edits, dict) or not edits:
            raise HttpError(400, "bad_request", "edits must be a non-empty object")
        entry = self.store.peek(pid)
        if entry is None:
            try:
                self.store.take(pid, "used")
            except PlanError as e:
                raise HttpError(STATUS[e.code], "plan_" + e.code, e.message) from None
            raise HttpError(409, "plan_used", "the plan was just used")
        actions = [dict(a) for a in entry["plan"]["actions"]]
        for key, text in edits.items():
            if not (isinstance(key, str) and re.fullmatch(r"0|[1-9][0-9]?", key) and int(key) < len(actions) and actions[int(key)].get("type") == "send_text"
                    and isinstance(text, str)):
                raise HttpError(400, "bad_request", "an edit must give a text for a send_text action")
            actions[int(key)]["text"] = text
        raw = context.snapshot(self.tmux, self.session)
        if not raw:
            raise HttpError(502, "no_tmux", "the tmux session %r is not available" % self.session)
        try:
            plan = contract.validate_plan({"say": entry["plan"]["say"], "actions": actions}, [p["id"] for p in raw])
        except contract.ContractError as e:
            raise HttpError(422, "plan_" + e.code, e.message) from None
        rating = risk.plan_risk(plan, raw)
        try:
            new = self.store.swap(pid, plan, text=entry.get("text", ""), risk=rating)   # the old id is dropped only now that the edit is good
        except PlanError as e:
            raise HttpError(STATUS[e.code], "plan_" + e.code, e.message) from None
        return {"id": new, "text": entry.get("text", ""), "say": plan["say"], "actions": plan["actions"], "risk": rating,
                "expires_in": int(self.store.ttl)}

    def cancel(self, pid):
        try:
            self.store.take(pid, "cancelled")
        except PlanError as e:
            raise HttpError(STATUS[e.code], "plan_" + e.code, e.message) from None
        return {"ok": True}


def _host_of(netloc):
    netloc = netloc.strip().lower()
    return netloc.rsplit(":", 1)[0] if re.search(r":\d+$", netloc) else netloc


def make_handler(service, allow_hosts=()):
    allowed = set(LOOPBACK) | {h.lower() for h in allow_hosts}

    class Handler(BaseHTTPRequestHandler):
        server_version = "swarmbox-voice"
        sys_version = ""
        protocol_version = "HTTP/1.0"   # one request per connection

        def log_message(self, fmt, *args):   # no access log: URLs and timing only, but quiet is better in a terminal box
            pass

        def _send(self, status, obj):
            body = json.dumps(obj).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def _guard(self):
            host = self.headers.get("Host", "")
            if _host_of(host) not in allowed:
                raise HttpError(403, "bad_host", "this Host is not allowed")
            origin = self.headers.get("Origin")
            if origin is not None and urlsplit(origin).netloc.lower() != host.strip().lower():
                raise HttpError(403, "bad_origin", "cross-origin calls are not allowed")

        def _body(self, limit, types):
            ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            if ctype not in types:
                raise HttpError(415, "bad_content_type", "Content-Type must be one of: " + ", ".join(types))
            try:
                length = int(self.headers.get("Content-Length", ""))
            except ValueError:
                raise HttpError(411, "length_required", "Content-Length is required") from None
            if length < 0 or length > limit:
                raise HttpError(413, "too_large", "the body is larger than %d bytes" % limit)
            data = self.rfile.read(length)
            if len(data) != length:
                raise HttpError(400, "bad_request", "the body is incomplete")
            return data

        def _json(self):
            try:
                obj = json.loads(self._body(MAX_JSON, ("application/json",)).decode("utf-8"))
            except (ValueError, RecursionError):
                raise HttpError(400, "bad_request", "the body is not valid JSON") from None
            if not isinstance(obj, dict):
                raise HttpError(400, "bad_request", "the body must be a JSON object")
            return obj

        def _route(self, method):
            self._guard()
            url = urlsplit(self.path)
            path = url.path
            if method == "GET" and path == "/voice/health":
                return service.health()
            if method == "POST" and path == "/voice/audio":
                return service.audio(self._body(stt.MAX_WAV_BYTES, AUDIO_TYPES))
            if method == "GET" and path == "/voice/pending":
                q = parse_qs(url.query)
                try:
                    wait = float(q.get("wait", ["0"])[0])
                except ValueError:
                    raise HttpError(400, "bad_request", "wait must be a number of seconds") from None
                if wait != wait:   # NaN
                    wait = 0.0
                return service.pending(wait, q.get("since", [""])[0][:128])
            if method == "POST" and path == "/voice/edit":
                obj = self._json()
                if not isinstance(obj.get("id"), str):
                    raise HttpError(400, "bad_request", "id must be a string")
                return service.edit(obj["id"], obj.get("edits"))
            if method == "POST" and path == "/voice/plan":
                obj = self._json()
                return service.plan(obj.get("utterance"), obj.get("pane"))
            if method == "POST" and path in ("/voice/run", "/voice/cancel"):
                obj = self._json()
                pid = obj.get("id")
                if not isinstance(pid, str):
                    raise HttpError(400, "bad_request", "id must be a string")
                return service.confirm(pid) if path == "/voice/run" else service.cancel(pid)
            if path.startswith("/voice/"):
                raise HttpError(405 if path in ("/voice/health", "/voice/audio", "/voice/pending", "/voice/edit", "/voice/run",
                                              "/voice/plan", "/voice/cancel")
                                else 404, "not_found", "no such endpoint or method")
            raise HttpError(404, "not_found", "no such endpoint")

        def _handle(self, method):
            try:
                self._send(200, self._route(method))
            except HttpError as e:
                self._send(e.status, {"error": e.code, "message": e.message})
            except Exception:   # never leak a traceback to the client
                self._send(500, {"error": "internal", "message": "internal error"})

        def do_GET(self):
            self._handle("GET")

        def do_POST(self):
            self._handle("POST")

        def do_OPTIONS(self):
            self._send(405, {"error": "no_cors", "message": "cross-origin calls are not allowed"})

        do_PUT = do_DELETE = do_PATCH = do_OPTIONS

    return Handler


class _Server(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address):
        """A panel that closes while it waits on a long poll leaves a broken connection: that is not an error worth a traceback."""
        if isinstance(sys.exc_info()[1], (BrokenPipeError, ConnectionResetError)):
            return
        super().handle_error(request, client_address)


def is_loopback(host):
    return host in ("127.0.0.1", "localhost")


def make_server(service, host="127.0.0.1", port=0, allow_hosts=()):
    """A bound (not yet serving) HTTP server. Refuses any address that is not loopback."""
    if not is_loopback(host):
        raise ValueError("the voice service listens only on a loopback address, not %r" % host)
    if host == "localhost":
        host = "127.0.0.1"
    return _Server((host, port), make_handler(service, allow_hosts))
