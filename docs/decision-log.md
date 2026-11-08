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

## [1.4] FakeHostHelper design: Python script, unknown command exits 64, no PATH change
Context: the slice asks for a fake swarmbox-host with a test-set version, call recording and per-command routing.
Options: sh script; Python script like FakePodman; modify PATH.
Chosen: a Python script sharing FakePodman's JSON-lines log and script.json scheme, because argument quoting must be exact. PATH is not touched, because the function calls the helper by absolute path ($dir/swarmbox-host). `version` prints the version option (None prints nothing, exit 0) unless commands has its own version entry. A command with no entry and no "*" exits 64 (EX_USAGE), silent, so an unexpected word fails visibly (FakePodman, by contrast, defaults to exit 0). Builder options executable=False and present=False cover the non-executable and missing cases.
Impact on the design: 13.1 helpers.py row and plan Phase 1 bullet updated. The API may change in Phase 3; accepted.
How to reverse: delete FakeHostHelper and its tests.

## [1.4] The bootstrap condition is tested through a labeled sh prototype
Context: the real function does not exist until Phase 2; D33 scenarios are the first consumer of the pair of fakes.
Chosen: a 6-line sh STUB in tests/test_helpers.py copies only the condition from design 3.6 (missing, non-exec, or older by sort -V: podman run ... host-helper; newer: skew notice). It is labeled as a prototype, not product code, and has no extraction, lock or config logic. The cases: missing, non-executable, no version, 1.9.0 re-extract; 2.0.0 kept silently; 2.0.10 vs marker 2.0.9 kept with notice, and 2.0.9 vs 2.0.10 extracted. Runs under the system sh only (dash here); bash 3.2, zsh, fish are Phase 3. The design needed no correction.
Impact on the design: none beyond the 13.1 row. How to reverse: delete the class; Phase 3 supersedes it.

## [1.4] Red run skipped
Context: rules say see tests fail first.
Chosen: honestly, tests and fakes were written in one pass and run green; no separate failing run was recorded (the ImportError was the only possible red). Noted for the owner.
Impact on the design: none. How to reverse: n/a.

## [1.5] Tool choice: gitleaks 8.30.1 plus a supplementary Python scanner
Context: D37 wants a history scan; the network is open, so gitleaks could be downloaded.
Options: gitleaks only; own script only; both.
Chosen: both. gitleaks 8.30.1 (linux x64 release, sha256 checked against the release checksums.txt, run from a mktemp directory and deleted afterwards, never installed). tests/audit_history.py (read-only, tested in tests/test_history_audit.py) adds what gitleaks does not give: identities, hosts, home paths, IPs, e-mails, sensitive file names, a blob pass. It is also the documented fallback if gitleaks is unavailable. The checksum comes from the same release page, so it is not an authenticity proof (recorded as [unverified] in the report).
Impact on the design: none. How to reverse: delete tests/audit_history.py and its test.

## [1.5] Triage: no credential in the history; two false positives
Context: gitleaks reported 2 hits (same line, two commits), the script 1 high-entropy hit.
Chosen: all false positives. The gitleaks hit is a counting-sequence test fixture for a Cloudflare Global API Key shape check; the script hit is the README placeholder for an OAuth token. Nothing is to be rotated. gitleaks scanned 222 of 227 commits because it skips the 5 merge commits; the script's blob pass covers merge content. Values are redacted everywhere (first 4 characters and the length; the report holds no secret-shaped string, and a test enforces it).
Impact on the design: none. How to reverse: n/a.

## [1.5] Recommended Phase 7 action: publish whole for secrets, owner decides on identities, push selected refs only
Context: the history holds 4 identities: the owner (feroult@gmail.com), a second personal address (6 commits), an employer address (fer@ciandt.com, 1 commit on main) and a placeholder (User Name, 43 commits). Branches backup/before-author-rewrite and origin/memory and three refs/original/* refs also exist.
Options: publish whole; rewrite authors with git filter-repo --mailmap; start from a clean history.
Chosen: recommend publishing whole (nothing secret), pushing only main or opensource and the tag v0.1.0 (never --all or --mirror); if the owner does not want the employer address or the placeholder public, Phase 7 rewrites authors on a fresh clone and recreates the tag. I did not decide the identity question for the owner: it is listed for review tomorrow. No history was rewritten, no ref changed, and the repository visibility was not touched (a manual owner action).
Impact on the design: none (D37 and plan Phase 7 already allow either). How to reverse: n/a.

## [1.5] Bug found while testing the scanner
Context: for-each-ref output was first split on the wrong field, so ref names came out as "commit"; the tag-message scan therefore did not run in the first real run.
Chosen: fixed (field 3) and re-ran; the 16 tests pass. The unit tests did not catch it because tag content was also reached through git log, so the report's numbers come from the fixed version only.
Impact on the design: none. How to reverse: n/a.

## [1.6] ci.yml: runner image, Podman guard, pinned versions, browser job split
Context: plan section 3 asks for CI on a runner with Podman 4.3 or newer, browser tests kept out of the push path, a macOS job with a fake Podman, a weekly schedule, read-only permissions.
Options: ubuntu-22.04 plus a Podman install; ubuntu-24.04 (Podman 4.9) with a guard; a container job.
Chosen: ubuntu-24.04 with an explicit guard step that fails if podman is older than 4.3, because it needs no install and fails loudly if the image changes. Actions pinned to the major tag actions/checkout@v4 (not a SHA: SHAs cannot be looked up reliably offline; tags are enough for a repository with contents: read and no secrets; the owner may pin SHAs later). macOS job on macos-14 (arm64, bash 3.2 at /bin/bash). The three browser tests (clipboard_bridge, web_style, tmux_browser_keys) run only on the weekly schedule or workflow_dispatch, in a debian:bookworm job container because chromium on Ubuntu is a snap stub; this container and apt package set (chromium, ttyd from bookworm) are [unverified] on a real runner. The macOS job runs every test file except the browser ones and those needing tmux or GNU tools (test_web_terminal, test_start_attach, test_spikes_common, test_history_audit); tests/test_ci_workflow.py enforces that the Linux job runs exactly the tests/test_*.py on disk minus the scheduled ones, and that macOS runs the rest of the allowed set, so a new test file cannot be forgotten. The macOS subset is a guess: some tests may fail on bash 3.2 or BSD tools on the first run, which is the purpose of the job. Concurrency group per ref with cancel-in-progress; timeouts on every job; workflow_dispatch added.
Impact on the design: 13.4 and Part B B30 text updated; the image build, smoke test, validate, migration test, zsh and fish function tests and arm64 job are left to later phases (stated as a comment in the file).
How to reverse: edit .github/workflows/ci.yml and the constants at the top of tests/test_ci_workflow.py.

## [1.6] B30 reduced: probe prepared, not closed
Context: B30 asks what a real macOS runner provides; that cannot be observed here.
Chosen: record B30 as prepared with the exact probe step ("Probe for B30": /bin/bash --version, command -v podman, python3 --version, sw_vers, sort -V as an extra B19 probe) and keep it [unverified]; no evidence tag. The first real CI run closes it. Whether the owner's CI already ran is not checkable here.
Impact on the design: B30 row and 13.4 note say so. How to reverse: n/a.

## [1.6] Validation method for ci.yml
Context: YAML mistakes cannot be proven without a runner.
Chosen: test_ci_workflow.py parses with PyYAML (not installed system-wide; the test pip-installs it into a venv under the temp dir, fallback to a text-marker class that always runs); actionlint 1.7.12 downloaded to a mktemp dir with its checksum verified, run with shellcheck integration (clean), then deleted; the test runs it only when ACTIONLINT or PATH points at it, otherwise it is skipped, so a plain run reports a skip. Every command was also run locally once.
Impact on the design: none. How to reverse: n/a.

## [1.7] Phase 1 gate status is partial, not done
Context: the plan's Phase 1 exit criteria require CI green on Podman of at least 4.3 and a result for B30. Neither can happen here: the workflow cannot run on a runner and nothing may be pushed.
Options: mark the gate done because all files and local checks exist; mark it partial and list the open items.
Chosen: partial because claiming CI green or closing B30 without a real run would be dishonest (rule: never invent behavior).
Impact on the design: none; B30 stays `[unverified]` as written in slice 1.6.
How to reverse: after the first real CI run, record its result in Part B (B30) with an evidence tag and change the 1.gate row to done.

## [1.7] Home-path guard in the docs consistency test is a heuristic grep
Context: the slice asks for a repo-wide check that no test writes to real home paths.
Options: ban every mention; flag only lines that look like writes (open, write, mkdir) and are not assertions or mktemp use.
Chosen: the second, because mentions as string data (for example the layout fed to the socket-length spike) are legitimate; the one existing mention was reviewed by hand and is data only.
Impact on the design: none.
How to reverse: tighten the regex in PhaseOneCloseTest.test_tests_do_not_touch_real_home in tests/test_docs_consistency.py.

## [1.7] Plan text left unchanged
Context: the plan's Phase 1 exit criteria were checked one by one (see the 1.gate status row). The design and plan cross-references, D1 to D39 and B1 to B36 numbering and code fences were already enforced by test_docs_consistency and pass.
Options: add a Phase 1 outcome section to the plan; keep the outcome only in the status file.
Chosen: status file only because the plan states intent and the status file records results (same split as Phase 0 apart from the design's outcome table, which exists because Part B needed it).
Impact on the design: none.
How to reverse: copy the 1.gate row into a "Phase 1 outcome" paragraph in the plan.

## [2.1] The new Dockerfile takes the root path; the old one is renamed Dockerfile.v0.1.0 and build.sh gets one flag
Context: the design puts the 2.0 image at the root `Dockerfile` (9.1), but `build.sh` runs `podman build .` and so builds whatever the root file is. The task said v0.1.0 `build.sh`, `start.sh` and `lib/` stay, and asked for a decision on how the two Dockerfiles coexist.
Options: (a) new file elsewhere (for example `container/Dockerfile`), root untouched; (b) rename the old file to `Dockerfile.v0.1.0`, put the new one at the root and add `-f Dockerfile.v0.1.0` to the one `podman build` line of `build.sh`; (c) replace the root file and leave `build.sh` to build the slim image under the old name.
Chosen: (b) because it matches the design's tree, keeps `./build.sh` producing exactly the v0.1.0 image (agents included) so the owner's workflow keeps working until Phase 6, and the build.sh change is one line plus a comment. Option (c) would silently give `start.sh` an image without agents.
Impact on the design: 9.1 tree lists `Dockerfile.v0.1.0` and `dev/dev-build.sh`. `tests/test_repo_files.py` (notices) now reads both Dockerfiles; `tests/test_starship.py` reads `Dockerfile.v0.1.0` because its bashrc wiring checks describe the old image (the 2.0 image gets `bashrc.sh` in a later slice). Both old Dockerfile COPY sources (`container/scripts/init.sh`, `container/opencode/`, `container/web/web-terminal.sh`) must stay until Phase 6. `tests/test_dockerfile.py` asserts the `-f` flag in `build.sh`.
How to reverse: `git mv Dockerfile.v0.1.0 Dockerfile` after restoring the old file contents and remove the `-f` flag. Phase 6 deletes `Dockerfile.v0.1.0` together with `build.sh`. The v0.1.0 file is also reachable with `git show v0.1.0:Dockerfile`. Not verified: I did not run `./build.sh` (it would tag the owner's image name `swarmbox`); the `-f` edit was checked by reading and by `tests/test_dockerfile.py`, and `Dockerfile.v0.1.0` is a pure rename (`git mv`), so its content is unchanged [unverified: a real `./build.sh` run].

## [2.1] Dev build script: dev/dev-build.sh, scratch copy with the apt override
Context: apt in a nested build fails with a setgroups error unless `APT::Sandbox::User "root";` is set, which must never be in the product Dockerfile.
Options: a build argument that writes the file; a wrapper that edits the Dockerfile in place and restores it; a wrapper that writes a scratch copy outside the repository and builds from it with the repository as context.
Chosen: the scratch copy, in `mktemp -d`, with the override as a `RUN` right after the first `FROM` (a conf file `/etc/apt/apt.conf.d/99swarmbox-dev-sandbox`). The script refuses any tag not starting with `swarmbox-test-` (plain name only: no registry, no `:tag`), defaults to `swarmbox-test-img-<random>`, removes the scratch directory on exit (`--keep-scratch` and `--dry-run` exist for tests), and only ever calls `podman build`. Location `dev/` is new; POSIX sh.
Impact on the design: 9.1 lists `dev/dev-build.sh`. The first RUN of every scratch build adds a small layer (8.7 kB), so a scratch build differs from a CI build by that one layer and the conf file in the image.
How to reverse: delete `dev/`, `tests/test_dev_build.py` and the CONTRIBUTING lines. CI builds will not need the override.

## [2.1] Placeholder entrypoint so the image builds and runs
Context: the Dockerfile needs `ENTRYPOINT swarmbox-entrypoint` and `CMD ["serve"]` (design 10.2), but the entrypoint and `serve` are later slices of Phase 2.
Options: leave `container/entrypoint.sh` out and make the Dockerfile fail to build; ship a no-op that exits 0 for `serve`; ship a placeholder that fails loudly for the subcommands not written yet and already runs "any other command" as given.
Chosen: the third. `serve`, `attach`, `init`, `pubkey`, `tool`, `host-helper` exit 70 with a message that names the placeholder; no command exits 64; anything else is `exec`ed (this is already the final behavior, design 10.2). A no-op exit 0 would let a later test pass against nothing.
Impact on the design: none. Until the real entrypoint lands, a container started from this image with the default `CMD` exits at once with 70.
How to reverse: the next slice overwrites `container/entrypoint.sh`.

## [2.1] What the 2.1 Dockerfile copies and what it leaves out
Context: slice 2.1 is the image only; the later slices add `swarmbox-tool`, `swarmbox-shim`, the host helper, `swarmbox-web`, `swarmbox-attach`, `swarmbox-init`, `bashrc.sh` and the MCP registry.
Chosen: copy only files that exist and are needed by design 10.1 (dirs.sh, ssh-key.sh as swarmbox-pubkey, banner.sh, messages.sh, podman-service.sh, starship-init.sh, tmux and starship and ssh config, the web assets plus the new build-index.sh, `container/mcp/` as is, `cloudflare-setup.py` NOT yet). Left out until their slices: the `RUN ... swarmbox-tool link --system` wiring, the helper archive (`cloudflare-setup.py`, `tool-ports`), `swarmbox-web`, the `bashrc` fragment (so interactive shells in this image have no banner, aliases or Starship yet), the OpenCode template, the `COPY container/tools/`. `container/mcp/chrome-devtools/config.json` still says `npx -y chrome-devtools-mcp@latest`: switching `command` to the installed program is the registry work of the `serve` slice (design 4.4). `tests/test_dockerfile.py::test_every_copy_source_exists` makes a missing source a test failure, not a build failure.
Impact on the design: none; the image in 2.1 is a stable base for the later slices, not a complete 2.0 image.
How to reverse: n/a.

## [2.1] Pinned versions and package choices
Context: design 10.2 says every version is an ARG with a default.
Chosen: `CHROME_DEVTOOLS_MCP_VERSION=1.12.0` (latest on npm on 2026-11-08, modified 2026-10-22, Apache-2.0, Node `^20.19 || ^22.12 || >=23` which fits Node 24), `UV_VERSION=0.9.5` (v0.1.0 installed uv unpinned: now pinned through the versioned installer URL `astral.sh/uv/<version>/install.sh`; the installer script's own checksum is not verified, and neither does the install check the binary's published sha256 [unverified: the checksum of uv; Phase 7 can add it]), `TTYD_VERSION=1.7.7` and `STARSHIP_VERSION=1.27.0` unchanged with their checksum checks, `NODE_VERSION=24` as a global ARG before FROM. Package lists are v0.1.0's minus the ones only gcloud needed (gnupg, lsb-release, software-properties-common, apt-transport-https) plus tmux; `apt-get install` keeps v0.1.0's flags (recommended packages are installed) because dropping them for Podman or Chromium could break the nested setup and the 2.5 GB budget was met anyway (1.75 GB).
Impact on the design: 10.1 package list matches. `THIRD_PARTY_NOTICES.md` now lists chrome-devtools-mcp (license read with `npm view`).
How to reverse: change the ARG defaults; a Dependabot-style bump is Phase 7.

## [2.1] npm cache: separate build cache instead of npm cache clean
Context: design 10.2 requires `/opt/npm-cache` owned by `agent`. My first build ran `npm install -g ...; npm cache clean --force; install -d -o agent ...`. The image test (npm cache entries not owned by agent) failed: `npm cache clean` left a root-owned `_logs` folder and `_update-notifier-last-checked` in `/opt/npm-cache`, which is the EACCES trap the design describes.
Options: `chown -R` afterwards (rejected by design: duplicates a layer); run the install as agent (cannot write /usr/local/lib); give root's install its own cache and delete it.
Chosen: `npm install -g --cache /tmp/npm-build-cache ... && rm -rf /tmp/npm-build-cache` in one RUN, with `/opt/npm-cache` created empty and owned by agent in its own earlier RUN. Verified: the rebuilt image has no entry in `/opt/npm-cache` that is not owned by agent.
Impact on the design: 10.2 npm cache bullet carries the finding.
How to reverse: n/a.

## [2.1] The size test fails when the budget is exceeded
Context: B27's 2.5 GB is a budget.
Chosen: `tests/test_image_build.py` always prints the size and per-layer history and fails over 2.5 GB, so a regression is visible; today it is 1.75 GB. The image test is skipped unless `SWARMBOX_IMAGE_BUILD=1`; it is listed in ci.yml (linux and macos lists, where it skips) because a test above requires every test file to be listed. The CI job will not build the image yet (plan section 3: the image job is added with the smoke test in a later slice), so the image test has so far only run here, in the development box.
Impact on the design: B24, B26, B27 closed with evidence tags (Part B, "Results of Phase 2"). B24 shows the MCP server answering `tools/list`; it did not open a page in Chromium.
How to reverse: n/a.

## [2.2] Test-only switches (SWARMBOX_TEST_*) kept out of the configuration table
Context: `serve` must be tested in the development box with no `/dev/net/tun`, no nested Podman, a run folder that is not `/tmp/swarmbox`, and a ttyd backoff of 0 s. The slice asks for one switch, `SWARMBOX_TEST_NO_NESTED=1`.
Options: (a) no switches, test only inside real containers (slow, and the nested service cannot run here at all); (b) one switch per need, named `SWARMBOX_TEST_*`, read only by `container/entrypoint.sh`; (c) a general `SWARMBOX_TEST=1` gate.
Chosen: (b). `SWARMBOX_TEST_NO_NESTED` (step 2 becomes a warning instead of a failure, step 8 starts no service and is a warning), `SWARMBOX_TEST_LIB` (where `dirs.sh` is), `SWARMBOX_TEST_RUN_DIR` (replaces `/tmp/swarmbox`), `SWARMBOX_TEST_TUN` (replaces `/dev/net/tun`), `SWARMBOX_TEST_BACKOFF_SCALE` (integer multiplier of the ttyd backoff), `SWARMBOX_TEST_SERVICE_WAIT` (seconds to wait for the nested socket). They are listed only in the header comment of `container/entrypoint.sh` and here; `tests/test_serve_steps.py` checks that design section 8 (the configuration reference) never names them. Never put in `swarmbox config`, the host helper's `create-flags` or the docs for users.
Impact on the design: none visible to users. The risk is that someone sets NO_NESTED on a real box and gets a box with no nested Podman and a warning in the banner; that is the safe failure direction.
How to reverse: delete the variables from `container/entrypoint.sh`; the tests would need a different way to fake the environment (for example a chroot-like layout).

## [2.2] serve calls hook programs for the steps that belong to later slices
Context: steps 4 (layout migration), 6 (`swarmbox-tool link --user`), 7 (MCP file, `prepare.sh`) and 12 (`WITH` installs) need code written later in Phase 2 and Phases 4a, 4b. The slice says those steps call stubs and are no-ops with logging.
Options: ship stub programs (`swarmbox-migrate`, `swarmbox-tool`) in this slice; or make `serve` tolerate their absence.
Chosen: `serve` tolerates absence. A program not on `PATH` makes the step a logged no-op in `serve.log` (the word "skipped"), no health line, not counted in `warnings=`. A program that exists and exits non-zero is a W with one health line per step. Interfaces fixed now so the later slices can match them: `swarmbox-migrate` (no arguments), `swarmbox-tool link --user`, `swarmbox-tool prepare` (prepare.sh of every installed or declared tool; the tool reads `SWARMBOX_WITH` itself) and `swarmbox-tool install <tool>`. The MCP generation of step 7 is a plain logged no-op in `serve` until 4.4. No stub program is shipped: a stub `swarmbox-tool` that exits 0 would hide a missing tool machinery in the smoke test, and the stub list of the plan (empty `tool-ports`, `swarmbox-tool` entry point) is left to the slice that builds the helper archive.
Impact on the design: 4.1 gets a paragraph that names these interfaces. If the later slices choose other names, they change `container/entrypoint.sh` and `tests/test_serve_steps.py` together.
How to reverse: replace the `have <program>` guards with plain calls once the programs exist.

## [2.2] The web terminal interface between serve and swarmbox-web
Context: `swarmbox-web` (container/scripts/swarmbox-web.sh) is not written yet, but the supervisor must start ttyd and `swarmbox-web restart` must reach the supervisor.
Chosen: the supervisor runs `swarmbox-web run` when that command exists (a foreground command that prepares the page and the options and `exec`s ttyd), else `ttyd -W -p 7681 tmux attach -t main` (so the 2.2 box already serves ttyd's stock page). The supervisor's PID is written by serve to `box:/tmp/swarmbox/web-supervisor.pid` and `swarmbox-web restart` sends it `USR1`; `TERM` stops it. Output of ttyd goes to `<state>/web-terminal.log`. Step 10 is a W when neither `swarmbox-web` nor `ttyd` exists.
Impact on the design: 4.1 and 5.1 name the interface. The fallback ttyd command has no `--index`, no theme and no clipboard bridge: it is a placeholder until the `swarmbox-web` slice.
How to reverse: the later slice may rename `run`; change `ttyd_command` in the entrypoint.

## [2.2] serve starts the nested Podman service itself and checks that it answers
Context: v0.1.0 starts the service with `container/scripts/podman-service.sh` (detached with `setsid`, paths under `~/.swarmbox`), which `Dockerfile.v0.1.0` also copies, so it cannot change in this phase. A detached service would also survive `serve`'s signal handler.
Options: call the old script; write a new script; start `podman system service` directly as a child of serve.
Chosen: the child, `env -u CONTAINER_HOST podman system service --time=0 unix://$SB_PODMAN_SOCK` with output in `<state>/podman-service.log`, which serve stops on SIGTERM and SIGINT. After starting it, serve waits up to 10 s for the socket and runs `podman --url unix://<socket> version` (5 s limit). No socket (or the process died) or no answer is one W line. The check happens once, at step 8; the later "does the socket answer" check from the host is the helper's `up` (Phase 3, design 4.2). Tested with a fake `podman` only: the real service cannot run in the development box (reduced).
Impact on the design: 4.1 describes it. `container/scripts/podman-service.sh` stays for the v0.1.0 image and is not copied for 2.0 use by serve (the 2.1 Dockerfile still copies it as `swarmbox-podman-service`; Phase 6 removes it).
How to reverse: n/a.

## [2.2] The marker's warning count, health file clearing and the log
Context: design 4.2 says the marker holds `ok` or `warnings=<n>` and the health file is cleared at every start, but not what is counted nor when the file is cleared, and the health file lives in a folder that does not exist before step 3.
Chosen: `<n>` counts the W failures recorded by serve before step 11 (plus the step 2 warning under the test switch). Health lines written afterwards (ttyd giving up; a failed `WITH` install) are in the file but not in the marker, because the marker is written once. The health file is truncated in step 3, right after the folders exist (so a fatal step 1 or 2 leaves the old file alone); log lines of steps 0 to 2 are held in memory and written to `serve.log` at step 3; `serve.log` is appended to, never truncated (a size cap is not implemented). The supervisor removes only its own line from the health file (a rewrite, `grep -vxF`); a concurrent append by the installer job at that moment could be lost, which I accepted for 2.0 (a lock would be the fix).
Impact on the design: 4.1 states the counting rule.
How to reverse: n/a.

## [2.2] Bug found by the tests: a signal lost between starting a sleep and storing its PID
Context: `tests/test_serve_steps.py::test_sigterm_during_a_crash_loop_backoff` hung in about 1 run of 3: the spike's supervisor (and my first copy of it) killed the PID of the running sleep from the trap, but a SIGTERM that arrives after `sleep N &` and before `sp=$!` finds `sp=0`, so nothing is killed and the supervisor sleeps the whole backoff; serve's `wait` on it then blocks `podman stop` until the kill timeout.
Chosen: one helper `nap` that stores the PID and then checks the stop and restart flags, killing the sleep if either is set. 25 consecutive runs of the whole test file afterwards had no failure. The same race exists for the first `ttyd` start and is handled the same way.
Impact on the design: 4.1 notes it. The spike's prototype had the same race (it did not show because its backoff is 1 s).
How to reverse: n/a.

## [2.2] Tests: fakes on PATH, no real tmux or podman
Context: the hard rules forbid touching the live tmux server; `serve` runs `tmux` and `podman`.
Chosen: `tests/test_serve_steps.py` puts a scratch folder with fake `tmux`, `ttyd`, `podman`, `swarmbox-pubkey`, `swarmbox-tool` and `swarmbox-migrate` first on a minimal `PATH` (`/usr/bin:/bin` after it) and asserts that `tmux` and `podman` resolve to the fakes before every run. The signal tests start `serve` themselves and only signal that PID (own process group) and children recorded in the fakes' pid files. The tests are Linux-only (they use `sleep infinity` and `/proc`), so `tests/test_ci_workflow.py` lists `test_serve_steps.py` and `test_serve_container.py` among the files that are not run on macOS, and `ci.yml` shellchecks `container/entrypoint.sh` as bash (it was in the `sh` list while it was a placeholder).
Impact on the design: none.
How to reverse: n/a.

## [2.2] Container checks are reduced and idle-window check (B36) is not done here
Context: the exit criteria want a reduced container check and say B36's idle window is recorded once 2.3 is done.
Chosen: `tests/test_serve_container.py` (needs `SWARMBOX_IMAGE_BUILD=1`) runs serve in a throwaway `swarmbox-test-serve-<random>` container from the 2.1 image with `SWARMBOX_TEST_NO_NESTED=1`, a mktemp workspace and `--tmpfs /tmp/swarmbox`. Tagged `[reduced: development box, no nested Podman in the box]`; the nested service, step 8 and `/dev/net/tun` are NOT exercised for real. B36 stays open: serve only runs `tmux new-session -d -s main`, so the session has one default window; recognizing and closing it is `attach`'s job.
Impact on the design: Part B has a "Results of Phase 2 (slice 2.2)" table.
How to reverse: n/a.

## [2.3] How the idle window is recognized (B36)
Context: design 3.4 says `attach` closes the idle window when it is the only other one, and left open how to recognize it. A window the user typed into must never be closed.
Options: (a) by name only; (b) a tmux user option set by `serve`; (c) name, one pane, and the pane's current command being a shell; (d) also look at the cursor position or history.
Chosen: (c). `serve` creates the session with `-n idle` (which also stops automatic renaming); `attach` closes it only when it is the only window of `main`, still named `idle`, has one pane and `pane_current_command` is bash, zsh, sh, dash or fish. Option (d) was rejected because the banner and the prompt make cursor and history values unreliable. Known weakness: text typed without Enter, or a command that already finished, is not detected and the window is then closed. A renamed, split or busy window is kept, which is the safe direction.
Impact on the design: 3.4 and 4.1 step 9 say it; B36 is closed with this limit written down.
How to reverse: change `idle_window` in container/scripts/swarmbox-attach.sh and the `-n idle` in the entrypoint together (a test checks that both say `idle`).

## [2.3] A command call does not close the idle window
Context: design 3.3 says `attach` adds a window and closes the idle one when it is the only other. For `swarmbox <command>` the new window ends with the command; with the idle window already gone `main` would have no window, tmux would end the session and the server, and the browser's `tmux attach -t main` would fail until the next attach.
Options: close it for commands too; never close it for commands; close it and recreate `main` afterwards.
Chosen: only the interactive path (no command) closes the idle window. A command leaves it alone, so `swarmbox true` changes nothing in `main`.
Impact on the design: 3.3 states it. Consequence: after `swarmbox claude` (a command) the browser shows `idle` plus the command window; the next interactive attach does not close `idle` while the command window exists, because then it is not the only window.
How to reverse: call `idle_window` and `kill-window` in `run_command` too, and make the end of the call recreate the session.

## [2.3] Test-only variables of swarmbox-attach and how tmux is isolated in the tests
Context: the tests need a short readiness timeout, a short poll interval, a test fragment and a run folder, and they must never address the live tmux server.
Chosen: four test-only variables, deliberately NOT in the configuration table of design 8: SWARMBOX_TEST_READY_TIMEOUT (seconds, default 60), SWARMBOX_TEST_POLL_INTERVAL (seconds, default 1), SWARMBOX_TEST_FRAGMENT (default /etc/swarmbox/bashrc.sh), plus the two of serve (SWARMBOX_TEST_LIB, SWARMBOX_TEST_RUN_DIR). tmux itself needs no switch: the tests put a `tmux` first on PATH, either a recording fake or a shim that does `unset TMUX; exec tmux -L swarmbox-test-<random> -f /dev/null "$@"` with a private TMUX_TMPDIR. Every real-tmux call of the test file goes through `IsoTmux.run` -> `checked_tmux_argv`, which refuses a call without `-L swarmbox-test-<name> -f /dev/null` (it has its own test), and the server is stopped only with that exact -L name. The live server was checked before and after (tmux ls: main and main-1, attached).
Impact on the design: none; 3.3 lists nothing test-only.
How to reverse: n/a.

## [2.3] Terminal means standard input and standard output; no command and no terminal gives a plain shell
Context: design 3.3 decides the path by "standard output is a terminal", but the tmux client needs both a terminal in and out, and the design does not say what `swarmbox` with no command and no terminal does.
Chosen: the tmux paths need `[ -t 0 ] && [ -t 1 ]`; otherwise the direct forms run. No command and no terminal runs a plain `bash` (which reads standard input); with `--plain` and a terminal it is `bash -i`. The host function, which decides about `-t` on `podman exec`, stays the first line of defense.
Impact on the design: 3.3 (bullet "What the 2.3 implementation does").
How to reverse: n/a.

## [2.3] Choices inside the wrapper and the waiter
Context: the spike's wrapper ran `bash -ic` in the foreground and was never tried with typed input; the design asks for a trap and a poll fallback but not for their details.
Chosen: (1) `bash -ic` runs in the background with stdin passed explicitly (`exec 3<&0 ... <&3`), because a shell trap does not run while a foreground child runs and a background job of a non-interactive shell gets /dev/null as stdin; typed input reaching a `read` was tested with real tmux. (2) The poll interval is 1 s by default and the loop wakes every 0.1 s, so the call returns as soon as `wait-for` does. (3) A window that disappeared with no status gets a 1 s grace for a status on its way before exit 1. (4) A grouped client that ended while the window is still listed means the user detached: message and exit 0; the command keeps running and its status file is removed by the caller (the wrapper may still write one later: a few bytes in the tmpfs, gone at the next start, and `serve` deletes `exit.*` at step 0). (5) SIGHUP or SIGTERM to the call ends the client and leaves the window running (129 and 143). (6) `eval --` in the no-terminal form, found by a failing test (a command starting with `-`).
Impact on the design: 3.3 describes each point.
How to reverse: n/a.

## [2.3] Requirement handed to the shell fragment slice: no banner for `bash -c`
Context: the command window runs `bash -ic '<command>'`, an interactive shell, so it reads /etc/bash.bashrc and the future fragment. The banner (design 10.3) would print before the output of every `swarmbox <command>` and could corrupt a piped result.
Chosen: not built here (the fragment does not exist yet); recorded as a requirement: the fragment must return early from banner and prompt setup when `${BASH_EXECUTION_STRING:-}` is not empty, while still defining aliases and PATH. The test fragment in tests/test_attach_command.py defines only aliases and PATH.
Impact on the design: 3.3 repeats it so the fragment slice finds it.
How to reverse: n/a.

## [2.3] Finding, not fixed: a killed host `podman exec -it` leaves the in-box tmux client alive
Context: while writing the container test, closing the test's pty (SIGHUP to the host-side `podman exec -it`) left the tmux client and its grouped session running inside the box; only the detach key (C-a d) ended them cleanly.
Options: add a reaper to `serve`; use a different client lifetime; leave it.
Chosen: left as is and recorded. The mechanism (`podman exec` of tmux) is the same as v0.1.0's, but v0.1.0 was not run to compare, so "same as today" is [unverified]. A stale grouped session costs a few kilobytes and a `main-N` name; the windows are shared, so nothing is lost. The container test leaves its tabs with the detach key.
Impact on the design: 3.3 notes it.
How to reverse: n/a; a reaper (kill grouped sessions with no client activity) could be a later improvement for the owner to decide.

## [2.3] Tests, honesty about the order and reductions
Context: the slice asks for tests first.
Chosen: tests/test_attach_command.py was written before swarmbox-attach.sh; the first full run began before the script was saved, so its output is not a clean "fails for the right reason" record. After the script existed, 5 of 48 tests failed once, all for reasons in the tests or the script found by them (the fake tmux did not accept a window without a wrapper; two quoting tests counted the output file name as an argument; `eval` rejected a command starting with `-`). Afterwards four consecutive full runs passed. The container test is a full result for this part (level 2) with the nested Podman service off by the test switch; the terminal is a pty made by the test, not a host terminal or ttyd, and the shell fragment is a test file.
Impact on the design: Part B tags carry "reduced: pty as terminal, test fragment".
How to reverse: n/a.

## [2.4] Fragment test-only variables and the paths the design fixes
Context: the design fixes the paths (/usr/local/lib/swarmbox/tools, .../shims, /usr/local/bin/banner.sh, /etc/swarmbox/scripts/starship-init.sh, /opt/flow), but the tests need fixtures in mktemp and the live box has a real /opt/flow.
Options: hard-code the paths and test only in containers; or accept overrides.
Chosen: overrides with the design's path as default: SWARMBOX_DIRS_SH, SWARMBOX_IMAGE_TOOLS_DIR, SWARMBOX_IMAGE_SHIMS_DIR, SWARMBOX_BANNER_SCRIPT, SWARMBOX_STARSHIP_INIT, SWARMBOX_VENV. They are listed in the fragment's header, not in the settings table of design 8.2 (like the 2.2 and 2.3 test variables).
Impact on the design: 6.6 describes the fragment; the variables are not user settings.
How to reverse: delete the `${VAR:-default}` forms; the unit tests would then need a container.

## [2.4] Manifest format assumed by the fragment
Context: the tool slice (4a) does not exist; 6.3 gives the format of tool.conf.
Chosen: tool.conf at <config>/tools/<name>/ (user) and /usr/local/lib/swarmbox/tools/<name>/ (image), the name is the directory name, the file is sourced in a subshell and only KIND, PROVIDES, YOLO_FLAGS, YOLO_ALIAS and MCP_FLAGS are read. A manifest that fails to load, or one with a syntax error, is skipped silently. Alias = first word of PROVIDES (the name if empty). Flags are split on blanks, so a flag value with a space is unsupported. `swarmbox-tool` (Phase 4a) must keep these keys; a later parser can replace the scan without changing the fragment's behavior.
Impact on the design: 6.6 states it.
How to reverse: n/a.

## [2.4] yolo default: a third fallback, and yolo ignores SWARMBOX_YOLO=0
Context: 6.6 says the default is SWARMBOX_AGENT, else the first agent of SWARMBOX_WITH; it does not say what happens with neither, nor what SWARMBOX_YOLO=0 does to `yolo`. v0.1.0's yolo was claude.
Options: fail with a message; or take the first agent manifest.
Chosen: the first agent manifest by name (with the image manifests this gives claude, as v0.1.0), and "no agent installed" (exit 1) only when no agent manifest exists. `yolo` keeps working with SWARMBOX_YOLO=0, because the variable is documented as disabling the aliases and typing `yolo` is explicit. A SWARMBOX_AGENT with no manifest also fails with a message, exit 1.
Impact on the design: 6.6 gains the fallback and the last sentence.
How to reverse: remove the fallback line in `yolo`, or make it return 1 when SWARMBOX_YOLO=0.

## [2.4] No alias or yolo flag for "installed": every manifest counts
Context: 6.6 says "installed or declared agent". The image-level manifests exist for agents that are not installed yet, and their shim installs them on first use.
Chosen: aliases and yolo follow the manifests (image or user level), not the presence of the program. The command found through the alias is the shim, which installs the tool, so the alias is right either way.
Impact on the design: none.
How to reverse: check for the program (or `current`) before defining the alias.

## [2.4] The banner shows every health line; the SSH fingerprint line is not built
Context: 4.2 says the banner shows the startup-health lines and the stale-image line; 10.3 also says the shell prints the one-line SSH fingerprint.
Chosen: the banner prints each non-empty line of the health file (control characters dropped, so a line cannot repaint the terminal) after the art; the stale-image and fingerprint lines are shown if something writes them there (Phase 3's helper). The SSH fingerprint line is left out: it needs `swarmbox-pubkey --ensure` in every shell, which creates a key, and `serve` already ensures it (step 5). Recorded as not done in the status row.
Impact on the design: 6.6 says so in "Not done here".
How to reverse: call `swarmbox-pubkey --ensure` in the banner block.

## [2.4] Banner skipped for `bash -c`, and the hermetic interactive test
Context: the 2.3 requirement: the command window runs `bash -ic`, which must not print the banner.
Chosen: the banner and Starship are guarded by `BASH_EXECUTION_STRING` empty and SWARMBOX_CMD unset; aliases and PATH apply anyway. Found while writing the tests: `bash --rcfile X -i` still sources Debian's /etc/bash.bashrc (on the live box that ran the old init and created a key under the test's HOME), so the interactive tests use `bash --noprofile --norc -i` with the fragment sourced from standard input. The stray test directory it made was in /tmp and was removed.
Impact on the design: none.
How to reverse: n/a.

## [2.4] clasp's shell.sh and the SSH fingerprint stay for later; Starship moves into the fragment
Context: the image's bashrc used to source starship-init.sh last; 6.6 moves the clasp function to container/tools/clasp/shell.sh (Phase 4).
Chosen: the fragment sources starship-init.sh itself, last, so the order is kept and the Dockerfile has one line instead of echoes. tests/test_starship.py now reads the 2.0 Dockerfile and the fragment (the order test became a text-order check of the fragment). The clasp function is not in the 2.0 image (clasp is not installed there) and has no shell.sh yet. The fragment is not tested under bash 3.2 and is excluded from the macOS job (it runs only in the Debian image).
Impact on the design: none.
How to reverse: n/a.

## [2.5] The "three-value substitution" is padding, ctrlVPaste and ctrlCCopy; font, theme, size and scrollback are ttyd options
Context: the slice text speaks of rendering "font size, theme, scrollback or the three-value set in 5.1" into the page. Design 5.1 is explicit: the page has three placeholders (the padding and the switches `ctrlVPaste` and `ctrlCCopy`), while font, theme and size are NOT in the HTML but travel as ttyd `-t key=value` options. build-index.sh (slice 2.1) already builds exactly those three placeholders.
Options: (a) follow 5.1 and test both paths separately; (b) put font, size and theme into the page as placeholders too.
Chosen: (a). `swarmbox-web` substitutes the three placeholders with sed and turns every other key of `web-terminal.conf` into a `-t` option (so a `scrollback=5000` line reaches ttyd with no code change). The tests assert both: the page for the three values, the ttyd argument list for the rest.
Impact on the design: none; 5.1 gets a paragraph that says what 2.5 does.
How to reverse: n/a (the alternative would change build-index.sh and its test).

## [2.5] swarmbox-web: interface, validation, and what ttyd runs
Context: 4.1 fixed the interface for the slice (`swarmbox-web run`, `restart` through USR1 to `/tmp/swarmbox/web-supervisor.pid`). It left open: validation of the three values, which command ttyd runs, the listening address, and a `render` mode.
Chosen: (1) padding must be 0 to 99 digits, otherwise 10 with a message on stderr (the v0.1.0 rule); only the word `false` turns a switch off. The values are validated before they reach sed, so no escaping is needed and a value cannot inject into the page (tested). (2) A page with a missing placeholder is refused (exit 1): a stale page would otherwise ignore the user's settings silently. (3) ttyd runs `swarmbox-attach` when it exists (so the browser is one more window of the shared session, 3.4), else `tmux attach -t main` (the 2.2 stand-in). v0.1.0's `tmux new -A -s main` is not used, because it would bypass the grouped session. (4) ttyd listens on every interface inside the box, port 7681 (the published port is what limits exposure to the host's 127.0.0.1, as 5.1 says); the test-only variables SWARMBOX_TEST_WEB_PORT and SWARMBOX_TEST_WEB_IFACE (not in the table of design 8) replace the port and add `-i`. (5) `swarmbox-web render` renders without starting ttyd (used by the browser tests). (6) `restart` refuses a missing, non-numeric, stale or pid-1-or-lower PID file; it cannot verify that the PID is really the supervisor (the supervisor is a subshell of `serve` and has the same command line), which is [unverified] hardening left out.
Impact on the design: 5.1 describes the 2.5 implementation.
How to reverse: change the command line at the end of container/scripts/swarmbox-web.sh.

## [2.5] swarmbox-tool is a stub with a working `link --system`, and `link --user` and `prepare` succeed
Context: the slice asks for a stub with `validate` as a placeholder and an exit message pointing to Phase 4a. `serve` (2.2) calls `swarmbox-tool link --user` (step 6) and `prepare` (step 7) whenever the program exists, and treats a failure as a warning in the readiness marker.
Options: every subcommand but `validate` exits 70; or the three that `serve` calls succeed as no-ops.
Chosen: the second: `validate`, `link --user` and `prepare` exit 0 with a one-line message naming the stub; `link --system` writes the empty `tool-ports` (the Dockerfile runs it at build, as 10.2's wiring does, so the file always exists); `install`, `run`, anything else exits 70 with a message that names Phase 4a. Effect worth knowing: with a non-empty `WITH`, step 12 now runs `swarmbox-tool install <tool>`, gets 70, and writes the health line "installing <tool> failed" at every start. That is honest (nothing is installed), and goes away in Phase 4a.
Impact on the design: none (the plan already says "stubs").
How to reverse: make the three subcommands exit 70; `serve` then counts two warnings.

## [2.5] The helper archive holds only cloudflare-setup.py and tool-ports until Phase 3
Context: 3.7.1 and 9.3 list `swarmbox-host`, `cloudflare-setup.py`, `templates/` and `tool-ports`. `container/host/` (the helper and the templates) is Phase 3 work and does not exist.
Chosen: the Dockerfile copies `cloudflare-setup.py` into `/usr/local/share/swarmbox/host/` and `swarmbox-tool link --system` writes `tool-ports`; `host-helper` tars whatever that folder holds (`tar --owner=0 --group=0 --numeric-owner -C <dir> -cf - .`, only the archive on stdout). It does not check for `swarmbox-host`: the function checks that after unpacking (3.7.1, exit 3). The test-only variable SWARMBOX_TEST_HOST_DIR replaces the folder.
Impact on the design: 9.3 notes that the archive is partial until Phase 3.
How to reverse: n/a.

## [2.5] Entrypoint subcommands forward by exec; a missing program is 127; `init` has no program yet
Context: 10.2 lists the subcommands. The 2.1 placeholder exited 70 for four of them.
Chosen: `attach`, `init`, `pubkey` and `tool` replace the process (`exec`) with `swarmbox-attach`, `swarmbox-init`, `swarmbox-pubkey` and `swarmbox-tool`, with every argument unchanged (empty strings, spaces and globs tested) and the program's exit status and signals as the entrypoint's own. A missing program is exit 127 and a message that names it (one rule for all four). `swarmbox-init` is a Phase 3 program, so `init` gives 127 "swarmbox-init not found" for now (a stricter reading of the slice would not have built anything for it). `host-helper` with extra arguments is 64, a missing folder is 1. Any other command is `exec "$@"` unchanged (already so since 2.1); a command that does not exist is 127 from bash.
Impact on the design: none.
How to reverse: n/a.

## [2.5] swarmbox-pubkey --ensure is used as it is
Context: the slice says "SSH key from container/scripts/ssh-key.sh as serve step 5". The script already has `--ensure`, is already installed as swarmbox-pubkey (2.1) and serve step 5 (2.2) already calls it.
Chosen: no change to the script; tests/test_pubkey_ensure.py states the 2.0 contract (created once, idempotent, never overwritten, only under the test HOME, short output with no private material, entrypoint path) next to the older tests/test_ssh_key.py, which stays. The real container check shows the key made by serve and no SSH health line.
Impact on the design: none. The banner's one-line fingerprint remains unbuilt (decision [2.4]).
How to reverse: n/a.

## [2.5] Test files in CI lists; browser tests rerun on the new page
Context: tests/test_ci_workflow.py requires every test file to be in ci.yml (Linux job) and, unless listed, in the macOS job; CONTRIBUTING.md must describe every file.
Chosen: the five new files run in the Linux job and are listed as not-for-macOS (GNU tar flags, fake programs, containers); the two new shell programs are shellchecked there. test_web_build.py subclasses the existing browser test classes (clipboard bridge and style) so the same 16 browser tests run against the page that build-index.sh built and swarmbox-web rendered; they skip without chromium, ttyd and tmux, as before. The v0.1.0 tests test_web_terminal.py, test_web_style.py and test_clipboard_bridge.py are unchanged (v0.1.0's web-terminal.sh stays until Phase 6), which is why "adapt" was done by subclassing instead of editing them.
Impact on the design: none.
How to reverse: n/a.

## [2.5] ttyd rewrites its own argv; the container test reads `-t key value`
Context: found by the container test: `/proc/<pid>/cmdline` of the running ttyd shows `-t fontSize 19`, not `-t fontSize=19` (ttyd splits the option at the "=" in place).
Chosen: the test matches the rewritten form and says why. Not a product problem.
Impact on the design: none.
How to reverse: n/a.

## [2.6] The migration is a separate program, `swarmbox-migrate`, with the interface fixed in [2.2]
Context: slice 2.2 made `serve` step 4 call `swarmbox-migrate` (no arguments) and fixed its exit rule (non-zero is one health line).
Chosen: `container/scripts/swarmbox-migrate.sh`, bash, installed as `/usr/local/bin/swarmbox-migrate` (Dockerfile COPY and chmod 755). It sources `dirs.sh` (test-only `SWARMBOX_TEST_LIB`, as the other scripts). The step 4 code in `serve` only changed its "not installed" log text. The 2.2 style failure test already existed (a fake program); 2.6 adds the same test with the real script.
Impact on the design: 12.4 describes the behavior; 4.1 notes the program exists.
How to reverse: remove the Dockerfile lines; `serve` goes back to a logged no-op.

## [2.6] Conflict rules the table in 12.4 did not settle
Context: the table says "never overwrites an existing destination" but not what happens to the source then, nor what to do with links and look-alike files.
Options: delete the source anyway (loses data); keep the source and say so; stop with an error.
Chosen: keep the source, print one line, exit 0 (a conflict is not a failure, `.swarmbox/` simply stays). Details: a real `.claude/settings.json` with identical content lets the old copy go (otherwise `.swarmbox/` could never disappear); a link pointing elsewhere is left; a dangling link into `.swarmbox/` is removed (otherwise Claude Code writes through it back into the old folder). "web-terminal.conf (and any copies)": only the exact name is moved; files with other names are unknown to the table, so they are listed and left. Deleted classes are the exact names plus `*.log` and `*.lock`; I derived these from v0.1.0 (`init.sh`, `podman-service.sh`, `web-terminal.sh`).
Impact on the design: 12.4 now states these rules.
How to reverse: change the case branches in swarmbox-migrate.sh; the tests name each rule.

## [2.6] `memory/` is mentioned at every start, not once in the life of the workspace
Context: "serve mentions it once". A "once ever" rule needs a state file, which the migration otherwise does not have, and the second run must be a no-op.
Chosen: one line per run while `memory/` exists (it goes to serve.log, not to the health file and not to the banner). So "once" means once per start, never twice in one run.
Impact on the design: 12.4 says so. How to reverse: add a marker file under the state folder and skip the line when it exists.

## [2.6] The fixture is built from v0.1.0 code and may be incomplete; no real workspace was touched
Context: B29 asks for a run on a copy of a real v0.1.0 workspace; this build must not touch the owner's workspace.
Chosen: the fixture lists the files written by the v0.1.0 scripts (settings.json and its link, web-terminal.conf, .lock and .log files, podman.sock, ttyd-index.html, opencode-local.json) plus `memory/`, whose producer (the removed memory service) is not in v0.1.0's tree, so its content is a placeholder. podman.sock is a plain file in most tests and a real Unix socket in one. B29 is closed with the tag "fixture, not a real v0.1.0 workspace"; the owner runs it on a copy in Phase 6.
Impact on the design: Part B row and 12.4 say so. How to reverse: n/a.

## [2.7] The smoke test is one script with steps, not a unittest class; two modes and an opt-in
Context: the plan asks for the layer 2 smoke test with a reduced run in the development box and a full run in CI. The other container tests are unittest classes that skip unless `SWARMBOX_IMAGE_BUILD=1`.
Options: another unittest file; a standalone script with its own step list and report.
Chosen: standalone `tests/smoke_image.py` (not named `test_*.py`, so the CI test-set equality checks stay as they are) with a `Step` list, a `run_steps` runner and one output line per step (`STEP <id> PASS|FAIL|SKIP ...`). A step that needs the third nesting level is reported SKIP in the reduced run, never PASS. Reduced results carry the tag `[reduced: development box, no nested Podman in the box]`; full results carry `[full]`. Without `SWARMBOX_IMAGE_BUILD=1` or `SWARMBOX_SMOKE_FULL=1` nothing runs and every step is SKIP (exit 0). A failed step does not stop later steps; exit 1 if any failed. `tests/test_smoke_skeleton.py` checks the structure without a container.
Impact on the design: 13.3 layer 2 names the file and the two modes.
How to reverse: wrap the step functions in a unittest class.

## [2.7] Steps beyond the five named by the plan, and what was left out
Context: the plan lists readiness, tmpfs emptied on restart, page built, `swarmbox-tool validate`, nested Podman. Its exit criteria also name attach and the neutral image, and B28 needs a nested step.
Chosen: eight steps: ready, tmpfs-restart (includes `podman stop` time and exit 143, B3), page-built, tool-validate, attach-session (two windows of one session, the idle window gone, exit codes), no-agent (D2), and the two full-only steps nested-podman and nested-cgroup (B28: the image's engine settings must read cgroupfs and file; the result of the systemd manager is printed for the record and does not fail the run). Left out for Phase 3, because they need the host helper that does not exist yet: `up` waiting for the new marker, `up` exit 6 and 7, `reset`, the held-back `serve`, attach's 60 s not-ready exit (13.3 layer 2 text keeps them as the target). The nested container image is `docker.io/library/debian:bookworm-slim`, pulled in CI [unverified, never run].
Impact on the design: 13.3 says which host-side checks arrive with Phase 3.
How to reverse: edit the STEPS list.

## [2.7] The throwaway box in the smoke test uses a random high port inside its own network namespace
Context: the box's ttyd listens on 7681, and 7681 is the port of the live web terminal in the development box's network namespace. The box under test has its own namespace, so it would not collide, but a test file that names 7681 is one typo away from a collision.
Chosen: like the 2.5 tests, the smoke test passes the test-only variables SWARMBOX_TEST_WEB_PORT (random 20000 to 40000) and SWARMBOX_TEST_WEB_IFACE=lo, so ttyd is on the container's loopback; nothing is published; a static test forbids 7681, 8889 and 43323 in the file. The real default port 7681 and the real bind interface are therefore not exercised by this test (they are covered only by the swarmbox-web tests with a fake ttyd). In full mode the same switches are used.
Impact on the design: none; the switches are test-only (see 5.1 and decision [2.5]).
How to reverse: drop the two `-e` flags and use 7681 in the box's own namespace.

## [2.7] The CI `smoke` job
Context: the plan wants the smoke job in ci.yml, not run here.
Chosen: job `smoke` on ubuntu-24.04: `podman build` of the real Dockerfile (tag swarmbox-test-img-ci), the full smoke test (the job fails if any step was skipped), the container tests on the same image (they keep their reduced switch inside), image removed by exact name with `if: always()`. The `test_smoke_skeleton.py` test runs in the `linux` and `macos` jobs (it starts no container). The job runs on push and pull request. Actionlint was not available in this run (see the 1.6 row), so the YAML was checked by `tests/test_ci_workflow.py` only. Risks never observed: the ubuntu runner's rootless Podman may need `--device /dev/net/tun` permissions or a different `unmask` behavior; the first CI run decides, and the failure would be recorded as the B28 result.
Impact on the design: 13.4 describes the job.
How to reverse: delete the job and the two list entries.

## [2.gate] Phase 2 is partial, M1 is reached as reduced only
Context: the exit criterion "the smoke test passes in CI" cannot be met here (no repository push, no third nesting level).
Chosen: the gate row is `partial`; every other exit criterion is met in the reduced form (see the status file). B28 is recorded as open and `[unverified]`; B3, B17, B13, B36 are rechecked with the reduced tag. Nothing in the design was contradicted by the smoke test.
Impact on the design: Part B results table of slice 2.7; plan Phase 2 paragraph.
How to reverse: when the first CI run passes the full smoke test, change the 2.gate row to done and close B28 with its tag.

## [4a.1] Test-only environment overrides for the image and user manifest levels
Context: `swarmbox-tool` reads the image level from `/usr/local/lib/swarmbox/tools` and the user level from `$SB_CONFIG_DIR/tools`; tests need fixture folders, and the dev box must not read its own real configuration.
Options: (a) a command-line flag for every level; (b) test-only environment variables in the style of SWARMBOX_TEST_HOST_DIR; (c) always derive everything from HOME and XDG variables.
Chosen: (b). SWARMBOX_TEST_IMAGE_TOOLS (image level), SWARMBOX_TEST_USER_TOOLS (user level; empty counts as unset, so the real path through dirs.sh and XDG can also be tested) and the existing SWARMBOX_TEST_LIB (folder with dirs.sh; the script also falls back to the dirs.sh next to it, so a source checkout works). Not in the configuration table of design 8. In addition `validate DIR` takes a folder argument as a product feature, because CI must check `container/tools` in the repository.
Impact on the design: 6.9 describes `validate [DIR]`; the variables are listed in the header of the script only.
How to reverse: delete the three lines that read the variables and run the tests under HOME and XDG instead.

## [4a.1] Manifests are loaded by sourcing them in a subshell; the install.sh lint is only a lint
Context: design 6.3 says `tool.conf` is a shell-sourceable file. Sourcing executes whatever the file contains.
Options: (a) source in a subshell; (b) write a restricted KEY=VALUE parser in bash; (c) python3 (not in the image).
Chosen: (a), as the design says, with three guards: only the image and user levels are ever read (D18, there is an absence test that runs with the working directory inside a fake project and checks that a manifest there is never sourced); the subshell runs with cwd in the manifest folder, stdout and stdin discarded, and the known keys unset first so that the environment cannot supply a missing field; a manifest that calls `exit` or does not parse counts as not sourced. The user level is the user's own workspace, so the trust boundary is the same as for any shell startup file the user owns. A restricted parser (b) would be safer but would change the manifest format the design settled (`MCP_FLAGS="--mcp-config $HOME/..."` relies on expansion). The `install.sh` lint (apt, sudo, writes outside the prefix) is explicitly documented as a lint: it skips full-line comments, does not understand quoting or variables, and a hostile script passes it. The real protection for user-level tools is that the user wrote them.
Impact on the design: 6.9 now says so (4a.1 state).
How to reverse: replace `load_manifest` with a parser; the tests only use the file format.

## [4a.1] Extra validate rules and the shape of the claude installer
Context: the slice list names the rules of 6.9; a few gaps would make the loader unsafe or confusing.
Chosen: also enforced: NAME equals the folder name and matches `^[a-z0-9][a-z0-9_-]*$`; PROVIDES entries match a plain command-name pattern (no slash); UPDATE is managed or self; SHA256 values are 64 hex digits; both SHA256_amd64 and SHA256_arm64 or neither. Folders whose name starts with a dot are not scanned (shell glob). `container/tools/claude/install.sh` downloads the vendor script into a variable first (so a failed download stops before anything runs) and then pipes it to `bash -s` with no argument for `latest` or the version as the one argument, instead of the design's literal `curl | bash -s`; the behavior is the same, the failure handling is stricter. It writes a small record `$TOOL_PREFIX/installed` (requested and reported version, arch), which the design's 6.7 describes as "SwarmBox's record of the install". The test runs the installer against a fake `curl`; the real vendor installer was not run in this slice (first-call install under `--prefix` and the B1 re-check belong to the shim slice) [unverified: that the vendor script accepts `-s` with no argument and with a version through `bash -s`; B1 recorded the version form only].
Also: the smoke test step `tool-validate` and test_web_container now expect the real validate output ("manifest(s) checked") instead of the word "placeholder"; the image still has no tool manifests until the Dockerfile copies `container/tools` (a later 4a slice), so there it reports 0 manifests. test_tool_manifest.py is excluded from the macOS job like test_tool_stub.py: the tool uses bash 4 features (associative arrays, namerefs) and runs in the box's bash 5.
Impact on the design: 6.9 (4a.1 state).
How to reverse: remove the rule lines in `check_manifest`.


## [4a.2] Index format, where the files live, and the test-only shim folders
Context: design 6.2 gives the paths (`/usr/local/lib/swarmbox/shims`, `.../index`; user level `.../shims/`, `.../index`) and says "command tool" per line, but not the order, the separator, or what an empty level looks like.
Options: (a) unsorted, in manifest order; (b) sorted by command; the index as a sibling file of the shim folder; (c) index inside the shim folder.
Chosen: (b). One line `<command> <tool>` separated by a single space, sorted bytewise (`LC_ALL=C`) so that the output does not depend on glob order or locale and a rerun is byte-identical; the file always exists, empty when there is nothing. The index is `dirname(shims)/index`, matching the layout in 6.2 (a file inside the shim folder would be on `PATH` and look like a command). Test-only variables SWARMBOX_TEST_IMAGE_SHIMS and SWARMBOX_TEST_USER_SHIMS (index = sibling `index`), in the style of [4a.1]; user level without the override comes from dirs.sh and honors XDG.
Impact on the design: 6.2 (4a.2 state).
How to reverse: change the `sort` and the `index=` line in `link_level`.

## [4a.2] Stale-shim removal and conflict handling
Context: `link` must be idempotent, follow manifest removal, and never harm things it did not make; the shim folder at image level is root's, at user level the user's.
Options: (a) wipe and recreate the folder; (b) remove only what link generated; (c) never remove.
Chosen: (b), with a precise definition of "generated": a symlink whose target is exactly `/usr/local/bin/swarmbox-shim` and whose name does not start with a dot (dot names are the temporary links of a concurrent `link`). Wiping (a) would give a reader a moment with no shim, which is the race named in the slice. A command name occupied by a regular file or a link elsewhere is reported on stderr and skipped (exit 0, no index line), because refusing to link everything over one stray file would break the box start (serve step 6 is a W failure at most). A same-level duplicate command exits 1, writes nothing at that level and keeps the previous good state (decided before any write). A manifest that does not source, has a bad SCHEMA, or a PROVIDES entry that is not a plain name (so no `../x`, which would write outside the folder) is skipped with a warning; `validate` reports them as failures. Removing a manifest also removes its shims at the next link; a user manifest that breaks therefore loses its shims until fixed.
Impact on the design: 6.2 and 6.3 (conflicts) 4a.2 state.
How to reverse: remove the stale loop at the end of `link_level` to keep old shims.

## [4a.2] Atomicity and write order of link
Context: serve step 6 and an interactive attach may run `link --user` at the same time.
Chosen: new links are created as `.link.<pid>.<cmd>` and renamed over with `mv -T` (atomic, so a correct existing link is never missing; links already correct are not touched at all, so inode and mtime stay), the index and tool-ports through `<file>.tmp.<pid>` and `mv -f`, stale links removed last. `tool-ports` is written first, before the shims, so a failure there stops with exit 1 before anything else changes. Two concurrent runs produce the same bytes, so the last rename wins harmlessly. Not tested with a real race, only by construction and idempotence tests [unverified under real concurrency]. The user level is entirely in the workspace; the image level is made by root at build and read-only for the agent, so no ownership problem arises (a user-level shim folder created by the agent user is agent-owned).
Impact on the design: 6.2 (4a.2 state).
How to reverse: n/a.

## [4a.2] Test updates and what was not run
Context: link now creates folders, so tests that call `link` need the shim folder overrides.
Chosen: tests/test_tool_stub.py and tests/test_tool_manifest.py pass the two new override variables; the stub test for `link --user` now expects an empty user level under HOME instead of "writes nothing". test_tool_link.py is added to the CI list and to the macOS exclusions (bash 4 features, like the other tool tests). The container tests (test_web_container, test_serve_container, smoke) skip without a built image and were not run; the image still does not copy `container/tools` (a later 4a slice), so the real image tree here is only tested through a copy of `container/tools` in a temp folder (claude is linked, tool-ports empty).
Impact on the design: none.
How to reverse: n/a.

## [4a.3] Where the lock lives and how tests move it
Context: design 6.5 says "take the lock" and the slice names /tmp/swarmbox/tools.lock; tests must not touch the real /tmp/swarmbox.
Options: (a) lock the tool folder itself; (b) one global lock file in /tmp/swarmbox; (c) a lock per tool.
Chosen: (b), path /tmp/swarmbox/tools.lock (the tmpfs run dir of dirs.sh), test-only override SWARMBOX_TEST_LOCK, with flock on descriptor 9, a non-blocking try first (then "another install is running, waiting for it..."), then a wait of 900 s (test-only override SWARMBOX_TEST_LOCK_WAIT). One global lock because installs are rare and a second install of another tool waiting is harmless; per-tool locks would need a lock directory. The lock is outside the workspace on purpose: a reset starts with no stale lock. The installer child gets the descriptor closed (9>&-) and `run` closes it before exec, so a daemon started by an installer or the tool cannot hold the lock (tested with a leftover background sleep). flock is util-linux, an Essential package of Debian, so it is in the node:24-slim based image; I did not add it to the Dockerfile list. [unverified in the built image: not rebuilt in this slice; present on this box.]
Impact on the design: 6.5 (4a.3 state).
How to reverse: change LOCK_FILE; for per-tool locks, derive the file name from the tool.

## [4a.3] Architecture mapping and override
Context: TOOL_ARCH must be amd64 or arm64 from `uname -m`.
Chosen: x86_64 and amd64 give amd64; aarch64 and arm64 give arm64 (macOS hosts report arm64); anything else is refused before the installer runs with a message that names the value. Override for tests: SWARMBOX_TEST_ARCH (the mapping itself is tested with a fake `uname` first on PATH, without the override).
Impact on the design: 6.4 (4a.3 state).
How to reverse: edit tool_arch.

## [4a.3] TOOL_SHA256: how an installer gets the manifest checksum
Context: 6.4 says an installer verifies the manifest's SHA256_<arch>, and 6.4's contract table lists only TOOL_PREFIX, TOOL_VERSION, TOOL_ARCH, so an installer had no way to read it.
Options: (a) the installer sources tool.conf itself; (b) swarmbox-tool passes it.
Chosen: (b), a fourth variable TOOL_SHA256 = SHA256_<TOOL_ARCH> when declared, unset otherwise (an inherited TOOL_SHA256 is removed, so an installer cannot be fooled by the caller's environment). swarmbox-tool does not verify anything itself: the installer does, and when it exits non-zero swarmbox-tool removes the whole prefix. Tested with a fixture archive and sha256sum -c, both a mismatch (tree byte-identical afterwards) and a match; claude declares no checksum.
Impact on the design: 6.4 table row added.
How to reverse: drop the export in run_installer and the row.

## [4a.3] Layout, in-place install and what "complete" and "installed" mean
Context: 6.7 gives tools/<name>/<version>/ plus current for managed and tools/<name>/self/ for UPDATE=self; 6.11 gives the fingerprint file `.swarmbox-env`.
Options for managed: (a) install into a staging folder and rename it to <version>; (b) install in place into <version>/ and delete it on failure.
Chosen: (b). npm and gcloud installs may write absolute prefix paths into scripts, which a rename would break. The price is that a crash (kill -9 of swarmbox-tool) can leave a version directory without `.swarmbox-env`; that is treated as incomplete and redone on the next call, and `current` is never moved before the marker and every PROVIDES command exist, so there is never a half-installed current link. For UPDATE=self the prefix is only a record, so a staging folder (tools/<name>/.staging.<pid>) is used and renamed to self/ after success; a failed reinstall therefore keeps the previous record. Where the self record lives: tools/<name>/self/ under the dirs.sh tools dir (the workspace, survives reset). Installed for UPDATE=self: record present AND command resolvable at $HOME/.local/bin/<command> AND not the shim (risk named in the slice); a stale record with a deleted binary, or a binary with no record, reinstalls (tested both ways). For managed: current -> a complete version directory. The vendor's files in ~/.local are outside swarmbox-tool's undo: on a failed self install only SwarmBox's own tree is restored (the fake installer in the test leaves partial files in ~/.local on purpose; they are the installer's).
Failure cleanup also removes the empty folders the call itself created (tools/, tools/<name>/), so the tree is byte-identical, not just free of links.
Impact on the design: 6.5 and 6.7 (4a.3 state).
How to reverse: n/a.

## [4a.3] Exit codes of a failed install, and `latest` for managed tools
Context: `run` passes the tool's own exit status through exec, so an install failure with exit 1 could be mistaken for the tool's.
Chosen: install failure (and a refused or missing real command) exits 69 (EX_UNAVAILABLE) from both `run` and `install`; usage errors 64 (as elsewhere); later-phase commands 70 (as the slice says). `latest` for a MANAGED tool has no resolver yet (no network call is made by swarmbox-tool, and design 6.7 does not say how to resolve): the literal name `latest` is used as the version directory and passed as TOOL_VERSION; real resolution (opencode is the first managed agent, Phase 4b) is left open [unverified]. For UPDATE=self, `latest` is passed to the installer as is, which is what the claude installer expects.
Impact on the design: 6.5 (4a.3 state).
How to reverse: change the exit numbers in cmd_install and cmd_run.

## [4a.3] Surface of `list`, `update`, `--force`, and what is not done
Context: the slice asks for a coherent surface: list and update for UPDATE=self, the rest "later phase" with exit 70.
Chosen: `list` prints a header and one sorted row per tool (user level wins over the image of the same name): name, kind, update, level, state. `update` for UPDATE=self resolves the first word of UPDATE_CMD to the real program when the tool provides it (so it does not go through the shim), runs it with stdout to stderr and passes its exit code; not installed gives exit 1 "not installed"; a managed tool gives 70. `install --force` is implemented (it is in 6.11) because it is a few lines: it removes and reinstalls the version directory (or record). `use`, `remove`, `doctor`, `new` exit 70 with "later phase". The environment fingerprint is written (ARCH, NODE_MAJOR from `node -v` or empty, LIBC, VERSION) but nothing reads it yet (the check at `link --user` is a later phase). The swarmbox-shim dispatcher and shipping container/tools in the image are not part of this slice. Not run: the real claude installer against claude.ai (B1 is already verified by the Phase 0 spike); the claude installer is exercised here only through a fake curl and the real manifest.
Impact on the design: 6.5, 6.7 (4a.3 state).
How to reverse: n/a.

## [4a.4] The shim is POSIX sh, not bash
Context: the slice risk says "use bash"; the test list says "dash for #!/bin/sh variant if chosen".
Options: (a) #!/bin/bash; (b) #!/bin/sh with POSIX-only code.
Chosen: (b). The shim is the only SwarmBox script on a per-command path for tools that are not yet installed or are UPDATE=self (the shim stays reachable); dash starts in about a third of the time of bash, and the logic needs no bash feature (one read loop, one exec). It still runs under bash and busybox sh, and the tests run it under each (shebang shell, dash, bash, busybox sh). Costs nothing else: swarmbox-tool stays bash.
Impact on the design: 6.5 (4a.4 state).
How to reverse: change the shebang and the CI shellcheck dialect; the code is already valid bash.

## [4a.4] Index lookup, loop guard and test-only variables
Context: the design says "looks up in an index"; the guard needed a mechanism; the tests need to move the paths.
Chosen: user index located through dirs.sh (so XDG is honored, D10); image index at /usr/local/lib/swarmbox/index. Exact-name first match per file, user file first. Loop guard has two layers: swarmbox-tool's existing refusal (now also recognizing the repository name swarmbox-shim.sh, a small change to real_command in swarmbox-tool.sh so tests that link to the repository file see the same refusal as the image) and a depth counter SWARMBOX_SHIM_DEPTH (limit 16, exit 70). A flag "already inside the shim for this command" was rejected because it breaks legitimate nesting (an agent that starts agent). Test-only variables: SWARMBOX_TEST_TOOL (manager path), plus the existing SWARMBOX_TEST_USER_SHIMS, SWARMBOX_TEST_IMAGE_SHIMS and SWARMBOX_TEST_LIB; none is in design 8.
Impact on the design: 6.5 (4a.4 state).
How to reverse: n/a.

## [4a.4] Registration, image and what was not run
Context: the shim must be in the image for the links to stop dangling.
Chosen: Dockerfile copies it to /usr/local/bin/swarmbox-shim (chmod 755, before `link --system`); ci.yml runs test_tool_shim.py and shellchecks the shim with -s sh; test_ci_workflow.py lists the test in the non-macOS set; CONTRIBUTING.md has a row. Not run: an image build (the Dockerfile change is a one-line COPY plus chmod, checked by a text test), zsh as the interpreter (the shim runs by shebang, and the zsh case of B12 is about `$0`, already verified), a real Claude Code download (B1 was closed by Phase 0).
Impact on the design: none.
How to reverse: n/a.

## [4a.3] Test registration
Context: new test file and a changed stub test.
Chosen: tests/test_tool_install.py is in ci.yml and in the macOS exclusions of test_ci_workflow.py (bash 4 features, like the other tool tests) and described in CONTRIBUTING.md; test_tool_stub.py now checks the later-phase commands (use, remove, doctor, new) instead of install/run/update/list.
Impact on the design: none.
How to reverse: n/a.

## [4a.5] The image ships the claude manifest and puts the image shims on PATH
Context: the Dockerfile already copied swarmbox-tool and swarmbox-shim and ran `link --system`, but not `container/tools/`, so the image had 0 manifests, no shim, an empty index. The design 10.2 snippet also lists `ENV PATH=/usr/local/lib/swarmbox/shims:$PATH`, which the slice text does not mention.
Options: (a) only copy the manifests; (b) also set the ENV PATH as the design says; (c) rely on bashrc.sh alone.
Chosen: (b). `COPY container/tools/`, `chmod -R a+rX` on the tree and `chmod 755` on every `*.sh` in it (the installer must be executable whatever the checkout's modes are), all in the RUN that ends with `link --system`. ENV PATH so that non-shell processes (tmux commands, `podman exec`, `swarmbox-entrypoint <command>`) find the shim too; bashrc.sh still puts the user shims first. curl and flock were already in the image (checked in the built image), so nothing was added to the package list.
Impact on the design: 6.2 (4a.5 state), 10.2 (snippet now shows the chmod and find). Image size delta against the 2.1 build: +343,292 bytes (1,751,732,768 against 1,751,389,476); with the ENV line 1,751,735,020.
How to reverse: remove the COPY, the ENV line and the added chmod/find; the tests in test_dockerfile.py (ToolMachinery) name each one.

## [4a.5] serve step 7 leaves an empty mcp-servers.json when there is none (not in the design)
Context: with the claude manifest in the image, the generated alias is `claude --dangerously-skip-permissions --mcp-config $HOME/.claude/mcp-servers.json`. In a real throwaway box (first call really installed Claude Code 2.1.319) `claude` died with `Error: Invalid MCP configuration: MCP config file not found`, because the MCP registry that writes the file (4.4) is Phase 4b. So the alias, the design's own default, was unusable on a fresh workspace.
Options: (a) leave it and document; (b) drop MCP_FLAGS from the claude manifest until 4b; (c) step 7 writes `{"mcpServers": {}}` only when the file does not exist.
Chosen: (c), because it keeps the manifest as designed, never overwrites a user's or the future registry's file, and is a few lines in the entrypoint. Verified in a real box that `claude ... --mcp-config <empty file> -p hi` passes the MCP check and stops at `Not logged in`. Test: test_serve_steps (written when missing, kept when present).
Impact on the design: 6.2 (4a.5 state) says it; 4.4 stays as written (the registry will write the real file at every start, replacing this one).
How to reverse: delete the block under "step 7" in container/entrypoint.sh and its test; or take (b).

## [4a.5] Container tests that assumed an image without tools or with the stub were changed
Context: three existing checks broke for the right reason. test_web_container ran `tool install claude` expecting the stub's exit 70, which would now start a real download; test_bashrc_container expected no claude alias and ran `yolo` (default agent is the first manifest, claude, so it would install it: it did, once, in a throwaway box, before I saw it); test_image_build and the smoke `no-agent` step ran `command -v claude`, which now finds the shim.
Chosen: `tool list` (shows claude "not installed") and `tool use` (still 70) replace the install; the bashrc test checks the real claude alias and runs yolo only with SWARMBOX_AGENT set to a fake or unknown agent; the no-agent checks accept exactly the shim path for claude, require `readlink` to be swarmbox-shim, and require no `claude` or `.claude` file outside /usr/local/lib/swarmbox and no ~/.local. No default test performs a real install.
Impact on the design: none.
How to reverse: n/a.

## [4a.5] Smoke steps, B1 evidence, and what was not run
Context: the slice asks for validate (real), shim-exists and index-contains-claude checks.
Chosen: smoke_image.py has `tool-validate` (also fails on "0 manifest"), `tool-shim` (readlink, executable, `command -v claude` after sourcing bashrc.sh, no tools/claude directory) and `tool-index-ports` (index has the line `claude claude`, tool-ports exists and is 0 bytes); all reduced-capable. Reduced run on swarmbox-test-4a5-img: 8 passed, 0 failed, 2 skipped (the two nested steps). The real first-call install ran once by hand in a throwaway box (swarmbox-test-4a5-real, removed): 2.1.319, about 13 s, second call instant. Not run: the full smoke mode, the CI job (never ran), zsh/fish, arm64. No new test file was added, so ci.yml and test_ci_workflow.py needed no change. One serve-steps test failed once during development and passed in every later run (12 repeats of it alone, 4 full runs); I could not reproduce it and have no explanation, the same kind of unexplained flake as the SIGINT one in 2.7.
Impact on the design: 6.2 (4a.5 state) carries the evidence.
How to reverse: n/a.

## [4a.6] The vendor installer creates ~/.claude and ~/.claude.json: the design said "never"
Context: the slice test "~/.claude.json is not created by the install itself" failed in the real run. Running the vendor script alone (curl | bash, no claude call before) in a fresh volume already leaves `~/.claude/` and `~/.claude.json` (installMethod native, ids, `autoUpdates: false`, `autoUpdatesProtectedForNative: true`, no login data). The Phase 0 spike had recorded the file but 6.7 still said the login paths were never touched.
Options: (a) delete the files after the install (would break `claude update`'s method detection, and fights the vendor); (b) keep the test and mark it expected-fail; (c) correct the design and the test: install.sh does not write them, the vendor does.
Chosen: (c), because the files are the tool's own state in the workspace and harmless. The test now asserts they exist, say native and hold no token.
Impact on the design: 6.7 consequences text and a new "4a.6 state" bullet; B1 evidence line; install.sh header comment.
How to reverse: n/a (a measurement).
Note: `autoUpdates: false` sits next to 6.7's statement that the background update stays on. I did not observe a background update either way [unverified]; `swarmbox-tool update claude` is the sure path.

## [4a.6] The real test lives in the default test list but skips itself; it was run once by hand
Context: "optional slow test file, excluded from default CI", while test_ci_workflow requires every tests/test_*.py to be listed in ci.yml (and in NOT_ON_MACOS or the macOS list).
Chosen: listed in the Linux unit step and in NOT_ON_MACOS; the real classes skip unless SWARMBOX_TEST_NETWORK=1, SWARMBOX_IMAGE_BUILD=1 and podman work (CI sets only the second, so they skip there). The three fake-curl tests (version passed as one argument only when not latest; failed download runs nothing and leaves no record) always run. Alternative of a separate exclusion list rejected as more machinery.
Impact on the design: none. How to reverse: remove the two list entries.

## [4a.6] Results of the real run and what was not measured
Context/Chosen: image swarmbox-test-4a6-img built with dev/dev-build.sh (about 8 min), tests run with SWARMBOX_IMAGE_TAG; 14 tests OK in about 36 s (Claude Code 2.1.319, real download). Snapshot of /usr /etc /opt /var /root: only /opt/npm-cache differs (none observed in this run's filter either way). Offline run (--network=none) fails with exit non-zero and no leftovers; online run afterwards on the same volume installs. Not measured: a second update that finds a newer version (only the Phase 0 spike), disk size of the install in this image, arm64, the same through a nested Podman box.
Impact on the design: 6.7 4a.6 state. How to reverse: n/a.

## [4a.7] swarmbox-tool validate is a CI step of the linux job; wording of the leftover stub messages
Context: the CI header said the real `swarmbox-tool validate` would come in a later phase; `swarmbox-tool.sh` still said "prepare: stub" and "this is a placeholder, tools arrive in Phase 4a" although 4a is done.
Options: leave the messages (harmless); reword them; remove `prepare` (it belongs to 4b).
Chosen: add one step `container/scripts/swarmbox-tool.sh validate container/tools` to the linux job (no container, no network) and reword both messages: `prepare` says it has nothing to prepare until the tools that ship a `prepare.sh` arrive in Phase 4b (still exit 0, `serve` step 7 depends on it); an unknown command says "unknown command" (still exit 70, the existing tests keep passing). `prepare` itself stays as a no-op.
Impact on the design: none (6.2 already describes the 4a state).
How to reverse: remove the CI step; restore the two echo lines from the previous commit.

## [4a.7] A flake in test_serve_steps fixed in the test, not hidden
Context: in the first full regression `WarnSteps.test_steps_are_logged_noops_when_programs_are_missing` failed once (step 12 line not in the log) and then passed in 4 reruns. Cause: step 12 logs after the readiness marker and the test stopped `serve` right after the marker, so SIGTERM could arrive first. This is a test race, not a product bug (the step runs in the background by design). It is not the earlier unexplained SIGINT flake of 2.7, which did not show in this run.
Options: leave it and report; wait for the line in the test.
Chosen: the test waits (up to 10 s) for the `step 12 ... skipped` line before stopping `serve`.
Impact on the design: none.
How to reverse: revert the `wait_for` line in tests/test_serve_steps.py.

## [4a.7] Docs gate checks and the D18 test in the shim tests
Context: the slice asked for meta tests of the consistency of design, plan, status and CI.
Chosen: `PhaseFourACloseTest` in tests/test_docs_consistency.py (no stub or placeholder wording in the Dockerfile, entrypoint, tool and shim scripts; in the design and plan any line about a `swarmbox-tool` stub must name 4a; the 4a test files are listed in the plan, exist and run in CI; D18 tests exist in the manifest, link and shim tests; status rows and gate; decision-log entries for 4a.1 to 4a.7; Appendix A rows D2, D3, D18, D21, B1) and `test_tools_validate_is_a_ci_step_without_a_container` in tests/test_ci_workflow.py. The shim tests had no D18 test (only the manifest and link tests did), so `test_a_project_level_tools_folder_is_not_consulted_by_the_shim` was added (a tools folder in the working directory adds no command and changes none). The plan now lists the 4a test files and a 4a.7 paragraph, and Phase 3 states what it relies on from 4a (a fixture `tool-ports` for `create-flags` tests); the B1 row of A.3 notes the 4a.6 re-verification.
Impact on the design: none; plan wording only.
How to reverse: delete the new test class and the plan paragraphs.

## [4a.7] Gate reading: 4a.gate is partial
Context: the exit criteria ask for the first `claude` call to install and run in a throwaway box, with `validate` passing.
Chosen: partial, because what stays unproven is the same as in Phases 1 and 2: CI has never run (the new `validate` step, the full smoke test B28, the fake-installer tests on the runner). Locally: the fake installer lifecycle (test_tool_shim), the real installer in a throwaway container (test_tool_claude_real with SWARMBOX_TEST_NETWORK=1, 14 tests OK on a fresh image swarmbox-test-4a7-img, removed by name) and `validate` on container/tools (exit 0) all pass. B1 stays closed (evidence in 6.7 and Part B, re-verified in 4a.6). Not run: a third nesting level (the full smoke test).
Impact on the design: none.
How to reverse: set the row to done after the owner reads the first CI run.

## [3.1] Where the helper lives, and how its version is found (VERSION file next to the helper)
Context: the slice says `version` is taken from a VERSION file next to the helper; the repository had no container/host/ yet and the Dockerfile still copies only cloudflare-setup.py into the helper archive folder.
Options: (a) container/host/swarmbox-host with container/host/VERSION beside it, both going to box:/usr/local/share/swarmbox/host/; (b) a version constant inside the script; (c) version passed by the function.
Chosen: (a), as design 9.1 and 9.3 already place the helper in container/host/. VERSION holds one line `X.Y.Z` (2.0.0 for now, the first public version, 10.4); a release would write it from the tag (Phase 7). The helper reads it from the folder of `$0`; a missing or malformed file exits 3 for every command that needs paths (a corrupted archive, 3.7.1). The Dockerfile COPY of container/host/ and the host-helper archive test are left to a later slice of Phase 3 (nothing in this slice builds an image).
Impact on the design: 3.7.1 archive table gets a VERSION row; 9.3 lists it; the "2.5 state" paragraph says what 3.1 wrote.
How to reverse: delete container/host/VERSION and read the version from a constant in the script.

## [3.1] Helper shape: one script, helpers prefixed with underscore variables, umask 077 for the whole process
Context: POSIX sh has no `local`, so functions share one variable namespace.
Chosen: one file, functions take arguments and return values in a few globals (P_KEY, P_VAL, V_OUT, R_VAL, R_SRC) or by printing; temporary variables start with an underscore. `umask 077` is set once at the top, so every file and folder the helper creates is private (the config folder is 700); later slices that need a different mode must set it themselves. `LC_ALL=C` is set so that character ranges in `case` patterns mean ASCII. A `die` inside a command substitution only ends the substitution, so the VERSION is read once with `|| exit 3` outside it.
Impact on the design: none. How to reverse: n/a.

## [3.1] Exit code 70 for subcommands that are not built yet
Context: the table of 3.7.2 lists create-flags, fingerprint, url, up, update, reset, stop and remote, which later slices implement; the table has no code for "not implemented".
Options: exit 2 (usage); exit 64 as the fake helper does for an unknown word; exit 70 (EX_SOFTWARE), the code swarmbox-tool uses for its unbuilt subcommands.
Chosen: 70 with the message "'<cmd>' is not implemented in this build of the host helper." because 2 would say the user made a mistake, and 70 matches 4a. Temporary: each later slice removes its word from the list.
Impact on the design: 3.7.2 "3.1 state" paragraph. How to reverse: change the code in the final `case`.

## [3.1] config list, config get and the empty value
Context: the table says `config list` prints KEY=VALUE with the source as a third tab-separated field and `config get` exits 1 when a key is unset and has no default; it does not say how keys without a default appear in `list`, what an empty environment value does, or whether `get` shows the token.
Chosen: `list` prints every key of 8.2 that has a host-config name, plus NAME first, in the table order (16 lines); a key with no default prints `KEY=<TAB>default`; the token prints `set` or `unset` and its source. An empty `SWARMBOX_<KEY>` counts as unset (the same idiom as the file, where an empty value means the default). `get` prints the token (the Cloudflare script will need it and `get` is the contract's resolved value) only from the environment or from a mode-600 file; it is the one place a secret is printed on purpose, on request. AGENT has no default in the helper (the box picks the first agent of WITH); IMAGE's default is `ghcr.io/<org>/swarmbox:<VERSION>` with the placeholder `<org>` (D32).
Impact on the design: 3.7.2 "3.1 state". How to reverse: change resolve() and cmd_config_list().

## [3.1] Validation rules per key (the "grammar rule" in the messages)
Context: 3.7.3 asks `config set` to refuse invalid values naming the rule but defines no per-key grammar.
Chosen: WORKSPACE absolute after `~/` and relative expansion, no ':'; HOSTNAME letters, digits, '.' and '-' starting with a letter or digit, at most 63; TZ `local`, `off` or a zone name (letters, digits, `_+-/`, no `//`, no `..`, starts with a letter); INIT auto|0|1; HOST_ACCESS, WEB, YOLO 0|1; PORTS a comma list of PORT, HOST:CONTAINER or ADDRESS:HOST:CONTAINER with ports 1 to 65535 (what v0.1.0's `--ports` accepted, minus the ADDRESS check beyond digits and dots); BROWSER_URL a port, HOST:PORT or an http(s) URL; WEB_PORT 1 to 65535; WITH a comma list and AGENT one name of lower-case letters, digits, `_` and `-` (the tool manifests are not consulted yet); ENV_KEYS a comma list of variable names, not SWARMBOX_CLOUDFLARE_*; IMAGE letters, digits and `._/:@-`; token letters, digits and `+/=_.-`. An empty value is always valid and means the default. Leading and trailing blanks are trimmed at set, as they are at read. Values from the environment are not validated by the helper (the use sites will).
Impact on the design: none beyond the 3.1 paragraph. How to reverse: edit validate_value().

## [3.1] The tunnel token: terminal only, chmod failure refuses every write, reserved box name `config`
Context: 3.7.3 says the token is read from the terminal without echo and the write is refused if chmod fails.
Options for a hidden read under dash: `read -s` (not POSIX, absent in dash); `stty -echo` with a trap that restores; reading /dev/tty.
Chosen: `stty -g` to save the terminal, `stty -echo`, `read -r`, restore, and a trap on INT, TERM and HUP that restores and exits 1; standard input must be a terminal, so a piped token is refused with exit 2 (a script that needs it can use SWARMBOX_CLOUDFLARE_TUNNEL_TOKEN). The same chmod rule applies to every key: the write happens in a temporary file in the config folder, chmod 600 is run on it, and only then does `mv` replace the config; if chmod fails nothing is written and the exit is 1. The cost is that a symlinked config file is replaced by a regular file. A box named `config` is refused because <config>/config is the default box's file and a folder of that name could not exist beside it. A CRLF line ending counts as a trailing blank.
Impact on the design: 3.7.3 and the 3.1 paragraph of 3.7.2. How to reverse: use /dev/tty for the read, or write in place with `>`.

## [3.1] Notices go to standard error; seed announces the recorded workspace
Context: 3.7.2 says `config seed` prints nothing on stdout, while 3.7.5 says the helper prints the absolute path it recorded and the once-per-key notice.
Chosen: both on standard error (messages are not data). `config seed` also creates the config file when no seed value is given, so that a later call counts as "the file exists". The comparison for the notice uses the value in the file, or the default if the file has no line, and ignores the environment.
Impact on the design: 3.7.2 "3.1 state". How to reverse: print to stdout instead.

## [3.1] B22, B23 and B34: Linux parts closed-reduced, evidence in Part B
Context: the Linux checks ran here; macOS, bash 3.2 and a WSL home are not available.
Chosen: Part B rows B22, B23 and B34 start with "Linux part checked in 3.1" and a new results table has the evidence tags with `reduced:` notes. `stat -f %Lp` is simulated by a shim that answers like BSD stat. bash started under the name `sh` stands in for macOS /bin/sh only as POSIX mode, not as version 3.2. zsh in `sh` emulation also passes; it is in the matrix as an extra, not a requirement.
New tests are in the macOS job of ci.yml too (the first macOS run will show whether they hold there; the BSD-stat branches of the test shims are untested [unverified]).
Impact on the design: 3.7.1, 3.7.3 and Part B. How to reverse: remove the tags and put `[unverified]` back.

## [3.1] What failed or was left
Context/Chosen: I wrote the helper before the tests in this session, then moved it away to show the tests fail (62 errors and 3 failures in test_host_config.py, 1 test passing vacuously; the shell matrix test file 9 failures and 1 error). Not done here: arm64 and macOS runs, the Dockerfile copy of container/host/, bash 3.2 itself, a test of two helper calls writing the config at the same moment (the helper does not lock; the later `up` lock covers `up` only, so two parallel `config set` calls can lose one write [unverified, not tested]).
Impact on the design: none. How to reverse: n/a.

## [3.2] The order of the flags, and a flag with its value on two lines
Context: 3.6 and 8.3 list the flags but not an order, and "one argument per line" does not say whether `-p 127.0.0.1:1:1` is one line or two.
Options: (a) `--flag=value` everywhere; (b) the flag and its value on two lines, `=` only for flags written that way today (`--userns=...`, `--pids-limit=...`, `--tz=...`, `--init`); (c) one line `-p 127.0.0.1:1:1` (needs word splitting on the reading side, which 3.6 forbids).
Chosen: (b), because Podman accepts both and the read loop of 3.6 then needs no parsing. The order is fixed by the golden files (`tests/fixtures/create-flags.default.golden`, `create-flags.full.golden`): namespace and limits, hostname, workspace mount, `--init`, `--tz`, tmpfs, tun device, unmask, nested volume, `--add-host`, the `-p` flags (user, tool, web), `-e NAME` for the listed variables, the `-e SWARMBOX_*` flags, the six labels. The listed variables come before the `SWARMBOX_*` ones, so when Podman sees a name twice the last one (ours) wins.
Impact on the design: 3.7.2 "3.2 state" lists the order. How to reverse: edit cmd_create_flags and regenerate the golden files.

## [3.2] How `-e NAME` is passed, and which keys the box gets as SWARMBOX_*
Context: 7.1 says `-e NAME` without a value; 8.1 says the non-secret creation keys the box reads are passed as `-e SWARMBOX_<KEY>=value` but only the table's "passed" marks tell which.
Chosen: `-e` on one line and the bare name on the next, only for names that are set in the terminal of the helper (an unset name passes nothing and gives the warning of 7.1 on standard error). The value is never in the output (a canary test checks create-flags, fingerprint and `--explain`, stdout and stderr). Passed as SWARMBOX_*: `WEB` and `YOLO` always (their defaults are 1, so the box need not know them), `WITH`, `AGENT` and `BROWSER_URL` when not empty, plus `SWARMBOX_NAME` (not in the table: `swarmbox-attach` already reads it for its messages, and a second box would otherwise print the wrong name). `SWARMBOX_WEB_PORT`, `HOSTNAME`, `TZ`, `INIT`, `PORTS`, `HOST_ACCESS`, `IMAGE`, `WORKSPACE` are host-only and not passed.
Impact on the design: 3.7.2 "3.2 state". The box side still reads the old `BROWSER_URL` in `container/scripts/init.sh` (v0.1.0 leftover, 4b rewrites it with the MCP registry): until then `SWARMBOX_BROWSER_URL` is passed and not read. How to reverse: change the emit lines.

## [3.2] Tests-only switches in the helper: SWARMBOX_TEST_OS, SWARMBOX_TEST_PROC_VERSION, SWARMBOX_LOCALTIME_FILE
Context: the slice needs a macOS branch and a WSL probe that tests can drive, and the machine this runs on is itself WSL2.
Chosen: `SWARMBOX_TEST_OS` (value `Darwin` turns the macOS extras on; default `uname -s`), `SWARMBOX_TEST_PROC_VERSION` (a file read instead of `/proc/version`), and `SWARMBOX_LOCALTIME_FILE` (the name `start.sh` already uses for the local time file). They are ordinary environment variables read in production code, as 3.1's other overrides are; setting one by hand only changes what the helper believes about the host. A missing or unreadable probe file means "not WSL".
Impact on the design: 3.6 names the macOS switch. How to reverse: remove the three reads.

## [3.2] macOS: `label=disable` only, the keep-id line stays 1000/1000
Context: 3.6 said macOS adds `--security-opt label=disable` and "an explicit `keep-id:uid=<host>,gid=<host>`". With the fixed image user (uid 1000) the right line is already `keep-id:uid=1000,gid=1000`; `<host>` would map the host user to a different container user and break the fixed home.
Chosen: only `label=disable` is added; the sentence in 3.6 is corrected. Nothing about macOS was run here ([unverified], Phase 6).
Impact on the design: 3.6. How to reverse: add the second flag behind the same switch.

## [3.2] Fingerprint: which keys, how INIT and TZ are taken, and the per-key explanation
Context: 3.7.4 says "every creation-time key of 8.2" and D30 wants one line per differing key, but only four labels (image, workspace, ports, env-hash) carry a value; the fingerprint label is a hash.
Options: (a) add one label per key (more than the six labels of 3.7.4); (b) keep six labels, name the differences that have a label, and one generic line for the rest; (c) store the whole input in a label.
Chosen: (b), because the slice fixes the six labels. `--explain` names image, workspace, `PORTS` and the variables in the wording of 3.5, 3.7.4, 3.8 and 7.1, and says "another creation setting changed (the fingerprint differs); run `swarmbox reset` to apply" otherwise. This is weaker than "one line per differing key" for HOSTNAME, TZ, WITH and so on. Keys in the hash: NAME, WORKSPACE, HOSTNAME, TZ, INIT, PORTS, HOST_ACCESS, BROWSER_URL, WEB, WEB_PORT, WITH, AGENT, YOLO, ENV_KEYS (names), IMAGE. TZ is the resolved value, so `local` without a local time file equals `off`. INIT is the configured value (`auto` stays `auto`), because resolving it needs a throwaway container and the entry path may not start one (B35): `up` has to feed the value the box was created with (the inspect output has it). The workspace is the absolute path and the fingerprint never creates it. The ports line is the normalized list (a user entry `3000` becomes `127.0.0.1:3000:3000`), so the D30 example in 3.7.4 changed to that form. Empty values are written `KEY=`. SHA-256 comes from `sha256sum`, else `shasum -a 256`, else exit 3.
Impact on the design: 3.7.2 and 3.7.4. How to reverse: add labels per key.

## [3.2] fingerprint's interface until `up` exists: --label NAME=VALUE
Context: 3.7.2 says `fingerprint` compares with the box's labels and exits 5 when there is no box; reading them needs Podman, which is `up`'s slice.
Chosen: the labels are given as `--label NAME=VALUE` (or `--label=NAME=VALUE`), repeated. No labels: print the hash, exit 0; `--explain` then exits 5 "no box". Labels without `swarmbox.fingerprint`: exit 5. The later `up` calls the same functions after one `podman container inspect`.
Impact on the design: 3.7.2 "3.2 state". How to reverse: n/a, extend with a Podman read.

## [3.2] `--browser-url` and the "empty argument means 9222" parity
Context: the slice asks for the remote-browser parity where an empty argument means 9222, but 2.0 has no `--remote-browser` flag and an empty `BROWSER_URL` in the config means "none".
Chosen: `create-flags --browser-url VALUE` overrides the key for one call, and an empty VALUE means `http://host.containers.internal:9222`. Nothing in the function calls it; it exists so the parity table is testable. Bare number N is `http://host.containers.internal:N`, `host:port` gets `http://`, `http(s)://` is kept, anything else is exit 2 (the grammar of `config set`).
Impact on the design: 3.7.2 "3.2 state". How to reverse: delete the option and its tests.

## [3.2] Ports: a stricter address rule, the 0.0.0.0 warning, and which host ports count as duplicates
Context: 3.1 accepted any digits and dots as an address (`1.2.3`, `999.1.1.1`); 6.3 says a tool port is skipped when `PORTS` "already lists an entry starting with that number".
Chosen: the address must be four decimal numbers from 0 to 255 (also for `config set`); the warning ("port 0.0.0.0:80:80 is exposed on all network interfaces") is printed by `create-flags` only, not by `fingerprint`. A tool port is skipped when any user entry already publishes the same host port, whatever its address (so `0.0.0.0:43323:80` also stops the tool's `127.0.0.1:43323:43323`, which Podman would refuse as a clash anyway), which is a slightly wider rule than "starting with that number". Duplicate user entries are not removed. `[::]` forms stay refused by the grammar of 3.1.
Impact on the design: 3.7.2 "3.2 state". How to reverse: loosen valid_ipv4; narrow the duplicate test.

## [3.2] Workspace checks: made absolute, created with umask 022, WSL by three looks
Context: 3.5 asks for creation with one message, a not-writable exit 4 and the D34 refusal; "relative workspace refused or made absolute" was left to this slice.
Chosen: a relative or `~/` workspace is made absolute (against the current directory of the helper call), as `config set` already does; the folder (and its parents) is created with umask 022 (the helper's own umask is 077, which would make the home unreadable to other tools) and `swarmbox: created the workspace folder X` is printed once; a path that is a file, cannot be created or is not writable and searchable gives exit 4 with its own message. WSL is decided by `/proc/version` containing `microsoft` (any case), and then the path is refused if the written path, any symlink target on the way (`readlink` without options), or `pwd -P` of an existing folder is `/mnt/<one letter>` or below it. The `mnt` letter match includes upper case (Windows drive letters are case-insensitive). The refusal comes before any creation, so nothing is made under `/mnt`. The macOS "folder not shared with the Podman machine" check needs a throwaway container and is left to `up`.
Impact on the design: 3.5 WSL row. How to reverse: edit check_workspace.

## [3.2] TZ spellings of v0.1.0 kept, and a missing local time file only warns
Context: `start.sh` took `off`, `OFF`, `none` and `NONE` as "no zone"; the grammar of 3.1 accepts `OFF` as a zone name.
Chosen: `off`, `OFF`, `none` and `NONE` mean off (parity, D8); `local` without `/etc/localtime` gives no `--tz` and one warning (v0.1.0 was silent), and counts as `off` in the fingerprint.
Impact on the design: none beyond 3.7.2 "3.2 state". How to reverse: drop the case.

## [3.2] A guard on the output, and what the tests could and could not show
Context: D7 says `--network=host` can never be emitted.
Chosen: no code path builds such a line (every user value is validated and sits behind its own flag), and, as a last look, `guard_flags` stops with exit 70 and prints nothing if any line starts with `--network`, `--net=`, `--privileged`, `--pid=`, `--ipc=`, `--uts=`, `--cap-add` or `--userns=host`. The loop test runs 120 random combinations of ten keys (seeded) and every value of the hostile-value test; the guard itself is only reached by reading the source, not by a test input (no input can trigger it, which is the point) [unverified by execution]. Failed first: the new test file was run against the 3.1 helper (create-flags and fingerprint exit 70) and all 100 tests failed or errored for that reason before the code was written. Not done: macOS and bash 3.2 runs, a real WSL run, a host UID other than 1000, `up` reading the labels, the `shasum -a 256` branch on a real Mac (here it is a shim around the real `shasum` with `sha256sum` hidden).
Impact on the design: none. How to reverse: n/a.

## [3.3] The fast path makes two Podman calls; the version and tun checks run only when a box is created or started
Context: 3.8 lists the prerequisite checks for `up`; 3.7.2 gives the fast path a budget of at most two Podman calls (B35). `podman version` is a call.
Options: (a) check the version on every entry (3 calls with the image comparison); (b) check only on the create and start paths; (c) cache the result in the state folder.
Chosen: (b). A box that exists was made when the version and the tun device were fine, so the checks add nothing on entry; the two calls of the fast path are the inspect and one `podman image inspect` for the stale-image warning. (c) adds state that can go stale.
Impact on the design: 3.7.2 "3.3 state". How to reverse: call check_podman_version and check_tun before the lookup in up_main (and give up one call of the budget).

## [3.3] The format of the lookup, and what "no box" means
Context: the design asks for one `container inspect --format` that gives state, name and labels, with an exact-name comparison; it does not fix the format.
Chosen: `state|name|image ID|HostConfig.Init|managed|image|ports|env-hash|fingerprint|workspace`, pipe separated, the workspace last because a path may contain `|`. Labels are read with `index .Config.Labels "..."`, which gives an empty string for a missing label (also for v0.1.0 containers, which have none). Not a JSON dump: parsing it in POSIX sh is fragile. "No box" is a failed call whose message contains `no such container` (Podman 4.3.1 prints `Error: inspecting object: no such container X`), or a call that prints another container's name (an ID prefix); any other failure of the call is exit 3 with Podman's lines, so a broken Podman is not mistaken for an empty host. `HostConfig.Init` and the image ID were added to the format: the first gives the value `INIT=auto` must take in the fingerprint at entry (3.2 left this to `up`), the second is the stale-image comparison.
Impact on the design: 3.7.2 "3.3 state". How to reverse: change LOOKUP_FORMAT and find_box together; the tests build the line with one function (`line()` in tests/test_host_up.py).

## [3.3] The stale lock is renamed and re-read before it is deleted (the sketch of 3.6 can delete a live lock)
Context: the sketch in 3.6 removes a lock with `rm -rf` as soon as the pid it read is dead. With two waiters that both read the dead pid, the second `rm -rf` can delete the lock that the first one has just made, and then both proceed. B33 asks that the stale rule never remove a live lock.
Options: (a) the sketch as written; (b) a second `mkdir` lock around the removal (a lock for the lock, which can itself go stale); (c) rename the folder (atomic), read the pid file in the renamed folder, delete it only if it is still the dead pid (or still absent), else put it back.
Chosen: (c). It shrinks the window to a `mkdir` by a third call between the rename and the put-back, which is not closed and is written down as [unverified]; a pid that another process reused is not detected either. Tunables for tests: SWARMBOX_TEST_LOCK_TRIES (default 90 polls), SWARMBOX_TEST_LOCK_PIDWAIT (default 5 polls), SWARMBOX_TEST_NAP (default 1 s), counted in loops rather than read from a clock so the code stays POSIX.
Impact on the design: 3.6 and 3.7.2 "3.3 state". How to reverse: replace reap_stale by `rm -rf "$UP_LOCK"`.

## [3.3] Signals end `up` at once: children and pauses run in the background and are waited for
Context: a POSIX shell runs the trap of a signal only after the foreground child has finished, so a `kill -TERM` on the helper during a slow `create-flags` or a `sleep 1` would leave the lock until the child ended; the test asked for "no lock folder after SIGTERM".
Chosen: `create-flags` runs in the background and `wait`s, every pause is `sleep N &` and `wait`; the EXIT trap kills the child and removes the lock (only if this call made it) and its own temporary files; the exits are 129, 130, 143. `podman run` and the other short Podman calls stay in the foreground (a Ctrl-C reaches them through the terminal's process group; a `kill` of the helper alone waits for them). A call killed with SIGKILL leaves `flags.<pid>`, `cid.<pid>`, `err.<pid>`; the next call sweeps them under the lock when the pid is dead (a pid in use, or one that is this call's, is left alone).
Impact on the design: 3.7.2 "3.3 state". How to reverse: run create-flags in the foreground.

## [3.3] create-flags is run as a program, and SWARMBOX_TEST_CREATE_FLAGS can replace it
Context: the tests need a create-flags that is slow (to hold the lock deterministically) or fails after printing flags; the design says `up` captures the output and checks the status.
Chosen: `up` runs `<helper folder>/swarmbox-host create-flags` as a separate process (a function call would not let a signal or a slow step be tested the same way). The test-only variable SWARMBOX_TEST_CREATE_FLAGS names a program that is called in its place; the tests wait on marker files, not on sleeps. The variable executes whatever the environment names, like the other SWARMBOX_TEST_ switches; it is documented there and only the owner's own environment can set it.
Impact on the design: none. How to reverse: call cmd_create_flags in a subshell.

## [3.3] reset captures and checks the new box before it removes the old one
Context: 3.7.2 says `reset` removes the container (step 2) and then runs the steps of `up` (step 3), so a workspace problem or an old Podman found in step 3 would leave the user with no box and no way to enter.
Options: (a) follow the order; (b) run every check and `create-flags` first, then `podman rm -f`, then `podman run`.
Chosen: (b). For a good configuration the result is the same; for a bad one the old box stays. The removal still happens before the creation, so the name is free. The cost is that a problem that only `podman run` can find (a busy port) is found after the removal, as in (a); the message then tells the user to fix it and run `swarmbox` again, which creates the box.
Impact on the design: 3.7.2 "3.3 state". How to reverse: move prepare_create after the removal in up_main.

## [3.3] A start that fails is exit 7; a paused box counts as alive while waiting; an unreadable state counts as gone
Context: 3.7.2 gives 7 only for "creation failed" and says nothing about `podman start` failing, a paused box or an inspect that fails during the wait.
Chosen: a failed `podman start` of a stopped box is exit 7 (the same family: a port in use at start), removes nothing and says the box is still there; while waiting, `running`, `created`, `configured`, `initialized` and `paused` keep waiting and every other state, or a failed read, is "gone" (exit 6 at once with `podman logs --tail 20`).
Impact on the design: 3.7.2 "3.3 state". How to reverse: change the case in wait_ready.

## [3.3] stop: exact lookup first; no box is exit 0; a container that is not ours is exit 5
Context: the table says exit 0 or 1. `podman stop ab` also stops a container whose ID starts with `ab`.
Chosen: the helper looks the box up by exact name (one call) before it stops anything. No box: a line and exit 0 (stopping what is not running is not a failure). A container with the box's name and no `swarmbox.managed` label (v0.1.0): the v0.1.0 message and exit 5, nothing stopped; "a container that was not created by this design is never touched" is the safer reading. These two outcomes are additions to the table.
Impact on the design: 3.7.2 table (the stop row). How to reverse: drop the lookup and call `podman stop <name>`.

## [3.3] url: exit 1 with WEB=0; the public name; no Podman, no config validation beyond WEB and WEB_PORT
Context: the table says exit 0 and "the public one when configured". `cloudflare.json` holds `domain`, `emails` and `tunnel`, no host name; v0.1.0 printed `<container>.<domain>` or `SWARMBOX_WEB_HOSTNAME`.
Chosen: two lines: `http://127.0.0.1:<WEB_PORT>` and `https://<host>`, the host being SWARMBOX_WEB_HOSTNAME or `<box name>.<domain>` (domain from SWARMBOX_WEB_DOMAIN, else the `"domain"` line of `~/.config/swarmbox/cloudflare.json`, read with sed, because the helper has no JSON parser and python3 is needed only for `remote`). A value with other than letters, digits, `.` and `-` is ignored with a line. With `WEB=0` there is no URL: exit 1 and a message (the table says 0; a script that reads the output would otherwise get an empty answer and a success). Only WEB and WEB_PORT are read and validated; no Podman call exists on the path.
Impact on the design: 3.7.2 table (the url row). How to reverse: print nothing and exit 0 for WEB=0.

## [3.3] Image check on the create path: `image exists`, else `pull -q`; INIT probe name; conflict check by label
Context: 3.8 says a missing image is pulled and that `up` checks it; today's code lets `podman run` pull implicitly, where a network failure would look like a creation failure (exit 7) and the probe of `INIT=auto` would also try to pull.
Chosen: `podman image exists <image>`, else `podman pull -q <image>` after one line; a failure is exit 3 with the last line of Podman's error and the advice of 3.8. The `--init` probe is `podman run --rm --init --name <box>-init-probe-<pid> --entrypoint true <image>` (v0.1.0 ran `true` through the entrypoint; the explicit entrypoint does not depend on what the image's entrypoint does with an unknown word); the name starts with the box's name so a test box keeps its `swarmbox-test-` prefix. The other-box check is `podman ps -a --filter label=swarmbox.workspace=<path> --format {{.Names}}`; a failure of that call is ignored (the creation then finds its own errors). The messages are one line each; the creation failure is two (the lines of Podman's error between them).
Impact on the design: 3.7.2 "3.3 state". How to reverse: drop ensure_image and let `podman run` pull.

## [3.3] The mount point of the nested volume is made by the helper (found by the real smoke test)
Context: the first real throwaway box (reduced mode) stopped at serve step 3: "cannot create the SwarmBox folders". A manual run with the same flags showed `.local` and `.local/share` created by Podman as the container's root (not mapped to the user), mode 1755; `containers` itself was the volume. With the old layout (`.swarmbox/`) the folder was never a child of a missing folder. The live box works only because its home already had `.local`.
Chosen: before `podman run`, the helper runs `mkdir -p <workspace>/.local/share/containers` with umask 022, as the user; an error is exit 4. It is not part of create-flags (a pure function that touches only the workspace folder itself). This means every first `up` creates `.local/share/containers` in the workspace; the design already shows it as an empty folder there.
Impact on the design: 3.7.2 "3.3 state"; 3.5 mentions the folder. How to reverse: do not; without it a fresh workspace does not start. A real fix in the image (serve running as root for one step) would be a larger change.

## [3.3] Reduced real smoke: SWARMBOX_TEST_NO_NESTED drops --hostname too; XDG_DATA_HOME stays real; the podman wrapper only records
Context: the development box's nested level has `utsns=host` in /etc/containers/containers.conf, so `--hostname` is refused ("cannot set hostname when running in the host UTS namespace"); a private UTS namespace is refused too (`sethostname: Operation not permitted`); a scratch HOME also moves Podman's image store to a scratch folder on overlayfs, which fails ("'overlay' is not supported over overlayfs").
Chosen: the test-only switch SWARMBOX_TEST_NO_NESTED=1 removes `--device /dev/net/tun`, `--security-opt unmask=/proc/*` and `--hostname` from create-flags and adds `-e SWARMBOX_TEST_NO_NESTED=1` (what the older smoke steps already do); every result is tagged reduced. HOME, the XDG config and state folders, the workspace and the lock are scratch folders; only XDG_DATA_HOME is the real one, so that Podman's own store is found (the helper writes nothing under it). A `podman` wrapper first in PATH writes each call's arguments to a log in the scratch folder and runs the real Podman, so the call count of the fast path is measured. The full flags (tun, unmask, hostname) have not run for real here: CI or the owner's host (SWARMBOX_SMOKE_FULL=1) must.
Impact on the design: 3.7.2 "3.3 state" lists the switch; 13.3 layer 2 lists the steps. How to reverse: n/a, it is test-only.

## [3.3] Smoke bookkeeping: SWARMBOX_SMOKE_ONLY, `podman unshare rm` for scratch folders, the old "no port" test
Context: the new steps publish the web port (through the helper) on 127.0.0.1 at a random port from 20000 to 39999 (never 7681, 8889 or 43323; the file does not contain those numbers), which the older test "publishes no port" forbade; a failed first run left scratch folders with sub-UID owners that shutil cannot remove.
Chosen: the old test now says the smoke code itself passes no `-p` and a new test checks the random loopback port, the prefixed names, the scratch HOME and the real XDG_DATA_HOME in the new steps; the cleanup falls back to `podman unshare rm -rf <dir>` for a scratch folder that is still there; SWARMBOX_SMOKE_ONLY=id,id runs chosen steps (a development convenience, not used by CI). Two such folders from my own failed runs were removed by exact path.
Impact on the design: none. How to reverse: n/a.

## [3.3] Fake podman: rules by arguments and answers in sequence
Context: `podman container inspect` is called with three different formats in one run, and "the box does not exist the first time and runs afterwards" must work for two concurrent processes.
Chosen: an entry of FakePodman may be {"rules": [...], "default": {...}}, a rule has "match" (strings that must all occur in the joined arguments), and any rule or entry may have "seq", answered one per call that the rule answered, counted from the call log up to the process's own line (so it is the same for concurrent callers). Backward compatible (the old keys work unchanged); three tests added to tests/test_helpers.py.
Impact on the design: 13.1 describes the fake in general terms. How to reverse: n/a.

## [3.3] What was not done or did not work
- The host connection (`podman -c <name>`, the short-symlink fallback, step 6 of "What up does") is not in this slice: the slice goal did not list it. It stays in the Phase 3 scope for a later slice.
- Only the busy port was run for real as a creation failure; "a rejected option leaves a cidfile" shares the code path but was not run (B18 stays as it was for other causes).
- macOS (`mkdir`, `kill -0`, `sleep 0.02`, `stat`) and arm64 were not run; bash 3.2 not here. The CI macOS job runs tests/test_host_up.py for the first time on the owner's push.
- The full-mode flags (tun, unmask, hostname) were not started for real.
- The first three smoke runs failed (storage on overlayfs under a scratch HOME; `--hostname` in the host UTS namespace; the mount point owned by the container's root); each cause is above.
- The first draft of one test asserted the text "did not become ready in 60 s" against the source, which does not hold (the number comes from the tuned variable); it now runs with 3 polls of 1 s.

## [3.4] The 100-character limit is counted in bytes
Context: the design says "100 characters"; the kernel limit is 108 bytes (107 usable) and a workspace name may hold multibyte characters (an accented folder name is two bytes per letter).
Options: count characters (what a shell `${#var}` does in a UTF-8 locale, and varies with the locale); count bytes (`printf %s | wc -c`).
Chosen: bytes, because the kernel compares bytes and `wc -c` gives the same number in every locale (tested under C, POSIX and C.UTF-8). A path of 100 bytes is direct, 101 bytes gets the link, even when it has fewer than 100 characters.
Impact on the design: 3.7.2 "3.4 state" says bytes; 3.5 still says characters, which is the same for ASCII paths. How to reverse: replace `byte_len` by `${#1}`.

## [3.4] The rule is by length only; the default workspace gets no link because it is short
Context: the slice says "no symlink is ever made for the default workspace". With a very long HOME the default workspace could exceed 66 bytes.
Options: special-case the default workspace (never a link, so the connection would fail to connect); measure every workspace the same way.
Chosen: measure every workspace the same way. The default `~/swarmbox` is far below the limit for any normal HOME (tested), so the requirement holds in practice; an enormous HOME would get a link rather than a connection that cannot work.
Impact on the design: 3.7.2 "3.4 state". How to reverse: skip `sock_plan` when the workspace equals the default.

## [3.4] Step 6 runs last, under the lock, on every successful `up` including the fast path; a failed registration is a warning
Context: the design puts the connection in step 6 but also says the fast path calls nothing else (B35).
Options: skip the step on the fast path (a box started elsewhere would never get its connection; a changed address never re-registered, which 12.4 requires "on every up"); run it everywhere.
Chosen: run it everywhere, after readiness, and let it cost one `podman system connection list` on the fast path (an add and a remove only when the address differs). B35's two-call budget now counts the non-`system` calls; tests/test_host_up.py and tests/smoke_image.py were changed that way. Registration failures (list, add) print one warning and keep the exit code, as v0.1.0 did, because the box is usable without the connection. Only "too deep" and "not a symlink at the link path" exit 4; for a box that is about to be created that happens before `podman run`, so nothing is created.
Impact on the design: 3.7.2 step 6, B35 row, 3.8 `connection` row. How to reverse: remove the `host_connection` calls in cmd_up and cmd_reset.

## [3.4] A new subcommand, `swarmbox-host connection`
Context: the slice asks for "its supporting subcommand"; the design lists none for step 6.
Chosen: `connection` runs the step alone (no lock, no box) and prints the registered URI, which makes it testable without a box and gives the function or the owner a way to repair the registration. Added to the 3.8 command table.
Impact on the design: the table row. How to reverse: delete cmd_connection and its dispatch line.

## [3.4] A link made once is not removed when the path becomes short again; only the connection named like the box is touched
Context: the link is a small state file that the next long workspace reuses.
Chosen: never delete an old link (the helper only creates or refreshes); a connection name that merely starts with the box name is not the box's (matched exactly, by `awk index`, so a URI with spaces is read whole).
Impact on the design: 3.7.2 "3.4 state". How to reverse: remove the link when the plan has no link.

## [3.4] Test isolation, and the stateful fake
Context: registering a connection edits Podman's configuration when isolation fails.
Chosen: every test sets HOME, XDG_CONFIG_HOME and CONTAINERS_CONF (an empty file, Podman refuses a missing one) in a mktemp folder; most tests use a small stateful fake `podman` (only `system connection list|add|remove`, it exits 99 for anything else); one class uses the real `podman system connection` (no service is contacted) in the isolated config; `tearDownModule` compares snapshots of the real ~/.config/containers, ~/.local/state/swarmbox and the real `podman system connection ls` taken in `setUpModule` (they were identical). tests/smoke_image.py got the same isolation for its throwaway box. The first smoke run with an empty CONTAINERS_CONF failed (exit 7, `sethostname: Operation not permitted`): CONTAINERS_CONF replaces /etc/containers/containers.conf, where the development box keeps `utsns = "host"`. The scratch file now starts as a copy of that file; the rerun passed (up-lifecycle and up-busy-port, reduced), and the fast path measured 3 calls (inspect, image inspect, `system connection list`), 0.10 s.
Impact on the design: none. How to reverse: n/a.

## [3.4] What was not done or did not work
- macOS (skipped by the step, tagged [unverified]), arm64, bash 3.2 and a real nested Podman service behind the socket were not run; the reduced check uses a Python stand-in server in a throwaway container (swarmbox-test-3-4-<random>, removed by exact name).
- Whether `podman system connection add` makes the first connection the default for plain `podman` on a host is [unverified]; v0.1.0 had the same behaviour, and the helper does not pass `--default` either way.
- A real `up` on a real long workspace with the nested service was not run; only the connection step with the real Podman CLI in an isolated config.

## [3.5] swarmbox-init is POSIX sh, filled from template files with awk
Context: the slice left "POSIX sh or the image's bash" open.
Options: bash (arrays, easy quoting); POSIX sh.
Chosen: POSIX sh (`container/scripts/swarmbox-init.sh`) because it is testable under dash and bash --posix like the helper, and needs no bashism. Templates carry `@VERSION@`, `@IMAGE@`, `@SEED_WITH@`, `@SEED_WORKSPACE@`, `@SEED_IMAGE@`; values are quoted per shell (`'\''` for bash and zsh, `\'` and `\\` for fish) and substituted by one awk pass that reads them from its environment, so a value is never parsed as a pattern or substituted twice. A newline in a seed is exit 2.
Impact on the design: 3.7.5 (nothing contradicted), 9.3 unchanged. How to reverse: rewrite the script in bash; tests do not depend on the language.

## [3.5] The seed block always defines the three seed variables; the call to `config seed` is made only when one is non-empty
Context: the sketch called `config seed` on every call.
Chosen: skip the call with no seeds (one process less per call; the helper has nothing to record or compare). Order of arguments: with, workspace, image. `--image` is both the extraction image and a seed; without it the extraction image is `ghcr.io/<org>/swarmbox:<VERSION>` and IMAGE is not seeded (the helper's default is the same string).
Impact on the design: 3.6 "3.5 state". How to reverse: call it unconditionally.

## [3.5] `-t` only when stdin and stdout are both terminals (deviation from 3.3, which said stdout)
Context: `podman exec -t` fails when stdin is not a terminal.
Chosen: both ends; tested with ptys for all four combinations. Design 3.3 and 3.6 updated.
How to reverse: test `[ -t 1 ]` only.

## [3.5] zsh gets `emulate -L zsh`; fish is its own text
Context: the zsh template would otherwise equal the bash one, and zsh options (KSH_ARRAYS, SH_WORD_SPLIT, NO_UNSET) can change a function.
Chosen: one extra first line in the zsh template; tests also run it with those options set by the caller.
How to reverse: delete the line.

## [3.5] Version probe is strict; `sort -V` failure keeps the helper silently; XDG_DATA_HOME honored
Context: the sketch compared raw text, would claim "newer" when sort failed, and used only HOME.
Chosen: a helper whose `version` is not one first line of the shape X.Y.Z counts as having no version (re-extract); an empty answer from `sort -V` means no comparison, so keep and say nothing; the helper folder is under `${XDG_DATA_HOME:-$HOME/.local/share}` (a relative XDG value ignored), which is what lets the tests isolate it. `~` and `~/...` seeds pass unchanged (the helper expands them; the sketch would have broken them).
How to reverse: n/a, each is a few lines of the templates.

## [3.5] Host words also include `fingerprint` and `version`
Context: the slice names them; 3.3 listed eight words. `connection` is not routed (it is `up`'s step 6).
Impact on the design: the 3.3 table.

## [3.5] Tests: shared case table, a two-word key and env log in the fake helper, a stdout_file in the fake podman
Context: the bootstrap needs a real tar archive on the fake `podman run` output, and `config get NAME` must answer differently from `config seed`.
Chosen: FakePodman got `stdout_file`; FakeHostHelper got two-word command keys ("config get") and logs each call's SWARMBOX_* variables. Every function call makes one `version` probe, which the tests drop from the call lists. I mutated the templates by hand (removed the `-x` check, the `-t 0` and `-t 1` tests, `sort -V`, the cleanup) to confirm the table notices; two mutations were first not caught (a stdin-only terminal case, and a comment that held the text I replaced) and a test was added for the first.
How to reverse: n/a.

## [3.5] What was not done or did not work
- bash 3.2 and macOS were not run: only `bash --posix` and a lint of known bash 4 constructs, which cannot find a construct it does not list.
- A real attach (`podman exec -it` into a running box through the function) was not run; the pty tests prove the arguments. The real function did extract the helper from the real image under bash, zsh and fish (isolated XDG_DATA_HOME with a symlink to the real container storage, because Podman keeps its storage under XDG_DATA_HOME; the first attempts failed with the overlay error, which also showed the 3.8 failure message with the real Podman).
- B19 for the CI images (ubuntu, macOS) was not run; only Debian 12.
- A leftover empty ~/.local/share/fish (made by my own `fish -c` probes under the real HOME) was removed with rmdir; nothing else outside temp folders was written. The test image swarmbox-test-35-img was removed by name.

## [3.6] update changes things in the order: pull, extract to a temp folder, tag, rename the helper, write the config
Context: design 3.8 listed the helper rename (step 3) before `podman tag` and the config write (step 4), and promised "if `podman tag` fails, nothing is written (exit 3)". With that order a failing tag would leave a new helper next to an old `IMAGE`.
Options: (a) keep the design's order; (b) read the version from the temporary folder, tag, then rename and write the config.
Chosen: (b), because every failure before the rename (pull, run, tar, executable, version, tag) then leaves the helper, the config and the box exactly as they were, which is what 3.8 says. The one failure after the rename is the config write itself (exit 1, new helper, old `IMAGE`; the next `update` or `config set IMAGE` repairs it).
Impact on the design: 3.8 "Update flow" steps 3 and 4 reworded; 3.7.2 table row for `update`.
How to reverse: move the `podman tag` block below the rename in `cmd_update`.

## [3.6] The series comes from the tag of IMAGE; digest, tag-less and non-numeric images are refused for a plain update
Context: the design says "the same X.Y series as the current IMAGE" but not what to do with `IMAGE=swarmbox:dev`, `...@sha256:...` or no tag (the task also asked to log "digests refused or handled").
Options: guess a series; pull `latest`; refuse.
Chosen: refuse with exit 2 and the hint to use `--to TAG`, before any Podman call; a tag is a series when it starts with two numbers followed by the end, `.` or `-` (`2.0.1`, `2.0`, `3.4.5-rc1`; `2` and `main-2.0` are not). `--to TAG` works for all of them: the repository is everything before the tag and before `@digest`, so a digest-pinned image can be moved to a tag, which drops the digest. A registry port is never taken for a tag (only a `:` in the last path component is).
Impact on the design: 3.8 step 1 says so.
How to reverse: n/a (a more lenient rule would make `update` surprising).

## [3.6] --to accepts a tag only, and an exact X.Y.Z tag must hold that version
Context: `--to TAG` could mean a tag or a whole reference.
Chosen: a tag (letters, digits, `_`, `.`, `-`, at most 128, not starting with `.` or `-`; `--to=TAG` also works); the repository is always the current one. If the tag looks like `X.Y.Z` and the extracted helper reports another version, exit 3: tagging it as that other version would make `IMAGE` lie about what the box runs. A moving tag (`2.1`, `latest`) gets the local tag of the version it holds; when the tag already is the version, no `podman tag` call is made.
Impact on the design: 3.8 steps 1, 3 and 4.
How to reverse: delete the check in `cmd_update`.

## [3.6] update replaces the helper in the standard data folder, not the folder the running script is in
Context: the function extracts into `${XDG_DATA_HOME:-$HOME/.local/share}/swarmbox/host`. A helper run from a repository checkout (tests, development) would otherwise overwrite `container/host/`.
Chosen: `update` always writes the standard folder (created when missing), the same one the function uses. The running script keeps working because the rename leaves its open file alone (the old folder is unlinked after the rename).
Impact on the design: none beyond 3.7.1, which already names that folder.
How to reverse: use the folder of `$0`.

## [3.6] The success line goes to standard output, "pulling ..." to standard error; SWARMBOX_IMAGE is reported, not obeyed
Context: 3.7.2 says standard output is data only, but `update` has no other data; a pull can take minutes with no sign of life.
Chosen: the one result line on standard output (so a script can capture it); a progress line on standard error, as `up` does for its pull. A set `SWARMBOX_IMAGE` is used to find the repository and series (it is the effective `IMAGE`), the file is written anyway, and a warning says that the variable overrides it.
How to reverse: n/a.

## [3.6] The e2e derives 2.0.1 and 2.1.0 from one build with a one-line Containerfile
Context: the goal said "two throwaway builds"; a full build of the image takes minutes and the versions differ only in the helper's `VERSION` file (what `update` reads).
Chosen: one `dev/dev-build.sh` build (`SWARMBOX_E2E_IMAGE` reuses it), and `FROM <base>` layers that rewrite `VERSION` for the other versions. The registry gets different image IDs per version, which is all `update` tells apart. A real second release would differ in more files; that is a Phase 7 check against the real registry.
How to reverse: build each version from a Dockerfile with a different `container/host/VERSION`.

## [3.6] The install line needs --image when the registry is not ghcr.io/<org>
Context: `init` knows only its own default repository, so the printed function would extract the helper from `ghcr.io/<org>/swarmbox:2.0.0`, which does not exist.
Options: let the entrypoint learn the image it runs from (no reliable way inside a container); document `--image`.
Chosen: the e2e runs the line of design 3.1 with the registry substituted and `--image <ref>` appended; 3.1 now says an install from another registry needs `--image`. No code change. README has no install line yet (Phase 7 rewrites it), so "design 3.1 and README match" holds for design 3.1 and is open for the README.
How to reverse: n/a.

## [3.6] Podman store, registries and the scratch XDG folders in the e2e
Context: the function writes the helper under XDG_DATA_HOME, which must be scratch, but rootless Podman's image store defaults to XDG_DATA_HOME too (a store on this box's overlayfs fails). `registries.conf` in a scratch XDG_CONFIG_HOME and `CONTAINERS_STORAGE_CONF` were both ignored by Podman 4.3.1.
Chosen: a `containers/storage.conf` in the scratch XDG_CONFIG_HOME pointing at the real graphroot and runroot (read from `podman info`), a copy of `/etc/containers/containers.conf`, and `CONTAINERS_REGISTRIES_CONF` for the insecure `localhost:<port>`. Documented in docs/local-registry.md. The first, wrong, attempt (a registries.conf file in the XDG folder) failed with "server gave HTTP response to HTTPS client".
How to reverse: n/a.

## [3.6] registry:2 cleanup and what was left
Context: `registry:2` is not a swarmbox-test- image and was absent before this slice.
Chosen: the e2e pulls it once, and removes it at the end only when it pulled it (`SWARMBOX_E2E_KEEP_REGISTRY_IMAGE=1` keeps it). My own probe of the registry before the test left an anonymous volume (a registry container removed without `-v`); I removed it by its ID. The e2e uses a named volume `swarmbox-test-3-registry-<rand>-data` and removes it by name.
How to reverse: n/a.

## [3.6] What was not done or did not work
- Reduced everywhere: no nested Podman in the boxes (`SWARMBOX_TEST_NO_NESTED=1`; boxes are ready "with 2 warnings"), no real registry (Phase 7), no macOS, bash 3.2 or arm64 (the arm64 CI job was not built in this slice; it needs a runner).
- The fake-registry fallback the task described was not needed: `registry:2` pulled and ran. If it cannot, `tests/e2e_registry.py` reports the failure and the fake-Podman tests of `tests/test_host_update.py` are the reduced run.
- The e2e's first run failed for three shells' worth of reasons that were the test's: the "image is already local" pre-check ran for the second shell after the first had pulled it (now each world untags first), and the teardown called the function when the install had failed. Both fixed; the product code passed on the first real run.
- Two terminals at once before the helper exists (first install) worked in one trial per shell; no lock protects the function's extraction, so it is not guaranteed. Not asserted.
- The README does not yet carry the install line (Phase 7).


## [3.7] The arm64 job: a native `ubuntu-24.04-arm` runner, not QEMU
Context: the plan says "an arm64 CI job, if the CI provider allows"; design 13.4 and B31 name both an arm64 runner and `podman build --platform linux/arm64` under emulation as ways to check it. The job cannot run here (no arm64 host, no runner).
Options: (a) emulation with QEMU on the amd64 runner; (b) a native arm64 hosted runner; (c) no job, only a note.
Chosen: (b), `runs-on: ubuntu-24.04-arm`, because B31 asks that the nested Podman, `keep-id` and Chromium work on arm64, which an emulated build cannot show for the nested Podman and runs very slowly for the Chromium step. The job fails at once if `uname -m` is not `aarch64`. It builds with `dev/dev-build.sh --tag swarmbox-test-img-ci-arm64` (the slice asked for the dev build script; on a runner its only effect is the harmless APT sandbox line in a scratch copy) and runs `SWARMBOX_SMOKE_FULL=1 tests/smoke_image.py`, where a skipped step fails the job; it removes the image by its exact name; no push, no login, no port, no secret. I did not use `podman build --platform` anywhere (a test forbids it, so emulation cannot slip in).
Impact on the design: 13.4 now describes the job as built; B31 is open (`[unverified]`) in Part B, A.3 and the 3.7 results table. Nothing in the product changed.
How to reverse: delete the `arm64` job and its tests in `tests/test_ci_workflow.py`; or change `runs-on` if the account has no access to the label (the label is the one GitHub documents for hosted arm64 runners; I could not check that this account may use it: if it cannot, the job stays queued and the owner should decide between a self-hosted runner and emulation).

## [3.7] bash 3.2 on macOS: `SWARMBOX_TEST_BASH` and a guard step
Context: the macOS job ran `tests/test_function_bash.py`, but the test used the first `bash` in `PATH`, which on a macOS runner may be a Homebrew bash 5 and so would not prove anything about bash 3.2.
Options: (a) leave it; (b) a test-only environment variable that picks the interpreter, plus a step that fails unless `/bin/bash` is a 3.x.
Chosen: (b). `tests/test_function_bash.py` reads `SWARMBOX_TEST_BASH` (default: `which bash`); the macOS job sets it to `/bin/bash` for a dedicated step and a guard step before it fails the job unless `${BASH_VERSINFO[0]}` is 3. The same file no longer appears in the general macOS list (a test checks that every non-excluded file still runs there once). The guard is a hard failure rather than a probe on purpose: if the runner's `/bin/bash` is not 3.x, the job would say nothing about bash 3.2 and the owner should know.
Impact on the design: 13.4 describes it; B19 and B30 stay `[unverified]` for macOS until the first run.
How to reverse: remove the env line and the guard step; the test falls back to `which bash`.

## [3.7] Shell presence is a CI failure, and dash and busybox get their own step
Context: `tests/test_host_shells.py` skips the busybox cases when busybox is absent, and the zsh and fish tests skip when the shell is missing; on a runner that would turn B23 and the three-shell function test into silent skips.
Chosen: the linux job installs `zsh fish busybox-static dash`, one step runs `command -v bash zsh fish dash busybox` (a missing one fails the job), and a second step runs `tests/test_host_shells.py` and `tests/test_host_create_flags.py` (the file that compares the helper's output across the shells) with `command -v dash` and `command -v busybox` first. The tests themselves keep their skips so that a developer without busybox can still run them; only CI is strict. I used the package `busybox-static` (Ubuntu's `busybox` package is a transitional name for it; `busybox-static` is certain to provide `/bin/busybox`).
Impact on the design: 13.4; B23. How to reverse: drop the two steps.

## [3.7] tests/run_all.sh is a POSIX sh runner, and it is a CI test of its own
Context: the slice asked for a full-regression runner "tests/run_all.sh reduced if absent": no such file existed and every earlier phase ran its files by hand.
Chosen: `tests/run_all.sh` (POSIX sh, shellcheck clean), options `--werror`, `--repeat N`, `--only a.py,b.py`, `--browser`, `--list`; it counts tests from the unittest summary, prints one line per file and a TOTAL line, and exits 1 if any run fails. The browser files are skipped unless `--browser` (they need chromium and ttyd and run in the scheduled job). `tests/test_run_all.py` tests it on small files only (and on two throwaway test files for the failing case), never the whole suite from inside the suite. It is added to the linux and macOS lists of `ci.yml`.
Impact on the design: none (plan 3.7 state and CONTRIBUTING). How to reverse: delete the two files and the two CI lines.

## [3.7] B22 is closed on Linux with a journey test; the real WSL home and macOS stay open
Context: B22 had a Linux part closed in 3.1 by many single-purpose tests (pty set, mode refusal, environment value). The slice asked that the whole path be exercised end to end.
Chosen: one `TokenJourneyTest` in `tests/test_host_config.py`: `config set` on a pseudo-terminal -> mode 600 -> `get` and `list` -> the environment value wins -> `chmod 644` -> every reader ignores the file's token with one line naming the mode and `chmod 600 <file>` and the rest of the file still works -> typing the token again repairs the mode -> an explicit `chmod 600` is accepted. It passed on its first run (no bug found; it adds coverage, not a fix), so I cannot claim it failed first. B22's evidence tag now names both test classes; macOS and a WSL home on a Windows drive stay `[unverified]` with a Phase 6 pointer.
Impact on the design: the 3.7 results table. How to reverse: delete the class.

## [3.7] Two absences that A.1 claimed were proven had no test: D19 and D36
Context: A.1 says D19 (`swarmbox --once` creates no container) and D36 (`uninstall` is no host word, routed as a command) are proven in Phase 3, but no test mentioned `--once` or `uninstall`. Found while writing the close-out table.
Chosen: one shared case in `tests/function_cases.py` (so it runs in bash, `bash --posix`, zsh and fish): `--once` and `uninstall` (alone and with arguments) are no host words; the function makes only the helper's `up` and `config get NAME` and one `podman exec ... attach <words>`, never a `rm`, `stop`, `kill` or `run`. The helper answers exit 2 "unknown subcommand" to both (checked by hand, not by a test, because the dispatcher test for unknown words already exists). It passed at once: the behavior was already right, the proof was missing.
Impact on the design: none. How to reverse: delete the case.

## [3.7] The close table: states are closed, reduced or open, and B33 is called reduced
Context: A.1 and A.3 rows that point at Phase 3 had no common statement of how far they got. Part B uses "closed-reduced" for several.
Chosen: a table in plan section 6 ("3.7 state") with one row for every D and B whose A.1 or A.3 phase includes 3, state `closed` (nothing left for Phase 3), `reduced` (the Linux or fake part is done, a named part is left for CI or Phase 6 or 7) or `open` (B31 only). I was conservative: D5, D6, D16, D20, D28, D33 and D34 are `reduced` although their Phase 3 work is done, because the proof still has a named part that did not run (nested container, macOS, bash 3.2, a real WSL). `tests/test_docs_consistency.py` checks the table against A.1 and A.3 so that a new Phase 3 row cannot be forgotten, and checks that each Part B fact has an evidence tag naming existing test files, or `[unverified]` with a Phase 6 or 7 pointer (B31: the CI job and the first CI run).
Impact on the design: a 3.7 results table in Part B. How to reverse: delete the table and `PhaseThreeCloseTest`.

## [3.7] Stale wording removed; what was found
Context: grep for "Phase 3 writes", "Phase 3 adds", "until Phase 3" and for stub wording in code and docs.
Chosen: the only stale wording left was in design 3.3 (the entrypoint's `init` was "127 until Phase 3 writes swarmbox-init") and in 13.4 ("the zsh and fish function tests and the arm64 job are added by later phases"); both corrected. The Dockerfile comment and the entrypoint comments were already correct (slice 3.5). CONTRIBUTING.md still says `test_tool_stub.py` covers "parts that are still stubs": that is true (`prepare`, `remove`, `doctor`, `new` are Phase 4b) and I left it. A test (`test_no_stale_phase3_wording_in_code_or_docs`) now fails on these phrases outside the history files.
Impact on the design: the two lines. How to reverse: n/a.

## [3.7] What was not done or did not work
- The arm64 job, the macOS bash 3.2 step and the dash/busybox step have never run; their only checks are `tests/test_ci_workflow.py` (28 tests) and actionlint 1.7.12 (downloaded into a mktemp directory, checksum verified, run once, deleted; clean).
- Not testable here and written down in the gate row: arm64; macOS bash 3.2, `sh`, `stat` and `sort`; a real WSL path and a Windows-drive workspace on a real WSL; a host UID other than 1000; Podman older than 4.3; the real registry; the third nesting level.
- The Phase 3 gate is `partial`, not `done`: the exit criterion "the function and helper tests pass in CI" is true only locally.

## [4b.1] The MCP generator is a jq script, swarmbox-mcp, with exit 1 for "written but incomplete"
Context: the slice asked for a generator script and left jq versus python3 open; the image has both, and v0.1.0 used jq.
Options: jq; python3; keep the code inside entrypoint.sh.
Chosen: `container/scripts/swarmbox-mcp.sh` in bash with jq, installed as `swarmbox-mcp` (a separate program so prepare.sh can call it). Merge is shallow (`add`): a user `args` replaces the image `args`, a user `env` replaces the whole `env`; this is predictable and what "fields override" says. Exit 0 = clean, 1 = file written but some server file was bad (one stderr line each), 2 = nothing written. serve turns any non-zero into one W health line and, if no file exists, leaves the empty valid file. Test-only variable SWARMBOX_TEST_MCP_DIR (image registry path), next to SWARMBOX_TEST_LIB.
Impact on the design: "4b.1 state" paragraph in 4.4; 4.1 wording about the no-op removed.
How to reverse: delete the script, its Dockerfile lines and restore the placeholder block of step 7.

## [4b.1] Server names with spaces and a user-level entry without command
Context: not settled by the design.
Chosen: a user-only entry needs a string `command`, otherwise it is skipped with a warning (an MCP client would reject it). Server folder names are iterated word by word, so a folder name containing whitespace is not supported (not tested, not guarded). The fallback empty file, "enabled: true" in a user file (accepted, field removed) and the OpenCode mirror (left for the opencode slice) are as in the design.
Impact on the design: none. How to reverse: n/a.

## [4b.1] What did not work
Running the serve tests through a pipe (`python3 ... | tail`) hung for the whole tool timeout because fake background processes kept the pipe open; with output to a file the 41 tests take 10 s. The generator was not run inside a built image (no container used in this slice).

## [4b.1] test_mcp_registry.py runs on Linux CI only
Context: test_ci_workflow requires every test file on the macOS job unless excluded. The generator is a container program (bash and jq in the image), like swarmbox-migrate.
Chosen: added to NOT_ON_MACOS in tests/test_ci_workflow.py, listed in the linux job only. Found because the first commit forgot it.
Impact on the design: none. How to reverse: remove it from the set and add the line to the macOS list.

## [4b.2] Package name: keep @opencode/cli, in one variable of install.sh
Context: the open question of the gate (`@opencode/cli` 2.x or `opencode-ai` 1.x). The design default and the 0.3 spike chose `@opencode/cli`, which v0.1.0 installs; the two are different release lines and a home written by one fails under the other.
Options: `@opencode/cli`; `opencode-ai`; support both with a switch.
Chosen: `@opencode/cli`, as `PACKAGE="@opencode/cli"` at the top of `install.sh`, tested to be the only place that names it. The slice asked for "one manifest variable"; the manifest keys are fixed and the installer does not see the manifest, so it is an installer variable, not a manifest key (a new key would need a SCHEMA decision and a validate rule for one tool).
Impact on the design: 6.6 "4b.2 state". Still [unverified]: which package upstream means as the main one. The owner may want to decide.
How to reverse: change the line (and, if the 1.x line is chosen, expect the builds folder to be `node_modules` directly; install.sh already falls back to that layout, untested against the real package).

## [4b.2] The 2.x shared background server is not investigated in this slice
Context: 0.3 noted that 2.x starts a shared background service per user account (`--standalone` avoids it). The slice must "note" it.
Chosen: noted in install.sh, 6.6 and here as [unverified]; nothing in the box starts or stops it, and `prepare.sh` does not pass `--standalone` (it renders a file; it does not run the program). The behaviour under `serve` (a process the supervisor does not know) and across `reset` needs the real program, which 4b.7 runs in a throwaway container.
Impact on the design: a sentence in 6.6. How to reverse: n/a.

## [4b.2] Prune rule: keep what bin/opencode.exe is linked to, and never the current architecture
Context: B10 said "never delete the current-arch build" and "prune by what is there, not by a list".
Options: (a) keep only the hard-linked build; (b) keep the linked build plus every build of the current architecture (including musl and baseline variants); (c) (a) plus a guard for the plain `-linux-<arch>` name.
Chosen: (c). The linked build is kept; the build named exactly `*-linux-x64` (amd64) or `*-linux-arm64` (arm64) is also kept even if the link points elsewhere; with no linked build nothing is removed. (b) would keep a 250 MB musl build on a glibc box for no reason. A musl box links to the musl build, which is kept, and the plain build then stays as well (about 250 MB more, tested).
Impact on the design: 6.4 says what is kept; the 745 MB figure holds for the glibc case. How to reverse: edit the `case` in install.sh.

## [4b.2] Local LLM off unless LOCAL_LLM_URL is set; the provider is removed, not left empty
Context: design 6.6 says "off unless set" (v0.1.0 had a default URL and model). The template has an empty `provider.local`. The slice says "unset gives a config without the local provider models".
Options: keep the empty provider; remove `provider.local` (and `provider` when it is empty).
Chosen: remove it: an OpenAI-compatible provider with no base URL and no models is noise in OpenCode's model list. A URL without a model is an error (exit 1, one health line) and renders the file without the provider: with no default model there is nothing safe to guess (design 7.2 removes the default).
Impact on the design: 6.6. How to reverse: change the `off` filter in prepare.sh.

## [4b.2] Failure reporting of prepare: a line protocol and one health line per tool
Context: 6.3 wants one health line per failing tool; `serve` step 7 until now made one generic W line for the whole command.
Options: prepare writes the health file itself; prepare prints `prepare-failed: <tool>: <reason>` lines and `serve` turns each into a W line.
Chosen: the second. The health file and the marker's `warnings=` count are owned by `serve` (marker count equals health lines is tested); a second writer would break that. A failure with no such line (the command itself broke) is still one generic W line. The output of prepare goes into serve.log as before.
Impact on the design: 6.3 "4b.2 state". How to reverse: restore the one-line `warn`.

## [4b.2] Other small decisions
- prepare.sh is run with `bash <file>`, not by its executable bit, so a lost bit cannot hide a tool; the timeout is 60 s (not in the design; a test-only environment variable shortens it). The timeout kills the whole process group.
- prepare also runs after the first-use install through the shim (design says "after a tool install"); a failing prepare never fails an install.
- `validate` gained the MCP_FORMAT rule (claude, opencode or empty); the design listed the key but no rule.
- `container/opencode/local-llm.json` is kept next to the new `container/tools/opencode/local-llm.json` because `Dockerfile.v0.1.0` still copies it; the 6.6 text said the folder is removed, now "in Phase 6". A test checks the two files are equal. v0.1.0's init.sh also still reads the old path.
- The mirror now accepts a file without `mcpServers` (empty `mcp`), where v0.1.0 would have failed. The mapping is otherwise the v0.1.0 one, compared on four fixtures by running the old function extracted from the tag (skipped when the tag is not in the clone).
- The two new test files are on the Linux CI job only (NOT_ON_MACOS), like the other container-program tests.
- Real install of opencode (npm, the real package, the 745 MB figure again under the new installer) is not done here: reduced, to 4b.7.

## [4b.3] Pinned versions: clasp 3.4.1, poetry 2.5.1, looked up on 2026-11-08
Context: D21 pins every non-agent tool; the slice said versions must be real.
Options: pin what the registries say today; copy v0.1.0's versions (not recoverable without building).
Chosen: today's values. clasp: `npm view @google/clasp dist-tags` returned `{"latest": "3.4.1"}`. poetry: `https://pypi.org/pypi/poetry/json` `info.version` was 2.5.1 and `https://install.python-poetry.org` answered HTTP 200. Neither version was installed for real in this slice (fakes only), so that the installer accepts `--version 2.5.1` and that clasp 3.4.1 runs on the image's Node is [unverified] until 4b.7. gemini is `latest` (agent); the current npm latest was 0.67.0, not recorded in the manifest.
Impact on the design: 6.12 table unchanged; "4b.3 state" paragraph in 6.3 records the versions. How to reverse: edit VERSION in the two tool.conf files.

## [4b.3] Poetry installer: private cache, config and temp folder, run through stdin
Context: 6.4 forbids writes outside TOOL_PREFIX. The official installer uses pip (cache in ~/.cache/pip) and Poetry itself uses ~/.config/pypoetry and ~/.cache/pypoetry.
Options: let it write and clean up afterwards; redirect all of it to a mktemp folder and delete that.
Chosen: redirect: `XDG_CACHE_HOME`, `XDG_CONFIG_HOME`, `XDG_DATA_HOME`, `POETRY_CONFIG_DIR`, `POETRY_CACHE_DIR` point into a private folder, `PIP_NO_CACHE_DIR=1`, and an EXIT trap removes it. The script is downloaded fully first (as claude's installer does) and piped to `python3 -`. The post-install `poetry --version` also runs inside that redirect. The 4b.7 no-side-effects test with the real installer decides whether this is enough.
Impact on the design: none. How to reverse: remove the exports.

## [4b.3] clasp login function: pass-through rules
Context: 6.12 says the function adds `--redirect-port 43323` to `login`.
Options: add it to any call containing `login`; only when `login` is the first argument; also add it when the user gave their own port.
Chosen: only when the first argument is `login` and no argument is `--redirect-port` or `--redirect-port=...` (the user's own port wins; the box then does not publish it, which is the user's choice). `clasp run login` is untouched. The function is written without arrays or bash-only syntax so it works in bash and zsh (tested in both). The option name was taken from the design text, not from clasp 3.4.1's `--help` [unverified].
Impact on the design: 6.12 "4b.3 state". How to reverse: edit clasp/shell.sh.

## [4b.3] Other small decisions
- gemini has no MCP_FLAGS and no MCP_FORMAT: the design gives no Gemini MCP wiring, so "MCP_FLAGS absent unless declared" holds. A Gemini MCP mirror, if wanted, is a later slice.
- gemini's installer checks only that bin/gemini exists, not that it runs: `gemini --version` of a real install was not measured here and could contact the network; 4b.7 checks it.
- tests/test_tool_link.py `test_real_tools_tree_links_claude_and_tool_ports_is_empty` asserted an empty tool-ports for the real tools; it is renamed and now asserts exactly `clasp\t43323`.
- Found while writing the fragment test: tests/test_tool_opencode.py `test_bashrc_fragment_makes_no_opencode_alias_but_yolo_works` uses environment variable names the fragment does not read (SWARMBOX_TEST_IMAGE_TOOLS instead of SWARMBOX_IMAGE_TOOLS_DIR), so it passes without exercising the real manifest. Not fixed here; the new test uses the correct names. Left for the owner or the 4b close-out.
- The new test file is listed in ci.yml (Linux job) and in the NOT_ON_MACOS set of test_ci_workflow.py, like the other container-program tests.

## [4b.4] Checksums recorded by really running the maintainer script
Context: the slice allowed deferring the real run if the network failed.
Options: leave checksums pending; run dev/record-checksums.sh for both tools.
Chosen: run it (the network worked, about 4 s for go and 8 s for gcloud). Results: go1.27.3 amd64 `65efbc80...79b40`, arm64 `a06e9930...65f49` (the listing and the computed value agreed, the script refuses otherwise); gcloud 592.0.0 x86_64 `2d841a23...3d50b`, arm `ba588759...e44f4d`, trust on first use (B11). Both equal the values the 0.4 spike recorded, which is the only cross-check available for gcloud. The B11 and B25 evidence tags are unchanged; the new tag is in the 4b.4 paragraph of 6.4.
Impact on the design: 6.4 "4b.4 state". How to reverse: delete the two SHA256_ lines (validate then fails until recorded again).

## [4b.4] The installers require TOOL_SHA256 and verify before extracting; validate gained a rule
Context: the design says a checksum is "required for tools with a published hash" but validate only checked both-or-neither and the hex form.
Options: leave it to the installer; add a validate rule.
Chosen: both. install.sh of go and gcloud exits 1 before downloading if TOOL_SHA256 is not 64 hex digits, downloads into a private temp folder, compares, and only then extracts, so a mismatch leaves the prefix empty. validate fails a manifest whose install.sh mentions TOOL_SHA256 (comments ignored) while the manifest has no SHA256_*; this is a text match, a lint like the rest of validate. Uppercase hex is accepted in the manifest and compared in lower case.
Impact on the design: 6.4 and the validate paragraph. How to reverse: remove the grep block in validate.

## [4b.4] gcloud: the SDK's install.sh is not run, no CLOUDSDK_CONFIG, no shell.sh
Context: Google's tarball ships an install.sh that edits shell startup files and may write config; the slice asked to decide where gcloud's config may live (6.4).
Options: run it with quiet flags; extract only and use bin/ in place; also set CLOUDSDK_CONFIG under a SwarmBox path.
Chosen: extract only, leave gcloud's default `~/.config/gcloud` (created by the user's own `gcloud auth login`, which is the user's data, in the workspace home, and survives a reset like the rest of the home). Setting CLOUDSDK_CONFIG would move users' credentials to a non-standard place for no gain. Whether the extracted bin/gcloud runs without the SDK's own install.sh (bundled Python) was not measured here [unverified]; 4b.7 runs it for real and, if it fails, the installer will run install.sh with `--quiet --path-update=false --command-completion=false --usage-reporting=false --rc-path=/dev/null`.
Impact on the design: 6.4 "4b.4 state". How to reverse: add the install.sh call.

## [4b.4] go: GOPATH and GOCACHE keep a value the user exported; the install is the plain tarball
Context: 6.12 says `GOPATH=$HOME/go`, `GOCACHE=$HOME/.cache/go-build`.
Options: assign unconditionally; default only (`${GOPATH:-$HOME/go}`).
Chosen: default only, so a user's own export (or a project tool) is not silently overridden; `$GOPATH/bin` is appended once to PATH (after the existing entries, so system tools win over a stray binary in ~/go/bin). The tarball is extracted with its top directory stripped, so GOROOT is the tool prefix and the tool needs no GOROOT variable (Go finds its root from the executable's location, which `current` links resolve) [unverified: real run in 4b.7].
Impact on the design: none beyond 6.4 state. How to reverse: assign unconditionally in go/shell.sh.

## [4b.4] Small decisions
- The maintainer script is `dev/record-checksums.sh <go|gcloud> [TOOL_CONF]`; it falls back to go.dev's `include=all` listing when the version is not in the current one (the fallback was only tested with a fake, the real `include=all` was not read [unverified]); versions `latest` or with odd characters are refused; writes are atomic (temp file then mv) and only after both downloads succeed.
- Versions pinned: go 1.27.3 (the release B25 measured) and gcloud 592.0.0 (B11). Newer releases may exist; bumping is the maintainer script's job.
- The two new test files are in ci.yml (Linux job) and in NOT_ON_MACOS (they use sha256sum, GNU chmod and bash 4 associative arrays), like the other container-program tests.
- The shim test asserts the five shims exist and that the index maps gofmt to go and gsutil and bq to gcloud; the call lifecycle is covered by test_tool_shim.


## [4b.5] NODE_MAJOR and LIBC differences: the shim warns and runs, doctor says "needs reinstall"
Context: design 6.11 says the shim warns once per entry and runs for a different NODE_MAJOR or LIBC, and also that `doctor` lists `ok`, `needs reinstall` or `missing`. It does not say which state a NODE_MAJOR difference gets in `doctor`; the slice asked to record the warn-vs-reinstall choice.
Options: doctor lists it as ok with a note; doctor lists it as `needs reinstall` (and `--fix` rebuilds it); an extra state `warn`.
Chosen: `needs reinstall` in `doctor` (the audit view should show every divergence and `--fix` should be able to clear the warning), while the shim keeps the design's behavior (warn once, run) because the tool may still work. Only ARCH refuses.
Impact on the design: 6.11 "4b.5 state". How to reverse: in `doctor_classify` set the state to `ok` when only FP_WARN is set.

## [4b.5] Exit code 69 for the ARCH refusal, "once per entry" is a marker per tool cleared by link --user
Context: the design says "refuses" and "once per entry" without a code or a mechanism.
Options: a new exit code; reuse 69 (the code of a failed install in `run`); marker in /tmp/swarmbox (per container start) or in the state dir.
Chosen: 69, because from the caller's side the tool is unavailable here, as after a failed install. Markers in `<state dir>/tool-warned/<name>`, as the slice text suggested; `link --user` (run at every entry) clears them and writes the markers of the tools it warns about, so shim calls of the same entry stay quiet. Without any `link --user` (for example a shell that never ran it) the first shim call warns once and the marker stays until the next `link --user`.
Impact on the design: 6.11 "4b.5 state". How to reverse: change fp_gate (exit code) or warned_dir (location).

## [4b.5] remove: an image-level tool IS removable; only --purge of an image manifest is refused
Context: the slice text says "remove of an image-level tool is refused" and, in the same list, "remove then run triggers a fresh first-use install", and the design says `remove claude` deletes Claude Code's paths while claude's manifest is image-level. The two cannot both hold if "remove" means the workspace install.
Options: refuse removal of anything whose manifest is image-level (then no shipped tool could be removed); remove the install for every tool and refuse only what cannot be changed, the image manifest.
Chosen: the install is workspace state for every tool, so `remove NAME` deletes it and manifests and shims stay (the next call reinstalls, 6.5). `remove NAME --purge` additionally deletes a USER-level manifest and relinks (this is where "its shim entries" go); with an image-level manifest `--purge` is refused ("part of the image"). Tests: test_tool_use_remove.py.
Impact on the design: 6.9 "4b.5 state". How to reverse: refuse in cmd_remove when MDIR is under IMAGE_TOOLS.

## [4b.5] remove of an UPDATE=self tool: own paths only, with a guard
Context: design 6.7 lists the four paths of Claude Code; the tool model is generic.
Options: hard-code the claude paths; derive them from the tool name; derive and guard.
Chosen: derive `~/.local/bin/<command>` for each PROVIDES entry plus `~/.local/share/<name>`, `~/.local/state/<name>`, `~/.cache/<name>`, and skip (with a message) any path that is or contains SwarmBox's data, state and config folders, the tools folder or the home, so a tool called `swarmbox` cannot delete the tools folder (tested). `~/.claude` and `~/.claude.json` are never touched. The release tests for the real vendor installer layout are 4b.7.
Impact on the design: 6.9 "4b.5 state". How to reverse: delete safe_rm calls.

## [4b.5] Small decisions
- `use` of the version that is already active succeeds and says so; `use` takes no new install (it never runs an installer) and does not run prepare.sh (a config rendered for another version is re-rendered at the next start).
- `new` takes `--repo` (git top level + container/tools) or `--dir DIR`; both together are a usage error. The skeleton installer exits 1 with "edit install.sh first" so an unedited skeleton can never be mistaken for a working tool.
- `doctor --fix` does not install `missing` tools (they install on first use) and uses `install_locked` with force, so a failed forced reinstall leaves that version folder removed (documented in 6.11).
- `doctor` takes the manifest's level by the same rule as `list` (the user level wins).
- The old stub tests that asserted exit 70 for use, remove, doctor and new were rewritten (test_tool_stub.py, test_tool_install.py); the three new test files are in ci.yml, NOT_ON_MACOS and CONTRIBUTING.
- test_tool_shim.py failed once in one run right after the first implementation edit, and passed in the next five runs without a change to that test (3 consecutive runs after the last edit, and the earlier ones); not reproduced, cause unknown. Recorded rather than hidden.

## [4b.6] The image-level install is a flag of install (`--image`), not a separate command or an environment variable
Context: the design says the Dockerfile runs `swarmbox-tool install` "into /opt/swarmbox/tools instead of the workspace" but gives no switch, and nothing in the program could read an install outside the workspace.
Options: an environment variable (invisible in the Dockerfile and easy to leave set); a new subcommand; a flag on install.
Chosen: `install NAME --image`, because it is visible in the Dockerfile and in the usage line, and it reuses the one installer path (one installer, two triggers).
Impact on the design: 6.8 "4b.6 state", 10.2. How to reverse: drop the flag and read an environment variable in cmd_install.

## [4b.6] Run-time lookup: workspace install if complete, else image install, else first-use install into the workspace
Context: the exit criterion asks that an image install is "not shadowed wrongly by a user-level one". The program only knew the workspace folder.
Options: the workspace always wins when it has a record; the image always wins; the workspace wins only when it is complete.
Chosen: workspace-if-complete, because a user who installs a newer version wants it, while a half-removed workspace install (a deleted binary) must not hide a working image copy. Implemented in `root_for` and used by `run`, `list`, `doctor`, the fingerprint gate and `prepare`.
Impact on the design: 6.8. How to reverse: make root_for print the workspace folder.

## [4b.6] UPDATE=self tools at the image level run their installer with HOME=/opt/swarmbox/tools/<name>/home
Context: Claude Code's vendor installer writes ~/.local/bin and ~/.local/share under HOME. At build the home is /home/agent, which is replaced by the bind-mounted workspace at run time, so an install there would vanish.
Options: leave HOME alone (the install is lost); copy the files out afterwards; give the installer its own HOME inside /opt/swarmbox/tools.
Chosen: its own HOME, set only for the installer. Measured: claude 2.1.319 installs, `claude --version` runs with the real HOME and no network. The vendor installer also writes ~/.claude and ~/.claude.json into that private home (harmless, never read at run time).
Not checked [unverified]: `claude update` of this install (the vendor updater may look at the real HOME) and its auto-update; the first one is the owner's to decide: an image-level claude is updated by rebuilding.
Impact on the design: 6.8. How to reverse: remove the ihome lines of run_installer.

## [4b.6] `prepare.sh` does not run at build
Context: prepare.sh renders files (the opencode config, the local-LLM hook) into the workspace home; at build the home is not the workspace.
Chosen: skipped with `--image`; `serve` step 7 (`swarmbox-tool prepare`) runs it for every installed tool and now sees image installs. Test: `test_image_install_does_not_run_prepare`.
How to reverse: call prepare_after_install in image mode.

## [4b.6] `install NAME` without --force is "already installed" when the image has the tool
Context: install_locked uses is_installed, which now looks at both levels.
Chosen: accepted: the user gets what they asked for (the tool is there); `--force` makes a workspace copy that then wins. Not changed to keep first-use and install consistent.

## [4b.6] The smoke test and the old tests had stale expectations that this slice corrects
Context: tests/smoke_image.py still expected one shim (claude), an empty tool-ports and "no command found but the claude shim", which stopped being true in 4b.3 (more tools, clasp's PORTS). The smoke test is opt-in, so nothing failed. The first run on the new image found one more: clasp's shell.sh defines a shell function named clasp, so `command -v clasp` prints `clasp`, not the shim path.
Chosen: the steps list all seven tools and eleven commands, use `type -P` (ignores functions), expect tool-ports to be exactly `clasp 43323`, add a `mcp-generated` step (chrome-devtools, no npx), and `no-agent` also requires /opt/swarmbox/tools to be empty in a default build. The rule that smoke code never names 43323 is narrowed to never binding or publishing it.
How to reverse: git revert.

## [4b.6] Real build, recorded
`dev/dev-build.sh --build-arg WITH_TOOLS=claude`: 117 s with warm layers (the full cold build was not repeated), image 2,092,380,207 bytes, 325 MB in /opt/swarmbox/tools, 0 entries not owned by agent. A default build of the same Dockerfile passes the reduced smoke steps ready, tmpfs-restart, page-built, tool-validate, tool-shim, tool-index-ports, mcp-generated, attach-session, no-agent, up-lifecycle, up-busy-port (nested-podman and nested-cgroup skipped: third nesting level). `WITH_TOOLS=nonesuch` fails the build at the RUN with exit 1. Images swarmbox-test-4b6-img, -def and the failed build's dangling intermediate were removed by name or ID; nothing else was created.
A tool at the image level is not read by `swarmbox-tool link --user`'s fingerprint scan (that scans the workspace); the shim's gate reads the right record for the tool it runs. Same image on both sides makes this a non-issue except for ARCH, which a baked image cannot have wrong.


## [4b.7] The side-effects check separates the installer from the first run of the program
Context: the first real run (clasp, go) failed the "no side effects" check for Go: `go version` itself wrote `~/.config/go/telemetry`. That is the program's own state, not the installer's doing, and the design rule (6.4, 6.9) is about the installer.
Options: allow a per-tool list of run-time paths; scan after the first call through the shim; run `swarmbox-tool install <tool>` alone, scan, then run the program.
Chosen: install alone, scan strictly (only the tool's folder, SwarmBox's state and the npm cache are allowed), then run the program and only REPORT what it wrote outside the prefix. No per-tool allow list exists, so a new installer cannot hide behind one. Cost: the real test no longer exercises the first-call-through-the-shim path for the six tools (4a.4 covers it with fakes for every shell and 4a.6 with the real installer for Claude Code). [unverified] for the six tools through the real shim.
Impact on the design: 6.9 "4b.7 state". How to reverse: make setUpClass call the command directly and add allow lists.

## [4b.7] Two installers broke the hard rules of 6.4 and were fixed
Context: with the strict scan, `gemini` wrote 2811 files to `~/.cache/node-gyp` (a native dependency; node-gyp unpacks the Node headers into its devdir) and `opencode` wrote `~/.local/share/opencode/log/opencode.log` (the postinstall of `@opencode/cli` runs the program). The fake-installer tests of 4b.2 and 4b.3 could not see either.
Options: allow those paths in the test; delete them at the end of the installer; run npm in a scratch environment.
Chosen: scratch environment for `gemini`, `clasp` and `opencode` (all three are npm installers; clasp had no problem but shares the shape): `mktemp -d`, removed by a trap, `npm_config_devdir` and `XDG_DATA_HOME`, `XDG_STATE_HOME`, `XDG_CONFIG_HOME`, `XDG_CACHE_HOME` pointing into it for the `npm install` and the `npm cache clean`. `NPM_CONFIG_CACHE` is explicit in the image, so the npm cache is unaffected. Fake-npm tests were written first and failed (the variables were unset). Risk: a postinstall that must keep state in the real XDG folders would lose it; none does today (the log is regenerated at the first run). `poetry`, `go` and `gcloud` are not npm and showed no violation.
Impact on the design: 6.4 rules hold; 6.9 "4b.7 state". How to reverse: remove the `scratch` block from the three installers (the real test then fails again).

## [4b.7] npm cache residue: two files are accepted
Context: `npm cache clean --force` leaves `_logs/` and, as measured, an empty `_update-notifier-last-checked` marker in `/opt/npm-cache`.
Chosen: the cache rule is "no file except those two"; the test names them (`CACHE_RESIDUE`). Anything else (blobs, indexes) fails.
How to reverse: empty the tuple and have the installers remove the folder.

## [4b.7] A named volume stands in for the "temp bind mount"
Context: the slice text says a second container on the same temp bind mount. In this nested rootless Podman the container's uid 1000 maps to a sub-uid, so a bind-mounted mktemp folder owned by the host's uid 1000 is not writable by `agent`.
Chosen: a fresh named volume `swarmbox-test-4b7-vol-<rand>` (what 4a.6 did; it takes the image's ownership of `/home/agent`), removed by exact name. The reset is `podman rm` of the container and a new container on the same volume. Same guarantee, different mount kind. The real `swarmbox` start path (host helper, `--userns=keep-id`) was not used: reduced, like the Phase 2 and 3 container tests (the entrypoint does not run; `sleep` is the command).
How to reverse: none needed.

## [4b.7] The real tests are a scheduled job plus a harness that runs on every push
Context: design 13.4 puts the real-installer tests on a schedule.
Chosen: a `real-tools` job in `ci.yml` with `if: schedule or workflow_dispatch`, which builds the image and fails when any real test is skipped; `tests/test_tool_real.py` is also in the linux job (its real classes skip there, its harness classes run) and in the macOS exclusion list. The job has never run on a runner [unverified], same as every other job.
How to reverse: delete the job and the entry in the linux job.

## [4b.7] OpenCode 2.x shared background server: observed only
Context: the risk note says never start it on a fixed port and record what is seen.
Observed: `opencode --version` (2.2.6) exits at once and no TCP socket was listening afterwards (`/proc/net/tcp*` state 0A, empty). Other subcommands (which may start the server) were NOT run, so the open item of 4b.2 stays open.

## [4b.7] Per-tool outcome and the gate are `partial`
All six tools pass both real checks here (install as uid 1000, no side effects, cache rule, second call, survives a reset): nothing is recorded as reduced or blocked for size or network. They are reduced in these ways, all stated in 6.9: no real `swarmbox` start (no host helper, no `serve`), amd64 only, no CI runner. The 4b.gate row is `partial` because CI never ran (the same reason as every earlier gate) and the first-call-through-the-real-shim of the six tools is unverified.

## [4b.7] The SIGINT "flake" of test_serve_steps and test_host_up is explained: it is a background launch
Context: slice 2.7 recorded an unexplained SIGINT flake in test_serve_steps; in this slice the full regression, started with `( ... &)` from a non-interactive shell, failed test_serve_steps and test_host_up (the SIGINT tests: `test_sigint_leaves_no_lock`, serve's SIGINT) twice, while both files passed alone and in a foreground run of `run_all.sh --only`.
Observed: started in the background the same way, `run_all.sh --only test_serve_steps.py` fails again; in the foreground it passes. A non-interactive shell starts background jobs with SIGINT ignored and the children inherit that, so a test that sends SIGINT to its child cannot work. This is the likeliest cause of the 2.7 flake too [unverified for 2.7: the cause was not examined then].
Chosen: no code change. The full-regression numbers below combine the background run (61 files OK) with the foreground run of the two files. To run the whole regression in the background, start it with `setsid` or from an interactive shell. Not fixed in the tests (they could reset the disposition with `trap - INT` in a wrapper): left for the owner.

## [4b.7] The real-tools CI step must not swallow the test's exit status (review fix, round 1)
Context: the step ran `python3 tests/test_tool_real.py 2>&1 | tee real.out` in GitHub's default `bash -e {0}`, which has no pipefail, so the pipeline status was tee's and a failing real-installer test would not fail the scheduled job; only the "skipped" grep could. Read from the YAML; the job has never run on a runner [unverified].
Options: `shell: bash` (runs `-e -o pipefail`); `set -o pipefail` in the script; redirect to a file and check `$?`.
Chosen: both `shell: bash` and `set -o pipefail` as the first line, because the explicit line stays correct if the shell setting is changed, and a test now asserts both (tests/test_ci_workflow.py).
Impact on the design: none.
How to reverse: remove the `shell:` key and the `set -o pipefail` line, and the assertions.

## [4b.7] The real test cleans up even when its setup fails (review fix, round 2)
Context: `Real.setUpClass` created the volume and a container, but unittest does not call `tearDownClass` when `setUpClass` raises. A missing `SWARMBOX_IMAGE_TAG` image left one `swarmbox-test-4b7-vol-*` volume per tool (6 reproduced by the reviewer).
Options: wrap setUpClass in try/except and clean up; `addClassCleanup` registered before anything can fail.
Chosen: `addClassCleanup` (volume first, then the box list, so boxes go first) replaces `tearDownClass`; `Box.__init__` removes its own half-created container before raising; `setUpModule` checks `podman image exists` for a given tag and fails once before any volume is created. Two default-mode tests with a fake podman assert both (a failing `run` still gets `volume rm -f` and `rm -f -t 0`; a missing image creates no volume).
Impact on the design: none.
How to reverse: restore `tearDownClass` and drop the image check and the two tests.

## [5.1] cloudflare-setup.py: session kept on rerun, remove stops the connector, pinned image
Context: design 5.2 and 12.3 listed three changes to the script before `swarmbox remote` wraps it: the 4h default reset the session on every rerun, `remove` left the connector running, and the image was `:latest`.
Options: (session) keep it only in cloudflare.json, only on the Access app, or both; (connector stop) always stop, never stop, or stop when no other hostname uses the tunnel; (image) a version tag or a digest.
Chosen: (session) `--session` defaults to None. Order: explicit flag, then the value on the existing Access app (the source of truth), then the `session` key now saved in cloudflare.json (covers an app deleted by hand), then 4h for a first setup. cloudflare.json is written only by non-dry runs, with the same code as before (no chmod added; it never holds a secret). (connector) `remove` reads the tunnel's ingress after dropping this hostname's rule (also in `--dry-run`, where the PUT is not sent); if the tunnel exists and no other hostname remains, it runs `podman rm -f swarmbox-cloudflared` only when `podman inspect` finds the container, and with `--dry-run` only prints "would stop and remove". If the tunnel is not found (or is locally managed) the connector is left alone, because nothing proves it is unused. The tunnel itself is never deleted. (image) pinned tag `docker.io/cloudflare/cloudflared:2026.10.7`, the newest numbered tag in Docker Hub's tag list read on 2026-11-08 (the ones above it were `latest` and an old `2002-...` build). `--connector-image` beats `SWARMBOX_CLOUDFLARED_IMAGE`, which beats the default. A tag is easier to read and bump than a digest; D39-style digest pinning is not applied.
Impact on the design: 5.2 and 12.3 updated (the three `[today]` markers are now changes made in 5.1). The pinned image was NOT pulled or run here [unverified]. A connector container created earlier with `:latest` is not recreated by `apply` (it only compares the token), so an existing box keeps its old image until `remote off` and `remote setup`; the helper's `up` logic (later slices) must use the same pin. `lib/web.sh` (v0.1.0) still says `:latest` and stays until Phase 6.
How to reverse: set DEFAULT_CONNECTOR_IMAGE back, restore the `default="4h"` and drop the saved key, delete `step_connector_off` and its call in `cmd_remove`.

## [5.2] swarmbox remote: a thin exec wrapper over cloudflare-setup.py
Context: `remote` answered "not implemented" (exit 70). The slice asked for setup, status, off and token over the script, with the script found next to the helper, python3 checked first, NAME and WEB_PORT as defaults, a shared cloudflare.json folder, and the tunnel token passed "only to commands that need it".
Options: (script lookup) the directory of `$0`, a fixed path under `~/.local/share/swarmbox/host`, or the repository path; (options) a whitelist parsed in sh, or everything after the subcommand passed through; (tunnel token) pass it to some commands, to all, or to none.
Chosen: (lookup) the directory of `$0`, because it is how `VERSION` and `tool-ports` are found already, so the helper and the script always come from the same extracted archive (the Dockerfile copies `cloudflare-setup.py` next to the helper); symlinks are not followed, as for `VERSION`. A missing script is exit 3 with the advice to run `swarmbox update`. (options) everything after the subcommand goes through unchanged and argparse in the script validates it (its usage errors are exit 2); the wrapper puts `--name "$SWARMBOX_NAME|swarmbox" --port <resolved WEB_PORT>` first so an explicit user option wins. Only `setup`, `status`, `off` and `token` are accepted, the script's own names (`apply`, `remove`) are exit 2 with the usage, so the surface stays the one design 3.7 documents. (tunnel token) to no command: the script never reads `SWARMBOX_CLOUDFLARE_TUNNEL_TOKEN` (it asks the API for the tunnel's token), so the wrapper unsets it in the script's environment instead of widening where a secret goes. The token of the config is for the connector logic of `up`, a later slice. The wrapper `exec`s python3, so the script's exit code is the wrapper's. `XDG_CONFIG_HOME` is set to the folder holding `CFG_ROOT`, because the script reads the variable as it is (relative or empty values included) while the helper ignores such values; this keeps `cloudflare.json` the file `url` reads. Check order: subcommand (2), python3 (3), script (3), then WEB_PORT/NAME validation (2).
Impact on the design: 3.7.2 table row and 3.1 state text rewritten (no more "not implemented"), a 5.2 state paragraph added. `tests/test_host_config.py` no longer expects exit 70 for `remote`; a bare `remote` is usage (exit 2). Not done in this slice: the connector on every entry; the real end-to-end run (no Cloudflare account here) [unverified]. The stub script stands for the real one in most tests; two tests run the real script only as far as argument parsing and its "no API token" refusal.
How to reverse: restore the `remote)` branch that dies with 70, delete `cmd_remote`, `tests/test_host_remote.py` and the `remote` lines of the shells test, and revert the design text.

## [5.3] The tunnel token: setup offers to store it, never stores it unasked
Context: the slice asked that `remote setup` "offers (never forces, and only on a terminal) to store the tunnel token, or prints the exact command", a `resolve_tunnel_token` helper, and a `remote token` that prints only the token. Most of the reading rules existed since 3.1 (`resolve`, `cfg_prepare`, the mode check).
Options: (a) only print the command, as the script does today; (b) print the commands and ask a [y/N] question, default no; (c) store the token automatically after a successful setup.
Chosen: (b), because it follows the slice goal literally and a stored secret should be the person's decision. The default answer is no, anything but y/yes is no, and without a terminal (stdin or stderr not a tty), with `--dry-run`, or after a failed setup nothing is printed or asked. It is also skipped when a token is already resolvable (checked before the wrapper unsets `SWARMBOX_CLOUDFLARE_TUNNEL_TOKEN` for the script; the first run of the new test found the bug: the offer appeared although the variable was set). On yes the epilogue calls the script's `token` command (it needs the API token, from `CLOUDFLARE_API_TOKEN` or the script's own hidden prompt) and keeps the output in a shell variable, then writes it with `cfg_write_keys` (umask 077, chmod 600, atomic rename), so no argv or terminal echo ever holds it. Failure to fetch, a malformed token or a failed chmod print one line, store nothing and leave the exit code of setup (0) alone. `remote setup` therefore stopped being an `exec` (the other subcommands still are); the script's exit code is kept. `config get CLOUDFLARE_TUNNEL_TOKEN` now goes through `resolve_tunnel_token` (same behavior). The script's own v0.1.0 wording ("export SWARMBOX_CLOUDFLARE_TUNNEL_TOKEN=... ./cloudflare-setup.py token") is unchanged and still printed before our text: not edited, to leave its tested output alone; to reconcile in Phase 6 when the old entry points go.
Impact on the design: 5.2 gets a "5.3 state" paragraph. The prompt text and the [y/N] default are new behavior. The terminal-only code is tested with a python pty and a stub script; with the real script and a real account it is [unverified]. One test-only mistake along the way: a test left a mode 400 file and failed to rewrite it (fixed in the test).
How to reverse: restore the single `exec` in `cmd_remote` and delete `remote_token_epilogue`; keep `resolve_tunnel_token`.

## [5.4] The connector step of up: position, failure policy, one connector per host, environment-only image
Context: the slice asked that every entry makes sure `swarmbox-cloudflared` is up using the host token, with a pinned image, without disturbing the hot path of `up`. Points the documents left open: where in `up` it runs, what a failure does, how two boxes share it, whether `CLOUDFLARED_IMAGE` is a config key, how to do the exact-name check, whether `reset` runs it.
Options: (position) before the box start, after readiness, or after the connection step; (failure) warn, or fail `up` with a new exit code; (names) one fixed connector, or one per box; (image key) add a config key, or environment only; (exact name) `podman container exists` plus an inspect, or one inspect that prints the name; (reset) run it or not.
Chosen: (position) last in `cmd_up`, after readiness and the host connection, under the lock, because the box must never wait on the network or on an image pull of the connector and a failure there cannot leave the box half made. (failure) warn only, exit codes of `up` unchanged, because the box is usable without the connector and exit 7 and its neighbours already mean specific box problems. (names) one connector per host with the fixed name, because the design (5.2, 5.1 `remove` logic) already models many hostnames on one tunnel; a second box with another SWARMBOX_NAME just finds it. Consequence: the connector's token is the one of whichever box entry runs, so two boxes with different tunnel tokens would recreate it on each other's entries; that is a misconfiguration, not supported, and not detected. (image key) environment only, because the 8.2 table says the config file column is "none"; the task text said "if the table lists it as host/runtime", and the table lists it with no file key, so a `CLOUDFLARED_IMAGE` config line is an unknown key (warned). The planned test name "image override by config" became a test that the config line is not honored. (exact name) one inspect that prints `{{.Name}}`, compared with the fixed name, because that is how 3.7.2 step 3 already does it for the box and it keeps the running case to one call; the `container exists` of the slice text is not used (the design allows either). (reset) not run: reset replaces the box, not the connector, and the next `up` or entry fixes the connector anyway. `--user root` is kept from the script (5.1 comment): in rootless Podman it is the caller's own user and it avoids mapping the image's user 65532, which fails in a nested container.
Impact on the design: 3.7.2 gets a step 7 (connector) and the lock release is step 8; 5.2 gets a "5.4 state" paragraph and its `[today]` notes are adjusted; the 8.2 row says environment only. The tests helper FakePodman now records TUNNEL_* environment variables per call (`FakePodman.envs()`), so the secret path is testable. Not done: a real image pull or cloudflared start (unverified); reacting to a changed image pin on an existing connector (a connector with the old image and the same token is left running, as in 5.1; recreate it with `podman rm -f swarmbox-cloudflared` or change the token). Process note: the code was written before the tests in this slice.
How to reverse: delete `connector_ensure` and its call in `cmd_up`, the 3.7.2 step 7 and the 5.4 paragraph, `tests/test_host_connector.py`; the helper change to the fake is harmless.

## [5.5] url and remote status share one saved host name; status adds host-side lines
Context: `url` printed `<name>.<domain>` while the script could serve a `--hostname`, so the two could disagree; `remote status` was a bare `exec` of the script with no host-side facts. The slice asked for "hostname" in cloudflare.json, host lines in status, and no Podman in `url`.
Options: (hostname key) one global "hostname" key, or a key plus the box name it belongs to; (script rerun) ignore the saved name or reuse it; (status) keep `exec`, or run the script and append lines; (lines on a script failure) always or skip.
Chosen: save `"hostname"` together with `"name"` and honor the saved hostname only for the same box name and inside the domain in use, because cloudflare.json is shared by every box on the host and a bare global hostname would be printed for a second box named differently. The script reuses it for rerun/status/off without `--hostname` (same rule as `url`), so `remote off` removes what `setup --hostname` created. `status` runs the script, keeps its exit code and appends an `On this host:` block (public address, connector, login session) unless the exit code is 2 (usage errors; the block would be noise); a missing or failing podman prints "connector: unknown" and never changes the exit code. The connector is read with one inspect of the exact fixed name. `url` keeps no Podman call and reads no labels: the design allows labels only for `remote status`, and the connector line does not need them. The shared code is `public_host`; JSON read with sed stays POSIX. An old cloudflare.json (no new keys) behaves as before. A bad saved host name is warned about and the name.domain form is used.
Impact on the design: 3.3 url text, the 5.2 table row for status and a "5.5 state" paragraph; Part B untouched. test_cloudflare_setup's key-set assertion now includes hostname and name. Process notes: the implementation was written right after the tests in the same step, so the helper url tests were not seen failing first (the script tests were); a test-only JSON fixture was written without indent and failed until fixed; shellcheck rejected backticks in single quotes and one bad quote nesting, both fixed. If status exits 2 because the hostname is exposed (if the script uses that code for status) the host block is skipped; not checked [unverified].
How to reverse: restore the single exec for status, delete `remote_host_lines`, `public_host` back into `cmd_url`, drop the two keys and the saved-hostname rule from the script.

## [5.6] Remote docs rewritten in Phase 5; CI and CONTRIBUTING registration fixed; checklist is a blocked status row
Context: the slice asked for docs/cloudflare.md for `swarmbox remote`, an owner checklist, test registration and cross-reference fixes. The plan listed the rewrite of docs/cloudflare.md under Phase 6. tests/test_ci_workflow.py and tests/test_repo_files.py were already failing on HEAD: slices 5.2 and 5.4 added test_host_remote.py and test_host_connector.py but not to ci.yml or CONTRIBUTING.md (run_all.sh discovers files by glob, so it did not notice).
Options: (doc timing) rewrite in Phase 5, or leave for Phase 6; (docs shape) one file with the checklist inside, or a separate checklist file; (checklist status) a row marked partial/done, or blocked; (CI) list the new tests in the Linux and macOS jobs, or Linux only.
Chosen: rewrite now, in docs/cloudflare.md with the checklist as its last section, because the slice says so and the wrapper exists; the status row `5.owner-checklist` is `blocked` because no real account can be used here and calling it partial would hide that nothing was run; both test files go to the Linux and macOS jobs (neither is in NOT_ON_MACOS: they need only python3 and sh, and macOS python3 is B15) and to CONTRIBUTING.md. The doc says `swarmbox remote off` asks for confirmation unless -y (the script's remove behavior) and that the reboot case is [unverified] (B16). Nothing in README changed (Phase 6). The doc keeps one remark that `start.sh --web` was the v0.1.0 way, as history.
Impact on the design: 5.2 gets a "5.6 state" paragraph; plan phase 5 notes that docs/cloudflare.md is done there and Phase 6 no longer lists it as a rewrite. New tests in tests/test_docs_consistency.py (PhaseFiveDocsTest) tie the doc to the helper's usage line, the script's options and the pinned image. No Part B fact closed.
How to reverse: revert the commit; remove the two test names from ci.yml and CONTRIBUTING.md only together with the test files.
