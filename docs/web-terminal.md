# Web terminal (`--web`)

`./start.sh --reset --web` serves the container's shell in a browser (ttyd + tmux, so
sessions survive closing the tab) on `http://127.0.0.1:7681` of your machine. Use
`--web 7682` for a second container.

**Same tabs in the browser and in your terminal**: the shell `start.sh` opens in your host terminal is a new
window of the same tmux session (`main`) the browser shows, through a grouped session, so each host tab is also a
tab in the browser and the other way round; each side keeps its own current window, and the grouped session goes
away when you close the host tab (the window stays until its shell exits). Nested tmux: if your host terminal also
runs tmux, give it another prefix (SwarmBox uses `C-a`) or press `C-a a` to send the prefix inside.
`SWARMBOX_ATTACH=shell ./start.sh` gives the plain bash instead.

**Font, size, theme**: out of the box the terminal is dark (Windows Terminal's Campbell colors), size 21, with a
Nerd Font list (JetBrainsMono, Cascadia). To change any of it, put `key=value` lines (xterm.js options) in `.work/.swarmbox/web-terminal.conf`
(`~/.swarmbox/web-terminal.conf` inside), e.g. `fontFamily='JetBrainsMono Nerd Font', Consolas, monospace`.
`padding=10` is the space (px) around the terminal, and the scrollbar is a thin translucent one (both are CSS in
`container/web/ttyd-style.css`, injected into ttyd's page). A `theme` line replaces the whole default theme. No rebuild: run `pkill ttyd; swarmbox-web-terminal` inside to apply (tmux sessions survive). The font is
the *browser's*, so it must be installed on the machine that opens the page.

**tmux.** The image ships a complete default config, `container/config/tmux.conf` (installed as `/etc/tmux.conf`): prefix
`Ctrl+A`, windows and panes numbered from 1, mouse, 50,000 lines of history, true color, a dark status bar, splits
and new windows in the current directory, and the browser shortcuts below. It stands alone: nothing in your
workspace is needed. Your own `~/.tmux.conf` (`.work/.tmux.conf` on the host) is read *after* it, so add to it or
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
xterm.js sends Ctrl+V to the shell as `^V` instead of pasting. `swarmbox-web-terminal` therefore serves ttyd's
own page with a small script injected (`container/web/ttyd-clipboard.js`, built from `ttyd-stock.html` in the image):
- a selection (or `tmux set-buffer -w`) **reaches the browser clipboard**. Only *writes* are honoured: a
  clipboard *read* request (`OSC 52 ; ... ; ?`) is never answered, so nothing in the terminal can read what you
  copied elsewhere;
- **`Ctrl+V` pastes** (as `Ctrl+Shift+V` already did), with bracketed paste when the program asked for it;
- **`Ctrl+C` copies while text is selected in the terminal** (`Shift`+drag selects when tmux has the mouse) and
  does not interrupt; with no selection it is still `^C`.
- **Right click** opens only tmux's menu while tmux captures the mouse (the browser's menu used to open on top of
  it). `Shift`+right-click still opens the browser's, and in a plain shell (no mouse capture) the right click keeps
  the browser's menu, so copy and paste stay there.
Set `ctrlVPaste=false` and/or `ctrlCCopy=false` in `web-terminal.conf` to keep `^V` (vim block mode, readline
quoted-insert) or to let `Ctrl+C` always interrupt, then `pkill ttyd; swarmbox-web-terminal`. Tested in Chromium; a
browser that only allows clipboard writes from a user gesture (Firefox) may need the click to be recent.

The image sets `LANG=C.UTF-8` (and `swarmbox-web-terminal` enforces a UTF-8 locale): without one, bash
drops an accented character typed on its own (a dead key + letter) instead of inserting it.

**That local port has no login.** It is published on `127.0.0.1` only (and ttyd refuses
cross-origin websockets), but anything running on your machine can open it, and the shell
has `sudo`. To reach it from elsewhere, put Cloudflare Access in front of it. Do not use
`--host-network` with `--web` (refused), and do not publish the port on `0.0.0.0`.

[← Back to the README](../README.md)
