#!/usr/bin/env python3
"""Tests for cloudflare-setup.py against an in-process fake of the Cloudflare API.

Run:  python3 tests/test_cloudflare_setup.py

The fake implements the endpoints the script uses (with auth, pagination and the response
envelopes of the real API), records every mutating call, and a fake `podman` stands in for
the connector. Nothing here talks to Cloudflare. It does NOT prove the real API accepts the
payloads: it proves our logic (idempotency, ordering, drift repair, refusal to clobber).
"""
import contextlib
import http.server
import importlib.util
import io
import json
import os
import re
import socketserver
import stat
import sys
import tempfile
import threading
import unittest
import urllib.parse

from helpers import ROOT, DEFAULT_CONNECTOR, DEFAULT_NAME, DEFAULTS_FILE

SCRIPT = os.path.join(ROOT, "cloudflare-setup.py")
GOOD_TOKEN = "good-token"


# --------------------------------------------------------------------------- fake API
class Fake:
    def __init__(self):
        self.reset()

    def reset(self):
        self.zones = [{"id": "z1", "name": "talkr.run", "account": {"id": "acc1", "name": "acc"}}]
        self.org = {"name": "team", "auth_domain": "team.cloudflareaccess.com"}
        self.org_error = False
        self.idps = []
        self.policies, self.apps, self.tunnels, self.dns = [], [], [], []
        self.configs = {}
        self.log = []
        self.seq = 0
        self.page_size = 2  # smaller than what the script asks for: forces real pagination

    def nid(self, prefix):
        self.seq += 1
        return "%s%d" % (prefix, self.seq)

    def mutations(self):
        return [(m, p) for m, p, _ in self.log if m != "GET"]

    # -- helpers
    def page(self, items, q):
        page = int(q.get("page", ["1"])[0])
        per = min(int(q.get("per_page", ["20"])[0]), self.page_size)
        total = max(1, -(-len(items) // per))
        return {"success": True, "errors": [], "messages": [],
                "result": items[(page - 1) * per: page * per],
                "result_info": {"page": page, "per_page": per, "total_pages": total,
                                "count": len(items), "total_count": len(items)}}

    @staticmethod
    def ok(result):
        return 200, {"success": True, "errors": [], "messages": [], "result": result}

    @staticmethod
    def err(status, code, message):
        return status, {"success": False, "errors": [{"code": code, "message": message}],
                        "messages": [], "result": None}

    def handle(self, method, path, q, body, auth):
        self.log.append((method, path, body))
        if auth == "Bearer invalid9109":
            return self.err(403, 9109, "Invalid access token")
        if auth != "Bearer " + GOOD_TOKEN:
            return self.err(403, 10000, "Authentication error")
        a = "/accounts/acc1"
        m = re.match
        if path == "/zones" and method == "GET":
            name = q.get("name", [None])[0]
            return self.ok([z for z in self.zones if name in (None, z["name"])])
        if path == a + "/access/organizations" and method == "GET":
            if self.org_error:
                # the real API answers 403 here, which is what made it easy to misreport
                return self.err(403, 9999, "access.api.error.not_enabled: Access is not enabled.")
            return self.ok(self.org)
        if path == a + "/access/identity_providers":
            if method == "GET":
                return self.ok(self.idps)
            obj = dict(body, id=self.nid("idp"))
            self.idps.append(obj)
            return self.ok(obj)
        if path == a + "/access/policies":
            if method == "GET":
                return 200, self.page(self.policies, q)
            obj = dict(body, id=self.nid("pol"))
            self.policies.append(obj)
            return self.ok(obj)
        mm = m(r"^" + a + r"/access/policies/([^/]+)$", path)
        if mm:
            return self.crud(self.policies, mm.group(1), method, body)
        if path == a + "/access/apps":
            if method == "GET":
                dom = q.get("domain", [None])[0]
                return 200, self.page([x for x in self.apps if dom in (None, x["domain"])], q)
            obj = dict(body, id=self.nid("app"), aud=self.nid("aud"))
            self.apps.append(obj)
            return self.ok(obj)
        mm = m(r"^" + a + r"/access/apps/([^/]+)$", path)
        if mm:
            return self.crud(self.apps, mm.group(1), method, body, keep=("aud",))
        if path == a + "/cfd_tunnel":
            if method == "GET":
                name = q.get("name", [None])[0]
                return self.ok([t for t in self.tunnels if name in (None, t["name"])])
            obj = {"id": self.nid("tun"), "name": body["name"], "config_src": body.get("config_src")}
            self.tunnels.append(obj)
            return self.ok(obj)
        mm = m(r"^" + a + r"/cfd_tunnel/([^/]+)/configurations$", path)
        if mm:
            tid = mm.group(1)
            if method == "GET":
                return self.ok({"tunnel_id": tid, "config": self.configs.get(tid)})
            cfg = json.loads(json.dumps(body["config"]))
            for r in cfg.get("ingress", []):
                if r.get("hostname"):  # emulate server-side defaults the script does not set
                    r.setdefault("originRequest", {})["noTLSVerify"] = False
            self.configs[tid] = cfg
            return self.ok({"tunnel_id": tid, "config": cfg})
        mm = m(r"^" + a + r"/cfd_tunnel/([^/]+)/token$", path)
        if mm:
            return self.ok("tok." + mm.group(1))
        if path == "/zones/z1/dns_records":
            if method == "GET":
                name = q.get("name", [None])[0]
                return self.ok([r for r in self.dns if name in (None, r["name"])])
            obj = dict(body, id=self.nid("dns"))
            self.dns.append(obj)
            return self.ok(obj)
        mm = m(r"^/zones/z1/dns_records/([^/]+)$", path)
        if mm:
            return self.crud(self.dns, mm.group(1), method, body, merge=True)
        return self.err(404, 7003, "no route for %s %s" % (method, path))

    def crud(self, coll, oid, method, body, keep=(), merge=False):
        obj = next((o for o in coll if o["id"] == oid), None)
        if obj is None:
            return self.err(404, 7003, "not found")
        if method == "DELETE":
            coll.remove(obj)
            return self.ok({"id": oid})
        if method in ("PUT", "PATCH"):
            new = dict(obj) if merge else {"id": oid}
            for k in keep:
                new[k] = obj[k]
            new.update(body)
            coll[coll.index(obj)] = new
            return self.ok(new)
        return self.ok(obj)


FAKE = Fake()


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _do(self):
        u = urllib.parse.urlparse(self.path)
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n)) if n else None
        path = u.path[len("/client/v4"):]
        status, payload = FAKE.handle(self.command, path, urllib.parse.parse_qs(u.query),
                                      body, self.headers.get("Authorization"))
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = _do


class Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True


# --------------------------------------------------------------------------- harness
SERVER = Server(("127.0.0.1", 0), Handler)
threading.Thread(target=SERVER.serve_forever, daemon=True).start()
os.environ["CLOUDFLARE_API_BASE"] = "http://127.0.0.1:%d/client/v4" % SERVER.server_address[1]
_spec = importlib.util.spec_from_file_location("cloudflare_setup", SCRIPT)
cs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cs)

BASE = ["--domain", "talkr.run", "--email", "me@example.com", "--no-connector", "--no-verify"]


class T(unittest.TestCase):
    def setUp(self):
        FAKE.reset()
        self.tmp = tempfile.mkdtemp()
        self.env = {"CLOUDFLARE_API_TOKEN": GOOD_TOKEN, "XDG_CONFIG_HOME": self.tmp}
        for k in ("SWARMBOX_WEB_DOMAIN", "SWARMBOX_WEB_EMAIL"):
            os.environ.pop(k, None)

    def run_cli(self, *argv, env=None):
        full = dict(self.env, **(env or {}))
        saved = {k: os.environ.get(k) for k in full}
        os.environ.update(full)
        out, err = io.StringIO(), io.StringIO()
        code = 0
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                try:
                    code = cs.main(list(argv))
                except SystemExit as e:
                    code = e.code
        finally:
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
        return code, out.getvalue(), err.getvalue()

    def apply(self, *extra, **kw):
        return self.run_cli(*(BASE + list(extra)), **kw)

    def host_rule(self, host=DEFAULT_NAME + ".talkr.run"):
        cfg = FAKE.configs[FAKE.tunnels[0]["id"]]
        return next(r for r in cfg["ingress"] if r.get("hostname") == host)


# --------------------------------------------------------------------------- tests
class TestApply(T):
    def test_fresh_apply_creates_everything_in_a_safe_order(self):
        code, out, err = self.apply()
        self.assertEqual(code, 0, err)
        kinds = []
        for m, p in FAKE.mutations():
            for key, label in (("identity_providers", "idp"), ("access/policies", "policy"),
                               ("access/apps", "app"), ("configurations", "route"),
                               ("cfd_tunnel", "tunnel"), ("dns_records", "dns")):
                if key in p:
                    kinds.append(label)
                    break
        self.assertEqual(kinds, ["idp", "policy", "app", "tunnel", "route", "dns"])
        # the login is in place before anything can route to the hostname
        self.assertLess(kinds.index("app"), kinds.index("route"))
        self.assertLess(kinds.index("app"), kinds.index("dns"))

    def test_second_run_changes_nothing(self):
        self.apply()
        FAKE.log.clear()
        code, out, _ = self.apply()
        self.assertEqual(code, 0)
        self.assertEqual(FAKE.mutations(), [])
        self.assertNotIn("  + ", out)

    def test_session_saved_in_cloudflare_json_and_file_mode_is_600(self):
        path = os.path.join(self.tmp, "swarmbox", "cloudflare.json")
        self.apply("--session", "168h")
        with open(path) as f:
            saved = json.load(f)
        self.assertEqual(saved["session"], "168h")
        self.assertEqual({"domain", "emails", "tunnel", "session", "hostname", "name"}, set(saved))
        self.apply()
        with open(path) as f:
            self.assertEqual(json.load(f)["session"], "168h")
        # security review SR-04: the file is private (mode 600) whatever the umask
        self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)

class TestSafetyAndErrors(T):
    def test_dry_run_and_status_never_mutate(self):
        for argv in (BASE + ["--dry-run"], ["status", "--domain", "talkr.run", "--email", "me@example.com",
                                            "--no-connector", "--no-verify"]):
            FAKE.reset()
            code, out, err = self.run_cli(*argv)
            self.assertEqual(code, 0, err)
            self.assertEqual(FAKE.mutations(), [])
            self.assertIn("would be created", out)
            self.assertNotIn("  + ", out)

    def test_bad_token_explains_permissions_and_changes_nothing(self):
        code, _, err = self.apply(env={"CLOUDFLARE_API_TOKEN": "nope"})
        self.assertNotEqual(code, 0)
        self.assertIn("Cloudflare Tunnel", err)
        self.assertEqual(FAKE.mutations(), [])

    def test_token_is_never_printed_or_saved(self):
        _, out, err = self.apply()
        self.assertNotIn(GOOD_TOKEN, out + err)
        path = os.path.join(self.tmp, "swarmbox", "cloudflare.json")
        self.assertTrue(os.path.exists(path))
        with open(path) as f:
            self.assertNotIn(GOOD_TOKEN, f.read())


class TestTokenCommand(T):
    def test_prints_only_the_tunnel_token_on_stdout_and_never_writes(self):
        self.apply()
        tunnel_id = FAKE.tunnels[0]["id"]
        FAKE.log.clear()
        code, out, err = self.run_cli("token", "--domain", "talkr.run")
        self.assertEqual(code, 0, err)
        self.assertEqual(out, "tok." + tunnel_id + "\n", "stdout must be exactly the token, usable in $(...)")
        self.assertIn("can only connect a connector", err)  # the explanation goes to stderr
        self.assertEqual(FAKE.mutations(), [])

class TestRemove(T):
    def test_remove_undoes_one_hostname_route_first_and_keeps_others(self):
        self.apply()
        self.apply("--name", "second", "--port", "7682")
        FAKE.log.clear()
        code, _, err = self.run_cli("remove", "--domain", "talkr.run", "--name", "second", "--yes")
        self.assertEqual(code, 0, err)
        order = []
        for m, p in FAKE.mutations():
            order.append("dns" if "dns_records" in p else "route" if "configurations" in p
                         else "app" if "access/apps" in p else "policy" if "access/policies" in p else "?")
        self.assertEqual(order, ["dns", "route", "app", "policy"], "route is taken away before the login")
        hosts = [r.get("hostname") for r in FAKE.configs[FAKE.tunnels[0]["id"]]["ingress"]]
        self.assertEqual(hosts, [DEFAULT_NAME + ".talkr.run", None])
        self.assertEqual([a["domain"] for a in FAKE.apps], [DEFAULT_NAME + ".talkr.run"])
        self.assertEqual(len(FAKE.dns), 1)

class TestConnector(T):
    def setUp(self):
        super().setUp()
        self.shim = tempfile.mkdtemp()
        path = os.path.join(self.shim, "podman")
        with open(path, "w") as f:
            f.write('''#!/bin/sh
echo "$@" >> "$SHIM_DIR/calls"
case "$1" in
  inspect) [ -f "$SHIM_DIR/state" ] || exit 1
           read st tok < "$SHIM_DIR/state"
           if [ "$st" = running ]; then r=true; else r=false; fi
           printf '%s|TUNNEL_TOKEN=%s\\n' "$r" "$tok"; exit 0 ;;
  run) if [ -n "$SHIM_RUN_FAIL" ]; then
         printf 'Trying to pull x...\nCopying blob a\nCopying blob b\nCopying blob c\nError: potentially insufficient UIDs or GIDs available in user namespace (requested 65532:65532)\n' >&2
         exit 125
       fi
       echo "TUNNEL_TOKEN=$TUNNEL_TOKEN" >> "$SHIM_DIR/env"; echo "running $TUNNEL_TOKEN" > "$SHIM_DIR/state" ;;
  start) read st tok < "$SHIM_DIR/state"; echo "running $tok" > "$SHIM_DIR/state" ;;
  rm) rm -f "$SHIM_DIR/state" ;;
esac
''')
        os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR)
        self.env.update({"SHIM_DIR": self.shim, "PATH": self.shim + os.pathsep + os.environ["PATH"]})
        self.conn = ["--domain", "talkr.run", "--email", "me@example.com", "--no-verify"]

    def calls(self):
        p = os.path.join(self.shim, "calls")
        if not os.path.exists(p):
            return []
        with open(p) as f:
            return f.read().splitlines()

    def test_connector_runs_with_token_in_env_not_argv_and_is_idempotent(self):
        code, _, err = self.run_cli(*self.conn)
        self.assertEqual(code, 0, err)
        runs = [c for c in self.calls() if c.startswith("run ")]
        self.assertEqual(len(runs), 1)
        self.assertIn("--network=host", runs[0])
        self.assertIn("--restart=always", runs[0])
        self.assertIn("--user root", runs[0])
        self.assertNotIn("tok.", runs[0], "token must not be on the command line")
        with open(os.path.join(self.shim, "env")) as f:
            self.assertIn("TUNNEL_TOKEN=tok.tun", f.read())
        self.run_cli(*self.conn)
        self.assertEqual(len([c for c in self.calls() if c.startswith("run ")]), 1, "no second connector")

    # ---- remove stops the connector only when nothing else uses the tunnel; image pinning
    def remove(self, *extra):
        return self.run_cli("remove", "--domain", "talkr.run", "--yes", *extra)

class TestVerify(unittest.TestCase):
    def serve(self, status, location=""):
        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                self.send_response(status)
                if location:
                    self.send_header("Location", location)
                self.send_header("Content-Length", "0")
                self.end_headers()
        srv = Server(("127.0.0.1", 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        return "http://127.0.0.1:%d/" % srv.server_address[1]

    def test_redirect_to_access_is_protected(self):
        url = self.serve(302, "https://team.cloudflareaccess.com/cdn-cgi/access/login/x?kid=1")
        self.assertEqual(cs.check_protected(url, timeout=5)[0], "protected")

class TestDefaultNames(unittest.TestCase):
    """The default name, the tunnel and the connector come from container/host/DEFAULTS, read next to the script."""

    def test_defaults_of_the_parser_and_the_connector(self):
        a = cs.build_parser().parse_args([])
        self.assertEqual((a.name, a.tunnel), (DEFAULT_NAME, DEFAULT_NAME))
        self.assertEqual(cs.CONNECTOR_NAME, DEFAULT_CONNECTOR)
        self.assertEqual(cs.DEFAULT_NAME, DEFAULT_NAME)

    def test_the_script_reads_the_defaults_file_next_to_it_and_refuses_without_one(self):
        import shutil
        import subprocess
        d = tempfile.mkdtemp(prefix="swarmbox-test-cfdefaults-")
        try:
            shutil.copy(SCRIPT, d)
            r = subprocess.run([sys.executable, "-I", os.path.join(d, "cloudflare-setup.py"), "--help"],
                               capture_output=True, text=True, cwd=d, env=dict(os.environ, COLUMNS="80"))
            self.assertNotEqual(r.returncode, 0)          # no DEFAULTS here, and no container/host/ below it
            self.assertIn("DEFAULTS", r.stderr)
            with open(os.path.join(d, "DEFAULTS"), "w") as f:
                f.write("SWARMBOX_DEFAULT_NAME=flipped\nSWARMBOX_DEFAULT_IMAGE_REPO='ghcr.io/<org>/flipped'\n")
            r = subprocess.run([sys.executable, "-I", os.path.join(d, "cloudflare-setup.py"), "--help"],
                               capture_output=True, text=True, cwd=d, env=dict(os.environ, COLUMNS="80"))
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("(default:\n                        flipped)", r.stdout)   # argparse wraps the help text
            self.assertIn("remove --name flipped --yes", r.stdout)
        finally:
            shutil.rmtree(d)


if __name__ == "__main__":
    unittest.main(verbosity=2)
