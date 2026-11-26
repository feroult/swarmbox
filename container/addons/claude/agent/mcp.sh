#!/bin/bash
# Claude Code's copy of the box's MCP servers: <workspace>/.claude/mcp-servers.json, the file the claude function passes with
# --mcp-config (agent.conf MCP_ARGS). Run by `swarmbox-addon prepare` (serve step 7, and right after an install) with SWARMBOX_MCP_FILE,
# the box's list written by swarmbox-mcp. The format is the same {"mcpServers": {...}}. Claude Code refuses a --mcp-config file that is
# missing, so a missing or broken list gives an empty one (and exit 1 for a broken one). Atomic, mode 0600.
set -u
src=${SWARMBOX_MCP_FILE:-}
out="$HOME/.claude/mcp-servers.json"
command -v jq > /dev/null 2>&1 || { echo "claude mcp: jq not found" >&2; exit 2; }
mkdir -p "$HOME/.claude" || { echo "claude mcp: cannot create $HOME/.claude" >&2; exit 1; }
tmp=$(mktemp "$HOME/.claude/.mcp-servers.json.XXXXXX") || { echo "claude mcp: cannot create a temporary file" >&2; exit 1; }
trap 'rm -f "$tmp"' EXIT
chmod 600 "$tmp"
rc=0
if [ -n "$src" ] && [ -f "$src" ] && jq -e '(.mcpServers // {}) | type == "object"' "$src" > /dev/null 2>&1; then
    jq '{mcpServers: (.mcpServers // {})}' "$src" > "$tmp" || { echo "claude mcp: cannot read $src" >&2; exit 1; }
else
    if [ -n "$src" ] && [ -f "$src" ]; then
        echo "claude mcp: $src is not a usable MCP file: Claude Code gets no MCP servers of the box" >&2
        rc=1
    fi
    printf '{"mcpServers": {}}\n' > "$tmp"
fi
mv -f "$tmp" "$out" || { echo "claude mcp: cannot write $out" >&2; exit 1; }
exit "$rc"
