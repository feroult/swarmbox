# Web terminal

The box serves its shell in a browser (ttyd + tmux, so sessions survive closing the tab). It is on by default and listens on
`127.0.0.1:<WEB_PORT>` of your machine, port 7681 unless you change it. `swarmbox url` prints the address (and the public one, when
`swarmbox remote setup` has been run). A second box needs its own port: `SWARMBOX_NAME=dev swarmbox config set WEB_PORT 7682`, then
`SWARMBOX_NAME=dev swarmbox reset`. `swarmbox config set WEB 0` turns it off (the port is a creation setting: `swarmbox reset` applies it).
Inside the box ttyd always uses port 7681; `WEB_PORT` is only the host side of the mapping. There is no host-network mode in 2.0.

**Same tabs in the browser and in your terminal**: the shell `swarmbox` opens in your host terminal is a new
window of the same tmux session (`main`) the browser shows, through a grouped session, so each host tab is also a
tab in the browser and the other way round; each side keeps its own current window, and the grouped session goes
away when you close the host tab (the window stays until its shell exits). Nested tmux: if your host terminal also
runs tmux, give it another prefix (SwarmBox uses `C-a`) or press `C-a a` to send the prefix inside.
`swarmbox --plain` gives the plain bash instead.

**Font, size, theme**: out of the box the terminal is dark (Windows Terminal's Campbell colors), size 21, with a
Nerd Font list (JetBrainsMono, Cascadia). To change any of it, put `key=value` lines (xterm.js options) in `<workspace>/.config/swarmbox/web-terminal.conf`
(`~/.config/swarmbox/web-terminal.conf` inside the box), e.g. `fontFamily='JetBrainsMono Nerd Font', Consolas, monospace`.
`padding=10` is the space (px) around the terminal, and the scrollbar is a thin translucent one (both are CSS in
`container/web/ttyd-style.css`, joined into ttyd's page when the image is built). A `theme` line replaces the whole default theme. No rebuild and no new box: run `swarmbox-web restart` inside the box to apply (the box and its tmux sessions stay up). The page is rendered again at every ttyd start, by a plain text substitution of `padding`, `ctrlVPaste` and `ctrlCCopy`; every other key goes to ttyd as `-t key=value`. The font is
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
The log is `<workspace>/.local/state/swarmbox/web-terminal.log`. [verified: tests/test_serve_steps.py and tests/smoke_image.py; 2026-11-08; Podman 4.3.1, Debian 12 (bookworm); reduced: development box] That a real browser keeps a session across a ttyd restart was not checked [unverified].

[← Back to the README](../README.md)
