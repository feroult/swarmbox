# Changelog fragments

Add one Markdown file per user-visible change in this folder instead of editing `CHANGELOG.md` directly.
This avoids merge conflicts when multiple branches or agent worktrees are open at the same time.

## Format

- **Filename:** `<YYYYMMDD>-<short-slug>.md` (for example, `20261126-mobile-popover-drag.md`).
- **Content:** one or more `- ` items using `Added:`, `Changed:`, `Fixed:`, or `Removed:` (at least 25 characters, describing what changed for a user of SwarmBox and, when not obvious, why).

Example:

```markdown
- Fixed: on a phone, the Web Studio's popover sheets now close when dragged down.
```

`sh dev/release.sh` validates the fragments, merges them into `CHANGELOG.md` under the new version heading, and removes the consumed files in the release commit.
