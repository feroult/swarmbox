# SwarmBox 2.0 image. Slim: no agent, gcloud, clasp, Go or Poetry; addons arrive on demand.
# Layer order: stable first (packages, Podman, pinned downloads), volatile last (scripts, configuration).
ARG NODE_VERSION=24
FROM node:${NODE_VERSION}-trixie-slim

# System packages (Debian 13 "trixie" base). Every RUN that downloads cleans up in the same RUN.
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
    bind9-dnsutils \
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
    && rm -rf /var/lib/apt/lists/*

# Nested rootless Podman: no host socket is ever mounted.
# netavark + aardvark-dns give nested networks DNS by container name (netavark needs iptables for its firewall
# driver, which Debian only lists as a hidden requirement); uidmap provides newuidmap/newgidmap; libcap2-bin setcap.
RUN apt-get update && \
    apt-get install -y podman netavark aardvark-dns iptables uidmap libcap2-bin && \
    # Podman only recommends criu (checkpoint and restore, unused here); criu drags in python3-protobuf, which the
    # release scan flags (GHSA-8qvm-5x2c-j2w7, GHSA-7gcm-g887-7qv7). Removing it does not remove podman.
    apt-get purge -y criu python3-pycriu python3-protobuf && \
    rm -rf /var/lib/apt/lists/*

# Chromium, for the chrome-devtools MCP
RUN apt-get update && \
    apt-get install -y chromium && \
    rm -rf /var/lib/apt/lists/*

# The fixed user. The base image already has user and group "node" with UID and GID 1000:
# rename it instead of adding a second user. sudo without a password is intentional: the box is the sandbox.
RUN usermod -l agent node && \
    groupmod -n agent node && \
    usermod -d /home/agent -m agent && \
    usermod -s /bin/bash agent && \
    echo "agent ALL=(ALL) NOPASSWD: ALL" >> /etc/sudoers

# --- Nested rootless Podman settings (the reason for each is under "Nested Podman and its isolation cost" in docs/design.md) ---
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

# Pinned chrome-devtools-mcp: the registry runs the installed program, never npx.
ARG CHROME_DEVTOOLS_MCP_VERSION=1.12.0
RUN npm install -g --cache /tmp/npm-build-cache chrome-devtools-mcp@${CHROME_DEVTOOLS_MCP_VERSION} && chrome-devtools-mcp --version && rm -rf /tmp/npm-build-cache

# uv (fast Python package manager), system-wide, at a pinned version
ARG UV_VERSION=0.9.5
RUN curl -LsSf "https://astral.sh/uv/${UV_VERSION}/install.sh" | UV_INSTALL_DIR=/usr/local/bin UV_NO_MODIFY_PATH=1 sh

# Environment
ENV LANG=C.UTF-8
ENV BROWSER=/usr/local/bin/swarmbox-open
ENV CHROME_BIN=/usr/bin/chromium
ENV PUPPETEER_SKIP_CHROMIUM_DOWNLOAD=true
ENV PUPPETEER_EXECUTABLE_PATH=/usr/bin/chromium

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

# The multiplexer: herdr-core (hc daemon, OpenRPC + OSC 7501), pinned by SHA-256.
ARG HERDR_CORE_VERSION=0.1.21
ARG HERDR_CORE_SHA256_AMD64=78424755c10a40dde38a0bdb55c20ac19706e9ae05ed68fc2acf1fcff0d941c1
ARG HERDR_CORE_SHA256_ARM64=e844a2bfab48a226097679d076bc83042fe57fccef5387ef802e5b24e78b529a
RUN case "$(dpkg --print-architecture)" in \
        amd64) T=herdr-core-linux-x86_64.tar.gz; SHA256=$HERDR_CORE_SHA256_AMD64 ;; \
        arm64) T=herdr-core-linux-aarch64.tar.gz; SHA256=$HERDR_CORE_SHA256_ARM64 ;; \
        *) echo "herdr-core: unsupported architecture $(dpkg --print-architecture)" >&2; exit 1 ;; \
    esac && \
    curl -fsSL -o "/tmp/$T" "https://releases.herdr.dev/core/${HERDR_CORE_VERSION}/$T" && \
    echo "$SHA256  /tmp/$T" | sha256sum -c - && \
    tar -xzf "/tmp/$T" -C /usr/local/bin herdr-core && \
    chmod 755 /usr/local/bin/herdr-core && \
    ln -sf /usr/local/bin/herdr-core /usr/local/bin/hc && \
    rm -f "/tmp/$T" && hc --version

# Dependencies for the herdr web gateway (ws + local xterm.js & symbol font bundles, zero runtime CDN calls).
COPY container/web/herdr/package.json /usr/local/share/swarmbox/herdr-web/package.json
RUN cd /usr/local/share/swarmbox/herdr-web && \
    npm install --omit=dev --no-audit --no-fund --cache /tmp/npm-build-cache && \
    rm -rf /tmp/npm-build-cache

# Full upstream JetBrains Mono WOFF2 webfonts (OFL-1.1, pinned by SHA-256) with complete box-drawing,
# block-element, geometric-shape, arrow, and Powerline glyph coverage (no Google Fonts subsetting).
ARG JETBRAINS_MONO_VERSION=2.304
ARG JETBRAINS_MONO_SHA256=6f6376c6ed2960ea8a963cd7387ec9d76e3f629125bc33d1fdcd7eb7012f7bbf
RUN curl -fsSL -o /tmp/JetBrainsMono.zip \
        "https://github.com/JetBrains/JetBrainsMono/releases/download/v${JETBRAINS_MONO_VERSION}/JetBrainsMono-${JETBRAINS_MONO_VERSION}.zip" && \
    echo "${JETBRAINS_MONO_SHA256}  /tmp/JetBrainsMono.zip" | sha256sum -c - && \
    mkdir -p /usr/local/share/swarmbox/herdr-web/fonts && \
    unzip -q -j /tmp/JetBrainsMono.zip \
        fonts/webfonts/JetBrainsMono-Regular.woff2 \
        fonts/webfonts/JetBrainsMono-SemiBold.woff2 \
        fonts/webfonts/JetBrainsMono-Bold.woff2 \
        fonts/webfonts/JetBrainsMono-Italic.woff2 \
        -d /usr/local/share/swarmbox/herdr-web/fonts && \
    rm -f /tmp/JetBrainsMono.zip

# Python virtual environment at /opt/flow (the "(swarmbox)" prompt); the directory is created with agent as owner (no chown -R)
RUN install -d -o agent -g agent -m 755 /opt/flow
USER agent
RUN python3 -m venv --prompt swarmbox /opt/flow && /opt/flow/bin/pip install --no-cache-dir --upgrade pip
USER root

# --- Volatile layers: scripts, configuration, the web server ---
COPY container/config/starship.toml /etc/swarmbox/starship.toml
COPY container/config/bashrc.sh /etc/swarmbox/bashrc.sh
COPY container/config/ssh-swarmbox.conf /etc/ssh/ssh_config.d/swarmbox.conf
COPY container/web/herdr/*.mjs /usr/local/share/swarmbox/herdr-web/
COPY container/web/herdr/public/ /usr/local/share/swarmbox/herdr-web/public/
COPY container/scripts/dirs.sh /usr/local/lib/swarmbox/dirs.sh
COPY container/scripts/mux/ /usr/local/lib/swarmbox/mux/
COPY container/scripts/starship-init.sh /etc/swarmbox/scripts/starship-init.sh
COPY container/scripts/messages.sh /etc/swarmbox/scripts/messages.sh
COPY container/scripts/swarmbox-statusline.sh /usr/local/bin/swarmbox-statusline
COPY container/scripts/ssh-key.sh /usr/local/bin/swarmbox-pubkey
COPY container/mcp/ /etc/swarmbox/mcp/
COPY container/scripts/swarmbox-attach.sh /usr/local/bin/swarmbox-attach
COPY container/scripts/swarmbox-open.py /usr/local/bin/swarmbox-open
COPY container/scripts/swarmbox-web.sh /usr/local/bin/swarmbox-web
COPY container/scripts/swarmbox-addon.sh /usr/local/bin/swarmbox-addon
COPY container/scripts/swarmbox-bus.py /usr/local/bin/swarmbox-bus
# The tabs of the box (list, active, screen, send): a capability of the host with its own command, separate from the bus.
COPY container/scripts/swarmbox-tabs.py /usr/local/bin/swarmbox-tabs
COPY container/scripts/swarmbox-pins.py /usr/local/bin/swarmbox-pins
COPY container/scripts/swarmbox-worktree.py /usr/local/bin/swarmbox-worktree
COPY container/scripts/swarmbox-state.py /usr/local/bin/swarmbox-state
COPY container/scripts/swarmbox-agents.py /usr/local/bin/swarmbox-agents
COPY container/scripts/swarmbox_agents.py /usr/local/lib/swarmbox/swarmbox_agents.py
COPY container/scripts/swarmbox-shim.sh /usr/local/bin/swarmbox-shim
COPY container/addons/ /usr/local/lib/swarmbox/addons/
COPY container/scripts/swarmbox-mcp.sh /usr/local/bin/swarmbox-mcp
# The addon manifests are read-only data of the image; `swarmbox-addon link --system` below generates the shims,
# the index and addon-ports from them. No agent is installed here: the first call of a shim installs it.
COPY container/scripts/swarmbox-install.sh /usr/local/bin/swarmbox-install
# The helper archive: what `swarmbox-entrypoint host-helper` writes. container/host/ holds swarmbox-host (the `swarmbox` command,
# which `swarmbox-install` prints an installer for), VERSION and DEFAULTS; addon-ports is written by `swarmbox-addon link --system` below, always, empty
# when no manifest has ports.
COPY container/host/ /usr/local/share/swarmbox/host/
COPY cloudflare-setup.py /usr/local/share/swarmbox/host/cloudflare-setup.py
COPY container/entrypoint.sh /usr/local/bin/swarmbox-entrypoint
RUN chmod 644 /etc/swarmbox/starship.toml /etc/swarmbox/bashrc.sh /etc/ssh/ssh_config.d/swarmbox.conf \
        /usr/local/lib/swarmbox/dirs.sh /usr/local/lib/swarmbox/swarmbox_agents.py /etc/swarmbox/scripts/starship-init.sh /etc/swarmbox/scripts/messages.sh && \
    chmod 755 /usr/local/bin/swarmbox-statusline /usr/local/bin/swarmbox-pubkey \
        /usr/local/bin/swarmbox-attach /usr/local/bin/swarmbox-open /usr/local/bin/swarmbox-web /usr/local/bin/swarmbox-addon /usr/local/bin/swarmbox-bus /usr/local/bin/swarmbox-tabs /usr/local/bin/swarmbox-pins /usr/local/bin/swarmbox-worktree /usr/local/bin/swarmbox-state /usr/local/bin/swarmbox-agents /usr/local/bin/swarmbox-shim /usr/local/bin/swarmbox-mcp /usr/local/bin/swarmbox-install /usr/local/bin/swarmbox-entrypoint && \
    ln -sf /usr/local/bin/swarmbox-open /usr/local/bin/xdg-open && \
    chmod 755 /usr/local/share/swarmbox/host/swarmbox-host /usr/local/share/swarmbox/herdr-web/server.mjs /usr/local/share/swarmbox/herdr-web/cockpit.mjs && \
    chmod 644 /usr/local/share/swarmbox/host/cloudflare-setup.py /usr/local/share/swarmbox/host/VERSION /usr/local/share/swarmbox/host/DEFAULTS && \
    chmod -R a+rX /usr/local/share/swarmbox/host /usr/local/share/swarmbox/herdr-web && \
    chmod -R a+rX /etc/swarmbox/mcp /usr/local/lib/swarmbox/addons /usr/local/lib/swarmbox/mux && \
    find /usr/local/lib/swarmbox/addons -name '*.sh' -exec chmod 755 {} + && \
    swarmbox-addon link --system

# Build-time preinstall: WITH_ADDONS is a comma list of addon names (default empty: no addon is baked). Each one is
# installed by the same installer that an on-demand install runs, as agent (the owner of /opt/swarmbox/addons, so no chown -R and no
# root-owned entries; the npm cache rule: NPM_CONFIG_CACHE is /opt/npm-cache, owned by agent), into /opt/swarmbox/addons instead
# of the workspace. The fingerprint is recorded at that moment. An unknown name or a failed installer fails the build; with an
# empty list the loop does nothing. The core never names an addon: the names come from the argument and the manifests.
ARG WITH_ADDONS=""
RUN install -d -o agent -g agent -m 755 /opt/swarmbox /opt/swarmbox/addons
USER agent
RUN set -eu; set -f; \
    for t in $(printf '%s' "$WITH_ADDONS" | tr ',' ' '); do \
        swarmbox-addon install "$t" --image; \
    done
USER root

# The shell fragment runs from Debian's /etc/bash.bashrc leaves at once in a
# non-interactive shell, so the line below runs for interactive shells only; swarmbox-attach sources the fragment
# directly for a command run without a terminal.
RUN printf '\n# SwarmBox shell fragment\n[ -r /etc/swarmbox/bashrc.sh ] && . /etc/swarmbox/bashrc.sh\n' >> /etc/bash.bashrc

# The image-level shims are on the PATH of every process of the box, also outside a shell; the shell fragment puts the
# user-level shims before them.
ENV PATH=/usr/local/lib/swarmbox/shims:$PATH

USER agent
WORKDIR /home/agent
ENTRYPOINT ["/usr/local/bin/swarmbox-entrypoint"]
CMD ["serve"]
