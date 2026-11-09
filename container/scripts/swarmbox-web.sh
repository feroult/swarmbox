#!/bin/bash
# swarmbox-web (installed as /usr/local/bin/swarmbox-web).
#
#   swarmbox-web run       what the ttyd supervisor of `serve` runs: render the page, build ttyd's options, exec ttyd
#   swarmbox-web render    only the first part: box:/tmp/swarmbox/index.html from the page built at image build
#   swarmbox-web restart   make the supervisor start ttyd again (SIGUSR1 to the PID in box:/tmp/swarmbox/web-supervisor.pid),
#                          for example after editing web-terminal.conf; the box and its tmux sessions stay up
#
# The page is built into the image (build-index.sh) with three placeholders. Every start replaces them with a plain text
# substitution (sed, no Python, no hash) from <config>/web-terminal.conf:
#   padding      a number from 0 to 99 (pixels around the terminal), default 10
#   ctrlVPaste   true (default) or false
#   ctrlCCopy    true (default) or false
# Every other key of that file is a ttyd/xterm.js option (font, theme, size, scrollback ...) and goes to ttyd as `-t key=value`;
# they are not in the page. One `key=value` per line, `#` starts a comment.
#
# ttyd listens on every interface INSIDE the box (the published port is what limits it to the host's 127.0.0.1), port 7681,
# and runs `swarmbox-attach`, so the browser is a window of the shared tmux session like every other entry; without
# swarmbox-attach it attaches to the session main directly.
#
# Test-only variables (not in the configuration table): SWARMBOX_TEST_LIB (folder with dirs.sh),
# SWARMBOX_TEST_RUN_DIR (replaces /tmp/swarmbox), SWARMBOX_TEST_WEB_PAGE (the built page), SWARMBOX_TEST_WEB_PORT (replaces
# 7681), SWARMBOX_TEST_WEB_IFACE (ttyd -i value).

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
# The user's settings: defaults, then web-terminal.conf. The theme is Windows Terminal's Campbell scheme.
declare -A OPT=(
    [fontSize]=21
    [fontWeight]=400
    [fontWeightBold]=700
    [padding]=10
    [cursorBlink]=true
    [titleFixed]=SwarmBox
    [fontFamily]="'JetBrainsMono Nerd Font', 'JetBrainsMono NF', 'JetBrainsMono Nerd Font Mono', 'JetBrainsMono NFM', 'CaskaydiaCove Nerd Font', 'Cascadia Code', Consolas, Menlo, 'Liberation Mono', monospace"
    [theme]='{"background":"#0c0c0c","foreground":"#c2c2c2","cursor":"#ffffff","selectionBackground":"#264f78","black":"#0c0c0c","red":"#e74856","green":"#16c60c","yellow":"#f9f1a5","blue":"#3b78ff","magenta":"#b4009e","cyan":"#61d6d6","white":"#cccccc","brightBlack":"#767676","brightRed":"#ff6b78","brightGreen":"#3ee05f","brightYellow":"#f9f1a5","brightBlue":"#6ea0ff","brightMagenta":"#e04fc4","brightCyan":"#8ee6e6","brightWhite":"#f2f2f2"}'
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
unset 'OPT[ctrlVPaste]' 'OPT[ctrlCCopy]' 'OPT[padding]'

# render: the three-value substitution. The values are validated above, so sed needs no escaping.
render() {
    [ -r "$PAGE" ] || die "the built page $PAGE is missing (build-index.sh runs at image build; is this the right image?)"
    local ph
    for ph in __SWARMBOX_PADDING__ __SWARMBOX_CTRL_V__ __SWARMBOX_CTRL_C__; do
        grep -q "$ph" "$PAGE" || die "the built page $PAGE has no $ph placeholder (a stale page? rebuild the image)"
    done
    mkdir -p "$SB_RUN_DIR" || die "cannot create $SB_RUN_DIR"
    local tmp
    tmp=$(mktemp "$SB_RUN_DIR/index.html.XXXXXX") || die "cannot write in $SB_RUN_DIR"
    if ! sed -e "s/__SWARMBOX_PADDING__/$PAD/g" -e "s/__SWARMBOX_CTRL_V__/$CTRL_V/g" -e "s/__SWARMBOX_CTRL_C__/$CTRL_C/g" "$PAGE" > "$tmp" \
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
# cannot drive the terminal through localhost. Authentication is not done here: Cloudflare Access sits in front.
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
exec ttyd "${TTYD_ARGS[@]}"
