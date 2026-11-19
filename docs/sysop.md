# The sysop

The `sysop` addon operates the box for you from a goal in plain words: "run the tests in the second tab", "ask Claude in the active tab to fix the failing test". It looks at your tmux tabs, types into them, looks again and tells you what happened.
It uses a **brain** (by default the headless Claude Code CLI) to decide what to do, but the brain has no hands of its own: every action goes through tmux, where you see it, and the host rates and may hold each one before it is typed.
The design and its reasons are in [addons-design.md](addons-design.md). This page says what is there now and how to use it.

## The path

```
goal (typed, spoken, or from a program) -> bus topic (sysop.topic, default `goal`) -> swarmbox-sysop (resident) -> brain (one process per goal)
brain -> tool calls (MCP) -> host policy -> swarmbox-tabs -> tmux tab         the panel shows each step
```

1. A goal is a line of text published on the topic of `sysop.topic` (default `goal`) of the bus ([design.md](design.md), section 6, "The bus"). Today that is `swarmbox-sysop goal "text"` in the box, the key `g`, the panel, or any program that runs `swarmbox bus pub goal` (with the topic of the setting). The `voice` addon publishes where `voice.topic` says (`source` `voice`): when that is the same name as `sysop.topic`, what you say into the microphone of the web terminal arrives as a goal. The two addons know nothing of each other; the shared name is the only connection. The sysop subscribes as a member of the group `sysop.group` (default `sysop`): two sysops in one group handle a goal once between them, one each in turn. Each goal carries a `source`, a label such as `panel`, `voice` or `cli`.
2. The resident `swarmbox-sysop serve` takes one goal at a time (up to five wait; the next is dropped and audited). It starts the brain, which gets the goal on its standard input and a list of tools.
3. The brain looks first (`list_tabs`, `read_tab`), then acts (`run`, `input`), checks the screen that comes back, and ends with `done`. The tools are served over MCP by `swarmbox-sysop mcp`, which acts on the box only through `swarmbox-tabs` (the tabs of the box: list, screen, send). The bus is for goals only, and the brain never sees it.
4. Before an action is typed, the host rates it and decides what must happen (autonomy levels, below). The panel, a pane of the shared tmux session that is up in every window (`sysop.panel`, below), shows the goal, the log, the countdown and the approval prompt, and an idle screen when there is no goal.

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
In a tab that runs an agent, a prompt is low; **any key while a dialog of the agent is on the screen is high**, Esc included: a permission dialog is the user's decision (Enter or a letter may grant it, Esc rejects the request), so it always needs approval, at every autonomy level, never a countdown. The system prompt also tells the brain not to touch a dialog: it reports it with `say` and finishes, unless the goal itself asks it to answer. A text that starts with `/` or `!` is **blocked** (a slash command or a shell escape). A tab that runs something else (an editor, `python`, `ssh`) is at least medium. Control characters are blocked, and long texts too.

`sysop.autonomy` chooses what each risk costs:

| Level | low | medium | high |
|---|---|---|---|
| `confirm-all` | approval | approval | approval |
| `confirm-risky` | countdown | approval | approval |
| `auto` (default) | at once | countdown | approval |

A **blocked** action is refused at once at every level, and no level lets a high risk go without your approval.

- **At once.** In `auto`, a harmless action (a prompt for an agent, `ls`, `git status`) is typed without waiting: that is the point of speaking a goal.
- **Countdown.** The panel shows the action in an amber bar ("sending in 4 s") and sends it after `sysop.countdown` seconds (default 4; `0` sends at once) unless you cancel it: the **Cancel** button of the panel or of the web strip, or `Ctrl+A V`.
- **Approval.** The action is shown in a red or amber bar ("allow? high risk") with two buttons, **Allow** and **Cancel**. It is not sent until you press Allow (in the panel, on the web strip, or `Ctrl+A a`): one tap, no word to type. If you do not answer within 60 seconds it is refused. A refusal, a veto or a block goes back to the brain as an error; it is told not to try another way round it.

## Stop and budgets

- **Stop.** `swarmbox-sysop stop` (`Ctrl+A X`, and the stop key of the panel) kills the brain's process group, ends the goal as `stopped` and drops the queue. It always works, also while an approval waits.
- **Steps.** At most `sysop.max_steps` tool calls per goal (default 20; `say` and `done` do not count). After that every tool but `say` and `done` answers with an error.
- **Time.** At most `sysop.max_seconds` per goal (default 300). The brain is killed at the deadline.

## How the tools reach the tabs

Each tool call runs the command `swarmbox-tabs` as a child process with a timeout and reads its JSON (`lib/swarmbox_sysop/tabsclient.py`): `list`, `screen TAB [--lines N]` and `send TAB --run - | --input -` (the text goes on standard input, never in the command line; the sysop never passes `--queue` or `--slash`). The library of `swarmbox-tabs` could be imported by path instead; the command is used, as its own documentation recommends, for these reasons:

- The command is the contract: its JSON, exit codes, lock per tab (two typers never interleave) and timeouts are the same for every caller, and the sysop imports nothing from a host file.
- A failure stays in a child: the MCP server of a goal holds the policy's memory of what was typed, and a hang or a bug in the tmux code is killed at the timeout (20 s for a read, 120 s for a send) and becomes an error the model can read.
- The price is one Python start (15 to 25 ms) per call. The settled-screen polling reads every 0.1 s until the screen has not changed for 0.5 s (at most 6 s); that polling stays in the sysop, because the command has no notion of "settled".

A failure of the command is `{"err", "msg"}`, and becomes an error result the model reads, with a hint: `dialog_open` (the user's decision: report it and stop), `busy_tab`, `slash_refused`, `no_such_tab`, `ambiguous_tab`, `not_submitted`, `lock_error`, `no_tmux`, `no_session`, and three of the sysop's own: `tabs_unavailable` (the command cannot be started; nothing was typed), `tabs_timeout` and `tabs_protocol`. The command is found as `swarmbox-tabs` on PATH, or as `SWARMBOX_SYSOP_TABS_CMD` says (tests). The MCP config passes on to the server what the command needs to find tmux (`PATH`, `TMUX_TMPDIR`, `SB_TABS_*`).

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

`sysop.brain` is either a preset name or a **command template**. The only preset today is `claude`: the headless Claude Code CLI (`claude -p`, using the login that is already in the box) with every built-in tool turned off (`--tools ""`; without it Bash stays on),
only the tools of the sysop allowed, a system prompt of its own, no session file and a turn limit. The model is `sysop.model` (default `sonnet`: about 11 to 15 seconds and a cent a goal in the tests; `haiku` is quicker, about 7 seconds, and costs about a tenth as much, at the price of more mistakes on a spoken goal that is not clear).

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

**Why a template and not an addon.** A brain is a command line, not code that needs to live inside SwarmBox: an addon would add an interface to maintain and a second place to decide what is allowed. With a template there is one rule: the brain gets tools, and the host policy sits in front of them whatever the brain is.
The `claude` preset is a piece of text, so the sysop does not depend on the `claude` addon being installed through SwarmBox; it only needs a `claude` command and a login.

## Security

- **Text from a tab is untrusted data.** A web page, a log or a file shown in a tab can contain instructions aimed at the brain. The system prompt says to treat them as data, and that held in the tests, but it is a model: the policy does not depend on it. Whatever the brain asks, the host rates the action itself.
- **`source` is a label.** The sender of a goal declares it; it is shown and audited and is never used to authorize anything. Any process in the box can publish a goal, the same trust it already has with `tmux send-keys`. Topic and group names are not protected either: any process of your user can also subscribe to the goal topic, read every goal, or join group `sysop` and take a round-robin share of them (the publisher is told it was received, and the sysop never hears it). `swarmbox bus topics` shows who listens on which topic. The bus socket is private to your user and the web tunnel does not reach it.
- **The risk is computed by the host** from the text and from what the tab runs (and, for keys, from the screen: a dialog is an agent's dialog whatever process shows it), never from what the brain says. The brain cannot lower it, choose the autonomy level or skip the countdown.
- **Nothing is hidden.** There is no side channel: the sysop reads tabs and types into tabs, through `swarmbox-tabs`, which drives tmux. Whatever it does is visible in a tab and written to the audit file. Screens it reads have the secrets removed first.
- **It is not a sandbox.** The risk analysis is best effort: an alias, a script or a Makefile can do anything, and a prompt typed into an agent tab is judged by that agent. The point is that the dangerous shapes cost a deliberate approval, and that you can stop it at any moment. Run it with `confirm-all` when in doubt.
- The brain inherits the environment of the service, so a credential in that environment (the Claude login) is available to the brain program. It is not given to the tabs.

## Install and try

The default brain is Claude Code, so first have the `claude` addon (`--with claude` when you install SwarmBox, or `swarmbox addon install claude` later) and a login (run `claude` once in a tab, or `swarmbox env add CLAUDE_CODE_OAUTH_TOKEN`).

```bash
swarmbox addon install sysop              # code of this repository, nothing is downloaded; the sysop starts at once and with every start of the box (the first `swarmbox-sysop` you type installs it too)
swarmbox                                 # a tab of the box; open a second one (Alt+N in the browser, or `swarmbox` in another terminal tab), then in the first:
swarmbox-sysop goal --wait "run echo hello in the second tab"
```

With the default autonomy the goal runs by itself: `echo hello` is typed at once (in `auto` a harmless action does not wait), it is typed in the second tab, and the command ends with `done: ...` (exit 0; `--wait` exits 1 when the goal failed or was stopped).
A setting is learned by the box when it is created, so to be asked about every action: `swarmbox config set sysop.autonomy confirm-all` and `swarmbox reset`: the goal then waits for you, so press Allow (the strip button, a click on the panel, or `Ctrl+A a`). You can also type the goal with `Ctrl+A g`, or speak it ([voice.md](voice.md)).

Check the service with `swarmbox-sysop status` (it runs from `prepare.sh` at every start of the box); `swarmbox-sysop --self-test` checks the install without a model, and `swarmbox tabs list` shows the tabs the sysop sees (`swarmbox bus topics` shows who listens on which topic). `swarmbox-sysop goal` exits with 3 when nobody listens (the service is not running) and 4 when the bus is not.
The brain needs a login: the `claude` preset uses the one already in the box.

| Key | Default | Meaning |
|---|---|---|
| `sysop.brain` | `claude` | a preset name or a command template (no line break) |
| `sysop.model` | `sonnet` | the model the `claude` preset asks for, and `{model}` |
| `sysop.autonomy` | `auto` | `confirm-all`, `confirm-risky` or `auto` |
| `sysop.countdown` | `4` | seconds an action waits for your veto, 0 to 30 (`0` sends at once) |
| `sysop.max_steps` | `20` | tool calls of one goal, 1 to 100 |
| `sysop.max_seconds` | `300` | seconds of one goal, 10 to 3600 |
| `sysop.topic` | `goal` | the bus topic the sysop listens on (`[a-z0-9][a-z0-9._-]{0,62}`); it hears voice when `voice.topic` is the same name |
| `sysop.group` | `sysop` | the group the sysop subscribes with (same charset); members of a group share the goals, one each |
| `sysop.panel` | `always` | when the panel is in tmux: `always` (in every window from the start of the box), `auto` (while a goal runs) or `off` (the sysop never opens it); see "The panel" |

A setting that equals its default is not passed to the box. Inside the box the sysop reads `SWARMBOX_SYSOP_BRAIN`, `_MODEL`, `_AUTONOMY`, `_COUNTDOWN`, `_MAX_STEPS`, `_MAX_SECONDS`, `_TOPIC`, `_GROUP` and `_PANEL_MODE` (not `SWARMBOX_SYSOP_PANEL`: that name, set to `1`, marks the start command of a panel pane, which `swarmbox-tabs` hides). Changing a setting needs `swarmbox reset`; after `swarmbox update` the addon refreshes its code at the next start.

## The panel

The panel is a pane of the tmux session (`swarmbox-sysop panel` runs it by hand). It shows the goal, what the brain did and said, and the countdown or the approval prompt, which carries the whole text of the action. A text that does not fit the pane says how many characters are left out and cannot be allowed there, only refused.
**When it is there is a setting, `sysop.panel`**, so that it never comes as a surprise:

| `sysop.panel` | What it does |
|---|---|
| `always` (default) | the panel is up **in every window** from the start of the box (except the narrow windows of a phone, see "Narrow windows"), and shows an idle screen when there is no goal. It follows new windows (a tmux hook on window creation) and re-docks when a window changes shape. `Ctrl+A S` (and `q` in the panel) hide it in all windows, and `Ctrl+A S` shows it again; the choice is remembered until the box starts again |
| `auto` | the panel opens, in the window you look at, when a goal arrives and closes a few seconds after the last goal; `Ctrl+A S` opens or closes the panel of one window by hand |
| `off` | the sysop never opens it; `Ctrl+A S` still opens one by hand, in the window you press it in |

Change it with `swarmbox config set sysop.panel auto` and `swarmbox reset`. The service (`serve --dock`, which the box starts) carries it out.

**Where it docks** (one panel per window, a pane that `swarmbox-tabs` never lists or targets):

| Window | Panel |
|---|---|
| landscape (at least twice as many columns as lines) | on the right, 20 % of the width, at least 40 columns |
| portrait (a phone held upright) | at the bottom, **30 %** of the height, at least 8 lines (never more than half the window) |
| landscape but narrower than 100 columns (the terminal would keep fewer than 60) | at the bottom, as portrait |

When a window changes shape the panel of that window (only that one) moves to the other layout and keeps running. Nothing it does takes the focus. A browser window that is being dragged makes dozens of resize events a second; the runs of the hook are coalesced (each leaves a mark and the one that holds the lock serves every mark), and it imports only the dock, so the box never has more than a few of them at once (10 Python processes and 114 MiB at the very peak of a burst of 200 resizes in the soak test, against 105 processes before). A panel that meets a problem (a file that went away, a full disk) says "The panel hit a problem and goes on (...)" in one line instead of printing a traceback in your tab.

**What the panel shows** is little, on purpose. The head is the name and one word for the state: `idle`, `working`, `sending` (a countdown), `allow?` (it waits for you), `done`, `failed`, `stopped` or `off`. Under it the goal in a line or two, then a line for each step in plain words (`✓ read tab 1`, `✓ run: pytest -q`, `✗` when it failed) and what the sysop said; the results of the tools stay out. At the bottom is what needs you, and only then: a **bar of colour the width of the panel** (amber for a countdown, red for a high risk, with the tab), the text of the action, and the buttons: **Allow** and **Cancel** for an approval, **Cancel** for a countdown, **Stop** while a goal runs, **Goal** when idle. The result of the last goal stays on screen when idle, also after a restart of the box. There is no list of keys, settings or topic on it: `swarmbox-sysop status` has those.
An idle panel does almost nothing: it looks once a second (a stat of two files and a lock probe) and reads the files only when one changed, so it uses well under 1 % of a core; the service in the mode `always` looks at tmux every 4 seconds and the hooks do the quick part.

**Narrow windows (a phone).** In the mode `always`, a window of **80 columns or fewer** is *compact*: it has **no panel** until it is opened, and the web page shows **one line** of what the sysop is doing instead (next, "The one line"). A window is as wide as the screen that was used last, so a phone held upright (about 64 columns) is compact while a computer on the same session is not, and each gets what suits it: when the phone takes the window the panel goes (at once by the resize hook), and when the computer takes it back the panel comes back (at the next sync, a few seconds at most). Wide windows are not touched by any of this. The panel of a narrow window has `✕ close` at the end of its head line and, when it is 7 rows tall or more, a blank line under the head so the content is not stuck to the title (a shorter panel keeps every row for the content). The head line is a dark purple bar from edge to edge. The panel at the right edge of a wide window (14 lines or more) has the bar three lines high, with the title on the middle one, where the web page puts the microphone.
What opens the panel is the global tmux option `@swarmbox_sysop_open`, which means the same for every compact window: **not set** is closed (the default) and **`1`** is "you opened it" (`Ctrl+A S`, the Panel button of the web strip or a tap on the line); it stays until you close it. `Ctrl+A S` in a compact window **toggles** this and does not hide the panels of the other screens. The panel of a compact window has a **close control** (` ✕ close `) at the right end of its head line, and its key `q` does the same: both close the compact panels and leave everything else alone, where `q` in a wide window hides the panels of all windows as before.

**The approval pane.** An action that **needs your approval** does not open the panel in a compact window. It makes a second, small pane at the bottom of the window, below everything, full width and about **10 rows** (never more than 40 % of the window, never more than half): the **approval pane**. It shows only the action and what it needs from you: a bar in the colour of the risk (` ALLOW?  high risk · tab 1`; it has no word `SYSOP`, the page reads that word to know the panel is up), the text of the action (five lines; one that does not fit says how many characters are left out and can then only be cancelled, as in the panel), and two **big buttons** side by side, **Allow** (violet) and **Cancel**, each half the width and three rows high. **One tap answers** (the first tap that gives the pane the focus answers too; the half second guard after a new action still applies), with the same decision file as the panel and the keys `a` or `y` and `c` or `n` (any other key does nothing, `q` included). It never takes the focus by itself and closes by itself about **1 second after the action is answered, expires or is stopped**, or when the window stops being compact. A countdown to veto does not open it (the line says it and Cancel is one tap away). A compact window that is made, or becomes compact, while an action waits gets one at the next look (half a second). The panel opened by hand and the approval pane are two kinds of pane (the pane option `@swarmbox_sysop_kind=approval` and the marker `SWARMBOX_SYSOP_APPROVAL=1` in the start command of the second): they live together, one of each at most in a window, and neither takes the other for its extra. Both are hidden from `swarmbox-tabs`. `Ctrl+A a` and `Ctrl+A V` keep answering from any tab (they write the decision file, not a pane). A wide window has no approval pane: its panel answers.

**The one line.** The service (every panel mode, the mode `off` included) keeps the global tmux option `@sysop_line` and tmux sends it to the clients as the title of the terminal (`set-titles` in `tmux.conf`; with no line the title is the usual `#S:#I:#W`). The value is `sysop:<state>:<sentence>`: the state is `idle` (`sysop:idle:`, a sysop is there with nothing to do: it is how the page knows to give a phone the compact strip), `working`, `sending`, `allow?`, `queued`, `done`, `failed` or `stopped`, and the sentence is one plain line of at most 140 characters, never a whole result: the latest thing the sysop said or did (`read tab 1`, `run: pytest -q`), the action itself while it waits (`sending`, `allow?`), the summary or the error when a goal ends. The end of a goal stays on the line for **10 seconds** and the line then says `idle`; the option is unset only when the service is down. It is a change of one option, so it costs nothing while the sysop is idle (a stat of two files every two seconds) and half a second of polling while a goal runs.

**Windows and panes.** A window never stays with only the panel in it, because that is not a tab: when the last pane of yours in a window is gone (`tmux kill-pane`, or the program ends), the window is closed with its panel. If it was the last window the session ends, exactly as it would without a panel. Killing the panel pane itself (`kill-pane` on it) is not a choice to hide it, so in the mode `always` it comes back at once; hide it with `Ctrl+A S` or `q`. The names of the tabs follow the program of your pane as usual in the mode `always` (the panel does not take the focus; after a click on it the name reads `python3` until you click back). In the modes `auto` and `off` a window with a panel keeps the name it had.

**The panel never takes the focus by itself.** Whether it is up already or opens when a goal arrives, what you are typing keeps going to your tab: not one key reaches the panel, where `c`, `x` and `g` would veto, stop or start something. The keys are reachable in three ways:

| What | How |
|---|---|
| From any tab, without focusing the panel | `Ctrl+A` then **`V`** cancel (a countdown is vetoed, an approval is refused; with nothing waiting it stops the goal), **`X`** stop the goal and the queue, **`a`** allow what waits, **`g`** type a goal (a small popup). On a phone: the **Allow** and **Cancel** buttons of the web strip send `Ctrl+A a` and `Ctrl+A V` |
| Click | a mouse click on the panel focuses it; then its own keys work (below) |
| Allow a high-risk action | the **Allow** button (strip, or a click on the panel's button), or `Ctrl+A a`: one press, nothing to type. If nothing waits it does nothing |

These are plain tmux prefix keys (`container/config/tmux.conf`, all four unbound in tmux itself, so a fast `Ctrl+A a` never loses a key); they call `swarmbox-sysop veto | stop | approve | goal`, which you can run from any shell of the box too (`approve` and `veto` act on the pane of the window you press them in; `goal` with no text asks for one line).
Keys of the focused panel: `a` or `y` allows, `c` or `n` cancels (it stops the goal when nothing waits), `x` stops the goal (`X` also drops the queue), `g` types a goal, Up and Down scroll the log, `q` hides the panels (the mode `always`) or closes this one. Keys are ignored for half a second after a new action appears, as a second guard. An action whose text does not fit on the panel cannot be allowed (only cancelled): you allow only what you can read.
The web terminal behaves the same: keys and mouse arrive from the browser as from any terminal.

## Troubleshooting

What you see, why, and what to do. Everything here was met in the soak and end-to-end runs; the messages are the exact ones.

| What you see | Why | What to do |
|---|---|---|
| `swarmbox-sysop: no_subscriber (is the sysop service running? swarmbox-sysop status)` (exit 3), or "Nobody is listening." on the microphone | nobody listens on the goal topic: the addon is not installed, the service is down (for a second or two after a crash), or the topics differ (`voice.topic` is not `sysop.topic`) | `swarmbox-sysop status`; `swarmbox bus topics` shows who listens on which topic; if it is not running, `swarmbox-addon prepare` starts it; if the command is missing, `swarmbox addon install sysop` |
| `sysop: not running (the box starts it at boot and again after a crash; by hand: swarmbox-addon prepare)` | the service is down | `swarmbox-addon prepare`. When the line says it keeps crashing (five abnormal exits in a minute), the cause is in `serve.log` of the sysop in the state folder; `swarmbox-sysop --self-test` checks the install |
| `swarmbox-sysop: ...` with exit 4, or "The bus of the box is not answering" on the microphone | the bus is away (it is restarted within seconds; after five crashes in a minute it waits) | `swarmbox-bus ping`; `swarmbox-bus restart` |
| `failed: the brain program 'claude' was not found: install it (swarmbox addon install claude) or set SWARMBOX_SYSOP_BRAIN` | the brain command is not in the box | `swarmbox addon install claude`, or point `sysop.brain` to a command that exists |
| `failed: the brain is not logged in (claude). Log in once in a tab (`claude`, then /login) or add CLAUDE_CODE_OAUTH_TOKEN with `swarmbox env add`` | the brain has no login (a login in `~/.claude` is enough and survives a reset) | run `claude` in a tab and log in, or `swarmbox env add CLAUDE_CODE_OAUTH_TOKEN` and `swarmbox reset`; then send the goal again |
| a tool answers "tmux is not available: the goal cannot act on the box" (`no_tmux`) | no `tmux` on the PATH of the service | this is a box without tmux; the image has it, so check what changed the PATH (`swarmbox-tabs list` in a tab shows the error) |
| a tool answers "there is no tmux session: the goal cannot act on the box" (`no_session`) | the tmux session `main` is gone (its server was killed) | open a tab (`swarmbox attach`, or the web terminal): it starts the session again, and the sysop goes on with the next goal |
| the panel is not there | `sysop.panel` is `off`, or it is `auto` and no goal is running; or you hid it (`Ctrl+A S` or `q` in the panel); or the service is down | `swarmbox config get sysop.panel`; press `Ctrl+A S`; `swarmbox-sysop status`. In the mode `always` the panel is back within a few seconds of a new window or a resize |
| `failed: the time budget of 300 s is spent: the brain was killed` | the goal took longer than `sysop.max_seconds` (a slow model, a long `wait`, an approval nobody gave) | send a smaller goal, or `swarmbox config set sysop.max_seconds 600` and `swarmbox reset`; `haiku` (the default) is the fast model |
| `failed: the brain used all its 23 turns without calling done` | the goal needs more steps than `sysop.max_steps` allows (the turns are the steps plus 3) | raise `sysop.max_steps`, or split the goal |
| the goal sits at "waiting for approval" and then ends refused | a high-risk action waits for you, and no answer came in 60 seconds | tap Allow (or `Ctrl+A a`); or Cancel (`Ctrl+A V`) to refuse it at once |
| the goal ends `failed` with "lost" after the service was killed or crashed | goals in flight are not kept | send the goal again |

`swarmbox-sysop status` also lists the last goals with their state, and the audit file (`events.jsonl`, above) says what the brain did, step by step.

## Limits of version 1

- One goal at a time, up to five waiting. No memory between goals: each starts with a new brain.
- Two ways to type: `run` and `input`. There is no tool that sees an image, and no `ask` (the brain cannot put a question to you and wait; it can `say` and `done`).
- Only text: a program that draws without text (a full-screen graphic) is not readable, and a full-screen program has no scrollback, so only what is visible counts.
- The risk analysis is conservative and best effort; it flags quoted separators too and can ask for approval of something harmless. It cannot read what a script does.
- Typing into an agent that is busy or has a dialog open is refused by `swarmbox-tabs` (`dialog_open`, `busy_tab`); the brain sees the error.
- Whether an agent is busy is read from the text of its screen: the footer of Claude Code says `· esc to interrupt` while it works. In a pane of about 40 to 70 columns (a phone held sideways) the end of that footer is cut and `swarmbox-tabs` reads the cut words, but in a pane of about 30 columns (a phone held upright, where every window is that narrow) the footer shows no sign at all, so a busy Claude Code looks idle there and a prompt is typed into its input box, where Claude Code queues it as it would a line you typed.
- One preset (`claude`). Other brains are templates you write and test.
- The panel works inside the shared tmux session (see "The panel"); `swarmbox-sysop stop` is the stop key from any shell of the box, and `swarmbox-sysop goal` gives a goal without it.
- An approval is not authenticated against code of your own user. It is a file in the state folder that the panel writes, and a process of yours, in a tab the brain types into for instance, can write it too. The host rates every command that mentions the sysop's files, `tmux`, the bus or the sysop commands (`swarmbox-tabs` included) as high risk, so the obvious ways to approve or to type into another tab cost an approval themselves, but a script or an alias can still do it. This is the same trust the box gives any of its processes, and one more reason to run with `confirm-all` when in doubt.
