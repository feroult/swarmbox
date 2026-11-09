# SwarmBox 2.0 image (design 10). Slim: no agent, gcloud, clasp, Go or Poetry; tools arrive on demand (design 6).
# The v0.1.0 image file is retired (git show v0.1.0:Dockerfile).
# Layer order: stable first (packages, Podman, pinned downloads), volatile last (scripts, configuration).
ARG NODE_VERSION=24
FROM node:${NODE_VERSION}-slim

# System packages (Debian 12 base). Every RUN that downloads cleans up in the same RUN.
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
    openssh-client \
    rsync \
    file \
    less \
    man-db \
    bash-completion \
    sqlite3 \
    tmux \
    && rm -rf /var/lib/apt/lists/*

# Nested rootless Podman (design 10.5): no host socket is ever mounted.
# netavark + aardvark-dns give nested networks DNS by container name (netavark needs iptables for its firewall
# driver, which Debian only lists as a hidden requirement); uidmap provides newuidmap/newgidmap; libcap2-bin setcap.
RUN apt-get update && \
    apt-get install -y podman netavark aardvark-dns iptables uidmap libcap2-bin && \
    rm -rf /var/lib/apt/lists/*

# Chromium, for the chrome-devtools MCP (design D24)
RUN apt-get update && \
    apt-get install -y chromium && \
    rm -rf /var/lib/apt/lists/*

# The fixed user (design 10.2). The base image already has user and group "node" with UID and GID 1000 (B26):
# rename it instead of adding a second user. sudo without a password is intentional: the box is the sandbox.
RUN usermod -l agent node && \
    groupmod -n agent node && \
    usermod -d /home/agent -m agent && \
    usermod -s /bin/bash agent && \
    echo "agent ALL=(ALL) NOPASSWD: ALL" >> /etc/sudoers

# --- Nested rootless Podman settings, kept unchanged from v0.1.0 (design 10.5 lists the reason for each) ---
# 1. File capabilities instead of the setuid bit: a setuid-root binary does not work in an unprivileged container.
RUN chmod u-s /usr/bin/newuidmap /usr/bin/newgidmap && \
    setcap cap_setuid+ep /usr/bin/newuidmap && \
    setcap cap_setgid+ep /usr/bin/newgidmap
# 2. subuid/subgid: the rename above leaves a stale range for "node"; 1001..65535 works with keep-id and without.
RUN echo "agent:1001:64535" > /etc/subuid && \
    echo "agent:1001:64535" > /etc/subgid
# 3. System-wide defaults (the home is a bind mount, so nothing here can live under it): native overlay with
#    ignore_chown_errors (only ~64k user IDs), utsns=host (the nested crun cannot sethostname), no systemd
#    (cgroupfs, file events), netavark for DNS between nested containers.
RUN mkdir -p /etc/containers && \
    printf '[storage]\ndriver = "overlay"\n\n[storage.options.overlay]\nignore_chown_errors = "true"\n' > /etc/containers/storage.conf && \
    printf '[containers]\nutsns = "host"\n[engine]\ncgroup_manager = "cgroupfs"\nevents_logger = "file"\n[network]\nnetwork_backend = "netavark"\n' > /etc/containers/containers.conf

# npm cache outside the home, owned by agent (created with the right owner, no chown -R afterwards). An npm run as
# root leaves root-owned entries that make a later npm as agent fail with EACCES (an `npm cache clean` leaves root-owned
# _logs and a stamp file behind: found by the image test), so the install below uses its own cache in /tmp and removes it.
ENV NPM_CONFIG_CACHE=/opt/npm-cache
RUN install -d -o agent -g agent -m 755 /opt/npm-cache

# Pinned chrome-devtools-mcp (D23, closes B24): the registry runs the installed program, never npx.
ARG CHROME_DEVTOOLS_MCP_VERSION=1.12.0
RUN npm install -g --cache /tmp/npm-build-cache chrome-devtools-mcp@${CHROME_DEVTOOLS_MCP_VERSION} && chrome-devtools-mcp --version && rm -rf /tmp/npm-build-cache

# uv (fast Python package manager), system-wide, at a pinned version
ARG UV_VERSION=0.9.5
RUN curl -LsSf "https://astral.sh/uv/${UV_VERSION}/install.sh" | UV_INSTALL_DIR=/usr/local/bin UV_NO_MODIFY_PATH=1 sh

# Environment
ENV LANG=C.UTF-8
ENV BROWSER=none
ENV CHROME_BIN=/usr/bin/chromium
ENV PUPPETEER_SKIP_CHROMIUM_DOWNLOAD=true
ENV PUPPETEER_EXECUTABLE_PATH=/usr/bin/chromium

# Web terminal: ttyd is not in Debian 12, so fetch the pinned release and verify its published checksum.
ARG TTYD_VERSION=1.7.7
RUN case "$(dpkg --print-architecture)" in \
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

# Starship prompt: a pinned release with its published SHA-256 verified (static musl binaries)
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

# Python virtual environment at /opt/flow (the "(swarmbox)" prompt); the directory is created with agent as owner (no chown -R)
RUN install -d -o agent -g agent -m 755 /opt/flow
USER agent
RUN python3 -m venv --prompt swarmbox /opt/flow && /opt/flow/bin/pip install --no-cache-dir --upgrade pip
USER root

# --- Volatile layers: scripts, configuration, the web page ---
# ttyd's own page, the clipboard bridge and the style: build-index.sh assembles the page at image build (D13, 5.1)
COPY container/web/ttyd-clipboard.js container/web/ttyd-style.css container/web/build-index.sh /usr/local/share/swarmbox/
RUN chmod 644 /usr/local/share/swarmbox/ttyd-clipboard.js /usr/local/share/swarmbox/ttyd-style.css && \
    chmod 755 /usr/local/share/swarmbox/build-index.sh && \
    (ttyd -p 17681 -i lo true >/dev/null 2>&1 & TTYD_PID=$!; \
     for i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20; do \
         curl -fsS -o /usr/local/share/swarmbox/ttyd-stock.html http://127.0.0.1:17681/ && break; sleep 0.3; \
     done; kill $TTYD_PID) && \
    test -s /usr/local/share/swarmbox/ttyd-stock.html && \
    sh /usr/local/share/swarmbox/build-index.sh

COPY container/config/tmux.conf /etc/tmux.conf
COPY container/config/tmux-browser-keys.conf /etc/tmux-browser-keys.conf
COPY container/config/starship.toml /etc/swarmbox/starship.toml
COPY container/config/bashrc.sh /etc/swarmbox/bashrc.sh
COPY container/config/ssh-swarmbox.conf /etc/ssh/ssh_config.d/swarmbox.conf
COPY container/scripts/dirs.sh /usr/local/lib/swarmbox/dirs.sh
COPY container/scripts/starship-init.sh /etc/swarmbox/scripts/starship-init.sh
COPY container/scripts/messages.sh /etc/swarmbox/scripts/messages.sh
COPY container/scripts/banner.sh /usr/local/bin/banner.sh
COPY container/scripts/podman-service.sh /usr/local/bin/swarmbox-podman-service
COPY container/scripts/ssh-key.sh /usr/local/bin/swarmbox-pubkey
COPY container/mcp/ /etc/swarmbox/mcp/
COPY container/scripts/swarmbox-attach.sh /usr/local/bin/swarmbox-attach
COPY container/scripts/swarmbox-web.sh /usr/local/bin/swarmbox-web
COPY container/scripts/swarmbox-tool.sh /usr/local/bin/swarmbox-tool
COPY container/scripts/swarmbox-shim.sh /usr/local/bin/swarmbox-shim
COPY container/tools/ /usr/local/lib/swarmbox/tools/
COPY container/scripts/swarmbox-mcp.sh /usr/local/bin/swarmbox-mcp
# The tool manifests (design 6.3) are read-only data of the image; `swarmbox-tool link --system` below generates the shims,
# the index and tool-ports from them. No agent is installed here (D2): the first call of a shim installs it.
COPY container/scripts/swarmbox-init.sh /usr/local/bin/swarmbox-init
# The helper archive (3.7.1, 9.3): what `swarmbox-entrypoint host-helper` writes. container/host/ holds swarmbox-host, VERSION and
# templates/ (the files `swarmbox-init` prints from); tool-ports is written by `swarmbox-tool link --system` below, always, empty
# when no manifest has ports.
COPY container/host/ /usr/local/share/swarmbox/host/
COPY cloudflare-setup.py /usr/local/share/swarmbox/host/cloudflare-setup.py
COPY container/entrypoint.sh /usr/local/bin/swarmbox-entrypoint
RUN chmod 644 /etc/tmux.conf /etc/tmux-browser-keys.conf /etc/swarmbox/starship.toml /etc/swarmbox/bashrc.sh /etc/ssh/ssh_config.d/swarmbox.conf \
        /usr/local/lib/swarmbox/dirs.sh /etc/swarmbox/scripts/starship-init.sh /etc/swarmbox/scripts/messages.sh && \
    chmod 755 /usr/local/bin/banner.sh /usr/local/bin/swarmbox-podman-service /usr/local/bin/swarmbox-pubkey \
        /usr/local/bin/swarmbox-attach /usr/local/bin/swarmbox-web /usr/local/bin/swarmbox-tool /usr/local/bin/swarmbox-shim /usr/local/bin/swarmbox-mcp /usr/local/bin/swarmbox-init /usr/local/bin/swarmbox-entrypoint && \
    chmod 755 /usr/local/share/swarmbox/host/swarmbox-host && \
    chmod 644 /usr/local/share/swarmbox/host/cloudflare-setup.py /usr/local/share/swarmbox/host/VERSION /usr/local/share/swarmbox/host/DEFAULTS && \
    chmod -R a+rX /usr/local/share/swarmbox/host && \
    chmod -R a+rX /etc/swarmbox/mcp /usr/local/lib/swarmbox/tools && \
    find /usr/local/lib/swarmbox/tools -name '*.sh' -exec chmod 755 {} + && \
    swarmbox-tool link --system

# Build-time preinstall (design 6.8, D23): WITH_TOOLS is a comma list of tool names (default empty: no tool is baked, D2). Each one is
# installed by the same installer that an on-demand install runs, as agent (the owner of /opt/swarmbox/tools, so no chown -R and no
# root-owned entries; the npm cache rule of 10.2: NPM_CONFIG_CACHE is /opt/npm-cache, owned by agent), into /opt/swarmbox/tools instead
# of the workspace. The fingerprint (6.11) is recorded at that moment. An unknown name or a failed installer fails the build; with an
# empty list the loop does nothing. The core never names a tool: the names come from the argument and the manifests.
ARG WITH_TOOLS=""
RUN install -d -o agent -g agent -m 755 /opt/swarmbox /opt/swarmbox/tools
USER agent
RUN set -eu; set -f; \
    for t in $(printf '%s' "$WITH_TOOLS" | tr ',' ' '); do \
        swarmbox-tool install "$t" --image; \
    done
USER root

# The shell fragment (design 6.6, 10.3) replaces the v0.1.0 echo lines: Debian's /etc/bash.bashrc leaves at once in a
# non-interactive shell, so the line below runs for interactive shells only; swarmbox-attach sources the fragment
# directly for a command run without a terminal (3.3).
RUN printf '\n# SwarmBox shell fragment\n[ -r /etc/swarmbox/bashrc.sh ] && . /etc/swarmbox/bashrc.sh\n' >> /etc/bash.bashrc

# The image-level shims are on the PATH of every process of the box, also outside a shell (design 10.2); the shell fragment puts the
# user-level shims before them (6.2).
ENV PATH=/usr/local/lib/swarmbox/shims:$PATH

USER agent
WORKDIR /home/agent
ENTRYPOINT ["/usr/local/bin/swarmbox-entrypoint"]
CMD ["serve"]
