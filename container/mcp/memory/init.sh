#!/bin/bash
# Memory MCP initialization
# Called from main init.sh when MEMORY environment variable is set

DB_NAME="${1}.db"
SQLITE_PATH="/home/agent/.swarmbox/memory/$DB_NAME"
MCP_DIR="/etc/swarmbox/mcp/memory"
source /etc/swarmbox/scripts/messages.sh

msg_blank
msg "Configuring memory service..."

# 1. Setup hooks configuration
cp "$MCP_DIR/hooks-config.json" "$HOME/.claude/hooks/config.json"

# 2. Install memory sub-agent
mkdir -p "$HOME/.claude/agents"
cp "$MCP_DIR/agent.md" "$HOME/.claude/agents/memory.md"
msg_detail "Memory sub-agent installed"

# 3. Build and merge memory MCP config into existing mcp-servers.json
jq -n \
   --slurpfile chrome /etc/swarmbox/mcp/chrome-devtools/config.json \
   --slurpfile memory "$MCP_DIR/config.json" \
   --arg sqlite_path "$SQLITE_PATH" \
   '{mcpServers: {
     "chrome-devtools": $chrome[0],
     "memory": ($memory[0] | .env."MCP_MEMORY_SQLITE_PATH" = $sqlite_path)
   }}' \
   > "$HOME/.claude/mcp-servers.json"

msg_detail "Database: $DB_NAME"

# 4. Start HTTP server for web dashboard if not already running
if ! pgrep -f "uvicorn.*mcp_memory_service.web.app" > /dev/null 2>&1; then
    cd /opt/flow && \
    MCP_OAUTH_ENABLED=false \
    MCP_MEMORY_STORAGE_BACKEND=sqlite_vec \
    MCP_MEMORY_SQLITE_PATH="$SQLITE_PATH" \
    MCP_MEMORY_SQLITE_PRAGMAS="journal_mode=WAL,busy_timeout=30000,cache_size=20000,synchronous=NORMAL" \
    nohup /opt/flow/bin/uvicorn mcp_memory_service.web.app:app \
        --host 0.0.0.0 --port 8889 > /tmp/mcp-http-server.log 2>&1 &

    # Wait a moment to ensure it starts
    sleep 2
    if pgrep -f "uvicorn.*mcp_memory_service.web.app" > /dev/null 2>&1; then
        msg_detail "Dashboard: http://localhost:8889"
    else
        msg_detail "Dashboard failed to start (check /tmp/mcp-http-server.log)"
    fi
fi

msg_blank
