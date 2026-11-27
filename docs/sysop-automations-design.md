# The Sysop: Time, Triggers, Memory and a Channel to You (Design)

Status: **implemented (2026-11-27)**. Builds on the resident brain ([sysop-resident-brain-design.md](sysop-resident-brain-design.md)): a
goal no longer pays a start, so the host can wake the brain often.

## 1. Purpose

The sysop answered a goal and forgot the world until the next one. It could not watch an agent and act later ("when the quota comes back, tell
it to go on"): its only workaround was to ask an agent in a tab to keep a timer of its own (Claude Code's `CronCreate`), which lives in the
memory of that session and acts through no policy, audit or panel. The CLIs' own schedulers are no answer either: Claude Code's lives in its
process, Antigravity's holds the turn open ([spikes/resident-brain.md](spikes/resident-brain.md) section 2).

What this adds, all of it owned by the host (the service), whatever the brain:

| Tool | What it is |
|---|---|
| `schedule` | a goal at a time: a cron line, an interval, or once |
| `trigger` | a goal when a tab changes: its state (blocked, idle, working, done), a text that appears on its screen, or the tab going away |
| `notify` | a message that reaches you even when you are not looking at the panel |
| `ask` | a question with buttons (or a free answer); the goal waits for it |
| `note` | the sysop's own notes, kept across goals, sessions and restarts |

And one change of the conversation: a message you send while a goal runs reaches that goal (**steering**) instead of waiting for it to end.

## 2. Automations (schedule and trigger)

### 2.1 The record

`<state>/sysop/automations.json`, private, written under a lock (`automations.lock`, flock) by whoever changes it: the MCP server (the brain
creates one), the CLI and the Web Studio (you pause, resume or cancel one), the service (it fires one). Each item:

```
{"id": "a3", "kind": "schedule" | "trigger", "prompt": "...", "state": "active" | "paused" | "ended", "why": "...",
 "created": t, "goal": "the goal that created it", "source": "its source",
 "cron": "*/10 * * * *" | "every": 600 | "at": t,                       (schedule)
 "tab": "t8y", "label": "2:api", "when": "blocked" | "idle" | "working" | "done" | "text" | "gone", "text": "regex", "cooldown": 300,   (trigger)
 "expires": t, "max_runs": n | 0, "runs": n, "last": t, "next": t}
```

### 2.2 The tools

`schedule(action=create, prompt, cron | every | at, expires, max_runs)` and `trigger(action=create, prompt, tab, when, text, cooldown, expires,
max_runs)`; `action=list | cancel | pause | resume` with `id` for both. The names and the shape follow Claude Code's `CronCreate` (a cron line,
a prompt), so a model knows how to use them.

- `cron`: five fields in the box's time zone (minute hour day month weekday: `*`, lists, ranges, steps). `every`: `90s`, `10m`, `2h`, `1d`
  (at least 60 s). `at`: `2026-11-27 14:10`, `14:10` (today, else tomorrow) or `in 20m`; once.
- `expires`: when it ends by itself; default 7 days for a schedule and 1 day for a trigger, at most 30 days. `max_runs`: 0 = until it expires.
- A trigger fires on a change, never on a state that only goes on: `when=blocked` fires when the tab becomes blocked; `when=text` when the
  text appears on a screen that did not show it at the last look. `cooldown` (default 5 min, at least 30 s) is the least time between two runs.
- At most 20 active automations.

### 2.3 Policy

- Creating one is a medium-risk action of the goal, rated and audited like `run`; at autonomy `full-auto` it goes at once.
- **A goal started by an automation cannot create another one without your approval**, at every autonomy level (the approval card of the
  panel; refused after `sysop.approval_timeout`): an automation must not grow automations.
- Cancel, pause and resume are low risk.
- Every change and every run is in the audit file (`automation` events) and in the panel's Events tab.

### 2.4 Firing

A thread of the service, apart from the goals (a schedule is due while a goal runs too), looks every 3 s at the schedules that are due and,
while a trigger is active, at the tabs (`swarmbox-tabs list`, and the screen only of a tab with a text trigger). A due automation becomes a goal of the queue with
source `schedule` or `trigger`; its text is framed: `[automation a3 (every 10 min, run 4, until 2026-12-04 10:00): ...]` then the prompt
and, for a trigger, what changed. One goal of an automation at a time: when its last goal still waits or runs, the run is skipped (the
Events tab says so). An automation whose time passed, whose runs are done or whose tab is gone (a trigger) ends with the reason.

## 3. `notify`

`notify(text, level=info | warn | urgent)`: written to the Events of the panel (`system_events.jsonl`, kind `notify`), shown as a toast in
every open Web Studio, and as a browser notification when the page allows it (the Web Studio asks once, from Settings → Sysop). `urgent` also
keeps the toast until it is closed. It counts as a step.

## 4. `ask`

`ask(question, options=[...], seconds=300)`: the goal writes `pending_question.json`; the panel shows the question with one button per option
and a field for another answer (the Web Studio, and `swarmbox-sysop answer TEXT` from any shell); the answer comes back as the tool's result.
No answer in `seconds` (at most 1800, and never past the goal's time budget): the result says so and the brain decides. Stop ends the wait.
A question is not an approval: it decides nothing by itself and the policy still rates what the brain does with the answer.

## 5. `note`

`note(action=write | read | list | delete, name, text)`: `<state>/sysop/notes/<name>.md`, at most 50 notes of 4000 characters. Each goal's
message starts with the list of notes (name and first line), so the brain knows what it kept; it reads one in full with `read`. The notes
are the sysop's, not the user's: + New does not remove them; `swarmbox-sysop notes [rm NAME]` lists or removes them.

## 6. Steering

A goal typed or spoken while another runs (sources web, panel, cockpit and voice; not cli or agent, whose scripts expect a queue) is first offered to the running goal: the MCP server adds
it to the result of the brain's next tool call (`[the user wrote while you were working: "..."]`). Delivered: that message's own goal ends
`done` ("passed to the goal that was running"). Not delivered when the running goal ends (no tool call came): it runs as a goal of its own,
first in the queue. Goals of automations are never steered into, and never steer.

## 7. Where it lives

| Part | File |
|---|---|
| record, cron, intervals, firing rules | `automations.py` |
| notes | `notes.py` |
| tools | `mcpserver.py` (`schedule`, `trigger`, `notify`, `ask`, `note`; steering in `call`) |
| firing, trigger watcher, steering, preseed | `service.py` |
| CLI | `cli.py`: `automations`, `automation cancel|pause|resume ID`, `answer TEXT`, `notes` |
| panel | `container/web/herdr`: `sysop-store.mjs` (snapshot), `routes-system.mjs` (`/api/sysop/automation`, `/api/sysop/answer`), `public/app.js` |
