# Third-party notices

SwarmBox itself is licensed under the Apache License 2.0 (see `LICENSE`). The image built from the `Dockerfile` downloads
and installs the tools below. Each stays under its own license; SwarmBox does not modify them. This is the first version of
the list: Phase 7 of `docs/implementation-plan.md` completes it (full list of packages, license texts shipped in the image).

Evidence tags: `[verified: ...]` means the license was read from the upstream LICENSE file or the installed package on
2026-11-08 (Debian 12 bookworm, Podman 4.3.1). `[unverified]` means it was not checked in this environment.

## Tools downloaded at a pinned version

### ttyd

- Version: 1.7.7 (`ARG TTYD_VERSION`, release binary with its SHA-256 checked)
- License: MIT
- Source: https://github.com/tsl0922/ttyd
- [verified: LICENSE of tag 1.7.7 read from raw.githubusercontent.com, "MIT License, Copyright (c) 2016-2022 Shuanglei Tao"; 2026-11-08]

### Starship

- Version: 1.27.0 (`ARG STARSHIP_VERSION`, static musl release with its SHA-256 checked)
- License: ISC
- Source: https://github.com/starship/starship
- [verified: LICENSE of tag v1.27.0, "ISC License, Copyright (c) 2019-2022, Starship Contributors"; 2026-11-08]

## Tools installed from Debian packages

### tmux

- Version: the Debian 12 package (3.3a)
- License: ISC (the source files carry ISC and BSD notices; Debian lists ISC, BSD-2-clause and BSD-3-clause for some files)
- Source: https://github.com/tmux/tmux
- [verified: /usr/share/doc/tmux/copyright of the installed package and COPYING of tag 3.3a; 2026-11-08]

### Podman (with netavark, aardvark-dns, iptables, uidmap, libcap2-bin)

- Version: the Debian 12 package (4.3.1)
- License: Apache-2.0 (Podman). The helper packages carry their own licenses.
- Source: https://github.com/containers/podman
- [verified: /usr/share/doc/podman/copyright, Podman only; 2026-11-08] [unverified: the license of netavark, aardvark-dns, iptables, uidmap, libcap2-bin]

### Chromium

- Version: the Debian 12 package
- License: BSD-3-clause for the main part; the package bundles many components under other licenses
- Source: https://www.chromium.org/ and https://packages.debian.org/bookworm/chromium
- [verified: first entries of /usr/share/doc/chromium/copyright; 2026-11-08] [unverified: the full list of bundled component licenses]

### Google Cloud CLI (google-cloud-cli)

- Version: from Google's apt repository
- License: Apache-2.0 for the SDK; some bundled components have other terms
- Source: https://cloud.google.com/sdk/docs/install-sdk
- [unverified: not read in this environment (no copyright file was found for the installed package)]

### Base system packages

git, curl, wget, python3, build-essential, sudo, vim, jq, openssh-client, rsync and the others of the first `apt-get install`
of the `Dockerfile` keep their Debian licenses (`/usr/share/doc/<package>/copyright` inside the image).
[unverified: not listed one by one yet; Phase 7 generates the list from the package database]

## Tools installed by their own installer

### Poetry

- Version: latest at build time (`install.python-poetry.org`)
- License: MIT
- Source: https://github.com/python-poetry/poetry
- [verified: LICENSE on the main branch, "Copyright (c) 2018-present Sebastien Eustace"; 2026-11-08]

### uv

- Version: latest at build time (`astral.sh/uv/install.sh`)
- License: Apache-2.0 or MIT, at your option
- Source: https://github.com/astral-sh/uv
- [verified: LICENSE-MIT on the main branch is MIT, Copyright (c) 2025 Astral Software Inc.; the Apache-2.0 half comes from the project's dual-license statement and was not re-read; 2026-11-08]

### Go

- Version: latest at build time (`go.dev/dl`)
- License: BSD-3-Clause
- Source: https://github.com/golang/go
- [verified: LICENSE of the installed /usr/local/go, "Copyright 2009 The Go Authors", BSD-style; 2026-11-08]

## Tools installed with npm

### Gemini CLI (`@google/gemini-cli`)

- License: Apache-2.0
- Source: https://github.com/google-gemini/gemini-cli
- [verified: "license" field of the installed package.json and LICENSE on the main branch; 2026-11-08]

### clasp (`@google/clasp`)

- License: Apache-2.0
- Source: https://github.com/google/clasp
- [verified: "license" field of the installed package.json and LICENSE on the master branch; 2026-11-08]

### OpenCode (`@opencode/cli`)

- License: MIT
- Source: https://github.com/sst/opencode [unverified: the repository URL; the npm package was not traced to it]
- [verified: "license" field of the installed package.json (version 2.2.5); 2026-11-08]

### Claude Code (`@anthropic-ai/claude-code`)

- License: proprietary. Use is subject to Anthropic's legal agreements (https://code.claude.com/docs/en/legal-and-compliance).
  The package is not redistributed by SwarmBox: the image build downloads it from npm.
- [verified: LICENSE.md of the installed package, "(c) Anthropic PBC. All rights reserved. Use is subject to the Legal Agreements ..."; 2026-11-08]

### Chrome DevTools MCP (`chrome-devtools-mcp`)

- License: Apache-2.0
- Source: https://github.com/ChromeDevTools/chrome-devtools-mcp
- Installed at build by the 2.0 Dockerfile at a pinned version (`CHROME_DEVTOOLS_MCP_VERSION`); the v0.1.0 image fetches it with `npx` at run time.
- [verified: "license" and "repository" fields of the npm registry entry for 1.12.0 (`npm view`); 2026-11-08]

## Not installed by the Dockerfile but pulled at run time

In the v0.1.0 image the Chrome DevTools MCP server is fetched by `npx` when an agent starts it; the 2.0 image installs it at build (above).
Phase 7 reviews every run-time download.
