"""swarmbox_sysop: the library of the `sysop` addon (stdlib only, Python 3.9+).

The sysop takes goals from the bus (the topic of `sysop.topic`, default `goal`, as a member of the group `sysop.group`), runs a brain (a command that
speaks MCP, by default `claude -p`) with ONE set of tools, and the tools act on the tabs of the box through the command `swarmbox-tabs`, never
through the bus. Everything the brain does is rated by the host (policy.py) before it is typed, and everything is written to the audit file (audit.py). Modules:

    config       the settings (SWARMBOX_SYSOP_*), validated in one place
    paths        the run and state folders, private (0700) and checked
    busclient    the socket protocol of swarmbox-bus (publish, subscribe with a group), spoken directly: goals only
    tabsclient   the command swarmbox-tabs (list, screen, send), run as a child, its JSON parsed: the tools' only way to the tabs
    risk, policy host-computed risk, autonomy levels, countdown and approval, budgets
    audit        events.jsonl, append-only
    ipc          the files the panel and the sysop share (pending action, decision, stop request, goal state)
    mcpserver    the MCP server the brain talks to (stdio JSON-RPC): list_tabs read_tab run input wait say done
    brain        the command template and the run of the brain (own process group, timeout, stream-json kept)
    service      the resident subscriber: goal queue, one goal at a time, state files, reconnect
    panel, dock  the panel (goal, log, countdown, approval, typing a goal) and its docking in tmux (one per window, the hook, the Follower)
    cli          swarmbox-sysop serve | goal | status | stop | mcp | panel | dock
"""

__version__ = "1.0.0"      # equal to VERSION of addon.conf (tests/test_sysop_addon.py checks it)
