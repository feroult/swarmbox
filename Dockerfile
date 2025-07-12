FROM node:20-slim

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

# Install Deno
RUN curl -fsSL https://deno.land/x/install/install.sh | sh
ENV DENO_INSTALL="/root/.deno"
ENV PATH="$DENO_INSTALL/bin:$PATH"

# Create app directory
WORKDIR /app

# Create a non-root user with sudo privileges
RUN useradd -m -s /bin/bash claude-user && \
    echo "claude-user ALL=(ALL) NOPASSWD: ALL" >> /etc/sudoers

# Set npm cache directory
ENV NPM_CONFIG_CACHE=/home/claude-user/.npm

# Install Claude Code and Claude Flow globally as root
RUN npm install -g @anthropic-ai/claude-code@latest && \
    npm install -g claude-flow@alpha && \
    # Make global npm binaries accessible to all users
    chmod -R 755 /usr/local/lib/node_modules && \
    chmod -R 755 /usr/local/bin

# Create directories with proper permissions
RUN mkdir -p /home/claude-user/.claude && \
    mkdir -p /home/claude-user/workspace && \
    mkdir -p /home/claude-user/.npm && \
    mkdir -p /home/claude-user/.config && \
    chown -R claude-user:claude-user /home/claude-user

# Switch to non-root user
USER claude-user

# Set working directory to user workspace
WORKDIR /home/claude-user/workspace

# Keep container running
CMD ["tail", "-f", "/dev/null"]