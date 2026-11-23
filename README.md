<div align="center">

# SwarmBox

**Give your AI coding agents a persistent Podman box of their own —<br>operated from a native Web Studio, your phone, or SSH.**

<p>
  <a href="https://github.com/feroult/swarmbox/releases/latest"><img src="https://img.shields.io/github/v/release/feroult/swarmbox?color=7c3aed&labelColor=1b1726&style=flat-square" alt="Latest release"></a>
  <a href="#security"><img src="https://img.shields.io/badge/Podman-4.3%2B%20rootless-6d28d9?labelColor=1b1726&style=flat-square" alt="Podman 4.3+ rootless"></a>
  <a href="#security"><img src="https://img.shields.io/badge/telemetry-zero-3dba7a?labelColor=1b1726&style=flat-square" alt="Zero telemetry"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-Apache--2.0-a78bfa?labelColor=1b1726&style=flat-square" alt="Apache-2.0"></a>
</p>

<p>
  <a href="#quick-start">Quick start</a> ·
  <a href="#web-studio--settings">Web Studio &amp; Settings</a> ·
  <a href="#mobile-sysop--voice">Mobile, Sysop &amp; Voice</a> ·
  <a href="#agents-addons--base-image">Addons</a> ·
  <a href="#remote-access">Remote access</a> ·
  <a href="#everyday-commands">Commands</a> ·
  <a href="#security">Security</a> ·
  <a href="#documentation">Docs</a>
</p>

<br>

<img src="docs/img/swarmbox-herdr-desktop.png" alt="SwarmBox Herdr Web Studio v2.2 — 3-pane browser workspace with pixel-art Agent Mascot Cards, symmetric panel chevrons, zero-redundancy adaptive topbar, JetBrains Mono + Nerd Font, Purple Glow Starship prompt, and docked Sysop drawer with its reactive pixel-art operator mascot" width="880">

</div>

<br>

| Persistent Sandbox | Native Web Studio &amp; Mobile | Sysop Operator &amp; Local Voice |
| :--- | :--- | :--- |
| Run **Claude Code**, **Antigravity (`agy`)**, **OpenCode**, or **Gemini CLI** in auto-approve mode with `sudo`, nested rootless Podman, and headless Chromium — with projects, logins, SSH keys, and addons persisted in one host folder (`~/swarmbox`). | Pixel-art **Agent Mascot Cards** with live OSC 7501 status, adaptive Focus Mode (`Alt+B`), 5 synced themes, bundled **JetBrains Mono + Nerd Font**, studio **Settings** (`Alt+,`), smart wrapped-line copy, instant bracketed &amp; **clipboard image paste (`Ctrl+V` / drag-and-drop)**, and a 3-pane 24-bit **Terminal Cockpit** over SSH. | Type or speak a goal from desktop or phone. **Sysop** reads your tabs, routes to the active agent, and pauses risky actions behind one-tap **Allow / Cancel** cards — backed by local `whisper.cpp` speech-to-text. |

---

## Quick start

Requires **Podman 4.3+** (Linux, WSL2 on the Linux filesystem, or macOS via a Podman machine).

```bash
curl -fsSL https://github.com/feroult/swarmbox/releases/latest/download/install.sh | sh -s -- --with claude
swarmbox          # pulls the image, creates the box, and opens a shell (shortcut: sx)
claude            # inside the box: installs Claude Code on first use and runs in auto-approve mode
```

- **Switch to Herdr Web Studio &amp; Terminal Cockpit:** `tmux` + `ttyd` is the default mux; opt into `herdr` any time with `swarmbox config set MUX herdr && swarmbox reset` (revert anytime with `MUX tmux`).
- **Open the Web Studio:** run `swarmbox url` and visit `http://127.0.0.1:7681`, or run `swarmbox` again in another terminal to share the live session.
- **Other agents &amp; API keys:** pass `--with antigravity` (`agy`) or `--with opencode`, install later with `swarmbox addon install <name>`, or forward a host key via `export ANTHROPIC_API_KEY=...` and `swarmbox env add ANTHROPIC_API_KEY && swarmbox reset`.

---

## Web Studio & Settings

Opt into `MUX=herdr` for a cohesive browser studio, responsive phone UI, and matching 24-bit SSH Terminal Cockpit — all attached to the same live `herdr-core` daemon with zero extra host installs.

<p align="center">
  <img src="docs/img/swarmbox-web-settings.png" alt="SwarmBox Studio Settings on desktop and mobile — 5 visual theme cards synced with Terminal Cockpit, JetBrains Mono font slider with live preview, line-height density, cursor, scrollback, and 5-section navigation" width="880">
</p>

| Capability | What you get out of the box |
| :--- | :--- |
| **Pixel-Art Agent Cards &amp; Focus Mode** | Active coding agents (`agy`, `claude`, `codex`, `opencode`, `gemini`) get color-coded **Pixel-Art Mascot Cards** in the sidebar with live OSC 7501 badges (`IDLE`, `WORKING 74%`, `BLOCKED`, `DONE`), inline progress bars, and `Alt+1..9` switching — while plain shells stay cleanly grouped under `SHELLS`. Collapse the sidebar (`Alt+B`) and informative horizontal pixel-icon tabs automatically take over the topbar for distraction-free full-width focus; Sysop also opens responsively by viewport width (`>= 1360px`). |
| **Studio Settings (`Alt+,`)** | Desktop dialog + mobile bottom sheet across 5 live sections — **Appearance**, **SwarmBox**, **Sysop** (3-card autonomy policy), **Voice**, and **Addons &amp; System** (one-click live addon install, MCP servers, Git SSH public key copy, shortcuts). Editing host-managed keys stages a sticky **Apply on host** bar (`swarmbox config set ... && swarmbox reset`) with one-click copy. |
| **5 Synced Themes &amp; Offline Fonts** | **Purple Glow** (default), **Catppuccin Mocha**, **Tokyo Night**, **Nord**, and **Rosé Pine** — synchronized across Web UI, Terminal Cockpit, and `herdr.toml` — paired with self-hosted **JetBrains Mono + Nerd Font** (zero CDN) and a Purple Glow Starship prompt. |
| **Smart Copy, Bracketed &amp; Image Paste** | **Copy** (`Ctrl+C` / `Cmd+C` / context menu) inspects the terminal buffer to rejoin soft-wrapped, shaded, or bordered AI commands into one clean line while preserving real multi-line scripts. **Text paste** (`Ctrl+V` / `Ctrl+Shift+V`) uses native Bracketed Paste (`\x1b[200~...\x1b[201~`) with zero double-paste. **Image paste** (`Ctrl+V` / `Cmd+V` or drag-and-drop PNG/JPEG/WebP/GIF/BMP) uploads directly to `/tmp/swarmbox/paste/` (`0600`, rolling prune) and injects the local file path straight into the active agent (`claude`, `agy`, `codex`, `opencode`). |
| **Zero-Scroll Hydration &amp; Cockpit** | Per-tab live `xterm.js` sessions open already anchored at the bottom, switch in 0 ms preserving scrollback (with a floating **Jump to live** pill), auto-heal WebSockets on wake, and match the 3-pane SSH **Terminal Cockpit** (`Alt+1..9`, `Alt+N`, `Alt+B`, `Alt+S`, `Alt+G`, `Alt+T`, `Alt+,`, `Alt+-/=/0`). |

---

## Mobile, Sysop & Voice

Operate long-running agents comfortably from your phone with iOS-calibrated momentum touch scrolling, a floating glass dock, one-tap approvals, and local offline Whisper dictation.

<p align="center">
  <img src="docs/img/swarmbox-mobile.png" alt="SwarmBox Herdr Web Studio on mobile — left phone shows live agent tabs with pixel-art mascot icons, 1-line Starship prompt, floating ALLOW? approval card, and glass dock; right phone shows the Sysop bottom sheet with countdown bar, live steps, and voice composer" width="740">
</p>

```bash
swarmbox addon install sysop      # autonomous operator + approval cards
swarmbox addon install voice      # local whisper.cpp speech-to-text microphone
```

- **Context-aware operator:** Sysop remembers recent goals, infers the active agent tab, queues messages when an agent is working, and keeps a full audit log.
- **Host-enforced safety policy:** Low-risk actions run directly under `auto`; medium-risk actions pause on a veto countdown; high-risk commands and open agent dialogs always wait for **Allow** (`confirm-risky` and `confirm-all` tighten further via **Settings → Sysop**).
- **Private local voice:** Tap **Speak** on desktop or phone to capture audio with a live waveform and timer, then tap **Send** (or **×** to discard) — transcribed locally through `whisper.cpp` straight to Sysop without audio ever leaving your machine, and `swarmbox-voice say "..."` works from any shell ([docs/sysop.md](docs/sysop.md), [docs/voice.md](docs/voice.md)).

---

## Agents, Addons & Base Image

Addons install on demand inside your persistent workspace — keeping the base image lean while preserving versions across resets and upgrades.

| Addon | Commands | Notes |
| :--- | :--- | :--- |
| **`claude`** | `claude` | Claude Code (`--dangerously-skip-permissions` interactive default) + Purple Glow statusline |
| **`antigravity`** | `agy` | Google Antigravity CLI (`--dangerously-skip-permissions` interactive default) + isolated statusline |
| **`opencode`** | `opencode` | Open-source terminal coding agent |
| **`gemini`** | `gemini` | Gemini CLI *(deprecated; paid API key only — use `antigravity`)* |
| **`sysop`** | `swarmbox-sysop` | Autonomous goal operator, live activity panel, and risk-gated approval host |
| **`voice`** | `swarmbox-voice` | Local `whisper.cpp` speech-to-text web front and goal publisher |
| **`go`** | `go`, `gofmt` | Pinned Go toolchain (SHA-256 verified) with workspace `GOPATH` |
| **`gcloud`** | `gcloud`, `gsutil`, `bq` | Pinned Google Cloud CLI (SHA-256 verified) |
| **`clasp`** | `clasp` | Pinned Google Apps Script CLI with OAuth callback port (`43323`) published |
| **`poetry`** | `poetry` | Pinned Python dependency manager installed isolated in the workspace |

- **Agent shortcut &amp; custom addons:** Run `yolo` inside the box to launch your default agent (`YOLO=0` disables auto-approve); scaffold custom workspace addons with `swarmbox addon new NAME`, inspect with `swarmbox addon doctor`, and roll back with `swarmbox addon use NAME VERSION`.
- **Included in the base image:** Node 24, Python 3 + `uv`, nested rootless Podman (`netavark` + `aardvark-dns`, [docs/nested-podman.md](docs/nested-podman.md)), pinned headless Chromium + `chrome-devtools-mcp`, both mux backends (`tmux 3.7c` + `ttyd` default; `herdr-core` + Herdr Web Studio &amp; Terminal Cockpit opt-in), Starship prompt, `swarmbox-bus`, `swarmbox-tabs`, `git`, `jq`, `sqlite3`, and `build-essential`.

---

## Remote access

Reach the Web Studio, Sysop approvals, and Whisper microphone from anywhere over HTTPS with **Cloudflare Tunnel + Access** (email one-time code, free Zero Trust tier):

```bash
swarmbox remote setup --domain example.com --email you@example.com
swarmbox url
```

`cloudflared` runs in a separate container **on your host**, never inside the box — no open router ports, no public IP, and no tunnel secrets inside the agent's environment ([docs/cloudflare.md](docs/cloudflare.md), [docs/web-terminal.md](docs/web-terminal.md)).

---

## Everyday commands

```bash
swarmbox                        # attach to the shared session (starts the box if needed)
swarmbox --plain                # open a plain bash shell without a multiplexer
swarmbox url                    # print local and remote web terminal addresses
swarmbox config list            # show all settings and where each comes from
swarmbox config set MUX herdr   # enable Herdr Web Studio & Terminal Cockpit
swarmbox env add NAME           # pass a host environment variable into the box
swarmbox addon list             # show available and installed addons
swarmbox addon install NAME     # install an addon (e.g. sysop, voice, antigravity, go)
swarmbox update                 # pull a newer image and refresh the host script from it
swarmbox reset                  # recreate the box so changed settings apply (workspace kept)
swarmbox stop                   # stop the box without deleting anything
swarmbox pubkey                 # print the box's Git SSH public key
swarmbox remote setup           # set up Cloudflare Tunnel + email-code Access
```

---

## Security

SwarmBox runs in a rootless Podman container, which is **not complete isolation**: it shares the kernel with your host and carries the known limits of containers (and nested Podman requires `/dev/net/tun` and an unmasked `/proc`). It confines agent mistakes to one workspace folder (`~/swarmbox`), keeps your host Podman socket and Cloudflare credentials outside the box, binds the web gateway to `127.0.0.1`, and makes no telemetry calls. For untrusted code or a stronger boundary, run SwarmBox inside a virtual machine ([docs/microvm.md](docs/microvm.md)). More in [SECURITY.md](SECURITY.md) and [docs/security-review.md](docs/security-review.md).

---

## Documentation

| Guide | What it covers |
| :--- | :--- |
| [Web terminal](docs/web-terminal.md) | Browser shortcuts, clipboard sync, mobile controls strip, font sizing, and customization |
| [Herdr &amp; Cockpit](docs/herdr-cockpit-design.md) · [Mux architecture](docs/mux-architecture.md) | Opt-in `herdr` backend, Terminal Cockpit, Herdr Web Studio, and native OSC 7501 Sysop bridge |
| [Sysop](docs/sysop.md) | Autonomous tab operator, MCP brain presets/templates, risk policy, panel modes, and audit log |
| [Voice control](docs/voice.md) | Local Whisper setup, language/model settings, `/voice/` proxy, and troubleshooting |
| [Remote access](docs/cloudflare.md) | Cloudflare Tunnel + Access setup, token handling, and multi-box hostnames |
| [Nested Podman](docs/nested-podman.md) | Running containers inside the box, host `podman -c` connection, and port forwarding |
| [Theme](docs/theme.md) | The Purple Glow palette for Windows Terminal, Ghostty, and Claude Code + statusline |
| [Addons &amp; Bus](docs/addons-design.md) | Addon manifest model, `swarmbox-bus` pub/sub, and `swarmbox-tabs` capability |
| [Architecture](docs/design.md) | Complete system design, configuration reference, and design decisions |
| [MicroVM](docs/microvm.md) · [Uninstall](docs/uninstall.md) | Running inside a VM boundary; clean removal steps |

[Changelog](CHANGELOG.md) · [Contributing](CONTRIBUTING.md) · [Security](SECURITY.md) · [Code of conduct](CODE_OF_CONDUCT.md) · [Third-party notices](THIRD_PARTY_NOTICES.md) · [Apache-2.0](LICENSE)
