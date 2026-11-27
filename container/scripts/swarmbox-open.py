#!/usr/bin/env python3
"""swarmbox-open: open an http(s) URL from inside the box on the user's side.

Installed as /usr/local/bin/swarmbox-open, symlinked as /usr/local/bin/xdg-open,
and set as $BROWSER so agents (Claude Code, Codex, OpenCode, Antigravity, gh,
etc.) that click or open an external link do not fail with "Couldn't open your
browser".

Delivery channels:
  1. Web Studio: POST http://127.0.0.1:<port>/api/open-url broadcasts an
     `open_url` event over /ws/events so connected browsers open the URL (or
     show a 1-click toast when blocked by a popup blocker).
  2. Terminal Cockpit: writes <run_dir>/open-url.json atomically; any live
     cockpit.mjs session copies the URL via OSC 52 and shows a clickable OSC 8
     hyperlink toast in its footer.
  3. Plain terminal fallback: when neither Web Studio nor Cockpit is active,
     writes an OSC 52 clipboard sequence to /dev/tty (if writable) and exits 1
     so the calling agent still prints the URL as a fallback.

Test-only variables (not in the configuration table):
  SWARMBOX_TEST_WEB_PORT   replaces 7681 (also respects SWARMBOX_WEB_PORT)
  SWARMBOX_TEST_WEB_HOST   replaces 127.0.0.1
  SWARMBOX_TEST_RUN_DIR    replaces /tmp/swarmbox
  SWARMBOX_TEST_TTY        replaces /dev/tty
"""
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

MAX_URL_LENGTH = 4096


def validate_url(raw):
    """Return a clean http(s) URL string, or None when invalid/disallowed."""
    if not isinstance(raw, str):
        return None
    url = raw.strip()
    if not url or len(url) > MAX_URL_LENGTH:
        return None
    if any(ord(ch) < 0x20 or ord(ch) == 0x7F or ch.isspace() for ch in url):
        return None
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme.lower() not in ("http", "https") or not parsed.netloc:
        return None
    return url


def run_dir():
    return os.environ.get("SWARMBOX_TEST_RUN_DIR") or "/tmp/swarmbox"


def web_endpoint():
    host = os.environ.get("SWARMBOX_TEST_WEB_HOST") or "127.0.0.1"
    raw_port = os.environ.get("SWARMBOX_TEST_WEB_PORT") or os.environ.get("SWARMBOX_WEB_PORT") or "7681"
    try:
        port = int(raw_port)
        if not (1 <= port <= 65535):
            port = 7681
    except ValueError:
        port = 7681
    return f"http://{host}:{port}/api/open-url"


def post_to_web(url, timeout=1.5):
    """POST url to the local Web Studio server. Returns count of delivered browsers."""
    endpoint = web_endpoint()
    data = json.dumps({"url": url}).encode("utf-8")
    req = urllib.request.Request(
        endpoint,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status != 200:
                return 0
            body = json.loads(resp.read().decode("utf-8", errors="replace") or "{}")
            delivered = body.get("delivered", 0)
            return delivered if isinstance(delivered, int) and delivered > 0 else 0
    except (urllib.error.URLError, OSError, ValueError):
        return 0


def has_live_cockpit(rdir):
    """Return True when at least one cockpit.<pid> marker belongs to a live process."""
    try:
        entries = os.listdir(rdir)
    except OSError:
        return False
    for name in entries:
        if not name.startswith("cockpit."):
            continue
        pid_str = name[len("cockpit."):]
        if not pid_str.isdigit():
            continue
        pid = int(pid_str)
        if pid <= 1:
            continue
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            # Stale marker from a crashed cockpit; best-effort cleanup.
            try:
                os.unlink(os.path.join(rdir, name))
            except OSError:
                pass
        except PermissionError:
            return True
        except OSError:
            continue
    return False


def write_cockpit_event(rdir, url):
    """Atomically write <run_dir>/open-url.json for any attached cockpit."""
    try:
        os.makedirs(rdir, exist_ok=True)
        payload = {
            "id": uuid.uuid4().hex,
            "url": url,
            "ts": int(time.time() * 1000),
        }
        target = os.path.join(rdir, "open-url.json")
        tmp = os.path.join(rdir, f".open-url.{os.getpid()}.{uuid.uuid4().hex[:8]}.tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(payload, fh)
        os.replace(tmp, target)
        return True
    except OSError:
        return False


def emit_osc52(url):
    """Copy url to the host clipboard via OSC 52 on /dev/tty when available."""
    tty_path = os.environ.get("SWARMBOX_TEST_TTY") or "/dev/tty"
    b64 = base64.b64encode(url.encode("utf-8")).decode("ascii")
    seq = f"\x1b]52;c;{b64}\x07".encode("ascii")
    try:
        with open(tty_path, "wb") as fh:
            fh.write(seq)
            fh.flush()
        return True
    except OSError:
        return False


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] == "--":
        args = args[1:]
    if len(args) != 1 or args[0] in ("-h", "--help"):
        sys.stderr.write("usage: swarmbox-open <http(s)://url>\n")
        return 0 if args and args[0] in ("-h", "--help") else 2

    url = validate_url(args[0])
    if not url:
        sys.stderr.write("swarmbox-open: only valid http:// or https:// URLs are supported\n")
        return 2

    delivered = post_to_web(url)
    rdir = run_dir()
    cockpit = has_live_cockpit(rdir)
    if cockpit:
        write_cockpit_event(rdir, url)

    if delivered > 0 or cockpit:
        return 0

    # Plain terminal fallback: copy to host clipboard if a tty is attached, then exit 1
    # so the calling agent still prints the URL for the user to open manually.
    emit_osc52(url)
    return 1


if __name__ == "__main__":
    sys.exit(main())
