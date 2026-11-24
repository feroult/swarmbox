# Pinned Sessions & Auto-Naming (Design)

Status: **design agreed, ready for implementation** (Phase 1: Pins & Rename; Phase 2: `tab.events` & Sysop Auto-Namer). Git worktree isolation for multi-agent work on the same repository is designed separately and intentionally parked so this ships cleanly first; the schema below is extensible for it.

## 1. Goals

1. **Pinned sessions survive restarts and resets:** pinning a live tab persists its session identity in the workspace (`~/.config/swarmbox/pins.json`), surviving `swarmbox stop`, host reboots, `swarmbox reset`, and image updates.
2. **Live auto-follow:** a pinned tab tracks the user's current working directory (`cwd`) and active agent as they work, without requiring manual bookmark updates.
3. **Zero-weight restart (`parked` by default):** on container start, pinned sessions appear in the sidebar ready to wake in one click instead of launching every agent at boot. Only pins explicitly marked `autostart: true` spawn automatically during `serve` startup.
4. **Resume where you left off (`continue` by default):** waking a pinned agent tries `--continue` (`claude`, `agy`, `opencode`) in its saved `cwd`, falling back cleanly to a fresh session when no prior conversation exists in that folder.
5. **Zero-friction session naming:** no mandatory modal when creating a tab. Tabs default to the folder name, can be renamed inline at any time (`title_source=user`), and when the `sysop` addon is installed, an event-driven Sysop auto-namer gives unnamed tabs concise semantic titles (`title_source=auto`) and logs the rename in the Sysop visual feed without consuming conversation-memory slots.

---

## 2. Data Model

### 2.1 Live terminal labels (`herdr-core`)

`herdr-core` terminal names (`--name`) are immutable and restricted to `1–32` chars of `[a-z0-9-_]`. Rich mutable session metadata therefore lives in `herdr-core` labels (`hc run --label k=v` / OpenRPC `terminal.label`):

| Label | Example | Meaning |
| :--- | :--- | :--- |
| `swarmbox.title` | `Fix OAuth Login` | Human-readable display title shown in Web Studio, Cockpit, and `swarmbox-tabs list` |
| `swarmbox.title_source` | `auto` \| `user` | `user` locks the title against automatic renames |
| `swarmbox.pin_id` | `p_8f3a1c` | Links the live terminal to a record in `pins.json` |
| `swarmbox.agent` | `claude` \| `agy` \| `opencode` \| `gemini` \| `shell` | Agent kind associated with the session |

*(Reserved for future Git worktree support: `swarmbox.repo`, `swarmbox.worktree`, `swarmbox.branch`.)*

### 2.2 Persistent file (`~/.config/swarmbox/pins.json`)

Stored under XDG config inside the workspace (`$SB_CONFIG_DIR/pins.json`), written atomically via temp file + `rename` with mode `0600`:

```json
{
  "schema": 1,
  "pins": [
    {
      "id": "p_8f3a1c",
      "title": "Fix OAuth Login",
      "title_source": "auto",
      "agent": "claude",
      "cwd": "/home/agent/my-app",
      "resume": "continue",
      "autostart": false,
      "created_at": 1795400000,
      "updated_at": 1795401200
    }
  ]
}
```

Rules:
- Array order in `pins` is the display order in the sidebar.
- Unknown fields on a pin record are preserved on read-modify-write so future fields (such as worktree metadata) stay backward-compatible.
- If `pins.json` is absent or empty, the box behaves identically to today.

---

## 3. Lifecycle & Invariants

### 3.1 Pinning & Auto-Follow
- **Pinning a live tab** captures:
  - `cwd`: `foreground.cwd || terminal.cwd || HOME`
  - `agent`: detected agent (`status.app`, `foreground.name`, or `swarmbox.agent`), else `shell`
  - `title`: current `swarmbox.title`, else basename of `cwd` (or `shell` for `$HOME`)
  - `title_source`: current `swarmbox.title_source` (if set), else `""`
  - `resume`: `"continue"` (default)
  - `autostart`: `false` (default)
- **Live auto-follow:** while a pinned tab is alive, the gateway observes `foreground.cwd` and active agent during terminal refreshes:
  - When `cwd` changes to an existing directory different from `pin.cwd`, `pins.json` is updated (debounced / write-on-change only).
  - When a known agent starts inside a pinned tab (e.g. starting `agy` in a pinned shell, or switching agents), `pin.agent` updates to that agent.
  - **Downgrade guard:** exiting an agent back to `bash` does **not** overwrite an agent pin (`claude`, `agy`, `opencode`, `gemini`) with `shell`, so closing an agent before stopping the box never demotes the pin.
  - Renaming a pinned tab immediately updates both `swarmbox.title` / `swarmbox.title_source` and `pins.json`.

### 3.2 Closing vs. Unpinning
- **Closing a live pinned tab** (`DELETE /api/tabs/:id` or process exit) ends the `herdr-core` terminal, **leaving the pin intact**. The pin immediately renders as **`PARKED`** in the sidebar.
- **Unpinning** removes the record from `pins.json` and clears `swarmbox.pin_id` on any linked live terminal (leaving a live terminal open).

### 3.3 Boot Restoration & Waking a Parked Pin
- **On container start** (`mux_serve_init` in [herdr.sh](../container/scripts/mux/herdr.sh)):
  - Only pins with `autostart: true` are spawned automatically.
  - If a pin's `cwd` no longer exists on disk, boot does not fail: the pin stays `PARKED` with a `missing_cwd` flag surfaced in the UI.
  - If no pin is spawned at boot, `herdr.sh` creates the default `shell` tab in `$HOME` as before.
- **Waking a `PARKED` pin** (`POST /api/pins/:id/wake` or CLI):
  - If a live terminal with `swarmbox.pin_id == id` already exists, focuses it instead of duplicating.
  - Spawns a `herdr-core` terminal (`keep: true`, `no_parent: true`) in `pin.cwd` with the pin's labels (`swarmbox.pin_id`, `swarmbox.title`, `swarmbox.title_source`, `swarmbox.agent`).
- **Safe `--continue` wrapper (`resume: "continue"`):**
  - Agents with native continue support (`claude`, `agy`, `opencode`) launch via a small shell wrapper that records start time, runs `<agent> --continue`, and **only** falls back to fresh `<agent>` if `--continue` exits non-zero almost immediately (e.g. `< 3s`, meaning no prior conversation exists in that directory).
  - A normal session that exits later falls through to `exec /bin/bash -l` as usual, never unexpectedly relaunching the agent.
  - Pins with `resume: "fresh"` skip `--continue`; `agent: "shell"` launches `/bin/bash -l`.

---

## 4. Session Naming & Event-Driven Sysop Auto-Namer

### 4.1 Three-Layer Naming Model
1. **Layer 0 — Instant fallback (zero cost, no LLM):** unnamed tabs display the short folder name (e.g. `swarmbox`, `api-payments`) rather than `claude-2`.
2. **Layer 1 — Event-driven Sysop Auto-Namer (`title_source=auto`):** concise 2–4 word task title assigned automatically by the Sysop addon when real activity happens.
3. **Layer 2 — Manual rename (`title_source=user`):** inline edit in Web Studio (double-click, `✎`, or `Alt+R`), Cockpit, or `swarmbox tabs rename <tab> <title>`. Locks the title so Layer 1 never overwrites it unless explicitly cleared or re-requested.

### 4.2 `tab.events` on `swarmbox-bus`
Aligned with [addons-design.md](addons-design.md):
- The box publishes lightweight lifecycle metadata on the `swarmbox-bus` topic `tab.events` with `--allow-none` (no error when `sysop` is absent; **never** carries terminal screen text):
  ```json
  {
    "event": "turn",
    "tab": "t3",
    "cwd": "/home/agent/my-app",
    "agent": "claude",
    "state": "done",
    "title": "",
    "title_source": ""
  }
  ```
- Triggered by real `herdr-core` events (`turn`, `status` transitions such as `working -> done|idle`, and `cwd` change) — zero blind polling.
- Published from a thin `hc events` bridge (or the gateway with a `WEB=0` fallback) so both Web Studio and SSH Cockpit sessions emit events.

### 4.3 Sysop Auto-Namer Behavior
- Subscribes to `tab.events` inside the existing `swarmbox-sysop` daemon (controlled by `sysop.autoname`, default `1`).
- **Cheap local gate (before any LLM call):**
  - Skip if `title_source == "user"`.
  - Skip while an interactive user goal is active in the Sysop queue.
  - Skip during per-tab cooldown (unless `cwd` changed to a different project).
  - Trigger on first completed `turn`, `working -> done/idle` transition, or substantial post-cooldown work.
- **1-shot naming call:**
  - Reads the already-redacted screen via `swarmbox-tabs screen <tab> --lines 40`.
  - Runs a lightweight, non-MCP single-shot prompt (fast model, short max output) asking for either a concise 2–4 word task title or `KEEP` when there is not enough context yet.
  - Applies via `swarmbox-tabs rename <tab> "<Title>" --source auto`.
  - Additionally, the Sysop MCP server exposes `rename_tab(tab, title)` so interactive goals can name tabs opportunistically with zero extra calls.

### 4.4 Visibility in Sysop History (Without Polluting Memory)
- Auto-renames are recorded in the Sysop audit log (`events.jsonl`) and in a lightweight system-event stream (e.g. `system_events.jsonl`) read by [hc-client.mjs](../container/web/herdr/hc-client.mjs) when assembling `sysop.turns` / timeline entries.
- **In the Web Studio Sysop feed:** rendered as a compact inline system event row (e.g. `✎ Renamed claude → Fix OAuth Login · 14:22`) with quick edit/undo — respecting the **New** conversation timestamp (`conversation.json`).
- **In LLM conversation memory ([history.py](../container/addons/sysop/lib/swarmbox_sysop/history.py)):** excluded from the `HISTORY_GOALS = 8` user-goal window so automatic renames never evict the user's actual recent instructions.

---

## 5. Implementation Phases

1. **Phase 1 — Core Pins & Manual Rename**
   - `swarmbox-tabs rename` (`--source user|auto`) and enriched `swarmbox-tabs list` (`title`, `title_source`, `pin_id`, `pinned`).
   - Atomic `pins.json` store, `/api/pins` + `/api/pins/:id/wake` + `PATCH /api/tabs/:id` in [server.mjs](../container/web/herdr/server.mjs), and live `cwd`/agent auto-follow.
   - `autostart` boot restoration in [herdr.sh](../container/scripts/mux/herdr.sh) with the safe `--continue` wrapper.
   - Web Studio UI (desktop & mobile): `📌` pin/unpin, `PARKED` cards with 1-click wake, per-pin `⚡ Autostart` and `continue/fresh` controls, inline rename (`✎` / double-click / `Alt+R`), and `missing_cwd` indicator.
2. **Phase 2 — `tab.events` & Sysop Auto-Namer**
   - `tab.events` publisher on `swarmbox-bus`.
   - Event-driven auto-namer + `rename_tab` MCP action in `sysop`, `sysop.autoname` config key, and compact rename rows in the Sysop visual feed.
3. **Future (Separate Design) — Git Worktrees**
   - Isolated worktrees when spawning multiple agents in the same Git repository, plugging into the same session labels and `pins.json` schema.
