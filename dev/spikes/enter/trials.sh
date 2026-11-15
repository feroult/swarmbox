# Trials of "type a prompt and submit it". Env: VARIANT (burst|p0|p50|p150|p300|p600), N (trials), OUT.
# Runs inside the test container: bash /spike/trials.sh
. /spike/lib.sh
VARIANT=${VARIANT:-p150}; N=${N:-8}
PROJ=/work/proj; mkdir -p $PROJ; cd $PROJ; git init -q .; seed_home $PROJ
boot ${CLAUDE_ARGS:-} || exit 1

ms() { echo $(( $(date +%s%N) / 1000000 )); }
ok=0
for n in $(seq 1 $N); do
  tag="PONG-$VARIANT-$n"
  t0=$(ms)
  # the sleep value in seconds for the variant
  if [[ $VARIANT =~ ^p([0-9]+)$ ]]; then sleep_s=$(awk "BEGIN{print ${BASH_REMATCH[1]}/1000}"); fi
  text="reply with exactly the word $tag"
  if [ -n "$LONG" ]; then   # about $LONG characters of filler before the instruction
    filler=$(head -c $LONG /dev/zero | tr '\0' 'x' | sed 's/xxxxx/lorem /g')
    text="Background text to ignore: ${filler}. Now the real instruction: $text"
  fi
  case $VARIANT in
    burst) TM send-keys -t $SESS -l "$text" \; send-keys -t $SESS Enter ;;
    p0)    TM send-keys -t $SESS -l "$text"; TM send-keys -t $SESS Enter ;;
    *)     TM send-keys -t $SESS -l "$text"; sleep $sleep_s; TM send-keys -t $SESS Enter ;;
  esac
  res=FAIL
  for i in $(seq 1 120); do
    sleep 0.5
    if cap | grep -q "^● $tag"; then res=OK; break; fi
  done
  t1=$(ms)
  if [ $res = OK ]; then ok=$((ok+1)); else cap | tail -8 > /out/fail-$VARIANT-$n.txt; TM send-keys -t $SESS C-u; fi
  # wait for idle before the next trial
  for i in $(seq 1 60); do [ "$(state)" = idle ] && break; sleep 0.5; done
  echo "$VARIANT trial $n $res $((t1-t0))ms state=$(state)"
done
echo "RESULT $VARIANT $ok/$N"
