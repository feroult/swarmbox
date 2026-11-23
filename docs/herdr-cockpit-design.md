# Herdr Cockpit & Native Sysop Agent Design

This document specifies SwarmBox's native terminal experience and remote `herdr-app` integration on top of `herdr-core` (`hc`), complementing the browser Web Gateway described in `docs/mux-architecture.md`.

## Goals

1. **Terminal parity with the Web UI (`sx` / `swarmbox`):** running `swarmbox` (or `sx`) opens a 3-pane SwarmBox Terminal Cockpit directly inside the user's host terminal — sidebar with live OSC 7501 status dots, full 24-bit center PTY, right-hand Sysop panel with live approvals and goal input, and the 5 synchronized themes — with zero extra software installed on the host.
2. **Single source of truth (`herdr-core`):** the Web UI, the Terminal Cockpit (`cockpit.mjs`), `swarmbox-tabs`, and any external `herdr-app` client all attach to the exact same `herdr-core` daemon and see the exact same live terminals.
3. **Sysop as a native OSC 7501 agent for `herdr-app` without UI duplication:** Sysop publishes a persistent `herdr-core` terminal labeled `swarmbox.role=sysop` that speaks native OSC 7501 (`idle`, `working`, `blocked:permission`, `done`, `error`) so remote `herdr-app` users can monitor and interact with Sysop in their Agent Inbox, while the SwarmBox Web UI, Terminal Cockpit, and `swarmbox-tabs` filter out `swarmbox.role=sysop` so Sysop appears only in its dedicated panel and never as a duplicate tab.
4. **Remote `herdr-app` readiness:** external `herdr-app` clients connect over the existing Podman/SSH transport (`hc machine add <name> --via 'podman exec -i <box> hc connect'`) without exposing any extra TCP port.

## Visibility Matrix (`swarmbox.role=sysop`)

| Surface | Regular terminals | `swarmbox.role=sysop` terminal |
| --- | --- | --- |
| **Web UI (`herdr-web`)** | Shown in left sidebar tab list | Hidden from tab list; Sysop shown exclusively in right panel / mobile glass capsule |
| **Terminal Cockpit (`sx`)** | Shown in left sidebar tab list | Hidden from tab list; Sysop shown exclusively in right panel |
| **`swarmbox-tabs` (`HerdrBackend`)** | Listed & targetable by Sysop brain | Hidden from `list`, `active`, `screen`, `send` so Sysop never inspects or drives itself |
| **`herdr-app` / `hc ls`** | Shown as terminals/agents | Shown natively in Agent Inbox with live OSC 7501 states and interactive prompt |

## Component 1: Shared Herdr Runtime Module (`container/web/herdr/hc-client.mjs`)

Both `server.mjs` (Web Gateway) and `cockpit.mjs` (Terminal Cockpit) share one ESM module to prevent drift:

- **`HerdrClient`:** framed binary JSON-RPC 2.0 client over `hc connect` (`FRAME_DATA=0`, `FRAME_CREDIT=1`, `FRAME_CLOSE=2`, `FRAME_RESIZE=3`, `FRAME_FOCUS=4`) with automatic `CREDIT` flow control, reconnect backoff, and live event state.
- **`isHiddenRole(terminal)`:** returns `true` when `terminal.labels && terminal.labels['swarmbox.role'] === 'sysop'`. Applied by `listSnapshot()` so neither UI lists internal role terminals as user tabs.
- **Theme registry (`COCKPIT_THEMES` + `HERDR_THEMES`):** exact 5 palettes (`purple-glow`, `catppuccin`, `tokyo-night`, `nord`, `rose-pine`) persisted in `~/.config/swarmbox/herdr-web-theme` (`readSavedTheme` / `saveTheme`), keeping Web UI and Terminal Cockpit synchronized in real time.
- **Active-tab tracking:** `readActiveTab()` / `writeActiveTab()` reading/writing `$SB_RUN_DIR/herdr-active-tab`.
- **Real Sysop state reader & CLI bridge:** `readSysopSnapshot()` (reading `status.json`, `state.json`, `calls.jsonl`, `say.jsonl`, `pending_action.json`, plus live OSC 7501 `blocked` terminals) and `runCommand()` for `swarmbox-sysop goal|approve|veto|stop`.

## Component 2: SwarmBox Terminal Cockpit (`container/web/herdr/cockpit.mjs`)

Launched by `mux_attach_interactive` in `container/scripts/mux/herdr.sh` (with fallback to `hc attach` when `SWARMBOX_HERDR_RAW=1` or when `cockpit.mjs` is unavailable). `mux_attach_command CMD` continues to attach directly to the single command terminal via `hc attach` so shell command exit codes and detach semantics remain exact.

### Rendering Architecture

- **Terminal emulator:** `@xterm/headless` (`5.5.0`, MIT, pure JavaScript — no native compilation, zero `node-pty`) maintains an exact headless screen buffer per attached `herdr-core` terminal at the center viewport dimensions `(paneCols, paneRows)`.
- **Compositor:** renders a flicker-free frame inside synchronized output (`\x1b[?2026h` ... `\x1b[?2026l`) using 24-bit TrueColor ANSI escapes (`\x1b[38;2;r;g;bm` / `\x1b[48;2;r;g;bm`) with row-level diffing so idle ticks write zero bytes.
- **Responsive 3-pane layout:**
  - **Top bar (1 row):** brand mark, active tab name and OSC 7501 status pill, Sysop status badge, theme indicator, and compact shortcut hints.
  - **Left sidebar (24 cols, auto-shown when `cols >= 100`, toggleable anytime):** numbered tab list with live colored OSC 7501 dots (green = idle/done, accent = working, amber = blocked, red = error), `[+ Shell]`, `[+ Agent]`, and `[Theme]` controls.
  - **Center viewport:** exact 24-bit cell rendering of the active `@xterm/headless` buffer (foreground, background, bold, dim, italic, underline, inverse, wide characters, real cursor positioning, scrollback viewing via `Shift+PgUp`/`PgDn` or mouse wheel).
  - **Right Sysop panel (34 cols, auto-shown when `cols >= 120` or whenever an approval/veto is pending, toggleable anytime):** live state pill, recent activity feed, highlighted `ALLOW?` / `SENDING` decision card with 1-key Allow/Veto/Stop, OSC 7501 blocked-terminal alert, and inline interactive Goal input box.

### Keyboard & Mouse Ergonomics

- All normal keystrokes pass straight to the active `herdr-core` terminal PTY.
- **`Ctrl+A` prefix** (the prefix SwarmBox always used):
  - `Ctrl+A Ctrl+A`: send literal `Ctrl+A` to the active terminal
  - `Ctrl+A 1..9` / `n` / `p`: switch tabs
  - `Ctrl+A c` / `Ctrl+A C`: open new Shell / Agent tab
  - `Ctrl+A x`: close active tab (when more than one tab exists)
  - `Ctrl+A b`: toggle left sidebar
  - `Ctrl+A s`: toggle right Sysop panel
  - `Ctrl+A g`: focus Sysop goal input box
  - `Ctrl+A a`: approve pending Sysop action (or answer blocked dialog)
  - `Ctrl+A v`: veto pending Sysop action / stop active goal
  - `Ctrl+A t`: cycle through the 5 synchronized themes
  - `Ctrl+A d`: detach cleanly (leaving all `herdr-core` terminals running)
  - `Ctrl+A ?`: toggle shortcut help overlay
- **Direct `Alt` shortcuts** (mirroring the Web UI): `Alt+1..9`, `Alt+N`, `Alt+B`, `Alt+S`, `Alt+G`, `Alt+T`.
- **SGR 1006 mouse:** click tabs, `[+ Shell]`, `[+ Agent]`, `[Theme]`, Sysop `[Allow]` / `[Veto]` / `[Stop]` / Goal box, or scroll the active terminal history.

## Component 3: Sysop Native OSC 7501 Agent (`swarmbox-sysop agent`)

Implemented in `container/addons/sysop/lib/swarmbox_sysop/agent.py` (pure Python stdlib) and wired into `cli.py` and `ui_host.py`.

### OSC 7501 Protocol (Verified Against `herdr-core 0.1.21`)

`herdr-core` parses colon-delimited `key=value` OSC 7501 sequences terminated by BEL (`\x07`):

| Sysop state (`state.line_of`) | OSC 7501 emitted | Terminal title (`OSC 0`) |
| --- | --- | --- |
| `idle` | `\x1b]7501;state=idle\x07` | `sysop · idle` |
| `working` / `queued` | `\x1b]7501;state=working\x07` | `sysop · <sentence>` |
| `allow?` / `sending` | `\x1b]7501;state=blocked:kind=permission\x07` | `sysop · allow? <sentence>` |
| `done` | `\x1b]7501;state=done\x07` | `sysop · done` |
| `failed` / `stopped` | `\x1b]7501;state=error\x07` | `sysop · <state>` |

### Interactive Session Loop

- Runs inside a persistent `herdr-core` terminal started with `--name sysop --label swarmbox.role=sysop --keep --no-parent`.
- Streams real-time goal steps (`say`, MCP calls, approvals, summaries) cleanly to stdout so both `herdr-app` viewers and `hc read sysop` see readable progress.
- Accepts line input from a human in `herdr-app` or programmatically via `hc send sysop "..."`:
  - While an approval or veto countdown is live: `y` / `yes` / `allow` / `approve` approves (`actions.approve`); `n` / `no` / `veto` / `deny` refuses (`actions.veto`).
  - `/stop` stops the active goal and queue (`actions.stop`).
  - `/status` prints current service state and recent goals.
  - Any other non-empty text publishes a goal on the bus (`actions.publish_goal(..., source="agent")`).

### Lifecycle & Template Seeding (`ui_host.py`)

When `swarmbox-sysop serve --dock` runs:

1. `ui_host.start_ui()` starts `HerdrBridge` (a lightweight background watcher thread in `agent.py`).
2. `HerdrBridge` seeds `~/.config/herdr-core/templates/sysop.md` once (never overwriting user edits) so `hc templates` and `herdr-app` expose the Sysop template.
3. `HerdrBridge` checks `hc ls --json` for a live terminal with label `swarmbox.role=sysop`; if none exists and `herdr-core` is up, it spawns one (`hc run --bg --keep --no-parent --name sysop --label swarmbox.role=sysop -- swarmbox-sysop agent`).
4. In `container/scripts/swarmbox-tabs.py`, `HerdrBackend.list_tabs_raw()` excludes any terminal whose `labels.get("swarmbox.role") == "sysop"`, keeping `swarmbox-tabs` and the Sysop brain cleanly isolated from the bridge terminal.

## Remote `herdr-app` Workflow

Users who run `herdr-app` on their workstation can connect directly to a local or remote SwarmBox container without exposing any extra TCP port:

```sh
# Local SwarmBox container
hc machine add swarmbox --via 'podman exec -i swarmbox hc connect'

# Remote SwarmBox over SSH
hc machine add swarmbox-vps --via 'ssh my-vps podman exec -i swarmbox hc connect'
```

Once added, `herdr-app` discovers all live terminals plus the `sysop` agent (with live OSC 7501 status badges and permission prompts) natively inside the user's own `herdr-app` workspace.

## Follow-up Cleanup (Future)

Once the Terminal Cockpit (`cockpit.mjs`) is validated in daily use, the older standalone `herdr 0.9.5` binary and `container/config/herdr.toml` (which run a separate daemon unrelated to `herdr-core`) can be removed from `Dockerfile` to slim the image further.
