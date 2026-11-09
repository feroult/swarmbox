#!/bin/bash
# OpenCode prepare.sh (design 6.6, 4.4): run by `swarmbox-tool prepare` (serve step 7, after the MCP file is written) and after an install.
# Renders box:/tmp/swarmbox/opencode.json: the local-LLM provider from LOCAL_LLM_* (off unless LOCAL_LLM_URL is set), then the MCP mirror
# of <workspace>/.claude/mcp-servers.json. Writes only that file (mode 600: it can hold the key), atomically, and is idempotent.
#
#   LOCAL_LLM_URL      base URL of an OpenAI-compatible server (unset or empty: no local provider)
#   LOCAL_LLM_MODEL    model name (required when the URL is set; there is no default any more, design 7.2)
#   LOCAL_LLM_KEY      API key (default sk-local, a dummy: the provider type wants one)
#   LOCAL_LLM_CONTEXT  context window in tokens (default 65536)    LOCAL_LLM_OUTPUT  output limit (default 8192)
#
# Exit 0, or 1 when something was wrong (a missing model, a bad number, an unreadable MCP file): the file is still written, without the
# part that failed, and one line on stderr says what. Test-only variables: SWARMBOX_TEST_LIB (folder with dirs.sh), SWARMBOX_TEST_RUN_DIR.
set -u
here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
SB_LIB=${SWARMBOX_TEST_LIB:-/usr/local/lib/swarmbox}
# shellcheck source=/dev/null
. "$SB_LIB/dirs.sh" || { echo "opencode prepare: cannot read $SB_LIB/dirs.sh" >&2; exit 2; }
run_dir=${SWARMBOX_TEST_RUN_DIR:-$SB_RUN_DIR}
out="$run_dir/opencode.json"
template="$here/local-llm.json"
rc=0

command -v jq >/dev/null 2>&1 || { echo "opencode prepare: jq not found" >&2; exit 2; }
[ -f "$template" ] || { echo "opencode prepare: the template $template is missing" >&2; exit 2; }
mkdir -p "$run_dir" || { echo "opencode prepare: cannot create $run_dir" >&2; exit 2; }
tmp=$(mktemp "$run_dir/.opencode.json.XXXXXX") || { echo "opencode prepare: cannot create a temporary file in $run_dir" >&2; exit 2; }
trap 'rm -f "$tmp" "$tmp.2"' EXIT
chmod 600 "$tmp"

# build_opencode_config: the template with the local provider filled in, or removed when it is off or wrong.
build_opencode_config() {
    local url=${LOCAL_LLM_URL:-} model=${LOCAL_LLM_MODEL:-} ctx=${LOCAL_LLM_CONTEXT:-65536} outp=${LOCAL_LLM_OUTPUT:-8192}
    local off='del(.provider.local) | if (.provider // {}) == {} then del(.provider) else . end'
    if [ -n "$url" ]; then
        if [ -z "$model" ]; then
            echo "opencode prepare: LOCAL_LLM_URL is set but LOCAL_LLM_MODEL is not: the local provider is left out" >&2
            rc=1
            url=
        elif [[ ! "$ctx" =~ ^[0-9]+$ || ! "$outp" =~ ^[0-9]+$ ]]; then
            echo "opencode prepare: LOCAL_LLM_CONTEXT and LOCAL_LLM_OUTPUT must be whole numbers: the local provider is left out" >&2
            rc=1
            url=
        fi
    fi
    if [ -z "$url" ]; then
        jq "$off" "$template" > "$tmp"
        return
    fi
    jq --arg m "$model" --arg url "$url" --arg key "${LOCAL_LLM_KEY:-sk-local}" --argjson ctx "$ctx" --argjson out "$outp" \
       '.provider.local.options = {baseURL: $url, apiKey: $key}
        | .provider.local.models = {($m): {name: $m, limit: {context: $ctx, output: $out}}}
        | .model = ("local/" + $m)' "$template" > "$tmp"
}

# sync_opencode_mcp: the mapping (design 4.4): each server s becomes
#   {type: "local", command: [s.command] + s.args, enabled: true} plus environment: s.env when s has env.
sync_opencode_mcp() {
    local src="$HOME/.claude/mcp-servers.json"
    [ -f "$src" ] || return 0
    if jq --slurpfile src "$src" \
        '.mcp = (($src[0].mcpServers // {}) | with_entries(.value = ({
            type: "local",
            command: ([.value.command] + (.value.args // [])),
            enabled: true
        } + (if .value.env then {environment: .value.env} else {} end))))' "$tmp" > "$tmp.2" 2>/dev/null; then
        mv -f "$tmp.2" "$tmp"
    else
        echo "opencode prepare: $src is not a usable MCP file: the MCP servers are not mirrored" >&2
        rc=1
    fi
}

build_opencode_config || { echo "opencode prepare: rendering the configuration failed" >&2; exit 2; }
sync_opencode_mcp
mv -f "$tmp" "$out" || { echo "opencode prepare: cannot write $out" >&2; exit 2; }
echo "opencode prepare: wrote $out ($(jq -r '.model // "local LLM off"' "$out"))" >&2
exit "$rc"
