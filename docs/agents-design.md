# Agent registry: refactor plan

Status: **plan, not implemented**. Written from a line-by-line audit of the code at `2e06be8` (2026-11-26). Line numbers are of that commit.

Goal: a coding agent (Claude Code, Antigravity `agy`, OpenCode, and any future one) is **declared once**, in its addon folder, and every part
of SwarmBox (shell, gateway, Web Studio, cockpit, `swarmbox-tabs`, pins, worktrees, state, sysop) reads that declaration. Adding an agent
must be one new folder under `container/addons/` with **zero changes elsewhere**, and a guard test must prove it.

## 1. Where we are

The addon layer (`addon.conf`, `install.sh`, `prepare.sh`, `shell.sh`) is well isolated. What is missing is the concept "this addon is an
agent": `addon.conf` cannot say it, so everything that treats an agent differently from a shell is hardcoded, in three kinds.

### A. By name (lists, alias maps, display data)

| Place | Contents |
|---|---|
| `swarmbox-tabs.py:85` `AGENT_COMMANDS` | claude, gemini, opencode, codex, agy |
| `swarmbox-tabs.py:587` `ALLOWED_OPEN_AGENTS` | shell, claude, agy, opencode, codex, gemini (no yolo) |
| `swarmbox-state.py:21` `AGENT_COMMANDS`, `:190-210` PATH probe | + aider / without aider; `antigravity`→`agy` twice |
| `swarmbox-pins.py:25-26` `ALLOWED_AGENTS`, `CONTINUE_AGENTS` | + yolo; claude, agy, opencode |
| `swarmbox-worktree.py:1084` `AGENT_CMDS`, `:1099-1116` | + claude-code, antigravity; aliases inline |
| `sysop/policy.py:47`, `sysop/risk.py:17` (unused) | + aider |
| `sysop/autoname.py:36-37` | generic titles, aliases |
| `sysop/mcpserver.py:225`, `sysop/brain.py:54` | names in the description of the `tab` action and in the system prompt |
| `hc-client.mjs:35,38` `CONTINUE_AGENTS`, `ALLOWED_AGENT_CMDS` | + yolo |
| `hc-client.mjs:1192` `AGENT_NAME_MAP`, `:1396` `KNOWN_CODING_AGENTS` | aliases; display names |
| `server.mjs:570`, `app.js:1121` | name regex `^(claude\|agy\|antigravity\|opencode\|gemini\|codex)\b` |
| `cockpit.mjs:247` `AGENT_APP_LABELS` | aliases, **without `claude-code`** |
| `app.js:2066` `AGENT_APP_LABELS`, `:2989` names, `:2998-3105` `PIXEL_SVG`, `:7684` settings dropdown, `:7808` placeholder | |
| `app.css:1121-1156` `.agent-card[data-agent=…]` | 5 colour blocks |
| `tabrefs.js:15` `COMMON` | without `antigravity` |
| `config/bashrc.sh:115-124` codex wrapper, `:138-140` yolo alias | |
| `host/swarmbox-host:120,657` | `sysop.brain` default and validation `claude` |

Ten lists with different contents; the `antigravity`→`agy` alias in seven places; `claude-code` (the OSC 7501 `app` that Claude Code
really reports) missing in two.

### B. "Is this an agent / a TUI?" predicates

Generic logic whose predicate uses the lists above: `detectTerminalAgent`/`detectLiveAgent` (`hc-client.mjs:1225,1245`),
`isInteractiveTuiTerminal` (`server.mjs:564`), `isSessionTui`/`tabAgentKind`/`tabAgentBadge` (`app.js:1109,3134,2077`), `detect_agent`
(`swarmbox-state.py:170`), `_tab_agent_kind` (`swarmbox-worktree.py:1099`), `tab_kind` (`policy.py:126`), `agent_state`
(`swarmbox-tabs.py:496`), `findMainAgentTerminal` (`server.mjs:740`), pins sync (`hc-client.mjs:1338`), project discovery
(`server.mjs:363`). The UI also uses "has a pixel icon" as "is an agent" (`app.js:5531,5591,5835,6314`).

### C. One agent's behaviour hidden in generic code

| Where | Implicit assumption |
|---|---|
| `server.mjs:2654-2659,2709-2749,2729`; `app.js:1188` | resize/hydration/late-redraw timings (900/3500 ms, 4200 ms, 2500 ms…) tuned for agy's long-conversation relayout; one value for every TUI |
| `swarmbox-tabs.py:446-512` | screen heuristics (rules `──────`, input box, `❯`, "esc to interrupt", "Do you want to") are Claude Code's |
| `swarmbox-tabs.py:1360-1380` `_verify` | submit check needs Claude's input box and `[Pasted text` placeholder; ignores OSC 7501 |
| `swarmbox-tabs.py:1323`, `policy.py:224-230` | `/` and `!` refusal = Claude's slash commands and bash mode |
| `swarmbox-pins.py:196-211`, `hc-client.mjs:1278-1290` | `{ag} --continue`, fresh after a non-zero exit within 4 s (Claude's "No conversation found"); duplicated in Python and JS; agy's `--continue` unverified |
| `server.mjs:1947-1955` | new worktree forces `fresh` (Claude resumes by cwd) |
| `server.mjs:1711` `answer` | allow→`y`, deny→`n` (not Claude's numbered menu; unverified) |
| `config/bashrc.sh:76-79` | worktree guard skips `-p/--print/--output-format/--input-format`, Claude's flags |
| `app.js:2290-2531` smart copy | `❯` prompt and box glyphs of today's TUIs |
| `app.js:1566-1597,2554` image paste | assumes the agent attaches a pasted path |
| `entrypoint.sh:359-372`, `swarmbox-mcp.sh:23`, `opencode/prepare.sh:59` | `~/.claude/mcp-servers.json` is the box's canonical MCP list |
| `claude/shell.sh:14-15` | `--mcp-config` only together with the YOLO flag |
| `sysop/autoname.py:171-202` | the namer is always `claude -p --model haiku` |
| `sysop/brain.py:38-47,234-373`, `config.py:27,38` | brain preset, stream-json parsing, login hint, model names are Claude's |
| `sysop/usermsgs.py:89-141` | history readers per agent inside the sysop |
| `sysop/risk.py:52,60` | secrets: only `CLAUDE_CODE_OAUTH_TOKEN`/`ANTHROPIC_API_KEY`; no credential files |
| `swarmbox-statusline.sh` vs `antigravity/statusline.sh` | two statuslines, duplicated rendering |
| `claude/prepare.sh:20-54`, `antigravity/prepare.sh:23-67` | copy-pasted settings seeding |

### Protocol-generic code to keep as is

DEC 2026 coalescer (`server.mjs:491-562`), `NON_TYPING_INPUT_RE` (`:488`), OSC 7501 state handling (`server.mjs:1118`,
`hc-client.mjs:918`, `HerdrBackend.tab_state` `swarmbox-tabs.py:973`), the `TabsBackend` contract, alt-buffer and mouse-mode checks
(`app.js:601,1113,2646`), the cockpit wheel (`cockpit.mjs:750-785`), overlay scrollbar, OSC 52, bracketed paste, text/Enter split
(`PAUSE`, `PROMPT_ENTER_GAP_MS`).

### Where live status comes from

herdr-core does not detect agents: `term.status = {app, state}` is exactly what the program reported with OSC 7501, `foreground.name`
is its process detection, the `swarmbox.agent` label is SwarmBox's. Checked on this box (read-only `hc ls`/`hc get`, `strings`):
Claude Code 2.1.332 (`app=claude-code`), agy (`app=antigravity`, switch `AGY_CLI_OSC7501`) and OpenCode emit OSC 7501; a hand-installed
gemini does not; codex unknown. So **a new agent's live state is an external dependency** (the vendor CLI), its `app` string is
vendor-chosen, and without it SwarmBox falls back to the Claude-only screen heuristics, which give `unknown` for anything else.

## 2. Bugs found (fix first, independent of the refactor)

| # | Bug | Where |
|---|---|---|
| 1 | Worktree collision never uses the `swarmbox.agent` label: `row.get("agent") is True`, but `swarmbox-tabs list` gives a string | `swarmbox-worktree.py:1111` |
| 2 | `swarmbox-tabs open <agent>` runs `bash -lc "exec <cmd>"`, which skips the addon's shell function: no auto-approve, no MCP, no guard (pins and cockpit use `bash -lic`) | `swarmbox-tabs.py:942` |
| 3 | `claude-code` (Claude's real 7501 `app`) missing: cockpit badge and `swarmbox-state` rely on fallbacks | `cockpit.mjs:247`, `swarmbox-state.py:182` |
| 4 | `SWARMBOX_AGENT=antigravity` (the addon name, accepted by `yolo`) is rejected by the gateway and cockpit: tab labelled `yolo`, worktree open falls to `shell`, wrong default in the launcher | `server.mjs:1504,2350`, `hc-client.mjs:1423`, `cockpit.mjs:620` |
| 5 | Default agent differs: `'yolo'` for tabs, `'claude'` for worktree open (runs `claude` in a box without it) | `server.mjs:1502` vs `:2349` |
| 6 | The default agent is the first `WITH` entry even when it is not an agent (`WITH=gcloud,claude` → `yolo` runs gcloud) | `swarmbox-host:1411-1414` |
| 7 | `YOLO=0` silently drops the box MCP servers for Claude | `claude/shell.sh:14-15` |
| 8 | agy never gets the box MCP servers (chrome-devtools) | `antigravity/prepare.sh` |
| 9 | Tabs with an agent label or an agent-like name but a bare shell get TUI resize masks (900/3500 ms); `claimPtyOwnership` never passes `isTui`; any non-shell foreground counts as TUI | `server.mjs:564-572,635,652` |
| 10 | UI demotes an agent without a pixel icon to `shell` (kind, `data-agent`, styling); launcher falls back to a non-existent `agent` icon key | `app.js:3915,5531,5591,5835,6314` |
| 11 | Agent credential files (`~/.claude/.credentials.json`, `~/.claude.json`, `~/.gemini/oauth_creds.json`, `~/.local/share/opencode/auth.json`) rated `low` risk | `sysop/risk.py:52,60` |
| 12 | `_verify` returns at once for non-Claude agents (no input box): no `not_submitted`, no retry Enter | `swarmbox-tabs.py:1360` |
| 13 | `--continue` fallback hides any fast failure (auth, crash) by starting fresh | `swarmbox-pins.py:202`, `hc-client.mjs:1278` |
| 14 | Dead code: `risk.AGENT_COMMANDS`, orphan comment `usermsgs.py:30`, the name-prefix loop after bug 1 | |

**Step 0 status** (branch `fix/agent-bugs`): fixed 1, 2, 3, 4+5, 7, 8, 11, 12 and the dead code of 14, each with a regression test.
Left on purpose: 6 needs to know in bash which addons are agents (step 2, from the registry, not another list); 9 and 10 are steps 4
and 3; 13 is step 5 (`resume_argv`). Checked at runtime: bug 2 (`bash -lc "exec claude"` runs the program without the function's
flags); agy 1.5.17 and OpenCode accept `--continue` (not a bug), but agy's help says "the most recent conversation" without "in this
directory": whether a pin resumes the conversation of its own folder is open for step 5 (`RESUME_SCOPE`). Still to check by hand, with
a real permission dialog: what the Web Studio's Allow/Cancel card types (`server.mjs` `answer`: `y`/`n`) does in Claude Code, agy
and OpenCode.

## 3. Target design

### 3.1 Principles

1. **Terminal signals first, identity second.** Whether a tab is a TUI, busy, blocked, or in a dialog comes from the terminal: alternate
   screen, mouse mode, DEC 2026 seen, OSC 7501. The agent declaration only overrides tuning (timings) and fills gaps (screen adapter
   when no 7501).
2. **Declared once, generated everywhere.** The manifest is the only source; a generated registry is what code reads.
3. **One resolver per language**, fed by the same JSON, with shared test vectors.
4. **Unknown degrades safely**: generic icon and colour, state `unknown`, conservative sysop policy.
5. **Escape hatches are files in the addon**, never `if agent == ...` in generic code.

### 3.2 The agent driver: everything of an agent in its addon folder

The model is a **driver**. The core owns the *mechanisms* (PTY gateway, resize masking, DEC 2026 coalescing, OSC 7501, typing and locks,
pins, worktrees, the sysop policy engine) and never names an agent. An agent addon owns *everything that is specific to that agent*, as
an `agent/` folder next to its lifecycle files. **An addon is an agent if and only if it has `agent/agent.conf`.** Only installed agent
addons exist for SwarmBox: there is no catalogue of agents without an addon (a CLI installed by hand is a plain program until it gets an
addon).

```
container/addons/antigravity/
├── addon.conf          lifecycle (unchanged): NAME, VERSION, COMMANDS, UPDATE...
├── install.sh          lifecycle
├── prepare.sh          lifecycle; may call the agent hooks below through shared helpers
└── agent/              the driver: the only place that knows agy
    ├── agent.conf      data: identity, launch, resume, terminal profile, input semantics, sysop integration
    ├── icon.svg        16x16 pixel icon
    ├── settings.json   defaults seeded into the agent's own settings (shared seeding helper)
    ├── mcp.sh          writes the box MCP list in the agent's format
    ├── statusline.sh   extracts fields from the agent's statusline input; the shared renderer draws them
    ├── screen.py       screen adapter: state / input box / submit check when OSC 7501 is missing
    ├── history.py      the user's last prompts in a folder (for the sysop's tab naming)
    ├── shell.sh        only when the generated wrapper is not enough (OpenCode's `run --auto`)
    └── terminal.mjs    only when the terminal profile's numbers are not enough (no agent needs it today)
```

Every capability has a **default in the core**, so an agent declares only what differs, and a missing piece degrades safely:

| Capability | Where in `agent/` | Kind | Used by | Default when absent |
|---|---|---|---|---|
| Identity: id, command, aliases (incl. OSC 7501 `app` id and process names), label, colour | `agent.conf` | data | everything | id, command required |
| Icon | `icon.svg` | asset | Web Studio, `/api/agents` | generic agent icon |
| Launch: YOLO args, MCP args, passthrough subcommands, print-mode flags | `agent.conf`, or `shell.sh` | data / sh | generated shell wrapper, every launch | plain command |
| Resume: args, fast-failure window, scope (cwd) | `agent.conf` | data | pins, gateway, worktree open | no resume |
| MCP servers in the agent's format | `mcp.sh` | sh | `serve`, after addon install | agent gets no box MCP |
| Default settings | `settings.json` | data | shared seeding helper in `prepare` | none |
| Statusline | `statusline.sh` | sh | the agent itself | none |
| Live status source | `agent.conf` (`STATUS=osc7501`) | data | gateway, tabs, sysop | `osc7501` |
| Screen fallback: state, input box, submit check | `screen.py` | Python | `swarmbox-tabs`, sysop | state `unknown`, submit `unverified` |
| **Terminal profile**: hydration and resize timings, late-redraw window, copy glyphs, image paste mode | `agent.conf` (`TERM_*`), or `terminal.mjs` | data / Node | gateway (hydration, resize mask), Web Studio via `/api/agents` | the core's TUI profile |
| Input semantics: reserved prefixes, permission answer keys | `agent.conf` | data | tabs, sysop policy, gateway `answer` | `/ !`; answering disabled |
| Prompt history | `history.py`, or `HISTORY=jsonl:...` | Python / data | sysop autoname | redacted screen text |
| Namer and brain command templates, login hint, default model | `agent.conf` | data | sysop | agent not usable as namer/brain |
| Secrets: env vars, credential files | `agent.conf` | data | sysop risk | none |

**The hydration and reflow code you saw in the gateway is mechanism, not agent code.** The masking holds the PTY output after a resize
until the TUI finished redrawing; what was tuned for agy are only its numbers. They become a named profile:

| `agent.conf` key | Today (hardcoded) | Where |
|---|---|---|
| `TERM_RESIZE_QUIET_MS`, `TERM_RESIZE_CAP_MS` | 900 / 3500 (TUI), 110 / 350 (plain) | `server.mjs:2658-2659` |
| `TERM_RESIZE_CLIENT_FALLBACK_MS` | 4200 / 600 | `app.js:1188` |
| `TERM_HYDRATE_GAP_MS`, `TERM_HYDRATE_MIN_BYTES`, `TERM_HYDRATE_FLUSH_MS`, `TERM_HYDRATE_CAP_MS` | 60-40 / 256 / 160-460 / 1400 | `server.mjs:2709-2725,2788` |
| `TERM_LATE_REDRAW_MS` | 2500 | `server.mjs:500,2729` |
| `TERM_SETTLE_MS` | 420 / 650 / 320 | `server.mjs:2747-2749` |
| `TERM_COPY_PROMPT_GLYPHS`, `TERM_COPY_GUTTER_GLYPHS` | `❯`, `│┃║▕▎▏` | `app.js:2294-2299` |
| `TERM_IMAGE_PASTE` | always `path` | `app.js:2554` |

The core keeps two built-in profiles, `tui` (today's agy-tuned numbers) and `plain`, and picks one from terminal signals (alternate
screen, mouse mode, OSC 7501), not from the agent's name; the agent's keys override the `tui` one. If an agent ever needs *logic*
rather than numbers, `terminal.mjs` is the extension point, with a narrow interface that the gateway calls in its hot path:

```js
// agent/terminal.mjs (optional): every export is optional
export const profile = { resizeQuietMs: 900 };            // same as the TERM_* keys
export function redrawSettled({ bytesSinceResize, msSinceLastChunk, sawFullClear, inSyncFrame }) {
  return undefined;                                         // true / false to decide, undefined = core default
}
```

The browser never runs addon code: it receives data from `/api/agents` (icon, colour, label, copy glyphs, paste mode, timings).

**Python hooks** are loaded by `swarmbox_agents.py` with `importlib` from the agent folder, and have fixed signatures:

```python
# agent/screen.py
def state(rows):            # -> "dialog" | "busy" | "idle" | "unknown"
def input_box(rows):        # -> str | None: the text still in the agent's input box
def submitted(before, after):   # -> True | False | None (None: cannot tell)

# agent/history.py
def messages(cwd, home, now):   # -> [{"text": str, "ts": float, "session": str}], newest last
```

Claude Code's heuristics of `swarmbox-tabs.py:446-512` and `:1360-1380` move as they are into `addons/claude/agent/screen.py`; the
readers of `usermsgs.py` into each addon's `history.py` (Claude and agy share the generic `HISTORY=jsonl:` form).

**Validation.** `swarmbox-addon check` validates `agent/`: `agent.conf` keys known and well-formed (same subset that both parsers read:
one line, optional double quotes, no `$`, no escapes; lists are space-separated words), `CMD` one of the addon's `COMMANDS`, templates
with known placeholders only, `icon.svg` small and well-formed, hook files with the expected functions (`python3 -I` import in a
check, `node --check` for `terminal.mjs`).

**Pseudo-agents.** `shell`, `yolo` (resolved at launch to the default agent; what is persisted is the real id) and the role `sysop` are
built into the resolver, not drivers.

**What stays in the core** (never per agent): the PTY gateway and its masking mechanism, DEC 2026, OSC 7501 parsing, mouse and
alternate-screen tracking, typing and the send lock, pins storage, worktrees, the sysop policy engine and risk rules (fed by the drivers'
data), the statusline renderer, the seeding helper, `swarmbox-mcp` (the box's MCP list, in a neutral place).

### 3.3 The registry

- `container/scripts/swarmbox-agents` (Python, stdlib): `generate` writes `<run>/agents.json` (box:/tmp/swarmbox, regenerated at the
  `serve` addon step and after `addon install|remove|use`); `list`, `get ID`, `resolve NAME` (alias → id), `default`, `sh` (prints the
  generated shell wrappers). The library computes from the manifests when the JSON is missing or older than a manifest, so a stale
  cache can never be wrong.
- `swarmbox_agents.py` in `/usr/local/lib/swarmbox` for tabs, state, pins, worktree and the sysop. `resolve()`, `is_agent()`,
  `default_agent()`, `resume_argv()`, `screen_adapter()`, `SHELL_NAMES` (one copy; today two different ones).
- `agents.mjs` in `container/web/herdr/` reads the same JSON: gateway, hc-client, cockpit.
- `GET /api/agents` (and icons at `/agents/<id>/icon.svg`) for the browser; replaces `installed_agents` in `/api/config`, which already
  is a seed of this.
- **One `default_agent()`**: `AGENT` (alias-normalised) if it is an agent, else the first `WITH` entry that is an agent, else the first
  installed agent, else none. The host keeps passing `AGENT`/`WITH` raw (it cannot read the box's registry); the box resolves and writes
  a health line when `AGENT` is not an agent.
- **Detection order** (one function, both languages): OSC 7501 `app` → foreground process name → `swarmbox.agent` label (trusted only when
  the argv is not a bare login shell, the rule of `app.js:3139`) → never the tab name. "Live" detection stops after the first two.

### 3.4 Consumers after the refactor

| Area | Change |
|---|---|
| Shell (`bashrc.sh`) | sources `swarmbox-agents sh`: one function per installed agent through `_sb_agent_run ID "$@"` (passthrough → plain; print flags → no guard; guard; YOLO args; MCP args always). An addon `shell.sh` defining the function wins. Codex fallback and the yolo alias removed. |
| Launch (`swarmbox-tabs open`, pins, cockpit, gateway) | every launch goes through `bash -lic` so the wrapper applies; argv from `resume_argv()` (one implementation; the JS copy reads the registry). |
| TUI detection (`server.mjs`) | the gateway tracks the alternate screen (`\e[?1049h/l`, `\e[?47h`) and mouse mode in the PTY stream it already scans for DEC 2026; `isTui` = alt screen or mouse mode or 7501 reported; registry timings override the defaults. The name regex and the client's `?tui=1` hint go (the server is the one source). |
| Client (`app.js`, `app.css`, `tabrefs.js`) | names, icons, colours (CSS variables set inline, one generic `.agent-card` rule), settings dropdown, `COMMON` words, from `/api/agents`; membership from the registry, never from the icon; generic agent icon. `PIXEL_SVG` keeps only shell and sysop. |
| State and screen (`swarmbox-tabs.py`) | `agent_state` = 7501 → `screen_adapter(agent)` → `unknown`. The Claude heuristics move to `addons/claude/agent/screen.py` (interface in 3.2); an agent without `screen.py` gets `unknown`. `_verify` uses the 7501 transition to `working` when reported, else the adapter, else reports `unverified` instead of success. Reserved prefixes from the registry. |
| Sysop | `policy.tab_kind`, risk, autoname generic titles, the action descriptions and the system prompt from the registry; namer and brain from the drivers' templates (first installed agent that has one, or the configured one); history via the driver's `history.py` or `HISTORY=jsonl:`; secrets from the drivers' `agent.conf`. Policy for an agent in state `unknown`: treat a submit as possibly answering a dialog (needs `--queue`/approval), the safe side. |
| MCP | canonical list moves to `<workspace>/.local/share/swarmbox/mcp-servers.json` (written by `swarmbox-mcp`); `~/.claude/mcp-servers.json` becomes what the claude addon's `mcp.sh` writes (kept as the same content for compatibility). Each agent's `mcp.sh` writes its format: Claude (file), OpenCode (`.mcp` in its config), agy (`mcpServers` in its settings). |
| Settings seeding, statusline | shared `seed_json_defaults FILE DEFAULTS STAMP` in the lib; one statusline renderer, per-agent field extractors. |
| Host | `sysop.brain` validated against the presets the registry can provide (`claude` stays a valid name). |

## 4. Plan

Each step is one pull request that leaves the suite green. Steps 1–2 change no behaviour except where the CHANGELOG says so.

**Step 0: bug fixes** (small, independent PRs, each with its regression test): bugs 1, 2, 3, 4+5 (one `resolveDefaultAgent` in JS),
6, 7, 8, 11, 12 (report `unverified`), 14. Bug 9 and 10 are fixed by steps 4 and 3.

**Step 1: registry core.** The `agent/` folder and its checks in `swarmbox-addon.sh`; `agent.conf` for claude, antigravity, opencode;
`swarmbox-agents`, `swarmbox_agents.py` (with the hook loader), `agents.mjs`; serve and `addon` regenerate the JSON. codex, gemini and
aider are dropped from every list (CHANGELOG "Changed": a CLI installed by hand without an addon is a plain program, until it gets one). Tests: manifest contract (every `AGENT=1` manifest valid), resolver vectors in `tests/support/fixtures/agents/cases.json` run by
the Python library and by `agents.mjs` (node, as the herdr tests already do). No consumer changes yet.

**Step 2: identity consumers.** Every list and alias map of section 1.A goes: Python (tabs, state, pins, worktree, sysop policy, risk,
autoname, mcpserver text) and JS (hc-client, server, cockpit). One detection order (3.3). The divergent lists become one: yolo, aider,
claude-code and antigravity behave the same everywhere (CHANGELOG: "Fixed").

**Step 3: browser.** `/api/agents`, icons as files, colours as variables, dropdown, `tabrefs` words, membership not by icon, generic icon.
Moves the three pixel icons into their addons (`agent/icon.svg`); the codex and gemini icons are deleted (git history keeps them for
their future addons).

**Step 4: TUI from terminal signals.** Alt-screen/mouse tracking in the gateway; `isInteractiveTuiTerminal` and `isSessionTui` without
names; registry timing overrides; `?tui=1` removed. Regression tests on the coalescer side with recorded streams (alt screen on/off,
an agent label on a bare shell).

**Step 5: launch and shell.** Generated wrappers; MCP args independent of YOLO; print flags and passthrough from the registry; one
`resume_argv` (the JS copy reads it); `swarmbox-tabs open` through `bash -lic`; codex fallback removed. OpenCode keeps its `shell.sh`.

**Step 6: state and input.** Claude's heuristics into `addons/claude/agent/screen.py`; `_verify` by 7501 transition, else the driver's `submitted()`; reserved prefixes; `TERM_IMAGE_PASTE`; the
`answer` keys verified at runtime and declared if they differ per agent. The `unknown`-state policy in the sysop.

**Step 7: MCP and settings.** Neutral canonical MCP file and per-agent `mcp.sh` (agy gets the servers: CHANGELOG "Added");
`seed_json_defaults`; statusline renderer and extractors.

**Step 8: sysop.** History by declaration (the generic jsonl reader covers Claude and agy; OpenCode's SQLite reader moves to its addon);
namer and brain templates (a box with only agy or OpenCode can name tabs); secrets from the registry.

**Step 9: guards and docs.** `tests/fast/test_guard_agents.py` on `tests/support/repo_scan.py`, in the style of `test_guard_names.py`:
no agent id or alias of the registry as a literal under `PRODUCT_ROOTS` outside `container/addons/<id>/agent/`, with
an allowlist of glob + regex + reason, the dead-entry check and dict-tree self-tests. Docs: `design.md` §8, `addons-design.md` (keys),
`pins-design.md`, `worktrees-design.md`, `mux-architecture.md` (adapters), and "Adding an agent" in `CONTRIBUTING.md`. Keep
`docs/history/test-suite-review/regressions.md` in step with renamed ledger tests (`test_layout.py`).

**Step 10: proof.** A `codex` addon (or gemini) that touches only `container/addons/codex/`. Acceptance: `git diff --stat` outside that
folder is empty, the guard passes, and the agent is detected, persisted, guarded, iconed, resumed and named like the others.

## 5. Definition of done

- Adding an agent is one folder; nothing else changes (step 10 proves it, the guard keeps it so).
- No agent name in generic code; one resolver per language, same vectors.
- TUI-ness and state come from terminal signals; agent fields only override or fill gaps.
- An agent without OSC 7501 or without an icon degrades to `unknown` and a generic icon, never to "shell" and never to Claude's heuristics.
- Every behaviour of section 1.C is either a declared field, an addon file, or protocol-generic code.

## 6. Decisions to take

1. ~~Flat keys in `addon.conf` or a separate file~~ decided: the `agent/` folder with `agent.conf` (3.2).
2. ~~Detection-only catalogue~~ decided: no; only agent addons are agents, codex/gemini/aider come later as addons.
3. Decided: an agent in state `unknown` is treated by the sysop policy as possibly showing a dialog (conservative).
4. Decided: the canonical MCP file moves out of `~/.claude`; the old path stays as Claude's own copy.
5. Decided: the bugs of section 2 are fixed first (step 0), before the refactor.
