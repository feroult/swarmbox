"""Spike B4: does ttyd serve only a single-file page (`--index`)?

Design claim (5.1): ttyd serves a single file as the page; a page of several files must be inlined or fronted by a
small server. Runs the box's ttyd on 127.0.0.1 (random port 20000-40000) with --index pointing at a page that
references style.css and app.js placed beside it, and requests those assets. Also reads ttyd's own --help.
ttyd is started and stopped by this script (its own PID only); nothing is created in podman.
Run: python3 tests/spikes/spike_b4_ttyd_index.py   Exit 1 if a claim is contradicted.
"""
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import spikes_common as sc  # noqa: E402


def get(port, path):
    try:
        with urllib.request.urlopen("http://127.0.0.1:%d%s" % (port, path), timeout=5) as r:
            return r.status, r.headers.get("Content-Type", ""), r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("Content-Type", ""), e.read()


def main():
    sp = sc.Spike("b4")
    d = sp.mkdtemp("b4")
    page = ("<html><head><link rel=stylesheet href=style.css><script src=app.js></script></head>"
            "<body>SECOND-FILE-TEST</body></html>")
    for n, c in (("index.html", page), ("style.css", "body{}"), ("app.js", "//x"), ("other.txt", "hello")):
        with open(os.path.join(d, n), "w") as f:
            f.write(c)
    ver = subprocess.run(["ttyd", "--version"], capture_output=True, text=True).stdout.strip()
    helptext = subprocess.run(["ttyd", "--help"], capture_output=True, text=True)
    hl = [l for l in (helptext.stdout + helptext.stderr).splitlines() if "--index" in l]
    print("  %s; help line: %s" % (ver, hl[0].strip() if hl else "(none)"))
    sp.expect("ttyd documents --index as 'Custom index.html path' (a path to one file)",
              bool(hl) and "index.html path" in hl[0], repr(hl))
    port = sp.free_port()
    p = subprocess.Popen(["ttyd", "-i", "127.0.0.1", "-p", str(port), "-I", os.path.join(d, "index.html"),
                          "-W", "true"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    sp.pids.append(p.pid)
    for _ in range(50):
        try:
            get(port, "/")
            break
        except OSError:
            time.sleep(0.1)
    code, ctype, body = get(port, "/")
    sp.expect("GET / serves the --index file", code == 200 and b"SECOND-FILE-TEST" in body, "%s %s" % (code, ctype))
    for path in ("/style.css", "/app.js", "/other.txt", "/index.html"):
        code, ctype, _ = get(port, path)
        print("  GET %-12s -> %s %s" % (path, code, ctype))
        sp.expect("GET %s (a file beside the index) is not served: 404" % path, code == 404, str(code))
    code, ctype, body = get(port, "/token")
    sp.expect("ttyd's own /token endpoint still answers (the page's own protocol is unaffected)",
              code == 200 and b"token" in body, str(code))
    p.terminate()
    p.wait(timeout=5)
    tag = sc.evidence("host ttyd (%s, the box's binary) started on a random 127.0.0.1 port with -I; HTTP requests"
                      % ver, "the live box's /usr/local/bin/ttyd, no container", reduced="no container")
    return sp.finish(tag, "ttyd serves only the one --index file; every sibling path is 404")


if __name__ == "__main__":
    sys.exit(main())
