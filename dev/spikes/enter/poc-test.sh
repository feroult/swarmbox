# Test of enter.sh against the real claude. bash /spike/poc-test.sh (inside the container)
. /spike/lib.sh
PROJ=/work/proj; mkdir -p $PROJ; cd $PROJ; git init -q .; seed_home $PROJ
boot || exit 1
E="/spike/enter.sh -L spike -t $SESS"
wait_idle() { for i in $(seq 1 240); do [ "$(state)" = idle ] && return 0; sleep 0.25; done; return 1; }
answer() { for i in $(seq 1 120); do sleep 0.5; cap | grep -q "^● $1" && return 0; done; return 1; }
pass=0; total=0
check() { total=$((total+1)); if [ "$1" = "$2" ]; then pass=$((pass+1)); echo "PASS $3"; else echo "FAIL $3 (got $1, want $2)"; fi; }

echo "== 1. short prompt, 8 times"
for n in 1 2 3 4 5 6 7 8; do wait_idle; $E -- "reply with exactly the word SHORT-$n"; rc=$?; answer "SHORT-$n"; check "$rc/$?" "0/0" "short $n"; done
echo "== 2. 600 chars, newlines, quotes, backticks, \$, unicode, 8 times"
filler=$(head -c 400 /dev/zero | tr '\0' 'x' | sed 's/xxxxx/lorem /g')
for n in 1 2 3 4 5 6 7 8; do wait_idle
  $E -- "Ignore this background: ${filler}
it's \"q\" \`bt\` \$HOME \$(id) é ✓ 日本
Now reply with exactly the word LONG-$n"; rc=$?; answer "LONG-$n"; check "$rc/$?" "0/0" "long $n"; done
echo "== 3. busy: refuse, then --queue"
wait_idle; $E -- "write a 500 word story about a ship, no preamble"; sleep 3
$E -- "reply with exactly the word NOQUEUE"; check "$?" 4 "busy is refused"
$E --queue -- "reply with exactly the word QUEUED-OK"; check "$?" 0 "queue accepted while busy"
answer "QUEUED-OK"; check "$?" 0 "queued prompt answered after the story"
echo "== 4. slash"
wait_idle; $E -- "/help"; check "$?" 6 "slash refused"
echo "== 5. dialog (permission prompt) refuses typing"
boot --permission-mode default >/dev/null
$E -- "Use the Bash tool to run exactly: touch /work/proj/x.txt"; sleep 12; cap | tail -3 | head -1; st=$(state)
$E -- "reply with exactly the word NOPE"; rc=$?; check "$st/$rc" "dialog/3" "dialog refuses"
echo "RESULT $pass/$total"
