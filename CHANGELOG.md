# Changelog

All notable changes are listed here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the
project follows [semantic versioning](https://semver.org/).

## [Unreleased]

- Fixed: switching tabs in the Web Studio (Claude Code to agy and back) could paint the agent's reflow without the loader when a second Studio window or device was open. Every window followed the active tab with a viewport claim at its own size, so two windows resized the PTY back and forth on each switch, and the gateway masked the redraw only for the window that asked. Now only the window the user is in (visible and focused) claims a PTY, a background window follows passively and takes the size back when it gets the focus; a PTY resize masks the redraw for every window attached to it (a claim, a resize, an attach that changes the size, a stream that closes); a passive attach joins at the owner's exact size instead of hc's cached one (an attach always applies its size in herdr-core); and each stream's size is refreshed in herdr-core before `focus(true)`, which re-applies a stream's last size.
- Fixed: an agent started in a folder without a Git repository came back as a bare shell after the box restarted. Only agent tabs opened from **New agent** were persisted, and that picker listed repos only, so in any other folder you opened a shell and typed `claude` or `agy`, and the tab was never pinned. Now every agent session persists until its tab is closed, however it started (typed into a shell, a cockpit or Sysop tab, a worktree opened from its badge): the first time the Web Studio sees a terminal without a pin running a known agent, it gives it an `auto` pin, like a New agent tab (`persist: false` opts out).
- Changed: **New agent** (`Alt+A`) picks any folder, not only a repo, without typing: a **Recent** group (folders you launched in, the folders of open tabs, pinned sessions) above a folder browser with a breadcrumb, where a repo shows its branch, a plain folder opens with `›` (entering a folder selects it), and **Use this folder** selects the one you are in. The filter searches recent folders, every discovered repo and the folder shown; Backspace on an empty filter goes up one folder. New `GET /api/dirs?path=` lists the subfolders; `/api/projects` also returns `recent`.
- Changed: the Sysop's automatic tab naming (`sysop.autoname`) names a tab after what you asked, not after the screen: it reads your last requests in that folder from the agent's own prompt history (`~/.claude/history.jsonl`, `~/.gemini/antigravity-cli/history.jsonl`, the OpenCode database; the screen when they cannot be told apart), which is shorter and more specific. Titles are 1–3 words of at most 18 characters, cut on a word boundary. A tab is no longer named once and frozen: it is renamed when the goal becomes clearer or changes (an exploring first request such as "understand the repo" keeps the folder name), with a per-tab backoff of 3, 10, 30 and then 60 minutes between automatic renames. The naming call uses its own short system prompt instead of Claude Code's, with `--tools ""`, no MCP servers and no settings.
- Removed: the `gemini` addon (Google stopped serving Gemini CLI for most accounts; its successor is the `antigravity` addon, `agy`). A `gemini` installed by hand is still recognised as an agent in a tab.
- Removed: the leftovers of the tmux era. The host no longer special-cases the config keys `MUX` and `sysop.panel` (a file that still has one gets the generic "unknown key" warning; `swarmbox config unset KEY` removes it), `swarmbox-attach --web` and the backend function `mux_attach_web` (what ttyd ran; the Web Studio talks to herdr-core itself), and the fallback of a stale `SWARMBOX_MUX=tmux` to herdr. The system section of `swarmbox state` loses its constant `"mux": "herdr"` field.
- Changed: the sysop's MCP action `box_state` always reads the world model from `swarmbox-state` (the checkout's script when it is not on `PATH`), passing it the sysop's own `swarmbox-tabs` command; the ~150-line copy of that logic that only the tests used is gone. A timeout of a child command of the sysop now kills its whole process group, so a `swarmbox-tabs` started by `swarmbox-state` cannot outlive it.
- Fixed: in the Herdr Web Studio on macOS, `Cmd+C` and `Cmd+V` now copy and paste in a terminal like `Ctrl+C` and `Ctrl+V` (smart unwrapping of wrapped lines on copy, clipboard images on paste, `Cmd+Shift+V` as `Ctrl+Shift+V`); before, only `Ctrl` worked. `Cmd+C` with nothing selected sends nothing; `Ctrl+C` stays `^C`.
- Fixed: in the terminal cockpit, two fingers on a trackpad (the wheel) now reach a program that wants them: a program on the alternate screen (Claude Code in fullscreen, vim, less) gets arrow keys, and one that asked for the mouse gets the wheel as a mouse event (SGR, or the classic encoding) in its own cells. Before, the wheel only scrolled the history kept by the cockpit, so those programs did not move. A shell still scrolls its history. The Web Studio is not touched.
- Added: the `claude` addon now seeds the status line of the box (`swarmbox-statusline`) in `~/.claude/settings.json` on the first start (`prepare.sh`), like the `antigravity` addon does for `agy`: once, keeping every key the user already has, mode 600. Remove it from the file and it stays removed.
- Added: **`swarmbox-state` (`swarmbox state`) & Sysop v2 Actions**: unified read-only box world model (`--section workspace|system|all`) grouping running agents and pending worktrees under their repositories alongside shells, parked sessions, installed agents, and system health/resources. Sysop now pre-seeds the workspace state on stdin (saving Turn 1), streamlines its MCP actions from 13 to 9 (`box_state`, `read_tab`, `run`, `input`, `wait`, `tab` with `open`/`focus`/`rename`/`close`/`wake`, `worktree` supporting both live tabs and detached pending worktrees, `say`, `done`), and uses a concise structured system prompt; `swarmbox-tabs` now always attaches and exposes `swarmbox.agent` and supports `--pin-id` on `open`.

- Added: **Pinned Sessions & Manual/Auto Session Naming** (`docs/pins-design.md`): pin any live tab in the Herdr Web Studio (or via `swarmbox pins`) into persistent `~/.config/swarmbox/pins.json` so sessions survive `swarmbox stop`, `reset`, and reboots. Pinned tabs live-follow `cwd` and agent upgrades (never downgrading an agent pin to `shell`), default to zero-RAM **`PARKED`** cards on restart with 1-click **Wake** using a safe `--continue` wrapper (`claude`, `agy`, `opencode`), and support per-pin **`⚡ Autostart`** on boot (`herdr.sh` → `swarmbox-pins restore`). Any tab can be renamed inline (double-click, `Alt+R`, or `swarmbox tabs rename`), locking `title_source=user`; when `sysop` is installed (`sysop.autoname=1`), `tab.events` on `swarmbox-bus` wakes a silent auto-namer that gives unnamed tabs concise titles and logs compact inline rename rows in the Sysop visual feed without consuming the 8-goal conversation memory window.
- Added: **Git Worktrees for Multi-Agent Isolation** (`docs/worktrees-design.md`, `swarmbox-worktree`): opening a second agent (or waking a `PARKED` pin) on a Git repository with an active agent detects the working-tree collision and opens a 2-button popover (`New worktree` / `Same folder`, configurable live in **Settings → SwarmBox** as `ask` / `auto` / `off`). Worktrees live under `~/.local/share/swarmbox/worktrees/<repo>/<id>` on named `sb/wt-*` branches from `HEAD`, copy root `.env*` files (`0600`, `<= 64 KiB`, toggleable) and optional `.swarmbox-worktree` entries, dry-run merges in memory via `git merge-tree --write-tree`, offer an adaptive topbar merge popover (1-click clean merge & cleanup, agent commit, or in-worktree conflict resolution), auto-clean empty unpinned worktrees on close while keeping dirty/unmerged ones under **Pending worktrees**, and expose `open_tab(worktree=true)` and `worktree(tab, action)` to Sysop.
- Added: `swarmbox config path` prints where the config file is (also before it exists), and `swarmbox config unset KEY` removes a key from it, so its default (or the environment) applies again: the comments and the other lines are kept, the file stays mode 600, and it also cleans up a key the file holds that SwarmBox does not know (a typo, or the removed `MUX` and `sysop.panel`, whose warnings now name the command). The README no longer suggests `config set MUX herdr`.
- Changed: on mobile the Sysop sheet opens above the dock bar, which stays as it is (the Sysop capsule and the purple Speak; recording turns it into the voice bar in place), and the sheet opens by itself when a goal is sent by voice or text, so the reply shows in full. Typing is a quiet "Type a message" row at the end of the conversation: tapped, it becomes a one-line field with a round send arrow (16 px, so iOS does not zoom); sent, emptied or closed, it goes back to the row. The big composer with its own Speak and Send is desktop only.
- Changed: the Sysop header keeps **Collapse** apart from **New** and **Stop**: a thin divider and a wider gap sit between them (no divider when neither shows), **New** gets a `+` icon, and on mobile the collapse button is a 34 px target.
- Fixed: the terminal scrollbar of the Herdr Web Studio was always on in an AGY tab (AGY draws inline, so the normal buffer keeps scrollback; a short transcript gave a near-full thumb that looked like a stray line) and never there in a Claude Code tab (it draws in the alternate screen, which has no scrollback). The scrollbar is now an overlay: its thumb shows while you look back through history, for a moment after you scroll (wheel or finger), and while the mouse is at the right edge to grab it; at the live bottom it is hidden, so both agents rest the same.
- Fixed: dragging a terminal of the Herdr Web Studio with a finger moved in whole-row jumps (xterm scrolls by rows); the normal buffer now follows the finger pixel by pixel (whole rows through `scrollToLine`, the rest as a transform of `.xterm-screen` painted with the new rows), moves are coalesced to one per frame, the flick speed is measured over the last 100 ms of the drag, and the text comes to rest on a row, forward in the direction of the glide. The alternate screen (vim, less, TUIs) still gets wheel steps.
- Changed: the Sysop's default autonomy is the new level **`full-auto`**: what you ask, it does, with no approval or countdown for any action (the risk is still rated and written in the log and the audit, and a blocked action, such as control characters or a `/` command for an agent, is still refused). The brain's system prompt now depends on the level and, under `full-auto`, tells it to act directly and to ask only when it cannot tell what you want. The previous default `auto`, and `confirm-risky` and `confirm-all`, stay selectable (`swarmbox config set sysop.autonomy auto`, or **Settings → Sysop**).
- Fixed: active shell tabs in the Web Studio sidebar no longer clip their `Alt+N` shortcut hint inside `.tab-right` (switched from fixed `20px` width to right-aligned `min-width: 20px` with `white-space: nowrap` and a right-anchored `20x20` close button).
- Fixed: multi-client PTY viewport resolution conflicts in the Herdr Web Studio — `server.mjs` now tracks per-terminal viewport ownership so an idle or auto-reconnecting browser on another monitor cannot hijack the active client's PTY dimensions (`reconnect=1` attaches at the active PTY size, passive `resize` and automated terminal replies do not trigger `SIGWINCH`), while real user interaction (click/tap, tab switch, or typing) cleanly reclaims the PTY to that device's dimensions without needing a page refresh.

## [2.3.0] - 2026-11-23

- Removed: **tmux and ttyd**. herdr-core is the only multiplexer of the box: `swarmbox` opens the Terminal Cockpit, the web port always serves the Herdr Web Studio, and `swarmbox-tabs`, the sysop and the voice front all work on herdr-core terminals. The image no longer ships tmux, ttyd, `/etc/tmux.conf`, `/etc/tmux-browser-keys.conf` or the ttyd page (clipboard bridge, controls strip, style), and the shell no longer sets `CLAUDE_CODE_TMUX_TRUECOLOR`.
- Removed: the config keys `MUX` and `sysop.panel`. A config that still has them keeps working: each is ignored with a one-line warning and never passed to the box; `swarmbox config get|set` of them exits 2. The Studio's Settings lose the Multiplexer and Panel Visibility choices.
- Removed: `web-terminal.conf` and `swarmbox-web render` (`swarmbox-web` is `run` and `restart`); the voice addon's page files (`/voice/page.js`, `/voice/page.css`): its front serves only `/voice/health` and `/voice/audio` in front of the Web Studio (`--ttyd-port` is now `--server-port`), and `prepare.sh` removes the old `web/` folder of an install.
- Removed: the tmux panel of the sysop (`dock.py`, `panel.py`, `line.py`, `keys.py`), the commands `swarmbox-sysop panel` and `swarmbox-sysop dock ...`, the `--socket/--window/--client` options of `veto`, `approve` and `stop`, and `SWARMBOX_SYSOP_PANEL_MODE`; the panel is the one of the Web Studio and the cockpit, and `serve --dock` starts the OSC 7501 agent bridge.
- Changed: `swarmbox-tabs` has one backend, `HerdrBackend`: the error codes `no_tmux` and `tmux_error` are now `no_backend` and `backend_error`, `SB_TABS_SESSION`, `SB_TABS_SOCKET` and `TMUX`/`TMUX_TMPDIR` are gone, and `SWARMBOX_MUX` is not read. The tests of its facade run on a fake `hc` (`tests/support/tabs_support.py`).
- Removed: the tests that only exercised tmux or ttyd (the real-tmux, browser-strip, clipboard and sysop dock tests, `slow/test_tabs_real.py`) and the e2e harnesses `e2e_sysop`, `e2e_voice` and `soak_v1`, which drove a real tmux; the slow gate `SWARMBOX_TEST_REAL_TMUX` is now `SWARMBOX_TEST_REAL`, and `dev/test-slow.sh` lost `--tmux`. `tests/fast/test_guard_mux.py` now fails if anything under `container/` runs tmux or ttyd again.

## [2.2.3] - 2026-11-23

- Added: Sysop tools `box_info` (read-only disk, memory, mux, addons and nested containers), `focus_tab`, `open_tab` (a shell or an allowlisted agent, rated by the policy) and `close_tab` (always approved), backed by new `swarmbox-tabs open|focus|close` commands for the tmux and herdr backends; `list_tabs` now carries the live OSC 7501 status of each tab.
- Changed: the Sysop answers questions about the state of the box itself (what runs, what failed, what an agent answered) instead of forwarding them to an agent, replies in the user's language, and may reply in a few `- ` lines (`done` limit 240 → 1200 characters); the system prompt is mux-agnostic and keeps every behaviour the e2e runs found necessary.
- Changed: Sysop panel redesign V2 in the Herdr Web Studio (airy, borderless, calm confirmation): the conversation of the last 12 hours of goals (`turns` in the snapshot) with the user's words in a bubble, the reply as plain text under a `Sysop · ▸ N actions` line (collapsible steps), `- ` lines as rows with the tab's pixel icon and a clickable tab name, relative times and a mic mark for spoken goals; a light first screen with three suggestion prompts; the confirmation card inside the conversation (peach rail, command in a code block, violet Allow) instead of an amber card above it; the hero card is gone and the header shows the state as a word (`ready`, `working`, `confirm`). The panel also follows an active tab changed elsewhere (the Sysop's `focus_tab`, the cockpit).
- Changed: every tab a Sysop reply names (`shop-api`, `t3`, `1:shell`, "shop-api (t3)") is drawn as the same chip, with the agent's pixel icon and the name the sidebar shows, and a tab that has closed since keeps its name, dimmed (`public/tabrefs.js`); `list_tabs` gives the brain that same name, and the prompt asks it to name tabs only by it. Test results in a reply ("24 passed", "2 failed") get a quiet colour.
- Added: **New** in the Sysop header starts a new conversation (`POST /api/sysop/new` writes `conversation.json`): the panel hides the goals before it and the sysop's brain forgets them (`history.py`).
- Removed: the browser spoken feedback (TTS) toggle of the Sysop panel and Settings; voice input (local Whisper) is unchanged.

## [2.2.2] - 2026-11-23

- Added: unified transparent 4-agent isometric cube brand mark as the Herdr Web Studio SVG favicon (`/favicon.svg`, with `/favicon.ico` fallback in `container/web/herdr/server.mjs`) and matching boot splash emblem (`container/web/herdr/public/index.html`).
- Fixed: `swarmbox reset` (`cmd_reset` in `container/host/swarmbox-host`) now calls `connector_ensure` so the Cloudflare tunnel connector (`swarmbox-cloudflared`) starts automatically on reset as well as `up`, with regression coverage in `tests/fast/test_host_connector.py`.
- Fixed: eliminated visible scrolling text cascades when toggling the left sidebar or right Sysop drawer in the Herdr Web Studio by coalescing `SIGWINCH` resize repaint bursts into a single atomic WebSocket frame (`container/web/herdr/server.mjs`) and painting atomically with deduplicated `scheduleFit()` (`container/web/herdr/public/app.js`, `app.css`).

## [2.2.1] - 2026-11-23

- Added: bespoke pixel-art **SwarmBox Boot Splash** (`#sb-boot`) and reactive **Sysop Operator Mascot** in the Herdr Web Studio (`container/web/herdr/public/`):
  - Replaced the legacy ASCII BBS boot screen with a crisp 24×24 inline pixel-art isometric SwarmBox cube emblem, refined letter-spaced `SWARMBOX` wordmark, luminous hairline progress sweep, and subtle connection status.
  - Added a 16×16 state-reactive pixel-art Sysop mascot (headset, radar antenna, and expression-changing visor across `idle`, `working`, `allow?`, `done`, `failed`, and `off`) featured in a new Sysop hero card mirroring the left `AGENTS` cards, the Sysop header, and the mobile Sysop capsule.
- Added: WhatsApp-style **tap-to-record Voice Bar** on both mobile and desktop (`Speak` → borderless live recording bar with discard `×`, pulsing indicator, timer, real-time audio-reactive waveform, and `Send`), replacing press-and-hold and eliminating accidental mobile text selection (`user-select: none` / `-webkit-touch-callout: none` on UI chrome).
- Changed: simplified the mobile dock by removing the confusing manual keyboard toggle button so tapping the terminal uses the phone's native keyboard naturally (while still auto-revealing the `Esc`/`Tab`/`^C`/arrow accessory strip via `visualViewport` when the soft keyboard is open) and widening **Speak** into a generous 48 px primary pill.
- Fixed: mirrored the Sysop panel collapse button to a matching `>` chevron on desktop (`⌄` on mobile sheet) and hid the redundant `Sysop` toggle pill from the main topbar whenever the Sysop panel is already open.

## [2.2.0] - 2026-11-23

- Added: **Pixel-Art Agent Mascot Cards** and a zero-redundancy adaptive topbar in the Herdr Web Studio (`container/web/herdr/public/`):
  - Active agent tabs (`agy`, `claude`, `codex`, `opencode`, `gemini`) render as color-coded cards in the `AGENTS` sidebar section with hand-crafted 16×16 inline crisp-pixel SVG mascots (zero external assets), corner status tiles (`Z` / `⚡` / `!` / `✓`), subtle step-bob working/blocked animations, live OSC 7501 state badges (`IDLE`, `WORKING 74%`, `BLOCKED`, `DONE`), inline progress bars, hover close controls, and `Alt+1..9` shortcuts; plain shell tabs live cleanly under `SHELLS` with zero duplication, and mobile tab pills display matching 15×15 pixel icons.
  - Adaptive Focus Mode: when the sidebar is open, the single 42 px topbar displays the active session context (pixel icon, title, live status, and state badge) over a full-bleed terminal canvas and slim bottom status bar; collapsing the sidebar (`Alt+B`) automatically swaps in horizontal informative tabs with pixel icons, status dots, and `+`.
- Added: clipboard image paste (`Ctrl+V` / `Cmd+V` / `Ctrl+Shift+V`) and image drag-and-drop in the Herdr Web Studio (`POST /api/paste-image`), validating PNG, JPEG, WebP, GIF, and BMP magic bytes up to 20 MiB with same-origin enforcement, writing `0600` files to `/tmp/swarmbox/paste/` with rolling 40-file pruning, and injecting the saved container path into the active agent terminal via Bracketed Paste (with async `navigator.clipboard.read()` fallback when browsers omit image `clipboardData` items).
- Changed: minimalist chrome polish and responsive Sysop drawer default in the Herdr Web Studio — Sysop opens automatically on wide viewports (`>= 1360px`) and starts collapsed on narrower screens (`< 1360px`) while respecting manual toggles, hides the redundant healthy `herdr-core live` badge and duplicate topbar settings button when the sidebar is open, and trims header hairlines.
- Fixed: eliminated an HTTP proxy deadlock in `swarmbox-voice front` (`container/addons/voice/lib/swarmbox_voice/front.py` `_terminal()`) where buffering upstream response headers before forwarding the client request body stalled large `POST` requests (including `/api/paste-image`) larger than one TCP packet; bidirectional pumping now injects `FRAME_GUARD` in flight (`tests/fast/test_voice_front.py`).

## [2.1.1] - 2026-11-22

- Added: studio Settings panel in the Herdr Web UI (`Alt+,`, sidebar Settings button, and topbar gear icon), rendered as a desktop dialog with left navigation rail and a responsive mobile bottom sheet with horizontal section pills:
  - **Appearance** (live across all open tabs): 5 visual mini-terminal theme preview cards synced with `/api/theme` and Terminal Cockpit, terminal font size slider and stepper with live `JetBrains Mono` preview, line height density (`Compact` / `Studio` / `Airy`), cursor style (`Block` / `Bar` / `Line`), cursor blink toggle, scrollback buffer selector (`1.5k`–`10k`), and appearance reset.
  - **SwarmBox, Sysop, Voice, and Addons & System:** backed by `GET /api/config` and same-origin-guarded `POST /api/addons/:name/install` (`container/web/herdr/server.mjs` and `hc-client.mjs`), surfacing live container health, all host-managed SwarmBox/Sysop/Voice settings with a sticky bottom "Apply on host" command bar (`swarmbox config set ... && swarmbox reset` with one-click Copy and Discard), live browser TTS toggle, 3-card Sysop autonomy policy picker, one-click live addon installation, configured MCP servers, Git SSH public key copy box, and keyboard shortcuts cheat sheet.
- Fixed: pasting into the Herdr Web terminal (`Ctrl+V` / `Ctrl+Shift+V`) now uses `xterm.js` native Bracketed Paste (`\x1b[200~ ... \x1b[201~`) via `term.paste()` with zero duplicate paste, eliminating slow character-by-character redraws and premature newline execution inside TUI coding agents (`agy`, `claude`, `codex`, `opencode`).
- Added: smart wrapped-line unwrapping on copy (`Ctrl+C`, `Ctrl+Shift+C`, `Cmd+C`, and context-menu Copy) in the Herdr Web terminal (`getSmartSelection()`), inspecting `term.buffer.active` to rejoin native soft-wraps, full-width `herdr-core` wraps, and AI TUI padded/shaded/bordered code blocks back into single-line commands while preserving intentional multi-line scripts, blank lines, lists, prompts, and explicit `\` continuations.

## [2.1.0] - 2026-11-22

- Added: opt-in `herdr` multiplexer backend (`swarmbox config set MUX herdr` / `SWARMBOX_MUX=herdr`) running in parallel to the default `tmux` backend with zero regression:
  - Pinned SHA-256 `herdr-core` (`hc` 0.1.21) and `herdr` TUI (0.9.5) binaries in the image with SwarmBox Purple Glow default theme (`container/config/herdr.toml`).
  - Shell backend `container/scripts/mux/herdr.sh` and `HerdrBackend(TabsBackend)` in `swarmbox-tabs` with framed `hc connect` literal UTF-8 delivery and native OSC 7501 `tab_state()` (falling back to screen heuristics when unreported).
  - Native Herdr Web Gateway and responsive desktop + mobile Web UI (`container/web/herdr/`) with self-hosted **JetBrains Mono + Nerd Font** (`@fontsource-variable/jetbrains-mono` 5.3.0 + `@azurity/pure-nerd-font` 3.0.5, zero CDN), lightweight BBS ANSI-art boot splash with alternating color inks, 5 synchronized themes (Purple Glow default, Catppuccin Mocha, Tokyo Night, Nord, Rosé Pine), live OSC 7501 status indicators and agent badges, real `swarmbox-sysop` integration, per-tab live `xterm.js` sessions with server-coalesced zero-scroll hydration, native-feel mobile momentum touch scroll, WebSocket ping/pong keepalive + automatic PTY reconnect with buffered keystrokes, persistent font size stepper, and native `swarmbox-voice front` compatibility.
  - SwarmBox Terminal Cockpit (`container/web/herdr/cockpit.mjs`, `@xterm/headless`) launched automatically on interactive `swarmbox` / `sx` attach when `MUX=herdr` (3-pane terminal parity with Web UI: exact-width sidebar with OSC 7501 dots and inline progress, inset 24-bit PTY, right Sysop panel with framed Goal Composer, 5 synced themes, `Ctrl+A` prefix + `Alt` shortcuts + SGR mouse; set `SWARMBOX_HERDR_RAW=1` for raw `hc attach`).
  - Native OSC 7501 Sysop agent bridge (`swarmbox-sysop agent` + `HerdrBridge` + `~/.config/herdr-core/templates/sysop.md`, labeled `swarmbox.role=sysop`): visible natively in `herdr-app` Agent Inbox (working / blocked:permission / done / idle) while automatically filtered out of Web UI, Terminal Cockpit, and `swarmbox-tabs` so Sysop is never duplicated as a regular tab. See `docs/herdr-cockpit-design.md`.
- Changed: modernized the default Purple Glow Starship prompt (`container/config/starship.toml`) with a crisp violet left-accent directory band (`▍ ~/dir`), clean middle-dot dividers, semantic amber git status, command duration (`>= 2s`), compact exit status, and clean single-line fit even on 390 px mobile screens.
- Removed: retired the legacy terminal startup banner (`container/scripts/banner.sh`) across all modes so interactive shells open cleanly with startup-health warnings (if any) and the modernized Starship prompt.
- Changed: isolated `tmux` behind explicit multiplexer backend boundaries (`container/scripts/mux/`, `TabsBackend`/`TmuxBackend` in `swarmbox-tabs`, and mux-agnostic `state.py`, `actions.py`, and `ui_host.py` in `swarmbox_sysop`), enforced by a static boundary guard (`tests/fast/test_guard_mux.py`) and non-`tmux` isolation tests (`tests/fast/test_mux_isolation.py`). Default behavior (`SWARMBOX_MUX=tmux`) is unchanged.

## [2.0.24] - 2026-11-20

- Fixed: on touch screens (such as iPhone), scrolling the web terminal no longer flashes the Sysop button's border or highlight. Button `:hover` border rules are now scoped to `@media (hover: hover)` so touch gestures do not trigger sticky hover highlights, `showToast()` preserves the panel state while scrolled back in tmux copy mode, and `sysopState()` only matches the exact two-space `SYSOP  <state>` panel header at a word/pane boundary.

## [2.0.23] - 2026-11-20

- Changed: modernized the web terminal's mobile controls strip and desktop Sysop microphone bar. On a phone, the Sysop toggle and live status line are now one full-width glass capsule with an SVG chevron; the microphone button uses a violet gradient and hides its status dot while idle; the touch-key row is slimmer with grouped SVG arrows; and the keyboard button now lights up with a hide-keyboard chevron only when the phone keyboard is actually open (never falsely lit when only the Sysop drawer is open) without shrinking the Sysop capsule when the keyboard reduces viewport height. On desktop, the docked Sysop panel's microphone is now a `Speak` pill.

## [2.0.22] - 2026-11-20

- Added: the `antigravity` addon now ships its own isolated status line (`container/addons/antigravity/statusline.sh`) and `prepare.sh` that seeds `~/.gemini/antigravity-cli/settings.json` once (without overwriting user keys) with a Purple Glow status line showing current folder, git branch, active model, context usage bar and tokens, estimated cost, and quota usage, plus `colorScheme: "tokyo night"`, `allowNonWorkspaceAccess: true`, and `showFeedbackSurvey: false`. Claude Code's `swarmbox-statusline` and `~/.claude/settings.json` remain completely separate.

## [2.0.21] - 2026-11-20

- Added: the addon `antigravity`, the Antigravity CLI, Google's successor of Gemini CLI (command `agy`). `swarmbox addon install antigravity` (or `--with antigravity`, or the first `agy`) downloads the vendor's release for the architecture of the box, checks its SHA-512 against the vendor's manifest and puts the program in `~/.local/bin/agy`; the program updates itself (`agy update`), like Claude Code. The installer does not run the vendor's `install.sh`, because that edits the shell's startup files. The shell function starts `agy` with `--dangerously-skip-permissions` (not for its subcommands; `SWARMBOX_YOLO=0` turns it off), `yolo` runs it when the default agent is `antigravity` or `agy`, and `swarmbox-tabs` and the sysop know `agy` as an agent next to claude, gemini, opencode and codex. Its login and data are in `~/.gemini/` (the folder Gemini CLI uses too); on an SSH session it prints an address to log in from another browser. It is closed source (see `THIRD_PARTY_NOTICES.md`).
- Changed: the addon `gemini` is marked deprecated. Google stopped serving Gemini CLI for most accounts on 2026-06-18; it still works with a paid Gemini API key. Nothing is removed.

## [2.0.20] - 2026-11-19

- Changed: the sysop remembers the conversation. Each goal's brain gets the last 8 goals of the last 12 hours (what you said, what it typed and where, how it ended) in front of the goal, so a follow-up ("and the other one?") is understood. What you say is by default a message for an agent: the sysop infers the most likely one (the agent of the active tab, else the tab it was talking to, else the only agent) and types your words there; you never have to say "send it to Claude". Only a clear operation on the box is done by the sysop itself.
- Changed: the sysop no longer refuses to type into an agent that is working: a `run` is sent with `--queue`, and the agent queues the message. A dialog open in the agent is still left to you.
- Changed: the field of the idle sysop panel (`Type a goal`) has a blank line above it when the pane has 12 rows or more (a short pane keeps its room for the result of the goal).
- Changed: the letters on a phone are a little bigger: 58 columns held upright (was 64) and 108 sideways (was 120), so a 390 px phone gets 11 px (was 10) upright and 13 px (was 11) sideways. `swarmboxStrip.setColumns(64)` brings the old size back.
- Fixed: on a phone the lettering of the banner no longer shows thin horizontal lines across the letters. In the DOM renderer the block characters of a phone's own monospace font stop short of the row (a line gap), so a hairline of background showed between two rows; the fixed 12% stretch of 2.0.x did not close it for every font. The page now measures the font it really uses (it draws a full block, finds its ink and the baseline of a row) and stretches the rows that hold blocks so that the ink fills the row, with a little to spare. Tested with lines taller than the letters (the gap of such a font) at several pixel ratios.
- Changed: the idle sysop panel ends in a line that looks like a text field (`Type a goal`, the key `g` at the right) instead of a lone Goal button; a tap anywhere on it, or `g`, opens the editor. The idle text above it says `Say a goal, or type it below.`
- Fixed: on a phone, the sentence shown while the microphone records no longer covers the fine line at the top of the closed bar or leaves a darker patch beside the button (it takes the colour of the bar). The buttons of the bar are softer: a fainter surface and edge, a tinted microphone (red while it records) instead of a filled one, no glow on the dot of the Sysop button.
- Changed: the buttons of the closed bar of a phone are one designed set. The Sysop button, the keyboard button and the microphone are all 44 px tall with the same corners (14 px), surface and edge; the microphone is the one that is filled (violet, it is the main action) and it is no longer bigger than the others, the Sysop button is no longer a pill, and the keyboard has a drawn icon instead of the glyph (a phone may draw U+2328 as a colour emoji). Recording turns the microphone red with a ring inside it that breathes, and nothing glows outside a button any more: the halo of the old recording state was cut by the edge of the screen and looked like a patch of colour at the right of the button. A tap presses the button in (a small scale) instead of changing its background.

- Changed: the tall sysop panel at the right edge of a desktop has a bar of buttons under its title. The title is the same dark purple bar as on a phone, the two lines under it (from 14 lines of panel, at most 80 columns wide) are a slightly lighter band that the page draws, followed by a line of space before the content, and the microphone, which floated in the top right corner over the head of the panel, sits in that band at the right, with the same space above, below and at the right. More buttons can go there later. The whole panel has the tint of the phone's drawer (a dark violet a little lighter than the terminal). Without a panel, or when it has no room for the bar, the microphone stays in the corner. The room for the bar is only made when the browser used the window last: with a terminal (ssh) there is no page to draw it, so the panel leaves one blank line under the title and nothing more (the panel looks at the tmux client that was active last: the one that `swarmbox-attach --web` starts says so in its environment with `SWARMBOX_WEB_CLIENT`, and ttyd is its parent).

## [2.0.19] - 2026-11-19

- Changed: the sysop looks finished on a phone. The panel and the strip under it are one drawer: the same dark violet, a little lighter than the terminal, a fine gradient line where the border of tmux was, and a dim line under the head of the panel (SYSOP ... close). The tabs of tmux go to the top of a window of 80 columns or fewer, above the sysop panel and the work, and come down again when a wider client takes the window. A desktop looks as it did. The panel of a phone has a blank line under its head (SYSOP ... close) when it is 7 rows tall or more, so the content is not stuck to the title. Its head line is a bar of a dark purple (`#2a1a52`) edge to edge, to stand out and part the panel from the terminal above.

## [2.0.18] - 2026-11-19

- Changed: the logo of the loading page is the word alone: no tagline and no segmented bar under it, and it takes about 60% of the width of the screen (it was the width of the screen, with the bar and `// your agent's shell, from anywhere` under it).

## [2.0.17] - 2026-11-19

- Fixed: the lettering of the loading page was soft (a font draws block characters with its own line height and anti-aliasing). The letters are now drawn as squares of whole device pixels (an SVG, one half block each), as sharp as in `banner.sh`, with the same gradient and glint, and sized again when the phone has its viewport.

## [2.0.16] - 2026-11-18

- Changed: a cleaner sysop on a phone. In a window of 80 columns or fewer (a phone held upright) the operator panel is **closed** by default and the strip under the terminal is **compact**: a **Sysop button** (a light for the state and an arrow that says which way it opens; filled while the panel is open), **one line with what the sysop is doing** (two lines at most; "idle" when it has nothing to do) and the microphone. The key buttons are **one slim row** (Esc, Tab, ^C and the arrows) that opens by itself with the panel, and a ⌨ button shows it when the panel is closed. What needs a yes or a no is a **separate small approval panel** (the risk, the action, a big Allow and a big Cancel) that opens only while an action waits and closes a second after the answer. A wide window (a computer) is as before. The line travels as the title of the terminal (`set-titles on` in `tmux.conf`, the option `@sysop_line`, `sysop:<state>:<sentence>`), which the page reads off the connection, so a reload knows it at once; a terminal that attaches to the session now shows tmux's usual title. A narrow desktop window counts as a phone. Needs `swarmbox update` and `swarmbox reset` (the sysop addon refreshes itself).
- Changed: the keyboard of the phone no longer opens at every tap on the terminal. On a touch screen the terminal takes the focus without it (Chrome: `virtualkeyboardpolicy="manual"`, and ONE **keyboard button** (the ⌨ of the compact bar, or the tall one at the right of the keys in the usual strip) opens the row of keys and the keyboard of the phone together, is lit while they are open, closes both on the next tap and follows the real keyboard; it calls `navigator.virtualKeyboard.show()`, tries again with a fresh focus and then with a plain text field if the keyboard does not come; elsewhere `inputmode="none"` until Aa makes it a text field; the key buttons and a hardware keyboard type either way).
- Added: the page is black with the banner of the box while it loads (the lettering of `banner.sh`, in the style of a 90s BBS login screen: half blocks in the font of the terminal, the same gradient from dark gray and purple to white, the bar, the signature and a glint that sweeps across), and fades out only when the page has settled (the screen, font, size and strip stopped changing), so nothing is seen reorganising behind it.
- Changed: the page presses Enter by itself when ttyd says "Press ⏎ to Reconnect", so coming back to the page is enough.
- Fixed: two fingers zoom the page again on a phone (the finger scroll had turned every gesture on the terminal off, the pinch too): the terminal now leaves the pinch to the browser and takes only the single finger.
- Fixed: scrolling with a finger on a phone was slow and uneven. The text now goes further the faster the finger moves (2 to 8 times its distance), keeps going a little after a flick and slows down by itself, the wheel events are given out a few per frame, and a stretch of a screenful or more goes as one PageUp or PageDown key, as on a computer, instead of a dozen wheel events, and a slow finger is followed line by line (Ctrl+Up and Ctrl+Down of tmux in copy mode) and not in jumps of five lines. The Panel switch no longer lights up and goes out as the history scrolls by: it reads the word SYSOP only where it is bold and coloured, as in the panel, and is left alone while a tab is scrolled back.
## [2.0.15] - 2026-11-18

- Fixed: on a phone, dragging a finger over the terminal did nothing, so the history of tmux could not be reached (the mouse wheel of a computer worked, but a finger makes no wheel event, and the history of the browser is off on purpose). A vertical drag is now turned into the wheel events a mouse would make, at the place of the finger, one per 5 rows, so the pane under it scrolls (a tab goes into copy mode, the log of the sysop panel moves); a tap is left alone.

## [2.0.14] - 2026-11-17

- Changed: what you install on demand (agents such as Claude Code, and gcloud, clasp, Go, Poetry, `voice`, `sysop`) is called an **addon**: `swarmbox addon list|install|remove|update|use|link|prepare|run|where|doctor|validate|new` (`swarmbox-addon` in the box), manifests in `container/addons/<name>/addon.conf`, with the commands of the addon in `COMMANDS` and its start-up in an optional `shell.sh` (the auto-approve flags of the agents live there: `claude` adds them only to the interactive prompt, so `claude update` and `claude mcp ...` do not get them). `yolo` runs the default agent, `AGENT` or else the first item of `WITH`, and says so when there is none. Needs `swarmbox update` and `swarmbox reset`, and addons are installed again on first use.
- Added: talk to your box, typed or spoken (the `sysop` addon and the `voice` addon). Give a goal in plain words ("run the tests in the second tab", "ask Claude in the active tab to fix the failing test") and the **sysop** operates the box for you: it looks at your tmux tabs, types into them, looks again and tells you what happened
  (`swarmbox addon install sysop`, and `swarmbox addon install voice` for the microphone; `docs/sysop.md`, `docs/voice.md`). It is optional and made of separate pieces that know nothing of each other; a box that installs none of them behaves as before.
  - **`sysop`** takes the goals of its topic, runs a brain (`claude -p` by default with every built-in tool off, so it needs the `claude` addon and a login, or any command that speaks MCP, `sysop.brain`) and gives it seven tools (`list_tabs`, `read_tab`, `run`, `input`, `wait`, `say`, `done`) that act only through `swarmbox-tabs`, so whatever it does is typed in a tab you can see.
    The host rates every `run` and `input`: a low risk goes at once (the default level `auto`), a medium one waits a few seconds for your veto, a high one waits for you to press Allow, a text that starts with `/` or `!` for an agent is refused, any key while a dialog of an agent is open is a high risk, and no autonomy level skips the approval of a high risk.
    It has step and time budgets, a stop command and an append-only audit file (kept to 32 MiB). Text read from a tab is treated as untrusted data. `swarmbox-sysop goal --wait "text"` gives a goal from a shell (exit 3 when nobody listens, 4 when the bus does not answer), `swarmbox-sysop status` shows the service and the last goals.
    The service runs under a small watcher: if it dies, it starts again by itself after 1, 2, 4 ... 30 seconds, and goals that were in flight are marked `failed`.
  - **The panel** is a pane of your tmux session that shows the goal, the log, the countdown and the approval prompt, and **never takes the focus on its own**: what you type keeps going to your tab. `sysop.panel` says when it is there: `always` (default: in every window from the start of the box, idle when there is no goal, at the right in a wide window and at the bottom in a narrow or portrait one),
    `auto` (it opens in the window you look at when a goal arrives and closes a few seconds after the last one) or `off` (never, unless you open it). Veto, stop, approve and type a goal are tmux prefix keys that work from any tab: `Ctrl+A` then `V`, `X`, `a`, `g`; `Ctrl+A` then `S` shows or hides the panel. A click on the panel gives it the focus and its own keys.
    A window never stays with only the panel in it. The panel is the only thing of the sysop in your tabs; it is code of this repository and downloads nothing.
  - **`voice`** is an input only. The web terminal gets a microphone button (hold, speak, release); Whisper (`whisper.cpp`, built inside the box, one multilingual model, `small` by default) turns the audio into text and publishes it as a goal on a bus topic. Only audio crosses the Cloudflare tunnel, through a fixed table of four routes on the web port.
    The page shows a state light and a short sentence only (`Sent`, `Nothing heard`, `Nobody is listening`, `Busy`, an error such as "The microphone needs https or localhost."), never the text. `swarmbox-voice say "text"` publishes a goal without a microphone. It does not plan, does not show a plan and does not touch tmux.
  - **The controls strip** is new in the web terminal: a slim bar under the terminal (the terminal is refitted above it, so it never covers the status bar and its clock) with **key buttons** for a phone, which has no Esc, Tab, Ctrl+C or arrows (`Esc`, `Tab`, `^C`, the arrows and `Panel`, which types `Ctrl+A S`; at least 44 px, they keep the focus in the terminal so the keyboard stays open),
    and a place at its right end where an addon puts its control (the microphone). The page also has a viewport meta tag now (a phone used to lay it out 980 px wide) and follows the on-screen keyboard. The strip also has green `Allow` and red `Cancel` buttons to answer the sysop with a thumb (on a desktop with only the microphone there is no bar: the microphone floats in the top right corner and takes no space), and it refuses to build itself inside a frame of another site (the front adds `frame-ancestors 'self'`). In `web-terminal.conf`: `strip=auto|on|off` (the buttons show on a touch screen or when you list them; the strip shows on any screen once the microphone is there) and `stripKeys=label=keys, ...` in tmux key names (`C-a S`, `F5`, ...); `swarmbox-web restart` applies them. With the strip hidden the page is exactly ttyd's, as before.
  - **The bus** (`swarmbox bus pub|sub|topics|watch|ping|restart`, `swarmbox-bus --help` in the box) is plain publish and subscribe inside the box, started and supervised at box start; nothing else depends on it. A topic is a free name that addons take from their settings; a message goes to every subscriber, and subscribers that give the same `--group` share the work, one member per message.
    Nothing is kept: the bus has no state, no reads and no tmux in it. `pub` prints how many subscribers received the message and exits 3 when nobody did (`--allow-none` accepts that), 7 when one is behind. The socket is private to your user.
  - **`swarmbox-tabs`** (`swarmbox tabs list|active|screen|send`) is the tmux tabs of the box as a capability of the host, called directly and never through a topic: it lists the tabs, says which one is active, reads one with the secrets removed (keys, tokens, a JWT, a run of 120 or more base64 characters; the colours of the screen as `[sel]`, `[bg]` and `[err]` spans),
    and types into one, the text and the Enter as separate steps under a lock per tab. It refuses a busy agent, an open dialog and a text that starts with `/` or `!` unless told otherwise. No daemon; every answer is JSON and errors are `{"err", "msg"}`.
  - **Settings** (all applied by `swarmbox reset`; one that equals its default is not passed to the box, so a box that never sets one keeps its fingerprint): `voice.topic` and `sysop.topic` (both `goal`: the same name is the only link between the two addons), `sysop.group` (`sysop`), `sysop.panel` (`always`; `auto` or `off`), `sysop.brain` (`claude`), `sysop.model` (`sonnet`; `haiku` is quicker and cheaper),
    `sysop.autonomy` (`auto`; `confirm-all` or `confirm-risky`), `sysop.countdown` (`4`), `sysop.max_steps` (`20`), `sysop.max_seconds` (`300`), and for the voice addon `voice.language` (`auto`), `voice.stt.model` (`small`), `voice.stt.vocabulary` (empty) and `voice.web` (`1`; `0` turns the voice front off). They reach the box as `SWARMBOX_VOICE_*` and `SWARMBOX_SYSOP_*`.
  - **Breaking:** `bus` and `tabs` are now words of the `swarmbox` script, so a program of the box called `bus` or `tabs` runs as `swarmbox attach bus` or `swarmbox attach tabs` (inside the box, `tabs` is swarmbox-tabs only as `swarmbox-tabs`; the system `tabs` utility for tab stops is not shadowed). The default tmux config binds the prefix keys `S`, `V`, `X`, `a` and `g`; a binding of yours in `~/.tmux.conf` is read after it and wins.
  Tested end to end in Podman with a real Claude Code in a tab and a headless browser whose microphone plays speech, and under a soak of faults (killed services, a full disk, bursts of resizes and goals); not tried with a human voice or a real phone. **Needs `swarmbox update` and `swarmbox reset`.**
- Fixed: nested Podman failed with `fuse: device not found` and `kernel does not support overlay fs` after some other run of Podman in the box (one `podman --root /tmp/...`, or a run with another `HOME`) had made it fall back to `fuse-overlayfs`, which the box has no `/dev/fuse` to run. The start of the box now removes that stale marker when `/dev/fuse` is not usable; to repair a running box, `rm -rf /tmp/storage-run-$(id -u) ~/.local/share/containers/storage/overlay/.has-mount-program` (`docs/nested-podman.md`). Needs `swarmbox update` and `swarmbox reset`.
- Fixed: a link that Claude Code shows as a label (an OSC 8 hyperlink) did nothing when clicked, in the browser and in a host terminal: tmux dropped the address of the link for `xterm*` clients, so only the label arrived. The tmux config now turns on the `hyperlinks` feature.
- Fixed: nested Podman did not start on macOS (the state folder is a shared drive that cannot hold a unix socket: the service now listens on the box's own disk) nor after a host reboot (`/tmp/podman-run-<uid>` also held the old boot ID).
- Changed: the sysop panel ends a goal with two or three whole lines, not a long result: the brain is told to summarize in two short sentences in its own words, a longer summary is sent back to it once to be written again, and only a runaway one is cut on the panel.
- Changed: on a phone the letters of the web terminal follow the width instead of a fixed 21 px: `(width - 20) / (columns * 0.6)` with 64 columns upright and 120 sideways, between 7 px and the configured `fontSize` (a 390 px phone: 10 px upright, 11 sideways; a size you set yourself in the console is left alone; `swarmboxStrip.setColumns(n)` in the browser console tries another target). A screen with a mouse wider than 600 px keeps the configured size.
- Fixed: on a phone the lines ran behind the right edge and the prompt was out of sight (tmux said, for instance, 193x99 while the page showed 123 columns): tmux sizes a window by the client that last had focus, so the terminal of the host (or another tab) that got focus after the page left the window at its width. The page now sends tmux the focus report when it is looked at (focus, visible again, a tap, after a resize), which makes the window follow it again.
- Fixed: on a phone the web terminal drew its letters at twice the width of its grid (so 123 columns did not fit the screen, lines seemed not to wrap and the font looked big whatever the size): the default renderer of ttyd, WebGL, misdrew the letters after the font size changed. The box now sets `rendererType=canvas`; `rendererType=webgl` in `web-terminal.conf` brings the old one back.
- Fixed: on a phone tmux was told 28 columns and then 123 at every refresh, and the letters were sometimes drawn at the wrong width: the font was changed after ttyd had applied its own. The page now sits in the head and rewrites the settings message of ttyd on its way in, so the terminal is measured once with the size that fits the screen.
- Fixed: on a phone, or in the device mode of Chrome, the letters were painted at 2 or 3 times the width of the grid (a canvas of 467 px for 374 css px at a pixel ratio of 2.625), so the columns did not fit the screen and lines seemed not to wrap. A phone (a touch screen, or a window up to 600 px wide) now gets the DOM renderer of xterm.js, chosen in the settings message of ttyd; a wide window keeps `rendererType=canvas`.
- Fixed: tmux was told a width with the room of a scrollbar and, a moment later, the real one (the blink 58 columns, then 61): the settings message of ttyd is rewritten with `scrollback` before `fontSize`.
- Changed: the buttons of the controls strip on a phone. `Allow` (filled violet, breathing while the sysop asks for it) and `Cancel` (outlined violet) replace the green and red, and they are dim and do nothing until the sysop waits for them: the page reads the head of the sysop panel off the screen (`allow?`, `sending`, `working`). The four arrows stay together on one line, the answers come first in the default `stripKeys`, and ttyd's box with the size of the terminal (the `61x66` that flashed at every resize) is off (`disableResizeOverlay=false` in `web-terminal.conf` brings it back).
- Changed: `Panel` on the strip is a switch, not a key: a pill with a light that is lit while the sysop panel is on the screen.
- Fixed: on a phone (DOM renderer) a hairline of background cut across the letters of the banner between two rows of block characters. The rows that hold block characters (U+2580 to U+259F) are drawn 12% taller, which closes it (two dark rows of pixels before, none after, measured in Chrome at a pixel ratio of 2.625).
- Changed: the default keys of the strip on a phone are a grid of five equal columns and two rows: `Allow` over `Cancel` on the left, `Esc`, `Tab`, `^C` and `Panel` on the first row and the four arrows under them, so every edge of one row is the edge of a key in the other (at 360, 390 and 412 px wide with the microphone beside them). A phone turned sideways keeps the single scrolling row; a list of your own in `stripKeys` keeps the plain flowing row.
- Changed: the logs of the box (`serve.log`, `bus.log`, `web-terminal.log`, `podman-service.log`) no longer grow for ever: every five minutes one that is past 4 MiB is cut to its last megabyte, with a line that says so. Needs `swarmbox update` and `swarmbox reset`.
- Fixed: `Ctrl+A a`, which `docs/web-terminal.md` gave for sending the prefix to a nested tmux, is `Ctrl+A Ctrl+A`.
- Added: `swarmbox-addon where NAME COMMAND`, which prints the real program of a complete install without installing anything.
- Dev only: `tests/e2e/e2e_sysop.sh` and `tests/e2e/e2e_voice.sh` (the real pieces, a real Claude Code and a headless browser, in Podman), `tests/e2e/soak_v1.sh` (the soak and fault run) and the real-tmux tests (`SWARMBOX_TEST_REAL_TMUX=1`) are not part of `dev/check.sh`.
- Dev only: the tests live in `tests/fast`, `tests/slow` (real tmux, browser, Podman) and `tests/e2e`, run by one runner, `sh tests/run.sh` (the fast ones, in parallel, by default); `dev/check.sh` and the pre-push hook run the fast ones, `sh dev/test-slow.sh` runs the slow ones in Podman, and `dev/mutate.py` measures what the tests would notice (`tests/README.md`).

## [2.0.13] - 2026-11-13

- Fixed: the colors of the Claude Code theme came out wrong inside tmux. Claude Code caps itself at 256 colors there unless `CLAUDE_CODE_TMUX_TRUECOLOR` is set, and turned every exact color into the nearest of 256 with a rough formula: the rose of an error
  (`#ff6b78`) came out as a salmon (`#ff8787`), and the grays of the borders were off. The shell of the box now sets it, because the tmux of the box declares RGB. Set it empty in your `~/.bashrc` to go back to 256. Needs `swarmbox update` and
  `swarmbox reset`.
- Added: `swarmbox-statusline`, a status line for Claude Code in the style of the box: `╶─ …/swarmbox ─ main ! ─ Sonnet 5.5 ─ ▰▰▰▱▱▱▱▱▱▱ 34% ─ 5h 71%`, the context as a bar that is violet, fuchsia from 70% and rose from 90%, and the usage limits when
  Claude Code reports them. It is not on by default: put `"statusLine": {"type": "command", "command": "swarmbox-statusline"}` in `~/.claude/settings.json`.
- Changed: the whole box is in one palette, the purple glow (`docs/theme.md`). The browser terminal has new colors: a near-black background (`#0c0b10`), `#d4d4d8` text, a lavender cursor and a violet selection, and its 16 colors are
  tones of the same family (blue is a violet, so what a program paints blue is violet; red, green and yellow keep their meaning). `ls` (folders violet, links lavender) and `grep` (the match lavender) use 256-colour numbers, so they look
  the same in any terminal scheme, and the messages of the scripts use two fixed grays; the scrollbar of the browser is violet. `theme=` in `web-terminal.conf` still replaces the whole theme of the browser terminal, and `LS_COLORS` and
  `GREP_COLORS` in your `~/.bashrc` still win. New in `docs/theme/`: a color scheme for Windows Terminal and one for Ghostty with the same palette, so the terminal you run the box in can match it, and the theme of Claude Code
  (`custom:swarmbox-purple-glow`, 29 colors: the selection, permissions, suggestions, the prompt box, user messages, Claude's orange, and the tones of errors, successes and warnings). Needs `swarmbox update` and `swarmbox reset`.
- Changed: a selection made in the web terminal with the browser's own selection (Shift and drag, which skips tmux) is the violet of the box (`#6d28d9`, light text), the same as tmux's, and no longer the steel blue of the old theme. A selection made
  by dragging with the mouse is tmux's and was already violet. A program that takes the mouse for itself (a full-screen TUI) draws its own selection in its own colors; that is not tmux's and not ours. Needs `swarmbox update` and `swarmbox reset`.
- Changed: the line under the banner now says what the box is for: `// your agent's shell, from anywhere` (it was `// agent box`). It is in the dark grays of the box, with the `//` darkest and the last word darkening letter by letter.
  Needs `swarmbox update` and `swarmbox reset`.

## [2.0.12] - 2026-11-13

- Fixed: the glint of the banner. A pass from left to right stopped one step too soon and left one cell of the last row a shade lighter until the next pass; it now ends past the last column. And a step no longer rewrites the three rows whole: it writes
  only the cells that change (about 210 bytes a step in place of 940, and about five times less for tmux to send to the terminal), which should help a terminal that draws while it is still receiving. It was reported as flicker of little white
  blocks in Ghostty on a Mac; that is not reproduced here, so whether it is gone is for you to say. New: `set -g @swarmbox-glint off` in your `~/.tmux.conf` turns the glint off, and `tmux set -g @swarmbox-glint off` (or `on`) does it at once, in a
  box that is already open. Needs `swarmbox update` and `swarmbox reset`.
- Changed: the progress line of `swarmbox update` (and of the first pull) is minimal and in the violet and gray of the box: `pull  ▰▰▰▰▰▰▱▱▱▱▱▱▱▱▱▱ 42%  130/310 MB · 4.1 MB/s 32s`, the filled part of the bar in violet and the rest in dark gray, and a
  `✓ pulled <image> · 310 MB in 1m05s` that stays when it is done. The four colored blocks, the powerline arrows and the icon are gone, and so is `SWARMBOX_ICONS`: nothing in the line needs a Nerd Font any more. As before, a narrow
  terminal drops the right-hand parts, `NO_COLOR=1` turns the colors off, a locale without UTF-8 gives `#` and `-`, and `SWARMBOX_PROGRESS=plain` leaves Podman's own bars.

## [2.0.11] - 2026-11-13

- Changed: the banner is lighter. The half-block lettering keeps its dark gray and purple glow, but the rounded frame and the two tagline lines are gone: under the letters there is now a segmented bar that lights up
  like them, and a dim `// agent box` on the right. The glint that crosses the letters in a tmux pane is the same. Needs `swarmbox update` and `swarmbox reset`.
- Changed: the prompt is one line again, in the style of the banner: thin gray `─` separators, the user, the directory, the branch, the language, the Docker context and the time in gray and violet, the directory on a soft band whose edges fade in and out with `░▒▓` like the old BBS screens, and a violet `❯` at the end. There is a blank line above every prompt, so one command does not stick to the output of the one before (the banner lost its own blank line at the bottom for it). It no
  longer uses any Nerd Font glyph (the language symbols are short words such as `py`, `go` and `node`), so it looks the same in any terminal font. The colored ribbon is gone. A `~/.config/starship.toml` of your own is untouched
  and still wins. Needs `swarmbox update` and `swarmbox reset`.
- Changed: the tmux theme follows the banner and the prompt: dark gray and violet instead of the pastel one. The current window sits on the same soft band as the directory of the prompt, with a dithered `▒` at each edge; the other windows,
  the date and the time are gray with thin `─` dashes, and every window is the same width, so nothing moves when you change window. The session name is no longer shown. The active pane border and the copy-mode selection are violet.
  The `[+]` button keeps its first three columns, now in gray. Put your own `set -g status-style ...` and the like in `~/.tmux.conf`, which is read after this file. Needs `swarmbox update` and `swarmbox reset`.
- Changed: the tmux scrollbar is off by default. The pane keeps its whole width; in copy mode tmux still shows where you are (`[position/total]`) and the wheel scrolls 5 lines per event.
  `set -g pane-scrollbars on` in your `~/.tmux.conf` brings the bar back. Needs `swarmbox update` and `swarmbox reset`.
- Dev only: `dev/local-up.sh` builds the image from the checkout and switches your box to it in one command (and `--release` goes back to the published image), so a change can be tried without a release.

## [2.0.10] - 2026-11-12

- Changed: a new banner. Half-block lettering in a rounded frame, like the login screen of a 90s BBS, in a gradient that runs across the whole word: dark gray and purple that light up to white in the middle and fade
  out again. In a tmux pane, which is where the box always runs, a glint crosses the letters back and forth every few seconds, from a background process, so the shell never waits for it. It writes only
  when the screen has been still, skips a frame if anything moved, and stops when the banner has scrolled away or been cleared; outside tmux there is no glint. It needs 256 colours. Needs `swarmbox update` and `swarmbox reset`.
- Changed: the prompt follows the banner: its segments go from dark gray through purple and back to gray, with one light text colour on all of them. The roles of the palette in `starship.toml` changed (`color_text` is the text colour);
  a `~/.config/starship.toml` of your own is untouched and still wins. Needs `swarmbox update` and `swarmbox reset`.
- Dev only: `banner.sh` is in the shellcheck list of the CI; a comment and a line of `design.md` no longer say that the pull progress bar follows the colours of the prompt.
- Changed: the thumb of the tmux scrollbar is dimmer (a dark gray, `colour238`, on a transparent track), so the bar is there when you look for it and out of the way when you do not. It is already one column, the least tmux
  allows. Change it with `set -g pane-scrollbars-style "bg=default,fg=colourNNN,width=1"` in your `~/.tmux.conf` (236 nearly vanishes, 243 is the lighter gray of 2.0.9). Needs `swarmbox update` and `swarmbox reset`.

## [2.0.9] - 2026-11-12

- Added: tmux has a scrollbar again, and this one works: a thin bar on the right of the pane, showing where you are in the 50,000 lines of history; drag it with the mouse or click its track.
  It is one column wide and always on, on purpose: a bar that showed only while scrolling would resize the pane each time, and a program with columns would reflow while you read. A full-screen program
  (vim, less, a TUI) gets the whole width and no bar, and one that asks for the mouse gets the wheel itself. The image now carries tmux 3.7c (Debian 13 has 3.5a, which has no scrollbar),
  a Debian backport pinned by SHA-256 so every build gets the same file. `set -g pane-scrollbars off` (or `modal`) in your `~/.tmux.conf` changes it. Needs `swarmbox update` and `swarmbox reset`.

## [2.0.8] - 2026-11-12

- Changed: a tab that leaves and comes back (`exit`, then `swarmbox` again in the same terminal tab) is now put back in the same place in the browser, not at the end. The host passes the
  `tty` of the terminal tab, which names it in any terminal or over ssh, and the box keeps the host tabs in the order they first appeared. Dragging the tabs of your terminal is not followed,
  and a window opened from the browser (`Alt+N`) can end up on either side of a returning tab. Needs `swarmbox update` and `swarmbox reset`.
## [2.0.7] - 2026-11-11

- Changed: `exit` in a host terminal tab now ends `swarmbox` and returns you to your own shell. Before, with two tabs open, it closed the window and moved you to the
  shell of the other tab. Each tab has a session of its own with its window linked into the box's session, so the browser still shows every tab, and closing a host tab
  only detaches (the window keeps running and stays in the browser). Needs `swarmbox update` and `swarmbox reset`.
- Dev only: a local gate (`dev/check.sh` and a pre-push hook) and `dev/release.sh`, which releases from a CHANGELOG written beforehand; see CONTRIBUTING.md.

## [2.0.6] - 2026-11-11

- Changed: the web terminal has no scrollbar by default. tmux owns the scrollback (50,000 lines) and the browser has no history of its own, so the bar sat still while the wheel
  scrolled tmux. `scrollbar=true` in `web-terminal.conf` brings back the thin one. Without the bar the browser keeps no scrollback (`scrollback=0` unless you set one): xterm.js reserves
  15 px for a scrollbar it measures as zero width, which cost a column of text.
- Changed: the mouse wheel scrolls tmux's copy mode 5 lines per event (tmux's default) instead of 2. How to change it is in `docs/web-terminal.md`.
- Tests: the browser tests of the web terminal now start ttyd with the options `swarmbox-web run` builds, as in the box, and a real tmux checks the lines per wheel event.

## [2.0.5] - 2026-11-11

- Added: a progress line for the image pull in `swarmbox update`, the first `swarmbox` and the installer, in the colors of the prompt of the box: `[ pull ][ bar and percentage ][ MB done/total ][ MB/s and time ]`,
  and `unpack` when the download is over and Podman writes the layers out. The bytes come from Podman's temporary download folder and the total from the layer sizes of the manifest on `ghcr.io`
  (read with `curl` in the background; without it the bar sweeps and shows no percentage). Powerline separators and an icon are on when Starship runs in your shell (`SWARMBOX_ICONS=1` or `0` forces them);
  `NO_COLOR=1` turns the colors off; `SWARMBOX_PROGRESS=plain` goes back to Podman's own bars; without a terminal the pull stays quiet. A failed pull shows the last lines of Podman's error.

## [2.0.4] - 2026-11-11

- Added: the installers (`install.sh` and `podman run IMAGE install | sh`) write `sx`, a short name for `swarmbox` (`sx up`, `sx claude`), next to the script.
  It is a two-line script that runs the `swarmbox` beside it, so `swarmbox update` keeps working and `sx` always follows it.
  It is written only when nothing else answers to `sx`: no other file of that name in the folder and no `sx` anywhere on the `PATH`
  (a startx replacement has that name); an existing `sx` is never touched and the installer says why none was written. `SWARMBOX_NO_SX=1` skips it.
  A box that is only updated does not get it: run the installer again.

## [2.0.3] - 2026-11-11

- Fixed: `swarmbox update`, the first `swarmbox` and the installer (`install.sh`, `podman run IMAGE install | sh`) showed no progress while they pulled the image, so they looked stuck.
  When standard error is a terminal the pull now shows Podman's own progress, and a failed pull points at the error already on screen. Without a terminal (a script, a log) the pull stays quiet as before.
- The installer now pulls the image in its own step, with the message "pulling IMAGE (this can take a while)...", before it reads the support files from it.

## [2.0.2] - 2026-11-11

Fixes the nested Podman not starting after a host reboot.

- Fixed: after a host reboot the box is stopped and later started again with its own filesystem intact. The nested Podman keeps its runtime state in
  `/tmp/storage-run-<uid>` inside that filesystem, with the boot ID of the previous boot, and refused to start: "current system boot ID differs from cached boot ID;
  an unhandled reboot has occurred". `serve` now removes that folder before it starts the nested service, when it exists, and says so in `serve.log`.
  Nothing of a previous run is alive when `serve` starts, and the nested images and containers are in the volume, not in that folder.

## [2.0.1] - 2026-11-11

Fixes a box that never became ready after a host reboot.

- Fixed: after a host reboot the box's run folder (`/tmp/swarmbox`, a tmpfs) could come back as a folder the agent user cannot write. `serve` then could not write the
  readiness marker or the ttyd pid file, the web terminal gave up after five crashes, and `swarmbox` waited 60 s and failed with "the box did not become ready".
  `serve` now checks the folder first and, when it is not writable, makes it writable with `sudo chmod 1777` (the agent has sudo in the box) and says so in `serve.log`.
- When the box is running but never writes its readiness marker, `swarmbox` now prints the last 15 lines of the box's log before it exits with status 6, so the cause is on screen.
- The cause of the unwritable folder after a reboot is not known; if the nested Podman service still does not start after this fix, send `podman-service.log`.

## [2.0.0] - 2026-11-11

First stable version. Same feature set as the two prereleases (below), with these changes since 2.0.0-beta.2:

- The README now walks through the install from zero with Claude Code (Podman, the installer, the login, the first run) and through remote access to the same tmux session (from a browser with Cloudflare, or over SSH to your machine).
- The image is published at `ghcr.io/feroult/swarmbox` with the tags `2.0.0`, `2.0` and `latest`; `swarmbox update` follows the `2.0` series.

### Features

- One persistent rootless Podman box per workspace; every terminal tab and the browser join the same tmux session.
- A small neutral image (`node:24-trixie-slim`, user `agent`, about 1.75 GB) with no agent inside. Claude Code, Gemini CLI, OpenCode, gcloud, clasp, Go and Poetry
  install on first use from manifests, through shims, with pinned versions and checksums where the vendor publishes them.
- The workspace is one folder of your machine and holds projects, logins, the SSH key and installed tools; the box can be recreated without loss (`swarmbox reset`).
- One executable POSIX `sh` script, `swarmbox`, on the `PATH` (no shell function, no startup file): `up`, `stop`, `reset`, `url`, `update`, `config`, `env`, `pubkey`, `tool`, `remote`, `fingerprint`, `version`; any other word runs in the box.
- Two ways to install it, with the same result: `podman run --rm IMAGE install [--with TOOLS] | sh`, and `install.sh`, which downloads `swarmbox` from a release and checks its sha256. The release attaches `swarmbox`, `swarmbox.sha256` and `install.sh`.
- `swarmbox <command>` runs a command in the box and returns its exit status; `--plain` skips tmux.
- Creation settings in one host file, compared on every entry by a fingerprint; variables are passed by name at creation and never written to disk.
- Nested Podman, always on, with the host connection (`podman -c`) and a short-symlink fallback for long socket paths.
- A web terminal (ttyd and tmux) on `127.0.0.1`, supervised inside the box; optional remote access with Cloudflare Tunnel and Access (`swarmbox remote setup|status|off|token`),
  with the credentials and the connector on the host.
- Chrome DevTools MCP with Chromium in the image, written to the MCP configuration of the agents.
- `swarmbox update [--to TAG]` refreshes the script from the new image (never by an older one) and uses an exact local tag, so a later `reset` works offline and a rollback is one command.
- No telemetry; logs stay on your machine.
- XDG-aware paths on the host and in the box.
- `LICENSE` (Apache-2.0), `THIRD_PARTY_NOTICES.md`, `CONTRIBUTING.md`, `SECURITY.md`, `CODE_OF_CONDUCT.md`, a CI workflow and a signed multi-arch release workflow.

### Known limits

macOS with a real Podman machine, Podman older than 4.3, a host user other than UID 1000 and the real Cloudflare setup are not verified. A container shares the host kernel:
see [SECURITY.md](SECURITY.md) and [docs/microvm.md](docs/microvm.md).

## [2.0.0-beta.2] - 2026-11-11

Second prerelease of 2.0.0, tagged `2.0.0-beta.2` only. Install it with `sh install.sh --version 2.0.0-beta.2`, or move from a
beta.1 box with `swarmbox update --to 2.0.0-beta.2`. Changes since beta.1:

- Fixed: with `BROWSER_URL` set, the Chrome DevTools MCP now attaches to that browser. `swarmbox-mcp` read a variable the host never
  passes (`BROWSER_URL`) instead of `SWARMBOX_BROWSER_URL`, so the generated MCP file kept the headless Chromium of the box.
- The web terminal treats Option as Meta on a Mac, so Option+1..9 and Option+N change and open tmux windows (`macOptionIsMeta=false`
  in `web-terminal.conf` brings the special characters back).
- The `tmux` status bar stays visible in the browser, so every window is listed.
- macOS test and CI fixes (macos-15 runner, tests run one by one).

## [2.0.0-beta.1] - 2026-11-11

First public prerelease of 2.0.0, for testing before the final release. The image is tagged `2.0.0-beta.1` only (never `2.0` or
`latest`) and the GitHub release is marked as a prerelease. Install it with `sh install.sh --version 2.0.0-beta.1`;
`swarmbox update` follows the `2.0` series, which exists only once 2.0.0 is out, so until then move between betas with
`swarmbox update --to TAG`. The feature list is the one of 2.0.0 below. Changes while preparing it: the base image is
`node:24-trixie-slim` (Debian 13) with Podman 5.4; `criu` and its `python3-protobuf` are removed from the image; the Go
standard library findings that Debian 13 has not fixed yet are listed, with the reasons, in `.grype.yaml`.

[2.3.0]: https://github.com/feroult/swarmbox/releases/tag/v2.3.0
[2.2.3]: https://github.com/feroult/swarmbox/releases/tag/v2.2.3
[2.2.2]: https://github.com/feroult/swarmbox/releases/tag/v2.2.2
[2.2.1]: https://github.com/feroult/swarmbox/releases/tag/v2.2.1
[2.2.0]: https://github.com/feroult/swarmbox/releases/tag/v2.2.0
[2.1.1]: https://github.com/feroult/swarmbox/releases/tag/v2.1.1
[2.1.0]: https://github.com/feroult/swarmbox/releases/tag/v2.1.0
[2.0.24]: https://github.com/feroult/swarmbox/releases/tag/v2.0.24
[2.0.23]: https://github.com/feroult/swarmbox/releases/tag/v2.0.23
[2.0.22]: https://github.com/feroult/swarmbox/releases/tag/v2.0.22
[2.0.21]: https://github.com/feroult/swarmbox/releases/tag/v2.0.21
[2.0.20]: https://github.com/feroult/swarmbox/releases/tag/v2.0.20
[2.0.19]: https://github.com/feroult/swarmbox/releases/tag/v2.0.19
[2.0.18]: https://github.com/feroult/swarmbox/releases/tag/v2.0.18
[2.0.17]: https://github.com/feroult/swarmbox/releases/tag/v2.0.17
[2.0.16]: https://github.com/feroult/swarmbox/releases/tag/v2.0.16
[2.0.15]: https://github.com/feroult/swarmbox/releases/tag/v2.0.15
[2.0.14]: https://github.com/feroult/swarmbox/releases/tag/v2.0.14
[2.0.13]: https://github.com/feroult/swarmbox/releases/tag/v2.0.13
[2.0.12]: https://github.com/feroult/swarmbox/releases/tag/v2.0.12
[2.0.11]: https://github.com/feroult/swarmbox/releases/tag/v2.0.11
[2.0.10]: https://github.com/feroult/swarmbox/releases/tag/v2.0.10
[2.0.9]: https://github.com/feroult/swarmbox/releases/tag/v2.0.9
[2.0.8]: https://github.com/feroult/swarmbox/releases/tag/v2.0.8
[2.0.7]: https://github.com/feroult/swarmbox/releases/tag/v2.0.7
[2.0.6]: https://github.com/feroult/swarmbox/releases/tag/v2.0.6
[2.0.5]: https://github.com/feroult/swarmbox/releases/tag/v2.0.5
[2.0.4]: https://github.com/feroult/swarmbox/releases/tag/v2.0.4
[2.0.3]: https://github.com/feroult/swarmbox/releases/tag/v2.0.3
[2.0.2]: https://github.com/feroult/swarmbox/releases/tag/v2.0.2
[2.0.1]: https://github.com/feroult/swarmbox/releases/tag/v2.0.1
[2.0.0]: https://github.com/feroult/swarmbox/releases/tag/v2.0.0
