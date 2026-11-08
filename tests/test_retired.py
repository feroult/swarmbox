#!/usr/bin/env python3
"""Slice 6.3: the v0.1.0 entry points are gone, and nothing in 2.0 names them (design 12.1, 12.2, D8, D9, 13.2).

Deleted in slice 6.3, after the parity suite (6.1) and the ported tests (6.2) were green: start.sh, build.sh, lib/
(attach-session.sh, podman-connection.sh, ui.sh, web.sh), container/scripts/init.sh, container/opencode/,
container/web/web-terminal.sh and Dockerfile.v0.1.0. The old content stays reachable through the tag v0.1.0
(`git show v0.1.0:start.sh`); this file also checks that the tag still resolves.

It fails when a retired path comes back, when a 2.0 source (Dockerfile, dev/, ci.yml, container/, the host script, the
tests) names a retired file outside a line that marks it as history (`v0.1.0`), or when a replacement the retirement
relies on is missing.
Run: python3 tests/test_retired.py
"""
import os
import re
import subprocess
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import ROOT  # noqa: E402
from test_retired_coverage import ALLOW, FORBIDDEN  # noqa: E402

RETIRED = (
    "start.sh", "build.sh", "Dockerfile.v0.1.0",
    "lib", "lib/attach-session.sh", "lib/podman-connection.sh", "lib/ui.sh", "lib/web.sh",
    "container/scripts/init.sh", "container/opencode", "container/opencode/local-llm.json",
    "container/web/web-terminal.sh",
)

# what each retired file became (the 2.0 counterpart must exist)
COUNTERPARTS = (
    "container/scripts/swarmbox-attach.sh",      # lib/attach-session.sh
    "container/host/swarmbox-host",              # start.sh, lib/podman-connection.sh (the `connection` step of up), lib/web.sh (connector)
    "container/scripts/messages.sh",             # lib/ui.sh
    "container/scripts/swarmbox-web.sh",         # lib/web.sh, container/web/web-terminal.sh
    "container/web/build-index.sh",              # container/web/web-terminal.sh (the page)
    "container/tools/opencode/local-llm.json",   # container/opencode/local-llm.json
    "container/tools/opencode/prepare.sh",       # container/scripts/init.sh (the OpenCode config)
    "dev/dev-build.sh", "Dockerfile",            # build.sh, Dockerfile.v0.1.0
)

# a 2.0 source line may name a retired file only as history
HISTORY = re.compile(r"v0\.1\.0|retired|history", re.I)
FORBIDDEN_ALL = re.compile(FORBIDDEN.pattern + r"|Dockerfile\.v0\.1\.0|(?<![\w-])(?:attach-session|podman-connection)\.sh")
SKIP_DIRS = {".git", "__pycache__", "docs", "spikes", "fixtures"}


def sources():
    for base in ("Dockerfile", "cloudflare-setup.py", "CONTRIBUTING.md", "dev", ".github", "container", "tests"):
        p = os.path.join(ROOT, base)
        if os.path.isfile(p):
            yield base, p
            continue
        for root, dirs, files in os.walk(p):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
            for f in files:
                if f.endswith((".png", ".ico", ".pyc")):
                    continue
                yield os.path.relpath(os.path.join(root, f), ROOT), os.path.join(root, f)


class Absent(unittest.TestCase):
    def test_no_retired_path_exists(self):
        for rel in RETIRED:
            with self.subTest(path=rel):
                self.assertFalse(os.path.lexists(os.path.join(ROOT, rel)), rel)

    def test_the_counterparts_exist(self):
        for rel in COUNTERPARTS:
            with self.subTest(path=rel):
                self.assertTrue(os.path.isfile(os.path.join(ROOT, rel)), rel)

    def test_the_old_content_is_still_in_the_tag(self):
        for rel in ("start.sh", "build.sh", "lib/ui.sh", "container/scripts/init.sh", "container/opencode/local-llm.json",
                    "container/web/web-terminal.sh", "Dockerfile"):
            with self.subTest(path=rel):
                r = subprocess.run(["git", "-C", ROOT, "show", "v0.1.0:" + rel], capture_output=True)
                self.assertEqual(r.returncode, 0, r.stderr.decode()[:200])
                self.assertGreater(len(r.stdout), 50)


class NoReferences(unittest.TestCase):
    def test_no_2_0_source_names_a_retired_file_except_as_history(self):
        bad = []
        for rel, path in sources():
            name = os.path.basename(rel)
            if name in ALLOW and name != os.path.basename(__file__):
                continue
            if name == os.path.basename(__file__):
                continue
            try:
                with open(path, encoding="utf-8") as f:
                    lines = f.readlines()
            except UnicodeDecodeError:
                continue
            for n, line in enumerate(lines, 1):
                if FORBIDDEN_ALL.search(line) and not HISTORY.search(line):
                    bad.append("%s:%d: %s" % (rel, n, line.strip()[:110]))
        self.assertEqual(bad, [])

    def test_the_dockerfile_and_the_build_script_copy_nothing_retired(self):
        for rel in ("Dockerfile", "dev/dev-build.sh", ".github/workflows/ci.yml"):
            with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
                text = f.read()
            self.assertNotRegex(text, FORBIDDEN_ALL, rel)

    def test_the_function_templates_and_the_entrypoint_name_none(self):
        for rel in ("container/entrypoint.sh", "container/host/swarmbox-host", "container/scripts/swarmbox-init.sh"):
            with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
                for n, line in enumerate(f, 1):
                    if FORBIDDEN_ALL.search(line):
                        self.assertRegex(line, HISTORY, "%s:%d" % (rel, n))

    def test_the_ci_shellcheck_lists_name_only_files_that_exist(self):
        with open(os.path.join(ROOT, ".github", "workflows", "ci.yml"), encoding="utf-8") as f:
            text = f.read()
        for line in text.splitlines():
            if "shellcheck -s" in line:
                for tok in line.split():
                    if tok.endswith(".sh") or tok.endswith("swarmbox-host"):
                        self.assertTrue(os.path.isfile(os.path.join(ROOT, tok)), tok)

    def test_the_local_llm_template_is_the_v0_1_0_one(self):
        # the removal of the local-LLM defaults (12.2) is in prepare.sh, not in the template
        old = subprocess.run(["git", "-C", ROOT, "show", "v0.1.0:container/opencode/local-llm.json"], capture_output=True, text=True)
        self.assertEqual(old.returncode, 0)
        with open(os.path.join(ROOT, "container", "tools", "opencode", "local-llm.json"), encoding="utf-8") as f:
            self.assertEqual(f.read(), old.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
