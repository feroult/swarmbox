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

# Install Deno globally
RUN curl -fsSL https://deno.land/x/install/install.sh | sh && \
    mv /root/.deno /usr/local/deno && \
    chmod -R 755 /usr/local/deno
ENV DENO_INSTALL="/usr/local/deno"
ENV PATH="$DENO_INSTALL/bin:$PATH"

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

# Install Claude Code globally as root
RUN npm install -g @anthropic-ai/claude-code@latest && \
    # Make global npm binaries accessible to all users
    chmod -R 755 /usr/local/lib/node_modules && \
    chmod -R 755 /usr/local/bin

# Create directories with proper permissions
RUN mkdir -p /home/agent && \
    chown -R agent:agent /home/agent

# Switch to non-root user
USER agent

# Set working directory to user home
WORKDIR /home/agent

# Copy entrypoint script
COPY --chown=root:root entrypoint.sh /entrypoint.sh
RUN sudo chmod +x /entrypoint.sh

# Set entrypoint
ENTRYPOINT ["/entrypoint.sh"]

# Keep container running
CMD ["tail", "-f", "/dev/null"]