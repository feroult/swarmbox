# Spike: tmux facts for the bus

Run with tmux 3.5a (the test image) and 3.7c (trixie-backports, what the box image pins: see `TMUX_VERSION` in the Dockerfile). All 24 tests pass on both.
Code: `dev/spikes/tmux-facts/tmuxfacts.py` (standard library), tests `test_tmuxfacts.py`, run with `dev/spikes/tmux-facts/run-in-container.sh [image]`
(real tmux, real pty clients, private socket, inside Podman). Fixtures: real Claude Code 2.1.325 screens in `fixtures/`.

## 1. `ls tab/` and which tab is active

Topology of the box (`swarmbox-attach`): session `main` holds every window (linked); each host terminal has a session of its own with only its window;
the browser attaches to `main`.

- **Two clients of the same session always show the same window.** A session has one current window; `select-window` in one client moves both.
  So "two clients showing different windows" only exists across sessions, which is exactly the box topology.
- `list-clients -F '#{client_activity} #{client_session} #{window_id}'`: in that format `window_id` is the window **that client's session shows**.
  Verified: keys typed in the client of session t1, then t2, then `main` move the answer to tab1, tab2, idle.
- **Rule (implemented in `shown_window`)**: among clients that are not control mode (`#{client_control_mode}` is 0; a control client, which the bus
  may use, has the newest activity and would always win), take the highest `client_activity`, and its `window_id` is the active tab. With no client:
  the current window of `main` (`display-message -p -t =main: '#{window_id}'`).
- Traps: `client_activity` has **one-second resolution**, so two keystrokes in the same second tie (the first in `list-clients` order wins; the
  window follows the client that sized it last, `window-size latest`, which is not the same thing). `window_active` (the flag in `list-windows`) is only
  the current window of ONE session and is wrong for host terminals. A window linked into `main` appears once per session: dedupe by `@id`.
- Listing command: `tmux list-panes -s -t =main -F '#{window_id}|#{window_index}|#{window_name}|#{pane_id}|#{pane_active}|#{pane_current_path}|#{pane_current_command}|#{pane_last}|#{@swarmbox_sysop_panel}|#{@swarmbox_voice_panel}'`
  (separator `@@sb@@`, not a tab: 3.6+ prints control characters of a list as `_`). One tmux call, 6 ms for 10 windows.
- **Hiding panels**: a pane with the pane option `@swarmbox_sysop_panel` (or the existing `@swarmbox_voice_panel`) set is never listed nor a target; a
  window made only of panels is not listed. When the focus is in a panel, the tab's pane is the one with `pane_last` (the program the user was on).
  The voice **front** has no tmux pane (it is the audio entry on the web port), so there is nothing to exclude.
- `pane_current_command` of `new-window "sleep 300"` is `sh`, not `sleep` (dash does not exec); `exec sleep` gives `sleep`. For claude it is `claude`.

## 2. Addressing and duplicates

- Tab address = **`@window_id`** (canonical, stable for the life of the window, never reused). Readable label = `index:name` (`2:editor`).
- `resolve()` accepts `@3`, `@3.%7`, `%7`, an index, or a name; a name used twice raises `AmbiguousTab` listing the candidates, and the sysop must say
  `@id` or the index.
- Verified: with `renumber-windows on` (the box config) closing a window shifts the indexes of the others but every `@id` still means the same window;
  a stale `@id` raises (tmux does not reuse it) instead of hitting another window. So: **show `index:name` to the model, but let it pass `@id`**, and
  re-list when a call fails. Never address by index across a step that can close a window.
- Targets: `%id` alone is global and unambiguous (also for a window linked in two sessions), `@id` alone means its active pane, `@id.%id` works. A bare `@id`
  of a linked window is looked up in the first session that has it (see the comment in `swarmbox-attach.sh`): use `%pane` for capture and keys.

## 3. The screen

- `capture-pane -p` returns the screen only (height lines); `-S -N` adds N lines **above the top** of the screen (total N + height), so `screen(lines=N)`
  keeps the last N of the capture. `-J` joins wrapped lines (a 205-char line is one line instead of three) and keeps trailing spaces (cut by the converter).
  `-S -` gives the whole history. Scrollback is bounded by `history-limit` (box: 50000; tested with 100: only the last ~100 lines exist).
- `-e` emits SGR as `ESC[7m`, `ESC[1m ESC[31m`, `ESC[38;5;Nm`, `ESC[39m`, `ESC(B` (charset reset), no OSC. Per-word colouring (Claude) produces one escape per word.
- **Alternate screen** (`less`, `vim`, **Claude Code itself**: `alternate_on` is 1): the capture is the alternate screen only, `-S` does not reach the shell's
  scrollback (history_size 0), `capture-pane -a` returns the normal screen saved underneath. Consequence: for a tab running Claude Code there is **no scrollback to read**,
  only the visible screen (`lines` is useless there). Flag it in the answer with `alternate`.
- `cursor_x`, `cursor_y` (cells of the pane, 0 based) work (less: bottom line after `:`, Claude: inside the input box, vim: 0,0). `pane_in_mode` and `pane_mode`
  (`copy-mode`) say whether the pane is in a mode; the capture then shows the content under the mode.
- **Converter `to_marked`**: spans `[sel]..[/sel]` for reverse video (SGR 7), `[bg]..[/bg]` for a background colour that has letters or digits, `[err]..[/err]` for red text
  (ANSI red, 256-colour reds, true red), `[b]` for bold (off by default). A span never crosses a line; spans of only spaces (a reverse cursor cell) and trailing spaces are dropped;
  neighbours with the same marker merge.
- **Do the markers expose the highlighted option? It depends on the program, measured:**
  | program | how it shows the current option | text with markers |
  |---|---|---|
  | **Claude Code** (permission, trust, theme dialogs) | pointer `❯` plus colour 38;5;153 on the pointer and the label, **no reverse, no background** | `❯ 2. Yes, and always allow ...`; the pointer in the plain text is the signal. Unselected lines have two leading spaces |
  | fzf | background 236 on the line plus bold, pointer `▌` | `[bg]alpha[/bg]` on exactly one line |
  | printf with SGR 7 (ncurses-like bars) | reverse | `[sel]two[/sel]` |
  | bash `select` | nothing (the numbered list is the menu) | plain text |
  So for Claude Code `[sel]` stays silent and the **`❯` in the text is the highlight**; tell the model that. Do not colour-guess (153 is the dark theme's colour; other themes differ).
  Claude paints your own prompt echo with a background (`[bg]❯ Reply with just the word PONG[/bg]`) and its logo with blocks: blocks are dropped (no letters), the echo shows as `[bg]`, harmless but name it
  "background" and not "selection" in the tool description.
- Fixtures `fixtures/claude-*.raw` are real screens (`capture-claude.py` makes them): permission dialog with option 1 and with option 2 selected, folder trust, theme.

## 4. Secrets filter

- `context.redact` works on marked text: `sk-...` inside `[sel]..[/sel]`, `TOKEN=[sel]x[/sel]`, a PEM block with a marker inside are all redacted; plain tags are untouched.
  It must run **after** the conversion, not on the raw `-e` text: a secret split by an escape (`sk-ESC[1m...`) is not found in the raw text (tested).
- **Trouble found: `redact` is quadratic on a long run of one character.** 5000 `-`: 0.3 s, 20000: 4.4 s, **100000: 110 s** (the `_FLAG` pattern, `--...key` scanned to the end for every
  start). A `-J`-joined minified file or a progress bar is such a line. Fix in the module: `clip_lines` cuts every line to 1000 characters **before** the filter (60 lines of 1000 dashes: 0.68 s, worst
  case that remains). The build should also bound `[A-Za-z0-9-]*` in `_FLAG` and `_ASSIGN` in `context.py` (I did not touch it, outside the spike).
- Cost (10 windows, 50 lines each, in the container): `list_tabs()` 6 ms; `screen()` of all ten 40 ms (19 ms of it is the ten `capture-pane` processes); a `redact` of normal screens is
  not measurable. A single tab read is about 4 ms.

## 5. send-keys

Bytes that reach a raw-mode program (measured with a probe in a pane):

| call | bytes |
|---|---|
| `send-keys -l -- 'ab'` | `ab` (always put `--`: a text starting with `-` is safe) |
| `Enter` / `Escape` / `C-c` / `Tab` / `BSpace` / `Space` | `0d` / `1b` / `03` / `09` / `7f` / `20` |
| `Up` / `Down` | `ESC [ A` / `ESC [ B` (normal cursor-key mode) |
| `-l` with `ç { } " ' $HOME ; \` and a tab | typed unchanged, UTF-8 intact |
| `-l 'one\ntwo'` | `one 0a two`: **LF, not Enter**. In Claude Code LF inserts a **newline in the input box**, it does not submit (tested: two lines `aaa` / `bbb`) |
| `-l` with a CR (`\r`) inside | acts as Enter (tested: submitted a prompt in Claude Code) |
| `paste-buffer -p` of `a\nb` | `a 0d b`; brackets only if the program enabled mode 2004 |

- **Key translation (`parse_keys`)**: `{Name}` is a key only for these case-sensitive names: `Esc Enter Tab BTab Space BSpace Up Down Left Right Home End PgUp PgDn Delete Insert`,
  `C-a..C-z`, `M-<char>`, `F1..F12`. Any other `{word}` is literal text (`{"a": 1}`, `{foo}`), a `{` right after `$` is never a key (`${HOME}` and `${Home}` stay shell variables; the
  first version took `{HOME}` for the Home key, found by a test), and **`{{` and `}}` are a literal brace** (`{{Esc}}` types the text `{Esc}`). Text and each key go in separate
  `send-keys` calls with a pause between them (`PAUSE = 0.15`, the design value).
- Against the real Claude Code TUI (2.1.325, manual mode): text then `Enter` after 150 ms submitted; text and `Enter` as two back-to-back tmux processes (a few ms) also submitted;
  both for a one-line prompt. A long or multi-line text with the Enter right behind it was **not** tested: the paste-detection risk of the design is open.
  Claude: `C-u` deletes one line of the input per press, so clearing a multi-line input takes several.
- **Copy-mode swallows keys**: with `pane_in_mode` 1, `send-keys` goes to the mode, nothing reaches the program (tested: the bytes never arrived and the pane stayed in copy-mode).
  `send()` checks `#{pane_in_mode}` and runs `send-keys -X cancel` first (or raises with `cancel_mode=False`). The user's copy-mode position is lost; the alternative is to refuse and tell the model.
- Addressing: `-t %pane` (pane ids are global).

## 6. Events (control mode)

`tmux -C attach -t main` (a control client, flagged and excluded from "active") pushes, verified on both versions: `%window-add @id`, `%window-close @id`, `%window-renamed @id name`,
`%unlinked-window-add/-close/-renamed` (windows of other sessions), `%sessions-changed`, `%client-session-changed`, `%output %pane <octal-escaped bytes>` for **every** pane, even one nobody looks at
(a ready-made "something changed in tab X" signal, but it is the whole byte stream: count, do not parse). `refresh-client -B 'w:@*:#{window_name}'` gives
`%subscription-changed` for any format, **polled once a second** (quote it: an unquoted `#` is a comment in the control channel). Cost: one process and one pipe. Enough for the bus to push
"tab changed" later.

## 7. Panel marking and the dock for the sysop

Verified: the `window-resized` hook runs with `#{hook_window}` (the resized window) and `#{window_width}x#{window_height}`; after a client resized from 100x30 to 150x40 the log held
`@0 150x39` (status line taken off) and nothing for the window nobody shows. `#{window_id}` and `#{pane_id}` also resolve inside the command. Panes marked with a pane option are found
by `list-panes -s -F '#{@opt}'` in the same call as the listing.

What must change in `dock.py` for a panel that belongs to the sysop and docks per window shape:
- the mark: new option `@swarmbox_sysop_panel` (and `SWARMBOX_SYSOP_PANEL=1` in the start command); `tmuxfacts.HIDDEN_OPTIONS` already lists both while `voice` still has its panel.
- **One panel per window, not one for the whole session.** Today `open` kills every extra panel and MOVES the one panel to the shown window; `redock` takes `panels[0]`. Per window: group rows by
  `window_id`, keep one panel per window, never kill the panel of another window.
- **The hook must carry the window**: `window-resized[417]` runs `run-shell -b "#{@opt}"`; it should pass `#{hook_window}` (`... dock redock --window '#{hook_window}'`) and `redock` fits only that window
  (`layout(window_w, window_h)` is already a pure function on the window size). Because a window follows the last active client (`window-size latest`) the hook fires when another client becomes the latest.
- The lock stays per user; the hook removes itself when no panel is left in any window (today: none at all).
- `shape_of`, `layout`, `split_args` are reusable as they are. The focus rule (`focus=False` on redock) matters more: the panel of the sysop must never steal the focus from the program being driven.
- The panel is outside `list_tabs` by construction (option), so the sysop never reads itself.

## Facts the build can rely on, and what is open

- Use `@id` for tabs, `%pane` for tmux targets, `list-clients` activity (non control) for "active", clip then redact then return, `-l --` for text, separate calls with a pause for keys, cancel copy mode first.
- Open: long/multi-line text plus Enter in Claude Code (paste detection); the one-second tie of `client_activity`; behaviour under several `main` clients attached to the real `swarmbox-attach`
  topology of the box (tested with the same shape built by hand, not the real script); tmux mouse/focus events and the `focus-events` option (Claude prints "focus-events off").
