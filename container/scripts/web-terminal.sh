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
    [fontSize]=14
    [cursorBlink]=true
    [titleFixed]=SwarmBox
    [fontFamily]="'JetBrainsMono Nerd Font', 'JetBrains Mono', Consolas, Menlo, 'Liberation Mono', monospace"
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
unset 'OPT[ctrlVPaste]' 'OPT[ctrlCCopy]'

# Clipboard bridge. ttyd 1.7.7 ignores OSC 52 (what tmux uses to copy to the clipboard) and xterm.js sends
# Ctrl+V to the shell as ^V, so the page is served with a small script injected: copies made in tmux reach
# the browser clipboard and Ctrl+V pastes. The image keeps ttyd's own page (ttyd-stock.html); the page used
# here is rebuilt only when that page, the script or these options change. Without the files (or python3)
# ttyd simply serves its own page.
STOCK="${SWARMBOX_TTYD_STOCK:-/usr/local/share/swarmbox/ttyd-stock.html}"
BRIDGE="${SWARMBOX_TTYD_BRIDGE:-/usr/local/share/swarmbox/ttyd-clipboard.js}"
INDEX="$SWARMBOX_DIR/ttyd-index.html"
INDEX_ARGS=()
if [ -r "$STOCK" ] && [ -r "$BRIDGE" ] && command -v python3 >/dev/null 2>&1; then
    stamp="$(sha256sum "$STOCK" "$BRIDGE" | awk '{print $1}' | tr '\n' ' ')$CTRL_V $CTRL_C"
    if [ ! -s "$INDEX" ] || [ "$(cat "$INDEX.stamp" 2>/dev/null)" != "$stamp" ]; then
        if python3 - "$STOCK" "$BRIDGE" "$INDEX.tmp" "$CTRL_V" "$CTRL_C" <<'PY'
import json, sys
stock_path, bridge_path, out_path, ctrl_v, ctrl_c = sys.argv[1:6]
with open(stock_path) as f:
    page = f.read()
with open(bridge_path) as f:
    bridge = f.read().replace("</script", "<\\/script")
if page.count("</body>") != 1:
    sys.exit(1)
cfg = json.dumps({"ctrlVPaste": ctrl_v == "true", "ctrlCCopy": ctrl_c == "true"})
snippet = "<script>window.__swarmboxClipboard=%s;</script><script>%s</script></body>" % (cfg, bridge)
with open(out_path, "w") as f:
    f.write(page.replace("</body>", snippet, 1))
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
