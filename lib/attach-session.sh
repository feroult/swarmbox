# Runs INSIDE the container (start.sh sends it through `podman exec ... bash -c`) for every terminal start.sh opens.
# It opens a new window of the tmux session "main" -- the one the web terminal shows -- through a grouped session,
# so every tab of the host terminal is also a tab in the browser (and the browser's tabs can be reached from here),
# while each side keeps choosing its own current window. The grouped session goes away when you detach.
# Its status bar is off (a session option, so the browser keeps its bar): no tabs-in-tabs in the host terminal.
command -v tmux >/dev/null 2>&1 || exec bash
nw="new-window"
tmux has-session -t main 2>/dev/null || { tmux new-session -d -s main; nw="refresh-client"; }
exec tmux new-session -t main \; set-option destroy-unattached on \; set-option status off \; $nw
