# SwarmBox 2.0 implementation plan

Status: **proposal, to be validated with the project owner.** This plan turns [design.md](design.md) into work. The design is the source of truth for
*what* is built; this file says *in which order*, *how each piece is proven*, and *when it is done*. Section numbers (3.6, 4.1, D33, B13...) refer to the design.
The design's roadmap (its section 15) is a short form of the phase list below.

"Today" is the git tag `v0.1.0`. Nothing in this plan changes `v0.1.0` or `main`: the work happens on the branch `opensource`.

---

## 1. How the work is organized

### 1.1 Principles

1. **Walking skeleton first.** The first slice is the thinnest box that works end to end (image, `serve`, `attach`), with no tools, no Cloudflare and no variables. Everything else is added in slices that each leave the system working.
2. **Prove the risky assumptions before building on them.** The design has 36 facts marked `[unverified]` (Part B, section 14). The few that can change the design are checked first, in throwaway containers (Phase 0).
3. **Tests first, with fakes.** Each slice starts with its tests (design 13): unit tests with a fake `podman`, a fake Cloudflare API and fake installers; real containers only in a smoke test with names that are never `swarmbox`.
4. **The design stays true.** If building something shows the design is wrong, the same commit corrects `design.md`, and a closed Part B fact gets its evidence tag (`[verified: how; date; Podman and OS; image]`).
5. **Protocol details are hypotheses until proven.** The readiness marker, exit codes and the `swarmbox <command>` mechanism (4.1, 4.2, 3.3) were specified before any code existed. Phases 0 and 2 confirm or change them.
6. **`v0.1.0` keeps working until parity** (D8). It is retired in Phase 6, not before.
7. **A fact is closed once.** Every Part B fact is closed by exactly one phase (Appendix A.3). A spike or a later test that only feeds or rechecks it says "feeds" or "rechecks", and does not close it.

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
| 0 | Spikes and documentation reads: close the unverified facts that can change the design | none | S to M |
| 1 | Foundations: license, CI, history audit, paths file, test helpers | none (parallel with 0) | S |
| 2 | The box: slim image, entrypoint, `serve`, `attach`, `swarmbox <command>`, web terminal, migration | 0, 1 | L |
| 4a | Minimal tool slice: manifest parsing, `link --system`, `swarmbox-shim`, the claude manifest, an empty `tool-ports` | 2 | S to M |
| 3 | The host half: helper, generated function, `init`, configuration, variables, local registry | 2, 4a | L |
| 4b | The other tools, the MCP registry, `prepare.sh`, the environment fingerprint, `doctor` | 4a (runs in parallel with 3 and after it) | M to L |
| 5 | Remote access: `swarmbox remote` over the Cloudflare script | 3 | M |
| 6 | Parity, retire the scripts, documentation, move the owner's own box | 3, 4b, 5 | M |
| 7 | Release: registry, signing, name, licensing, security review, `v2.0.0` | 6 | M |

Sizes are relative (S, M, L), not durations.

Milestones: **M1** a box runs and is shared (end of Phase 2); **M2** usable every day, one install line with Claude Code on demand (Phases 3 and 4a); **M3** parity, old scripts removed (Phase 6); **M4** public release (Phase 7). The GitHub repository stays private until M4 (D37).

```
Phase 0 ──┐
          ├─► Phase 2 ─► Phase 4a ─┬─► Phase 3 ─┬─► Phase 5 ─┐
Phase 1 ──┘                        │            │            ├─► Phase 6 ─► Phase 7
                                   └─► Phase 4b ┴────────────┘
```

Phase 4b starts as soon as 4a is done, runs in parallel with Phase 3 and may continue after it; Phase 6 needs 3, 4b and 5. Phase 2 ships stubs where a later phase fills them in: an empty `tool-ports` file and the `swarmbox-tool` entry point (so the `tool` subcommand of the entrypoint already exists and the helper archive is complete).

---

## 2. Phase 0: spikes and documentation reads

**Goal:** answer the questions whose answer could change the design, cheaply, before the code depends on them. **Where:** throwaway containers inside the current SwarmBox (a nested rootless Podman 4.3.1 with about 64,000 user IDs). **Output:** one note per spike and, where it is reusable, a script under `tests/spikes/` (not run in CI) that later becomes a real test. Results are recorded in Part B with the tag `[verified: nested in a SwarmBox, Podman 4.3.1, <date>, <image>]`. The documentation reads (B12, B14, B16, B25) need no owner.

| Spike | Question | Method | Closed in | If it fails |
|---|---|---|---|---|
| B3 | Can `serve` be the main process while supervising ttyd; does `swarmbox-web restart` leave the box running; does a PID 1 with SIGTERM and SIGINT handlers stop in time? | Test image with tmux and ttyd; start `serve`; restart ttyd; send SIGTERM and SIGINT; time `podman stop` | feeds Phase 2 | 4.1 and 5.1: decide who is PID 1 and how ttyd restarts |
| B13 | Does the `swarmbox <command>` mechanism (detached window, `wait-for` channel, status file, interactive shell) return on exit with the exit code, keep quoting, apply aliases and `PATH`, and behave without a terminal? | A tmux inside a test container; commands with spaces, quotes, a failing command, an alias; output piped through `od -c` | feeds Phase 2 | 3.3: replace the mechanism (for example a pty without a window) |
| B9 | How does tmux pass its environment to a new window? | In a test container start a tmux server with `X=1`; attach a client whose environment has `X=2`; open a window from that client and one from the server's own command; print `$X` in both and compare | Phase 0 | 7: the claim that browser and host tabs see the same variables |
| B4 | Does ttyd serve only one file as the page? | Run ttyd with an index that references a second file; read its documentation | Phase 0 | 5.1: how a larger page is delivered |
| B17 | Is `box:/tmp/swarmbox` (tmpfs) empty after `podman stop` and `podman start`, and writable by the `agent` user with `keep-id`? | Throwaway container with `--tmpfs`, stop and start | Phase 0 | 4.2: the readiness marker design |
| B18 | When `podman run -d` fails because a published port is in use, is a container left behind, and with which exit code and message? | Bind the port first, then `podman run -d -p`; also with `--cidfile` (what the file holds after a failure) | Phase 0 | 3.8: the create-failure path (exit 7 and cleanup by ID) |
| B5 | What is the unix socket path limit and where does the fallback start? | Create sockets in increasingly deep folders | feeds Phase 3 | 3.5 and 3.7: the socket location |
| B1 | Which Claude Code install method keeps its updater working? | Install with npm under `--prefix` and with the native installer; run the updater; compare file listings | Phase 0 | 6.7: how `UPDATE=self` is installed |
| B2 | What is OpenCode's auto-approve flag? | Read `opencode --help` for the installed version and its documentation | Phase 0 | 6.6: whether OpenCode gets an alias |
| B10 | Does the OpenCode size saving hold under `--prefix`? | Install with `--prefix`; remove the unused platform builds; check it still runs; measure | Phase 0 | 6.4: the OpenCode installer |
| B11 | Where are gcloud's download URL and checksums? | Read Google's documentation; fetch both architectures | Phase 0 | 6.4 and D29: how the checksum is recorded |
| B25 | Where does Go publish a checksum for its tarball? | Read go.dev's download page; fetch both architectures | Phase 0 | 6.12 and D29: how the Go checksum is recorded |
| B12 | Re-record the checks whose setup was not recorded (`keep-id` acceptance, the install sizes and where the npm cache went, the 4.2 GB image size, the symlink `$0` behavior, the `podman exec -e` check) | Repeat each in a throwaway container; note date, Podman version, OS, image | Phase 0 | 3.6, 6.2, 6.11, 7.3, 10.2: restate the claim |
| B14 | Where are Cloudflare Access sessions revoked in the dashboard? | Read Cloudflare's documentation and name the screen | Phase 0 | 11: say it is not documented |
| B16 | Does restarting a `--restart` container after a host reboot work for rootless Podman, and under what service? | Read Podman's documentation; read `podman-restart.service` | Phase 0 | 4.2: how the connector is described |

**Cannot be checked in this environment** (hardware or a registry is needed): B6 (macOS), B7 (a host UID other than 1000), B8 (older Podman versions) and B15 (`python3` on a clean macOS), each **closed in Phase 6** by the owner or a CI matrix; the macOS parts of B19, B21, B22, B23 and B34, **rechecked in Phase 6** after their Linux parts are closed in Phase 3; and the real-registry run of B20, **rechecked in Phase 7** after Phase 3 closes it against a local registry.

**Results so far:** slice 0.1 ran B3, B13, B9, B17 and B18 (`tests/spikes/`); the results are in design Part B ("Results of the Phase 0 spikes") and `docs/decision-log.md`. B9, B17 and B18 are closed; B3 and B13 are spiked and stay open until the Phase 2 product tests, which must include the two corrections the spikes found. Slice 0.4 (documentation reads) closed B4, B11 and B25, checked B14 (documentation only, still `[unverified]`) and partly checked B16: gcloud's published checksum belongs to the unversioned URL only (so the maintainer script of D29 computes the pinned file's checksum), and on Podman 4.3.1 `podman-restart.service` restarts `--restart=always` containers only, not `unless-stopped`.

**Phase 0 outcome (slice 0.5):** every spike above has a tagged result in Part B. Closed: B1, B2, B4, B5, B9, B10, B11, B17, B18, B25. Reduced (stand-in or partial), closed by the phase that owns the real code: B3, B13 (Phase 2), B12 (image size, with B27 in Phase 2). Open with an owner: B14 (documentation only, owner with a Cloudflare dashboard) and B16 (the reboot, a host with systemd). Not doable here: B6, B7, B8 and B15, closed in Phase 6. The table "Phase 0 outcome" in design Part B has the detail and `tests/spikes/README.md` lists the scripts and how each becomes a test. `tests/test_docs_consistency.py` guards the cross-references.

**Exit criteria:** every spike above has a recorded result; every result that contradicts the design has a design change committed; Part B shows which facts remain open and who closes them.

---

## 3. Phase 1: foundations

**Goal:** the project can be developed safely and continuously.

- `LICENSE` (Apache-2.0, D25) and the start of `THIRD_PARTY_NOTICES.md` (ttyd, starship, tmux, ...).
- **History audit (D37):** scan the whole git history for secrets and personal data (a scanner such as gitleaks, plus a read of the author and host names); write down the findings. The GitHub repository stays private until M4; Phase 7 acts on the findings.
- `.github/workflows/ci.yml` running the tests that exist today (design 13.4). Browser tests and anything slow go to the scheduled run. **Runner details:** use a runner image whose Podman is at least 4.3 (the Ubuntu 22.04 image ships Podman 3.4, which is too old), or install Podman in the job; on macOS run the function tests with a fake Podman, which needs no Podman there. Closes B30 (does the macOS runner exist, and what does it provide). *Slice 1.6 wrote the file and the probe; B30 itself stays `[unverified]` until the first real run.*
- `container/scripts/dirs.sh`: every path, XDG-aware (honors `XDG_CONFIG_HOME`, `XDG_DATA_HOME`, `XDG_STATE_HOME`), with its test.
- `tests/helpers.py` today holds only `ROOT` (4 lines); each test writes its stubs inline. Phase 1 **creates** the shared fakes there: a fake `podman` that records its calls (slice 1.3, `FakePodman`, done) and a fake host helper (slice 1.4, `FakeHostHelper`, done; its API may change when the real function tests arrive in Phase 3).
- A short `CONTRIBUTING.md` with how to run the tests and how to build the image locally.

**Exit criteria:** CI is green on the current tests, on a Podman of at least 4.3; `dirs.sh` is covered; the fakes exist and are used by at least one new test; the history audit report exists; B30 has a result.

---

## 4. Phase 2: the box (M1)

**Goal:** a throwaway box starts from the new image, reaches readiness, and two entries share one tmux session. Design: 4, 5.1, 10, 12.4, 3.3.

Scope
- **Image** (10.1, 10.2): slim `Dockerfile` (`node:24-slim`, fixed user `agent` with UID 1000, no `USER_UID` or `HOST_OS`, no agents, no gcloud, clasp, Go or Poetry), the nested-Podman settings kept from today (10.5), `/opt/npm-cache` owned by `agent`, the pinned `chrome-devtools-mcp` installed at build (D23, closes B24), `CMD ["serve"]`. Slice 2.1 built it: the root `Dockerfile` is the 2.0 image, today's image is `Dockerfile.v0.1.0` (used by `build.sh` until Phase 6), and `dev/dev-build.sh` builds it in the development box (decision [2.1]).
- **Entrypoint** `swarmbox-entrypoint` with the subcommands `serve`, `attach`, `init`, `pubkey`, `tool`, `host-helper` and "any other command". `tool` forwards to the stub `swarmbox-tool` until Phase 4a; the empty `tool-ports` is shipped in the helper archive.
- **`serve`**: the ordered steps of 4.1 (PID 1 with SIGTERM and SIGINT handlers, what it blocks on with `WEB=0`), readiness and health (4.2) including the nested-service health check, a ttyd supervisor that stays alive after it gives up so that `swarmbox-web restart` can reach it (spike 0.1, design 4.2), the SSH key, the layout migration (12.4), the session `main` with one idle window.
  Slice 2.2 built `serve` in `container/entrypoint.sh` (decisions [2.2]): steps 4, 6, 7 and 12 are logged no-ops until the programs they call (`swarmbox-migrate`, `swarmbox-tool`) exist; B3 is closed-reduced; B36 is left to the `attach` slice.
  Slice 2.3 built `swarmbox-attach` (`container/scripts/swarmbox-attach.sh`, installed as `/usr/local/bin/swarmbox-attach`) and the entrypoint's `attach` forwarding (decisions [2.3]); `serve` now names the idle window `idle`; B13 and B36 are closed.
- **`swarmbox-attach`**: replaces `lib/attach-session.sh`; joins the session `main` through a grouped session, no status bar on host tabs, closes the idle window; the **`swarmbox <command>` mechanism** (3.3): no `exec` of tmux, a detached command window with a `wait-for` channel and a status file, the interactive shell so aliases and `PATH` apply, the exit code handling (`128 + signal`; a killed window gives 129 through a HUP/TERM trap in the wrapper, a missing file gives 1), the wrapper's fallback poll of its window id for a SIGKILLed wrapper, and the no-terminal case (no `-t`, no CRLF, and a non-interactive `bash -c` that sources the fragment with `SWARMBOX_CMD=1` instead of `bash -ic`, which prints job-control errors; spike 0.1, design 3.3).
- **Web terminal**: `build-index.sh` at image build, `swarmbox-web` at start with the three-value substitution (5.1).
- **Shell**: `container/config/bashrc.sh` (banner, aliases, Starship, `PATH`) replacing the `bashrc` echo lines; `shell.sh` sourcing for tools; the aliases and `yolo` generated from manifests, `SWARMBOX_AGENT` and `SWARMBOX_YOLO` (6.6), with no manifest yet the aliases are empty and `yolo` says no agent is installed.
  Slice 2.4 built the fragment (decisions [2.4]); the image's `/etc/bash.bashrc` sources it, `test_starship.py` follows it to the new place, and the banner skips itself for `bash -c`. The one-line SSH fingerprint is left out.
- **The stale-image warning** (3.8, 4.2): Phase 2 builds the part inside the box (the banner and the health file); the comparison of image IDs is the helper's `up` in Phase 3.

Tests first
- Migration test on a fixture workspace with a `v0.1.0` `.swarmbox/` (13.3 layer 3).
- `serve` step failures (13.1) with a fake environment; `swarmbox <command>` tests (13.3 layer 6).
- The image smoke test skeleton (13.3 layer 2): readiness, `box:/tmp/swarmbox` emptied on restart, the page built, `swarmbox-tool validate` placeholder, nested Podman running a container.

**Where the smoke test runs.** The image smoke test needs a third level of nesting: the development box (level 1, itself a container) runs the image under test as a throwaway box (level 2), whose nested Podman runs a container (level 3). That is not available in the development box, so the full smoke test runs **in CI (or on the owner's host)**. In the development box only **reduced checks** run (the image as a level-2 container without the nested-Podman step: readiness with warnings, the tmpfs, the page, `attach`, the exit codes), and each result is tagged `[reduced: development box, no nested Podman in the box]` and is never recorded as the full result.

Closes: B3, B13 (the product tests; the spikes fed them), B24, B26 (`id node` in the base image), B27 (image size), B28 (the cgroup settings; needs the third level, so in CI), B29 (the migration), B36 (the idle window).

**Exit criteria:** the smoke test passes in CI; in a throwaway box two `attach` calls land in the same session as two windows and the idle window is gone; `swarmbox-entrypoint attach false` fails and `attach true` succeeds; the web terminal serves the built page with the user's three settings substituted; the migration test passes; the reduced checks pass in the development box and are tagged as such. **M1.**

---

## 5. Phase 4a: the minimal tool slice

**Goal:** the smallest tool machinery that lets `claude` install on first call, so Phase 3 can be tested with a real `WITH`. Design: 6.1 to 6.5.

Scope: **`swarmbox-tool`** (manifest parsing and `validate`, `link --system`, `install`, `run`), the dispatcher **`swarmbox-shim`**, the `claude` manifest and installer (`UPDATE=self`, installed with the vendor's native installer: B1 closed in 0.3, design 6.7; the manifest's installer is not the npm shape and needs `curl`) and the real, still empty, `tool-ports`. It replaces the Phase 2 stubs.

Tests first: manifest parsing and `validate` rules (6.9) including `UPDATE=self` needing `VERSION=latest`; `link --system` is idempotent and writes the shims, the index and `tool-ports`; the shim installs with a fake installer on the first call and runs the real command after; a manifest under a project folder is **not** read (D18, the absence test).

**Exit criteria:** in a throwaway box the first `claude` call installs (with a fake installer in CI, the real one in a throwaway container) and runs it; `validate` passes for the `claude` manifest.

---

## 6. Phase 3: the host half

**Goal:** one install line, then `swarmbox` creates or joins the box. Design: 3.1 to 3.8, 7, 8.

Scope
- **Host helper in POSIX `sh`** (D16): `version`, `config get|set|list|seed`, `create-flags`, the fingerprint and labels, `up` (the lock, the flags captured before `podman run`, cleanup by `--cidfile`, the fast path with one `podman container inspect`, the exact-name match), `reset`, `stop`, `url`, `update`, and the `host-helper` archive the image serves. `swarmbox url` belongs to this phase only.
- **`swarmbox-init`**: prints the seed values and the function for bash, zsh and fish; markers; idempotent (D20); `--with`, `--workspace`, `--image`, `--shell`; the shell taken from `-e SHELL`.
- **The function and its bootstrap** (3.6, D33): extracts the helper, the "never undo an update" rule, relative `--workspace` made absolute on the host, `config seed`, no `-t` without a terminal.
- **Install, upgrade and failure behavior** (3.8): prerequisites, exit codes, messages, version skew, rollback; the WSL refusal of a workspace on a Windows drive (D34); `update` with the local `X.Y.Z` tag (D35).
- **Variables** (7, D12, D28): `swarmbox env add|rm|list`, `ENV_KEYS`, names validation, the hash label; `BROWSER_URL` and the `--remote-browser` parity (a bare number, `host:port`, no argument meaning 9222).
- **Configuration** (8): `swarmbox config`, the per-box config folder (D31), `NAME` only from `SWARMBOX_NAME`; the portable mode check (`stat -c %a`, `stat -f %Lp`, `find -perm`; never a parse of `ls` output); `notices` state file.
- **Host Podman connection** (`podman -c <name>`) and its migration to the new socket address (12.1, 12.4); the **short-symlink fallback** when the socket path is too long (3.5).
- **A local registry (`registry:2`)** in a throwaway container, with a placeholder `<org>`, so the install line, `update` and `update --to` run end to end without the real registry.
- **An arm64 CI job** (design 13.4), if the CI provider allows: build for arm64 and run the smoke test on an arm64 runner.

Tests first
- `create-flags` for every key of 8.2 (quoting, values with spaces, lists, tool ports, a missing `tool-ports`, `INIT` resolved by `up`) (13.1); no `--network=host` ever (D7).
- Function tests in bash, zsh and fish, and macOS bash 3.2 where a runner exists, with a fake helper and a fake `podman` (13.3 layer 4), including the bootstrap and the update-then-next-call cases.
- The **`up` lock and cleanup tests** (13.3 layer 5): two terminals at once create one box; a failed create removes only its own container; a stale lock is removed; `create-flags` failing never reaches `podman run`.
- The portable mode check on a file with extended attributes where possible; the WSL refusal with fake paths; the fast path call count.
- The **socket-path fallback** (3.5, B5 measured in 0.2): a workspace whose socket path is 100 characters uses it directly, 101 gets the short symlink, a symlink path over 100 exits 4; no symlink is made for the default workspace.

Closes: B5 (with the fallback; the spike fed it), B19 (`sort -V`, Linux and CI images), B20 (against the local registry), B21 (`-e SHELL`, Linux), B22 (tunnel token mode, Linux; WSL home rechecked in Phase 6), B23 (the helper under different `sh` implementations), B31 (arm64 build and run), B32 (the WSL refusal), B33 (the `up` lock and cleanup), B34 (the mode check), B35 (the fast path budget).

**Exit criteria:** with a local registry and a placeholder `<org>`, on a clean Linux machine, the documented install line followed by `swarmbox` creates the box; a second terminal joins it; two terminals started at once create one box; `stop`, `reset` (offline after `update`) and `update` behave as specified; the function and helper tests pass in CI.

---

## 7. Phase 4b: the other tools

**Goal:** every tool of the design installs, survives a reset, and the browser MCP is wired. Design: 6, 4.4, 6.8, 6.11, 6.12. It runs in parallel with Phase 3 and after it.

Scope
- **Manifests and installers** in `container/tools/`: opencode (with `prepare.sh` and the local-LLM hook), gemini, clasp (with its port, now visible in `tool-ports`), gcloud (checksum in the manifest), go, poetry. Order: opencode first (with claude it exercises both update modes), then the rest. `swarmbox-tool` gains `list`, `update`, `use`, `remove`, `link --user`, `new`.
- **`prepare.sh`** run by `serve` at step 7 and after a `tool install`.
- **Environment fingerprint** per install, `doctor` and `doctor --fix` (6.11).
- **MCP registry** (4.4): generated `mcp-servers.json`, the registry entry that runs the installed `chrome-devtools-mcp` (no `npx`), the OpenCode mirror.
- **The `WITH_TOOLS` build argument** (6.8): the Dockerfile installs the named tools into `/opt/swarmbox/tools`.
- **The D29 maintainer script** that records gcloud's (and Go's) `SHA256_amd64` and `SHA256_arm64` in the manifest.

Tests first
- `swarmbox-tool` and each installer with a fake installer (13.1); `validate` rules (6.9); MCP generation and the OpenCode mirror.
- Scheduled real-installer tests: "no side effects" and "survives a reset" per tool (6.9, 13.4), including the npm cache rule of 6.4.

**Exit criteria:** `reset` keeps an installed tool; `validate` passes for every manifest; the "no side effects" test passes for each tool; `tool-ports` lists clasp's port; a build with `--build-arg WITH_TOOLS=claude` ships it preinstalled.

---

## 8. Phase 5: remote access

**Goal:** `swarmbox remote` over the existing Cloudflare script. Design: 5.2, 3.7, D14, D28.

Scope: `remote setup|status|off|token` (and `--dry-run`) as thin wrappers over `cloudflare-setup.py`; the connector brought up on entry when configured, pinned image; the login length preserved on rerun; the tunnel token read from the host environment or from the host config with mode 600. (`swarmbox url` is Phase 3's.)

Tests first: the existing `test_cloudflare_setup.py` (kept), plus the rerun-keeps-`--session` case and the wrapper arguments; the connector logic against the fake `podman`.

Closes: no Part B fact (B14 is a documentation read in Phase 0, B22 is closed in Phase 3).

**Exit criteria:** the tests pass; the owner runs one end-to-end setup against their own Cloudflare account and reaches the box from outside.

---

## 9. Phase 6: parity, retire the scripts, documentation (M3)

**Goal:** nothing from `v0.1.0` is lost, and the old entry points are gone. Design: 12, 13.2.

- **Parity test:** one test per row of the feature catalog (8.4) against the function (D8).
- **Delete** `start.sh`, `build.sh` and `lib/` (including `lib/attach-session.sh`, replaced by `swarmbox-attach`), `container/scripts/init.sh` (D9), `container/opencode/` (its template moved to `container/tools/opencode/`) and `container/web/web-terminal.sh` (replaced by `swarmbox-web` and `build-index.sh`); a test asserts that none of them exists and that the Dockerfile names none of them.
- **Documentation:** rewrite `README.md` around the new install and first use, including the **manual uninstall steps** (D36, design 12.5) and the no-telemetry, local-logs statement; update `docs/web-terminal.md`, `docs/cloudflare.md`, `docs/nested-podman.md`; keep `design.md` and this plan in sync.
- **Dogfooding:** the owner first runs a second box (`SWARMBOX_NAME=dev`, another workspace) from M2 on; after parity the main workspace is migrated with the layout migration (12.4), after a backup.
- **Owner's real-hardware checks, closing:** B6 (macOS), B7 (UID other than 1000), B8 (older Podman), B15 (`python3` on a clean macOS). **Rechecks** (not closing): the macOS parts of B19, B21, B22, B23 and B34, and the WSL home of B22.

**Exit criteria:** the parity suite is green; the scripts are deleted; the owner's main box runs on 2.0; the checks that need real hardware have a result or an explicit, documented limit. **M3.**

---

## 10. Phase 7: release (M4)

**Goal:** a public, signed `v2.0.0`. Design: 10.4, 11, 13.4, D25, D26.

- `release.yml`: multi-arch build (amd64 and arm64), tests, vulnerability scan, signing, SBOM, publish to `ghcr.io/feroult/swarmbox` (D32, D38). One run of `update` against the real registry rechecks B20.
- Settle the registry owner and **check that the name SwarmBox is available** (D25).
- **Act on the history audit** of Phase 1 (D37): publish the history whole, or start from a clean history; only then make the repository public.
- **Security review of the host helper** before release: it runs on the host with the user's privileges (D26, 11). Review the lock and temporary files, quoting, the extraction, the token handling and `up`'s cleanup; fix or document each finding.
- **Licensing of the redistributed image:** the image includes Debian, Chromium and other third-party software; complete `THIRD_PARTY_NOTICES.md` with every license, and check that the redistribution terms are met.
- **Logging policy:** no telemetry; logs stay local under `<workspace>/.local/state/swarmbox/` and `host:~/.local/state/swarmbox/` (design 12.5); stated in `SECURITY.md` and the README.
- The Renovate or Dependabot configuration that bumps the pinned versions and the base image (10.4).
- `SECURITY.md`, `CODE_OF_CONDUCT.md`, `CHANGELOG.md` complete; the README is the 15-second pitch.
- Tag `v2.0.0`.

**Exit criteria:** a user on a clean machine follows only the README and gets a working box; the image is signed and its digest published; the security review has no open finding. **M4.**

---

## 11. Risks and how the plan handles them

| Risk | Handling |
|---|---|
| The design specifies mechanisms that never ran (readiness marker, exit codes, `swarmbox <command>` via tmux, the `up` lock) | Phase 0 spikes first; Phases 2 and 3 treat them as hypotheses and correct the design when they fail |
| The experiments run in a nested Podman with a small UID range, which may not match a normal host, and the image smoke test needs a third nesting level | Results are tagged with how they were observed (`[reduced: ...]` in the development box); the full smoke test runs in CI; B7, B8, B6 are closed on real hardware (Phase 6) |
| macOS is in scope (D6) but cannot be tested here | The platform adapter is written from the code and kept small; the owner tests on a Mac in Phase 6; failures become documented limits |
| The document is long, and code and design may drift apart | Rule 1.1.4: a change that contradicts the design updates it in the same commit; parity is a test, not a promise |
| A change in the live box breaks work in progress | The safety rule (1.2); the owner's box moves last, after a backup, and a second box is used first |
| The Cloudflare end-to-end needs the owner's account | Fakes cover the logic; one end-to-end run by the owner closes Phase 5 |
| Secrets or personal data in the git history | The audit is in Phase 1 and the repository stays private until M4 (D37) |
| Scope creep from detailed specification | Anything in the design not needed for parity or for a decision in D1 to D39 can be deferred to 2.1 and listed in the changelog |

---

## 12. Validation checklist (for the project owner)

Status: **applied** (done in the documents), **assumed default** (the plan proceeds on this answer until you change it), **open** (needs your answer).

1. **Phase order.** *Applied.* The box (Phase 2) is built before the tools and the host half; the minimal tool slice (4a) precedes Phase 3, and the design's roadmap (section 15) now follows this plan.
2. **Spikes.** *Assumed default:* run Phase 0 now in nested throwaway containers here, with the limits above. **Hardware checks:** the owner runs the macOS ones (B6, B15 and the macOS parts of B19, B21, B22, B23) later, on a Mac, before M3 (*decided*). *Open:* who runs B7 (a host UID other than 1000) and B8 (older Podman versions), or whether a CI matrix covers them.
3. **Dogfooding.** *Assumed default:* a second box (`SWARMBOX_NAME=dev`) from M2, and the main workspace moves only after parity (M3).
4. **CI provider.** *Assumed default:* GitHub Actions (the remote host alias points at GitHub). Whether a macOS runner is available is checked in Phase 1 (B30).
5. **Registry owner.** *Decided (D38):* the owner's account `feroult`, so `ghcr.io/feroult/swarmbox`. Examples keep `<org>` until the name check (D25) passes.
6. **Scope of 2.0.0.** *Decided (D39):* the whole catalog ships in 2.0.0, Cloudflare remote access included. No feature of v0.1.0 is dropped, except what section 12 of the design lists as removed.
7. **Review cadence.** *Assumed default:* review at each milestone (M1 to M4).
8. **Who builds what.** *Assumed default:* the work is done by the agent with parallel sub-agents where phases allow it (4b in parallel with 3; 5 after 3), under the rules in section 1.

---

## Appendix A. Where each decision, feature, command and fact is handled

Built from the design. "Phase" is where the decision is implemented (or where its absence is proven); a second phase is shown when the work is split.

### A.1 Decisions D1 to D39

| D | Decision (short) | Phase | How it is proven |
|---|---|---|---|
| D1 | One persistent box, one shared session | 2 | smoke test: two `attach` calls, two windows of `main` |
| D2 | Neutral image, tools on demand through shims | 2, 4a | the image holds no agent (smoke test); the first `claude` call installs it (4a) |
| D3 | Claude Code updates itself | 4a | `validate` (`UPDATE=self` needs `latest` and `UPDATE_CMD`); the scheduled real-installer test in 4b |
| D4 | OpenCode is a shim; local LLM in its tool directory | 4b | `prepare.sh` renders the config from `LOCAL_LLM_*`; the OpenCode mirror test |
| D5 | Nested Podman always on | 2, 3 | image settings and a nested container in the CI smoke test (2); `create-flags` always has the nested flags (3) |
| D6 | macOS in scope | 3, 6 | adapter and fake-Podman tests (3); owner on a Mac (6, B6) |
| D7 | No host-network mode (absence) | 3 | `create-flags` never emits `--network=host` for any key; `config set HOST_NETWORK` is refused |
| D8 | Retire `start.sh`, `build.sh`, `lib/` after parity | 6 | the parity suite, then a test that the files are gone |
| D9 | No `init.sh` (absence) | 6 | a test that `container/scripts/init.sh` is absent and the Dockerfile does not name it (the new image does not use it from Phase 2) |
| D10 | XDG layout; regenerated files in `box:/tmp/swarmbox` | 1, 2 | `dirs.sh` test (1); tmpfs emptied on restart (2) |
| D11 | Workspace chosen at install | 3 | `init --workspace`, relative path made absolute, in function tests |
| D12 | Variables only at creation, names in the config | 3 | `env` tests, `-e NAME` without value, the hash label |
| D13 | The ttyd page is built into the image | 2 | the smoke test serves the built page |
| D14 | Cloudflare credentials and connector on the host | 5 | the connector runs from the host; no Cloudflare name reaches the box (`env add` refuses `SWARMBOX_CLOUDFLARE_*`, 3) |
| D15 | A printed function, not an alias | 3 | `init` output tests |
| D16 | POSIX `sh` helper; `remote` stays Python | 3, 5 | the helper under dash, busybox and macOS `sh` (3, B23); `remote` wrappers (5) |
| D17 | `update` pulls the `X.Y` series and writes `IMAGE` | 3 | update tests against the local registry |
| D18 | No project level of tools (absence) | 4a | a manifest in a project folder is not read by `link` or `validate` |
| D19 | No throwaway mode, no `--once` (absence) | 3 | `swarmbox --once` creates no container and removes none; a second box with `SWARMBOX_NAME` works |
| D20 | Seed design; shell from `-e SHELL` | 3 | seed and `init` tests; B21 |
| D21 | Agents `latest`, other tools pinned | 4a, 4b | `validate` rule (4a); every non-agent manifest pinned (4b) |
| D22 | The option is `--with` | 3 | `init --with` records `WITH`; the function tests use `--with` |
| D23 | `chrome-devtools-mcp` pinned, installed, run directly | 2, 4b | installed at build (2, B24); the registry never uses `npx` (4b test) |
| D24 | Chromium stays in the image | 2 | present in the image; size measured (B27) |
| D25 | Apache-2.0; name availability | 1, 7 | `LICENSE` (1); the name check (7) |
| D26 | Helper accepted as coming from the signed image | 7 | signature and digest published; the helper security review |
| D27 | `update` only pulls | 3 | update tests record no `rm`, `run` or `reset` call |
| D28 | No fallback secrets file; token only with mode 600 | 3 | `env set` does not exist; mode tests; B22, B34 |
| D29 | gcloud checksum by a maintainer script | 4b | the script writes both checksums; `validate` requires them |
| D30 | A fingerprint mismatch only warns | 3 | `up` prints the line and exits 0 |
| D31 | Config folder of a second box | 3 | `SWARMBOX_NAME=dev` reads `<name>/config` |
| D32 | First version 2.0.0; `<org>` a placeholder | 3, 7 | the placeholder works with the local registry (3); the real owner is set (7) |
| D33 | The bootstrap re-extracts only when older | 3 | the bootstrap-condition and update-then-next-call function tests |
| D34 | WSL: workspace on the Linux filesystem only | 3 | `up` and `create-flags` refuse `/mnt/<letter>/` (exit 4); B32 |
| D35 | `update` tags the exact `X.Y.Z` locally | 3 | `podman tag` recorded; `reset` offline after `update`; B20 |
| D36 | No `uninstall` command (absence) | 3, 6 | `swarmbox uninstall` is no host word, routed as a command (3); the manual steps in the README (6) |
| D37 | History audit early; repository private until M4 | 1, 7 | the audit report (1); the repository is made public only at the release (7) |
| D38 | Image owner `feroult`: `ghcr.io/feroult/swarmbox` | 3, 7 | local registry with a placeholder (3); the first publish under `ghcr.io/feroult` and the package visibility set to public at release (7) |
| D39 | 2.0.0 includes the whole catalog, Cloudflare remote access too | 5, 6 | the parity suite has a row for `remote` (6); the end-to-end run of Phase 5 |

### A.2 Feature catalog (8.4) and command contract (3.2, 3.3)

Feature rows, in the order of 8.4:

| Row | Phase |
|---|---|
| Box: persistent container, enter-or-create, stop, reset, update, up | 3 |
| Box: shared tmux session, no status bar on host tabs | 2 |
| Box: workspace mount, fixed user with `sudo`, `--init`, pids limit, hostname, time zone, locale | 2 (user, locale), 3 (the flags) |
| Box: fingerprint, stale-image and startup-health warnings | 2 (health lines, banner), 3 (fingerprint, stale image on the host) |
| Box: environment variables and keys | 3 |
| Shell: Starship, banner, aliases, `PATH`, `/opt/flow`, `uv` | 2 |
| Shell: tmux configuration, Alt shortcuts, clipboard bridge | 2 |
| Git: SSH key, `swarmbox pubkey`, trust on first use | 2 |
| Web: web terminal on by default | 2 |
| Web: remote access through Cloudflare | 5 |
| Containers: nested Podman with the host connection | 2 (box), 3 (host connection) |
| Browser: chrome-devtools MCP, local or remote | 4b (registry), 3 (`BROWSER_URL` parity) |
| Network: published ports, host access | 3 |
| Tools: claude, gemini, opencode, gcloud, clasp, Go, Poetry | 4a (claude), 4b (the others) |

Commands, in the order of 3.2 and 3.3 (the phase where the command is built; the function routes it from Phase 3):

| Command | Phase |
|---|---|
| `swarmbox` (enter) and `attach` | 2 (entrypoint and attach), 3 (function and `up`) |
| `claude`, `yolo` (inside the box) | 4a (`claude`), 2 (`yolo`, aliases) |
| `swarmbox <command>` (for example `swarmbox claude`) | 2 (the mechanism and its exit code), 3 (routing) |
| `swarmbox --plain` | 2 (`attach --plain`), 3 (function parsing) |
| `swarmbox pubkey` | 2 |
| `swarmbox tool ...` | 4a (the stub is shipped in 2) |
| `swarmbox up`, `stop`, `reset`, `update [--to TAG]` | 3 |
| `swarmbox url` | 3 (only) |
| `swarmbox config set\|get\|list`, `env add\|rm\|list` | 3 |
| `swarmbox remote setup\|status\|off\|token`, `remote setup --dry-run` | 5 |

### A.3 Facts B1 to B36

Each fact is **closed** by one phase. "Feeds" and "rechecks" are shown separately and never close.

| B | Fact (short) | Closed in | Feeds or rechecked |
|---|---|---|---|
| B1 | Claude Code install method that keeps its updater (closed in 0.3: native installer) | 0 | feeds 4a |
| B2 | OpenCode auto-approve flag (closed in 0.3: `--auto`, no alias, `YOLO_ALIAS=0`) | 0 | feeds 4b |
| B3 | `serve` as main process; signals; ttyd restart | 2 | fed by the Phase 0 spike (spiked in 0.1, reduced) |
| B4 | ttyd serves one file | 0 | closed in 0.4 |
| B5 | Unix socket path limit and the fallback | 3 | closed in 0.2: limit 107 characters, fallback above 100 (3.5); the Phase 3 tests carry it |
| B6 | The design on macOS | 6 | not doable in Phase 0 (hardware) |
| B7 | A host UID other than 1000 | 6 | not doable in Phase 0 (hardware) |
| B8 | Lowest working Podman version | 6 | not doable in Phase 0 (older Podman versions) |
| B9 | tmux environment for new windows | 0 | closed in 0.1 |
| B10 | OpenCode size saving under `--prefix` (closed in 0.3: 745 MB) | 0 | feeds 4b |
| B11 | gcloud URL and checksum | 0 | feeds 4b; closed in 0.4 (checksum of the pinned file is computed, D29) |
| B12 | Re-record unrecorded checks | 0 | re-recorded in 0.2; the 4.2 GB size stays `[unverified]` until B27 in 2 |
| B13 | `swarmbox <command>` mechanism and exit code | 2 | fed by the Phase 0 spike (spiked in 0.1, reduced); closed in 2.3 |
| B14 | Where Access sessions are revoked | 0 | documentation read in 0.4, stays `[unverified]`; owner tries it in a dashboard |
| B15 | `python3` on a clean macOS | 6 | not doable in Phase 0 (hardware) |
| B16 | Restart after a host reboot | 0 | partly checked in 0.4; the reboot is `[unverified]` (needs systemd) |
| B17 | tmpfs empty after stop and start | 0 | rechecked by the Phase 2 smoke test |
| B18 | Container left behind by a failed `run` | 0 | used by B33 in 3 |
| B19 | `sort -V` | 3 | macOS part rechecked in 6 |
| B20 | `update` and the exact tag | 3 | real registry rechecked in 7 |
| B21 | `-e SHELL` reaches `init` | 3 | macOS part rechecked in 6 |
| B22 | Tunnel token file mode | 3 | macOS and WSL home rechecked in 6 |
| B23 | Helper under several `sh` | 3 | macOS part rechecked in 6 |
| B24 | `chrome-devtools-mcp` installed program | 2 | used by 4b |
| B25 | Go checksum source | 0 | feeds 4b; closed in 0.4 |
| B26 | UID of the base image's `node` user | 2 | |
| B27 | 2.5 GB size target | 2 | |
| B28 | cgroup manager settings | 2 | |
| B29 | Layout migration | 2 | |
| B30 | macOS CI runner | 1 | |
| B31 | arm64 build and run | 3 | |
| B32 | WSL workspace refusal | 3 | |
| B33 | `up` lock and cleanup | 3 | |
| B34 | Portable mode check | 3 | macOS part rechecked in 6 |
| B35 | Fast path of `up` | 3 | |
| B36 | Idle window of `main` | 2 | closed in 2.3 |
