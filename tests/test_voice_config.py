"""Voice settings: the box-side module (the one place of the defaults), the six host keys of `swarmbox config`, and the docs.

The host helper runs as a real program with a cleared environment (the Base of test_host_create_flags: a mktemp HOME, a fixture
tool-ports, no Podman). Keys: voice.language (auto), voice.stt.model (small), voice.stt.vocabulary (empty), voice.planner
(passthrough), voice.planner.model (empty). They reach the box as SWARMBOX_VOICE_* at creation, only when they differ from the
default, so a box that never set one keeps its fingerprint. Run with: python3 -W error tests/test_voice_config.py
"""
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import voice_support  # noqa: E402
import test_host_create_flags as cf  # noqa: E402
from helpers import ROOT  # noqa: E402

from swarmbox_voice import config  # noqa: E402

# key -> (default, env name, a good value, bad values)
KEYS = {
    "voice.language": ("auto", "SWARMBOX_VOICE_LANGUAGE", "pt", ["pt-br", "PT", "p", "portuguese", "p t", "a1"]),
    "voice.stt.model": ("small", "SWARMBOX_VOICE_STT_MODEL", "medium", ["small.en", "tiny.en", "Small", "../x", "a b", "-x", "a/b"]),
    "voice.stt.vocabulary": ("", "SWARMBOX_VOICE_STT_VOCABULARY", "kubectl, Podman, swarmbox", ["x" * 501]),
    "voice.planner": ("passthrough", "SWARMBOX_VOICE_PLANNER", "claude", ["Claude", "a b", "-x", "a/b", "a.b"]),
    "voice.planner.model": ("", "SWARMBOX_VOICE_PLANNER_MODEL", "haiku", ["a b", "-x", "a;b", "$(x)", "a\tb"]),
    "voice.web": ("1", "SWARMBOX_VOICE_WEB", "0", ["yes", "2", "true", "on", "00"]),
}
ORDER = list(KEYS)


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


class BoxSideTests(unittest.TestCase):
    def test_defaults(self):
        c = config.load({})
        self.assertEqual((c.language, c.stt_model, c.stt_vocabulary, c.planner, c.planner_model, c.web), ("auto", "small", "", "passthrough", "", "1"))
        self.assertEqual(c, config.load({k: "" for _, (_, k, _, _) in KEYS.items()}), "empty means default")
        self.assertEqual({v[0] for v in KEYS.values()}, {"auto", "small", "", "passthrough", "1"})

    def test_the_host_defaults_equal_the_box_defaults(self):
        for key, (default, env, _, _) in KEYS.items():
            self.assertEqual(config.DEFAULTS[env.replace("SWARMBOX_VOICE_", "").lower()], default, key)
            self.assertEqual(config.ENV[env.replace("SWARMBOX_VOICE_", "").lower()], env)

    def test_overrides_and_validation(self):
        for key, (_, env, good, bad) in KEYS.items():
            attr = env.replace("SWARMBOX_VOICE_", "").lower()
            self.assertEqual(getattr(config.load({env: good}), attr), good)
            for value in bad:
                with self.assertRaises(config.ConfigError, msg="%s=%r" % (env, value)):
                    config.load({env: value})

    def test_the_environment_is_read_only_from_the_given_mapping(self):
        os.environ["SWARMBOX_VOICE_LANGUAGE"] = "fr"
        self.addCleanup(os.environ.pop, "SWARMBOX_VOICE_LANGUAGE", None)
        self.assertEqual(config.load({}).language, "auto")
        self.assertEqual(config.load(os.environ).language, "fr")


class HostKeyTests(cf.Base):
    def get(self, key, env=None, cfg=None):
        p = self.run_h("config", "get", key, env=env, cfg=cfg)
        return p.returncode, p.stdout, p.stderr

    def test_list_has_the_six_keys_last_with_their_defaults(self):
        p = self.run_h("config", "list")
        self.assertEqual(p.returncode, 0, p.stderr)
        rows = p.stdout.splitlines()
        self.assertEqual([r.split("=")[0] for r in rows][-12:-6], ORDER)
        for row, key in zip(rows[-12:-6], ORDER):
            self.assertEqual(row, "%s=%s\tdefault" % (key, KEYS[key][0]))

    def test_get_set_roundtrip_and_empty_resets_to_the_default(self):
        for key, (default, _, good, _) in KEYS.items():
            rc, out, _ = self.get(key)
            self.assertEqual((rc, out), (0, default + "\n") if default else (1, ""), key)
            p = self.run_h("config", "set", key, good)
            self.assertEqual((p.returncode, p.stderr), (0, ""), key)
            self.assertEqual(self.get(key), (0, good + "\n", ""), key)
            self.assertIn("%s=%s\n" % (key, good), read(os.path.join(self.cfgroot, "config")))
            self.assertEqual(self.run_h("config", "set", key, "").returncode, 0)
            self.assertEqual(self.get(key)[1], default + "\n" if default else "", key)

    def test_bad_values_are_exit_2_and_not_written(self):
        for key, (_, _, _, bad) in KEYS.items():
            for value in bad:
                p = self.run_h("config", "set", key, value)
                self.assertEqual(p.returncode, 2, "%s=%r" % (key, value))
                self.assertIn("invalid value for %s" % key, p.stderr)
        self.assertFalse(os.path.exists(os.path.join(self.cfgroot, "config")))
        self.assertEqual(self.run_h("config", "set", "voice.nosuch", "x").returncode, 2)
        self.assertEqual(self.run_h("config", "set", "VOICE_LANGUAGE", "pt").returncode, 2)

    def test_environment_wins_over_the_file(self):
        for key, (_, env, good, _) in KEYS.items():
            self.run_h("config", "set", key, "x" if key == "voice.stt.vocabulary" else good)
            rc, out, _ = self.get(key, env={env: "env-value" if key == "voice.stt.vocabulary" else good})
            self.assertEqual(rc, 0)
            row = [r for r in self.run_h("config", "list", env={env: "from-env"}).stdout.splitlines() if r.startswith(key + "=")][0]
            self.assertEqual(row, "%s=from-env\tenv" % key)

    def clear(self):
        if os.path.exists(os.path.join(self.cfgroot, "config")):
            os.remove(os.path.join(self.cfgroot, "config"))

    def test_nothing_set_means_no_voice_flag_and_the_old_fingerprint(self):
        flags = self.flags()
        self.assertFalse([f for f in flags if "VOICE" in f])
        lines = self.fp_lines()
        self.assertFalse([x for x in lines if "VOICE" in x])
        self.assertEqual(self.fp(), cf.fingerprint(lines, cf.env_hash([])))

    def test_a_default_value_set_explicitly_changes_nothing(self):
        base = self.fp()
        cfg = "voice.language=auto\nvoice.stt.model=small\nvoice.planner=passthrough\nvoice.stt.vocabulary=\nvoice.web=1\n"
        self.assertEqual(self.fp(cfg=cfg), base)
        self.assertFalse([f for f in self.flags(cfg=cfg) if "VOICE" in f])

    def test_set_values_reach_the_box_as_flags_and_change_the_fingerprint(self):
        cfg = ("voice.language=pt\nvoice.stt.model=medium\nvoice.stt.vocabulary=kubectl, Podman, $HOME 'x'\n"
               "voice.planner=claude\nvoice.planner.model=haiku\nvoice.web=0\n")
        base = self.fp()
        flags = self.flags(cfg=cfg)
        got = [flags[i + 1] for i, f in enumerate(flags) if f == "-e" and flags[i + 1].startswith("SWARMBOX_VOICE_")]
        self.assertEqual(got, ["SWARMBOX_VOICE_LANGUAGE=pt", "SWARMBOX_VOICE_STT_MODEL=medium",
                               "SWARMBOX_VOICE_STT_VOCABULARY=kubectl, Podman, $HOME 'x'", "SWARMBOX_VOICE_PLANNER=claude",
                               "SWARMBOX_VOICE_PLANNER_MODEL=haiku", "SWARMBOX_VOICE_WEB=0"])
        lines = self.fp_lines({"SWARMBOX_VOICE_LANGUAGE": "pt", "SWARMBOX_VOICE_STT_MODEL": "medium",
                               "SWARMBOX_VOICE_STT_VOCABULARY": "kubectl, Podman, $HOME 'x'",
                               "SWARMBOX_VOICE_PLANNER": "claude", "SWARMBOX_VOICE_PLANNER_MODEL": "haiku",
                               "SWARMBOX_VOICE_WEB": "0"})
        self.assertEqual(self.fp(cfg=cfg), cf.fingerprint(lines, cf.env_hash([])))
        self.assertNotEqual(self.fp(cfg=cfg), base)
        self.assertNotEqual(self.fp(cfg="voice.language=pt\n"), self.fp(cfg="voice.language=en\n"))

    def test_an_invalid_value_in_the_file_or_environment_stops_create_flags(self):
        self.assertEqual(self.cf(cfg="voice.language=pt-br\n").returncode, 2)
        self.clear()
        self.assertEqual(self.cf(env={"SWARMBOX_VOICE_STT_MODEL": "small.en"}).returncode, 2)
        flags = self.flags(env={"SWARMBOX_VOICE_PLANNER": "claude"})
        self.assertIn("SWARMBOX_VOICE_PLANNER=claude", flags)

    def test_an_unknown_dotted_key_in_the_file_is_still_reported(self):
        p = self.cf(cfg="voice.nosuch=1\n")  # noqa
        self.assertIn("voice.nosuch", p.stderr)


class DocsTests(unittest.TestCase):
    def test_design_doc_lists_the_six_keys_with_their_defaults(self):
        text = read(os.path.join(ROOT, "docs", "design.md"))
        for key, (default, env, _, _) in KEYS.items():
            row = [r for r in text.splitlines() if r.startswith("| `%s`" % key)]
            self.assertEqual(len(row), 1, key)
            self.assertIn(env, row[0], key)
            self.assertIn("`%s`" % default if default else "empty", row[0], key)

    def test_voice_doc_lists_the_keys_and_the_changelog_has_an_entry(self):
        text = read(os.path.join(ROOT, "docs", "voice.md"))
        for key in KEYS:
            self.assertIn("`%s`" % key, text)
        change = read(os.path.join(ROOT, "CHANGELOG.md"))
        unreleased = change.split("## [Unreleased]")[1].split("\n## [")[0]
        self.assertRegex(unreleased, r"- Added: .*`voice`")
        self.assertIn("swarmbox update", unreleased)

    def test_the_usage_and_every_key_are_documented_in_the_status_line_of_the_design(self):
        text = read(os.path.join(ROOT, "docs", "voice-design.md"))
        self.assertRegex(text.splitlines()[2], r"^Status: ")
        self.assertNotIn("design only, nothing is implemented", text)


if __name__ == "__main__":
    unittest.main()
