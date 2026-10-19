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
    local model="${LOCAL_LLM_MODEL:-qwen3.8-27b}"
    jq --arg m "$model" \
       --arg url "$url" \
       --arg key "${LOCAL_LLM_KEY:-sk-local}" \
       --argjson ctx "${LOCAL_LLM_CONTEXT:-24576}" \
       --argjson out "${LOCAL_LLM_OUTPUT:-6144}" \
       '.provider.local.options = {baseURL: $url, apiKey: $key}
        | .provider.local.models = {($m): {name: $m, limit: {context: $ctx, output: $out}}}
        | .model = ("local/" + $m)' \
       /etc/swarmbox/opencode/local-llm.json > "$out"
}

msg_blank
msg "Initializing swarmbox..."

# 1. Create base directories
mkdir -p "$SWARMBOX_DIR/memory"
mkdir -p "$HOME/.claude/hooks"

# 2. Copy framework hooks to .claude/hooks if they don't exist
if [ ! -d "$HOME/.claude/hooks/core" ]; then
    cp -r /etc/swarmbox/claude-hooks/* "$HOME/.claude/hooks/"
    chmod +x "$HOME/.claude/hooks"/*.sh 2>/dev/null || true
    msg_detail "Framework hooks installed"
fi

# 3. Create symlink for Claude Code to find settings
mkdir -p "$HOME/.claude"
if [ ! -L "$HOME/.claude/settings.json" ]; then
    ln -sf "$SWARMBOX_DIR/settings.json" "$HOME/.claude/settings.json"
fi

# 4. Build base MCP config (chrome-devtools only)
build_base_mcp_config
msg_detail "MCP servers configured"

# 4b. Render OpenCode config (local LLM by default)
build_opencode_config
msg_detail "OpenCode local LLM: $(jq -r '.model // "disabled"' "$SWARMBOX_DIR/opencode-local.json")"

# 5. Initialize memory MCP if MEMORY environment variable is set
if [ -n "$MEMORY" ]; then
    /etc/swarmbox/mcp/memory/init.sh "$MEMORY"
else
    # Create empty settings.json when MEMORY is not set
    if [ ! -f "$SWARMBOX_DIR/settings.json" ]; then
        echo '{}' > "$SWARMBOX_DIR/settings.json"
    fi
    msg_blank
fi

msg "Type 'claude' for Claude Code or 'gemini' for Gemini CLI"
msg_blank
