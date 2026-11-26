"""End to end: an agent declared by one folder works in a real box (docs/agents-design.md, step 10's acceptance), offline.

A box from the image (skipped unless SWARMBOX_IMAGE_BUILD=1; SWARMBOX_IMAGE_TAG reuses an image), with a user-level addon `robo` that is
only an addon folder with agent/agent.conf: a small program that reports its state with OSC 7501 (app=robo-cli), draws on the alternate
screen and logs its arguments. Through the Web Studio's own API (inside the box: curl to 127.0.0.1:7681) and the box's commands:
the registry sees it, the shell function adds its words, New agent starts it and pins it, the box detects it (gateway, swarmbox-tabs,
swarmbox-state), a second agent in the same repository is isolated in a worktree, a prompt is verified by the state it reports, its
reserved prefix is refused, the Allow / Cancel card refuses to guess its keys, a restart resumes it (and a resume that fails at once starts
fresh), and closing a tab cleans its pin and its worktree.

Run with: SWARMBOX_IMAGE_BUILD=1 SWARMBOX_IMAGE_TAG=swarmbox-test-... python3 tests/slow/test_agents_e2e.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "support"))
import image_support  # noqa: E402
from image_support import podman, rnd  # noqa: E402

setUpModule = image_support.setUpModule
tearDownModule = image_support.tearDownModule

ROBO = r'''#!/bin/bash
echo "$(date +%s) cwd=$PWD args=$*" >> "$HOME/robo-argv.log"
[ "${1:-}" = "--yes" ] && shift
if [ "${1:-}" = "--continue" ]; then
    if [ -f "$HOME/.robo-sessions/${PWD//\//_}" ]; then echo "resuming"; else echo "no session here" >&2; exit 3; fi
fi
mkdir -p "$HOME/.robo-sessions" && touch "$HOME/.robo-sessions/${PWD//\//_}"   # outside the folder: a worktree stays clean
st() { printf '\033]7501;state=%s:app=robo-cli\007' "$1"; }
printf '\033[?1049h\033[H\033[2J'
st idle
echo "robo ready in $PWD"
while IFS= read -r line; do
    st working; echo "$line" >> "$HOME/robo-input.log"; sleep 2; st idle
done
'''


def wait_for(fn, seconds=60, step=0.5):
    end = time.time() + seconds
    while time.time() < end:
        v = fn()
        if v:
            return v
        time.sleep(step)
    return fn()


@unittest.skipUnless(image_support.ENABLED, "set SWARMBOX_IMAGE_BUILD=1 (the image is built, or SWARMBOX_IMAGE_TAG reused)")
class DeclaredAgentInABox(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ws = tempfile.mkdtemp(prefix="agents-e2e-")
        d = os.path.join(cls.ws, ".config", "swarmbox", "addons", "robo")
        os.makedirs(os.path.join(d, "agent"))
        files = {
            "addon.conf": 'SCHEMA=1\nNAME=robo\nDESCRIPTION="a test agent"\nVERSION=1.0.0\nCOMMANDS="robo"\n',
            "install.sh": '#!/bin/bash\nset -eu\nmkdir -p "$ADDON_PREFIX/bin"\ncp "$(dirname "$0")/robo.bin" "$ADDON_PREFIX/bin/robo"\n'
                          'chmod 755 "$ADDON_PREFIX/bin/robo"\n',
            "robo.bin": ROBO,
            "agent/agent.conf": 'ID=robo\nLABEL="Robo Agent"\nALIASES="robo-cli"\nCOLOR="#ff8800"\nYOLO_ARGS="--yes"\nRESUME_ARGS="--continue"\n'
                                'PASSTHROUGH="login"\n',
        }
        for rel, text in files.items():
            with open(os.path.join(d, rel), "w") as f:
                f.write(text)
        os.chmod(os.path.join(d, "install.sh"), 0o755)
        proj = os.path.join(cls.ws, "proj")
        os.makedirs(proj)
        for args in (["init", "-q", "-b", "main"], ["-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "init"]):
            subprocess.run(["git"] + args, cwd=proj, check=True)
        cls.name = "swarmbox-test-agents-e2e-" + rnd()
        r = podman("run", "-d", "--name", cls.name, "--userns=keep-id:uid=1000,gid=1000", "-v", cls.ws + ":/home/agent",
                   "--tmpfs", "/tmp/swarmbox", "-e", "SWARMBOX_TEST_NO_NESTED=1", image_support.TAG)
        assert r.returncode == 0, r.stderr
        assert cls.ready(), "the box did not get ready"

    @classmethod
    def tearDownClass(cls):
        podman("rm", "-f", "-t", "0", cls.name)
        shutil.rmtree(cls.ws, ignore_errors=True)

    @classmethod
    def ready(cls):
        return wait_for(lambda: cls.sh("cat /tmp/swarmbox/ready 2>/dev/null"), 120)

    @classmethod
    def sh(cls, cmd, timeout=120):
        r = podman("exec", cls.name, "bash", "-c", cmd, timeout=timeout)
        return r.stdout.decode("utf-8", "replace").strip()

    def api(self, method, path, body=None):
        data = "" if body is None else " -H 'Content-Type: application/json' -d %s" % json.dumps(json.dumps(body))
        out = self.sh("curl -s -X %s -H 'Origin: http://127.0.0.1:7681'%s http://127.0.0.1:7681%s" % (method, data, path))
        try:
            return json.loads(out)
        except ValueError:
            return {"raw": out}

    def tabs(self):
        try:
            return {r["tab"]: r for r in json.loads(self.sh("swarmbox-tabs list"))}
        except ValueError:
            return {}

    def argv_log(self):
        try:
            with open(os.path.join(self.ws, "robo-argv.log")) as f:
                return f.read().splitlines()
        except OSError:
            return []

    def test_the_whole_life_of_a_declared_agent(self):
        # the registry, and the generated shell function (first call installs it through its shim)
        self.sh("swarmbox-addon link --user")
        self.assertIn("robo", self.sh("swarmbox-agents list"))
        self.sh("bash -ic 'robo login me; robo hello </dev/null' >/dev/null 2>&1")
        log = self.argv_log()
        self.assertTrue(any(l.endswith("args=login me") for l in log), log)
        self.assertTrue(any(l.endswith("args=--yes hello") for l in log), log)
        reg = self.api("GET", "/api/agents")
        robo = [a for a in reg["agents"] if a["id"] == "robo"][0]
        self.assertEqual((robo["label"], robo["color"], robo["installed"], robo["icon_svg"]), ("Robo Agent", "#ff8800", True, ""))

        # New agent: started, pinned, detected everywhere
        t = self.api("POST", "/api/tabs", {"preset": "agent", "agent": "robo-cli", "cwd": "/home/agent/proj"})
        addr = t["address"]
        self.assertEqual(t["labels"]["swarmbox.agent"], "robo")
        self.assertEqual(t["pin"]["agent"], "robo")
        row = wait_for(lambda: (self.tabs().get(addr) or {}).get("status") and self.tabs().get(addr), 30)
        self.assertEqual(row["status"]["app"], "robo-cli")
        self.assertEqual(self.sh("swarmbox-agents resolve %s" % row["cmd"]), "robo")
        state = json.loads(self.sh("swarmbox-state --section workspace"))
        self.assertIn(("proj", "robo"), [(r["name"], a.get("agent")) for r in state["repos"] for a in r.get("agents", [])])

        # a second agent in the same repository: the collision is seen, and the new one gets a worktree
        chk = self.api("GET", "/api/worktrees/check?cwd=/home/agent/proj")
        self.assertEqual([x["agent"] for x in chk["collision"]["active_tabs"]], ["robo"])
        t2 = self.api("POST", "/api/tabs", {"preset": "agent", "agent": "robo", "cwd": "/home/agent/proj", "worktree_choice": "new"})
        self.assertIn("/worktrees/proj/", t2["worktree"]["path"])

        # a prompt is verified by the state the agent reports; its reserved prefix is refused; the card does not guess keys
        out = json.loads(self.sh("swarmbox-tabs send %s --run 'fix the login bug'" % addr))
        self.assertIs(out["verified"], True, out)
        wait_for(lambda: (self.tabs().get(addr) or {}).get("status", {}).get("state") == "idle", 20)
        out = json.loads(self.sh("swarmbox-tabs send %s --run '/clear'" % addr))
        self.assertEqual(out.get("err"), "slash_refused", out)
        r = self.sh("curl -s -o /dev/null -w '%%{http_code}' -X POST -H 'Origin: http://127.0.0.1:7681' -H 'Content-Type: application/json' "
                    "-d '{\"decision\":\"deny\"}' http://127.0.0.1:7681/api/tabs/%s/answer" % addr)
        self.assertEqual(r, "409")

        # closing the second tab removes its pin and its empty worktree
        closed = self.api("DELETE", "/api/tabs/%s" % t2["address"])
        self.assertTrue(closed.get("auto_cleaned_worktree"), closed)

        # a restart resumes the pinned agent in its folder
        podman("stop", "-t", "10", self.name, timeout=60)
        podman("start", self.name, timeout=60)
        self.assertTrue(self.ready())
        self.assertTrue(wait_for(lambda: any(l.endswith("cwd=/home/agent/proj args=--yes --continue") for l in self.argv_log()), 60),
                        self.argv_log())

        # a pin in a folder without a session: the resume fails at once and a fresh one starts
        os.makedirs(os.path.join(self.ws, "fresh"), exist_ok=True)
        pin = self.api("POST", "/api/pins", {"cwd": "/home/agent/fresh", "agent": "robo", "title": "fresh"})["pin"]
        self.api("POST", "/api/pins/%s/wake" % pin["id"], {})
        self.assertTrue(wait_for(lambda: [l for l in self.argv_log() if "cwd=/home/agent/fresh" in l][-2:] and
                                 [l.split("args=")[1] for l in self.argv_log() if "cwd=/home/agent/fresh" in l][-2:] == ["--yes --continue", "--yes"],
                                 30), self.argv_log())


if __name__ == "__main__":
    unittest.main(verbosity=2)
