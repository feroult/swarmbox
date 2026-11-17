#!/bin/sh
# build-index.sh: assemble the web terminal page at image build.
# Joins ttyd's own page, the clipboard bridge and the style into one file (ttyd serves a single file), leaving eight
# placeholders for the user's settings, which swarmbox-web replaces at every start with a plain text substitution:
#   __SWARMBOX_PADDING__   a number of pixels (the CSS variable --swarmbox-padding)
#   __SWARMBOX_CTRL_V__    true or false (ctrlVPaste)
#   __SWARMBOX_CTRL_C__    true or false (ctrlCCopy)
#   __SWARMBOX_SCROLLBAR__     0 or 6, the width in pixels of the scrollbar (the CSS variable --swarmbox-scrollbar)
#   __SWARMBOX_SCROLLBAR_FF__  none or thin (scrollbar-width in Firefox)
#   __SWARMBOX_STRIP__         auto, on or off (the controls strip under the terminal)
#   __SWARMBOX_STRIP_CUSTOM__  true when the user listed the key buttons, else false
#   __SWARMBOX_STRIP_KEYS__    the list of key buttons, "label=keys, ..." already escaped for a JS string (see ttyd-clipboard.js)
# Usage: build-index.sh [STOCK_HTML [BRIDGE_JS [STYLE_CSS [OUT_HTML]]]]
# Defaults are the image paths. python3 is used here, at build; there is none at run time (the substitution is sed).
set -eu
D=/usr/local/share/swarmbox
STOCK=${1:-$D/ttyd-stock.html}
BRIDGE=${2:-$D/ttyd-clipboard.js}
STYLE=${3:-$D/ttyd-style.css}
OUT=${4:-$D/web/index.html}
mkdir -p "$(dirname "$OUT")"
python3 - "$STOCK" "$BRIDGE" "$STYLE" "$OUT" <<'PY'
import sys
stock, bridge, style, out = sys.argv[1:5]
page = open(stock, encoding="utf-8").read()
js = open(bridge, encoding="utf-8").read().replace("</script", "<\\/script")
css = open(style, encoding="utf-8").read().replace("</style", "<\\/style")
if page.count("</body>") != 1 or page.count("</head>") != 1:
    sys.exit("build-index: the stock page must have exactly one </head> and one </body>")
cfg = '{"ctrlVPaste":__SWARMBOX_CTRL_V__,"ctrlCCopy":__SWARMBOX_CTRL_C__}'
strip = '{"mode":"__SWARMBOX_STRIP__","custom":__SWARMBOX_STRIP_CUSTOM__,"keys":"__SWARMBOX_STRIP_KEYS__"}'
# in the HEAD, before ttyd's own script: the page rewrites the settings message of the websocket (the font size of a phone) before ttyd opens its socket
if page.count("<head>") != 1:
    sys.exit("build-index: the stock page must have exactly one <head>")
page = page.replace("<head>", "<head><script>window.__swarmboxClipboard=%s;window.__swarmboxStripCfg=%s;</script><script>%s</script>" % (cfg, strip, js), 1)
# ttyd's page has no viewport meta: a phone would lay it out 980 px wide and shrink it, and the strip's buttons with it. viewport-fit=cover lets the
# safe-area insets work; interactive-widget=resizes-content makes the on-screen keyboard shrink the layout (the strip stays above it).
if 'name="viewport"' not in page and "name='viewport'" not in page:
    page = page.replace("</head>", '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover, interactive-widget=resizes-content"></head>', 1)
page = page.replace("</head>", "<style>:root{--swarmbox-padding:__SWARMBOX_PADDING__px;--swarmbox-scrollbar:__SWARMBOX_SCROLLBAR__px;--swarmbox-scrollbar-ff:__SWARMBOX_SCROLLBAR_FF__}\n%s</style></head>" % css, 1)
open(out + ".tmp", "w", encoding="utf-8").write(page)
PY
mv "$OUT.tmp" "$OUT"
