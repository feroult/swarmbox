FROM node:20-slim

# Accept build arguments for user UID/GID
ARG USER_UID=1000
ARG USER_GID=1000
ARG HOST_OS=linux

# Install system dependencies
RUN apt-get update && apt-get install -y \
    git \
    curl \
    wget \
    python3 \
    python3-pip \
    python3-venv \
    build-essential \
    unzip \
    sudo \
    vim \
    nano \
    procps \
    net-tools \
    netcat-openbsd \
    iputils-ping \
    dnsutils \
    htop \
    tree \
    jq \
    zip \
    tar \
    gzip \
    bzip2 \
    xz-utils \
    ca-certificates \
    gnupg \
    lsb-release \
    software-properties-common \
    apt-transport-https \
    openssh-client \
    rsync \
    file \
    less \
    man-db \
    bash-completion \
    sqlite3 \
    pandoc \
    && rm -rf /var/lib/apt/lists/*

# Install Podman CLI (for accessing host Podman daemon via socket)
# Podman is available in default Debian 12 repositories
RUN apt-get update && \
    apt-get install -y podman && \
    rm -rf /var/lib/apt/lists/*

# Create directory for Podman socket
RUN mkdir -p /run/podman && chmod 755 /run/podman

# Configure Podman to use proper Podman socket path
# CONTAINER_HOST tells Podman CLI where to find the socket
# This will be set by start.sh when --with-unsafe-podman is used
ENV CONTAINER_HOST=unix:///run/podman/podman.sock

# Install Poetry system-wide
ENV POETRY_HOME=/opt/poetry
RUN curl -sSL https://install.python-poetry.org | python3 - && \
    ln -s /opt/poetry/bin/poetry /usr/local/bin/poetry && \
    chmod -R a+rx /opt/poetry

# Install uv (fast Python package installer and manager) system-wide
RUN curl -LsSf https://astral.sh/uv/install.sh | UV_INSTALL_DIR=/usr/local/bin sh

# Create a system-wide Python virtual environment
RUN python3 -m venv /opt/flow && \
    /opt/flow/bin/pip install --upgrade pip

# Clone and install mcp-memory-service from fork with fix
RUN git clone https://github.com/feroult/mcp-memory-service.git /tmp/mcp-memory-service && \
    cd /tmp/mcp-memory-service && \
    /opt/flow/bin/pip install python-docx . && \
    rm -rf /tmp/mcp-memory-service

# Install Chromium
RUN apt-get update && \
    apt-get install -y chromium && \
    rm -rf /var/lib/apt/lists/*

# Create app directory
WORKDIR /app

# Create a non-root user with sudo privileges using dynamic UID/GID
# First check if the UID already exists
RUN if id -u ${USER_UID} >/dev/null 2>&1; then \
        # UID exists, rename existing user to agent
        existing_user=$(id -nu ${USER_UID}) && \
        existing_group=$(id -gn ${USER_GID} 2>/dev/null || id -gn ${USER_UID}) && \
        if [ "$existing_user" != "agent" ]; then \
            usermod -l agent "$existing_user" && \
            groupmod -n agent "$existing_group" 2>/dev/null || true; \
        fi && \
        usermod -d /home/agent -m agent && \
        usermod -s /bin/bash agent && \
        echo "agent ALL=(ALL) NOPASSWD: ALL" >> /etc/sudoers; \
    else \
        # UID doesn't exist, create agent with specified UID/GID
        groupadd -g ${USER_GID} agent && \
        useradd -m -s /bin/bash -u ${USER_UID} -g ${USER_GID} agent && \
        echo "agent ALL=(ALL) NOPASSWD: ALL" >> /etc/sudoers; \
    fi

# Add agent to root group for Podman socket access (socket is owned by root:root in rootful mode)
RUN usermod -aG root agent

# Set npm cache directory to a non-mounted location
ENV NPM_CONFIG_CACHE=/opt/npm-cache

# Set Anthropic model
ENV ANTHROPIC_MODEL=sonnet

# Disable browser auto-opening for Vite and other dev servers
ENV BROWSER=none

# Chromium/Puppeteer environment variables for Docker
ENV CHROME_BIN=/usr/bin/chromium
ENV PUPPETEER_SKIP_CHROMIUM_DOWNLOAD=true
ENV PUPPETEER_EXECUTABLE_PATH=/usr/bin/chromium

# Install Claude Code globally via npm (avoids native binary warnings)
RUN npm install -g @anthropic-ai/claude-code

# Install Gemini CLI globally via npm
RUN npm install -g @google/gemini-cli

# Disable Claude Code auto-updates (Docker containers should be rebuilt for updates)
ENV DISABLE_AUTOUPDATER=true

# Add ~/.local/bin to PATH for all users (prevents Claude warning)
RUN echo "" >> /etc/bash.bashrc && \
    echo "# Add ~/.local/bin to PATH" >> /etc/bash.bashrc && \
    echo 'export PATH="$HOME/.local/bin:$PATH"' >> /etc/bash.bashrc

# Enable colors for ls and other commands
RUN echo "# Enable colors for common commands" >> /etc/bash.bashrc && \
    echo "export LS_COLORS='rs=0:di=1;34:ln=1;36:mh=00:pi=40;33:so=1;35:do=1;35:bd=40;33;1:cd=40;33;1:or=40;31;1:mi=00:su=37;41:sg=30;43:ca=30;41:tw=30;42:ow=34;42:st=37;44:ex=1;32:'" >> /etc/bash.bashrc && \
    echo "alias ls='ls --color=auto'" >> /etc/bash.bashrc && \
    echo "alias ll='ls -alF --color=auto'" >> /etc/bash.bashrc && \
    echo "alias la='ls -A --color=auto'" >> /etc/bash.bashrc && \
    echo "alias l='ls -CF --color=auto'" >> /etc/bash.bashrc && \
    echo "alias grep='grep --color=auto'" >> /etc/bash.bashrc && \
    echo "alias fgrep='fgrep --color=auto'" >> /etc/bash.bashrc && \
    echo "alias egrep='egrep --color=auto'" >> /etc/bash.bashrc && \
    echo "" >> /etc/bash.bashrc && \
    echo "# Alias to run claude CLI and dangerously skip permissions (hidden, backward compatibility)" >> /etc/bash.bashrc && \
    echo "alias yolo='claude --dangerously-skip-permissions --mcp-config ~/.claude/mcp-servers.json'" >> /etc/bash.bashrc && \
    echo "" >> /etc/bash.bashrc && \
    echo "# Main claude alias with auto-approve (same as yolo)" >> /etc/bash.bashrc && \
    echo "alias claude='claude --dangerously-skip-permissions --mcp-config ~/.claude/mcp-servers.json'" >> /etc/bash.bashrc && \
    echo "" >> /etc/bash.bashrc && \
    echo "# Alias to run gemini CLI with yolo mode (bypass all approvals)" >> /etc/bash.bashrc && \
    echo "alias gemini='/usr/local/bin/gemini --yolo'" >> /etc/bash.bashrc && \
    echo "" >> /etc/bash.bashrc && \
    echo "# UUID function" >> /etc/bash.bashrc && \
    echo 'uuid() { python3 -c "import sys, uuid; print(uuid.uuid5(uuid.NAMESPACE_DNS, sys.argv[1]))" "$1"; }' >> /etc/bash.bashrc



# Create global MCP configuration file (base config without memory)
RUN mkdir -p /etc/claude && \
    echo '{\n\
  "mcpServers": {\n\
    "chrome-devtools": {\n\
      "command": "npx",\n\
      "args": [\n\
        "-y",\n\
        "chrome-devtools-mcp@latest",\n\
        "--executablePath=/usr/bin/chromium",\n\
        "--headless",\n\
        "--chromeArg=--no-sandbox",\n\
        "--chromeArg=--disable-setuid-sandbox",\n\
        "--chromeArg=--disable-dev-shm-usage",\n\
        "--chromeArg=--disable-gpu"\n\
      ]\n\
    }\n\
  }\n\
}' > /etc/claude/mcp-servers-base.json

# Add Claude wrapper to always use MCP config
RUN echo '#!/bin/bash\n\
/usr/local/bin/claude --mcp-config ~/.claude/mcp-servers.json "$@"' > /usr/local/bin/claude-mcp && \
    chmod +x /usr/local/bin/claude-mcp

# Update the yolo alias to include MCP config (done in global aliases section above)
# RUN sed -i 's|alias yolo=.*|alias yolo="/usr/local/bin/claude --dangerously-skip-permissions --mcp-config /etc/claude/mcp-servers.json"|' /etc/bash.bashrc

# Activate Python virtual environment by default for all users
RUN echo "" >> /etc/bash.bashrc && \
    echo "# Activate Python virtual environment" >> /etc/bash.bashrc && \
    echo "source /opt/flow/bin/activate" >> /etc/bash.bashrc

# Add welcome banner for interactive shells with BBS-style ANSI art
RUN echo "" >> /etc/bash.bashrc && \
    echo "# Display welcome banner for interactive shells" >> /etc/bash.bashrc && \
    echo "if [[ \$- == *i* ]]; then" >> /etc/bash.bashrc && \
    echo "  /usr/local/bin/banner.sh" >> /etc/bash.bashrc && \
    echo "fi" >> /etc/bash.bashrc

# Create /etc/swarmbox/ structure with hook templates (won't be overwritten by volume mount)
RUN mkdir -p /etc/swarmbox/hooks && \
    echo '#!/usr/bin/env python3\n\
import json\n\
import sys\n\
\n\
# SessionStart hook: Automatically inject memory awareness at session start\n\
try:\n\
    input_data = json.load(sys.stdin)\n\
except json.JSONDecodeError:\n\
    sys.exit(0)\n\
\n\
# Create context message to inject memory awareness\n\
context = """\n\
Memory system active. Your memories are automatically loaded.\n\
\n\
Available memory tools:\n\
- mcp__memory__store_memory: Save important context, decisions, and learnings\n\
- mcp__memory__recall_memory: Search and retrieve relevant past memories\n\
- Use memories to maintain continuity across sessions\n\
\n\
Remember to consolidate key findings at the end of this session.\n\
"""\n\
\n\
output = {\n\
    "hookSpecificOutput": {\n\
        "hookEventName": "SessionStart",\n\
        "additionalContext": context\n\
    }\n\
}\n\
\n\
print(json.dumps(output))\n\
sys.exit(0)' > /etc/swarmbox/hooks/session-start.py && \
    chmod +x /etc/swarmbox/hooks/session-start.py && \
    echo '#!/usr/bin/env python3\n\
import json\n\
import sys\n\
import os\n\
from datetime import datetime\n\
\n\
# SessionEnd hook: Log session end\n\
try:\n\
    input_data = json.load(sys.stdin)\n\
except json.JSONDecodeError:\n\
    sys.exit(0)\n\
\n\
# Log session end\n\
log_file = os.path.expanduser("~/.swarmbox/session-history.log")\n\
os.makedirs(os.path.dirname(log_file), exist_ok=True)\n\
\n\
with open(log_file, "a") as f:\n\
    timestamp = datetime.now().isoformat()\n\
    f.write(f"{timestamp} - Session ended\\n")\n\
\n\
output = {\n\
    "hookSpecificOutput": {\n\
        "hookEventName": "SessionEnd"\n\
    }\n\
}\n\
\n\
print(json.dumps(output))\n\
sys.exit(0)' > /etc/swarmbox/hooks/session-end.py && \
    chmod +x /etc/swarmbox/hooks/session-end.py


# Create initialization script for .swarmbox setup (runs at container start)
RUN echo '#!/bin/bash\n\
# Initialize .swarmbox directory structure at runtime\n\
SWARMBOX_DIR="$HOME/.swarmbox"\n\
\n\
# Create directory structure\n\
mkdir -p "$SWARMBOX_DIR"/{hooks,memory}\n\
\n\
# Copy hook scripts if they don'"'"'t exist\n\
if [ ! -f "$SWARMBOX_DIR/hooks/session-start.py" ]; then\n\
    cp /etc/swarmbox/hooks/session-start.py "$SWARMBOX_DIR/hooks/"\n\
    chmod +x "$SWARMBOX_DIR/hooks/session-start.py"\n\
fi\n\
\n\
if [ ! -f "$SWARMBOX_DIR/hooks/session-end.py" ]; then\n\
    cp /etc/swarmbox/hooks/session-end.py "$SWARMBOX_DIR/hooks/"\n\
    chmod +x "$SWARMBOX_DIR/hooks/session-end.py"\n\
fi\n\
\n\
# Create settings.json if it doesn'"'"'t exist\n\
if [ ! -f "$SWARMBOX_DIR/settings.json" ]; then\n\
    # Only configure hooks if MEMORY is set\n\
    if [ -n "$MEMORY" ]; then\n\
        # Create settings.json with memory hooks\n\
        cat > "$SWARMBOX_DIR/settings.json" << 'EOF'\n\
{\n\
  "hooks": {\n\
    "SessionStart": [\n\
      {\n\
        "hooks": [\n\
          {\n\
            "type": "command",\n\
            "command": "/usr/bin/python3 /home/agent/.swarmbox/hooks/session-start.py"\n\
          }\n\
        ]\n\
      }\n\
    ],\n\
    "SessionEnd": [\n\
      {\n\
        "hooks": [\n\
          {\n\
            "type": "command",\n\
            "command": "/usr/bin/python3 /home/agent/.swarmbox/hooks/session-end.py"\n\
          }\n\
        ]\n\
      }\n\
    ]\n\
  }\n\
}\n\
EOF\n\
    else\n\
        # Create empty settings.json when MEMORY is not set\n\
        echo '{}' > "$SWARMBOX_DIR/settings.json"\n\
    fi\n\
fi\n\
\n\
# Create symlink for Claude Code to find settings\n\
mkdir -p "$HOME/.claude"\n\
if [ ! -L "$HOME/.claude/settings.json" ]; then\n\
    ln -sf "$SWARMBOX_DIR/settings.json" "$HOME/.claude/settings.json"\n\
fi\n\
\n\
# Configure MCP servers based on MEMORY environment variable\n\
if [ -n "$MEMORY" ]; then\n\
    # MEMORY is set - create MCP config with memory service\n\
    DB_NAME="${MEMORY}.db"\n\
    cat > "$HOME/.claude/mcp-servers.json" <<EOF\n\
{\n\
  "mcpServers": {\n\
    "chrome-devtools": {\n\
      "command": "npx",\n\
      "args": [\n\
        "-y",\n\
        "chrome-devtools-mcp@latest",\n\
        "--executablePath=/usr/bin/chromium",\n\
        "--headless",\n\
        "--chromeArg=--no-sandbox",\n\
        "--chromeArg=--disable-setuid-sandbox",\n\
        "--chromeArg=--disable-dev-shm-usage",\n\
        "--chromeArg=--disable-gpu"\n\
      ]\n\
    },\n\
    "memory": {\n\
      "command": "/opt/flow/bin/python",\n\
      "args": ["-m", "mcp_memory_service.server"],\n\
      "env": {\n\
        "MCP_MEMORY_STORAGE_BACKEND": "sqlite_vec",\n\
        "MCP_MEMORY_SQLITE_PATH": "/home/agent/.swarmbox/memory/$DB_NAME",\n\
        "MCP_MEMORY_SQLITE_PRAGMAS": "busy_timeout=15000,cache_size=20000",\n\
        "MCP_MEMORY_HTTP_AUTO_START": "true",\n\
        "MCP_HTTP_PORT": "8338",\n\
        "MCP_HTTP_HOST": "0.0.0.0",\n\
        "MCP_OAUTH_ENABLED": "false"\n\
      }\n\
    }\n\
  }\n\
}\n\
EOF\n\
    echo "Memory enabled: Using database $DB_NAME"\n\
    \n\
    # Start HTTP server for web dashboard if not already running\n\
    if ! pgrep -f "uvicorn.*mcp_memory_service.web.app" > /dev/null 2>&1; then\n\
        echo "Starting memory web dashboard on port 8338..."\n\
        cd /opt/flow && MCP_OAUTH_ENABLED=false MCP_MEMORY_STORAGE_BACKEND=sqlite_vec MCP_MEMORY_SQLITE_PATH="/home/agent/.swarmbox/memory/$DB_NAME" nohup /opt/flow/bin/uvicorn mcp_memory_service.web.app:app --host 0.0.0.0 --port 8338 > /tmp/mcp-http-server.log 2>&1 &\n\
        # Wait a moment to ensure it starts\n\
        sleep 2\n\
        if pgrep -f "uvicorn.*mcp_memory_service.web.app" > /dev/null 2>&1; then\n\
            echo "Web dashboard started at http://localhost:8338"\n\
        else\n\
            echo "Warning: Web dashboard failed to start. Check /tmp/mcp-http-server.log"\n\
        fi\n\
    fi\n\
else\n\
    # MEMORY is not set - create MCP config without memory service\n\
    cp /etc/claude/mcp-servers-base.json "$HOME/.claude/mcp-servers.json"\n\
fi' > /usr/local/bin/init-swarmbox.sh && \
    chmod +x /usr/local/bin/init-swarmbox.sh

# Add initialization to bashrc (runs for interactive shells)
RUN echo "" >> /etc/bash.bashrc && \
    echo "# Initialize .swarmbox directory structure" >> /etc/bash.bashrc && \
    echo "/usr/local/bin/init-swarmbox.sh 2>/dev/null" >> /etc/bash.bashrc

# Create cache directories and set permissions for agent user
RUN if [ "${HOST_OS}" = "darwin" ]; then \
        mkdir -p /opt/npm-cache /workspace && \
        chmod -R 777 /opt/npm-cache /opt/flow /workspace; \
    else \
        mkdir -p /opt/npm-cache /workspace && \
        chown -R ${USER_UID}:${USER_GID} /opt/npm-cache /opt/flow /workspace && \
        chmod -R 755 /opt/npm-cache /opt/flow /workspace; \
    fi

# Copy banner script (at the end to optimize build cache)
COPY banner.sh /usr/local/bin/banner.sh
RUN chmod +x /usr/local/bin/banner.sh

# Expose HTTP port for MCP memory service web dashboard
EXPOSE 8338

# Switch to non-root user
USER agent

# Set working directory to user home
WORKDIR /home/agent

# Keep container running
CMD ["tail", "-f", "/dev/null"]