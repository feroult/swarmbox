#!/bin/bash
# Swarmbox initialization orchestrator
# Handles general setup and delegates to MCP-specific init scripts

SWARMBOX_DIR="$HOME/.swarmbox"
source /etc/swarmbox/scripts/messages.sh

# Helper: Build base MCP config (chrome-devtools only)
build_base_mcp_config() {
    if [ -n "$BROWSER_URL" ]; then
        jq -n --arg url "$BROWSER_URL" \
          '{mcpServers: {"chrome-devtools": {command: "npx", args: ["-y", "chrome-devtools-mcp@latest", ("--browserUrl=" + $url)]}}}' \
          > "$HOME/.claude/mcp-servers.json"
    else
        jq -n \
          --slurpfile chrome /etc/swarmbox/mcp/chrome-devtools/config.json \
          '{mcpServers: {"chrome-devtools": $chrome[0]}}' \
          > "$HOME/.claude/mcp-servers.json"
    fi
}

# Helper: Render OpenCode config for a local OpenAI-compatible LLM (llama.cpp + llama-swap on the podman host).
# Works with no env vars set; every LOCAL_LLM_* variable only overrides the default. Values are baked
# into the file so OpenCode needs no environment. Set LOCAL_LLM_URL="" to disable.
build_opencode_config() {
    local out="$SWARMBOX_DIR/opencode-local.json"
    local url="${LOCAL_LLM_URL-http://host.containers.internal:8000/v1}"
    if [ -z "$url" ]; then
        echo '{}' > "$out"
        return
    fi
    local model="${LOCAL_LLM_MODEL:-qwen3.6-35b-a3b-64k}"
    jq --arg m "$model" \
       --arg url "$url" \
       --arg key "${LOCAL_LLM_KEY:-sk-local}" \
       --argjson ctx "${LOCAL_LLM_CONTEXT:-65536}" \
       --argjson out "${LOCAL_LLM_OUTPUT:-8192}" \
       '.provider.local.options = {baseURL: $url, apiKey: $key}
        | .provider.local.models = {($m): {name: $m, limit: {context: $ctx, output: $out}}}
        | .model = ("local/" + $m)' \
       /etc/swarmbox/opencode/local-llm.json > "$out"
}

# Helper: Mirror the Claude Code MCP servers (~/.claude/mcp-servers.json) into the OpenCode config.
# Must run after every step that writes mcp-servers.json (base config and memory init).
sync_opencode_mcp() {
    local out="$SWARMBOX_DIR/opencode-local.json"
    local src="$HOME/.claude/mcp-servers.json"
    [ -f "$src" ] || return
    jq --slurpfile src "$src" \
       '.mcp = ($src[0].mcpServers | with_entries(.value = ({
            type: "local",
            command: ([.value.command] + (.value.args // [])),
            enabled: true
        } + (if .value.env then {environment: .value.env} else {} end))))' \
       "$out" > "$out.tmp" && mv "$out.tmp" "$out"
}

msg_blank
msg "Initializing swarmbox..."

# 1. Create base directories
mkdir -p "$SWARMBOX_DIR" "$HOME/.claude"

# 2. Settings live under .swarmbox (the home is a bind mount); Claude Code finds them through a symlink
if [ ! -f "$SWARMBOX_DIR/settings.json" ]; then
    echo '{}' > "$SWARMBOX_DIR/settings.json"
fi
if [ ! -L "$HOME/.claude/settings.json" ]; then
    ln -sf "$SWARMBOX_DIR/settings.json" "$HOME/.claude/settings.json"
fi

# 3. Build base MCP config (chrome-devtools only)
build_base_mcp_config
msg_detail "MCP servers configured"

# 3b. Render OpenCode config (local LLM by default)
build_opencode_config
msg_detail "OpenCode local LLM: $(jq -r '.model // "disabled"' "$SWARMBOX_DIR/opencode-local.json")"

# 4. Mirror MCP servers into OpenCode
sync_opencode_mcp
msg_blank

# 5. Nested Podman API service (host reaches it via `podman -c <container-name>`)
/usr/local/bin/swarmbox-podman-service

# 6. Web terminal (only when the container was created with --web)
/usr/local/bin/swarmbox-web-terminal

msg "Type 'claude' for Claude Code or 'gemini' for Gemini CLI"
msg_blank
