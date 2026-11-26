"""Fast tests of the agent registry: swarmbox_agents.py (Python) and agents.mjs (Node) against the same vectors
(tests/support/fixtures/agents/cases.json), the agent/ contract of the repository's addons, the `swarmbox-agents` command and the
checks that `swarmbox-addon validate` runs on an agent/ folder.
Run with: python3 -W error tests/fast/test_agents_registry.py
"""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPTS = os.path.join(ROOT, "container", "scripts")
ADDONS = os.path.join(ROOT, "container", "addons")
AGENTS_MJS = os.path.join(ROOT, "container", "web", "herdr", "agents.mjs")
CASES = os.path.join(ROOT, "tests", "support", "fixtures", "agents", "cases.json")

spec = importlib.util.spec_from_file_location("swarmbox_agents", os.path.join(SCRIPTS, "swarmbox_agents.py"))
A = importlib.util.module_from_spec(spec)
spec.loader.exec_module(A)

with open(CASES, encoding="utf-8") as _f:
    VEC = json.load(_f)

NODE_HARNESS = r"""
import * as A from %(mjs)s;
import fs from 'node:fs';
const job = JSON.parse(fs.readFileSync(0, 'utf8'));
const out = { resolve: [], default: [], detect: [], launch: [] };
const base = job.env;
for (const [name] of job.vec.resolve) out.resolve.push(A.resolveAgent(name, base));
for (const c of job.vec.default) out.default.push(A.defaultAgent({ ...job.homes[out.default.length], ...c.env }));
for (const c of job.vec.detect) out.detect.push([A.detectAgent(c.term, {}, base), A.detectAgent(c.term, { live: true }, base)]);
for (const c of job.vec.launch) out.launch.push(A.launchScript(c.id, { resume: c.resume }, base));
out.argv = job.vec.argv.map((c) => A.buildAgentArgv(c.agent, c.resume, { ...base, ...c.env }));
out.ids = A.listAgents(base).map((a) => a.id);
out.parse = A.parseConf(job.conf_text);
process.stdout.write(JSON.stringify(out));
"""

TRICKY_CONF = '# a comment\nID=x\n  LABEL="Two words"  \nBAD LINE\nCMD=$(rm)\nALIASES="a b  c"\nQ="say "hi""\nEMPTY=\n'


class World:
    """A temporary world: the repository's addons as the image level, a user level with the agent `fakebot`, and one HOME per need."""

    def __init__(self, tmp):
        self.tmp = tmp
        self.user = os.path.join(tmp, "user-addons")
        self.image_state = os.path.join(tmp, "image-state")
        os.makedirs(self.image_state)
        fb = os.path.join(self.user, "fakebot")
        os.makedirs(os.path.join(fb, "agent"))
        with open(os.path.join(fb, "addon.conf"), "w") as f:
            f.write('SCHEMA=1\nNAME=fakebot\nDESCRIPTION="a test agent"\nVERSION=1.0\nCOMMANDS="fbot"\n')
        with open(os.path.join(fb, "agent", "agent.conf"), "w") as f:
            f.write('ID=fakebot\nCMD=fbot\nALIASES="fake-bot"\nLABEL="Fake Bot"\n')

    def env(self, home, installed=()):
        os.makedirs(home, exist_ok=True)
        for name in installed:
            sub = "current" if name in ("opencode", "fakebot") else "self"
            d = os.path.join(home, ".local", "share", "swarmbox", "addons", name, sub)
            os.makedirs(d, exist_ok=True)
            open(os.path.join(d, ".swarmbox-env"), "w").close()
        return {"HOME": home, "PATH": "/usr/bin:/bin", "SWARMBOX_TEST_IMAGE_ADDONS": ADDONS,
                "SWARMBOX_TEST_USER_ADDONS": self.user, "SWARMBOX_TEST_IMAGE_STATE": self.image_state}


class RegistryVectors(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="sbagents-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.w = World(self.tmp)
        self.env = self.w.env(os.path.join(self.tmp, "home"))
        self.homes = [self.w.env(os.path.join(self.tmp, "home-%d" % i), c["installed"]) for i, c in enumerate(VEC["default"])]

    def python_results(self):
        out = {"resolve": [A.resolve(n, self.env) for n, _ in VEC["resolve"]],
               "default": [A.default_agent(dict(self.homes[i], **c["env"])) for i, c in enumerate(VEC["default"])],
               "detect": [[A.detect(c["term"], self.env), A.detect(c["term"], self.env, live=True)] for c in VEC["detect"]],
               "launch": [A.launch_script(c["id"], c["resume"], self.env) for c in VEC["launch"]],
               "argv": [A.build_argv(c["agent"], c["resume"], dict(self.env, **c["env"])) for c in VEC["argv"]],
               "ids": A.ids(self.env)}
        vals, probs = A.parse_conf(TRICKY_CONF)
        out["parse"] = {"values": vals, "problems": probs}
        return out

    def check(self, got, who):
        for (name, want), g in zip(VEC["resolve"], got["resolve"]):
            self.assertEqual(g, want, "%s resolve(%r)" % (who, name))
        for c, g in zip(VEC["default"], got["default"]):
            self.assertEqual(g, c["want"], "%s default %r installed %r" % (who, c["env"], c["installed"]))
        for c, (g, gl) in zip(VEC["detect"], got["detect"]):
            self.assertEqual(g, c["want"], "%s detect %r" % (who, c["term"]))
            self.assertEqual(gl, c["live"], "%s live detect %r" % (who, c["term"]))
        for c, g in zip(VEC["launch"], got["launch"]):
            self.assertEqual(g, c["want"], "%s launch %r" % (who, c))
        for c, g in zip(VEC["argv"], got["argv"]):
            self.assertEqual(g, c["want"], "%s argv %r" % (who, c))
        self.assertEqual(got["ids"], ["agy", "claude", "fakebot", "opencode"], who)

    def test_python_library_meets_the_vectors(self):
        self.check(self.python_results(), "python")

    def test_node_library_meets_the_same_vectors_and_parses_like_python(self):
        if not shutil.which("node"):
            self.skipTest("node is not installed")
        job = {"vec": VEC, "env": self.env, "homes": self.homes, "conf_text": TRICKY_CONF}
        js = NODE_HARNESS % {"mjs": json.dumps(AGENTS_MJS)}
        p = subprocess.run(["node", "--input-type=module", "-e", js], input=json.dumps(job), capture_output=True, text=True, timeout=60)
        self.assertEqual(p.returncode, 0, p.stderr)
        got = json.loads(p.stdout)
        self.check(got, "node")
        py = self.python_results()["parse"]
        self.assertEqual(got["parse"], py)
        self.assertEqual(py["values"], {"ID": "x", "LABEL": "Two words", "ALIASES": "a b  c", "EMPTY": ""})
        self.assertEqual(len(py["problems"]), 3, py["problems"])   # BAD LINE, the $, the quotes inside

    def test_a_user_addon_without_agent_hides_the_image_agent_of_the_same_name(self):
        d = os.path.join(self.w.user, "claude")
        os.makedirs(d)
        with open(os.path.join(d, "addon.conf"), "w") as f:
            f.write('NAME=claude\nCOMMANDS="claude"\n')
        self.assertEqual(A.resolve("claude", self.env), "")
        self.assertEqual(A.resolve("agy", self.env), "agy")

    def test_a_pseudo_agent_id_is_never_registered(self):
        d = os.path.join(self.w.user, "evil")
        os.makedirs(os.path.join(d, "agent"))
        with open(os.path.join(d, "addon.conf"), "w") as f:
            f.write('NAME=evil\nCOMMANDS="yolo"\n')
        with open(os.path.join(d, "agent", "agent.conf"), "w") as f:
            f.write("ID=yolo\n")
        self.assertNotIn("yolo", A.ids(self.env))
        self.assertEqual(A.resolve("evil", self.env), "")

    def test_installed_follows_the_install_record_and_a_self_updating_program(self):
        home = os.path.join(self.tmp, "h2")
        env = self.w.env(home, ["opencode"])
        self.assertEqual(A.ids(env, installed_only=True), ["opencode"])
        b = os.path.join(home, ".local", "bin")
        os.makedirs(b)
        with open(os.path.join(b, "claude"), "w") as f:
            f.write("#!/bin/sh\n")
        os.chmod(os.path.join(b, "claude"), 0o755)
        A._CACHE.clear()
        self.assertEqual(A.ids(env, installed_only=True), ["claude", "opencode"])

    def test_a_changed_manifest_is_seen_at_once(self):
        self.assertEqual(A.resolve("fake-bot", self.env), "fakebot")
        p = os.path.join(self.w.user, "fakebot", "agent", "agent.conf")
        with open(p, "w") as f:
            f.write('ID=fakebot\nCMD=fbot\nALIASES="robot"\nLABEL="Fake Bot 2"\n')
        os.utime(p, ns=(1, 1))
        self.assertEqual(A.resolve("robot", self.env), "fakebot")
        self.assertEqual(A.resolve("fake-bot", self.env), "")


class RepositoryAgents(unittest.TestCase):
    """The contract of the agent addons of the repository."""

    def test_every_agent_folder_passes_the_check_and_the_agents_are_the_expected_ones(self):
        found = []
        for name in sorted(os.listdir(ADDONS)):
            d = os.path.join(ADDONS, name)
            if os.path.isdir(os.path.join(d, "agent")):
                self.assertEqual(A.check_dir(d), [], name)
                found.append(name)
        self.assertEqual(found, ["antigravity", "claude", "opencode"])

    def test_no_two_agents_share_a_name(self):
        env = {"HOME": tempfile.gettempdir(), "SWARMBOX_TEST_IMAGE_ADDONS": ADDONS, "SWARMBOX_TEST_USER_ADDONS": "/nonexistent"}
        seen = {}
        for a in A.agents(env):
            for n in [a["id"]] + a["aliases"]:
                self.assertNotIn(n, seen, "%s is a name of %s and of %s" % (n, seen.get(n), a["id"]))
                seen[n] = a["id"]


class CheckAndCommand(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="sbagents-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def addon(self, conf, icon=None, files=None):
        d = os.path.join(self.tmp, "addons", "bot")
        os.makedirs(os.path.join(d, "agent"), exist_ok=True)
        with open(os.path.join(d, "addon.conf"), "w") as f:
            f.write('SCHEMA=1\nNAME=bot\nDESCRIPTION="x"\nVERSION=1.0\nCOMMANDS="bot"\n')
        with open(os.path.join(d, "install.sh"), "w") as f:
            f.write("#!/bin/sh\nexit 0\n")
        os.chmod(os.path.join(d, "install.sh"), 0o755)
        with open(os.path.join(d, "agent", "agent.conf"), "w") as f:
            f.write(conf)
        if icon is not None:
            with open(os.path.join(d, "agent", "icon.svg"), "w") as f:
                f.write(icon)
        for rel, txt in (files or {}).items():
            with open(os.path.join(d, "agent", rel), "w") as f:
                f.write(txt)
        return d

    def test_check_reports_every_kind_of_problem(self):
        d = self.addon('ID=bot\nCMD=other\nCOLOR=red\nFOO=1\nNAMER="x {nope}"\nRESUME_FAST_FAIL_S=soon\nSTATUS=maybe\nALIASES="Bad"\n',
                       icon='<svg onload="alert(1)"></svg>', files={"screen.py": "def other():\n    pass\n", "settings.json": "[1]"})
        errs = "\n".join(A.check_dir(d))
        for frag in ("CMD 'other'", "COLOR", "unknown key FOO", "{nope}", "RESUME_FAST_FAIL_S", "STATUS", "ALIASES entry 'Bad'",
                     "event handler", "does not define state()", "settings.json is not a JSON object"):
            self.assertIn(frag, errs)

    def test_a_good_agent_folder_has_no_problem_and_no_folder_is_not_an_agent(self):
        d = self.addon('ID=bot\nLABEL="Bot"\nCOLOR="#112233"\nRESUME_ARGS="--continue"\n', icon='<svg viewBox="0 0 16 16"></svg>',
                       files={"screen.py": "def state(rows):\n    return 'unknown'\n"})
        self.assertEqual(A.check_dir(d), [])
        shutil.rmtree(os.path.join(d, "agent"))
        self.assertEqual(A.check_dir(d), [])

    def test_swarmbox_addon_validate_fails_an_addon_with_a_bad_agent_conf(self):
        d = self.addon("CMD=bot\n")
        p = subprocess.run(["bash", os.path.join(SCRIPTS, "swarmbox-addon.sh"), "validate", os.path.dirname(d)],
                           capture_output=True, text=True, env={"PATH": "/usr/bin:/bin", "HOME": self.tmp, "SWARMBOX_TEST_LIB": "/nonexistent"},
                           timeout=60)
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertIn("agent.conf: ID is missing", p.stdout)

    def test_the_command_resolves_defaults_and_generates_the_json(self):
        home = os.path.join(self.tmp, "home")
        os.makedirs(home)
        env = {"PATH": "/usr/bin:/bin", "HOME": home, "SWARMBOX_TEST_IMAGE_ADDONS": ADDONS, "SWARMBOX_TEST_USER_ADDONS": "/nonexistent",
               "SWARMBOX_TEST_IMAGE_STATE": self.tmp, "SWARMBOX_AGENT": "antigravity"}
        cmd = [sys.executable, "-I", os.path.join(SCRIPTS, "swarmbox-agents.py")]
        run = lambda *a: subprocess.run(cmd + list(a), capture_output=True, text=True, env=env, timeout=60)
        self.assertEqual(run("resolve", "claude-code").stdout, "claude\n")
        self.assertEqual(run("resolve", "gcloud").returncode, 1)
        self.assertEqual(run("default").stdout, "agy\n")
        out = os.path.join(self.tmp, "run", "agents.json")
        self.assertEqual(run("generate", "--output", out).returncode, 0)
        with open(out) as f:
            data = json.load(f)
        self.assertEqual(data["default"], "agy")
        self.assertEqual([a["id"] for a in data["agents"]], ["agy", "claude", "opencode"])
        self.assertNotIn("dir", data["agents"][0])
        self.assertEqual(run("bogus").returncode, 64)


class GatewayRoutes(unittest.TestCase):
    """The page's view of the registry: /agents.js (loaded before app.js), /api/agents and /agents/<id>/icon.svg of the real gateway."""

    def test_the_gateway_serves_the_registry_and_the_icons(self):
        if not shutil.which("node"):
            self.skipTest("node is not installed")
        tmp = os.path.realpath(tempfile.mkdtemp(prefix="sbagents-gw-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        js = r"""
import { registerHooks } from 'node:module';
if (typeof registerHooks === 'function') {
  registerHooks({ resolve(specifier, context, next) {
    if (specifier === 'ws') return { shortCircuit: true, url: 'data:text/javascript,export class WebSocketServer { constructor(){ this.clients = new Set(); } on(){} handleUpgrade(){} }' };
    return next(specifier, context);
  } });
}
const { createGateway } = await import('./server.mjs');
const { server } = createGateway({ hc: { terminals: new Map(), on() {}, proc: null, close() {} } });
await new Promise((r) => server.listen(0, '127.0.0.1', r));
const base = `http://127.0.0.1:${server.address().port}`;
const out = {};
let r = await fetch(base + '/agents.js'); out.js = { status: r.status, type: r.headers.get('content-type'), text: await r.text() };
r = await fetch(base + '/api/agents'); out.api = await r.json();
r = await fetch(base + '/agents/claude/icon.svg'); out.icon = { status: r.status, type: r.headers.get('content-type'), text: await r.text() };
r = await fetch(base + '/agents/claude-code/icon.svg'); out.alias = r.status;
r = await fetch(base + '/agents/nope/icon.svg'); out.nope = r.status;
r = await fetch(base + '/agents/..%2F..%2Fetc/icon.svg'); out.trav = r.status;
server.close();
console.log(JSON.stringify(out));
"""
        env = dict(os.environ, HOME=tmp, SWARMBOX_HC_AUTOSTART="0", SWARMBOX_TEST_USER_ADDONS=os.path.join(tmp, "none"))
        env.pop("SWARMBOX_IMAGE_ADDONS_DIR", None)
        env.pop("SWARMBOX_TEST_IMAGE_ADDONS", None)
        p = subprocess.run(["node", "--input-type=module", "-e", js], cwd=os.path.dirname(AGENTS_MJS), env=env, capture_output=True, text=True, timeout=60)
        self.assertEqual(p.returncode, 0, p.stderr)
        out = json.loads(p.stdout.strip().splitlines()[-1])
        self.assertEqual(out["js"]["status"], 200)
        self.assertIn("javascript", out["js"]["type"])
        self.assertTrue(out["js"]["text"].startswith("window.SWARMBOX_AGENTS = {"))
        self.assertNotIn("<svg", out["js"]["text"], "a < in the inlined data is escaped, so it cannot close a script element")
        ids = [a["id"] for a in out["api"]["agents"]]
        self.assertEqual(ids, ["agy", "claude", "opencode"])
        claude = out["api"]["agents"][ids.index("claude")]
        self.assertEqual(claude["label"], "Claude Code")
        self.assertIn("claude-code", claude["aliases"])
        self.assertTrue(claude["icon_svg"].startswith("<svg"))
        self.assertNotIn("dir", claude)
        self.assertIn("bash", out["api"]["shell_names"])
        self.assertEqual((out["icon"]["status"], out["icon"]["type"]), (200, "image/svg+xml"))
        self.assertEqual(out["icon"]["text"].strip(), claude["icon_svg"])
        self.assertEqual((out["alias"], out["nope"], out["trav"]), (404, 404, 404))


if __name__ == "__main__":
    unittest.main()
