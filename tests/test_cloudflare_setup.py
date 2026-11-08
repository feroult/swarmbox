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

from helpers import ROOT

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

    def host_rule(self, host="swarmbox.talkr.run"):
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

    def test_resources_have_the_expected_shape(self):
        self.apply()
        app = FAKE.apps[0]
        pol = FAKE.policies[0]
        self.assertEqual(app["type"], "self_hosted")
        self.assertEqual(app["domain"], "swarmbox.talkr.run")
        self.assertEqual(app["allowed_idps"], [FAKE.idps[0]["id"]])
        self.assertEqual(FAKE.idps[0]["type"], "onetimepin")
        self.assertEqual(app["policies"], [{"id": pol["id"], "precedence": 1}])
        self.assertEqual(pol["decision"], "allow")
        self.assertEqual(pol["include"], [{"email": {"email": "me@example.com"}}])
        rule = self.host_rule()
        self.assertEqual(rule["service"], "http://localhost:7681")
        self.assertEqual(rule["originRequest"]["access"],
                         {"required": True, "teamName": "team", "audTag": [app["aud"]]})
        ingress = FAKE.configs[FAKE.tunnels[0]["id"]]["ingress"]
        self.assertEqual(ingress[-1], {"service": "http_status:404"})
        rec = FAKE.dns[0]
        self.assertEqual((rec["type"], rec["proxied"]), ("CNAME", True))
        self.assertEqual(rec["content"], FAKE.tunnels[0]["id"] + ".cfargotunnel.com")

    def test_default_hostname_hint_uses_the_domain(self):
        code, out, err = self.apply()
        self.assertIn("https://swarmbox.talkr.run", out)
        self.assertNotIn("--reset --web", out)
        self.assertIn("delete the API token", out)

    def test_second_run_changes_nothing(self):
        self.apply()
        FAKE.log.clear()
        code, out, _ = self.apply()
        self.assertEqual(code, 0)
        self.assertEqual(FAKE.mutations(), [])
        self.assertNotIn("  + ", out)

    def test_pagination_is_followed(self):
        # more policies/apps than the fake's page size, ours is last
        for i in range(5):
            FAKE.policies.append({"id": "x%d" % i, "name": "other %d" % i})
            FAKE.apps.append({"id": "a%d" % i, "domain": "other%d.talkr.run" % i, "aud": "z"})
        self.apply()
        FAKE.log.clear()
        self.apply()
        self.assertEqual(FAKE.mutations(), [], "found existing resources across pages")

    def test_email_change_updates_only_the_policy(self):
        self.apply()
        FAKE.log.clear()
        self.run_cli(*[a if a != "me@example.com" else "me@example.com,two@example.com" for a in BASE])
        muts = FAKE.mutations()
        self.assertEqual(len(muts), 1)
        self.assertEqual(muts[0][0], "PUT")
        self.assertIn("access/policies", muts[0][1])
        self.assertEqual({r["email"]["email"] for r in FAKE.policies[0]["include"]},
                         {"me@example.com", "two@example.com"})

    def test_session_change_updates_only_the_app(self):
        self.apply()
        FAKE.log.clear()
        self.apply("--session", "30m")
        muts = FAKE.mutations()
        self.assertEqual([(m, "access/apps" in p) for m, p in muts], [("PUT", True)])
        self.assertEqual(FAKE.apps[0]["session_duration"], "30m")

    def test_rerun_without_session_keeps_the_configured_session(self):
        self.apply()
        self.assertEqual(FAKE.apps[0]["session_duration"], "4h", "first run uses the default")
        self.apply("--session", "168h")
        self.assertEqual(FAKE.apps[0]["session_duration"], "168h", "an explicit --session changes it")
        FAKE.log.clear()
        code, _, err = self.apply()
        self.assertEqual(code, 0, err)
        self.assertEqual(FAKE.apps[0]["session_duration"], "168h")
        self.assertEqual(FAKE.mutations(), [], "no PUT to the app (or anything else)")
        self.apply("--session", "30m")
        self.assertEqual(FAKE.apps[0]["session_duration"], "30m", "explicit still wins afterwards")

    def test_saved_config_contains_hostname_and_session(self):
        path = os.path.join(self.tmp, "swarmbox", "cloudflare.json")
        self.apply("--session", "168h", "--hostname", "tty.talkr.run")
        with open(path) as f:
            saved = json.load(f)
        self.assertEqual(saved["hostname"], "tty.talkr.run")
        self.assertEqual(saved["name"], "swarmbox")
        self.assertEqual(saved["session"], "168h")

    def test_rerun_without_hostname_serves_the_saved_hostname_for_the_same_name(self):
        self.apply("--hostname", "tty.talkr.run")
        FAKE.log.clear()
        code, out, err = self.apply()
        self.assertEqual(code, 0, err)
        self.assertIn("tty.talkr.run", out)
        self.assertNotIn("swarmbox.talkr.run", out)

    def test_saved_hostname_is_ignored_for_another_name(self):
        self.apply("--hostname", "tty.talkr.run")
        code, out, err = self.apply("--name", "other")
        self.assertIn("other.talkr.run", out)

    def test_rerun_keeps_the_session_from_cloudflare_json_when_the_app_is_gone(self):
        self.apply("--session", "168h")
        FAKE.apps.clear()
        self.apply()
        self.assertEqual(FAKE.apps[0]["session_duration"], "168h")

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

    def test_dry_run_does_not_save_the_session(self):
        self.apply("--dry-run", "--session", "168h")
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "swarmbox", "cloudflare.json")))

    def test_drifted_app_is_repaired(self):
        self.apply()
        FAKE.apps[0]["policies"] = [{"id": "someone-elses-policy", "precedence": 1}]  # e.g. a bypass
        FAKE.log.clear()
        self.apply()
        self.assertEqual(FAKE.apps[0]["policies"], [{"id": FAKE.policies[0]["id"], "precedence": 1}])

    def test_drifted_route_loses_access_requirement_is_repaired(self):
        self.apply()
        cfg = FAKE.configs[FAKE.tunnels[0]["id"]]
        del self.host_rule()["originRequest"]["access"]
        FAKE.log.clear()
        self.apply()
        self.assertTrue(self.host_rule()["originRequest"]["access"]["required"])

    def test_second_container_reuses_tunnel_and_keeps_first_route(self):
        self.apply()
        self.apply("--name", "second", "--port", "7682")
        self.assertEqual(len(FAKE.tunnels), 1)
        hosts = [r.get("hostname") for r in FAKE.configs[FAKE.tunnels[0]["id"]]["ingress"]]
        self.assertEqual(hosts, ["swarmbox.talkr.run", "second.talkr.run", None])
        self.assertEqual(self.host_rule("second.talkr.run")["service"], "http://localhost:7682")
        self.assertEqual(len(FAKE.apps), 2)
        self.assertEqual(len(FAKE.dns), 2)

    def test_existing_unrelated_ingress_rules_are_preserved(self):
        FAKE.tunnels.append({"id": "tunX", "name": "swarmbox", "config_src": "cloudflare"})
        FAKE.configs["tunX"] = {"ingress": [{"hostname": "other.talkr.run", "service": "http://localhost:9"},
                                            {"service": "http_status:404"}],
                                "warp-routing": {"enabled": False}}
        self.apply()
        cfg = FAKE.configs["tunX"]
        first = cfg["ingress"][0]  # (the fake decorates stored rules; we only care it was kept)
        self.assertEqual((first["hostname"], first["service"]), ("other.talkr.run", "http://localhost:9"))
        self.assertEqual(cfg["warp-routing"], {"enabled": False})

    def test_existing_one_time_pin_is_reused(self):
        FAKE.idps.append({"id": "idp-existing", "type": "onetimepin", "name": "OTP"})
        self.apply()
        self.assertEqual(FAKE.apps[0]["allowed_idps"], ["idp-existing"])
        self.assertFalse([1 for m, p in FAKE.mutations() if "identity_providers" in p])

    def test_wrong_dns_target_is_fixed(self):
        FAKE.dns.append({"id": "d0", "type": "CNAME", "name": "swarmbox.talkr.run",
                         "content": "old.example.net", "proxied": False})
        self.apply()
        self.assertEqual(len(FAKE.dns), 1)
        self.assertTrue(FAKE.dns[0]["content"].endswith(".cfargotunnel.com"))
        self.assertTrue(FAKE.dns[0]["proxied"])

    def test_refuses_to_replace_a_non_cname_record(self):
        FAKE.dns.append({"id": "d0", "type": "A", "name": "swarmbox.talkr.run", "content": "1.2.3.4"})
        code, _, err = self.apply()
        self.assertNotEqual(code, 0)
        self.assertIn("already has a A record", err)
        self.assertEqual([r["id"] for r in FAKE.dns], ["d0"])

    def test_locally_managed_tunnel_is_refused(self):
        FAKE.tunnels.append({"id": "tunL", "name": "swarmbox", "config_src": "local"})
        code, _, err = self.apply()
        self.assertNotEqual(code, 0)
        self.assertIn("configured locally", err)

    def test_saved_answers_make_the_next_run_shorter(self):
        self.apply()
        FAKE.log.clear()
        code, _, err = self.run_cli("--no-connector", "--no-verify")
        self.assertEqual(code, 0, err)
        self.assertEqual(FAKE.mutations(), [])


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

    def test_unrecognized_token_is_not_reported_as_a_permission_problem(self):
        code, _, err = self.apply(env={"CLOUDFLARE_API_TOKEN": "invalid9109"})
        self.assertNotEqual(code, 0)
        self.assertIn("does not recognize this token", err)
        self.assertIn("11 characters", err)          # helps spot a truncated paste
        self.assertNotIn("invalid9109", err)         # ...without echoing the token
        self.assertEqual(FAKE.mutations(), [])

    def test_global_api_key_is_recognised(self):
        key = "0123456789abcdef0123456789abcdef01234"
        code, _, err = self.apply(env={"CLOUDFLARE_API_TOKEN": "invalid9109"})
        self.assertIn("characters", err)
        self.assertIn("Global API Key", cs.token_shape(key))

    def test_pasted_token_is_cleaned_of_terminal_escapes(self):
        self.assertEqual(cs.clean_token("\x1b[200~abc-DEF_123\x1b[201~\r\n "), "abc-DEF_123")
        code, _, err = self.apply(env={"CLOUDFLARE_API_TOKEN": "\x1b[200~" + GOOD_TOKEN + "\x1b[201~\n"})
        self.assertEqual(code, 0, err)

    def test_subdomain_given_as_domain_points_to_the_zone(self):
        code, _, err = self.run_cli("--domain", "tty.talkr.run", "--email", "a@b.co", "--no-connector", "--no-verify")
        self.assertNotEqual(code, 0)
        self.assertIn("is a subdomain, not a Cloudflare zone", err)
        self.assertIn("--domain talkr.run --hostname tty.talkr.run", err)
        self.assertEqual(FAKE.mutations(), [])

    def test_serving_exactly_a_chosen_hostname(self):
        code, out, err = self.apply("--hostname", "tty.talkr.run")
        self.assertEqual(code, 0, err)
        self.assertIn("https://tty.talkr.run", out)
        self.assertNotIn("--reset --web", out)
        self.assertNotIn("SWARMBOX_WEB_DOMAIN", out)
        self.assertEqual(FAKE.apps[0]["domain"], "tty.talkr.run")
        self.assertEqual(FAKE.dns[0]["name"], "tty.talkr.run")
        self.assertEqual(self.host_rule("tty.talkr.run")["service"], "http://localhost:7681")

    def test_missing_token_without_a_terminal_fails_clearly(self):
        saved = os.environ.pop("CLOUDFLARE_API_TOKEN", None)
        try:
            code, _, err = self.run_cli(*BASE, env={"CLOUDFLARE_API_TOKEN": ""})
        finally:
            if saved:
                os.environ["CLOUDFLARE_API_TOKEN"] = saved
        self.assertNotEqual(code, 0)
        self.assertIn("CLOUDFLARE_API_TOKEN", err)

    def test_unknown_domain(self):
        code, _, err = self.run_cli("--domain", "nope.example", "--email", "a@b.co", "--no-connector", "--no-verify")
        self.assertNotEqual(code, 0)
        self.assertIn("was not found", err)
        self.assertEqual(FAKE.mutations(), [])

    def test_zero_trust_not_enabled_is_explained(self):
        FAKE.org_error = True
        code, _, err = self.apply()
        self.assertNotEqual(code, 0)
        self.assertIn("one.dash.cloudflare.com", err)
        self.assertIn("Zero Trust is not activated", err)
        self.assertNotIn("lacks a permission", err)   # it is not a token problem
        self.assertEqual(FAKE.mutations(), [])

    def test_input_validation(self):
        self.assertNotEqual(self.run_cli("--domain", "talkr.run", "--email", "not-an-email", "--no-connector")[0], 0)
        self.assertNotEqual(self.apply("--hostname", "x.other.com")[0], 0)
        self.assertNotEqual(self.apply("--session", "forever")[0], 0)
        self.assertNotEqual(self.apply("--port", "70000")[0], 0)
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

    def test_needs_neither_an_email_nor_the_other_settings(self):
        self.apply()
        code, out, _ = self.run_cli("token", "--domain", "talkr.run", "--tunnel", "swarmbox")
        self.assertEqual(code, 0)
        self.assertTrue(out.startswith("tok."))

    def test_unknown_tunnel_is_a_clear_error_with_empty_stdout(self):
        code, out, err = self.run_cli("token", "--domain", "talkr.run")
        self.assertNotEqual(code, 0)
        self.assertEqual(out, "")
        self.assertIn("does not exist in this account yet", err)
        self.assertEqual(FAKE.mutations(), [])

    def test_a_subdomain_given_as_the_zone_is_explained_with_empty_stdout(self):
        code, out, err = self.run_cli("token", "--domain", "tty.talkr.run")
        self.assertNotEqual(code, 0)
        self.assertEqual(out, "")
        self.assertIn("is a subdomain, not a Cloudflare zone", err)

    def test_a_bad_api_token_explains_and_prints_nothing(self):
        code, out, err = self.run_cli("token", "--domain", "talkr.run", env={"CLOUDFLARE_API_TOKEN": "invalid9109"})
        self.assertNotEqual(code, 0)
        self.assertEqual(out, "")
        self.assertIn("does not recognize this token", err)

    def test_the_final_message_of_apply_tells_how_to_get_it_before_deleting_the_api_token(self):
        _, out, _ = self.apply()
        self.assertIn('export SWARMBOX_CLOUDFLARE_TUNNEL_TOKEN="$(./', out)
        self.assertIn("then delete the API token", out)


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
        self.assertEqual(hosts, ["swarmbox.talkr.run", None])
        self.assertEqual([a["domain"] for a in FAKE.apps], ["swarmbox.talkr.run"])
        self.assertEqual(len(FAKE.dns), 1)

    def test_remove_last_route_leaves_a_valid_catch_all(self):
        self.apply()
        self.run_cli("remove", "--domain", "talkr.run", "--yes")
        self.assertEqual(FAKE.configs[FAKE.tunnels[0]["id"]]["ingress"], [{"service": "http_status:404"}])
        self.assertEqual((FAKE.apps, FAKE.policies, FAKE.dns), ([], [], []))

    def test_remove_requires_confirmation_without_a_terminal(self):
        self.apply()
        FAKE.log.clear()
        code, _, err = self.run_cli("remove", "--domain", "talkr.run")
        self.assertNotEqual(code, 0)
        self.assertEqual(FAKE.mutations(), [])


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

    def test_connector_failure_keeps_cloudflare_configured_and_a_retry_only_fixes_the_connector(self):
        code, out, err = self.run_cli(*self.conn, env={"SHIM_RUN_FAIL": "1"})
        self.assertEqual(code, 3)
        # everything on the Cloudflare side exists, login first
        self.assertEqual((len(FAKE.apps), len(FAKE.policies), len(FAKE.dns), len(FAKE.tunnels)), (1, 1, 1, 1))
        # short, actionable message instead of the whole pull log
        self.assertIn("could not start the connector", err)
        self.assertIn("run it from your host shell", err)
        self.assertNotIn("Trying to pull", err)
        self.assertIn("hostname is protected by the login", out)
        self.assertNotIn("Done. Open the URL", out)
        self.assertTrue(os.path.exists(os.path.join(self.tmp, "swarmbox", "cloudflare.json")),
                        "answers are saved before the connector step")
        FAKE.log.clear()
        code, out, err = self.run_cli("--no-verify")  # no flags: reads the saved domain/email
        self.assertEqual(code, 0, err)
        self.assertEqual(FAKE.mutations(), [], "retry must not touch Cloudflare again")
        self.assertEqual(len([c for c in self.calls() if c.startswith("run ")]), 1 + 1)

    def test_running_inside_a_container_warns_about_the_connector_and_token(self):
        original = cs.inside_container
        cs.inside_container = lambda: True
        try:
            code, out, err = self.run_cli(*self.conn)
        finally:
            cs.inside_container = original
        self.assertEqual(code, 0, err)
        self.assertIn("running inside a container", err)
        self.assertIn("host shell", err)

    def test_stopped_connector_is_started_not_recreated(self):
        self.run_cli(*self.conn)
        with open(os.path.join(self.shim, "state")) as f:
            tok = f.read().split()[1]
        with open(os.path.join(self.shim, "state"), "w") as f:
            f.write("exited %s\n" % tok)
        self.run_cli(*self.conn)
        self.assertEqual(len([c for c in self.calls() if c.startswith("run ")]), 1)
        self.assertTrue([c for c in self.calls() if c.startswith("start ")])


    # ---- remove stops the connector only when nothing else uses the tunnel; image pinning
    def remove(self, *extra):
        return self.run_cli("remove", "--domain", "talkr.run", "--yes", *extra)

    def test_remove_stops_connector_when_no_other_hostname_uses_the_tunnel(self):
        self.run_cli(*self.conn)
        self.assertTrue(os.path.exists(os.path.join(self.shim, "state")))
        code, out, err = self.remove()
        self.assertEqual(code, 0, err)
        self.assertIn("rm -f swarmbox-cloudflared", self.calls())
        self.assertFalse(os.path.exists(os.path.join(self.shim, "state")), "connector gone")
        self.assertNotIn("were left in place", out)

    def test_remove_keeps_connector_when_another_hostname_remains(self):
        self.run_cli(*self.conn)
        self.run_cli(*self.conn, "--name", "second", "--port", "7682")
        before = len(self.calls())
        code, out, err = self.remove("--name", "second")
        self.assertEqual(code, 0, err)
        self.assertEqual([c for c in self.calls()[before:] if c.startswith(("rm", "stop"))], [])
        self.assertTrue(os.path.exists(os.path.join(self.shim, "state")), "connector still runs")
        self.assertIn("still used", out)

    def test_remove_without_a_connector_container_calls_no_rm(self):
        self.apply()
        code, _, err = self.remove()
        self.assertEqual(code, 0, err)
        self.assertEqual([c for c in self.calls() if c.startswith(("rm", "stop"))], [])

    def test_remove_dry_run_does_not_touch_the_connector(self):
        self.run_cli(*self.conn)
        FAKE.log.clear()
        before = len(self.calls())
        code, out, err = self.remove("--dry-run")
        self.assertEqual(code, 0, err)
        self.assertEqual(FAKE.mutations(), [])
        self.assertEqual([c for c in self.calls()[before:] if c.startswith(("rm", "stop", "start", "run"))], [])
        self.assertTrue(os.path.exists(os.path.join(self.shim, "state")))
        self.assertIn("would stop and remove connector", out + err)

    def test_remove_dry_run_with_another_hostname_reports_no_stop(self):
        self.run_cli(*self.conn)
        self.run_cli(*self.conn, "--name", "second", "--port", "7682")
        code, out, err = self.remove("--name", "second", "--dry-run")
        self.assertNotIn("would stop", out + err)

    def test_default_connector_image_is_pinned(self):
        self.assertNotIn(":latest", cs.DEFAULT_CONNECTOR_IMAGE)
        self.assertRegex(cs.DEFAULT_CONNECTOR_IMAGE, r"^docker\.io/cloudflare/cloudflared:\d{4}\.\d+\.\d+$")
        with open(SCRIPT) as f:
            self.assertNotIn("cloudflared:latest", f.read())
        self.run_cli(*self.conn)
        run = [c for c in self.calls() if c.startswith("run ")][0]
        self.assertIn(cs.DEFAULT_CONNECTOR_IMAGE, run)

    def test_env_override_of_the_connector_image(self):
        code, _, err = self.run_cli(*self.conn, env={"SWARMBOX_CLOUDFLARED_IMAGE": "example.test/cf:1.2.3"})
        self.assertEqual(code, 0, err)
        run = [c for c in self.calls() if c.startswith("run ")][0]
        self.assertIn("example.test/cf:1.2.3", run)
        self.assertNotIn(cs.DEFAULT_CONNECTOR_IMAGE, run)

    def test_flag_beats_the_env_override(self):
        self.run_cli(*self.conn, "--connector-image", "example.test/flag:9",
                     env={"SWARMBOX_CLOUDFLARED_IMAGE": "example.test/cf:1.2.3"})
        run = [c for c in self.calls() if c.startswith("run ")][0]
        self.assertIn("example.test/flag:9", run)

    def test_token_never_appears_in_podman_argv_after_the_changes(self):
        self.run_cli(*self.conn, "--session", "168h")
        self.run_cli(*self.conn)
        self.remove()
        self.assertTrue(self.calls())
        for c in self.calls():
            self.assertNotIn("tok.", c)


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

    def test_200_without_login_is_exposed(self):
        self.assertEqual(cs.check_protected(self.serve(200), timeout=5)[0], "exposed")

    def test_redirect_elsewhere_is_not_protection(self):
        url = self.serve(302, "https://example.com/")
        self.assertEqual(cs.check_protected(url, timeout=1)[0], "unknown")


if __name__ == "__main__":
    unittest.main(verbosity=2)
