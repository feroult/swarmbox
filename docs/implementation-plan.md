# SwarmBox 2.0 implementation plan

Status: **proposal, to be validated with the project owner.** This plan turns [design.md](design.md) into work. The design is the source of truth for
*what* is built; this file says *in which order*, *how each piece is proven*, and *when it is done*. Section numbers (3.6, 4.1, D33, B13...) refer to the design.

"Today" is the git tag `v0.1.0`. Nothing in this plan changes `v0.1.0` or `main`: the work happens on the branch `opensource`.

---

## 1. How the work is organized

### 1.1 Principles

1. **Walking skeleton first.** The first slice is the thinnest box that works end to end (image, `serve`, `attach`), with no tools, no Cloudflare and no variables. Everything else is added in slices that each leave the system working.
2. **Prove the risky assumptions before building on them.** The design has 24 facts marked `[unverified]` (Part B, section 14). The few that can change the design are checked first, in throwaway containers (Phase 0).
3. **Tests first, with fakes.** Each slice starts with its tests (design 13): unit tests with a fake `podman`, a fake Cloudflare API and fake installers; real containers only in a smoke test with names that are never `swarmbox`.
4. **The design stays true.** If building something shows the design is wrong, the same commit corrects `design.md`, and a closed Part B fact gets its evidence tag (`[verified: how; date; Podman and OS; image]`).
5. **Protocol details are hypotheses until proven.** The readiness marker, exit codes and the `swarmbox <command>` mechanism (4.1, 4.2, 3.3) were specified before any code existed. Phases 0 and 2 confirm or change them.
6. **`v0.1.0` keeps working until parity** (D8). It is retired in Phase 6, not before.

### 1.2 Safety rule for tests and experiments

Tests and experiments run only in throwaway containers (names such as `swarmbox-test-<id>`, workspaces in temporary folders). They never run `tmux`, `podman stop/rm`, or any command against the box a person is using, and they never `kill-server`. The development machine hosts live sessions; an earlier experiment that ran `tmux kill-server` outside a container ended them.

### 1.3 Definition of done for a slice

- Its tests exist and pass in CI (design 13.4) and, where relevant, in the image smoke test.
- The design is updated for anything that changed, and the evidence tags of the facts it closed are updated.
- No behavior of the slice depends on an `[unverified]` item that is not closed or explicitly accepted.
- Commits are small and single-purpose, in the repository's style (`feat:`, `fix:`, `refactor:`, `docs:`, `test:`).

### 1.4 Overview

| Phase | Goal | Depends on | Size |
|---|---|---|---|
| 0 | Spikes: close the unverified facts that can change the design | none | S to M |
| 1 | Foundations: license, CI, paths file, test helpers | none (parallel with 0) | S |
| 2 | The box: slim image, entrypoint, `serve`, `attach`, web terminal, migration | 0, 1 | L |
| 3 | The host half: helper, generated function, `init`, configuration, variables | 2 | L |
| 4 | Tools and shims: `swarmbox-tool`, manifests, MCP registry | 2 (parallel with 3) | L |
| 5 | Remote access: `swarmbox remote` over the Cloudflare script | 3 | M |
| 6 | Parity, retire the scripts, documentation, move the owner's own box | 3, 4, 5 | M |
| 7 | Release: registry, signing, name, history audit, `v2.0.0` | 6 | M |

Sizes are relative (S, M, L), not durations.

Milestones: **M1** a box runs and is shared (end of Phase 2); **M2** usable every day, one install line with Claude Code on demand (Phases 3 and 4); **M3** parity, old scripts removed (Phase 6); **M4** public release (Phase 7).

```
Phase 0 ──┐
          ├─► Phase 2 ─┬─► Phase 3 ─┬─► Phase 5 ─┐
Phase 1 ──┘            │            │            ├─► Phase 6 ─► Phase 7
                       └─► Phase 4 ─┴────────────┘
```

---

## 2. Phase 0: spikes

**Goal:** answer the questions whose answer could change the design, cheaply, before the code depends on them. **Where:** throwaway containers inside the current SwarmBox (a nested rootless Podman 4.3.1 with about 64,000 user IDs). **Output:** one note per spike and, where it is reusable, a script under `tests/spikes/` (not run in CI) that later becomes a real test. Results are recorded in Part B with the tag `[verified: nested in a SwarmBox, Podman 4.3.1, <date>, <image>]`.

| Spike | Question | Method | If it fails |
|---|---|---|---|
| B3 | Can `serve` be the main process while supervising ttyd, and does `swarmbox-web restart` leave the box running? | Test image with tmux and ttyd; start `serve`; restart ttyd; check the container stays up and the session survives | 4.1 and 5.1: decide who is PID 1 and how ttyd restarts |
| B13 | Does `swarmbox <command>` through a new tmux window keep quoting and propagate the exit code? | A tmux inside a test container; run commands with spaces, quotes, a failing command | 3.3: replace the mechanism (for example `exec` with a pty and no window) |
| B9 | How does tmux pass its environment to a new window? | The same experiment as the void one, now inside a test container, with its own tmux | 7: the claim that browser and host tabs see the same variables |
| B4 | Does ttyd serve only one file as the page? | Run ttyd with an index that references a second file | 5.1: how a larger page is delivered |
| B17 | Is `box:/tmp/swarmbox` (tmpfs) empty after `podman stop` and `podman start`, and writable by the `agent` user with `keep-id`? | Throwaway container with `--tmpfs`, stop and start | 4.2: the readiness marker design |
| B18 | When `podman run -d` fails because a published port is in use, is a container left behind, and with which exit code? | Bind the port first, then `podman run -d -p` | 3.8: the create-failure path (exit 7 and cleanup) |
| B5 | What is the unix socket path limit and where does the fallback start? | Create sockets in increasingly deep folders | 3.5 and 3.7: the socket location |
| B1 | Which Claude Code install method keeps its updater working? | Install with npm under `--prefix` and with the native installer; run the updater | 6.7: how `UPDATE=self` is installed |
| B2 | What is OpenCode's auto-approve flag? | Read `opencode --help` for the installed version and its documentation | 6.6: whether OpenCode gets an alias |
| B10 | Does the OpenCode size saving hold under `--prefix`? | Install with `--prefix`; remove the unused platform builds; check it still runs; measure | 6.4: the OpenCode installer |
| B11 | Where are gcloud's download URL and checksums? | Read Google's documentation; fetch both architectures | 6.4 and D29: how the checksum is recorded |

**Cannot be checked in this environment** (the owner or a CI runner must do them, see the validation list): B6 (macOS), B7 (a host UID other than 1000), B8 (older Podman versions), B14 (the Cloudflare dashboard), B15 (python3 on a clean macOS), B16 (restart after a host reboot). Each is attached to the phase that needs it (Phase 6 and 7).

**Exit criteria:** every spike above has a recorded result; every result that contradicts the design has a design change committed; Part B shows which facts remain open and who closes them.

---

## 3. Phase 1: foundations

**Goal:** the project can be developed safely and continuously.

- `LICENSE` (Apache-2.0, D25) and the start of `THIRD_PARTY_NOTICES.md` (ttyd, starship, tmux, ...).
- `.github/workflows/ci.yml` running the tests that exist today (design 13.4). Browser tests and anything slow go to the scheduled run.
- `container/scripts/dirs.sh`: every path, XDG-aware (honors `XDG_CONFIG_HOME`, `XDG_DATA_HOME`, `XDG_STATE_HOME`), with its test.
- `tests/helpers.py` extended with a fake `podman` that records its calls and a fake host helper (design 13.1).
- A short `CONTRIBUTING.md` with how to run the tests and how to build the image locally.

**Exit criteria:** CI is green on the current tests; `dirs.sh` is covered; the fakes exist and are used by at least one new test.

---

## 4. Phase 2: the box (M1)

**Goal:** a throwaway box starts from the new image, reaches readiness, and two entries share one tmux session. Design: 4, 5.1, 10, 12.4.

Scope
- **Image** (10.1, 10.2): slim `Dockerfile` (`node:24-slim`, fixed user `agent` with UID 1000, no `USER_UID` or `HOST_OS`, no agents, no gcloud, clasp, Go or Poetry), the nested-Podman settings kept from today (10.5), `CMD ["serve"]`.
- **Entrypoint** `swarmbox-entrypoint` with the subcommands `serve`, `attach`, `init`, `pubkey`, `host-helper` and "any other command".
- **`serve`**: the ordered steps of 4.1, readiness and health (4.2), the nested Podman service, the SSH key, the layout migration (12.4).
- **`swarmbox-attach`**: replaces `lib/attach-session.sh`; joins the session `main` through a grouped session, no status bar on host tabs.
- **Web terminal**: `build-index.sh` at image build, `swarmbox-web` at start with the three-value substitution (5.1).
- The shell fragment `container/config/bashrc.sh` (banner, aliases, Starship, `PATH`) replacing the `bashrc` echo lines.

Tests first
- Migration test on a fixture workspace with a `v0.1.0` `.swarmbox/` (13.3 layer 3).
- `serve` step failures (13.1) with a fake environment.
- The image smoke test skeleton (13.3 layer 2): readiness, `box:/tmp/swarmbox` emptied on restart, the page built, `swarmbox-tool validate` placeholder.

Closes: B3, B4, B9, B17 (confirmed by the product code, not only by the spikes).

**Exit criteria:** the smoke test passes in CI; in a throwaway box two `attach` calls land in the same session as two windows; the web terminal serves the built page with the user's three settings substituted; the migration test passes. **M1.**

---

## 5. Phase 3: the host half

**Goal:** one install line, then `swarmbox` creates or joins the box. Design: 3.1 to 3.8, 7, 8.

Scope
- **Host helper in POSIX `sh`** (D16): `version`, `config get|set|list`, `create-flags`, the fingerprint and labels, `up`, `reset`, `stop`, `url`, `update`, and the `host-helper` archive the image serves.
- **`swarmbox-init`**: prints the seed values and the function for bash, zsh and fish; markers; idempotent (D20); `--with`, `--workspace`, `--image`, `--shell`.
- **The function and its bootstrap** (3.6, D33): extracts the helper, the "never undo an update" rule.
- **Install, upgrade and failure behavior** (3.8): prerequisites, exit codes, messages, version skew, rollback.
- **Variables** (7, D12, D28): `swarmbox env add|rm|list`, `ENV_KEYS`, names validation, the hash label.
- **Configuration** (8): `swarmbox config`, the per-box config folder (D31).

Tests first
- `create-flags` for every key of 8.2 (quoting, values with spaces, lists, tool ports) (13.1).
- Function tests in bash, zsh and fish, and macOS bash 3.2 where a runner exists, with a fake helper and a fake `podman` (13.3 layer 4), including the bootstrap and the update-then-next-call cases.

Closes: B13 and B18 (confirmed by the product code), B19 (`sort -V`), B20 (the exact tag on update), B21 (default shell), B22 (tunnel token mode), B23 (the helper under different `sh` implementations).

**Exit criteria:** on a clean Linux machine, the documented install line followed by `swarmbox` creates the box; a second terminal joins it; `stop`, `reset` and `update` behave as specified; the function and helper tests pass in CI.

---

## 6. Phase 4: tools and shims (M2 with Phase 3)

**Goal:** `claude` installs on first call and survives a reset. Design: 6, 4.4, 6.11, 6.12.

Scope
- **`swarmbox-tool`** (`list`, `install`, `update`, `use`, `remove`, `run`, `link`, `validate`, `doctor`, `new`) and the dispatcher **`swarmbox-shim`**; the generated index and `tool-ports`.
- **Manifests and installers** in `container/tools/`: claude (`UPDATE=self`), opencode (with `prepare.sh` and the local-LLM hook), gemini, clasp (with its port), gcloud (checksum in the manifest), go, poetry. Order: claude and opencode first (they exercise both update modes), then the rest.
- **Environment fingerprint** per install, `doctor` and `doctor --fix` (6.11).
- **MCP registry** (4.4): generated `mcp-servers.json`, the pinned chrome-devtools server (D23), the OpenCode mirror.
- **Image-level link** at build (`link --system`) and the entry-time link (`link --user`).

Tests first
- `swarmbox-tool` and each installer with a fake installer (13.1); `validate` rules (6.9).
- Scheduled real-installer tests: "no side effects" and "survives a reset" per tool (6.9, 13.4).

Closes: B1 (in the product), B2, B10, B11 and B24 (the pinned `chrome-devtools-mcp`).

**Exit criteria:** in a throwaway box, the first `claude` call installs and runs it; `reset` keeps it; `validate` passes for every manifest; the "no side effects" test passes for each tool. **M2** (together with Phase 3): installable and usable every day.

---

## 7. Phase 5: remote access

**Goal:** `swarmbox remote` over the existing Cloudflare script. Design: 5.2, 3.7, D14, D28.

Scope: `remote setup|status|off|token` (and `--dry-run`) as thin wrappers over `cloudflare-setup.py`; the connector brought up on entry when configured, pinned image; the login length preserved on rerun; the tunnel token read from the host environment or from the host config with mode 600; `swarmbox url`.

Tests first: the existing `test_cloudflare_setup.py` (kept), plus the rerun-keeps-`--session` case and the wrapper arguments; the connector logic against the fake `podman`.

Closes: B14 (owner), B22.

**Exit criteria:** the tests pass; the owner runs one end-to-end setup against their own Cloudflare account and reaches the box from outside.

---

## 8. Phase 6: parity, retire the scripts, documentation (M3)

**Goal:** nothing from `v0.1.0` is lost, and the old entry points are gone. Design: 12, 13.2.

- **Parity test:** one test per row of the feature catalog (8.4) against the function (D8).
- **Delete** `start.sh`, `build.sh` and `lib/`.
- **Documentation:** rewrite `README.md` around the new install and first use; update `docs/web-terminal.md`, `docs/cloudflare.md`, `docs/nested-podman.md`; keep `design.md` and this plan in sync.
- **Dogfooding:** the owner first runs a second box (`SWARMBOX_NAME=dev`, another workspace) from M2 on; after parity the main workspace is migrated with the layout migration (12.4), after a backup.
- Owner's real-hardware checks: B6 (macOS), B7 (UID other than 1000), B8 (older Podman), B15, B16.

**Exit criteria:** the parity suite is green; the scripts are deleted; the owner's main box runs on 2.0; the checks that need real hardware have a result or an explicit, documented limit. **M3.**

---

## 9. Phase 7: release (M4)

**Goal:** a public, signed `v2.0.0`. Design: 10.4, 13.4, D25, D26.

- `release.yml`: multi-arch build (amd64 and arm64), tests, vulnerability scan, signing, SBOM, publish to `ghcr.io/<org>/swarmbox` (D32).
- Settle the registry owner and **check that the name SwarmBox is available** (D25).
- **Audit the git history** for secrets and personal data (the repository has about 200 commits); decide whether to publish it whole or start from a clean history.
- `SECURITY.md`, `CODE_OF_CONDUCT.md`, `CHANGELOG.md`, `THIRD_PARTY_NOTICES.md` complete; the README is the 15-second pitch.
- Tag `v2.0.0`.

**Exit criteria:** a user on a clean machine follows only the README and gets a working box; the image is signed and its digest published. **M4.**

---

## 10. Risks and how the plan handles them

| Risk | Handling |
|---|---|
| The design specifies mechanisms that never ran (readiness marker, exit codes, `swarmbox <command>` via tmux) | Phase 0 spikes first; Phase 2 and 3 treat them as hypotheses and correct the design when they fail |
| The experiments run in a nested Podman with a small UID range, which may not match a normal host | Results are tagged with how they were observed; B7, B8, B6 are re-checked on real hardware (Phases 6 and 7) |
| macOS is in scope (D6) but cannot be tested here | The platform adapter is written from the code and kept small; the owner tests on a Mac in Phase 6; failures become documented limits |
| The document is long, and code and design may drift apart | Rule 1.1.4: a change that contradicts the design updates it in the same commit; parity is a test, not a promise |
| A change in the live box breaks work in progress | The safety rule (1.2); the owner's box moves last, after a backup, and a second box is used first |
| The Cloudflare end-to-end needs the owner's account | Fakes cover the logic; one end-to-end run by the owner closes Phase 5 |
| Scope creep from detailed specification | Anything in the design not needed for parity or for a decision in D1 to D33 can be deferred to 2.1 and listed in the changelog |

---

## 11. Validation checklist (for the project owner)

1. **Phase order.** This plan builds the box (Phase 2) before the tools (Phase 4) and the host half (Phase 3), because the tools run inside the box. The design's roadmap (section 15) lists the tools first. Should the roadmap be changed to match this plan?
2. **Spikes.** Run Phase 0 now in nested throwaway containers here, with the limits above? And who runs the ones that need real hardware (B6, B7, B8, B15, B16), and when?
3. **Dogfooding.** Use a second box (`SWARMBOX_NAME=dev`) from M2 and move the main workspace only after parity (M3)?
4. **CI provider.** GitHub Actions is assumed (the remote host alias points at GitHub). Is that right, and is a macOS runner available for the function tests?
5. **Registry owner.** `ghcr.io/<org>`: a personal account or an organization? It is needed in Phase 7; examples keep the placeholder until then.
6. **Scope of 2.0.0.** All of the catalog, including `remote` (Cloudflare), ships in 2.0.0, as D14 and the catalog say. Should anything move to 2.1 to reach M2 and M4 sooner?
7. **Review cadence.** How do you want to review: at each milestone (M1 to M4), at the end of every phase, or at every pull request?
8. **Who builds what.** The work is done by the agent with parallel sub-agents where phases allow it (3 and 4 after 2; 5 after 3), under the rules in section 1. Is that the model you want, and which parts do you want to write or review by hand?
