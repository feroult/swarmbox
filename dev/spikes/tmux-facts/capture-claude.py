# How fixtures/claude-*.raw were captured: drives a real claude in tmux inside the container, answers the first-run dialogs and saves
# `capture-pane -p -e -J` of each screen to /tf/out. Needs CLAUDE_CODE_OAUTH_TOKEN in the environment of the container (never in a file).
import os, subprocess, time
env=dict(os.environ); env.pop("TMUX",None)
T=["tmux","-L","cl"]
def tm(*a):
    p=subprocess.run(T+list(a),capture_output=True,text=True,env=env); return (p.stdout+p.stderr)
tm("new-session","-d","-s","main","-n","c","-x","110","-y","40","-c","/work/proj")
P=tm("display","-p","-t","main:","#{pane_id}").strip()
tm("send-keys","-t",P,"-l","cd /work/proj && claude --permission-mode default"); time.sleep(.2); tm("send-keys","-t",P,"Enter")
n=0
def snap(tag):
    global n
    raw=tm("capture-pane","-t",P,"-p","-e","-J"); plain=tm("capture-pane","-t",P,"-p","-J")
    open("/tf/out/%02d-%s.raw"%(n,tag),"w").write(raw); open("/tf/out/%02d-%s.txt"%(n,tag),"w").write(plain); n+=1
    return plain
for i in range(14):
    time.sleep(4)
    s=snap("boot%d"%i)
    print("=== step",i); print(s[-900:])
    if "Is this a project you created" in s: tm("send-keys","-t",P,"Down"); time.sleep(.5); tm("send-keys","-t",P,"Enter")
    elif "Yes, I trust these settings" in s: tm("send-keys","-t",P,"Enter")
    elif "Choose the text style" in s or "theme" in s.lower() and "1." in s: tm("send-keys","-t",P,"Enter")
    elif "Press Enter" in s or "Enter to confirm" in s: tm("send-keys","-t",P,"Enter")
    elif "for shortcuts" in s: break
time.sleep(1)
tm("send-keys","-t",P,"-l","Use the Bash tool to run exactly: echo hi > /work/proj/a.txt"); time.sleep(.3); tm("send-keys","-t",P,"Enter")
for i in range(8):
    time.sleep(5); s=snap("prompt%d"%i); print("=== prompt step",i); print(s[-1200:])
    if "Do you want" in s or "proceed?" in s:
        tm("send-keys","-t",P,"Down"); time.sleep(.8); snap("permission-down1"); print(tm("capture-pane","-t",P,"-p")[-700:])
        tm("send-keys","-t",P,"Escape"); time.sleep(2); snap("after-esc"); break
tm("kill-server")
