#!/usr/bin/env python3
"""Records what v0.1.0's start.sh passes to `podman run` for each old flag of design 12.3 (slice 6.1).

Run: python3 tests/record_v010_flags.py > tests/fixtures/v0.1.0-run-flags.json

The old tree is taken from the git tag with `git archive v0.1.0` (never from the working tree, so this keeps working after
start.sh and lib/ are deleted in slice 6.2), unpacked in a mktemp folder, and run against the shared FakePodman with
`--no-shell`. The workspace folder is replaced by @WS@ and every `--flag=value` is split into `--flag`, `value`, so the
comparison with the 2.0 flags (tests/test_parity.py) is about meaning, not spelling. The fixture is committed; this script only
documents where it came from and regenerates it. It never touches the real home or a real container.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import ROOT, FakePodman  # noqa: E402

CASES = [
    ("default", [], {}),
    ("ports", ["--ports", "3000,8080:80"], {}),
    ("hostname", ["--hostname", "myhost"], {}),
    ("tz", [], {"SWARMBOX_TZ": "Europe/Paris"}),
    ("init", [], {"SWARMBOX_INIT": "1"}),
    ("remote-browser", ["--remote-browser", "10.0.0.5:9222"], {}),
    ("remote-browser-bare", ["--remote-browser"], {}),
    ("clasp", ["--clasp"], {}),
    ("env-keys", ["--env-keys", "A,B"], {"A": "1"}),
    ("iports", ["--iports", "8000"], {}),
    ("web", ["--web"], {}),
    ("host-network", ["--host-network"], {}),
]


def normalize(argv, ws):
    out = []
    for a in argv:
        a = a.replace(ws, "@WS@")
        if a.startswith("--") and "=" in a:
            k, v = a.split("=", 1)
            out += [k, v]
        else:
            out.append(a)
    return out


def main():
    tree = tempfile.mkdtemp(prefix="swarmbox-test-v010.")
    try:
        tar = subprocess.run(["git", "-C", ROOT, "archive", "v0.1.0"], capture_output=True, check=True).stdout
        subprocess.run(["tar", "-x", "-C", tree], input=tar, check=True)
        result = {}
        for cid, args, env in CASES:
            work = tempfile.mkdtemp(prefix="swarmbox-test-v010w.")
            try:
                ws = os.path.join(work, ".work")
                os.makedirs(os.path.join(ws, ".swarmbox"))
                open(os.path.join(ws, ".swarmbox", "podman.sock"), "w").close()
                with FakePodman({"images": {"stdout": "img1\n"}}) as fp:
                    e = fp.env(**{"HOME": work, "SWARMBOX_INIT": "0", **env})
                    r = subprocess.run(["bash", os.path.join(tree, "start.sh"), "--no-shell", *args], cwd=work, env=e,
                                       capture_output=True, text=True, timeout=60)
                    runs = [c for c in fp.calls() if c[0] == "run"]
                result[cid] = {"args": args, "env": env, "exit": r.returncode,
                               "flags": normalize(runs[0][1:], ws) if runs else None,
                               "stderr_tail": r.stderr.strip().splitlines()[-1:] }
            finally:
                shutil.rmtree(work, True)
        json.dump(result, sys.stdout, indent=1, sort_keys=True)
        sys.stdout.write("\n")
    finally:
        shutil.rmtree(tree, True)


if __name__ == "__main__":
    main()
