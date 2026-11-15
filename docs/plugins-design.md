# Plugins and the bus (design)

Status: **design only, nothing here is implemented.** It replaces the "tools" of SwarmBox 2.0 by "plugins", adds a small **bus** (topics and the
state of the box) that plugins use to talk without knowing each other, and splits the `voice` tool in two plugins, `voice` and `sysop`.
There is no compatibility with the 2.0 manifests: they are migrated once. Today's mechanism is in [design.md](design.md) (section 8).

## Why

- "Tool" means three things: a program installed on demand (`go`), an AI agent (`claude`), and the tools an agent calls (MCP tools). `voice`
  is none of them: it extends SwarmBox itself.
- The manifest has keys for one family of programs (`KIND`, `YOLO_FLAGS`, `YOLO_ALIAS`, `MCP_FLAGS`, `MCP_FORMAT`). The host only uses them to
  build a shell alias, which the plugin can do by itself.
- The `voice` of [voice-design.md](voice-design.md) hears, plans, shows and executes in one piece, and an input such as the microphone would have
  to know the one that handles it.
- Two rules guide the choices below. **An attribute is in the manifest only if the host acts on it for the plugin.** **The bus is plumbing
  and has no policy**: what to confirm, what is risky and what to refuse belongs to the plugin that acts (the sysop).

## Vocabulary

- **Plugin:** anything installable on demand in the box: `claude`, `gemini`, `opencode`, `gcloud`, `clasp`, `poetry`, `go`, `voice`, `sysop`.
  The command is `swarmbox-plugin list | install | remove | update` in the box, and `swarmbox plugin ...` on the host, which forwards it into the box
  as `swarmbox tool` does today; `swarmbox tool` is removed, not kept as an alias.

**Names of the commands.** Every SwarmBox command keeps the prefix: `swarmbox-bus`, `swarmbox-plugin`, `swarmbox-sysop`, `swarmbox-voice`, as the existing
`swarmbox-tool`, `swarmbox-web` and `swarmbox-mcp`. The prefix keeps them from colliding with anything on `PATH` and lets `swarmbox-<TAB>` list them. Inside
the box only these prefixed names exist (the plain `swarmbox` is the script of the host); on the host `swarmbox <name> ...` forwards to `swarmbox-<name>` in
the box. These commands are mostly run by programs, not typed, so their length does not matter.
- **There is no `KIND`.** A plugin is described by what it declares and what it does on the bus. The roles are words for the documentation and no
  code reads them: an *input* publishes goals (`voice`), an *operator* handles them (`sysop`), an *agent* is an AI CLI you work with, a *tool*
  is a program that helps the work. A role is a consequence of the topics a plugin uses, not a field.
- "MCP tools" always means the tools an agent calls, never a plugin.

## The plugin: a folder

```
plugins/<name>/
  plugin.conf    the manifest (KEY=VALUE, read by bash)
  install.sh     how to put it in the workspace
  prepare.sh     optional: runs at every start of the box
  shell.sh       optional: sourced by every interactive shell (bash and zsh)
  ...            whatever else the plugin ships
```

The host only runs these files at the right moments (install, start of the box, interactive shell).

| Mandatory attribute | What the host does with it |
|---|---|
| `SCHEMA` | knows how to read the manifest |
| `NAME` | install folder, name in the listing and in the commands (equal to the folder name) |
| `DESCRIPTION` | one line in the listing |
| `VERSION` | `latest` or a pinned version: decides when to reinstall and how to update |
| `COMMANDS` | creates the links on `PATH` that install on first call; the install is complete only when these commands exist |

| Optional attribute | What the host does with it |
|---|---|
| `UPDATE` (`managed`, the default, or `self`) and `UPDATE_CMD` | `self` runs the plugin's own update command |
| `PORTS` | publishes the ports when the box is created (`clasp` uses it for the OAuth login) |
| `SHA256_amd64`, `SHA256_arm64` | passes `TOOL_SHA256` to `install.sh`, which checks the download |

Rule that replaces `KIND`: `VERSION=latest` needs `UPDATE=self` and an `UPDATE_CMD`; any other version is pinned and `managed`.

**Not in the manifest, on purpose:**

- How a command starts. `YOLO_*` and `MCP_*` are gone: each plugin does it in its own `shell.sh`, which the box already loads for `clasp` and `go`
  (Claude defines its alias with the auto-approve flag and `--mcp-config`, Gemini defines `alias gemini='gemini --yolo'`, opencode defines a
  function that adds `--auto` only for `opencode` and `opencode run`, as the `clasp` function adds a port only to `login`). The host already sets
  `SWARMBOX_YOLO` (`0` turns auto-approve off) and a `shell.sh` reads it. `yolo` becomes "run the default agent" (`$SWARMBOX_AGENT`, recorded when the
  box is created from the first agent of `--with`).
- Services, tmux keys, web page assets, MCP servers a plugin offers: the plugin starts or installs them in `prepare.sh`.
- Which topics a plugin uses: it just uses them (below).
- `REQUIRES` and any handler declaration: with the bus no plugin needs to name another.

## The bus

A small service of the host, in the image, started with the box: `swarmbox-bus` on a unix socket in the run folder, with a command line, the same
`swarmbox-bus`, that works in shell. It is not a plugin, because everything else may depend on it. Nothing of the host (entrypoint, ttyd) depends on it either; components publish
when it is useful, and the bus is an integration surface, not a rewrite.

```
swarmbox-bus pub <topic> [message]    publish (JSON of one line, or plain text)
swarmbox-bus sub <topic>              stream the messages of a topic
swarmbox-bus get <topic>              read state
swarmbox-bus ls [prefix]              list topics of the state
swarmbox-bus watch                    everything that passes (to debug and audit)
```

Two things share it, and for now both are about **the box**, meaning tmux; plugin state is not in this version.

**Events (publish and subscribe).** A message is delivered to who is listening at that moment and is not kept.

| Topic | Delivery | Meaning |
|---|---|---|
| `goal` | **queue**: one consumer handles it | something someone wants done, `{"source": "voice", "text": "run the tests"}` |
| `tab/<tab>/in` | to the tab | a message to a tmux tab, below |

**State (read).** The bus answers from tmux when asked; nothing is stored.

| Topic | Read gives |
|---|---|
| `ls tab/` | the tabs: name, directory, running command, and which one is **active** (the window tmux shows; the pane of the sysop's own panel is never listed) |
| `get tab/<tab>/screen` | the text on the tab now (lines can be asked for), with the cursor position and simple markers for what the terminal shows highlighted (see "The screen of a tab") |

**The screen of a tab.** The text comes first because it is exact (a hash, a path or a number must be copied right), cheap, testable, and the
filter that removes secrets works on text. Plain text loses what only colour says, such as the option selected in a menu or a permission prompt. So
the answer of `get tab/<tab>/screen` is the text of the screen **after the secrets are removed**, plus the cursor position and markers for reverse video
and highlighted spans (for example `[sel]option 2[/sel]`), made from what tmux gives with `capture-pane -e`. This is the main thing an image would add,
at the cost of text.

**The tabs.** A tab is a tmux window; the pane it means is the active one unless `tab/<window>/<pane>` says otherwise; two windows with the same name
are told apart by their index. The bus has a built-in **plain driver** for `tab/<tab>/in`, with no intelligence and no process per tab:

- `{"run": "pytest -x"}`: the command is typed in the tab and Enter is pressed;
- `{"input": "text"}`: the text is typed as it is, without Enter. A few keys are written in braces, `{Esc}`, `{C-c}`, `{Enter}`, `{Up}`, and the driver
  only turns them into tmux key names.

The driver sends the typed text and then each key or the Enter as **separate steps with a short pause** between them (a first value of 150 ms, to be
tuned with the real program). A terminal program such as Claude Code treats a fast burst of characters as a paste, and an Enter that comes in the same burst
can become a line break instead of sending the prompt. The driver does not know what program runs in the tab and does not judge the message. The plugin that decides what to send (the sysop) knows what
it is doing. A smarter driver for one program could exist later; it is not part of this design.

**Trust.** Any process in the box can publish, which is the trust it already has with `tmux send-keys`. The web tunnel does not reach the bus: only the
audio entry of `voice` is exposed (see below).

## Voice and sysop

```
voice (input) --pub--> goal (queue) --> sysop --run / input--> tab/<tab>/in  (plain driver, tmux)
                                           ^
                                           +--get-- tab/<tab>/screen <-- tmux
```

- **`voice` only hears.** Microphone page, audio entry on the web terminal port, Whisper and its models. It turns audio into text and publishes it on
  `goal`. It never executes anything and does not know who listens; with no listener, `pub` fails at once and the page shows the error.
- **`sysop` handles goals and operates the box.** It subscribes to `goal`, and it has its own panel, where what you type becomes the same goal with
  `source` `panel`. It knows tmux and nothing about the other plugins. It is an agent loop: it looks at the tabs, acts, looks again.
- **Its tools**, served to the brain over MCP and validated by the host: `list_tabs`, `read_tab`, `run`, `input`, `wait`, `say`, `ask`, `done`. Everything it
  does goes through tmux and the bus: there is no hidden channel, and whatever it does you see in a tab.
- **The brain** is any command that speaks MCP and runs without interaction, set as a command template (`sysop.brain`, with the goal on its input and
  `{mcp_config}` for the MCP file). Ready values by name (`claude`, `gemini`...) are data, a piece of text, and not a dependency on those plugins.
- **Safety is a policy of the sysop.** The host-computed risk of each `run` and `input`, a high risk pauses the loop and asks in the panel, budgets
  (steps, time), a stop key that is always live, a live log in the panel and an audit file, an autonomy level as a setting (`confirm-all`,
  `confirm-risky`, `auto`), and an action of low risk (typing a prompt in a tab that runs an agent is one) is **not** asked first: the panel shows it with a countdown of a few seconds
  and sends it unless you veto it with `c`, so the path can be hands-free and a badly transcribed goal can still be stopped. Text read from a tab is untrusted data; the `source` of a
  goal tells how much to trust it.
- **Reused** from today's `voice` code: the contract and its validator, the risk, the context and its redaction, the panel and its docking in tmux.
  They move to the sysop; the executor becomes the plain driver of the bus.
- **Only audio crosses the tunnel.** The front on the web terminal port stays with `voice` as an audio entry with a fixed, minimal table.

## The plugins

| Plugin | Version | Ships | On the bus |
|---|---|---|---|
| `claude` | `latest`, `UPDATE=self` | `install.sh`, `shell.sh` | nothing |
| `gemini`, `opencode` | `latest`, managed | `install.sh`, `shell.sh` (opencode also `prepare.sh`) | nothing |
| `gcloud`, `poetry`, `go`, `clasp` | pinned (`clasp` has `PORTS`) | `install.sh` (`go`, `clasp` also `shell.sh`) | nothing |
| `voice` | pinned (whisper.cpp release) | `install.sh`, `prepare.sh`, the library, the page | publishes `goal` |
| `sysop` | pinned | `install.sh`, `prepare.sh`, the library, the panel | subscribes `goal`, reads and writes the tabs |

```
NAME=voice                                       NAME=sysop
DESCRIPTION="Speak goals: microphone, Whisper"   DESCRIPTION="Agent that operates the box from a goal"
VERSION=1.9.5                                    VERSION=1.0.0
COMMANDS="swarmbox-voice"                        COMMANDS="swarmbox-sysop"
```

## Migration (one time, no compatibility)

1. `container/tools/` becomes `container/plugins/`, `tool.conf` becomes `plugin.conf`, `PROVIDES` becomes `COMMANDS`, `DESCRIPTION` is added; `KIND` and
   the `YOLO_*` and `MCP_*` keys are removed and the agent plugins get a `shell.sh` with their aliases. `bashrc.sh` stops building aliases and `yolo` runs
   `$SWARMBOX_AGENT`.
2. `swarmbox-tool` becomes `swarmbox-plugin` (the validator drops the `KIND` rules and gains the `latest` / `UPDATE=self` rule); the user command is
   `swarmbox-plugin ...` in the box and `swarmbox plugin ...` on the host. The words `tool` and `--with` in the host script, the configuration, the help and the docs are renamed or kept where they read well.
3. `swarmbox-bus` is added to the image and started by the entrypoint, with `swarmbox bus ...` forwarded by the host script.
4. `voice` is split: the planning, the panel, the docking, the risk and the executor move to the new `sysop` (the executor becomes the plain driver of the
   bus); the page, the front, Whisper and the models stay in `voice`, which publishes on `goal`. The `voice.planner*` settings become settings of the sysop.
5. The tests and the guard tests that check command words in the docs follow the new names.

## Version 1

The path that version 1 has to do: you send audio from the browser; the sysop understands what you ask; it sees that Claude Code is open in the
**active** tab; it types the prompt there and presses Enter.

| Step | Where it is |
|---|---|
| audio from the browser, Whisper, text | exists (the page, the audio entry, `whisper.cpp`) |
| `voice` publishes `goal` | to build, with the bus |
| the sysop receives `goal`, lists the tabs, reads the active one and recognizes Claude Code | to build; it is a judgment of the model over `ls tab/` and the screen, with no special code |
| it types the prompt and presses Enter | to build, in the plain driver, with the separate steps above |

Scope of version 1:

- the bus with `goal`, `tab/<tab>/in`, `ls tab/` (with the active tab) and `get tab/<tab>/screen`, and `watch`;
- `voice` publishing on `goal`;
- the `sysop` with the tools `list_tabs`, `read_tab`, `run`, `input`, `say` and `done`, a panel that shows the goal and the log, the stop key and the
  countdown to veto an action; `wait`, `ask` and `look_tab` come later;
- the rename of tools to plugins is **not** on this path. The two new plugins are born with today's manifest and move to the plugin model afterwards.

What is not proven yet and has to be tested before it is trusted:

- the pause between the text and the Enter with the real Claude Code, in a real tmux (the biggest technical unknown);
- the agent loop through an MCP server with `claude -p`: today's real test was of the one-shot planner. Every tool call is one turn of the model, and the path has
  about four, so the total time is an estimate (10 to 15 s) and not a measurement.

## Order of work

1. The bus (`goal`, `tab/<tab>/in`, `ls tab/`, `get tab/<tab>/screen`, `watch`), with real tmux in a container, and the test of the Enter with the real Claude Code.
2. The `sysop` loop on top of the bus, with its panel, the countdown and the policy.
3. `voice` publishing on `goal`: this closes version 1.
4. The plugin model: rename, the manifest, `shell.sh` aliases, `swarmbox-plugin`, and the move of the two new plugins to it.
5. Later, if it is needed: plugin state on the bus, delivery to several subscribers, permissions per topic, smarter drivers for one program, and
   an image of a tab (next section).

## Possible extension: an image of a tab

A model that sees an image can read layout, colour and full-screen programs (`vim`, `htop`, menus) the way a person does. It is not a replacement for the
text, for these reasons: text is exact and an image read can get a character wrong; the secrets filter cannot work on pixels; an image costs more tokens
and time per tab and per step; returning an image through MCP depends on the brain accepting it, and text works with any; and text is easy to test.

If the real tests of the sysop show it failing to read full-screen programs, mostly permission prompts, a second tool `look_tab` is added next to
`read_tab`. It returns an image **drawn by SwarmBox from the filtered text and its markers**, never a capture of the real screen, so the secrets stay
removed, and it is only offered to a brain that accepts images. It needs a monospace font in the image and a light renderer (the one that makes the
image of the README is too heavy to run in the box). Until then, only the text with markers exists.

## Open questions

- **Who consumes `goal`.** A queue needs a subscriber running: the sysop starts a small resident one in its `prepare.sh`. Starting it on demand when a goal
  arrives would need a manifest attribute; left out until it hurts. With no subscriber, `pub` to a queue fails at once and nothing is buffered.
- Tab naming and the pane inside a window with several panes (above are the defaults). With several clients looking at different windows, "active" is
  the window of the client that was active last.
- The pause between text and keys (150 ms is a guess) and whether it depends on the program.
- The exact set of keys in braces, and the shape and versioning of the JSON of a message.
- Whether `watch` shows the contents of the screens or only that a read happened.
- The markers for highlighted spans (which attributes of the terminal become a marker, and the exact notation).
- How the Claude `shell.sh` keeps auto-approve and `--mcp-config` off subcommands such as `claude update` and `claude mcp list` (a function rather than an alias).
- Whether `--with` and the configuration key that lists what to install keep their names, now that they list plugins.
- The sysop's policy defaults (autonomy, limits) and the brain templates; [voice-design.md](voice-design.md) still describes the combined design and is
  to be reworked when this is implemented.
