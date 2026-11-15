# Voice control (design)

Status: **implemented, as an input only.** `voice` hears and publishes; it does not plan, show, confirm or execute. The part that acts is the `sysop`. How to use it is in [voice.md](voice.md); the split and the bus are in [plugins-design.md](plugins-design.md).

An earlier design had `voice` hear, plan, show a plan in a panel and execute it, with pluggable planners. That design was dropped: its planning, risk rules, panel and executor moved to the sysop ([sysop.md](sysop.md)), and its tests moved with them. The reasons are in "Why an input only" of plugins-design.md; an earlier copy of this file is in the git history (the commit `ca2faca` and before).

## Purpose

Let you give a goal to the box by voice, from a phone or a browser, without typing into a web terminal. The goal is a line of text; what to do with it is the business of whoever listens to it.

## What it is

```
browser (microphone) --audio--> web terminal port --> voice service (Whisper) --text--> bus topic (voice.topic) ...
```

- **The `voice` tool.** Installed on demand (`swarmbox tool install voice`), inside the box. It holds `whisper.cpp` (built at install, CPU only), one multilingual Whisper model and a small service. Nothing is in the image, no nested Podman and no login are needed.
- **The microphone page.** `getUserMedia` with push-to-talk: a button and a state light added to the ttyd page by `swarmbox-web` (`/voice/page.js` and `/voice/page.css`). `getUserMedia` works on `localhost` and through the Cloudflare tunnel, since both are secure contexts. The page records and sends
  the audio; it shows only a state (recording, sending, sent, nothing heard, nobody is listening, busy, error). No transcript, no plan, no confirmation: nothing on it can make the box do anything.
- **The audio entry.** The box publishes one port, the web terminal's, so `swarmbox-voice front` listens on it and starts ttyd and the service behind it. Under `/voice/` it has a **fixed table of four routes**: the two page files, `GET /voice/health` and `POST /voice/audio`. Any other path
  under `/voice/` is a 404 from the front and never reaches the service; anything else is piped to ttyd unchanged, websockets included. The answers are filtered, so only a few booleans and short fixed strings come back. Details and limits are in [voice.md](voice.md).
- **Whisper, fixed.** The recognizer is always Whisper, called through one function (`stt.transcribe`). Settings: `voice.stt.model` (`small` by default, multilingual only, never `.en`), `voice.language` (`auto` or a code such as `pt`; `auto` is passed as `-l auto`, because `whisper-cli` assumes English
  without `-l`) and `voice.stt.vocabulary` (optional words given as the prompt). A recording that is quiet (no speech) is not given to Whisper, and a transcript of notes only (`[BLANK_AUDIO]`) is dropped, because Whisper turns silence into words and each would become a goal.
- **The publication.** The service publishes `{"text": ...}` with `source` `voice` on the topic of `voice.topic` (default `goal`), speaking the socket of the bus directly. `pub` says how many received it: none is "nobody is listening" on the page, and a subscriber that is behind is "busy". `swarmbox-voice say TEXT`
  publishes the same goal without a microphone.

## What it does not do

- It does not plan, rate risk, show a plan, ask for a confirmation or type into a tab: it has no tmux code and no call on the tabs. A goal is a request, not a command; the sysop reads it as text and decides.
- It does not know who listens. The only link with any other plugin is the topic name in the settings: the sysop hears voice when `sysop.topic` equals `voice.topic`. Any other subscriber of the topic gets the goal too, and without one the page says so.
- It does not keep the audio (a private temporary folder while Whisper runs) or log the transcript, and it never sends the transcript back to the browser.
- It does not read screens, so it has no use for the secrets filter (that one belongs to `swarmbox-tabs`).

## Security

- Only audio crosses the tunnel, and what it can cause is a goal on a topic. The route table is fixed, the `Origin` of a `/voice/` request must name its `Host`, a POST needs the WAV content type, the body is limited, and the service behind the front listens on loopback and checks its own `Host` and `Origin`.
- The risk of what a goal leads to is rated by the sysop, from the action and not from the text of the goal, and a high risk waits for you in a session that is yours. Anyone who can already open the terminal can type any command, so the path adds no way to run things.
- `voice.web` at `0` removes the button and the front: the web port then goes straight to ttyd.

## Configuration

`voice.language`, `voice.stt.model`, `voice.stt.vocabulary`, `voice.web` and `voice.topic`, with their defaults and variables, in [voice.md](voice.md) and in section 9 of [design.md](design.md). They reach the box as `SWARMBOX_VOICE_*` only when they differ from the default.

## Tests

Unit tests of the config, the service, the front and the page (`tests/test_voice_*.py`, `tests/test_tool_voice.py`), a browser test of the page with a fake service (`tests/test_voice_page_browser.py`), and the end-to-end run in Podman (`tests/e2e_voice.sh`): the microphone of a headless Chromium
plays speech made with espeak-ng, and the goal is followed through the real bus and sysop to a real Claude Code in the active tab (see "Version 1" in plugins-design.md for what it proved and found).

## Open questions

- Whether the latency of `small` on CPU is acceptable (2 to 4 s on a short phrase in the tests), and whether `medium` is needed; and how Whisper hears real speech in the language you use (the tests only had a synthetic voice).
- A host command that records the microphone of the host terminal (`swarmbox listen`): a terminal tab has no microphone in the box. Not built.
- Whether the page should show a preview of the text next to the button. Decided no: the transcript is not shown anywhere on the page, and nothing of it crosses the tunnel.
