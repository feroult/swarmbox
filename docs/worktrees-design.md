# Git Worktrees for Multi-Agent Isolation (Design)

Status: **design agreed, implemented alongside [pins-design.md](pins-design.md)**.

## 1. Purpose & Philosophy

When two coding agents work concurrently on the same Git repository, sharing one working tree leads to overwritten edits, `index.lock` races, and mixed commits. SwarmBox solves this with standard Git worktrees managed by the box — **non-intrusive when there is no collision, 1-click intuitive when there is**.

Key principles:
- **Agent-agnostic:** uses pure `git worktree`, so it works identically for every agent of the registry (`claude`, `agy`, `opencode`, and any addon with an `agent/` folder) and plain shells — while passively recognizing worktrees created manually (including `claude --worktree`).
- **Zero forms on creation:** never blocks with branch-naming modals.
- **Zero data loss:** never deletes a worktree with uncommitted changes or unmerged commits without explicit user action, and never leaves the main repository stuck in a conflicted `MERGING` state.

---

## 2. Storage, Branching & Local Files

- **Location:** `~/.local/share/swarmbox/worktrees/<repo-name>/<id>` (`$SB_DATA_DIR/worktrees/`), keeping `~/swarmbox/` clean, avoiding `.gitignore` / build-watcher interference, and surviving `swarmbox reset`.
- **Metadata:** stored in `$SB_DATA_DIR/worktrees/.meta/<id>.json` (`{id, path, repo_root, repo_name, branch, base, created_at}`), never inside the worktree folder, so `git status` remains clean.
- **Branching:** creates a named branch `sb/wt-<short-id>` starting from the active repo's current **`HEAD`** (never detached `HEAD`, so agents can commit, push, and open PRs naturally).
- **Local `.env` files:** by default (`copy_env: true`, toggleable in Settings), copies root-level `.env` and `.env.*` files (`<= 64 KiB`, mode `0600`, excluding `.env.example`, `.env.sample`, `.env.template`). Also honors an optional `.swarmbox-worktree` file in the repo root listing extra relative paths to copy. Heavy dependency directories (`node_modules`, `.venv`, `target`) are never symlinked or copied.

---

## 3. Collision Detection & Interaction (Option 1 — `Ask` / `Auto` / `Off`)

Settings persisted in `$SB_CONFIG_DIR/worktree-prefs.json` (live-editable in Web Studio Settings, no host reset required):
- `mode`: `"ask"` (default) | `"auto"` | `"off"`
- `copy_env`: `true` (default) | `false`

When opening a new agent tab in a Git repo, waking a `PARKED` pin whose saved `cwd` points to a Git repo, or launching an agent (any agent of the registry: `agy`, `claude`, `opencode`, ...) manually inside an interactive shell:
1. Check whether **another live terminal** is already running on the same Git working tree. (`PARKED` pins do **not** count as collisions.)
2. **No collision:** opens directly in that directory with zero prompts.
3. **Collision detected:**
   - **`ask` (default):** in Web Studio, the unified **New agent** popover inspects the folder upfront (`GET /api/worktrees/check`), highlights the active collision inline, and pre-selects **`New worktree`** (toggleable to **`Same folder`** via click or `W`) so picking an agent launches in 1 click with no second popup — and when no collision exists in a Git repo, the same inline toggle lets users opt into a new worktree proactively. (Waking a colliding `PARKED` pin uses a compact 2-button popover, and in an interactive shell `swarmbox-worktree guard` prompts `[W] New worktree / [S] Same folder / [C] Cancel`, switches `cwd` to the new worktree, and labels the terminal tab so the topbar Merge button appears immediately.)
   - **`auto`:** immediately creates the isolated worktree and shows a non-blocking status toast (or one-line shell notice).
   - **`off`:** opens directly in the same folder without prompting.

When a `PARKED` pin collides and the user chooses **New worktree**, the new isolated worktree starts a fresh agent session (since `--continue` keys on directory path) while leaving the original folder untouched.

---

## 4. Merge & Conflict Flow

Git 2.47+ in the base image supports `git merge-tree --write-tree`, allowing SwarmBox to dry-run merges **in memory** with zero working-tree mutations.

Tabs running inside a worktree show a branch badge (`⎇ <branch> → <base>`) in the topbar. Clicking it opens a contextual popover whose primary button adapts to live Git state:

1. **Uncommitted changes in worktree:** primary action **`Ask agent to commit`** (sends a short commit prompt into that worktree's tab).
2. **Clean worktree & 0 conflicts (and clean base repo):** primary action **`Merge into <base> & clean`** (1-click merge on `<base>`, closes the tab, removes the worktree and deletes the merged branch), plus secondary actions **`Merge & keep tab`** and **`Open PR`**.
3. **Merge conflict detected:** primary action **`Resolve conflict with agent`** — sends a prompt to the **worktree's own agent** to pull `<base>` into the worktree, resolve conflicts with full context, run tests, and commit. The main repository is never left conflicted. Once committed, the branch is fast-forwardable and flips to the 1-click clean merge state.
4. **Main repository dirty:** blocks local merge cleanly and suggests committing in the main folder first or opening a PR.

---

## 5. Lifecycle, Cleanup & Pin Symmetry

| Tab state on close (`✕`) | Behavior |
| :--- | :--- |
| **Manual pin** (`swarmbox pins add`, no `auto`) | Becomes **`PARKED`** in the sidebar; worktree and branch stay intact until the pin is removed. |
| **Automatic pin or none, clean & 0 commits ahead** | The `auto` pin is removed with the tab, then the worktree and its empty `sb/wt-*` branch are removed (zero clutter, zero popup). |
| **Automatic pin or none, dirty or commits ahead** | Closes the tab without deleting anything; surfaces under **`Pending worktrees (N)`** in the sidebar with 1-click **Reopen** or **Remove**. |

Every agent tab has an automatic pin while it is open (see [pins-design.md](pins-design.md)), so the last two rows are the usual case; a worktree tab open when the box stops comes back on boot or as `PARKED`.

---

## 6. Minimal Sysop Integration

Keeping Sysop prompts lean and compliant with [addons-design.md](addons-design.md):
- **`list_tabs`** adds `"worktree": {"branch", "base", "repo", "path"}` only for tabs inside a worktree.
- **`open_tab`** gains one optional boolean parameter `worktree`.
- **One host capability (`swarmbox-worktree`)** exposed via one compact MCP action `worktree(tab, action, clean?)` (`action`: `status` | `merge` | `remove`): `status` is read-only; `merge` and `remove` pass through the Sysop risk policy.
