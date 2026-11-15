# Helpers for the "enter" spike. Source it inside the test container.
# Isolated tmux: never the master's server.
export HOME=/work/home
export TMUX_TMPDIR=${TMUX_TMPDIR:-/work/tmux}
mkdir -p "$HOME" "$TMUX_TMPDIR"
TM() { tmux -L spike "$@"; }
SESS=s

# cap [-e] : the visible screen of the pane, without trailing blank lines
cap() { TM capture-pane -p "$@" -t $SESS | sed -e :a -e '/^\n*$/{$d;N;ba' -e '}'; }

# seed_home DIR : first-run files so no onboarding/theme/trust dialog appears
seed_home() {
  local proj=$1
  mkdir -p "$HOME/.claude" "$proj"
  cat > "$HOME/.claude.json" <<J
{"hasCompletedOnboarding":true,"theme":"dark","projects":{"$proj":{"hasTrustDialogAccepted":true,"allowedTools":[]}}}
J
}

# is_ready : an empty or typed input box and the footer, no dialog
is_ready() { local s; s=$(cap); grep -q '^❯' <<<"$s" && ! grep -q -E 'Enter to confirm|Esc to (exit|cancel)' <<<"$s" && ! grep -q -E 'esc to interrupt' <<<"$s"; }

# boot [claude args...] : start claude in tmux and drive the one-time dialogs until the prompt is ready
boot() {
  TM kill-server 2>/dev/null; sleep 0.3
  TM new-session -d -s $SESS -x 120 -y 40 -c "$PROJ" "claude $*"
  local i s
  for i in $(seq 1 120); do
    sleep 0.5; s=$(cap)
    if grep -q 'Managed settings require approval' <<<"$s"; then TM send-keys -t $SESS Enter; continue; fi
    if grep -q 'Yes, I accept' <<<"$s"; then TM send-keys -t $SESS Down; sleep 0.3; TM send-keys -t $SESS Enter; continue; fi
    if is_ready; then echo "ready after ~$((i/2))s"; return 0; fi
  done
  echo "NOT READY"; cap; return 1
}

# state : dialog | busy | idle   (from the screen text alone, see docs/spikes/enter.md)
state() {
  local s; s=$(cap)
  if grep -q -E 'Enter to confirm|Esc to cancel|Esc to exit|Do you want to' <<<"$s"; then echo dialog
  elif grep -q 'esc to interrupt' <<<"$s"; then echo busy
  elif grep -q '^❯' <<<"$s"; then echo idle
  else echo unknown; fi
}
