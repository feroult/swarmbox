#!/usr/bin/env bash
# Run the sysop brain once: claude -p with only our MCP tools.
# Usage: GOAL="..." MODEL=haiku SYSOP_TMUX_SOCKET=sock ./brain.sh   (stream-json on stdout, audit log lines on stdout)
# Env: MODEL (default haiku), TIMEOUT (s, default 120), STATE (dir for say.log, done.json, mcp.log), CLAUDE_BIN, PROMPT_FILE, SYSOP_SETTLE=1 (run/input return the settled screen), EXTRA_FLAGS
set -u
here=$(cd "$(dirname "$0")" && pwd)
STATE=${STATE:-$(mktemp -d)}; export SYSOP_STATE=$STATE
cfg=$STATE/mcp.json
cat >"$cfg" <<JSON
{"mcpServers":{"tmux":{"command":"python3","args":["$here/mcp_tmux.py"],
 "env":{"SYSOP_TMUX_SOCKET":"${SYSOP_TMUX_SOCKET:?}","SYSOP_STATE":"$STATE","SYSOP_PANEL_WINDOW":"${SYSOP_PANEL_WINDOW:-}","SYSOP_SETTLE":"${SYSOP_SETTLE:-0}","SYSOP_STEP_PAUSE":"${SYSOP_STEP_PAUSE:-0.15}"}}}}
JSON
SYSTEM=$(cat "${PROMPT_FILE:-$here/system-prompt.txt}")
# setsid: own process group, so a timeout can kill claude and the MCP server together.
exec setsid timeout -k 5 "${TIMEOUT:-120}" "${CLAUDE_BIN:-claude}" -p \
  --model "${MODEL:-haiku}" \
  --mcp-config "$cfg" --strict-mcp-config \
  --tools "" \
  --allowedTools 'mcp__tmux__*' \
  --permission-mode dontAsk \
  --no-session-persistence \
  --system-prompt "$SYSTEM" \
  --output-format stream-json --verbose \
  ${EXTRA_FLAGS:-} <<<"${GOAL:?}"
