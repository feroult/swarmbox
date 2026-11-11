# Third-party notices

SwarmBox itself is licensed under the Apache License 2.0 (see `LICENSE`). The image built from the `Dockerfile` contains
the software below. Each part stays under its own license; SwarmBox does not modify any of it. This file is the complete
list for the 2.0 image.

Evidence tags: a verified tag says what was read, where, and when. An owner-check tag marks something that could
not be checked here (legal sufficiency, texts that need a lawyer or a hardware or account check), with the reason. This file is not legal advice: it is a record of what the license
files say, not a legal opinion.
This file has not been reviewed by a lawyer.

## What the image ships, and what it does not

The default image is slim: `ARG WITH_TOOLS=""`, so **no agent and no tool is baked in**. What the image
contains: Debian packages (the base `node:24-trixie-slim`, which is Debian 13, plus the packages of the `Dockerfile`), Node.js and
Yarn from the base image, `chrome-devtools-mcp` (npm, pinned), `uv`, `ttyd` and `starship` (pinned release binaries), the
Python virtual environment `/opt/flow` (pip and setuptools), and SwarmBox's own scripts. The licenses of all of them are
below. Everything under "Not shipped in the image" is downloaded on the user's machine, on first use, by the user's own box;
SwarmBox does not distribute those files. A build with `WITH_TOOLS=<names>` bakes the named tools in; an image built
like that and published would redistribute them, and then their terms below apply (Claude Code and Google Cloud CLI first of all).

## Full package list

Every Debian package of the built image (594 packages) with its version, its license identifiers and the link to its Debian
source is in `docs/debian-packages.tsv`, produced by `dev/gen-notices.sh` (read-only: `dpkg-query -W` and the `License:`
fields of `/usr/share/doc/<package>/copyright`). [verified: dev/gen-notices.sh --image swarmbox-test-img-notices, an image built by dev/dev-build.sh from the repository at commit cdab064 plus the Debian 13 package list change, run in a throwaway container and removed by its exact name; 2026-11-10; Podman 4.3.1 on the build host, image Debian 13 (trixie), amd64]
Run again with `sh dev/dev-build.sh --tag swarmbox-test-<name>` and `sh dev/gen-notices.sh --image swarmbox-test-<name>`.
How to read the file: the `licenses` column is what the package's own copyright file declares (Debian's machine-readable
format). The `flags` column is `NO-LICENSE-FIELD` for the old-style copyright files (146 packages, among them glibc, gcc
and its libraries, binutils and avahi): the cell then says "see copyright file" with the license files it names as a
hint, not as a finding. No package lacked a copyright file in this run (`NO-COPYRIGHT-FILE` is flagged when one does).
The identifiers are Debian's own spellings, not strictly SPDX. The list is for the amd64 image. [owner-check: the arm64
image has the same package names but was not built and listed here, because this box is amd64 only; the CI job on arm64
 builds it, and the release workflow can run the same script on it]

`NO-LICENSE-FIELD` is explained here: the package's copyright file has no `License:` field, so the script cannot read an
identifier. The text of such a file has to be read by hand; the table below records the ones the Dockerfile names directly.

## Debian packages named in the Dockerfile

The packages the `Dockerfile` installs by name (the other 554 are their dependencies and the base image: see the full list).
The license column is read from the table of the full list; where it says "read by hand" the old-style copyright file was
read in the image and the cell is the identifier I took from it. Source links point to the Debian source package.
[verified: dev/gen-notices.sh --image swarmbox-test-img-notices, an image built by dev/dev-build.sh from the repository at commit cdab064 plus the Debian 13 package list change, run in a throwaway container and removed by its exact name; 2026-11-10; Podman 4.3.1 on the build host, image Debian 13 (trixie), amd64]

| Package | License identifiers (from the package's copyright file) | Version | Source |
|---|---|---|---|
| `aardvark-dns` | Apache-2.0 | 1.14.0-3 | https://sources.debian.org/src/aardvark-dns/ |
| `bash-completion` | GPL-2+ | 1:2.16.0-7 | https://sources.debian.org/src/bash-completion/ |
| `build-essential` | GPL-2+ (old-style file, read by hand) | 12.12 | https://sources.debian.org/src/build-essential/ |
| `bzip2` | BSD-variant, GPL-2 | 1.0.8-6 | https://sources.debian.org/src/bzip2/ |
| `ca-certificates` | GPL-2+, MPL-2.0 | 20250419+deb13u1 | https://sources.debian.org/src/ca-certificates/ |
| `chromium` | mixed, 22 identifiers (main part: see the note; complete list in docs/debian-packages.tsv) | 156.0.8078.79-1~deb13u1 | https://sources.debian.org/src/chromium/ |
| `curl` | 12 identifiers, among them BSD-3-Clause, BSD-3-clause, BSD-4-Clause-UC, FSFULLR (complete list in docs/debian-packages.tsv) | 8.14.1-2+deb13u7 | https://sources.debian.org/src/curl/ |
| `bind9-dnsutils` | 10 identifiers, among them BSD-2-clause, BSD-3-clause, CC0-1.0, FSFAP (complete list in docs/debian-packages.tsv) | 1:9.20.30-1~deb13u1 | https://sources.debian.org/src/bind9/ |
| `file` | 5 identifiers, among them BSD-2-Clause-alike, BSD-2-Clause-netbsd, BSD-2-Clause-regents, MIT-Old-Style-with-legal-disclaimer-2 (complete list in docs/debian-packages.tsv) | 1:5.46-5 | https://sources.debian.org/src/file/ |
| `git` | 15 identifiers, among them Apache-2.0, Artistic-1, BSD-3-clause, Boost (complete list in docs/debian-packages.tsv) | 1:2.47.3-0+deb13u1 | https://sources.debian.org/src/git/ |
| `gzip` | FSF-manpages, GFDL-1.3+-no-invariant, GPL-3+ | 1.13-1+deb13u1 | https://sources.debian.org/src/gzip/ |
| `htop` | GPL-2+ | 3.4.1-5 | https://sources.debian.org/src/htop/ |
| `iptables` | Artistic, GPL-2, GPL-2+, custom | 1.8.11-2 | https://sources.debian.org/src/iptables/ |
| `iputils-ping` | BSD-3-clause, GPL-2+, public-domain | 3:20240905-3 | https://sources.debian.org/src/iputils/ |
| `jq` | CC-BY-3.0, Expat, GPL-2.0+, MIT | 1.7.1-6+deb13u4 | https://sources.debian.org/src/jq/ |
| `less` | GPL-3+, GPL-3+ or Less, GPL-3+ or Less, and X11, Less, Spencer-86, X11, public-domain | 668-1 | https://sources.debian.org/src/less/ |
| `libcap2-bin` | BSD-3-clause, BSD-3-clause or GPL-2, BSD-3-clause or GPL-2+, GPL-2, GPL-2+ | 1:2.75-10+deb13u1+b3 | https://sources.debian.org/src/libcap2/ |
| `man-db` | GPL-2+, GPL-3+ | 2.13.1-1 | https://sources.debian.org/src/man-db/ |
| `nano` | GFDL-NIV+, GFDL-NIV+ or GPL-3+, GPL-3+ | 8.4-1+deb13u1 | https://sources.debian.org/src/nano/ |
| `net-tools` | GPL-2+ | 2.10-1.3 | https://sources.debian.org/src/net-tools/ |
| `netavark` | Apache-2.0 | 1.14.0-2 | https://sources.debian.org/src/netavark/ |
| `netcat-openbsd` | BSD-2-Clause, BSD-3-Clause | 1.229-1 | https://sources.debian.org/src/netcat-openbsd/ |
| `openssh-client` | 7 identifiers, among them BSD-2-clause, BSD-3-clause, Expat-with-advertising-restriction, Mazieres-BSD-style (complete list in docs/debian-packages.tsv) | 1:10.0p1-7+deb13u4 | https://sources.debian.org/src/openssh/ |
| `podman` | Apache-2.0, BSD-3-clause, Expat, LGPL-2.1+ | 5.4.2+ds1-2+b2 | https://sources.debian.org/src/podman/ |
| `procps` | GPL-2.0+, LGPL-2.0+, LGPL-2.1+ | 2:4.0.4-9 | https://sources.debian.org/src/procps/ |
| `python3` | PSF-2.0 (Python license; old-style file, read by hand) | 3.13.5-1 | https://sources.debian.org/src/python3-defaults/ |
| `python3-pip` | 8 identifiers, among them Apache-2.0, Apache-2.0 OR BSD-2, BSD-2, BSD-3 (complete list in docs/debian-packages.tsv) | 25.1.1+dfsg-1 | https://sources.debian.org/src/python-pip/ |
| `python3-venv` | PSF-2.0 (as python3) | 3.13.5-1 | https://sources.debian.org/src/python3-defaults/ |
| `rsync` | 14 identifiers, among them FSF-unlimited, FSFULLR, GPL-2, GPL-2+ (complete list in docs/debian-packages.tsv) | 3.5.0+ds1-0+deb13u1 | https://sources.debian.org/src/rsync/ |
| `sqlite3` | GPL-2+, public-domain | 3.46.1-7+deb13u2 | https://sources.debian.org/src/sqlite3/ |
| `sudo` | 7 identifiers, among them BSD-2-Clause, BSD-3-Clause, GPL-2+, ISC (complete list in docs/debian-packages.tsv) | 1.9.16p2-3+deb13u2 | https://sources.debian.org/src/sudo/ |
| `tar` | GPL-2+, GPL-3+, GPL-3+ with Bison exception, LGPL-2.1+, LGPL-3+ | 1.35+dfsg-3.1 | https://sources.debian.org/src/tar/ |
| `tmux` | BSD-2-clause, BSD-2-clause or ISC, BSD-2-clause-NetBSD, BSD-3-clause, Expat, FSFUL, FSFULLR, ISC | 3.5a-3 | https://sources.debian.org/src/tmux/ |
| `tree` | GPL-2+, LGPL-2.1+ | 2.2.1-1 | https://sources.debian.org/src/tree/ |
| `uidmap` | BSD-3-clause, GPL-1, GPL-2+ | 1:4.17.4-2 | https://sources.debian.org/src/shadow/ |
| `unzip` | Info-ZIP license (BSD-style; old-style file, read by hand) | 6.0-29+deb13u1 | https://sources.debian.org/src/unzip/ |
| `vim` | 24 identifiers, among them Apache, Apache or Expat, Artistic-1, BSD-2-clause (complete list in docs/debian-packages.tsv) | 2:9.1.1230-2+deb13u2 | https://sources.debian.org/src/vim/ |
| `wget` | GPL-3 with the OpenSSL linking exception (old-style file, read by hand) | 1.25.0-2 | https://sources.debian.org/src/wget/ |
| `xz-utils` | 11 identifiers, among them 0BSD, FSFUL, FSFULLR, GPL-2+ (complete list in docs/debian-packages.tsv) | 5.8.1-1+deb13u2 | https://sources.debian.org/src/xz-utils/ |
| `zip` | Info-ZIP license (BSD-style; old-style file, read by hand) | 3.0-15+deb13u1 | https://sources.debian.org/src/zip/ |

Notes on the table: `podman`'s helper packages (`netavark` and `aardvark-dns`, Apache-2.0 for the programs; the Debian
packages also contain the vendored Rust crates the programs were built with, which carry MIT, Apache-2.0 and other licenses
that the copyright file lists in its own paragraphs; `iptables`; `uidmap`, built from `shadow`; `libcap2-bin`, built from
`libcap2`) are in the table with the identifiers of their copyright files, which is the check the first version of this file
lacked.

### tmux

- Version: the Debian 13 package (3.5a-3)
- License: ISC (the source files carry ISC and BSD notices; Debian lists ISC, BSD-2-clause and BSD-3-clause for some files)
- Source: https://github.com/tmux/tmux
- [verified: /usr/share/doc/tmux/copyright of the installed package (3.5a-3), in an image built from the repository on 2026-11-10; the license text of upstream tag 3.5a was not re-read, the 3.3a one was on 2026-11-08]

### Podman and its helpers

- Version: the Debian 13 packages (Podman 5.4.2, netavark 1.14.0, aardvark-dns 1.14.0)
- License: Apache-2.0 (netavark, aardvark-dns); Apache-2.0 for Podman with parts under BSD-3-clause, Expat and LGPL-2.1+ (the `podman` row of `docs/debian-packages.tsv`); `iptables` GPL-2+ (with Artistic for some scripts); `uidmap` (shadow) GPL-2+ and BSD-3-clause; `libcap2-bin` BSD-3-clause or GPL-2
- Source: https://github.com/containers/podman, https://github.com/containers/netavark, https://github.com/containers/aardvark-dns, https://sources.debian.org/src/iptables/, https://sources.debian.org/src/shadow/, https://sources.debian.org/src/libcap2/
- [verified: dev/gen-notices.sh --image swarmbox-test-img-notices, an image built by dev/dev-build.sh from the repository at commit cdab064 plus the Debian 13 package list change, run in a throwaway container and removed by its exact name; 2026-11-10; Podman 4.3.1 on the build host, image Debian 13 (trixie), amd64]

### Chromium

- Version: the Debian 13 package (156.0.8078.79-1~deb13u1 in the listed image)
- License: BSD-3-clause for the main part (the Chromium Authors). The Debian copyright file lists the bundled components
  under Apache-2.0, BSD-2-clause, BSD-3-clause, BSL-1 (Boost), GPL-2 and GPL-3 (some build and test files), ICU, ISC, LGPL-2
  to LGPL-2.1+, MIT, MPL-1.1 and MPL-2.0 (with the GPL and LGPL alternatives of the MPL-1.1 files), Ms-PL, Unicode,
  zlib, public domain and a license of Apple's; the exact list of 22 identifiers is the `chromium` row of `docs/debian-packages.tsv`.
- Source: https://www.chromium.org/ and https://sources.debian.org/src/chromium/
- [verified: dev/gen-notices.sh --image swarmbox-test-img-notices, an image built by dev/dev-build.sh from the repository at commit cdab064 plus the Debian 13 package list change, run in a throwaway container and removed by its exact name; 2026-11-10; Podman 4.3.1 on the build host, image Debian 13 (trixie), amd64]
- [owner-check: the Debian copyright file is Debian's summary of the bundled components, written for the source package. The
  texts that Chromium shows in its own about:credits page (the licenses of the code compiled into the binary, including
  components Debian does not bundle but links from the system, such as the libraries listed as the package's dependencies) were not
  read here; the dependencies are in the full list, but whether that covers everything the binary contains is for the owner or
  a lawyer to confirm]

## Corresponding source for copyleft components

Many Debian packages above are under the GPL, LGPL, MPL or similar terms (the identifiers `GPL-*`, `LGPL-*`, `MPL-*` in the
list: for example glibc, bash, tar, gzip, git, vim, rsync, wget, iptables, `uidmap`, `libcap2-bin`, `bzip2`, `xz-utils`, GNU
binutils and GCC). They are installed unmodified from the Debian 13 archive, and SwarmBox does not patch them. Where to get
the corresponding source of any package of the image:

1. **Debian's source archive.** Each package row links to `https://sources.debian.org/src/<source package>/`. The exact
   version is the one in the `version` column; older versions of a package stay available at https://snapshot.debian.org/.
2. **On the running box:** with the `deb-src` lines of Debian 13 added to apt's sources (`deb-src http://deb.debian.org/debian
   trixie main` and the matching security line), `apt-get source <package>` downloads the source of the installed
   version. This works in the box because the image keeps the Debian apt configuration of the base image.
3. **Written offer.** For three years after the image of a release is last distributed, a copy of the complete corresponding
   source of the GPL and LGPL parts is available on request, at cost of the physical distribution, from
   feroult@gmail.com. The offer is here so
   that the pointer above is not the only means.
4. **The programs SwarmBox downloads itself** (`ttyd` MIT, `starship` ISC, `uv` Apache-2.0 or MIT, `chrome-devtools-mcp`
   Apache-2.0) are not copyleft; their source is at the URLs in their sections.

[owner-check: whether a pointer to Debian's archive plus the written offer satisfies the GPL and LGPL for an image the owner
publishes on ghcr.io, and whether the LGPL requirement to allow relinking is met by the dynamic linking in these packages,
is a legal question. Debian's own distribution practice is the model followed here; it is not a legal conclusion.]

The licenses' full texts are in the image, in `/usr/share/common-licenses/` (GPL, LGPL, Apache-2.0, GFDL, Artistic, MPL, BSD)
and in each package's `/usr/share/doc/<package>/copyright`, so a user of the image has them without network. The project
also keeps the texts of Node.js (`/usr/local/LICENSE`), Yarn (`/opt/yarn-v1.22.22/LICENSE`) and the packages of `/opt/flow`
in the image, where they were installed.

## Software that is part of the base image

### Node.js

- Version: the `node:24-slim` base image (v24.22.2 in the listed image)
- License: MIT, with the licenses of its bundled dependencies (V8, ICU, OpenSSL, c-ares, acorn and others) in `/usr/local/LICENSE` (2946 lines)
- Source: https://github.com/nodejs/node
- [verified: first lines and the list of bundled dependencies of /usr/local/LICENSE in the image, "Node.js is licensed for use as follows"; 2026-11-10; Podman 4.3.1 on the build host, image Debian 13; swarmbox-test-img-notices]

### Yarn 1.x

- Version: 1.22.22 (shipped by the base image in `/opt/yarn-v1.22.22`)
- License: BSD-2-Clause
- Source: https://github.com/yarnpkg/yarn
- [verified: /opt/yarn-v1.22.22/LICENSE of the image, "BSD 2-Clause License, For Yarn software"; 2026-11-10; swarmbox-test-img-notices]

### Python packages of `/opt/flow` (pip, setuptools)

- License: pip is MIT (`License-Expression: MIT` in its metadata), setuptools is MIT
- Source: https://github.com/pypa/pip and https://github.com/pypa/setuptools
- [verified: METADATA of pip 26.3 in the image, "License-Expression: MIT"; 2026-11-08]
- [owner-check: the setuptools license text was not read in the image; its MIT license is from its project page, so the owner may confirm it]

## Programs downloaded at a pinned version during the image build

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

### uv

- Version: 0.9.5 (`ARG UV_VERSION`, installer script of that version)
- License: Apache-2.0 or MIT, at your option
- Source: https://github.com/astral-sh/uv
- [verified: LICENSE-MIT on the main branch is MIT, Copyright (c) 2025 Astral Software Inc.; the Apache-2.0 half comes from the project's dual-license statement and was not re-read; 2026-11-08]

### Chrome DevTools MCP (`chrome-devtools-mcp`)

- Version: 1.12.0 (`ARG CHROME_DEVTOOLS_MCP_VERSION`, npm, pinned; the registry runs the installed program, never `npx`)
- License: Apache-2.0
- Source: https://github.com/ChromeDevTools/chrome-devtools-mcp
- [verified: "license" and "repository" fields of the npm registry entry for 1.12.0 (`npm view`); 2026-11-08]

### cloudflared (connector image, not in the SwarmBox image)

- Version: `docker.io/cloudflare/cloudflared:2026.10.7`, pinned in the host helper and in `cloudflare-setup.py`
- License: Apache-2.0
- Source: https://github.com/cloudflare/cloudflared
- The image is pulled by the user's Podman only when the user turns remote access on (`swarmbox remote setup`); SwarmBox neither builds nor republishes it.
- [verified: LICENSE of the master branch, "Apache License Version 2.0, January 2004"; 2026-11-08]
- [owner-check: the licenses of the layers inside Cloudflare's image were not read here; Cloudflare publishes the image and SwarmBox does not redistribute it]

## Not shipped in the image: tools installed on first use

These tools have a manifest under `container/tools/` and are installed by `swarmbox-tool` into the user's own tools volume
the first time they are used (or at build time only when someone passes `WITH_TOOLS`). With the default build none of them is in
the image, so SwarmBox does not redistribute them: the user's machine downloads them from the vendor. The license
statements below are for people who bake them in or want to know the terms.

### Claude Code (`@anthropic-ai/claude-code`, tool `claude`)

- License: proprietary. Use is subject to Anthropic's legal agreements (https://code.claude.com/docs/en/legal-and-compliance).
  The npm "license" field reads `SEE LICENSE IN README.md` and the package's `LICENSE.md` reads "(c) Anthropic PBC. All rights reserved".
- Source: not published as open source; the vendor's installer and package registry are the only source.
- Not redistributed by SwarmBox: the manifest installs it on first use with the vendor's native installer, into the user's
  tools volume. It must not be baked into a published image (`WITH_TOOLS=claude` is for private images; a test
  documents this in the manifest list).
- [verified: LICENSE.md of the installed package; `npm view @anthropic-ai/claude-code license` on 2026-11-08 returns "SEE LICENSE IN README.md"; 2026-11-08]

### Google Cloud CLI (`google-cloud-cli`, tool `gcloud`)

- Version: 592.0.0 (pinned in `container/tools/gcloud/tool.conf`; SHA-256 per architecture recorded by `dev/record-checksums.sh`)
- License: Apache-2.0 for the CLI and its source "unless otherwise specified by an alternate license file"; use with Google Cloud
  products is additionally governed by the terms of service of those products. Some bundled components carry their own license files.
- Source: https://github.com/twistedpair/google-cloud-sdk (a mirror) and https://cloud.google.com/sdk/docs/downloads-versioned-archives; the SDK's `LICENSE` is in the archive.
- Not redistributed by SwarmBox: downloaded from `dl.google.com` on first use (installed on first use, not in the image).
- [verified: google-cloud-sdk/LICENSE inside google-cloud-cli-592.0.0-linux-x86_64.tar.gz, "licensed under Apache License v. 2.0 (the License), unless otherwise specified by an alternate license file"; 2026-11-08]
- [owner-check: the license files of the bundled components (gsutil, bq, the Python and third-party directories of the archive) were not individually read; only the top-level LICENSE was extracted]

### Gemini CLI (`@google/gemini-cli`, tool `gemini`)

- License: Apache-2.0
- Source: https://github.com/google-gemini/gemini-cli
- [verified: "license" field of the installed package.json and LICENSE on the main branch; `npm view` shows Apache-2.0 and the repository URL (version 0.67.0); 2026-11-08]

### clasp (`@google/clasp`, tool `clasp`)

- License: Apache-2.0
- Source: https://github.com/google/clasp
- [verified: "license" field of the installed package.json and LICENSE on the master branch; `npm view` shows Apache-2.0 (version 3.4.1); 2026-11-08]

### OpenCode (`@opencode/cli`, tool `opencode`)

- License: MIT
- Source: https://github.com/anomalyco/opencode (the repository field of the npm package `@opencode/cli`; https://github.com/sst/opencode names the same project and carries the same LICENSE)
- [verified: "license" and "repository" fields of the npm registry entry (`npm view @opencode/cli`, version 2.2.6) and LICENSE of the repository's dev branch, "MIT License, Copyright (c) 2025 opencode"; 2026-11-08]
- The other package, `opencode-ai` 1.x, is also MIT by `npm view`; which of the two the tool installs is an open question (docs/release-checklist.md), not a license one.

### Poetry (tool `poetry`)

- Version: latest at install time (`install.python-poetry.org`)
- License: MIT
- Source: https://github.com/python-poetry/poetry
- [verified: LICENSE on the main branch, "Copyright (c) 2018-present Sebastien Eustace"; 2026-11-08]

### Go (tool `go`)

- Version: latest at install time (`go.dev/dl`)
- License: BSD-3-Clause
- Source: https://github.com/golang/go
- [verified: LICENSE of the installed /usr/local/go, "Copyright 2009 The Go Authors", BSD-style; 2026-11-08]

## Run-time downloads

The 2.0 image downloads nothing at run time except what the user asks for: the tools above on first use, and the connector
image when remote access is on. The v0.1.0 image fetched the Chrome DevTools MCP server with `npx` at run time; 2.0 installs
it at build (above). The MCP servers an agent starts for its own use are the user's choice.
