# Implementation status

Progress of the build, one row per slice. Status is done, partial or blocked.

| Slice | Title | Status | Commits | Tests | Notes |
|-------|-------|--------|---------|-------|-------|
| 0.preflight | Environment check and baseline | done | see git log | 11 test files run, all pass | Baseline below |
| 0.1-harness-container-spikes | Spike harness and the tmux/PID 1/container-lifecycle spikes (B3, B13, B9, B17, B18) | done | see git log | tests/test_spikes_common.py 7 tests OK; the five spikes run to completion (b17, b18, b9, b13, b3 each print RESULT CONFIRMED); the 11 older test files still pass | B9, B17, B18 closed; B3 and B13 spiked and left open for Phase 2 (reduced: bash stand-ins). Design corrected in 3.3 (wrapper trap, no-terminal form), 4.2 (supervisor stays alive), Part B results table. ttyd is the box's own 1.7.7 binary. Scratch image swarmbox-test-spikes-img:1 removed at the end. |
| 0.2-fs-socket-spikes | Socket path limit and re-recorded environment checks (B5, B12) | done | see git log | spike_b5_socket_len.py CONFIRMED; spike_b12_keepid.py, spike_b12_exec_env.py, spike_b12_npm_sizes.py CONFIRMED; spike_b12_symlink_arg0.sh CONFIRMED (dash, bash, zsh, busybox sh); test_spikes_common.py re-run | B5 closed: limit 107 characters, fallback above 100 through a symlink to the state folder (3.5 rewritten). B12 re-recorded with tags in 3.6, 6.2, 7.3, Part B table; the 4.2 GB image size could not be measured (reduced, still [unverified]). Reduced: stand-in service for B5 container half, no macOS; keep-id with host UID 1000 only. fish not tested for $0. No test objects left. Review fix: the fallback and exit 4 are mirrored in 3.5 host-state list, 3.7.2 (`up` row and step 6) and the 3.8 table. |
| 0.3-agent-install-spikes | Agent CLI install spikes (B1, B2, B10) | done | see git log | spike_b1_claude_update.py, spike_b2_opencode_flag.py, spike_b10_opencode_prefix.py each CONFIRMED (final runs); no test objects left | B1 closed: native installer for UPDATE=self (npm under --prefix cannot update without NPM_CONFIG_PREFIX). B2 closed: `--auto`, rejected before a subcommand, so no alias and new keys YOLO_FLAGS/YOLO_ALIAS=0. B10 closed: 745 MB saved (opencode-ai line: 204 MB). Reduced: one update only; `yolo` TUI with --auto not run (no terminal); docs lack the flag. Open for the owner: @opencode/cli vs opencode-ai. |
| 0.4-doc-reads | Documentation reads (B4, B11, B25, B14, B16) | done | see git log | spike_b4_ttyd_index.py, spike_b11_b25_checksums.py, spike_b16_restart_policy.py CONFIRMED (final runs); tests/test_design_partb.py 5 tests OK; test_spikes_common.py 7 tests OK; no test objects left | B4, B11, B25 closed. B14 documentation only, stays [unverified]. B16 partly: user unit exists, covers restart-policy=always only on 4.3.1 (unless-stopped not matched); reboot untried (no systemd). Finding: Google's checksum is for the unversioned URL only, pinned archive has other bytes, so D29 computes it. Reduced: no containers for B4/B11/B25 (host ttyd, network reads). |
| 0.5-phase-closeout | Phase 0 close-out: Part B reconciliation and consistency | done | see git log | tests/test_docs_consistency.py 11 tests OK (written first, 4 failed for the right reasons); all 14 other test files pass (158 v0.1.0 tests plus test_design_partb 5, test_spikes_common 7) | Design Part B has a Phase 0 outcome table (closed, reduced, open with owner); B6, B7, B8, B15 listed as not doable here; plan Phase 0 paragraph and Appendix A.3 notes updated; "D1 to D37" corrected to D39; tests/spikes/README.md added. Open for the owner: B14 (real dashboard), B16 (reboot with systemd), B6, B7, B8, B15 (hardware). No test objects left. |

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
