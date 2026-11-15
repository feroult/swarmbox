#!/usr/bin/env bash
# enter.sh: type a prompt into the Claude Code TUI of a tmux pane and make it submit.
# Proof of concept of the "plain driver" of the bus (see docs/spikes/enter.md).
#
#   enter.sh [-L socket] -t <target> [--pause-ms 150] [--queue] [--allow-slash] [--no-enter] [--timeout 5] -- "text"
#
# Exit codes: 0 submitted | 2 usage | 3 a dialog is open (nothing typed) | 4 busy (nothing typed; use --queue)
#             5 typed but not submitted | 6 text starts with / or ! (a command, not a prompt; use --allow-slash)
# The method: the text is ONE `send-keys -l` (a newline in it is a newline in the input box, it does not submit),
# then a pause, then Enter as a separate tmux command, then a check that the prompt left the input box.
set -u
SOCK=() ; TARGET= ; PAUSE=150 ; QUEUE=0 ; SLASH=0 ; ENTER=1 ; TMO=5
while [ $# -gt 0 ]; do
  case $1 in
    -L) SOCK=(-L "$2"); shift 2 ;;
    -t) TARGET=$2; shift 2 ;;
    --pause-ms) PAUSE=$2; shift 2 ;;
    --queue) QUEUE=1; shift ;;
    --allow-slash) SLASH=1; shift ;;
    --no-enter) ENTER=0; shift ;;
    --timeout) TMO=$2; shift 2 ;;
    --) shift; break ;;
    *) break ;;
  esac
done
TEXT=${1-}
[ -n "$TARGET" ] && [ -n "$TEXT" ] || { echo "usage: enter.sh [-L socket] -t target [opts] -- text" >&2; exit 2; }
tm() { tmux "${SOCK[@]}" "$@"; }

screen() { tm capture-pane -p -t "$TARGET"; }
# the input box is the text between the last two horizontal rules of the screen
box() { screen | awk '{l[NR]=$0} /^──────/{r[++n]=NR} END{for(i=r[n-1]+1;i<r[n];i++){s=l[i]; sub(/^❯ ?/,"",s); sub(/^  /,"",s); print s}}'; }
state() {
  local s; s=$(screen)
  if grep -q -E 'Enter to confirm|Esc to cancel|Esc to exit|Do you want to' <<<"$s"; then echo dialog
  elif grep -q 'esc to interrupt' <<<"$s"; then echo busy
  elif grep -q '^❯' <<<"$s"; then echo idle
  else echo unknown; fi
}

st=$(state)
[ "$st" = dialog ] && { echo "dialog open, not typing" >&2; exit 3; }
[ "$st" = busy ] && [ $QUEUE = 0 ] && { echo "busy, not typing (use --queue to queue the message)" >&2; exit 4; }
case $TEXT in
  /*|'!'*) [ $SLASH = 1 ] || { echo "text starts with / or !: it would run a command" >&2; exit 6; } ;;
esac

tm send-keys -t "$TARGET" -l -- "$TEXT"
[ $ENTER = 1 ] || exit 0
sleep "$(awk "BEGIN{print $PAUSE/1000}")"

tail=${TEXT##*$'\n'}; tail=${tail: -12}          # the last characters of the last line
left() { box | grep -qF -- "$tail"; }             # is our text still in the input box?
submitted() { [ "$(state)" != idle ] || ! left; }

for attempt in 1 2; do
  tm send-keys -t "$TARGET" Enter
  end=$(( $(date +%s) + TMO ))
  while [ "$(date +%s)" -le $end ]; do
    sleep 0.1
    submitted && exit 0
  done
  left || exit 0        # retry Enter only if our text is really still there
done
echo "typed, but the prompt did not leave the input box" >&2
exit 5
