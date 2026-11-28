# Positioning: SwarmBox among similar projects

Snapshot analysis from 2026-11-27. The ecosystem changes quickly, so check
competitors again before relying on any detail here.

## TL;DR

SwarmBox is **not unique feature by feature, but it is unique as a
combination and as a thesis**. Each individual capability (Web Studio, phone
UI, worktrees, approvals, tunnels, voice) exists elsewhere. What we did not
find ready-made is *one persistent, full machine for a swarm of agents,
operated by a resident sysop, reachable from anywhere*.

## Landscape

The space is crowded: the *awesome-agent-orchestrators* list alone has about
300 entries. The closest projects:

| Project | Overlap with SwarmBox |
|---|---|
| **Agent of Empires** (MIT, Rust) | Very high: Docker container per agent, automatic worktrees, web dashboard/PWA on the phone, tap-to-approve cards, remote access via Cloudflare Tunnel or Tailscale. No voice. |
| **Codeman** (MIT) | Very high: web dashboard over persistent tmux sessions, phone client with push, optional Docker, worktrees, voice input, approvals queue, an agent that manages other agents, cron, no telemetry. Supports Antigravity, Codex, OpenCode and more. |
| **Parallel Code** | Worktree plus container per task, mobile UI |
| **AgentBox** | Moves the project into an isolated VM, reattachable tmux |
| **devc, agent-sandbox, aicontainer** | Persistent container with Claude, Codex and OpenCode only, no studio |
| **Sculptor, Conductor, Claude Squad, Vibe Kanban** | Worktree orchestrators. Vibe Kanban lost the company behind it in April 2026 and is community-maintained. |
| **Docker Sandbox, first-party Anthropic/OpenAI offerings** | Official isolation and remote control, no multi-agent studio |

Taken together, Codeman and Agent of Empires cover most of the feature list in
our README.

## What is actually different about SwarmBox

1. **A machine for the agents, not a sandbox per session.** Others isolate
   *each task* in a disposable container. SwarmBox gives agents a complete,
   persistent environment: `sudo`, nested Podman, headless Chromium, and
   addons that survive `reset` and `update`. Agents can run containers,
   integration tests and a real browser, which slim sandboxes block.
2. **Rootless Podman as the foundation.** Nearly every competitor uses
   Docker. For users who want no daemon and no root, this matters.
3. **Sysop as an operator that routes work across tabs**, with Allow/Cancel
   gates, automations and triggers. Codeman has something close, but a
   resident "system operator" is a more ambitious idea.
4. **Offline voice via whisper.cpp.** Codeman has voice, but its page does not
   say whether it runs locally.
5. **Explicit security posture:** `cloudflared` secrets stay outside the box,
   no external CDN dependencies, and an honest threat model ("not a VM
   boundary").

None of these alone is exclusive; the combination is.

## Does it deserve to exist?

- **As the maintainer's daily driver: yes.** It already fits that
  workflow, and no competitor covers exactly the same thing.
- **As a project seeking adoption: only with sharper positioning.** As the
  README reads today, it looks like "yet another orchestrator with a web UI",
  a category where Codeman and Agent of Empires are ahead in features and
  reach. The differentiation lives in the thesis:
  - **"A real machine for your agents, not a sandbox"**, nested Podman and
    browser included.
  - **Sysop** as the core product, not an addon.
- **Structural risk:** Anthropic, OpenAI and Docker are absorbing the basic
  layer (sandboxing, remote control, cloud sessions). What is likely to
  survive is what they will not build: a self-hosted, opinionated environment
  with a resident operator.

## Suggested next steps

- Rewrite the README opening around the "persistent machine with a sysop"
  thesis.
- Spend an afternoon with Codeman and Agent of Empires to see what they do
  better. Push notifications, PWA install and QR pairing are clear
  candidates.
- Decide whether the goal is adoption or an excellent personal setup; that
  changes how much to invest in docs and outreach.

## Sources

- [Agent of Empires](https://www.agent-of-empires.com/)
- [Codeman](https://getcodeman.com/)
- [awesome-agent-orchestrators](https://github.com/andyrewlee/awesome-agent-orchestrators)
- [Parallel Code](https://github.com/johannesjo/parallel-code)
- [AgentBox](https://agent-box.sh/)
- [devc / ai-dev-container](https://github.com/grahambrooks/ai-dev-container)
- [agent-sandbox](https://github.com/mattolson/agent-sandbox)
- [aicontainer](https://github.com/stefanoginella/aicontainer)
- [Docker Sandbox vs DevContainers](https://shanedeconinck.be/posts/docker-sandbox-coding-agents/)
- [All My Agents](https://github.com/amack87/all-my-agents-web)
- [StarAgent](https://github.com/SiriusNEO/StarAgent)
- [Multiplexers — All the Agents](https://alltheagents.org/multiplexers/)
- [Best multi-agent coding tools 2026 (agentsroom)](https://agentsroom.dev/blog/best-multi-agent-coding-tools)
- [Best Vibe Kanban alternatives 2026 (nimbalyst)](https://www.nimbalyst.com/blog/best-vibe-kanban-alternatives-2026/)
- [Best AI agent orchestration tools (crystl)](https://crystl.dev/blog/best-ai-agent-orchestration-tools/)
- [Show HN: voice-control agents via tmux](https://news.ycombinator.com/item?id=46968740)
