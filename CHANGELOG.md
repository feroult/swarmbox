# Changelog

All notable changes are listed here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the
project follows [semantic versioning](https://semver.org/).

## [Unreleased]

- Changed: what you install on demand (agents such as Claude Code, and gcloud, clasp, Go, Poetry, `voice`, `sysop`) is called an **addon**: `swarmbox addon list|install|remove|update|use|link|prepare|run|where|doctor|validate|new` (`swarmbox-addon` in the box), manifests in `container/addons/<name>/addon.conf`, with the commands of the addon in `COMMANDS` and its start-up in an optional `shell.sh` (the auto-approve flags of the agents live there: `claude` adds them only to the interactive prompt, so `claude update` and `claude mcp ...` do not get them). `yolo` runs the default agent, `AGENT` or else the first item of `WITH`, and says so when there is none. Needs `swarmbox update` and `swarmbox reset`, and addons are installed again on first use.
- Added: talk to your box, typed or spoken (the `sysop` addon and the `voice` addon). Give a goal in plain words ("run the tests in the second tab", "ask Claude in the active tab to fix the failing test") and the **sysop** operates the box for you: it looks at your tmux tabs, types into them, looks again and tells you what happened
  (`swarmbox addon install sysop`, and `swarmbox addon install voice` for the microphone; `docs/sysop.md`, `docs/voice.md`). It is optional and made of separate pieces that know nothing of each other; a box that installs none of them behaves as before.
  - **`sysop`** takes the goals of its topic, runs a brain (`claude -p` by default with every built-in tool off, so it needs the `claude` addon and a login, or any command that speaks MCP, `sysop.brain`) and gives it seven tools (`list_tabs`, `read_tab`, `run`, `input`, `wait`, `say`, `done`) that act only through `swarmbox-tabs`, so whatever it does is typed in a tab you can see.
    The host rates every `run` and `input`: a low risk goes at once (the default level `auto`), a medium one waits a few seconds for your veto, a high one waits for you to press Allow, a text that starts with `/` or `!` for an agent is refused, any key while a dialog of an agent is open is a high risk, and no autonomy level skips the approval of a high risk.
    It has step and time budgets, a stop command and an append-only audit file (kept to 32 MiB). Text read from a tab is treated as untrusted data. `swarmbox-sysop goal --wait "text"` gives a goal from a shell (exit 3 when nobody listens, 4 when the bus does not answer), `swarmbox-sysop status` shows the service and the last goals.
    The service runs under a small watcher: if it dies, it starts again by itself after 1, 2, 4 ... 30 seconds, and goals that were in flight are marked `failed`.
  - **The panel** is a pane of your tmux session that shows the goal, the log, the countdown and the approval prompt, and **never takes the focus on its own**: what you type keeps going to your tab. `sysop.panel` says when it is there: `always` (default: in every window from the start of the box, idle when there is no goal, at the right in a wide window and at the bottom in a narrow or portrait one),
    `auto` (it opens in the window you look at when a goal arrives and closes a few seconds after the last one) or `off` (never, unless you open it). Veto, stop, approve and type a goal are tmux prefix keys that work from any tab: `Ctrl+A` then `V`, `X`, `a`, `g`; `Ctrl+A` then `S` shows or hides the panel. A click on the panel gives it the focus and its own keys.
    A window never stays with only the panel in it. The panel is the only thing of the sysop in your tabs; it is code of this repository and downloads nothing.
  - **`voice`** is an input only. The web terminal gets a microphone button (hold, speak, release); Whisper (`whisper.cpp`, built inside the box, one multilingual model, `small` by default) turns the audio into text and publishes it as a goal on a bus topic. Only audio crosses the Cloudflare tunnel, through a fixed table of four routes on the web port.
    The page shows a state light and a short sentence only (`Sent`, `Nothing heard`, `Nobody is listening`, `Busy`, an error such as "The microphone needs https or localhost."), never the text. `swarmbox-voice say "text"` publishes a goal without a microphone. It does not plan, does not show a plan and does not touch tmux.
  - **The controls strip** is new in the web terminal: a slim bar under the terminal (the terminal is refitted above it, so it never covers the status bar and its clock) with **key buttons** for a phone, which has no Esc, Tab, Ctrl+C or arrows (`Esc`, `Tab`, `^C`, the arrows and `Panel`, which types `Ctrl+A S`; at least 44 px, they keep the focus in the terminal so the keyboard stays open),
    and a place at its right end where an addon puts its control (the microphone). The page also has a viewport meta tag now (a phone used to lay it out 980 px wide) and follows the on-screen keyboard. The strip also has green `Allow` and red `Cancel` buttons to answer the sysop with a thumb (on a desktop with only the microphone there is no bar: the microphone floats in the top right corner and takes no space), and it refuses to build itself inside a frame of another site (the front adds `frame-ancestors 'self'`). In `web-terminal.conf`: `strip=auto|on|off` (the buttons show on a touch screen or when you list them; the strip shows on any screen once the microphone is there) and `stripKeys=label=keys, ...` in tmux key names (`C-a S`, `F5`, ...); `swarmbox-web restart` applies them. With the strip hidden the page is exactly ttyd's, as before.
  - **The bus** (`swarmbox bus pub|sub|topics|watch|ping|restart`, `swarmbox-bus --help` in the box) is plain publish and subscribe inside the box, started and supervised at box start; nothing else depends on it. A topic is a free name that addons take from their settings; a message goes to every subscriber, and subscribers that give the same `--group` share the work, one member per message.
    Nothing is kept: the bus has no state, no reads and no tmux in it. `pub` prints how many subscribers received the message and exits 3 when nobody did (`--allow-none` accepts that), 7 when one is behind. The socket is private to your user.
  - **`swarmbox-tabs`** (`swarmbox tabs list|active|screen|send`) is the tmux tabs of the box as a capability of the host, called directly and never through a topic: it lists the tabs, says which one is active, reads one with the secrets removed (keys, tokens, a JWT, a run of 120 or more base64 characters; the colours of the screen as `[sel]`, `[bg]` and `[err]` spans),
    and types into one, the text and the Enter as separate steps under a lock per tab. It refuses a busy agent, an open dialog and a text that starts with `/` or `!` unless told otherwise. No daemon; every answer is JSON and errors are `{"err", "msg"}`.
  - **Settings** (all applied by `swarmbox reset`; one that equals its default is not passed to the box, so a box that never sets one keeps its fingerprint): `voice.topic` and `sysop.topic` (both `goal`: the same name is the only link between the two addons), `sysop.group` (`sysop`), `sysop.panel` (`always`; `auto` or `off`), `sysop.brain` (`claude`), `sysop.model` (`haiku`),
    `sysop.autonomy` (`auto`; `confirm-all` or `confirm-risky`), `sysop.countdown` (`4`), `sysop.max_steps` (`20`), `sysop.max_seconds` (`300`), and for the voice addon `voice.language` (`auto`), `voice.stt.model` (`small`), `voice.stt.vocabulary` (empty) and `voice.web` (`1`; `0` turns the voice front off). They reach the box as `SWARMBOX_VOICE_*` and `SWARMBOX_SYSOP_*`.
  - **Breaking:** `bus` and `tabs` are now words of the `swarmbox` script, so a program of the box called `bus` or `tabs` runs as `swarmbox attach bus` or `swarmbox attach tabs` (inside the box, `tabs` is swarmbox-tabs only as `swarmbox-tabs`; the system `tabs` utility for tab stops is not shadowed). The default tmux config binds the prefix keys `S`, `V`, `X`, `a` and `g`; a binding of yours in `~/.tmux.conf` is read after it and wins.
  Tested end to end in Podman with a real Claude Code in a tab and a headless browser whose microphone plays speech, and under a soak of faults (killed services, a full disk, bursts of resizes and goals); not tried with a human voice or a real phone. **Needs `swarmbox update` and `swarmbox reset`.**
- Fixed: nested Podman failed with `fuse: device not found` and `kernel does not support overlay fs` after some other run of Podman in the box (one `podman --root /tmp/...`, or a run with another `HOME`) had made it fall back to `fuse-overlayfs`, which the box has no `/dev/fuse` to run. The start of the box now removes that stale marker when `/dev/fuse` is not usable; to repair a running box, `rm -rf /tmp/storage-run-$(id -u) ~/.local/share/containers/storage/overlay/.has-mount-program` (`docs/nested-podman.md`). Needs `swarmbox update` and `swarmbox reset`.
- Fixed: a link that Claude Code shows as a label (an OSC 8 hyperlink) did nothing when clicked, in the browser and in a host terminal: tmux dropped the address of the link for `xterm*` clients, so only the label arrived. The tmux config now turns on the `hyperlinks` feature.
- Fixed: nested Podman did not start on macOS (the state folder is a shared drive that cannot hold a unix socket: the service now listens on the box's own disk) nor after a host reboot (`/tmp/podman-run-<uid>` also held the old boot ID).
- Changed: the sysop panel ends a goal with two or three whole lines, not a long result: the brain is told to summarize in two short sentences in its own words, a longer summary is sent back to it once to be written again, and only a runaway one is cut on the panel.
- Changed: on a phone the letters of the web terminal follow the width instead of a fixed 21 px: `(width - 20) / (columns * 0.6)` with 100 columns upright and 200 sideways, between 5 px and the configured `fontSize` (a 390 px phone: 6 px upright, 7 sideways; a size you set yourself in the console is left alone; `swarmboxStrip.setColumns(n)` in the browser console tries another target). A screen with a mouse wider than 600 px keeps the configured size.
- Changed: the logs of the box (`serve.log`, `bus.log`, `web-terminal.log`, `podman-service.log`) no longer grow for ever: every five minutes one that is past 4 MiB is cut to its last megabyte, with a line that says so. Needs `swarmbox update` and `swarmbox reset`.
- Fixed: `Ctrl+A a`, which `docs/web-terminal.md` gave for sending the prefix to a nested tmux, is `Ctrl+A Ctrl+A`.
- Added: `swarmbox-addon where NAME COMMAND`, which prints the real program of a complete install without installing anything.
- Dev only: `tests/e2e/e2e_sysop.sh` and `tests/e2e/e2e_voice.sh` (the real pieces, a real Claude Code and a headless browser, in Podman), `tests/e2e/soak_v1.sh` (the soak and fault run) and the real-tmux tests (`SWARMBOX_TEST_REAL_TMUX=1`) are not part of `dev/check.sh`.
- Dev only: the tests live in `tests/fast`, `tests/slow` (real tmux, browser, Podman) and `tests/e2e`, run by one runner, `sh tests/run.sh` (the fast ones, in parallel, by default); `dev/check.sh` and the pre-push hook run the fast ones, `sh dev/test-slow.sh` runs the slow ones in Podman, and `dev/mutate.py` measures what the tests would notice (`tests/README.md`).

## [2.0.13] - 2026-11-13

- Fixed: the colors of the Claude Code theme came out wrong inside tmux. Claude Code caps itself at 256 colors there unless `CLAUDE_CODE_TMUX_TRUECOLOR` is set, and turned every exact color into the nearest of 256 with a rough formula: the rose of an error
  (`#ff6b78`) came out as a salmon (`#ff8787`), and the grays of the borders were off. The shell of the box now sets it, because the tmux of the box declares RGB. Set it empty in your `~/.bashrc` to go back to 256. Needs `swarmbox update` and
  `swarmbox reset`.
- Added: `swarmbox-statusline`, a status line for Claude Code in the style of the box: `╶─ …/swarmbox ─ main ! ─ Sonnet 5.5 ─ ▰▰▰▱▱▱▱▱▱▱ 34% ─ 5h 71%`, the context as a bar that is violet, fuchsia from 70% and rose from 90%, and the usage limits when
  Claude Code reports them. It is not on by default: put `"statusLine": {"type": "command", "command": "swarmbox-statusline"}` in `~/.claude/settings.json`.
- Changed: the whole box is in one palette, the purple glow (`docs/theme.md`). The browser terminal has new colors: a near-black background (`#0c0b10`), `#d4d4d8` text, a lavender cursor and a violet selection, and its 16 colors are
  tones of the same family (blue is a violet, so what a program paints blue is violet; red, green and yellow keep their meaning). `ls` (folders violet, links lavender) and `grep` (the match lavender) use 256-colour numbers, so they look
  the same in any terminal scheme, and the messages of the scripts use two fixed grays; the scrollbar of the browser is violet. `theme=` in `web-terminal.conf` still replaces the whole theme of the browser terminal, and `LS_COLORS` and
  `GREP_COLORS` in your `~/.bashrc` still win. New in `docs/theme/`: a color scheme for Windows Terminal and one for Ghostty with the same palette, so the terminal you run the box in can match it, and the theme of Claude Code
  (`custom:swarmbox-purple-glow`, 29 colors: the selection, permissions, suggestions, the prompt box, user messages, Claude's orange, and the tones of errors, successes and warnings). Needs `swarmbox update` and `swarmbox reset`.
- Changed: a selection made in the web terminal with the browser's own selection (Shift and drag, which skips tmux) is the violet of the box (`#6d28d9`, light text), the same as tmux's, and no longer the steel blue of the old theme. A selection made
  by dragging with the mouse is tmux's and was already violet. A program that takes the mouse for itself (a full-screen TUI) draws its own selection in its own colors; that is not tmux's and not ours. Needs `swarmbox update` and `swarmbox reset`.
- Changed: the line under the banner now says what the box is for: `// your agent's shell, from anywhere` (it was `// agent box`). It is in the dark grays of the box, with the `//` darkest and the last word darkening letter by letter.
  Needs `swarmbox update` and `swarmbox reset`.

## [2.0.12] - 2026-11-13

- Fixed: the glint of the banner. A pass from left to right stopped one step too soon and left one cell of the last row a shade lighter until the next pass; it now ends past the last column. And a step no longer rewrites the three rows whole: it writes
  only the cells that change (about 210 bytes a step in place of 940, and about five times less for tmux to send to the terminal), which should help a terminal that draws while it is still receiving. It was reported as flicker of little white
  blocks in Ghostty on a Mac; that is not reproduced here, so whether it is gone is for you to say. New: `set -g @swarmbox-glint off` in your `~/.tmux.conf` turns the glint off, and `tmux set -g @swarmbox-glint off` (or `on`) does it at once, in a
  box that is already open. Needs `swarmbox update` and `swarmbox reset`.
- Changed: the progress line of `swarmbox update` (and of the first pull) is minimal and in the violet and gray of the box: `pull  ▰▰▰▰▰▰▱▱▱▱▱▱▱▱▱▱ 42%  130/310 MB · 4.1 MB/s 32s`, the filled part of the bar in violet and the rest in dark gray, and a
  `✓ pulled <image> · 310 MB in 1m05s` that stays when it is done. The four colored blocks, the powerline arrows and the icon are gone, and so is `SWARMBOX_ICONS`: nothing in the line needs a Nerd Font any more. As before, a narrow
  terminal drops the right-hand parts, `NO_COLOR=1` turns the colors off, a locale without UTF-8 gives `#` and `-`, and `SWARMBOX_PROGRESS=plain` leaves Podman's own bars.

## [2.0.11] - 2026-11-13

- Changed: the banner is lighter. The half-block lettering keeps its dark gray and purple glow, but the rounded frame and the two tagline lines are gone: under the letters there is now a segmented bar that lights up
  like them, and a dim `// agent box` on the right. The glint that crosses the letters in a tmux pane is the same. Needs `swarmbox update` and `swarmbox reset`.
- Changed: the prompt is one line again, in the style of the banner: thin gray `─` separators, the user, the directory, the branch, the language, the Docker context and the time in gray and violet, the directory on a soft band whose edges fade in and out with `░▒▓` like the old BBS screens, and a violet `❯` at the end. There is a blank line above every prompt, so one command does not stick to the output of the one before (the banner lost its own blank line at the bottom for it). It no
  longer uses any Nerd Font glyph (the language symbols are short words such as `py`, `go` and `node`), so it looks the same in any terminal font. The colored ribbon is gone. A `~/.config/starship.toml` of your own is untouched
  and still wins. Needs `swarmbox update` and `swarmbox reset`.
- Changed: the tmux theme follows the banner and the prompt: dark gray and violet instead of the pastel one. The current window sits on the same soft band as the directory of the prompt, with a dithered `▒` at each edge; the other windows,
  the date and the time are gray with thin `─` dashes, and every window is the same width, so nothing moves when you change window. The session name is no longer shown. The active pane border and the copy-mode selection are violet.
  The `[+]` button keeps its first three columns, now in gray. Put your own `set -g status-style ...` and the like in `~/.tmux.conf`, which is read after this file. Needs `swarmbox update` and `swarmbox reset`.
- Changed: the tmux scrollbar is off by default. The pane keeps its whole width; in copy mode tmux still shows where you are (`[position/total]`) and the wheel scrolls 5 lines per event.
  `set -g pane-scrollbars on` in your `~/.tmux.conf` brings the bar back. Needs `swarmbox update` and `swarmbox reset`.
- Dev only: `dev/local-up.sh` builds the image from the checkout and switches your box to it in one command (and `--release` goes back to the published image), so a change can be tried without a release.

## [2.0.10] - 2026-11-12

- Changed: a new banner. Half-block lettering in a rounded frame, like the login screen of a 90s BBS, in a gradient that runs across the whole word: dark gray and purple that light up to white in the middle and fade
  out again. In a tmux pane, which is where the box always runs, a glint crosses the letters back and forth every few seconds, from a background process, so the shell never waits for it. It writes only
  when the screen has been still, skips a frame if anything moved, and stops when the banner has scrolled away or been cleared; outside tmux there is no glint. It needs 256 colours. Needs `swarmbox update` and `swarmbox reset`.
- Changed: the prompt follows the banner: its segments go from dark gray through purple and back to gray, with one light text colour on all of them. The roles of the palette in `starship.toml` changed (`color_text` is the text colour);
  a `~/.config/starship.toml` of your own is untouched and still wins. Needs `swarmbox update` and `swarmbox reset`.
- Dev only: `banner.sh` is in the shellcheck list of the CI; a comment and a line of `design.md` no longer say that the pull progress bar follows the colours of the prompt.
- Changed: the thumb of the tmux scrollbar is dimmer (a dark gray, `colour238`, on a transparent track), so the bar is there when you look for it and out of the way when you do not. It is already one column, the least tmux
  allows. Change it with `set -g pane-scrollbars-style "bg=default,fg=colourNNN,width=1"` in your `~/.tmux.conf` (236 nearly vanishes, 243 is the lighter gray of 2.0.9). Needs `swarmbox update` and `swarmbox reset`.

## [2.0.9] - 2026-11-12

- Added: tmux has a scrollbar again, and this one works: a thin bar on the right of the pane, showing where you are in the 50,000 lines of history; drag it with the mouse or click its track.
  It is one column wide and always on, on purpose: a bar that showed only while scrolling would resize the pane each time, and a program with columns would reflow while you read. A full-screen program
  (vim, less, a TUI) gets the whole width and no bar, and one that asks for the mouse gets the wheel itself. The image now carries tmux 3.7c (Debian 13 has 3.5a, which has no scrollbar),
  a Debian backport pinned by SHA-256 so every build gets the same file. `set -g pane-scrollbars off` (or `modal`) in your `~/.tmux.conf` changes it. Needs `swarmbox update` and `swarmbox reset`.

## [2.0.8] - 2026-11-12

- Changed: a tab that leaves and comes back (`exit`, then `swarmbox` again in the same terminal tab) is now put back in the same place in the browser, not at the end. The host passes the
  `tty` of the terminal tab, which names it in any terminal or over ssh, and the box keeps the host tabs in the order they first appeared. Dragging the tabs of your terminal is not followed,
  and a window opened from the browser (`Alt+N`) can end up on either side of a returning tab. Needs `swarmbox update` and `swarmbox reset`.
## [2.0.7] - 2026-11-11

- Changed: `exit` in a host terminal tab now ends `swarmbox` and returns you to your own shell. Before, with two tabs open, it closed the window and moved you to the
  shell of the other tab. Each tab has a session of its own with its window linked into the box's session, so the browser still shows every tab, and closing a host tab
  only detaches (the window keeps running and stays in the browser). Needs `swarmbox update` and `swarmbox reset`.
- Dev only: a local gate (`dev/check.sh` and a pre-push hook) and `dev/release.sh`, which releases from a CHANGELOG written beforehand; see CONTRIBUTING.md.

## [2.0.6] - 2026-11-11

- Changed: the web terminal has no scrollbar by default. tmux owns the scrollback (50,000 lines) and the browser has no history of its own, so the bar sat still while the wheel
  scrolled tmux. `scrollbar=true` in `web-terminal.conf` brings back the thin one. Without the bar the browser keeps no scrollback (`scrollback=0` unless you set one): xterm.js reserves
  15 px for a scrollbar it measures as zero width, which cost a column of text.
- Changed: the mouse wheel scrolls tmux's copy mode 5 lines per event (tmux's default) instead of 2. How to change it is in `docs/web-terminal.md`.
- Tests: the browser tests of the web terminal now start ttyd with the options `swarmbox-web run` builds, as in the box, and a real tmux checks the lines per wheel event.

## [2.0.5] - 2026-11-11

- Added: a progress line for the image pull in `swarmbox update`, the first `swarmbox` and the installer, in the colors of the prompt of the box: `[ pull ][ bar and percentage ][ MB done/total ][ MB/s and time ]`,
  and `unpack` when the download is over and Podman writes the layers out. The bytes come from Podman's temporary download folder and the total from the layer sizes of the manifest on `ghcr.io`
  (read with `curl` in the background; without it the bar sweeps and shows no percentage). Powerline separators and an icon are on when Starship runs in your shell (`SWARMBOX_ICONS=1` or `0` forces them);
  `NO_COLOR=1` turns the colors off; `SWARMBOX_PROGRESS=plain` goes back to Podman's own bars; without a terminal the pull stays quiet. A failed pull shows the last lines of Podman's error.

## [2.0.4] - 2026-11-11

- Added: the installers (`install.sh` and `podman run IMAGE install | sh`) write `sx`, a short name for `swarmbox` (`sx up`, `sx claude`), next to the script.
  It is a two-line script that runs the `swarmbox` beside it, so `swarmbox update` keeps working and `sx` always follows it.
  It is written only when nothing else answers to `sx`: no other file of that name in the folder and no `sx` anywhere on the `PATH`
  (a startx replacement has that name); an existing `sx` is never touched and the installer says why none was written. `SWARMBOX_NO_SX=1` skips it.
  A box that is only updated does not get it: run the installer again.

## [2.0.3] - 2026-11-11

- Fixed: `swarmbox update`, the first `swarmbox` and the installer (`install.sh`, `podman run IMAGE install | sh`) showed no progress while they pulled the image, so they looked stuck.
  When standard error is a terminal the pull now shows Podman's own progress, and a failed pull points at the error already on screen. Without a terminal (a script, a log) the pull stays quiet as before.
- The installer now pulls the image in its own step, with the message "pulling IMAGE (this can take a while)...", before it reads the support files from it.

## [2.0.2] - 2026-11-11

Fixes the nested Podman not starting after a host reboot.

- Fixed: after a host reboot the box is stopped and later started again with its own filesystem intact. The nested Podman keeps its runtime state in
  `/tmp/storage-run-<uid>` inside that filesystem, with the boot ID of the previous boot, and refused to start: "current system boot ID differs from cached boot ID;
  an unhandled reboot has occurred". `serve` now removes that folder before it starts the nested service, when it exists, and says so in `serve.log`.
  Nothing of a previous run is alive when `serve` starts, and the nested images and containers are in the volume, not in that folder.

## [2.0.1] - 2026-11-11

Fixes a box that never became ready after a host reboot.

- Fixed: after a host reboot the box's run folder (`/tmp/swarmbox`, a tmpfs) could come back as a folder the agent user cannot write. `serve` then could not write the
  readiness marker or the ttyd pid file, the web terminal gave up after five crashes, and `swarmbox` waited 60 s and failed with "the box did not become ready".
  `serve` now checks the folder first and, when it is not writable, makes it writable with `sudo chmod 1777` (the agent has sudo in the box) and says so in `serve.log`.
- When the box is running but never writes its readiness marker, `swarmbox` now prints the last 15 lines of the box's log before it exits with status 6, so the cause is on screen.
- The cause of the unwritable folder after a reboot is not known; if the nested Podman service still does not start after this fix, send `podman-service.log`.

## [2.0.0] - 2026-11-11

First stable version. Same feature set as the two prereleases (below), with these changes since 2.0.0-beta.2:

- The README now walks through the install from zero with Claude Code (Podman, the installer, the login, the first run) and through remote access to the same tmux session (from a browser with Cloudflare, or over SSH to your machine).
- The image is published at `ghcr.io/feroult/swarmbox` with the tags `2.0.0`, `2.0` and `latest`; `swarmbox update` follows the `2.0` series.

### Features

- One persistent rootless Podman box per workspace; every terminal tab and the browser join the same tmux session.
- A small neutral image (`node:24-trixie-slim`, user `agent`, about 1.75 GB) with no agent inside. Claude Code, Gemini CLI, OpenCode, gcloud, clasp, Go and Poetry
  install on first use from manifests, through shims, with pinned versions and checksums where the vendor publishes them.
- The workspace is one folder of your machine and holds projects, logins, the SSH key and installed tools; the box can be recreated without loss (`swarmbox reset`).
- One executable POSIX `sh` script, `swarmbox`, on the `PATH` (no shell function, no startup file): `up`, `stop`, `reset`, `url`, `update`, `config`, `env`, `pubkey`, `tool`, `remote`, `fingerprint`, `version`; any other word runs in the box.
- Two ways to install it, with the same result: `podman run --rm IMAGE install [--with TOOLS] | sh`, and `install.sh`, which downloads `swarmbox` from a release and checks its sha256. The release attaches `swarmbox`, `swarmbox.sha256` and `install.sh`.
- `swarmbox <command>` runs a command in the box and returns its exit status; `--plain` skips tmux.
- Creation settings in one host file, compared on every entry by a fingerprint; variables are passed by name at creation and never written to disk.
- Nested Podman, always on, with the host connection (`podman -c`) and a short-symlink fallback for long socket paths.
- A web terminal (ttyd and tmux) on `127.0.0.1`, supervised inside the box; optional remote access with Cloudflare Tunnel and Access (`swarmbox remote setup|status|off|token`),
  with the credentials and the connector on the host.
- Chrome DevTools MCP with Chromium in the image, written to the MCP configuration of the agents.
- `swarmbox update [--to TAG]` refreshes the script from the new image (never by an older one) and uses an exact local tag, so a later `reset` works offline and a rollback is one command.
- No telemetry; logs stay on your machine.
- XDG-aware paths on the host and in the box.
- `LICENSE` (Apache-2.0), `THIRD_PARTY_NOTICES.md`, `CONTRIBUTING.md`, `SECURITY.md`, `CODE_OF_CONDUCT.md`, a CI workflow and a signed multi-arch release workflow.

### Known limits

macOS with a real Podman machine, Podman older than 4.3, a host user other than UID 1000 and the real Cloudflare setup are not verified. A container shares the host kernel:
see [SECURITY.md](SECURITY.md) and [docs/microvm.md](docs/microvm.md).

## [2.0.0-beta.2] - 2026-11-11

Second prerelease of 2.0.0, tagged `2.0.0-beta.2` only. Install it with `sh install.sh --version 2.0.0-beta.2`, or move from a
beta.1 box with `swarmbox update --to 2.0.0-beta.2`. Changes since beta.1:

- Fixed: with `BROWSER_URL` set, the Chrome DevTools MCP now attaches to that browser. `swarmbox-mcp` read a variable the host never
  passes (`BROWSER_URL`) instead of `SWARMBOX_BROWSER_URL`, so the generated MCP file kept the headless Chromium of the box.
- The web terminal treats Option as Meta on a Mac, so Option+1..9 and Option+N change and open tmux windows (`macOptionIsMeta=false`
  in `web-terminal.conf` brings the special characters back).
- The `tmux` status bar stays visible in the browser, so every window is listed.
- macOS test and CI fixes (macos-15 runner, tests run one by one).

## [2.0.0-beta.1] - 2026-11-11

First public prerelease of 2.0.0, for testing before the final release. The image is tagged `2.0.0-beta.1` only (never `2.0` or
`latest`) and the GitHub release is marked as a prerelease. Install it with `sh install.sh --version 2.0.0-beta.1`;
`swarmbox update` follows the `2.0` series, which exists only once 2.0.0 is out, so until then move between betas with
`swarmbox update --to TAG`. The feature list is the one of 2.0.0 below. Changes while preparing it: the base image is
`node:24-trixie-slim` (Debian 13) with Podman 5.4; `criu` and its `python3-protobuf` are removed from the image; the Go
standard library findings that Debian 13 has not fixed yet are listed, with the reasons, in `.grype.yaml`.

[2.0.13]: https://github.com/feroult/swarmbox/releases/tag/v2.0.13
[2.0.12]: https://github.com/feroult/swarmbox/releases/tag/v2.0.12
[2.0.11]: https://github.com/feroult/swarmbox/releases/tag/v2.0.11
[2.0.10]: https://github.com/feroult/swarmbox/releases/tag/v2.0.10
[2.0.9]: https://github.com/feroult/swarmbox/releases/tag/v2.0.9
[2.0.8]: https://github.com/feroult/swarmbox/releases/tag/v2.0.8
[2.0.7]: https://github.com/feroult/swarmbox/releases/tag/v2.0.7
[2.0.6]: https://github.com/feroult/swarmbox/releases/tag/v2.0.6
[2.0.5]: https://github.com/feroult/swarmbox/releases/tag/v2.0.5
[2.0.4]: https://github.com/feroult/swarmbox/releases/tag/v2.0.4
[2.0.3]: https://github.com/feroult/swarmbox/releases/tag/v2.0.3
[2.0.2]: https://github.com/feroult/swarmbox/releases/tag/v2.0.2
[2.0.1]: https://github.com/feroult/swarmbox/releases/tag/v2.0.1
[2.0.0]: https://github.com/feroult/swarmbox/releases/tag/v2.0.0
