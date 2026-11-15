# The sysop

The `sysop` tool operates the box for you from a goal in plain words: "run the tests in the second tab", "ask Claude in the active tab to fix the failing test". It looks at your tmux tabs, types into them, looks again and tells you what happened.
It uses a **brain** (by default the headless Claude Code CLI) to decide what to do, but the brain has no hands of its own: every action goes through tmux, where you see it, and the host rates and may hold each one before it is typed.
The design and its reasons are in [plugins-design.md](plugins-design.md). This page says what is there now and how to use it.

## The path

```
goal (typed, spoken, or from a program) -> bus topic `goal` -> swarmbox-sysop (resident) -> brain (one process per goal)
brain -> tool calls (MCP) -> host policy -> bus -> tmux tab                  the panel shows each step
```

1. A goal is a line of text published on the topic `goal` of the bus ([design.md](design.md), section 6, "The bus"). Today that is `swarmbox-sysop goal "text"` in the box, or any program that runs `swarmbox bus pub goal`. The `voice` tool is meant to publish there too. Each goal carries a `source`, a label such as `panel`, `voice` or `cli`.
2. The resident `swarmbox-sysop serve` takes one goal at a time (up to five wait; the next is dropped and audited). It starts the brain, which gets the goal on its standard input and a list of tools.
3. The brain looks first (`list_tabs`, `read_tab`), then acts (`run`, `input`), checks the screen that comes back, and ends with `done`. The tools are served over MCP by `swarmbox-sysop mcp`, which only talks to the bus.
4. Before an action is typed, the host rates it and decides what must happen (autonomy levels, below). The panel, a pane of the shared tmux session, shows the goal, the log, the countdown and the approval prompt.

## The tools

| Tool | What it does |
|---|---|
| `list_tabs` | the tabs (tmux windows) with their `@` id, label, directory, the program running and which one is active |
| `read_tab` | the text on a tab's screen now, with secrets removed and the highlighted parts marked `[sel]`, `[bg]`, `[err]` |
| `run` | types text in a tab and presses Enter (a shell command, or a prompt for an agent such as Claude Code); returns the settled screen |
| `input` | types text or keys written in braces (`{Esc}`, `{C-c}`, `{Enter}`, `{Up}`) without Enter, to answer a program or interrupt it |
| `wait` | waits some seconds, or until a text shows on a tab |
| `say` | shows a message to you in the panel; it does not count as a step |
| `done` | ends the goal with a one-line summary |

The **active** tab is the one the goal means when it names none: the window of the client that was used last. The panel pane of the sysop is never listed or targeted.

## Autonomy

The host computes a risk for each `run` and `input` from the text and from what the target tab runs; the brain cannot change it. In a shell tab the whole line is analysed (`rm`, `sudo`, `dd`, redirects to system paths, `ssh`, `curl | sh` and the like raise it); a line typed in several parts is judged as one.
In a tab that runs an agent, a prompt is low; answering one of its dialogs is high (it may grant permissions); a text that starts with `/` or `!` is **blocked** (a slash command or a shell escape). A tab that runs something else (an editor, `python`, `ssh`) is at least medium. Control characters are blocked, and long texts too.

`sysop.autonomy` chooses what each risk costs:

| Level | low | medium | high |
|---|---|---|---|
| `confirm-all` | approval | approval | approval |
| `confirm-risky` (default) | countdown | approval | approval |
| `auto` | countdown | countdown | approval |

A **blocked** action is refused at once at every level, and no level lets a high risk go without your approval.

- **Countdown.** The panel shows the action and sends it after `sysop.countdown` seconds (default 4; `0` sends at once) unless you veto it with `c`. This keeps a hands-free path (speak, wait four seconds) while a badly heard goal can still be stopped.
- **Approval.** The action is not sent until you type the word `run` and Enter in the panel. If you do not answer within 60 seconds it is refused. A refusal, a veto or a block goes back to the brain as an error; it is told not to try another way round it.

## Stop and budgets

- **Stop.** `swarmbox-sysop stop` (and the stop key of the panel) kills the brain's process group, ends the goal as `stopped` and drops the queue. It always works, also while an approval waits.
- **Steps.** At most `sysop.max_steps` tool calls per goal (default 20; `say` and `done` do not count). After that every tool but `say` and `done` answers with an error.
- **Time.** At most `sysop.max_seconds` per goal (default 300). The brain is killed at the deadline.

## The audit file

Everything is written to `<state>/sysop/events.jsonl` (in the workspace state folder of the box, so it survives a restart): append-only, one JSON object per line, mode 0600, in a private folder. It has every goal, each call of the brain with its arguments,
the result, each decision (sent, vetoed, refused, approved, blocked) with the risk and the reasons, the `say` texts and the way the goal ended. Next to it, `goals/<id>/` keeps what the brain printed (`stream.jsonl`) and its error output. `swarmbox-sysop status` shows the service and its goals.

## The brain

`sysop.brain` is either a preset name or a **command template**. The only preset today is `claude`: the headless Claude Code CLI (`claude -p`, using the login that is already in the box) with every built-in tool turned off (`--tools ""`; without it Bash stays on),
only the tools of the sysop allowed, a system prompt of its own, no session file and a turn limit. The model is `sysop.model` (default `haiku`, about 7 seconds and a tenth of a cent a goal in the tests; `sonnet` is slower and costs about ten times as much).

To use another brain, write a template. It is split into words like a shell would, but **no shell runs it**: a quote, `$(...)` or `;` in it is a character of an argument, never a command. Placeholders are replaced inside each word:

| Placeholder | Value |
|---|---|
| `{mcp_config}` | path of the MCP config file of the goal (required: the brain must reach the tools) |
| `{model}` | `sysop.model` |
| `{system_prompt}`, `{system_prompt_file}` | the system prompt as a word, or in a file |
| `{max_turns}` | steps + 3 |
| `{goal_dir}` | the folder of the goal (also the working directory) |

Words at the front written `NAME=value` are environment variables of the brain, as in `env(1)`. The goal arrives on standard input, never on the command line. The brain's output is kept as the audit stream. A `{name}` that does not exist is an error. For example:

```bash
swarmbox config set sysop.brain 'OPENCODE_CONFIG={mcp_config} opencode run'
swarmbox reset
```

Some brains need more than a flag to find an MCP file (Gemini reads `mcpServers` from its own settings file), so such a template may need a small wrapper script of yours. The command you name must run without interaction, speak MCP over stdio, and exist in the box.

**Why a template and not a plugin.** A brain is a command line, not code that needs to live inside SwarmBox: a plugin would add an interface to maintain and a second place to decide what is allowed. With a template there is one rule: the brain gets tools, and the host policy sits in front of them whatever the brain is.
The `claude` preset is a piece of text, so the sysop does not depend on the `claude` tool being installed through SwarmBox; it only needs a `claude` command and a login.

## Security

- **Text from a tab is untrusted data.** A web page, a log or a file shown in a tab can contain instructions aimed at the brain. The system prompt says to treat them as data, and that held in the tests, but it is a model: the policy does not depend on it. Whatever the brain asks, the host rates the action itself.
- **`source` is a label.** The sender of a goal declares it; it is shown and audited and is never used to authorize anything. Any process in the box can publish a goal, the same trust it already has with `tmux send-keys`. The bus socket is private to your user and the web tunnel does not reach it.
- **The risk is computed by the host** from the text and from what the tab runs, never from what the brain says. The brain cannot lower it, choose the autonomy level or skip the countdown.
- **Nothing is hidden.** There is no side channel: the sysop reads tabs and types into tabs, through the bus and tmux. Whatever it does is visible in a tab and written to the audit file. Screens it reads have the secrets removed first.
- **It is not a sandbox.** The risk analysis is best effort: an alias, a script or a Makefile can do anything, and a prompt typed into an agent tab is judged by that agent. The point is that the dangerous shapes cost a deliberate approval, and that you can stop it at any moment. Run it with `confirm-all` when in doubt.
- The brain inherits the environment of the service, so a credential in that environment (the Claude login) is available to the brain program. It is not given to the tabs.

## Install and try

```bash
swarmbox tool install sysop              # code of this repository, nothing is downloaded
swarmbox config set sysop.autonomy confirm-all
swarmbox reset                           # the box learns its settings when it is created
swarmbox attach                          # then, in a tab of the box:
swarmbox-sysop goal --wait "say hello in the second tab"
```

Check the service with `swarmbox-sysop status` (it runs from `prepare.sh` at every start of the box); `swarmbox-sysop --self-test` checks the install without a model, and `swarmbox bus ls tab/` shows what the sysop sees. `swarmbox-sysop goal` exits with 3 when nobody listens (the service is not running) and 4 when the bus is not.
The brain needs a login: the `claude` preset uses the one already in the box.

| Key | Default | Meaning |
|---|---|---|
| `sysop.brain` | `claude` | a preset name or a command template (no line break) |
| `sysop.model` | `haiku` | the model the `claude` preset asks for, and `{model}` |
| `sysop.autonomy` | `confirm-risky` | `confirm-all`, `confirm-risky` or `auto` |
| `sysop.countdown` | `4` | seconds an action waits for your veto, 0 to 30 (`0` sends at once) |
| `sysop.max_steps` | `20` | tool calls of one goal, 1 to 100 |
| `sysop.max_seconds` | `300` | seconds of one goal, 10 to 3600 |

A setting that equals its default is not passed to the box. Inside the box the sysop reads `SWARMBOX_SYSOP_BRAIN`, `_MODEL`, `_AUTONOMY`, `_COUNTDOWN`, `_MAX_STEPS` and `_MAX_SECONDS`. Changing a setting needs `swarmbox reset`; after `swarmbox update` the tool refreshes its code at the next start.

## The panel

`Ctrl+A` then `S` shows or hides the panel, a pane of the tmux session (`swarmbox-sysop panel` runs it by hand); with the service started with `--dock`, which the box does, it opens by itself when a goal arrives. It shows the goal, what the brain did and said, and the countdown or the approval prompt, which carries the whole text of the action. A text that does not fit the pane says how many characters are left out and cannot be allowed there, only refused. Keys: `c` vetoes a countdown or refuses an approval, `r` then the word `run` and Enter allows an approval, `x` stops the goal (`X` also drops the queue), `g` types a goal, Up and Down scroll the log, `q` closes the panel.

## Limits of version 1

- One goal at a time, up to five waiting. No memory between goals: each starts with a new brain.
- Two ways to type: `run` and `input`. There is no tool that sees an image, and no `ask` (the brain cannot put a question to you and wait; it can `say` and `done`).
- Only text: a program that draws without text (a full-screen graphic) is not readable, and a full-screen program has no scrollback, so only what is visible counts.
- The risk analysis is conservative and best effort; it flags quoted separators too and can ask for approval of something harmless. It cannot read what a script does.
- Typing into an agent that is busy or has a dialog open is refused by the bus; the brain sees the error.
- One preset (`claude`). Other brains are templates you write and test.
- The panel works inside the shared tmux session (see "The panel"); `swarmbox-sysop stop` is the stop key from any shell of the box, and `swarmbox-sysop goal` gives a goal without it.
- An approval is not authenticated against code of your own user. It is a file in the state folder that the panel writes, and a process of yours, in a tab the brain types into for instance, can write it too. The host rates every command that mentions the sysop's files, `tmux`, the bus or the sysop commands as high risk, so the obvious ways to approve or to type into another tab cost an approval themselves, but a script or an alias can still do it. This is the same trust the box gives any of its processes, and one more reason to run with `confirm-all` when in doubt.
