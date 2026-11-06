#!/bin/bash
# Starts the web terminal (ttyd -> tmux) when the container was created with --web
# (SWARMBOX_WEB is set). Idempotent and safe to call concurrently (init.sh and
# start.sh both call it).
#
# ttyd listens on all interfaces *inside* the container, which is what lets the
# outer port forwarder reach it. start.sh publishes it on the host's 127.0.0.1 only.
#   -W  writable (ttyd is read-only by default)
#   -O  refuse websockets whose Origin differs from the Host: keeps a random web page
#       from driving the terminal through localhost
# Authentication is NOT done here: put it in front (Cloudflare Access).

[ -n "$SWARMBOX_WEB" ] || exit 0

SWARMBOX_DIR="$HOME/.swarmbox"
mkdir -p "$SWARMBOX_DIR"

# Serialize concurrent callers
exec 9>"$SWARMBOX_DIR/web-terminal.lock"
flock 9

PORT="${SWARMBOX_WEB_PORT:-7681}"   # container-side port; start.sh publishes 7681 (overridable for tests)
if pgrep -u "$(id -u)" -f "^(/usr/local/bin/)?ttyd -p $PORT " >/dev/null 2>&1; then
    exit 0
fi

# The shells inside tmux inherit this environment. Without a UTF-8 locale bash/readline drops an
# accented character typed on its own (dead key + letter), so make sure there is one.
case "${LC_ALL:-${LC_CTYPE:-${LANG:-}}}" in
    *[Uu][Tt][Ff]-8*|*[Uu][Tt][Ff]8*) ;;
    *)
        export LANG=C.UTF-8
        [ -n "${LC_ALL:-}" ] && export LC_ALL=C.UTF-8
        ;;
esac

# Client options (xterm.js): defaults, overridden by ~/.swarmbox/web-terminal.conf. That file lives in
# your workspace, so editing it needs no rebuild: one `key=value` per line, `#` for comments, e.g.
#   fontFamily='JetBrainsMono Nerd Font', Consolas, monospace
#   fontSize=15
# Restart the terminal to apply (tmux sessions survive): pkill ttyd; swarmbox-web-terminal
# The font is the *browser's*: it must be installed on the machine that opens the page.
declare -A OPT=(
    [fontSize]=21
    [fontWeight]=400
    [fontWeightBold]=700
    [padding]=5
    [cursorBlink]=true
    [titleFixed]=SwarmBox
    [fontFamily]="'JetBrainsMono Nerd Font', 'JetBrainsMono NF', 'JetBrainsMono Nerd Font Mono', 'JetBrainsMono NFM', 'CaskaydiaCove Nerd Font', 'Cascadia Code', Consolas, Menlo, 'Liberation Mono', monospace"
    # Dark like Windows Terminal's Campbell scheme (ttyd's own default is a lighter #2b2b2b)
    [theme]='{"background":"#0c0c0c","foreground":"#c2c2c2","cursor":"#ffffff","selectionBackground":"#264f78","black":"#0c0c0c","red":"#e74856","green":"#16c60c","yellow":"#f9f1a5","blue":"#3b78ff","magenta":"#b4009e","cyan":"#61d6d6","white":"#cccccc","brightBlack":"#767676","brightRed":"#ff6b78","brightGreen":"#3ee05f","brightYellow":"#f9f1a5","brightBlue":"#6ea0ff","brightMagenta":"#e04fc4","brightCyan":"#8ee6e6","brightWhite":"#f2f2f2"}'
)
CONF="$SWARMBOX_DIR/web-terminal.conf"
if [ -f "$CONF" ]; then
    trim() { local v="$1"; v="${v#"${v%%[![:space:]]*}"}"; printf '%s' "${v%"${v##*[![:space:]]}"}"; }
    while IFS= read -r line || [ -n "$line" ]; do
        # a comment is a whole line starting with '#', or '#' after whitespace ('#rrggbb' in a value is not one)
        line="$(trim "$line")"
        [[ "$line" == \#* ]] && continue
        line="$(trim "${line%%[[:space:]]#*}")"
        [[ "$line" == *=* ]] || continue
        OPT["$(trim "${line%%=*}")"]="$(trim "${line#*=}")"
    done < "$CONF"
fi
# Options for the clipboard bridge (container/ttyd-clipboard.js) are consumed here, not passed to ttyd.
CTRL_V=true; CTRL_C=true
[ "${OPT[ctrlVPaste]:-}" = "false" ] && CTRL_V=false
[ "${OPT[ctrlCCopy]:-}" = "false" ] && CTRL_C=false
# Space (px) around the terminal: consumed here too, it is CSS (container/ttyd-style.css), not a ttyd option.
PAD="${OPT[padding]:-5}"
[[ "$PAD" =~ ^[0-9]{1,2}$ ]] || PAD=5
unset 'OPT[ctrlVPaste]' 'OPT[ctrlCCopy]' 'OPT[padding]'

# Clipboard bridge. ttyd 1.7.7 ignores OSC 52 (what tmux uses to copy to the clipboard) and xterm.js sends
# Ctrl+V to the shell as ^V, so the page is served with a small script injected: copies made in tmux reach
# the browser clipboard and Ctrl+V pastes. The image keeps ttyd's own page (ttyd-stock.html); the page used
# here is rebuilt only when that page, the script or these options change. Without the files (or python3)
# ttyd simply serves its own page.
STOCK="${SWARMBOX_TTYD_STOCK:-/usr/local/share/swarmbox/ttyd-stock.html}"
BRIDGE="${SWARMBOX_TTYD_BRIDGE:-/usr/local/share/swarmbox/ttyd-clipboard.js}"
STYLE="${SWARMBOX_TTYD_STYLE:-/usr/local/share/swarmbox/ttyd-style.css}"
INDEX="$SWARMBOX_DIR/ttyd-index.html"
INDEX_ARGS=()
if [ -r "$STOCK" ] && [ -r "$BRIDGE" ] && command -v python3 >/dev/null 2>&1; then
    [ -r "$STYLE" ] || STYLE=/dev/null
    stamp="$(sha256sum "$STOCK" "$BRIDGE" "$STYLE" | awk '{print $1}' | tr '\n' ' ')$CTRL_V $CTRL_C $PAD"
    if [ ! -s "$INDEX" ] || [ "$(cat "$INDEX.stamp" 2>/dev/null)" != "$stamp" ]; then
        if python3 - "$STOCK" "$BRIDGE" "$INDEX.tmp" "$CTRL_V" "$CTRL_C" "$STYLE" "$PAD" <<'PY'
import json, sys
stock_path, bridge_path, out_path, ctrl_v, ctrl_c, style_path, pad = sys.argv[1:8]
with open(stock_path) as f:
    page = f.read()
with open(bridge_path) as f:
    bridge = f.read().replace("</script", "<\\/script")
if page.count("</body>") != 1:
    sys.exit(1)
cfg = json.dumps({"ctrlVPaste": ctrl_v == "true", "ctrlCCopy": ctrl_c == "true"})
snippet = "<script>window.__swarmboxClipboard=%s;</script><script>%s</script></body>" % (cfg, bridge)
page = page.replace("</body>", snippet, 1)
# the style goes in <head>, so it is there before the terminal is built (and measured)
with open(style_path) as f:
    css = f.read().replace("</style", "<\\/style")
if css.strip() and page.count("</head>") == 1:
    page = page.replace("</head>", "<style>:root{--swarmbox-padding:%spx}\n%s</style></head>" % (pad, css), 1)
with open(out_path, "w") as f:
    f.write(page)
PY
        then
            mv "$INDEX.tmp" "$INDEX" && printf '%s' "$stamp" > "$INDEX.stamp"
        else
            rm -f "$INDEX.tmp"
        fi
    fi
    [ -s "$INDEX" ] && INDEX_ARGS=(--index "$INDEX")
fi

# ttyd reads each value as JSON and silently stops at the first thing it can parse, so a font list
# like  'A', 'B', monospace  would be cut to  A  (losing the fallbacks). Hand over real JSON:
# numbers, true/false/null, objects/arrays and quoted strings pass through; anything else becomes a string.
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
TTYD_OPTS=()
for key in "${!OPT[@]}"; do
    TTYD_OPTS+=(-t "$key=$(json_value "${OPT[$key]}")")
done

# 9>&- keeps ttyd from inheriting (and holding) the lock
nohup setsid ttyd -p "$PORT" -W -O "${INDEX_ARGS[@]}" "${TTYD_OPTS[@]}" \
    tmux new -A -s main \
    >"$SWARMBOX_DIR/web-terminal.log" 2>&1 </dev/null 9>&- &
exit 0
