"""dev/release.sh: from a written CHANGELOG to a published, verified release.

Each test builds a real git repository (a bare "origin", a clone with tags, the files the script touches) in a mktemp folder and runs the
real script in it. The gate and the release check are replaced by `true` or `false` (SWARMBOX_RELEASE_CHECK_CMD, _RCHECK_CMD): they are
tested on their own (test_dev_check.py, test_release_check.py). `curl` is a fake that answers the GitHub API and the downloads from canned
text, so nothing touches the network. The script never runs against this repository.
Run with: python3 tests/test_release_script.py
"""
import hashlib
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import ROOT  # noqa: E402

RELEASE = os.path.join(ROOT, "dev", "release.sh")

CHANGELOG = """# Changelog

All notable changes are listed here.

## [Unreleased]

## [2.0.6] - 2026-11-11

- Changed: the web terminal has no scrollbar by default because tmux owns the scrollback.

## [2.0.5] - 2026-11-11

- Added: a progress line for the image pull in swarmbox update.

[2.0.6]: https://github.com/example/proj/releases/tag/v2.0.6
[2.0.5]: https://github.com/example/proj/releases/tag/v2.0.5
"""

ITEMS = "- Fixed: the mouse wheel scrolls tmux five lines per event instead of two, which was too little.\n"

FAKE_CURL = r"""#!/bin/sh
d=$FAKE_DIR
url=
out=
while [ $# -gt 0 ]; do
    case $1 in
        -o) out=$2; shift ;;
        -H|-m) shift ;;
        -*) ;;
        *) url=$1 ;;
    esac
    shift
done
put() { if [ -n "$out" ]; then cat > "$out"; else cat; fi; }
count() { n=$(cat "$d/$1" 2> /dev/null || echo 0); n=$((n + 1)); echo "$n" > "$d/$1"; echo "$n"; }
case $url in
    */actions/runs/*/jobs*)
        put <<'EOT'
{
  "total_count": 3,
  "jobs": [
    {
      "id": 1, "run_id": 777, "status": "completed", "conclusion": "failure", "started_at": "2026-11-11T10:00:00Z", "name": "linux (ubuntu-24.04)",
      "steps": [
        { "name": "Set up job", "status": "completed", "conclusion": "success", "number": 1 },
        { "name": "Unit tests", "status": "completed", "conclusion": "failure", "number": 2 }
      ]
    },
    {
      "id": 2, "run_id": 777, "status": "completed", "conclusion": "success", "started_at": "2026-11-11T10:00:00Z", "name": "macos",
      "steps": [ { "name": "Set up job", "status": "completed", "conclusion": "success", "number": 1 } ]
    },
    {
      "id": 3, "run_id": 777, "status": "completed", "conclusion": "skipped", "started_at": "2026-11-11T10:00:00Z", "name": "browser tests",
      "steps": []
    }
  ]
}
EOT
        ;;
    */actions/workflows/ci.yml/runs\?head_sha=*)
        n=$(count ci_calls)
        case ${FAKE_CI:-ok} in
            none) printf '{"total_count": 0, "workflow_runs": []}' | put; exit 0 ;;
            ok) st=completed; cc='"success"' ;;
            fail) st=completed; cc='"failure"' ;;
            slow) if [ "$n" -lt 3 ]; then st=in_progress; cc=null; else st=completed; cc='"success"'; fi ;;
        esac
        put <<EOT
{
  "total_count": 1,
  "workflow_runs": [
    {
      "id": 777,
      "name": "ci",
      "head_sha": "abc",
      "status": "$st",
      "conclusion": $cc,
      "repository": { "id": 5, "name": "proj" }
    }
  ]
}
EOT
        ;;
    */releases/download/*/swarmbox.sha256)
        n=$(count pub_calls)
        [ "$n" -ge "${FAKE_PUBLISH_AFTER:-1}" ] || exit 22
        put < "$d/sha"
        ;;
    */releases/download/*/swarmbox)
        put < "$d/swarmbox"
        ;;
    *) exit 22 ;;
esac
"""


class ReleaseCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="swarmbox-test-release.")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.origin = os.path.join(self.tmp, "origin.git")
        self.work = os.path.join(self.tmp, "work")
        self.fake = os.path.join(self.tmp, "fake")
        os.mkdir(self.fake)
        self.genv = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.com", GIT_COMMITTER_NAME="t",
                         GIT_COMMITTER_EMAIL="t@example.com", GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_SYSTEM="/dev/null")
        self.g("init", "-q", "--bare", "-b", "main", self.origin, cwd=self.tmp)
        self.g("clone", "-q", self.origin, self.work, cwd=self.tmp)
        self.g("checkout", "-q", "-b", "main")
        self.put("CHANGELOG.md", CHANGELOG)
        self.put("container/host/swarmbox-host", '#!/bin/sh\nSCRIPT_VERSION=2.0.6\n[ "${1:-}" = version ] && echo "$SCRIPT_VERSION"\n', 0o755)
        self.put("container/host/VERSION", "2.0.6\n")
        self.put("container/host/DEFAULTS", "SWARMBOX_DEFAULT_IMAGE_REPO='ghcr.io/example/proj'\n")
        os.makedirs(os.path.join(self.work, "dev"))
        shutil.copy(RELEASE, os.path.join(self.work, "dev", "release.sh"))
        self.g("add", "-A")
        self.g("commit", "-q", "-m", "release: 2.0.6")
        self.g("tag", "-a", "v2.0.6", "-m", "2.0.6")
        self.put("tweak.txt", "x")
        self.g("add", "-A")
        self.g("commit", "-q", "-m", "fix: the mouse wheel scrolls five lines per event")
        self.g("push", "-q", "origin", "main", "v2.0.6")
        with open(os.path.join(self.fake, "curl"), "w") as f:
            f.write(FAKE_CURL)
        os.chmod(os.path.join(self.fake, "curl"), 0o755)
        script = "#!/bin/sh\n[ \"$1\" = version ] && echo 2.0.7\n"
        with open(os.path.join(self.fake, "swarmbox"), "w") as f:
            f.write(script)
        self.set_sha(hashlib.sha256(script.encode()).hexdigest())

    # -- helpers ---------------------------------------------------------------------------------------------------
    def g(self, *args, cwd=None):
        return subprocess.run(["git", *args], cwd=cwd or self.work, env=self.genv, capture_output=True, text=True, check=True).stdout.strip()

    def put(self, name, text, mode=None):
        p = os.path.join(self.work, name)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as f:
            f.write(text)
        if mode:
            os.chmod(p, mode)

    def read(self, name):
        with open(os.path.join(self.work, name)) as f:
            return f.read()

    def set_sha(self, sha):
        with open(os.path.join(self.fake, "sha"), "w") as f:
            f.write("%s  swarmbox\n" % sha)

    def write_items(self, items=ITEMS):
        self.put("CHANGELOG.md", CHANGELOG.replace("## [Unreleased]\n", "## [Unreleased]\n\n" + items, 1))

    def run_release(self, *args, **env):
        e = dict(self.genv, PATH=self.fake + os.pathsep + os.environ["PATH"], FAKE_DIR=self.fake, SWARMBOX_RELEASE_CHECK_CMD="true",
                 SWARMBOX_RELEASE_RCHECK_CMD="true", SWARMBOX_RELEASE_SLUG="example/proj", SWARMBOX_RELEASE_API="http://fake",
                 SWARMBOX_RELEASE_DL="http://fake", SWARMBOX_RELEASE_POLL="0", SWARMBOX_RELEASE_NO_IMAGE_CHECK="1")
        e.update(env)
        return subprocess.run(["sh", os.path.join(self.work, "dev", "release.sh"), *args], cwd=self.work, env=e, capture_output=True,
                              text=True, timeout=60)

    def head(self):
        return self.g("rev-parse", "HEAD")


class ChangelogGate(ReleaseCase):
    def assert_not_ready(self, r, problem):
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("is not ready for 2.0.7", r.stderr)
        self.assertIn(problem, r.stderr)

    def test_an_empty_unreleased_stops_with_instructions_that_carry_the_commits_and_a_model(self):
        r = self.run_release("--dry-run")
        self.assert_not_ready(r, 'has no "- " items')
        self.assertIn("fix: the mouse wheel scrolls five lines per event", r.stderr, "the commits since the last tag")
        self.assertNotIn("release: 2.0.6", r.stderr.split("These are the commits")[1].split("This is the last entry")[0], "only commits after the tag")
        self.assertIn("## [2.0.6] - 2026-11-11", r.stderr, "the last entry as a model")
        self.assertIn("web terminal has no scrollbar", r.stderr)
        self.assertIn("## [Unreleased]", r.stderr)
        self.assertIn("sh dev/release.sh", r.stderr, "how to run it again")
        self.assertIn("Do not touch the version numbers", r.stderr)

    def test_a_missing_unreleased_section_is_refused(self):
        self.put("CHANGELOG.md", CHANGELOG.replace("## [Unreleased]\n\n", ""))
        self.assert_not_ready(self.run_release("--dry-run"), 'no "## [Unreleased]" section')

    def test_a_placeholder_is_refused(self):
        for text in ("- TODO: write this one properly later on\n", "- Changed: something about the thing, to be written...\n", "- TBD what changed in this release\n"):
            self.write_items(text)
            self.assert_not_ready(self.run_release("--dry-run"), "looks like a placeholder")

    def test_an_item_too_short_to_say_anything_is_refused(self):
        self.write_items("- fix\n")
        self.assert_not_ready(self.run_release("--dry-run"), "too short")

    def test_an_entry_for_the_new_version_that_already_exists_is_refused(self):
        self.put("CHANGELOG.md", CHANGELOG.replace("## [2.0.6]", "## [2.0.7] - 2026-11-12\n\n- early entry that should not be here yet\n\n## [2.0.6]", 1))
        self.assert_not_ready(self.run_release("--dry-run"), "already an entry for 2.0.7")

    def test_a_good_entry_passes_and_a_dry_run_changes_nothing(self):
        self.write_items()
        before = self.read("CHANGELOG.md")
        r = self.run_release("--dry-run")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("changelog: 1 item(s) under [Unreleased]", r.stdout)
        self.assertIn("Nothing was changed", r.stdout)
        self.assertEqual(self.read("CHANGELOG.md"), before)
        self.assertEqual(self.read("container/host/VERSION"), "2.0.6\n")


class Versions(ReleaseCase):
    def planned(self, *args):
        self.write_items()
        r = self.run_release("--dry-run", *args)
        return r

    def test_the_default_is_the_next_patch_and_minor_and_major_work(self):
        for args, want in (((), "2.0.7"), (("patch",), "2.0.7"), (("minor",), "2.1.0"), (("major",), "3.0.0"), (("2.0.9",), "2.0.9")):
            r = self.planned(*args)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("release: 2.0.6 -> %s" % want, r.stdout, args)

    def test_a_version_that_is_not_newer_or_not_a_version_is_refused(self):
        for bad in ("2.0.6", "2.0.5", "1.9.0", "v2.0.7", "2.0", "two", "2.0.7-beta.1"):
            r = self.planned(bad)
            self.assertEqual(r.returncode, 1, (bad, r.stdout, r.stderr))

    def test_prerelease_tags_are_not_taken_for_the_last_release(self):
        self.g("tag", "-a", "v2.1.0-beta.1", "-m", "beta")
        r = self.planned()
        self.assertIn("release: 2.0.6 -> 2.0.7", r.stdout)


class Preconditions(ReleaseCase):
    def test_a_release_is_made_from_main(self):
        self.write_items()
        self.g("checkout", "-q", "-b", "feature")
        r = self.run_release("--dry-run")
        self.assertEqual(r.returncode, 1)
        self.assertIn("from main", r.stderr)

    def test_changes_to_anything_but_the_changelog_stop_it(self):
        self.write_items()
        self.put("tweak.txt", "changed")
        r = self.run_release("--dry-run")
        self.assertEqual(r.returncode, 1)
        self.assertIn("tweak.txt", r.stderr)

    def test_an_untracked_file_stops_it_too(self):
        self.write_items()
        self.put("new.txt", "x")
        self.assertEqual(self.run_release("--dry-run").returncode, 1)

    def test_a_main_behind_origin_stops_it(self):
        self.write_items()
        other = os.path.join(self.tmp, "other")
        self.g("clone", "-q", self.origin, other, cwd=self.tmp)
        with open(os.path.join(other, "o.txt"), "w") as f:
            f.write("o")
        self.g("add", "-A", cwd=other)
        self.g("commit", "-q", "-m", "elsewhere", cwd=other)
        self.g("push", "-q", "origin", "main", cwd=other)
        r = self.run_release("--dry-run")
        self.assertEqual(r.returncode, 1)
        self.assertIn("behind", r.stderr)


class Bump(ReleaseCase):
    def test_bump_only_rewrites_the_three_files_and_commits_nothing(self):
        self.write_items()
        head = self.head()
        r = self.run_release("--bump-only")
        self.assertEqual(r.returncode, 0, r.stderr)
        text = self.read("CHANGELOG.md")
        # the empty Unreleased stays on top, and the items now belong to the new dated entry
        self.assertRegex(text, r"## \[Unreleased\]\n\n## \[2\.0\.7\] - \d{4}-\d{2}-\d{2}\n\n- Fixed: the mouse wheel")
        self.assertIn("[2.0.7]: https://github.com/example/proj/releases/tag/v2.0.7\n[2.0.6]: ", text)
        self.assertEqual(text.count("## [2.0.7]"), 1)
        self.assertEqual(self.read("container/host/VERSION"), "2.0.7\n")
        self.assertIn("\nSCRIPT_VERSION=2.0.7\n", self.read("container/host/swarmbox-host"))
        self.assertTrue(os.stat(os.path.join(self.work, "container/host/swarmbox-host")).st_mode & stat.S_IXUSR, "the mode of the script stays")
        self.assertEqual(self.head(), head, "no commit")


class FullRelease(ReleaseCase):
    def test_the_whole_flow_commits_pushes_waits_for_the_ci_tags_and_verifies(self):
        self.write_items()
        r = self.run_release(FAKE_CI="slow", FAKE_PUBLISH_AFTER="3")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("RELEASED 2.0.7", r.stdout)
        self.assertIn("ci: passed", r.stdout)
        self.assertIn("verified: the checksum matches and the published script says 2.0.7", r.stdout)
        self.assertEqual(self.g("log", "-1", "--format=%s"), "release: 2.0.7")
        self.assertNotIn("Co-Authored-By", self.g("log", "-1", "--format=%B"))
        self.assertEqual(self.g("rev-parse", "main", cwd=self.origin), self.head(), "main is pushed")
        self.assertEqual(self.g("rev-parse", "v2.0.7^{commit}", cwd=self.origin), self.head(), "the tag is on the release commit")
        self.assertEqual(self.g("cat-file", "-t", "v2.0.7", cwd=self.origin), "tag", "an annotated tag")
        self.assertIn("- Fixed: the mouse wheel", self.g("show", "HEAD:CHANGELOG.md"), "the author's text is in the release commit")
        self.assertEqual(self.g("status", "--porcelain"), "")

    def test_no_wait_stops_after_the_tag(self):
        self.write_items()
        r = self.run_release("--no-wait")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("tag v2.0.7 pushed", r.stdout)
        self.assertNotIn("RELEASED", r.stdout)
        self.assertEqual(self.g("rev-parse", "v2.0.7^{commit}", cwd=self.origin), self.head())

    def test_a_ci_that_fails_leaves_no_tag_and_names_the_jobs_that_did_not_pass(self):
        self.write_items()
        r = self.run_release(FAKE_CI="fail")
        self.assertEqual(r.returncode, 1)
        self.assertIn("failure linux (ubuntu-24.04)", r.stderr, "the job that failed, although some of its steps passed")
        self.assertNotIn("macos", r.stderr)
        self.assertNotIn("browser tests", r.stderr, "a skipped job is not a failure")
        tags = self.g("tag", "--list", cwd=self.origin)
        self.assertNotIn("v2.0.7", tags)
        self.assertEqual(self.g("tag", "--list", "v2.0.7"), "")

    def test_a_gate_that_fails_puts_the_files_back_and_keeps_the_authors_text(self):
        self.write_items()
        head, edited = self.head(), self.read("CHANGELOG.md")
        r = self.run_release(SWARMBOX_RELEASE_CHECK_CMD="false")
        self.assertEqual(r.returncode, 1)
        self.assertIn("the gate failed", r.stderr)
        self.assertEqual(self.read("CHANGELOG.md"), edited, "the CHANGELOG is exactly what the author wrote")
        self.assertEqual(self.read("container/host/VERSION"), "2.0.6\n")
        self.assertIn("SCRIPT_VERSION=2.0.6", self.read("container/host/swarmbox-host"))
        self.assertEqual(self.head(), head)
        self.assertEqual(self.g("status", "--porcelain"), "M CHANGELOG.md")   # g() strips the leading space of " M"
        self.assertNotIn("v2.0.7", self.g("tag", "--list", cwd=self.origin))

    def test_a_release_check_that_fails_undoes_the_commit_and_restores_the_files(self):
        self.write_items()
        head, edited = self.head(), self.read("CHANGELOG.md")
        r = self.run_release(SWARMBOX_RELEASE_RCHECK_CMD="false")
        self.assertEqual(r.returncode, 1)
        self.assertIn("release check failed", r.stderr)
        self.assertEqual(self.head(), head, "the release commit was undone")
        self.assertEqual(self.read("CHANGELOG.md"), edited)
        self.assertEqual(self.read("container/host/VERSION"), "2.0.6\n")
        self.assertEqual(self.g("rev-parse", "main", cwd=self.origin), head, "nothing was pushed")

    def test_a_published_script_whose_checksum_does_not_match_is_a_failure(self):
        self.write_items()
        self.set_sha("0" * 64)
        r = self.run_release()
        self.assertEqual(r.returncode, 1)
        self.assertIn("checksum", r.stderr)

    def test_a_published_script_that_reports_another_version_is_a_failure(self):
        self.write_items()
        script = "#!/bin/sh\n[ \"$1\" = version ] && echo 2.0.6\n"
        with open(os.path.join(self.fake, "swarmbox"), "w") as f:
            f.write(script)
        self.set_sha(hashlib.sha256(script.encode()).hexdigest())
        r = self.run_release()
        self.assertEqual(r.returncode, 1)
        self.assertIn("says '2.0.6', not 2.0.7", r.stderr)


class Housekeeping(unittest.TestCase):
    def test_the_script_parses_and_is_executable_and_linted_by_ci(self):
        self.assertEqual(subprocess.run(["sh", "-n", RELEASE], capture_output=True, text=True).returncode, 0)
        self.assertTrue(os.stat(RELEASE).st_mode & stat.S_IXUSR)
        with open(os.path.join(ROOT, ".github", "workflows", "ci.yml")) as f:
            self.assertIn("dev/release.sh", f.read())

    def test_contributing_describes_the_release_command(self):
        with open(os.path.join(ROOT, "CONTRIBUTING.md")) as f:
            text = f.read()
        self.assertIn("dev/release.sh", text)
        self.assertIn("[Unreleased]", text)


if __name__ == "__main__":
    unittest.main()
