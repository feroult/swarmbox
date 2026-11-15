"""swarmbox-bus as programs: the broker as a process and the command line against it, with the exit codes, stdin, streams, a stale socket
after kill -9, groups, many clients and 100 messages per second. No tmux, no network, no model. Run with: python3 tests/test_bus_cli.py
"""
import json
import os
import signal
import subprocess
import sys
import threading
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bus_support import BUS_PATH, Conn, Process, bus, wait_for  # noqa: E402


class Base(unittest.TestCase):
    def broker(self, **kw):
        p = Process(**kw).start()
        self.addCleanup(p.close)
        return p

    def idle(self):
        p = Process()
        self.addCleanup(p.close)
        return p


class Usage(Base):
    def test_no_arguments_and_unknown_things_are_2(self):
        p = self.idle()
        for args in ([], ["frobnicate"], ["pub"], ["pub", "a", "b", "c"], ["pub", "--source"], ["pub", "--nope", "jobs", "x"], ["get", "a"], ["ls"],
                     ["sub"], ["sub", "a", "b"], ["sub", "--nope", "a"], ["sub", "--group"], ["sub", "--group", "g"], ["topics", "x"], ["watch", "x"],
                     ["watch", "--no-screen"], ["ping", "x"], ["restart", "x"], ["serve", "--nope"], ["serve", "--driver", "stub"]):
            with self.subTest(args=args):
                r = p.cli(*args)
                self.assertEqual(r.returncode, 2, r.stderr)
                self.assertTrue(r.stderr)
                self.assertEqual(r.stdout, b"")

    def test_help_prints_the_docstring_and_exits_0(self):
        p = self.idle()
        for a in ("--help", "-h", "help"):
            r = p.cli(a)
            self.assertEqual(r.returncode, 0)
            self.assertIn(b"Exit codes: 0 ok, 1 other error, 2 usage, 3 nobody received the message", r.stdout)

    def test_the_documented_exit_codes_are_the_ones_of_the_code(self):
        self.assertEqual(bus.EXIT, {"no_subscriber": 3, "too_large": 5, "bad_topic": 6, "bad_group": 6, "bad_request": 6, "busy": 7})


class NotRunning(Base):
    def test_every_command_says_4_with_no_traceback(self):
        p = self.idle()
        for args in (["pub", "jobs", "x"], ["topics"], ["sub", "jobs"], ["sub", "--group", "g", "jobs"], ["watch"], ["ping"]):
            with self.subTest(args=args):
                r = p.cli(*args, stdin=b"")
                self.assertEqual(r.returncode, 4, r.stderr)
                self.assertIn(b"the bus is not running", r.stderr)
                self.assertNotIn(b"Traceback", r.stderr)

    def test_a_stale_socket_after_kill_9_is_4_and_a_new_broker_takes_over(self):
        p = self.broker()
        p.proc.kill()
        p.proc.wait()
        self.assertTrue(os.path.exists(p.path), "kill -9 leaves the socket file")
        r = p.cli("ping")
        self.assertEqual(r.returncode, 4)
        self.assertNotIn(b"Traceback", r.stderr)
        p.start()
        self.assertEqual(p.cli("ping").returncode, 0)

    def test_permission_denied_is_1(self):
        if os.geteuid() == 0:
            self.skipTest("root ignores the mode")
        p = self.broker()
        os.chmod(p.path, 0o000)
        r = p.cli("ping")
        self.assertEqual(r.returncode, 1)
        self.assertIn(b"permission denied", r.stderr)

    def test_a_socket_path_that_is_too_long_is_1(self):
        p = self.idle()
        r = p.cli("ping", env={"SB_BUS_SOCKET": "/tmp/" + "x" * 200})
        self.assertEqual(r.returncode, 1)

    def test_the_default_path_follows_sb_run_dir(self):
        p = self.broker()
        env = {"SB_BUS_SOCKET": ""}
        self.assertEqual(p.cli("ping", env=dict(env, SB_RUN_DIR=p.dir)).returncode, 0)
        self.assertEqual(p.cli("ping", env=dict(env, SB_RUN_DIR=p.dir + "x")).returncode, 4)


class Pub(Base):
    def test_pub_exit_codes(self):
        p = self.broker()
        r = p.cli("pub", "jobs", "hi")
        self.assertEqual((r.returncode, r.stdout), (3, b""))
        self.assertIn(b"no_subscriber", r.stderr)
        self.assertEqual(p.cli("pub", "no good", "hi").returncode, 6)
        self.assertEqual(p.cli("pub", "tab/x/in", "text").returncode, 6)                 # the tab topics are gone: a slash is not a name
        sub = p.popen("sub", "--raw", "-v", "jobs")
        self.assertIn(b"subscribed", sub.stderr.readline())
        r = p.cli("pub", "jobs", '{"run": "ls"}')
        self.assertEqual(r.returncode, 0)
        out = json.loads(r.stdout)
        self.assertRegex(out["id"], r"^[0-9a-f]{6}-\d+$")
        self.assertEqual(out["receivers"], 1)
        sub.terminate()
        sub.wait()

    def test_allow_none_and_the_count(self):
        p = self.broker()
        r = p.cli("pub", "--allow-none", "jobs", "hi")
        self.assertEqual((r.returncode, json.loads(r.stdout)["receivers"]), (0, 0))
        r = p.cli("pub", "jobs", "--allow-none", "hi")           # the flag may come anywhere before the end
        self.assertEqual(r.returncode, 0)
        subs = [p.popen("sub", "-v", "jobs"), p.popen("sub", "-v", "--group", "g", "jobs"), p.popen("sub", "-v", "--group", "g", "jobs")]
        for s in subs:
            self.assertIn(b"subscribed", s.stderr.readline())
        r = p.cli("pub", "jobs", "x")
        self.assertEqual(json.loads(r.stdout)["receivers"], 2)       # the plain subscriber, and one member of the group
        for s in subs:
            s.terminate()
            s.wait()

    def test_bad_names_are_6(self):
        p = self.broker()
        for t in ("-x", "a b", "a/b", "x" * 65):
            self.assertEqual(p.cli("pub", "--", t, "m").returncode, 6, t)
            self.assertEqual(p.cli("sub", "--", t).returncode, 6, t)
        r = p.cli("sub", "--group", "bad group", "jobs")
        self.assertEqual(r.returncode, 6)
        self.assertIn(b"bad_group", r.stderr)

    def test_topics_prints_one_line_of_json(self):
        p = self.broker()
        self.assertEqual(json.loads(p.cli("topics").stdout), [])
        s = p.popen("sub", "-v", "--group", "sysop", "jobs")
        self.assertIn(b"subscribed", s.stderr.readline())
        self.assertEqual(json.loads(p.cli("topics").stdout), [{"topic": "jobs", "subscribers": 1, "groups": {"sysop": 1}}])
        s.terminate()
        s.wait()

    def test_message_forms_text_json_and_stdin(self):
        p = self.broker()
        sub = p.popen("sub", "--raw", "-v", "jobs")
        self.assertIn(b"subscribed", sub.stderr.readline())
        p.cli("pub", "jobs", "plain text with spaces")
        p.cli("pub", "jobs", '{"text": "run the tests"}')
        p.cli("pub", "jobs", "-", stdin=b'{"text":\n "multi line json"}\n')
        p.cli("pub", "jobs", stdin=b"from stdin by default\n")
        p.cli("pub", "jobs", "5")
        got = [sub.stdout.readline().decode().rstrip("\n") for _ in range(5)]
        sub.terminate()
        sub.wait()
        self.assertEqual(got, ["plain text with spaces", '{"text": "run the tests"}', '{"text": "multi line json"}',
                               "from stdin by default", "5"])

    def test_raw_prints_one_line_per_message_whatever_the_body(self):
        # a line reader (`while read -r goal`) must see one goal per published message
        p = self.broker()
        sub = p.popen("sub", "--raw", "-v", "jobs")
        self.assertIn(b"subscribed", sub.stderr.readline())
        for msg in ('"line one\\nline two"', "plain text", "null", '"null"', "5", '"5"', '"a\\rb"', '"é ü"', '{"k": "é\\nx"}', "NaN"):
            self.assertEqual(p.cli("pub", "jobs", msg).returncode, 0, msg)
        got = [sub.stdout.readline().decode().rstrip("\n") for _ in range(10)]
        sub.terminate()
        sub.wait()
        self.assertEqual(got, ['"line one\\nline two"', "plain text", "null", '"null"', "5", '"5"', '"a\\rb"', "é ü", '{"k": "é\\nx"}', "NaN"])

    def test_nan_and_infinity_are_text_and_never_reach_a_subscriber_as_bare_json(self):
        p = self.broker()
        sub = p.popen("sub", "-v", "jobs")
        self.assertIn(b"subscribed", sub.stderr.readline())
        for msg in ("NaN", "Infinity", "-Infinity", "1e999", "[NaN]"):
            self.assertEqual(p.cli("pub", "jobs", "--", msg).returncode, 0, msg)
        envs = [sub.stdout.readline() for _ in range(5)]
        sub.terminate()
        sub.wait()
        for line in envs:
            json.loads(line, parse_constant=lambda c: self.fail("bare %s in %r" % (c, line)))
        self.assertEqual([json.loads(l)["body"] for l in envs], ["NaN", "Infinity", "-Infinity", "1e999", "[NaN]"])
        # a client that sends it anyway (not this CLI) is refused by the broker
        c = Conn(p.path)
        c.send(b'{"op":"pub","topic":"jobs","body":NaN}\n')
        self.assertEqual(c.line()["err"], "bad_request")
        c.close()
        c = Conn(p.path)
        c.send(b'{"op":"pub","topic":"jobs","body":1e999}\n')
        self.assertEqual(c.line()["err"], "bad_request")
        c.close()

    def test_double_dash_ends_the_options(self):
        p = self.broker()
        sub = p.popen("sub", "--raw", "-v", "jobs")
        self.assertIn(b"subscribed", sub.stderr.readline())
        for args in (("--", "jobs", "-5"), ("jobs", "--", "-x"), ("--source", "me", "--", "jobs", "--help"), ("jobs", "--")):
            r = p.cli("pub", *args, stdin=b"from stdin\n")
            self.assertEqual(r.returncode, 0, (args, r.stderr))
        got = [sub.stdout.readline().decode().rstrip("\n") for _ in range(4)]
        sub.terminate()
        sub.wait()
        self.assertEqual(got, ["-5", "-x", "--help", "from stdin"])
        for args in (("jobs", "-5"), ("jobs", "--help"), ("jobs", "-x")):           # without `--` a dash word is still an unknown option
            self.assertEqual(p.cli("pub", *args).returncode, 2, args)

    def test_source_flag_and_env(self):
        p = self.broker()
        sub = p.popen("sub", "-v", "jobs")
        self.assertIn(b"subscribed", sub.stderr.readline())
        p.cli("pub", "--source", "voice", "jobs", "a")
        p.cli("pub", "jobs", "b", env={"SB_BUS_SOURCE": "sysop"})
        p.cli("pub", "jobs", "c")
        srcs = [json.loads(sub.stdout.readline())["source"] for _ in range(3)]
        sub.terminate()
        sub.wait()
        self.assertEqual(srcs, ["voice", "sysop", "cli"])

    def test_a_big_body_goes_by_stdin_and_arrives_whole(self):
        p = self.broker()
        sub = p.popen("sub", "--raw", "jobs")
        self.assertTrue(wait_for(lambda: p.cli("pub", "jobs", "probe").returncode == 0, 5))
        sub.stdout.readline()
        body = ("0123456789abcdef" * 56 * 1024)[:900 * 1024]
        r = p.cli("pub", "jobs", "-", stdin=body.encode())
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(sub.stdout.readline().decode().rstrip("\n"), body)
        sub.terminate()
        sub.wait()

    def test_too_large_is_5_from_stdin_and_from_a_long_argument(self):
        p = self.broker()
        r = p.cli("pub", "jobs", "-", stdin=b"x" * (bus.MAX_LINE + 10))
        self.assertEqual(r.returncode, 5)
        self.assertIn(b"too large", r.stderr)
        r = p.cli("pub", "jobs", "x" * 120000, stdin=b"")      # under the 128 KiB argv limit, over nothing: no subscriber
        self.assertEqual(r.returncode, 3)
        self.assertEqual(p.cli("ping").returncode, 0)

    def test_invalid_utf8_on_stdin_is_6(self):
        p = self.broker()
        self.assertEqual(p.cli("pub", "jobs", "-", stdin=b"\xff\xfe").returncode, 6)


class Streams(Base):
    def test_sub_exits_4_when_the_broker_goes_away_and_watch_too(self):
        p = self.broker()
        sub, watch = p.popen("sub", "jobs"), p.popen("watch")
        self.assertTrue(wait_for(lambda: p.cli("pub", "jobs", "x").returncode == 0, 5))
        p.stop()
        for c in (sub, watch):
            self.assertEqual(c.wait(10), 4)
            self.assertIn(b"the broker closed the connection", c.stderr.read())

    def test_sub_of_a_bad_topic_is_6(self):
        p = self.broker()
        self.assertEqual(p.cli("sub", "tab/x/in").returncode, 6)

    def test_groups_share_between_two_cli_subscribers(self):
        p = self.broker()
        a, b = p.popen("sub", "--raw", "-v", "--group", "w", "jobs"), p.popen("sub", "--raw", "-v", "--group", "w", "jobs")
        for s in (a, b):
            self.assertIn(b"subscribed", s.stderr.readline())
        for i in range(6):
            self.assertEqual(p.cli("pub", "jobs", "m%d" % i).returncode, 0)
            time.sleep(0.05)
        time.sleep(0.2)
        outs = []
        for s in (a, b):
            s.terminate()
            out, _ = s.communicate(10)
            outs.append(out.decode().split())
        self.assertEqual(sorted(outs[0] + outs[1]), ["m%d" % i for i in range(6)])
        self.assertEqual((len(outs[0]), len(outs[1])), (3, 3))

    def test_ctrl_c_is_130_and_a_closed_pipe_ends_quietly(self):
        p = self.broker()
        sub = p.popen("sub", "jobs")
        self.assertTrue(wait_for(lambda: p.cli("pub", "jobs", "x").returncode == 0, 5))
        sub.send_signal(signal.SIGINT)
        self.assertEqual(sub.wait(10), 130)
        sub = subprocess.Popen("%s -S %s sub jobs | head -n 1" % (sys.executable, BUS_PATH), shell=True, env=p.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        time.sleep(0.5)
        self.assertEqual(p.cli("pub", "jobs", "one").returncode, 0)
        time.sleep(0.2)
        p.cli("pub", "jobs", "two")
        out, err = sub.communicate(10)
        self.assertEqual((out.strip().count(b"\n"), err), (0, b""))

    def test_watch_prints_one_json_line_per_message(self):
        p = self.broker()
        w = p.popen("watch", "-v")
        self.assertIn(b"subscribed", w.stderr.readline())
        p.cli("pub", "--allow-none", "--source", "t", "alpha", '{"a": 1}')
        ev = json.loads(w.stdout.readline())
        w.terminate()
        w.wait()
        self.assertEqual((ev["kind"], ev["topic"], ev["receivers"], ev["result"], ev["envelope"]["body"], ev["envelope"]["source"]),
                         ("pub", "alpha", 0, "ok", {"a": 1}, "t"))


class SecondBroker(Base):
    def test_serve_twice_is_8_and_the_first_lives(self):
        p = self.broker()
        r = p.cli("serve")
        self.assertEqual(r.returncode, 8)
        self.assertIn(b"another broker holds", r.stderr)
        self.assertEqual(p.cli("ping").returncode, 0)
        self.assertIsNone(p.proc.poll())

    def test_sigterm_removes_the_socket_and_exits_0(self):
        p = self.broker()
        p.proc.terminate()
        self.assertEqual(p.proc.wait(10), 0)
        self.assertFalse(os.path.exists(p.path))
        self.assertIn("listening on", p.log())

    def test_a_dead_broker_lets_the_next_one_start_at_once(self):
        p = self.broker()
        for _ in range(3):
            p.proc.kill()
            p.proc.wait()
            p.start()
        self.assertEqual(p.cli("ping").returncode, 0)


class Restart(Base):
    def test_restart_signals_the_supervisor_of_the_pid_file(self):
        p = self.idle()
        got = os.path.join(p.dir, "got")
        sup = subprocess.Popen([sys.executable, "-c", "import signal,time,sys\nsignal.signal(signal.SIGUSR1, lambda *a: open(sys.argv[1],'w').write('usr1'))\n"
                                "time.sleep(30)", got])
        self.addCleanup(sup.kill)
        self.assertEqual(p.cli("restart").returncode, 1)               # no pid file yet
        time.sleep(0.3)
        with open(os.path.join(p.dir, "bus-supervisor.pid"), "w") as f:
            f.write("%d\n" % sup.pid)
        r = p.cli("restart")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(wait_for(lambda: os.path.exists(got)))
        for junk in ("", "abc", "1", "999999999"):
            with open(os.path.join(p.dir, "bus-supervisor.pid"), "w") as f:
                f.write(junk)
            self.assertEqual(p.cli("restart").returncode, 1, junk)


class ClientPath(Base):
    def test_the_client_never_imports_asyncio(self):
        p = self.broker()
        code = ("import sys, runpy\nsys.argv = ['swarmbox-bus', sys.argv[1], 'jobs', 'x']\n"
                "try:\n    runpy.run_path(%r, run_name='__main__')\nexcept SystemExit as e:\n    print('rc', e.code)\n"
                "print('asyncio' in sys.modules)" % BUS_PATH)
        r = subprocess.run([sys.executable, "-S", "-c", code, "pub"], env=p.env, capture_output=True, text=True)
        self.assertIn("rc 3", r.stdout)
        self.assertTrue(r.stdout.strip().endswith("False"), r.stdout + r.stderr)

    def test_the_client_starts_fast(self):
        p = self.broker()
        t = []
        for _ in range(20):
            t0 = time.time()
            p.cli("ping")
            t.append(time.time() - t0)
        t.sort()
        median = t[len(t) // 2]
        print("   swarmbox-bus ping, median of 20: %.1f ms" % (median * 1000), file=sys.stderr)
        self.assertLess(median, 0.25, "a CLI call must stay cheap enough for a shell hook")


class Load(Base):
    def test_many_clients_in_parallel_all_delivered_once(self):
        p = self.broker()
        subs = [p.popen("sub", "--raw", "-v", "--group", "w", "jobs") for _ in range(3)]
        for s in subs:
            self.assertIn(b"subscribed", s.stderr.readline())
        n_threads, per = 8, 25
        fails = []

        def work(k):
            for i in range(per):
                r = p.cli("pub", "--source", "t%d" % k, "jobs", "m-%d-%d" % (k, i))
                if r.returncode != 0:
                    fails.append(r.stderr)

        ts = [threading.Thread(target=work, args=(k,)) for k in range(n_threads)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        self.assertEqual(fails, [])
        time.sleep(0.5)
        seen = []
        for s in subs:
            s.terminate()
            out, _ = s.communicate(10)
            seen += out.decode().split()
            s.stderr.close()
        self.assertEqual(len(seen), n_threads * per)
        self.assertEqual(len(set(seen)), n_threads * per, "a message went to two members of one group")

    def test_100_messages_per_second_for_3_seconds_one_process_each(self):
        p = self.broker()
        sub = p.popen("sub", "--raw", "jobs")
        self.assertTrue(wait_for(lambda: p.cli("pub", "jobs", "probe").returncode == 0, 5))
        sub.stdout.readline()
        total, rate = 300, 100
        start = time.time()
        procs = []
        fails = 0
        for i in range(total):
            delay = start + i / rate - time.time()
            if delay > 0:
                time.sleep(delay)
            procs.append(subprocess.Popen([sys.executable, "-S", BUS_PATH, "pub", "jobs", str(i)], env=p.env, stdout=subprocess.DEVNULL))
        for q in procs:
            fails += q.wait(30) != 0
        elapsed = time.time() - start
        self.assertEqual(fails, 0)
        got = []
        sub.stdout.flush()
        end = time.time() + 10
        while len(got) < total and time.time() < end:
            line = sub.stdout.readline()
            if not line:
                break
            got.append(int(line))
        sub.terminate()
        sub.wait()
        print("   %d messages in %.1f s, %d delivered" % (total, elapsed, len(got)), file=sys.stderr)
        self.assertEqual(len(got), total)
        self.assertEqual(sorted(got), list(range(total)))


if __name__ == "__main__":
    unittest.main()
