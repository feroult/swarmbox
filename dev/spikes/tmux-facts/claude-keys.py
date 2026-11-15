# The experiment that tested keys and Enter against the real Claude Code TUI (see the report, section send-keys).
import os, subprocess, time, sys
sys.path.insert(0,"/src/dev/spikes/tmux-facts")
os.environ["TMUXFACTS_TMUX"]="tmux -L cl3"
import tmuxfacts as tf
env=dict(os.environ); env.pop("TMUX",None)
def tm(*a): return subprocess.run(["tmux","-L","cl3"]+list(a),capture_output=True,text=True,env=env).stdout
tm("new-session","-d","-s","main","-n","c","-x","110","-y","40","-c","/work/proj")
tm("send-keys","-t","main:","-l","cd /work/proj && claude --permission-mode default"); tm("send-keys","-t","main:","Enter")
for i in range(15):
    time.sleep(3); s=tf.screen("main:c" if False else "0")["text"]
    if "Is this a project you created" in s: tm("send-keys","-t","main:","Down"); time.sleep(.5); tm("send-keys","-t","main:","Enter")
    elif "Yes, I trust these settings" in s or "Press Enter" in s: tm("send-keys","-t","main:","Enter")
    elif "for shortcuts" in s: break
r=tf.screen("0")
print("ready:", r["alternate"], r["cursor"], r["in_mode"], r["size"], tf.list_tabs()[0].command)
def show(tag): print("---",tag); print("\n".join(l for l in tf.screen("0")["text"].split("\n") if l.strip()))
tf.send("0","Reply with just the word PONG{Enter}",pause=0.15); time.sleep(9); show("pause 150ms then Enter")
subprocess.run(["tmux","-L","cl3","send-keys","-t","0","-l","--","Reply with just the word PING"],env=env)
subprocess.run(["tmux","-L","cl3","send-keys","-t","0","Enter"],env=env); time.sleep(9); show("two tmux calls back to back, no pause")
subprocess.run(["tmux","-L","cl3","send-keys","-t","0","-l","--","Reply with just the word RAW\r"],env=env); time.sleep(9); show("CR inside the literal text")
tm("kill-server")
