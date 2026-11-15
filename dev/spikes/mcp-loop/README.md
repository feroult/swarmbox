# mcp-loop spike

PoC of the sysop loop: `claude -p` is the brain, `mcp_tmux.py` (stdlib only, stdio JSON-RPC) is the tool server over a tmux socket.

- `mcp_tmux.py`   the MCP server: list_tabs, read_tab, run, input, say, done. Env: SYSOP_TMUX_SOCKET, SYSOP_STATE, SYSOP_SETTLE, SYSOP_STEP_PAUSE.
- `brain.sh`      the exact claude invocation (writes the MCP config, own process group, timeout). `GOAL=... MODEL=haiku SYSOP_TMUX_SOCKET=x ./brain.sh`
- `system-prompt.txt`  the system prompt used.
- `selftest.py`   drives the server with no model (needs tmux). `scenario.sh`, `flags.sh`, `summarize.py`, `fake_agent.py`  the test harness (run in a container).

Report: docs/spikes/mcp-loop.md
