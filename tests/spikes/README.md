# Phase 0 spikes

One-off experiments that answered the questions of Part B of `docs/design.md` before the code depended on them. They are
**not run in CI**: each one starts throwaway Podman containers named `swarmbox-test-...` (nested rootless Podman 4.3.1),
prints one `RESULT` line with an evidence tag `[verified: how; date; Podman and OS; image]` and exits 1 if a claim of the
design is contradicted. Every object they create is removed by its exact name at the end (`spikes_common.py` tracks them).
The results and the corrections they caused are in design Part B ("Results of the Phase 0 spikes") and
`docs/decision-log.md`.

Run any of them from the repository root. Needs: Podman, Python 3.11, the cached base images (`node:24-slim`,
`debian:bookworm-slim`, `python:3.11-slim-bookworm`). "Network" means the script downloads from npm or the vendor.
Never run them against a box that holds live sessions: they use only their own containers, temporary directories and
random high ports on 127.0.0.1.

| Script | Fact | Run | Needs |
|---|---|---|---|
| `spike_b1_claude_update.py` | B1 Claude Code updater, native installer vs npm `--prefix` | `python3 tests/spikes/spike_b1_claude_update.py` | network |
| `spike_b2_opencode_flag.py` | B2 OpenCode auto-approve flag (`--auto`) | `python3 tests/spikes/spike_b2_opencode_flag.py` | network |
| `spike_b3_serve_pid1.py` | B3 `serve` as PID 1, ttyd restart, signals (bash stand-ins) | `python3 tests/spikes/spike_b3_serve_pid1.py` | spike image, host ttyd |
| `spike_b4_ttyd_index.py` | B4 ttyd serves one file with `--index` | `python3 tests/spikes/spike_b4_ttyd_index.py` | host ttyd (no container) |
| `spike_b5_socket_len.py` | B5 AF_UNIX path limit (107) and the fallback | `python3 tests/spikes/spike_b5_socket_len.py` | python image |
| `spike_b9_tmux_env.py` | B9 tmux environment of new windows | `python3 tests/spikes/spike_b9_tmux_env.py` | spike image |
| `spike_b10_opencode_prefix.py` | B10 OpenCode size saving under `--prefix` | `python3 tests/spikes/spike_b10_opencode_prefix.py` | network |
| `spike_b11_b25_checksums.py` | B11 gcloud and B25 Go checksum sources | `python3 tests/spikes/spike_b11_b25_checksums.py` | network (no container) |
| `spike_b12_keepid.py` | B12 `--userns=keep-id:uid=1000,gid=1000` | `python3 tests/spikes/spike_b12_keepid.py` | node image |
| `spike_b12_exec_env.py` | B12 `podman exec -e NAME` | `python3 tests/spikes/spike_b12_exec_env.py` | node image |
| `spike_b12_npm_sizes.py` | B12 install sizes and npm cache location | `python3 tests/spikes/spike_b12_npm_sizes.py` | network |
| `spike_b12_symlink_arg0.sh` | B12 `$0` through a symlink, per shell | `bash tests/spikes/spike_b12_symlink_arg0.sh` | dash, bash, zsh, busybox |
| `spike_b13_run_command.py` | B13 the `swarmbox <command>` mechanism (3.3) | `python3 tests/spikes/spike_b13_run_command.py` | spike image |
| `spike_b16_restart_policy.py` | B16 `--restart` and `podman-restart.service` | `python3 tests/spikes/spike_b16_restart_policy.py` | debian image |
| `spike_b17_tmpfs.py` | B17 tmpfs empty after stop and start | `python3 tests/spikes/spike_b17_tmpfs.py` | node image |
| `spike_b18_port_in_use.py` | B18 container left behind by a failed `run -p` | `python3 tests/spikes/spike_b18_port_in_use.py` | node image |

`spikes_common.py` is the shared harness (name and port guards, tracked cleanup, the shared scratch image
`swarmbox-test-spikes-img:1` that is built once and removed at the end unless `SWARMBOX_SPIKE_KEEP_IMAGE` is set,
`evidence()` for the tag). Its own test is `tests/test_spikes_common.py`.

## Promotion to real tests

A spike becomes a product test in the phase that closes its fact (plan Appendix A.3), rewritten against the real code
instead of a stand-in:

| Spike | Becomes | Phase |
|---|---|---|
| B3, B13 | tests of the real `serve` and `swarmbox-attach` (the two corrections of 3.3 and 4.2 must be in them) | 2 |
| B17 | the Phase 2 smoke test (readiness marker on the tmpfs) | 2 |
| B9 | a check of the real tmux configuration | 2 |
| B5, B18 | `create-flags` and `up` tests (socket fallback, failed-run cleanup by ID) | 3 |
| B1, B2, B10, B11, B25 | the installer and `validate` tests of the tools (4a, 4b); gcloud and Go checksums by the maintainer script (D29) | 4a, 4b |
| B12 | the smoke test (keep-id, exec -e), the shim tests (`$0`) | 2, 3, 4a |
| B4, B14, B16 | none: documentation and one-off checks | none |
