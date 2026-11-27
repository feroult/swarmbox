# Spike: a resident brain (ACP and Claude Code's own stream-json input)

Verdict: **works**. Claude Code's own resident mode (`claude -p --input-format stream-json`) is what the sysop uses
([sysop-resident-brain-design.md](../sysop-resident-brain-design.md)). The Agent Client Protocol (ACP) works with every CLI tried, but how far each one
can be locked down differs, and the only ACP route to Claude Code is a third-party adapter, so it is not used for now.
Code in `dev/spikes/resident-brain/`. Run on 2026-11-27, in the box, every agent with a temporary `HOME` holding only its login
(no settings, no hooks, no instructions of the user), against `fake_mcp.py`: a stdio MCP server with three tools (`note`, `slow` that sleeps,
`done`) that logs every call, cancel and exit.

## 1. The scenario

One resident process and one session, for every agent:

| Step | What is asked | What it shows |
|---|---|---|
| T1 | remember PAPAYA, call `note`, list every tool by name | the tools reach the agent; which tools it has |
| T2 | call `note` again | a second goal in the same process |
| T3 | call `slow` 20 s; the client cancels 4 s after the call reached the server | cancel latency, what the MCP server sees |
| T4 | did `slow` finish? | the model's record after a cancel (the SIGINT stop of [sysop-brain-design.md](../sysop-brain-design.md) 8, S3, recorded a call that ran as refused) |
| T5 | create a file with a built-in tool | whether a tool other than ours exists or asks |
| kill -9, start again, resume the session | | crash recovery |
| T6 | what was the word? | memory survives the crash |

`acp_spike.py` drives an ACP agent (`initialize`, `session/new` with the MCP server, `session/prompt`, `session/cancel`, `session/load`) and
answers `session/request_permission`: allow for our tools, reject for anything else. `stream_spike.py` drives `claude -p --input-format
stream-json`: one user message per line on stdin, `{"type":"control_request","request":{"subtype":"interrupt"}}` to cancel, `--resume` after
the kill.

## 2. ACP

| | Claude Code (`@agentclientprotocol/claude-agent-acp` 0.113.0) | Antigravity 1.5.18 (`agy acp`) | Codex 0.172.0 (`@agentclientprotocol/codex-acp` 2.12.1) |
|---|---|---|---|
| start / `session/new` | 0.3 s / 2.0 s | 0.1 s / 1.3 s | 0.4 s / 1.6 s |
| a simple turn | 1.3 to 3.8 s | 7 to 16 s | 2 to 28 s |
| cancel | the turn ends `cancelled` in 0.02 s; the MCP server gets `notifications/cancelled` | at once; the server gets it | 0.02 s; the server gets it |
| T4 | "interrupted" (true) | "interrupted" (true) | "interrupted" (true) |
| kill -9 + `session/load` | 0.8 s, PAPAYA | 1.2 s, PAPAYA | 1.0 s, PAPAYA |
| only our tools | yes (`_meta.claudeCode.options.tools: []`) | no: 18 tools of its own (`run_command`, `search_web`, `schedule`, subagents...), no flag removes them | no: dozens (`exec_command`, `apply_patch`, apps, subagents...) |
| settings, instructions, hooks | not read (`settingSources: []`; a planted `CLAUDE.md` and a `UserPromptSubmit` hook did nothing) | not tried | `AGENTS.md` read (the canary showed); `project_doc_max_bytes=0` stops it |
| tools of its own ask the client | none exist | edit and read ask (rejected, nothing written); **`search_web` ran without asking** | nothing asks: its own reviewer ("Guardian Review") approves, and `apply_patch` wrote the file with `sandbox_mode = "read-only"`, even with most features turned off |

- The Claude Code adapter is **not Anthropic's**: it is Zed Industries' (Apache-2.0), released almost every day (a dozen versions in a week), about
  77 MB of Node modules without its optional 381 MB bundled CLI, and the lock-down depends on how it passes its options to the Agent SDK.
- It can emit the SDK's raw messages (`_meta.claudeCode.emitRawSDKMessages`, as `_claude/sdkMessage` notifications): they are Claude Code's
  stream-json, line for line.
- Antigravity's `schedule` tool holds the turn open until it fires (a one-minute task: a 74 s turn); nothing fired by itself in the 150 s after.
  Claude Code's `CronCreate` lives in the memory of the process ("session-only"; its `durable` flag "has no effect"). Neither is a scheduler the
  sysop can rely on: time stays with the host.
- Every CLI forwards a cancel to the MCP server as `notifications/cancelled`; stopping the work is the server's job (the fake kept sleeping).

## 3. Claude Code's own resident mode

The flags of the sysop's preset as they were (`--tools ''`, `--strict-mcp-config`, `--allowedTools 'mcp__sysop__*'`, `--permission-mode
dontAsk`, `--setting-sources ''`, `--settings brain-settings.json`, `--disable-slash-commands`, `--system-prompt`, `--output-format stream-json
--include-partial-messages --verbose`), without `--max-turns`, plus `--input-format stream-json`. Claude Code 2.1.332, sonnet.

| Step | Result |
|---|---|
| T1 (includes the start) | 3.8 s; the init lists only `mcp__sysop__done`, `note`, `slow`; no canary of the planted `CLAUDE.md` files; the hook did not run |
| T2 | 2.5 s, same process, same MCP server process (one `initialize` for T1 to T5) |
| T3 | `control_response` success at once; the turn's `result` 0.01 s after the interrupt, subtype `error_during_execution`, `is_error` true; the server got `notifications/cancelled` |
| T4 | "It was interrupted ... never returned 'slow finished'" (true) |
| T5 | "The only tools I have are the three sysop ones"; nothing written |
| kill -9, `--resume`, T6 (includes the start) | 2.3 s, PAPAYA |
| stdin closed | exit 0 |

- Every turn writes a `system/init` and ends with one `result`; `num_turns` counts the turn, **`total_cost_usd` is the total of the process** (the
  cost of one turn is the difference).
- An interrupted turn ends with `result` subtype `error_during_execution`: a stop, not a failure.
- The output is the same stream-json as one goal per process: the sysop's `ClaudeStreamAdapter` reads it unchanged.

## 4. What it decided

- The brain becomes one resident Claude Code process, driven over its own stream-json input: no new dependency, the hardened flags already
  proven, the same output format. Stop becomes an interrupt, not a signal.
- ACP stays the route for a second brain: `agy acp` is the vendor's own, but its web search must be blocked first; Codex cannot be locked down today.
- Scheduling, triggers and memory are the host's, whatever the brain.
