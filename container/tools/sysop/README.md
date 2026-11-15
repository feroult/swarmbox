# sysop

An agent loop that operates the box from a goal ([docs/plugins-design.md](../../../docs/plugins-design.md)). It subscribes to the topic `goal`
of `swarmbox-bus`, runs a brain (a command that speaks MCP, `claude -p` by default) with seven tools, and the tools read and type into the tabs
through the bus. The host rates every action first (countdown, approval, block), keeps budgets, and writes an audit file.

```
swarmbox-sysop serve [--log]     the resident service (prepare.sh starts it, detached, at every start of the box)
swarmbox-sysop goal "text"       publish a goal (--source panel|voice|cli, --wait follows it)
swarmbox-sysop status [--json]   the service and its goals (exit 1 when it is not running)
swarmbox-sysop stop [GOAL_ID]    the stop key: kills the brain's process group, ends the goal, drops the queue
swarmbox-sysop mcp               the MCP server of a goal (the brain's MCP config runs it)
swarmbox-sysop panel             the panel (goal, log, countdown, approval; g types a goal), in a tmux pane
swarmbox-sysop dock open|close|toggle|redock   the panel in tmux, one per window; Ctrl+A then S toggles it; `serve --dock` opens it for a goal
```

Settings (environment, `SWARMBOX_SYSOP_*`, see `lib/swarmbox_sysop/config.py`): `BRAIN` (preset `claude` or a command template, never run by a shell),
`MODEL` (haiku), `AUTONOMY` (`confirm-all` | `confirm-risky` | `auto`), `COUNTDOWN` (4 s, 0 = none), `APPROVAL_TIMEOUT` (60 s), `MAX_STEPS` (20),
`MAX_SECONDS` (300), `MAX_GOALS` (5).

Files (all private, folders 0700 and files 0600; `lib/swarmbox_sysop/paths.py`):

- run folder `$SB_RUN_DIR/sysop/`: `serve.lock`, `serve.pid`, `status.json`, `stop.request`
- state folder `$SB_STATE_DIR/sysop/`: `events.jsonl` (the audit file, append-only), `serve.log`, `goals/<id>/` with `state.json`, `pending_action.json`,
  `decision.json`, `stream.jsonl` (what the brain printed), `calls.jsonl`, `say.jsonl`, `done.json`, `context.json`, `mcp.json`, `mcp.log`

The contract between the service, the MCP server and the panel is in the docstring of `lib/swarmbox_sysop/ipc.py`; the risk and the autonomy
table are in `policy.py`; the tools are in `mcpserver.py`. Tests: `tests/test_sysop_*.py` (`test_sysop_real.py` needs Podman, see its docstring). The whole path with the real bus, the real Claude Code as the brain and a second one in a tab is `tests/e2e_sysop.sh` (Podman, needs a login, not part of the fast gate).
