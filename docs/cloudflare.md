# Remote access: `swarmbox remote` (Cloudflare Tunnel + Access, e-mail one-time code)

```
browser ── https://swarmbox.example.com ──> Cloudflare Access (email code) ──> tunnel
                                                                         │ outbound only
                                          cloudflared (Podman, this host) ┘──> 127.0.0.1:7681
```

`cloudflared` runs **on the host, not in the box**, so the tunnel credentials never reach the agent (decision D14).
It only makes outbound connections: no router port, no public IP. Free plan (Zero Trust, up to 50 users); a card may
be requested to activate it. Remote access is part of the 2.0 scope (D39). Design: section 5.2 of `docs/design.md`.

`swarmbox remote` is a thin wrapper over `cloudflare-setup.py`, which sits next to the host helper. It is the only part
of the host side that needs `python3` (3.8+, no other dependency; the helper itself is POSIX `sh`, D16). If `python3` or
the script is missing, the command exits with status 3 and says so.

| Command | Runs the script's | What it does |
|---|---|---|
| `swarmbox remote setup` | `apply` | provisions everything below; idempotent |
| `swarmbox remote status` | `status` | read-only report and login check, then host-side lines (public address, connector, login session) |
| `swarmbox remote off` | `remove` | removes the hostname, stops the connector when no other hostname uses the tunnel |
| `swarmbox remote token` | `token` | prints **only** the tunnel token on stdout |

`swarmbox url` prints the local address and, when remote access is configured, the public one. It never calls Podman.

```bash
export CLOUDFLARE_API_TOKEN=...          # or run the command and paste it when asked (input hidden)
swarmbox remote setup --domain example.com --email you@example.com
swarmbox remote status
swarmbox url
```

## API token

You need a domain on Cloudflare and a one-time **API token**
(<https://dash.cloudflare.com/profile/api-tokens> -> Create Custom Token):

| Scope   | Permission                                            | Level |
|---------|-------------------------------------------------------|-------|
| Account | Cloudflare Tunnel                                     | Edit  |
| Account | Access: Apps and Policies                             | Edit  |
| Account | Access: Organizations, Identity Providers, and Groups | Edit  |
| Zone    | DNS                                                   | Edit  |
| Zone    | Zone                                                  | Read  |

Include your account and the zone in the token's resources, and activate Zero Trust once at
<https://one.dash.cloudflare.com>. The API token is only read from the environment or the prompt: it is never stored,
never put on a command line and never printed. Delete it when the command finishes.

## What it provisions

In this order (the login always exists before anything is routable):

1. an *Access policy* allowing only your e-mail(s), and an *Access application* for `<name>.<domain>` that offers only
   the One-time PIN login (session 4h on a first setup);
2. one *Tunnel* per account (`swarmbox`), shared by all your boxes, with the route `<name>.<domain>` ->
   `http://localhost:<port>`. The route makes `cloudflared` itself require the Access token, so a mistake in the
   Access policy cannot expose the shell;
3. the proxied *DNS* record (it refuses to overwrite a non-CNAME record);
4. the `cloudflared` connector as a Podman container on the host (`swarmbox-cloudflared`, `--restart=always`);
5. a check that the hostname redirects to the Cloudflare login (a loud error if it answers without one).

Your domain, e-mails, hostname, box name and session length are remembered in `~/.config/swarmbox/cloudflare.json`
(under `XDG_CONFIG_HOME` when set), so later runs need no flags.

## Options

Options go after the subcommand and are passed to the script unchanged. The wrapper adds `--name` (from
`SWARMBOX_NAME`) and `--port` (the resolved `WEB_PORT`) first, so your own `--name` or `--port` wins.

| Option | Meaning |
|---|---|
| `--domain` | the Cloudflare *zone* (`example.com`), not a subdomain (env `SWARMBOX_WEB_DOMAIN`, remembered) |
| `--email` | comma-separated e-mails allowed to log in (env `SWARMBOX_WEB_EMAIL`, remembered) |
| `--name` | box name; the hostname is `<name>.<domain>` (default `swarmbox`) |
| `--hostname` | serve exactly this hostname (for example `tty.example.com`); keep it one level below the zone, the free certificate does not cover `a.b.example.com` |
| `--port` | host port of the web terminal (default 7681) |
| `--session` | login length, for example `30m` or `168h`; see "Rerun keeps the session" |
| `--tunnel` | tunnel name, shared by all hostnames (default `swarmbox`) |
| `--dry-run` | read-only: show what would change (also checks the API token); setup and off |
| `--no-connector` | do not run `cloudflared` with Podman (run it yourself, with `swarmbox remote token`) |
| `--connector-image` | the `cloudflared` image; see "The connector image" |
| `--print-token` | print the tunnel token during setup (to run `cloudflared` yourself) |
| `--no-verify` | skip the final login check |
| `-y`, `--yes` | do not ask for confirmation (`remote off`) |

A second box on the same domain: `swarmbox remote setup --name second --port 7682` gives `second.example.com`.

## Tunnel token

Two different credentials. The *API token* is powerful and only needed to provision. The connector needs only the
tunnel's own, much narrower *tunnel token*, which lets whoever holds it join your tunnel. It is read on the host only
and is **never passed into the box**: `env add` refuses `SWARMBOX_CLOUDFLARE_*` names and `--env-keys` of it is refused (D14).

Where `swarmbox up` finds it, in this order:

1. the host environment variable `SWARMBOX_CLOUDFLARE_TUNNEL_TOKEN`;
2. the key `CLOUDFLARE_TUNNEL_TOKEN` in the host config file, **only when that file has mode 600**. This is the one
   secret the config may hold (D28). A looser mode is refused with a warning naming `chmod 600 <file>`. The mode check
   is portable (`stat -c %a`, `stat -f %Lp`, then `find -perm`). `swarmbox config list` shows the key only as set.

After a successful `remote setup` on a terminal (not with `--dry-run`), when no token is stored yet, the command
**offers** to fetch it and store it; the default answer is no. By hand:

```bash
swarmbox remote token                          # only the token on stdout: usable inside $(...)
swarmbox config set CLOUDFLARE_TUNNEL_TOKEN    # type or paste it; stored with mode 600
```

`remote token` needs the API token once, so run it before deleting the API token. With a token available, every
`swarmbox` entry (`up`) makes sure the connector is up: a missing `swarmbox-cloudflared` container is created, a
stopped one is started, and one holding a different token is recreated. Without a token an existing connector is
only started when stopped. The token goes to Podman through the environment, never a command line, and is never printed.
`reset` and `stop` never touch the connector.

**Rotating.** In the Cloudflare dashboard (Networking -> Tunnels -> your tunnel; older UIs: Zero Trust -> Networks ->
Tunnels) refresh the token, put the new value in the environment or the config key, and run `swarmbox up`: it notices
the connector holds a different token and recreates it. Rotate if the token may have been exposed.

## Rerun keeps the session

Running `remote setup` again without `--session` keeps the login length already configured (v0.1.0 reset it to 4h; that is
history). The order is: an explicit `--session`, else the value on the existing Access application, else the `session`
key in `cloudflare.json`, else `4h` (a first setup only).

## Remote off

`swarmbox remote off` removes the DNS record, the tunnel route, the Access application and its policy (route first,
login last). It then stops and removes the `swarmbox-cloudflared` container, but only when the tunnel's remaining
routes name no other hostname. The tunnel itself stays in your account. `--dry-run` only reports what it would do.
It asks for confirmation unless `-y` is given.

## The connector image

The image is pinned: `docker.io/cloudflare/cloudflared:2026.10.7` (never `latest`, so an upstream release cannot change
what runs on your host unannounced). Override it, in this order, with `--connector-image`, then the environment variable
`SWARMBOX_CLOUDFLARED_IMAGE`, then the pinned default. `swarmbox up` uses the same pin. Bumping the pin is a code change
checked by a test that keeps the script and the helper equal.

## Running outside a box

`cloudflare-setup.py` also runs on its own, with the same commands (`apply`, `status`, `remove`, `token`) and the same
options, for a host where the helper is not installed. v0.1.0 users ran it as `./cloudflare-setup.py` together with
`./start.sh --web`; that is history, and `start.sh` stays only until the 2.0 migration. To run `cloudflared` yourself
(for example as a systemd service) use `--no-connector` with `swarmbox remote token`.

Rootless Podman does not restart a `--restart=always` container after a reboot unless `podman-restart.service` is
enabled for your user (and, on systemd, lingering lets it start without a login). `swarmbox up` brings the connector
back on the next entry in any case. The reboot behavior was not tried (no systemd in the build sandbox) and is
`[unverified]` (B16); the checklist below covers it.

## Owner checklist: the one end-to-end run no fake can replace

No real Cloudflare account was available while this was built. The commands were tested against a fake Cloudflare API
and a fake `podman` only. Run this once, on a real host with a real domain, and note anything that differs.

1. `swarmbox remote setup --dry-run --domain example.com --email you@example.com`: reads only; it lists what it
   would create and confirms that the API token has the right scopes. Nothing changes in Cloudflare.
2. `swarmbox remote setup`: creates the policy, application, tunnel route, DNS record and the connector. Answer the
   token offer (y to keep the tunnel token at mode 600 in the host config, or n and export it).
3. `swarmbox remote status`: the report says the login check passes; host lines show the public address, the
   connector running and the login session. `swarmbox url` prints the same name.
4. Open the URL from outside your network (a phone on mobile data): Cloudflare asks for your e-mail, mails a
   one-time code, and the terminal opens after you enter it. A different e-mail must be refused.
5. Run `swarmbox remote setup` again without `--session`: the session length stays as it was.
6. Reboot behavior of the connector (B16): reboot the host, do not run `swarmbox`, wait a minute, run
   `podman ps --filter name=swarmbox-cloudflared` and `swarmbox remote status`. Note whether it came back by itself
   (needs `podman-restart.service` enabled for your user; `systemctl --user enable --now podman-restart.service`) or
   only after `swarmbox up`.
7. `swarmbox remote off --dry-run`, then `swarmbox remote off`: the URL stops answering, the connector container is
   gone, `swarmbox remote status` reports nothing configured. Delete the API token in the Cloudflare dashboard.

Report results back; the 5.owner-checklist row of `docs/implementation-status.md` is then set to done.

Tests (fake Cloudflare API and fake podman, no network): `python3 tests/test_cloudflare_setup.py`,
`python3 tests/test_host_remote.py`, `python3 tests/test_host_connector.py`, `python3 tests/test_host_up.py`.

[Back to the README](../README.md)
