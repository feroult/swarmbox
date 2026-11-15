"""A stand-in for the input box of Claude Code, for the tests of the tmux driver (no model, no network). It draws the same shapes the driver reads:
history, a rule, `❯<nbsp>` and the box text, a rule, a footer ("esc to interrupt" while busy). Like the real thing, a chunk of characters that
arrives in one read and holds a carriage return is a PASTE: the return becomes a line break in the box and nothing is submitted. A return that
arrives alone submits: the text goes to the history, the agent is busy for BUSY seconds, then answers "● ANSWER <text>".
Env: FAKE_AGENT_BUSY (seconds, default 1.0), FAKE_AGENT_DIALOG=1 (starts with a permission dialog; any key but Esc ends it)."""
import os
import select
import sys
import termios
import threading
import time
import tty

RULE = "─" * 60
busy_until = 0.0
history, box = [], ""
dialog = os.environ.get("FAKE_AGENT_DIALOG") == "1"
BUSY = float(os.environ.get("FAKE_AGENT_BUSY", "1.0"))
queued = []
lock = threading.Lock()


def draw():
    out = ["\x1b[H\x1b[2J"]
    out += [h + "\r\n" for h in history[-12:]]
    if dialog:
        out += [RULE + "\r\n", " Bash command\r\n", " Do you want to proceed?\r\n", " ❯ 1. Yes\r\n", "   2. No\r\n", "\r\n", " Esc to cancel · Tab to amend"]
    else:
        busy = time.time() < busy_until
        out += [RULE + "\r\n"]
        for i, ln in enumerate(box.split("\n")):
            out.append(("❯ " if i == 0 else "  ") + ln + "\r\n")
        out += [RULE + "\r\n", "  auto mode on (shift+tab to cycle)" + (" · esc to interrupt" if busy else "")]
    sys.stdout.write("".join(out))
    sys.stdout.flush()


def finish():
    global busy_until
    with lock:
        busy_until = 0.0
        history.append("● ANSWER " + (history[-2][2:] if len(history) >= 2 else ""))
        history.append("")
        draw()
        if queued:
            start(queued.pop(0))


def start(text):
    global busy_until
    history.append("❯ " + text.replace("\n", " "))
    history.append("")
    busy_until = time.time() + BUSY
    threading.Timer(BUSY, finish).start()


tty.setraw(0)
draw()
while True:
    r, _, _ = select.select([0], [], [], 0.2)
    with lock:
        if not r:
            draw() if time.time() >= busy_until else None
            continue
        data = os.read(0, 65536).decode("utf-8", "replace")
        if dialog:
            if data == "\x1b":
                dialog = False
            elif data in ("1", "\r"):
                dialog = False
            draw()
            continue
        if data == "\x1b":
            if time.time() < busy_until:
                busy_until = 0.0
        elif data == "\r":
            if box:
                if time.time() < busy_until:
                    queued.append(box)
                else:
                    start(box)
                box = ""
        else:
            for ch in data:
                if ch in "\r\n":
                    box += "\n"
                elif ch == "\x03":
                    box = ""
                elif ch >= " ":
                    box += ch
        draw()
