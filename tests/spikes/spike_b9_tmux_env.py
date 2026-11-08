"""Spike B9: how tmux passes its environment to new windows (design 7.3).

Design claim (7.3): all windows are created by the tmux server that started inside the box, with the environment it was
created with, so browser and host tabs see the same variables. Expected: a variable set for the server (X=1) is what a
window sees even when the client that asks for the window has X=2 (attached or not), unless update-environment lists X.
Run: python3 tests/spikes/spike_b9_tmux_env.py   Exit 1 if the claim is contradicted.
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import spikes_common as sc  # noqa: E402

SCRIPT = r'''
set -u
S="tmux -L b9 -f /dev/null"
unset TMUX
out=/tmp/out; rm -rf $out; mkdir -p $out
# the server starts with X=1 (the way serve starts it: its own environment)
X=1 $S new-session -d -s main 'sleep 600'
wait_file() { for i in $(seq 1 50); do [ -s "$1" ] && return 0; sleep 0.1; done; return 1; }

# 1. a window requested by a client process whose environment has X=2 (the shape of `podman exec -e X=2 ... tmux new-window`)
X=2 $S new-window -d -t main "sh -c 'echo \$X > $out/client_cmd'"
wait_file $out/client_cmd

# 2. a window requested from the server's own command (run-shell: a child of the server)
$S run-shell "tmux -L b9 -f /dev/null new-window -d \"sh -c 'echo \\\$X > $out/server_cmd'\""
wait_file $out/server_cmd

# 3. the design's attach: an ATTACHED client (pty through script) with X=2 creates a grouped session and a window
cat > /tmp/attach.sh <<EOF2
X=2 tmux -L b9 -f /dev/null new-session -t main -s grp \; new-window -d "sh -c 'echo \\\$X > $out/attached_cmd'"
EOF2
sleep 4 | script -qfc "sh /tmp/attach.sh" /dev/null >/dev/null 2>&1 &
wait_file $out/attached_cmd

# 4. the same for the first window of a NEW session created by an X=2 client (new-session -d from outside)
X=2 $S new-session -d -s other "sh -c 'echo \$X > $out/newsession_cmd; sleep 5'"
wait_file $out/newsession_cmd

# 5. what tmux itself holds: the global environment and the session environment seen by the grouped session
$S show-environment -g X > $out/global_env 2>&1
$S show-environment -t grp X > $out/grp_env 2>&1

# 6. update-environment containing X: then an attached client with X=3 passes it on
$S set-option -g update-environment "X"
cat > /tmp/attach2.sh <<EOF2
X=3 tmux -L b9 -f /dev/null new-session -t main -s grp3 \; new-window -d "sh -c 'echo \\\$X > $out/updenv_attached'"
EOF2
sleep 4 | script -qfc "sh /tmp/attach2.sh" /dev/null >/dev/null 2>&1 &
wait_file $out/updenv_attached
# and a window made by the unattached X=3 client with update-environment set
X=3 $S new-window -d -t main "sh -c 'echo \$X > $out/updenv_client'"
wait_file $out/updenv_client
$S kill-server
for f in $out/*; do printf '%s=%s\n' "$(basename $f)" "$(cat $f | tr -d '\r\n')"; done
'''


def main():
    sp = sc.Spike("b9")
    image = sc.ensure_spike_image(sp)
    name = sp.name()
    sp.run(name, image, "--userns=keep-id:uid=1000,gid=1000", cmd=["sleep", "infinity"])
    r = sp.exec(name, "bash", "-c", SCRIPT, user="1000", timeout=120)
    print(r.stdout)
    if r.stderr.strip():
        print("stderr: " + r.stderr.strip()[:400])
    got = dict(l.split("=", 1) for l in r.stdout.splitlines() if "=" in l)
    sp.expect("script ran", r.returncode == 0 and got, "rc=%d" % r.returncode)
    sp.expect("window requested by a client with X=2 sees the server's X=1 (unattached client)",
              got.get("client_cmd") == "1", repr(got.get("client_cmd")))
    sp.expect("window started from the server's own command sees X=1", got.get("server_cmd") == "1",
              repr(got.get("server_cmd")))
    sp.expect("window created by an ATTACHED client with X=2 (grouped session, as 3.4) sees X=1",
              got.get("attached_cmd") == "1", repr(got.get("attached_cmd")))
    sp.expect("a new session's first window from an X=2 client sees X=1", got.get("newsession_cmd") == "1",
              repr(got.get("newsession_cmd")))
    print("  tmux global environment X: %r; grouped session environment X: %r" % (
        got.get("global_env"), got.get("grp_env")))
    # informational: with update-environment=X the client's value does travel (so the default is what 7.3 relies on)
    print("  with update-environment=X: attached client X=3 -> window sees %r; unattached X=3 client -> %r" % (
        got.get("updenv_attached"), got.get("updenv_client")))
    tag = sc.evidence("tmux 3.3a in a container: server X=1; clients X=2 attached (script pty) and unattached; run-shell; "
                      "update-environment control", image)
    return sp.finish(tag, "windows get the server's environment (X=1) whichever client asks; update-environment=X "
                          "makes an attached client's value travel (attached=%s, unattached=%s)" % (
                              got.get("updenv_attached"), got.get("updenv_client")))


if __name__ == "__main__":
    sys.exit(main())
