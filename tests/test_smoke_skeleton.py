"""Slice 2.7: static and logic checks of tests/smoke_image.py (the image smoke test, design 13.3 layer 2).

This file never starts a container. It checks that the smoke test lists every step of the plan (section 4 of
docs/implementation-plan.md), that a reduced step prints the tag "[reduced: development box, no nested Podman in the box]",
that a step that needs the full environment is SKIPPED (never reported as passed) unless SWARMBOX_SMOKE_FULL=1, that the
run without the opt-in does nothing, and that every container, volume and image name starts with swarmbox-test- and is
removed by its exact name (no forbidden podman verb in the file).
Run: python3 tests/test_smoke_skeleton.py
"""
import importlib.util
import io
import os
import re
import subprocess
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import ROOT  # noqa: E402

SMOKE = os.path.join(ROOT, "tests", "smoke_image.py")
TAG = "[reduced: development box, no nested Podman in the box]"
# The five steps named by the plan (section 4) plus the ones the exit criteria add.
PLAN_STEPS = ["ready", "tmpfs-restart", "page-built", "tool-validate", "nested-podman"]
EXTRA_STEPS = ["attach-session", "no-agent", "nested-cgroup", "tool-shim", "tool-index-ports", "mcp-generated", "up-lifecycle", "up-busy-port"]


def load():
    spec = importlib.util.spec_from_file_location("smoke_image", SMOKE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def clean_env(**extra):
    env = {k: v for k, v in os.environ.items() if not k.startswith("SWARMBOX_")}
    env.update(extra)
    return env


class Skeleton(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = open(SMOKE, encoding="utf-8").read()
        cls.mod = load()

    def test_every_step_of_the_plan_is_listed(self):
        ids = [s.id for s in self.mod.STEPS]
        for sid in PLAN_STEPS + EXTRA_STEPS:
            self.assertIn(sid, ids)
        self.assertEqual(len(ids), len(set(ids)))

    def test_only_the_nested_steps_need_the_full_environment(self):
        full = sorted(s.id for s in self.mod.STEPS if s.needs_full)
        self.assertEqual(full, ["nested-cgroup", "nested-podman"])

    def test_list_prints_every_step_with_its_tag(self):
        r = subprocess.run([sys.executable, SMOKE, "--list"], env=clean_env(), capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        for s in self.mod.STEPS:
            line = [l for l in r.stdout.splitlines() if l.split()[:1] == [s.id]]
            self.assertEqual(len(line), 1, s.id)
            self.assertIn("full-only" if s.needs_full else "reduced-capable", line[0])

    def test_without_the_opt_in_nothing_runs_and_nothing_passes(self):
        r = subprocess.run([sys.executable, SMOKE], env=clean_env(PATH="/nonexistent"), capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        lines = [l for l in r.stdout.splitlines() if l.startswith("STEP ")]
        self.assertEqual(len(lines), len(self.mod.STEPS))
        for l in lines:
            self.assertIn(" SKIP ", l)
        self.assertNotIn(" PASS ", r.stdout)
        self.assertIn("opt-in", r.stdout)

    def test_reduced_pass_is_tagged_and_full_step_is_skipped_not_passed(self):
        S = self.mod.Step
        calls = []
        steps = [S("a", "reduced-capable step", False, lambda ctx: calls.append("a")),
                 S("b", "full-only step", True, lambda ctx: calls.append("b"))]
        out = io.StringIO()
        code = self.mod.run_steps(steps, full=False, ctx=None, out=out)
        text = out.getvalue()
        self.assertEqual(code, 0)
        self.assertEqual(calls, ["a"])
        self.assertRegex(text, r"STEP a PASS .*" + re.escape(TAG))
        self.assertRegex(text, r"STEP b SKIP .*SWARMBOX_SMOKE_FULL=1")
        self.assertNotRegex(text, r"STEP b PASS")
        self.assertIn("[unverified]", text)  # the full result stays unverified until CI

    def test_full_run_runs_every_step_without_the_reduced_tag(self):
        S = self.mod.Step
        calls = []
        steps = [S("a", "x", False, lambda ctx: calls.append("a")), S("b", "y", True, lambda ctx: calls.append("b"))]
        out = io.StringIO()
        code = self.mod.run_steps(steps, full=True, ctx=None, out=out)
        self.assertEqual(code, 0)
        self.assertEqual(calls, ["a", "b"])
        self.assertNotIn(TAG, out.getvalue())
        self.assertRegex(out.getvalue(), r"STEP b PASS .*\[full\]")

    def test_a_failing_step_is_reported_and_the_exit_code_is_1_and_later_steps_still_run(self):
        S = self.mod.Step

        def boom(ctx):
            raise AssertionError("it broke")
        calls = []
        steps = [S("a", "x", False, boom), S("b", "y", False, lambda ctx: calls.append("b"))]
        out = io.StringIO()
        code = self.mod.run_steps(steps, full=False, ctx=None, out=out)
        self.assertEqual(code, 1)
        self.assertEqual(calls, ["b"])
        self.assertRegex(out.getvalue(), r"STEP a FAIL .*it broke")

    def test_names_start_with_swarmbox_test_and_are_removed_by_exact_name(self):
        self.assertEqual(self.mod.PREFIX, "swarmbox-test-")
        for name in ("swarmbox", "other", "swarmbox-test"):
            with self.assertRaises(AssertionError):
                self.mod.exact_name(name)
        self.assertEqual(self.mod.exact_name("swarmbox-test-smoke-abc"), "swarmbox-test-smoke-abc")
        # every removal goes through the guarded helper
        for verb in ("rm", "rmi"):
            for m in re.finditer(r'podman\(\s*"%s"' % verb, self.src):
                self.fail("direct podman %s call at offset %d: use rm_exact/rmi_exact" % (verb, m.start()))

    def test_no_forbidden_podman_verb_in_the_file(self):
        bad = [r"system\s+(prune|reset)", r"volume\s+prune", r"image\s+prune", r"container\s+prune", r"rmi\s+-a",
               r"rm\s+-a\b", r"stop\s+-a\b", r"kill\s+-a\b", r'"--all"', r'"-a"', r"kill-server", r"pkill", r"killall",
               r"\b7681\b", r"\b8889\b", r"(\"-p\"|--publish|\bbind\b|\blisten\b)[^\n]*\b43323\b", r"0\.0\.0\.0", r"tmux\s+kill", r"send-keys"]
        for pat in bad:
            # the module docstring may name the rules in prose; only code lines count
            code = "\n".join(l for l in self.src.splitlines() if not l.lstrip().startswith("#"))
            code = re.sub(r'"""[\s\S]*?"""', "", code, count=1)
            self.assertIsNone(re.search(pat, code), "forbidden pattern %r in smoke_image.py" % pat)

    def test_full_mode_creates_only_prefixed_volumes_and_the_smoke_code_publishes_no_port_itself(self):
        # the box of the older steps publishes nothing; the up steps (slice 3.3) go through the host helper, which publishes
        # the web port on 127.0.0.1 only, at a random high port (see test_the_up_steps_*)
        self.assertNotRegex(self.src, r'"-p"|"--publish"|"-P"')
        self.assertIn("swarmbox-test-", self.src)
        self.assertRegex(self.src, r"volume\", \"rm\"|vol_rm_exact")

    def test_the_up_steps_use_prefixed_names_a_random_high_loopback_port_and_a_scratch_home(self):
        a = self.src.index("def free_port")
        b = self.src.index("def run_steps")
        code = self.src[a:b]
        self.assertIn("random.randrange(20000, 40000)", code)
        self.assertIn('("127.0.0.1", port)', code)
        self.assertIn('"swarmbox-test-3-"', code)
        self.assertIn("tempfile.mkdtemp", code)
        self.assertIn('"HOME": self.home', code)
        self.assertIn('e["XDG_DATA_HOME"]', code)   # only Podman's image store is the real one; see HostSide.env
        by_id = {s.id: s for s in self.mod.STEPS}
        for sid in ("up-lifecycle", "up-busy-port"):
            self.assertFalse(by_id[sid].needs_full, sid)
        self.assertIn("SWARMBOX_SMOKE_ONLY", self.src)

    def test_tool_steps_check_the_real_machinery_and_never_install(self):
        """Slice 4a.5: validate is the real one, the shim, the index and tool-ports are checked, nothing is downloaded."""
        src = self.src
        for needle in ("swarmbox-shim", "/usr/local/lib/swarmbox/shims/", "tool-ports", "type -P $c", "manifest(s) checked"):
            self.assertIn(needle, src)
        self.assertNotRegex(src, r"validate placeholder|the placeholder validate")
        self.assertNotRegex(src, r'"tool",\s*"(install|run)"')
        self.assertNotRegex(src, r"swarmbox-tool (install|run)")
        by_id = {s.id: s for s in self.mod.STEPS}
        for sid in ("tool-validate", "tool-shim", "tool-index-ports", "mcp-generated"):
            self.assertFalse(by_id[sid].needs_full, sid)
        self.assertNotIn("placeholder", by_id["tool-validate"].title)
        ids = [s.id for s in self.mod.STEPS]
        self.assertLess(ids.index("tool-validate"), ids.index("tool-shim"))

    def test_slice_4b6_the_tool_steps_cover_all_seven_tools_ports_and_mcp(self):
        """The smoke data matches the manifests of the repository: the seven tools and their commands, 43323, chrome-devtools."""
        import glob
        names = sorted(os.path.basename(os.path.dirname(p)) for p in glob.glob(os.path.join(ROOT, "container", "tools", "*", "tool.conf")))
        self.assertEqual(sorted(self.mod.TOOL_COMMANDS), names)
        self.assertEqual(sorted(self.mod.ALL_COMMANDS), sorted("claude gemini opencode gcloud gsutil bq clasp go gofmt poetry".split()))
        for name, cmds in self.mod.TOOL_COMMANDS.items():
            with open(os.path.join(ROOT, "container", "tools", name, "tool.conf"), encoding="utf-8") as f:
                m = re.search(r'^PROVIDES="?([^"\n]*)"?', f.read(), re.M)
            self.assertEqual(m.group(1).split(), cmds, name)
        for needle in ("43323", "chrome-devtools", "npx", "swarmbox-mcp generate", "/opt/swarmbox/tools"):
            self.assertIn(needle, self.src)
        self.assertNotIn("claude claude", self.src)

    def test_reduced_switch_is_the_only_test_only_variable_used(self):
        self.assertIn("SWARMBOX_TEST_NO_NESTED", self.src)
        self.assertIn("SWARMBOX_SMOKE_FULL", self.src)
        self.assertIn(TAG, self.src)


if __name__ == "__main__":
    unittest.main()
