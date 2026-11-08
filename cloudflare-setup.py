#!/usr/bin/env python3
"""Provision remote access to a SwarmBox web terminal through Cloudflare.

Creates (or updates, or leaves alone) everything needed to reach
`./start.sh --web` from anywhere behind an email one-time-code login:

  1. an Access policy that allows only the e-mail addresses you give
  2. an Access application for <name>.<domain> using only the One-time PIN login
  3. a Cloudflare Tunnel (one per account, shared by all your containers)
  4. the tunnel route <name>.<domain> -> http://localhost:<port>, with the origin
     itself requiring the Access token (so a policy mistake cannot expose the shell)
  5. the DNS record for the hostname
  6. the `cloudflared` connector, run with Podman on this machine

It is idempotent: run it again and it only changes what differs. Nothing is written
to disk except your non-secret answers (domain, e-mails) so the next run is shorter.
The API token is read from CLOUDFLARE_API_TOKEN or prompted, never stored or printed.

Standard library only (Python 3.8+).
"""
import argparse
import getpass
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

API_BASE = os.environ.get("CLOUDFLARE_API_BASE", "https://api.cloudflare.com/client/v4")
CONNECTOR_NAME = "swarmbox-cloudflared"
# Pinned (design 12.3). Override with --connector-image or SWARMBOX_CLOUDFLARED_IMAGE.
DEFAULT_CONNECTOR_IMAGE = "docker.io/cloudflare/cloudflared:2026.10.7"
DEFAULT_SESSION = "4h"  # applies to a first setup only; a rerun keeps what is configured
ACCESS_HOST_MARK = "cloudflareaccess.com"

TOKEN_HELP = """\
API token (create one at https://dash.cloudflare.com/profile/api-tokens, "Create Custom Token"):
  Account  | Cloudflare Tunnel                                      | Edit
  Account  | Access: Apps and Policies                              | Edit
  Account  | Access: Organizations, Identity Providers, and Groups  | Edit
  Zone     | DNS                                                    | Edit
  Zone     | Zone                                                   | Read
  Resources: include your account and the zone (domain) you will use.
Zero Trust must be activated once (free plan): https://one.dash.cloudflare.com
You can delete the token as soon as the script is done."""


# --------------------------------------------------------------------------- output
def say(msg=""):
    print(msg, flush=True)


def ok(msg):
    say("  ✓ " + msg)


DRY = False


def changed(subject, verb):
    if DRY:
        say("  ~ %s would be %s" % (subject, verb))
    else:
        say("  + %s %s" % (subject, verb))


def info(msg):
    say("  · " + msg)


def warn(msg):
    print("  ! " + msg, file=sys.stderr, flush=True)


def die(msg, code=1):
    print("\nERROR: " + msg, file=sys.stderr, flush=True)
    sys.exit(code)


# --------------------------------------------------------------------------- API
class CFError(Exception):
    def __init__(self, status, errors, method, path):
        self.status = status
        self.errors = errors or []
        self.method = method
        self.path = path
        text = "; ".join("%s (code %s)" % (e.get("message"), e.get("code")) for e in self.errors)
        super().__init__("%s %s -> HTTP %s: %s" % (method, path, status, text or "no details"))


class Api:
    def __init__(self, token, dry_run=False):
        self.token = token
        self.dry_run = dry_run

    def raw(self, method, path, body=None, params=None):
        if self.dry_run and method != "GET":
            return {"success": True, "result": {}}
        url = API_BASE + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method, headers={
            "Authorization": "Bearer " + self.token,
            "Content-Type": "application/json",
            "User-Agent": "swarmbox-cloudflare-setup",
        })
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                payload = json.loads(r.read().decode() or "{}")
        except urllib.error.HTTPError as e:
            try:
                payload = json.loads(e.read().decode() or "{}")
            except ValueError:
                payload = {}
            raise CFError(e.code, payload.get("errors"), method, path)
        except urllib.error.URLError as e:
            die("cannot reach the Cloudflare API (%s)" % e.reason)
        if not payload.get("success", True):
            raise CFError(200, payload.get("errors"), method, path)
        return payload

    def call(self, method, path, body=None, params=None):
        return self.raw(method, path, body, params).get("result")

    def paged(self, path, params=None):
        out, page = [], 1
        while True:
            p = dict(params or {})
            p.update({"per_page": 50, "page": page})
            resp = self.raw("GET", path, params=p)
            out += resp.get("result") or []
            if page >= (resp.get("result_info") or {}).get("total_pages", 1):
                return out
            page += 1


def explain(err, token=None):
    """Turn an API error into something actionable."""
    codes = {e.get("code") for e in err.errors}
    hint = ""
    if 9109 in codes or err.status == 401:
        hint = ("Cloudflare does not recognize this token. Usual causes: a truncated or garbled paste, "
                "the Global API Key or a token ID instead of an API Token, or a revoked/expired token.\n"
                + (token_shape(token) + "\n" if token else "")
                + "Check it with:  curl -s -H \"Authorization: Bearer $CLOUDFLARE_API_TOKEN\" "
                  "https://api.cloudflare.com/client/v4/zones?per_page=1")
    elif 9999 in codes or "not_enabled" in str(err) or "not enabled" in str(err).lower():
        # (the API answers 403 for this, so it must be checked before the generic 403 case)
        hint = ("Zero Trust is not activated on this account, so the token is fine but Access cannot be used yet.\n"
                "Activate it once (free plan): open https://one.dash.cloudflare.com, choose a team name and the "
                "Free plan, then run this again.")
    elif err.status == 403:
        hint = "The token is valid but lacks a permission or access to this account/zone.\n" + TOKEN_HELP
    return "%s\n%s" % (err, hint) if hint else str(err)


def clean_token(raw):
    """Drop terminal escape sequences (e.g. bracketed-paste markers), whitespace and control characters."""
    t = re.sub(r"\x1b\[[0-9;?]*[ -/]*[@-~]", "", raw or "")
    return re.sub(r"[^\x21-\x7e]", "", t)


def token_shape(token):
    if re.fullmatch(r"[0-9a-f]{37}", token):
        return "The value you gave has 37 hex characters: that looks like the Global API Key, which this script does not use. Create an API Token instead."
    odd = "" if re.fullmatch(r"[A-Za-z0-9_-]+", token) else " and contains unexpected characters"
    return "The token you gave has %d characters%s (tokens are letters, digits, '-' and '_')." % (len(token), odd)


# --------------------------------------------------------------------------- helpers
EMAIL_RE = re.compile(r"^[^@\s,]+@[^@\s,]+\.[^@\s,]+$")


def parse_emails(value):
    emails = sorted({e.strip().lower() for e in re.split(r"[,\s]+", value or "") if e.strip()})
    bad = [e for e in emails if not EMAIL_RE.match(e)]
    if bad:
        die("not an e-mail address: %s" % ", ".join(bad))
    return emails


def config_path():
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, "swarmbox", "cloudflare.json")


def load_saved():
    try:
        with open(config_path()) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_config(domain, emails, tunnel, session=None):
    path = config_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            data = {"domain": domain, "emails": emails, "tunnel": tunnel}
            if session:
                data["session"] = session
            json.dump(data, f, indent=2)
    except OSError as e:
        warn("could not save %s (%s)" % (path, e))


def ask(label, default=None):
    if not sys.stdin.isatty():
        return None
    suffix = " [%s]" % default if default else ""
    answer = input("%s%s: " % (label, suffix)).strip()
    return answer or default


# --------------------------------------------------------------------------- steps
def find_zone(api, domain):
    """Return (zone_id, account_id) for a Cloudflare zone, or explain what to use instead. Prints nothing."""
    zones = api.call("GET", "/zones", params={"name": domain})
    if not zones:
        labels = domain.split(".")
        for i in range(1, len(labels) - 1):
            parent = ".".join(labels[i:])
            if api.call("GET", "/zones", params={"name": parent}):
                die("'%s' is a subdomain, not a Cloudflare zone: the zone is '%s'.\n"
                    "  - to serve it at <name>.%s:        --domain %s\n"
                    "  - to serve exactly '%s':     --domain %s --hostname %s"
                    % (domain, parent, parent, parent, domain, parent, domain))
        die("domain '%s' was not found in this account/token. Use the zone name (e.g. example.com), "
            "make sure it is added to Cloudflare, and that the token's zone resources include it." % domain)
    return zones[0]["id"], zones[0]["account"]["id"]


def step_zone(api, domain):
    zone, account = find_zone(api, domain)
    ok("domain %s" % domain)
    return zone, account


def step_org(api, account):
    org = api.call("GET", "/accounts/%s/access/organizations" % account) or {}
    auth_domain = org.get("auth_domain") or ""
    if not auth_domain:
        die("Zero Trust has no team name yet. Open https://one.dash.cloudflare.com and finish "
            "the (free) onboarding, then run this again.")
    team = auth_domain.split(".")[0]
    ok("Zero Trust team '%s'" % team)
    return team


def step_idp(api, account):
    for idp in api.call("GET", "/accounts/%s/access/identity_providers" % account) or []:
        if idp.get("type") == "onetimepin":
            ok("login method: One-time PIN")
            return idp["id"]
    created = api.call("POST", "/accounts/%s/access/identity_providers" % account,
                       {"name": "One-time PIN", "type": "onetimepin", "config": {}}) or {}
    changed("login method One-time PIN", "enabled")
    return created.get("id", "<new-idp>")


def policy_emails(policy):
    emails = set()
    for rule in policy.get("include") or []:
        if set(rule) != {"email"}:
            return None
        emails.add((rule["email"] or {}).get("email", "").lower())
    return emails


def step_policy(api, account, host, emails):
    name = "SwarmBox %s" % host
    desired = {
        "name": name,
        "decision": "allow",
        "include": [{"email": {"email": e}} for e in emails],
    }
    existing = next((p for p in api.paged("/accounts/%s/access/policies" % account)
                     if p.get("name") == name), None)
    if existing is None:
        created = api.call("POST", "/accounts/%s/access/policies" % account, desired) or {}
        changed("policy '%s' (allow: %s)" % (name, ", ".join(emails)), "created")
        return created.get("id", "<new-policy>")
    same = (existing.get("decision") == "allow"
            and policy_emails(existing) == set(emails)
            and not existing.get("exclude") and not existing.get("require"))
    if same:
        ok("policy '%s' (allow: %s)" % (name, ", ".join(emails)))
    else:
        api.call("PUT", "/accounts/%s/access/policies/%s" % (account, existing["id"]), desired)
        changed("policy '%s' (allow: %s)" % (name, ", ".join(emails)), "updated")
    return existing["id"]


def step_app(api, account, host, name, session, idp_id, policy_id, saved_session=None):
    """Returns (aud, session). session=None means "not given": keep the value on the existing
    Access app, else the one saved in cloudflare.json, else the default (first setup)."""
    existing = next((a for a in api.paged("/accounts/%s/access/apps" % account, {"domain": host})
                     if a.get("domain") == host), None)
    if not session:
        session = (existing or {}).get("session_duration") or saved_session or DEFAULT_SESSION
    desired = {
        "type": "self_hosted",
        "name": "SwarmBox %s" % name,
        "domain": host,
        "session_duration": session,
        "allowed_idps": [idp_id],
        "auto_redirect_to_identity": True,
        "app_launcher_visible": False,
        "policies": [{"id": policy_id, "precedence": 1}],
    }
    if existing is None:
        created = api.call("POST", "/accounts/%s/access/apps" % account, desired) or {}
        changed("Access application for %s (session %s)" % (host, session), "created")
        return created.get("aud", "<new-aud>"), session
    same = (existing.get("type") == "self_hosted"
            and existing.get("session_duration") == session
            and existing.get("allowed_idps") == [idp_id]
            and bool(existing.get("auto_redirect_to_identity"))
            and [p.get("id") for p in existing.get("policies") or []] == [policy_id])
    if same:
        ok("Access application for %s (session %s)" % (host, session))
    else:
        api.call("PUT", "/accounts/%s/access/apps/%s" % (account, existing["id"]), desired)
        changed("Access application for %s" % host, "updated")
    return existing["aud"], session


def step_tunnel(api, account, tunnel_name):
    found = [t for t in api.call("GET", "/accounts/%s/cfd_tunnel" % account,
                                 params={"name": tunnel_name, "is_deleted": "false"}) or []
             if t.get("name") == tunnel_name]
    if found:
        t = found[0]
        if t.get("config_src") == "local":
            die("tunnel '%s' is configured locally (config file), so its routes cannot be managed "
                "through the API. Use another name with --tunnel." % tunnel_name)
        ok("tunnel '%s'" % tunnel_name)
        return t["id"], False
    created = api.call("POST", "/accounts/%s/cfd_tunnel" % account,
                       {"name": tunnel_name, "config_src": "cloudflare"}) or {}
    changed("tunnel '%s'" % tunnel_name, "created")
    return created.get("id", "<new-tunnel>"), True


def step_route(api, account, tunnel_id, host, port, team, aud):
    path = "/accounts/%s/cfd_tunnel/%s/configurations" % (account, tunnel_id)
    current = {}
    if not tunnel_id.startswith("<new"):
        current = (api.call("GET", path) or {}).get("config") or {}
    rule = {
        "hostname": host,
        "service": "http://localhost:%d" % port,
        # cloudflared itself rejects requests without a valid Access token for this app:
        # the route fails closed even if the Access application were misconfigured.
        "originRequest": {"access": {"required": True, "teamName": team, "audTag": [aud]}},
    }
    cur = current.get("ingress") or []
    cur_rule = next((r for r in cur if r.get("hostname") == host), None)
    rule_ok = (cur_rule is not None
               and cur_rule.get("service") == rule["service"]
               and (cur_rule.get("originRequest") or {}).get("access") == rule["originRequest"]["access"])
    tail_ok = bool(cur) and "hostname" not in cur[-1]  # catch-all rule last
    if rule_ok and tail_ok:
        ok("route %s -> localhost:%d (Access required at the origin)" % (host, port))
        return
    others = [r for r in cur if r.get("hostname") and r["hostname"] != host]
    new_config = dict(current)
    new_config["ingress"] = others + [rule, {"service": "http_status:404"}]
    api.call("PUT", path, {"config": new_config})
    changed("route %s -> localhost:%d (Access required at the origin)" % (host, port), "updated" if cur_rule else "created")


def step_dns(api, zone, host, tunnel_id):
    content = "%s.cfargotunnel.com" % tunnel_id
    records = api.call("GET", "/zones/%s/dns_records" % zone, params={"name": host}) or []
    foreign = [r for r in records if r.get("type") != "CNAME"]
    if foreign:
        die("%s already has a %s record. Refusing to replace it: remove it or pick another --name."
            % (host, foreign[0].get("type")))
    wanted = {"type": "CNAME", "name": host, "content": content, "proxied": True, "ttl": 1,
              "comment": "SwarmBox web terminal"}
    if not records:
        api.call("POST", "/zones/%s/dns_records" % zone, wanted)
        changed("DNS %s -> tunnel" % host, "created")
    elif records[0].get("content") == content and records[0].get("proxied"):
        ok("DNS %s -> tunnel" % host)
    else:
        api.call("PATCH", "/zones/%s/dns_records/%s" % (zone, records[0]["id"]), wanted)
        changed("DNS %s -> tunnel" % host, "updated")


def inside_container():
    return os.path.exists("/run/.containerenv") or os.path.exists("/.dockerenv")


def run_podman(args, env=None):
    return subprocess.run(["podman"] + args, capture_output=True, text=True, env=env)


def step_connector_off(dry_run):
    """Stop and remove the connector container (only called when no hostname uses the tunnel)."""
    if not shutil.which("podman"):
        info("podman not found: if you run cloudflared yourself, stop it yourself.")
        return
    if run_podman(["inspect", "-f", "{{.State.Running}}", CONNECTOR_NAME]).returncode != 0:
        ok("no connector '%s' on this host" % CONNECTOR_NAME)
        return
    if dry_run:
        info("[dry-run] would stop and remove connector '%s'" % CONNECTOR_NAME)
        return
    r = run_podman(["rm", "-f", CONNECTOR_NAME])
    if r.returncode != 0:
        warn("could not remove the connector '%s': %s" % (CONNECTOR_NAME, (r.stderr or r.stdout).strip()[:300]))
        return
    changed("connector '%s'" % CONNECTOR_NAME, "stopped and removed")


def step_connector(api, account, tunnel_id, image, dry_run):
    if tunnel_id.startswith("<new"):
        info("[dry-run] would run the cloudflared connector (%s)" % CONNECTOR_NAME)
        return True
    token = api.call("GET", "/accounts/%s/cfd_tunnel/%s/token" % (account, tunnel_id))
    if not isinstance(token, str) or not token:
        die("could not fetch the tunnel token")
    if inside_container() and not dry_run:
        warn("running inside a container: the connector will stop when this container does, and the "
             "tunnel token will sit within reach of whatever runs here. Prefer running this script "
             "from your host shell.")
    if not shutil.which("podman"):
        warn("podman not found: run cloudflared yourself with this tunnel's token "
             "(use --print-token), or install Podman.")
        return False
    inspect = run_podman(["inspect", "-f",
                          "{{.State.Running}}|{{range .Config.Env}}{{println .}}{{end}}", CONNECTOR_NAME])
    if inspect.returncode == 0:
        running, _, env_text = inspect.stdout.partition("|")
        same_token = ("TUNNEL_TOKEN=" + token) in env_text.splitlines()
        if same_token and running.strip() == "true":
            ok("connector '%s' is running" % CONNECTOR_NAME)
            return True
        if dry_run:
            info("[dry-run] would (re)start connector '%s'" % CONNECTOR_NAME)
            return True
        if same_token:
            run_podman(["start", CONNECTOR_NAME])
            changed("connector '%s'" % CONNECTOR_NAME, "started")
            return True
        run_podman(["rm", "-f", CONNECTOR_NAME])
    if dry_run:
        info("[dry-run] would run connector '%s' (%s)" % (CONNECTOR_NAME, image))
        return True
    env = dict(os.environ, TUNNEL_TOKEN=token)  # in the environment, not on the command line
    # --user root: in rootless Podman that is just your own user, and it avoids needing the image's
    # own user (cloudflared's is 65532) to be mappable, which it is not inside a nested container.
    r = run_podman(["run", "-d", "--name", CONNECTOR_NAME, "--restart=always", "--network=host",
                    "--user", "root", "-e", "TUNNEL_TOKEN", image, "tunnel", "--no-autoupdate", "run"], env=env)
    if r.returncode != 0:
        output = (r.stderr or r.stdout).strip()
        tail = "\n".join("      " + l for l in output.splitlines()[-3:] if l.strip())
        warn("could not start the connector '%s':\n%s" % (CONNECTOR_NAME, tail[:900]))
        if "UIDs or GIDs" in output or "user namespace" in output:
            warn("Podman cannot map this image's user. This usually means the script is running inside "
                 "a SwarmBox/nested container: run it from your host shell instead.")
        return False
    changed("connector '%s' (outbound only; no router port needed)" % CONNECTOR_NAME, "started")
    return True


# --------------------------------------------------------------------------- verification
class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **kw):
        return None


def check_protected(base_url, timeout=60):
    """Return ('protected'|'exposed'|'unknown', detail). Never follows redirects."""
    opener = urllib.request.build_opener(_NoRedirect)
    deadline = time.time() + timeout
    detail = "no answer"
    while True:
        status, location = None, ""
        try:
            req = urllib.request.Request(base_url, headers={"User-Agent": "swarmbox-cloudflare-setup"})
            with opener.open(req, timeout=10) as resp:
                status = resp.status
        except urllib.error.HTTPError as e:
            status, location = e.code, e.headers.get("Location", "") or ""
            e.close()
        except Exception as e:  # DNS not propagated yet, TLS not ready, ...
            detail = str(getattr(e, "reason", e))
        if status in (301, 302, 303, 307, 308) and ACCESS_HOST_MARK in location:
            return "protected", location.split("?")[0]
        if status == 200:
            return "exposed", "HTTP 200 without login"
        if status is not None:
            detail = "HTTP %s" % status
        if time.time() >= deadline:
            return "unknown", detail
        time.sleep(3)


# --------------------------------------------------------------------------- commands
def get_token():
    token = clean_token(os.environ.get("CLOUDFLARE_API_TOKEN", ""))
    if not token and sys.stdin.isatty():
        say(TOKEN_HELP)
        say()
        token = clean_token(getpass.getpass("Cloudflare API token (input hidden): "))
    if not token:
        die("set CLOUDFLARE_API_TOKEN (or run interactively).\n" + TOKEN_HELP)
    return token


def resolve_settings(args):
    saved = load_saved()
    domain = args.domain or os.environ.get("SWARMBOX_WEB_DOMAIN") or saved.get("domain") \
        or ask("Domain (the Cloudflare zone, e.g. example.com; not a subdomain)")
    if not domain:
        die("--domain is required (e.g. --domain example.com)")
    emails = args.email or os.environ.get("SWARMBOX_WEB_EMAIL") or ",".join(saved.get("emails") or []) \
        or ask("E-mail(s) allowed to log in (comma separated)")
    return domain.strip().lower().rstrip("."), parse_emails(emails), saved


def hostname_for(args, domain):
    host = (args.hostname or "%s.%s" % (args.name, domain)).strip().lower()
    if host != domain and not host.endswith("." + domain):
        die("hostname '%s' is not inside '%s'" % (host, domain))
    if host.count(".") > domain.count(".") + 1:
        warn("'%s' is more than one level below the domain: Cloudflare's free certificate only "
             "covers one level (name.%s)." % (host, domain))
    return host


def cmd_apply(args):
    domain, emails, saved = resolve_settings(args)
    if not emails:
        die("--email is required: the address(es) allowed to log in")
    host = hostname_for(args, domain)
    if args.session is not None and not re.match(r"^\d+[mh]$", args.session):
        die("--session must look like 30m or 4h")
    global DRY
    DRY = args.dry_run or args.command == "status"
    api = Api(get_token(), dry_run=DRY)

    say("\nSwarmBox web terminal → https://%s%s\n" % (host, "   (dry run: nothing is changed)" if api.dry_run else ""))
    try:
        zone, account = step_zone(api, domain)
        team = step_org(api, account)
        # Access first: the hostname must never be routable without a login in front of it.
        idp_id = step_idp(api, account)
        policy_id = step_policy(api, account, host, emails)
        aud, session = step_app(api, account, host, args.name, args.session, idp_id, policy_id,
                                saved.get("session"))
        tunnel_id, _created = step_tunnel(api, account, args.tunnel)
        step_route(api, account, tunnel_id, host, args.port, team, aud)
        step_dns(api, zone, host, tunnel_id)
        if not api.dry_run:
            save_config(domain, emails, args.tunnel, session)  # before the connector, so a retry needs no flags
        if args.print_token and not tunnel_id.startswith("<new"):
            say(api.call("GET", "/accounts/%s/cfd_tunnel/%s/token" % (account, tunnel_id)))
        connector_ok = True
        if not args.no_connector:
            image = args.connector_image or os.environ.get("SWARMBOX_CLOUDFLARED_IMAGE") or DEFAULT_CONNECTOR_IMAGE
            connector_ok = step_connector(api, account, tunnel_id, image, api.dry_run)
    except CFError as e:
        die(explain(e, api.token))

    exit_code = 0 if connector_ok else 3
    if not args.no_verify and not tunnel_id.startswith("<new"):
        say("\nChecking that the hostname asks for a login...")
        state, detail = check_protected("https://%s/" % host, timeout=args.verify_timeout)
        if state == "protected":
            ok("protected: unauthenticated visitors are redirected to %s" % detail)
        elif state == "exposed":
            warn("EXPOSED: https://%s answered %s. Remove it now: %s remove --name %s --yes"
                 % (host, detail, os.path.basename(sys.argv[0]), args.name))
            exit_code = 2
        else:
            warn("could not confirm yet (%s). DNS/certificates can take a minute: try "
                 "`%s status` shortly." % (detail, os.path.basename(sys.argv[0])))
    if exit_code == 3 and not api.dry_run:
        say("\nCloudflare is configured and the hostname is protected by the login, but the connector is "
            "not running, so the page will not load yet. Fix the problem above and run this command "
            "again (it only retries what is missing), or use --no-connector to run cloudflared yourself.\n")
    elif exit_code == 0 and not api.dry_run:
        say("\nDone. Start the terminal and open the URL:")
        var = ("SWARMBOX_WEB_HOSTNAME=%s" % host) if args.hostname else ("SWARMBOX_WEB_DOMAIN=%s" % domain)
        say("  %s ./start.sh --reset --web %d" % (var, args.port))
        say("  https://%s   (log in with the e-mail code)" % host)
        say("\nTo have `./start.sh --web` bring the tunnel up from now on without any API token, get the tunnel's "
            "own token now (this still needs the API token), export it on the host, and then delete the API token:\n"
            '  export SWARMBOX_CLOUDFLARE_TUNNEL_TOKEN="$(./%s token)"\n' % os.path.basename(sys.argv[0]))
    return exit_code


def cmd_remove(args):
    domain, _emails, saved = resolve_settings_for_remove(args)
    host = hostname_for(args, domain)
    if not args.yes:
        answer = ask("Remove the SwarmBox web access for https://%s? [y/N]" % host)
        if not answer or answer.lower() not in ("y", "yes"):
            die("aborted (use --yes to skip the question)")
    global DRY
    DRY = args.dry_run
    api = Api(get_token(), dry_run=DRY)
    say("\nRemoving https://%s\n" % host)
    tunnel_seen, remaining = False, []
    try:
        zone, account = step_zone(api, domain)
        # Reverse order of apply: take the route away first, the login last.
        records = api.call("GET", "/zones/%s/dns_records" % zone, params={"name": host}) or []
        for r in records:
            if r.get("type") == "CNAME" and str(r.get("content", "")).endswith(".cfargotunnel.com"):
                api.call("DELETE", "/zones/%s/dns_records/%s" % (zone, r["id"]))
                changed("DNS %s" % host, "removed")
        for t in api.call("GET", "/accounts/%s/cfd_tunnel" % account,
                          params={"name": args.tunnel, "is_deleted": "false"}) or []:
            if t.get("name") != args.tunnel or t.get("config_src") == "local":
                continue
            path = "/accounts/%s/cfd_tunnel/%s/configurations" % (account, t["id"])
            config = (api.call("GET", path) or {}).get("config") or {}
            rest = [r for r in config.get("ingress") or [] if r.get("hostname") != host]
            tunnel_seen = True
            remaining += [r["hostname"] for r in rest if r.get("hostname")]
            if len(rest) != len(config.get("ingress") or []):
                config["ingress"] = rest if any(r.get("hostname") for r in rest) \
                    else [{"service": "http_status:404"}]
                api.call("PUT", path, {"config": config})
                changed("route for %s" % host, "removed")
        for a in api.paged("/accounts/%s/access/apps" % account, {"domain": host}):
            if a.get("domain") == host:
                api.call("DELETE", "/accounts/%s/access/apps/%s" % (account, a["id"]))
                changed("Access application for %s" % host, "removed")
        for p in api.paged("/accounts/%s/access/policies" % account):
            if p.get("name") == "SwarmBox %s" % host:
                api.call("DELETE", "/accounts/%s/access/policies/%s" % (account, p["id"]))
                changed("policy for %s" % host, "removed")
    except CFError as e:
        die(explain(e, api.token))
    if tunnel_seen and not remaining:
        step_connector_off(DRY)
        say("\nDone. The tunnel itself was left in place (delete it in the Cloudflare dashboard if you want).")
    elif tunnel_seen:
        say("\nDone. The tunnel and the '%s' connector are still used by: %s." % (CONNECTOR_NAME, ", ".join(remaining)))
    else:
        say("\nDone. The tunnel and the '%s' connector were left in place (the tunnel was not found here)." % CONNECTOR_NAME)
    return 0


def resolve_settings_for_remove(args):
    saved = load_saved()
    domain = args.domain or os.environ.get("SWARMBOX_WEB_DOMAIN") or saved.get("domain") \
        or ask("Domain (the Cloudflare zone, e.g. example.com; not a subdomain)")
    if not domain:
        die("--domain is required")
    return domain.strip().lower().rstrip("."), [], saved


def cmd_token(args):
    """Print ONLY the tunnel's own token on stdout (everything else goes to stderr), for
    export SWARMBOX_CLOUDFLARE_TUNNEL_TOKEN="$(./cloudflare-setup.py token)"."""
    domain, _emails, _ = resolve_settings_for_remove(args)
    api = Api(get_token())
    try:
        _zone, account = find_zone(api, domain)
        tunnels = [t for t in api.call("GET", "/accounts/%s/cfd_tunnel" % account,
                                       params={"name": args.tunnel, "is_deleted": "false"}) or []
                   if t.get("name") == args.tunnel]
        if not tunnels:
            die("tunnel '%s' does not exist in this account yet: run this script once without a command "
                "to create it." % args.tunnel)
        token = api.call("GET", "/accounts/%s/cfd_tunnel/%s/token" % (account, tunnels[0]["id"]))
    except CFError as e:
        die(explain(e, api.token))
    if not isinstance(token, str) or not token:
        die("could not fetch the tunnel token")
    print(token)
    print("(That is the tunnel's own token: it can only connect a connector to this tunnel, it cannot change "
          "anything in your Cloudflare account. The API token you just used can be deleted now.)", file=sys.stderr)
    return 0


def build_parser():
    p = argparse.ArgumentParser(
        prog=os.path.basename(sys.argv[0]),
        description="Provision Cloudflare access (Tunnel + Access with e-mail one-time code) "
                    "for a SwarmBox web terminal. Idempotent: safe to run again.",
        epilog=TOKEN_HELP + "\n\nExamples:\n"
               "  export CLOUDFLARE_API_TOKEN=...   # or just run it and paste when asked\n"
               "  %(prog)s --domain example.com --email you@example.com\n"
               "  %(prog)s --dry-run                # show what would change (read-only)\n"
               "  %(prog)s status                   # read-only report + login check\n"
               "  %(prog)s token                    # print ONLY the tunnel token (for SWARMBOX_CLOUDFLARE_TUNNEL_TOKEN)\n"
               "  %(prog)s remove --name swarmbox --yes",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("command", nargs="?", default="apply", choices=["apply", "status", "remove", "token"],
                   help="apply (default), status (read-only), remove, token (print only the tunnel token)")
    p.add_argument("--domain", help="the Cloudflare zone, e.g. example.com, not a subdomain (env SWARMBOX_WEB_DOMAIN; remembered)")
    p.add_argument("--email", help="comma-separated e-mails allowed to log in (env SWARMBOX_WEB_EMAIL; remembered)")
    p.add_argument("--name", default="swarmbox", help="container name; hostname is <name>.<domain> (default: swarmbox)")
    p.add_argument("--hostname", help="serve exactly this hostname instead of <name>.<domain> (e.g. tty.example.com)")
    p.add_argument("--port", type=int, default=7681, help="host port given to ./start.sh --web (default: 7681)")
    p.add_argument("--session", default=None,
                   help="login session length, e.g. 30m, 4h. Default: keep the configured value; 4h on a first setup")
    p.add_argument("--tunnel", default="swarmbox", help="tunnel name, shared by all hostnames (default: swarmbox)")
    p.add_argument("--dry-run", action="store_true", help="only read from Cloudflare; show what would change")
    p.add_argument("--no-connector", action="store_true", help="do not run cloudflared with Podman")
    p.add_argument("--connector-image", default=None,
                   help="cloudflared image (default: env SWARMBOX_CLOUDFLARED_IMAGE, else %s)" % DEFAULT_CONNECTOR_IMAGE)
    p.add_argument("--print-token", action="store_true", help="print the tunnel token (to run cloudflared yourself)")
    p.add_argument("--no-verify", action="store_true", help="skip the final login check")
    p.add_argument("--verify-timeout", type=int, default=60, help=argparse.SUPPRESS)
    p.add_argument("-y", "--yes", action="store_true", help="do not ask for confirmation (remove)")
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    if not 1 <= args.port <= 65535:
        die("--port must be 1-65535")
    if args.command == "remove":
        return cmd_remove(args)
    if args.command == "token":
        return cmd_token(args)
    return cmd_apply(args)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
