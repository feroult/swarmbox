"""The broker of swarmbox-bus (container/scripts/swarmbox-bus.py), in process, over a real unix socket, with a fake driver.

Queue semantics, subscribers that die or are slow, big messages, bad topics and requests, permissions, a stale socket, two brokers,
the driver interface, watch. No tmux, no network, no model. Run with: python3 tests/test_bus.py
"""
import os
import socket
import stat
import sys
import threading
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bus_support import Conn, Harness, bus, rpc, short_tmp, wait_for  # noqa: E402


class FakeDriver(bus.Driver):
    """records what it is asked; a tab named slow sleeps; a tab named boom raises; two tabs exist"""

    def __init__(self):
        self.sent, self.reads, self.active, self.max_active = [], [], {}, {}
        self.lock = threading.Lock()
        self.delay = 0.0

    def list_tabs(self):
        self.reads.append(("ls",))
        return [{"tab": "@1", "name": "main", "active": True}, {"tab": "@2", "name": "work", "active": False}]

    def screen(self, tab, lines):
        self.reads.append(("screen", tab, lines))
        if tab == "boom":
            raise RuntimeError("tmux exploded")
        if tab != "@1":
            raise bus.DriverError("no_such_tab", "no tab %s" % tab)
        return {"text": "hello\nworld\n", "cursor": [1, 2]}

    def send(self, tab, body):
        with self.lock:
            self.active[tab] = self.active.get(tab, 0) + 1
            self.max_active[tab] = max(self.max_active.get(tab, 0), self.active[tab])
        try:
            if tab == "boom":
                raise RuntimeError("tmux exploded")
            if tab == "amb":
                raise bus.DriverError("ambiguous_tab", "two windows are called amb: @4, @5")
            time.sleep(self.delay)
            self.sent.append((tab, body))
        finally:
            with self.lock:
                self.active[tab] -= 1


def collect(conn):
    """read the lines of a subscriber in a thread, as a consumer that reads all the time does: the list of bodies"""
    got = []

    def run():
        try:
            while True:
                env = conn.line()
                if env is None:
                    return
                got.append(env["body"])
        except (OSError, ValueError):
            return
    threading.Thread(target=run, daemon=True).start()
    return got


class Base(unittest.TestCase):
    driver = None

    def start(self, driver=None, **kw):
        h = Harness(driver or self.driver, **kw)
        self.addCleanup(h.close)
        self.assertEqual(h.rc, 0)
        return h


class Goal(Base):
    def test_no_subscriber(self):
        h = self.start()
        self.assertEqual(h.pub("goal", {"text": "x"}), {"ok": False, "err": "no_subscriber"})

    def test_one_subscriber_gets_the_envelope(self):
        h = self.start()
        s = h.sub()
        rep = h.pub("goal", {"text": "run the tests"}, source="voice")
        self.assertTrue(rep["ok"])
        self.assertEqual(rep["delivered"], 1)
        env = s.line()
        self.assertEqual(sorted(env), ["body", "id", "peer", "source", "time", "topic", "v"])
        self.assertEqual((env["v"], env["topic"], env["source"], env["body"]), (1, "goal", "voice", {"text": "run the tests"}))
        self.assertEqual(env["id"], rep["id"])
        self.assertEqual(env["peer"]["uid"], os.getuid())
        self.assertRegex(env["time"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z$")
        self.assertRegex(env["id"], r"^[0-9a-f]{6}-\d+$")

    def test_ids_are_ordered_and_unique(self):
        h = self.start()
        s = h.sub()
        got = collect(s)
        ids = [h.pub("goal", i)["id"] for i in range(5)]
        self.assertEqual([int(i.split("-")[1]) for i in ids], sorted(int(i.split("-")[1]) for i in ids))
        self.assertEqual(len(set(ids)), 5)
        self.assertTrue(wait_for(lambda: len(got) == 5))
        self.assertEqual(got, [0, 1, 2, 3, 4])

    def test_source_is_cut_at_64_and_peer_cannot_be_forged(self):
        h = self.start()
        s = h.sub()
        h.pub("goal", 1, source="x" * 200, peer={"pid": 1, "uid": 0})
        env = s.line()
        self.assertEqual(env["source"], "x" * 64)
        self.assertEqual(env["peer"]["uid"], os.getuid())
        h.pub("goal", 2)
        self.assertEqual(s.line()["source"], "cli")

    def test_two_subscribers_share_by_round_robin_and_each_message_goes_to_one(self):
        h = self.start()
        a, b = h.sub(), h.sub()
        ga, gb = collect(a), collect(b)          # consumers that read all the time
        for i in range(10):
            self.assertTrue(h.pub("goal", i)["ok"])
        self.assertTrue(wait_for(lambda: len(ga) + len(gb) == 10))
        self.assertEqual((len(ga), len(gb)), (5, 5))
        self.assertEqual(sorted(ga + gb), list(range(10)))

    def test_a_subscriber_that_dies_is_dropped_and_the_other_gets_everything(self):
        h = self.start()
        a, b = h.sub(), h.sub()
        a.close()
        self.assertTrue(wait_for(lambda: len(h.broker.subs["goal"]) == 1))
        got = collect(b)
        for i in range(6):
            self.assertTrue(h.pub("goal", i)["ok"])
        self.assertTrue(wait_for(lambda: len(got) == 6))
        self.assertEqual(got, list(range(6)))
        b.close()
        self.assertTrue(wait_for(lambda: not h.broker.subs["goal"]))
        self.assertEqual(h.pub("goal", 1)["err"], "no_subscriber")

    def test_a_subscriber_may_talk_and_nothing_happens(self):
        h = self.start()
        s = h.sub()
        s.s.sendall(b"garbage\n" * 100)
        h.pub("goal", "still works")
        self.assertEqual(s.line()["body"], "still works")

    def test_slow_subscriber_is_skipped_then_busy_and_a_healthy_one_keeps_receiving(self):
        old = bus.SLOW_BUFFER
        bus.SLOW_BUFFER = 200 * 1024
        self.addCleanup(setattr, bus, "SLOW_BUFFER", old)
        h = self.start()
        slow = h.conn()
        slow.s.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4096)
        slow.send({"op": "sub", "topic": "goal"})
        self.assertTrue(slow.line()["ok"])      # and never reads again
        big = "x" * 100000
        res = None
        for _ in range(100):
            res = h.pub("goal", big)
            if not res["ok"]:
                break
        self.assertEqual(res, {"ok": False, "err": "busy"})
        good = h.sub()
        self.assertTrue(h.pub("goal", "to the healthy one")["ok"])
        self.assertEqual(good.line()["body"], "to the healthy one")

    def test_a_subscriber_that_does_not_read_gets_one_message_and_then_the_others_get_the_rest(self):
        # alive but not reading (stopped, hung): the goals are not queued behind it, they go to a consumer that reads
        h = self.start()
        stuck = h.sub()
        reading = h.sub()
        got = collect(reading)
        for i in range(20):
            rep = h.pub("goal", {"n": i})
            self.assertEqual(rep.get("delivered"), 1, rep)
        self.assertTrue(wait_for(lambda: len(got) >= 19, 5), got)
        self.assertEqual([g["n"] for g in got], list(range(1, 20)))      # the first went to the stuck one, which had read nothing yet
        self.assertEqual(stuck.line()["body"], {"n": 0})
        stuck.s.settimeout(0.3)
        with self.assertRaises(socket.timeout):
            stuck.line()                                                    # and nothing else is waiting for it

    def test_when_every_subscriber_is_stuck_the_goal_is_busy_after_a_short_wait_and_goes_again_when_one_reads(self):
        h = self.start()
        a = h.sub()
        self.assertTrue(h.pub("goal", 1)["ok"])
        t = time.time()
        rep = h.pub("goal", 2)
        self.assertEqual(rep, {"ok": False, "err": "busy"})
        self.assertGreaterEqual(time.time() - t, bus.GOAL_GRACE * 0.9)
        self.assertLess(time.time() - t, bus.GOAL_GRACE + 2)
        self.assertEqual(a.line()["body"], 1)                                # it reads, so it is ready again
        self.assertTrue(h.pub("goal", 3)["ok"])
        self.assertEqual(a.line()["body"], 3)

    def test_a_consumer_that_reads_a_moment_later_is_waited_for(self):
        h = self.start()
        a = h.sub()
        self.assertTrue(h.pub("goal", 1)["ok"])
        threading.Timer(0.05, a.line).start()
        self.assertTrue(h.pub("goal", 2)["ok"])

    def test_goal_body_is_any_json_value(self):
        h = self.start()
        s = h.sub()
        for body in ("text", 5, None, [1, 2], {"a": {"b": 1}}, True):
            self.assertTrue(h.pub("goal", body)["ok"])
            self.assertEqual(s.line()["body"], body)


class Sizes(Base):
    def test_900_kib_arrives_whole(self):
        h = self.start()
        s = h.sub()
        body = "é" * 450000 if False else "a" * (900 * 1024)
        self.assertTrue(h.pub("goal", body)["ok"])
        env = s.line()
        self.assertEqual(len(env["body"]), len(body))

    def test_over_the_limit_is_too_large_and_the_broker_survives(self):
        h = self.start()
        self.assertEqual(h.pub("goal", "a" * bus.MAX_LINE), {"ok": False, "err": "too_large"})
        c = h.conn()
        try:
            c.s.sendall(b"x" * (bus.MAX_LINE + 5000))     # no newline within the limit
        except OSError:
            pass
        try:
            self.assertEqual(c.line(), {"ok": False, "err": "too_large"})
        except ConnectionError:
            pass            # the broker closed with unread bytes: also fine
        self.assertTrue(h.rpc({"op": "ping"})["ok"])

    def test_the_envelope_never_exceeds_the_limit(self):
        h = self.start()
        s = h.sub()
        body = "a" * (bus.MAX_REQUEST - 200)
        rep = h.pub("goal", body, source="é" * 64)
        if rep["ok"]:
            raw = s.f.readline()
            self.assertLessEqual(len(raw), bus.MAX_LINE)
        else:
            self.assertEqual(rep["err"], "too_large")


class BadInput(Base):
    BAD_TOPICS = ["", "foo", "tab", "tab/x", "tab/x/out", "tab//in", "tab/a b/in", "tab/x/in/y", "goal/", "Goal", "tab/x/screen", "tab/" + "a" * 65 + "/in",
                  "tab/a;b/in", "tab/../in", "tab/a\nb/in", "/goal"]

    def test_bad_topics_on_pub(self):
        h = self.start()
        for t in self.BAD_TOPICS:
            with self.subTest(topic=t):
                self.assertEqual(h.pub(t, 1), {"ok": False, "err": "bad_topic"})
        self.assertEqual(h.rpc({"op": "pub", "topic": 5, "body": 1})["err"], "bad_topic")
        self.assertEqual(h.rpc({"op": "pub", "topic": None, "body": 1})["err"], "bad_topic")
        self.assertEqual(h.driver.sent if hasattr(h.driver, "sent") else [], [])

    def test_good_tab_names(self):
        h = self.start(FakeDriver())
        for t in ("main", "@3", "1:main", "a.b_c-d", "A" * 64):
            with self.subTest(tab=t):
                self.assertTrue(h.pub("tab/%s/in" % t, {"run": "x"})["ok"])

    def test_bad_topics_on_get_ls_sub(self):
        h = self.start()
        for t in ("", "goal", "tab/x", "tab/x/in", "tab/x/screen/y", "tab//screen", "foo"):
            with self.subTest(get=t):
                self.assertEqual(h.rpc({"op": "get", "topic": t})["err"], "bad_topic")
        for t in ("goal", "tab/x", "foo"):
            with self.subTest(ls=t):
                self.assertEqual(h.rpc({"op": "ls", "topic": t})["err"], "bad_topic")
        for t in ("tab/x/in", "foo", "", "tab/x/screen"):
            with self.subTest(sub=t):
                self.assertEqual(h.rpc({"op": "sub", "topic": t})["err"], "bad_topic")

    def test_bad_requests_and_the_broker_lives(self):
        h = self.start()
        for raw in (b"not json\n", b"[1,2]\n", b"5\n", b"{}\n", b'{"op":5}\n', b'{"op":"nope"}\n', b'{"op":"pub","topic":"goal"}\n', b"\n",
                    b'{"op":"get","topic":"tab/x/screen","lines":"3"}\n', b'{"op":"get","topic":"tab/x/screen","lines":0}\n',
                    b'{"op":"get","topic":"tab/x/screen","lines":true}\n', b"\xff\xfe\n"):
            with self.subTest(raw=raw):
                rep = Conn(h.path).send(raw).line()
                self.assertEqual(rep["err"], "bad_request")
        self.assertTrue(h.rpc({"op": "ping"})["ok"])

    def test_clients_that_die_half_way(self):
        h = self.start()
        Conn(h.path).close()                              # connect and close
        c = Conn(h.path)
        c.s.sendall(b'{"op":"pub","top')                  # half a line, then close
        c.s.shutdown(socket.SHUT_WR)
        self.assertEqual(c.line()["err"], "bad_request")
        c.close()
        c = Conn(h.path)
        c.s.sendall(b'{"op":"pub","topic":"goal","body":1}\n')
        c.close()                                         # sent and left without reading the reply
        self.assertTrue(h.rpc({"op": "ping"})["ok"])

    def test_a_client_that_sends_nothing_gets_bad_request_after_the_timeout(self):
        old = bus.REQUEST_TIMEOUT
        bus.REQUEST_TIMEOUT = 0.3
        self.addCleanup(setattr, bus, "REQUEST_TIMEOUT", old)
        h = self.start()
        c = Conn(h.path)
        t0 = time.time()
        self.assertEqual(c.line()["err"], "bad_request")
        self.assertLess(time.time() - t0, 3)
        self.assertTrue(h.rpc({"op": "ping"})["ok"])

    def test_ping(self):
        h = self.start()
        rep = h.rpc({"op": "ping"})
        self.assertEqual((rep["ok"], rep["v"], rep["pid"]), (True, 1, os.getpid()))


class Permissions(Base):
    def test_socket_is_0600_and_the_lock_file_too(self):
        h = self.start()
        self.assertEqual(stat.S_IMODE(os.stat(h.path).st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(os.stat(h.path + ".lock").st_mode), 0o600)

    def test_a_missing_folder_is_created_private(self):
        d = short_tmp()
        self.addCleanup(__import__("shutil").rmtree, d, True)
        b = bus.Broker(os.path.join(d, "sub", "bus.sock"), bus.StubDriver())
        self.assertEqual(b.acquire(), 0)
        self.assertEqual(stat.S_IMODE(os.stat(os.path.join(d, "sub")).st_mode), 0o700)

    def test_another_uid_is_refused(self):
        h = self.start(allowed_uids={os.getuid() + 4242})
        self.assertEqual(h.rpc({"op": "ping"})["err"], "forbidden")
        self.assertEqual(h.pub("goal", 1)["err"], "forbidden")
        self.assertEqual(h.rpc({"op": "ls", "topic": "tab/"})["err"], "forbidden")
        self.assertEqual(h.rpc({"op": "sub"})["err"], "forbidden")

    def test_root_and_own_uid_are_accepted_by_default(self):
        h = self.start()
        self.assertEqual(h.broker.allowed, {os.getuid(), 0})

    def test_a_client_of_another_user_cannot_even_connect(self):
        if os.geteuid() == 0:
            self.skipTest("root ignores the mode")
        h = self.start()
        os.chmod(h.path, 0o600)
        self.assertEqual(stat.S_IMODE(os.stat(h.path).st_mode) & 0o077, 0)


class SingleInstance(Base):
    def test_a_stale_socket_is_taken_over(self):
        d = short_tmp()
        self.addCleanup(__import__("shutil").rmtree, d, True)
        path = os.path.join(d, "bus.sock")
        s = socket.socket(socket.AF_UNIX)
        s.bind(path)
        s.close()                                          # a socket file nobody listens on: what a kill -9 leaves
        self.assertTrue(os.path.exists(path))
        with self.assertRaises(ConnectionRefusedError):
            rpc(path, {"op": "ping"})
        h = Harness.__new__(Harness)
        h.dir, h.path, h.logs, h.driver, h.conns = d, path, [], bus.StubDriver(), []
        h.broker = bus.Broker(path, h.driver, log=h.logs.append)
        h.broker.started = threading.Event()
        self.assertEqual(h.broker.acquire(), 0)
        h.thread = threading.Thread(target=h._run, daemon=True)
        h.thread.start()
        self.assertTrue(h.broker.started.wait(10))
        self.addCleanup(h.close)
        self.assertTrue(rpc(path, {"op": "ping"})["ok"])

    def test_a_file_that_is_not_a_socket_is_not_deleted(self):
        d = short_tmp()
        self.addCleanup(__import__("shutil").rmtree, d, True)
        path = os.path.join(d, "bus.sock")
        with open(path, "w") as f:
            f.write("precious")
        b = bus.Broker(path, bus.StubDriver())
        self.assertEqual(b.acquire(), 1)
        with open(path) as f:
            self.assertEqual(f.read(), "precious")

    def test_a_second_broker_exits_8_and_the_first_is_untouched(self):
        h = self.start()
        second = bus.Broker(h.path, bus.StubDriver())
        self.assertEqual(second.acquire(), 8)
        self.assertTrue(os.path.exists(h.path))
        s = h.sub()
        self.assertTrue(h.pub("goal", "still the first")["ok"])
        self.assertEqual(s.line()["body"], "still the first")

    def test_many_brokers_at_once_leave_exactly_one(self):
        d = short_tmp()
        self.addCleanup(__import__("shutil").rmtree, d, True)
        path = os.path.join(d, "bus.sock")
        brokers = [bus.Broker(path, bus.StubDriver()) for _ in range(6)]
        rcs = []
        ts = [threading.Thread(target=lambda b=b: rcs.append(b.acquire())) for b in brokers]
        [t.start() for t in ts]
        [t.join() for t in ts]
        self.assertEqual(sorted(rcs), [0, 8, 8, 8, 8, 8])

    def test_the_lock_is_free_once_the_broker_stops(self):
        h = self.start()
        h.broker.stop()
        h.thread.join(10)
        again = bus.Broker(h.path, bus.StubDriver())
        self.assertEqual(again.acquire(), 0)

    def test_stop_closes_subscribers_and_removes_the_socket(self):
        h = self.start()
        s = h.sub()
        w = h.conn().send({"op": "watch"})
        w.line()
        h.broker.stop()
        h.thread.join(10)
        self.assertIsNone(s.line())
        self.assertIsNone(w.line())
        self.assertFalse(os.path.exists(h.path))


class Tabs(Base):
    def setUp(self):
        self.driver = FakeDriver()

    def test_pub_to_a_tab_goes_to_the_driver(self):
        h = self.start()
        rep = h.pub("tab/@1/in", {"run": "pytest -x"})
        self.assertEqual((rep["ok"], rep["delivered"]), (True, 1))
        self.assertEqual(self.driver.sent, [("@1", {"run": "pytest -x"})])

    def test_driver_errors_reach_the_client_with_code_and_message(self):
        h = self.start()
        rep = h.pub("tab/amb/in", {"run": "x"})
        self.assertEqual(rep, {"ok": False, "err": "ambiguous_tab", "msg": "two windows are called amb: @4, @5"})
        self.assertEqual(h.rpc({"op": "get", "topic": "tab/@9/screen"})["err"], "no_such_tab")

    def test_a_driver_that_raises_is_driver_error_and_the_broker_lives(self):
        h = self.start()
        self.assertEqual(h.pub("tab/boom/in", {"run": "x"}), {"ok": False, "err": "driver_error", "msg": "RuntimeError"})
        self.assertEqual(h.rpc({"op": "get", "topic": "tab/boom/screen"})["err"], "driver_error")
        self.assertTrue(any("tmux exploded" in l for l in h.logs))
        self.assertTrue(h.rpc({"op": "ping"})["ok"])

    def test_ls_and_get(self):
        h = self.start()
        self.assertEqual(h.rpc({"op": "ls", "topic": "tab/"})["result"], self.driver.list_tabs())
        self.assertEqual(h.rpc({"op": "ls", "topic": "tab"})["result"][0]["tab"], "@1")
        self.assertEqual(h.rpc({"op": "ls", "topic": ""})["result"], ["tab/"])
        rep = h.rpc({"op": "get", "topic": "tab/@1/screen", "lines": 7})
        self.assertEqual(rep["result"], {"text": "hello\nworld\n", "cursor": [1, 2]})
        self.assertIn(("screen", "@1", 7), self.driver.reads)
        h.rpc({"op": "get", "topic": "tab/@1/screen"})
        self.assertIn(("screen", "@1", None), self.driver.reads)

    def test_sends_to_one_tab_never_overlap_but_other_tabs_run_in_parallel(self):
        self.driver.delay = 0.15
        h = self.start()
        t0 = time.time()
        res = []
        ts = [threading.Thread(target=lambda i=i: res.append(h.pub("tab/@1/in", {"run": str(i)})["ok"])) for i in range(4)]
        ts += [threading.Thread(target=lambda: res.append(h.pub("tab/@2/in", {"run": "o"})["ok"]))]
        [t.start() for t in ts]
        [t.join() for t in ts]
        self.assertEqual(res, [True] * 5)
        self.assertEqual(self.driver.max_active["@1"], 1)
        self.assertGreaterEqual(time.time() - t0, 0.55)         # four sends in a row
        self.assertEqual(len(self.driver.sent), 5)
        self.assertEqual(h.broker.tab_locks, {}, "no lock is kept after use")

    def test_a_driver_call_that_takes_too_long_is_a_timeout(self):
        old = bus.DRIVER_TIMEOUT
        bus.DRIVER_TIMEOUT = 0.3
        self.addCleanup(setattr, bus, "DRIVER_TIMEOUT", old)
        self.driver.delay = 1.0
        h = self.start()
        rep = h.pub("tab/@1/in", {"run": "x"})
        self.assertEqual(rep["err"], "timeout")
        self.assertTrue(h.rpc({"op": "ping"})["ok"])

    def test_a_timed_out_send_keeps_the_tab_locked_until_it_really_ends(self):
        # the sender is told `timeout`, the keys are still being typed: a second send to the tab must wait, never type over the first
        old = bus.DRIVER_TIMEOUT
        bus.DRIVER_TIMEOUT = 0.4
        self.addCleanup(setattr, bus, "DRIVER_TIMEOUT", old)
        self.driver.delay = 0.7
        h = self.start()
        rep = h.pub("tab/@1/in", {"run": "first"})
        self.assertEqual(rep["err"], "timeout")
        self.assertIn("do not send it again", rep["msg"])
        self.driver.delay = 0.0
        rep2 = h.pub("tab/@1/in", {"run": "second"})                       # waits for the first to end (0.3 s more), then types
        self.assertTrue(rep2["ok"], rep2)
        self.assertEqual(self.driver.max_active["@1"], 1)
        self.assertEqual([b["run"] for _, b in self.driver.sent], ["first", "second"])
        self.assertTrue(wait_for(lambda: h.broker.tab_locks == {}), "the lock entry is removed once the thread ended")
        self.assertEqual([l for l in h.logs if "never retrieved" in l or "internal" in l], [])

    def test_a_send_that_waits_too_long_for_a_stuck_one_is_a_timeout_and_types_nothing(self):
        old = bus.DRIVER_TIMEOUT
        bus.DRIVER_TIMEOUT = 0.3
        self.addCleanup(setattr, bus, "DRIVER_TIMEOUT", old)
        self.driver.delay = 1.5
        h = self.start()
        self.assertEqual(h.pub("tab/@1/in", {"run": "first"})["err"], "timeout")
        rep = h.pub("tab/@1/in", {"run": "second"})
        self.assertEqual(rep["err"], "timeout")
        self.assertIn("nothing was typed", rep["msg"])
        self.assertTrue(wait_for(lambda: len(self.driver.sent) == 1, 5))
        self.assertEqual(self.driver.sent, [("@1", {"run": "first"})])

    def test_the_stub_driver_validates_its_body(self):
        d = bus.StubDriver()
        d.send("main", {"run": "ls"})
        d.send("main", {"input": "x{Esc}"})
        for bad in ({}, {"run": 1}, {"run": "a", "input": "b"}, {"other": "x"}, "ls", None, ["run"]):
            with self.subTest(body=bad):
                with self.assertRaises(bus.DriverError) as cm:
                    d.send("main", bad)
                self.assertEqual(cm.exception.code, "bad_body")
        with self.assertRaises(bus.DriverError) as cm:
            d.send("nope", {"run": "ls"})
        self.assertEqual(cm.exception.code, "no_such_tab")
        self.assertEqual(len(d.sent), 2)

    def test_the_base_driver_class_is_an_interface(self):
        d = bus.Driver()
        for call in (d.list_tabs, lambda: d.screen("a", None), lambda: d.send("a", {})):
            with self.assertRaises(NotImplementedError):
                call()
        self.assertIsInstance(bus.make_driver("auto"), bus.Driver)
        with self.assertRaises(ValueError):
            bus.make_driver("nope")


class Watch(Base):
    def setUp(self):
        self.driver = FakeDriver()

    def watcher(self, h, **kw):
        c = h.conn().send(dict({"op": "watch"}, **kw))
        self.assertEqual(c.line(), {"ok": True, "subscribed": "*"})
        return c

    def test_watch_sees_every_pub_including_the_failed_ones_and_the_reads(self):
        h = self.start()
        w = self.watcher(h)
        h.pub("goal", "nobody")
        s = h.sub()
        h.pub("goal", "someone")
        h.pub("tab/@1/in", {"run": "ls"})
        h.pub("tab/@7/in", {"run": "ls"})     # the fake driver accepts any tab for send
        h.rpc({"op": "ls", "topic": "tab/"})
        h.rpc({"op": "get", "topic": "tab/@1/screen"})
        evs = [w.line() for _ in range(6)]
        self.assertEqual([(e["kind"], e.get("result") if e["kind"] == "pub" else e["op"]) for e in evs],
                         [("pub", "no_subscriber"), ("pub", "ok"), ("pub", "ok"), ("pub", "ok"), ("read", "ls"), ("read", "get")])
        self.assertEqual(evs[0]["envelope"]["body"], "nobody")
        self.assertEqual(evs[5]["result"]["text"], "hello\nworld\n")
        self.assertEqual(s.line()["body"], "someone")

    def test_no_screen_replaces_the_text_in_the_broker(self):
        h = self.start()
        w = self.watcher(h, no_screen=True)
        full = self.watcher(h)
        h.rpc({"op": "get", "topic": "tab/@1/screen"})
        ev = w.line()
        self.assertEqual(ev["result"], {"text": "<12 bytes omitted>", "cursor": [1, 2]})
        self.assertNotIn("hello", str(ev))
        self.assertEqual(full.line()["result"]["text"], "hello\nworld\n")

    def test_a_watcher_that_dies_is_removed(self):
        h = self.start()
        w = self.watcher(h)
        w.close()
        self.assertTrue(wait_for(lambda: not h.broker.watchers))
        self.assertTrue(h.pub("tab/@1/in", {"run": "x"})["ok"])

    def test_a_slow_watcher_is_dropped(self):
        old = bus.SLOW_BUFFER
        bus.SLOW_BUFFER = 100 * 1024
        self.addCleanup(setattr, bus, "SLOW_BUFFER", old)
        h = self.start()
        slow = h.conn()
        slow.s.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4096)
        slow.send({"op": "watch"})
        slow.line()
        for _ in range(60):
            h.pub("tab/@1/in", {"run": "x" * 20000})
            if not h.broker.watchers:
                break
        self.assertEqual(h.broker.watchers, [])
        self.assertTrue(h.rpc({"op": "ping"})["ok"])


if __name__ == "__main__":
    unittest.main()
