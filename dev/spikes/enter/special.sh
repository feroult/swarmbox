# Q3: special characters and newlines. bash /spike/special.sh (inside the container)
. /spike/lib.sh
PROJ=/work/proj; mkdir -p $PROJ; cd $PROJ; git init -q .; seed_home $PROJ
boot || exit 1
wait_idle() { for i in $(seq 1 120); do sleep 0.5; [ "$(state)" = idle ] && cap | grep -q '^●' && [ $i -gt 3 ] && break; done; }
settle() { sleep 1; }
# 1. special characters, plain driver method (-l, 150 ms, Enter)
for n in 1 2 3; do
  body="[it's \"q\" \`bt\` \$HOME \$(id) \\n é ✓ 日本 n$n]"
  TM send-keys -t $SESS -l "Repeat back exactly the text between the curly braces, nothing else: {$body}"; sleep 0.15; TM send-keys -t $SESS Enter
  for i in $(seq 1 90); do sleep 0.5; cap | grep -qF "● {$body}" && break; cap | grep -qF "● $body" && break; done
  if cap | grep -qF -e "$body"; then
    # distinguish echo of the prompt from the answer
    if cap | grep -E '^●' | grep -qF -e "$body"; then echo "special n$n OK (answer line has it)"; else echo "special n$n answer differs"; fi
  else echo "special n$n FAIL"; fi
  cap | grep -E '^●' | tail -1
  wait_idle
done
cap > /out/special-last.txt
# 2. newline inside -l text
echo "### literal LF with send-keys -l"
TM send-keys -t $SESS -l $'ALPHA-LF\nBETA-LF'; sleep 1; cap | tail -8; echo "state=$(state)"
TM send-keys -t $SESS C-u; sleep 0.5; echo "after C-u:"; cap | tail -5
# 3. candidate keys for newline in the input box
for k in S-Enter M-Enter C-j; do
  echo "### key $k"
  TM send-keys -t $SESS -l "LINE1-$k"; sleep 0.15; TM send-keys -t $SESS $k; sleep 0.15; TM send-keys -t $SESS -l "LINE2-$k"; sleep 1
  cap | tail -7; echo "state=$(state)"
  TM send-keys -t $SESS C-u; sleep 0.3; TM send-keys -t $SESS C-u; sleep 0.3; TM send-keys -t $SESS C-u; sleep 0.5
done
echo "### backslash+Enter"
TM send-keys -t $SESS -l 'LINE1-bs\'; sleep 0.15; TM send-keys -t $SESS Enter; sleep 0.15; TM send-keys -t $SESS -l "LINE2-bs"; sleep 1; cap | tail -7
TM send-keys -t $SESS C-u; sleep 0.3; TM send-keys -t $SESS C-u; sleep 0.5
# 4. bracketed paste of multi-line text, then Enter
echo "### paste-buffer -p"
printf 'Reply with the two words below, joined by a dash, nothing else.\nMULTI\nPASTE' | TM load-buffer -b spk -
TM paste-buffer -p -b spk -t $SESS; sleep 0.5; cap | tail -9
TM send-keys -t $SESS Enter
for i in $(seq 1 60); do sleep 0.5; cap | grep -q '^● MULTI' && break; done; cap | grep '^●' | tail -2
cap > /out/paste-last.txt
