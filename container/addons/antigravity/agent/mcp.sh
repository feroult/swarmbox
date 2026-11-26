#!/bin/bash
# The box's MCP servers for agy, as an Antigravity plugin of SwarmBox's own: ~/.gemini/config/plugins/swarmbox/{plugin.json,mcp_config.json}.
# agy loads the MCP servers of every enabled plugin, the format is the same `mcpServers` map, and the user's own
# ~/.gemini/config/mcp_config.json is never touched. The user can turn it off like any plugin (`agy plugin disable swarmbox`).
# Run by `swarmbox-addon prepare` (serve step 7, and right after an install) with SWARMBOX_MCP_FILE, the box's list written by
# swarmbox-mcp. Rewritten at every start, so a server removed from the box goes away; a missing list writes nothing. Exit 1 when the
# list is not a usable MCP file (the plugin is left as it was).
set -u
src=${SWARMBOX_MCP_FILE:-}
dir="$HOME/.gemini/config/plugins/swarmbox"
command -v jq > /dev/null 2>&1 || { echo "antigravity mcp: jq not found" >&2; exit 2; }
[ -n "$src" ] && [ -f "$src" ] || exit 0
if ! jq -e '(.mcpServers // {}) | type == "object"' "$src" > /dev/null 2>&1; then
    echo "antigravity mcp: $src is not a usable MCP file: the MCP servers are not given to agy" >&2
    exit 1
fi
mkdir -p "$dir" || { echo "antigravity mcp: cannot create $dir" >&2; exit 1; }
t=$(mktemp "$dir/.plugin.json.XXXXXX") || exit 1
if ! { jq -n '{name: "swarmbox", version: "1.0.0", description: "The MCP servers of the SwarmBox (written by SwarmBox at every start)"}' > "$t" \
    && mv -f "$t" "$dir/plugin.json"; }; then
    rm -f "$t"; echo "antigravity mcp: cannot write $dir/plugin.json" >&2; exit 1
fi
t=$(mktemp "$dir/.mcp_config.json.XXXXXX") || exit 1
chmod 600 "$t"
if ! { jq '{mcpServers: (.mcpServers // {})}' "$src" > "$t" && mv -f "$t" "$dir/mcp_config.json"; }; then
    rm -f "$t"; echo "antigravity mcp: cannot write $dir/mcp_config.json" >&2; exit 1
fi
exit 0
