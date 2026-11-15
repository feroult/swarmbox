#!/usr/bin/env python3
# Tiny fake "agent": prints a prompt and echoes each line it receives.
import sys
while True:
    sys.stdout.write("fake-agent> "); sys.stdout.flush()
    l = sys.stdin.readline()
    if not l: break
    sys.stdout.write(f"[fake-agent received: {l.strip()}]\n")
