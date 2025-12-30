#!/bin/bash
# Swarmbox initialization orchestrator
# Handles general setup and delegates to MCP-specific init scripts

SWARMBOX_DIR="$HOME/.swarmbox"

# Helper: Build base MCP config (chrome-devtools only)
build_base_mcp_config() {
    jq -n \
      --slurpfile chrome /etc/swarmbox/mcp/chrome-devtools/config.json \
      '{mcpServers: {"chrome-devtools": $chrome[0]}}' \
      > "$HOME/.claude/mcp-servers.json"
}

# 1. Create base directories
mkdir -p "$SWARMBOX_DIR/memory"
mkdir -p "$HOME/.claude/hooks"

# 2. Copy framework hooks to .claude/hooks if they don't exist
if [ ! -d "$HOME/.claude/hooks/core" ]; then
    cp -r /etc/swarmbox/claude-hooks/* "$HOME/.claude/hooks/"
    chmod +x "$HOME/.claude/hooks"/*.sh 2>/dev/null || true
    echo "Installed mcp-memory-service framework hooks"
fi

# 3. Create symlink for Claude Code to find settings
mkdir -p "$HOME/.claude"
if [ ! -L "$HOME/.claude/settings.json" ]; then
    ln -sf "$SWARMBOX_DIR/settings.json" "$HOME/.claude/settings.json"
fi

# 4. Build base MCP config (chrome-devtools only)
build_base_mcp_config

# 5. Initialize memory MCP if MEMORY environment variable is set
if [ -n "$MEMORY" ]; then
    /etc/swarmbox/mcp/memory/init.sh "$MEMORY"
else
    # Create empty settings.json when MEMORY is not set
    if [ ! -f "$SWARMBOX_DIR/settings.json" ]; then
        echo '{}' > "$SWARMBOX_DIR/settings.json"
    fi
fi
