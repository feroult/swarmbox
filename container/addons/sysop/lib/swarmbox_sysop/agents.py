"""The agent registry of the box (swarmbox_agents.py, docs/agents-design.md) for the sysop: which programs are agents, their names, their
secrets. The library is the box's own (/usr/local/lib/swarmbox), or the repository's when the sysop runs from a checkout (the tests)."""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
for _d in (os.path.normpath(os.path.join(_HERE, "..", "..", "..", "..", "scripts")), "/usr/local/lib/swarmbox"):
    if os.path.isfile(os.path.join(_d, "swarmbox_agents.py")):
        if _d not in sys.path:
            sys.path.insert(0, _d)
        break

import swarmbox_agents as registry  # noqa: E402,F401


def pick(role, env=None):
    """The agent that serves the sysop as `role` ("brain": its BRAIN, "namer": its NAMER): the default agent of the box when it declares
    one, else the first installed agent that does, else the first whose command is on PATH; None when no agent declares one."""
    env = os.environ if env is None else env
    field = {"brain": "brain", "namer": "namer"}[role]
    cands = [a for a in registry.agents(env) if a[field]]
    if not cands:
        return None
    d = registry.get(registry.default_agent(env), env)
    if d and d[field]:
        return d
    for a in cands:
        if a["installed"]:
            return a
    import shutil
    for a in cands:
        if shutil.which(a["cmd"], path=env.get("PATH")):
            return a
    return cands[0]
