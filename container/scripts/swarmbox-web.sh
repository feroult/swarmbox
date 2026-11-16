#!/bin/bash
# swarmbox-web (installed as /usr/local/bin/swarmbox-web).
#
#   swarmbox-web run       what the ttyd supervisor of `serve` runs: render the page, build ttyd's options, exec ttyd
#   swarmbox-web render    only the first part: box:/tmp/swarmbox/index.html from the page built at image build
#   swarmbox-web restart   make the supervisor start ttyd again (SIGUSR1 to the PID in box:/tmp/swarmbox/web-supervisor.pid),
#                          for example after editing web-terminal.conf; the box and its tmux sessions stay up
#
# The page is built into the image (build-index.sh) with placeholders. Every start replaces them with a plain text
# substitution (sed, no Python, no hash) from <config>/web-terminal.conf:
#   padding      a number from 0 to 99 (pixels around the terminal), default 10
#   ctrlVPaste   true (default) or false
#   ctrlCCopy    true (default) or false
#   strip        auto (default), on or off: the controls strip under the terminal. auto shows it when it has something to show (the key buttons
#                on a touch screen, or when stripKeys is set; an addon control such as the microphone on any screen); off never shows it
#                (an addon then has no place for its controls)
#   stripKeys    the key buttons of the strip: entries `label=keys` separated by commas, keys written as tmux key names separated by spaces
#                (Escape Tab Up C-c M-x F5 ...; "C-a S" is Ctrl+A then S). Default: Esc=Escape, Tab=Tab, ^C=C-c, arrows, Panel=C-a S, Veto=C-a V, Stop=C-a X.
#                An empty value means no buttons.
#   scrollbar    true or false (default false): a thin scrollbar on the right; tmux owns the scrollback, so it is off, and so is the
#                scrollback of the browser (scrollback=0, unless you set one)
# Every other key of that file is a ttyd/xterm.js option (font, theme, size, scrollback ...) and goes to ttyd as `-t key=value`;
# they are not in the page. One `key=value` per line, `#` starts a comment.
#
# ttyd listens on every interface INSIDE the box (the published port is what limits it to the host's 127.0.0.1), port 7681,
# and runs `swarmbox-attach`, so the browser is a window of the shared tmux session like every other entry; without
# swarmbox-attach it attaches to the session main directly.
#
# The voice front. When the `voice` addon is really installed (`swarmbox-addon where voice swarmbox-voice`, which is false for the bare
# shim) and SWARMBOX_VOICE_WEB is not 0 (the setting voice.web), the page gets the two tags of the voice page (/voice/page.css before
# </head>, /voice/page.js before </body>) and `run` execs `swarmbox-voice front` instead of ttyd: the front owns the web port, serves
# /voice/ itself and pipes everything else to ttyd on 127.0.0.1:7680. Otherwise nothing changes: ttyd on the web port, no tags.
#
# Test-only variables (not in the configuration table): SWARMBOX_TEST_LIB (folder with dirs.sh),
# SWARMBOX_TEST_RUN_DIR (replaces /tmp/swarmbox), SWARMBOX_TEST_WEB_PAGE (the built page), SWARMBOX_TEST_WEB_PORT (replaces
# 7681), SWARMBOX_TEST_WEB_IFACE (ttyd -i value, and the address the front listens on), SWARMBOX_TEST_WEB_TTYD_PORT (the port of ttyd
# behind the front, default 7680), SWARMBOX_TEST_VOICE_PORT (the port of the voice service, default 17682).

SB_LIB=${SWARMBOX_TEST_LIB:-/usr/local/lib/swarmbox}
PAGE=${SWARMBOX_TEST_WEB_PAGE:-/usr/local/share/swarmbox/web/index.html}

usage() { echo "usage: swarmbox-web run | render | restart" >&2; exit 64; }
die() { echo "swarmbox-web: $*" >&2; exit "${2:-1}"; }
warn() { echo "swarmbox-web: $*" >&2; }

[ $# -eq 1 ] || usage
case "$1" in run|render|restart) ;; *) usage ;; esac
MODE=$1

# shellcheck source=/dev/null
. "$SB_LIB/dirs.sh" || die "cannot read $SB_LIB/dirs.sh"
SB_RUN_DIR=${SWARMBOX_TEST_RUN_DIR:-$SB_RUN_DIR}

# ---------------------------------------------------------------------------------------------------------------------
if [ "$MODE" = restart ]; then
    pidfile=$SB_RUN_DIR/web-supervisor.pid
    [ -r "$pidfile" ] || die "no web terminal supervisor is running (no $pidfile; is the web terminal off, WEB=0, or is serve not running?)"
    read -r pid < "$pidfile"
    case "$pid" in
        ''|*[!0-9]*) die "$pidfile does not hold a process number" ;;
    esac
    [ "$pid" -gt 1 ] || die "$pidfile holds $pid, which is not a supervisor"
    kill -0 "$pid" 2>/dev/null || die "the web terminal supervisor (process $pid) is not running"
    kill -USR1 "$pid" 2>/dev/null || die "could not signal the web terminal supervisor (process $pid)"
    echo "swarmbox-web: asked the supervisor (process $pid) to restart the web terminal"
    exit 0
fi

# ---------------------------------------------------------------------------------------------------------------------
# The user's settings: defaults, then web-terminal.conf. The theme is the purple glow of the box (docs/theme.md): near-black, violet and gray, with the
# usual hues of the 16 colors kept (red for an error, green for success) in tones of the same family.
declare -A OPT=(
    [fontSize]=21
    [fontWeight]=400
    [fontWeightBold]=700
    [padding]=10
    [strip]=auto
    [stripKeys]="Esc=Escape, Tab=Tab, ^C=C-c, ↑=Up, ↓=Down, ←=Left, →=Right, Panel=C-a S, Veto=C-a V, Stop=C-a X"
    [macOptionIsMeta]=true
    [cursorBlink]=true
    [titleFixed]=SwarmBox
    [fontFamily]="'JetBrainsMono Nerd Font', 'JetBrainsMono NF', 'JetBrainsMono Nerd Font Mono', 'JetBrainsMono NFM', 'CaskaydiaCove Nerd Font', 'Cascadia Code', Consolas, Menlo, 'Liberation Mono', monospace"
    [theme]='{"background":"#0c0b10","foreground":"#d4d4d8","cursor":"#c4b5fd","cursorAccent":"#0c0b10","selectionBackground":"#6d28d9","selectionForeground":"#fafafa","selectionInactiveBackground":"#3f3f46","black":"#1c1a24","red":"#e5484d","green":"#3dba7a","yellow":"#d9a441","blue":"#8b5cf6","magenta":"#d946ef","cyan":"#5eb5c9","white":"#d4d4d8","brightBlack":"#71717a","brightRed":"#ff6b78","brightGreen":"#4ade80","brightYellow":"#fbbf24","brightBlue":"#a78bfa","brightMagenta":"#e879f9","brightCyan":"#8ad7e6","brightWhite":"#fafafa"}'
)
CONF=$SB_CONFIG_DIR/web-terminal.conf

trim() { local v="$1"; v="${v#"${v%%[![:space:]]*}"}"; printf '%s' "${v%"${v##*[![:space:]]}"}"; }

if [ -f "$CONF" ]; then
    while IFS= read -r line || [ -n "$line" ]; do
        # a comment is a whole line starting with '#', or '#' after whitespace ('#rrggbb' in a value is not one)
        line=$(trim "$line")
        [[ "$line" == \#* ]] && continue
        line=$(trim "${line%%[[:space:]]#*}")
        [[ "$line" == *=* ]] || continue
        OPT["$(trim "${line%%=*}")"]=$(trim "${line#*=}")
    done < "$CONF"
fi

CTRL_V=true; CTRL_C=true
[ "${OPT[ctrlVPaste]:-}" = false ] && CTRL_V=false
[ "${OPT[ctrlCCopy]:-}" = false ] && CTRL_C=false
PAD=${OPT[padding]:-10}
if ! [[ "$PAD" =~ ^[0-9]{1,2}$ ]]; then
    warn "padding='$PAD' in $CONF is not a number from 0 to 99; using 10"
    PAD=10
fi
STRIP=${OPT[strip]:-auto}
case "$STRIP" in
    auto|on|off) ;;
    *) warn "strip='$STRIP' in $CONF is not auto, on or off; using auto"; STRIP=auto ;;
esac
# the user listed the key buttons (an empty list included) when the conf has a stripKeys line; the default list is not "listed"
STRIP_CUSTOM=false
[ -f "$CONF" ] && grep -Eq '^[[:space:]]*stripKeys[[:space:]]*=' "$CONF" && STRIP_CUSTOM=true
STRIP_KEYS=${OPT[stripKeys]-}
# for a JS string inside the page (a script element), then for the replacement of sed
STRIP_KEYS=${STRIP_KEYS//$'\t'/ }
STRIP_KEYS=${STRIP_KEYS//\\/\\\\}
STRIP_KEYS=${STRIP_KEYS//\"/\\\"}
STRIP_KEYS=${STRIP_KEYS//</\\u003c}
STRIP_KEYS=${STRIP_KEYS//\\/\\\\}
STRIP_KEYS=${STRIP_KEYS//&/\\&}
STRIP_KEYS=${STRIP_KEYS//\//\\\/}
SCROLLBAR_PX=0
SCROLLBAR_FF=none
if [ "${OPT[scrollbar]:-}" = true ]; then
    SCROLLBAR_PX=6
    SCROLLBAR_FF=thin
fi
# Without a scrollbar the browser keeps no history either (tmux has it): xterm.js reserves 15 px for a scrollbar it measures as zero width
# (and none when scrollback is 0), so a hidden bar with a scrollback would still cost a column. A scrollback set in the conf wins.
if [ "${OPT[scrollbar]:-}" != true ] && [ -z "${OPT[scrollback]+x}" ]; then OPT[scrollback]=0; fi
unset 'OPT[ctrlVPaste]' 'OPT[ctrlCCopy]' 'OPT[padding]' 'OPT[scrollbar]' 'OPT[strip]' 'OPT[stripKeys]'

# voice_front_bin: prints the real swarmbox-voice when the front is to be used, else nothing. One place for the rule: the setting is on and
# the addon is installed (swarmbox-addon decides, with the same logic as everywhere else) and carries the front and the page parts.
voice_front_bin() {
    [ "${SWARMBOX_VOICE_WEB:-1}" = 0 ] && return 0
    local real prefix
    real=$(swarmbox-addon where voice swarmbox-voice 2>/dev/null) || return 0
    prefix=${real%/bin/swarmbox-voice}
    [ "$prefix" != "$real" ] || return 0
    [ -f "$prefix/lib/swarmbox_voice/front.py" ] && [ -f "$prefix/web/page.js" ] && [ -f "$prefix/web/page.css" ] || return 0
    printf '%s' "$real"
}
VOICE_BIN=$(voice_front_bin)

# render: the substitution of the placeholders. The values are validated above, so sed needs no escaping.
render() {
    [ -r "$PAGE" ] || die "the built page $PAGE is missing (build-index.sh runs at image build; is this the right image?)"
    local ph
    for ph in __SWARMBOX_PADDING__ __SWARMBOX_CTRL_V__ __SWARMBOX_CTRL_C__ __SWARMBOX_SCROLLBAR__ __SWARMBOX_SCROLLBAR_FF__ __SWARMBOX_STRIP__ __SWARMBOX_STRIP_CUSTOM__ __SWARMBOX_STRIP_KEYS__; do
        grep -q "$ph" "$PAGE" || die "the built page $PAGE has no $ph placeholder (a stale page? rebuild the image)"
    done
    mkdir -p "$SB_RUN_DIR" || die "cannot create $SB_RUN_DIR"
    local tmp
    local -a voice_tags=()
    if [ -n "$VOICE_BIN" ]; then
        voice_tags=(-e 's#</head>#<link rel="stylesheet" href="/voice/page.css"></head>#' -e 's#</body>#<script src="/voice/page.js" defer></script></body>#')
    fi
    tmp=$(mktemp "$SB_RUN_DIR/index.html.XXXXXX") || die "cannot write in $SB_RUN_DIR"
    if ! sed -e "s/__SWARMBOX_PADDING__/$PAD/g" -e "s/__SWARMBOX_CTRL_V__/$CTRL_V/g" -e "s/__SWARMBOX_CTRL_C__/$CTRL_C/g" -e "s/__SWARMBOX_SCROLLBAR__/$SCROLLBAR_PX/g" -e "s/__SWARMBOX_SCROLLBAR_FF__/$SCROLLBAR_FF/g" -e "s/__SWARMBOX_STRIP__/$STRIP/g" -e "s/__SWARMBOX_STRIP_CUSTOM__/$STRIP_CUSTOM/g" -e "s/__SWARMBOX_STRIP_KEYS__/$STRIP_KEYS/g" "${voice_tags[@]}" "$PAGE" > "$tmp" \
        || ! chmod 644 "$tmp" || ! mv -f "$tmp" "$SB_RUN_DIR/index.html"; then
        rm -f "$tmp"
        die "cannot write $SB_RUN_DIR/index.html"
    fi
}
render
[ "$MODE" = render ] && exit 0

# ---------------------------------------------------------------------------------------------------------------------
# run: the options and ttyd. The shells inside tmux inherit this environment; without a UTF-8 locale bash/readline drops an
# accented character typed on its own (dead key + letter), so make sure there is one (the image sets LANG=C.UTF-8).
case "${LC_ALL:-${LC_CTYPE:-${LANG:-}}}" in
    *[Uu][Tt][Ff]-8*|*[Uu][Tt][Ff]8*) ;;
    *)
        export LANG=C.UTF-8
        [ -n "${LC_ALL:-}" ] && export LC_ALL=C.UTF-8
        ;;
esac

# ttyd reads each value as JSON and silently stops at the first thing it can parse, so a font list like  'A', 'B', monospace
# would be cut to  A  (losing the fallbacks). Hand over real JSON: numbers, true/false/null, objects/arrays and quoted strings
# pass through; anything else becomes a string.
json_value() {
    local v="$1"
    if [[ "$v" =~ ^-?[0-9]+(\.[0-9]+)?$ || "$v" == true || "$v" == false || "$v" == null \
          || "$v" == \{*\} || "$v" == \[*\] || ( "$v" == \"*\" && ${#v} -ge 2 ) ]]; then
        printf '%s' "$v"
    else
        v="${v//\\/\\\\}"
        v="${v//\"/\\\"}"
        printf '"%s"' "$v"
    fi
}

TTYD_ARGS=(-p "${SWARMBOX_TEST_WEB_PORT:-7681}")
[ -n "${SWARMBOX_TEST_WEB_IFACE:-}" ] && TTYD_ARGS+=(-i "$SWARMBOX_TEST_WEB_IFACE")
# -W writable (ttyd is read-only by default); -O refuse websockets whose Origin differs from the Host, so a random web page
# cannot drive the terminal through localhost. It does not stop another origin from FRAMING the page (the socket of a framed page has the same origin as
# the Host): the controls strip is never built in a frame, and the voice front adds frame-ancestors when it is on. Authentication is not done here:
# Cloudflare Access sits in front.
TTYD_ARGS+=(-W -O --index "$SB_RUN_DIR/index.html")
for key in "${!OPT[@]}"; do
    TTYD_ARGS+=(-t "$key=$(json_value "${OPT[$key]}")")
done
if command -v swarmbox-attach > /dev/null 2>&1; then
    TTYD_ARGS+=(swarmbox-attach --web)
else
    TTYD_ARGS+=(tmux attach -t main)
fi
command -v ttyd > /dev/null 2>&1 || die "ttyd not found on PATH" 127
if [ -n "$VOICE_BIN" ]; then
    FRONT_ARGS=(front --listen "${SWARMBOX_TEST_WEB_IFACE:-0.0.0.0}:${SWARMBOX_TEST_WEB_PORT:-7681}" --ttyd-port "${SWARMBOX_TEST_WEB_TTYD_PORT:-7680}")
    [ -n "${SWARMBOX_TEST_VOICE_PORT:-}" ] && FRONT_ARGS+=(--service-listen "127.0.0.1:$SWARMBOX_TEST_VOICE_PORT")
    exec "$VOICE_BIN" "${FRONT_ARGS[@]}" -- ttyd "${TTYD_ARGS[@]}"
fi
exec ttyd "${TTYD_ARGS[@]}"
