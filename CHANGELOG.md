# Changelog

All notable changes are listed here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the
project follows [semantic versioning](https://semver.org/).

## [Unreleased]

- Changed: a tab that leaves and comes back (`exit`, then `swarmbox` again in the same terminal tab) is now put back in the same place in the browser, not at the end. The host passes the
  `tty` of the terminal tab, which names it in any terminal or over ssh, and the box keeps the host tabs in the order they first appeared. Dragging the tabs of your terminal is not followed,
  and a window opened from the browser (`Alt+N`) can end up on either side of a returning tab. Needs `swarmbox update` and `swarmbox reset`.
## [2.0.7] - 2026-11-11

- Changed: `exit` in a host terminal tab now ends `swarmbox` and returns you to your own shell. Before, with two tabs open, it closed the window and moved you to the
  shell of the other tab. Each tab has a session of its own with its window linked into the box's session, so the browser still shows every tab, and closing a host tab
  only detaches (the window keeps running and stays in the browser). Needs `swarmbox update` and `swarmbox reset`.
- Dev only: a local gate (`dev/check.sh` and a pre-push hook) and `dev/release.sh`, which releases from a CHANGELOG written beforehand; see CONTRIBUTING.md.

## [2.0.6] - 2026-11-11

- Changed: the web terminal has no scrollbar by default. tmux owns the scrollback (50,000 lines) and the browser has no history of its own, so the bar sat still while the wheel
  scrolled tmux. `scrollbar=true` in `web-terminal.conf` brings back the thin one. Without the bar the browser keeps no scrollback (`scrollback=0` unless you set one): xterm.js reserves
  15 px for a scrollbar it measures as zero width, which cost a column of text.
- Changed: the mouse wheel scrolls tmux's copy mode 5 lines per event (tmux's default) instead of 2. How to change it is in `docs/web-terminal.md`.
- Tests: the browser tests of the web terminal now start ttyd with the options `swarmbox-web run` builds, as in the box, and a real tmux checks the lines per wheel event.

## [2.0.5] - 2026-11-11

- Added: a progress line for the image pull in `swarmbox update`, the first `swarmbox` and the installer, in the colors of the prompt of the box: `[ pull ][ bar and percentage ][ MB done/total ][ MB/s and time ]`,
  and `unpack` when the download is over and Podman writes the layers out. The bytes come from Podman's temporary download folder and the total from the layer sizes of the manifest on `ghcr.io`
  (read with `curl` in the background; without it the bar sweeps and shows no percentage). Powerline separators and an icon are on when Starship runs in your shell (`SWARMBOX_ICONS=1` or `0` forces them);
  `NO_COLOR=1` turns the colors off; `SWARMBOX_PROGRESS=plain` goes back to Podman's own bars; without a terminal the pull stays quiet. A failed pull shows the last lines of Podman's error.

## [2.0.4] - 2026-11-11

- Added: the installers (`install.sh` and `podman run IMAGE install | sh`) write `sx`, a short name for `swarmbox` (`sx up`, `sx claude`), next to the script.
  It is a two-line script that runs the `swarmbox` beside it, so `swarmbox update` keeps working and `sx` always follows it.
  It is written only when nothing else answers to `sx`: no other file of that name in the folder and no `sx` anywhere on the `PATH`
  (a startx replacement has that name); an existing `sx` is never touched and the installer says why none was written. `SWARMBOX_NO_SX=1` skips it.
  A box that is only updated does not get it: run the installer again.

## [2.0.3] - 2026-11-11

- Fixed: `swarmbox update`, the first `swarmbox` and the installer (`install.sh`, `podman run IMAGE install | sh`) showed no progress while they pulled the image, so they looked stuck.
  When standard error is a terminal the pull now shows Podman's own progress, and a failed pull points at the error already on screen. Without a terminal (a script, a log) the pull stays quiet as before.
- The installer now pulls the image in its own step, with the message "pulling IMAGE (this can take a while)...", before it reads the support files from it.

## [2.0.2] - 2026-11-11

Fixes the nested Podman not starting after a host reboot.

- Fixed: after a host reboot the box is stopped and later started again with its own filesystem intact. The nested Podman keeps its runtime state in
  `/tmp/storage-run-<uid>` inside that filesystem, with the boot ID of the previous boot, and refused to start: "current system boot ID differs from cached boot ID;
  an unhandled reboot has occurred". `serve` now removes that folder before it starts the nested service, when it exists, and says so in `serve.log`.
  Nothing of a previous run is alive when `serve` starts, and the nested images and containers are in the volume, not in that folder.

## [2.0.1] - 2026-11-11

Fixes a box that never became ready after a host reboot.

- Fixed: after a host reboot the box's run folder (`/tmp/swarmbox`, a tmpfs) could come back as a folder the agent user cannot write. `serve` then could not write the
  readiness marker or the ttyd pid file, the web terminal gave up after five crashes, and `swarmbox` waited 60 s and failed with "the box did not become ready".
  `serve` now checks the folder first and, when it is not writable, makes it writable with `sudo chmod 1777` (the agent has sudo in the box) and says so in `serve.log`.
- When the box is running but never writes its readiness marker, `swarmbox` now prints the last 15 lines of the box's log before it exits with status 6, so the cause is on screen.
- The cause of the unwritable folder after a reboot is not known; if the nested Podman service still does not start after this fix, send `podman-service.log`.

## [2.0.0] - 2026-11-11

First stable version. Same feature set as the two prereleases (below), with these changes since 2.0.0-beta.2:

- The README now walks through the install from zero with Claude Code (Podman, the installer, the login, the first run) and through remote access to the same tmux session (from a browser with Cloudflare, or over SSH to your machine).
- The image is published at `ghcr.io/feroult/swarmbox` with the tags `2.0.0`, `2.0` and `latest`; `swarmbox update` follows the `2.0` series.

### Features

- One persistent rootless Podman box per workspace; every terminal tab and the browser join the same tmux session.
- A small neutral image (`node:24-trixie-slim`, user `agent`, about 1.75 GB) with no agent inside. Claude Code, Gemini CLI, OpenCode, gcloud, clasp, Go and Poetry
  install on first use from manifests, through shims, with pinned versions and checksums where the vendor publishes them.
- The workspace is one folder of your machine and holds projects, logins, the SSH key and installed tools; the box can be recreated without loss (`swarmbox reset`).
- One executable POSIX `sh` script, `swarmbox`, on the `PATH` (no shell function, no startup file): `up`, `stop`, `reset`, `url`, `update`, `config`, `env`, `pubkey`, `tool`, `remote`, `fingerprint`, `version`; any other word runs in the box.
- Two ways to install it, with the same result: `podman run --rm IMAGE install [--with TOOLS] | sh`, and `install.sh`, which downloads `swarmbox` from a release and checks its sha256. The release attaches `swarmbox`, `swarmbox.sha256` and `install.sh`.
- `swarmbox <command>` runs a command in the box and returns its exit status; `--plain` skips tmux.
- Creation settings in one host file, compared on every entry by a fingerprint; variables are passed by name at creation and never written to disk.
- Nested Podman, always on, with the host connection (`podman -c`) and a short-symlink fallback for long socket paths.
- A web terminal (ttyd and tmux) on `127.0.0.1`, supervised inside the box; optional remote access with Cloudflare Tunnel and Access (`swarmbox remote setup|status|off|token`),
  with the credentials and the connector on the host.
- Chrome DevTools MCP with Chromium in the image, written to the MCP configuration of the agents.
- `swarmbox update [--to TAG]` refreshes the script from the new image (never by an older one) and uses an exact local tag, so a later `reset` works offline and a rollback is one command.
- No telemetry; logs stay on your machine.
- XDG-aware paths on the host and in the box.
- `LICENSE` (Apache-2.0), `THIRD_PARTY_NOTICES.md`, `CONTRIBUTING.md`, `SECURITY.md`, `CODE_OF_CONDUCT.md`, a CI workflow and a signed multi-arch release workflow.

### Known limits

macOS with a real Podman machine, Podman older than 4.3, a host user other than UID 1000 and the real Cloudflare setup are not verified. A container shares the host kernel:
see [SECURITY.md](SECURITY.md) and [docs/microvm.md](docs/microvm.md).

## [2.0.0-beta.2] - 2026-11-11

Second prerelease of 2.0.0, tagged `2.0.0-beta.2` only. Install it with `sh install.sh --version 2.0.0-beta.2`, or move from a
beta.1 box with `swarmbox update --to 2.0.0-beta.2`. Changes since beta.1:

- Fixed: with `BROWSER_URL` set, the Chrome DevTools MCP now attaches to that browser. `swarmbox-mcp` read a variable the host never
  passes (`BROWSER_URL`) instead of `SWARMBOX_BROWSER_URL`, so the generated MCP file kept the headless Chromium of the box.
- The web terminal treats Option as Meta on a Mac, so Option+1..9 and Option+N change and open tmux windows (`macOptionIsMeta=false`
  in `web-terminal.conf` brings the special characters back).
- The `tmux` status bar stays visible in the browser, so every window is listed.
- macOS test and CI fixes (macos-15 runner, tests run one by one).

## [2.0.0-beta.1] - 2026-11-11

First public prerelease of 2.0.0, for testing before the final release. The image is tagged `2.0.0-beta.1` only (never `2.0` or
`latest`) and the GitHub release is marked as a prerelease. Install it with `sh install.sh --version 2.0.0-beta.1`;
`swarmbox update` follows the `2.0` series, which exists only once 2.0.0 is out, so until then move between betas with
`swarmbox update --to TAG`. The feature list is the one of 2.0.0 below. Changes while preparing it: the base image is
`node:24-trixie-slim` (Debian 13) with Podman 5.4; `criu` and its `python3-protobuf` are removed from the image; the Go
standard library findings that Debian 13 has not fixed yet are listed, with the reasons, in `.grype.yaml`.

[2.0.7]: https://github.com/feroult/swarmbox/releases/tag/v2.0.7
[2.0.6]: https://github.com/feroult/swarmbox/releases/tag/v2.0.6
[2.0.5]: https://github.com/feroult/swarmbox/releases/tag/v2.0.5
[2.0.4]: https://github.com/feroult/swarmbox/releases/tag/v2.0.4
[2.0.3]: https://github.com/feroult/swarmbox/releases/tag/v2.0.3
[2.0.2]: https://github.com/feroult/swarmbox/releases/tag/v2.0.2
[2.0.1]: https://github.com/feroult/swarmbox/releases/tag/v2.0.1
[2.0.0]: https://github.com/feroult/swarmbox/releases/tag/v2.0.0
