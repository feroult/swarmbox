# Mutation baseline of the old test suite

`dev/mutate.py` applies one small change at a time to a product file and runs the test files that cover it; a mutant is *killed* when a test file fails and *survived* when every selected file passes (nothing checks that behaviour). Mutants are chosen by a seeded random draw weighted to the logic that can regress; the plan is a list of exact text replacements, so the **same 250 mutants can be replayed against any later suite** (`python3 dev/mutate.py run --plan plan.json ...`; a mutant whose text is gone is reported as stale).

## How it was run

- Suite: the old `tests/test_*.py` at commit `ff7ddf6` (102 files, 1849 tests).
- World: Podman, `--network none --read-only`, tmpfs `/tmp` and `/work`, the image with tmux 3.5a, ttyd and chromium, `SWARMBOX_TEST_REAL_TMUX=1` (the gated real-tmux and browser files run).
- Every mutant: a private copy of the repository, a private `TMPDIR` and `HOME`, **every** test file that refers to the product file (`--all-tests`, so the kill matrix is complete), a failing file run a second time (`--confirm`: a file that then passes is flaky, not a kill), per-file timeout 400 s, per-mutant 1800 s, 18 mutants in parallel.
- Controls: each product file's tests were also run with no mutation (`--control`); a failing control names a test that is not parallel-safe.

## Result

250 mutants were planned in 40 product files (two identical-looking `||` replacements on one line of `release-check.sh` shared an id, so 249 distinct results): **180 killed (2 of them by a hang that a test file noticed as a timeout), 69 survived**, 72 % killed.

Controls that failed without any mutation (9 of 40): all name `test_sysop_real.py`. Its test `test_stop_ends_the_goal_and_nothing_more_is_typed` ends with `pgrep -f fixtures/sysop/bin/claude` over the whole machine, so it fails whenever another mutant's fake `claude` is running in parallel. Every one of the 67 mutants on which it failed was therefore run again with that file alone, one at a time (`-j 1`, `--tests test_sysop_real.py`; 13 of them became survivors) and the kill matrix keeps the serial result. This is a bug of the test for the area agents: it must look only at its own processes (by PID or by the private folder), and it also breaks `tests/run.sh slow -j 3` when two sysop files run together.

Per product file:

| Product file | Mutants | Killed | Survived | Kill rate |
|---|---|---|---|---|
| `container/addons/sysop/lib/swarmbox_sysop/risk.py` | 21 | 15 | 6 | 71 % |
| `container/addons/sysop/lib/swarmbox_sysop/policy.py` | 14 | 12 | 2 | 86 % |
| `container/addons/sysop/lib/swarmbox_sysop/brain.py` | 6 | 5 | 1 | 83 % |
| `container/addons/sysop/lib/swarmbox_sysop/service.py` | 7 | 3 | 4 | 43 % |
| `container/addons/sysop/lib/swarmbox_sysop/mcpserver.py` | 7 | 6 | 1 | 86 % |
| `container/addons/sysop/lib/swarmbox_sysop/panel.py` | 7 | 7 | 0 | 100 % |
| `container/addons/sysop/lib/swarmbox_sysop/dock.py` | 6 | 5 | 1 | 83 % |
| `container/addons/sysop/lib/swarmbox_sysop/watch.py` | 4 | 2 | 2 | 50 % |
| `container/addons/sysop/lib/swarmbox_sysop/audit.py` | 6 | 6 | 0 | 100 % |
| `container/addons/sysop/lib/swarmbox_sysop/ipc.py` | 2 | 2 | 0 | 100 % |
| `container/addons/sysop/lib/swarmbox_sysop/keys.py` | 4 | 4 | 0 | 100 % |
| `container/addons/sysop/lib/swarmbox_sysop/config.py` | 2 | 1 | 1 | 50 % |
| `container/addons/sysop/lib/swarmbox_sysop/busclient.py` | 2 | 1 | 1 | 50 % |
| `container/addons/sysop/lib/swarmbox_sysop/tabsclient.py` | 2 | 1 | 1 | 50 % |
| `container/addons/sysop/lib/swarmbox_sysop/cli.py` | 3 | 2 | 1 | 67 % |
| `container/scripts/swarmbox-bus.py` | 18 | 6 | 12 | 33 % |
| `container/scripts/swarmbox-tabs.py` | 25 | 21 | 4 | 84 % |
| `container/host/swarmbox-host` | 20 | 13 | 7 | 65 % |
| `container/scripts/swarmbox-addon.sh` | 18 | 9 | 9 | 50 % |
| `container/entrypoint.sh` | 16 | 15 | 1 | 94 % |
| `container/scripts/swarmbox-web.sh` | 5 | 4 | 1 | 80 % |
| `container/scripts/swarmbox-attach.sh` | 4 | 3 | 1 | 75 % |
| `container/scripts/swarmbox-shim.sh` | 1 | 1 | 0 | 100 % |
| `container/scripts/swarmbox-install.sh` | 2 | 2 | 0 | 100 % |
| `container/scripts/swarmbox-mcp.sh` | 2 | 2 | 0 | 100 % |
| `container/scripts/banner.sh` | 1 | 1 | 0 | 100 % |
| `container/scripts/swarmbox-statusline.sh` | 1 | 0 | 1 | 0 % |
| `container/web/build-index.sh` | 1 | 1 | 0 | 100 % |
| `container/web/ttyd-clipboard.js` | 2 | 2 | 0 | 100 % |
| `container/addons/voice/web/page.js` | 3 | 2 | 1 | 67 % |
| `container/addons/voice/lib/swarmbox_voice/front.py` | 11 | 9 | 2 | 82 % |
| `container/addons/voice/lib/swarmbox_voice/server.py` | 6 | 3 | 3 | 50 % |
| `container/addons/voice/lib/swarmbox_voice/stt.py` | 4 | 3 | 1 | 75 % |
| `container/addons/voice/lib/swarmbox_voice/config.py` | 1 | 1 | 0 | 100 % |
| `dev/release.sh` | 4 | 3 | 1 | 75 % |
| `dev/release-check.sh` | 2 | 1 | 1 | 50 % |
| `dev/release-version.sh` | 1 | 1 | 0 | 100 % |
| `dev/record-checksums.sh` | 1 | 0 | 1 | 0 % |
| `install.sh` | 3 | 3 | 0 | 100 % |
| `cloudflare-setup.py` | 4 | 2 | 2 | 50 % |

By kind of mutation:

| Kind | Mutants | Killed | Survived |
|---|---|---|---|
| negate-cond | 41 | 37 | 4 |
| compare | 34 | 25 | 9 |
| boolop | 25 | 17 | 8 |
| drop-call | 24 | 11 | 13 |
| sh-and-or | 21 | 15 | 6 |
| sh-negate | 16 | 14 | 2 |
| const | 14 | 11 | 3 |
| sh-delete | 14 | 4 | 10 |
| exit-code | 13 | 9 | 4 |
| bool-const | 10 | 5 | 5 |
| sh-case | 10 | 9 | 1 |
| sh-test-flag | 4 | 4 | 0 |
| sh-cmp | 4 | 4 | 0 |
| not-removed | 3 | 3 | 0 |
| return-none | 3 | 3 | 0 |
| sh-str-eq | 3 | 2 | 1 |
| js-cmp | 3 | 2 | 1 |
| arith | 2 | 1 | 1 |
| sh-const | 2 | 1 | 1 |
| loop-ctl | 1 | 1 | 0 |
| js-andor | 1 | 1 | 0 |
| js-const | 1 | 1 | 0 |

## Which test files do the killing

The matrix (`mutants-kill-matrix.json`, mutant to the test files that killed it, with the plan `mutants-plan.json`, both in this folder) is what the Integrate step compares a new suite with: `python3 dev/mutate.py run --plan mutants-plan.json ...` replays the same mutants. *Sole* means that no other file killed the mutant: deleting that file without moving the case loses the kill.

| Test file | Mutants killed | Sole killer of |
|---|---|---|
| `test_sysop_review.py` | 28 | 0 |
| `test_sysop_policy.py` | 27 | 9 |
| `test_sysop_mcp.py` | 24 | 1 |
| `test_tabs.py` | 21 | 6 |
| `test_sysop_soak.py` | 20 | 4 |
| `test_sysop_real.py` | 17 | 0 |
| `test_sysop_panel.py` | 16 | 2 |
| `test_tabs_real.py` | 15 | 0 |
| `test_sysop_service.py` | 14 | 1 |
| `test_sysop_dock.py` | 11 | 0 |
| `test_sysop_always.py` | 10 | 0 |
| `test_serve_steps.py` | 10 | 8 |
| `test_host_config.py` | 9 | 2 |
| `test_entrypoint.py` | 9 | 4 |
| `test_voice_front.py` | 9 | 9 |
| `test_voice_service.py` | 8 | 3 |
| `test_install.py` | 8 | 4 |
| `test_sysop_brain.py` | 7 | 2 |
| `test_sysop_web.py` | 7 | 0 |
| `test_voice_web.py` | 7 | 1 |
| `test_addon_install.py` | 7 | 3 |
| `test_sysop_addon.py` | 6 | 1 |
| `test_bus.py` | 6 | 3 |
| `test_security_review.py` | 6 | 0 |
| `test_clipboard_bridge.py` | 6 | 1 |
| `test_web_strip.py` | 6 | 1 |
| `test_sysop_keys.py` | 5 | 3 |
| `test_host_shells.py` | 5 | 0 |
| `test_web_build.py` | 5 | 0 |
| `test_host_up.py` | 4 | 0 |
| `test_attach_command.py` | 4 | 2 |
| `test_voice_soak.py` | 4 | 0 |
| `test_sysop_bus.py` | 3 | 0 |
| `test_host_create_flags.py` | 3 | 0 |
| `test_host_update.py` | 3 | 1 |
| `test_swarmbox_command.py` | 3 | 0 |
| `test_addon_prepare.py` | 3 | 0 |
| `test_addon_new.py` | 3 | 0 |
| `test_release_script.py` | 3 | 3 |
| `test_host_socket.py` | 2 | 0 |
| `test_addon_opencode.py` | 2 | 0 |
| `test_addon_go_gcloud.py` | 2 | 0 |
| `test_addon_gemini_clasp_poetry.py` | 2 | 0 |
| `test_mcp_registry.py` | 2 | 2 |
| `test_voice_page_browser.py` | 2 | 2 |
| `test_cloudflare_setup.py` | 2 | 0 |
| `test_host_remote_e2e_fake.py` | 2 | 0 |
| `test_sysop_watch.py` | 1 | 1 |
| `test_tabs_redact_dos.py` | 1 | 0 |
| `test_host_remote.py` | 1 | 0 |
| `test_pubkey_ensure.py` | 1 | 0 |
| `test_addon_shim.py` | 1 | 1 |
| `test_banner_glint.py` | 1 | 1 |
| `test_build_index.py` | 1 | 0 |
| `test_web_style.py` | 1 | 0 |
| `test_voice_config.py` | 1 | 0 |
| `test_release_check.py` | 1 | 1 |
| `test_release_version.py` | 1 | 1 |

Test files that killed nothing in this sample: `test_addon_agent_shell.py`, `test_addon_link.py`, `test_addon_manifest.py`, `test_addon_real.py`, `test_addon_stub.py`, `test_addon_voice.py`, `test_banner.py`, `test_bashrc_fragment.py`, `test_default_names_lint.py`, `test_dockerfile.py`, `test_docs_consistency.py`, `test_helpers.py`, `test_host_connector.py`, `test_image_with_addons.py`, `test_nested_fuse_real.py`, `test_no_old_names.py`, `test_pull_ui.py`, `test_record_checksums.py`, `test_statusline.py`, `test_theme.py`, `test_voice_page.py`. (A file that killed nothing may still guard a past bug that no sampled mutant resembles; this is a sample of 250, not a proof.)

## The survivors that matter most

Read from the table below: behaviour that a release, a security rule or a validator depends on and that no test of the old suite fails for. Each needs a test in the new suite (the mutant ids replay against it):

- `container/addons/sysop/lib/swarmbox_sysop/risk.py:399` (flip In -> NotIn): publishing commands (twine upload, cargo publish, gem push) are rated high by `cmd in (...)`; no test runs one of them
- `container/addons/sysop/lib/swarmbox_sysop/risk.py:421` (And -> Or): `kubectl delete` and `terraform destroy|apply` are rated high; no test distinguishes the two clauses (and/or)
- `container/addons/sysop/lib/swarmbox_sysop/config.py:90` (Or -> And): settings validator: a newline or CR inside a setting value (not `brain`) is accepted once the NUL test is false; no test feeds one
- `container/scripts/swarmbox-bus.py:198` (drop the call): the broker socket is made 0600; no test checks the mode of bus.sock
- `container/host/swarmbox-host:647` (return 1 -> return 0): settings validator: a `voice.stt.model` with characters outside [a-z0-9._-]: no test checks that it is refused (the function would answer 0 after its message)
- `container/host/swarmbox-host:650` (the branch voice.stt.vocabulary never matches): settings validator: nothing checks the rules of `voice.stt.vocabulary` (at most 500 characters, no forbidden character): without its branch every value is accepted and no test notices
- `container/host/swarmbox-host:2306` (return 1 -> return 0): the helper archive check refuses a hard link entry; no test has an archive with one
- `container/scripts/swarmbox-addon.sh:695` (|| -> &&): `run_installer || status=$?` turned into `&&`: the status of a failed installer is lost; no test makes an installer fail at this call and checks the exit status
- `dev/release.sh:291` (= -> !=): the release verification (`manifest of the new tag == serve == latest`, at least two architectures) is checked by one test file that never reaches the failing branch
- `cloudflare-setup.py:424` (drop the call): `die` when the DNS name already has a record of another kind (never replace it); no test covers that refusal

## Survivors

Behaviour that no test of the old suite checks (as far as these mutants reach). The line is the mutated source line; *files* is how many test files were run against it. The importance column is a reading of the line, not a measurement.

| Product file:line | Mutation | Source line | Test files | Importance |
|---|---|---|---|---|
| `sysop/risk.py:19` | const: constant 4 -> 5 | `_MAX_DEPTH = 4` | 9 | medium: depth limit of the shell-in-shell unwrapping of the risk classifier (4): no test nests deeper than the limit |
| `sysop/risk.py:243` | compare: flip Gt -> GtE | `or (a.startswith("+") and len(a) > 1) for a in rest)` | 9 | medium: the risk classifier's rule for a `+x` argument of length 1 versus longer (a bare `+`) |
| `sysop/risk.py:293` | compare: flip In -> NotIn | `code = [a.split("=", 1)[1] for a in args if "=" in a]` | 9 | medium: the code argument of `name=code` options is taken only when there is an `=`; the case without one is not pinned |
| `sysop/risk.py:304` | compare: flip Eq -> NotEq | `elif cmd == "enable" and any(a == "-f" for a in rest):` | 9 | medium: `enable -f` (load a builtin from a file) is rated by its flag; the plain `enable` case is the only one tested |
| `sysop/risk.py:399` | compare: flip In -> NotIn | `(cmd in ("twine", "cargo", "gem") and rest[:1] in (["upload"], ["publish"], ["push"]))):` | 9 | IMPORTANT: publishing commands (twine upload, cargo publish, gem push) are rated high by `cmd in (...)`; no test runs one of them |
| `sysop/risk.py:421` | boolop: And -> Or | `(cmd == "kubectl" and rest[:1] == ["delete"]) or (cmd in ("terraform", "tofu") and rest[:1] in (["destroy"], ["apply"])) or` | 9 | IMPORTANT: `kubectl delete` and `terraform destroy|apply` are rated high; no test distinguishes the two clauses (and/or) |
| `sysop/policy.py:301` | bool-const: True -> False | `dirty = True` | 5 | medium: the approval-dialog rule (a non-Esc key on a dialog sets `dirty`); only the Esc and typed-text paths are pinned |
| `sysop/policy.py:322` | negate-cond: negate the condition | `elif val == "Esc":` | 5 | medium: the Esc key on a screen that is not a dialog (the dialog case is tested at line 297) |
| `sysop/brain.py:259` | boolop: Or -> And | `return Result("failed", "cannot start the brain %s: %s" % (argv[0], e.strerror or e))` | 10 | low: wording of the error of a brain that cannot be started |
| `sysop/service.py:206` | drop-call: drop the call | `self.cond.wait(min(5.0, 0.5 * fails))` | 12 | low: the wait between failed reads of the service loop (a missing wait would spin the CPU; no test measures that) |
| `sysop/service.py:316` | drop-call: drop the call | `self.cond.wait(wait)` | 12 | low: the wait before the next attempt (same: no test would notice a busy loop) |
| `sysop/service.py:353` | const: constant 200 -> 201 | `goal.text = goal.text[:200]           # a rejected goal does not keep its text (a goal of 1 MiB, a hundred times, would fill the disk)` | 12 | low: a rejected goal keeps its first 200 characters (the limit is not pinned exactly) |
| `sysop/service.py:506` | boolop: And -> Or | `if res.outcome == "failed" and disk_low(gdir):` | 12 | medium: the disk-full guard acts only after a failed goal AND a low disk; the two parts are not tested apart |
| `sysop/mcpserver.py:98` | boolop: Or -> And | `if not isinstance(d, dict) or "goal_dir" not in d:` | 5 | medium: a goal_dir file that is not a JSON object is not tested (it would raise instead of being refused) |
| `sysop/dock.py:722` | drop-call: drop the call | `self.stop.set()` | 6 | low: the stop event of the dock loop is set on exit |
| `sysop/watch.py:133` | drop-call: drop the call | `self.log("the service refused its settings (status 2; the reason is in serve.log above): not starting it again")` | 5 | low: one log line of the watcher |
| `sysop/watch.py:141` | negate-cond: negate the condition | `what = "killed by signal %d" % -rc if rc < 0 else "status %s" % rc` | 5 | low: the wording of how the service ended (signal or status) |
| `sysop/config.py:90` | boolop: Or -> And | `if "\0" in raw[key] or (key != "brain" and ("\n" in raw[key] or "\r" in raw[key])):` | 3 | IMPORTANT: settings validator: a newline or CR inside a setting value (not `brain`) is accepted once the NUL test is false; no test feeds one |
| `sysop/busclient.py:53` | compare: flip Gt -> GtE | `if len(raw) > MAX_LINE:` | 4 | low: exact boundary of the line limit of the sysop's bus client |
| `sysop/tabsclient.py:38` | drop-call: drop the call | `Exception.__init__(self, "%s: %s" % (code, msg) if msg else code)` | 1 | low: message text of an error class |
| `sysop/cli.py:62` | bool-const: False -> True | `return False` | 5 | medium: log rotation of the sysop daemon returns False when the file is small or on OSError; the caller's use of the result is not tested |
| `scripts/swarmbox-bus.py:145` | boolop: Or -> And | `self.log = log or self._log` | 4 | low (equivalent in practice): default logger |
| `scripts/swarmbox-bus.py:198` | drop-call: drop the call | `os.chmod(self.path, 0o600)` | 4 | IMPORTANT: the broker socket is made 0600; no test checks the mode of bus.sock |
| `scripts/swarmbox-bus.py:201` | drop-call: drop the call | `self.loop.add_signal_handler(sg, self.stop_event.set)` | 4 | medium: the broker's SIGTERM/SIGINT handlers (clean stop); the tests stop it through the entrypoint |
| `scripts/swarmbox-bus.py:213` | drop-call: drop the call | `os.unlink(self.path)` | 4 | medium: the socket file is removed when the broker stops |
| `scripts/swarmbox-bus.py:354` | compare: flip Gt -> GtE | `if len(encode(env)) > MAX_LINE:` | 4 | low: exact boundary of the maximum line (an oversized line one byte long) |
| `scripts/swarmbox-bus.py:498` | bool-const: True -> False | `while True:` | 4 | medium: the read loop of `swarmbox-bus sub` streams until EOF; `while False` ends after setup and prints nothing, yet no CLI test asserts a second message |
| `scripts/swarmbox-bus.py:512` | exit-code: return 4 -> 0 | `return 4` | 4 | medium: exit code 4 of a CLI failure path |
| `scripts/swarmbox-bus.py:525` | negate-cond: negate the condition | `if i + 1 >= len(a):` | 4 | medium: a flag that is the last word and has no value (usage error) |
| `scripts/swarmbox-bus.py:553` | const: constant 2 -> 3 | `if p is None or not 1 <= len(p[1]) <= 2:` | 4 | low: the parser accepts 1 or 2 words of a pattern |
| `scripts/swarmbox-bus.py:574` | negate-cond: negate the condition | `if pid <= 1:` | 4 | medium: a supervisor pid file that holds 0 or 1 is refused (never signal PID 1) |
| `scripts/swarmbox-bus.py:583` | exit-code: return 0 -> 1 | `return 0` | 4 | medium: exit code of `restart` |
| `scripts/swarmbox-bus.py:605` | bool-const: False -> True | `p = flags(a, {"--raw": False, "-v": False, "--group": True})` | 4 | medium: default of the --raw flag of the CLI |
| `scripts/swarmbox-tabs.py:156` | arith: +/- | `o2.extend([org[min(cut, m.end() - 1)]] * len(rest))` | 4 | medium: redaction keeps a one-to-one map of the screen text to its original cells; the index of a replacement is not pinned |
| `scripts/swarmbox-tabs.py:177` | compare: flip Lt -> LtE | `while i < len(lines):` | 4 | low: loop bound of the joining of wrapped lines |
| `scripts/swarmbox-tabs.py:191` | compare: flip IsNot -> Is | `a = m.end("keep") if "keep" in pat.groupindex and m.group("keep") is not None else m.start()` | 4 | medium: the `keep` group of a redaction pattern (what stays visible) when the group did not take part in the match |
| `scripts/swarmbox-tabs.py:353` | compare: flip Lt -> LtE | `if pos < len(line):` | 4 | low: boundary of the cursor position in a line |
| `host/swarmbox-host:647` | exit-code: return 1 -> return 0 | `[!a-z0-9]*\|*[!a-z0-9._-]*) _bad "it must be a model name such as small or medium (lower-case letters, digits, '.', '_', '-')."; return 1 ;;` | 18 | IMPORTANT: settings validator: a `voice.stt.model` with characters outside [a-z0-9._-]: no test checks that it is refused (the function would answer 0 after its message) |
| `host/swarmbox-host:650` | sh-case: the branch voice.stt.vocabulary never matches | `voice.stt.vocabulary)` | 18 | IMPORTANT: settings validator: nothing checks the rules of `voice.stt.vocabulary` (at most 500 characters, no forbidden character): without its branch every value is accepted and no test notices |
| `host/swarmbox-host:2065` | sh-and-or: || -> && | `rm -f "$SOCK_LINK" \|\| die 4 "cannot replace the symlink $SOCK_LINK."` | 18 | low: error path when the old socket link cannot be removed |
| `host/swarmbox-host:2248` | sh-delete: drop the line | `show_err "$UP_ERRF"` | 18 | medium: the error text of a failed `up` is not shown (show_err) |
| `host/swarmbox-host:2306` | exit-code: return 1 -> return 0 | `*' link to '*) return 1 ;;   # a hard link as bsdtar lists it` | 18 | IMPORTANT (security): the helper archive check refuses a hard link entry; no test has an archive with one |
| `host/swarmbox-host:2607` | sh-and-or: && -> || | `if [ "$r_rc" -eq 0 ] && [ "$r_dry" = 0 ] && [ "$r_have" = 0 ] && [ -t 0 ] && [ -t 2 ]; then` | 18 | low: the interactive-only condition of a prompt in `remote` |
| `host/swarmbox-host:2642` | sh-delete: drop the line | `h_s=` | 18 | low: an initialisation that the following code does not depend on |
| `scripts/swarmbox-addon.sh:566` | sh-delete: drop the line | `[ -f "$path" ] && [ -x "$path" ] \|\| return 1` | 14 | medium: a manifest command path must be a regular executable file |
| `scripts/swarmbox-addon.sh:695` | sh-and-or: || -> && | `run_installer "$name" "$tmp" "$version" "$arch" \|\| status=$?` | 14 | IMPORTANT: `run_installer || status=$?` turned into `&&`: the status of a failed installer is lost; no test makes an installer fail at this call and checks the exit status |
| `scripts/swarmbox-addon.sh:697` | sh-delete: drop the line | `rm -rf "$tmp"` | 14 | medium: the scratch directory of an install is removed (no test looks for leftovers) |
| `scripts/swarmbox-addon.sh:709` | sh-and-or: || -> && | `[ "$IMAGE_MODE" -eq 0 ] \|\| rm -rf "${ndir:?}/home"` | 14 | medium: in image mode the addon's home is not wiped |
| `scripts/swarmbox-addon.sh:1248` | sh-negate: negate the if condition | `if [ "$have" -eq 1 ] && [ "${M[UPDATE]:-managed}" = self ]; then` | 14 | medium: `update` of an addon that updates itself (UPDATE=self) |
| `scripts/swarmbox-addon.sh:1248` | sh-const: bound 1 -> 2 | `if [ "$have" -eq 1 ] && [ "${M[UPDATE]:-managed}" = self ]; then` | 14 | medium: the same line, the `have` flag |
| `scripts/swarmbox-addon.sh:1366` | sh-negate: negate the if condition | `if [ ! -f "$rec" ]; then` | 14 | medium: a missing fingerprint record |
| `scripts/swarmbox-addon.sh:1424` | sh-delete: drop the line | `needfix=1` | 14 | low: a flag of the doctor report |
| `scripts/swarmbox-addon.sh:1433` | sh-delete: drop the line | `[ "${#rows[@]}" -eq 0 ] \|\| printf '%s\n' "${rows[@]}" \| LC_ALL=C sort` | 14 | low: the sorted listing of the doctor |
| `entrypoint.sh:117` | sh-delete: drop the line | `rm -f "${SB_RUN_DIR:-/nonexistent}/web-supervisor.pid" "${SB_RUN_DIR:-/nonexistent}/bus-supervisor.pid" 2>/dev/null` | 7 | low: the pid files of the supervisors are removed at stop |
| `scripts/swarmbox-web.sh:57` | sh-delete: drop the line | `[ -r "$pidfile" ] \|\| die "no web terminal supervisor is running (no $pidfile; is the web terminal off, WEB=0, or is serve not running?)"` | 5 | medium: `restart` with no supervisor says so instead of failing obscurely |
| `scripts/swarmbox-attach.sh:49` | sh-delete: drop the line | `PLAIN=0` | 2 | low: initialisation of PLAIN |
| `scripts/swarmbox-statusline.sh:23` | sh-delete: drop the line | `[ -n "$input" ] \|\| exit 0` | 1 | low: an empty input prints nothing |
| `addons/voice/web/page.js:254` | js-cmp: === -> !== | `mic.addEventListener('blur', function () { pressed = false; if (state === 'recording') finish(); });` | 10 | medium: the page stops recording when the microphone button loses focus (blur); the browser test does not blur |
| `addons/voice/lib/swarmbox_voice/front.py:315` | drop-call: drop the call | `conn.close()` | 3 | low: a connection is closed explicitly |
| `addons/voice/lib/swarmbox_voice/front.py:499` | drop-call: drop the call | `s.setblocking(True)` | 3 | low: socket mode after the upgrade |
| `addons/voice/lib/swarmbox_voice/server.py:66` | boolop: Or -> And | `self.log = log or (lambda text: print("swarmbox-voice: " + text, file=sys.stderr, flush=True))` | 5 | low (equivalent in practice): default logger |
| `addons/voice/lib/swarmbox_voice/server.py:66` | bool-const: True -> False | `self.log = log or (lambda text: print("swarmbox-voice: " + text, file=sys.stderr, flush=True))` | 5 | low (equivalent in practice): default logger |
| `addons/voice/lib/swarmbox_voice/server.py:140` | drop-call: drop the call | `self.send_header("Content-Type", "application/json; charset=utf-8")` | 5 | medium: the Content-Type of the JSON answers of the voice service |
| `addons/voice/lib/swarmbox_voice/stt.py:33` | drop-call: drop the call | `RuntimeError.__init__(self, message)` | 4 | low: message of an error class |
| `dev/release.sh:291` | sh-str-eq: = -> != | `if [ "$m_new" = "$m_ser" ] && [ "$m_new" = "$m_lat" ] && [ "$archs" -ge 2 ]; then` | 1 | IMPORTANT: the release verification (`manifest of the new tag == serve == latest`, at least two architectures) is checked by one test file that never reaches the failing branch |
| `dev/release-check.sh:121` | sh-and-or: && -> || | `[ "$o" = "$c" ] && [ "$ob" = "$cb" ] && [ -s "$REPO/$f" ] \|\| bad="$bad $f"` | 1 | medium: the release check that the published files equal the committed ones |
| `dev/record-checksums.sh:55` | sh-and-or: || -> && | `want=$(listing_sha "$json" "$arch" 2>/dev/null \|\| true)` | 1 | low: a failing listing lookup is tolerated |
| `cloudflare-setup.py:424` | drop-call: drop the call | `die("%s already has a %s record. Refusing to replace it: remove it or pick another --name."` | 11 | IMPORTANT (safety): `die` when the DNS name already has a record of another kind (never replace it); no test covers that refusal |
| `cloudflare-setup.py:638` | boolop: And -> Or | `if exit_code == 3 and not api.dry_run:` | 11 | medium: exit code 3 is not reported in dry-run |

