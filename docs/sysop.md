# The sysop

The `sysop` addon operates the box for you from a goal in plain words: "run the tests in the second tab", "ask Claude in the active tab to fix the failing test". It looks at the tabs of the box (herdr-core terminals), types into them, looks again and tells you what happened.
It uses a **brain** (by default the headless Claude Code CLI) to decide what to do, but the brain has no hands of its own: every action goes through a tab, where you see it, and the host rates and may hold each one before it is typed.
The design and its reasons are in [addons-design.md](addons-design.md). This page says what is there now and how to use it.

## The path

```
goal (typed, spoken, or from a program) -> bus topic (sysop.topic, default `goal`) -> swarmbox-sysop (resident) -> brain (one process per goal)
brain -> tool calls (MCP) -> host policy -> swarmbox-tabs -> herdr-core tab   the panel shows each step
```

1. A goal is a line of text published on the topic of `sysop.topic` (default `goal`) of the bus ([design.md](design.md), section 6, "The bus"). Today that is `swarmbox-sysop goal "text"` in the box, the key `g`, the panel, or any program that runs `swarmbox bus pub goal` (with the topic of the setting). The `voice` addon publishes where `voice.topic` says (`source` `voice`): when that is the same name as `sysop.topic`, what you say into the microphone of the web terminal arrives as a goal. The two addons know nothing of each other; the shared name is the only connection. The sysop subscribes as a member of the group `sysop.group` (default `sysop`): two sysops in one group handle a goal once between them, one each in turn. Each goal carries a `source`, a label such as `panel`, `voice` or `cli`.
2. The resident `swarmbox-sysop serve` takes one goal at a time (up to five wait; the next is dropped and audited). It starts the brain, which gets the goal on its standard input and a list of tools.
3. The service pre-seeds a compact, nonce-framed `[box state (workspace)]` snapshot (repos with their agents and live states, pending worktrees, shells, parked sessions, and installed agents) alongside `[conversation so far]` on the brain's stdin. The brain can inspect further (`box_state`, `read_tab`), act (`run`, `input`, `tab`, `worktree`), check the settled screen, and end with `done`. The tools are served over MCP by `swarmbox-sysop mcp`, backed by `swarmbox-state`, `swarmbox-tabs`, `swarmbox-worktree`, and `swarmbox-pins`. The bus is for goals only, and the brain never sees it.
4. Before an action is typed, the host rates it and decides what must happen (autonomy levels, below). The panel (the Sysop panel of the Web Studio and of the terminal cockpit, below) shows the goal, the log, the countdown and the approval prompt, and the conversation when there is no goal.

## The tools

| Tool | What it does |
|---|---|
| `box_state` | read-only world model (`swarmbox-state`): `section="workspace"` (default: active tab, repos with running agents, live OSC 7501 states, branch/worktree, pending worktrees, shells, parked sessions, installed agents), `"system"` (disk, memory, health, addons, MCP, nested containers), or `"all"` |
| `read_tab` | the text on a tab's screen now, with secrets removed and the highlighted parts marked `[sel]`, `[bg]`, `[err]` |
| `run` | types text in a tab and presses Enter (a shell command, or a prompt for an agent such as Claude Code; auto-queues if working); returns the settled screen |
| `input` | types text or keys written in braces (`{Esc}`, `{C-c}`, `{Enter}`, `{Up}`) without Enter, to answer a program or interrupt it |
| `wait` | waits some seconds, or until a text shows on a tab |
| `tab` | unified tab & parked-session lifecycle (`action`: `open` with `agent`/`repo`/`cwd`/`name`/`worktree`, `focus`, `rename`, `close`, or `wake` a parked session); `open`/`wake` are low risk, `close` is high risk |
| `worktree` | `action`: `status` (read-only), `merge` (medium), or `remove` (high) — `target` accepts either a live tab or a `pending_worktrees` id/branch/path |
| `say` | shows a message to you in the panel; it does not count as a step |
| `done` | ends the goal with the reply: one or two sentences for an action, a few `- ` lines for a question about the box (at most 1200 characters; a longer one is sent back once to be written again) |

The **active** tab is the one the goal means when it names none: the window of the client that was used last. The panel pane of the sysop is never listed or targeted.

## Autonomy

The host computes a risk for each `run` and `input` from the text and from what the target tab runs; the brain cannot change it. In a shell tab the whole line is analysed (`rm`, `sudo`, `dd`, redirects to system paths, `ssh`, `curl | sh` and the like raise it); a line typed in several parts is judged as one.
In a tab that runs an agent, a prompt is low; **any key while a dialog of the agent is on the screen is high**, Esc included: a permission dialog is the user's decision (Enter or a letter may grant it, Esc rejects the request), so it needs approval at every autonomy level but `full-auto`, never a countdown. The system prompt also tells the brain not to touch a dialog: it reports it with `say` and finishes, unless the goal itself asks it to answer. A text that starts with `/` or `!` is **blocked** (a slash command or a shell escape). A tab that runs something else (an editor, `python`, `ssh`) is at least medium. Control characters are blocked, and long texts too.

`sysop.autonomy` chooses what each risk costs:

| Level | low | medium | high |
|---|---|---|---|
| `full-auto` (default) | at once | at once | at once |
| `auto` | at once | countdown | approval |
| `confirm-risky` | countdown | approval | approval |
| `confirm-all` | approval | approval | approval |

`full-auto` is the default: what you ask the sysop, it does, without asking for permission. The risk is still computed and written in
the log and the audit, but nothing waits for you; the system prompt tells the brain to act and to ask (in its reply, without acting)
only when it cannot tell what you want. Choose `auto` or a stricter level to have risky actions wait for you.

A **blocked** action is refused at once at every level, `full-auto` included: a block is not a question for you but something the host
cannot type as it reads (control characters, a Tab or a history reference in a shell, a text for an agent that starts with `/` or `!`),
and the error tells the brain how to write it. Below `full-auto`, no level lets a high risk go without your approval.

- **At once.** In `full-auto` every action, and in `auto` a harmless one (a prompt for an agent, `ls`, `git status`), is typed without waiting: that is the point of speaking a goal.
- **Countdown.** The panel shows the action in an amber bar ("sending in 4 s") and sends it after `sysop.countdown` seconds (default 4; `0` sends at once) unless you cancel it: the **Cancel** button of the panel or of the web strip, or `Ctrl+A V`.
- **Approval.** The action is shown in a red or amber bar ("allow? high risk") with two buttons, **Allow** and **Cancel**. It is not sent until you press Allow (in the panel, on the web strip, or `Ctrl+A a`): one tap, no word to type. If you do not answer within 60 seconds it is refused. A refusal, a veto or a block goes back to the brain as an error; it is told not to try another way round it.

## Stop and budgets

- **Stop.** `swarmbox-sysop stop` (`Ctrl+A X`, and the stop key of the panel) kills the brain's process group, ends the goal as `stopped` and drops the queue. It always works, also while an approval waits.
- **Steps.** At most `sysop.max_steps` tool calls per goal (default 20; `say` and `done` do not count). After that every tool but `say` and `done` answers with an error.
- **Time.** At most `sysop.max_seconds` per goal (default 300). The brain is killed at the deadline.

## How the tools reach the tabs

Each tool call runs the command `swarmbox-tabs` as a child process with a timeout and reads its JSON (`lib/swarmbox_sysop/tabsclient.py`): `list`, `screen TAB [--lines N]` and `send TAB --run - | --input -` (the text goes on standard input, never in the command line; a `run` always passes `--queue`, so an agent that is working takes the message and queues it; `input` (keys) and `--slash` never). The library of `swarmbox-tabs` could be imported by path instead; the command is used, as its own documentation recommends, for these reasons:

- The command is the contract: its JSON, exit codes, lock per tab (two typers never interleave) and timeouts are the same for every caller, and the sysop imports nothing from a host file.
- A failure stays in a child: the MCP server of a goal holds the policy's memory of what was typed, and a hang or a bug in the code that talks to herdr-core is killed at the timeout (20 s for a read, 120 s for a send) and becomes an error the model can read.
- The price is one Python start (15 to 25 ms) per call. The settled-screen polling reads every 0.1 s until the screen has not changed for 0.5 s (at most 6 s); that polling stays in the sysop, because the command has no notion of "settled".

A failure of the command is `{"err", "msg"}`, and becomes an error result the model reads, with a hint: `dialog_open` (the user's decision: report it and stop), `busy_tab`, `slash_refused`, `no_such_tab`, `ambiguous_tab`, `not_submitted`, `lock_error`, `no_backend`, `no_session`, `backend_error`, and three of the sysop's own: `tabs_unavailable` (the command cannot be started; nothing was typed), `tabs_timeout` and `tabs_protocol`. The command is found as `swarmbox-tabs` on PATH, or as `SWARMBOX_SYSOP_TABS_CMD` says (tests). The MCP config passes on to the server what the command needs to find herdr-core (`PATH`, `HC_SESSION`, `SB_TABS_*`).

## The audit file

Everything is written to `<state>/sysop/events.jsonl` (in the workspace state folder of the box, so it survives a restart): append-only, one JSON object per line, mode 0600, in a private folder. It has every goal, each call of the brain with its arguments,
the result, each decision (sent, vetoed, refused, approved, blocked) with the risk and the reasons, the `say` texts and the way the goal ended. Next to it, `goals/<id>/` keeps what the brain printed (`stream.jsonl`) and its error output. `swarmbox-sysop status` shows the service and its goals.

**The limit.** The audit file does not grow for ever: past **8 MiB** it is renamed to `events.jsonl.1` (the older ones move up to `.2` and `.3`) and a new file starts; the oldest of the three old files is deleted. So the audit takes **at most 32 MiB** of the workspace and keeps the last 24 to 32 MiB of events (some 20 000 goals); copy the old files elsewhere if you need more. Folders of goals are pruned to the newest 50, and `serve.log` of the sysop is moved to `serve.log.1` past 1 MiB.
A line that cannot be written (the disk is full) does not stop the service: it goes on and says so once a minute in `serve.log`. An action that types (`run`, `input`) is the exception: it is refused with "nothing was typed: the audit file cannot be written", because nothing should be typed that the audit cannot show; reading, `say` and `done` go on.

## Staying up

`prepare.sh` starts the service under a small **watcher** (`swarmbox-sysop serve --log --dock --watch`). If the service dies (a kill, the kernel's out-of-memory killer, a crash) the watcher starts it again after 1, 2, 4 ... 30 seconds, and the new service marks the goals that were in flight as `failed` ("lost": goals in flight are not kept, and nobody is told). A stop on purpose (SIGTERM to the service) ends the watcher too, and so does a refused setting (the reason is in `serve.log`).
Five abnormal exits within a minute make the watcher give up: it writes `crashloop` in the run folder, `swarmbox-sysop status` and the panel say that the service keeps crashing, and `swarmbox-addon prepare` (what the box runs at its start; run it by hand to try again) wakes the watcher and starts the service now. The bus and the web terminal have their own supervisors in the entrypoint; the sysop is an addon, so its supervisor is its own and the entrypoint knows nothing of it.
While the bus is away (it is restarted within seconds; after five crashes in a minute it waits for `swarmbox-bus restart`) the service retries every 1 to 5 seconds, so it listens again within five seconds of the bus coming back. A goal published in that gap is not delivered: the publisher is told (`swarmbox-sysop goal` exits 4 or 3, the microphone shows "The bus of the box is not answering" or "Nobody is listening").

## The brain

`sysop.brain` is `auto` (the default), the name of an agent, or a **command template**. A brain is declared by an agent's addon (`BRAIN` in its
`agent/agent.conf`, with its default `MODEL`); `auto` takes the one of the box's default agent, else of the first agent that declares one. Only
Claude Code declares one today, `claude`: the headless Claude Code CLI (`claude -p`, using the login that is already in the box) with every
built-in tool turned off (`--tools ""`; without it Bash stays on), only the tools of the sysop allowed, a system prompt of its own, no session file
and a turn limit. A box with no agent that declares a brain still runs the service, and a goal fails with that reason. The model is `sysop.model`
(default `auto`: the agent's `MODEL`, `sonnet` for Claude Code: about 11 to 15 seconds and a cent a goal in the tests; `haiku` is quicker,
about 7 seconds, and costs about a tenth as much, at the price of more mistakes on a spoken goal that is not clear). The tab namer is declared the
same way (`NAMER`, `NAMER_MODEL`: Claude Code's runs `haiku`); without an agent that declares one, tabs keep their names.

To use another brain, write a template. It is split into words like a shell would, but **no shell runs it**: a quote, `$(...)` or `;` in it is a character of an argument, never a command. Placeholders are replaced inside each word:

| Placeholder | Value |
|---|---|
| `{mcp_config}` | path of the MCP config file of the goal (required: the brain must reach the tools) |
| `{model}` | `sysop.model` (`auto`: the `MODEL` of the brain's agent; a template of no agent then needs `sysop.model` set) |
| `{system_prompt}`, `{system_prompt_file}` | the system prompt as a word, or in a file |
| `{max_turns}` | steps + 3 |
| `{goal_dir}` | the folder of the goal (also the working directory) |

Words at the front written `NAME=value` are environment variables of the brain, as in `env(1)`. The goal arrives on standard input, never on the command line. The brain's output is kept as the audit stream. A `{name}` that does not exist is an error. For example:

```bash
swarmbox config set sysop.brain 'OPENCODE_CONFIG={mcp_config} opencode run'
swarmbox reset
```

Some brains need more than a flag to find an MCP file (Gemini reads `mcpServers` from its own settings file), so such a template may need a small wrapper script of yours. The command you name must run without interaction, speak MCP over stdio, and exist in the box.

**Why a template and not an addon.** A brain is a command line, not code that needs to live inside SwarmBox: an addon would add an interface to maintain and a second place to decide what is allowed. With a template there is one rule: the brain gets tools, and the host policy sits in front of them whatever the brain is.
The `claude` preset is a piece of text, so the sysop does not depend on the `claude` addon being installed through SwarmBox; it only needs a `claude` command and a login.

## Security

- **Text from a tab is untrusted data.** A web page, a log or a file shown in a tab can contain instructions aimed at the brain. The system prompt says to treat them as data, and that held in the tests, but it is a model: the policy does not depend on it. Whatever the brain asks, the host rates the action itself.
- **`source` is a label.** The sender of a goal declares it; it is shown and audited and is never used to authorize anything. Any process in the box can publish a goal, the same trust it already has with `hc send`. Topic and group names are not protected either: any process of your user can also subscribe to the goal topic, read every goal, or join group `sysop` and take a round-robin share of them (the publisher is told it was received, and the sysop never hears it). `swarmbox bus topics` shows who listens on which topic. The bus socket is private to your user and the web tunnel does not reach it.
- **The risk is computed by the host** from the text and from what the tab runs (and, for keys, from the screen: a dialog is an agent's dialog whatever process shows it), never from what the brain says. The brain cannot lower it, choose the autonomy level or skip the countdown.
- **Nothing is hidden.** There is no side channel: the sysop reads tabs and types into tabs, through `swarmbox-tabs`, which drives herdr-core. Whatever it does is visible in a tab and written to the audit file. Screens it reads have the secrets removed first.
- **It is not a sandbox.** The risk analysis is best effort: an alias, a script or a Makefile can do anything, and a prompt typed into an agent tab is judged by that agent. The point is that the dangerous shapes cost a deliberate approval, and that you can stop it at any moment. Run it with `confirm-all` when in doubt.
- The brain inherits the environment of the service, so a credential in that environment (the Claude login) is available to the brain program. It is not given to the tabs.

## Install and try

The default brain is Claude Code, so first have the `claude` addon (`--with claude` when you install SwarmBox, or `swarmbox addon install claude` later) and a login (run `claude` once in a tab, or `swarmbox env add CLAUDE_CODE_OAUTH_TOKEN`).

```bash
swarmbox addon install sysop              # code of this repository, nothing is downloaded; the sysop starts at once and with every start of the box (the first `swarmbox-sysop` you type installs it too)
swarmbox                                 # a tab of the box; open a second one (Alt+N in the browser, or `swarmbox` in another terminal tab), then in the first:
swarmbox-sysop goal --wait "run echo hello in the second tab"
```

With the default autonomy the goal runs by itself: `echo hello` is typed at once (in `full-auto` nothing waits), it is typed in the second tab, and the command ends with `done: ...` (exit 0; `--wait` exits 1 when the goal failed or was stopped).
A setting is learned by the box when it is created, so to be asked about every action: `swarmbox config set sysop.autonomy confirm-all` and `swarmbox reset`: the goal then waits for you, so press Allow (the strip button, a click on the panel, or `Ctrl+A a`). You can also type the goal with `Ctrl+A g`, or speak it ([voice.md](voice.md)).

Check the service with `swarmbox-sysop status` (it runs from `prepare.sh` at every start of the box); `swarmbox-sysop --self-test` checks the install without a model, and `swarmbox tabs list` shows the tabs the sysop sees (`swarmbox bus topics` shows who listens on which topic). `swarmbox-sysop goal` exits with 3 when nobody listens (the service is not running) and 4 when the bus is not.
The brain needs a login: Claude Code's preset uses the one already in the box.

| Key | Default | Meaning |
|---|---|---|
| `sysop.brain` | `auto` | `auto`, an agent's name (its preset) or a command template (no line break) |
| `sysop.model` | `auto` | the model of the brain, `{model}` (`auto`: the `MODEL` its agent declares) |
| `sysop.autonomy` | `full-auto` | `full-auto`, `auto`, `confirm-risky` or `confirm-all` |
| `sysop.autocontext` | `1` | `1` writes a digest of each repository an agent works in and starts new sessions with it (below); `0` writes none and removes them |
| `sysop.countdown` | `4` | seconds an action waits for your veto, 0 to 30 (`0` sends at once) |
| `sysop.max_steps` | `20` | tool calls of one goal, 1 to 100 |
| `sysop.max_seconds` | `300` | seconds of one goal, 10 to 3600 |
| `sysop.topic` | `goal` | the bus topic the sysop listens on (`[a-z0-9][a-z0-9._-]{0,62}`); it hears voice when `voice.topic` is the same name |
| `sysop.group` | `sysop` | the group the sysop subscribes with (same charset); members of a group share the goals, one each |

A setting that equals its default is not passed to the box. Inside the box the sysop reads `SWARMBOX_SYSOP_BRAIN`, `_MODEL`, `_AUTONOMY`, `_AUTOCONTEXT`, `_COUNTDOWN`, `_MAX_STEPS`, `_MAX_SECONDS`, `_TOPIC` and `_GROUP`. Changing a setting needs `swarmbox reset`; after `swarmbox update` the addon refreshes its code at the next start.

## Repository context

A new session in a repository, such as an agent in a fresh worktree beside one that works on `main`, starts knowing nothing of it and
spends its first minute reading files that another session of the box already read. With `sysop.autocontext 1` (the default) the sysop
writes a short orientation of the repository, a **digest**, and the agent starts with it in its system prompt:

```
sysop (starts)  -> makes <state>/sysop/digests/ (the launchers know that autocontext is on) and prepares the repositories you use
agent launcher  -> the file of HEAD exists? no: publish `prepare` on tab.events
sysop           -> carries the repository's digest to HEAD at once (no model call); the first time in a repository: <commit>.wait and a
                   model call, then the file (or <commit>.none with why)
agent launcher  -> waits for the file: instant for a carry; the first time it says so on the terminal (about 10 s, Enter skips, 30 s
                   at most); the agent starts with CONTEXT_ARGS (file) or without; publish `session` (which file, or none, skipped,
                   off: started with SWARMBOX_CONTEXT=0, which publishes no `prepare`)
sysop           -> records the session (sessions/<tab>: the exact text) and a `session` line in the panel
```

- **What it is.** One call of the `DIGEST` an agent declares (Claude Code's: `claude -p` on haiku, no tools, no MCP, no settings) over the
  repository's file list, its top-level docs (README, CLAUDE.md, AGENTS.md, CONTRIBUTING), its manifests (`package.json`, `pyproject.toml`,
  `Makefile`, ...) and its last 15 commits: purpose, stack, layout, commands and conventions in at most 60 lines, under a header that says
  when and at which commit it was written and, when it was carried forward, at which commit the session starts and how many files changed
  since (listed at the end, at most 60). Nothing of the working tree that is not committed or listed is read.
- **When it is written.** When the service starts (a box start or reset), for the repositories you use: your agent pins, then the folders
  of the last 14 days (`recent-dirs.json`), 5 at most, the ones that need one (a few haiku calls). Else the first time a session starts in
  a repository: its launcher waits for the model, about 10 s, with one still line on the terminal (*sysop: preparing the context of REPO
  (first time) - Enter starts without it*, cut to the terminal's width) and, in the Web Studio, the SwarmBox loader over the terminal
  with the same words, a counter and **Start without it**; Enter starts the agent at once without it, a failed call starts it at once,
  and it never waits more than 30 s. Without a terminal (a script) it does not wait. **New agent** has a **Repository context** box
  (ticked for every new agent, `C` toggles it): unticked, the session starts without it (`SWARMBOX_CONTEXT=0`), its card shows a grey
  book (*context off*), and a restart of its pin starts without it too. The worktrees of a repository share it. A new
  commit gets the digest carried forward at once, with the list of files changed since, so a session never waits for the model; it is
  written again in the background when it is older than 6 hours, or when more than 40 files or a top-level doc or manifest changed and it is
  older than 30 minutes. A failed call (no login) is tried again after 10 minutes. `swarmbox-sysop context [DIR] [--force]` writes it now.
- **What you see.** In the Web Studio, the state is where the thing is, and the Sysop panel keeps what the sysop did by itself apart
  from your conversation:
  - **the repository header** in the sidebar has a pill: its age (`5m`, green) when the context is ready, *writing* (pulsing) while the
    model writes it, *failed* or *no answer* (amber). When the repository's name does not fit beside it, the pill keeps only its book
    (same colors) and the name keeps the room. A click opens its card: when and at which commit it was written, why, how many open
    sessions have it, **View**, **Retry now** after a failure, **Events**, and ↻ in its corner: it rewrites the context there, the card
    stays open, the arrow turns while the model writes, then a check. The viewer of a repository's context has the same ↻ (it reloads
    with the new text); the viewer of what a session got has none (that text does not change), but **See current context**;
  - **the agent card** says what its session started with: *STARTING · preparing context · 6s* while its launcher waits for the first
    context of the repository, then a small book beside Alt+N (green: with it; amber: without). The active tab's title bar has the
    same mark with words (**context** / **no context** / *preparing context…*). A click opens the session's card: why, at which commit,
    when the context was written and the files changed since, **See what it got** (the exact text, Rendered / Raw), **Rewrite the context**
    (it opens the repository's card, where the rewrite shows);
  - **the Sysop panel** has two tabs: **Chat** (you and the sysop) and **Events** (what it did by itself: the context it writes, with
    why, how long it took, or why it failed and **Retry now**; the repositories it prepared when the box started, in one row; the tab
    names it gave). *Now* holds a call that runs and a failure the repository still has; the Events tab counts those failures. Filters:
    All, Context, Tab names, and one repository (from a card's **Events**). No row per session: the card shows it. New conversation
    clears the chat, not the events. Every outcome is also a line `autocontext ...` in `serve.log`.
- **How the agent gets it.** The shell function of the agent passes `CONTEXT_ARGS` (Claude Code: `--append-system-prompt-file FILE`) when a
  session (not a one-shot `-p`) starts on a commit that has a digest. The agent's system prompt is fixed when it starts: a digest written
  later reaches the next session, not this one. It writes nothing on the terminal (an agent's screen would cover it at once).
- **Off.** `swarmbox config set sysop.autocontext 0` and `swarmbox reset` (or the toggle in **Settings → Sysop**): the sysop writes none and
  removes the folder when it starts, so no agent gets an old one and the marks are gone. A digest is only used for its own commit, so after `swarmbox addon remove
  sysop` the next commit has none.
- **Agents.** Only Claude Code declares `CONTEXT_ARGS` and `DIGEST` today; another agent starts as before.

## The panel

The panel is the Sysop panel of the Herdr Web Studio (the web terminal) and of the terminal cockpit (`swarmbox attach`), both drawn from the
same files of the service (`state.py`, `actions.py`). It shows the conversation of the last 12 hours, what the brain did and said under each
goal (`Sysop · ▸ N actions`, the steps fold), and, when an action waits for you, a confirmation card in the conversation with the whole text
of the action and **Allow** and **Cancel**. **New** starts a new conversation (`POST /api/sysop/new`): the panel and the brain forget the goals
before it. In the cockpit `Ctrl+A s` shows or hides the panel, `Ctrl+A g` types a goal, `Ctrl+A a` allows and `Ctrl+A v` cancels what waits
(or stops the goal); see [herdr-cockpit-design.md](herdr-cockpit-design.md). From any shell of the box, `swarmbox-sysop goal | approve | veto | stop`
do the same. The panel never takes the focus from the tab you type in.

The service also runs one herdr-core terminal of its own, labelled `swarmbox.role=sysop`, which speaks OSC 7501 so a remote `herdr-app` sees the
sysop in its Agent Inbox; `swarmbox-tabs`, the Web Studio and the cockpit hide it.

**The conversation, and which agent.** Each goal runs in a brain that starts with no memory, so the service puts what came before in front of it: the last 8 finished goals of the last 12 hours (`history.py`), each as the words of the user, the texts the sysop typed and into which tab, and the sentence it ended with. The block goes on the standard input of the brain, before `The goal now (source):` and the goal; the goal itself is stored and shown as the user said it. It holds no screens and nothing an agent answered. With it "and the other one?", "do it again" or "no, the second" mean what they meant. The system prompt (`brain.py`) tells the brain that, by default, what you say is a message for an agent that it passes on in your words, with no need to say "send it to Claude": the agent is inferred (the one in the active tab, else the tab the conversation was with, else the only agent), and only a clear operation on the box ("open a new tab", "run the tests in tab 2") is carried out by the sysop itself. A message for an agent that is working is typed anyway: the agents queue it.

## Troubleshooting

What you see, why, and what to do. Everything here was met in the soak and end-to-end runs; the messages are the exact ones.

| What you see | Why | What to do |
|---|---|---|
| `swarmbox-sysop: no_subscriber (is the sysop service running? swarmbox-sysop status)` (exit 3), or "Nobody is listening." on the microphone | nobody listens on the goal topic: the addon is not installed, the service is down (for a second or two after a crash), or the topics differ (`voice.topic` is not `sysop.topic`) | `swarmbox-sysop status`; `swarmbox bus topics` shows who listens on which topic; if it is not running, `swarmbox-addon prepare` starts it; if the command is missing, `swarmbox addon install sysop` |
| `sysop: not running (the box starts it at boot and again after a crash; by hand: swarmbox-addon prepare)` | the service is down | `swarmbox-addon prepare`. When the line says it keeps crashing (five abnormal exits in a minute), the cause is in `serve.log` of the sysop in the state folder; `swarmbox-sysop --self-test` checks the install |
| `swarmbox-sysop: ...` with exit 4, or "The bus of the box is not answering" on the microphone | the bus is away (it is restarted within seconds; after five crashes in a minute it waits) | `swarmbox-bus ping`; `swarmbox-bus restart` |
| `failed: no agent of this box declares a brain` | `sysop.brain` is `auto` and no agent addon of the box has a `BRAIN` | install an agent addon that declares one (`swarmbox addon install claude`), or set `sysop.brain` to a command |
| `failed: the brain program 'claude' was not found: install it (swarmbox addon install claude) or set SWARMBOX_SYSOP_BRAIN` | the brain command is not in the box | `swarmbox addon install claude`, or point `sysop.brain` to a command that exists |
| `failed: the brain is not logged in (claude). Log in once in a tab (claude, then /login) or add CLAUDE_CODE_OAUTH_TOKEN with swarmbox env add` (the agent's `LOGIN_HINT`) | the brain has no login (a login in `~/.claude` is enough and survives a reset) | run `claude` in a tab and log in, or `swarmbox env add CLAUDE_CODE_OAUTH_TOKEN` and `swarmbox reset`; then send the goal again |
| a tool answers that herdr-core is not available (`no_backend`) | no `hc` on the PATH of the service | the image has it, so check what changed the PATH (`swarmbox-tabs list` in a tab shows the error) |
| a tool answers that there is no herdr-core session (`no_session`) | the herdr-core daemon is not answering | open a tab (`swarmbox attach`, or the web terminal): it starts the daemon again, and the sysop goes on with the next goal |
| the panel is not there | you hid it (`Ctrl+A s` in the cockpit, the Sysop button of the Web Studio), or the service is down | show it again; `swarmbox-sysop status` |
| `failed: the time budget of 300 s is spent: the brain was killed` | the goal took longer than `sysop.max_seconds` (a slow model, a long `wait`, an approval nobody gave) | send a smaller goal, or `swarmbox config set sysop.max_seconds 600` and `swarmbox reset`; `haiku` (the default) is the fast model |
| `failed: the brain used all its 23 turns without calling done` | the goal needs more steps than `sysop.max_steps` allows (the turns are the steps plus 3) | raise `sysop.max_steps`, or split the goal |
| the goal sits at "waiting for approval" and then ends refused | a high-risk action waits for you, and no answer came in 60 seconds | tap Allow (or `Ctrl+A a` in the cockpit); or Cancel (`Ctrl+A v`) to refuse it at once |
| the goal ends `failed` with "lost" after the service was killed or crashed | goals in flight are not kept | send the goal again |

`swarmbox-sysop status` also lists the last goals with their state, and the audit file (`events.jsonl`, above) says what the brain did, step by step.

## Limits of version 1

- One goal at a time, up to five waiting. No memory between goals: each starts with a new brain.
- Two ways to type: `run` and `input`. There is no tool that sees an image, and no `ask` (the brain cannot put a question to you and wait; it can `say` and `done`).
- Only text: a program that draws without text (a full-screen graphic) is not readable, and a full-screen program has no scrollback, so only what is visible counts.
- The risk analysis is conservative and best effort; it flags quoted separators too and can ask for approval of something harmless. It cannot read what a script does.
- A `run` into an agent that is working is queued by the agent (the sysop passes `--queue`), as a line you typed would be; a dialog open in the agent is still refused by `swarmbox-tabs` (`dialog_open`): it is your decision. `busy_tab` only happens for keys (`input`).
- Whether an agent is busy is read from the text of its screen: the footer of Claude Code says `· esc to interrupt` while it works. In a pane of about 40 to 70 columns (a phone held sideways) the end of that footer is cut and `swarmbox-tabs` reads the cut words, but in a pane of about 30 columns (a phone held upright, where every window is that narrow) the footer shows no sign at all, so a working Claude Code looks idle there and a prompt is typed into its input box, where Claude Code queues it as it would a line you typed (which is also what the sysop does on purpose now).
- One preset (`claude`). Other brains are templates you write and test.
- The panel lives in the Web Studio and the terminal cockpit (see "The panel"); `swarmbox-sysop stop` is the stop key from any shell of the box, and `swarmbox-sysop goal` gives a goal without it.
- An approval is not authenticated against code of your own user. It is a file in the state folder that the panel writes, and a process of yours, in a tab the brain types into for instance, can write it too. The host rates every command that mentions the sysop's files, herdr-core (`hc`, `herdr`; `tmux` too), the bus or the sysop commands (`swarmbox-tabs` included) as high risk, so the obvious ways to approve or to type into another tab cost an approval themselves, but a script or an alias can still do it. This is the same trust the box gives any of its processes, and one more reason to run with `confirm-all` when in doubt.
