"""Spike B13: the `swarmbox <command>` mechanism of design 3.3 (detached window, wait-for channel, status file).

Design claims (3.3, 3.4, 13.3 layer 6): the call returns when the command ends and with its exit code (0, 1, 130, a
signal = 128+n); quoting survives; an alias and a PATH addition of the shell fragment apply (the command runs through
`bash -ic`); a missing status file gives exit 1; with standard output not a terminal, `podman exec` runs without -t
and the output has no CRLF; the command can run directly (no tmux) through `bash -ic`.
Run: python3 tests/spikes/spike_b13_run_command.py   Exit 1 if a claim is contradicted.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import spikes_common as sc  # noqa: E402

ARGS = ["a b", "it's", "$HOME", '"dq"', "a\\b", "*", "line1\nline2", "", "-n", "~", "`id`",
        ";touch /tmp/pwned", "&", "!x", "é", "tab\there", "  lead and trail  "]

PROTO = r'''
# prototype of the 3.3 mechanism, run inside the container as the agent user (a stand-in for swarmbox-attach)
S="tmux -L b13 -f /dev/null"
sd=/tmp/swarmbox
export HOME=/home/node
unset TMUX
mkdir -p $sd /home/node/bin
cat > /home/node/.bashrc <<'EOF2'
case $- in *i*) ;; *) return;; esac
alias greet='sh -c '"'"'echo "$@" > /tmp/alias_out'"'"' x --auto-approve'
export PATH=$HOME/bin:$PATH
EOF2
printf '#!/bin/sh\necho "mytool:$*" > /tmp/path_out\n' > /home/node/bin/mytool; chmod +x /home/node/bin/mytool
$S new-session -d -s main 'sleep 3600'

# usage: run_cmd args...   (sets RC, WIN). The wrapper: bash -ic "<%q string>"; status file; wait-for -S
WRAP='bash -ic "$1"; s=$?; echo $s > "$2.tmp"; mv "$2.tmp" "$2"; tmux wait-for -S "$3"'
run_cmd() {
  id=$(date +%s%N)$RANDOM
  q=$(printf '%q ' "$@")
  rm -f $sd/exit.$id
  WIN=$($S new-window -d -P -F '#{window_id}' -t main: bash -c "$WRAP" wrapper "$q" "$sd/exit.$id" "swarmbox-$id")
  $S wait-for swarmbox-$id
  if [ -s $sd/exit.$id ]; then RC=$(cat $sd/exit.$id); rm -f $sd/exit.$id; else RC=missing; fi
}
rcof() { run_cmd "$@"; echo "$RC"; }

echo "rc_true=$(rcof true)"
echo "rc_false=$(rcof false)"
echo "rc_exit130=$(rcof sh -c 'exit 130')"
echo "rc_exit7=$(rcof sh -c 'exit 7')"
echo "rc_kill9=$(rcof sh -c 'kill -9 $$')"
echo "rc_kill15=$(rcof sh -c 'kill -15 $$')"
echo "rc_notfound=$(rcof no-such-command-xyz)"

# race: a command that ends at once must not lose the wake-up (the signal may come before wait-for)
bad=0; for i in $(seq 1 30); do r=$(rcof true); [ "$r" = 0 ] || bad=$((bad+1)); done
echo "race_failures=$bad"

# timing of the whole call
t0=$(date +%s%N); run_cmd true; t1=$(date +%s%N); echo "ms_true=$(( (t1-t0)/1000000 ))"
t0=$(date +%s%N); run_cmd sleep 1; t1=$(date +%s%N); echo "ms_sleep1=$(( (t1-t0)/1000000 ))"

# quoting: the arguments reach the command byte for byte
mapfile -d '' -t ARGS < /tmp/args
rm -f /tmp/q.out
run_cmd sh -c 'printf "%s\0" "$@" > /tmp/q.out' sh "${ARGS[@]}"
echo "q_rc=$RC"
echo "q_hex=$(od -An -tx1 -v /tmp/q.out | tr -d ' \n')"
od -c /tmp/q.out | head -12 > /tmp/q.od
test ! -e /tmp/pwned && echo "injection=none" || echo "injection=PWNED"

# alias and PATH from the interactive fragment
run_cmd greet world; echo "alias_rc=$RC"; echo "alias_out=$(cat /tmp/alias_out 2>/dev/null)"
run_cmd mytool one two; echo "path_rc=$RC"; echo "path_out=$(cat /tmp/path_out 2>/dev/null)"
# control: without -i neither applies
rm -f /tmp/alias_out; bash -c 'greet world' 2>/dev/null; echo "noninteractive_alias_rc=$? out=$(cat /tmp/alias_out 2>/dev/null)"

# a window killed from elsewhere: does wait-for return? (it must not hang the caller)
WRAP_SAVE=$WRAP
id=killed$RANDOM
WIN=$($S new-window -d -P -F '#{window_id}' -t main: bash -c "$WRAP" wrapper "sleep 60" "$sd/exit.$id" "swarmbox-$id")
sleep 0.5
$S kill-window -t "$WIN"
( $S wait-for swarmbox-$id; echo done > /tmp/waitfor_returned ) &
WP=$!
for i in $(seq 1 30); do [ -e /tmp/waitfor_returned ] && break; sleep 0.1; done
if [ -e /tmp/waitfor_returned ]; then echo "killed_window_waitfor=returned"; else echo "killed_window_waitfor=HANGS"; kill $WP 2>/dev/null; fi
echo "killed_status_file=$([ -e $sd/exit.$id ] && echo present || echo absent)"

# the same with a trap in the wrapper that records 129 and signals the channel
WRAP2='trap '"'"'echo 129 > "$2"; tmux wait-for -S "$3"; exit 129'"'"' HUP TERM; bash -ic "$1" & wait $!; s=$?; trap - HUP TERM; echo $s > "$2.tmp"; mv "$2.tmp" "$2"; tmux wait-for -S "$3"'
rm -f /tmp/waitfor_returned
id=killed2$RANDOM
WIN=$($S new-window -d -P -F '#{window_id}' -t main: bash -c "$WRAP2" wrapper "sleep 60" "$sd/exit.$id" "swarmbox-$id")
sleep 0.5
$S kill-window -t "$WIN"
( $S wait-for swarmbox-$id; echo done > /tmp/waitfor_returned ) &
WP=$!
for i in $(seq 1 30); do [ -e /tmp/waitfor_returned ] && break; sleep 0.1; done
if [ -e /tmp/waitfor_returned ]; then echo "killed_window_trap_waitfor=returned status=$(cat $sd/exit.$id 2>/dev/null)"; else echo "killed_window_trap_waitfor=HANGS"; kill $WP 2>/dev/null; fi

# the attached variant: a grouped session client (pty via script) selected on the window; ended after the wait-for
attached() {
  id=$(date +%s%N)$RANDOM; q=$(printf '%q ' "$@"); rm -f $sd/exit.$id
  WIN=$($S new-window -d -P -F '#{window_id}' -t main: bash -c "$WRAP" wrapper "$q" "$sd/exit.$id" "swarmbox-$id")
  ( sleep 60 | script -qfc "tmux -L b13 -f /dev/null new-session -t main -s grp$id \; select-window -t $WIN" /dev/null >/dev/null 2>&1 ) &
  CP=$!
  $S wait-for swarmbox-$id
  $S kill-session -t grp$id 2>/dev/null
  # the client must return by itself once its session is gone, even though window main:0 still exists
  for i in $(seq 1 30); do $S has-session -t grp$id 2>/dev/null || break; sleep 0.1; done
  ACLIENT=$($S has-session -t grp$id 2>/dev/null && echo alive || echo ended)
  RC=$(cat $sd/exit.$id 2>/dev/null || echo missing); rm -f $sd/exit.$id
  kill $CP 2>/dev/null
}
attached sh -c 'exit 3'; echo "attached_rc=$RC client=$ACLIENT"
attached true; echo "attached_true_rc=$RC client=$ACLIENT"
echo "windows_left=$($S list-windows -t main -F '#{window_index}' | tr '\n' ' ')"

# no terminal: bash -ic run directly (no tmux), as the design says for the no-terminal case
bash -ic 'true' >/tmp/direct.out 2>/tmp/direct.err </dev/null; echo "direct_rc=$?"
echo "direct_stderr=$(tr '\n' '|' < /tmp/direct.err)"
bash -ic 'exit 130' >/dev/null 2>&1 </dev/null; echo "direct_130=$?"

# no terminal, alternative: a non-interactive bash that sources the fragment, whose guard also accepts SWARMBOX_CMD=1
cat > /home/node/.bashrc <<'EOF2'
case $- in *i*) ;; *) [ -n "${SWARMBOX_CMD:-}" ] || return;; esac
alias greet='sh -c '"'"'echo "$@" > /tmp/alias_out'"'"' x --auto-approve'
export PATH=$HOME/bin:$PATH
EOF2
rm -f /tmp/alias_out /tmp/path_out
SWARMBOX_CMD=1 bash -c 'shopt -s expand_aliases; . ~/.bashrc; eval "$1"' bash 'greet world; mytool a b; exit 9' >/dev/null 2>/tmp/alt.err </dev/null; echo "alt_rc=$?"
echo "alt_stderr=$(tr '\n' '|' < /tmp/alt.err)"
echo "alt_alias=$(cat /tmp/alias_out 2>/dev/null) alt_path=$(cat /tmp/path_out 2>/dev/null)"
# the interactive guard is unchanged for real interactive shells (tmux window with the same fragment)
run_cmd greet again; echo "guard_alias_rc=$RC out=$(cat /tmp/alias_out 2>/dev/null)"

# a window whose wrapper is SIGKILLed (no trap can run): the window must at least disappear so a poll can notice
id=k9$RANDOM
WIN=$($S new-window -d -P -F '#{window_id}' -t main: bash -c "$WRAP" wrapper "sleep 60" "$sd/exit.$id" "swarmbox-$id")
sleep 0.5
PP=$($S list-panes -t "$WIN" -F '#{pane_pid}'); kill -9 $PP
for i in $(seq 1 30); do $S list-windows -t main -F '#{window_id}' | grep -qx "$WIN" || break; sleep 0.1; done
$S list-windows -t main -F '#{window_id}' | grep -qx "$WIN" && echo "sigkill_window=still-listed" || echo "sigkill_window=gone"
$S kill-server
'''


def main():
    sp = sc.Spike("b13")
    image = sc.ensure_spike_image(sp)
    name = sp.name()
    sp.run(name, image, "--userns=keep-id:uid=1000,gid=1000", cmd=["sleep", "infinity"])
    work = sp.mkdtemp("b13")
    with open(os.path.join(work, "args"), "wb") as f:
        for a in ARGS:
            f.write(a.encode() + b"\0")
    with open(os.path.join(work, "proto.sh"), "w") as f:
        f.write(PROTO)
    for fn in ("args", "proto.sh"):
        os.chmod(os.path.join(work, fn), 0o644)
        sp.podman("cp", os.path.join(work, fn), name + ":/tmp/" + fn, check=True)
    r = sp.exec(name, "bash", "/tmp/proto.sh", user="1000", timeout=240)
    print(r.stdout)
    if r.stderr.strip():
        print("stderr: " + r.stderr.strip()[:600])
    got = {}
    for l in r.stdout.splitlines():
        if "=" in l:
            k, v = l.split("=", 1)
            got[k] = v
    sp.expect("prototype ran to the end", "direct_130" in got, "rc=%s" % r.returncode)
    sp.expect("true -> 0", got.get("rc_true") == "0", got.get("rc_true"))
    sp.expect("false -> 1", got.get("rc_false") == "1", got.get("rc_false"))
    sp.expect("sh -c 'exit 130' -> 130", got.get("rc_exit130") == "130", got.get("rc_exit130"))
    sp.expect("exit 7 -> 7", got.get("rc_exit7") == "7", got.get("rc_exit7"))
    sp.expect("killed by SIGKILL -> 137 (128+9)", got.get("rc_kill9") == "137", got.get("rc_kill9"))
    sp.expect("killed by SIGTERM -> 143 (128+15)", got.get("rc_kill15") == "143", got.get("rc_kill15"))
    sp.expect("command not found -> 127", got.get("rc_notfound") == "127", got.get("rc_notfound"))
    sp.expect("30 instant commands never lose the wake-up (signal before wait-for)", got.get("race_failures") == "0",
              got.get("race_failures"))
    print("  timing: true=%s ms, sleep 1=%s ms" % (got.get("ms_true"), got.get("ms_sleep1")))
    expected = b"".join(a.encode() + b"\0" for a in ARGS).hex()
    sp.expect("17 awkward arguments (space, quotes, $, backslash, glob, newline, empty, -n, ~, backtick, ;, &, !, "
              "unicode, tab) reach the command byte for byte", got.get("q_hex") == expected and got.get("q_rc") == "0",
              "rc=%s got=%s" % (got.get("q_rc"), (got.get("q_hex") or "")[:80]))
    sp.expect("no shell injection from an argument", got.get("injection") == "none", got.get("injection"))
    sp.expect("alias of the interactive fragment applies", got.get("alias_out") == "--auto-approve world",
              repr(got.get("alias_out")))
    sp.expect("PATH addition of the interactive fragment applies", got.get("path_out") == "mytool:one two",
              repr(got.get("path_out")))
    print("  control, plain bash -c: %s" % got.get("noninteractive_alias_rc", ""))
    kw = got.get("killed_window_waitfor")
    print("  window killed from elsewhere, plain wrapper: wait-for %s; status file %s" % (kw, got.get("killed_status_file")))
    # Finding of 2026-11-08: design 3.3 first assumed a missing status file gives exit 1; in fact the caller would hang.
    sp.expect("control (the finding): with a plain wrapper, killing the window leaves wait-for blocked forever, so the "
              "wrapper needs a HUP/TERM trap", kw == "HANGS", kw)
    kt = got.get("killed_window_trap_waitfor", "")
    print("  window killed from elsewhere, wrapper with a HUP/TERM trap: %s" % kt)
    sp.expect("wrapper with a trap: wait-for returns and a status (129) is recorded when the window is killed",
              kt.startswith("returned") and kt.endswith("status=129"), kt)
    print("  attached variant: %s | %s | windows left: %s" % (got.get("attached_rc"), got.get("attached_true_rc"),
                                                              got.get("windows_left")))
    sp.expect("attached: the status is returned and the grouped session ends by itself",
              got.get("attached_rc") == "3 client=ended" and got.get("attached_true_rc") == "0 client=ended",
              "%s | %s" % (got.get("attached_rc"), got.get("attached_true_rc")))
    print("  no terminal, bash -ic direct: rc=%s stderr=%r; exit 130 -> %s" % (
        got.get("direct_rc"), got.get("direct_stderr"), got.get("direct_130")))
    sp.expect("no tty: bash -ic returns the command's status", got.get("direct_rc") == "0" and
              got.get("direct_130") == "130", "%s %s" % (got.get("direct_rc"), got.get("direct_130")))
    sp.expect("control (the finding): bash -ic without a terminal writes 'cannot set terminal process group' and 'no job "
              "control' to stderr, so the no-terminal path must not use it",
              "no job control" in (got.get("direct_stderr") or ""), got.get("direct_stderr"))
    sp.expect("no tty, alternative: `bash -c` that sources the fragment (guard accepts SWARMBOX_CMD=1) applies alias and PATH "
              "with a clean stderr and returns the status",
              got.get("alt_rc") == "9" and got.get("alt_stderr") == "" and
              got.get("alt_alias") == "--auto-approve world alt_path=mytool:a b",
              "rc=%s stderr=%r alias/path=%r" % (got.get("alt_rc"), got.get("alt_stderr"), got.get("alt_alias")))
    sp.expect("the extended guard still lets a real interactive window apply the alias",
              got.get("guard_alias_rc", "").startswith("0 out=--auto-approve again"), got.get("guard_alias_rc"))
    sp.expect("a SIGKILLed wrapper makes its window disappear (a waiter can poll the window id as a fallback)",
              got.get("sigkill_window") == "gone", got.get("sigkill_window"))
    # CRLF: podman exec without -t, output through a pipe
    out_plain = sp.exec(name, "sh", "-c", "printf 'a\\nb\\n'", user="1000")
    sp.expect("podman exec without -t: output 'a\\nb\\n' has no CR", out_plain.stdout.encode() == b"a\nb\n",
              repr(out_plain.stdout))
    out_tty = sp.exec(name, "sh", "-c", "printf 'a\\nb\\n'", user="1000", tty=True)
    print("  control, podman exec -t with a pipe on stdout: %r (rc %d, stderr %r)" % (
        out_tty.stdout, out_tty.returncode, out_tty.stderr.strip()[:100]))
    # stdout through od -c for the record
    od = sp.exec(name, "sh", "-c", "printf 'x\\ny\\n' | od -c", user="1000")
    print("  od -c of the piped output of a plain exec: %s" % od.stdout.strip().replace("\n", " | "))
    if got.get("direct_stderr"):
        print("  NOTE bash -ic without a terminal writes to stderr: %s" % got["direct_stderr"])
    tag = sc.evidence("tmux 3.3a in a container, prototype wrapper (bash -ic, status file, tmux wait-for), podman exec with and "
                      "without -t, od -c / hex compare", image,
                      reduced="the grouped client uses script(1) as the pty; no real ttyd or host terminal")
    return sp.finish(tag, "exit codes, quoting, alias and PATH confirmed; two corrections: the wrapper needs a HUP/TERM trap "
                          "(a killed window hangs wait-for), and the no-terminal path needs a non-interactive shell that "
                          "sources the fragment (bash -ic prints job-control errors)")


if __name__ == "__main__":
    sys.exit(main())
