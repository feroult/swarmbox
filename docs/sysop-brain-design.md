# The Sysop Brain: Isolation and Streaming (Design)

Status: **implemented (2026-11-26)**: sections 3 to 5 describe what the code does; section 8 records the spikes it rests on. Open items at the end.

Since 2026-11-27 the brain is one resident process across goals (stop by interrupt, one MCP server per goal behind a reconnecting proxy): [sysop-resident-brain-design.md](sysop-resident-brain-design.md). The isolation and the stream below are unchanged.

## 1. Purpose

The sysop's brain is a coding-agent CLI (Claude Code today) run without interaction, once per goal, whose only way to act on the box is the
sysop's MCP server. This design fixes two things the current implementation does only halfway:

1. **Isolation of the brain.** The brain must be a hermetic, least-privilege worker: it sees exactly the sysop's tools, no configuration of the
   user, no secret but its own login, and nothing it does outside the MCP server.
2. **Streaming, end to end.** What the model is doing (the text it writes, the action it chose, the arguments it is typing, the approval it waits
   for) reaches every client as it happens, in order, resumable, with no polling hop between the model and the screen.

A third goal follows from the two: **the brain is agent-agnostic**. Everything specific to one CLI (its output format, how it resumes a session,
how it is stopped, how it says it is not logged in, where its configuration lives) is declared by its addon, never written in the sysop.

Not a goal: calling a model API directly. The CLI is what lets the brain use the user's subscription login and any agent that speaks MCP.

Why MCP: the brain must *ask* the sysop for every action so the sysop can check arguments, rate the risk, ask for approval, count the budget and
audit it (`policy.py`, `risk.py`, `audit.py`). A ready-made agent CLI accepts custom tools only through MCP; letting it use its own Bash would
skip all of that, and parsing actions out of its text would be a fragile protocol of our own.

## 2. Before this design (commit 98d967d)

What is already right:
- The invocation is a template in the agent's `agent.conf` (`BRAIN=`), filled without a shell (`brain.build`).
- The tool surface is closed: `--tools ''` (built-ins off), `--strict-mcp-config`, `--allowedTools 'mcp__sysop__*'`, `--permission-mode dontAsk`.
  The `init` event of a real goal lists exactly the 9 sysop tools.
- The process runs in its own group, under `timeout`, with a death signal tied to the service and `RLIMIT_FSIZE`.
- The goal goes on standard input; the end is the `done` tool (`done.json`), not the output format.

What is not:

| Gap | Where | Effect |
|---|---|---|
| The brain runs with the user's `~/.claude` | no `CLAUDE_CONFIG_DIR`, no `--setting-sources` in `BRAIN` | the `init` of goal `144e94-6` loaded 5 plugins, 20 skills, 54 slash commands, 5 subagents and an auto-memory path in the user's projects. Hooks of the user's settings or plugins run shell commands inside the brain: the one door that bypasses `--tools ''` and the MCP policy |
| The brain inherits the whole environment of the service | `brain.py` `env = dict(os.environ)` | any secret of the box is visible to the brain program (`docs/sysop.md` says so) |
| One session folder per goal in the user's projects | `cwd` is the goal folder | the persistent session is scattered in `~/.claude/projects/-…-goals-<id>/` |
| Claude Code's format and flags are written in the sysop | `brain.py`: `extract_stream_info` (`result`, `num_turns`, `total_cost_usd`, `stream_event`), `--resume` added when the argv contains `stream-json`, `--max-turns` stripped by name, SIGINT first on Stop, `LOGIN_FAILURE` regex; `service.py` keys the history preseed on `"--resume" in argv` | a second brain would lose usage, resume and login errors, or break |
| The stream reaches the page through files and timers | stdout redirected to `stream.jsonl`; `calls.jsonl`/`say.jsonl` written by the MCP server after a call ran; `state.json` by the service; the gateway polls all of them every 600 ms (and, in the uncommitted interim change, tails `stream.jsonl` every 50 ms) | the action label shows 1-2 s after the model chose it; three writers with no order between them; dedup in the UI (a `say` becoming a note); the Web Studio parses Claude Code's format |

## 3. Isolation of the brain

### 3.1 Hermetic configuration

The brain gets a home of its own, `<state>/sysop/brain/` (mode 0700), named to the CLI by the variable its addon declares
(`BRAIN_HOME_ENV=CLAUDE_CONFIG_DIR`), plus the flags that turn user and project settings off (`--setting-sources ''`) and the CLI's own
slash commands and skills (`--disable-slash-commands`). The home is created by the service (`brain.prepare_home`), never edited by the
user; `swarmbox reset` keeps it (it holds the persistent session).

Both are needed, for different reasons (S1, S2): `--setting-sources ''` is what stops hooks, the user's **and the project's** (a
`.claude/settings.json` in the working directory); `CLAUDE_CONFIG_DIR` is what moves the session, the plugin store and the user's skills out of
the user's `~/.claude`. Belt and braces: the Claude Code preset also passes `--settings {agent_dir}/brain-settings.json`, a file of the addon
(`{"disableAllHooks": true}`) in the image's read-only folder, which stops hooks on its own (S2). (`agent.conf` takes no double quotes in a
value, hence a file and the `{agent_dir}` placeholder.) The CLI's built-in plugins (`path: builtin`) stay; they are part of the CLI, not configuration of the user.

The login: the variables of the agent's `SECRET_ENV` (Claude Code: `CLAUDE_CODE_OAUTH_TOKEN`, `ANTHROPIC_API_KEY`) are passed from the
service's environment. A login kept in a file (`.credentials.json`) is never copied: an OAuth refresh rotates the refresh token, and a copy
would log the other side out. The box's sysop already logs in with `CLAUDE_CODE_OAUTH_TOKEN` (a long-lived token, no refresh), and it works
unchanged with a hermetic home (S1). A login kept only in the user's `~/.claude` (a `claude` then `/login` in a tab, no token) is the open
case: the brain home would need a symlink to that one credentials file, not measured (no such login in the spike box).

### 3.2 Fixed working directory

The brain's working directory is its home (or a fixed `work/` inside it), not the goal folder, so the persistent session is one folder of the
sysop and `--resume` does not depend on a path that changes every goal. The goal folder keeps the goal's artifacts (`mcp.json`, the system
prompt, the streams) and is passed by path. `conversation.json` tags the saved id with the home that wrote it (`session_home`); an id saved
before the brain home (in the user's folder) is not resumed: the first goal after the update starts a new session.

### 3.3 Environment by allowlist

The brain's environment is built, not inherited: `PATH`, `HOME` (the brain home), `LANG`, proxy variables, the agent's `SECRET_ENV`, the
variables its `BRAIN` template sets, the home variable and a private `TMPDIR` inside the brain home. It works with nothing else (S1-S8 all
ran with `env -i`). The CLI passes its whole environment to its MCP servers **except its own `CLAUDE_CODE_OAUTH_TOKEN`**, which it removes,
and adds `CLAUDE_CODE_MESSAGING_SOCKET`/`_TOKEN` (a channel back to its session) (S4): so what the brain does not get, the MCP server does not
get either, and the MCP server never sees the login.

### 3.4 Process limits and an optional filesystem sandbox

Kept: own process group, `timeout`, death signal, `RLIMIT_FSIZE`. Not `RLIMIT_NPROC`: it counts every process of the user, and the whole box
runs as one user, so a cap low enough to matter for the brain (it peaks at 3 processes and 20-29 threads, S5) would refuse its first fork. Not
`RLIMIT_AS`: the CLI maps 5.6-7 GB of address space for 240-250 MB resident, so a cap there would only break it.

Filesystem sandbox: **Landlock**, applied by the service in the child before `exec` (`landlock.py`, ctypes, no new package): writes allowed
only under the brain home, the goal folder and `/dev`; reads stay open. A kernel that has Landlock but refuses a step fails the start (fail
closed); a kernel without it runs the brain unsandboxed and the service logs it (`swarmbox-sysop status`: `sandbox: landlock | unavailable |
off`; `SWARMBOX_SYSOP_SANDBOX=0` turns it off). The brain and its MCP server (which inherits the domain) ran a whole goal
under it with a private `TMPDIR` and no `/tmp` (S5); `/tmp` must not be allowed, it holds the box's run folder (`/tmp/swarmbox`).

The MCP server is **not** in the domain. Landlock is inherited by children, and the server legitimately writes far outside the brain's
folders (its files, the audit, `swarmbox-tabs` and herdr-core's locks, `git` for a worktree merge). So the service runs it (`brain.McpHost`:
`swarmbox-sysop mcp --socket PATH`, its own environment, outside the domain) and the brain's `mcp.json` names only a proxy
(`swarmbox-sysop mcp-proxy PATH`) that carries bytes between the CLI's stdio and the server's socket. Connecting to an existing unix socket
is not a filesystem write, so the proxy works inside the domain. The socket is in the private run folder, mode 0600, takes one connection
and is removed once the brain connected. Landlock ABI 3 was available in the box (WSL2 kernel 6.6, rootless Podman);
where it is not, the service logs it once and runs without. bubblewrap is not in the image and is not needed.

### 3.5 The MCP server is the only decision point

Unchanged in principle, made explicit: the server does not trust the brain. Policy, risk, approval and budget live in the server and the
service. The `permission_denials` of the CLI's `result` (a tool it tried and was refused) become security events in the goal's log.

## 4. Streaming, end to end

```
 ┌─ Landlock domain ─────────────────────┐
 │ brain CLI ──stdio── mcp-proxy ────────┼──unix socket──▶ MCP server (hosted by the service, outside the domain)
 └──────┬────────────────────────────────┘                     │ events on its stdout
        │ stdout pipe                                          ▼
 service: reader thread ──┬──▶ stream.jsonl (raw, the audit stream)
                          └──▶ adapter (BRAIN_FORMAT) ──▶ EventLog ◀── MCP events, states   (one writer, monotonic seq)
                                                             │
                                                  goals/<id>/events.jsonl
                                                             │ inotify (+ 1 s fallback)
                                          gateway: relay, compacted replay on connect, backpressure
                                                             │ WebSocket
                                          page: reducer, paced reveal, one redraw per animation frame
```

### 4.1 The service reads the brain's output

`brain.run` gives the brain a pipe instead of a file. A reader thread does three things and nothing else (it never waits on anyone, so the
brain never blocks on its standard output): appends the raw bytes to `stream.jsonl`, feeds each complete line to the adapter, and queues the
resulting events. The service then knows the brain's state as it happens: the end comes from the `result` event or `done`, not from polling
`done.json`.

### 4.2 Adapters and neutral events

An adapter turns one CLI's output into neutral events. It is chosen by the agent's `BRAIN_FORMAT` (`claude-stream-json` first; `text` for a
CLI that prints only its reply). The events (one JSON line each, `seq` and `t` on every one):

| Event | From | Fields |
|---|---|---|
| `session` | adapter | `id` (to resume) |
| `thinking` | adapter | `block`, `state` (started, ended): the model is thinking, its text is not given |
| `text.delta` / `text` | adapter | `block`, `text` (delta / whole block) |
| `action.start` | adapter | `block`, `fn` (the moment the model chose the action, before it runs) |
| `action.args` | adapter | `block`, `fn`, `args` (once the block is complete, before the call runs) |
| `say.delta`, `reply.delta` | adapter | `block`, `text` (the text argument of `say` / summary of `done`, decoded so far) |
| `call` | MCP server | `fn`, `args`, `risk`, `decision` (run, countdown, approval, refused) |
| `approval` | MCP server / service | `call`, `state` (waiting, allowed, denied, expired) |
| `call.end` | MCP server | `fn`, `ok`, `result` (short) |
| `say`, `done` | MCP server | `text` / `summary` (the authoritative text) |
| `usage` | adapter | `turns`, `cost`, `tokens` |
| `denied` | adapter | the CLI refused a tool (security event) |
| `state` | service | `queued`, `running`, `done`, `failed`, `stopped`, with `error` |

The MCP server writes its events as JSON lines on its standard output, which the service reads (it hosts the server, 3.5); the service is the
only writer of `events.jsonl` and gives it one order (`events.EventLog`, a lock across the brain's reader thread, the server's reader thread
and the main thread). `calls.jsonl`, `say.jsonl`, `done.json` and `state.json` stay as they are: the CLI, the cockpit and the snapshot read them.
The log drops deltas past 32 MB (blocks, actions and states are still written).

### 4.3 Correlation

The CLI passes the model's tool-use id to the MCP server: every `tools/call` carries `_meta: {"claudecode/toolUseId": "toolu_…",
"progressToken": n}` (S6). The server puts it in its `call` and `call.end` events, and the service joins them to the adapter's
`action.start`/`action.args` of the same block by that id: exact, also for parallel calls in one turn. (A brain whose CLI does not pass an id
falls back to order + name + arguments; none is known yet.) The CLI sends each call as soon as its block is complete, while the model is still
writing the next block (S6).

### 4.4 Transport: the log file

`events.jsonl` is the broker. The gateway watches it with inotify (`fs.watch`), reads from the last offset, and relays. A client connects with
`since=<seq>` and gets the missing events from the file, then the live ones; a reloaded page, a phone, a restarted gateway or a restarted
service lose nothing. A slow poll (1-2 s) stays as a fallback where inotify does not fire. The bus is not the transport (one connection per
publish, no replay, no resume); it may carry coarse notices for other consumers (a goal ended, an approval is waiting).

Backpressure: when a client's `bufferedAmount` grows, the gateway coalesces the deltas of a block into one "block so far" event for it; it never
blocks and never buffers without bound.

### 4.5 The page

On connect a page gets the goal's events so far, compacted (consecutive deltas of one block merged, which loses nothing), right after its
snapshot; it rebuilds its state from that replay, so there is no `since` to negotiate. Events of an action carry the labels the snapshot's turns
use (`label`, `live`), computed by the gateway. A reducer applies events to the running turn: append an action, change the live label, grow a text, show or close an approval. Updates are
batched per animation frame. The 600 ms snapshot no longer carries the Sysop chat (it keeps terminals, pins, worktrees); the chat's first
paint on connect is a replay of the goal's log.

The rhythm of the deltas is uneven (S7): free text comes in a steady ~30 chunks a second; the arguments of a call come smoothly with `opus`
(a chunk every ~50 ms) and in bursts with `sonnet` (26 chunks with a 0.6 s pause in the middle, or a whole summary in 0.1 s); thinking comes
as a hidden block (only its signature) that can last seconds. So the page paces what it shows: a burst is revealed at a steady rate that
catches up within a few hundred milliseconds, never all at once and never behind for long; and a `thinking` block start shows "thinking"
until the next block.

## 5. The agent boundary (`agent.conf`)

New keys, all optional, read by `swarmbox_agents.py` and `agents.mjs` like the others:

```
BRAIN_FORMAT=claude-stream-json          # the adapter; default text
BRAIN_RESUME="--resume {session_id}"     # how to resume; absent = no persistent session
BRAIN_STOP=INT                           # the polite stop signal before TERM; default TERM
BRAIN_HOME_ENV=CLAUDE_CONFIG_DIR         # the variable that points the CLI at the brain home
BRAIN_LOGIN_FAILURE="Not logged in|Please run /login|Invalid API key|OAuth token has expired|authentication_error|Credit balance is too low"
```

`--max-turns` stops being stripped by name: a placeholder that expands to nothing drops its whole word pair (a template rule, not a flag name).
A full command whose program is an agent of the box takes that agent's keys; any other program is read as `text`, with no session. New
placeholder in `BRAIN`: `{agent_dir}`, the agent's read-only folder. `BRAIN` for Claude Code gains `--setting-sources '' --settings '{"disableAllHooks":true}' --disable-slash-commands` and loses nothing else.

## 6. Where it lives

| Part | Code | Tests |
|---|---|---|
| agent keys | `container/scripts/swarmbox_agents.py`, `container/web/herdr/agents.mjs`, `container/addons/claude/agent/agent.conf`, `brain-settings.json` | `tests/fast/test_agents_registry.py` |
| hermetic run, MCP host, proxy | `swarmbox_sysop/brain.py` (`options`, `build`, `environment`, `prepare_home`, `McpHost`, `run`), `landlock.py`, `mcpserver.py` (`listen`, `proxy`, events) | `tests/fast/test_sysop_hermetic.py`, `test_sysop_brain.py` |
| events and adapters | `swarmbox_sysop/events.py` | `tests/fast/test_sysop_events.py` |
| service | `swarmbox_sysop/service.py` (`execute`), `history.py` (session home, stop note), `paths.py` | `tests/fast/test_sysop_service.py` |
| gateway | `container/web/herdr/hc-client.mjs` (`GoalEventsTail`, `compactEvents`), `server.mjs` (inotify pump, replay, backpressure) | `tests/fast/test_sysop_live_web.py` |
| page | `container/web/herdr/public/sysoplive.js` (the reducer, pure), `app.js` (`onSysopEvents`, `paceLive`, `redrawLiveTurn`) | `tests/fast/test_sysop_live_web.py`, the end-to-end run (section 9) |

### 3.6 The brain's program

An agent's command in the box is a SwarmBox shim (`swarmbox-shim`: install on first use, then exec the real program through `swarmbox-addon
run`). Inside the brain's sandbox and environment the shim can neither take the addon lock (`/tmp/swarmbox/addons.lock`) nor find the user's
install (HOME is the brain home): the first real run in the nested box failed with `swarmbox-addon: cannot open the lock file`. So the service
resolves the program before it starts the brain, outside both (`brain.real_program`: `swarmbox-addon where ADDON COMMAND`, after
`swarmbox-addon install ADDON` when there is no install yet), runs the real file, and puts its folder first in the brain's PATH (what the shim
would have added).

## 7. Risks

- The reader thread must never stall (a stalled reader blocks the brain on its standard output). It only reads, writes and queues.
- **A Stop can leave the session wrong about what ran** (S3): a call the MCP server had executed when SIGINT arrived was recorded in the
  CLI's transcript as rejected, and the resumed model said so. The next goal after a Stop starts with a short, authoritative note of the calls
  that did run (from the goal's `call.end` events), so the persistent session is corrected before the model acts on it.
- The extra turn after `done` (the CLI writes one more message, S3/S7) costs time and tokens; the service ends the brain on the first `done`
  as today (it no longer needs `done.json`: it sees the `call.end` of `done` in the stream).
- A CLI update can change its output; the adapter tolerates unknown events and the audit stream keeps the raw bytes.
- The filesystem sandbox may be unavailable in nested rootless Podman; it is defence in depth, not the boundary.

## 8. Spikes

Results are filled in below; the harness is described with each one. All runs: Claude Code 2.1.332, `sonnet`, in the box, environment by
allowlist (`env -i` with `PATH`, `HOME`, `LANG` and `CLAUDE_CODE_OAUTH_TOKEN`), a scratch working directory, never the live sysop.

Harness: `dev/spikes/sysop-brain/` (a fake MCP server that logs every request with a timestamp; a driver that reads the CLI's standard
output on a pipe and timestamps every line; a Landlock exec helper). Cost of all runs: about USD 0.10.

**S1 - Hermetic configuration.** Four variants of a one-call goal; what the `init` event lists:

| Variant | plugins | skills | slash commands | session and memory folder | login |
|---|---|---|---|---|---|
| as today (user `~/.claude`) | 5 | 20 | 54 | user's `~/.claude/projects/` | ok |
| `--setting-sources ''` | 5 | 20 | 54 | user's | ok |
| `CLAUDE_CONFIG_DIR=<empty dir>` | 5 | 19 | 53 | the brain home | ok |
| both | 5 | 19 | 53 | the brain home | ok |
| both + `--disable-slash-commands` (S8) | 5 | 0 | 0 | the brain home | ok |

The 5 plugins and 19 skills are the CLI's built-ins (`path: builtin`); the user brought one skill. `--settings '{"enabledPlugins":{…:false}}'`
turns 4 of the 5 built-in plugins off. The input tokens are the same in every variant (2370-2404): with the Skill tool off, skills and slash
commands are not in the model's context. The isolation is about what runs and where the session lives, not about tokens.

**S2 - Hooks and CLAUDE.md.** A fake user home and a project folder, each with hooks on `SessionStart`, `UserPromptSubmit`, `PreToolUse`,
`PostToolUse`, `Stop` (each appends a line to a file) and a `CLAUDE.md` canary ("every summary must contain PINEAPPLE / MANGO"):

| Variant | user hooks ran | project hooks ran |
|---|---|---|
| `--tools ''` only (as today) | **all 5** | **all 5** |
| + `--setting-sources ''` | none | none |
| + `CLAUDE_CONFIG_DIR` | none | (not tested alone) |
| + `--settings '{"disableAllHooks":true}'` | none | - |

Hooks are a real door around `--tools ''` today. Neither `CLAUDE.md` reached the model (no canary word, identical token counts): with
`--system-prompt` in print mode, memory files are not loaded.

**S3 - Persistent session and Stop.** With a hermetic home and a fixed working directory: goal 1 told a word, goal 2 `--resume <id>` recalled it;
`--resume` from a different working directory recalled it too; the session id stays the same across resumes. Stop: SIGINT while a 20 s call was
pending made the CLI write its `result` event and exit 0 within 1.3 s, and the session resumed with the word remembered. But the `say` the MCP
server had executed was recorded as rejected, and the resumed model said it never ran (section 7).

**S4 - Environment.** The brain runs with `env -i` + `PATH`, `HOME`, `LANG`, the token. The MCP server saw the brain's variables (a probe
variable passed to the brain arrived) plus the ones of `mcp.json`, plus `CLAUDE_CODE_MESSAGING_SOCKET`/`_TOKEN`, `CLAUDE_PROJECT_DIR`; **not**
`CLAUDE_CODE_OAUTH_TOKEN`.

**S5 - Sandbox and limits.** In the box: Landlock ABI 3, unprivileged user namespaces, seccomp filter on, no bubblewrap. A whole goal ran under
Landlock with writes only under the brain home, the goal folder and `/dev`, `TMPDIR` inside the brain home and no `/tmp`; a write outside was
denied. Peak of the process group (CLI + MCP server + helper): RSS 239-252 MB, VSZ 5.6-7.1 GB, 20-29 threads, 3 processes.

**S6 - Correlation.** Every `tools/call` carried `_meta.claudecode/toolUseId` equal to the `id` of the `tool_use` block in the stream. Three
parallel `run` calls in one message: the first was sent 6 ms after its block completed and ran while the model was still writing the other two.

**S7 - The stream's timing**, read on a pipe (seconds from start):

| | sonnet | opus |
|---|---|---|
| CLI start to `init` | 0.9 | ~1 |
| `say` (390 chars) | 26 chunks over 1.16 s, bursty (median gap 0, a 0.62 s pause) | 21 chunks over 1.23 s, median gap 50 ms |
| head start of the `say` text over its MCP call | 1.17 s | ~1.2 s |
| `done` (330-480 chars) | 28 chunks in 0.11 s | 33 chunks over 1.12 s, median gap 49 ms |
| thinking before `done` | 2.7 s, text hidden | 2.8 s, text hidden |
| free text, 250 words, no calls | 127 chunks over 4.5 s, one every ~35 ms | - |

The pipe adds no buffering (chunks arrive spread out as the model writes them). The text after `done` (the extra turn) came as one burst.

**What changed in the design because of the spikes:** `--setting-sources ''` is required, not optional (S2); correlation is by the id the CLI
passes, not by order (S6); Landlock replaces "Landlock or bubblewrap", without `/tmp` (S5); no `RLIMIT_AS` (S5); a Stop is followed by a
correcting note (S3); the page paces bursts and shows thinking (S7).

Open:
- **TODO: a user logged in only through `~/.claude`** (a login made in a tab, no token): the hermetic brain does not see it and the goal fails
  with a hint to add `CLAUDE_CODE_OAUTH_TOKEN`. Sharing that login (a symlinked credentials file under the brain home, and what an OAuth refresh
  does to it) is not measured; the box's sysop uses a token today.
- Whether `--disable-slash-commands` or a disabled built-in plugin changes anything a goal needs (none seen).

## 9. End to end (2026-11-26)

An image built from the working tree (`dev/dev-build.sh`), a test box in nested rootless Podman, the real `claude` 2.1.332 and sysop addons,
`sonnet`, `CLAUDE_CODE_OAUTH_TOKEN` passed to the box; the Web Studio driven by a headless Chromium inside the box over CDP (a goal typed in
the panel, the running turn sampled every 50 ms, the `sysop_events` frames counted).

- **Sandbox**: `swarmbox-sysop status` said `sandbox: landlock` inside the nested box.
- **The real brain process** (`/proc/<pid>` of the claude binary during a goal): environment `CLAUDE_CODE_OAUTH_TOKEN CLAUDE_CONFIG_DIR HOME LANG
  PATH TMPDIR` (plus the box's `SWARMBOX_TEST_*`), none of the box's others (`NODE_VERSION`, `NPM_CONFIG_CACHE`, `BROWSER`...); working directory
  `<state>/sysop/brain/work`; `NoNewPrivs: 1` (set with the Landlock domain). Its `init` event: the 9 sysop tools, 0 skills, 0 slash commands,
  memory in the brain home.
- **Hooks**: hooks on the five events in the box user's `~/.claude/settings.json`, each writing a marker file: no marker after the goals.
- **Correlation**: every `call` of the MCP server carried the id of its `action.start` block (`toolu_…`), for say, box_state, run and done.
- **The page** (goal "say what you will check, box_state system, done with 5 points"): first live event 484 ms after Enter; the `say` shown as a
  note being written (cursor) from 2.4 s, before the call ran; "Inspecting box state…" when the model chose it, "box_state · system" when its
  arguments were complete; the reply grew from 2 to 466 characters between 5.3 and 7.0 s; 70 `sysop_events` frames, 4 snapshots.
- **Approval** (`confirm-all`, goal "run echo ..."): the action at 2.2 s, its arguments at 2.6 s, the `approval` event at 2.69 s and the card on
  the page at 2.73 s (the event brought the snapshot), before a watcher polling the pending file every 50 ms saw it; the card gone 70 ms after
  the approval; the line "Waiting for you · run → shell" while it waited.
- **A page opened in the middle of a goal** got an 11-event compacted replay and showed the say note and the running `run` at once.
- **Stop and resume**: a goal stopped while its `run sleep 40` went on; the note `- \`run\` in shell: sleep 40 (ran)` was kept; the next goal
  resumed the session (`session_home: hermetic-1`, the transcript in the brain home, none in the user's `~/.claude`) and answered that the
  command ran and the goal was interrupted; the note was used once.
- Found and fixed in this run: the shim (3.6); the live line after `done` and between a call and the next block (now "Finishing…" and
  "Thinking…" instead of an old action's label).

