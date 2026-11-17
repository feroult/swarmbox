# Web terminal

The box serves its shell in a browser (ttyd + tmux, so sessions survive closing the tab). It is on by default and listens on
`127.0.0.1:<WEB_PORT>` of your machine, port 7681 unless you change it. `swarmbox url` prints the address (and the public one, when
`swarmbox remote setup` has been run). A second box needs its own port: `SWARMBOX_NAME=dev swarmbox config set WEB_PORT 7682`, then
`SWARMBOX_NAME=dev swarmbox reset`. `swarmbox config set WEB 0` turns it off (the port is a creation setting: `swarmbox reset` applies it).
Inside the box ttyd always uses port 7681; `WEB_PORT` is only the host side of the mapping. There is no host-network mode in 2.0.

**Same tabs in the browser and in your terminal**: the shell `swarmbox` opens in your host terminal is a new
window of the same tmux session (`main`) the browser shows, so each host tab is also a tab in the browser. In your terminal it
behaves like any program: **`exit` ends the shell and returns you to your own shell**, it does not move you to the window of another
tab (the tmux tabs are for the browser). Closing the host tab only detaches: the window keeps running and stays in the browser until its
shell exits. A tab that leaves and comes back is **put back in the same place in the browser**: the host passes the pty of the terminal tab
(`tty`, the same for as long as the tab lives, in any terminal or over ssh) and the box keeps the host tabs in the order they first appeared, so after
`exit` and `swarmbox` again in the leftmost tab the browser shows it on the left, not at the end. What is kept is the order of the host tabs among
themselves: dragging the tabs of your terminal is not followed (nothing tells the box), and a window opened from the browser (`Alt+N`) can end up on either side of a
returning tab. Nested tmux: if your host terminal also
runs tmux, give it another prefix (SwarmBox uses `C-a`) or press `C-a C-a` to send the prefix inside (`C-a a` is the allow key of the sysop).
`swarmbox --plain` gives the plain bash instead.

**Font, size, theme**: out of the box the terminal is dark (Windows Terminal's Campbell colors, with the violet of the box for a selection made in the browser, the one tmux uses for its own), size 21, with a
Nerd Font list (JetBrainsMono, Cascadia). To change any of it, put `key=value` lines (xterm.js options) in `<workspace>/.config/swarmbox/web-terminal.conf`
(`~/.config/swarmbox/web-terminal.conf` inside the box), e.g. `fontFamily='JetBrainsMono Nerd Font', Consolas, monospace`.
`padding=10` is the space (px) around the terminal (CSS in
`container/web/ttyd-style.css`, joined into ttyd's page when the image is built). A `theme` line replaces the whole default theme. No rebuild and no new box: run `swarmbox-web restart` inside the box to apply (the box and its tmux sessions stay up). The page is rendered again at every ttyd start, by a plain text substitution of `padding`, `ctrlVPaste`, `ctrlCCopy`, `scrollbar`, `strip` and `stripKeys`; every other key goes to ttyd as `-t key=value`. The font is
the *browser's*, so it must be installed on the machine that opens the page.

**tmux.** The image ships a complete default config, `container/config/tmux.conf` (installed as `/etc/tmux.conf`): prefix
`Ctrl+A`, windows and panes numbered from 1, mouse, 50,000 lines of history, true color, a dark status bar, splits
and new windows in the current directory, and the browser shortcuts below. It stands alone: nothing in your
workspace is needed. Your own `~/.tmux.conf` (`<workspace>/.tmux.conf` on the host) is read *after* it, so add to it or
override anything there (`unbind -n M-n`, `set -g prefix C-b`, another theme).

Ctrl+T/N/W and Ctrl+Shift+T belong to the browser (and xterm.js sends nothing, or only the plain control
character, for most other Ctrl combinations), so `container/config/tmux-browser-keys.conf` (loaded by the default config)
binds **Alt** instead, without the prefix:
`Alt+N` new window, `Alt+W` close (asks), `Alt+H`/`Alt+L` previous/next, `Alt+1..9`/`Alt+0` jump/last,
`Alt+Shift+H`/`Alt+Shift+L` move, `Alt+R` rename, `Alt+G` list; panes: `Alt+\` and `Alt+-` split, `Alt+arrows` focus,
`Alt+Shift+arrows` resize, `Alt+Z` zoom, `Alt+X` close (asks); and a green **+** button in the status bar creates a
window. Use the left Alt: the right one is AltGr on an international layout. If you use your own tmux config
without ours, add `source-file /path/to/tmux-browser-keys.conf` to it (it needs `set -g base-index 1` so
`Alt+1..9` match the status bar).
With the `voice` addon installed the controls strip (below) has a microphone button: hold it and speak, and what you said becomes a goal on the bus, which the `sysop` addon acts on when it is installed ([voice.md](voice.md)). **Ctrl+A then `S`** shows or hides the panel of the sysop ([sysop.md](sysop.md)).

**The controls strip.** A slim bar under the terminal, part of the web page of the box (not of any addon): the terminal ends where the strip begins, xterm is refitted to what is left, so tmux sees the smaller window and the strip never covers a cell, the status bar and its clock included. It holds two things:

- **Key buttons**, for a phone keyboard that has no Esc, Tab, Ctrl+C or arrows. They type into the terminal when you tap or click them (a tap is sent on release, so a drag along the row types nothing; a held arrow, PageUp, PageDown or BSpace repeats), they keep the focus in the terminal (the on-screen keyboard stays open), and they are at least 44 px. The default is `Allow=C-a a, Cancel=C-a V, Esc=Escape, Tab=Tab, ^C=C-c, Panel=C-a S, ←=Left, ↑=Up, ↓=Down, →=Right`; **Panel**, **Allow** and **Cancel** type the prefix and `S`, `a` or `V`, the bindings of `container/config/tmux.conf` for the panel of the sysop ([sysop.md](sysop.md)): a phone has no Ctrl, so these are the way to answer the sysop with a thumb (**Allow** is filled violet and breathes while the sysop asks for it, **Cancel** is outlined; both are first in the row, dim and inert until the sysop waits for them: the page reads the head of the sysop panel off the screen. Cancel also stops the goal while it works. The default keys are a grid of five equal columns and two rows: `Allow` over `Cancel` on the left, `Esc`, `Tab`, `^C` and `Panel` on the first row and, under them, the four arrows, so every left and right edge of one row is the edge of a key in the other. A list of your own in `stripKeys` flows in rows instead, and a phone turned sideways has one scrolling row. **Panel** is a switch: a pill with a light that is lit while the panel is on the screen). On a desktop with only the microphone there is no bar at all: the microphone floats in the top right corner, over the head of the sysop panel, and the terminal keeps the whole window (see "When it is shown"). They need no addon; without the sysop addon installed they say so in tmux's status line and change nothing (they follow the prefix: if you change it with `set -g prefix`, change the buttons too). The strip is never built in a page that another origin frames, so a click in a frame cannot type a key; the voice front also sends `frame-ancestors 'self'` and `X-Frame-Options: SAMEORIGIN` with the page.
- **The controls of addons**, at the right end. The page offers a small API, `window.swarmboxStrip` (`container/web/ttyd-clipboard.js`): `add({id, title, label, icon, className, order})` returns the `<button>` to wire, `note(text, tone)` shows a short sentence in the strip (tone `ok`, `warn` or `error`; it covers the key buttons until the addon clears it with `note('')` or the host does, after 12 seconds (130 for a plain state without a tone); a tap dismisses it; it wraps to two lines and the strip does not grow), `remove(id)`. The `voice` addon puts its microphone and state light there ([voice.md](voice.md)) and knows no other control.

When it is shown: with `strip=auto` (the default) the key buttons appear on a touch screen (`pointer: coarse`) or when you list them yourself, and the strip appears on any screen as soon as an addon adds a control; on a desktop with only the microphone there is no bar: the microphone floats in the top right corner (a small card under it shows what the addon says) and takes no space; with key buttons (`strip=on`, a listed `stripKeys`) or on a touch screen it is the bar below the terminal. `strip=on` always shows it (with the key buttons), `strip=off` never (an addon then has no place for its controls: for the microphone, set `voice.web` to `0` too). In `web-terminal.conf`, then `swarmbox-web restart`:

```
strip=auto
stripKeys=Esc=Escape, Tab=Tab, ^C=C-c, Up=Up, Down=Down, Panel=C-a S, F5=F5
```

`stripKeys` is a list of `label=keys` entries separated by commas. The keys are **tmux key names** separated by spaces and sent in order: `Escape Tab BTab Enter Space BSpace Up Down Left Right Home End PageUp PageDown IC DC F1`..`F12`, `C-x` (Ctrl), `M-x` (Alt), `C-M-x`, a single character (typed as it is) and `Comma` (the character `,`). `C-a S` is Ctrl+A then S. An entry that cannot be read is dropped with a warning in the browser console; an empty `stripKeys=` means no buttons (a listed `stripKeys`, empty or not, also shows the strip on a desktop). Arrow and Home/End keys follow the mode the program asked for (`ESC [ A` or `ESC O A`).

Layout: one row on a phone turned sideways (the keys scroll inside the strip if they do not fit, so the terminal keeps its height) and wrapped on a portrait phone or a tablet; the safe-area insets of a notch are respected (the page asks for `viewport-fit=cover`); the page has a viewport meta tag (ttyd's own has none, so a phone used to lay it out 980 px wide and shrink it), which also makes the on-screen keyboard shrink the layout in Chrome, and on iOS, where only the visual viewport shrinks, the strip follows `visualViewport` and stays above the keyboard. The colours are those of [theme.md](theme.md). With the strip hidden the page is exactly ttyd's, as before.

**The size of the letters on a phone** is not a number but a number of columns. On a touch screen, or in a window up to 600 px wide (the device mode of a desktop browser has a mouse), the page sets the font size to `(width - 20) / (columns * 0.6)`, rounded, with 64 columns held upright and 120 sideways, never above the `fontSize` of the box (21 by default) and never below 7: a 390 px phone gets 10 px upright and 11 px sideways. A size you set yourself (`term.options.fontSize = 8` in the console) is left alone once the page has settled (3 s after it opens); `swarmboxStrip.setColumns()` makes the page fit again. To try another number without rebuilding anything, run `swarmboxStrip.setColumns(72)` in the console of the browser (the sideways number follows as 1.8 times, or give it: `setColumns(72, 130)`); it is kept in that browser, and `swarmboxStrip.setColumns()` goes back to the default. The size reaches the terminal already right: the script of the page is in the `<head>`, before ttyd's own, and rewrites the `fontSize` of the settings message that ttyd sends over the websocket, so the terminal is measured once (no 28 columns and then 123 at a refresh). The sysop panel is part of the same terminal, so it follows. A wider screen with a mouse keeps `fontSize`; a tablet wide enough for more than the configured size keeps it too. The constants are at the top of that block in `container/web/ttyd-clipboard.js`.

**The size box.** ttyd shows a box with the size of the terminal (`61x66`) at every resize; the box turns it off (`disableResizeOverlay=true`), because on a phone it flashed at every refit. `disableResizeOverlay=false` in `web-terminal.conf` brings it back.

**Block art.** In the DOM renderer a row of the terminal is a box of its own, and where its height is not a whole number of device pixels a hairline of background shows between two rows of block characters (the banner of the box). The page marks the rows that hold block characters (U+2580 to U+259F) and draws them 12% taller (`.sb-blk` in `ttyd-style.css`); other rows are untouched.

**Renderer.** On a phone (a touch screen, or a window up to 600 px wide) the page makes ttyd use the `dom` renderer, whatever the setting: the canvas renderers size their bitmap by the device pixel ratio they saw when they were made and, where it changes (the device mode of Chrome, a screen that is moved or zoomed), paint letters at 2 or 3 times the width of the grid. Elsewhere the box asks ttyd for the `canvas` renderer (`rendererType=canvas`), not ttyd's own default, `webgl`: after the font size changes (a phone, `term.options.fontSize = n`) WebGL drew the letters at twice the width of the grid, or not at all, so the columns did not fit the screen. `rendererType=webgl` or `dom` in `web-terminal.conf` (then `swarmbox-web restart`) chooses another one.

**One session, several screens.** tmux sizes a window by the client that last had focus. If the terminal of your computer and a browser (a phone, a window in device mode) show the same session, whichever got focus last decides the size, and the other one sees a window that is wider or taller than its screen. The page therefore tells tmux "I am the one looked at" (the focus report, `ESC [ I`, only when tmux asked for focus reports) when the page gets focus, becomes visible, is tapped or is resized, and every 2 seconds while it has the focus, so the window follows it. The terminal of the computer takes the window back as soon as you click it. `swarmboxStrip.claimSize(true)` in the console does it by hand.\n\n**Scrolling.** The history is tmux's: 50,000 lines, and the mouse wheel moves through it in copy mode, **5 lines per wheel event** (tmux's own default; it was 2, which
is little for 50,000 lines). The browser keeps no history of its own, because tmux draws on the terminal's alternate screen, so there is **no scrollbar** by default: it would
sit still. **tmux can draw its own scrollbar**, a thin bar on the right of the pane (one column of its width) whose thumb shows where you are in the history, but it is **off** by default:
the pane keeps its whole width. `set -g pane-scrollbars on` in your `~/.tmux.conf` turns it on (it needs tmux 3.6 or later, which the image carries: 3.7c, pinned). A program that takes over
the screen (vim, less, a full-screen TUI) gets the whole width and no bar, and one that asks for the mouse gets the wheel itself (tmux does not scroll its history over it): the scrolling of such a program is its own. In copy mode tmux also shows
where you are (`[position/total]`, top right); `q` or `Esc` leaves it, `PageUp`/`PageDown` move by a screen. To scroll faster or slower, put in your
`~/.tmux.conf` (read after ours; `tmux source-file ~/.tmux.conf` applies it without a new box):

```
bind -T copy-mode WheelUpPane send -N10 -X scroll-up
bind -T copy-mode WheelDownPane send -N10 -X scroll-down
bind -T copy-mode-vi WheelUpPane send -N10 -X scroll-up
bind -T copy-mode-vi WheelDownPane send -N10 -X scroll-down
```

To change the bar of tmux: `set -g pane-scrollbars on` shows it, `modal` shows it only in copy mode (the pane is then one column narrower each time copy mode starts or ends, and the program in it is resized), and `set -g pane-scrollbars-style "bg=default,fg=colour238,width=1"` (in your `~/.tmux.conf`) sets its colors and width.
`scrollbar=true` in `web-terminal.conf` (then `swarmbox-web restart`) brings back the BROWSER's thin translucent bar on the right (which only scrolls the browser's own history, so it sits still under tmux) and keeps a browser history of 1000 lines for it; without it the
browser history is 0 (`scrollback=0`), because xterm.js reserves 15 px for a scrollbar it measures as zero width, which would cost a column. A `scrollback=` line of yours wins.

**Copy and paste.** With the mouse on, tmux owns the mouse: a selection is copied into tmux's own buffer and
sent to the terminal as OSC 52, but ttyd 1.7.7 ignores OSC 52, so nothing reached the browser clipboard, and
xterm.js sends Ctrl+V to the shell as `^V` instead of pasting. `swarmbox-web` therefore serves ttyd's
own page with a small script injected (`container/web/ttyd-clipboard.js`; `container/web/build-index.sh` joins it, the style and ttyd's own page into one file when the image is built):
- a selection (or `tmux set-buffer -w`) **reaches the browser clipboard**. Only *writes* are honoured: a
  clipboard *read* request (`OSC 52 ; ... ; ?`) is never answered, so nothing in the terminal can read what you
  copied elsewhere;
- **`Ctrl+V` pastes** (as `Ctrl+Shift+V` already did), with bracketed paste when the program asked for it;
- **`Ctrl+C` copies while text is selected in the terminal** (`Shift`+drag selects when tmux has the mouse) and
  does not interrupt; with no selection it is still `^C`.
- **Right click** opens only tmux's menu while tmux captures the mouse (the browser's menu used to open on top of
  it). `Shift`+right-click still opens the browser's, and in a plain shell (no mouse capture) the right click keeps
  the browser's menu, so copy and paste stay there.
On a Mac, Option acts as Meta by default (`macOptionIsMeta=true`), so the Alt shortcuts of tmux (Option+1..9 to change window, Option+N for a new one) reach the terminal instead of typing characters such as `¡™£`. The cost is that Option no longer composes special characters in the browser; set `macOptionIsMeta=false` in `web-terminal.conf` to get them back.

Set `ctrlVPaste=false` and/or `ctrlCCopy=false` in `web-terminal.conf` to keep `^V` (vim block mode, readline
quoted-insert) or to let `Ctrl+C` always interrupt, then `swarmbox-web restart`. Tested in Chromium; a
browser that only allows clipboard writes from a user gesture (Firefox) may need the click to be recent.

The image sets `LANG=C.UTF-8` (and `swarmbox-web` runs ttyd with it): without one, bash
drops an accented character typed on its own (a dead key + letter) instead of inserting it.

**That local port has no login.** It is published on `127.0.0.1` only (and ttyd refuses
cross-origin websockets), but anything running on your machine can open it, and the shell
has `sudo`. To reach it from elsewhere, put Cloudflare Access in front of it ([cloudflare.md](cloudflare.md)), and do not publish the port on `0.0.0.0`.

**Crashes and logs.** `serve` supervises ttyd and restarts it after 1, 2, 4 ... 30 seconds; after five exits within a minute it stops
trying, writes the line "web terminal keeps crashing; see web-terminal.log" to the `health` file and waits for `swarmbox-web restart`.
The log is `<workspace>/.local/state/swarmbox/web-terminal.log`. [verified: tests/fast/test_serve_steps.py and tests/slow/smoke_image.py; 2026-11-08; Podman 4.3.1, Debian 12 (bookworm); reduced: development box] That a real browser keeps a session across a ttyd restart was not checked [unverified].

[← Back to the README](../README.md)
