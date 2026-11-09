"""Dev/name-check.sh, the reduced name availability check. It runs only against a fake curl here.

The fake curl answers by URL from a folder of canned files, records its calls, and the script is run with PATH set so the
fake wins. The script must: query GitHub search, GitHub repo, npm and PyPI; report TAKEN or FREE per source; exit 0 always
(it informs, it does not decide); report UNKNOWN when curl fails; never write into the repository.
Run: python3 tests/test_name_check.py
"""
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import ROOT, DEFAULT_NAME  # noqa: E402

SCRIPT = os.path.join(ROOT, "dev", "name-check.sh")

FAKE = """#!/bin/sh
# fake curl: last argument is the URL; prints the canned body and, with -w, the status
url=""
for a in "$@"; do url=$a; done
echo "$url" >> "$FAKE_LOG"
[ -n "${FAKE_FAIL:-}" ] && exit 7
case "$url" in
  *search/repositories*) body=$FAKE_SEARCH; code=200 ;;
  *api.github.com/repos/*) body=$FAKE_REPO_BODY; code=$FAKE_REPO ;;
  *registry.npmjs.org*) body='{}'; code=$FAKE_NPM ;;
  *pypi.org*) body='{}'; code=$FAKE_PYPI ;;
  *) body=''; code=404 ;;
esac
printf '%s\\n' "$body"
printf '%s' "$code"
"""


class NameCheckTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="swarmbox-test-namecheck-")
        self.bin = os.path.join(self.tmp, "bin")
        os.makedirs(self.bin)
        p = os.path.join(self.bin, "curl")
        with open(p, "w") as f:
            f.write(FAKE)
        os.chmod(p, os.stat(p).st_mode | stat.S_IXUSR)
        self.log = os.path.join(self.tmp, "calls")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_it(self, search=3, repo=404, npm=404, pypi=404, fail=False, args=()):
        env = dict(os.environ, PATH=self.bin + os.pathsep + os.environ["PATH"], FAKE_LOG=self.log,
                   FAKE_SEARCH=json.dumps({"total_count": search}), FAKE_REPO=str(repo), FAKE_REPO_BODY="{}",
                   FAKE_NPM=str(npm), FAKE_PYPI=str(pypi))
        if fail:
            env["FAKE_FAIL"] = "1"
        return subprocess.run(["sh", SCRIPT] + list(args), env=env, capture_output=True, text=True, cwd=self.tmp)

    def test_exists(self):
        self.assertTrue(os.path.isfile(SCRIPT))
        with open(SCRIPT) as f:
            self.assertEqual(f.readline().strip(), "#!/bin/sh")

    def test_default_name_is_the_one_of_the_defaults_file(self):
        r = self.run_it()
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(self.log) as f:
            urls = f.read()
        self.assertIn("q=%s+in:name" % DEFAULT_NAME, urls)
        self.assertIn("/feroult/%s" % DEFAULT_NAME, urls)
        self.assertIn("/%s" % DEFAULT_NAME, urls.split("registry.npmjs.org")[1].split("\n")[0])
        r = self.run_it(args=["othername"])        # an argument still wins
        with open(self.log) as f:
            self.assertIn("othername", f.read())

    def test_taken_everywhere(self):
        r = self.run_it(search=21, repo=200, npm=200, pypi=200)
        self.assertEqual(r.returncode, 0, r.stderr)
        for name in ("github-search", "npm", "pypi"):
            self.assertRegex(r.stdout, r"(?m)^TAKEN %s " % name, r.stdout)
        self.assertIn("21", r.stdout)
        self.assertIn("not legal advice", r.stdout)

    def test_free_everywhere(self):
        r = self.run_it(search=0)
        self.assertRegex(r.stdout, r"(?m)^FREE github-search ")
        self.assertRegex(r.stdout, r"(?m)^FREE npm ")
        self.assertRegex(r.stdout, r"(?m)^FREE pypi ")
        self.assertRegex(r.stdout, r"(?m)^FREE github-repo ")

    def test_unknown_when_curl_fails(self):
        r = self.run_it(fail=True)
        self.assertEqual(r.returncode, 0)
        self.assertRegex(r.stdout, r"(?m)^UNKNOWN npm ")
        self.assertNotIn("TAKEN", r.stdout)

    def test_name_and_owner_arguments_reach_the_urls(self):
        self.run_it(args=["othername", "someowner"])
        with open(self.log) as f:
            calls = f.read()
        self.assertIn("othername", calls)
        self.assertIn("repos/someowner/othername", calls)
        self.assertNotIn("swarmbox", calls)

    def test_writes_nothing_in_the_working_folder(self):
        before = set(os.listdir(self.tmp))
        self.run_it()
        self.assertEqual(set(os.listdir(self.tmp)) - before, {"calls"})


if __name__ == "__main__":
    unittest.main()
