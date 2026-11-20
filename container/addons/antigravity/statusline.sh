#!/bin/bash
# Antigravity CLI (agy) status line, in the style of the box (docs/theme.md). Kept inside the antigravity addon so each agent owns its
# own configuration and status script without touching Claude Code's swarmbox-statusline.
#
# Antigravity CLI pipes the session state as JSON on standard input and prints what this script writes to standard output under the prompt:
#
#   Wide:
#     ╶─ …/swarmbox ─ main ! ─ Gemini 4 Neon (High) ─ ▰▰▱▱▱▱▱▱▱▱ 14% 149k ─ $0.42 ─ 7d 6%
#
#   Narrow (e.g. a 56-column phone, where one line would drop the model):
#     ╶─ …/swarmbox ─ main ! ─ $0.42 ─ 7d 6%
#     ╶─ Gemini 4 Neon (High) ─ ▰▰▱▱▱▱▱▱▱▱ 14% 149k
#
# Directory in violet (last two folders, "~" for home), git branch in lavender with "!" for tracked changes, active model dim,
# context bar in violet (fuchsia from 70%, rose from 90%; never orange) with total tokens when reported, estimated USD cost when > 0,
# quota usage (dim until 70%, then fuchsia/rose), and running subagents/tasks only when > 0.
#
# Width fitting uses COLUMNS when set, else .terminal_width from the JSON payload. On wide screens optional parts drop from least to most
# critical (activity -> quotas -> cost -> tokens). When directory + model + context still do not fit on one line, the script switches to
# two clean lines so the current directory, active model, and context usage always remain visible.
# Never fails the line: missing jq, bad JSON, or an unreadable folder prints what it can (or nothing) and exits 0. NO_COLOR turns ANSI off.

LC_ALL=C.UTF-8
export LC_ALL

command -v jq > /dev/null 2>&1 || exit 0
input=$(cat)
[ -n "$input" ] || exit 0

# One jq pass extracts every field joined by the unit separator (0x1f), so empty fields stay distinct to `read`.
IFS=$'\037' read -r dir vcs_branch vcs_dirty model ctx total_tok cost_usd q1_lbl q1_used q2_lbl q2_used sub_run tasks twidth < <(
    printf '%s' "$input" | jq -r '
        def fmt_tok:
            if type != "number" or . <= 0 then ""
            elif . >= 1000000 then ((. / 100000 | floor) / 10 | tostring) + "M"
            elif . >= 1000 then ((. / 1000 | floor) | tostring) + "k"
            else (floor | tostring)
            end;
        def q_label($k; $sec):
            ($k | ascii_downcase) as $l |
            if ($l | test("5h|five")) then "5h"
            elif ($l | test("week|7d")) then "7d"
            elif ($l | test("day|daily|24h|1d")) then "1d"
            elif ($sec | type) == "number" and $sec > 86400 then "7d"
            elif ($sec | type) == "number" and $sec > 0 and $sec <= 21600 then "5h"
            else ($k | .[0:8])
            end;
        def q_rank($lbl):
            if $lbl == "5h" then 0 elif $lbl == "1d" then 1 elif $lbl == "7d" then 2 else 3 end;
        (
            (.quota // {} | if type == "object" then to_entries else [] end)
            | map(
                select((.value | type) == "object" and (.value.disabled != true) and ((.value.remaining_fraction | type) == "number"))
                | {
                    lbl: q_label(.key; .value.reset_in_seconds),
                    used: (((1 - .value.remaining_fraction) * 100) | floor | if . < 0 then 0 elif . > 100 then 100 else . end)
                  }
              )
            | group_by(.lbl)
            | map({lbl: .[0].lbl, used: (map(.used) | max)})
            | sort_by(q_rank(.lbl), .lbl)
        ) as $qs |
        (
            if (.context_window.total_input_tokens | type) == "number" or (.context_window.total_output_tokens | type) == "number" then
                ((.context_window.total_input_tokens // 0) + (.context_window.total_output_tokens // 0))
            elif (.context_window.current_usage | type) == "object" then
                ((.context_window.current_usage.input_tokens // 0) + (.context_window.current_usage.cache_read_input_tokens // 0) + (.context_window.current_usage.cache_creation_input_tokens // 0))
            else 0 end
        ) as $tok |
        (
            if (.subagents | type) == "array" then
                [.subagents[] | select((type == "object") and .status == "running")] | length
            else 0 end
        ) as $subs |
        (
            if (.model | type) == "string" then .model
            elif (.model | type) == "object" then (.model.display_name // .model.label // .model.name // .model.id // "")
            else "" end
        ) as $mdl |
        [
            (.workspace.current_dir // .workspace.project_dir // .cwd // ""),
            (.vcs.branch // ""),
            (if .vcs.dirty == true then "1" else "" end),
            $mdl,
            (.context_window.used_percentage // "" | if type == "number" then floor else "" end),
            ($tok | fmt_tok),
            (if (.cost.total_usd | type) == "number" and .cost.total_usd > 0 then .cost.total_usd else "" end),
            ($qs[0].lbl // ""),
            ($qs[0].used // ""),
            ($qs[1].lbl // ""),
            ($qs[1].used // ""),
            (if $subs > 0 then $subs else "" end),
            (if (.task_count | type) == "number" and .task_count > 0 then (.task_count | floor) else "" end),
            (if (.terminal_width | type) == "number" and .terminal_width > 0 then (.terminal_width | floor) else "" end)
        ] | map(tostring) | join("\u001f")' 2> /dev/null
) || exit 0
[ -n "$dir" ] || dir=$PWD

# Palette (256-colour numbers, matching container/scripts/swarmbox-statusline.sh and docs/theme.md)
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

# build_bar PERCENT CELLS -> REPLY (colored bar + percentage)
build_bar() {
    local pct=$1 cells=$2 filled i cells_on='' cells_off='' col
    filled=$(((pct * cells + 50) / 100))
    level_color "$pct"
    col=$REPLY
    for ((i = 0; i < cells; i++)); do
        if ((i < filled)); then cells_on+='▰'; else cells_off+='▱'; fi
    done
    REPLY="${col}${cells_on}${c_empty}${cells_off}${c_off} ${col}${pct}%${c_off}"
}

# Directory: ~ for home, last two segments with "…/" when deeper
shown=$dir
[[ $shown == "$HOME" ]] && shown='~'
# shellcheck disable=SC2088  # literal tilde shown on screen
[[ $shown == "$HOME"/* ]] && shown="~/${shown#"$HOME"/}"
IFS=/ read -r -a parts <<< "${shown#/}"
if ((${#parts[@]} > 2)); then shown="…/${parts[-2]}/${parts[-1]}"; fi

# Git branch and tracked-file dirty mark (prefer payload vcs.branch when given, else inspect repo read-only)
branch=$vcs_branch
dirty=''
if [ -n "$branch" ]; then
    [ "$vcs_dirty" = "1" ] && dirty=' !'
else
    if branch=$(GIT_OPTIONAL_LOCKS=0 git -C "$dir" symbolic-ref --short -q HEAD 2> /dev/null) && [ -n "$branch" ]; then
        :
    elif short=$(GIT_OPTIONAL_LOCKS=0 git -C "$dir" rev-parse --short HEAD 2> /dev/null); then
        branch=$short
    fi
    if [ -n "$branch" ] && [ -n "$(GIT_OPTIONAL_LOCKS=0 git -C "$dir" status --porcelain --untracked-files=no 2> /dev/null | head -c 1)" ]; then
        dirty=' !'
    fi
fi

lead="${c_dash}╶─ ${c_off}"
dash="${c_dash} ─ ${c_off}"
head_part="${lead}${c_violet}${shown}${c_off}"
head_len=$((3 + ${#shown}))
if [ -n "$branch" ]; then
    head_part+="${dash}${c_lav}${branch}${dirty}${c_off}"
    head_len=$((head_len + 3 + ${#branch} + ${#dirty}))
fi

model_part=''; model_len=0
if [ -n "$model" ]; then
    model_part="${dash}${c_dim}${model}${c_off}"
    model_len=$((3 + ${#model}))
fi

ctx_part=''; ctx_len=0
tok_part=''; tok_len=0
if [[ $ctx =~ ^[0-9]+$ ]]; then
    ((ctx > 100)) && ctx=100
    build_bar "$ctx" 10
    ctx_part="${dash}${REPLY}"
    ctx_len=$((3 + 10 + 1 + ${#ctx} + 1))
    if [ -n "$total_tok" ]; then
        tok_part=" ${c_dim}${total_tok}${c_off}"
        tok_len=$((1 + ${#total_tok}))
    fi
elif [ -n "$total_tok" ]; then
    tok_part="${dash}${c_dim}${total_tok}${c_off}"
    tok_len=$((3 + ${#total_tok}))
fi

cost_part=''; cost_len=0
if [ -n "$cost_usd" ]; then
    cost_fmt=$(LC_NUMERIC=C printf '$%.2f' "$cost_usd" 2> /dev/null || true)
    if [ -n "$cost_fmt" ]; then
        cost_part="${dash}${c_dim}${cost_fmt}${c_off}"
        cost_len=$((3 + ${#cost_fmt}))
    fi
fi

limit_part() { # label percent
    local color=$c_dim
    if (($2 >= 70)); then level_color "$2"; color=$REPLY; fi
    printf '%s%s%s %s%%%s' "$dash" "$color" "$1" "$2" "$c_off"
}
q1_part=''; q1_len=0
if [ -n "$q1_lbl" ] && [[ $q1_used =~ ^[0-9]+$ ]]; then
    q1_part=$(limit_part "$q1_lbl" "$q1_used")
    q1_len=$((3 + ${#q1_lbl} + 1 + ${#q1_used} + 1))
fi
q2_part=''; q2_len=0
if [ -n "$q2_lbl" ] && [[ $q2_used =~ ^[0-9]+$ ]]; then
    q2_part=$(limit_part "$q2_lbl" "$q2_used")
    q2_len=$((3 + ${#q2_lbl} + 1 + ${#q2_used} + 1))
fi

act_part=''; act_len=0
act_txt=''
if [ -n "$sub_run" ]; then act_txt="${sub_run} sub"; fi
if [ -n "$tasks" ]; then act_txt="${act_txt:+$act_txt }${tasks} task"; fi
if [ -n "$act_txt" ]; then
    act_part="${dash}${c_lav}${act_txt}${c_off}"
    act_len=$((3 + ${#act_txt}))
fi

# Width budget: COLUMNS wins over JSON terminal_width.
width=''
if [[ ${COLUMNS:-} =~ ^[0-9]+$ ]] && ((COLUMNS > 0)); then
    width=$COLUMNS
elif [[ $twidth =~ ^[0-9]+$ ]] && ((twidth > 0)); then
    width=$twidth
fi

# Narrow terminals where directory + model + context cannot fit on one line switch to two clean lines
# so the current folder, active model, and context bar are never dropped (e.g. on a 56-column phone).
if [ -n "$width" ] && [ -n "$model" ] && ((head_len + model_len + ctx_len > width)); then
    # Line 1: directory + branch + whatever optional badges fit
    l1_cost=$cost_part; l1_q1=$q1_part; l1_q2=$q2_part; l1_act=$act_part
    l1_total=$((head_len + cost_len + q1_len + q2_len + act_len))
    if ((l1_total > width && act_len > 0)); then l1_act=''; l1_total=$((l1_total - act_len)); fi
    if ((l1_total > width && q2_len > 0)); then l1_q2=''; l1_total=$((l1_total - q2_len)); fi
    if ((l1_total > width && q1_len > 0)); then l1_q1=''; l1_total=$((l1_total - q1_len)); fi
    if ((l1_total > width && cost_len > 0)); then l1_cost=''; fi

    # Line 2: model + context bar (+ tokens if they fit; shrink bar to 5 cells on very narrow screens)
    l2_head="${lead}${c_dim}${model}${c_off}"
    l2_head_len=$((3 + ${#model}))
    l2_ctx=$ctx_part; l2_ctx_len=$ctx_len
    l2_tok=$tok_part; l2_tok_len=$tok_len
    if ((l2_head_len + l2_ctx_len + l2_tok_len > width && l2_tok_len > 0 && l2_ctx_len > 0)); then
        l2_tok=''; l2_tok_len=0
    fi
    if ((l2_head_len + l2_ctx_len > width)) && [[ $ctx =~ ^[0-9]+$ ]]; then
        build_bar "$ctx" 5
        l2_ctx="${dash}${REPLY}"
    fi
    printf '%s%s%s%s%s\n%s%s%s\n' "$head_part" "$l1_cost" "$l1_q1" "$l1_q2" "$l1_act" "$l2_head" "$l2_ctx" "$l2_tok"
    exit 0
fi

# Single-line layout: drop optional items progressively so the line fits cleanly.
if [ -n "$width" ]; then
    total=$((head_len + model_len + ctx_len + tok_len + cost_len + q1_len + q2_len + act_len))
    if ((total > width && act_len > 0)); then act_part=''; total=$((total - act_len)); fi
    if ((total > width && q2_len > 0)); then q2_part=''; total=$((total - q2_len)); fi
    if ((total > width && q1_len > 0)); then q1_part=''; total=$((total - q1_len)); fi
    if ((total > width && cost_len > 0)); then cost_part=''; total=$((total - cost_len)); fi
    if ((total > width && tok_len > 0 && ctx_len > 0)); then tok_part=''; fi
fi

printf '%s%s%s%s%s%s%s%s\n' "$head_part" "$model_part" "$ctx_part" "$tok_part" "$cost_part" "$q1_part" "$q2_part" "$act_part"
exit 0
