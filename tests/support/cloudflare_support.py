"""A fake Cloudflare API on 127.0.0.1 (a random port), shared by test_cloudflare_setup.py (in process) and test_host_remote_e2e_fake.py
(the real script as a subprocess): the objects of the account (tunnels, DNS, Access apps and policies, ingress) in memory, the calls it
records, the answers of a bad token. Importing this module starts the server and sets CLOUDFLARE_API_BASE to it.
"""
import http.server
import json
import os
import re
import socketserver
import threading
import urllib.parse

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
