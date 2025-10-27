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

# Create a system-wide Python virtual environment
RUN python3 -m venv /opt/flow && \
    /opt/flow/bin/pip install --upgrade pip && \
    /opt/flow/bin/pip install python-docx

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
    echo "# Alias to run claude CLI and dangerously skip permissions" >> /etc/bash.bashrc && \
    echo "alias yolo='claude --dangerously-skip-permissions --mcp-config /etc/claude/mcp-servers.json'" >> /etc/bash.bashrc && \
    echo "" >> /etc/bash.bashrc && \
    echo "# UUID function" >> /etc/bash.bashrc && \
    echo 'uuid() { python3 -c "import sys, uuid; print(uuid.uuid5(uuid.NAMESPACE_DNS, sys.argv[1]))" "$1"; }' >> /etc/bash.bashrc



# Create global MCP configuration file
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
    echo "source /opt/flow/bin/activate" >> /etc/bash.bashrc

# Add welcome banner for interactive shells with BBS-style ANSI art
RUN echo "" >> /etc/bash.bashrc && \
    echo "# Display welcome banner for interactive shells" >> /etc/bash.bashrc && \
    echo "if [[ \$- == *i* ]]; then" >> /etc/bash.bashrc && \
    echo "  /usr/local/bin/banner.sh" >> /etc/bash.bashrc && \
    echo "fi" >> /etc/bash.bashrc

# Create cache directories and set permissions for agent user
RUN if [ "${HOST_OS}" = "darwin" ]; then \
        # On macOS, just create directories without ownership changes
        # Docker Desktop will handle UID/GID mapping automatically
        mkdir -p /opt/npm-cache && \
        chmod -R 777 /opt/npm-cache /opt/flow; \
    else \
        # On Linux, use traditional approach
        mkdir -p /opt/npm-cache && \
        chown -R ${USER_UID}:${USER_GID} /opt/npm-cache /opt/flow && \
        chmod -R 755 /opt/npm-cache /opt/flow; \
    fi

# Copy banner script (at the end to optimize build cache)
COPY banner.sh /usr/local/bin/banner.sh
RUN chmod +x /usr/local/bin/banner.sh

# Switch to non-root user
USER agent

# Set working directory to user home
WORKDIR /home/agent

# Keep container running
CMD ["tail", "-f", "/dev/null"]