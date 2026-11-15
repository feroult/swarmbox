# Q3b: do special characters reach the input box intact? Compare the typed text with the box content (unwrapped).
. /spike/lib.sh
PROJ=/work/proj; mkdir -p $PROJ; cd $PROJ; git init -q .; seed_home $PROJ
boot --permission-mode default || exit 1
body='it'"'"'s "q" `bt` $HOME $(id) \n é ✓ 日本 ñ ; | & > <'
TM send-keys -t $SESS -l "$body"; sleep 0.5
box=$(cap | sed -n '/^❯/,/^─/p' | sed '$d' | sed 's/^❯ //; s/^  //' | tr -d '\n')
[ "$box" = "$body" ] && echo "BOX EQUALS TYPED TEXT" || { echo "DIFF"; echo "typed: $body"; echo "box:   $box"; }
TM send-keys -t $SESS Enter
# the user line in history echoes the submitted prompt; check the model got it by asking to count
sleep 1
TM send-keys -t $SESS C-u
send() { TM send-keys -t $SESS -l "$1"; sleep 0.15; TM send-keys -t $SESS Enter; }
sleep 8
send 'Reply only with the number of characters in this string, nothing else: "é✓日本ñ"'
for i in $(seq 1 60); do sleep 0.5; cap | grep -q '^● [0-9]' && break; done; cap | grep '^●' | tail -1
# a prompt starting with a slash or with ! would be a command: how does the driver stay safe
TM send-keys -t $SESS -l '/'; sleep 0.8; echo "--- after typing /"; cap | tail -8 | cut -c1-100; TM send-keys -t $SESS C-u
TM send-keys -t $SESS -l '!'; sleep 0.8; echo "--- after typing !"; cap | tail -4 | cut -c1-100; TM send-keys -t $SESS Escape
