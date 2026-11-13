# The purple glow

One look for everything SwarmBox draws: near-black, violet and gray, with a glow that lights up in the middle. The letters of the banner run from dark gray
through violet to white and back; the prompt, the tmux bar, the progress line of a pull, the colors of `ls` and `grep`, and the terminal in the browser use the same few colors.

## The palette

| Role | Color | Where it is used |
|---|---|---|
| Background | `#0c0b10` | the browser terminal, the schemes below |
| Text | `#d4d4d8` | the browser terminal, the schemes below |
| Violet | `#a78bfa` | the glow of the banner, the directory of the prompt, `ls` folders (256-colour `141`) |
| Deep violet | `#6d28d9` | a selection, the active pane border, the marks of the prompt |
| Lavender | `#c4b5fd` | the cursor, `ls` links (`183`), what `grep` finds |
| Grays | `#52525b` `#71717a` `#a1a1aa` | separators, dim text, words |
| The band | `#27222f` | what is "selected" in tmux (the current window) and the directory of the prompt |
| Signals | `#ff6b78` red, `#4ade80` green, `#fbbf24` amber, `#e879f9` fuchsia | errors, success, warnings, the bash mode of Claude Code: the usual hues, kept, in tones of the same family |

## Where each piece lives

| Part | File |
|---|---|
| The banner and its glint | `container/scripts/banner.sh` |
| The prompt | `container/config/starship.toml` |
| The tmux bar, borders and selection | `container/config/tmux.conf`, `container/config/tmux-browser-keys.conf` |
| The line of a pull (`swarmbox update`) | `ui_c` in `container/host/swarmbox-host` |
| The 16 colors, the cursor and the selection of the browser terminal | the default `theme` in `container/scripts/swarmbox-web.sh` (`theme=` in `web-terminal.conf` replaces it) |
| The scrollbar of the browser terminal | `container/web/ttyd-style.css` |
| `ls` and `grep` | `LS_COLORS` and `GREP_COLORS` in `container/config/bashrc.sh`, in 256-colour numbers so they look the same in any terminal scheme |
| The messages of the scripts | `container/scripts/messages.sh` |

## Your own terminal

The box cannot paint the colors of the terminal you run it in: a selection made with `Shift` and dragged, the background and the 16 colors are your terminal's. These files give it the same
palette as the browser terminal (`tests/test_theme.py` checks that they agree):

- **Windows Terminal:** paste the scheme of [theme/windows-terminal.json](theme/windows-terminal.json) into `"schemes"` in `settings.json`, then set `"colorScheme": "SwarmBox Purple-Glow"` in your profile.
- **Ghostty:** copy [theme/ghostty](theme/ghostty) to `~/.config/ghostty/themes/swarmbox-purple-glow` and put `theme = swarmbox-purple-glow` in your config.
- **Claude Code:** copy [theme/claude-code.json](theme/claude-code.json) to `~/.claude/themes/swarmbox-purple-glow.json` and choose it with `/theme`. It sits on the dark theme and changes 29 colors: the selection, the
  periwinkle blue of permissions and suggestions, the cyan of background tasks, the box of the prompt, the gray of messages, Claude's own orange, and the tones of errors, successes and warnings. The colors that are
  signals of their own (the diffs, the colors of the subagents) are left alone.

## Claude Code: what is what on the screen

- **The line `⏵⏵ bypass permissions on (shift+tab to cycle)`** is the indicator of the permission mode, not the status line. Each mode has a color of the theme: `autoAccept` for accept edits, `planMode` for the plan mode,
  and `error` for bypass permissions (the rose of the palette, which is also the rose of an error).
- **The bars above and below the input box** are `promptBorder` (and `promptBorderShimmer` when it moves); in the bash mode the box takes `bashBorder`.
- **The status line** is a line you configure: Claude Code runs a command and prints what it prints. `container/scripts/swarmbox-statusline.sh` (installed as `swarmbox-statusline`) is one in the style of the box,
  `╶─ …/swarmbox ─ main ! ─ Sonnet 5.5 ─ ▰▰▰▱▱▱▱▱▱▱ 34% ─ 5h 71%`: the directory in violet, the branch, the model, and the context as a bar that is violet, fuchsia from 70% and rose from 90% (no orange), with the usage
  limits when Claude Code reports them. Turn it on with `"statusLine": {"type": "command", "command": "swarmbox-statusline"}` in `~/.claude/settings.json`.
- **Exact colors inside tmux.** Claude Code caps itself at 256 colors inside tmux, even with `COLORTERM=truecolor`, and turns each exact color of a theme into the nearest of 256 with a rough formula (the rose `#ff6b78` came out as the salmon
  `#ff8787`). The shell of the box sets `CLAUDE_CODE_TMUX_TRUECOLOR=1`, which lifts the cap, because the tmux of the box declares RGB; set it empty in your `~/.bashrc` to go back.

## Fonts

Nothing here needs a Nerd Font: the prompt and the pull line use plain box-drawing characters. The browser terminal asks for JetBrainsMono Nerd Font first and falls back to Cascadia Code, Consolas, Menlo and any monospace
(`fontFamily=` in `web-terminal.conf` changes it).
