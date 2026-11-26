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
