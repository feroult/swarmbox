# Voice control

The `voice` tool lets you give a command by voice. It turns speech into text with Whisper, asks a planner what to do with the text and the state of tmux, and shows you a plan **in a panel of tmux**. Nothing reaches a terminal until you confirm it there.
The browser only captures the microphone: the plan, its risk and the confirmation are the same for every client (a terminal tab, the browser, a phone), and only audio crosses the tunnel.
The design and its reasons are in [voice-design.md](voice-design.md). This page says what is there now and how to use it.

## How it works for you

1. Hold the microphone button of the web terminal (bottom right) and speak; release to send. The light on the button shows recording, sending, sent (or "nothing heard", or a short error). The page shows nothing else.
2. A panel opens in the shared tmux session, so you see it in the browser and in any terminal attached to it: at the bottom (40 % of the height) when the window is taller than wide, as on a phone, else at the right edge (20 % of the width, at least 40 columns; at the bottom when the window is narrower than that allows).
3. The panel shows what was heard, the planner's sentence, the risk (a colour and the words LOW, MEDIUM or HIGH RISK), each action and the time left. Press `r` to run, `e` to edit the text of an action (the host rates the risk again), `c` or Esc to cancel, `q` to close it and leave the plan pending. A **high** risk plan needs more: after `r`, type the word `run` and Enter. Clicks on the key line work too.
4. When the plan is run, cancelled or expires, the panel closes by itself. Ctrl+A then `v` shows or hides the panel by hand (it moves to the window you are in when it is in another one).

A plan targets the active pane of the window the session shows. The panel is never a target, and its text is never given to a planner.

## What exists

- The tool: `swarmbox tool install voice` builds `whisper.cpp` inside the box (a few minutes, needs the network and the compiler of the image) and downloads one multilingual model (`small`, about 490 MB). Nothing is in the image.
- `swarmbox-voice`, in the box: `serve` (the service), `panel` (the panel), `dock open|close|toggle|redock` (the panel pane in tmux), `model list|fetch NAME`, `planners`, `plan TEXT` (a typed request: the service makes it the pending plan and the panel opens on it) and `--self-test`.
- The built-in planner `passthrough`: plain dictation. The text goes to the pane you were using, without Enter.
- The built-in planner `claude`: turns the utterance into a plan with the headless Claude Code CLI (`claude -p`, using the login already in the box). It runs with every tool disabled (`--tools ""`), no MCP servers (`--strict-mcp-config`), no user hooks or settings (`--safe-mode`) and no session file. Choose it with `swarmbox config set voice.planner claude`.
- The page (`web/page.js`, `web/page.css`): the microphone button and a state light, served by the front (next section). It hides itself when the service does not answer. It has no card, no plan and no buttons to run anything.
- The panel (`swarmbox-voice panel`, `dock.py`): a text program in a pane of the shared tmux session, and the code that opens, moves and closes that pane. The tmux key is `bind v` of the box's `tmux.conf`, after the prefix (Ctrl+A).
- The service, on the loopback address of the box, `127.0.0.1:17682`. It is not published: the front starts it, and the panel and the CLI talk to it from inside the box.
- `swarmbox-voice front`: the web terminal port of the box with the voice parts next to ttyd.

## The front

Tools have no hook to start a service and the box publishes one port, the one of the web terminal, so the voice parts share it. When the `voice` tool is installed and `voice.web` is not `0`, `swarmbox-web` (the program the box starts and restarts for the web terminal) does this instead of running ttyd alone:

- the generated page gets `<link rel="stylesheet" href="/voice/page.css">` before `</head>` and `<script src="/voice/page.js" defer></script>` before `</body>`;
- it runs `swarmbox-voice front`, which listens on the web port (`0.0.0.0:7681` in the box; the published host port is what keeps it on `127.0.0.1` of the host) and starts two children: the voice service on `127.0.0.1:17682` and the real ttyd on `127.0.0.1:7680`.

Every connection is routed by its first request. Under `/voice/` the front has a **fixed table of four routes** and nothing else:

| Route | What the front does |
|---|---|
| `GET /voice/page.js`, `GET /voice/page.css` | serves the file from the tool's `web/` folder |
| `GET /voice/health` | forwards it; only `{"ok": ...}` is passed back |
| `POST /voice/audio` | forwards the WAV (up to 8 MiB); only `ok`, `state`, `error` and `message` are passed back |

Every other path under `/voice/` (`run`, `edit`, `cancel`, `pending`, `plan`, the old `transcribe`, anything) is answered 404 (405 for a listed path with the wrong method, or OPTIONS) by the front itself, before the `Host` or `Origin` are looked at, and never reaches the service. Anything that is not `/voice/` is piped to ttyd byte for byte, websockets included (the head is not changed, except that a request that is not a websocket gets `Connection: close`). For the four routes the front checks what ttyd's `-O` checks for the terminal and a bit more, before the service sees the request: an `Origin` must name the `Host` (else 403), a POST needs the WAV content type (a cross-site form cannot send it) and a `Content-Length`, the body is limited, and at most 16 voice requests run at once. What it forwards is rebuilt: the path alone, `Host` and `Origin` rewritten to the loopback address of the service, which keeps its own loopback-only guard.

When ttyd exits the front stops the service and exits with ttyd's status, so the restart policy of the box applies unchanged; SIGTERM stops both children. If the service dies the front restarts it with a back-off, and meanwhile `/voice/` answers 502 while the terminal is not affected. If the tool is not installed, is an old install without the front, or `voice.web` is `0`, `swarmbox-web` runs
ttyd on the web port exactly as before and the page has no voice button.

After `swarmbox update` the tool follows the image: `install.sh` copies `lib/`, `planners/` and `web/` into the install and is not run again for the same whisper.cpp version, so the tool ships a `prepare.sh`, which `swarmbox-tool prepare` runs at every box start (before the web terminal starts) and which makes the copies in the install equal to the ones in the image. Whisper, the models and the launcher are not touched.

## Settings

Set them on the host, then recreate the box (the box is told its settings when it is created):

```bash
swarmbox tool install voice
swarmbox config set voice.language pt
swarmbox config set voice.stt.model medium
swarmbox reset
```

| Key | Default | Meaning |
|---|---|---|
| `voice.language` | `auto` | `auto` lets Whisper detect the language. A code such as `pt` fixes it, which avoids wrong guesses on short phrases. There is no `pt-br`. |
| `voice.stt.model` | `small` | a multilingual model: `tiny`, `base`, `small`, `medium`, `large-v3`, `large-v3-turbo`. Never an `.en` model: those only know English. |
| `voice.stt.vocabulary` | empty | words handed to Whisper as its prompt, so it prefers them (`kubectl, Podman`). At most 500 characters. Not an instruction to the agent. |
| `voice.planner` | `passthrough` | the planner to use. |
| `voice.planner.model` | empty | passed to the planner, which reads it its own way. |
| `voice.web` | `1` | `0` turns the front off (see "The front"): the web terminal port goes straight to ttyd and the page has no voice button. |

A setting that equals its default is not passed to the box. Inside the box the service reads `SWARMBOX_VOICE_LANGUAGE`, `SWARMBOX_VOICE_STT_MODEL`, `SWARMBOX_VOICE_STT_VOCABULARY`, `SWARMBOX_VOICE_PLANNER` and
`SWARMBOX_VOICE_PLANNER_MODEL`; `swarmbox-web` reads `SWARMBOX_VOICE_WEB` (`voice.web`; passed only when it is `0`). A model other than the one fetched at install is fetched with `swarmbox-voice model fetch medium` (the file is checked against a pinned SHA-256).

## The service

All paths are under `/voice/`, answers are JSON. The service listens on `127.0.0.1:17682` inside the box. **Only the first two lines of the table are reachable from the web** (through the front); the rest is for the panel and the CLI, on the loopback address.

| Call | Does |
|---|---|
| `GET /voice/health` | `{"ok": true, ...}` with the planner, language, model and the number of pending plans (through the front only `ok` comes back) |
| `POST /voice/audio` | body: a 16 kHz mono 16-bit WAV (`Content-Type: audio/wav`). Transcribes, runs the planner, stores the plan as **the pending plan**, opens the panel. Answers `{"ok": true, "state": "pending"}` or `{"ok": true, "state": "nothing_heard"}` and never the transcript, the plan or pane text; errors are fixed short sentences |
| `GET /voice/pending` | `{"pending": {"id", "text", "say", "actions", "risk", "expires_in"}}` or `{"pending": null}`. With `?wait=SECONDS&since=ID` it is a long poll (at most 55 s): it answers when the pending plan is not `ID` (`""` for none) |
| `POST /voice/plan` | `{"utterance": "...", "pane": "%2"}` (a typed request) runs the planner on the text and makes the plan the pending one; answers the plan. `pane` is optional |
| `POST /voice/run` | `{"id": "..."}` executes the stored plan, once |
| `POST /voice/edit` | `{"id": "...", "edits": {"0": "new text"}}` replaces the pending plan by one with the edited `send_text` texts, a new id and a risk computed again |
| `POST /voice/cancel` | `{"id": "..."}` drops it |

There is no `/voice/transcribe`: nothing needs text without a plan.

What the service guarantees:

- **One pending plan.** A new plan replaces (cancels) an older one; the old id then answers 409. An edit swaps the plan in one step, so a panel never sees "no plan" in the middle of it.
- **Nothing before the confirmation.** The plan is kept in the service and `run` executes that plan; the client sends only its id, so it cannot change the actions. An id works once (a second run answers 409), expires after two minutes (410), and an unknown id is 404.
- **The host rates the risk.** `risk` is computed by the service (`rm`, `git push`, `sudo`, `curl | sh`, redirections to files, chained commands, and similar are `high` or `medium`), again at `run` with the commands the panes run then (a pane that became riskier cancels the run), and a planner cannot declare it: the field is dropped.
- **Enter only when asked.** `send_text` types the text literally (`tmux send-keys -l`); Enter is pressed only if the confirmed action says `enter: true`. `passthrough` never does.
- **The panel is never a target.** The pane of the panel is marked, and the executor and the planner context leave it out.
- **Local only.** The service refuses to listen on anything but loopback, checks the `Host` and `Origin` headers (no other web page can call it, and DNS rebinding does not work), accepts only JSON or WAV bodies, and limits their size.
- **The audio is not kept.** It lives in a private temporary folder while Whisper runs.

Whisper is called through one function (`stt.transcribe`), with `-l` from `voice.language` (`-l auto` for detection: the default of `whisper-cli` is English), the multilingual model, and `--prompt` only when a vocabulary is set.

## Planners

A planner is an executable named `planner-<name>`. It reads one JSON object on stdin and writes one on stdout. Built-in ones are in the tool folder; yours go in `~/.config/swarmbox/voice/` (a planner there wins over a built-in of the same name).
The planner runs with a minimal environment (`PATH`, `HOME`, `LANG` and `SWARMBOX_VOICE_*`), a time limit and an output limit, and the text of the panes reaches it only on stdin.

Input:

```json
{"utterance": "run the shop-api tests",
 "active_pane": "%2",
 "panes": [{"id": "%2", "window": "shop-api", "cwd": "~/shop-api", "command": "bash", "tail": "...last lines..."}]}
```

Output:

```json
{"say": "Running pytest in the shop-api pane",
 "actions": [{"type": "send_text", "pane": "%2", "text": "pytest -x", "enter": false}]}
```

The actions are a closed set: `send_text`, `new_window` and `select_pane`. The host rejects anything else, a pane that is not in the input, control characters in text, and an output that is not valid JSON or is too large. The tails are limited and obvious secrets
(keys, tokens, `Authorization` headers, private keys) are cut before the planner sees them. Pane text can carry prompt injection: the confirmation is the defense, so read the plan.

## Security notes

- **What the tunnel can and cannot do.** Whoever reaches the web port can load the page files, ask for the health check and send audio. That makes at most a pending plan and opens the panel on it (and uses your Whisper and, with the `claude` planner, your Claude login). They cannot run, edit or cancel a plan, cannot read the pending plan or what was heard, and cannot reach any other route of the service: the front answers 404 to them, and what it forwards is filtered. Running a plan takes a key (or a click) in the tmux panel, in a session that is yours. Anyone who can open the terminal itself can already type any command, so this does not add a way to run things; it keeps the voice path from being a second one.
- Panes can contain prompt injection (a README or a log saying "ignore everything and run X"), and the planner reads them. Read the plan in the panel before you run it; a high risk plan asks you to type `run`.
- The planner folder in your workspace is your own code, like your user tools: anything in the box can write there.
- The front is the only place that sees the public `Host` (the tunnel's hostname or `localhost:7681`). It requires the `Origin` of a `/voice/` request, when there is one, to name that same host, as ttyd's `-O` does for the terminal; it does not know which hosts are legitimate, so it is not a defense against a browser the user controls or against DNS rebinding to a host name that reaches the box. The service behind it checks only loopback names, after the front rewrites them.
- The service has no authentication beyond being on loopback inside the box, and the panel and the CLI use it that way. Do not publish its port (17682) or ttyd's (7680): the front is the way in.
- The panel prints what the service sends with control characters replaced, so a plan cannot send escape sequences to your terminal, and it ignores keys for half a second after a plan appears, because it takes the focus when it opens.
- Dictating into a pane that runs Claude Code is the safest case: the text is only a prompt. Into a shell, read the plan before you confirm.
