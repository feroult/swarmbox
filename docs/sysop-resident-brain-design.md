# The Sysop Brain: One Resident Process (Design)

Status: **implemented (2026-11-27)**. The measurements behind it: [spikes/resident-brain.md](spikes/resident-brain.md). What it builds on:
[sysop-brain-design.md](sysop-brain-design.md) (the hermetic brain, the live events). Only Claude Code is a resident brain today.

## 1. Purpose

Until now the brain was one `claude -p` per goal: a process started with the goal on its stdin and killed after `done`. The session was
resumed from disk (`--resume`), so the brain remembered, but every goal paid a start, the stop key was a signal (SIGINT, then TERM), and a
stopped CLI could record a call that ran as refused (sysop-brain-design.md 7). This design keeps **one** brain process alive across goals:

- a goal is one user message to the live process, and its end is that turn's `result`;
- Stop is an **interrupt** of the turn (the CLI's own `control_request`), not a signal: the turn ends in about 0.01 s, the process and its session
  stay, and the model's record of what ran is true (spike T3, T4);
- everything that made the brain safe stays: the hermetic home and flags, the environment by allowlist, Landlock, the policy and the audit of
  the MCP server, one MCP server per goal.

Out of scope here, next: the host's schedule and triggers (they publish goals; this design is what makes a goal cheap).

## 2. The process

```
swarmbox-sysop serve
 ├─ Runtime (brain.py): one `claude -p --input-format stream-json ...` in its own process group, Landlock, built environment
 │    stdin  <- one user message per goal; a control_request interrupt on Stop or the deadline
 │    stdout -> the pump -> the current goal's stream.jsonl and EventLog (ClaudeStreamAdapter, a new one per goal)
 │    stderr -> the pump -> the current goal's brain.err
 │    its MCP server is `swarmbox-sysop mcp-proxy --reconnect <run>/sysop/brain.sock`
 └─ McpHost (one per goal, as before): listens on that stable path, takes ONE connection, then removes the socket file
```

- **Started** at the first goal, with `--resume <id>` when the conversation has a session (conversation.json, as before).
- **Kept** while the service runs. Started again, resuming the same session, when it died (a crash, the OOM killer) or when a stop could not end
  its turn (the kill fallback, below).
- **Replaced** when the conversation's session is not the live one: **+ New** clears the id in conversation.json, so the next goal starts a
  process with no `--resume`.
- **Ended** with the service: stdin closed (the CLI exits 0), then TERM and KILL to the group; a dead service still takes it along (the death signal).

Which brains are resident: a template whose words have `--input-format stream-json` (Claude Code's preset now). Any other template keeps the
one-process-per-goal run, unchanged (a template of your own, `opencode run`).

## 3. One goal

1. The service writes the goal's `context.json`, starts the goal's McpHost on the stable socket, and makes sure the Runtime runs.
2. The goal is sent as one user message: the source note (what was the system prompt's last line: "the goal was spoken...") comes first, then
   the pre-seeded box state, the stop note after a Stop, and the goal. The system prompt is fixed for the life of the process, so the source of
   each goal travels with it; a message never starts with `/`.
3. The pump sends every line to the goal's `stream.jsonl` and to a new ClaudeStreamAdapter, whose events reach the goal's EventLog: the Web
   Studio sees what it saw.
4. The goal ends at the turn's `result`. After `done`, the turn is given a short grace to end by itself; then it is interrupted.
5. Stop and the deadline: an interrupt; when no `result` comes in 3 s, the process group is killed and the next goal starts a new process on the
   same session. An interrupted turn (`error_during_execution`) is `stopped`, or `failed` with the time budget's message.
6. The McpHost of the goal is stopped. The cost of the goal is the difference of the process's `total_cost_usd` (a total, spike section 3).
7. The session id the service keeps is the one of a turn's `system/init`, the line the CLI writes when a session really runs. A `--resume` the
   CLI refuses still ends with a `result` that carries the refused id ("No conversation found with session ID: ...", then exit 1, measured):
   that goal fails with those words, the service clears the id, and the next goal starts a new session. A turn that ends in error with no
   interrupt of the sysop is a failure; a process that goes away during a goal fails it, whatever it wrote last.

### The MCP server, per goal

The CLI starts its MCP server once and keeps the connection. The sysop's server must stay per goal: it holds the goal's context (its folder, its
audit binding, the time budget) and the policy's memory of what was typed. So the proxy the CLI starts reconnects:

- it connects to the socket when a request arrives and it has no connection;
- when the server closes the connection (the goal ended), the proxy does not close its own stdout: the CLI keeps a live server;
- a request with no server behind it (between goals, or a socket that does not answer) gets a JSON-RPC error from the proxy itself.

The server needs no handshake per connection: it answers `tools/call` and `tools/list` whatever came before. The socket is private, as before,
and each McpHost still takes only one connection and removes the file at once.

## 4. Files and limits

- `goals/<id>/stream.jsonl` and `brain.err`: the lines written while the goal ran (the pump switches files at each goal); lines between goals go
  to `<state>/sysop/brain/idle.log`, at most 1 MiB.
- Landlock: the brain home and `/dev` (the goal folder changes each goal and the CLI never wrote there).
- `--max-turns` is gone from the preset (in a resident process it counts what is not one goal); `sysop.max_steps` is enforced by the MCP
  server's policy, as it already was, and `sysop.max_seconds` by the service.
- RLIMIT_FSIZE stays: it limits any file the CLI writes; the service's own files are written by the service.

## 5. Plan of the change

1. Spike (done): [spikes/resident-brain.md](spikes/resident-brain.md).
2. `mcpserver.proxy`: the reconnecting mode (`--reconnect`).
3. `brain.py`: `Runtime` (start, send, interrupt, kill, close; the pump with a switchable target; cost by difference) and `run_resident`, with
   the same `Result` as `run`. `system_prompt` without the source note for a resident brain; `source_note(source)`.
4. `service.py`: a resident template uses the Runtime (the stable socket, the session rule of + New, the close at shutdown); other
   templates keep `brain.run`.
5. `claude/agent/agent.conf`: `BRAIN` with `--input-format stream-json` and without `--max-turns`.
6. Tests: the fake `claude` (fixture and in-process) speaks the resident mode; tests of Stop, crash, login, deadline, + New and the pump; the
   one-shot path keeps its tests with a template of its own. Then the fast suite, and the slow suite in nested Podman (`sh dev/test-slow.sh`).
7. Docs: sysop.md (the brain, Stop, the limits), sysop-brain-design.md (a pointer here), a changelog fragment.

## 6. Risks

| Risk | Answer |
|---|---|
| The CLI changes its stream-json input or its interrupt | It is what Anthropic's Agent SDK uses; a failed interrupt falls back to the kill, then a new process resumes the session |
| A long session grows | The CLI compacts its own context; + New starts a new session |
| A turn that never ends after `done` | the grace, then the interrupt, then the kill |
| The proxy reconnects to a server of another goal | goals run one at a time, the McpHost of a goal is stopped before the next starts, each takes one connection |
| Autoname and autocontext | untouched: they run their own one-shot `NAMER` and `DIGEST`, not the brain |
