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
