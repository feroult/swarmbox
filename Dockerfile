FROM node:20-slim

# Accept build arguments for user UID/GID
ARG USER_UID=1000
ARG USER_GID=1000

# Install system dependencies
RUN apt-get update && apt-get install -y \
    git \
    curl \
    wget \
    python3 \
    python3-pip \
    build-essential \
    unzip \
    sudo \
    vim \
    nano \
    procps \
    net-tools \
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
    && rm -rf /var/lib/apt/lists/*

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

# Set npm cache directory
ENV NPM_CONFIG_CACHE=/home/agent/.npm

# Set Anthropic model
ENV ANTHROPIC_MODEL=sonnet

# Install Claude Code globally as root (latest version)
RUN curl -fsSL http://claude.ai/install.sh | bash && \
    # Copy Claude from the expected location to system path
    cp /root/.local/bin/claude /usr/local/bin/claude && \
    chmod +x /usr/local/bin/claude

# Install claude-flow globally with @alpha version
RUN npm install -g claude-flow@alpha

# Add global aliases for all users
RUN echo "# Alias for claude-flow to always use the latest alpha build via npx" >> /etc/bash.bashrc && \
    echo "alias flow='npx --y claude-flow@alpha init --force'" >> /etc/bash.bashrc && \
    echo "" >> /etc/bash.bashrc && \
    echo "# Alias to run claude CLI and dangerously skip permissions" >> /etc/bash.bashrc && \
    echo "alias yolo='claude --dangerously-skip-permissions'" >> /etc/bash.bashrc

# Create directories with proper permissions
RUN mkdir -p /home/agent && \
    chown -R agent:agent /home/agent

# Switch to non-root user
USER agent

# Set working directory to user home
WORKDIR /home/agent


# Keep container running
CMD ["tail", "-f", "/dev/null"]