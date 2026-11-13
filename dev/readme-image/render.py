"""render.py FRAME.ans OUT.html [--cursor X Y] : a captured tmux pane (ANSI) inside a dark macOS-style browser window."""
import html, re, sys

def xterm256(n):
    base = ["#000000","#cd0000","#00cd00","#cdcd00","#0000ee","#cd00cd","#00cdcd","#e5e5e5",
            "#7f7f7f","#ff0000","#00ff00","#ffff00","#5c5cff","#ff00ff","#00ffff","#ffffff"]
    if n < 16: return base[n]
    if n < 232:
        n -= 16; lv = [0, 95, 135, 175, 215, 255]
        return "#%02x%02x%02x" % (lv[n // 36], lv[n // 6 % 6], lv[n % 6])
    g = 8 + (n - 232) * 10
    return "#%02x%02x%02x" % (g, g, g)

BLOCKS = '▀▄█'
ROWS = 12
BG, FG = "#0c0b10", "#d4d4d8"
SGR = re.compile(r"\x1b\[([0-9;]*)m")

def cells(text):
    """rows of (char, fg, bg, bold)"""
    rows = []
    fg = bg = None; bold = False
    for line in text.split("\n"):
        row = []; pos = 0
        for m in SGR.finditer(line):
            for ch in line[pos:m.start()]: row.append((ch, fg, bg, bold))
            pos = m.end()
            codes = [c for c in (m.group(1) or "0").split(";")]
            i = 0
            while i < len(codes):
                c = codes[i]
                if c in ("0", ""): fg = bg = None; bold = False
                elif c == "1": bold = True
                elif c == "22": bold = False
                elif c == "39": fg = None
                elif c == "49": bg = None
                elif c in ("38", "48") and i + 2 < len(codes) and codes[i+1] == "5":
                    col = xterm256(int(codes[i+2])); i += 2
                    if c == "38": fg = col
                    else: bg = col
                elif c in ("38", "48") and i + 4 < len(codes) and codes[i+1] == "2":
                    col = "#%02x%02x%02x" % tuple(int(x) for x in codes[i+2:i+5]); i += 4
                    if c == "38": fg = col
                    else: bg = col
                elif c.isdigit() and 30 <= int(c) <= 37: fg = xterm256(int(c) - 30)
                elif c.isdigit() and 90 <= int(c) <= 97: fg = xterm256(int(c) - 90 + 8)
                i += 1
        for ch in line[pos:]: row.append((ch, fg, bg, bold))
        rows.append(row)
    return rows

def body(rows, cols, cur):
    out = []
    for y, row in enumerate(rows):
        row = row + [(" ", None, None, False)] * (cols - len(row))
        if cur and y == cur[1]:
            ch, fg, bg, b = row[cur[0]]; row[cur[0]] = (ch if ch != " " else " ", BG, "#c4b5fd", b)
        spans = []; i = 0
        while i < len(row):
            j = i
            if row[i][0] in BLOCKS:
                ch, fg, bg, b = row[i]
                top = {"▀": "100%", "▄": "0%", "█": "100%"}[ch]
                c = fg or FG
                grad = "linear-gradient(%s 0 50%%,transparent 50%%)" % c if ch == "▀" else "linear-gradient(transparent 50%%,%s 50%%)" % c if ch == "▄" else "linear-gradient(%s,%s)" % (c, c)
                spans.append('<span class="b" style="background:%s%s"></span>' % (grad, (";background-color:" + bg) if bg else ""))
                i += 1
                continue
            while j < len(row) and row[j][1:] == row[i][1:] and row[j][0] not in BLOCKS: j += 1
            text = html.escape("".join(c[0] for c in row[i:j]))
            _, fg, bg, b = row[i]
            st = ""
            if fg: st += "color:%s;" % fg
            if bg: st += "background:%s;" % bg
            if b: st += "font-weight:700;"
            spans.append('<span style="%s">%s</span>' % (st, text) if st else text)
            i = j
        out.append("".join(spans))
    return "\n".join(out)

PAGE = """<!doctype html><meta charset="utf-8"><style>
html,body{margin:0;background:%(page)s}
.stage{padding:%(pad)spx;display:inline-block}
.win{font:15px 'DejaVu Sans Mono','Liberation Mono',monospace;width:calc(%(w)sch + 44px);background:%(bg)s;border-radius:12px;overflow:hidden;box-sizing:content-box;
 box-shadow:0 0 0 1px #2a2733,0 24px 60px rgba(0,0,0,.55),0 0 80px rgba(139,92,246,.10)}
.bar{display:flex;align-items:center;height:42px;background:#17151d;border-bottom:1px solid #26232e;padding:0 14px;gap:18px;font:13px -apple-system,'Segoe UI','DejaVu Sans',sans-serif}
.dots{display:flex;gap:8px}.dots i{width:12px;height:12px;border-radius:50%%;display:block}
.dots i:nth-child(1){background:#ff5f57}.dots i:nth-child(2){background:#febc2e}.dots i:nth-child(3){background:#28c840}
.nav{color:#52525b;letter-spacing:6px;font-size:15px}
.url{flex:1;height:26px;border-radius:7px;background:#0f0e14;border:1px solid #26232e;color:#8e8e99;display:flex;align-items:center;justify-content:flex-start;padding:0 12px;gap:9px}
.url b{font-weight:400;color:#a78bfa}
pre .b{display:inline-block;width:1ch;height:18px;vertical-align:top}
pre{margin:0;padding:18px 22px 22px;font:15px/18px 'DejaVu Sans Mono','Liberation Mono',monospace;color:%(fg)s;white-space:pre;font-variant-ligatures:none}
</style><div class="stage"><div class="win"><div class="bar"><div class="dots"><i></i><i></i><i></i></div><div class="nav">‹ ›</div>
<div class="url"><svg width="11" height="13" viewBox="0 0 11 13" fill="none" stroke="#a78bfa" stroke-width="1.5"><rect x="1" y="5.5" width="9" height="6.5" rx="1.5" fill="#a78bfa" fill-opacity=".25"/><path d="M3 5.5V3.8a2.5 2.5 0 0 1 5 0v1.7"/></svg>localhost:7681</div></div><pre>%(body)s</pre></div></div>"""

def render(ans, cursor=None, cols=78, page="transparent", pad=44):
    rows = cells(ans.rstrip("\n"))
    rows += [[]] * (ROWS - len(rows))
    return PAGE % dict(body=body(rows[:ROWS], cols, cursor), w=cols, bg=BG, fg=FG, page=page, pad=pad)

if __name__ == "__main__":
    ans = open(sys.argv[1]).read()
    cur = None
    if "--cursor" in sys.argv:
        k = sys.argv.index("--cursor"); cur = (int(sys.argv[k+1]), int(sys.argv[k+2]))
    page = "#07060a" if "--solid" in sys.argv else "transparent"
    open(sys.argv[2], "w").write(render(ans, cur, page=page))
