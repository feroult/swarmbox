# Q6, clean preconditions: what Esc, Ctrl+C, Ctrl+U do. bash /spike/keys.sh (inside the container)
. /spike/lib.sh
PROJ=/work/proj; mkdir -p $PROJ; cd $PROJ; git init -q .; seed_home $PROJ
TM kill-server 2>/dev/null
TM new-session -d -s $SESS -x 120 -y 40 -c $PROJ bash; sleep 1
TM send-keys -t $SESS -l 'claude'; TM send-keys -t $SESS Enter
for i in $(seq 1 60); do sleep 0.5; s=$(cap); grep -q 'Managed settings' <<<"$s" && TM send-keys -t $SESS Enter; is_ready && break; done
show() { cap | python3 -c "
import sys
L=[l.rstrip() for l in sys.stdin if l.strip()]
L=['[rule]' if set(l.strip())<={'─'} else l[:105] for l in L]
print('\n'.join(L[-${2:-5}:]))"; }
send() { TM send-keys -t $SESS -l "$1"; sleep 0.15; TM send-keys -t $SESS Enter; }
now() { date +%s%N | cut -c1-13; }
wait_idle() { for i in $(seq 1 200); do [ "$(state)" = idle ] && return 0; sleep 0.25; done; }
clear_box() { for i in 1 2 3 4 5 6; do TM send-keys -t $SESS C-u; done; sleep 0.3; }
reset() { wait_idle; sleep 1; clear_box; }
busy_start() { send "write a 600 word story about a ship, no preamble"; for i in $(seq 1 40); do sleep 0.25; cap | grep -q '^●' && [ "$(state)" = busy ] && break; done; sleep 1; }

for key in Escape C-c; do
 for n in 1 2 3; do
  reset; busy_start; t0=$(now); TM send-keys -t $SESS $key
  res=STILL-BUSY; for i in $(seq 1 40); do sleep 0.1; if cap | grep -q 'Interrupted'; then res=INTERRUPTED; break; fi; done
  t1=$(now); sleep 1.5
  echo "busy + $key trial $n: $res after $((t1-t0)) ms, state now=$(state)"
 done
done
echo "--- screen after the last C-c (interrupt):"; show x 7; cap > /out/q6-interrupted.txt
echo; echo "--- Escape twice while busy"
reset; busy_start; TM send-keys -t $SESS Escape; sleep 0.1; TM send-keys -t $SESS Escape; sleep 1.5; echo "state=$(state)"; cap | grep -c Interrupted
echo; echo "--- idle, text 'some text' in box, then C-c"
reset; TM send-keys -t $SESS -l "some text"; sleep 0.3; TM send-keys -t $SESS C-c; sleep 0.8; show x 4
echo "--- idle, text in box, then Escape Escape"
reset; TM send-keys -t $SESS -l "some text"; sleep 0.3; TM send-keys -t $SESS Escape; sleep 0.1; TM send-keys -t $SESS Escape; sleep 0.8; show x 4
echo "--- idle, text in box, Escape once"
reset; TM send-keys -t $SESS -l "some text"; sleep 0.3; TM send-keys -t $SESS Escape; sleep 0.8; show x 4
echo "--- 3 lines in the box, C-u x1 / x3 / C-c"
reset; TM send-keys -t $SESS -l $'A1\nA2\nA3'; sleep 0.3; TM send-keys -t $SESS C-u; sleep 0.3; show x 4; echo "(C-u x1 above)"
TM send-keys -t $SESS C-u; TM send-keys -t $SESS C-u; sleep 0.3; show x 4; echo "(C-u x3 above)"
TM send-keys -t $SESS C-u; sleep 0.3
TM send-keys -t $SESS -l $'B1\nB2\nB3'; sleep 0.3; TM send-keys -t $SESS C-c; sleep 0.8; show x 4; echo "(C-c on 3 lines above)"
TM send-keys -t $SESS C-u; TM send-keys -t $SESS C-u;TM send-keys -t $SESS C-u; sleep 0.3
echo "--- empty box: C-c once, twice; what does the pane show"
reset; TM send-keys -t $SESS C-c; sleep 0.8; show x 4; TM send-keys -t $SESS C-c; sleep 2; show x 3; TM display -p -t $SESS 'pane_current_command=[#{pane_current_command}]'
