"""The watcher of the resident service: `swarmbox-sysop serve --log --dock --watch` (what prepare.sh starts) runs the service as a child and starts it again
when it dies, so a kill, an out-of-memory kill or a crash does not leave the box without a sysop until its next start (the bus and the web terminal have
supervisors in the entrypoint; the sysop is an addon, so its supervisor is the addon's own, and the entrypoint knows nothing of it).

  * One watcher per box: an flock on <run>/sysop/watch.lock (the kernel drops it however the process dies). A second one that finds it taken tells the first
    (SIGUSR1: start the service now, forget the earlier crashes) and ends: that is how `swarmbox-addon prepare` makes a service that is down come back at once.
  * What the child's exit means: 0 (a stop by SIGTERM or SIGINT, or "already running": another service holds the lock) ends the watcher, as does a
    child killed by SIGTERM; 2 (a refused setting: it would refuse again) ends it too, with the reason in serve.log; anything else (a kill -9, a crash, a
    failure) is started again after 1, 2, 4 ... 30 s. A run of more than 60 s is not a crash loop: the delay starts again at 1 s.
  * Five abnormal exits within 60 s: the watcher gives up (it says so in serve.log and in the file crashloop of the run folder, which the panel shows),
    and idles, alive, until SIGUSR1 (a second watcher, so `swarmbox-addon prepare` or `swarmbox-sysop serve --log --watch` by hand) or SIGTERM.
  * SIGTERM and SIGINT: the child gets SIGTERM, the watcher ends when it did (SIGKILL after 10 s).
  * The watcher does not touch the multiplexer, the bus or any goal: the service itself marks the goals that a death left in flight as lost when it starts again.
"""
import fcntl
import os
import signal
import subprocess
import sys
import time

BACKOFF = (1.0, 30.0)
CRASHES = (5, 60.0)         # this many abnormal exits within this many seconds: give up
STOP_WAIT = 10.0


class Watcher:
    def __init__(self, paths, argv, log=None, backoff=BACKOFF, crashes=CRASHES, popen=subprocess.Popen, clock=time.monotonic):
        if backoff is BACKOFF and os.environ.get("SWARMBOX_TEST_WATCH_BACKOFF"):
            # tests only ("first,last" seconds): a test that kills the service and starts it again with prepare must not race the watcher's own start
            parts = [float(x) for x in os.environ["SWARMBOX_TEST_WATCH_BACKOFF"].split(",") if x.strip()]
            if parts:
                backoff = (max(0.005, parts[0]), max(0.005, parts[-1]))
        self.paths, self.argv, self.backoff, self.crashes, self.popen, self.clock = paths, argv, backoff, crashes, popen, clock
        self.log = log or self.stderr_log
        self.lock_fd = None
        self.child = None
        self.stop = False
        self.poke = False

    @staticmethod
    def stderr_log(m):
        try:
            print("%s sysop-watch[%d]: %s" % (time.strftime("%Y-%m-%dT%H:%M:%S"), os.getpid(), m), file=sys.stderr, flush=True)
        except (OSError, ValueError):
            pass                      # a full disk must not end the watcher: it is what brings the service back

    # ---- one watcher per box
    def acquire(self):
        """True when this process is the watcher; False when another one is (it has been told to start the service now)."""
        self.paths.make()
        fd = os.open(self.paths.watch_lock, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(fd)
            self.tell_the_other()
            return False
        self.lock_fd = fd
        with open(self.paths.watch_pidfile, "w") as f:
            f.write("%d\n" % os.getpid())
        os.chmod(self.paths.watch_pidfile, 0o600)
        return True

    def tell_the_other(self):
        try:
            with open(self.paths.watch_pidfile) as f:
                pid = int(f.read().strip())
            if pid > 1:
                os.kill(pid, signal.SIGUSR1)
        except (OSError, ValueError):
            pass

    def release(self):
        for p in (self.paths.watch_pidfile, self.paths.crashloop):
            try:
                os.unlink(p)
            except OSError:
                pass
        if self.lock_fd is not None:
            os.close(self.lock_fd)
            self.lock_fd = None

    # ---- signals (the handlers only set flags: the loop acts)
    def on_term(self, *_):
        self.stop = True
        self.signal_child(signal.SIGTERM)

    def on_poke(self, *_):
        self.poke = True

    def signal_child(self, sig):
        c = self.child
        if c is not None and c.poll() is None:
            try:
                c.send_signal(sig)
            except OSError:
                pass

    def nap(self, seconds):
        """sleep up to `seconds`, ending early on a stop or a poke"""
        end = self.clock() + seconds
        while not self.stop and not self.poke and self.clock() < end:
            time.sleep(min(0.2, max(0.0, end - self.clock())))

    # ---- the loop
    def run(self):
        """0 when the watch ended on a clean stop, 2 when the service refused its settings, 1 when it could not run at all."""
        if not self.acquire():
            return 0
        signal.signal(signal.SIGTERM, self.on_term)
        signal.signal(signal.SIGINT, self.on_term)
        signal.signal(signal.SIGUSR1, self.on_poke)
        signal.signal(signal.SIGHUP, signal.SIG_IGN)
        try:
            return self.loop()
        finally:
            self.release()

    def loop(self):
        delay, exits = self.backoff[0], []
        while not self.stop:
            self.poke = False
            began = self.clock()
            try:
                self.child = self.popen(self.argv)
            except OSError as e:
                self.log("cannot start the service (%s): %s" % (self.argv[0], e.strerror or e))
                return 1
            rc = self.wait_child()
            self.child = None
            if self.stop:
                break
            if rc == 0 or rc == -signal.SIGTERM:
                self.log("the service ended by itself (status %s): not starting it again" % rc)
                return 0
            if rc == 2:
                self.log("the service refused its settings (status 2; the reason is in serve.log above): not starting it again")
                return 2
            now = self.clock()
            if self.poke:
                delay, exits = self.backoff[0], []
            if now - began > self.crashes[1]:
                delay = self.backoff[0]
            exits = [x for x in exits if now - x < self.crashes[1]] + [now]
            what = "killed by signal %d" % -rc if rc < 0 else "status %s" % rc
            if len(exits) >= self.crashes[0]:
                self.log("the service ended abnormally %d times within %d s (last: %s): giving up until `swarmbox-addon prepare` or `swarmbox-sysop serve --log --watch` is run"
                         % (len(exits), self.crashes[1], what))
                self.write_crashloop(what)
                while not self.stop and not self.poke:
                    self.nap(3600)
                exits, delay = [], self.backoff[0]
                self.clear_crashloop()
                continue
            self.log("the service ended abnormally (%s): starting it again in %g s" % (what, delay))
            if not self.poke:
                self.nap(delay)
            delay = min(self.backoff[1], delay * 2)
        return 0

    def wait_child(self):
        """the exit status of the child; on a stop, TERM was sent by the handler and KILL follows after STOP_WAIT"""
        c = self.child
        stopped_at = None
        while True:
            try:
                return c.wait(timeout=0.2)
            except subprocess.TimeoutExpired:
                pass
            if self.stop:
                if stopped_at is None:
                    stopped_at = self.clock()
                    self.signal_child(signal.SIGTERM)       # again: the handler may have run before the child existed
                elif self.clock() - stopped_at > STOP_WAIT:
                    self.signal_child(signal.SIGKILL)

    def write_crashloop(self, what):
        try:
            with open(self.paths.crashloop, "w") as f:
                f.write("the sysop service keeps crashing (%s); see serve.log\n" % what)
        except OSError:
            pass

    def clear_crashloop(self):
        try:
            os.unlink(self.paths.crashloop)
        except OSError:
            pass
