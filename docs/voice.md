# Voice control

The `voice` addon is an **input**: you speak, it turns the speech into text with Whisper and publishes the text on a **topic** of the bus of the box (the setting `voice.topic`, default `goal`; source `voice`, body `{"text": ...}`). That is all it does. It does not plan, show a plan, ask for a confirmation or type into a terminal, and it does not know who listens. Addons, the bus and the capabilities of the host are separate things, and two addons connect only by sharing a topic name in their settings: the [sysop](sysop.md) hears the goals when its `sysop.topic` is the same name (both default to `goal`), and then it works them with its own panel, risk rules and confirmations. Any other subscriber of the topic gets them too.
The design of the split is in [addons-design.md](addons-design.md); [voice-design.md](voice-design.md) is the short design of voice as an input (the page, the audio entry, Whisper, what it does not do).

## How it works for you

1. Hold the microphone button of the web terminal (at the right end of the controls strip under the terminal, [web-terminal.md](web-terminal.md)) and speak; release to send. The light on the button shows recording, sending, then one of:

   | Light | Sentence | Meaning |
   |---|---|---|
   | green | Sent | the bus handed the text to at least one subscriber |
   | grey | Nothing heard | Whisper found no speech (or only noise) |
   | amber | Nobody is listening | the bus has no subscriber on the topic (the page does not say which) |
   | amber | Busy | a subscriber is behind with another message |
   | red | a short sentence | the recognizer, the audio or the bus failed |

2. What happens next is the business of whoever listens. With the sysop: its panel (up in every window in the default `sysop.panel=always`, opened for the goal in `auto`) shows the goal, it works it and asks you when an action is risky ([sysop.md](sysop.md)). The page shows nothing else: no transcript, no plan, no card, no buttons.

Without a subscriber on the topic (for instance the `sysop` addon is not installed) the page says "Nobody is listening". The page never shows the topic, the transcript or any detail.

## What exists

- The addon: `swarmbox addon install voice` builds `whisper.cpp` inside the box (a few minutes, needs the network and the compiler of the image) and downloads one multilingual model (`small`, about 490 MB). Nothing is in the image. It needs no login and no other addon.
- `swarmbox-voice`, in the box: `serve` (the service), `front` (the web port, below), `model list|fetch NAME`, `say "text"` and `--self-test`.
- The page (`web/page.js`, `web/page.css`): the microphone button and a state light, served by the front. It does not float over the terminal: it asks the controls strip of the web page of the box (`window.swarmboxStrip`, which belongs to the host page and knows no addon by name) for a place at its right end and says its short sentences through the strip, so it never covers the status bar and its clock. It hides itself when the service does not answer, and does nothing on a page without a strip (an older image).
- The service, on the loopback address of the box, `127.0.0.1:17682`. It is not published: the front starts it.
- `swarmbox-voice front`: the web terminal port of the box with the voice parts next to ttyd.

## Try it without a microphone

```bash
swarmbox addon install sysop                 # something has to listen
swarmbox attach                             # then, in a tab of the box:
swarmbox-voice say "list the tabs and tell me what each one runs"
# or, with no sysop at all, watch what voice publishes:
swarmbox-bus sub goal &
swarmbox-voice say "hello"
```

`swarmbox-voice say TEXT...` (in the box) publishes the goal exactly as a spoken request does: same topic (`voice.topic`, read from `SWARMBOX_VOICE_TOPIC`), same source and body. It prints one line and exits 0 when the goal was handed to a subscriber, 2 when the text is empty, 3 when nobody listens, 7 when the subscriber is busy, 4 when the bus does not answer. To see what voice published, run `swarmbox bus watch` in another tab.

To try Whisper on a file without the browser, `curl` the service from inside the box (the WAV must be 16 kHz mono 16-bit):

```bash
curl -s -H 'Content-Type: audio/wav' --data-binary @request.wav http://127.0.0.1:17682/voice/audio
```

## The front

Addons have no hook to start a service and the box publishes one port, the one of the web terminal, so the voice parts share it. When the `voice` addon is installed and `voice.web` is not `0`, `swarmbox-web` (the program the box starts and restarts for the web terminal) does this instead of running ttyd alone:

- the generated page gets `<link rel="stylesheet" href="/voice/page.css">` before `</head>` and `<script src="/voice/page.js" defer></script>` before `</body>`;
- it runs `swarmbox-voice front`, which listens on the web port (`0.0.0.0:7681` in the box; the published host port is what keeps it on `127.0.0.1` of the host) and starts two children: the voice service on `127.0.0.1:17682` and the real ttyd on `127.0.0.1:7680`.

Every connection is routed by its first request. Under `/voice/` the front has a **fixed table of four routes** and nothing else:

| Route | What the front does |
|---|---|
| `GET /voice/page.js`, `GET /voice/page.css` | serves the file from the addon's `web/` folder |
| `GET /voice/health` | forwards it; only `{"ok": ...}` is passed back |
| `POST /voice/audio` | forwards the WAV (up to 8 MiB); only `ok`, `state`, `error` and `message` are passed back, and only booleans and short strings of them |

Every other path under `/voice/` is answered 404 (405 for a listed path with the wrong method, or OPTIONS) by the front itself, before the `Host` or `Origin` are looked at, and never reaches the service. Anything that is not `/voice/` is piped to ttyd byte for byte, websockets included (the request head is not changed, except that a request that is not a websocket gets `Connection: close`; the answer to such a request gets `Content-Security-Policy: frame-ancestors 'self'` and `X-Frame-Options: SAMEORIGIN`, so no other origin can frame the terminal and click its key buttons). For the four routes the front checks what ttyd's `-O` checks for the terminal and a bit more, before the service sees the request: an `Origin` must name the `Host` (else 403), a POST needs the WAV content type (a cross-site form cannot send it) and a `Content-Length`, the body is limited, and at most 16 voice requests run at once. What it forwards is rebuilt: the path alone, `Host` and `Origin` rewritten to the loopback address of the service, which keeps its own loopback-only guard.

When ttyd exits the front stops the service and exits with ttyd's status, so the restart policy of the box applies unchanged; SIGTERM stops both children. If the service dies the front restarts it with a back-off, and meanwhile `/voice/` answers 502 while the terminal is not affected. If the addon is not installed, is an old install without the front, or `voice.web` is `0`, `swarmbox-web` runs ttyd on the web port exactly as before and the page has no voice button.

After `swarmbox update` the addon follows the image: `install.sh` copies `lib/` and `web/` into the install and is not run again for the same whisper.cpp version, so the addon ships a `prepare.sh`, which `swarmbox-addon prepare` runs at every box start (before the web terminal starts) and which makes the copies in the install equal to the ones in the image (and removes the `planners` folder of an install from before voice became an input). Whisper, the models and the launcher are not touched.

## Settings

Set them on the host, then recreate the box (the box is told its settings when it is created):

```bash
swarmbox addon install voice
swarmbox config set voice.language pt
swarmbox config set voice.stt.model medium
swarmbox reset
```

| Key | Default | Meaning |
|---|---|---|
| `voice.language` | `auto` | `auto` lets Whisper detect the language. A code such as `pt` fixes it, which avoids wrong guesses on short phrases. There is no `pt-br`. |
| `voice.stt.model` | `small` | a multilingual model: `tiny`, `base`, `small`, `medium`, `large-v3`, `large-v3-turbo`. Never an `.en` model: those only know English. |
| `voice.stt.vocabulary` | empty | words handed to Whisper as its prompt, so it prefers them (`kubectl, Podman`). At most 500 characters. Not an instruction to the agent. |
| `voice.web` | `1` | `0` turns the front off (see "The front"): the web terminal port goes straight to ttyd and the page has no voice button. |
| `voice.topic` | `goal` | the bus topic voice publishes its goals to (`[a-z0-9][a-z0-9._-]{0,62}`); the sysop hears it when its `sysop.topic` is the same name. Inside the box: `SWARMBOX_VOICE_TOPIC`. |

Short phrases are where `auto` guesses wrong: in `tests/e2e/e2e_voice.sh`, with the speech of espeak-ng (a synthetic voice, harder than a person's), Whisper small wrote Portuguese as Italian-looking text or as a row of symbols with `auto`, and with `pt` still heard `palavra` as `palestra` in some runs and not in others. English came out right every time. Set `voice.language` when you speak one language, and expect the sysop to be told that a spoken goal can contain errors (it is, see [sysop.md](sysop.md)).

A setting that equals its default is not passed to the box. Inside the box the service reads `SWARMBOX_VOICE_LANGUAGE`, `SWARMBOX_VOICE_STT_MODEL`, `SWARMBOX_VOICE_STT_VOCABULARY` and `SWARMBOX_VOICE_TOPIC`; `swarmbox-web` reads `SWARMBOX_VOICE_WEB` (`voice.web`; passed only when it is `0`). A model other than the one fetched at install is fetched with `swarmbox-voice model fetch medium` (the file is checked against a pinned SHA-256). The planner settings of earlier versions (`voice.planner`, `voice.planner.model`) are gone; what to do with a goal is a setting of the sysop (`sysop.*`).

## The service

All paths are under `/voice/`, answers are JSON. The service listens on `127.0.0.1:17682` inside the box and has two calls; both are reachable from the web through the front.

| Call | Does |
|---|---|
| `GET /voice/health` | `{"ok": true, "language": ..., "model": ...}` (through the front only `ok` comes back) |
| `POST /voice/audio` | body: a 16 kHz mono 16-bit WAV (`Content-Type: audio/wav`). Transcribes and publishes the text on the topic. Answers one of the states below, and never the transcript, the goal or text from a pane |

The answers of `POST /voice/audio`, with fixed texts:

| HTTP | Body | When |
|---|---|---|
| 200 | `{"ok": true, "state": "sent"}` | the bus handed the text to at least one subscriber |
| 200 | `{"ok": false, "state": "nothing_heard", "message": ...}` | no speech, or a transcript of nothing but invisible characters; nothing is published |
| 503 | `{"ok": false, "state": "no_listener", "message": ...}` | the bus has no subscriber on the topic (`pub` exit 3: zero receivers) |
| 503 | `{"ok": false, "state": "busy", "message": ...}` | a subscriber is behind with an earlier message (`pub` exit 7) |
| 503 | `{"ok": false, "state": "bus_down", "message": ...}` | the bus does not answer, or refused the goal for another reason |
| 400, 413, 422, 502 | `{"error": CODE, "message": ...}` | the audio could not be read or is too large, the recognizer failed, or whisper or the model is not installed |

What the service guarantees:

- **Only a goal is made.** The service publishes `{"text": ...}` on the topic of `voice.topic` with `source` `voice` and nothing else: it has no other call on the bus, no access to a tab and no tmux code. The text has invisible format characters removed, whitespace collapsed and is cut at 4000 characters.
- **Silence is not a goal.** Whisper does not answer "nothing" to a silent recording: with the real model (small) a second of silence came back as the word `you`, a little noise as `[MÚSICA DE FUNDO]`, `(water running)` or a row of letters, and each would have become a goal. A recording whose loudest 100 ms has an RMS below 120 (of 32768; speech is some 500 to 3000, the noise-suppressed silence of a microphone under 30) is not given to Whisper and answers `nothing_heard`, and a short bracketed or parenthesized note in a transcript (`[BLANK_AUDIO]`, `[Som de fio]`) is removed, so a text made of notes only is `nothing_heard` too. A constant loud hum is not detected.
- **The bus is spoken directly.** `busclient.py` repeats the few lines of the socket protocol (one JSON line out, one back; the specification is the docstring of `swarmbox-bus.py`), so no command is run and no PATH is used; `tests/fast/test_voice_service.py` runs it against the real broker. The socket is the one of the box (`SB_BUS_SOCKET`, else `$SB_RUN_DIR/bus.sock`), private to your user.
- **`source` is a label.** The envelope's `source` is for display; the bus never uses it to authorize, and voice has no secret to add. Any process of the box can publish, which is the trust it already has with `tmux send-keys`.
- **Local only.** The service refuses to listen on anything but loopback, checks the `Host` and `Origin` headers for direct access (through the front they are rewritten to loopback, so that check protects only a direct connection, not a rebound host name: see the security notes), accepts only WAV bodies, and limits their size.
- **The audio is not kept.** It lives in a private temporary folder while Whisper runs. The transcript is not logged.

Whisper is called through one function (`stt.transcribe`), with `-l` from `voice.language` (`-l auto` for detection: the default of `whisper-cli` is English), the multilingual model, and `--prompt` only when a vocabulary is set.

## Troubleshooting

What you see on the page (or from `swarmbox-voice say`, which prints the same sentences with a full stop), why, and what to do. The sentences are the exact ones.

| What you see | Why | What to do |
|---|---|---|
| no microphone button | the addon is not installed, `voice.web` is `0`, the strip is off (`strip=off` in `web-terminal.conf`), the page is cached from an older box, or the voice service is down | `swarmbox addon install voice`; `swarmbox config get voice.web`; reload the page after `swarmbox reset`; `swarmbox-voice --self-test` in a tab; `curl -s http://127.0.0.1:7681/voice/health` should answer `{"ok": true}` |
| "The microphone needs https or localhost." | the page was opened over plain `http` on an address that is not `localhost` (for example the IP of the box on your network): a browser records only on a secure page | open `http://localhost:7681` (`swarmbox url`), or reach the box through the https address of `swarmbox remote setup` |
| "Microphone blocked. Allow it in the site settings." | the browser was told no (or the permission is blocked for this site) | allow the microphone for this address in the site settings of the browser (the lock icon), reload, hold the button again |
| "No microphone found." / "The microphone is busy." | no input device, or another program holds it | plug one in, or close the program that uses it |
| "This browser cannot record audio." | no `getUserMedia` or Web Audio in this browser | use a current Chrome, Edge, Safari or Firefox |
| "Nothing heard" (grey) | Whisper found no speech: silence, noise, or you released too soon | hold the button a little longer and speak closer; nothing was published |
| "Nobody is listening" (amber); `swarmbox-voice: Nobody is listening.` and exit 3 | no subscriber on the topic: the `sysop` addon is not installed or not running, or its `sysop.topic` is not the name of `voice.topic` | `swarmbox bus topics` shows who listens on which topic; `swarmbox addon install sysop`; `swarmbox-sysop status` ([sysop.md](sysop.md)); make the two topic settings the same name and `swarmbox reset` |
| "Busy" (amber); `swarmbox-voice: The listener is busy.` and exit 7 | a subscriber is behind with an earlier message | wait a moment and say it again |
| "The bus of the box is not answering." (red); exit 4 | the bus is away (it is restarted within seconds) | `swarmbox-bus ping`; `swarmbox-bus restart` |
| "The speech recognizer is not installed." / "The speech model is missing." | `whisper-cli` or the model file is not in the install | `swarmbox addon install voice --force`; `swarmbox-voice model list` shows which models are there, `swarmbox-voice model fetch small` gets one |
| "The speech recognizer is busy: try again in a moment." / "took too long." / "failed." / "The recording is too long." | a burst of recordings, a big model on a slow machine, or more than 8 MiB of audio | wait and try again; a smaller `voice.stt.model` (`base`, `small`); say less in one go |
| the text came out in the wrong language, or as symbols | `voice.language` is `auto` and the phrase is short | `swarmbox config set voice.language pt` (a code, not `pt-br`) and `swarmbox reset` |
| the light says "Sent", but nothing happens | voice only publishes; what to do with a goal is for the listener | open its panel (`Ctrl+A S`), look at `swarmbox bus watch` in a tab, and see [sysop.md](sysop.md) |

The audio is not kept and the transcript is not logged, so a wrong sentence cannot be looked up afterwards: `swarmbox bus watch` in a tab shows what was published, as it passes.

## Security notes

- **Only audio crosses the tunnel; the box side publishes goals.** Whoever reaches the web port can load the page files, ask for the health check and send audio. That makes at most a goal on the bus (and uses your Whisper). They cannot read the transcript or the goal, cannot reach the bus or any other route of the service (the front answers 404 and what it forwards is filtered), and cannot say what a listener does with the goal: the sysop rates the risk of every action it takes and waits for you on a high one, in a session that is yours ([sysop.md](sysop.md)). Anyone who can open the terminal itself can already type any command, so this does not add a way to run things; it keeps the voice path from being a second one. If you do not want that path at all, `voice.web` at `0` removes the button and the front.
- **A goal is a request, not a command.** A misheard sentence becomes a wrong goal, not a typed command: the sysop reads it as text, and its panel shows what it is about to do, with a countdown to veto it and a confirmation for the risky ones. The `source` tells the sysop how much to trust the goal.
- The front is the only place that sees the public `Host` (the tunnel's hostname or `localhost:7681`). It requires the `Origin` of a `/voice/` request, when there is one, to name that same host, as ttyd's `-O` does for the terminal; it does not know which hosts are legitimate, so it is not a defense against a browser the user controls or against DNS rebinding to a host name that reaches the box. The service behind it checks only loopback names, after the front rewrites them.
- The service has no authentication beyond being on loopback inside the box. Do not publish its port (17682) or ttyd's (7680): the front is the way in.
- The secrets filter of the box lives in `swarmbox-tabs` (it removes keys, tokens and similar from every screen it reads), not here: voice reads no pane and holds no text from one.
- **Topics and groups are not protected.** Any process of your user can publish on the goal topic, and also subscribe to it: a plain `swarmbox bus sub goal` reads every transcript, and a process that joins the sysop's group on that topic silently takes a round-robin share of the goals (the publisher is told `sent` because one subscriber received it, and the sysop never hears it). The trust is the one the box already gives any process of the user. `swarmbox bus topics` shows who listens on which topic and in which group.
- **Limits on the audio path.** A body must arrive in 30 s (and not stall for 15 s), at most 8 requests are served at once and a recording is at most 8 MiB, so a client that holds sockets open cannot pin the path for long; the loudness check keeps no list of samples.
