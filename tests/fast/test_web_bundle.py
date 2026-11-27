"""The Web Studio's page scripts: /app.js and /viewer.js are the esbuild bundles of public/dist/ when the image built them, and the
modular source of public/ when it did not (a checkout, the tests).

Real program: the herdr HTTP handler (container/web/herdr/*.mjs, copied to a scratch folder with a scratch public/), served by node on
127.0.0.1 at a random port. Run with: python3 -W error tests/fast/test_web_bundle.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "support"))
from helpers import stage_herdr_web  # noqa: E402

# Starts the real handler, GETs each path given on the command line, prints [{path, status, body}] as JSON, and closes the server.
HARNESS = r"""
import http from 'node:http';
import { createHttpHandler } from './http-routes.mjs';
const server = http.createServer(createHttpHandler({}));
await new Promise((ok) => server.listen(0, '127.0.0.1', ok));
const { port } = server.address();
const out = [];
for (const p of process.argv.slice(2)) {
  const r = await fetch(`http://127.0.0.1:${port}${p}`);
  out.push({ path: p, status: r.status, body: await r.text() });
}
server.close();
console.log(JSON.stringify(out));
"""


@unittest.skipUnless(shutil.which("node"), "node not on PATH")
class PageScripts(unittest.TestCase):
    def setUp(self):
        self.web = tempfile.mkdtemp(prefix="swarmbox-test-webbundle.")
        self.addCleanup(shutil.rmtree, self.web, True)
        stage_herdr_web(self.web)
        with open(os.path.join(self.web, "run.mjs"), "w") as f:
            f.write(HARNESS)
        self.public = os.path.join(self.web, "public")
        for rel, text in (("app.js", "source app"), ("viewer.js", "source viewer"), ("app/state.js", "source state")):
            self.put(os.path.join(self.public, rel), text)

    def put(self, path, text):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(text)

    def get(self, *paths):
        p = subprocess.run(["node", "run.mjs"] + list(paths), cwd=self.web, capture_output=True, text=True, timeout=30)
        self.assertEqual(p.returncode, 0, p.stderr)
        return {r["path"]: (r["status"], r["body"]) for r in json.loads(p.stdout)}

    def test_a_built_image_serves_the_bundles_in_place_of_the_entry_modules(self):
        self.put(os.path.join(self.public, "dist", "app.js"), "bundle app")
        self.put(os.path.join(self.public, "dist", "viewer.js"), "bundle viewer")
        got = self.get("/app.js", "/viewer.js", "/app/state.js")
        self.assertEqual(got["/app.js"], (200, "bundle app"))
        self.assertEqual(got["/viewer.js"], (200, "bundle viewer"))
        self.assertEqual(got["/app/state.js"], (200, "source state"))

    def test_without_a_build_the_modular_source_is_served(self):
        got = self.get("/app.js", "/viewer.js")
        self.assertEqual(got["/app.js"], (200, "source app"))
        self.assertEqual(got["/viewer.js"], (200, "source viewer"))


if __name__ == "__main__":
    unittest.main()
