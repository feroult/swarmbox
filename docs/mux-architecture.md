# Multiplexer Architecture

The box has one terminal multiplexer: **herdr-core** (`hc`). The Web Studio, the Terminal Cockpit, `swarmbox-tabs` and the sysop all attach
to the same `herdr-core` daemon and see the same live terminals. tmux and ttyd were removed. A `MUX` key in the config, and the
`sysop.panel` key that set the old tmux panel, are ignored with a warning and never reach the box.

The multiplexer is still kept behind three narrow contracts, so that the core of the box (`entrypoint.sh`, `swarmbox-attach`, `swarmbox-web`,
`swarmbox-bus`, the addons, the sysop) calls `hc` in one place only and the tests can load synthetic backends.

## 1. Shell backend (`container/scripts/mux/`)

`container/scripts/mux/mux.sh` loads `/usr/local/lib/swarmbox/mux/herdr.sh`. `SWARMBOX_MUX` is a test seam, not a setting: with
`SWARMBOX_TEST_MUX_DIR` it names a synthetic backend file in that folder, and a stale `SWARMBOX_MUX=tmux` loads herdr. The backend implements:

| Function | Caller | Responsibility |
|---|---|---|
| `mux_available` | `swarmbox-attach` | Return 0 when `hc` is installed on `PATH` |
| `mux_serve_init` | `entrypoint.sh` (step 9) | Seed the herdr configs, start the `herdr-core` daemon and its first `shell` tab |
| `mux_serve_shutdown_note` | `entrypoint.sh` (`on_signal`) | Log the shutdown message on `SIGTERM` / `SIGINT` |
| `mux_attach_web` | `swarmbox-attach --web` | Attach a browser client (`hc attach`) |
| `mux_attach_interactive` | `swarmbox-attach` | Open the Terminal Cockpit (`container/web/herdr/cockpit.mjs`; `SWARMBOX_HERDR_RAW=1` falls back to `hc attach` of a new tab) |
| `mux_attach_command CMD` | `swarmbox-attach CMD...` | Run a quoted shell command in an attached tab and exit with its status |
| `mux_web_run PORT IFACE VOICE_BIN` | `swarmbox-web run` | Exec the Herdr Web Gateway (`container/web/herdr/server.mjs`), behind `swarmbox-voice front` when the `voice` addon is installed |

See [herdr-cockpit-design.md](herdr-cockpit-design.md) for the Terminal Cockpit and the OSC 7501 sysop agent.

## 2. Tabs backend (`container/scripts/swarmbox-tabs.py`)

`swarmbox-tabs` separates the mux-agnostic facade (`Tabs`: secrets redaction, SGR markers, key-in-braces parsing, per-tab cross-process
`flock`, body validation, agent rules and the JSON CLI) from the driver (`TabsBackend`); `HerdrBackend` is the one driver:

- `list_tabs_raw()` -> list of `Tab` records in display order (the terminal labelled `swarmbox.role=sysop` is hidden)
- `active_tab_id(tab_ids)` -> id of the active tab (`<run folder>/herdr-active-tab`), or `None`
- `capture_screen(tab, lines)` / `capture_plain_rows(tab)` -> the screen of a tab
- `prepare_send(tab)`, `send_text(tab, text)`, `send_key(tab, key)` -> text and normalized key delivery
- `live_tab_ids()` -> live tab ids for stale lock cleanup
- `tab_state(tab)` -> the native OSC 7501 state `(is_agent, state)` when the agent reports one, else `None` and the screen heuristics run
- `open_tab(name, cwd, agent)`, `focus_tab(tab)`, `close_tab(tab)` -> the `open`, `focus` and `close` commands

`SB_TABS_BACKEND` is a test seam (`herdr` is the only name; an unknown one is `no_backend`, exit 4). A missing `hc` is `no_backend`, another
`hc` failure is `backend_error`. The facade is tested over a fake `hc` (`tests/support/tabs_support.py`).

## 3. Herdr Web Gateway (`container/web/herdr/`)

When `WEB=1`, `swarmbox-web run` starts `/usr/local/share/swarmbox/herdr-web/server.mjs`:

- **Framed OpenRPC multiplexing:** connects once to `hc connect` (framed binary JSON-RPC 2.0), streaming live PTY bytes over `/ws/pty/:address` with automatic `CREDIT` flow control (no `node-pty` required) and broadcasting live OSC 7501 terminal events over `/ws/events`.
- **Real Sysop integration:** reads real `swarmbox-sysop` state (`status.json`, `state.json`, `calls.jsonl`, `say.jsonl`, `pending_action.json`) and invokes `swarmbox-sysop goal|approve|veto|stop`, plus surfaces OSC 7501 `blocked` dialogs with 1-tap approval.
- **Voice addon:** accepts `-p PORT -i IFACE`, so `swarmbox-voice front` sits in front of it when installed, serving `/voice/health` and `/voice/audio` (local Whisper STT) and piping everything else to the server.
- **Synchronized themes:** defaults to SwarmBox Purple Glow ([theme.md](theme.md)) and offers Catppuccin Mocha, Tokyo Night, Nord, and Rosé Pine, synced with `~/.config/herdr/config.toml` via `/api/theme`.
- **Security:** enforces same-origin on WebSockets and mutating API routes and sets `Content-Security-Policy: frame-ancestors 'self'` and `X-Frame-Options: SAMEORIGIN`.

## 4. Sysop (`container/addons/sysop/lib/swarmbox_sysop/`)

The sysop core (`service.py`, `brain.py`, `mcpserver.py`, `policy.py`, `risk.py`, `audit.py`, `history.py`, `ipc.py`, `paths.py`,
`config.py`, `watch.py`, `busclient.py`, `tabsclient.py`, `cli.py`) acts on tabs only through `swarmbox-tabs`. Its UI lives in the Web
Studio and the cockpit, which read `state.py` (the snapshot as JSON) and call `actions.py` (approve, veto, stop, goal). `ui_host.py` starts
the OSC 7501 agent bridge (`agent.HerdrBridge`) for `serve --dock`; `SWARMBOX_MUX=none` runs headless (the tests use it).

## Enforcement & Verification

- `tests/fast/test_guard_mux.py` scans `container/` so that nothing runs tmux or ttyd again or ships a file for them, and the `Dockerfile` installs neither.
- `tests/fast/test_mux_isolation.py` exercises `entrypoint.sh serve`, `swarmbox-attach`, `swarmbox-web`, `swarmbox-tabs` and the sysop UI host against synthetic backends, with no `hc` on `PATH`.
- `tests/fast/test_herdr_backend.py` covers `herdr.sh`, `HerdrBackend`, the gateway and the cockpit against a fake `hc`.
