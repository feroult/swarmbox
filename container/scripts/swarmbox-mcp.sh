#!/bin/bash
# swarmbox-mcp: generate <workspace>/.claude/mcp-servers.json from the MCP registry, run by `serve` at step 7.
#
#   swarmbox-mcp [generate] [--output FILE]     default FILE: $HOME/.claude/mcp-servers.json (the workspace is $HOME in the box)
#
# Inputs: the image registry /etc/swarmbox/mcp/<name>/config.json and the user level $SB_CONFIG_DIR/mcp/<name>/config.json
# (<workspace>/.config/swarmbox/mcp/<name>/config.json). A server found in either is merged field by field (shallow: a user
# field replaces the image field of the same name). {"enabled": false} drops the server. When BROWSER_URL is not empty and the
# merged entry has browserUrlArgs, those replace args with ${BROWSER_URL} replaced by the value. `browserUrlArgs` and `enabled`
# are removed from the output. An entry without a string `command` is skipped.
#
# A bad file (not JSON, not an object, no command) gives one warning line on stderr and is skipped; the other servers are still
# written, and the exit status is 1 so that `serve` records one health line. The file is written atomically (a temporary file in
# the same folder, then mv): on failure (exit 2) the old file is untouched and no temporary file is left. Needs jq.
#
# Test-only variables: SWARMBOX_TEST_LIB (folder with dirs.sh), SWARMBOX_TEST_MCP_DIR (the image registry).
SB_LIB=${SWARMBOX_TEST_LIB:-/usr/local/lib/swarmbox}
# shellcheck source=/dev/null
. "$SB_LIB/dirs.sh" || { echo "swarmbox-mcp: cannot read $SB_LIB/dirs.sh" >&2; exit 2; }

IMAGE_DIR=${SWARMBOX_TEST_MCP_DIR:-/etc/swarmbox/mcp}
USER_DIR=$SB_CONFIG_DIR/mcp
OUT="$HOME/.claude/mcp-servers.json"

[ "${1:-}" = generate ] && shift
while [ $# -gt 0 ]; do
    case "$1" in
        --output) [ $# -ge 2 ] || { echo "swarmbox-mcp: --output needs a file" >&2; exit 2; }; OUT=$2; shift 2 ;;
        *) echo "usage: swarmbox-mcp [generate] [--output FILE]" >&2; exit 2 ;;
    esac
done
command -v jq > /dev/null 2>&1 || { echo "swarmbox-mcp: jq not found" >&2; exit 2; }

WARNED=0
warn() { echo "swarmbox-mcp: $*" >&2; WARNED=1; }

# names: the union of the server folders of both levels, sorted, hidden names left out
names=$(
    for d in "$IMAGE_DIR" "$USER_DIR"; do
        [ -d "$d" ] || continue
        for f in "$d"/*/config.json; do
            [ -f "$f" ] || continue
            n=${f%/config.json}; echo "${n##*/}"
        done
    done | LC_ALL=C sort -u
)

result='{}'
for name in $names; do
    files=()
    for f in "$IMAGE_DIR/$name/config.json" "$USER_DIR/$name/config.json"; do
        [ -f "$f" ] || continue
        if jq -e 'type == "object"' "$f" > /dev/null 2>&1; then
            files+=("$f")
        else
            warn "$f is not a JSON object: ignored"
        fi
    done
    [ ${#files[@]} -gt 0 ] || continue
    entry=$(jq -s -c --arg url "${BROWSER_URL:-}" '
        add
        | if .enabled == false then empty
          else (if $url != "" and (.browserUrlArgs | type) == "array"
                then .args = (.browserUrlArgs | map(split("${BROWSER_URL}") | join($url)))
                else . end)
               | del(.browserUrlArgs, .enabled)
          end' "${files[@]}") || { warn "could not read the configuration of server $name: skipped"; continue; }
    [ -n "$entry" ] || continue   # switched off
    if ! printf '%s' "$entry" | jq -e '.command | type == "string" and length > 0' > /dev/null 2>&1; then
        warn "server $name has no command: skipped"
        continue
    fi
    result=$(printf '%s' "$result" | jq -c --arg n "$name" --argjson e "$entry" '.[$n] = $e') || { warn "server $name: skipped"; continue; }
done

doc=$(printf '%s' "$result" | jq '{mcpServers: .}') || { echo "swarmbox-mcp: could not build the document" >&2; exit 2; }

dir=$(dirname -- "$OUT")
mkdir -p -- "$dir" 2> /dev/null || { echo "swarmbox-mcp: cannot create $dir" >&2; exit 2; }
tmp="$OUT.tmp.$$"
trap 'rm -f -- "$tmp"' EXIT
if ! printf '%s\n' "$doc" > "$tmp" 2> /dev/null || ! mv -f -- "$tmp" "$OUT" 2> /dev/null; then
    echo "swarmbox-mcp: cannot write $OUT" >&2
    exit 2
fi
[ "$WARNED" = 0 ] || exit 1
exit 0
