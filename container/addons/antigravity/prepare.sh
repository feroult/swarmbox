#!/bin/bash
# Antigravity CLI (agy) prepare.sh: run by `swarmbox-addon prepare` (serve step 7 and right after `swarmbox-addon install antigravity`).
# Gives agy the MCP servers of the box (sync_agy_mcp, below), then seeds SwarmBox's default settings in ~/.gemini/antigravity-cli/settings.json — statusLine pointing to this addon's own statusline.sh,
# dark purple-friendly colorScheme, no feedback surveys, and non-workspace access (the box is already the sandbox).
#
# Rules:
#   - Isolated to the antigravity addon: never writes the files of Claude Code or any other agent (it reads the box's MCP list).
#   - Never overwrites a key the user already set.
#   - Seeds once (tracked by $SB_ADDONS_DIR/antigravity/.defaults-applied): because agy removes keys that equal its own defaults when
#     saving /config or /statusline delete, re-seeding on every start would undo a user's choice. Deleting settings.json re-seeds it.
#   - Atomic write, mode 0600. A broken (non-JSON) settings.json is left untouched and reported on stderr (exit 1).
set -u

here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
statusline="$here/statusline.sh"
SB_LIB=${SWARMBOX_TEST_LIB:-/usr/local/lib/swarmbox}
# shellcheck source=/dev/null
. "$SB_LIB/dirs.sh" || { echo "antigravity prepare: cannot read $SB_LIB/dirs.sh" >&2; exit 2; }

command -v jq > /dev/null 2>&1 || { echo "antigravity prepare: jq not found" >&2; exit 2; }
[ -x "$statusline" ] || { echo "antigravity prepare: $statusline is missing or not executable" >&2; exit 2; }

cfg_dir="$HOME/.gemini/antigravity-cli"
settings="$cfg_dir/settings.json"
stamp_dir="$SB_ADDONS_DIR/antigravity"
stamp="$stamp_dir/.defaults-applied"

# sync_agy_mcp: the MCP servers of the box (<workspace>/.claude/mcp-servers.json, written by swarmbox-mcp before this runs) as an
# Antigravity plugin of SwarmBox's own, ~/.gemini/config/plugins/swarmbox/{plugin.json,mcp_config.json}: agy loads the MCP servers of
# every enabled plugin, the format is the same `mcpServers` map, and the user's own ~/.gemini/config/mcp_config.json is never touched.
# The user can turn it off like any plugin (`agy plugin disable swarmbox`). Rewritten at every start, so a server removed from the box
# goes away; a missing source writes nothing. Returns 1 when the source is not a usable MCP file (the plugin is left as it was).
sync_agy_mcp() {
    local src="$HOME/.claude/mcp-servers.json" dir="$HOME/.gemini/config/plugins/swarmbox" t
    [ -f "$src" ] || return 0
    if ! jq -e '(.mcpServers // {}) | type == "object"' "$src" > /dev/null 2>&1; then
        echo "antigravity prepare: $src is not a usable MCP file: the MCP servers are not given to agy" >&2
        return 1
    fi
    mkdir -p "$dir" || { echo "antigravity prepare: cannot create $dir" >&2; return 1; }
    t=$(mktemp "$dir/.plugin.json.XXXXXX") || return 1
    jq -n '{name: "swarmbox", version: "1.0.0", description: "The MCP servers of the SwarmBox (written by SwarmBox at every start)"}' > "$t" \
        && mv -f "$t" "$dir/plugin.json" || { rm -f "$t"; echo "antigravity prepare: cannot write $dir/plugin.json" >&2; return 1; }
    t=$(mktemp "$dir/.mcp_config.json.XXXXXX") || return 1
    chmod 600 "$t"
    jq '{mcpServers: (.mcpServers // {})}' "$src" > "$t" \
        && mv -f "$t" "$dir/mcp_config.json" || { rm -f "$t"; echo "antigravity prepare: cannot write $dir/mcp_config.json" >&2; return 1; }
    return 0
}
mcp_rc=0
sync_agy_mcp || mcp_rc=1

# Already seeded and the user's settings file still exists: leave their choices alone.
if [ -f "$stamp" ] && [ -f "$settings" ]; then
    exit "$mcp_rc"
fi

umask 077
mkdir -p "$cfg_dir" "$stamp_dir" || { echo "antigravity prepare: cannot create configuration folders" >&2; exit 1; }

tmp=$(mktemp "$cfg_dir/.settings.json.XXXXXX") || { echo "antigravity prepare: cannot create temporary file in $cfg_dir" >&2; exit 1; }
trap 'rm -f "$tmp"' EXIT
chmod 600 "$tmp"

defaults=$(jq -cn --arg cmd "$statusline" '{
    statusLine: { type: "command", command: $cmd },
    colorScheme: "tokyo night",
    showFeedbackSurvey: false,
    allowNonWorkspaceAccess: true
}') || { echo "antigravity prepare: failed to build default settings" >&2; exit 1; }

if [ -f "$settings" ]; then
    if ! jq -e 'type == "object"' "$settings" > /dev/null 2>&1; then
        echo "antigravity prepare: $settings is not a JSON object; leaving it untouched" >&2
        exit 1
    fi
    # Merge: user's existing keys always win ($defaults + .).
    jq --argjson defs "$defaults" '$defs + .' "$settings" > "$tmp" || {
        echo "antigravity prepare: failed to merge defaults into $settings" >&2
        exit 1
    }
else
    printf '%s\n' "$defaults" | jq '.' > "$tmp" || {
        echo "antigravity prepare: failed to format $settings" >&2
        exit 1
    }
fi

mv -f "$tmp" "$settings" || { echo "antigravity prepare: cannot write $settings" >&2; exit 1; }
: > "$stamp" 2> /dev/null || true
echo "antigravity prepare: configured defaults in $settings" >&2
exit "$mcp_rc"
