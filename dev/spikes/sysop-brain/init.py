"""init.py OUTDIR: summary of the init event and result of a run."""
import json, sys
d = sys.argv[1]
for line in open(d + "/stream.tsv"):
    t, _, j = line.rstrip("\n").partition("\t")
    if not j.startswith("{"): continue
    e = json.loads(j)
    if e.get("type") == "system" and e.get("subtype") == "init":
        print("init:", {k: (len(v) if isinstance(v, list) else v) for k, v in e.items() if k in ("tools", "plugins", "skills", "slash_commands", "agents", "mcp_servers", "memory_paths", "cwd", "session_id", "apiKeySource")})
    if e.get("type") == "result":
        print("result:", {k: e.get(k) for k in ("subtype", "is_error", "num_turns", "total_cost_usd", "session_id", "permission_denials")}, str(e.get("result"))[:120])
