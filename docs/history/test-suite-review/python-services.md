# Ledger: python-services (bus, swarmbox-tabs, sysop, voice)

Area of the second round of the test-suite simplification: every test of the bus, swarmbox-tabs, the sysop (policy, risk, mcp server, brain, service, ipc, panel, dock, always mode, web, soak) and voice (front, service, config, page logic). The product code was not touched.

## Result

- The fast tests of the area: **23 files, 743 tests, 230 s of file time (47 s wall at `-j 6`)** before, **23 files, 730 tests, 75 s of file time (10.5 s wall at `-j 8`)** after (`env -i`, tmux, ttyd, chromium and podman hidden from `PATH`, `--werror`, a quiet machine). The slowest file went from 46.9 s (`test_sysop_panel.py`) to 10.4 s (`test_sysop_service.py`); `test_sysop_panel.py` is 0.4 s. Four runs of `test_sysop_service`, `test_sysop_mcp`, `test_sysop_soak` and `test_tabs` at `-j 16 --werror` all passed (the old JSONDecodeError flake is gone: its cause was a test reading the fake claude's log while it was written).
- Tests of the area in all layers: 945 before (29 files), 905 after (30 files: `review` deleted, `dock_logic` and `panel_pty` added). The number of tests fell little because the seconds, not the count, were the problem in this area: most tests are one behaviour each; what was redundant was folded into tables (see below), and what only repeated another layer was deleted.
- The slow files (container, tmux 3.5a, `SWARMBOX_TEST_REAL_TMUX=1`, `--userns=keep-id`, while other areas used the machine, so the seconds are an upper bound): `test_sysop_panel_pty` 9 tests 22 s, `test_sysop_real` 15 / 34 s, `test_sysop_web` 4 / 20 s, `test_sysop_dock` 66 / 88 s, `test_sysop_always` 43 / 118 s: all pass.
- Mutation guard (`dev/mutate.py`, the plan of the baseline, **fast files only**, `--confirm`): sysop 94 mutants (66 killed, 1 timeout, 19 survived, 8 stale), tabs 25 (14 killed, 7 stale), bus 18 (15 killed), voice 24 (16 killed). Every mutant that the old suite killed and that was runnable stays killed by the new fast files, except **`dock.py:490`** (negate a condition), which the old suite killed only with the real-tmux dock and always files: those files still exist and still run in the container (not replayed for this mutant). `risk.py:19/243/293/304` and the other survivors were survivors of the old suite too. **Stale** mutants (the product files changed after the plan was drawn: 8 of risk/policy/service, 7 of swarmbox-tabs.py) cannot be replayed: the Integrate step should re-plan them against the current files.

## Per file

| Original file | Layer | Tests before | Seconds before | After | Tests after | Seconds after |
|---|---|---|---|---|---|---|
| `test_sysop_panel.py` | fast | 77 | 46.9 | `test_sysop_panel.py` (fast), `test_sysop_panel_pty.py` (slow) | 73 | 22.4 |
| `test_sysop_service.py` | fast | 56 | 29.8 | `test_sysop_service.py` (fast) | 60 | 10.4 |
| `test_sysop_mcp.py` | fast | 84 | 22.9 | `test_sysop_mcp.py` (fast) | 82 | 6.1 |
| `test_sysop_policy.py` | fast | 43 | 0.4 | `test_sysop_policy.py` (fast) | 45 | 0.5 |
| `test_sysop_review.py` | fast | 31 | 5.6 | deleted (each test moved to its subject) | 0 | 0.0 |
| `test_sysop_soak.py` | fast | 39 | 15.0 | `test_sysop_soak.py` (fast) | 36 | 4.5 |
| `test_sysop_brain.py` | fast | 33 | 8.2 | `test_sysop_brain.py` (fast) | 31 | 4.0 |
| `test_sysop_addon.py` | fast | 15 | 8.2 | `test_sysop_addon.py` (fast) | 15 | 6.2 |
| `test_sysop_watch.py` | fast | 6 | 4.3 | `test_sysop_watch.py` (fast) | 6 | 4.2 |
| `test_sysop_keys.py` | fast | 13 | 0.5 | `test_sysop_keys.py` (fast) | 13 | 0.5 |
| `test_sysop_bus.py` | fast | 12 | 1.2 | `test_sysop_bus.py` (fast) | 12 | 1.1 |
| `test_sysop_dock.py` | slow | 81 | 71.0 | `test_sysop_dock.py` (slow) | 66 | 88.1 |
| `test_sysop_always.py` | slow | 60 | 106.5 | `test_sysop_always.py` (slow) | 43 | 118.4 |
| `test_sysop_real.py` | slow | 15 | 24.1 | `test_sysop_real.py` (slow) | 15 | 34.1 |
| `test_sysop_web.py` | slow | 4 | 15.3 | `test_sysop_web.py` (slow) | 4 | 19.9 |
| `test_bus.py` | fast | 56 | 2.4 | `test_bus.py` (fast) | 56 | 2.4 |
| `test_bus_cli.py` | fast | 33 | 8.6 | `test_bus_cli.py` (fast) | 33 | 6.9 |
| `test_bus_serve.py` | fast | 4 | 5.3 | `test_bus_serve.py` (fast) | 4 | 2.2 |
| `test_tabs.py` | fast | 88 | 27.6 | `test_tabs.py` (fast) | 89 | 6.8 |
| `test_tabs_locks.py` | fast | 4 | 0.8 | `test_tabs_locks.py` (fast) | 4 | 0.4 |
| `test_tabs_redact_dos.py` | fast | 8 | 6.7 | `test_tabs_redact_dos.py` (fast) | 7 | 1.6 |
| `test_voice_config.py` | fast | 18 | 1.4 | `test_voice_config.py` (fast) | 18 | 1.4 |
| `test_voice_front.py` | fast | 46 | 24.9 | `test_voice_front.py` (fast) | 46 | 6.9 |
| `test_voice_page.py` | fast | 11 | 0.1 | `test_voice_page.py` (fast) | 11 | 0.1 |
| `test_voice_service.py` | fast | 36 | 7.5 | `test_voice_service.py` (fast) | 36 | 3.9 |
| `test_voice_soak.py` | fast | 5 | 4.0 | `test_voice_soak.py` (fast) | 5 | 2.0 |
| `test_voice_web.py` | fast | 25 | 1.5 | `test_voice_web.py` (fast) | 25 | 1.3 |
| (new) | fast | - | - | `test_sysop_dock_logic.py` (fast) | 32 | 1.1 |
| **Total** | | **903** | **451** | | **867** | **357** |

## What was done, file by file

Test counts and seconds are in the table above (seconds: the baseline's host column against a run of the new fast files under `env -i` with tmux, ttyd, chromium and podman hidden from `PATH`; the machine was loaded by the other areas, so the new seconds are an upper bound). Behaviours that a regression could bring back were not deleted: where a test went, the line says where its case lives now.

### Sysop

- **`test_sysop_panel.py`** (77 tests, 46.9 s). The model, the renderer and the keys (pure, 0 s) are kept; two tests that repeated another one through the same layer were folded (`the idle text and the service down message` into IdleScreen and Keys, `the end of a goal` into `the last goal is shown...`). The 27 tests that ran the panel on a pty (11 s of CPU measuring, 3 s countdowns, 0.75 s per `q`) became **in-process tests of `Panel`** with a fake clock, a fake bus and a file as its screen (`PanelObject`, `PanelLoop`): the files the service writes and what the panel shows, the veto, the guard of 0.5 s, the expiry of a countdown and of an approval, the approval gesture with the word `run`, `c` and Esc, `x` and `X`, `q`, a goal published with the source `panel` (topic of the setting, no subscriber, bus down, too long, the text kept), the idle panel that looks only when a file changed (`changed()`), the bytes drawn with hostile text from a tab, a failing turn of the loop (one short line, 20 in a row end it, EOF ends it quietly). The text that does not fit (`NOT shown`, cannot be allowed) moved here from `test_sysop_review.py` and was merged with the old request test. The process-level cases are `slow/test_sysop_panel_pty.py` (9 tests, 22 s): idle, SIGWINCH and `q` (screen given back), SIGTERM and SIGHUP, the idle CPU (4 s, not 10), the countdown that ticks and the keys that decide as bytes, a goal typed and published on a bus, the service going and coming, and three runs against the REAL service, the real bus and the fake claude (veto key, the typed word `run`, a goal typed in the panel). Dropped as redundant: `the countdown runs out and the action is sent` and `the stop key ends the goal` against the real core (the service side is in `test_sysop_mcp.py` (`allowed` after the countdown) and `test_sysop_service.py` (stop request)), and the pty copies of the width, control-text and quit tests (pure render/draw tests cover them).
- **`test_sysop_service.py`** (56 tests, 29.8 s). The fake claude has a new step `{"waitfile": path}` (a goal held running until the test opens a gate), so no test sleeps for a goal to stay running; the deadline and the approval timeout are shortened with `Config._replace` (below what a setting may be); the queue limit, the label of the source, the bad goals and the newer envelope version are tested on `Service.accept` directly (no thread, no brain: class `Accept`) instead of by running 3 to 8 goals; the waits of the main loop are cut by `ss.fast_cond` in the tests of a loop that fails turn after turn. `the default limit is five` was dropped (the default is asserted in `test_status_json`, the limit in `Accept`). The flake of the old suite (a JSONDecodeError at `-j 16`) was a test that read the fake claude's log while it was being written: the fixture now writes it whole and renames it.
- **`test_sysop_mcp.py`** (84 tests, 22.9 s). The server runs on a fake clock (`Clock`: `sleep` moves it and runs what is due: the fake panel answers, a screen changes), so a countdown of 0.6 s, an approval time-out, a wait of 20 s are a few dozen calls; the fake panel is a synchronous object (no thread, no 10 ms polling). Four tests about a decision that is not for this action (another id, an old file, a damaged file, a wrong word) became one table; three about an approval that does not approve (another id, an old file, no word) became two; the autonomy table is one test; the pinned constants of the settle (`QUIET`, `SETTLE_CAP`) were dropped (the maths is tested with a clock; the numbers are an implementation detail).
- **`test_sysop_policy.py`** (43 tests): the risk tables were ONE home already (`RISK_CASES`, `NEW_CASES`); the lists that lived elsewhere (`NOT_LOW`, `LOW`, the hooks, `RiskFormsFromVoice`, and the review's `SelfControls` and `NestedShapes`) are now rows of the same table (`EXTRA_CASES`, 181 rows after removing the duplicates), and two tests run every row: `classify_command` gives the level, and the policy routes it (low: a countdown; medium and high: an approval; a control character: blocked). New rows for the clauses that the old suite never reached (publish and infrastructure verbs: `twine upload`, `cargo publish`, `gem push`, `yarn publish`, `terraform apply`, `tofu apply`, `kubectl delete -f`, with the neighbours that must stay low). The review's `AgentStart`, `LineEnds` and `RunOnTopOfTheCommandLine` classes were moved here.
- **`test_sysop_review.py`** (31 tests, 5.6 s) was a bag of regression tests named after a review, not after what they test. **Deleted**; every test lives with its subject: risk rows into the table above, `ServerGate`/`ServerWait` into `test_sysop_mcp.py` (on the fake clock), `CliText`, `Flood`, `ShutdownRace` and `Surrogates` into `test_sysop_service.py`, `BrainSupervision` into `test_sysop_brain.py`, the refused-setting `Prepare` into `test_sysop_addon.py`, the two `Panel` tests into `test_sysop_panel.py`.
- **`test_sysop_soak.py`** (39 tests, 15.2 s). The waits of a main loop that fails (0.5 + 1.0 + 1.5 s) are cut (`ss.fast_cond`), the housekeeping and the end of a goal on a full disk wait for what they test (a gate, a counter), the wall clock that jumps back is tested on the steady clock itself and on `mcpserver.main` giving it to the Server (the thread-and-timer countdown test proved nothing beyond that and was dropped), `PanelFailures` moved to `PanelLoop` in the panel tests (no thread, no pty). Audit rotation, the full disk (service, log, goal end, watcher), the hooks flood (`RedockCoalescing`), the reconnect delay, the killed brain words, the surrogates are all kept.
- **`test_sysop_brain.py`** (33 tests, 8.2 s): the grace after `done` and the TERM grace are shortened (0.2 s) and the stop timers moved to 0.4 s; five tests that pinned phrases of the system prompt (each from an e2e finding) are one table with the finding named. **`test_sysop_addon.py`** (15, 8.2 s): `idempotent` and `a service that died is started again` and `prepare and goals work together` are one test (one install); the fixed sleep after two prepares is a wait. `test_sysop_watch.py`, `test_sysop_keys.py`, `test_sysop_bus.py`: unchanged (they are process-level and fast enough).
- **`slow/test_sysop_dock.py`, `slow/test_sysop_always.py`**: the 32 tests that never needed tmux (the layout rule as a pure function, the marks and the hook slot, the key of `tmux.conf`, the setting `sysop.panel`, the Follower with a fake dock for each mode) moved to **`fast/test_sysop_dock_logic.py`** (1.5 s; the two thread tests wait for what they need instead of 0.5 and 0.7 s). The real-tmux classes stay as they were (66 and 43 tests): they were not run again here beyond the skip and the container run below, and they are the candidates for the next merge (see the report).
- **`slow/test_sysop_real.py`**: the `pgrep -f fixtures/sysop/bin/claude` over the whole machine is gone (it broke 9 of the 40 mutation controls and `run.sh slow -j 3` whenever another fake claude ran): the test reads the pid of its own brain from the fake's log and checks that process. **`slow/test_sysop_web.py`**: now a `BrowserCase` of `support/browser_support.py` (the harness is no longer inherited from the clipboard test, whose 11 tests were nulled by a loop), and the processes are ended by group, which closes the leak of 4 processes that the runner showed.

### Bus, tabs, voice

- **`test_bus_serve.py`**: the 3.6 s test that waited for the backoff of 1 s and 2 s is a test of the behaviour (killed with -9, started again, takes over the stale socket) with the backoff set to 0; the values 1 s and 2 s are in `test_serve_steps.py` (fakes). **`test_bus_cli.py`**: the load tests keep their claim at 100 and 80 messages (3.1 s and 1 s before). `test_bus.py` and `test_sysop_bus.py`: unchanged.
- **`test_tabs.py`** (88 tests, 27.6 s). The fake tmux (an executable script, one Python process per tmux call) can also be run **in process**: `FakeTmux.driver()` replaces `subprocess.run` of the driver's own module by `InProcessTmux.run`, which executes the same script under a lock (calls to another binary still go to the real subprocess; `SB_TEST_TMUX_PROCESS=1` restores one process per call). The command line tests still run the real process. A long text is 5600 characters instead of 300000, `too many steps` patches the limit instead of typing 100 keys, and the 5 s real timeout of the command became `every error code has its exit code` in process (the real timeout of a tmux call is `every tmux call has a timeout`, 0.4 s). `test_tabs_redact_dos.py`: 256 KB instead of 1 MB for every adversarial input (a quadratic filter needed minutes for 100 KB, so the limit still separates them by orders of magnitude), and the ratio test was dropped as redundant with the absolute limit.
- **`test_voice_front.py`** (46, 24.9 s): the test servers stop in 10 ms instead of 0.5 s (`serve_forever(poll_interval=0.01)`), the shortened timeouts are shorter, the fake ttyd exits after 0.3 s. **`test_voice_service.py`** (36, 7.5 s): the same `poll_interval`. **`test_voice_soak.py`**: 4 races between two SIGTERMs instead of 10 (the handler is tested on its own), 0.05 s recognizers. `test_voice_config.py`, `test_voice_page.py`, `test_voice_web.py`: unchanged. `slow/test_voice_page_browser.py` was reworked by the web/browser area (support/browser_support.py) and is theirs in this round; `slow/test_tabs_real.py` is unchanged.

## Real bugs of version 1 and where each one is guarded now

| Bug | Regression test (file::test) | Layer |
|---|---|---|
| redact quadratic time (100000 dashes took 110 s) | `test_tabs_redact_dos.py::RedactTimeTest::test_adversarial_inputs_are_fast` | fast |
| the JWT lookbehind (`\beyJ` allowed a hyphen in front; the speed fix did not) | `test_tabs_redact_dos.py::test_a_jwt_after_a_dash_is_redacted_as_it_was_before_the_speed_fix` | fast |
| status.json race (reader thread and main thread both write it) | `test_sysop_service.py::StatusFile::test_two_threads_writing_status_json_leave_the_newest_state` | fast |
| the busy footer cut in a narrow pane | `test_tabs.py::TestAgentState::test_busy_in_a_narrow_pane_where_the_footer_is_cut` | fast |
| the Esc on a dialog is the user's decision (high, an approval at every level) | `test_sysop_policy.py::AgentTabs::test_a_dialog_on_the_screen_makes_every_key_high_esc_included` (+ `HooksReadlineAndDialogs` for a dialog in a tab that is not called claude) | fast |
| the Whisper silence goal (a recording with no sound reached the recognizer and became a goal) | `test_voice_service.py::GoalOnTheBus::test_silence_is_nothing_heard_and_nothing_is_published`, `::test_a_recording_with_no_sound_never_reaches_whisper_and_nothing_is_published` | fast |
| secrets split by markers / by hard line breaks / by colours | `test_tabs.py::TestScreenSecretsAndMarkers` (4 tests) | fast |
| the tab renamed `python3` (the panel froze the name of the window) | `slow/test_sysop_dock.py::TabName` (7 tests) | slow |
| audit rotation, the several writers, the lost generation | `test_sysop_soak.py::AuditLimit` | fast |
| the disk full: service, its log, the end of a goal, the watcher | `test_sysop_soak.py::ServiceOnAFullDisk`, `LogOnAFullDisk`, `FullDiskEnds`, `FailedGoalOnAFullDisk`, `McpWithoutAudit` | fast |
| the hooks flood (one redock process per resize event) | `test_sysop_soak.py::RedockCoalescing` | fast |
| the burst Enter (a burst of sends failed) | `slow/test_tabs_real.py::test_a_burst_would_have_failed_and_the_driver_does_not_burst` | slow |
| the window-resized hook passes the window that changed, fits only that window | `slow/test_sysop_dock.py::HookRedock` (11 tests) and `test_sysop_soak.py::RedockFastPath` | slow + fast |
| a goal with a byte that is not UTF-8 killed the service | `test_sysop_service.py::Surrogates` | fast |
| two SIGTERMs in a row left a traceback (voice) | `test_voice_soak.py::TwoSigterms` | fast |
| the body that trickles in held a slot of the voice front for ever | `test_voice_front.py::VoicePath::test_a_body_that_trickles_in_has_a_total_deadline` | fast |
| the dialog that opens while an action waits stops it; keys typed in the tab while a goal arrives never reach a countdown or an approval | `test_sysop_mcp.py::ServerWait`; `slow/test_sysop_dock.py::NoFocus`, `slow/test_sysop_always.py::NoFocusSteal`, `slow/test_sysop_web.py` | fast + slow |
| the text that does not fit cannot be allowed; a command of 615 characters shown whole | `test_sysop_panel.py::Approval` (two tests) | fast |
| the result of the last goal in a short pane; a paragraph whole or gone | `test_sysop_panel.py::IdleScreen` (two tests) | fast |
| the keys guard (stray typing answered an action that had just appeared) | `test_sysop_panel.py::Keys::test_keys_are_ignored_for_half_a_second_after_a_new_action`, `PanelObject::test_the_veto_key_writes_the_decision_once_the_guard_has_passed`, `slow/test_sysop_panel_pty.py::test_the_countdown_ticks_and_the_keys_decide` | fast + slow |
| the burst of kill and restart of the broker; the stale socket | `test_bus_serve.py`, `test_bus_cli.py::NotRunning` | fast |
| a brain left running after an error of the supervisor | `test_sysop_brain.py::BrainSupervision` | fast |

## Not done / for the next merge

- `slow/test_sysop_dock.py` (66), `test_sysop_always.py` (43), `test_tabs_real.py` (28): real tmux, one test per behaviour, many with fixed `time.sleep`s that guard the 0.5 s key guard of the panel; they are the candidates for one slow test per integration path. Not rewritten because a merge needs a container run per step and cannot be verified by the fast mutants.
- `test_bus.py`, `test_bus_cli.py`, `test_voice_front.py`, `test_tabs.py` keep their tests; tables could still fold some of them.
- The risk table has 328 rows (181 of them moved from other lists); rows are deduplicated by exact text only. A pass by bypass class needs a broader mutation run on `risk.py` than the 21 mutants of the plan.
- The bus survivors (12 of 18 in the old plan: `swarmbox-bus.py` socket mode, exit codes of `sub`/`watch`/`restart`, the `pub` usage line) were not given new tests.

## Support changes the other areas may meet (added, no behaviour of the others changed)

- `tests/support/fixtures/sysop/bin/claude`: step `{"waitfile": path}`; the log it writes is renamed into place.
- `tests/support/sysop_support.py`: `fast_cond(svc)`. `tests/support/tabs_support.py`: `InProcessTmux`, and `FakeTmux.driver()` uses it (`SB_TEST_TMUX_PROCESS=1` for processes). `tests/support/bus_support.py`: `Conn` closes its socket when the connect fails.
- `test_bus_serve.py` imports from `support/serve_support.py` (it imported `test_serve_steps`). `test_sysop_web.py` uses `support/browser_support.py` (`BrowserCase`, `CDP`).
- `slow/test_voice_page_browser.py` was changed by the web/browser area in this round and is not part of this ledger.
