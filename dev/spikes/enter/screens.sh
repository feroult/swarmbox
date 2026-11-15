# Capture the real screens into /out (copied to screens/ by hand). bash /spike/screens.sh
. /spike/lib.sh
PROJ=/work/proj; mkdir -p $PROJ; cd $PROJ; git init -q .
save() { cap > /out/screen-$1.txt; }
newsess() { TM kill-server 2>/dev/null; sleep 0.3; TM new-session -d -s $SESS -x 120 -y 40 -c $PROJ bash; sleep 0.7; }
send() { TM send-keys -t $SESS -l "$1"; sleep 0.15; TM send-keys -t $SESS Enter; }
# waitfor PATTERN: wait for it on screen, approving the managed-settings dialog on the way unless it is what we look for
waitfor() { for i in $(seq 1 120); do sleep 0.5; local s; s=$(cap); grep -q -E "$1" <<<"$s" && return 0
  grep -q 'Managed settings require' <<<"$s" && TM send-keys -t $SESS Enter; done; return 1; }
# 1. managed settings dialog (fresh HOME, only onboarding+theme+trust seeded)
seed_home $PROJ; newsess; send claude; waitfor 'Managed settings' && save dialog-managed-settings
TM send-keys -t $SESS Enter; waitfor 'auto mode on|manual mode on' && sleep 2 && save idle-first-start
# 2. folder trust dialog
rm -rf /work/other; mkdir -p /work/other; echo '{"hasCompletedOnboarding":true,"theme":"dark"}' > $HOME/.claude.json
newsess; TM send-keys -t $SESS -l 'cd /work/other && claude'; TM send-keys -t $SESS Enter; waitfor 'trust this folder' && save dialog-folder-trust
TM send-keys -t $SESS Down; TM send-keys -t $SESS Enter; waitfor 'auto mode on|manual mode on'; sleep 1
# 3. bypass dialog
newsess; seed_home $PROJ; send 'claude --dangerously-skip-permissions'; waitfor 'Bypass Permissions mode' && save dialog-bypass
TM send-keys -t $SESS Down; sleep 0.3; TM send-keys -t $SESS Enter; waitfor 'bypass permissions on' && sleep 1 && save idle-bypass
# 4. busy, queued, interrupted, idle with a suggestion, typed text (same session)
send "write a 400 word story about a bridge, no preamble"; waitfor 'esc to interrupt' ; sleep 2; save busy
send "reply with exactly the word QUEUED"; sleep 1; save busy-with-queued-message
TM send-keys -t $SESS Escape; waitfor 'Interrupted' ; sleep 1; save interrupted
send "reply with exactly the word OK1"; waitfor '^● OK1'; for i in $(seq 1 40); do [ "$(state)" = idle ] && break; sleep 0.5; done; sleep 4; save idle-after-answer
cap -e | grep -a '^.\[' | grep -a -E '❯' | cat -v > /out/screen-idle-after-answer.escapes.txt
TM send-keys -t $SESS -l $'multi\nline'; sleep 0.5; save idle-with-typed-multiline-text
TM send-keys -t $SESS C-c; sleep 0.5; save idle-after-ctrl-c-with-text
