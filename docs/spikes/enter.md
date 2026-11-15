# Spike: enter (typing a prompt into Claude Code in tmux)

Environment: Claude Code 2.1.325 (native binary `claude.exe` installed by npm, runs as process `claude`), tmux 3.5a, 120x40 pane, inside
`localhost/swarmbox-sysop-test` with an isolated tmux socket (`-L spike`). Code and screens: `dev/spikes/enter/`.

**Verdict: works, with one rule: never put the text and the Enter in the same burst.** Text with `send-keys -l`, a pause, Enter as a separate tmux
command. 150 ms was reliable in every trial; it is also the value in the design.

## 1. Getting to a ready prompt in a fresh HOME

Files and env, nothing else (login comes from `CLAUDE_CODE_OAUTH_TOKEN`; no login screen appears):

```
$HOME/.claude.json   {"hasCompletedOnboarding":true,"theme":"dark","projects":{"<abs project dir>":{"hasTrustDialogAccepted":true}}}
$HOME/.claude/settings.json   {"skipDangerousModePermissionPrompt":true}      # only needed with --dangerously-skip-permissions
```

Without `.claude.json` the sequence is: telemetry/managed settings dialog, theme picker, "Security notes" (Enter), folder trust (default option is
**No, exit**). With the seed only the managed dialog may remain.

Gotchas found:

- **"Managed settings require approval"** appears on the first start of a HOME when the account's organization pushes remote settings (here an
  `OTEL_EXPORTER_OTLP_ENDPOINT`). Default option is "Yes", Enter accepts. Once the cache `~/.claude/remote-settings.json` exists it does not come back in
  that HOME. It cannot be seeded away by env vars (`DISABLE_TELEMETRY`, `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC` did not remove it). The spike accepted it in
  throwaway containers, with synthetic prompts only. A boot loop must handle it (see `boot` in `lib.sh`): while not ready, if the screen has "Managed settings
  require approval" press Enter.
- With `--dangerously-skip-permissions` and no `skipDangerousModePermissionPrompt` there is a "Bypass Permissions mode" dialog whose default is **No, exit**; the
  accept option needs `Down`, `Enter` (a digit key does not select it).
- The default permission mode of this version is **auto mode** (footer "auto mode on"); `--permission-mode default` gives "manual mode on" and permission
  dialogs. With the flag the footer says "bypass permissions on".
- Ready after about 1 s of start (no network wait for the prompt itself).
- `tmux new-session ... claude` as the pane command: when claude exits (two Ctrl+C, see 6) the pane and session die. Launch from a shell pane if the pane should survive.

## 2. Burst versus separate Enter (trial table)

Success = the answer line `● <TAG>` is on the screen for the prompt `reply with exactly the word <TAG>` (`trials.sh`).

| Variant | ~40 chars | ~600 chars (with newline-free filler) | ~3000 chars |
|---|---|---|---|
| burst: `send-keys -l text \; send-keys Enter` (one tmux command line) | 8/8 | **0/4** (run stopped, see below) | not run |
| p0: two tmux commands, no sleep | 8/8 | 8/8 | **6/8** |
| p50: 50 ms | 8/8 | 8/8 | 8/8 |
| p150: 150 ms | 8/8 | 8/8 | 8/8 |
| p300: 300 ms | 8/8 | not run | 8/8 |
| p600: 600 ms | 8/8 | not run | not run |

- Failure mode of burst/p0 is the one of the design: the text arrives as a paste, the Enter becomes a **line break inside the input box** and nothing is
  submitted. The text stays in the box and the TUI looks idle (`screens/failed-burst-long-newline-in-box.txt`). Short text is not treated as a paste, which
  hides the problem in quick tests. It is size dependent, so a short-prompt test proves nothing.
- Chosen: **separate Enter after >= 50 ms; use 150 ms** (3x the smallest passing value). Pauses up to 600 ms also work; they only add latency.
- Not measured: whether the threshold depends on machine load or tmux over a slow ttyd link; 8 trials per cell is a small sample.
- Safety net in `enter.sh`: after Enter it checks that the typed text left the input box (or the state is busy/dialog); if the text is still there it presses
  Enter once more (only then, because Enter on an empty box could accept a suggestion).

## 3. Special characters, newlines, long prompts

- Characters survive: the box content after `send-keys -l` equals the typed text exactly for `it's "q" `bt` $HOME $(id) \n é ✓ 日本 ñ ; | & > <` (`-l` means
  no shell or tmux interpretation; quote it correctly in the calling language). The model also echoed them back (the TUI renders backticks as code, so an
  answer on screen shows them without the backticks; assert on the input box or on the answer words, not on rendered markdown).
- 600 and about 3000 characters work with a pause >= 50 ms (table above). With the PoC: 8/8 prompts of 600 chars containing newline, quotes, backticks, `$`,
  unicode.
- **A newline inside the `-l` text is a newline in the input box, it does not submit** (box shows two lines, state unchanged). So the plain driver can send
  multi-line text as it is, then one Enter. Bracketed paste (`tmux load-buffer` + `paste-buffer -p`, then Enter) also works and the answer used all lines.
- Other newline keys through send-keys: `C-j` and `M-Enter` and `\` + Enter insert a newline; **`S-Enter` submits** (tmux sends a plain CR). Do not use it.
- **A text that starts with `/` or `!` is not a prompt**: `/` opens the slash command menu and `!` switches to shell mode. A driver sending model-generated or
  voice text must refuse or escape it (the PoC exits 6; a leading space is a possible escape, not tested).

## 4. Detecting the state from capture-pane text

`pane_current_command`: `claude` when it was typed in a bash pane (also the process name); `sh` when claude was the `new-session` command (tmux reports the
wrapping `sh -c`). The npm package of this version installs the native binary, so `node` was **not** observed; an old node-based install is untested.
Do not rely on it for idle/busy; it only says that claude is running.

From the text (`state()` in `lib.sh` and `enter.sh`; real screens in `dev/spikes/enter/screens/`):

| State | Text signal | Screen |
|---|---|---|
| dialog (permission, trust, managed, bypass) | `Enter to confirm`, `Esc to cancel`, `Esc to exit` or `Do you want to` anywhere | `dialog-*.txt` |
| busy (thinking, streaming, running a tool) | the footer (last line) contains `esc to interrupt` | `busy-streaming.txt` |
| idle | a line starting with `❯` between two rules, footer without `esc to interrupt` | `idle-after-answer.txt` |

Check dialogs first (a permission dialog also shows `esc to interrupt`? not seen: its footer is `Esc to cancel · Tab to amend`). The input box is the text
between the last two rule lines (`──────...`), the footer is the line after the last rule. After an answer ends the footer shows `✻ Worked for 9s · done 4:02 AM`
above the box (also usable as "answer finished").

**Idle does not mean the box is empty.** The box can hold (a) a dim ghost suggestion (`❯ make it shorter`, `Try "fix lint errors"`), (b) text left by a failed
submit. Only `capture-pane -e` tells ghost text: it is wrapped in `ESC[2m` (see `screens/idle-after-answer.escapes.txt`); the typed prompt echo in the history
has a background colour `48;5;237`. The model answer is a line starting with `●`.

## 5. Typing while busy

Typed text plus Enter while claude is answering is **queued, not lost, not interleaved**: the screen shows the message above the box with
`ctrl+x ctrl+s to send now`, the box says `Press up to edit queued messages`, and when the answer ends the queued message is sent and answered
(`screens/busy-with-queued-message.txt`, `idle-after-queued-message-ran.txt`; 3/3 in `poc-test.sh`). Text typed without Enter stays in the box
(the box is live during busy).

Safe rule for a driver: **type only when the state is idle, otherwise wait** (or refuse); queueing must be a conscious choice (`--queue`), because a queued
prompt runs after whatever the previous answer does, and an Esc to interrupt may not drop it (not tested).

## 6. Esc and Ctrl+C

| Situation | Esc | Ctrl+C |
|---|---|---|
| busy | interrupts (3/3, about 110 ms until `Interrupted · What should Claude do instead?`, state idle) | same (3/3) |
| idle, text in box | once: nothing; **twice quickly: clears the box** | **clears the box**, footer `Press Ctrl-C again to exit` |
| idle, empty box | (double Esc on an empty box probably opens the rewind menu, not tested) | arms exit: **a second Ctrl+C within about a second quits claude** (in one run two C-c 0.5 s apart exited and killed the pane) |

- Both keys work through `send-keys` (`Escape`, `C-c`). Use **Esc to interrupt** (harmless when idle) and never send Ctrl+C twice.
- `C-u` clears only one line per press in a multi-line box (3 lines needed more than 1 press); to clear the box send Ctrl+C when it is non-empty (check the box first,
  because on an empty box it arms the exit) or Esc Esc.
- After an interrupt, the typed prompt stays in the history and the box is empty; `state` is idle.

## PoC

`dev/spikes/enter/enter.sh [-L sock] -t target [--pause-ms 150] [--queue] [--allow-slash] [--no-enter] -- "text"`. Exit codes: 0 submitted, 3 dialog open (nothing
typed), 4 busy (nothing typed), 5 typed but not submitted, 6 text starts with `/` or `!`. `poc-test.sh` (real claude): 8/8 short prompts, 8/8 prompts of
600 chars with newline/quotes/backticks/`$`/unicode, busy refused (exit 4), `--queue` accepted and answered, slash refused (exit 6), permission dialog refused (exit 3).

## Recommendations for the build

1. `{"run": ...}` and `{"input": ...}` of the plain driver: `send-keys -l -- "$text"`, pause **150 ms**, then `send-keys Enter` as its own command. Never one burst.
2. Multi-line text can go in the same `-l` text; do not use `S-Enter`.
3. The sysop's `input` tool should check `idle` before typing, refuse a leading `/` or `!`, and verify afterwards that the text left the box (as `enter.sh`).
4. Idle test: no dialog markers, `❯` line present, no `esc to interrupt` in the footer. Do not take "box is empty" from text alone (ghost suggestions).
5. Interrupt with `Escape`. Clear the box with `C-c` only when it is non-empty.
6. Test harness: seed `.claude.json` and handle the managed-settings dialog in the boot loop.

## Not tested

Node-based (old) install and `pane_current_command=node`; very slow ttyd/web paths; load; `/` escape by a leading space; Esc behaviour with queued messages;
double Esc on an empty box; the real `--dangerously-skip-permissions` alias of the box end to end (only booted and the footer checked); other terminal sizes;
other Claude Code versions (this is 2.1.325, the UI texts used as signals can change).
