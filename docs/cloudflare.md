# Remote access: Cloudflare Tunnel + Access (email one-time code)

```
browser ── https://swarmbox.example.com ──> Cloudflare Access (email code) ──> tunnel
                                                                         │ outbound only
                                          cloudflared (Podman, this host) ┘──> localhost:7681
```

`cloudflared` runs **on the host, not in the container**, so the tunnel credentials are
never inside the agent's reach. It only makes outbound connections: no router port, no
public IP. Free plan (Zero Trust, up to 50 users); a card may be requested to activate it.

`cloudflare-setup.py` provisions all of it and is **idempotent** (run it again and it only
changes what differs). Python 3.8+, no dependencies:

```bash
export CLOUDFLARE_API_TOKEN=...        # or just run it and paste when asked (input hidden)
./cloudflare-setup.py --domain example.com --email you@example.com
SWARMBOX_WEB_DOMAIN=example.com ./start.sh --reset --web
# open https://swarmbox.example.com and log in with the e-mail code
```

You need a domain on Cloudflare and a one-time **API token**
(<https://dash.cloudflare.com/profile/api-tokens> → Create Custom Token):

| Scope   | Permission                                            | Level |
|---------|-------------------------------------------------------|-------|
| Account | Cloudflare Tunnel                                     | Edit  |
| Account | Access: Apps and Policies                             | Edit  |
| Account | Access: Organizations, Identity Providers, and Groups | Edit  |
| Zone    | DNS                                                   | Edit  |
| Zone    | Zone                                                  | Read  |

Include your account and the zone in the token's resources, and activate Zero Trust once
at <https://one.dash.cloudflare.com>. The token is only read from the environment/prompt:
it is never stored or printed, and you can delete it when the script finishes.

What it sets up, in this order (the login always exists before anything is routable):

1. an *Access policy* allowing only your e-mail(s), and an *Access application* for
   `<name>.<domain>` that offers only the One-time PIN login (session 4h by default);
2. one *Tunnel* per account (`swarmbox`), shared by all your containers, with the route
   `<name>.<domain>` -> `http://localhost:<port>`. The route makes `cloudflared` itself
   require the Access token, so even a mistake in the Access policy cannot expose the shell;
3. the proxied *DNS* record (it refuses to overwrite a non-CNAME record);
4. the `cloudflared` connector as a Podman container (`swarmbox-cloudflared`, restarted
   automatically; rootless Podman restarts it after a reboot only if
   `podman-restart.service` is enabled);
5. a check that the hostname redirects to the Cloudflare login (and a loud error if it
   answers without one).

```bash
./cloudflare-setup.py --dry-run          # read-only: what would change (also checks your token)
./cloudflare-setup.py status             # read-only report + login check
./cloudflare-setup.py --name second --port 7682    # another container: second.example.com
./cloudflare-setup.py remove --name second --yes   # undo one hostname (route first, login last)
./cloudflare-setup.py --help             # --session, --tunnel, --hostname, --no-connector, ...
```

Your domain and e-mails are remembered in `~/.config/swarmbox/cloudflare.json`, so later
runs need no flags. `--domain` is the Cloudflare *zone* (`example.com`), not a subdomain. To
serve a specific name such as `tty.example.com`, add `--hostname tty.example.com` (and start with
`SWARMBOX_WEB_HOSTNAME=tty.example.com` so `start.sh` prints that URL). Keep names
one level below the zone: Cloudflare's free certificate does not cover `a.b.example.com`. To run `cloudflared` yourself (e.g. as a
systemd service), use `--no-connector --print-token`.

**Two different credentials.** The *API token* above is powerful and only needed to provision: delete it
once the script finishes. The connector needs only the tunnel's own, much narrower *tunnel token*.

**Bring the tunnel up with `--web`, using only the tunnel token.** Put the tunnel's token in an environment
variable **on the host** (the Cloudflare dashboard shows it: Networking -> Tunnels -> your tunnel; in older
UIs Zero Trust -> Networks -> Tunnels. Or
`./cloudflare-setup.py token`, which prints **only** that token, so it can be used in `$(...)`; it still needs the
API token once, so run it *before* deleting the API token):

```bash
export SWARMBOX_CLOUDFLARE_TUNNEL_TOKEN='...'     # e.g. in ~/.zshrc or ~/.bashrc
# or: export SWARMBOX_CLOUDFLARE_TUNNEL_TOKEN="$(./cloudflare-setup.py token --domain example.com)"
./start.sh --web
```

`--web` is only needed to *create* the container (together with `--reset`). Once it exists, both `./start.sh`
and `./start.sh --web` recognise it as a web container (it carries `SWARMBOX_WEB=1` and publishes the
terminal port), accept the flag, use the port it really publishes, and make sure the terminal and the tunnel
are up, for instance after the machine restarted. A container created *without* `--web` still refuses it
(the port could not be added), and its connector is never looked at.

Every time, the tunnel is brought up with no API token:
a missing `swarmbox-cloudflared` container is **created**, a stopped one is **started**, and one holding a
different token (after you rotate it) is **recreated**. Without the variable, an existing connector is just
started if it is stopped. The connector is a Podman container on your host (not inside SwarmBox); the token
goes to Podman through the environment (never a command line), is never printed, and is **never passed to
SwarmBox**: `--env-keys SWARMBOX_CLOUDFLARE_TUNNEL_TOKEN` is refused, because the token lets whoever holds
it join your tunnel and receive requests that already passed the login. `SWARMBOX_CLOUDFLARED_IMAGE`
overrides the `cloudflared` image.

**Rotating the tunnel token.** On the tunnel's page in the dashboard, the refresh-token button invalidates the
current token and generates a new one (every connector must then use the new token). Put the new value in
`SWARMBOX_CLOUDFLARE_TUNNEL_TOKEN` and run `./start.sh --web`: it notices that the connector holds a different
token and recreates it. Rotate if the token may have been exposed, e.g. if it ever ran inside SwarmBox.

Tests (a fake Cloudflare API and a fake podman, no network):
`python3 tests/test_cloudflare_setup.py`, `python3 tests/test_start_web_connector.py`.

[← Back to the README](../README.md)
