# Web terminal

The box serves its terminals in a browser: the **Herdr Web Studio** (`container/web/herdr/server.mjs`, installed as
`/usr/local/share/swarmbox/herdr-web/`), a client of the herdr-core daemon (`hc`) of the box, so the terminals survive closing the
page. It is on by default and listens on `127.0.0.1:<WEB_PORT>` of your machine, port 7681 unless you change it. `swarmbox url` prints
the address (and the public one, when `swarmbox remote setup` has been run). A second box needs its own port:
`SWARMBOX_NAME=dev swarmbox config set WEB_PORT 7682`, then `SWARMBOX_NAME=dev swarmbox reset`. `swarmbox config set WEB 0` turns it off
(the port is a creation setting: `swarmbox reset` applies it). Inside the box the server always uses port 7681; `WEB_PORT` is only the
host side of the mapping. There is no host-network mode.

Since version 2.3 herdr-core is the only multiplexer of the box: the tmux and ttyd page of earlier versions, its `web-terminal.conf`, the
controls strip and `swarmbox-web render` are gone.

**Same tabs in the browser and in your terminal.** The Studio, the terminal cockpit that `swarmbox` opens in your host terminal
(`container/web/herdr/cockpit.mjs`, [herdr-cockpit-design.md](herdr-cockpit-design.md)), `swarmbox-tabs` and the sysop all see the same
live terminals of one herdr-core daemon. A tab opened in one is a tab in the others; closing the page or the host terminal only detaches.
`swarmbox --plain` gives a plain bash instead.

**What the page has.** A sidebar with the tabs (a status dot from the OSC 7501 state each agent reports: idle, working, blocked, error),
buttons to open a shell or an agent, the terminal itself (xterm.js, 24-bit colour, the fonts served by the box: JetBrains Mono and a Nerd
Font symbol set, no CDN), the panel of the sysop when that addon is installed ([sysop.md](sysop.md)) and a settings page that shows the
configuration of the box. On a phone the sidebar and the sysop panel become drawers.

**Keys** (left Alt; on a Mac, Option): `Alt+1..9` a tab, `Alt+N` a new shell, `Alt+B` the sidebar, `Alt+S` the sysop panel, `Alt+G` type a
goal, `Alt+T` the next theme, `Alt+,` the settings, `Alt+=` / `Alt+-` / `Alt+0` the font size. The same keys work with any keyboard layout
(the page matches the physical key).

**Themes.** Five palettes: Catppuccin Mocha (the default), SwarmBox Purple Glow ([theme.md](theme.md)), Tokyo Night, Nord and Rosé Pine.
The choice is kept in `~/.config/swarmbox/herdr-web-theme` and shared with the cockpit.

**Copy and paste.** `Ctrl+C` copies while text is selected (and is `^C` otherwise), `Ctrl+V` pastes, and a program in a terminal can write
the browser clipboard with OSC 52; a clipboard *read* request (`OSC 52 ; ... ; ?`) is never answered, so nothing in the terminal can read
what you copied elsewhere. An image pasted into the page is saved in the box and its path typed into the terminal.

**Voice.** With the `voice` addon installed the page has a microphone button: hold it and speak, and what you said becomes a goal on the
bus, which the `sysop` addon acts on when it is installed ([voice.md](voice.md)). The addon's front then owns the web port and passes
everything but `/voice/health` and `/voice/audio` to the Studio.

**That local port has no login.** It is published on `127.0.0.1` only, and the server refuses cross-origin websockets and mutating API
calls and forbids framing by another origin, but anything running on your machine can open it, and the shell has `sudo`. To reach it from
elsewhere, put Cloudflare Access in front of it ([cloudflare.md](cloudflare.md)), and do not publish the port on `0.0.0.0`.

**Crashes and logs.** `serve` supervises the web server and restarts it after 1, 2, 4 ... 30 seconds; after five exits within a minute it
stops trying, writes the line "web terminal keeps crashing; see web-terminal.log" to the `health` file and waits for
`swarmbox-web restart` (inside the box). The log is `<workspace>/.local/state/swarmbox/web-terminal.log`. The server always runs with a
UTF-8 locale.

[← Back to the README](../README.md)
