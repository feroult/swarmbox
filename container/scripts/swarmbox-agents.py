#!/usr/bin/env python3
"""swarmbox-agents (installed as /usr/local/bin/swarmbox-agents): the command line of the agent registry. The registry itself is the
library swarmbox_agents.py (/usr/local/lib/swarmbox, or next to this file in the repository); `swarmbox-agents` with no word prints usage."""
import os
import sys

for _d in (os.path.dirname(os.path.realpath(__file__)), "/usr/local/lib/swarmbox"):
    if os.path.isfile(os.path.join(_d, "swarmbox_agents.py")):
        sys.path.insert(0, _d)
        break

import swarmbox_agents  # noqa: E402

if __name__ == "__main__":
    sys.exit(swarmbox_agents.main())
