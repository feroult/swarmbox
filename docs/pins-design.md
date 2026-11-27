# Pinned Sessions & Auto-Naming (Design)

Status: **implemented**. Pins are automatic: every agent session is pinned while its tab is open, so it survives a restart; closing the tab discards it. The Web Studio has no manual pin control; a manual pin (`auto` absent) is made only with `swarmbox pins add` or `POST /api/pins`. Git worktree isolation is in [worktrees-design.md](worktrees-design.md) and uses the same labels and `pins.json`.

## 1. Goals

1. **Agent sessions survive restarts and resets:** every open agent tab is pinned automatically in the workspace (`~/.config/swarmbox/pins.json`), surviving `swarmbox stop`, host reboots, `swarmbox reset`, and image updates.
2. **Live auto-follow:** a pinned tab tracks the user's current working directory (`cwd`) and active agent as they work, without requiring manual bookmark updates.
3. **Boot mode:** one global setting (**Settings → SwarmBox**, `boot_mode` in `~/.config/swarmbox/session-prefs.json`) decides whether pinned sessions start on boot (`autostart`, the default) or wait as `PARKED` cards to wake in one click (`parked`). Changing it rewrites `autostart` on every pin.
4. **Resume where you left off (`continue` by default):** waking a pinned agent tries its resume form (`RESUME_ARGS` of its `agent.conf`: `--continue` for `claude`, `agy`, `opencode`) in its saved `cwd`, falling back cleanly to a fresh session when no prior conversation exists in that folder.
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
| `swarmbox.agent` | an agent id of the registry (`claude` \| `agy` \| `opencode` ...) \| `shell` | Agent kind associated with the session |

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
      "autostart": true,
      "auto": true,
      "created_at": 1795400000,
      "updated_at": 1795401200
    }
  ]
}
```

Rules:
- Array order in `pins` is the display order in the sidebar.
- Unknown fields on a pin record are preserved on read-modify-write so future fields (such as worktree metadata) stay backward-compatible.
- `auto: true` marks a pin the gateway made for an open agent tab; closing that tab removes it. A pin without `auto` (from the CLI or the API) survives closing its tab as `PARKED`.
- If `pins.json` is absent or empty, the box starts with one `shell` tab and nothing is restored.

---

## 3. Lifecycle & Invariants

### 3.1 Pinning & Auto-Follow
- **A pin** captures:
  - `cwd`: `foreground.cwd || terminal.cwd || HOME`
  - `agent`: detected agent (`status.app`, `foreground.name`, or `swarmbox.agent`), else `shell`
  - `title`: current `swarmbox.title`, else basename of `cwd` (or `shell` for `$HOME`)
  - `title_source`: current `swarmbox.title_source` (if set), else `""`
  - `resume`: `"continue"` (default)
  - `autostart`: from `boot_mode` for an automatic pin; `false` unless asked for a manual one
- **Auto-pin of any agent session:** an agent tab from **New agent** is pinned when it opens (`auto: true`). Any other live terminal without a pin (a shell where an agent was typed, a cockpit or Sysop tab, a worktree opened from its badge) is pinned the first time the gateway sees it running a known agent, from live signals only (`status.app` or the foreground process, never the tab name or labels). The pin is `auto`, so closing the tab removes it; `swarmbox.persist=off` (`persist: false`) opts a terminal out.
- **Live auto-follow:** while a pinned tab is alive, the gateway observes `foreground.cwd` and active agent during terminal refreshes:
  - When `cwd` changes to an existing directory different from `pin.cwd`, `pins.json` is updated (debounced / write-on-change only).
  - When a known agent starts inside a pinned tab (e.g. starting `agy` in a pinned shell, or switching agents), `pin.agent` updates to that agent.
  - **Downgrade guard:** exiting an agent back to `bash` does **not** overwrite an agent pin with `shell`, so closing an agent before stopping the box never demotes the pin.
  - Renaming a pinned tab immediately updates both `swarmbox.title` / `swarmbox.title_source` and `pins.json`.

### 3.2 Closing, Parking and Removing
- **Closing an agent tab** (`DELETE /api/tabs/:id`) removes its `auto` pin: the session is discarded, and the agent's own `--continue` / `--resume` in that folder still reaches the conversation. A manual pin (no `auto`) is kept and renders as **`PARKED`**; `?drop_pin=1` removes it too.
- **Stopping the box** (`swarmbox stop`, `reset`, a reboot) with agent tabs open keeps their pins: they start again on boot or wait as `PARKED`, by `boot_mode`.
- **Dismissing a `PARKED` card** (its `×`) or `DELETE /api/pins/:id` removes the record and clears `swarmbox.pin_id` on any linked live terminal. A live terminal still running an agent is pinned again (`auto`) on the next snapshot, so the only way to keep an open agent tab out of `pins.json` is `persist: false` when it opens (`swarmbox.persist=off`).

### 3.3 Boot Restoration & Waking a Parked Pin
- **On container start** (`mux_serve_init` in [herdr.sh](../container/scripts/mux/herdr.sh)):
  - `swarmbox-pins restore --boot` spawns the pins with `autostart: true` and closes the bare `--keep` recovery shells of the others, so they show as `PARKED`.
  - If a pin's `cwd` no longer exists on disk, boot does not fail: the pin stays `PARKED` with a `missing_cwd` flag surfaced in the UI.
  - When no terminal is live and `pins.json` has no pins, `herdr.sh` creates the default `shell` tab in `$HOME`; with only parked pins it opens none, so waking one leaves no stray shell.
- **Waking a `PARKED` pin** (`POST /api/pins/:id/wake` or CLI):
  - If a live terminal with `swarmbox.pin_id == id` already exists, focuses it instead of duplicating.
  - Spawns a `herdr-core` terminal (`keep: true`, `no_parent: true`) in `pin.cwd` with the pin's labels (`swarmbox.pin_id`, `swarmbox.title`, `swarmbox.title_source`, `swarmbox.agent`).
- **Safe `--continue` wrapper (`resume: "continue"`):**
  - Agents that declare `RESUME_ARGS` (`claude`, `agy`, `opencode`) launch via a small shell wrapper that records start time, runs `<agent> --continue`, and **only** falls back to fresh `<agent>` if `--continue` exits non-zero almost immediately (e.g. `< 3s`, meaning no prior conversation exists in that directory).
  - A normal session that exits later falls through to `exec /bin/bash -l` as usual, never unexpectedly relaunching the agent.
  - Pins with `resume: "fresh"` skip `--continue`; `agent: "shell"` launches `/bin/bash -l`.

---

## 4. Session Naming & Event-Driven Sysop Auto-Namer

### 4.1 Three-Layer Naming Model
1. **Layer 0 — Instant fallback (zero cost, no LLM):** unnamed tabs display the short folder name (e.g. `swarmbox`, `api-payments`) rather than `claude-2`.
2. **Layer 1 — Event-driven Sysop Auto-Namer (`title_source=auto`):** short task title (1–3 words, at most 18 characters) assigned automatically by the Sysop addon when real activity happens, and revised while the goal becomes clearer (with a per-tab backoff).
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
- Triggered by real `herdr-core` events (`start` when a tab begins working, i.e. the user just sent a request; `turn`; `status` transitions such as `working -> done|idle`; and `cwd` change) — zero blind polling.
- Published from a thin `hc events` bridge (or the gateway with a `WEB=0` fallback) so both Web Studio and SSH Cockpit sessions emit events.

### 4.3 Sysop Auto-Namer Behavior
- Subscribes to `tab.events` inside the existing `swarmbox-sysop` daemon (controlled by `sysop.autoname`, default `1`); the code is `autoname.py` and `usermsgs.py` of the addon.
- **Cheap local gates (before any LLM call), in order:**
  - Skip if `title_source == "user"` (checked on the event and again on `swarmbox-tabs list` just before the call).
  - Skip while an interactive user goal is active in the Sysop queue.
  - **When:** about 3 seconds after the user sends a request (`start`, `SUBMIT_GRACE`), if the tab is still working then; when it stops working inside that window (an Esc) the request is not used. `start` comes from the OSC 7501 status that herdr-core reads from every agent (claude as `claude-code`, agy and opencode report it natively); the requests are read from that agent's own store, so the timing is the same for all three. The end of a turn and a `cwd` change are evaluated too, for a missed `start` or a tab that only has a screen to read.
  - **A tab without a name** (its folder or worktree slug, a generic title) has no backoff: every new request is tried, and a `KEEP` ("understand the repo") costs no wait.
  - **Per-tab backoff of a named tab:** after its 1st, 2nd, 3rd and every later automatic rename a tab keeps its title for 3, 10, 30 and then 60 minutes (`COOLDOWNS`), so a name can follow the goal but settles. A `cwd` change to another folder resets the backoff and names the tab at once.
  - After a call on a named tab that answered `KEEP`, no new call for that tab for 2 minutes (`RECHECK`).
  - No call when the input is the same as on the last call (the same requests, or the same screen tail).
- **Input: the user's requests first, the screen as the fallback.** `usermsgs.recent(agent, cwd)` reads the last 4 requests the user typed in that folder from the agent's own store, each clipped to 280 characters; slash commands, `!` shell lines and short replies ("ok", "pode sim": fewer than 3 words, while longer ones exist) are left out:
  - Where an agent keeps its prompts is declared by its addon (`HISTORY*` in `agent.conf`, or its `agent/history.py`):
  - `claude`: `~/.claude/history.jsonl` (`project` = cwd, `sessionId`), the prompt history, not the session transcript (which the output of the agent's commands grows to megabytes).
  - `agy`: `~/.gemini/antigravity-cli/history.jsonl` (`workspace` = cwd, `conversationId`).
  - `opencode`: `~/.local/share/opencode/opencode.db`, read-only: the latest top-level `session_v2` of the folder, its `session_message` rows of `type = 'user'`.
  - An event names the cwd, not the agent session: when two sessions of the same agent were active in the same folder in the last 10 minutes, the reader returns nothing and the redacted screen is used (`swarmbox-tabs screen <tab> --lines 40`, last 1500 characters).
- **1-shot naming call:** the `NAMER` template an agent declares (Claude Code's: `claude -p --model haiku` with its own short `--system-prompt` (not Claude Code's default one), `--tools ""`, `--strict-mcp-config`, `--setting-sources ""` and `--no-session-persistence` (not `--bare`, which reads no OAuth login)). The rules ask for 1 to 3 short words in the language of the requests, the concrete subject rather than the activity, and `KEEP` when there is no clear goal yet (exploring, "understand the repo") or when the current title still fits; the current auto title is sent so the model can keep it. A typical input is about 1500 characters.
  - The answer is cut to 18 characters on a word boundary (a dangling "of", "de" is dropped); `KEEP`, empty and generic answers change nothing. So do answers that explain instead of naming (a sentence that goes on after `.`, `:`, `!` or `?`, a quoted name, more than 10 words, or one that starts by repeating a data label such as `Current title`): cutting them would make a title of their first words ("Current title", "Título atual").
  - Applies via `swarmbox-tabs rename <tab> "<Title>" --source auto`; the audit record says whether the title came from the `requests` or the `screen`.
  - Every decision is one `autoname <tab>: ...` line in the sysop `serve.log`: the gate that skipped, a `KEEP` with the answer and the time it took, the rename, or why the naming call failed (a failed call is not an answer: the same input is tried again).
  - Additionally, the Sysop MCP server exposes `rename_tab(tab, title)` so interactive goals can name tabs opportunistically with zero extra calls.
- Not measured: the tokens of one real call (the development box had no Claude login for `claude -p`), and the store formats of agent versions other than the ones above (a changed format gives no requests, so the screen is used).

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
   - Web Studio UI (desktop & mobile): automatic pins for agent tabs, the global boot mode (**Auto-start** / **Parked**) in Settings, `PARKED` cards with 1-click wake and dismiss, inline rename (`✎` / double-click / `Alt+R`), and `missing_cwd` indicator. (The first version had a per-tab `📌` pin button and a per-pin `⚡ Autostart`; both were replaced by the automatic model.)
2. **Phase 2 — `tab.events` & Sysop Auto-Namer**
   - `tab.events` publisher on `swarmbox-bus`.
   - Event-driven auto-namer + `rename_tab` MCP action in `sysop`, `sysop.autoname` config key, and compact rename rows in the Sysop visual feed.
3. **Future (Separate Design) — Git Worktrees**
   - Isolated worktrees when spawning multiple agents in the same Git repository, plugging into the same session labels and `pins.json` schema.
