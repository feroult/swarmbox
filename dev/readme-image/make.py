#!/usr/bin/env python3
"""make.py: regenerates docs/img/swarmbox-banner.gif and .png (the image at the top of the README).

Runs the real banner and the real prompt of this checkout in a tmux of its own, captures the pane while the glint crosses the letters, draws
every frame inside a dark browser window (render.py, plain CSS) and joins them. Needs tmux, starship, chromium (or google-chrome) and Pillow
(`python3 -m venv /tmp/v && /tmp/v/bin/pip install pillow`, then run this with /tmp/v/bin/python). Run: python3 dev/readme-image/make.py
"""
import os
import random
import shutil
import string
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
import render  # noqa: E402

OUT = os.path.join(ROOT, "docs", "img")
COLS, ROWS = 78, render.ROWS
GLINT = "38;5;231"   # the colour of the one column where the glint is white
BROWSER = next((b for b in ("chromium", "google-chrome", "chromium-browser") if shutil.which(b)), None)


def capture(tmp):
    """frames of the pane: [(ansi text, (cursor x, cursor y))], from a still one to a whole glint pass and a little after"""
    home = os.path.join(tmp, "home")
    work = os.path.join(home, "shop-api")
    os.makedirs(os.path.join(work, "tests"))
    git = ["git", "-C", work, "-c", "user.email=a@b", "-c", "user.name=a"]
    subprocess.run(["git", "init", "-q", "-b", "main", work], check=True)
    for name in ("app.py", "README.md", "tests/test_app.py"):
        open(os.path.join(work, name), "w").close()
    subprocess.run(git + ["add", "-A"], check=True)
    subprocess.run(git + ["commit", "-qm", "init"], check=True)
    rc = os.path.join(tmp, "rc")
    with open(rc, "w") as f:
        f.write("export HOME=%s STARSHIP_CONFIG=%s TERM=xterm-256color LANG=C.UTF-8\n" % (home, os.path.join(ROOT, "container/config/starship.toml")))
        f.write("export SWARMBOX_DIRS_SH=/dev/null SWARMBOX_BANNER_SCRIPT=%s SWARMBOX_STARSHIP_INIT=/dev/null\n" % os.path.join(ROOT, "container/scripts/banner.sh"))
        f.write(". %s 2>/dev/null\neval \"$(starship init bash)\"\ncd %s\n" % (os.path.join(ROOT, "container/config/bashrc.sh"), work))
    sock = "swarmbox-shot-" + "".join(random.choice(string.ascii_lowercase) for _ in range(6))
    env = {k: v for k, v in os.environ.items() if k not in ("TMUX", "TMUX_PANE")}

    def tm(*a):
        return subprocess.run(["tmux", "-L", sock] + list(a), env=env, capture_output=True, text=True).stdout
    tm("-f", os.path.join(ROOT, "container/config/tmux.conf"), "new-session", "-d", "-s", "x", "-x", str(COLS), "-y", str(ROWS), "bash --rcfile %s -i" % rc)
    try:
        time.sleep(2.5)
        tm("send-keys", "-t", "x", "ls", "Enter")
        time.sleep(1)
        frames, end = [], time.time() + 9
        while time.time() < end:
            ans = tm("capture-pane", "-e", "-p", "-t", "x")
            cx, cy = tm("display-message", "-p", "-t", "x", "#{cursor_x} #{cursor_y}").split()[:2]
            frames.append((ans, (int(cx), int(cy))))
            time.sleep(0.04)
        return frames
    finally:
        tm("kill-server")
        for d in os.listdir("/tmp"):
            if d.startswith("tmux-"):
                p = os.path.join("/tmp", d, sock)
                if os.path.exists(p):
                    os.unlink(p)


def shot(html, png, scale, transparent):
    cmd = [BROWSER, "--headless=new", "--no-sandbox", "--disable-gpu", "--hide-scrollbars", "--force-device-scale-factor=%s" % scale,
           "--window-size=840,412", "--screenshot=" + png, "file://" + html]
    if transparent:
        cmd.insert(1, "--default-background-color=00000000")
    subprocess.run(cmd, check=True, capture_output=True)


def main():
    from PIL import Image
    if not BROWSER:
        sys.exit("make.py: needs chromium or google-chrome")
    tmp = tempfile.mkdtemp(prefix="readme-image-")
    try:
        frames = capture(tmp)
        lit = [i for i, (a, _) in enumerate(frames) if GLINT in a]
        if not lit:
            sys.exit("make.py: the glint never showed in the capture")
        still = frames[max(0, lit[0] - 20)]
        run = frames[lit[0] - 2:lit[-1] + 3]
        jobs = [(still, True)] + [(f, False) for f in run]
        pngs = []
        for i, (f, first) in enumerate(jobs):
            html = os.path.join(tmp, "f%03d.html" % i)
            with open(html, "w") as fh:
                fh.write(render.render(f[0], f[1], page="#07060a"))
            pngs.append((html, os.path.join(tmp, "f%03d.png" % i)))
        with ThreadPoolExecutor(8) as pool:
            list(pool.map(lambda p: shot(p[0], p[1], 2, False), pngs))
        os.makedirs(OUT, exist_ok=True)
        html = os.path.join(tmp, "still.html")
        with open(html, "w") as fh:
            fh.write(render.render(still[0], still[1], page="transparent"))
        shot(html, os.path.join(OUT, "swarmbox-banner.png"), 2, True)
        ims = [Image.open(p[1]).convert("RGB") for p in pngs]
        w, h = ims[0].size
        mosaic = Image.new("RGB", (w, h * 3))
        for i, k in enumerate((0, len(ims) // 2, len(ims) // 2 + 4)):
            mosaic.paste(ims[k], (0, i * h))
        pal = mosaic.quantize(256, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
        out = [im.quantize(palette=pal, dither=Image.Dither.FLOYDSTEINBERG) for im in ims]
        out[0].save(os.path.join(OUT, "swarmbox-banner.gif"), save_all=True, append_images=out[1:],
                    duration=[2600] + [50] * (len(out) - 1), loop=0, optimize=True, disposal=1)
        print("wrote docs/img/swarmbox-banner.gif (%d frames) and .png" % len(out))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
