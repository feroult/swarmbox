"""Settings > Addons through the real gateway: which addons offer Install, Update and Remove, and what each one runs.

The real createGateway() on 127.0.0.1:0 with a fake HerdrClient and a fake swarmbox-addon (SWARMBOX_TEST_ADDON_BIN) that logs its
arguments; the addon manifests and installs are folders in mktemp. Update installs a managed addon again (`install NAME --force`): the
newest release of a floating one, the image's version of a pinned one when it is behind; an addon that updates itself is never
offered one. Remove (`remove NAME`, never --purge) is offered for a workspace install only. The gateway refuses what it does not offer.

Run: python3 tests/fast/test_addons_web.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "support"))
from helpers import ROOT, stage_herdr_web  # noqa: E402

WEB = os.path.join(ROOT, "container", "web", "herdr")

HARNESS = r"""
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { EventEmitter } from 'node:events';
import { createGateway } from SERVER_PATH;

class FakeHc extends EventEmitter {
  constructor() { super(); this.proc = {}; }
  listSnapshot() { return []; }
  async call() { return { terminals: [] }; }
  close() {}
}
const gw = createGateway({ hc: new FakeHc() });
await new Promise((resolve) => gw.server.listen(0, '127.0.0.1', resolve));
const base = `http://127.0.0.1:${gw.server.address().port}`;
const log = process.env.FAKE_ADDON_LOG;
const calls = () => (fs.existsSync(log) ? fs.readFileSync(log, 'utf8').split('\n').filter(Boolean) : []);
async function api(method, p) {
  const r = await fetch(`${base}${p}`, { method, headers: { 'Content-Type': 'application/json', Origin: base }, body: method === 'POST' ? '{}' : undefined });
  return { status: r.status, data: await r.json().catch(() => ({})) };
}
try {
  const cfg = await api('GET', '/api/config');
  const by = Object.fromEntries(cfg.data.addons.map((a) => [a.name, a]));
  const offer = (n) => [by[n].installed, by[n].canUpdate, by[n].updateAvailable, by[n].canRemove];
  assert.deepEqual(offer('floaty'), [true, true, false, true]);     // floating: Update gets the newest release
  assert.deepEqual(offer('behind'), [true, true, true, true]);      // pinned, the image names a newer version
  assert.deepEqual(offer('current'), [true, false, false, true]);   // pinned and current: nothing to update
  assert.deepEqual(offer('selfy'), [true, false, false, true]);     // updates itself: no Update
  assert.deepEqual(offer('baked'), [true, true, false, false]);     // in the image: cannot be removed from the workspace
  assert.deepEqual(offer('fresh'), [false, false, false, false]);

  let r = await api('POST', '/api/addons/floaty/update');
  assert.equal(r.status, 200, JSON.stringify(r.data));
  assert.deepEqual(calls(), ['install floaty --force', 'prepare']);
  r = await api('POST', '/api/addons/behind/update');
  assert.equal(r.status, 200);
  r = await api('POST', '/api/addons/selfy/remove');
  assert.equal(r.status, 200);
  assert.equal(r.data.action, 'remove');
  r = await api('POST', '/api/addons/fresh/install');
  assert.equal(r.status, 200);
  assert.deepEqual(calls(), ['install floaty --force', 'prepare', 'install behind --force', 'prepare', 'remove selfy', 'install fresh', 'prepare']);

  for (const [p, err] of [['/api/addons/selfy/update', 'addon_update_refused'], ['/api/addons/current/update', 'addon_update_refused'],
                          ['/api/addons/baked/remove', 'addon_remove_refused'], ['/api/addons/fresh/remove', 'addon_remove_refused']]) {
    r = await api('POST', p);
    assert.equal(r.status, 409, p);
    assert.equal(r.data.error, err, p);
  }
  assert.equal((await api('POST', '/api/addons/nosuch/remove')).status, 404);
  assert.equal((await api('POST', '/api/addons/floaty/purge')).status, 404);
  assert.equal(calls().length, 7, 'a refused action runs nothing');

  // a failure carries the command's message
  fs.writeFileSync(process.env.FAKE_ADDON_FAIL, '1');
  r = await api('POST', '/api/addons/floaty/update');
  assert.equal(r.status, 502);
  assert.equal(r.data.error, 'addon_update_failed');
  assert.match(r.data.message, /registry unreachable/);
  console.log('ADDONS_WEB_OK');
} finally {
  gw.server.close();
  process.exit(process.exitCode || 0);
}
"""

FAKE_ADDON = """#!/bin/sh
if [ -f "$FAKE_ADDON_FAIL" ]; then echo "npm: registry unreachable" >&2; exit 1; fi
echo "$*" >> "$FAKE_ADDON_LOG"
"""


@unittest.skipUnless(shutil.which("node"), "node not on PATH")
class AddonsSettingsGateway(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="swarmbox-test-addonsweb.")
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def manifest(self, root, name, version, update="managed"):
        os.makedirs(os.path.join(root, name))
        with open(os.path.join(root, name, "addon.conf"), "w") as f:
            f.write('SCHEMA=1\nNAME=%s\nDESCRIPTION="x"\nVERSION=%s\nUPDATE=%s\nCOMMANDS="%s"\n' % (name, version, update, name))

    def managed_install(self, root, name, version):
        os.makedirs(os.path.join(root, name, version, "bin"))
        os.symlink(version, os.path.join(root, name, "current"))
        open(os.path.join(root, name, version, ".swarmbox-env"), "w").close()

    def test_install_update_remove(self):
        web = os.path.join(self.tmp, "web")
        ws = os.path.join(web, "node_modules", "ws")
        os.makedirs(ws)
        stage_herdr_web(web)
        with open(os.path.join(ws, "package.json"), "w") as f:
            json.dump({"name": "ws", "type": "module", "main": "index.js"}, f)
        with open(os.path.join(ws, "index.js"), "w") as f:
            f.write("import { EventEmitter } from 'node:events';\n"
                    "export class WebSocketServer extends EventEmitter { constructor() { super(); this.clients = new Set(); } close() {} }\n")
        home = os.path.join(self.tmp, "home")
        image, baked = os.path.join(self.tmp, "image"), os.path.join(self.tmp, "baked")
        data = os.path.join(home, ".local", "share", "swarmbox", "addons")
        for name, version, update in (("floaty", "latest", "managed"), ("behind", "2.0.0", "managed"), ("current", "1.0.0", "managed"),
                                      ("selfy", "latest", "self"), ("baked", "latest", "managed"), ("fresh", "1.0.0", "managed")):
            self.manifest(image, name, version, update)
        self.managed_install(data, "floaty", "latest")
        self.managed_install(data, "behind", "1.0.0")
        self.managed_install(data, "current", "1.0.0")
        self.managed_install(baked, "baked", "latest")
        os.makedirs(os.path.join(data, "selfy", "self"))
        open(os.path.join(data, "selfy", "self", ".swarmbox-env"), "w").close()
        fake = os.path.join(self.tmp, "swarmbox-addon")
        with open(fake, "w") as f:
            f.write(FAKE_ADDON)
        os.chmod(fake, 0o755)
        run = os.path.join(web, "run.mjs")
        with open(run, "w") as f:
            f.write(HARNESS.replace("SERVER_PATH", json.dumps(os.path.join(web, "server.mjs"))))
        env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": home,
            "XDG_CONFIG_HOME": os.path.join(home, ".config"),
            "XDG_DATA_HOME": os.path.join(home, ".local", "share"),
            "XDG_STATE_HOME": os.path.join(home, ".local", "state"),
            "SB_RUN_DIR": os.path.join(self.tmp, "run"),
            "SWARMBOX_IMAGE_ADDONS_DIR": image,
            "SWARMBOX_TEST_IMAGE_STATE": baked,
            "SWARMBOX_TEST_ADDON_BIN": fake,
            "FAKE_ADDON_LOG": os.path.join(self.tmp, "addon.log"),
            "FAKE_ADDON_FAIL": os.path.join(self.tmp, "fail"),
        }
        p = subprocess.run(["node", run], env=env, capture_output=True, text=True, timeout=60)
        self.assertEqual(p.returncode, 0, "stdout:\n%s\nstderr:\n%s" % (p.stdout, p.stderr))
        self.assertIn("ADDONS_WEB_OK", p.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
