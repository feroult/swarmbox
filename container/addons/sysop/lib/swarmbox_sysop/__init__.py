"""swarmbox_sysop: the library of the `sysop` addon (stdlib only, Python 3.9+).

The sysop takes goals from the bus (the topic of `sysop.topic`, default `goal`, as a member of the group `sysop.group`), runs a brain (a command that
speaks MCP, by default the one an agent of the box declares) with ONE set of tools, and the tools act on the tabs of the box through the command `swarmbox-tabs`, never
through the bus. Everything the brain does is rated by the host (policy.py) before it is typed, and everything is written to the audit file (audit.py). Modules:

    config       the settings (SWARMBOX_SYSOP_*), validated in one place
    paths        the run and state folders, private (0700) and checked
    busclient    the socket protocol of swarmbox-bus (publish, subscribe with a group), spoken directly: goals only
    tabsclient   the command swarmbox-tabs (list, screen, send), run as a child, its JSON parsed: the tools' only way to the tabs
    risk, policy host-computed risk, autonomy levels, countdown and approval, budgets
    audit        events.jsonl, append-only
    ipc          the files the panels (web, cockpit) and the sysop share (pending action, decision, stop request, goal state)
    mcpserver    the MCP server the brain talks to (stdio JSON-RPC): list_tabs read_tab run input wait say done
    brain        the command template and the run of the brain (own process group, timeout, stream-json kept)
    service      the resident subscriber: goal queue, one goal at a time, state files, reconnect
    state        mux-agnostic presentation state: snapshot, clean, one_line, step_text, line_of, value_of, state_dict
    actions      mux-agnostic control actions: pending_of, is_live, veto, approve, stop, publish_goal
    agent        the OSC 7501 agent bridge for herdr-core (the Sysop as a hidden agent terminal)
    ui_host      UI lifecycle host of `serve --dock` (the herdr agent bridge, or headless when SWARMBOX_MUX=none)
    cli          swarmbox-sysop serve | goal | veto | approve | status | stop | mcp | agent
"""

__version__ = "1.0.0"      # equal to VERSION of addon.conf (tests/fast/test_sysop_addon.py checks it)
