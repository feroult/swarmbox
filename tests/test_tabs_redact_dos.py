"""The secrets filter of swarmbox-tabs (container/scripts/swarmbox-tabs.py) must stay linear and keep redacting what it must. Ported from
tests/test_voice_redact_dos.py, which tested the same filter while it lived in the voice addon (context.py, removed with the planners).
No text of a few MB, however it is built, may take more than a fraction of a second per MB: a regex that rescans a long run from every
position inside it (100000 dashes took 110 s once) is a denial of service for every screen swarmbox-tabs gives out. A screen is clipped before it is
redacted (tests/test_tabs.py), but redact is a function of its own. Run: python3 tests/test_tabs_redact_dos.py"""
import os
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tabs_support import load_module  # noqa: E402

context = load_module()          # the tabs module: .redact and .REDACTED

MB = 1 << 20
LIMIT = 4.0  # seconds for 1 MB: the measured cost is about 0.2 s; the quadratic one needed minutes. Loose on purpose, a loaded CI runner is slow.


def _fill(unit, size=MB):
    return unit * (size // len(unit) + 1)


ADVERSARIAL = {
    "dashes": "-" * MB,
    "equals": "=" * MB,
    "spaces": " " * MB,
    "tabs and newlines": "\t\n" * (MB // 2),
    "base64-like": "A" * MB,
    "base64-like lines": _fill("A" * 40 + "\n"),
    "base64-like lines, one short": _fill("A" * 40 + "\n") + "x",
    "dash-separated words": _fill("a-"),
    "dotted words": _fill("a."),
    "flag-like": _fill("--a"),
    "flag with keyword": _fill("--key "),
    "flag keyword then spaces": "--key" + " " * MB,
    "keyword runs": _fill("key-"),
    "keyword assign": _fill("key="),
    "keyword assign, spaces": _fill("token" + " " * 50 + "="),
    "keyword then spaces": "password" + " " * MB,
    "keyword then quote": _fill("secret=\""),
    "nested quotes": _fill("key='\"'"),
    "nested quotes, one line": "key=\"" + _fill("'a\" ") ,
    "unterminated quote then text": "key=\"" + "a" * MB,
    "jwt-like": _fill("eyJ-"),
    "jwt-like with dots": _fill("eyJaaaaaaaa."),
    "jwt-like after dashes": _fill("-eyJ"),
    "jwt-like with a dot, after dashes": _fill("-eyJaaaaaaaa.a"),
    "scheme-like": _fill("a-") + "://",
    "scheme and colon": _fill("a://a:"),
    "bearer": _fill("bearer "),
    "bearer then spaces": "bearer" + " " * MB,
    "authorization": _fill("authorization:"),
    "private key begins": _fill("-----BEGIN PRIVATE KEY-----\n"),
    "private key begin, long body": "-----BEGIN " + "A" * MB,
    "user flag": _fill("-u "),
    "prefixes": _fill("sk-") + _fill("AKIA") + _fill("xoxb-") + _fill("ghp_"),
}


class RedactTimeTest(unittest.TestCase):
    def test_adversarial_inputs_are_fast(self):
        for name, text in ADVERSARIAL.items():
            with self.subTest(name):
                t = time.monotonic()
                context.redact(text)
                dt = time.monotonic() - t
                self.assertLess(dt, LIMIT, "%s: %.2f s for %d chars" % (name, dt, len(text)))

    def test_cost_does_not_grow_faster_than_the_size(self):
        # the old quadratic cost: 4x the input took 16x the time. Linear stays below 8x on any noise.
        for unit in ("-", "a-", "--a", "key-", "eyJ-", "-eyJ", "eyJ-a.", "eyJaaaaaaaa."):
            with self.subTest(unit):
                times = []
                for size in (100000, 400000):
                    text = _fill(unit, size)
                    t = time.monotonic()
                    context.redact(text)
                    times.append(max(time.monotonic() - t, 0.002))
                self.assertLess(times[1] / times[0], 8, times)

    def test_long_inputs_still_redact_what_they_must(self):
        pad = "-" * 200000
        self.assertIn("password=" + context.REDACTED, context.redact(pad + " password=hunter2"))
        self.assertIn("--api-key " + context.REDACTED, context.redact(pad + " --api-key abc123"))
        self.assertIn("a-" * 50000 + "\nAPI_TOKEN=" + context.REDACTED, context.redact("a-" * 50000 + "\nAPI_TOKEN=xyz"))
        self.assertNotIn("hunter2", context.redact(("x" * 100000 + " ") * 3 + "my.db-password: hunter2"))


class RedactBehaviourTest(unittest.TestCase):
    """What the rewrite of _ASSIGN, _FLAG, the JWT and the URL patterns must keep."""

    def check(self, text, secret, kept=""):
        out = context.redact(text)
        self.assertNotIn(secret, out, text)
        self.assertIn(context.REDACTED, out, text)
        if kept:
            self.assertIn(kept, out, text)

    def test_assignments(self):
        self.check("export API_KEY=abc123", "abc123", "API_KEY=")
        self.check("my-db.password: 's3cr3t pw'", "s3cr3t", "my-db.password")
        self.check('{"access_token": "abc123"}', "abc123", "access_token")
        self.check("x/mykey=abc", "abc", "x/mykey=")
        self.check("a=key=zzz", "zzz")
        self.check("tokenkey=zzz", "zzz")

    def test_flags(self):
        self.check("curl --api-key abc123 http://x", "abc123", "--api-key ")
        self.check("cmd --client-secret 'a b' --other", "a b")

    def test_jwt_urls_and_headers(self):
        jwt = "eyJhbGciOiJI.eyJzdWIiOiIx.SflKxwRJSMeKKF2QT4"
        self.check("t " + jwt, jwt)
        self.check("Authorization: Bearer abcdefgh12345", "abcdefgh12345")
        self.check("git clone https://user:pw123@github.com/x/y", "pw123", "https://user:")
        self.check("redis+ssh://u:pw123@host", "pw123")

    def test_a_jwt_after_a_dash_is_redacted_as_it_was_before_the_speed_fix(self):
        # `\beyJ` allowed a hyphen in front; the lookbehind of the first speed fix did not, and `(?<![A-Za-z0-9_])` alone is quadratic on "eyJ-eyJ-..."
        jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkw.abcdefghijk"
        for prefix in ("-", "x-", "sk-", "id-", "curl -H token-", "a.b-", "jwt:", "(", "\"", " "):
            out = context.redact(prefix + jwt)
            self.assertNotIn(jwt[:20], out, prefix)
            self.assertNotIn("abcdefghijk", out, prefix)
            self.assertTrue(out.startswith(prefix), (prefix, out))
        self.assertEqual(context.redact("id-" + jwt), "id-" + context.REDACTED)
        self.assertEqual(context.redact("a eyJ-eyJ-eyJ-eyJ-x " + jwt), "a eyJ-eyJ-eyJ-eyJ-x " + context.REDACTED)
        self.assertEqual(context.redact("eyJabcdefgh.abc"), "eyJabcdefgh.abc")      # not a JWT: three parts needed

    def test_plain_text_is_untouched(self):
        for text in ("ls -la /tmp", "--verbose --output file", "see http://example.com/a/b", "git log --oneline", "a=1 b: 2"):
            self.assertEqual(context.redact(text), text)


if __name__ == "__main__":
    unittest.main()
