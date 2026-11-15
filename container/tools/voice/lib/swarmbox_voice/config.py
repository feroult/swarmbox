"""Box-side settings of the voice tool: the ONE place of the defaults.

The host passes only the non-default values, as SWARMBOX_VOICE_* variables (language, stt model, stt vocabulary,
planner, planner model, web). Missing or empty means the default. Invalid values raise ConfigError.
"""
import re
from collections import namedtuple

DEFAULTS = {
    "language": "auto",
    "stt_model": "small",
    "stt_vocabulary": "",
    "planner": "passthrough",
    "planner_model": "",
    "web": "1",
}
ENV = {
    "language": "SWARMBOX_VOICE_LANGUAGE",
    "stt_model": "SWARMBOX_VOICE_STT_MODEL",
    "stt_vocabulary": "SWARMBOX_VOICE_STT_VOCABULARY",
    "planner": "SWARMBOX_VOICE_PLANNER",
    "planner_model": "SWARMBOX_VOICE_PLANNER_MODEL",
    "web": "SWARMBOX_VOICE_WEB",
}
MAX_VOCABULARY = 500

Config = namedtuple("Config", sorted(DEFAULTS))


class ConfigError(ValueError):
    pass


def _check(key, value):
    if "\n" in value or "\r" in value or "\0" in value:
        raise ConfigError("%s: no line breaks allowed" % ENV[key])
    if key == "language":
        if value != "auto" and not re.fullmatch(r"[a-z]{2,3}", value):
            raise ConfigError("%s: use auto or a Whisper code such as pt (not pt-br)" % ENV[key])
    elif key == "stt_model":
        if not re.fullmatch(r"[a-z0-9][a-z0-9._-]*", value) or value.endswith(".en"):
            raise ConfigError("%s: a multilingual model name (never *.en)" % ENV[key])
    elif key == "stt_vocabulary":
        if len(value) > MAX_VOCABULARY:
            raise ConfigError("%s: at most %d characters" % (ENV[key], MAX_VOCABULARY))
    elif key == "planner":
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", value):
            raise ConfigError("%s: a planner name (lowercase letters, digits, - and _)" % ENV[key])
    elif key == "web":
        if value not in ("0", "1"):
            raise ConfigError("%s: 0 or 1" % ENV[key])
    elif key == "planner_model":
        if not re.fullmatch(r"[A-Za-z0-9._:/][A-Za-z0-9._:/-]*", value):
            raise ConfigError("%s: letters, digits and . _ : / -, no blanks" % ENV[key])


def load(env):
    """Config from a mapping (pass os.environ, or an explicit dict in tests)."""
    values = {}
    for key, default in DEFAULTS.items():
        raw = env.get(ENV[key], "")
        value = raw if raw != "" else default
        if value != "":
            _check(key, value)
        values[key] = value
    return Config(**values)
