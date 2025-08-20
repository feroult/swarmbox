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
    # Playwright browser dependencies
    libnss3 \
    libnspr4 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libatspi2.0-0 \
    libx11-6 \
    libxcomposite1 \
    libxdamage1 \
    libxext6 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libxcb1 \
    libxkbcommon0 \
    libgtk-3-0 \
    libpango-1.0-0 \
    libcairo2 \
    libgdk-pixbuf2.0-0 \
    libasound2 \
    libdrm2 \
    libxss1 \
    libxtst6 \
    fonts-liberation \
    xdg-utils \
    && rm -rf /var/lib/apt/lists/*

# Create a system-wide Python virtual environment
RUN python3 -m venv /opt/swarmbox && \
    /opt/swarmbox/bin/pip install --upgrade pip && \
    /opt/swarmbox/bin/pip install python-docx

# Install Docker CLI
RUN curl -fsSL https://download.docker.com/linux/debian/gpg | gpg --dearmor -o /usr/share/keyrings/docker-archive-keyring.gpg && \
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/docker-archive-keyring.gpg] https://download.docker.com/linux/debian $(lsb_release -cs) stable" | tee /etc/apt/sources.list.d/docker.list > /dev/null && \
    apt-get update && \
    apt-get install -y docker-ce-cli && \
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

# Set npm cache directory to a non-mounted location
ENV NPM_CONFIG_CACHE=/opt/npm-cache

# Set Anthropic model
ENV ANTHROPIC_MODEL=sonnet

# Set Playwright environment variables to a non-mounted location
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/playwright-cache
ENV PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=0

# Disable browser auto-opening for Vite and other dev servers
ENV BROWSER=none

# Disable browser sandboxing for container environments (especially Podman)
ENV PLAYWRIGHT_CHROMIUM_ARGS="--no-sandbox --disable-setuid-sandbox --disable-dev-shm-usage"

# Install Claude Code globally as root (latest version)
RUN curl -fsSL http://claude.ai/install.sh | bash && \
    # Copy Claude from the expected location to system path
    cp /root/.local/bin/claude /usr/local/bin/claude && \
    chmod +x /usr/local/bin/claude

# Install claude-flow globally with @alpha version
RUN npm install -g claude-flow@alpha

# Install Playwright and MCP server globally
RUN npm install -g playwright @playwright/test @playwright/mcp@latest

# Add global aliases for all users
RUN echo "# Alias for claude-flow to initialize a project" >> /etc/bash.bashrc && \
    echo "alias flow_init='npx --y claude-flow@alpha init --force'" >> /etc/bash.bashrc && \
    echo "" >> /etc/bash.bashrc && \
    echo "# Alias for claude-flow to run commands" >> /etc/bash.bashrc && \
    echo "alias flow='npx --y claude-flow@alpha'" >> /etc/bash.bashrc && \
    echo "" >> /etc/bash.bashrc && \
    echo "# Alias to run claude CLI and dangerously skip permissions" >> /etc/bash.bashrc && \
    echo "alias yolo='claude --dangerously-skip-permissions --mcp-config /etc/claude/mcp-servers.json'" >> /etc/bash.bashrc && \
    echo "" >> /etc/bash.bashrc && \
    echo "# UUID function" >> /etc/bash.bashrc && \
    echo 'uuid() { python3 -c "import sys, uuid; print(uuid.uuid5(uuid.NAMESPACE_DNS, sys.argv[1]))" "$1"; }' >> /etc/bash.bashrc



# Create global MCP configuration file
RUN mkdir -p /etc/claude && \
    echo '{\n\
  "mcpServers": {\n\
    "playwright": {\n\
      "type": "stdio",\n\
      "command": "npx",\n\
      "args": ["@playwright/mcp@latest", "--executable-path", "/opt/playwright-cache/chromium-latest/chrome-linux/chrome", "--user-agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"],\n\
      "env": {}\n\
    }\n\
  }\n\
}' > /etc/claude/mcp-servers.json

# Add Claude wrapper to always use MCP config
RUN echo '#!/bin/bash\n\
/usr/local/bin/claude --mcp-config /etc/claude/mcp-servers.json "$@"' > /usr/local/bin/claude-mcp && \
    chmod +x /usr/local/bin/claude-mcp

# Update the yolo alias to include MCP config (done in global aliases section above)
# RUN sed -i 's|alias yolo=.*|alias yolo="/usr/local/bin/claude --dangerously-skip-permissions --mcp-config /etc/claude/mcp-servers.json"|' /etc/bash.bashrc

# Add claude alias that includes MCP config
RUN echo 'alias claude="/usr/local/bin/claude --mcp-config /etc/claude/mcp-servers.json"' >> /etc/bash.bashrc

# Activate Python virtual environment by default for all users
RUN echo "" >> /etc/bash.bashrc && \
    echo "# Activate Python virtual environment" >> /etc/bash.bashrc && \
    echo "source /opt/swarmbox/bin/activate" >> /etc/bash.bashrc

# Create cache directories with different approach for macOS
RUN if [ "${HOST_OS}" = "darwin" ]; then \
        # On macOS, just create directories without ownership changes
        # Docker Desktop will handle UID/GID mapping automatically
        mkdir -p /opt/npm-cache /opt/playwright-cache && \
        chmod -R 777 /opt/npm-cache /opt/playwright-cache; \
    else \
        # On Linux, use traditional approach
        mkdir -p /opt/npm-cache /opt/playwright-cache && \
        chown -R ${USER_UID}:${USER_GID} /opt/npm-cache /opt/playwright-cache && \
        chmod -R 755 /opt/npm-cache /opt/playwright-cache; \
    fi

# Install only Chromium browsers (including headless-shell) after cache setup
RUN npx playwright install chromium chromium-headless-shell --with-deps

# Create version-agnostic symlinks for browsers
RUN cd /opt/playwright-cache && \
    CHROMIUM_DIR=$(find . -maxdepth 1 -name "chromium-[0-9]*" -type d | head -1) && \
    CHROMIUM_HEADLESS_DIR=$(find . -maxdepth 1 -name "chromium_headless_shell-[0-9]*" -type d | head -1) && \
    if [ -n "$CHROMIUM_DIR" ]; then ln -sf "$CHROMIUM_DIR" chromium-latest; fi && \
    if [ -n "$CHROMIUM_HEADLESS_DIR" ]; then ln -sf "$CHROMIUM_HEADLESS_DIR" chromium-headless-latest; fi

# Switch to non-root user
USER agent

# Set working directory to user home
WORKDIR /home/agent

# Keep container running
CMD ["tail", "-f", "/dev/null"]