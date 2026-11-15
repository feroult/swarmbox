# Spike: the transport of `swarmbox-bus`

Code: `dev/spikes/bus/swarmbox-bus` (broker and CLI in one file, standard library only, about 330 lines) and `dev/spikes/bus/test_bus.py`
(about 40 checks plus measurements; `python3 test_bus.py`, no tmux, no network; prints `FAILURES: 0`). It ran on the master box (python 3.13.5)
and in the Podman image `swarmbox-sysop-test` (same result). tmux and state are stubs (a driver callback and a state callback in `serve()`).

Verdict: it works; the choices below are the ones to build with.

## 1. Design

- **asyncio, one process, one thread for the loop.** There is no shared state to lock (queues, watchers, round-robin position are plain lists in one loop);
  a dead peer is an EOF on a read that is already pending; a slow peer is a write-buffer size. With threads each of those needs a lock or a
  timeout. Blocking callbacks (tmux calls) go through `run_in_executor`. Only `serve` imports asyncio (29 ms); the client path does not (see 3).
- **Protocol:** one JSON line per request. `pub`, `get`, `ls`: one reply line (`{"ok":true,...}` or `{"ok":false,"err":"<code>"}`), then close.
  `sub`, `watch`: one `{"ok":true,"subscribed":...}` line (so the client knows it is registered), then one envelope per line until either side closes.
- **Topics:** `goal` (queue), `tab/<tab>/in` (the driver, answered by its result), anything else is `bad_topic`. `get`/`ls` accept `tab/...`.
- **Exit codes of the CLI:** 0 ok, 1 other error, 2 usage, 3 no subscriber, 4 broker not running (or it went away), 5 too large, 6 bad topic or unknown state,
  7 busy (only subscribers are too slow), 8 broker already running (`serve`).
- **Socket:** umask 0177 around `bind` and a `chmod 0600`; the broker also checks `SO_PEERCRED` and refuses a uid that is neither its own nor root.
  Path: `$SB_BUS_SOCKET`, else `$SB_RUN_DIR/bus.sock`, else `/tmp/swarmbox/bus.sock`. (The client must not source `dirs.sh`; the default is the same constant.)
- **Single instance and stale socket:** the broker takes `flock(LOCK_EX|LOCK_NB)` on `bus.sock.lock` (the kernel releases it however the process dies).
  Holding it, any socket file left there is stale and is unlinked before bind. Tested: 5 brokers started at once on a fresh path leave exactly one; a second
  broker exits 8 and the first is untouched; after `kill -9` the stale file stays, clients get exit 4 (not a hang, not a traceback), and a new broker takes over.
  Probing with `connect()` instead of a lock was rejected: it has a race between the probe and the bind.
- **Clients that die:** connect-and-close, half a line then close, garbage: the broker lives and answers `bad_request`. A dead subscriber is removed when its
  EOF is read (measured: before the next CLI can even start; see the window below).
- **Big messages:** a line is limited to 1 MiB (`MAX_LINE`), checked by the client (exit 5, before sending) and by the broker (`too_large`, then close, and it
  survives). 900 KiB (the pipe buffer is 64 KiB) arrives whole. **Gotcha: Linux limits one argv string to 128 KiB (`MAX_ARG_STRLEN`), so a big
  body must go by stdin (`pub goal -`); the voice service should use the socket directly or `-`.**
- **Slow subscriber:** never reads, with a 4 KiB receive buffer: 30 publishes of 500 KiB took 0.6 s in total (nothing blocks); the broker buffers up to 4 MiB
  for it (`SLOW_BUFFER`), after that that subscriber is skipped. A slow *watcher* is disconnected at that point. With only a slow subscriber, `pub goal` fails
  with exit 7 (`busy`); a healthy subscriber next to it keeps receiving. Memory is bounded by about 4 MiB per slow peer plus one message.
- **100 messages per second** for 3 s, one `swarmbox-bus pub` process per message: 300 of 300 delivered, order kept per connection.
- **`watch`:** every `pub` (also the failed ones, with `result` `ok`, `no_subscriber`, `busy`, `no_such_tab`) and every `get`/`ls` with its result. `watch --no-screen`
  replaces the screen text by `<N bytes omitted>` in the read events (done in the broker, so a screen never reaches that client). Default for the build:
  `--no-screen` is the safe one to show on a panel; full contents only on explicit request.

## 2. Queue semantics

- Two subscribers on `goal`: the broker rotates the subscriber list; 10 messages gave 5 and 5 (strict round robin, so the oldest-idle rule is not needed).
  Each message goes to exactly one, never both.
- A subscriber that dies **after** receiving and **before** handling: the message is lost. Measured separately: a subscriber killed with -9 and a `pub` right after
  (40 trials, one of two subscribers): 0 lost, because the broker reads the EOF in microseconds, well before a CLI process can start (13 ms). The only loss window is the
  time between the kernel accepting the bytes and the subscriber acting on them (crash while planning, a restart in the middle).
- **Recommendation: no ack in version 1.** `pub` returns 0 meaning "handed to a live subscriber's socket", never "done". An ack that means anything needs the
  subscriber to ack after handling, a timeout, a redelivery and idempotent goals, which is a buffer by another name and is against "nothing is buffered". The rule that is safe:
  (a) `pub` fails at once (exit 3 or 7) when nobody can take it, so the voice page tells the user right away; (b) the sysop writes the goal in its panel the moment it reads
  it, before planning, so a crash leaves a visible last goal and the user repeats it; (c) `watch` has the full log of what was published. If it hurts later, add an optional
  `pub --ack`, in which the subscriber replies `ack <id>` on its connection and `pub` waits for it with a timeout: the protocol leaves room for it (new field in the request).

## 3. Latency and the cost of the CLI

Persistent sockets, pub to sub: median 0.11 ms, p99 0.30 ms. `swarmbox-bus pub` as a process, start to exit: median 13.0 ms (p95 14 ms) against 6.0 ms for
`python3 -c pass` (shebang `python3 -S`, no site, no asyncio, imports only `json socket os sys time`; `import asyncio` alone is 29 ms, so it must stay out of the client).
Enough to call it per message from a shell hook or from a service (100 per second worked). Through `podman exec` from the host it is about 130 ms, nearly all of which is `podman exec`
itself (120 ms for `true`). A resident service that publishes often (voice) should talk to the socket directly with a 10 line client instead of forking.

## 4. Starting with the box

`entrypoint.sh serve` today: step 3 (folders, run folder), 5 (ssh key), 6 (`swarmbox-tool link`), 7 (`mcp generate`, then `swarmbox-tool prepare`), 8 (nested podman), 9 (tmux), 10 (ttyd supervisor),
11 (ready marker), 12 (WITH installs in the background).

- **New step, between 6 and 7 (call it 6b), `[W]`:** start the broker before `prepare`, because prepares may start subscribers and publishers. It needs the run folder (step 3) and not tmux
  (step 9), since the driver and the state reads call tmux lazily when asked and answer an error when there is no session. A failure is a `[W]` (warning and health line, the box still starts: "nothing of the host depends on the bus").
- **Restart policy: the same as ttyd's `supervise`**, generalised to `supervise_one <name> <health line> <cmd...>`: restart after 1, 2, 4 ... 30 s; 5 exits within 60 s: health line, idle until
  `swarmbox-bus restart` (USR1). Run it in the background with its pid in `$SB_RUN_DIR/bus-supervisor.pid`, and add it to `stop_children` (SIGTERM; the broker removes its socket on SIGTERM).
  The flock makes a second start harmless (exit 8, which the supervisor must treat as "someone else runs it": stop, not loop). Wait up to 2 s for the socket to accept before going on (poll `connect`), so that step 7 can publish.
- **Where the socket lives:** `$SB_RUN_DIR/bus.sock` (add `SB_BUS_SOCK=$SB_RUN_DIR/bus.sock` to `dirs.sh`; the run folder is tmpfs, regenerated at each start, so a stale socket after a *box* restart cannot exist; after a
  broker crash it can, and the flock rule handles it). Do not put it in the state folder, which is on the workspace volume and survives. The log: `$SB_STATE_DIR/bus.log`.
  The run folder is `1777`: the 0600 mode and the peer check are what keep other users out; `serve` must create files with the agent user, not root.
- **A resident subscriber (the sysop) in its `prepare.sh`:** `prepare_tool` runs `exec timeout -k 2 $PREPARE_TIMEOUT bash prepare.sh`, so a child started normally is killed with it. `prepare.sh` must
  start a detached small supervisor (`setsid nohup swarmbox-sysop run </dev/null >>log 2>&1 &`, the same restart loop as above, pid file in `$SB_RUN_DIR/sysop.pid`) and return at once; it is idempotent: if the pid file's process is
  alive, do nothing (prepare also runs after `plugin install`). The subscriber must **reconnect with backoff** when its connection closes (a broker restart is an EOF), because `sub` does not retry (it exits 4, on purpose, so shell users see it).
- **Goals while the sysop restarts:** there is no subscriber, so `pub goal` fails with exit 3 for the 1 to 30 s of the backoff (the first retry is at 1 s). Nothing is queued, nothing is replayed. Voice shows "nobody is listening" and the user repeats it.
  This is the stated design; the only mitigation worth it is that the sysop's loop reconnects first and then does the slow work (load the planner), so the gap is the restart and not the start-up.

## 5. Host forwarding

`attach_main` in `container/host/swarmbox-host` (about line 2738) does `pubkey|tool) exec podman exec "$a_t" -e TERM -e COLORTERM "$a_name" swarmbox-entrypoint "$@"`.
`bus` is a third word of that `case` (and the help text and the word list that decides "this is a command, not a program to run"), and `entrypoint.sh` gets `bus) forward swarmbox-bus "$@"`
(the `forward` helper `exec`s, so exit code and signals are the program's own). Tested through a real `podman exec -i` into a container: exit code 3 comes out as 3, stdout and stderr are
separate, stdin works (`echo '{"run":"ls"}' | podman exec -i ... swarmbox-bus pub tab/main/in -` prints the id), and `-it` is only used with a terminal, as `attach_main` already does. `watch` and `sub` stream until Ctrl-C.
Two notes: `attach_main` runs `cmd_up` first (starts the box if it is stopped; for `bus` that is acceptable but `pub goal` on a stopped box then fails with 3 or 4, which is the truth);
and `SB_BUS_SOCKET` must not be forwarded from the host (the path is in the box).

## 6. The envelope

```json
{"v":1,"id":"a02557-2","topic":"goal","source":"voice","peer":{"pid":66000,"uid":1000},"time":"2026-11-15T03:59:19.977Z","body":{"text":"run the tests"}}
```

- `v`: 1, the version of the envelope; a subscriber ignores unknown fields and refuses a larger `v`.
- `id`: set by the broker, `<boot id, 6 hex>-<counter>`; unique per broker run, ordered; not a secret.
- `topic`, `time` (UTC, ms), `body` (any JSON value; plain text on the CLI is a JSON string; the convention for `goal` is `{"text": "..."}`): `topic` and `body` come from the sender, `time` and `id` from the broker.
- Size: the whole line at most 1 MiB.
- **`source`:** a short label (at most 64 chars) **declared by the client** (`--source voice` or the env var `SB_BUS_SOURCE`, default `cli`). **It can be forged** by any process of the box: it is for
  display, audit and routing the answer, never for authorization. The broker adds `peer` (`pid`, `uid`) from `SO_PEERCRED`, which the sender cannot forge, but inside the box every process is the same
  uid (the agent user, which also has passwordless sudo), so `peer` only says which process, not whether it is entitled. Trust given: any process of the box that can open the socket may publish anything: exactly
  what it already has with `tmux send-keys`. The socket is not reachable from outside the box (not published; the web tunnel does not proxy it). What the policy cannot assume: that `source=voice` really came from voice. Therefore
  the sysop's confirmations must depend on what a goal asks, never on who claims to have sent it. (If an input must be authenticated later, the way is a per-plugin socket or a token in a file readable only by that plugin; not in v1.)

## Not tested

- A client of another uid (rootless Podman here would not allow `setpriv`; covered by the 0600 mode and the `SO_PEERCRED` check, not exercised).
- The real tmux driver and screen reads (stubbed), the real `entrypoint.sh` step and the supervisor code (designed, not written), a real plugin `prepare.sh` start of a detached subscriber, a broker restart with a reconnecting subscriber.
- Behaviour with a full `/tmp` tmpfs, and thousands of subscribers (not needed).
