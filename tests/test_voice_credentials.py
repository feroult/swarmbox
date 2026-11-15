"""Which login variables reach a planner. A box may log in to Claude Code with a variable; the built-in `claude` planner needs it,
nothing else may see it."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import voice_support  # noqa: E402,F401

from swarmbox_voice import planners  # noqa: E402

BASE = {"PATH": "/usr/bin", "HOME": "/home/x", "LANG": "C.UTF-8", "CLAUDE_CODE_OAUTH_TOKEN": "tok-oauth",
        "ANTHROPIC_API_KEY": "key-api", "CLAUDE_CODE_MESSAGING_TOKEN": "internal", "AWS_SECRET_ACCESS_KEY": "aws",
        "GITHUB_TOKEN": "gh", "SWARMBOX_VOICE_PLANNER_MODEL": "haiku"}


class CredentialTest(unittest.TestCase):
    def test_builtin_claude_gets_its_login_variables(self):
        env = planners.planner_env(BASE, None, planners.Planner("claude", "/x/planner-claude", "builtin"))
        self.assertEqual(env["CLAUDE_CODE_OAUTH_TOKEN"], "tok-oauth")
        self.assertEqual(env["ANTHROPIC_API_KEY"], "key-api")
        self.assertEqual(env["SWARMBOX_VOICE_PLANNER_MODEL"], "haiku")

    def test_nothing_else_of_the_box_reaches_it(self):
        env = planners.planner_env(BASE, None, planners.Planner("claude", "/x/planner-claude", "builtin"))
        for k in ("CLAUDE_CODE_MESSAGING_TOKEN", "AWS_SECRET_ACCESS_KEY", "GITHUB_TOKEN"):
            self.assertNotIn(k, env)

    def test_a_user_planner_called_claude_gets_nothing(self):
        env = planners.planner_env(BASE, None, planners.Planner("claude", "/home/x/planner-claude", "user"))
        self.assertNotIn("CLAUDE_CODE_OAUTH_TOKEN", env)
        self.assertNotIn("ANTHROPIC_API_KEY", env)

    def test_other_planners_and_plain_paths_get_nothing(self):
        for who in (planners.Planner("passthrough", "/x/planner-passthrough", "builtin"), "/some/path", None):
            env = planners.planner_env(BASE, None, who)
            self.assertNotIn("CLAUDE_CODE_OAUTH_TOKEN", env, who)
            self.assertNotIn("ANTHROPIC_API_KEY", env, who)

    def test_an_unset_or_empty_variable_is_not_invented(self):
        env = planners.planner_env({"PATH": "/usr/bin", "ANTHROPIC_API_KEY": ""}, None,
                                   planners.Planner("claude", "/x/planner-claude", "builtin"))
        self.assertNotIn("ANTHROPIC_API_KEY", env)


if __name__ == "__main__":
    unittest.main()
