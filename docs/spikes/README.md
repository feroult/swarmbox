# Spikes for the plugins design

Four proofs of concept run before the build. The reports describe the spike programs as they were then (the tabs as `tab/<tab>/...` topics of the bus, a fixed `goal` queue, `get`, `ls`, `watch --no-screen`); the build changed that: topics are settings, `pub` counts receivers and groups share the work, and the tabs are the separate command `swarmbox-tabs`. What the build keeps is in addons-design.md. Their findings are summarized in "Decisions from the spikes" of [addons-design.md](../addons-design.md). The code is under `dev/spikes/`; all tests ran in Podman containers, never on the master tmux.

## enter: works with changes
Typing a prompt into the real Claude Code 2.1.325 through tmux. Text with `send-keys -l`, a 150 ms pause, then a separate Enter works at every size; a burst fails for long prompts. Covers state detection, special characters, busy typing, Esc and Ctrl+C, and the first-run dialogs. Report: [enter.md](enter.md). Code: `dev/spikes/enter/` (`enter.sh`, `lib.sh`, `poc-test.sh`, `screens/`).

## mcp-loop: works
The agent loop as `claude -p` with only our MCP tmux tools. 8 of 8 runs succeeded, haiku in 6 to 12 s for about 0.001 USD; prompt injection resisted in 4 of 4 runs; the same server connects to gemini and opencode. Report: [mcp-loop.md](mcp-loop.md). Code: `dev/spikes/mcp-loop/` (`mcp_tmux.py`, `brain.sh`, `system-prompt.txt`, `selftest.py`, `scenario.sh`, `flags.sh`).

## tmux-facts: works with changes
Facts about tmux: the active tab with several clients, addressing, capture and the markers, send-keys and braces, control-mode events, the panel hook. 24 tests pass on tmux 3.5a and 3.7c. Found that `context.redact` is quadratic on long runs of one character. Report: [tmux-facts.md](tmux-facts.md). Code: `dev/spikes/tmux-facts/` (`tmuxfacts.py`, `test_tmuxfacts.py`, `run-in-container.sh`, `fixtures/`).

## bus: works
The broker and its CLI: asyncio, a unix socket, line-delimited JSON, round-robin `goal`, no ack, 13 ms per CLI call. Tests with 0 failures on the host and in a container; the entrypoint step and host forwarding are designed but not written. Report: [bus.md](bus.md). Code: `dev/spikes/bus/` (`swarmbox-bus`, `test_bus.py`).
