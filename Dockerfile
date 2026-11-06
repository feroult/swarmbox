FROM node:24-slim

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
    && rm -rf /var/lib/apt/lists/*

# Install Podman, used as a nested rootless engine inside this container
# (no host socket is ever mounted).
# netavark + aardvark-dns give nested networks DNS by container name (netavark needs
# iptables for its firewall driver, but Debian only lists it as a hidden requirement);
# uidmap provides newuidmap/newgidmap; libcap2-bin provides setcap.
RUN apt-get update && \
    apt-get install -y podman netavark aardvark-dns iptables uidmap libcap2-bin && \
    rm -rf /var/lib/apt/lists/*

# Install Poetry system-wide
ENV POETRY_HOME=/opt/poetry
RUN curl -sSL https://install.python-poetry.org | python3 - && \
    ln -s /opt/poetry/bin/poetry /usr/local/bin/poetry && \
    chmod -R a+rx /opt/poetry

# Install uv (fast Python package installer and manager) system-wide
RUN curl -LsSf https://astral.sh/uv/install.sh | UV_INSTALL_DIR=/usr/local/bin sh

# Install latest Go SDK system-wide (under /usr/local, never under /home/agent)
RUN ARCH=$(dpkg --print-architecture) && \
    GO_VERSION=$(curl -fsSL https://go.dev/VERSION?m=text | head -n1) && \
    curl -fsSL "https://go.dev/dl/${GO_VERSION}.linux-${ARCH}.tar.gz" -o /tmp/go.tar.gz && \
    tar -C /usr/local -xzf /tmp/go.tar.gz && \
    rm /tmp/go.tar.gz

# Keep GOPATH/GOCACHE off /home/agent so nothing gets installed into the user's home
ENV PATH=/usr/local/go/bin:/opt/go/bin:$PATH
ENV GOPATH=/opt/go
ENV GOCACHE=/opt/go-cache

# Install Google Cloud CLI (gcloud) system-wide via the official apt repo,
# which always tracks the latest release
RUN curl -fsSL https://packages.cloud.google.com/apt/doc/apt-key.gpg | gpg --dearmor -o /usr/share/keyrings/cloud.google.gpg && \
    echo "deb [signed-by=/usr/share/keyrings/cloud.google.gpg] https://packages.cloud.google.com/apt cloud-sdk main" > /etc/apt/sources.list.d/google-cloud-sdk.list && \
    apt-get update && \
    apt-get install -y google-cloud-cli && \
    rm -rf /var/lib/apt/lists/*

# Create a system-wide Python virtual environment
# --prompt: the shell prompt shows (swarmbox), not the directory name (flow); the path stays /opt/flow
RUN python3 -m venv --prompt swarmbox /opt/flow && \
    /opt/flow/bin/pip install --upgrade pip

# Clone and install mcp-memory-service from fork with fix
# Also extract the framework hooks for later use
RUN git clone https://github.com/feroult/mcp-memory-service.git /tmp/mcp-memory-service && \
    cd /tmp/mcp-memory-service && \
    /opt/flow/bin/pip install python-docx . && \
    mkdir -p /etc/swarmbox && \
    cp -r claude-hooks /etc/swarmbox/claude-hooks && \
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

# --- Nested rootless Podman (start.sh always runs the container with the flags it needs) ---
# 1. newuidmap/newgidmap: a setuid-root binary does not work in an unprivileged
#    container (write to uid_map fails with EPERM). File capabilities do; this is
#    what the official quay.io/podman/stable image does too.
RUN chmod u-s /usr/bin/newuidmap /usr/bin/newgidmap && \
    setcap cap_setuid+ep /usr/bin/newuidmap && \
    setcap cap_setgid+ep /usr/bin/newgidmap
# 2. subuid/subgid: the base image's user was renamed node -> agent, which leaves
#    a stale 'node' range. 1001..65535 exists both with --userns=keep-id and with
#    the default userns.
RUN echo "agent:1001:64535" > /etc/subuid && \
    echo "agent:1001:64535" > /etc/subgid
# 3. System-wide defaults (HOME is a bind mount, so nothing can live under it):
#    - storage: native overlay (the bind-mounted home is a real ext4; overlay on
#      the container's own overlay rootfs would not work, vfs is the slow fallback).
#      ignore_chown_errors: this container only has ~64k user IDs, so layers owning
#      files by a higher ID (65534 "nobody", 65532 distroless "nonroot": busybox,
#      cloudflared, ...) cannot be extracted otherwise; those files become root-owned.
#    - utsns=host: the nested crun cannot sethostname without CAP_SYS_ADMIN
#    - netavark backend: needed for DNS between nested containers
RUN mkdir -p /etc/containers && \
    printf '[storage]\ndriver = "overlay"\n\n[storage.options.overlay]\nignore_chown_errors = "true"\n' > /etc/containers/storage.conf && \
    printf '[containers]\nutsns = "host"\n[engine]\ncgroup_manager = "cgroupfs"\nevents_logger = "file"\n[network]\nnetwork_backend = "netavark"\n' > /etc/containers/containers.conf

# Set npm cache directory to a non-mounted location
ENV NPM_CONFIG_CACHE=/opt/npm-cache

# Set Anthropic model
ENV ANTHROPIC_MODEL=sonnet

# UTF-8 locale for every process. Without it bash/readline drops an accented character typed on its
# own (a dead key + letter) instead of inserting it, and tmux/ttyd inherit the same environment.
ENV LANG=C.UTF-8

# Disable browser auto-opening for Vite and other dev servers
ENV BROWSER=none

# Chromium/Puppeteer environment variables for Docker
ENV CHROME_BIN=/usr/bin/chromium
ENV PUPPETEER_SKIP_CHROMIUM_DOWNLOAD=true
ENV PUPPETEER_EXECUTABLE_PATH=/usr/bin/chromium

# Install Gemini CLI globally via npm
RUN npm install -g @google/gemini-cli

# Install clasp (Google Apps Script CLI) globally via npm
RUN npm install -g @google/clasp

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
    echo "# yolo is just another name for claude (the claude alias below carries the flags; repeating them passed every option twice)" >> /etc/bash.bashrc && \
    echo "alias yolo='claude'" >> /etc/bash.bashrc && \
    echo "" >> /etc/bash.bashrc && \
    echo "# Main claude alias with auto-approve (same as yolo)" >> /etc/bash.bashrc && \
    echo "alias claude='claude --dangerously-skip-permissions --mcp-config ~/.claude/mcp-servers.json'" >> /etc/bash.bashrc && \
    echo "" >> /etc/bash.bashrc && \
    echo "# Alias to run gemini CLI with yolo mode (bypass all approvals)" >> /etc/bash.bashrc && \
    echo "alias gemini='/usr/local/bin/gemini --yolo'" >> /etc/bash.bashrc && \
    echo "" >> /etc/bash.bashrc && \
    echo "# UUID function" >> /etc/bash.bashrc && \
    echo 'uuid() { python3 -c "import sys, uuid; print(uuid.uuid5(uuid.NAMESPACE_DNS, sys.argv[1]))" "$1"; }' >> /etc/bash.bashrc && \
    echo "" >> /etc/bash.bashrc && \
    echo "# clasp wrapper: inject --redirect-port 43323 for login" >> /etc/bash.bashrc && \
    echo 'clasp() { if [[ "$1" == "login" ]]; then command clasp login --redirect-port 43323 "${@:2}"; else command clasp "$@"; fi; }' >> /etc/bash.bashrc



# Copy MCP configurations to container (needed for next step)
COPY container/mcp/ /etc/swarmbox/mcp/
RUN chmod -R 755 /etc/swarmbox/mcp && \
    chmod +x /etc/swarmbox/mcp/memory/init.sh

# Copy OpenCode local-LLM config template (rendered at container start by init.sh)
COPY container/opencode/ /etc/swarmbox/opencode/
RUN chmod -R 755 /etc/swarmbox/opencode

# OpenCode loads this (merged with, never replacing, the user's own opencode.json).
# init.sh renders it at every start; lives under $HOME/.swarmbox so it survives the home mount.
ENV OPENCODE_CONFIG=/home/agent/.swarmbox/opencode-local.json

# Create global MCP configuration file (base config without memory)
RUN mkdir -p /etc/claude && \
    jq -n --slurpfile chrome /etc/swarmbox/mcp/chrome-devtools/config.json \
      '{mcpServers: {"chrome-devtools": $chrome[0]}}' \
      > /etc/claude/mcp-servers-base.json

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

# Copy initialization script for .swarmbox setup (runs at container start)
COPY container/scripts/init.sh /usr/local/bin/init-swarmbox.sh
RUN chmod 755 /usr/local/bin/init-swarmbox.sh

# Add initialization to bashrc (runs for interactive shells)
RUN echo "" >> /etc/bash.bashrc && \
    echo "# Initialize .swarmbox directory structure" >> /etc/bash.bashrc && \
    echo "/usr/local/bin/init-swarmbox.sh 2>/dev/null" >> /etc/bash.bashrc

# Create cache directories and set permissions for agent user
RUN if [ "${HOST_OS}" = "darwin" ]; then \
        mkdir -p /opt/npm-cache /opt/go /opt/go-cache /workspace && \
        chmod -R 777 /opt/npm-cache /opt/flow /opt/go /opt/go-cache /workspace; \
    else \
        mkdir -p /opt/npm-cache /opt/go /opt/go-cache /workspace && \
        chown -R ${USER_UID}:${USER_GID} /opt/npm-cache /opt/flow /opt/go /opt/go-cache /workspace && \
        chmod -R 755 /opt/npm-cache /opt/flow /opt/go /opt/go-cache /workspace; \
    fi

# Web terminal (start.sh --web): ttyd serving tmux. ttyd is not in Debian 12, so fetch the
# pinned release and verify its published checksum. Placed late so a version bump does not
# invalidate the expensive layers above.
ARG TTYD_VERSION=1.7.7
RUN apt-get update && apt-get install -y --no-install-recommends tmux && \
    rm -rf /var/lib/apt/lists/* && \
    case "$(dpkg --print-architecture)" in \
        amd64) T=ttyd.x86_64 ;; \
        arm64) T=ttyd.aarch64 ;; \
        *) echo "ttyd: unsupported architecture $(dpkg --print-architecture)" >&2; exit 1 ;; \
    esac && \
    BASE="https://github.com/tsl0922/ttyd/releases/download/${TTYD_VERSION}" && \
    curl -fsSL -o "/tmp/$T" "$BASE/$T" && \
    curl -fsSL -o /tmp/ttyd.SHA256SUMS "$BASE/SHA256SUMS" && \
    (cd /tmp && grep " $T\$" ttyd.SHA256SUMS | sha256sum -c -) && \
    install -m 755 "/tmp/$T" /usr/local/bin/ttyd && \
    rm -f "/tmp/$T" /tmp/ttyd.SHA256SUMS
# The default tmux config (/etc/tmux.conf) loads tmux-browser-keys.conf from its own directory
COPY container/config/tmux.conf /etc/tmux.conf
COPY container/config/tmux-browser-keys.conf /etc/tmux-browser-keys.conf
# ttyd's own page (kept as is) plus the clipboard bridge that swarmbox-web-terminal injects into it
COPY container/web/ttyd-clipboard.js /usr/local/share/swarmbox/ttyd-clipboard.js
COPY container/web/ttyd-style.css /usr/local/share/swarmbox/ttyd-style.css
RUN chmod 644 /usr/local/share/swarmbox/ttyd-clipboard.js /usr/local/share/swarmbox/ttyd-style.css && \
    (ttyd -p 17681 -i lo true >/dev/null 2>&1 & TTYD_PID=$!; \
     for i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20; do \
         curl -fsS -o /usr/local/share/swarmbox/ttyd-stock.html http://127.0.0.1:17681/ && break; sleep 0.3; \
     done; kill $TTYD_PID) && \
    test -s /usr/local/share/swarmbox/ttyd-stock.html && grep -q '</body>' /usr/local/share/swarmbox/ttyd-stock.html
COPY container/web/web-terminal.sh /usr/local/bin/swarmbox-web-terminal
RUN chmod 755 /usr/local/bin/swarmbox-web-terminal && chmod 644 /etc/tmux.conf /etc/tmux-browser-keys.conf

# Copy banner and messaging scripts (at the end to optimize build cache)
COPY container/scripts/banner.sh /usr/local/bin/banner.sh
RUN mkdir -p /etc/swarmbox/scripts && chmod +x /usr/local/bin/banner.sh
COPY container/scripts/podman-service.sh /usr/local/bin/swarmbox-podman-service
RUN chmod 755 /usr/local/bin/swarmbox-podman-service
COPY container/scripts/messages.sh /etc/swarmbox/scripts/messages.sh
RUN chmod 644 /etc/swarmbox/scripts/messages.sh

# Starship prompt for interactive bash: a pinned release with its published SHA-256 verified (static musl
# binaries for amd64 and arm64), the SwarmBox config (its own cool palette), and a script that turns it on.
# The bashrc line comes last on purpose: Starship redefines PS1, so it must run after the venv activation.
ARG STARSHIP_VERSION=1.27.0
RUN case "$(dpkg --print-architecture)" in \
        amd64) T=starship-x86_64-unknown-linux-musl.tar.gz ;; \
        arm64) T=starship-aarch64-unknown-linux-musl.tar.gz ;; \
        *) echo "starship: unsupported architecture $(dpkg --print-architecture)" >&2; exit 1 ;; \
    esac && \
    BASE="https://github.com/starship/starship/releases/download/v${STARSHIP_VERSION}" && \
    cd /tmp && curl -fsSL -O "$BASE/$T" && curl -fsSL -O "$BASE/$T.sha256" && \
    echo "$(tr -d '[:space:]' < "$T.sha256")  $T" | sha256sum -c - && \
    tar -xzf "$T" -C /usr/local/bin starship && chmod 755 /usr/local/bin/starship && \
    rm -f "/tmp/$T" "/tmp/$T.sha256"
COPY container/config/starship.toml /etc/swarmbox/starship.toml
COPY container/scripts/starship-init.sh /etc/swarmbox/scripts/starship-init.sh
RUN chmod 644 /etc/swarmbox/starship.toml /etc/swarmbox/scripts/starship-init.sh && \
    echo "" >> /etc/bash.bashrc && \
    echo "# Starship prompt (opt out with SWARMBOX_STARSHIP=0)" >> /etc/bash.bashrc && \
    echo ". /etc/swarmbox/scripts/starship-init.sh" >> /etc/bash.bashrc

# Copy agents (LAST - changes frequently, should invalidate minimal cache)
COPY container/agents/ /etc/swarmbox/agents/
RUN chmod -R 755 /etc/swarmbox/agents

# Install Claude Code and OpenCode globally via npm (avoids native binary warnings)
# Kept as the LAST installed thing so `--update-harness` only re-runs this single
# layer, not everything after it. CLAUDE_CODE_CACHEBUST defaults to a fixed value
# so normal builds stay cached; pass a timestamp via --build-arg to force a reinstall.
ARG CLAUDE_CODE_VERSION=latest
ARG CLAUDE_CODE_CACHEBUST=0
ARG OPENCODE_VERSION=latest
# This runs as root, AFTER the chown of /opt/npm-cache above, so the cache entries it writes would be
# root-owned and `npx` as agent (e.g. the chrome-devtools MCP) would fail with EACCES. Drop the cache
# (it is not needed at runtime, and it shrinks the layer) and give the directory back to the user.
# OpenCode also ships four platform builds (~240 MB each) under node_modules/@opencode; its postinstall
# hard-links the right one into bin/, so the others can go. It must happen in this same RUN: a later
# `rm` would not shrink the image, and `opencode --version` fails the build if the binary is missing.
RUN echo "cachebust=${CLAUDE_CODE_CACHEBUST}" && \
    npm install -g @anthropic-ai/claude-code@${CLAUDE_CODE_VERSION} @opencode/cli@${OPENCODE_VERSION} && \
    rm -rf /usr/local/lib/node_modules/@opencode/cli/node_modules/@opencode && \
    opencode --version >/dev/null && \
    npm cache clean --force && \
    mkdir -p /opt/npm-cache && \
    if [ "${HOST_OS}" = "darwin" ]; then chmod -R 777 /opt/npm-cache; else chown -R ${USER_UID}:${USER_GID} /opt/npm-cache; fi

# Expose HTTP port for MCP memory service web dashboard
EXPOSE 8889

# Switch to non-root user
USER agent

# Set working directory to user home
WORKDIR /home/agent

# Keep container running
CMD ["tail", "-f", "/dev/null"]