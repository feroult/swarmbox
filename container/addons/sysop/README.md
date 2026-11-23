# sysop

An agent loop that operates the box from a goal ([docs/addons-design.md](../../../docs/addons-design.md)). It subscribes to the topic of
`sysop.topic` (default `goal`) of `swarmbox-bus`, in the group `sysop.group` (default `sysop`: two sysops of a group handle a goal once between them),
runs a brain (a command that speaks MCP, `claude -p` by default) with eleven tools, and the tools read and type into the tabs through the command
`swarmbox-tabs` (the bus is for goals only). The host rates every action first (countdown, approval, block), keeps budgets, and writes an audit file.

```
swarmbox-sysop serve [--log]     the resident service (prepare.sh starts it, detached, at every start of the box)
swarmbox-sysop goal "text"       publish a goal (--source panel|voice|cli, --wait follows it)
swarmbox-sysop status [--json]   the service and its goals (exit 1 when it is not running)
swarmbox-sysop stop [GOAL_ID]    the stop key: kills the brain's process group, ends the goal, drops the queue
swarmbox-sysop mcp               the MCP server of a goal (the brain's MCP config runs it)
swarmbox-sysop panel             the panel (goal, log, countdown, approval; g types a goal), in a tmux pane
swarmbox-sysop dock open|close|toggle|redock|sync   the panel in tmux, one per window; Ctrl+A then S shows or hides it; `serve --dock` keeps it as `sysop.panel` says: up in every window (always, the default), open while a goal runs (auto) or never (off); it never takes the focus
swarmbox-sysop veto | approve       the keys of any tab: Ctrl+A then V veto, X stop, a approve (opens the approval prompt and focuses the panel), g goal
```

Settings (environment, `SWARMBOX_SYSOP_*`, see `lib/swarmbox_sysop/config.py`): `TOPIC` (goal), `GROUP` (sysop), `BRAIN` (preset `claude` or a command template, never run by a shell),
`MODEL` (sonnet), `AUTONOMY` (`confirm-all` | `confirm-risky` | `auto`, default `auto`), `COUNTDOWN` (4 s, 0 = none), `APPROVAL_TIMEOUT` (60 s), `MAX_STEPS` (20),
`MAX_SECONDS` (300), `MAX_GOALS` (5), `PANEL_MODE` (`always` | `auto` | `off`: when the panel is in tmux; not `SWARMBOX_SYSOP_PANEL`, which marks a panel pane).

Files (all private, folders 0700 and files 0600; `lib/swarmbox_sysop/paths.py`):

- run folder `$SB_RUN_DIR/sysop/`: `serve.lock`, `serve.pid`, `status.json`, `stop.request`, `watch.lock`, `watch.pid` (the watcher that starts the service again when it dies, `watch.py`), `crashloop` (only while the watcher has given up)
- state folder `$SB_STATE_DIR/sysop/`: `events.jsonl` (the audit file, append-only; rotated past 8 MiB, three old files kept: at most 32 MiB), `serve.log` (moved to `serve.log.1` past 1 MiB), `goals/<id>/` with `state.json`, `pending_action.json`,
  `decision.json`, `stream.jsonl` (what the brain printed), `calls.jsonl`, `say.jsonl`, `done.json`, `context.json`, `mcp.json`, `mcp.log`

The contract between the service, the MCP server and the panel is in the docstring of `lib/swarmbox_sysop/ipc.py`; the risk and the autonomy
table are in `policy.py`; the tools are in `mcpserver.py`. Tests: `tests/fast/test_sysop_*.py` and `tests/slow/test_sysop_*.py` (the slow ones need Podman, see their docstrings and `dev/test-slow.sh`). The soak and fault test of the whole stack for 40 minutes (kills, floods, a full disk, SIGSTOP, a table of fault, what happened, recovery time) is `tests/e2e/soak_v1.sh` (Podman, not part of the fast gate). The whole path with the real bus, the real swarmbox-tabs, the real Claude Code as the brain and a second one in a tab is `tests/e2e/e2e_sysop.sh` (Podman, needs a login, not part of the fast gate); the same from the microphone in a browser, with the web terminal, the voice addon and Whisper, is `tests/e2e/e2e_voice.sh`.
