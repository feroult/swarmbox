#!/usr/bin/env bash
# Flag matrix for claude -p with the MCP server. Runs inside the container.
export PATH=/work/npm/bin:$PATH HOME=/work/home; mkdir -p $HOME
here=$(cd "$(dirname "$0")" && pwd)
export TMUX_TMPDIR=$(mktemp -d) SYSOP_TMUX_SOCKET=spk
tmux -L spk new-session -d -s main -n shop-api -x 100 -y 20
tmux -L spk new-window -d -t main -n agent
D=$(mktemp -d); cat >$D/mcp.json <<JSON
{"mcpServers":{"tmux":{"command":"python3","args":["$here/mcp_tmux.py"],"env":{"SYSOP_TMUX_SOCKET":"spk"}}}}
JSON
SYS=$(cat $here/system-prompt.txt)
G="list the tabs, then call done"
t() { # name, then flags
  n=$1; shift
  out=$(timeout 60 claude -p "$@" --model haiku --output-format stream-json --verbose <<<"$G" 2>&1); rc=$?
  echo "--- $n rc=$rc"
  echo "$out" | python3 -c "
import sys,json
tools=None;res=None;err=[]
for l in sys.stdin:
  try: e=json.loads(l)
  except Exception: err.append(l.strip()[:200]); continue
  if e.get('type')=='system' and e.get('subtype')=='init': tools=(len(e['tools']),[t for t in e['tools'] if not t.startswith('mcp__tmux')][:12],e.get('permissionMode'),[m['status'] for m in e.get('mcp_servers',[])])
  if e.get('type')=='result': res=(e.get('subtype'),e.get('num_turns'),e.get('is_error'),e.get('permission_denials'),str(e.get('result'))[:100])
print(' init:',tools); print(' result:',res)
for x in err[:3]: print(' raw:',x)
"
}
C="--mcp-config $D/mcp.json --strict-mcp-config --no-session-persistence --system-prompt SYS"
t A-baseline          --mcp-config $D/mcp.json --strict-mcp-config --tools "" --allowedTools 'mcp__tmux__*' --permission-mode dontAsk --system-prompt "$SYS"
t B-no-tools-flag     --mcp-config $D/mcp.json --strict-mcp-config --allowedTools 'mcp__tmux__*' --permission-mode dontAsk --system-prompt "$SYS"
t C-no-allowedTools-dontAsk --mcp-config $D/mcp.json --strict-mcp-config --tools "" --permission-mode dontAsk --system-prompt "$SYS"
t D-no-allowedTools-default --mcp-config $D/mcp.json --strict-mcp-config --tools "" --system-prompt "$SYS"
t E-no-allowedTools-prompts-none --mcp-config $D/mcp.json --strict-mcp-config --tools "" --permission-prompts none --system-prompt "$SYS"
t F-bypass --mcp-config $D/mcp.json --strict-mcp-config --tools "" --permission-mode bypassPermissions --system-prompt "$SYS"
t G-max-turns --mcp-config $D/mcp.json --strict-mcp-config --tools "" --allowedTools 'mcp__tmux__*' --max-turns 2 --system-prompt "$SYS"
t H-safe-mode --safe-mode --mcp-config $D/mcp.json --strict-mcp-config --tools "" --allowedTools 'mcp__tmux__*' --permission-mode dontAsk --system-prompt "$SYS"
t I-bare --bare --mcp-config $D/mcp.json --strict-mcp-config --tools "" --allowedTools 'mcp__tmux__*' --permission-mode dontAsk --system-prompt "$SYS"
t J-restricted --restricted --mcp-config $D/mcp.json --strict-mcp-config --allowedTools 'mcp__tmux__*' --permission-mode dontAsk --system-prompt "$SYS"
t K-append-system-prompt --mcp-config $D/mcp.json --strict-mcp-config --tools "" --allowedTools 'mcp__tmux__*' --permission-mode dontAsk --append-system-prompt "$SYS"
t L-inline-mcp-json --mcp-config "$(cat $D/mcp.json)" --strict-mcp-config --tools "" --allowedTools 'mcp__tmux__*' --permission-mode dontAsk --system-prompt "$SYS"
t M-disallow-builtin --mcp-config $D/mcp.json --strict-mcp-config --disallowedTools Bash Edit Write --allowedTools 'mcp__tmux__*' --permission-mode dontAsk --system-prompt "$SYS"
t N-setting-sources-empty --setting-sources "" --mcp-config $D/mcp.json --strict-mcp-config --tools "" --allowedTools 'mcp__tmux__*' --permission-mode dontAsk --system-prompt "$SYS"
echo "--- O: goal as argument"
timeout 60 claude -p "list the tabs, then call done" --model haiku --mcp-config $D/mcp.json --strict-mcp-config --tools "" --allowedTools 'mcp__tmux__*' --permission-mode dontAsk --system-prompt "$SYS" 2>&1 | head -c 300
echo; echo "--- P: text output"
timeout 60 claude -p --model haiku --mcp-config $D/mcp.json --strict-mcp-config --tools "" --allowedTools 'mcp__tmux__*' --permission-mode dontAsk --system-prompt "$SYS" <<<"$G" 2>&1 | head -c 300
echo; echo "--- Q: no token (to see error)"; env -u CLAUDE_CODE_OAUTH_TOKEN claude -p --model haiku <<<hi 2>&1 | head -c 200
tmux -L spk kill-server
