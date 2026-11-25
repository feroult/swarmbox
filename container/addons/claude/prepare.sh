#!/bin/bash
# Claude Code prepare.sh: run by `swarmbox-addon prepare` (serve step 7 and right after `swarmbox-addon install claude`).
# Seeds SwarmBox's opinionated default in ~/.claude/settings.json: the status line of the box (swarmbox-statusline: folder, branch, model,
# context bar and usage limits).
#
# Rules:
#   - Isolated to the claude addon: never touches another agent.
#   - Never overwrites a key the user already set (their own statusLine wins).
#   - Seeds once (tracked by $SB_ADDONS_DIR/claude/.defaults-applied), so a user who removes the status line keeps it removed. Deleting
#     settings.json, or the stamp, seeds it again.
#   - Atomic write, mode 0600. A broken (non-JSON) settings.json is left untouched and reported on stderr (exit 1).
set -u

SB_LIB=${SWARMBOX_TEST_LIB:-/usr/local/lib/swarmbox}
# shellcheck source=/dev/null
. "$SB_LIB/dirs.sh" || { echo "claude prepare: cannot read $SB_LIB/dirs.sh" >&2; exit 2; }

command -v jq > /dev/null 2>&1 || { echo "claude prepare: jq not found" >&2; exit 2; }

cfg_dir="$HOME/.claude"
settings="$cfg_dir/settings.json"
stamp_dir="$SB_ADDONS_DIR/claude"
stamp="$stamp_dir/.defaults-applied"

if [ -f "$stamp" ] && [ -f "$settings" ]; then
    exit 0
fi

umask 077
mkdir -p "$cfg_dir" "$stamp_dir" || { echo "claude prepare: cannot create configuration folders" >&2; exit 1; }

tmp=$(mktemp "$cfg_dir/.settings.json.XXXXXX") || { echo "claude prepare: cannot create temporary file in $cfg_dir" >&2; exit 1; }
trap 'rm -f "$tmp"' EXIT
chmod 600 "$tmp"

defaults='{"statusLine": {"type": "command", "command": "swarmbox-statusline"}}'

if [ -f "$settings" ]; then
    if ! jq -e 'type == "object"' "$settings" > /dev/null 2>&1; then
        echo "claude prepare: $settings is not a JSON object; leaving it untouched" >&2
        exit 1
    fi
    # Merge: the user's existing keys always win ($defaults + .).
    jq --argjson defs "$defaults" '$defs + .' "$settings" > "$tmp" || {
        echo "claude prepare: failed to merge defaults into $settings" >&2
        exit 1
    }
else
    printf '%s\n' "$defaults" | jq '.' > "$tmp" || { echo "claude prepare: failed to format $settings" >&2; exit 1; }
fi

mv -f "$tmp" "$settings" || { echo "claude prepare: cannot write $settings" >&2; exit 1; }
: > "$stamp" 2> /dev/null || true
echo "claude prepare: configured the status line in $settings" >&2
exit 0
