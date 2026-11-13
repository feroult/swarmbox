#!/bin/bash
# The entry banner: half-block lettering with a segmented bar under it, in the style of a 90s BBS login screen.
# The letters glow: dark gray and purple lighting up to white in the middle of the word, a smooth gradient across
# all of it, and, in a tmux pane, a glint keeps sweeping back and forth across them in the background.
# 256 colours, 49 columns.

LC_ALL=C.UTF-8   # the art is UTF-8 and is measured in characters, not bytes
ESC=$'\033'
R="${ESC}[0m"
F="${ESC}[38;5;"   # F, then a colour number and an m

FONT=(
'▄▀▀▀▀ █   █ ▄▀▀▀▄ █▀▀▀▄ █▄ ▄█ █▀▀▀▄ ▄▀▀▀▄ ▀▄ ▄▀'
' ▀▀▀▄ █▄▀▄█ █▀▀▀█ █▀▀█  █ ▀ █ █▀▀▀▄ █   █  ▄▀▄ '
'▀▀▀▀  ▀   ▀ ▀   ▀ ▀   ▀ ▀   ▀ ▀▀▀▀   ▀▀▀  ▀   ▀'
)
W=${#FONT[0]}   # the width of the lettering

# nearest256 R G B -> REPLY: the 256-colour number closest to the colour (0-255 each), from the 6x6x6 cube or
# the gray ramp, whichever is nearer
nearest256() {
    local -a lv=(0 95 135 175 215 255)
    local -a c=("$1" "$2" "$3") q=(0 0 0)
    local i k best d dr dg db gl gd
    for i in 0 1 2; do
        best=999
        for k in 0 1 2 3 4 5; do d=$((c[i] - lv[k])); ((d < 0)) && d=$((-d)); if ((d < best)); then best=$d; q[i]=$k; fi; done
    done
    dr=$((c[0] - lv[q[0]])); dg=$((c[1] - lv[q[1]])); db=$((c[2] - lv[q[2]]))
    d=$((dr * dr + dg * dg + db * db))
    gl=$(((c[0] + c[1] + c[2]) / 3 - 8)); gl=$(((gl + 5) / 10)); ((gl < 0)) && gl=0; ((gl > 23)) && gl=23
    dr=$((c[0] - 8 - gl * 10)); dg=$((c[1] - 8 - gl * 10)); db=$((c[2] - 8 - gl * 10))
    gd=$((dr * dr + dg * dg + db * db))
    if ((gd < d)); then REPLY=$((232 + gl)); else REPLY=$((16 + 36 * q[0] + 6 * q[1] + q[2])); fi
}

# gradient WIDTH HEX...: COLS[0..WIDTH-1], one colour per column, running smoothly through the HEX keypoints
# (rrggbb), so the colour changes inside a letter too: the gradient belongs to the word, not to the letters
gradient() {
    local n=$1; shift
    local -a k=("$@") rgb
    local segs=$((${#k[@]} - 1)) j pos s f a b i ca cb
    COLS=()
    for ((j = 0; j < n; j++)); do
        pos=$((j * segs * 1000 / (n - 1))); s=$((pos / 1000)); ((s >= segs)) && s=$((segs - 1)); f=$((pos - s * 1000))
        a=${k[s]}; b=${k[s + 1]}
        for i in 0 2 4; do
            ca=$((16#${a:i:2})); cb=$((16#${b:i:2})); rgb[i / 2]=$((ca + (cb - ca) * f / 1000))
        done
        nearest256 "${rgb[0]}" "${rgb[1]}" "${rgb[2]}"; COLS[j]=$REPLY
    done
}

# dark gray and purple that light up to white in the middle of the word and fade out again: a smooth gradient
gradient ${#FONT[0]} 3f3f46 6d28d9 a78bfa ffffff a78bfa 6d28d9 3f3f46

# lighten COLOUR K -> REPLY: the 256-colour number moved K quarters of the way to white, in the same hue
lighten() {
    local base=$1 step=$2 r g b
    if ((base >= 232)); then REPLY=$((base + (255 - base) * step / 4)); return; fi
    base=$((base - 16)); r=$((base / 36)); g=$((base / 6 % 6)); b=$((base % 6))
    r=$((r + (5 - r) * step / 4)); g=$((g + (5 - g) * step / 4)); b=$((b + (5 - b) * step / 4))
    REPLY=$((16 + 36 * r + 6 * g + b))
}

# paint TEXT [GLINT] -> REPLY: the text coloured by the gradient. Around column GLINT the letters are white at
# the centre and fade back to their own colour over three more columns (a soft halo, which is the glint)
paint() {
    local t=$1 g=${2:--99} n=${#1} j ch col cur='' out='' d
    for ((j = 0; j < n; j++)); do
        ch=${t:j:1}
        if [ "$ch" = ' ' ]; then out+=$ch; continue; fi
        col=${COLS[j]}
        d=$((j - g)); ((d < 0)) && d=$((-d))
        if ((d == 0)); then col=231; elif ((d < 4)); then lighten "$col" $((4 - d)); col=$REPLY; fi
        if [ "$col" != "$cur" ]; then out+="${F}${col}m"; cur=$col; fi
        out+=$ch
    done
    REPLY="$out$R"
}

# put COLOURED VISIBLE-LENGTH: one line, one column from the left edge (the length is only there for the glint, which
# draws the same lines as the banner)
put() { printf ' %s\n' "$1"; }

# bar: segments of a heavy line, each coloured by the gradient at its own columns, so it lights up like the letters
bar() {
    local col=0 out='' j n
    for n in 14 8 4 2; do
        for ((j = 0; j < n; j++)); do out+="${F}${COLS[col + j]}m━"; done
        out+="$R "
        col=$((col + n + 1))
    done
    put "$out" "$W"
}

echo
for row in "${FONT[@]}"; do paint "$row"; put "$REPLY" "${#row}"; done
put '' 0
bar
printf ' %*s%s// agent box%s\n' $((W - 12)) '' "${F}240m" "$R"
# no blank line after the signature: the prompt brings its own above it (add_newline in starship.toml)

# the glint: a white diagonal with a soft halo that crosses the letters, back and forth, in the background so the
# shell never waits for it. It writes into the pane while the shell may be writing too, so it is careful: it only
# starts a pass when the screen has been still for a moment, it addresses the three rows of lettering by their row on
# the screen (not relative to the cursor), and just before each write it asks tmux again whether anything moved (new
# output, a scroll). If so it skips the frame, ends the pass, and puts the letters back to plain. It never draws
# when it cannot find the lettering on the screen. Needs tmux, which is always there in the box; elsewhere, no glint.
GLINT_EVERY=3   # seconds of rest between two passes, plus 0 to 2 more, so it is never a metronome
GLINT_FRAMES=44 # steps in one pass; with the pause below, a pass takes about two seconds
GLINT_STEP=0.03 # seconds between two steps
TMUX_STATE='#{history_size} #{cursor_y}'   # changes whenever the screen scrolls or the cursor changes line

# draw GLINT: redraw the three rows of lettering with the glint at column GLINT (-99: none, plain). 0 drawn;
# 1 the lettering is not on the screen, or the pane is gone; 2 the screen moved while we looked, nothing drawn.
draw() {
    local g=$1 lines y s1 s2 frame i
    # one tmux call: the visible rows, then the state as the last line
    mapfile -t lines < <(tmux capture-pane -p -t "$TMUX_PANE" \; display-message -p -t "$TMUX_PANE" "$TMUX_STATE" 2> /dev/null)
    ((${#lines[@]} > 1)) || return 1
    s1=${lines[-1]}
    for ((y = ${#lines[@]} - 2; y >= 0; y--)); do [[ ${lines[y]} == *"${FONT[0]}"* ]] && break; done
    ((y >= 0)) || return 1
    frame="${ESC}7"
    for i in 0 1 2; do
        paint "${FONT[$i]}" $((g - i * 2))
        frame+="${ESC}[$((y + 1 + i));1H$(put "$REPLY" "${#FONT[$i]}")"
    done
    s2=$(tmux display-message -p -t "$TMUX_PANE" "$TMUX_STATE" 2> /dev/null) || return 1
    [ "$s2" = "$s1" ] || return 2
    printf '%s' "$frame${ESC}8"
}

# sweep DIRECTION: one pass, 1 left to right and -1 right to left. It eases in and out (smoothstep), so it starts
# slowly, is fastest in the middle and settles at the end. Fails (1) when the lettering is gone.
sweep() {
    local dir=$1 lo=-6 hi=$((${#FONT[0]} + 6)) frames=$GLINT_FRAMES k t e g rc
    for ((k = 0; k <= frames; k++)); do
        t=$((k * 1000 / frames)); e=$((t * t * (3000 - 2 * t) / 1000000))
        ((dir < 0)) && e=$((1000 - e))
        g=$((lo + (hi - lo) * e / 1000))
        draw "$g"; rc=$?
        ((rc == 1)) && return 1
        if ((rc == 2)); then sleep 0.3; draw -99; return 0; fi   # something moved: plain letters again, end the pass
        sleep "$GLINT_STEP"
    done
}

# glint: the loop, alternating the direction. It ends when the lettering is gone (scrolled away, cleared), when the
# pane is gone, or when a newer banner in the same pane takes over (the pane option holds the pid of the one that
# owns it). It skips a pass while a full-screen program or copy mode is up, or while the screen is not still.
glint() {
    local me=$BASHPID q1 q2 dir=1
    tmux set-option -p -t "$TMUX_PANE" @swarmbox_glint "$me" 2> /dev/null || return
    sleep 0.1   # let the rest of the login output settle
    while :; do
        [ "$(tmux show-options -pqv -t "$TMUX_PANE" @swarmbox_glint 2> /dev/null)" = "$me" ] || return
        q1=$(tmux display-message -p -t "$TMUX_PANE" "#{alternate_on} #{pane_in_mode} $TMUX_STATE" 2> /dev/null) || return
        sleep 0.25
        q2=$(tmux display-message -p -t "$TMUX_PANE" "#{alternate_on} #{pane_in_mode} $TMUX_STATE" 2> /dev/null) || return
        if [ "$q1" = "$q2" ] && [[ $q1 == '0 0 '* ]]; then sweep "$dir" || return; dir=$((-dir)); fi
        sleep $((GLINT_EVERY + RANDOM % 3))
    done
}
if [ -t 1 ] && [ -n "${TMUX:-}" ] && [ -n "${TMUX_PANE:-}" ] && command -v tmux > /dev/null; then
    glint < /dev/null 2> /dev/null &
    disown
fi
