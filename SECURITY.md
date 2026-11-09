# Security policy

SwarmBox runs AI coding agents in auto-approve mode inside a container. Its security value is the box around the agent, so
please read what the box does and does not protect (below) before you rely on it.

## Reporting a vulnerability

Please report a vulnerability privately, not in a public issue.

- Contact: [OWNER-TODO: security contact, for example a private security advisory link of the repository or a mailbox]
- Include the SwarmBox version (`swarmbox version`), your host (Linux, macOS or WSL) and Podman version, and the steps that reproduce it.
- This project is maintained by one person. Expect an answer within a few days, not hours; a fix is released as a patch
  version of the supported series and named in `CHANGELOG.md`.

Reports about the host helper (`swarmbox-host`, which runs on your machine with your privileges) are the most valuable ones.
The written review of the helper is in `docs/security-review.md`, written by the same AI agent that wrote the code; no human has reviewed it yet.

## Supported versions

| Version | Supported |
|---|---|
| 2.0.x | yes: the newest patch release of the series |
| 0.1.0 and older (`v0.1.0`, the scripts before the redesign) | no |

## What the sandbox protects, and what it does not

A container shares the kernel with your machine, so a kernel or runtime vulnerability can let code in the box escape; for untrusted work use a virtual machine or a dedicated machine (`docs/microvm.md`). The sandbox protects the host's files and processes outside the workspace folder, and the host's Podman socket (it is never
mounted). It does not protect the following, and you should assume all of it when you start an agent (the model is in `docs/design.md`, section 12):

- The agent can change or delete everything in the workspace: all projects, the logins and the SSH key.
- Variables passed in with `swarmbox env` are stored in the container's configuration and are visible to every process in
  the box and to `podman inspect` on the host. API keys passed in are visible to the agent.
- The box has `sudo` and open outbound network.
- Nested Podman is always on and needs `/dev/net/tun` and an unmasked `/proc`, which weakens isolation compared with a plain
  container. It is a deliberate trade-off.
- The box is persistent: an agent keeps running, with those keys, while you are away.
- The SSH key lives in the workspace: anything in the box can use it. Use per-repository deploy keys.
- The web terminal has no login on its own port. It is bound to `127.0.0.1`. With `swarmbox remote`, access goes only through
  Cloudflare Access, and a browser session there is a shell with `sudo`: keep the session length short.
- Tools installed on demand are downloaded by the agent's request. Versions are pinned and checksums verified where the vendor
  publishes them; Claude Code updates itself inside the box.
- The Cloudflare tunnel token may be stored in the host config with mode 600; it never enters the box.

Defaults: no ports published beyond `127.0.0.1`, no host-network mode, tunnel credentials stay on the host.

## Trust in the signed image

The host helper is extracted from the image by `swarmbox init`, so it is versioned, signed and readable before you install
it. SwarmBox accepts the helper as coming from the signed image you already trust (decision D26): there is no separate signed
helper asset. A separately signed asset will be published only if users ask. If you do not trust the image, do not install the
helper from it. Verify the image signature and digest published with each release before you run `init`.

## Logs and telemetry

SwarmBox sends **no telemetry**. It makes no network call of its own except to pull the image, to install a tool you asked for,
to check for a tool update, and, with `swarmbox remote`, to reach Cloudflare. Logs stay on your machine:
`<workspace>/.local/state/swarmbox/` holds `serve.log`, `health` and `web-terminal.log`; on the host only `~/.local/state/swarmbox/` exists (locks and `notices`).

The tools you install have their own policies (Go, for one, keeps local telemetry counters; the others were not checked for
this). They are not part of SwarmBox; read their documentation.
