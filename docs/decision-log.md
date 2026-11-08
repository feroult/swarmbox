# Decision log

Every decision the build takes that the design or plan did not settle is recorded here: deviations from the design, scope reductions, workarounds, and things that did not work. The owner reviews this file.

Entry format:

    ## [<phase>.<slice>] <title>
    Context: what came up
    Options: the choices considered
    Chosen: <option> because <reason>
    Impact on the design: what changed in docs/design.md (or none)
    How to reverse: the steps to undo it

Entries are appended in order; none are rewritten.

## [0.preflight] Installed test shells and shellcheck on the live box
Context: The host helper must work in bash, zsh and fish, and be lint-clean; zsh, fish, busybox and shellcheck were missing.
Options: skip those shell checks; install the packages.
Chosen: install zsh, fish, busybox and shellcheck with apt (APT::Sandbox::User "root"; a prior apt-get update was needed because the package lists were empty) because they are additive and the checks need them. No existing package was removed or upgraded on purpose.
Impact on the design: none.
How to reverse: sudo apt-get remove zsh fish busybox shellcheck (these were not present before).

## [0.1] Spike harness is Python with guards in code
Context: Slice 0.1 needed a shared helper for the spikes (swarmbox-test- names, exact-name cleanup, evidence line, tmux isolation).
Options: a shell helper (tests/spikes/helpers.sh); a Python module (tests/spikes/spikes_common.py).
Chosen: Python module, unit-tested by tests/test_spikes_common.py with a fake podman and tmux on PATH, because the existing tests are Python unittest, and the safety rules (name prefix, no --all or prune, ports 127.0.0.1 in 20000-40000, tmux only with -L swarmbox-test-<id> and TMUX unset, rm by exact name, kill-server only on the spike's own socket) can be refused in code before a command is run. The test also scans every spike script for forbidden ports, 0.0.0.0, pkill and direct tmux/podman calls.
Impact on the design: none.
How to reverse: delete tests/spikes/ and tests/test_spikes_common.py.

## [0.1] Container-side port 7000 and 8080 in the spikes, never 7681
Context: The design says ttyd listens on 7681 inside the box. The static scan of the spikes forbids the literal 7681 (the live ttyd owns it on this machine's network namespace).
Options: use 7681 inside the throwaway container (the host side is random anyway); use another port inside.
Chosen: another port inside (ttyd -p 7000, a test container on 8080) because the number inside a container does not change what the spikes measure, and it keeps the rule "no spike mentions 7681" checkable by a plain scan.
Impact on the design: none. The spike results do not depend on the number.
How to reverse: change CPORT in spike_b3_serve_pid1.py and relax the scan in tests/test_spikes_common.py.

## [0.1] ttyd for B3 is the live box's own binary, copied into a scratch image
Context: B3 needs ttyd. /usr/local/bin/ttyd on this box is the static 1.7.7 executable that the product Dockerfile pins.
Options: download the release from GitHub; copy the box's binary into the scratch image build context.
Chosen: copy it (no network needed, same release as the Dockerfile's pin, 1.7.7-40e79c7) because the check is about supervision and signals, not about the download. The checksum was not re-verified here.
Impact on the design: none. The evidence tag says the ttyd binary came from the box.
How to reverse: n/a.

## [0.1] Scratch image swarmbox-test-spikes-img:1 (node:24-slim, tmux, procps, ttyd)
Context: B3, B9 and B13 need tmux and ttyd in a container; node:24-slim has neither. apt in a nested build fails unless APT::Sandbox::User "root" is set.
Options: build a scratch image with the apt sandbox line in the scratch Dockerfile only; install tmux at every run.
Chosen: build once, named swarmbox-test-spikes-img:1, kept during the run through SWARMBOX_SPIKE_KEEP_IMAGE=1 and removed by exact name at the end of the slice (a spike run without the variable removes it itself). The line is never added to the product Dockerfile.
Impact on the design: none.
How to reverse: podman rmi swarmbox-test-spikes-img:1.

## [0.1] B13: the command wrapper needs a HUP/TERM trap (design 3.3 corrected)
Context: The design said a missing status file (window killed from elsewhere) gives exit 1. The spike showed that with a plain wrapper, tmux kill-window leaves "tmux wait-for" blocked forever: the caller hangs and no status file exists.
Options: poll for the window only; add a trap to the wrapper; use tmux hooks (pane-exited).
Chosen: a trap on HUP and TERM that writes 129 and signals the channel (measured: the waiter returned, status 129), plus a fallback poll of the window id for the SIGKILL case (measured only that the window disappears; the poll loop itself is not built) because it is the smallest change that was measured to work. Hooks were not tried.
Impact on the design: 3.3 (mechanism, exit-code text), 13.3 layer 6 (a killed-window test), plan Phase 2 (attach bullet), Part B results.
How to reverse: remove the trap text from 3.3; the hang then returns.

## [0.1] B13: no-terminal commands do not use bash -ic (design 3.3 corrected)
Context: The design ran the no-terminal case through bash -ic. Measured: an interactive bash without a terminal writes "cannot set terminal process group" and "no job control in this shell" to stderr (status correct). A plain bash -c does not apply aliases because the fragment's interactive guard returns.
Options: bash -ic and live with the noise; filter stderr; a non-interactive bash that sources the fragment, whose guard also accepts SWARMBOX_CMD=1.
Chosen: the third, because it measured clean (alias and PATH applied, exit status 9 kept, empty stderr) and leaves interactive shells unchanged. Debian's /etc/bash.bashrc returns at once when PS1 is empty, so the fragment file is sourced directly, not through /etc/bash.bashrc.
Impact on the design: 3.3 (No terminal, --plain), 13.3 layer 6. Whether the real fragment behaves the same is left [unverified] for Phase 2.
How to reverse: go back to bash -ic in 3.3 and accept the two stderr lines.

## [0.1] B13: wrapper passed to tmux new-window as separate arguments
Context: The design built one string for the window command. tmux 3.3a accepts "new-window ... bash -c WRAPPER wrapper ARG ARG ARG" and runs it without another shell.
Options: one quoted string; separate arguments.
Chosen: separate arguments (all 17 awkward arguments arrived byte for byte, no injection) because it removes a quoting layer. Older tmux versions were not tried; the box's tmux is the Debian one.
Impact on the design: 3.3 mentions it.
How to reverse: build one string with printf %q as before.

## [0.1] B3: the ttyd supervisor stays alive after it gives up (design 4.2 corrected)
Context: 4.2 says that after 5 exits in 60 s the supervisor stops trying and "swarmbox-web restart" restarts ttyd and resets the count. My first prototype let the supervisor exit when it gave up, and then no restart was possible.
Options: supervisor exits (restart needs a new supervisor); supervisor idles and waits for the restart signal.
Chosen: idle and wait (measured: a restart signal after giving up started ttyd, cleared the health line, answered over the published port) because restart must work in exactly the case where ttyd keeps crashing.
Impact on the design: 4.2 text, plan Phase 2 serve bullet.
How to reverse: let the supervisor exit and have swarmbox-web start a new supervisor.

## [0.1] B3 and B13 stay open; B9, B17, B18 closed
Context: The plan (A.3) closes B3 and B13 in Phase 2 by product tests, and B9, B17, B18 in Phase 0.
Options: mark B3 and B13 closed from the spike; mark them spiked and leave them open.
Chosen: spiked, left open, because the prototypes are bash stand-ins (a sleep for the nested Podman service, script(1) for the terminal, no real swarmbox-attach), so the evidence tags say "reduced". The design still carries the measured results.
Impact on the design: Part B rows say "Spiked in 0.1 ... closed by the product test in Phase 2"; a results table was added after Part B.
How to reverse: edit the two rows.

## [0.1] B17 result: this Podman adds no noexec to --tmpfs
Context: B17 asked whether the default tmpfs options (Podman may add noexec) break serve or the shells.
Options: n/a (observation).
Chosen: record what was seen: mounted rw,nosuid,nodev,relatime, no noexec, on Podman 4.3.1; scripts in the folder also run through an interpreter. Other Podman versions were not checked (B8); nothing in the design executes from that folder.
Impact on the design: 4.1 step 0 cites it; no change to the design.
How to reverse: n/a.

## [0.1] B18 result: cleanup by cidfile ID is right, a fresh cidfile path per call is required
Context: B18 and B33 depend on what a failed podman run leaves behind.
Options: n/a (observation).
Chosen: record: busy port gives exit 126, message "rootlessport listen tcp 127.0.0.1:<port>: bind: address already in use", a Created container, and a cidfile with its ID; a name clash gives exit 125 and no cidfile; an existing cidfile gives exit 125. The design's cleanup and its fresh path per call (code in 3.6) match; only the text was made specific.
Impact on the design: 3.5 edge-case row, 3.6 note on B33.
How to reverse: n/a.

## [0.1] B14 and B16 and the rest of Phase 0 are not part of this slice
Context: Slice 0.1 is the five container spikes only.
Options: do all of Phase 0 in one slice; split.
Chosen: split, as the workflow assigned; B4, B5, B1, B2, B10, B11, B12, B14, B16 and B25 are left to later slices and stay [unverified] in Part B.
Impact on the design: none.
How to reverse: n/a.

## [0.2] B5: the socket limit is 107 characters and the fallback starts above 100
Context: 3.5 said "roughly 108 bytes" and "fall back to a short symlink if needed" without a number or a mechanism.
Options: threshold at 107 (the exact limit); threshold with a margin; no fallback, only an error.
Chosen: fall back when the host-side socket path is longer than 100 characters, because macOS and BSD sockets hold 104 bytes (103 characters) and B6 cannot be run here; 100 leaves a margin for both. Mechanism chosen: a symlink to the state FOLDER (not to the socket), measured to work: the service binds its short container path and the host connects through the symlink path. If the symlink path is still over 100, `up` exits 4 (exit 4 chosen first without checking; CHECKED in round 1 of the fix: the plan has no separate exit-code table, the design's authority is the 3.7.2 and 3.8 tables, where 2 is usage, 3 prerequisite or network, 4 workspace problem (D34, not writable, not shared), 5 conflict. A workspace path too deep for a socket is a workspace problem, so 4 fits and is kept).
Impact on the design: 3.5 rewritten with the rule; plan Phase 3 tests gained a boundary test (100, 101, symlink too long); B5 closed. The symlink location (host:~/.local/state/swarmbox/) and its name are proposals for Phase 3 [unverified as to macOS, where the socket does not cross the VM anyway].
How to reverse: change the threshold constant in the helper and the sentence in 3.5.

## [0.2] B5 reduced: a Python stand-in for the nested Podman service
Context: a real `podman system service` inside a throwaway container needs a third nesting level.
Options: skip the container half; use a stand-in that binds the socket.
Chosen: the stand-in (Python bind/listen in a python:3.11-slim container with the deep folder mounted at /home/agent), tagged reduced. `podman --url unix://<too long>` was run for real and fails with `connect: invalid argument`; the symlink case could not be run through Podman end to end because the stand-in does not speak HTTP (it answered connection refused once it was past its listen).
Impact on the design: the 3.5 tag says reduced. The kernel limit is the same for any process, so the rule does not depend on the stand-in.
How to reverse: rerun with a real service once a runner with a third level exists.

## [0.2] B12 keep-id: podman inspect says "private", so tests read uid_map
Context: my first test asserted that `podman inspect` shows keep-id; it shows `private` on Podman 4.3.1 although the mapping is a keep-id one.
Options: keep the assertion (fails); assert the uid map.
Chosen: assert /proc/self/uid_map (container 1000 to the invoking user, length 1) plus file ownership on the host, because that is the behavior the design relies on. A host UID other than 1000 is still B7 (the host here is 1000).
Impact on the design: 3.6 tag re-recorded with this note.
How to reverse: n/a.

## [0.2] B12 sizes: 325 MB and 156 MB re-confirmed; the 4.2 GB image figure stays unverified
Context: re-record the install sizes and the image size.
Options: rebuild the v0.1.0 image (hours, large, touches nothing of the owner but is outside the cheap scope); read an existing image (none exists: podman images shows no swarmbox image); measure components.
Chosen: components only: Claude Code 2.1.319 under --prefix 325 MB, cache 156 MB (the old figure said 157 MB), node:24-slim base 225 MB. The 4.2 GB figure is marked [unverified] with the reason, in the 10.2 size-budget bullet. The npm measurement used the registry's current release, so it moves with versions.
Impact on the design: persistence table (3.6) retagged with date, Podman, OS, image; 10.2 size bullet notes the gap.
How to reverse: build v0.1.0 in a scratch dir and run `podman image inspect`.

## [0.2] B12 `$0`: sourcing differs per shell, so the function never uses $0
Context: the design only claimed that a symlink keeps its name in $0 (shim, 6.2). The host function is sourced, which is a different case.
Options: record only the shim claim; also record the sourced case.
Chosen: both, per shell. Shebang scripts through a symlink give the symlink path in dash, bash, zsh and busybox sh (also through PATH). In a sourced file, $0 in a function is /usr/bin/dash, /usr/bin/bash, the function name (zsh) or `sh` (busybox). fish was not tested (not POSIX); the function must call the helper at its fixed location (3.6 already says it is fixed). The check ran on the box's own shells rather than in a throwaway container (no container is needed for a shell experiment), tagged reduced.
Impact on the design: 6.2 text and tag; Part B table.
How to reverse: n/a.

## [0.2] B12 `exec -e`: confirmed, extended
Context: the claim was verified without date or version.
Options: n/a (observation).
Chosen: re-ran with three entries (value A, value B, unset): each entry saw the current host value, unset gave empty, nothing in inspect or PID 1's environment. No design change.
Impact on the design: 7.3 tag only.
How to reverse: n/a.

## [0.2] B5 fallback reflected in 3.7 (review fix)
Context: the review found the exit 4, the symlink and its host path appeared only in 3.5.
Options: leave in 3.5 only; or mirror in 3.7 and 3.8.
Chosen: mirror, because the exit criterion asks for 3.5 and 3.7. Added: the `up` exit-4 cause, a new step 6 (the connection) in the `up` sequence of 3.7.2, the message row in the 3.8 table, and the symlink in the host-side state list of 3.5. The message text is a proposal.
Impact on the design: 3.5 host-state list, 3.7.2 `up` row and steps (the lock release is now step 7), 3.8 table.
How to reverse: remove those four insertions; 3.5 still carries the rule.

## [0.3] B1: UPDATE=self installs Claude Code with the vendor's native installer, not npm
Context: the design left open whether `claude` is installed with npm under `--prefix` or with the native installer (B1). Measured in two throwaway node:24-slim containers (uid 1000, empty home), release 2.1.314 then `claude update`. npm under `--prefix`: the updater runs npm against npm's default global prefix (/usr/local), prints "npm global folder isn't writable" and "Insufficient permissions to install update", and does nothing; with `NPM_CONFIG_PREFIX=<prefix>` in the environment it updates in place. Native: updates with no setting, writes only in the home, keeps both versions on disk (285 + 325 MB).
Options: (a) npm plus `NPM_CONFIG_PREFIX` exported by the shim; (b) native installer, no redirection; (c) native installer with XDG_DATA_HOME, XDG_STATE_HOME and XDG_CACHE_HOME redirected into `$TOOL_PREFIX`.
Chosen: (b), the design's own recommended direction (D3: the tool updates itself) and the method the updater itself recommends ("run claude install to switch to the native installer"). (a) would make the npm prefix global for everything the agent runs in that session; (c) works (verified, the launcher symlink still lands in ~/.local/bin) but exporting XDG variables to Claude Code redirects every program it starts. Cost accepted: the hard rule of 6.4 gets an explicit exception for `UPDATE=self` tools (four named paths in the workspace home); old versions pile up (610 MB for two) and nothing was seen pruning them (one update only, [unverified] beyond that); SwarmBox records no checksum for the vendor download.
Impact on the design: 6.4 (claude install.sh is not the npm shape; hard rule exception), 6.7 (the B1 bullet rewritten with the measurements), 6.11 (tag), 6.12 (table row), Part B (B1 closed, result row), plan 4a scope and A.3.
How to reverse: use (a): npm install in `claude/install.sh`, and set `NPM_CONFIG_PREFIX=$TOOL_PREFIX` for the `claude` shim only; remove the exception sentence in 6.4.

## [0.3] B2: OpenCode's flag is `--auto`, but OpenCode gets no alias; new manifest keys YOLO_FLAGS use with YOLO_ALIAS=0
Context: `opencode --help` and `opencode run --help` list `--auto` ("Auto-approve permissions that are not explicitly denied") in @opencode/cli 2.2.6 and opencode-ai 1.19.5. The documentation pages fetched (opencode.ai/docs/cli, /permissions, /) do not mention the flag. `opencode --auto run "x"` fails: "Unrecognized flag: --auto in command opencode run"; `opencode --auto --version`, `opencode --auto mcp --help` parse. So an alias `opencode --auto` breaks `opencode run`.
Options: (a) alias anyway; (b) no flag at all; (c) keep the flag for `yolo` only via a new manifest key.
Chosen: (c): `YOLO_FLAGS="--auto"` and a new key `YOLO_ALIAS=0` (default 1) so no alias is generated; `yolo` always starts the interactive program, where the flag is accepted. The semantics are weaker than Claude's (deny rules still apply), which is the safer side. The key name is my proposal.
Impact on the design: 6.3 (two keys documented), 6.6 (alias rule), the opencode manifest example, 6.12 table, Part B. Not verified: `yolo` starting the interactive OpenCode with `--auto` (no terminal in the spike); `run --auto` against a prompt was run once with OpenCode's built-in free model and no credentials (2.2.6 answered "ok"; 1.19.5 failed with a database error, see next entry).
How to reverse: delete `YOLO_ALIAS` and generate the alias (accepting that `opencode run` fails through the alias), or drop `YOLO_FLAGS` for opencode.

## [0.3] B10: the OpenCode pruning saving is confirmed (745 MB); the two npm packages are different lines and must not be swapped
Context: `@opencode/cli` (what v0.1.0 installs; 2.2.6 today) shows four builds under `node_modules/@opencode`, with `bin/opencode.exe` hard-linked to `cli-linux-x64`: 992 MB to 247 MB (saved 745 MB, the design said about 720), binary still runs. `opencode-ai` 1.19.5 installs two builds on glibc: 409 MB to 205 MB. Running opencode-ai 1.19.5 in a home that 2.2.6 had written to failed with "Database is not empty and has no session table".
Options: keep `@opencode/cli`; switch to `opencode-ai`; support both.
Chosen: keep `@opencode/cli` (continuity with v0.1.0, and `--auto` exists in both). The pruning rule says "keep what bin/opencode.exe is linked to" rather than a list of names, since the count and the names move with version and architecture. Not resolved: which package the upstream project means as its main one (the registry has `opencode-ai` on a 1.x line and `@opencode/cli` on a 2.x line; both point to the same GitHub repository) [unverified]; the owner may want to review this. Also noted, not investigated: 2.x starts a shared background server per user account ("background service", `--standalone` avoids it); how that behaves under the box's supervisor is a Phase 4b question.
Impact on the design: 6.4 text; 6.12 row.
How to reverse: change the package name in the opencode installer and remove the 6.4 note.

## [0.3] Spike scripts: the first runs contradicted my own over-strict assertions, fixed in the scripts, not in the design
Context: B10 asserted at least 300 MB saved for both packages (opencode-ai only has one removable build: 204 MB); B1 counted /opt/npm-cache entries as writes outside the home (the image deliberately puts the npm cache there).
Chosen: thresholds per package (600 MB and 150 MB); the /opt/npm-cache path is excluded from the outside-the-home check and reported in the text. I wrote the spikes after exploring by hand, so "tests first" here means the assertions were written before the final runs, not before the experiment.
Impact on the design: none. How to reverse: n/a.

## [0.4] B11: the gcloud checksum is computed for the pinned URL, not copied from Google's page
Context: Google's install page (docs.cloud.google.com/sdk/docs/install-sdk) publishes sha256 for the Linux x86_64 and arm archives, and both matched my downloads. But it publishes them only for the unversioned names (`google-cloud-cli-linux-x86_64.tar.gz`), which always mean the newest release. The version-pinned archives (`google-cloud-cli-592.0.0-linux-x86_64.tar.gz`) exist but are different bytes (other size by 8 bytes on arm, other sha256) with identical content (every file hashed and compared). The design had assumed a publisher checksum could be compared with the script's result.
Options: (a) pin the unversioned URL and copy Google's checksum (breaks at the next Google release); (b) pin the versioned URL and compute the checksum at release time (trust on first use), cross-checking content with the unversioned archive when the pinned version is still the newest; (c) verify extracted content only.
Chosen: (b), because it is what D29 already said and it is the only option that stays stable; the page's checksum is only a cross-check that applies for a short window. Arm64 uses Google's name `arm`.
Impact on the design: 6.4 (gcloud paragraph rewritten with URLs and values), 6.12 row, Part B rows B11 and results. D29 stands. Values recorded are those of 592.0.0 and will be stale; the maintainer script must recompute them.
How to reverse: (a) with a manifest that pins the unversioned URL and updates the checksum on every bump.

## [0.4] B25: Go's checksum is copied from go.dev's JSON listing
Context: `https://go.dev/dl/?mode=json` lists a sha256 per file; go1.27.3 linux-amd64 and linux-arm64 matched the computed values. The listing covers versioned files, so no computing is needed.
Options: compute like gcloud; copy the publisher value.
Chosen: copy the publisher value (a stronger check than computing). The same maintainer script handles both: gcloud computes, Go copies. `&include=all` for older releases was not tried.
Impact on the design: 6.4 (new Go paragraph), 6.12 row, Part B.
How to reverse: compute the value instead.

## [0.4] B4: ttyd's single-file limit is confirmed by measurement
Context: the box's ttyd 1.7.7-40e79c7 with `--index` serves only that file; `/style.css`, `/app.js`, `/other.txt` and `/index.html` return 404. Run with the host's ttyd binary on a random 127.0.0.1 port (not in a container; never on 7681); the spike kills only the PID it started. Documentation of ttyd was not separately fetched: `--help` only says "Custom index.html path".
Options: none needed; the design (inline into one file) is confirmed.
Chosen: record the measurement; reduced tag (no container).
Impact on the design: 5.1 limit sentence now states the measurement. How to reverse: n/a.

## [0.4] B14: Cloudflare session revocation recorded from documentation only
Context: Cloudflare's session-management page names Zero Trust > Access controls > Applications > app > Edit > "Revoke existing tokens", and Zero Trust > Team & Resources > Users > user > Action > Revoke. No real account may be contacted, so the screens were not seen.
Options: mark verified from the documentation; keep `[unverified]`.
Chosen: keep `[unverified]` with the documented path stated, because menu names change and nothing was tried. Fact B14 stays open.
Impact on the design: section 11 now gives the path; the plan's "say it is not documented" intent is superseded because it is documented.
How to reverse: n/a.

## [0.4] B16: podman-restart.service on 4.3.1 covers `--restart=always` only; the reboot is untested
Context: Podman 4.3.1 documentation: "restart will not restart containers after a system reboot" (without systemd). The package ships the USER unit /usr/lib/systemd/user/podman-restart.service (WantedBy=default.target) running `podman start --all --filter restart-policy=always`. Throwaway containers: the filter lists `--restart=always` but NOT `--restart=unless-stopped` (documented as "identical to always") and not `no`. The sandbox has no systemd, so enable, reboot and lingering were not tried.
Options: claim it works for rootless; leave everything unverified; record what was measured.
Chosen: record what was measured, mark the reboot and lingering `[unverified]`, and add the rule "if a box ever gets --restart on 4.3.x use always". The box still has no --restart in 2.0 (unchanged).
Impact on the design: 4.2 restart-policy bullet; Part B B16 stays partly open. The later-Podman claim (unit covers unless-stopped) comes from upstream main's unit text, not tested, so marked `[unverified]`.
How to reverse: n/a.

## [0.4] Spike scripts: the first run of B11 and B16 contradicted my assumptions; assertions changed into recorded findings
Context: B11 first asserted that pinned and unversioned archives had the same sha256 (they do not); B16 first asserted unless-stopped is matched by the unit's filter (it is not). Both assertions were my assumptions, not design claims, and both are now findings recorded in the design. The docs consistency test (tests/test_design_partb.py) was written before the design edits and failed first; it also needed two tolerance fixes (the format-description tag and a legacy tag marked "not recorded" are skipped).
Impact on the design: as above. How to reverse: n/a.

## [0.5] Phase 0 outcome table in the design, not a new Part B column
Context: the exit criteria want every Phase 0 fact shown as closed, reduced or open with an owner. The Part B table already has a long free-text Fact column per row that earlier slices edited.
Options: add a Status column to the Part B table; add a separate outcome table under the results; only edit Appendix A.3 of the plan.
Chosen: a separate "Phase 0 outcome" table after the results table (state, owner, note), plus short notes in plan A.3, because it avoids reflowing 36 long rows and keeps one row per fact for the test.
Impact on the design: new subsection at the end of Part B; "Part B lists" text unchanged.
How to reverse: delete the subsection and the plan paragraph "Phase 0 outcome"; update tests/test_docs_consistency.py.

## [0.5] Ownership of B12 (image size), B14 and B16 left open
Context: B12's 4.2 GB size needs a built image (the box's own must not be rebuilt); B14 needs a Cloudflare dashboard (no real account may be touched); B16's reboot needs systemd.
Options: close them with documentation; mark them reduced or open with an owner.
Chosen: B12 reduced, owner Phase 2 (with B27); B14 open, owner the project owner; B16 reduced, owner the project owner on a host with systemd. All stay `[unverified]` for the unchecked part.
Impact on the design: outcome table only. How to reverse: n/a.

## [0.5] B6, B7, B8 and B15 skipped as hardware or version dependent
Context: they need a Mac, a host UID other than 1000, older Podman versions (4.0, 4.9, latest) and a clean macOS. Pulling other Podman versions is not possible here.
Chosen: skip, list as "not doable here" with owner (the owner or a CI matrix in Phase 6). Nothing was tested or guessed.
Impact on the design: none beyond the outcome table. How to reverse: run them in Phase 6.

## [0.5] Design text said "D1 to D37" while D38 and D39 exist
Context: section 14 cited the decisions as D1 to D37; the table has D1 to D39.
Chosen: fix the text to D39 and add a test that guards the range.
Impact on the design: one sentence. How to reverse: n/a.

## [0.5] Spike scripts stay under tests/spikes/, documented, not run in CI
Context: the plan says they later become real tests.
Chosen: tests/spikes/README.md lists each script with its B number, command and prerequisites and a promotion table (which phase turns it into a test); test_docs_consistency.py checks the list against the directory. The spikes are not wired to CI because they download packages, need Podman and take minutes.
Impact on the design: none. How to reverse: n/a.

## [1.1] LICENSE text source and copyright holder line
Context: D25 fixes Apache-2.0 but not where the text comes from or whose name goes in the copyright line.
Options: copy the text from apache.org; copy it from the Debian package; add a "Copyright [yyyy] [name]" line to the LICENSE.
Chosen: the unmodified text of /usr/share/common-licenses/Apache-2.0 (Debian base-files, same text as apache.org, 202 lines, with the appendix left as the standard template) because it was available offline and verified by test (title, appendix, boilerplate, end marker). No copyright line was added to LICENSE, which is the Apache recommendation for the unmodified text. The recommended holder name "SwarmBox contributors" is not yet written anywhere because there are no source headers or NOTICE file to carry it; when one is added, use "Copyright <year> SwarmBox contributors". The owner may prefer a personal or company name.
Impact on the design: none (D25 stands; the name-availability check stays a Phase 7 task).
How to reverse: replace LICENSE; no other file depends on its text.

## [1.1] Repository visibility stays a manual owner action
Context: D37 and the plan keep the GitHub repository private until M4.
Chosen: nothing was changed or configured; this slice only adds the files. Making the repository public is for the owner after Phase 7 acts on the history audit.
Impact on the design: none. How to reverse: n/a.

## [1.1] Third-party notices: scope and honesty
Context: the Dockerfile installs more than ttyd, starship and tmux (Debian packages, Poetry, uv, Go, gcloud, npm tools, Claude Code, OpenCode).
Chosen: list every tool the Dockerfile names, with a license read from the upstream LICENSE file or the installed package where possible (tag [verified: ...; 2026-11-08]) and [unverified] otherwise: the licenses of Podman's helper packages, the components bundled in Chromium, google-cloud-cli (no copyright file found), the individual base packages, the OpenCode repository URL and chrome-devtools-mcp. uv is dual Apache-2.0/MIT: only the MIT file was re-read. Claude Code is listed as proprietary (not redistributed, downloaded at build). tests/test_repo_files.py checks that each ARG *_VERSION tool, each npm -g package and the named installers appear in the file.
Impact on the design: none. Phase 7 completes the list from the package database.
How to reverse: n/a.

## [1.1] New test file tests/test_repo_files.py instead of extending test_docs_consistency.py
Context: the slice allowed either.
Chosen: a separate file, because test_docs_consistency.py is about design and plan cross-references and this one is about repository files; CONTRIBUTING.md lists every tests/test_*.py, so a new test file must be added to its table (the test enforces that).
Impact on the design: none. How to reverse: n/a.

## [1.1] Build command in CONTRIBUTING.md
Context: the build command must match build.sh as it is today.
Chosen: ./build.sh (read: podman build with USER_UID, USER_GID, HOST_OS, tag from --name, default swarmbox). The text tells contributors to pass --name swarmbox-test-<id> so a build never replaces the live box's image. A full build was NOT run (several GB, minutes, and the default name would replace the owner's image), so the sentence is tagged [unverified]; --name is verified by reading build.sh lines 60-62 and 106. build.sh --name also renames CONTAINER_NAME, which was not exercised.
Impact on the design: none. How to reverse: n/a.

## [1.2] dirs.sh variable names
Context: design 4.3 fixes the folders but not variable names; Phase 2 will source the file from every script.
Options: SWARMBOX_* (collides with the SWARMBOX_<KEY> config overrides of 4.3 item 2); no prefix; SB_*.
Chosen: SB_CONFIG_DIR, SB_DATA_DIR, SB_TOOLS_DIR, SB_SHIMS_DIR, SB_STATE_DIR, SB_LOG_DIR, SB_HEALTH_FILE, SB_PODMAN_SOCK, SB_RUN_DIR (=/tmp/swarmbox) because SB_ cannot be mistaken for a config key. Variables are plain shell variables, not exported. SB_RUN_DIR is fixed (no override). Documented in the header of container/scripts/dirs.sh and named in design 4.3 item 4.
Impact on the design: 4.3 item 4 now lists the names. How to reverse: rename in dirs.sh, tests/test_dirs.py and design 4.3 (nothing else uses them yet).

## [1.2] Empty and relative XDG values; trailing slash
Context: the slice asked for a documented rule.
Chosen: the XDG Base Directory rule: empty counts as unset, a relative value (including ~/x, which a quoted env var never expands) is ignored and the default under $HOME applies; one trailing slash is stripped. No error is raised, so sourcing stays safe under set -eu.
Impact on the design: sentence added to 4.3. How to reverse: edit _sb_xdg_root in dirs.sh and the test_relative_is_ignored test.

## [1.2] Rewiring existing scripts deferred; B29 only fed
Context: the slice says dirs.sh only has to be correct and covered.
Chosen: no existing script sources dirs.sh (Phase 2 does). The v0.1.0 .swarmbox/ layout is untouched; B29 (migration) stays open and unverified.
Impact on the design: none. How to reverse: n/a.

## [1.2] Test scope and limits
Context: bash 3.2 and zsh were not available as separate binaries in a test.
Chosen: tests/test_dirs.py runs sh, dash and bash (the installed bash version, not 3.2); 3.2 compatibility is enforced by a static check (no [[, arrays, local, process substitution) and shellcheck -s sh. zsh was checked by hand with "emulate sh" (it printed the expected path) but is not in the test. unset -f is used to remove the helper function; it works in dash and bash but is not strictly POSIX, so a shell lacking it only keeps one harmless function (the error is ignored).
Impact on the design: none. How to reverse: n/a.

## [1.3] Fake podman is a Python script driven by a JSON script file
Context: the slice needs a recording fake with per-subcommand behavior, safe quoting and atomic concurrent logging; the v0.1.0 stubs were inline sh.
Options: sh stub with env vars (as STUB in test_start_attach.py); Python script reading a JSON script file.
Chosen: Python (sys.executable shebang) because argv with newlines and quotes needs JSON to be unambiguous, and one os.write on an O_APPEND descriptor keeps concurrent records whole. Behavior lives in script.json in the fake's temp dir (reconfigurable between calls). Python startup makes each call a few tens of ms.
Impact on the design: 13.1 helpers.py row now describes FakePodman. How to reverse: replace _FAKE_SCRIPT; the FakePodman API can stay.

## [1.3] Scope: fake host helper not built; PATH keeps the original entries
Context: the plan bullet names a fake podman and a fake host helper; the slice asks only for the fake podman.
Chosen: only FakePodman now; the fake host helper waits for Phase 2 when its interface exists (design and plan say so). PATH is the fake folder first then the original PATH (sh, bash must still resolve), so "real podman unreachable" is enforced by shadowing: the fake never executes anything (checked by a test that greps its source), and assert_no_leak() raises if podman does not resolve to the fake. An absolute /usr/bin/podman call in code under test could not be blocked; none exists in start.sh.
Impact on the design: none. How to reverse: n/a.

## [1.3] First user: start.sh through test_start_fake_podman.py; nothing migrated
Context: exit criteria want one new test against repository code.
Chosen: tests/test_start_fake_podman.py covers create, build-when-image-missing, and start-existing paths of start.sh with --no-shell (3 tests, ~15 s because start.sh waits for the socket). Existing tests keep their inline stubs (migration is for when each is rewritten, per the plan). CONTRIBUTING.md gained both new test files (test_repo_files.py requires it).
Impact on the design: none. How to reverse: delete the file.
