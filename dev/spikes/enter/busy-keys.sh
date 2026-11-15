# Q5 (typing while busy) and Q6 (Esc, Ctrl+C). bash /spike/busy-keys.sh (inside the container)
. /spike/lib.sh
PROJ=/work/proj; mkdir -p $PROJ; cd $PROJ; git init -q .; seed_home $PROJ
boot || exit 1
snap() { echo "----- $1 [state=$(state)]"; cap | grep -v '^\s*$' | tail -${2:-8} | cut -c1-110; }
send() { TM send-keys -t $SESS -l "$1"; sleep 0.15; TM send-keys -t $SESS Enter; }
wait_state() { for i in $(seq 1 160); do [ "$(state)" = "$1" ] && return 0; sleep 0.5; done; return 1; }
long() { send "write a 500 word story about a ship, no preamble"; sleep 3; }

echo "######## Q5a: prompt + Enter typed while busy"
long; snap "busy" 4
send "reply with exactly the word QUEUED-ONE"; sleep 1; snap "right after typing while busy" 8
wait_state idle; sleep 8; wait_state idle; snap "later" 14
cap > /out/q5-after-queue.txt

echo "######## Q5b: text typed while busy, no Enter"
long; TM send-keys -t $SESS -l "HALF-TYPED"; sleep 1; snap "typing, no enter" 6
wait_state idle; sleep 1; snap "after answer ended: is the half text kept?" 6
TM send-keys -t $SESS C-u; sleep 0.3

echo "######## Q6a: Esc while busy"
long; TM send-keys -t $SESS Escape; sleep 1.5; snap "after Esc" 8; cap > /out/q6-esc-busy.txt
echo "######## Q6b: Ctrl+C while busy"
long; TM send-keys -t $SESS C-c; sleep 1.5; snap "after one Ctrl+C" 8; cap > /out/q6-cc-busy.txt
echo "######## Q6c: Ctrl+C with text in the box"
TM send-keys -t $SESS -l "some text"; sleep 0.3; TM send-keys -t $SESS C-c; sleep 1; snap "after Ctrl+C with text" 5
echo "######## Q6d: Esc with text in the box; Esc Esc"
TM send-keys -t $SESS -l "some text"; sleep 0.3; TM send-keys -t $SESS Escape; sleep 1; snap "after Esc with text" 4
TM send-keys -t $SESS Escape; sleep 1; snap "after Esc Esc with text" 6; cap > /out/q6-escesc.txt
TM send-keys -t $SESS C-u; sleep 0.3
echo "######## Q6e: multi-line text, how to clear"
TM send-keys -t $SESS -l $'A1\nA2\nA3'; sleep 0.5; TM send-keys -t $SESS C-u; sleep 0.3; snap "after one C-u on 3 lines" 5
TM send-keys -t $SESS C-u; TM send-keys -t $SESS C-u; sleep 0.3; snap "after 3 C-u" 5
TM send-keys -t $SESS -l $'B1\nB2\nB3'; sleep 0.5; TM send-keys -t $SESS C-a C-k; sleep 0.3; snap "after C-a C-k" 5
TM send-keys -t $SESS -l $'C1\nC2\nC3'; sleep 0.5; TM send-keys -t $SESS C-a; TM send-keys -t $SESS C-k;  TM send-keys -t $SESS C-k;  TM send-keys -t $SESS C-k; TM send-keys -t $SESS C-k; sleep 0.3; snap "after C-k x4" 5
echo "######## Q6f: Ctrl+C on empty box, twice"
TM send-keys -t $SESS C-u C-u C-u; sleep 0.3
TM send-keys -t $SESS C-c; sleep 1; snap "1st Ctrl+C on empty" 4
TM send-keys -t $SESS C-c; sleep 2; echo "after 2nd: sessions=$(TM list-sessions 2>&1 | head -1)"
