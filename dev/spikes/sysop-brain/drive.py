"""drive.py OUTDIR GOAL [--cfg DIR] [--home DIR] [--cwd DIR] [--sigint-after-say] [--resume SID] [--model M] [--extra ARG]... :
runs the brain invocation of the design with stdout on a PIPE, timestamps every line (OUTDIR/stream.tsv), the fake MCP server logs to OUTDIR/mcp.jsonl."""
import argparse, json, os, signal, subprocess, sys, time
S = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ap = argparse.ArgumentParser()
ap.add_argument("out"); ap.add_argument("goal")
ap.add_argument("--cfg"); ap.add_argument("--home"); ap.add_argument("--cwd")
ap.add_argument("--resume"); ap.add_argument("--model", default="sonnet")
ap.add_argument("--sigint-after-say", action="store_true")
ap.add_argument("--run-sleep", default="0")
ap.add_argument("--extra", action="append", default=[])
ap.add_argument("--no-hermetic-flags", action="store_true")
ap.add_argument("--wrap", default="")
a = ap.parse_args()
a.out = os.path.abspath(a.out)
os.makedirs(a.out, exist_ok=True)
mcp_log = os.path.join(a.out, "mcp.jsonl")
mcp = {"mcpServers": {"sysop": {"command": sys.executable, "args": [os.path.join(S, "bin", "fake_mcp.py")],
       "env": {"SPIKE_MCP_LOG": mcp_log, "RUN_SLEEP": a.run_sleep, "FROM_MCP_JSON": "1"}}}}
mcp_path = os.path.join(a.out, "mcp.json")
json.dump(mcp, open(mcp_path, "w"))
tok = os.environ["CLAUDE_CODE_OAUTH_TOKEN"]   # the box login; never written to disk by the harness
env = {"PATH": os.environ["PATH"], **({"TMPDIR": os.environ["SPIKE_TMPDIR"]} if os.environ.get("SPIKE_TMPDIR") else {}), "HOME": a.home or os.environ["HOME"], "LANG": "C.UTF-8", "CLAUDE_CODE_OAUTH_TOKEN": tok, "BRAIN_SECRET_PROBE": "x"}
if a.cfg:
    env["CLAUDE_CONFIG_DIR"] = a.cfg
argv = ["claude", "-p", "--model", a.model, "--mcp-config", mcp_path, "--strict-mcp-config", "--tools", "", "--allowedTools", "mcp__sysop__*",
        "--permission-mode", "dontAsk", "--system-prompt", "You are a test operator. Use only the sysop tools. Follow the goal exactly.",
        "--output-format", "stream-json", "--include-partial-messages", "--verbose"] + a.extra
if a.resume:
    argv += ["--resume", a.resume]
cwd = a.cwd or a.out
if a.wrap:
    argv = [sys.executable, os.path.join(S, 'bin', 'landlock_exec.py'), a.wrap, '--'] + argv
t0 = time.time()
p = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=open(os.path.join(a.out, "err.txt"), "wb"), cwd=cwd, env=env, start_new_session=True)
p.stdin.write((a.goal + "\n").encode()); p.stdin.close()
out = open(os.path.join(a.out, "stream.tsv"), "w")
out.write("0\t#T0 %.6f\n" % t0)
sent_int = False
import threading
peak = {"rss": 0, "vsz": 0, "thr": 0, "procs": 0}
def sample():
    while p.poll() is None:
        try:
            pids = [int(x) for x in os.listdir('/proc') if x.isdigit()]
            grp = [q for q in pids if open('/proc/%d/stat' % q).read().rsplit(')', 1)[1].split()[2] == str(p.pid)]
            rss = vsz = thr = 0
            for q in grp:
                st = dict(l.split(':', 1) for l in open('/proc/%d/status' % q) if ':' in l)
                rss += int(st['VmRSS'].split()[0]); vsz += int(st['VmSize'].split()[0]); thr += int(st['Threads'])
            peak.update(rss=max(peak['rss'], rss), vsz=max(peak['vsz'], vsz), thr=max(peak['thr'], thr), procs=max(peak['procs'], len(grp)))
        except Exception:
            pass
        time.sleep(0.05)
threading.Thread(target=sample, daemon=True).start()
for raw in p.stdout:
    t = time.time() - t0
    line = raw.decode("utf-8", "replace").rstrip("\n")
    out.write("%.3f\t%s\n" % (t, line)); out.flush()
    if a.sigint_after_say and not sent_int and os.path.exists(mcp_log) and '"name": "say"' in open(mcp_log).read() and '"end"' in open(mcp_log).read():
        os.killpg(p.pid, signal.SIGINT); sent_int = True
        out.write("%.3f\t#SIGINT\n" % (time.time() - t0))
rc = p.wait()
out.write("%.3f\t#EXIT %d\n" % (time.time() - t0, rc))
print("rc", rc, "secs %.1f" % (time.time() - t0), "peak RSS %d MB, VSZ %d MB, threads %d, procs %d" % (peak["rss"]//1024, peak["vsz"]//1024, peak["thr"], peak["procs"]))
