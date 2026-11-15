#!/usr/bin/python3
"""Tests and measurements of the bus PoC. No tmux. Run: python3 test_bus.py   (prints PASS/FAIL lines and measurements)"""
import json, os, signal, socket, statistics, subprocess, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
BUS = os.path.join(HERE, "swarmbox-bus")
RUN = tempfile.mkdtemp(prefix="sbbus.")
SOCK = os.path.join(RUN, "bus.sock")
ENV = dict(os.environ, SB_BUS_SOCKET=SOCK)
fails = 0


def check(name, cond, extra=""):
    global fails
    fails += not cond
    print(("PASS " if cond else "FAIL ") + name + (" " + str(extra) if extra != "" else ""), flush=True)


def cli(*a, inp=None, timeout=10):
    return subprocess.run([BUS, *a], env=ENV, input=inp, capture_output=True, text=True, timeout=timeout)


def broker():
    p = subprocess.Popen([BUS, "serve", "--stub"], env=ENV, stderr=subprocess.PIPE, text=True)
    for _ in range(100):
        c = socket.socket(socket.AF_UNIX)
        try:
            c.connect(SOCK)
            c.close()
            return p
        except OSError:
            pass
        if p.poll() is not None:
            return p
        time.sleep(0.02)
    return p


def sub(*a):
    p = subprocess.Popen([BUS, "sub", *a], env=dict(ENV, SB_BUS_VERBOSE="1"), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    p.stderr.readline()            # "subscribed" line: registered at the broker
    return p


def lines(p, n, t=3):
    """take up to n lines from p.stdout, waiting at most t seconds (a reader thread per process, so buffering cannot hide lines)"""
    import queue, threading
    if not hasattr(p, "_q"):
        p._q = queue.Queue()
        def pump():
            for l in p.stdout:
                p._q.put(l)
        threading.Thread(target=pump, daemon=True).start()
    out = []
    end = time.time() + t
    while len(out) < n and time.time() < end:
        try:
            out.append(p._q.get(timeout=0.05))
        except queue.Empty:
            pass
    return out


b = broker()
try:
    # --- socket permissions
    check("socket mode 0600", oct(os.stat(SOCK).st_mode & 0o777) == "0o600", oct(os.stat(SOCK).st_mode & 0o777))

    # --- no subscriber
    r = cli("pub", "goal", "x")
    check("pub goal with no subscriber: exit 3, nothing buffered", r.returncode == 3 and "no_subscriber" in r.stderr, r.returncode)
    s1 = sub("goal")
    check("late subscriber gets nothing of the past", lines(s1, 1, 0.4) == [])
    r = cli("pub", "goal", '{"text":"run the tests"}', "--source", "x") if False else cli("pub", "--source", "voice", "goal", '{"text":"run the tests"}')
    m = json.loads(lines(s1, 1)[0])
    check("envelope fields", r.returncode == 0 and m["v"] == 1 and m["topic"] == "goal" and m["source"] == "voice" and m["body"] == {"text": "run the tests"} and m["id"] and m["time"].endswith("Z") and m["peer"]["uid"] == os.getuid(), m)
    cli("pub", "goal", "plain words")
    check("plain text body", json.loads(lines(s1, 1)[0])["body"] == "plain words")
    r = cli("pub", "goal", inp="from stdin\n")
    check("body from stdin", json.loads(lines(s1, 1)[0])["body"] == "from stdin")

    # --- queue: two subscribers, fairness
    s2 = sub("goal")
    for i in range(10):
        cli("pub", "goal", str(i))
    time.sleep(0.5); n1, n2 = len(lines(s1, 10, 0.3)), len(lines(s2, 10, 0.3))
    check("two subscribers: each message to exactly one, round robin", n1 + n2 == 10 and n1 == 5 and n2 == 5, (n1, n2))

    # --- subscriber dies after receiving: the message is lost; the next pub goes to the other
    s1.kill(); s1.wait()
    time.sleep(0.1)
    r = cli("pub", "goal", "after-death")
    check("dead subscriber is removed at once; the other gets it", r.returncode == 0 and len(lines(s2, 1)) == 1)
    s2.kill(); s2.wait(); time.sleep(0.1)
    r = cli("pub", "goal", "nobody")
    check("all subscribers dead: exit 3", r.returncode == 3)

    # --- kill -9 right after pub (race): the broker wrote into the socket, the process is gone; message is lost, pub said ok
    s3 = sub("goal")
    r = cli("pub", "goal", "lost-in-flight")
    s3.kill(); s3.wait()          # never read it
    check("pub ok but subscriber killed before reading: lost silently (no ack)", r.returncode == 0)
    time.sleep(0.1)
    check("... and the next pub fails at once", cli("pub", "goal", "x").returncode == 3)

    # --- tab delivery via the driver callback, state reads, bad input
    check("pub tab/main/in", cli("pub", "tab/main/in", '{"run":"ls"}').returncode == 0)
    r = cli("pub", "tab/nope/in", "x")
    check("pub to a missing tab fails with the driver's error", r.returncode == 1 and "no_such_tab" in r.stderr, r.stderr.strip())
    check("bad topic exit 6", cli("pub", "foo", "x").returncode == 6)
    check("ls tab/", json.loads(cli("ls", "tab/").stdout)[0]["tab"] == "main")
    check("get tab/main/screen", "screen of main" in json.loads(cli("get", "tab/main/screen").stdout)["text"])
    check("get unknown exit 6", cli("get", "tab/zzz/screen").returncode == 6)

    # --- watch, with and without screen contents
    w1 = subprocess.Popen([BUS, "watch"], env=dict(ENV, SB_BUS_VERBOSE="1"), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True); w1.stderr.readline()
    w2 = subprocess.Popen([BUS, "watch", "--no-screen"], env=dict(ENV, SB_BUS_VERBOSE="1"), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True); w2.stderr.readline()
    cli("pub", "goal", "unseen")                       # fails (no subscriber) but is still watched
    cli("get", "tab/main/screen")
    a = [json.loads(x) for x in lines(w1, 2)]
    c = [json.loads(x) for x in lines(w2, 2)]
    check("watch sees a failed pub and a read", a[0]["kind"] == "pub" and a[0]["result"] == "no_subscriber" and a[1]["kind"] == "read" and len(a[1]["result"]["text"]) > 1000)
    check("watch --no-screen omits the screen", c[1]["result"]["text"].startswith("<") and "omitted" in c[1]["result"]["text"], c[1]["result"]["text"])
    w1.kill(); w2.kill()

    # --- a client that connects and dies / connects and sends nothing / sends garbage
    x = socket.socket(socket.AF_UNIX); x.connect(SOCK); x.close()
    x = socket.socket(socket.AF_UNIX); x.connect(SOCK); x.sendall(b"not json\n"); check("garbage gets bad_request", b"bad_request" in x.recv(100)); x.close()
    x = socket.socket(socket.AF_UNIX); x.connect(SOCK); x.sendall(b'{"op":"pub","topic":"goal"'); x.close()   # half a line then death
    check("broker survives dying/garbage clients", cli("ls", "tab/").returncode == 0 and b.poll() is None)

    # --- message larger than the pipe buffer, and over the limit
    s4 = sub("goal")
    big = "y" * (900 * 1024)
    r = cli("pub", "goal", inp=big)   # argv is limited to 128 KiB per argument (MAX_ARG_STRLEN): big bodies go by stdin
    got = lines(s4, 1, 5)
    check("900 KiB message (pipe buffer is 64 KiB) arrives whole", r.returncode == 0 and len(got) == 1 and len(json.loads(got[0])["body"]) == len(big))
    r = cli("pub", "goal", inp="z" * (2 << 20))
    check("2 MiB message: exit 5, client-side", r.returncode == 5)
    x = socket.socket(socket.AF_UNIX); x.connect(SOCK)
    try:
        x.sendall(b'{"op":"pub","topic":"goal","body":"' + b"z" * (3 << 20) + b'"}\n')
    except OSError:
        pass
    try:
        rep = x.recv(100)
    except OSError:
        rep = b""
    check("3 MiB raw to the broker: too_large and the broker lives", (b"too_large" in rep or rep == b"") and cli("ls", "tab/").returncode == 0, rep)
    x.close(); s4.kill(); s4.wait(); time.sleep(0.2)

    # --- slow subscriber: never reads; broker must not block or grow without bound
    slow = socket.socket(socket.AF_UNIX); slow.connect(SOCK); slow.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4096)
    slow.sendall(b'{"op":"sub","topic":"goal"}\n'); time.sleep(0.2)
    chunk = "q" * (500 * 1024)
    t0 = time.time(); rcs = []
    for i in range(30):
        rcs.append(cli("pub", "goal", inp=chunk).returncode)
    dt = time.time() - t0
    check("slow subscriber: pubs never block (30 x 500 KiB in %.1fs); flips to busy (exit 7) once its buffer is over 4 MiB" % dt, 7 in rcs and dt < 15 and b.poll() is None, sorted(set(rcs)))
    healthy = sub("goal")
    check("a healthy subscriber next to a slow one still gets messages", cli("pub", "goal", "ok-now").returncode == 0 and len(lines(healthy, 1)) == 1)
    slow.close(); healthy.kill(); healthy.wait(); time.sleep(0.2)

    # --- 100 messages per second for 3 s through the CLI (a process per message), one subscriber
    s5 = sub("goal")
    t0 = time.time(); sent = 0; pubs = []
    while sent < 300:
        due = t0 + sent / 100.0
        if time.time() < due:
            time.sleep(due - time.time())
        pubs.append(subprocess.Popen([BUS, "pub", "goal", str(sent)], env=ENV, stdout=subprocess.DEVNULL))
        sent += 1
    bad = [p for p in pubs if p.wait() != 0]
    got = lines(s5, 300, 3)
    check("100 msg/s x 3 s (CLI process each): all 300 delivered", len(got) == 300, len(got))
    s5.kill(); s5.wait(); time.sleep(0.2)   # the broker learns of a death a moment after it (see the report: the window)

    # --- latency pub -> sub (persistent connections, no process start) and CLI cost
    s6 = socket.socket(socket.AF_UNIX); s6.connect(SOCK); s6.sendall(b'{"op":"sub","topic":"goal"}\n'); s6.recv(100)
    lat = []
    for i in range(300):
        p = socket.socket(socket.AF_UNIX); p.connect(SOCK)
        t = time.perf_counter(); p.sendall(b'{"op":"pub","topic":"goal","body":1}\n'); s6.recv(4096); lat.append((time.perf_counter() - t) * 1000); p.recv(100); p.close()
    lat.sort()
    print("MEASURE pub->sub latency, persistent sockets (ms): median %.3f p99 %.3f max %.3f" % (statistics.median(lat), lat[int(len(lat) * .99)], lat[-1]))
    s6.close(); time.sleep(0.2)
    s7 = sub("goal")
    cl = []
    for i in range(50):
        t = time.perf_counter(); cli("pub", "goal", "m"); cl.append((time.perf_counter() - t) * 1000)
    cl.sort(); lines(s7, 50, 3); s7.kill(); s7.wait(); time.sleep(0.2)
    print("MEASURE `swarmbox-bus pub` process start to exit (ms): median %.1f p95 %.1f" % (statistics.median(cl), cl[int(len(cl) * .95)]))
    t = time.perf_counter()
    for i in range(30): subprocess.run(["python3", "-c", "pass"])
    print("MEASURE python3 -c pass (ms): %.1f" % ((time.perf_counter() - t) / 30 * 1000))
    t = time.perf_counter()
    for i in range(30): subprocess.run(["python3", "-c", "import asyncio"])
    print("MEASURE python3 import asyncio (ms): %.1f" % ((time.perf_counter() - t) / 30 * 1000))
    check("CLI median under 50 ms", statistics.median(cl) < 50)

    # --- the window: a subscriber is killed -9 and a pub follows at once (how many are lost, how many fail)
    ok_lost = failed = 0
    for i in range(40):
        sa = sub("goal"); sb = sub("goal")
        sa.kill()                           # no wait: the broker has not looked at the socket yet
        r = cli("pub", "goal", "w")
        got = lines(sb, 1, 0.15)
        if r.returncode == 0 and not got: ok_lost += 1
        sa.wait(); sb.kill(); sb.wait(); time.sleep(0.05)
    print("MEASURE kill -9 of 1 of 2 subscribers then pub at once, 40 trials: %d pubs reported ok but the message was lost" % ok_lost)

    # --- two brokers at once, stale socket after a crash
    r = subprocess.run([BUS, "serve", "--stub"], env=ENV, capture_output=True, text=True, timeout=5)
    check("second broker refuses: exit 8, first untouched", r.returncode == 8 and cli("ls", "tab/").returncode == 0)
    racers = [subprocess.Popen([BUS, "serve", "--stub"], env=dict(ENV, SB_BUS_SOCKET=SOCK + "2"), stderr=subprocess.DEVNULL) for _ in range(5)]
    time.sleep(1.5)
    alive = [p for p in racers if p.poll() is None]
    check("5 brokers started at once on a fresh path: exactly one survives", len(alive) == 1, len(alive))
    for p in alive: p.terminate()
    b.send_signal(signal.SIGKILL); b.wait()
    check("after kill -9 the stale socket file remains", os.path.exists(SOCK))
    check("client on a stale socket: exit 4 (not running)", cli("pub", "goal", "x").returncode == 4)
    b = broker()
    check("new broker replaces the stale socket and works", b.poll() is None and cli("ls", "tab/").returncode == 0)
    s8 = sub("goal")
    b.send_signal(signal.SIGTERM); b.wait()
    check("SIGTERM removes the socket; subscribers see the close (exit 4)", not os.path.exists(SOCK) and s8.wait(timeout=3) == 4, s8.returncode)
    # a different uid cannot connect: only testable as root (socket is 0600); documented
finally:
    if b.poll() is None:
        b.kill()
print("FAILURES: %d" % fails)
sys.exit(1 if fails else 0)
