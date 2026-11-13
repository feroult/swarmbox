#!/bin/bash
# swarmbox-statusline: the status line of Claude Code, in the style of the box (docs/theme.md). Claude Code runs this command and
# hands it a JSON document on standard input (the model, the directory, how full the context and the usage limits are); what it
# prints is the line under the input. Set it with  "statusLine": {"type": "command", "command": "swarmbox-statusline"}  in
# ~/.claude/settings.json.
#
#   ╶─ …/swarmbox ─ main ! ─ Sonnet 5.5 ─ ▰▰▰▱▱▱▱▱▱▱ 34% ─ 5h 71% ─ 7d 38%
#
# The directory in violet (the last two folders, "~" for the home), the branch in lavender with "!" when a tracked file has changes,
# the model dim, the context as a bar that is violet, fuchsia from 70% and rose from 90% (no orange: it would not be of the box),
# and the usage limits only when Claude Code reports them: dim, and the same fuchsia or rose from 70%. Claude Code prints this line in
# dimmed colors, so the tones are a step lighter than the ones of the prompt. The colors are 256-colour numbers.
#
# It never fails the line: without jq, with input that is not JSON, or in a directory git cannot read, it prints what it can, or
# nothing, and exits 0. NO_COLOR turns the colors off. COLUMNS, when it is set, makes it drop the 7d limit, then the 5h one, then
# the model, so the line fits.

LC_ALL=C.UTF-8
export LC_ALL

command -v jq > /dev/null 2>&1 || exit 0
input=$(cat)
[ -n "$input" ] || exit 0

# one jq call; the fields are joined with the unit separator, which is not blank to `read`, so an empty field stays empty
IFS=$'\037' read -r dir model ctx five week < <(
    printf '%s' "$input" | jq -r '
        [ (.workspace.current_dir // .cwd // ""),
          (.model.display_name // ""),
          (.context_window.used_percentage // "" | if type == "number" then floor else "" end),
          (.rate_limits.five_hour.used_percentage // "" | if type == "number" then floor else "" end),
          (.rate_limits.seven_day.used_percentage // "" | if type == "number" then floor else "" end)
        ] | map(tostring) | join("\u001f")' 2> /dev/null
) || exit 0
[ -n "$dir" ] || dir=$PWD

# the colors
if [ -n "${NO_COLOR:-}" ]; then
    c_dash=''; c_dim=''; c_violet=''; c_lav=''; c_empty=''; c_fuchsia=''; c_rose=''; c_off=''
else
    esc=$'\033'
    c_dash="${esc}[38;5;242m"; c_dim="${esc}[38;5;245m"; c_violet="${esc}[38;5;147m"; c_lav="${esc}[38;5;189m"
    c_empty="${esc}[38;5;239m"; c_fuchsia="${esc}[38;5;177m"; c_rose="${esc}[38;5;204m"; c_off="${esc}[0m"
fi

# level_color PERCENT -> REPLY: violet, fuchsia from 70, rose from 90
level_color() {
    if (($1 >= 90)); then REPLY=$c_rose; elif (($1 >= 70)); then REPLY=$c_fuchsia; else REPLY=$c_violet; fi
}

# the directory as the prompt shows it: ~ for the home, the last two folders with a leading "…/" when there are more
shown=$dir
[[ $shown == "$HOME" ]] && shown='~'
# shellcheck disable=SC2088  # the tilde is the one shown on the screen, not one to expand
[[ $shown == "$HOME"/* ]] && shown="~/${shown#"$HOME"/}"
IFS=/ read -r -a parts <<< "${shown#/}"
if ((${#parts[@]} > 2)); then shown="…/${parts[-2]}/${parts[-1]}"; fi

# the branch, and a mark when a tracked file has changes (what the "!" of the prompt means); no locks, so it never blocks a git command of yours
branch=''
dirty=''
if branch=$(GIT_OPTIONAL_LOCKS=0 git -C "$dir" symbolic-ref --short -q HEAD 2> /dev/null) && [ -n "$branch" ]; then
    :
elif short=$(GIT_OPTIONAL_LOCKS=0 git -C "$dir" rev-parse --short HEAD 2> /dev/null); then
    branch=$short   # a detached HEAD: the short hash
fi
if [ -n "$branch" ] && [ -n "$(GIT_OPTIONAL_LOCKS=0 git -C "$dir" status --porcelain --untracked-files=no 2> /dev/null | head -c 1)" ]; then dirty=' !'; fi

# the parts, each with the text it shows and its length; the optional ones can be dropped from the end
dash="${c_dash} ─ ${c_off}"
head_part="${c_dash}╶─ ${c_off}${c_violet}${shown}${c_off}"
head_len=$((3 + ${#shown}))
if [ -n "$branch" ]; then
    head_part+="${dash}${c_lav}${branch}${dirty}${c_off}"
    head_len=$((head_len + 3 + ${#branch} + ${#dirty}))
fi

model_part=''; model_len=0
if [ -n "$model" ]; then model_part="${dash}${c_dim}${model}${c_off}"; model_len=$((3 + ${#model})); fi

ctx_part=''; ctx_len=0
if [[ $ctx =~ ^[0-9]+$ ]]; then
    ((ctx > 100)) && ctx=100
    filled=$(((ctx * 10 + 50) / 100))
    level_color "$ctx"
    ctx_color=$REPLY
    cells_on=''; cells_off=''
    for ((i = 0; i < 10; i++)); do if ((i < filled)); then cells_on+='▰'; else cells_off+='▱'; fi; done
    ctx_part="${dash}${ctx_color}${cells_on}${c_empty}${cells_off}${c_off} ${ctx_color}${ctx}%${c_off}"
    ctx_len=$((3 + 10 + 1 + ${#ctx} + 1))
fi

# a usage limit: dim until 70%, then the color of the level
limit_part() { # label percent
    local color=$c_dim
    if (($2 >= 70)); then level_color "$2"; color=$REPLY; fi
    printf '%s%s%s %s%%%s' "$dash" "$color" "$1" "$2" "$c_off"
}
five_part=''; five_len=0
if [[ $five =~ ^[0-9]+$ ]]; then five_part=$(limit_part 5h "$five"); five_len=$((3 + 3 + ${#five} + 1)); fi
week_part=''; week_len=0
if [[ $week =~ ^[0-9]+$ ]]; then week_part=$(limit_part 7d "$week"); week_len=$((3 + 3 + ${#week} + 1)); fi

# fit the width when it is known: the 7d limit goes first, then the 5h one, then the model
if [[ ${COLUMNS:-} =~ ^[0-9]+$ ]] && ((COLUMNS > 0)); then
    total=$((head_len + model_len + ctx_len + five_len + week_len))
    if ((total > COLUMNS && week_len > 0)); then week_part=''; total=$((total - week_len)); fi
    if ((total > COLUMNS && five_len > 0)); then five_part=''; total=$((total - five_len)); fi
    if ((total > COLUMNS && model_len > 0)); then model_part=''; fi
fi

printf '%s%s%s%s%s\n' "$head_part" "$model_part" "$ctx_part" "$five_part" "$week_part"
exit 0
