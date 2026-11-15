# Voice control (design)

Status: **steps 1 to 3 of "Order of work" are implemented** (see [voice.md](voice.md) for how to use it). The browser only captures the
microphone; the plan, its risk and the confirmation are shown and decided inside tmux, in a panel that every client sees (terminal tab,
browser, phone); only audio crosses the tunnel. Step 4 (`swarmbox listen`, actions without confirmation) is not done.

## Purpose

Give commands to the box by voice, from a phone or a browser, without typing in a web terminal. An agent turns what you
say into the commands to send, and you confirm them before anything runs.

## Parts

- **The `voice` tool.** Installed on demand (`swarmbox tool install voice`), inside the box, with no nested Podman. It holds
  `whisper.cpp`, a multilingual model, a small service and the panel program.
- **Audio capture, the only job of the browser.** `getUserMedia` and push-to-talk, with a microphone button added to the ttyd page
  (`--index`). `getUserMedia` works on `localhost` and through the Cloudflare tunnel, since both are secure contexts. The page sends the
  audio and shows only a small state (recording, sent). It does not show the plan and it cannot confirm anything. A terminal tab has no
  microphone in the box, so the native terminal gets a host command (`swarmbox listen`) that records and sends the audio the same way,
  with `podman exec -i`; that is a later step.
- **The panel, in tmux.** A pane of the shared tmux session, so every client sees it. It shows what was heard, the plan and its risk, and
  it is where you run, edit or cancel. See the next section.
- **Execution.** Always done by the service with `tmux send-keys`, and only for a plan confirmed in the panel.

```
[browser mic / swarmbox listen] audio -> [service in the box]            only audio crosses the tunnel
    whisper.cpp -> text -> planner (reads tmux) -> pending plan (kept by the service, one at a time)
                                                       |  opens the panel pane (dock)
   [tmux pane: swarmbox-voice panel] <- shows it; you press r / e / c -> service -> tmux send-keys
```

The HTTP interface exists only because the browser reaches the box through one port. A tool driven from tmux needs none: the panel
and the CLI talk to the service on the loopback address inside the box. Audio is the only thing that comes from outside the box, so the
front on the web terminal port is an **audio entry**, not a router of tools: a fixed, minimal table of four routes (the audio upload, the two files
of the microphone button, the health check). A second entry for audio, `swarmbox listen` from a native terminal through `podman exec -i`,
feeds the same service function. Other tools that may come later live in tmux and need neither HTTP nor the front.

## The panel in tmux

`swarmbox-voice panel` is a text program (stdlib only: raw ANSI, termios and select) that runs in a tmux pane. It asks the service for the
pending plan (a long poll of `GET /voice/pending`) and shows: what was heard, the planner's sentence, the host-computed risk (a colour AND
the words LOW, MEDIUM or HIGH RISK, never colour alone, and the reasons for the last two), each action ("type into pane %2: ..." and whether
Enter is pressed) and the time left. Keys: `r` run, `e` edit the text of an action in a one-line editor (left, right, home, end, backspace,
delete; Enter accepts, Esc aborts; the service computes the risk again and gives a new id), `c` or Esc cancel, `q` close (the plan stays
pending), Up/Down scroll. A plan of **high risk** needs a stronger gesture: after `r`, type the word `run` and Enter. Mouse clicks on the key
line work too (tmux passes mouse events to a program that asks for them), with the same gestures. Nothing runs without a key (or a click) in
this pane, and the panel exits by itself when the plan is run, cancelled or expires, which closes the pane. It wraps to the pane width,
redraws on a resize, and says so when the service does not answer (it keeps trying; `q` closes it).

Safety details the panel adds to what the card had:

- Keys are ignored for half a second after a plan appears or is replaced: the panel takes the focus when it opens, and typing meant for
  another pane must not answer a plan.
- A plan taller than the pane scrolls, and `r` is refused until the end of the plan has been on screen once, so a long command cannot hide
  its tail. The key line never scrolls away.
- Everything that comes from the service is printed with control and format characters replaced (a plan can carry text from a terminal, so an
  escape sequence or a bidi mark must not reach this terminal). An unknown risk level is treated as high; an action that is not in the closed
  set cannot be run.
- The key line stays clear of the last 7 columns of the bottom row, where the browser's microphone button sits.

**It appears when there is something to decide.** The service opens it when a plan becomes pending and the pane closes with the plan; a key
(Ctrl+A then `v`, `swarmbox-voice dock toggle`) shows or hides it by hand. A panel opened by hand with nothing pending waits for a plan and
stays until `q`. This keeps the screen free most of the time, which matters on a phone.

**Where it docks depends on the shape of the window**, in one pure function, `dock.layout(cols, rows)`:

- portrait, `cols < 2 x rows` (terminal cells are about twice as tall as wide, so "taller than wide" is not `cols < rows`; the factor is the
  constant `CELL_FACTOR`): a full-width pane at the bottom, **40 %** of the height (`split-window -fv -l 40%`);
- otherwise a pane at the right edge, **20 %** of the width, at least 40 columns (`split-window -fh -l 20%`, or `-l 40` when 20 % is less);
- if that would leave the terminal fewer than 60 columns (the border counts one), the bottom layout is used.

The size is the size of the window. The box's tmux.conf does not set `window-size`, so it is tmux's default, `latest`: the window follows
the client that was active last, and the size it has is the size of that client (a window is shown at the size of one client at a time; the
others see it cropped or padded). A phone that was last active therefore docks for the phone, and a desktop that becomes the latest client
docks for the desktop. Checked with tmux 3.5a and 3.7c.

**Re-docking.** tmux has the hook `window-resized` (checked: it fires when a client attaches with another size, when a client is resized, and
when the latest client changes; `window-layout-changed` and `client-resized` fire as well, but also on every split). While a panel exists, the
dock sets the global hook `window-resized[417]` to run `swarmbox-voice dock redock`; the hook is set when the panel opens and removes itself
when it runs and finds no panel. `redock` moves the same pane with `join-pane -f` when the layout kind changed (the program in it keeps running,
the plan on screen stays), and does not take the focus from a pane the user is in. Moving is idempotent, so the layout change it causes does not
loop.

**One panel, found by a mark.** The pane carries the pane option `@swarmbox_voice_panel`, and its start command carries the marker argument
`SWARMBOX_VOICE_PANEL=1` (for the instant before the option is set). The panel is found by those, never by position, every operation takes a
file lock, and an extra one is killed, so there is never more than one. The planner context (`context.snapshot`) and the executor
(`session_panes`) leave marked panes out: the panel is never the target of a plan and its text is never given to a planner. When the panel has
the focus, the "active pane" of its window is the pane that was active before it (tmux's last pane), so the plan still targets what the user was
looking at.

**Which pane a plan targets.** A typed request may name a pane (`pane` of `POST /voice/plan`) when it is a pane of the session; otherwise, and
for every spoken request, the plan targets the **active pane of the window the session `main` shows** (the window the user looks at, in the
browser; `window_active` and `pane_active` of tmux). The planner may choose another pane of the session in its answer, never the panel.

**Several windows.** The panel exists once, in one window. It opens in the window the session shows when the plan arrives (or in the window
where the toggle key was pressed). If it is in another window, opening or toggling MOVES it to this one (the toggle closes it only when it is
already in the window you are in), so "show the pending plan again from another window" is the same key. The window of a host terminal tab is
its own session linked into `main`; the rule uses the window the session `main` shows, which is what the browser shows.

## Speech to text: Whisper, fixed

The tool always uses Whisper (`whisper.cpp`). It is not a choice. Two settings change the result:

- `voice.stt.model`: `small` by default, which is the least that is reasonable for Portuguese; `medium` if the latency allows.
  Use the multilingual files (`ggml-small.bin`), never the `.en` ones, which only know English.
- `voice.language`: `auto` by default. Fixing it (`pt`) skips detection, avoids a wrong guess on short phrases and keeps the
  model from switching language when English terms are mixed in. Whisper has one Portuguese code, `pt`; there is no `pt-br`,
  and Brazilian speech works normally.
- `voice.stt.vocabulary` (optional, empty by default): words passed as Whisper's `initial_prompt`, so it favours them. It
  helps only if a technical word you say often is transcribed wrong. It is not an instruction to the agent.

The service calls the recognizer through one function (`stt.transcribe`), so replacing Whisper later is a small change, but it is not a
plug-in point today. `whisper-cli` assumes English when it gets no `-l`, so `auto` is passed as `-l auto`.

## The planner: the part that is pluggable

The planner receives the transcribed text and the state of tmux and returns a plan. It is an executable that reads JSON on
stdin and writes JSON on stdout, so any language and any agent CLI can implement it.

- Built-in planners live in the tool folder; yours go in `~/.config/swarmbox/voice/`, named `planner-<name>`.
- `voice.planner` selects one; `voice.planner.model` is passed to it, and each planner reads it its own way. Settings reach
  the plug-in as `SWARMBOX_VOICE_*` variables.
- Planners: `passthrough` (first, plain dictation), `claude` (`claude -p` with the login that is already in the box, a small
  model such as Haiku, and the tools restricted with `--allowedTools`), and later `gemini`, `opencode`, an API or a local model.

Input:

```json
{"utterance": "run the shop-api tests",
 "active_pane": "%2",
 "panes": [{"id": "%2", "window": "shop-api", "cwd": "~/shop-api",
            "command": "bash", "tail": "...last lines..."}]}
```

Output:

```json
{"say": "Running pytest in the shop-api pane",
 "actions": [{"type": "send_text", "pane": "%2", "text": "pytest -x", "enter": true}]}
```

The language is not part of the input: the planner understands the text as it comes, and only the recognizer needs it.

### Rules the plug-in does not own

- **A closed set of actions:** `send_text`, `new_window`, `select_pane`. The host validates the output and rejects anything else.
- **The plug-in only proposes.** The host executes, so the confirmation does not depend on each implementation.
- **The host computes the risk** (`rm`, `push`, `sudo` and similar always ask). A planner must not declare its own risk, since a
  faulty or injected one could mark everything as safe.
- **The host limits the context:** the number of `tail` lines, and obvious secrets are cut before text goes to an external service.

## Security

- Panes can contain prompt injection (a README or a log saying "ignore everything and run X"), and the planner reads them.
  Confirming in the panel is the defense.
- **What the web exposes is four routes.** The browser only needs to send audio, so the front serves two page files and forwards to the service
  only `GET /voice/health` and `POST /voice/audio`; every other `/voice/` path is a 404 or 405 from the front itself. Run, edit, cancel, the
  pending plan and typed plans are reachable only from inside the box (`127.0.0.1:17682`), by the panel and the CLI. The answers are filtered
  too: the front passes back only `ok`, `state`, `error` and `message`, and the service puts no transcript, plan or pane text in them. A hostile
  page or a stolen web session can at most create a pending plan (and have the panel open on it); it cannot run one, and it cannot read what it
  says. That is stricter than the card the page had before, where the same HTTP session could confirm. The cost is that the audio of the
  attacker is transcribed by your Whisper (and planned by your `claude` login) as before.
- Later, a short list of low-risk actions (status, list, switch pane) may run without asking. Anything that writes, deletes
  or pushes keeps asking.
- When the target pane runs Claude Code, the "command" is only prompt text sent to it, which is the safest and most common case.
- Show the transcript in the panel and never press Enter on a transcription: a recognition error must not become a command.
  Use push-to-talk, not continuous listening.

## Configuration

```bash
swarmbox tool install voice
swarmbox config set voice.language pt
swarmbox config set voice.planner claude
swarmbox config set voice.planner.model haiku
swarmbox reset
```

The other settings have defaults: `voice.stt.model` is `small`, `voice.language` is `auto`, and `voice.planner` starts as
`passthrough`. The settings are creation settings: the host passes them to the box as `SWARMBOX_VOICE_*` only when they differ from the
default, and `swarmbox reset` applies a change.

## Tests

- A fake planner with fixed answers tests the host and the interface.
- A contract suite runs against any planner: valid JSON, only allowed actions, a `pane` that exists. Whoever writes a new
  planner runs it to know the planner is correct.

## What exists

The contract, validator, risk, context limits, planners (`passthrough`, `claude`), the executor, the plan store, the `voice.*` settings, the
tool and its installer, the front on the web terminal port, the service (`GET /voice/health`, `POST /voice/audio`, `GET /voice/pending`,
`POST /voice/plan|edit|run|cancel`; there is no `/voice/transcribe` any more, nothing needed text without a plan), the page (the microphone and a
state light: idle, recording, sending, sent, nothing heard, error), `swarmbox-voice panel`, `dock.py` (the layout rule, opening, closing, toggling
and the re-dock hook) and the tmux key. There is one pending plan at a time: a new plan cancels the older one; an edit swaps it in one step.

## Order of work

1. The contract, the `passthrough` planner, the contract tests and the fake planner. Done.
2. Audio on the web, the service, Whisper, the `claude` planner. Done.
3. The panel in tmux (`swarmbox-voice panel`, docking by window shape, show and hide with the pending plan), the one-call upload, the
   narrower front, the page reduced to the microphone. Tests with a real tmux in a container, including the portrait and landscape cases. Done.
4. `swarmbox listen` for audio from a native terminal, and the list of actions that run without confirmation.

## Open questions

- The values of the layout rule (40 %, 20 %, the minimums, the cell factor), after trying them on a phone and on a desktop. (They are constants
  of `dock.py`. If tmux reported the cell size in pixels, `CELL_FACTOR` could be measured instead of assumed; it does not in a way the service can
  read, so it stays a constant.)
- Whether the latency of `small` on CPU is acceptable, and whether `medium` is needed.
- Whether the page should show a small spoken-text preview next to the microphone. Decided no for now: the page shows a state light only, because
  the transcript is a plan detail that belongs in the panel and nothing of it crosses the tunnel.
- A window of a host terminal tab (its own session linked into `main`) is not the window `main` shows unless the browser shows it; the panel
  follows the browser's window. Whether it should follow the most recently active client of any session instead.
