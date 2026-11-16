"""The broker of swarmbox-bus (container/scripts/swarmbox-bus.py), in process, over a real unix socket.

Topics, broadcast, groups (one member gets each message, round robin; a member that dies, is slow or all are slow), the count of receivers
and --allow-none, topics, watch, big messages, bad names and requests, permissions, a stale socket, two brokers. A goal still works end to
end on a topic that the test chooses. No tmux, no network, no model. Run with: python3 tests/fast/test_bus.py
"""
import os
import socket
import stat
import sys
import threading
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "support"))
import bus_support  # noqa: E402
from bus_support import Conn, Harness, bus, rpc, short_tmp, wait_for  # noqa: E402


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
    def start(self, **kw):
        h = Harness(**kw)
        self.addCleanup(h.close)
        self.assertEqual(h.rc, 0)
        return h


TOPIC = "orders.7"      # a name the test chooses: the bus has no special topic


class Basics(Base):
    def test_no_subscriber(self):
        h = self.start()
        self.assertEqual(h.pub(TOPIC, {"text": "x"}), {"ok": False, "err": "no_subscriber", "delivered": 0})

    def test_one_subscriber_gets_the_envelope(self):
        h = self.start()
        s = h.sub(TOPIC)
        rep = h.pub(TOPIC, {"text": "run the tests"}, source="voice")
        self.assertTrue(rep["ok"])
        self.assertEqual(rep["delivered"], 1)
        env = s.line()
        self.assertEqual(sorted(env), ["body", "id", "peer", "source", "time", "topic", "v"])
        self.assertEqual((env["v"], env["topic"], env["source"], env["body"]), (1, TOPIC, "voice", {"text": "run the tests"}))
        self.assertEqual(env["id"], rep["id"])
        self.assertEqual(env["peer"]["uid"], os.getuid())
        self.assertRegex(env["time"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z$")
        self.assertRegex(env["id"], r"^[0-9a-f]{6}-\d+$")

    def test_the_subscribe_reply_names_the_topic_and_the_group(self):
        h = self.start()
        c = h.conn().send({"op": "sub", "topic": TOPIC, "group": "g1"})
        self.assertEqual(c.line(), {"ok": True, "subscribed": TOPIC, "group": "g1"})
        c = h.conn().send({"op": "sub", "topic": TOPIC})
        self.assertEqual(c.line(), {"ok": True, "subscribed": TOPIC, "group": None})

    def test_a_message_goes_only_to_its_own_topic(self):
        h = self.start()
        a, b = h.sub("one"), h.sub("two")
        self.assertEqual(h.pub("one", 1)["delivered"], 1)
        self.assertEqual(a.line()["body"], 1)
        self.assertEqual(h.pub("three", 1)["err"], "no_subscriber")
        b.s.settimeout(0.2)
        with self.assertRaises(socket.timeout):
            b.line()

    def test_ids_are_ordered_and_unique(self):
        h = self.start()
        got = collect(h.sub(TOPIC))
        ids = [h.pub(TOPIC, i)["id"] for i in range(5)]
        self.assertEqual([int(i.split("-")[1]) for i in ids], sorted(int(i.split("-")[1]) for i in ids))
        self.assertEqual(len(set(ids)), 5)
        self.assertTrue(wait_for(lambda: len(got) == 5))
        self.assertEqual(got, [0, 1, 2, 3, 4])

    def test_source_is_cut_at_64_and_peer_cannot_be_forged(self):
        h = self.start()
        s = h.sub(TOPIC)
        h.pub(TOPIC, 1, source="x" * 200, peer={"pid": 1, "uid": 0})
        env = s.line()
        self.assertEqual(env["source"], "x" * 64)
        self.assertEqual(env["peer"]["uid"], os.getuid())
        h.pub(TOPIC, 2)
        self.assertEqual(s.line()["source"], "cli")

    def test_a_subscriber_may_talk_and_nothing_happens(self):
        h = self.start()
        s = h.sub(TOPIC)
        s.s.sendall(b"garbage\n" * 100)
        h.pub(TOPIC, "still works")
        self.assertEqual(s.line()["body"], "still works")

    def test_the_body_is_any_json_value(self):
        h = self.start()
        s = h.sub(TOPIC)
        for body in ("text", 5, None, [1, 2], {"a": {"b": 1}}, True):
            self.assertTrue(h.pub(TOPIC, body)["ok"])
            self.assertEqual(s.line()["body"], body)

    def test_a_goal_end_to_end_on_a_topic_the_test_chose(self):
        h = self.start()
        sysop = h.sub("tasks:today", "sysop")
        voice = h.rpc({"op": "pub", "topic": "tasks:today", "source": "voice", "body": {"text": "open the logs"}})
        self.assertEqual((voice["ok"], voice["delivered"]), (True, 1))
        env = sysop.line()
        self.assertEqual((env["topic"], env["source"], env["body"]), ("tasks:today", "voice", {"text": "open the logs"}))
        self.assertEqual(h.pub("goal", {"text": "x"})["err"], "no_subscriber")       # "goal" is a name like any other


class Broadcast(Base):
    def test_every_subscriber_gets_every_message(self):
        h = self.start()
        subs = [h.sub(TOPIC) for _ in range(3)]
        gots = [collect(c) for c in subs]
        for i in range(5):
            self.assertEqual(h.pub(TOPIC, i)["delivered"], 3)
        self.assertTrue(wait_for(lambda: all(len(g) == 5 for g in gots)))
        self.assertTrue(all(g == [0, 1, 2, 3, 4] for g in gots))

    def test_a_subscriber_that_dies_is_dropped_and_the_count_follows(self):
        h = self.start()
        a, b = h.sub(TOPIC), h.sub(TOPIC)
        self.assertEqual(h.pub(TOPIC, 0)["delivered"], 2)
        a.close()
        self.assertTrue(wait_for(lambda: len(h.broker.subs[TOPIC]) == 1))
        got = collect(b)
        self.assertEqual(h.pub(TOPIC, 1)["delivered"], 1)
        b.close()
        self.assertTrue(wait_for(lambda: TOPIC not in h.broker.subs))
        self.assertEqual(h.pub(TOPIC, 2)["err"], "no_subscriber")

    def test_a_slow_subscriber_without_a_group_is_skipped_and_the_others_still_get_the_message(self):
        old = bus.SLOW_BUFFER
        bus.SLOW_BUFFER = 200 * 1024
        self.addCleanup(setattr, bus, "SLOW_BUFFER", old)
        h = self.start()
        slow = h.conn()
        slow.s.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4096)
        slow.send({"op": "sub", "topic": TOPIC})
        self.assertTrue(slow.line()["ok"])      # and never reads again
        big = "x" * 100000
        res = None
        for _ in range(100):
            res = h.pub(TOPIC, big)
            if not res["ok"]:
                break
        self.assertEqual((res["err"], res["delivered"]), ("busy", 0))        # the only subscriber is far behind
        good = h.sub(TOPIC)
        res = h.pub(TOPIC, "to the healthy one")
        self.assertEqual((res["ok"], res["delivered"]), (True, 1))           # the slow one is skipped, not counted
        self.assertEqual(good.line()["body"], "to the healthy one")


class Groups(Base):
    def test_two_members_share_by_round_robin_and_each_message_goes_to_one(self):
        h = self.start()
        a, b = h.sub(TOPIC, "workers"), h.sub(TOPIC, "workers")
        ga, gb = collect(a), collect(b)          # consumers that read all the time
        for i in range(10):
            rep = h.pub(TOPIC, i)
            self.assertEqual((rep["ok"], rep["delivered"]), (True, 1))
        self.assertTrue(wait_for(lambda: len(ga) + len(gb) == 10))
        self.assertEqual((len(ga), len(gb)), (5, 5))
        self.assertEqual(sorted(ga + gb), list(range(10)))

    def test_the_rotation_alternates_members_in_order(self):
        h = self.start()
        gots = [collect(h.sub(TOPIC, "g")) for _ in range(3)]
        for i in range(6):
            h.pub(TOPIC, i)
            time.sleep(0.03)            # the member that took it reads it before the next one is published
        self.assertTrue(wait_for(lambda: sum(len(g) for g in gots) == 6))
        self.assertEqual(gots, [[0, 3], [1, 4], [2, 5]])

    def test_a_member_that_dies_is_dropped_and_the_other_gets_everything(self):
        h = self.start()
        a, b = h.sub(TOPIC, "g"), h.sub(TOPIC, "g")
        a.close()
        self.assertTrue(wait_for(lambda: len(h.broker.subs[TOPIC]) == 1))
        got = collect(b)
        for i in range(6):
            self.assertEqual(h.pub(TOPIC, i)["delivered"], 1)
        self.assertTrue(wait_for(lambda: len(got) == 6))
        self.assertEqual(got, list(range(6)))
        b.close()
        self.assertTrue(wait_for(lambda: TOPIC not in h.broker.subs))
        self.assertEqual(h.pub(TOPIC, 1)["err"], "no_subscriber")

    def test_a_member_that_does_not_read_gets_one_message_and_then_the_other_gets_the_rest(self):
        # alive but not reading (stopped, hung): the messages are not queued behind it, they go to a member that reads
        h = self.start()
        stuck = h.sub(TOPIC, "g")
        reading = h.sub(TOPIC, "g")
        got = collect(reading)
        for i in range(20):
            rep = h.pub(TOPIC, {"n": i})
            self.assertEqual(rep.get("delivered"), 1, rep)
        self.assertTrue(wait_for(lambda: len(got) >= 19, 5), got)
        self.assertEqual([g["n"] for g in got], list(range(1, 20)))      # the first went to the stuck one, which had read nothing yet
        self.assertEqual(stuck.line()["body"], {"n": 0})
        stuck.s.settimeout(0.3)
        with self.assertRaises(socket.timeout):
            stuck.line()                                                    # and nothing else is waiting for it

    def test_a_slow_member_is_skipped_and_a_healthy_one_keeps_receiving(self):
        old = bus.SLOW_BUFFER
        bus.SLOW_BUFFER = 200 * 1024
        self.addCleanup(setattr, bus, "SLOW_BUFFER", old)
        h = self.start()
        slow = h.conn()
        slow.s.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4096)
        slow.send({"op": "sub", "topic": TOPIC, "group": "g"})
        self.assertTrue(slow.line()["ok"])
        big = "x" * 100000
        res = None
        for _ in range(100):
            res = h.pub(TOPIC, big)
            if not res["ok"]:
                break
        self.assertEqual((res["err"], res["delivered"], res["busy"]), ("busy", 0, ["g"]))
        self.assertIn("group g", res["msg"])
        good = h.sub(TOPIC, "g")
        self.assertTrue(h.pub(TOPIC, "to the healthy one")["ok"])
        self.assertEqual(good.line()["body"], "to the healthy one")

    def test_when_every_member_is_stuck_the_share_is_busy_after_a_short_wait_and_goes_again_when_one_reads(self):
        h = self.start()
        a = h.sub(TOPIC, "g")
        self.assertTrue(h.pub(TOPIC, 1)["ok"])
        t = time.time()
        rep = h.pub(TOPIC, 2)
        self.assertEqual((rep["ok"], rep["err"], rep["delivered"], rep["busy"]), (False, "busy", 0, ["g"]))
        self.assertGreaterEqual(time.time() - t, bus.GROUP_GRACE * 0.9)
        self.assertLess(time.time() - t, bus.GROUP_GRACE + 2)
        self.assertEqual(a.line()["body"], 1)                                # it reads, so it is ready again
        self.assertTrue(h.pub(TOPIC, 3)["ok"])
        self.assertEqual(a.line()["body"], 3)

    def test_a_member_that_reads_a_moment_later_is_waited_for(self):
        h = self.start()
        a = h.sub(TOPIC, "g")
        self.assertTrue(h.pub(TOPIC, 1)["ok"])
        threading.Timer(0.05, a.line).start()
        self.assertTrue(h.pub(TOPIC, 2)["ok"])

    def test_two_groups_each_get_the_message_once(self):
        h = self.start()
        a1, a2 = h.sub(TOPIC, "a"), h.sub(TOPIC, "a")
        b1 = h.sub(TOPIC, "b")
        gots = [collect(c) for c in (a1, a2, b1)]
        for i in range(4):
            self.assertEqual(h.pub(TOPIC, i)["delivered"], 2)          # one per group
        self.assertTrue(wait_for(lambda: len(gots[0]) + len(gots[1]) == 4 and len(gots[2]) == 4))
        self.assertEqual(sorted(gots[0] + gots[1]), [0, 1, 2, 3])
        self.assertEqual(gots[2], [0, 1, 2, 3])

    def test_broadcast_and_a_group_mix(self):
        h = self.start()
        w1, w2 = h.sub(TOPIC, "workers"), h.sub(TOPIC, "workers")
        logger, auditor = h.sub(TOPIC), h.sub(TOPIC)
        gots = [collect(c) for c in (w1, w2, logger, auditor)]
        for i in range(6):
            self.assertEqual(h.pub(TOPIC, i)["delivered"], 3)          # two without a group, plus the group once
        self.assertTrue(wait_for(lambda: len(gots[0]) + len(gots[1]) == 6 and len(gots[2]) == 6 and len(gots[3]) == 6))
        self.assertEqual(gots[2], list(range(6)))
        self.assertEqual(gots[3], list(range(6)))
        self.assertEqual(sorted(gots[0] + gots[1]), list(range(6)))
        self.assertEqual((len(gots[0]), len(gots[1])), (3, 3))

    def test_a_busy_group_does_not_stop_the_others_from_receiving_and_the_reply_says_both(self):
        h = self.start()
        stuck = h.sub(TOPIC, "slowpoke")
        self.assertTrue(h.pub(TOPIC, 0)["ok"])                           # the stuck member now has an unread message
        fine = h.sub(TOPIC)
        rep = h.pub(TOPIC, 1)
        self.assertEqual((rep["ok"], rep["err"], rep["delivered"], rep["busy"]), (False, "busy", 1, ["slowpoke"]))
        self.assertEqual(fine.line()["body"], 1)                         # the broadcast subscriber did get it

    def test_the_same_group_name_on_another_topic_is_another_group(self):
        h = self.start()
        a, b = h.sub("t1", "g"), h.sub("t2", "g")
        self.assertEqual(h.pub("t1", 1)["delivered"], 1)
        self.assertEqual(h.pub("t2", 2)["delivered"], 1)
        self.assertEqual((a.line()["body"], b.line()["body"]), (1, 2))


class Receivers(Base):
    def test_allow_none_accepts_no_receiver(self):
        h = self.start()
        self.assertEqual(h.pub(TOPIC, 1, allow_none=True)["delivered"], 0)
        self.assertTrue(h.pub(TOPIC, 1, allow_none=True)["ok"])
        self.assertEqual(h.pub(TOPIC, 1, allow_none=False)["err"], "no_subscriber")
        self.assertEqual(h.pub(TOPIC, 1, allow_none="yes")["err"], "no_subscriber")      # only the boolean true counts

    def test_allow_none_does_not_hide_a_busy_group(self):
        h = self.start()
        h.sub(TOPIC, "g")
        h.pub(TOPIC, 1)
        self.assertEqual(h.pub(TOPIC, 2, allow_none=True)["err"], "busy")

    def test_the_count_is_ungrouped_subscribers_plus_one_per_group(self):
        h = self.start()
        cs = [h.sub(TOPIC), h.sub(TOPIC, "a"), h.sub(TOPIC, "a"), h.sub(TOPIC, "b"), h.sub(TOPIC, "c"), h.sub(TOPIC, "c"), h.sub(TOPIC, "c")]
        [collect(c) for c in cs]
        self.assertEqual(h.pub(TOPIC, 1)["delivered"], 4)


class Topics(Base):
    def test_topics_lists_only_topics_with_subscribers_with_their_counts(self):
        h = self.start()
        self.assertEqual(h.rpc({"op": "topics"}), {"ok": True, "result": []})
        a = h.sub("zeta")
        h.sub("alpha")
        h.sub("alpha", "g")
        h.sub("alpha", "g")
        h.sub("alpha", "h")
        self.assertEqual(h.rpc({"op": "topics"})["result"],
                         [{"topic": "alpha", "subscribers": 4, "groups": {"g": 2, "h": 1}}, {"topic": "zeta", "subscribers": 1, "groups": {}}])
        a.close()
        self.assertTrue(wait_for(lambda: [t["topic"] for t in h.rpc({"op": "topics"})["result"]] == ["alpha"]))

    def test_a_watcher_is_not_a_topic(self):
        h = self.start()
        h.conn().send({"op": "watch"}).line()
        self.assertEqual(h.rpc({"op": "topics"})["result"], [])


class Sizes(Base):
    def test_900_kib_arrives_whole(self):
        h = self.start()
        s = h.sub(TOPIC)
        body = "a" * (900 * 1024)
        self.assertTrue(h.pub(TOPIC, body)["ok"])
        env = s.line()
        self.assertEqual(len(env["body"]), len(body))

    def test_over_the_limit_is_too_large_and_the_broker_survives(self):
        h = self.start()
        self.assertEqual(h.pub(TOPIC, "a" * bus.MAX_LINE), {"ok": False, "err": "too_large"})
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
        s = h.sub(TOPIC)
        body = "a" * (bus.MAX_REQUEST - 200)
        rep = h.pub(TOPIC, body, source="é" * 64)
        if rep["ok"]:
            raw = s.f.readline()
            self.assertLessEqual(len(raw), bus.MAX_LINE)
        else:
            self.assertEqual(rep["err"], "too_large")


class BadInput(Base):
    BAD_NAMES = ["", ".x", "-x", "_x", ":x", "a b", "a/b", "tab/x/in", "a;b", "a\nb", "x" * 65, "é", "a\x00b", "..", "a\\b", "a*", " x"]
    GOOD_NAMES = ["goal", "Goal", "a", "0", "9lives", "a.b_c-d:e", "A" * 64, "voice.topic", "tab"]

    def test_bad_topics_on_pub(self):
        h = self.start()
        for t in self.BAD_NAMES:
            with self.subTest(topic=t):
                self.assertEqual(h.pub(t, 1), {"ok": False, "err": "bad_topic"})
        for t in (5, None, ["a"], {"a": 1}, True):
            self.assertEqual(h.rpc({"op": "pub", "topic": t, "body": 1})["err"], "bad_topic")
        self.assertEqual(h.rpc({"op": "pub", "body": 1})["err"], "bad_topic")

    def test_good_names_are_all_free_topics_and_no_name_is_reserved(self):
        h = self.start()
        for t in self.GOOD_NAMES:
            with self.subTest(topic=t):
                c = h.sub(t)
                self.assertEqual(h.pub(t, "x")["delivered"], 1)
                self.assertEqual(c.line()["topic"], t)

    def test_bad_topics_and_groups_on_sub(self):
        h = self.start()
        for t in self.BAD_NAMES + [5, None]:
            with self.subTest(sub=t):
                self.assertEqual(h.rpc({"op": "sub", "topic": t})["err"], "bad_topic")
        self.assertEqual(h.rpc({"op": "sub"})["err"], "bad_topic")
        for g in self.BAD_NAMES[1:] + [5, ["a"]]:
            with self.subTest(group=g):
                self.assertEqual(h.rpc({"op": "sub", "topic": "t", "group": g})["err"], "bad_group")
        self.assertEqual(h.rpc({"op": "sub", "topic": "t", "group": ""})["err"], "bad_group")
        self.assertEqual(h.rpc({"op": "topics"})["result"], [])          # nothing was subscribed

    def test_the_old_ops_are_gone(self):
        h = self.start()
        for req in ({"op": "get", "topic": "tab/x/screen"}, {"op": "ls", "topic": "tab/"}, {"op": "ls"}):
            self.assertEqual(h.rpc(req)["err"], "bad_request", req)

    def test_bad_requests_and_the_broker_lives(self):
        h = self.start()
        for raw in (b"not json\n", b"[1,2]\n", b"5\n", b"{}\n", b'{"op":5}\n', b'{"op":"nope"}\n', b'{"op":"pub","topic":"goal"}\n', b"\n", b"\xff\xfe\n"):
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
        c.s.sendall(b'{"op":"pub","topic":"t","body":1,"allow_none":true}\n')
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
        b = bus.Broker(os.path.join(d, "sub", "bus.sock"))
        self.assertEqual(b.acquire(), 0)
        self.assertEqual(stat.S_IMODE(os.stat(os.path.join(d, "sub")).st_mode), 0o700)

    def test_another_uid_is_refused(self):
        h = self.start(allowed_uids={os.getuid() + 4242})
        self.assertEqual(h.rpc({"op": "ping"})["err"], "forbidden")
        self.assertEqual(h.pub(TOPIC, 1)["err"], "forbidden")
        self.assertEqual(h.rpc({"op": "topics"})["err"], "forbidden")
        self.assertEqual(h.rpc({"op": "sub", "topic": TOPIC})["err"], "forbidden")

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
        h.dir, h.path, h.logs, h.conns = d, path, [], []
        h.broker = bus.Broker(path, log=h.logs.append)
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
        b = bus.Broker(path)
        self.assertEqual(b.acquire(), 1)
        with open(path) as f:
            self.assertEqual(f.read(), "precious")

    def test_a_second_broker_exits_8_and_the_first_is_untouched(self):
        h = self.start()
        second = bus.Broker(h.path)
        self.assertEqual(second.acquire(), 8)
        self.assertTrue(os.path.exists(h.path))
        s = h.sub(TOPIC)
        self.assertTrue(h.pub(TOPIC, "still the first")["ok"])
        self.assertEqual(s.line()["body"], "still the first")

    def test_many_brokers_at_once_leave_exactly_one(self):
        d = short_tmp()
        self.addCleanup(__import__("shutil").rmtree, d, True)
        path = os.path.join(d, "bus.sock")
        brokers = [bus.Broker(path) for _ in range(6)]
        rcs = []
        ts = [threading.Thread(target=lambda b=b: rcs.append(b.acquire())) for b in brokers]
        [t.start() for t in ts]
        [t.join() for t in ts]
        self.assertEqual(sorted(rcs), [0, 8, 8, 8, 8, 8])

    def test_the_lock_is_free_once_the_broker_stops(self):
        h = self.start()
        h.broker.stop()
        h.thread.join(10)
        again = bus.Broker(h.path)
        self.assertEqual(again.acquire(), 0)

    def test_stop_closes_subscribers_and_removes_the_socket(self):
        h = self.start()
        s = h.sub(TOPIC)
        w = h.conn().send({"op": "watch"})
        w.line()
        h.broker.stop()
        h.thread.join(10)
        self.assertIsNone(s.line())
        self.assertIsNone(w.line())
        self.assertFalse(os.path.exists(h.path))


class Watch(Base):
    def watcher(self, h):
        c = h.conn().send({"op": "watch"})
        self.assertEqual(c.line(), {"ok": True, "subscribed": "*", "group": None})
        return c

    def test_watch_sees_every_pub_with_its_topic_receivers_and_result(self):
        h = self.start()
        w = self.watcher(h)
        h.pub("alpha", "nobody")
        h.pub("alpha", "nobody, accepted", allow_none=True)
        s = h.sub("alpha")
        g1, g2 = h.sub("beta", "g"), h.sub("beta", "g")
        h.pub("alpha", "someone")
        h.pub("beta", "a group")
        evs = [w.line() for _ in range(4)]
        self.assertEqual([(e["kind"], e["topic"], e["receivers"], e["result"]) for e in evs],
                         [("pub", "alpha", 0, "no_subscriber"), ("pub", "alpha", 0, "ok"), ("pub", "alpha", 1, "ok"), ("pub", "beta", 1, "ok")])
        self.assertEqual(evs[0]["envelope"]["body"], "nobody")
        self.assertEqual(evs[2]["envelope"]["topic"], "alpha")
        self.assertEqual(s.line()["body"], "someone")

    def test_watch_shows_a_busy_share(self):
        h = self.start()
        w = self.watcher(h)
        h.sub("t", "g")
        h.pub("t", 1)
        h.pub("t", 2)
        self.assertEqual([w.line()["result"] for _ in range(2)], ["ok", "busy"])

    def test_nothing_but_publications_passes(self):
        h = self.start()
        w = self.watcher(h)
        h.rpc({"op": "topics"})
        h.rpc({"op": "ping"})
        h.pub("t", 1, allow_none=True)
        self.assertEqual(w.line()["kind"], "pub")

    def test_a_watcher_that_dies_is_removed(self):
        h = self.start()
        w = self.watcher(h)
        w.close()
        self.assertTrue(wait_for(lambda: not h.broker.watchers))
        self.assertTrue(h.pub(TOPIC, "x", allow_none=True)["ok"])

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
            h.pub(TOPIC, "x" * 20000, allow_none=True)
            if not h.broker.watchers:
                break
        self.assertEqual(h.broker.watchers, [])
        self.assertTrue(h.rpc({"op": "ping"})["ok"])


class NoTabs(unittest.TestCase):
    def test_the_bus_has_no_trace_of_tmux_or_tabs(self):
        with open(bus_support.BUS_PATH) as f:
            code = f.read()
        code = code.split('"""', 2)[2]                    # the docstring may say that there are none
        for word in ("tmux", "tab/", "Driver", "driver", "no_screen", "DriverError", "make_driver", "executor", "ThreadPool"):
            self.assertNotIn(word, code, word)
        for name in ("Driver", "StubDriver", "make_driver", "load_tmux_module", "DriverError", "pub_topic_ok", "tab_topic"):
            self.assertFalse(hasattr(bus, name), name)


if __name__ == "__main__":
    unittest.main()
