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

The default implementation lives in `container/scripts/mux/tmux.sh`.

## 2. Tabs backend (`container/scripts/swarmbox-tabs.py`)

`swarmbox-tabs` separates the mux-agnostic facade (`Tabs`: secrets redaction, SGR markers, key-in-braces parsing, per-tab cross-process `flock`, body validation, and JSON CLI) from the multiplexer driver (`TabsBackend`):

- `list_tabs_raw()` -> list of `Tab` records in display order
- `active_tab_id(tab_ids)` -> id of the active tab, or `None`
- `capture_screen(tab, lines)` -> `ScreenCapture(raw, cursor, alternate, in_mode, mode, size, lines)`
- `capture_plain_rows(tab)` -> plain screen rows
- `prepare_send(tab)` -> backend preparation before typing (for `tmux`, exiting copy mode)
- `send_text(tab, text)` / `send_key(tab, key)` -> literal text and normalized key delivery
- `live_tab_ids()` -> live tab ids for stale lock cleanup
- `tab_state(tab)` -> optional native `(is_agent, state)` (`dialog`, `busy`, `idle`, `unknown`); returns `None` on `TmuxBackend` so screen heuristics run, and lets future backends such as `herdr-core` supply OSC 7501 state directly without screen scraping

Backends are registered in `BACKENDS` and selected by `SB_TABS_BACKEND` or `SWARMBOX_MUX` (default `tmux`). An unknown backend returns error code `no_backend` (exit 4).

## 3. Sysop separation (`container/addons/sysop/lib/swarmbox_sysop/`)

The Sysop addon splits mux-agnostic core modules from `tmux`-specific UI adapters:

- **Core (zero `tmux` coupling):** `service.py`, `brain.py`, `mcpserver.py`, `policy.py`, `risk.py`, `audit.py`, `history.py`, `ipc.py`, `paths.py`, `config.py`, `watch.py`, `busclient.py`, `tabsclient.py`, `cli.py`, plus:
  - `state.py` — pure snapshot reader, text sanitizer (`clean`, `one_line`, `step_text`), status line (`line_of`, `value_of`), and JSON-serializable `state_dict()` for any front-end
  - `actions.py` — pure control operations (`pending_of`, `is_live`, `veto`, `approve`, `stop`, `publish_goal`)
- **UI host (`ui_host.py`):** starts `dock.Follower` + `line.Toaster` when `SWARMBOX_MUX=tmux`, and runs headless without importing `tmux` when `SWARMBOX_MUX=none` (or another backend that provides its own UI).
- **`tmux` UI adapters:** `dock.py`, `panel.py`, `line.py` (supports any custom `sink(value)` in addition to the default `@sysop_line` option), `keys.py`, and `__main__.py` (fast-path `dock redock`).

## Enforcement & Verification

- `tests/fast/test_guard_mux.py` statically scans `container/` (including the AST of `swarmbox-tabs.py`) to block any direct `tmux` command or `dock` import outside the allowlisted adapter files.
- `tests/fast/test_mux_isolation.py` exercises `entrypoint.sh serve`, `swarmbox-attach`, `swarmbox-web`, `swarmbox-tabs`, and Sysop (`state`, `actions`, `ui_host`, `Toaster`) against synthetic non-`tmux` backends with no `tmux` binary on `PATH`.
