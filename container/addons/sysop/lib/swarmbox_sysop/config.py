"""Settings of the sysop: the ONE place of the defaults and of the checks.

The host passes the non-default values as SWARMBOX_SYSOP_* variables (the same way voice gets SWARMBOX_VOICE_*); missing or empty means the
default. A wrong value raises ConfigError with a line that names the variable: the service does not start with a setting it cannot honour.

  SWARMBOX_SYSOP_BRAIN             `auto` (default: the brain an agent of the box declares), an agent's name (its preset) or a command
                                   template, see brain.py: split into words like a shell would, but never run
                                   by a shell. {mcp_config} is required; {model}, {system_prompt_file}, {system_prompt}, {max_turns} and {goal_dir}
                                   are known; leading NAME=value words are environment; {{ and }} are literal braces
  SWARMBOX_SYSOP_TOPIC             the bus topic the sysop listens on for goals (default goal); voice publishes on its own voice.topic: they meet by
                                   the same name. 1 to 63 characters of a-z 0-9 . _ - (a digit or a letter first)
  SWARMBOX_SYSOP_GROUP             the group the sysop subscribes with (default sysop; same characters): sysops of one group share the goals, one gets each
  SWARMBOX_SYSOP_MODEL             model name for the brain (default auto: the MODEL of the brain's agent, sonnet for Claude Code)
  SWARMBOX_SYSOP_AUTONOMY          full-auto (default) | auto | confirm-risky | confirm-all, see policy.py
  SWARMBOX_SYSOP_COUNTDOWN         seconds a low-risk action waits for a veto (default 4; 0 = none)
  SWARMBOX_SYSOP_APPROVAL_TIMEOUT  seconds a high-risk action waits for the word `run` before it is refused (default 60)
  SWARMBOX_SYSOP_MAX_STEPS         tool calls (not say/done) per goal (default 20)
  SWARMBOX_SYSOP_MAX_SECONDS       seconds per goal, the brain is killed after that (default 300)
  SWARMBOX_SYSOP_MAX_GOALS         goals that may wait in the queue (default 5)
"""
import re
from collections import namedtuple

DEFAULTS = {
    "topic": "goal",
    "group": "sysop",
    "brain": "auto",
    "model": "auto",
    "autonomy": "full-auto",
    "autoname": "1",
    "countdown": "4",
    "approval_timeout": "60",
    "max_steps": "20",
    "max_seconds": "300",
    "max_goals": "5",
}
ENV = {k: "SWARMBOX_SYSOP_" + k.upper() for k in DEFAULTS}
AUTONOMY = ("confirm-all", "confirm-risky", "auto", "full-auto")
MAX_BRAIN = 2000

Config = namedtuple("Config", sorted(DEFAULTS))


class ConfigError(ValueError):
    pass


def _number(name, raw, lo, hi, integer):
    try:
        v = int(raw) if integer else float(raw)
    except ValueError:
        raise ConfigError("%s: %s expected, got %r" % (name, "a whole number" if integer else "a number", raw))
    if v != v or not lo <= v <= hi:
        raise ConfigError("%s: between %g and %g, got %s" % (name, lo, hi, raw))
    return v


def goal_topic(env=None):
    """The topic goals are published on (what the service listens to): SWARMBOX_SYSOP_TOPIC, default `goal`. Raises ConfigError. For the publishers
    (the web panel, the key g, `swarmbox-sysop goal`), which read one setting and not all of them."""
    import os
    env = os.environ if env is None else env
    raw = env.get(ENV["topic"], "")
    raw = raw if raw.strip() != "" else DEFAULTS["topic"]
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,62}", raw):
        raise ConfigError("%s: a name of 1 to 63 characters (a-z 0-9 . _ -, a letter or a digit first)" % ENV["topic"])
    return raw


def load(env):
    """Config from a mapping (pass os.environ, or an explicit dict in tests); numbers are converted."""
    raw = {}
    for key, default in DEFAULTS.items():
        v = env.get(ENV[key], "")
        raw[key] = v if v.strip() != "" else default
        if "\0" in raw[key] or (key != "brain" and ("\n" in raw[key] or "\r" in raw[key])):
            raise ConfigError("%s: no line breaks or NUL allowed" % ENV[key])
    v = {}
    for key in ("topic", "group"):
        if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,62}", raw[key]):
            raise ConfigError("%s: a name of 1 to 63 characters (a-z 0-9 . _ -, a letter or a digit first)" % ENV[key])
        v[key] = raw[key]
    brain = raw["brain"].strip()
    if len(brain) > MAX_BRAIN:
        raise ConfigError("%s: at most %d characters" % (ENV["brain"], MAX_BRAIN))
    from . import brain as brainmod            # the template is checked where it is understood
    if brain != brainmod.AUTO:                 # auto is resolved for each goal: the agents of the box may change
        try:
            brainmod.parse_template(brain)
        except brainmod.TemplateError as e:
            raise ConfigError("%s: %s" % (ENV["brain"], e))
    v["brain"] = brain
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,99}", raw["model"]):
        raise ConfigError("%s: a model name (letters, digits and . _ : / -, no blanks or quotes)" % ENV["model"])
    v["model"] = raw["model"]
    if raw["autonomy"] not in AUTONOMY:
        raise ConfigError("%s: one of %s" % (ENV["autonomy"], ", ".join(AUTONOMY)))
    v["autonomy"] = raw["autonomy"]
    an = raw["autoname"].strip().lower()
    if an not in ("0", "1", "true", "false"):
        raise ConfigError("%s: 0 or 1 expected, got %r" % (ENV["autoname"], raw["autoname"]))
    v["autoname"] = an in ("1", "true")
    v["countdown"] = _number(ENV["countdown"], raw["countdown"], 0, 60, False)
    v["approval_timeout"] = _number(ENV["approval_timeout"], raw["approval_timeout"], 1, 3600, False)
    v["max_steps"] = _number(ENV["max_steps"], raw["max_steps"], 1, 500, True)
    v["max_seconds"] = _number(ENV["max_seconds"], raw["max_seconds"], 5, 86400, True)
    v["max_goals"] = _number(ENV["max_goals"], raw["max_goals"], 1, 100, True)
    return Config(**v)
