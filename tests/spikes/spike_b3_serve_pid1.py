"""Spike B3: `serve` as the container's main process supervising ttyd (design 4.1, 4.2, 5.1).

Design claims: serve works as PID 1 (alone or under --init); ttyd dies and is restarted without stopping the box;
`swarmbox-web restart` restarts ttyd and resets the crash count; after 5 exits in 60 s the supervisor gives up and
writes a health line while the box stays up; SIGTERM and SIGINT handlers run as PID 1 with and without --init and the
`podman stop` takes well under the 10 s kill timeout; with WEB=0 serve blocks without ttyd; waiting on a background
`sleep infinity` lets the handler run at once, which a foreground sleep would not.
The prototype below stands in for container/entrypoint.sh serve (steps 0, 9, 10, 11 and a fake "nested Podman service"
child). ttyd is the real pinned 1.7.7 static binary copied from the box into the scratch image.
Run: python3 tests/spikes/spike_b3_serve_pid1.py   Exit 1 if a claim is contradicted.
"""
import os
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import spikes_common as sc  # noqa: E402

CPORT = 7000  # ttyd's port INSIDE the throwaway container; the host side is a random 20000-40000 port on 127.0.0.1

SERVE = r'''#!/bin/bash
# prototype of design 4.1 serve: steps 0, 9, 10, 11 plus a fake service child, then the blocking wait
MODE=${MODE:-good}            # good | fg-sleep (handler but foreground sleep) | nohandler
SD=/tmp/swarmbox; mkdir -p $SD
rm -f $SD/ready $SD/exit.* $SD/health                               # step 0
log() { echo "$(date +%T.%N) serve[$$]: $*"; }
SCALE=${SB_SCALE:-1}

supervise() {                                                        # step 10 (4.2 restart policy)
  local TP=0 stop=0 restart=0 exits=() delay=1 now i keep
  echo $BASHPID > $SD/sup.pid
  trap 'stop=1; [ $TP -gt 0 ] && kill $TP 2>/dev/null' TERM
  trap 'restart=1; [ $TP -gt 0 ] && kill $TP 2>/dev/null' USR1       # what `swarmbox-web restart` sends
  while [ $stop = 0 ]; do
    if [ $restart = 1 ]; then restart=0; exits=(); delay=1; : > $SD/health; log "ttyd restarted by hand; count reset"; fi
    ttyd -W -p '''+str(CPORT)+r''' tmux attach -t main >/tmp/ttyd.log 2>&1 & TP=$!
    echo $TP > $SD/ttyd.pid
    while kill -0 $TP 2>/dev/null; do wait $TP; done                  # wait returns early when a trap fires
    TP=0
    [ $stop = 1 ] && break
    if [ $restart = 1 ]; then restart=0; exits=(); delay=1; : > $SD/health; log "ttyd restarted by hand; count reset"; continue; fi
    now=$(date +%s); exits+=($now); keep=()
    for i in "${exits[@]}"; do [ $((now - i)) -lt 60 ] && keep+=($i); done; exits=("${keep[@]}")
    if [ ${#exits[@]} -ge 5 ]; then
      echo "web terminal keeps crashing; see web-terminal.log" >> $SD/health; log "giving up on ttyd; waiting for a hand restart"
      while [ $restart = 0 ] && [ $stop = 0 ]; do sleep 100000 & SP=$!; wait $SP; kill $SP 2>/dev/null; done
      continue                                                        # loop top: restart or stop handled there
    fi
    log "ttyd exited; restart in $((delay * SCALE))s"
    sleep $((delay * SCALE)) & wait $!                                # interruptible backoff
    delay=$((delay * 2)); [ $delay -gt 30 ] && delay=30
  done
  exit 0
}

shutdown() {
  log "stopping children"
  [ -n "${SUP:-}" ] && kill -TERM $SUP 2>/dev/null && wait $SUP 2>/dev/null
  [ -n "${SVC:-}" ] && kill -TERM $SVC 2>/dev/null && wait $SVC 2>/dev/null
  if [ -s $SD/ttyd.pid ] && kill -0 "$(cat $SD/ttyd.pid)" 2>/dev/null; then log "ttyd STILL ALIVE"; else log "ttyd gone"; fi
  log "leaving the tmux server to end with the container"
}

if [ "$MODE" != nohandler ]; then
  trap 'log "got SIGTERM"; shutdown; exit 143' TERM
  trap 'log "got SIGINT"; shutdown; exit 130' INT
fi

sleep 100000 & SVC=$!                                                # stands in for the nested Podman service (step 8)
tmux new-session -d -s main                                          # step 9
if [ "${WEB:-1}" = 1 ]; then supervise & SUP=$!; fi                  # step 10
echo ok > $SD/ready                                                  # step 11
log "ready; pid $$; WEB=${WEB:-1}; mode $MODE"
case $MODE in
  good) sleep infinity & wait $!;;                                   # the design's blocking form
  fg-sleep) sleep infinity;;                                         # control: foreground sleep delays the handler
  nohandler) while :; do sleep 1; done;;                             # control: no handler at all
esac
'''


def wait_for(fn, seconds=20, step=0.2):
    end = time.time() + seconds
    while time.time() < end:
        v = fn()
        if v:
            return v
        time.sleep(step)
    return None


def http_ok(port):
    try:
        with urllib.request.urlopen("http://127.0.0.1:%d/" % port, timeout=3) as r:
            body = r.read(4000).decode("utf-8", "replace")
            return r.status == 200 and "ttyd" in body.lower()
    except Exception:
        return False


class Box:
    def __init__(self, sp, image, work, ident, init=False, web=1, mode="good", scale=1, port=None):
        self.sp, self.image, self.work = sp, image, work
        self.name = sp.name(ident)
        self.port = port or sp.free_port()
        self.web = web
        opts = ["--userns=keep-id:uid=1000,gid=1000", "-v", work + ":/opt/spike:ro",
                "-e", "WEB=%d" % web, "-e", "MODE=" + mode, "-e", "SB_SCALE=%d" % scale]
        if web:
            opts += ["-p", "127.0.0.1:%d:%d" % (self.port, CPORT)]
        if init:
            opts.append("--init")
        sp.run(self.name, image, *opts, cmd=["/opt/spike/serve.sh"])
        self.up = wait_for(lambda: sp.exec(self.name, "test", "-f", "/tmp/swarmbox/ready", user="1000").returncode == 0, 30)

    def sh(self, cmd):
        return self.sp.exec(self.name, "sh", "-c", cmd, user="1000").stdout.strip()

    def state(self):
        return self.sp.podman("inspect", "--format", "{{.State.Status}} {{.State.ExitCode}}", self.name).stdout.strip()

    def ttyd_pid(self):
        return self.sh("cat /tmp/swarmbox/ttyd.pid 2>/dev/null")

    def logs(self):
        return self.sp.podman("logs", self.name).stdout


def main():
    sp = sc.Spike("b3")
    image = sc.ensure_spike_image(sp)
    work = sp.mkdtemp("b3")
    with open(os.path.join(work, "serve.sh"), "w") as f:
        f.write(SERVE)
    os.chmod(work, 0o755)
    os.chmod(os.path.join(work, "serve.sh"), 0o755)
    stop_times = {}

    for label, init, web in (("pid1", False, 1), ("init", True, 1), ("web0", False, 0)):
        print("-- case %s (--init=%s, WEB=%d)" % (label, init, web))
        b = Box(sp, image, work, label, init=init, web=web)
        sp.expect("[%s] serve reaches the readiness marker" % label, b.up)
        pid1 = b.sh("tr '\\0' ' ' < /proc/1/cmdline")
        print("  PID 1 is: %s" % pid1)
        if init:
            sp.expect("[init] PID 1 is the init process (podman-init), serve is its child",
                      pid1.startswith("/run/podman-init"), pid1)
        else:
            sp.expect("[%s] PID 1 is serve itself" % label, "serve.sh" in pid1, pid1)
        if web:
            sp.expect("[%s] ttyd answers over the published 127.0.0.1 port" % label, wait_for(lambda: http_ok(b.port), 15))
            old = b.ttyd_pid()
            # (a) ttyd dies on its own: the supervisor restarts it, the box stays up
            b.sh("kill $(cat /tmp/swarmbox/ttyd.pid)")
            new = wait_for(lambda: (b.ttyd_pid() != old and b.ttyd_pid()) or None, 15)
            sp.expect("[%s] ttyd killed -> supervisor starts a new ttyd (pid %s -> %s)" % (label, old, new), bool(new))
            sp.expect("[%s] ... and it answers again" % label, wait_for(lambda: http_ok(b.port), 15))
            sp.expect("[%s] ... and the box is still running" % label, b.state().startswith("running"), b.state())
            # (b) swarmbox-web restart: USR1 to the supervisor
            old = b.ttyd_pid()
            b.sh("kill -USR1 $(cat /tmp/swarmbox/sup.pid)")
            new = wait_for(lambda: (b.ttyd_pid() != old and b.ttyd_pid()) or None, 15)
            sp.expect("[%s] `web restart` (USR1 to the supervisor) gives a new ttyd" % label, bool(new))
            sp.expect("[%s] ... answering, box still running" % label,
                      wait_for(lambda: http_ok(b.port), 15) and b.state().startswith("running"), b.state())
        else:
            alive = b.sh("ls /tmp/swarmbox/ttyd.pid 2>/dev/null; tr '\\0' ' ' < /proc/*/cmdline 2>/dev/null | grep -c 'ttyd -W'")
            sp.expect("[web0] no ttyd and no supervisor started; serve blocks", "ttyd.pid" not in alive, alive)
            sp.expect("[web0] box is up", b.state().startswith("running"), b.state())
        t0 = time.time()
        r = sp.podman("stop", "-t", "10", b.name)
        dt = time.time() - t0
        stop_times[label] = dt
        st = b.state()
        lg = b.logs()
        print("  podman stop took %.2f s; state/exit code: %s; stderr %r" % (dt, st, r.stderr.strip()[:120]))
        print("  log: " + " | ".join(l.split(": ", 1)[-1] for l in lg.splitlines()[-5:]))
        sp.expect("[%s] podman stop (-t 10) ends the box in well under 10 s (took %.2fs)" % (label, dt), dt < 4.0, "%.2f" % dt)
        sp.expect("[%s] the SIGTERM handler ran" % label, "got SIGTERM" in lg)
        sp.expect("[%s] it stopped its children (no ttyd left)" % label, "ttyd gone" in lg and "STILL ALIVE" not in lg)
        sp.expect("[%s] exit status is 143 (the handler's)" % label, st.endswith(" 143"), st)

    print("-- SIGINT (podman kill --signal INT), PID 1 and --init")
    for label, init in (("int-pid1", False), ("int-init", True)):
        b = Box(sp, image, work, label, init=init, web=1)
        sp.expect("[%s] ready" % label, b.up)
        t0 = time.time()
        sp.podman("kill", "--signal", "INT", b.name)
        w = sp.podman("wait", b.name)
        dt = time.time() - t0
        st = b.state()
        lg = b.logs()
        print("  [%s] SIGINT: exited after %.2f s; state/exit code: %s" % (label, dt, st))
        sp.expect("[%s] SIGINT ends the box within 4 s (%.2fs)" % (label, dt), dt < 4.0, "%.2f" % dt)
        sp.expect("[%s] the SIGINT handler ran and ttyd is gone" % label, "got SIGINT" in lg and "ttyd gone" in lg, lg[-300:])
        if init:
            print("  note: under --init the exit code is %s (the init forwards the signal and reports serve's status)" % st)
        else:
            sp.expect("[%s] exit status 130" % label, st.endswith(" 130"), st)

    print("-- crash loop: 5 exits within 60 s (backoff scaled to 0 for speed)")
    b = Box(sp, image, work, "crash", web=1, scale=0)
    sp.expect("[crash] ready", b.up)
    for i in range(7):
        pid = b.ttyd_pid()
        b.sh("kill $(cat /tmp/swarmbox/ttyd.pid) 2>/dev/null")
        wait_for(lambda: b.ttyd_pid() != pid or "keeps crashing" in b.sh("cat /tmp/swarmbox/health 2>/dev/null"), 5, 0.05)
        if "keeps crashing" in b.sh("cat /tmp/swarmbox/health 2>/dev/null"):
            break
    health = b.sh("cat /tmp/swarmbox/health 2>/dev/null")
    sp.expect("[crash] after 5 exits the supervisor stops trying and writes the health line", "keeps crashing" in health, health)
    sp.expect("[crash] the box stays up", b.state().startswith("running"), b.state())
    sp.expect("[crash] the supervisor is still alive after giving up (so `web restart` can reach it)",
              b.sh("kill -0 $(cat /tmp/swarmbox/sup.pid) && echo alive") == "alive")
    old = b.ttyd_pid()
    b.sh("kill -USR1 $(cat /tmp/swarmbox/sup.pid)")
    new = wait_for(lambda: (b.ttyd_pid() != old and b.ttyd_pid()) or None, 10)
    sp.expect("[crash] `web restart` after giving up starts ttyd again and clears the health line",
              bool(new) and wait_for(lambda: http_ok(b.port), 15) and b.sh("cat /tmp/swarmbox/health") == "")
    t0 = time.time()
    sp.podman("stop", "-t", "10", b.name)
    sp.expect("[crash] stop is still quick", time.time() - t0 < 4.0)

    print("-- controls: why the design waits on a background sleep and installs handlers")
    for label, mode in (("fgsleep", "fg-sleep"), ("nohandler", "nohandler")):
        b = Box(sp, image, work, label, web=0, mode=mode)
        sp.expect("[%s] ready" % label, b.up)
        t0 = time.time()
        sp.podman("stop", "-t", "3", b.name)
        dt = time.time() - t0
        st = b.state()
        print("  [%s] podman stop -t 3 took %.2f s; state/exit code %s" % (label, dt, st))
        sp.expect("[%s] control: without the background-sleep wait or without handlers, stop waits for the kill timeout "
                  "and exits 137 (took %.2fs)" % (label, dt), dt >= 2.8 and st.endswith(" 137"), "%.2f %s" % (dt, st))

    ver = sp.podman("run", "--rm", "--name", sp.name("ver"), image, "ttyd", "--version")
    sp.track_container(sp.name("ver"))
    tag = sc.evidence("prototype serve as PID 1 (alone and with --init), real ttyd %s, published 127.0.0.1 port, "
                      "podman stop/kill timing, ttyd killed, USR1 restart, crash loop" % ver.stdout.strip().replace("ttyd version ", ""),
                      image, reduced="the nested Podman service is a sleep, tmux has no clients, and the prototype is a "
                                     "bash stand-in for container/entrypoint.sh serve")
    return sp.finish(tag, "serve works as PID 1; stop times %s s; handlers run with and without --init" % (
        ", ".join("%s %.1f" % (k, v) for k, v in sorted(stop_times.items()))))


if __name__ == "__main__":
    sys.exit(main())
