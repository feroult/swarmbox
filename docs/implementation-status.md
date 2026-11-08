# Implementation status

Progress of the build, one row per slice. Status is done, partial or blocked.

| Slice | Title | Status | Commits | Tests | Notes |
|-------|-------|--------|---------|-------|-------|
| 0.preflight | Environment check and baseline | done | see git log | 11 test files run, all pass | Baseline below |

## Environment limits

Checked 2026-11-08 on the live box.

- Branch opensource, git status clean at start.
- Podman 4.3.1 (buildah 1.28.2), nested rootless, Debian 12 bookworm. podman info works; podman run --rm debian:bookworm-slim true succeeds.
- Disk: / has about 645G free of 1007G.
- Cached images: python:3.11-slim-bookworm, node:20-slim, node:22-slim, node:24-slim, debian:bookworm-slim, debian:trixie-slim.
- Python 3.11.2 (/opt/flow/bin/python3), bash, dash, tmux, jq present.
- Installed in preflight: zsh, fish, busybox, shellcheck (required apt-get update first, with APT::Sandbox::User "root").
- Live box is up: tmux ls shows sessions main and main-1; pgrep -x ttyd returns a PID (ttyd on 7681, never to be touched).
- A third Podman nesting level (needs /dev/net/tun, unmasked /proc) is not possible here: tests needing it use fakes or a test-only switch and are tagged reduced.
- apt in nested builds needs APT::Sandbox::User "root"; only in scratch Dockerfile copies.
- A browser is available: test_web_style.py and test_clipboard_bridge.py run and pass.

## Baseline (v0.1.0 tests, run as python3 tests/test_x.py)

| File | Result |
|------|--------|
| test_clipboard_bridge.py | 11 tests OK (42s) |
| test_cloudflare_setup.py | 44 tests OK |
| test_ssh_key.py | 5 tests OK |
| test_starship.py | 19 tests OK |
| test_start_attach.py | 6 tests OK (10s) |
| test_start_init.py | 6 tests OK |
| test_start_timezone.py | 7 tests OK |
| test_start_web_connector.py | 22 tests OK |
| test_tmux_browser_keys.py | 18 tests OK (60s) |
| test_web_style.py | 5 tests OK (16s) |
| test_web_terminal.py | 15 tests OK |

Total 158 tests, 0 failures.
