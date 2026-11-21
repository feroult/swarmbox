# Multiplexer Architecture & `tmux` Isolation

SwarmBox isolates terminal multiplexer specifics behind three narrow contracts so the core sandbox (`entrypoint.sh`, `swarmbox-attach`, `swarmbox-web`, `swarmbox-bus`, addons, and the Sysop engine) does not depend directly on `tmux`. The active backend is chosen by `SWARMBOX_MUX` (default `tmux`).

## 1. Shell backend (`container/scripts/mux/`)

`container/scripts/mux/mux.sh` loads `/usr/local/lib/swarmbox/mux/<backend>.sh` (`SWARMBOX_TEST_MUX_DIR` overrides the folder in tests). Each backend implements seven functions:

| Function | Caller | Responsibility |
|---|---|---|
| `mux_available` | `swarmbox-attach` | Return 0 when the backend binary is installed on `PATH` |
| `mux_serve_init` | `entrypoint.sh` (step 9) | Start the backend's background session or daemon |
| `mux_serve_shutdown_note` | `entrypoint.sh` (`on_signal`) | Log the shutdown message on `SIGTERM` / `SIGINT` |
| `mux_attach_web` | `swarmbox-attach --web` | Attach a browser client showing all tabs |
| `mux_attach_interactive` | `swarmbox-attach` | Open and attach an interactive host terminal tab |
| `mux_attach_command CMD` | `swarmbox-attach CMD...` | Run a quoted shell command in an attached tab and exit with its status |
| `mux_web_fallback` | `swarmbox-web` | Populate `MUX_WEB_FALLBACK_CMD` when `swarmbox-attach` is absent |
| `mux_web_run PORT IFACE VOICE_BIN` | `swarmbox-web run` | Optional: replace `ttyd` with a backend-native web gateway |

Two implementations live in `container/scripts/mux/`:

- `tmux.sh` (default, `MUX=tmux` / `SWARMBOX_MUX=tmux`) — keeps existing `tmux` + `ttyd` behavior unchanged.
- `herdr.sh` (opt-in, `MUX=herdr` / `SWARMBOX_MUX=herdr`) — starts `herdr-core` (`hc`), seeds `~/.config/herdr/config.toml` (Purple Glow theme) and `~/.config/herdr-core/config.toml`, opens/attaches tabs via `hc`, and launches the native Herdr Web Gateway (`container/web/herdr/server.mjs`) via `mux_web_run` (wrapped cleanly behind `swarmbox-voice front` when the `voice` addon is installed).

## 2. Tabs backend (`container/scripts/swarmbox-tabs.py`)

`swarmbox-tabs` separates the mux-agnostic facade (`Tabs`: secrets redaction, SGR markers, key-in-braces parsing, per-tab cross-process `flock`, body validation, and JSON CLI) from the multiplexer driver (`TabsBackend`):

- `list_tabs_raw()` -> list of `Tab` records in display order
- `active_tab_id(tab_ids)` -> id of the active tab, or `None`
- `capture_screen(tab, lines)` -> `ScreenCapture(raw, cursor, alternate, in_mode, mode, size, lines)`
- `capture_plain_rows(tab)` -> plain screen rows
- `prepare_send(tab)` -> backend preparation before typing (for `tmux`, exiting copy mode)
- `send_text(tab, text)` / `send_key(tab, key)` -> literal text and normalized key delivery
- `live_tab_ids()` -> live tab ids for stale lock cleanup
- `tab_state(tab)` -> optional native `(is_agent, state)` (`dialog`, `busy`, `idle`, `unknown`); returns `None` on `TmuxBackend` so screen heuristics run, and returns native OSC 7501 state on `HerdrBackend` when reported (falling back to screen heuristics when `reported` is false)

Backends are registered in `BACKENDS` (`tmux` -> `TmuxBackend`, `herdr` -> `HerdrBackend`) and selected by `SB_TABS_BACKEND` or `SWARMBOX_MUX` (default `tmux`). An unknown backend returns error code `no_backend` (exit 4).

## 3. Herdr Web Gateway (`container/web/herdr/`)

When `SWARMBOX_MUX=herdr` and `WEB=1`, `swarmbox-web run` starts `/usr/local/share/swarmbox/herdr-web/server.mjs`:

- **Framed OpenRPC multiplexing:** connects once to `hc connect` (framed binary JSON-RPC 2.0), streaming live PTY bytes over `/ws/pty/:address` with automatic `CREDIT` flow control (no `node-pty` required) and broadcasting live OSC 7501 terminal events over `/ws/events`.
- **Real Sysop integration:** reads real `swarmbox-sysop` state (`status.json`, `state.json`, `calls.jsonl`, `say.jsonl`, `pending_action.json`) and invokes `swarmbox-sysop goal|approve|veto|stop`, plus surfaces OSC 7501 `blocked` dialogs with 1-tap approval.
- **Voice addon compatibility:** accepts `-p PORT -i IFACE`, so `swarmbox-voice front` sits cleanly in front of it when installed, serving `/voice/health` and `/voice/audio` (local Whisper STT) with zero changes to the voice addon.
- **Synchronized themes:** defaults to SwarmBox Purple Glow (`docs/theme.md`) and offers Catppuccin Mocha, Tokyo Night, Nord, and Rosé Pine, synced with `~/.config/herdr/config.toml` via `/api/theme`.
- **Security:** enforces same-origin on WebSockets and mutating API routes and sets `Content-Security-Policy: frame-ancestors 'self'` and `X-Frame-Options: SAMEORIGIN`.

## 4. Sysop separation (`container/addons/sysop/lib/swarmbox_sysop/`)

The Sysop addon splits mux-agnostic core modules from `tmux`-specific UI adapters:

- **Core (zero `tmux` coupling):** `service.py`, `brain.py`, `mcpserver.py`, `policy.py`, `risk.py`, `audit.py`, `history.py`, `ipc.py`, `paths.py`, `config.py`, `watch.py`, `busclient.py`, `tabsclient.py`, `cli.py`, plus:
  - `state.py` — pure snapshot reader, text sanitizer (`clean`, `one_line`, `step_text`), status line (`line_of`, `value_of`), and JSON-serializable `state_dict()` for any front-end
  - `actions.py` — pure control operations (`pending_of`, `is_live`, `veto`, `approve`, `stop`, `publish_goal`)
- **UI host (`ui_host.py`):** starts `dock.Follower` + `line.Toaster` when `SWARMBOX_MUX=tmux`, and runs headless without importing `tmux` when `SWARMBOX_MUX=none` (or another backend that provides its own UI).
- **`tmux` UI adapters:** `dock.py`, `panel.py`, `line.py` (supports any custom `sink(value)` in addition to the default `@sysop_line` option), `keys.py`, and `__main__.py` (fast-path `dock redock`).

## Enforcement & Verification

- `tests/fast/test_guard_mux.py` statically scans `container/` (including the AST of `swarmbox-tabs.py`) to block any direct `tmux` command or `dock` import outside the allowlisted adapter files.
- `tests/fast/test_mux_isolation.py` exercises `entrypoint.sh serve`, `swarmbox-attach`, `swarmbox-web`, `swarmbox-tabs`, and Sysop (`state`, `actions`, `ui_host`, `Toaster`) against synthetic non-`tmux` backends with no `tmux` binary on `PATH`.
