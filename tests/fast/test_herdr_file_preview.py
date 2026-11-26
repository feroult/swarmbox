"""Unit and HTTP integration tests for the SwarmBox Web File Previewer.

Covers:
  - file-preview.mjs: path parsing, root allowlist, secret-path denylist, classification, sandbox headers
  - pathlinks.js: terminal/sysop path detection (absolute, ~/, file://, relative dirs like shots/, line numbers, false positives)
  - viewer.js: GFM Markdown rendering, relative image/link resolution, XSS escaping
  - server.mjs HTTP endpoints: /api/files/stat, /api/files/list, /api/files/read, /api/files/raw/*, /view
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "support"))
from helpers import ROOT  # noqa: E402

HERDR_DIR = os.path.join(ROOT, "container", "web", "herdr")
NODE = shutil.which("node")


def run_node_json(script, env=None):
    merged = dict(os.environ)
    if env:
        merged.update(env)
    p = subprocess.run(
        [NODE, "--input-type=module", "-e", script],
        cwd=HERDR_DIR,
        env=merged,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=20,
    )
    if p.returncode != 0:
        raise AssertionError(f"node failed ({p.returncode}):\nSTDOUT:\n{p.stdout}\nSTDERR:\n{p.stderr}")
    return json.loads(p.stdout)


@unittest.skipUnless(NODE, "node not installed")
class FilePreviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="sb-preview-test-")
        self.home = os.path.join(self.tmp, "home")
        os.makedirs(os.path.join(self.home, "report", "shots"), exist_ok=True)
        os.makedirs(os.path.join(self.home, ".ssh"), exist_ok=True)
        os.makedirs(os.path.join(self.home, ".swarmbox"), exist_ok=True)

        with open(os.path.join(self.home, "report", "PROPOSALS.md"), "w", encoding="utf-8") as f:
            f.write("# Audit Report\n\n![Hero](shots/01.png)\n\nSee [metrics](metrics.json).\n")
        with open(os.path.join(self.home, "report", "metrics.json"), "w", encoding="utf-8") as f:
            f.write('{"checks": 16, "passed": true}\n')
        with open(os.path.join(self.home, "report", "index.html"), "w", encoding="utf-8") as f:
            f.write("<!doctype html><h1>Interactive</h1><img src='shots/01.png'>\n")
        # Minimal valid 1x1 PNG
        png_bytes = (
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
            b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
            b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
        )
        with open(os.path.join(self.home, "report", "shots", "01.png"), "wb") as f:
            f.write(png_bytes)
        with open(os.path.join(self.home, ".ssh", "id_rsa"), "w", encoding="utf-8") as f:
            f.write("PRIVATE KEY\n")
        with open(os.path.join(self.home, ".swarmbox", "env"), "w", encoding="utf-8") as f:
            f.write("ANTHROPIC_API_KEY=secret\n")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_resolve_and_security_guards(self):
        res = run_node_json(f"""
            import * as fp from './file-preview.mjs';
            const home = {json.dumps(self.home)};
            const md = fp.resolveAndStat('~/report/PROPOSALS.md#L2-L5', {{ homeDir: home }});
            const relDir = fp.resolveAndStat('shots/', {{ cwd: home, fallbackDir: home + '/report', homeDir: home }});
            const fileUri = fp.resolveAndStat('file://' + home + '/report/metrics.json:1:5', {{ homeDir: home }});
            const outside = fp.resolveAndStat('/etc/passwd', {{ homeDir: home }});
            const ssh = fp.resolveAndStat('~/.ssh/id_rsa', {{ homeDir: home }});
            const envFile = fp.resolveAndStat('~/.swarmbox/env', {{ homeDir: home }});
            const htmlHdr = fp.sandboxHeadersForRaw('html', 'index.html', false);
            const dlHdr = fp.sandboxHeadersForRaw('code', 'metrics.json', true);
            console.log(JSON.stringify({{ md, relDir, fileUri, outside, ssh, envFile, htmlHdr, dlHdr }}));
        """)
        self.assertTrue(res["md"]["ok"])
        self.assertEqual(res["md"]["category"], "markdown")
        self.assertEqual(res["md"]["line"], 2)
        self.assertEqual(res["md"]["endLine"], 5)

        self.assertTrue(res["relDir"]["ok"])
        self.assertEqual(res["relDir"]["kind"], "dir")
        self.assertTrue(res["relDir"]["path"].endswith("/report/shots"))

        self.assertTrue(res["fileUri"]["ok"])
        self.assertEqual(res["fileUri"]["category"], "json")
        self.assertEqual(res["fileUri"]["line"], 1)

        self.assertFalse(res["outside"]["ok"])
        self.assertEqual(res["outside"]["status"], 403)
        self.assertFalse(res["ssh"]["ok"])
        self.assertEqual(res["ssh"]["status"], 403)
        self.assertFalse(res["envFile"]["ok"])
        self.assertEqual(res["envFile"]["status"], 403)

        csp = res["htmlHdr"]["Content-Security-Policy"]
        self.assertIn("sandbox allow-scripts", csp)
        self.assertNotIn("allow-same-origin", csp)
        self.assertIn("attachment;", res["dlHdr"]["Content-Disposition"])

    def test_pathlinks_extraction(self):
        sample = (
            "• Relatório ilustrado completo: ~/.gemini/antigravity-cli/brain/abc/scratch/pixel-perfect-audit/PROPOSALS.md\n"
            "• Pasta de capturas 2x Retina: shots/\n"
            "• Telemetria: /home/agent/report/metrics.json:12:4\n"
            "• Link URI: file:///tmp/output.html\n"
            "• Ignorar: https://example.com/foo/bar.png 25/11/2026 1/2 yes/no v2.2.2\n"
        )
        res = run_node_json(f"""
            import './public/pathlinks.js';
            const pl = globalThis.PathLinks;
            const matches = pl.extractPathMatches({json.dumps(sample)}).map(m => m.text);
            const dir = pl.dirnameOfAbsolute('~/.gemini/antigravity-cli/brain/abc/scratch/pixel-perfect-audit/PROPOSALS.md');
            console.log(JSON.stringify({{ matches, dir }}));
        """)
        self.assertEqual(
            res["matches"],
            [
                "~/.gemini/antigravity-cli/brain/abc/scratch/pixel-perfect-audit/PROPOSALS.md",
                "shots/",
                "/home/agent/report/metrics.json:12:4",
                "file:///tmp/output.html",
            ],
        )
        self.assertEqual(res["dir"], "~/.gemini/antigravity-cli/brain/abc/scratch/pixel-perfect-audit")

    def test_markdown_renderer_and_xss_safety(self):
        md = (
            "# Title\n\n"
            "![Shot](shots/01.png)\n\n"
            "Open [Metrics](metrics.json) or <script>alert(1)</script>.\n\n"
            "> [!TIP]\n> Useful note\n\n"
            "| A | B |\n|---|---|\n| 1 | 2 |\n"
        )
        res = run_node_json(f"""
            import './public/viewer.js';
            const v = globalThis.SwarmBoxViewer;
            const html = v.renderMarkdown({json.dumps(md)}, '/home/agent/report');
            console.log(JSON.stringify({{ html }}));
        """)
        html = res["html"]
        self.assertIn("/api/files/raw/home/agent/report/shots/01.png", html)
        self.assertIn('data-local-path="/home/agent/report/metrics.json"', html)
        self.assertIn("sbv-md-alert-tip", html)
        self.assertIn("<table>", html)
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", html)

    def test_syntax_highlighting_code_and_markdown(self):
        md = (
            "# Code\n\n"
            "```python\n"
            "# greet\n"
            "def hello(name: str) -> bool:\n"
            "    return '<script>' in name\n"
            "```\n\n"
            "```json\n"
            '{"ok": true, "count": 42}\n'
            "```\n"
        )
        multiline_js = "/* line 1\n   line 2 */\nconst x = greet('hi', 123);\n"
        res = run_node_json(f"""
            import './public/viewer.js';
            const v = globalThis.SwarmBoxViewer;
            const mdHtml = v.renderMarkdown({json.dumps(md)}, '/home/agent/report');
            const jsLines = v.highlightLines({json.dumps(multiline_js)}, 'server.mjs');
            const pyLang = v.detectLanguage('/tmp/app.py');
            const dockerLang = v.detectLanguage('Dockerfile');
            const shHtml = v.highlightCode('export FOO=$BAR; echo "hi" # note', 'bash');
            const htmlCode = v.highlightCode('<div class="a">hi</div>', 'html');
            const diffHtml = v.highlightCode('@@ -1,2 +1,2 @@\\n-old\\n+new', 'diff');
            const bigText = 'const a = 1;\\n'.repeat(30000);
            const bigHtml = v.highlightCode(bigText, 'js');
            console.log(JSON.stringify({{
              mdHtml, jsLines, pyLang, dockerLang, shHtml, htmlCode, diffHtml,
              bigFallbackPlain: !bigHtml.includes('sbv-tok-'),
            }}));
        """)
        # Markdown fenced code blocks highlighted & XSS-escaped
        self.assertIn('data-lang="python"', res["mdHtml"])
        self.assertIn('<span class="sbv-tok-cmt"># greet</span>', res["mdHtml"])
        self.assertIn('<span class="sbv-tok-kw">def</span>', res["mdHtml"])
        self.assertIn('<span class="sbv-tok-fn">hello</span>', res["mdHtml"])
        self.assertIn("&lt;script&gt;", res["mdHtml"])
        self.assertNotIn("<script>", res["mdHtml"])
        self.assertIn('<span class="sbv-tok-key">&quot;ok&quot;</span>', res["mdHtml"])
        self.assertIn('<span class="sbv-tok-bool">true</span>', res["mdHtml"])
        self.assertIn('<span class="sbv-tok-num">42</span>', res["mdHtml"])

        # Multiline block comment split cleanly across table rows
        self.assertEqual(len(res["jsLines"]), 4)
        self.assertIn('<span class="sbv-tok-cmt">/* line 1</span>', res["jsLines"][0])
        self.assertIn('<span class="sbv-tok-cmt">   line 2 */</span>', res["jsLines"][1])
        self.assertIn('<span class="sbv-tok-kw">const</span>', res["jsLines"][2])
        self.assertIn('<span class="sbv-tok-fn">greet</span>', res["jsLines"][2])
        self.assertIn('<span class="sbv-tok-num">123</span>', res["jsLines"][2])

        # Language detection, bash, html, diff, and large-file fallback
        self.assertEqual(res["pyLang"], "py")
        self.assertEqual(res["dockerLang"], "dockerfile")
        self.assertIn('<span class="sbv-tok-kw">export</span>', res["shHtml"])
        self.assertIn('<span class="sbv-tok-var">$BAR</span>', res["shHtml"])
        self.assertIn('<span class="sbv-tok-tag">div</span>', res["htmlCode"])
        self.assertIn('<span class="sbv-tok-attr">class</span>', res["htmlCode"])
        self.assertIn('<span class="sbv-tok-hunk">@@ -1,2 +1,2 @@</span>', res["diffHtml"])
        self.assertIn('<span class="sbv-tok-del">-old</span>', res["diffHtml"])
        self.assertIn('<span class="sbv-tok-add">+new</span>', res["diffHtml"])
        self.assertTrue(res["bigFallbackPlain"])

    def test_http_endpoints(self):
        res = run_node_json(
            f"""
            import {{ registerHooks }} from 'node:module';
            if (typeof registerHooks === 'function') {{
              registerHooks({{
                resolve(specifier, context, next) {{
                  if (specifier === 'ws') return {{ shortCircuit: true, url: 'data:text/javascript,export class WebSocketServer {{ constructor(){{ this.clients = new Set(); }} on(){{}} handleUpgrade(){{}} }}' }};
                  return next(specifier, context);
                }},
              }});
            }}
            const {{ createGateway }} = await import('./server.mjs');
            const fakeHc = {{ terminals: new Map(), on() {{}}, proc: null, close() {{}} }};
            const {{ server }} = createGateway({{ hc: fakeHc }});
            await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
            const port = server.address().port;
            const base = `http://127.0.0.1:${{port}}`;
            const getJson = async (u) => {{
              const r = await fetch(base + u);
              return {{ status: r.status, body: await r.json() }};
            }};
            const statMd = await getJson('/api/files/stat?path=' + encodeURIComponent('~/report/PROPOSALS.md'));
            const listDir = await getJson('/api/files/list?path=' + encodeURIComponent('~/report/shots'));
            const readJson = await getJson('/api/files/read?path=' + encodeURIComponent('~/report/metrics.json'));
            const blocked = await getJson('/api/files/stat?path=' + encodeURIComponent('/etc/passwd'));
            const rawHtmlRes = await fetch(base + '/api/files/raw' + {json.dumps(self.home)} + '/report/index.html');
            const rawHtmlCsp = rawHtmlRes.headers.get('content-security-policy') || '';
            const rawPngRes = await fetch(base + '/api/files/raw' + {json.dumps(self.home)} + '/report/shots/01.png');
            const viewRes = await fetch(base + '/view?path=' + encodeURIComponent('~/report/PROPOSALS.md'));
            const viewText = await viewRes.text();
            server.close();
            console.log(JSON.stringify({{
              statMd, listDir, readJson, blocked,
              rawHtmlStatus: rawHtmlRes.status, rawHtmlCsp,
              rawPngStatus: rawPngRes.status, rawPngType: rawPngRes.headers.get('content-type'),
              viewStatus: viewRes.status, hasViewerRoot: viewText.includes('standalone-viewer'),
            }}));
            """,
            env={"HOME": self.home, "SWARMBOX_HC_AUTOSTART": "0"},
        )
        self.assertEqual(res["statMd"]["status"], 200)
        self.assertEqual(res["statMd"]["body"]["category"], "markdown")
        self.assertEqual(res["listDir"]["status"], 200)
        self.assertEqual(len(res["listDir"]["body"]["items"]), 1)
        self.assertEqual(res["listDir"]["body"]["items"][0]["name"], "01.png")
        self.assertEqual(res["readJson"]["status"], 200)
        self.assertIn('"checks": 16', res["readJson"]["body"]["content"])
        self.assertEqual(res["blocked"]["status"], 403)
        self.assertEqual(res["rawHtmlStatus"], 200)
        self.assertIn("sandbox allow-scripts", res["rawHtmlCsp"])
        self.assertNotIn("allow-same-origin", res["rawHtmlCsp"])
        self.assertEqual(res["rawPngStatus"], 200)
        self.assertEqual(res["rawPngType"], "image/png")
        self.assertEqual(res["viewStatus"], 200)
        self.assertTrue(res["hasViewerRoot"])


if __name__ == "__main__":
    unittest.main()
