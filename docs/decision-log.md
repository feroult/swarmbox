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
