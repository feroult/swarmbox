# Ledger: guards, web, release, image (area "guards-web-release-image")

Area: the guard tests (docs, repo files, old names, notices, default names, Dockerfile, workflows, runner, dev check, hooks), the web page and strip tests and
the browser tests, the release scripts and checksums, the image tests and the smoke data, the e2e harnesses (kept, repointed). Times: "before" is
`baseline.json` (host for fast files, Podman with the gates on for slow files); "after" is measured in the test image (`swarmbox-test-slow:tmux35`, offline,
read-only root, the gate on), each file alone or at `-j 3`.

## Support added (nothing of the other areas changed)

- `tests/support/waiting.py`: `wait_until(fn, seconds, step)` (and the alias `wait_for`), the one polling helper. No fixed sleep is left in the browser, keys or voice tests
  except the two that are the behaviour itself (the length of a recording; the 310 ms that tmux itself asks between two clicks).
- `tests/support/repo_scan.py`: one `git ls-files` and one read of each file per process, for the guards that look at every file.
- `tests/support/browser_support.py`: `CDP`, `Chromium` (one per file, a tab per terminal), `WebTerminal` (the real page built by `build-index.sh` and rendered by
  `swarmbox-web`, a real ttyd, a real tmux on a private socket and `TMUX_TMPDIR`), `browser_tests()` (the gate and the programs), `BrowserCase` (the small base that
  `slow/test_sysop_web.py` uses). The ttyd stock page is fetched once per process, not once per test. `e2e/e2e_voice.py` imports `CDP` from here now.

## Files

| Before | Tests | Seconds | After | Tests | Seconds | What happened |
|---|---|---|---|---|---|---|
| `test_docs_consistency.py`, `test_repo_files.py` | 7 + 8 | 0.1 | `fast/test_guard_docs.py` | 12 | 0.2 | one file: README, links (now also CODE_OF_CONDUCT and CHANGELOG, fences balanced), LICENSE, CONTRIBUTING, policy files |
| `test_third_party_notices.py` | 6 | 0.1 | `fast/test_guard_docs.py` (Notices) + `fast/test_gen_notices.py` | 3 + 2 | 0.3 | the notices checks of three files (repo_files, third_party, dockerfile) were one idea three times: apt rows with license and source, downloaded programs, addon sections, the full list; the generator script keeps its own file |
| `test_no_old_names.py`, `test_default_names_lint.py` | 13 + 5 | 0.8 | `fast/test_guard_names.py` | 11 | 0.8 | one process, one read of the repository (`repo_scan`); the scanners are tested on a dict of path to text, no temp tree; the dead `ALLOWED` mechanism of the lint is gone |
| `test_dockerfile.py`, `test_smoke_image_data.py` | 16 + 3 | 0.1 | `fast/test_dockerfile.py` | 12 | 0.0 | the same invariants in fewer tests; the smoke data checks joined; the wording check ("eight addons") was a message pin and is gone |
| `test_ci_workflow.py`, `test_release_workflow.py` | 14 + 9 | 0.1 | `fast/test_workflows.py` | 12 | 0.0 | both workflows, the checks they share (a step has `run` or `uses`, a step name is a valid plain scalar, pins, no secrets, actionlint) once |
| `test_run_all.py` (now `test_runner.py`) | 8 | 0.6 | `fast/test_runner.py` | 7 | 1.6 | no longer names a real test file (`test_dirs.py`): a fake tests folder; the time limit test waits 1 s, not 2 |
| `test_dev_check.py` | 11 | 0.1 | `fast/test_dev_check.py` | 10 | 0.1 | new: `check.sh` runs `tests/run.sh fast` in a clean environment (no TERM, COLORTERM, STARSHIP_SHELL) and a failed file fails the check; the CONTRIBUTING test moved to the docs guard |
| `test_release_check.py` | 11 | 0.9 | `fast/test_release_check.py` | 12 | 1.1 | new: the reduced workflow check without PyYAML (empty, tab, unclosed `[`, unclosed `{`, a good one) |
| `test_release_script.py` | 23 | 1.6 | `fast/test_release_script.py` | 26 | 1.7 | new: image verification after the tag (same manifest for `2.0.7`, `2.0`, `latest`, at least two architectures) with a fake `podman`; the CONTRIBUTING test moved to the docs guard |
| `test_release_version.py` | 11 | 0.1 | `fast/test_release_version.py` | 5 | 0.1 | the same rows; the duplicated shell comparison and two format pins merged |
| `test_record_checksums.py` | 6 | 0.1 | `fast/test_record_checksums.py` | 6 | 0.1 | one new case (a listing that cannot be read), two gcloud tests merged |
| `test_web_build.py`, `test_build_index.py` | 18 + 6 | 1.7 | `fast/test_web_build.py` | 21 | 1.6 | `build-index.sh` joined; the settings the page consumes are checked once for all of them; new rows: padding fallback, `restart` without a pid file; the static `bash -n`/shellcheck test went (CI runs shellcheck) |
| `test_web_strip.py` (fast half) | 17 | 0.5 | `fast/test_web_strip_script.py` | 10 | 0.4 | settings render, key notation and fake DOM, the node calls merged (one node process for names, unknown names and the application cursor mode) |
| `test_web_strip.py` (browser half) | 18 | 62.1 | `slow/test_web_strip.py` | 12 | 4.0 (10 at `-j 3` x6) | 7 terminals instead of 18 openings; one phone terminal is turned (portrait, landscape, tablet), a Chromium per file, no sleep |
| `test_clipboard_bridge.py` | 11 | 39.5 | `slow/test_clipboard_bridge.py` | 8 | 1.2 (2.5 under load) | a terminal per class, two copy paths in one test, two right-click tests with a terminal each (the menu tmux opens held the keys of the next test) |
| `test_web_style.py` | 7 | 19.9 | `slow/test_web_style.py` | 2 | 0.8 | the settings are fast tests; the browser measures the defaults and one configured page |
| `test_tmux_browser_keys.py` | 22 | 72.1 | `slow/test_tmux_browser_keys.py` | 12 | 1.9 | the box config no longer repeats the keys-file tests; no sleep (effects are waited for, a prompt is waited for in the pty output); `TMUX_CONF=` override removed |
| `test_voice_page_browser.py` | 14 | 31.7 | `slow/test_voice_page_browser.py` | 10 | 16.4 | one Chromium, the answer table in one test on one page, the stub's answer is held by an event instead of a sleep; new: losing the focus ends the recording, the idle clock |
| `test_image_build.py` | 4 | - | `slow/test_image_build.py` | 3 | - | shares `image_support`; the entrypoint/cmd test repeated the Dockerfile test and is gone (run here against an existing image: 3 passed) |
| `test_image_with_addons.py` | 3 | - | unchanged | 3 | - | needs a built image (run here against an existing one: 2 passed, 1 skipped for the network) |
| `test_dev_build.py` | 13 | 0.2 | `fast/test_dev_build.py` | 4 | 0.2 | the same cases in four tests |
| `tests/e2e/*` | - | - | unchanged but `e2e_voice.py` | - | - | the three harnesses import, `--list` works, their paths are the new ones |

Totals of the area: 284 tests before, 200 after (the 5 tests of `test_layout.py`, which is not in the area, are not counted). Slow browser files (strip, clipboard,
style, keys, voice): 225 s of file time before (62 + 40 + 20 + 72 + 32), about 25 s after (4 + 1.2 + 0.8 + 1.9 + 16.4), wall 16 s at `-j 3`, bound by the voice page. The fast files of the
area were already fast (about 7 s of file time on the host before) and stay so (9 s in the offline container after, with four new process tests: `check.sh`, the image
verification of the release, the PyYAML-less check, the unreadable listing); the saving there is in the number of files and tests (19 files before, 14 after), not in seconds.

## Where each protected behaviour lives now

Real bugs and regressions of version 1 that belong to this area, and their test:

| Bug or rule | Test |
|---|---|
| a step name with `: ` makes GitHub show no job at all; a step with neither `run` nor `uses` | `test_workflows.BothWorkflows` |
| the first draft of `ci.yml` named a test file by hand on macOS (a copy of a list) | `test_workflows.Ci.test_linux_runs_fast_and_slow_and_macos_runs_the_list_in_one_place` |
| tmux 3.5a has no pane scrollbar: the pinned backport, checksum before install, snapshot fallback; the scrollbar line is quiet | `test_dockerfile.Pins`, `slow/test_tmux_browser_keys.BoxConfig.test_the_scrollbar_is_off...` |
| the tmux version in the notices and the package list equals the pin | `test_dockerfile.Pins.test_the_tmux_version...` |
| xterm.js reserves 15 px for a scrollbar it measures as zero when it keeps a history | `slow/test_web_style` (scrollback 0 by default) and `test_web_build.Render` (the scrollback table) |
| the browser must never answer an OSC 52 read request | `slow/test_clipboard_bridge.Defaults.test_an_osc52_read_request...` |
| Ctrl+V pastes, Ctrl+C copies only with a selection, both can be turned off | `Defaults`, `OptOuts` of the same file |
| right click: the browser menu is suppressed only while tmux has the mouse; Shift keeps it | `RightClick*` of the same file |
| the strip never covers the last row; tmux has exactly the rows xterm shows; 44 px targets; phone, landscape, tablet, keyboard (visualViewport) | `slow/test_web_strip.py` (Desktop, Phone, Settings) |
| a framed page gets no strip and no key button (the frame guard) | `fast/test_web_strip_script.FakeDom` |
| a note ends by itself (12 s tone, 130 s plain), a new one restarts the clock | `FakeDom` and `slow/test_web_strip.Phone.test_the_sentences...` |
| a hostile value of `stripKeys`, `padding` or `ctrlVPaste` stays inside the page | `test_web_strip_script.Render`, `test_web_build.Render` |
| the Panel button runs the sysop dock binding of the image | `slow/test_web_strip.Settings.test_the_panel_button...` |
| the mouse wheel scrolls five lines per event (was two); a program that asks for the mouse gets the wheel | `slow/test_tmux_browser_keys.BoxConfig` |
| `swarmbox-web restart` must not signal a stale, garbage or unsafe pid (0, 1, -1), nor fail obscurely without a pid file | `test_web_build.Restart` |
| voice page: the light, the answer table, text is text, denied microphone, blur ends the recording, the page is only a mic and a light | `slow/test_voice_page_browser.py` |
| a release: placeholders, a gate or release check that fails restores the files, a CI failure leaves no tag, a wrong checksum or version is a failure, the image tags must agree | `test_release_script.py` |
| the release check never modifies anything; a tag on another commit than HEAD fails; the PyYAML-less workflow check | `test_release_check.py` |
| the gate runs in a clean environment (a test that only passed with the variables of your terminal) | `test_dev_check.CheckScriptTest` |
| old names of the addon concept; default names written as literals | `test_guard_names.py` |

## Mutants of the area (the kill matrix of the old suite, replayed on the new one)

Replayed in the test image with `dev/mutate.py run --plan <the plan, filtered to these product files> --all-tests --confirm`, with the new files of the area:
`swarmbox-web.sh` (5), `build-index.sh` (1), `ttyd-clipboard.js` (2), `page.js` (3), `release.sh` (4), `release-check.sh` (2), `release-version.sh` (1),
`record-checksums.sh` (1): **20 of 20 killed**. The 15 killed before are still killed; the five that survived the old suite are killed now:

| Mutant | Killed by |
|---|---|
| `release.sh:291` image tags and architectures | `test_release_script.ImageVerification` |
| `release-check.sh:121` reduced workflow check | `test_release_check` (the PyYAML-less table) |
| `record-checksums.sh:55` a failing listing lookup | `test_record_checksums.GoTest.test_a_listing_that_cannot_be_read...` |
| `swarmbox-web.sh:57` restart with no supervisor | `test_web_build.Restart` |
| `page.js:254` blur ends the recording | `slow/test_voice_page_browser.test_losing_the_focus...` |

Note for the Integrate step: `dev/mutate.py` finds the tests of a product file by the product file's name in a test file. The browser tests now reach the page files through
`tests/support/browser_support.py`, so for `ttyd-clipboard.js`, `swarmbox-web.sh` and `build-index.sh` pass `--tests test_clipboard_bridge.py,test_web_style.py,test_web_strip.py,
test_web_strip_script.py,test_web_build.py,test_voice_web.py` (or add the support file to the search).

## Stability

The five browser files were run six times each at `-j 12` (24 runs of the four files, 10 runs of the clipboard file at `-j 10`) with tmux 3.5a and three times with tmux 3.7c,
`--werror`: no failure after the fixes of the first runs (the menu that tmux opens on a right click, a drag that needs copy mode before the release, a client that has to have drawn
before its first key counts, a confirm prompt that opens after the key). Two flakes of the old tests that fixed sleeps had hidden are described in the code where they are handled.

## Not done

- `tests/slow/test_image_with_addons.py`, `smoke_image.py`, `test_bashrc_container.py`, `test_nested_fuse_real.py`: need a built image or the network; checked here only against an
  existing image (two of them), not simplified further.
- `tests/e2e/*`: not run (they cost money and minutes); only that they import and list. The `wait_for` helper is still defined three times there (`waiting.py` could replace them).
- `CONTRIBUTING.md` and `tests/README.md`: only the rows and lines about the files of this area were changed.
