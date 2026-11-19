// Scripts of the host page of the web terminal (injected into ttyd's page by build-index.sh at image build). Two independent parts:
//   1. the clipboard bridge (this comment, down to the line "the controls strip"), and
//   2. the controls strip: a slim bar under the terminal with key buttons and a place where addons add controls (window.swarmboxStrip).
//
// Part 1, the clipboard bridge.
//
// ttyd 1.7.7 does not handle OSC 52, so a copy made inside tmux (a mouse selection, or `set-buffer -w`)
// never reaches the browser clipboard, and xterm.js sends Ctrl+V to the shell as ^V instead of pasting.
//
//  - OSC 52 write  -> the browser clipboard. A READ request ("?") is never answered, so nothing running in
//                     the terminal can read what you copied elsewhere.
//  - Ctrl+V        -> paste (the browser's own paste event is let through; xterm.js then pastes, with
//                     bracketed paste when the application asked for it). Turn off with ctrlVPaste=false
//                     if you need ^V (vim block mode, readline quoted-insert).
//  - Right click   -> only tmux's menu while tmux captures the mouse (Shift+right-click: the browser's).
//  - Ctrl+C        -> copy, but only while text is selected in the terminal (Shift+drag selects when tmux
//                     owns the mouse); with no selection it stays ^C. Turn off with ctrlCCopy=false.
(function () {
  var cfg = window.__swarmboxClipboard || {};
  var ctrlVPaste = cfg.ctrlVPaste !== false;
  var ctrlCCopy = cfg.ctrlCCopy !== false;

  function legacyCopy(term, text) {
    var area = document.createElement('textarea');
    area.value = text;
    area.style.position = 'fixed';
    area.style.opacity = '0';
    document.body.appendChild(area);
    area.select();
    try { document.execCommand('copy'); } catch (e) { /* nothing else to try */ }
    document.body.removeChild(area);
    term.focus();
  }

  function write(term, text) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).catch(function () { legacyCopy(term, text); });
    } else {
      legacyCopy(term, text);
    }
  }

  function decodeBase64(b64) {
    var bin = atob(b64);
    var bytes = new Uint8Array(bin.length);
    for (var i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
    return new TextDecoder().decode(bytes);
  }

  function install() {
    var term = window.term;
    if (!term || !term.parser || !term.attachCustomKeyEventHandler) return false;

    // OSC 52 ; <selection> ; <base64>
    term.parser.registerOscHandler(52, function (data) {
      var i = data.indexOf(';');
      var payload = i >= 0 ? data.slice(i + 1) : '';
      if (payload === '' || payload === '?') return true; // clear/read requests are ignored on purpose
      try { write(term, decodeBase64(payload)); } catch (e) { /* malformed payload */ }
      return true;
    });

    // Right click: xterm.js reports it to tmux (which opens its own menu) but the browser's context menu
    // opens on top. While the application captures the mouse (tmux with `mouse on`) the browser menu is
    // suppressed. Shift+right-click still opens it, and with no mouse capture (a plain shell) it works as
    // usual, so copy and paste stay one right click away there.
    if (term.element) {
      term.element.addEventListener('contextmenu', function (ev) {
        var tracking = term.modes && term.modes.mouseTrackingMode;
        if (tracking && tracking !== 'none' && !ev.shiftKey) ev.preventDefault();
      }, true);
    }

    // xterm.js keeps a single custom key handler: chain to one ttyd may have set
    var previous = term._core && term._core._customKeyEventHandler;
    term.attachCustomKeyEventHandler(function (ev) {
      if (ev.type === 'keydown' && ev.ctrlKey && !ev.altKey && !ev.metaKey && !ev.shiftKey) {
        var key = (ev.key || '').toLowerCase();
        if (key === 'v' && ctrlVPaste) return false; // no ^V; the native paste event does the work
        if (key === 'c' && ctrlCCopy && term.hasSelection()) {
          write(term, term.getSelection());
          term.clearSelection();
          ev.preventDefault();
          return false;
        }
      }
      return previous ? previous(ev) : true;
    });
    window.swarmboxClipboardReady = true;   // the bridge polls for the terminal every 100 ms: the tests wait for this before they click or type
    return true;
  }

  (function wait() { if (!install()) setTimeout(wait, 100); })();
})();

// ======================================================================================================================================
// Part 2, the controls strip.
//
// A slim bar BELOW the terminal (never over it: the terminal container ends where the strip begins, xterm is refitted, so tmux sees the
// smaller window and nothing is covered). It carries
//   - KEY BUTTONS that type keys into the terminal (a phone keyboard has no Esc, Tab, Ctrl+C or arrows), from web-terminal.conf (stripKeys);
//   - a place for the controls of addons: window.swarmboxStrip.add({id, title, label, icon, className, order}) returns the <button> (the
//     addon attaches its own handlers to it); window.swarmboxStrip.note(text, tone) shows a short sentence in the strip (tone: '', 'ok',
//     'warn' or 'error'; '' clears it), window.swarmboxStrip.remove(id) takes a control away. The host knows no addon by name.
// It is shown when it has something to show: key buttons on a coarse pointer (touch), or when the user listed buttons or forced it on
// (strip=on); an addon control on any pointer; never with strip=off.
//
// The list of keys is "label=keys" entries separated by commas; keys are tmux key names separated by spaces, sent in order:
//   Escape Tab BTab Enter Space BSpace Up Down Left Right Home End PageUp PageDown IC DC F1..F12 C-x (Ctrl) M-x (Alt) C-M-x, a single
//   character (typed as it is), Comma (the character ,). Example: "Esc=Escape, ^C=C-c, Panel=C-a S". An entry that cannot be read is dropped
//   (a warning in the console of the browser).
(function () {
  var cfg = window.__swarmboxStripCfg || {};
  var mode = cfg.mode === 'on' || cfg.mode === 'off' ? cfg.mode : 'auto';
  var custom = cfg.custom === true;

  // ---- keys -> the bytes xterm.js would send ---------------------------------------------------------------------------------
  var NAMED = { Escape: '\x1b', Esc: '\x1b', Tab: '\t', BTab: '\x1b[Z', Enter: '\r', Space: ' ', BSpace: '\x7f', Comma: ',' };
  var CURSOR = { Up: 'A', Down: 'B', Right: 'C', Left: 'D', Home: 'H', End: 'F' };
  var TILDE = { IC: 2, Insert: 2, DC: 3, Delete: 3, PageUp: 5, PgUp: 5, PageDown: 6, PgDn: 6 };
  var FKEYS = { F1: 'P', F2: 'Q', F3: 'R', F4: 'S', F5: 15, F6: 17, F7: 18, F8: 19, F9: 20, F10: 21, F11: 23, F12: 24 };
  var REPEAT = { Up: 1, Down: 1, Left: 1, Right: 1, PageUp: 1, PageDown: 1, BSpace: 1 };

  // the bytes of ONE key name, or null when it is not one we know
  function keyBytes(tok, appCursor) {
    var m = /^((?:[CM]-)*)(.+)$/.exec(tok);
    if (!m) return null;
    var ctrl = m[1].indexOf('C-') >= 0, meta = m[1].indexOf('M-') >= 0, base = m[2], out;
    if (Object.prototype.hasOwnProperty.call(NAMED, base)) out = NAMED[base];
    else if (Object.prototype.hasOwnProperty.call(CURSOR, base)) out = '\x1b' + (appCursor ? 'O' : '[') + CURSOR[base];
    else if (Object.prototype.hasOwnProperty.call(TILDE, base)) out = '\x1b[' + TILDE[base] + '~';
    else if (Object.prototype.hasOwnProperty.call(FKEYS, base)) out = typeof FKEYS[base] === 'string' ? '\x1bO' + FKEYS[base] : '\x1b[' + FKEYS[base] + '~';
    else if (Array.from(base).length === 1) out = base;
    else return null;
    if (ctrl) {
      if (out.length !== 1) return null;
      var c = out.charCodeAt(0);
      if (out === ' ') out = '\x00';
      else if (c >= 0x40 && c <= 0x5f) out = String.fromCharCode(c & 0x1f);
      else if (c >= 0x61 && c <= 0x7a) out = String.fromCharCode(c & 0x1f);
      else return null;
    }
    return meta ? '\x1b' + out : out;
  }

  function parseKeys(text) {
    var list = [];
    String(text || '').split(',').forEach(function (entry) {
      entry = entry.trim();
      if (!entry) return;
      var i = entry.indexOf('=');
      var label = i > 0 ? entry.slice(0, i).trim() : '', keys = (i > 0 ? entry.slice(i + 1) : entry).trim();
      var seq = keys.split(/\s+/).filter(Boolean);
      var ok = seq.length > 0 && label !== '' && seq.every(function (t) { return keyBytes(t, false) !== null; });
      if (!ok) { try { console.warn('swarmbox strip: cannot read the entry "' + entry + '"; use label=keys, keys as tmux key names'); } catch (e) { /* no console */ } return; }
      list.push({ label: label, keys: keys, seq: seq });
    });
    return list;
  }

  var keys = parseKeys(cfg.keys);
  var oskBtn, strip, keysEl, slot, noteEl, noteTimer = 0, byId = {}, count = 0;
  var coarse = window.matchMedia ? window.matchMedia('(pointer: coarse)') : { matches: false };

  function el(tag, cls) { var e = document.createElement(tag); if (cls) e.className = cls; return e; }

  function typeKeys(def) {
    var t = window.term;
    if (!t || typeof t.input !== 'function') return;
    var app = !!(t.modes && t.modes.applicationCursorKeysMode);
    t.input(def.seq.map(function (k) { return keyBytes(k, app); }).join(''), true);
  }

  // hold-to-talk style controls and the keys both must leave the focus where it is (the terminal, and with it the on-screen keyboard)
  function keepFocus(b) {
    b.addEventListener('mousedown', function (e) { e.preventDefault(); });
    b.addEventListener('contextmenu', function (e) { e.preventDefault(); });
  }

  function keyButton(def) {
    var answer = def.label === 'Allow' ? 'yes' : def.label === 'Cancel' ? 'no' : '';      // the two answers to the sysop: their own look, and they are off when there is nothing to answer
    var toggle = def.label === 'Panel';      // shows or hides the panel of the sysop: a switch, not a key, and it says whether the panel is up
    var b = el('button', 'sb-btn sb-key' + (answer ? ' sb-' + answer : '') + (toggle ? ' sb-toggle' : ''));
    if (toggle) { b.setAttribute('aria-pressed', 'false'); b.setAttribute('data-on', '0'); answers.panel = b; }
    if (answer) { b.setAttribute('data-off', '1'); b.setAttribute('aria-disabled', 'true'); answers[answer] = b; }
    b.type = 'button';
    b.textContent = def.label;
    b.title = def.keys;
    if (!/[A-Za-z0-9]/.test(def.label)) b.setAttribute('aria-label', def.keys);
    keepFocus(b);
    var rep = def.seq.length === 1 && REPEAT[def.seq[0]], delay = 0, tick = 0, fired = false, down = false;
    function stop() { clearTimeout(delay); clearInterval(tick); }
    function press() { if (answer && b.getAttribute('data-off') === '1') return; typeKeys(def); }
    b.addEventListener('pointerdown', function (e) {
      if (e.button > 0) return;
      e.preventDefault();
      down = true; fired = false;
      try { b.setPointerCapture(e.pointerId); } catch (x) { /* not for this pointer */ }
      if (rep) delay = setTimeout(function () { fired = true; press(); tick = setInterval(press, 70); }, 420);
    });
    // a tap is typed on release, so a drag along a scrolling row (a phone in landscape) types nothing
    b.addEventListener('pointerup', function (e) {
      stop();
      if (down && !fired) press();
      down = false;
      e.preventDefault();
    });
    b.addEventListener('pointercancel', function () { stop(); down = false; });
    b.addEventListener('click', function (e) { if (e.detail === 0) press(); }); // Enter or Space on the focused button
    return b;
  }

  // ---- Allow and Cancel are on only when the sysop waits for them -----------------------------------------------------------------
  // The panel of the sysop is part of the terminal, so the page reads its head line off the screen: `SYSOP  allow?` (it needs a yes or a no), `SYSOP  sending`
  // (a countdown: only a no), `SYSOP  working` or `queued` (a no stops it). Anything else, or no panel: both are off and a tap does nothing. Text on a screen can
  // say these words too, and all that costs is a button that is on: Allow and Cancel only type keys that do nothing when the sysop waits for nothing.
  var answers = {}, SYSOP_HEAD = /SYSOP\s+(allow\?|sending|working|queued|idle|done|failed|stopped|off)/, ACTIVE = /^(allow\?|sending|working|queued)$/;
  // the state of the panel as the screen shows it: {up: whether a panel is on the screen, state: what it waits for, '' when it is idle or finished}
  function sysopState() {
    var t = window.term;
    if (!t || !t.buffer || !t.buffer.active) return { up: false, state: '' };
    var buf = t.buffer.active;
    for (var r = 0; r < t.rows; r++) {
      var line = buf.getLine(buf.viewportY + r);
      if (!line) continue;
      var text = line.translateToString(true);
      var at = text.indexOf('SYSOP');
      if (at < 0 || !panelInk(line, at)) continue;
      var m = SYSOP_HEAD.exec(text);
      if (m) return { up: true, state: ACTIVE.test(m[1]) ? m[1] : '' };
    }
    return { up: false, state: '' };
  }
  // The word SYSOP of the panel is bold and coloured (violet); the same word in the history of a tab, which scrolling brings into view, is plain text.
  // Only the first one counts, or the switch lit up and went out as a finger scrolled.
  function panelInk(line, at) {
    try {
      var c = line.getCell(at);
      return !!c && c.isBold() !== 0 && !c.isFgDefault();      // tmux may turn the violet into the nearest of 256 colours, so it is not compared
    } catch (e) { return true; }      // a terminal that cannot say: trust the words
  }
  // tmux writes [position/total] at the top right of a pane that is in copy mode (scrolled back): the screen shows old text then, so the state of the panel is left as it was
  function inCopyMode() {
    var t = window.term;
    if (!t || !t.buffer || !t.buffer.active) return false;
    var buf = t.buffer.active;
    for (var r = 0; r < t.rows; r++) {
      var line = buf.getLine(buf.viewportY + r);
      if (line && /\[\d+\/\d+\]/.test(line.translateToString(true))) return true;
    }
    return false;
  }
  function setOff(b, off) {
    if (!b) return;
    b.setAttribute('data-off', off ? '1' : '0');
    b.setAttribute('aria-disabled', off ? 'true' : 'false');
  }
  function syncAnswers() {
    if (!strip || (!answers.yes && !answers.no && !answers.panel)) return;
    var seen = sysopState(), st = seen.state;
    strip.setAttribute('data-sysop', st || 'none');
    // the switch is left as it was while a tab is scrolled back (its old text may say SYSOP too); Allow and Cancel keep reading, so a real question is never missed
    if (answers.panel && !inCopyMode()) { answers.panel.setAttribute('data-on', seen.up ? '1' : '0'); answers.panel.setAttribute('aria-pressed', seen.up ? 'true' : 'false'); }
    setOff(answers.yes, st !== 'allow?');
    setOff(answers.no, st === '');
  }

  function build() {
    strip = el('div');
    strip.id = 'swarmbox-strip';
    strip.setAttribute('role', 'toolbar');
    strip.setAttribute('aria-label', 'Terminal controls');
    strip.hidden = true;
    keysEl = el('div', 'sb-keys');
    if (!custom) keysEl.setAttribute('data-grid', 'default');      // the default list is a grid: each arrow sits under a key of the row above (ttyd-style.css)
    var pad = null;      // consecutive arrow keys go in one group that never breaks across lines
    keys.forEach(function (d) {
      var arrow = d.seq.length === 1 && CURSOR[d.seq[0]] && d.seq[0] !== 'Home' && d.seq[0] !== 'End';
      if (arrow) { if (!pad) { pad = el('div', 'sb-pad'); keysEl.appendChild(pad); } pad.appendChild(keyButton(d)); }
      else { pad = null; keysEl.appendChild(keyButton(d)); }
    });
    oskBtn = el('button', 'sb-btn sb-osk');      // the one way to the keyboard of the phone: it is not opened by a tap on the screen (see "the keyboard of the phone")
    oskBtn.type = 'button';
    oskBtn.textContent = 'Aa';
    oskBtn.setAttribute('aria-label', 'Keyboard of the phone');
    oskBtn.setAttribute('aria-pressed', 'false');
    oskBtn.setAttribute('data-on', '0');
    oskBtn.title = 'Open or close the keyboard of the phone';
    keepFocus(oskBtn);
    oskBtn.addEventListener('click', openPhoneKeyboard);
    keysEl.appendChild(oskBtn);
    slot = el('div', 'sb-slot');
    noteEl = el('div', 'sb-note');
    noteEl.hidden = true;
    noteEl.setAttribute('role', 'status');
    noteEl.setAttribute('aria-live', 'polite');
    noteEl.addEventListener('click', function () { note(''); });
    strip.appendChild(keysEl);
    strip.appendChild(slot);
    strip.appendChild(noteEl);
    document.body.appendChild(strip);
    update();
    setInterval(syncAnswers, 250);
  }

  var refitQueued = false;
  function refit() {
    if (refitQueued) return;
    refitQueued = true;
    requestAnimationFrame(function () { refitQueued = false; window.dispatchEvent(new Event('resize')); });
  }

  var columnLayout = false;   // the bar is in the page layout (terminal above it); false when hidden or floating
  function update() {
    if (!strip) return;
    var keysOn = mode === 'on' || custom || coarse.matches;
    keysEl.hidden = !(keysOn && keys.length > 0);
    oskBtn.hidden = !coarse.matches;
    keysEl.setAttribute('data-osk', coarse.matches ? '1' : '0');
    var show = mode !== 'off' && (!keysEl.hidden || slot.children.length > 0 || mode === 'on');
    // only controls of addons and no key buttons (a desktop with the microphone): no bar at all, the controls float in the top right corner, over the
    // sysop panel, and the terminal keeps the whole window. With key buttons (a phone, or stripKeys listed, or strip=on) it is the bar below the terminal.
    var floating = show && keysEl.hidden && mode !== 'on' && !coarse.matches;   // never on a touch screen: the thumb is at the bottom
    var was = columnLayout;
    columnLayout = show && !floating;
    strip.hidden = !show;
    document.documentElement.classList.toggle('swarmbox-strip-on', columnLayout);
    document.documentElement.classList.toggle('swarmbox-strip-float', floating);
    if (columnLayout !== was) refit();
    viewport();
  }

  // The on-screen keyboard: Chrome with interactive-widget=resizes-content shrinks the layout itself; iOS only shrinks the visual
  // viewport, so the page follows it (--swarmbox-vvh, --swarmbox-vvtop) and the strip stays above the keyboard.
  function viewport() {
    var vv = window.visualViewport, root = document.documentElement.style;
    if (!vv || strip.hidden || Math.abs(vv.height - window.innerHeight) < 2) {
      root.removeProperty('--swarmbox-vvh');
      root.removeProperty('--swarmbox-vvtop');
    } else {
      root.setProperty('--swarmbox-vvh', Math.round(vv.height) + 'px');
      root.setProperty('--swarmbox-vvtop', Math.round(vv.offsetTop) + 'px');
    }
  }

  function note(text, tone) {
    if (!strip) return;
    clearTimeout(noteTimer);
    text = text === undefined || text === null ? '' : String(text);
    noteEl.textContent = '';
    if (text) { noteEl.appendChild(el('span')).textContent = text; }
    noteEl.title = text;
    noteEl.hidden = !text;
    // a sentence an addon forgot never covers the keys for good: a tone lasts 12 s, a plain state 130 s (a little more than a recording takes to send)
    if (text) noteTimer = setTimeout(function () { note(''); }, tone === 'ok' || tone === 'warn' || tone === 'error' ? 12000 : 130000);
    if (tone === 'ok' || tone === 'warn' || tone === 'error') noteEl.setAttribute('data-tone', tone); else noteEl.removeAttribute('data-tone');
    // the sentence covers the key buttons, not the addon controls: it ends where they begin
    strip.style.setProperty('--sb-slot-w', slot.children.length ? Math.max(0, Math.round(strip.getBoundingClientRect().right - slot.getBoundingClientRect().left)) + 'px' : '0px');
  }

  function add(spec) {
    spec = spec || {};
    if (!strip) return null;
    var id = typeof spec.id === 'string' ? spec.id : 'swarmbox-control-' + (++count);
    if (byId[id]) return byId[id];
    var b = el('button', 'sb-btn sb-addon' + (spec.className ? ' ' + spec.className : ''));
    b.type = 'button';
    b.id = id;
    if (spec.title) { b.title = String(spec.title); b.setAttribute('aria-label', String(spec.title)); }
    if (spec.icon && spec.icon.nodeType === 1) b.appendChild(spec.icon);
    if (spec.label) b.appendChild(document.createTextNode(String(spec.label)));
    b.style.order = typeof spec.order === 'number' ? String(spec.order) : '0';
    keepFocus(b);
    slot.appendChild(b);
    byId[id] = b;
    update();
    return b;
  }

  function remove(id) {
    var b = byId[id];
    if (!b) return;
    if (b.parentNode) b.parentNode.removeChild(b);
    delete byId[id];
    update();
  }

  // ---- the size of the letters on a phone ---------------------------------------------------------------------------------------
  // On a touch screen the size is not a number but a number of COLUMNS: size = usable width / (columns * GLYPH), rounded, never above the size the box
  // configured (fontSize, 21 by default) and never below FONT_MIN. A monospace letter is about 0.6 of its size wide, so a 390 px phone held upright
  // (370 px usable) gets 10 px = about 65 columns, instead of 21 px = 29; turned sideways (844 px) 11 px = about 120 columns. The target can be tried live: swarmboxStrip.setColumns(70)
  // in the console of the browser (kept in this browser, setColumns() forgets it). The sysop panel and the
  // tab are the same terminal, so one size serves both. A mouse screen wider than PHONE_WIDTH (600 px) keeps the configured size, as before.
  var GLYPH = 0.6, COLS_UPRIGHT = 64, COLS_SIDEWAYS = 120, FONT_MIN = 7, FONT_PAD = 10, PHONE_WIDTH = 600;      // a touch screen, or any window as narrow as a phone (the device mode of a desktop browser has a mouse)
  function fontFor(width, height, base, touch) {
    if (!touch) return base;
    var cols = height >= width ? COLS_UPRIGHT : COLS_SIDEWAYS;
    var size = Math.round((width - 2 * FONT_PAD) / (cols * GLYPH));
    return Math.max(FONT_MIN, Math.min(base, size));
  }
  try {      // a choice made in this browser with setColumns, kept in localStorage
    var kept = JSON.parse(localStorage.getItem('swarmbox.columns') || 'null');
    if (kept && kept.up >= 20 && kept.up <= 200) { COLS_UPRIGHT = kept.up; COLS_SIDEWAYS = kept.side; }
  } catch (e) { /* no storage: the defaults */ }
  function setColumns(up, side) {
    try {
      if (up === undefined) localStorage.removeItem('swarmbox.columns');
      else localStorage.setItem('swarmbox.columns', JSON.stringify({ up: up, side: side || Math.round(up * 1.8) }));
    } catch (e) { /* no storage: this page only */ }
    if (up === undefined) { COLS_UPRIGHT = 64; COLS_SIDEWAYS = 120; } else { COLS_UPRIGHT = Number(up); COLS_SIDEWAYS = Number(side) || Math.round(up * 1.8); }
    manual = false;      // the page fits the letters again, from whatever size the terminal has now
    if (window.term && window.term.options) setFont = Number(window.term.options.fontSize);
    fitFont();
    return [COLS_UPRIGHT, COLS_SIDEWAYS];
  }
  // The size is the automatic one until SOMEONE ELSE changes it: ttyd applies its own fontSize a moment after the terminal exists (that is the configured size and is
  // read as the base), but a change later than that, made in the console or by anything else, is a choice and stays: the page stops fitting until setColumns()
  // is called. (It used to fit again at every resize and undo the choice: a value above the computed one went back, and it was not predictable.)
  var baseFont = null, setFont = null, firstAt = null, manual = false, SETTLE_MS = 3000, PREFS_WAIT_MS = 2500, loadedAt = Date.now();
  function fitFont() {
    var t = window.term;
    if (!t || !t.options) return false;
    var now = Date.now();
    // not before ttyd's settings message has come (it is rewritten to the right size on its way in, see rewritePrefs): a size set earlier would be the extra change
    // that this avoids. If it never comes (an old ttyd, no websocket) the page fits by itself after PREFS_WAIT_MS.
    if (!prefsSeen && now - loadedAt < PREFS_WAIT_MS) return false;
    if (firstAt === null) firstAt = now;
    var cur = Number(t.options.fontSize);
    if (setFont !== null && cur !== setFont) {
      if (now - firstAt > SETTLE_MS) manual = true; else baseFont = cur || 21;
    }
    if (manual) return true;
    if (baseFont === null) baseFont = cur || 21;
    var w = document.documentElement.clientWidth || window.innerWidth;
    var want = fontFor(w, document.documentElement.clientHeight || window.innerHeight, baseFont, coarse.matches || w <= PHONE_WIDTH);
    if (cur !== want) {
      fontSets++;
      t.options.fontSize = want;
      // xterm measures the new letter on its next render: a refit asked at once counts the columns with the OLD width and the last ones fall off the right edge,
      // so it is asked again once the new size is in (the later ones change nothing when the first was right)
      refit();
      [120, 400, 1000].forEach(function (ms) { setTimeout(refit, ms); });
      // and the letters are drawn again from scratch once the size has settled: the cache of glyphs of the renderer is made for the size it had, and on some
      // browsers a repaint of the old cache is what showed letters at the wrong width until the next reload
      [1300, 2600].forEach(function (ms) { setTimeout(function () { try { if (t.clearTextureAtlas) t.clearTextureAtlas(); t.refresh(0, t.rows - 1); } catch (e) { /* no renderer yet */ } }, ms); });
    }
    setFont = want;
    return true;
  }

  // ---- this page is the screen you are looking at: tell tmux ---------------------------------------------------------------
  // tmux sizes a window by the client that last had focus (window-size latest). Another client of the same session (the terminal of the host, another tab) that
  // got focus after this page leaves the window at ITS size: on a phone the window is 193 columns wide, the screen shows 123, lines run behind the edge and the
  // prompt is out of sight. A page that is looked at sends the focus-in report (ESC [ I) tmux asked for, which makes the window follow this client again.
  // Only when tmux asked for focus reports (term.modes.sendFocusMode): otherwise those bytes would be typed into the shell.
  var claimedAt = 0;
  function claimSize(force) {
    var t = window.term, now = Date.now();
    if (!t || !t.input || !t.modes || !t.modes.sendFocusMode) return false;
    if (!force && now - claimedAt < 1500) return false;
    if (document.visibilityState === 'hidden') return false;
    claimedAt = now;
    t.input('\x1b[I', true);
    return true;
  }

  // ---- the font size from the first moment -------------------------------------------------------------------------------------
  // ttyd sends its settings (`-t fontSize=21 ...`) over the websocket as the first message, and the terminal applies them as they come. Changing the size
  // AFTER that (what fitFont does when the window turns) lands while the renderer is being made, and on some browsers left it with letters at the wrong width
  // and a tmux that was told 28 columns, then 123. So the message itself is rewritten on its way in: ttyd applies the size that fits THIS screen, once, in its own
  // order, and fitFont only has to follow later changes of the window. (The page is in the head, so this runs before ttyd opens its socket.)
  var fontSets = 0, prefsSeen = 0, prefsRewritten = 0;
  function rewritePrefs(data) {
    var bytes = Object.prototype.toString.call(data) === '[object ArrayBuffer]' ? new Uint8Array(data) : null, text;
    if (bytes) { if (bytes.length < 3 || bytes[0] !== 0x32) return data; text = new TextDecoder().decode(bytes.subarray(1)); }
    else if (typeof data === 'string' && data.charAt(0) === '2') text = data.slice(1);
    else return data;
    var o;
    try { o = JSON.parse(text); } catch (e) { return data; }
    if (!o || typeof o !== 'object' || (o.fontSize === undefined && o.rendererType === undefined) || manual) return data;
    prefsSeen++;
    var base = Number(o.fontSize) || 21;
    var w = document.documentElement.clientWidth || window.innerWidth;
    var touch = coarse.matches || w <= PHONE_WIDTH;
    var want = fontFor(w, document.documentElement.clientHeight || window.innerHeight, base, touch);
    var changed = false;
    if (o.fontSize !== undefined) { baseFont = base; setFont = want; }
    if (o.fontSize !== undefined && want !== base) { o.fontSize = want; changed = true; }
    // On a phone (or any window as narrow as one) the terminal is drawn with the DOM renderer: the canvas ones size their bitmap by the device pixel ratio they saw
    // when they were made, and where that changes (the device mode of a desktop browser, a screen that is moved or zoomed) they paint the letters at 2 or 3 times
    // the width of the grid, so 109 columns did not fit the screen and lines seemed not to wrap (seen in Chrome, measured: bitmap 467 px for 374 css px at a pixel
    // ratio of 2.625). The DOM renderer lays the text out with the browser and has no such state.
    if (touch && o.rendererType !== 'dom') { o.rendererType = 'dom'; changed = true; }
    if (!changed) return data;
    prefsRewritten++;
    // ttyd applies the settings in the order they are written, and refits the terminal after the font changes: with `scrollback` after `fontSize` that fit still
    // reserves the width of a scrollbar (xterm leaves it out only when the scrollback is 0), and the next one gives it back: tmux was told 58 columns and then 61.
    var ordered = {};
    ['scrollback', 'rendererType'].forEach(function (k) { if (o[k] !== undefined) ordered[k] = o[k]; });
    Object.keys(o).forEach(function (k) { if (ordered[k] === undefined) ordered[k] = o[k]; });
    o = ordered;
    var out = JSON.stringify(o);
    if (bytes) { var enc = new TextEncoder().encode(out), nb = new Uint8Array(enc.length + 1); nb[0] = 0x32; nb.set(enc, 1); return nb.buffer; }
    return '2' + out;
  }
  // The title of the terminal (OSC 0 or 2) is read off the output as it arrives, here, before xterm: tmux sends it when a client attaches, which is before the
  // terminal exists for onTitleChange to hear it, and the line of the sysop (below) would stay unknown until it changed.
  // The black page with the name (ttyd-style.css, html::before) goes when the page has SETTLED, not at the first screen: that one is drawn at the size the terminal had
  // before the font, the strip and the size were fitted, and tmux then redraws it. So it waits for the first output, then for the strip to exist and for a quiet
  // moment (QUIET_MS with no output and no resize); and never longer than BOOT_MAX_MS.
  var QUIET_MS = 500, BOOT_MAX_MS = 7000, bootAt = Date.now(), firstOutput = 0, lastActivity = Date.now(), bootTimer = 0;
  function ready() {
    var cl = document.documentElement && document.documentElement.classList;
    if (cl && cl.add) cl.add('swarmbox-ready');
    if (bootTimer) { clearInterval(bootTimer); bootTimer = 0; }
  }
  function bootCheck() {
    var now = Date.now();
    if (now - bootAt >= BOOT_MAX_MS || (firstOutput && strip && now - lastActivity >= QUIET_MS)) ready();
  }
  function markReady(data) {
    var first = typeof data === 'string' ? data.charCodeAt(0) : (data && Object.prototype.toString.call(data) === '[object ArrayBuffer]' ? new Uint8Array(data)[0] : -1);
    if (first !== 0x30) return;
    lastActivity = Date.now();
    if (!firstOutput) firstOutput = lastActivity;
    if (!bootTimer && typeof setInterval === 'function') bootTimer = setInterval(bootCheck, 100);
  }
  if (window.addEventListener) window.addEventListener('resize', function () { lastActivity = Date.now(); });
  function sniffTitle(data) {
    var u8;
    if (typeof data === 'string') { if (data.charCodeAt(0) !== 0x30 || data.indexOf('\x1b]') < 0) return; u8 = null; }
    else if (data && Object.prototype.toString.call(data) === '[object ArrayBuffer]') {
      u8 = new Uint8Array(data);
      if (u8[0] !== 0x30) return;
      var hit = false;
      for (var i = 1; i < u8.length - 1; i++) if (u8[i] === 0x1b && u8[i + 1] === 0x5d) { hit = true; break; }
      if (!hit) return;
    } else return;
    var text = u8 ? new TextDecoder('utf-8').decode(u8.subarray(1)) : data.slice(1);
    var re = /\x1b\][02];([^\x07\x1b]*)(?:\x07|\x1b\\)/g, m, last = null;
    while ((m = re.exec(text))) last = m[1];
    if (last !== null) titleChanged(last);
  }
  var NativeWS = window.WebSocket;
  if (NativeWS && NativeWS.prototype && !(function () { try { return window.top !== window.self; } catch (e) { return true; } })()) {
    var onmsg = Object.getOwnPropertyDescriptor(NativeWS.prototype, 'onmessage');
    var wrapMsg = function (fn) {
      return function (ev) {
        markReady(ev.data);
        sniffTitle(ev.data);
        var data = rewritePrefs(ev.data);
        return fn.call(this, data === ev.data ? ev : { data: data, type: ev.type, target: ev.target, currentTarget: ev.currentTarget, origin: ev.origin });
      };
    };
    window.WebSocket = class extends NativeWS {
      constructor(a, b) { if (b === undefined) super(a); else super(a, b); }
      addEventListener(type, fn, opt) { super.addEventListener(type, type === 'message' && typeof fn === 'function' ? wrapMsg(fn) : fn, opt); }
      set onmessage(fn) { onmsg.set.call(this, typeof fn === 'function' ? wrapMsg(fn) : fn); }
      get onmessage() { return onmsg.get.call(this); }
    };
  }

  // ---- scrolling with a finger ----------------------------------------------------------------------------------------------------
  // tmux owns the history, and it scrolls it when it gets WHEEL events (the mouse wheel of a computer, which xterm.js turns into mouse reports). A finger dragged over
  // the terminal makes no wheel event, and the browser would scroll xterm's own history, which is off (scrollback=0): so on a phone the history could not be reached.
  // A vertical drag is turned here into the wheel events a mouse would make, at the place of the finger, so the pane under it scrolls (a tab in copy mode, the log of
  // the sysop panel). One wheel event is tmux's step of 5 lines, so one is sent per 5 rows of drag: the text follows the finger, one to one. A tap is left alone.
  // Like a finger on any list: the text goes further the faster the finger moves (GAIN_MIN to GAIN_MAX times its distance, by its speed), and it keeps going a while
  // after the finger leaves (inertia), slowing down by itself. The wheel events are handed out a few per frame, so a fast flick is not one burst that tmux and the
  // screen swallow in one go.
  var DRAG_PX = 8, WHEEL_ROWS = 5, GAIN_MIN = 2, GAIN_MAX = 6, GAIN_PER_SPEED = 3, FLICK_SPEED = 0.25, FRICTION = 0.94, PER_FRAME = 6, MAX_BACKLOG = 16, MAX_PAGES = 8, FINE_PER_FRAME = 8;
  function rowHeight() {
    try { return window.term._core._renderService.dimensions.css.cell.height || 14; } catch (e) { return 14; }
  }
  function wheel(x, y, rows) {
    var target = document.querySelector('.xterm-screen') || document.getElementById('terminal-container');
    if (!target || typeof WheelEvent !== 'function') return;
    target.dispatchEvent(new WheelEvent('wheel', { deltaY: rows * rowHeight(), deltaMode: 0, clientX: x, clientY: y, bubbles: true, cancelable: true }));
  }
  function dragScroll() {
    var host = document.getElementById('terminal-container');
    if (!host) return false;
    if (host.getAttribute('data-drag') === '1') return true;
    host.setAttribute('data-drag', '1');
    var id = null, y0 = 0, last = 0, lastT = 0, px = 0, py = 0, moved = false, carry = 0, speed = 0, gain = GAIN_MIN, coasting = 0, wheeled = 0;
    function mine(e) {
      for (var i = 0; i < e.touches.length; i++) if (e.touches[i].identifier === id) return e.touches[i];
      return null;
    }
    function now() { return (window.performance && performance.now) ? performance.now() : Date.now(); }
    function pump() {      // gives out the wheel events owed, a few per frame; carry is in pixels of text
      var rh = rowHeight(), step = WHEEL_ROWS * rh, n = 0;
      var page = Math.max(10, (window.term && window.term.rows || 24) - 2) * rh, cap = Math.max(step * MAX_BACKLOG, page * MAX_PAGES);
      if (Math.abs(carry) > cap) carry = carry > 0 ? cap : -cap;
      var fine = 0, copy = null;
      while (n < PER_FRAME && Math.abs(carry) >= step) {
        if (wheeled > 0 && Math.abs(carry) >= page && window.term && typeof window.term.input === 'function') {
          // a screenful or more: ONE PageUp or PageDown, as the keyboard of a computer does (an app scrolls its page, tmux in copy mode its page), instead of a dozen wheel events
          window.term.input(carry > 0 ? '\x1b[5~' : '\x1b[6~', true);
          carry += carry > 0 ? -page : page;
        } else {
          wheel(px, py, carry > 0 ? -WHEEL_ROWS : WHEEL_ROWS);      // a finger moving down brings older text into view: the wheel turns up
          carry += carry > 0 ? -step : step;
          wheeled++;      // the first wheel is what puts a plain tab into copy mode: the pages follow it, never come first
        }
        n++;
      }
      // Less than a wheel step is left: tmux in copy mode scrolls ONE line on Ctrl+Up and Ctrl+Down, so a slow finger is followed line by line and not in jumps of five
      // (only where the screen says tmux is in copy mode: an app has no such key, and the wheel is all it gets)
      while (fine < FINE_PER_FRAME && Math.abs(carry) >= rh && wheeled > 0 && window.term && typeof window.term.input === 'function') {
        if (copy === null) copy = inCopyMode();
        if (!copy) break;
        window.term.input(carry > 0 ? '\x1b[1;5A' : '\x1b[1;5B', true);
        carry += carry > 0 ? -rh : rh;
        fine++;
      }
    }
    // One loop per frame while the finger is down and after it leaves, until everything owed is given out: the events do not wait for the next touchmove
    // (a finger that stops, or a drag faster than PER_FRAME events a frame, would otherwise leave the text behind it).
    function tick(t0) {
      var t = now(), dt = Math.min(50, t - t0);
      if (id === null) {      // released: inertia, if it was a flick
        carry += speed * dt * gain;
        speed *= Math.pow(FRICTION, dt / 16);
      }
      pump();
      var owed = Math.abs(carry) >= WHEEL_ROWS * rowHeight();
      if (id !== null || owed || Math.abs(speed) >= 0.02) { coasting = requestAnimationFrame(function () { tick(t); }); return; }
      coasting = 0; carry = 0;
    }
    function ensureTick() { if (!coasting && typeof requestAnimationFrame === 'function') coasting = requestAnimationFrame(function () { tick(now()); }); }
    host.addEventListener('touchstart', function (e) {
      if (e.touches.length !== 1) { id = null; return; }
      id = e.touches[0].identifier; y0 = last = e.touches[0].clientY; lastT = now(); moved = false; carry = 0; speed = 0; wheeled = 0;
      px = e.touches[0].clientX; py = y0;
    }, { passive: true });
    host.addEventListener('touchmove', function (e) {
      var t = id === null ? null : mine(e);
      if (!t) return;
      if (!moved && Math.abs(t.clientY - y0) < DRAG_PX) return;
      moved = true;
      var tt = now(), dt = Math.max(1, tt - lastT), dy = t.clientY - last;
      speed = speed === 0 ? dy / dt : 0.6 * speed + 0.4 * (dy / dt);      // px per ms, smoothed
      gain = Math.min(GAIN_MAX, GAIN_MIN + GAIN_PER_SPEED * Math.abs(speed));
      carry += dy * gain;
      last = t.clientY; lastT = tt; px = t.clientX; py = t.clientY;
      ensureTick();
      if (e.cancelable) e.preventDefault();
    }, { passive: false });
    host.addEventListener('touchcancel', function () { id = null; moved = false; speed = 0; carry = 0; }, { passive: true });      // the browser took the gesture (a pinch)
    host.addEventListener('touchend', function (e) {
      if (moved && e.cancelable) e.preventDefault();      // a drag is not a tap: no click follows it
      var flick = moved && Math.abs(speed) >= FLICK_SPEED && now() - lastT < 80;      // still moving when the finger left
      id = null; moved = false;
      if (!flick) speed = 0;
      ensureTick();
    }, { passive: false });
    return true;
  }

  // ---- block art in the DOM renderer ------------------------------------------------------------------------------------------
  // The DOM renderer lays every row of the terminal in a box of its own, and where the height of a row is not a whole number of device pixels (13.34 css px at a ratio
  // of 2.625) a thin line of background shows between two rows of block characters: the banner of the box (the half and whole blocks, U+2580 to U+259F) was cut across
  // every letter. The rows that hold block characters are marked and drawn 12% taller (CSS .sb-blk), which closes the line; the other rows are left as they are.
  // Measured in Chrome at 2.625: two dark rows of pixels in the banner before, none with it.
  var BLOCKS = /[\u2580-\u259f]/;
  function markBlockRows(a, b) {
    var host = document.querySelector('.xterm-rows');
    if (!host) return;
    var rows = host.children;
    for (var r = a; r <= b && r < rows.length; r++) {
      var on = BLOCKS.test(rows[r].textContent);
      if (rows[r].classList.contains('sb-blk') !== on) rows[r].classList.toggle('sb-blk', on);
    }
  }
  function watchBlockRows() {
    var t = window.term;
    if (!t || !t.onRender) return false;
    t.onRender(function (e) { markBlockRows(e.start, e.end); });
    markBlockRows(0, t.rows - 1);
    return true;
  }

  // ---- the keyboard of the phone ---------------------------------------------------------------------------------------------------
  // A tap on the terminal focuses xterm's hidden textarea, and the phone then opens its keyboard every time, over half of the screen. On a touch screen the keyboard is
  // therefore opened only by the "Aa" button among the key buttons. Chrome on a phone has an API for exactly this, the VirtualKeyboard: with virtualkeyboardpolicy="manual"
  // on the textarea a focus never shows the keyboard, and navigator.virtualKeyboard.show() does. Where there is none (Safari, Firefox) the textarea is marked
  // inputmode="none" (it takes the focus, the key buttons and a hardware keyboard type into it, and no keyboard shows), "Aa" makes it a text one for as long as that keyboard
  // is open, and the page puts it back when the keyboard goes away (the window gets its height back, or the textarea loses the focus).
  var oskOpen = false, oskHeight = 0, oskAt = 0, oskTry = 0;
  function vkApi() { try { return navigator.virtualKeyboard && typeof navigator.virtualKeyboard.show === 'function' ? navigator.virtualKeyboard : null; } catch (e) { return null; } }
  function inputBox() { var t = window.term; if (t && t.textarea) return t.textarea; try { return document.querySelector('.xterm-helper-textarea'); } catch (e) { return null; } }
  function setInputMode(mode) { var ta = inputBox(); if (ta && ta.getAttribute('inputmode') !== mode) ta.setAttribute('inputmode', mode); }
  function vkHeight() { try { return Math.round(navigator.virtualKeyboard.boundingRect.height); } catch (e) { return -1; } }      // -1: cannot be told
  // "Aa" is a switch: lit while the keyboard of the phone is open, and it says what is true (the page hears the keyboard come and go).
  function oskShow(on) {
    oskOpen = on;
    if (oskBtn) { oskBtn.setAttribute('data-on', on ? '1' : '0'); oskBtn.setAttribute('aria-pressed', on ? 'true' : 'false'); }
  }
  function openByInputMode(ta) {
    ta.blur();      // a focus that is already there does not bring the keyboard: take it and give it again
    oskAt = Date.now();
    oskHeight = window.innerHeight;
    ta.setAttribute('inputmode', 'text');
    setTimeout(function () { ta.focus(); }, 30);
  }
  function openPhoneKeyboard() {
    var ta = inputBox(), vk = vkApi();
    if (!ta) return;
    if (oskOpen) { closePhoneKeyboard(); return; }      // the second tap closes it
    oskShow(true);
    oskAt = Date.now();
    var my = ++oskTry;
    if (!vk) { openByInputMode(ta); return; }
    // Chrome: focus the terminal's textarea and ask for the keyboard. If it has not come in 0.4 s (a focus that was already there), once more with a fresh focus, and if that fails
    // too the textarea is made a plain text one (inputmode, no manual policy) and focused: the old way, for as long as the keyboard is open.
    ta.focus();
    try { vk.show(); } catch (e) { /* tried again below */ }
    setTimeout(function () {
      if (my !== oskTry || !oskOpen || vkHeight() !== 0) return;
      ta.blur(); ta.focus();
      try { vk.show(); } catch (e) { /* tried again below */ }
      setTimeout(function () {
        if (my !== oskTry || !oskOpen || vkHeight() !== 0) return;
        ta.setAttribute('virtualkeyboardpolicy', 'auto');
        try { ta.virtualKeyboardPolicy = 'auto'; } catch (e) { /* the attribute is enough */ }
        openByInputMode(ta);
        setTimeout(function () { if (my === oskTry && oskOpen && vkHeight() === 0 && window.innerHeight >= oskHeight - 2) oskShow(false); }, 1200);      // nothing worked: the button says so
      }, 450);
    }, 400);
  }
  function closePhoneKeyboard() {
    oskTry++;
    oskShow(false);
    var ta = inputBox(), vk = vkApi();
    if (vk && ta && ta.getAttribute('virtualkeyboardpolicy') === 'manual') { try { vk.hide(); } catch (e) { /* closed already */ } }
    else setInputMode('none');
    if (ta && ta.getAttribute('virtualkeyboardpolicy') !== 'manual') { ta.setAttribute('virtualkeyboardpolicy', 'manual'); try { ta.virtualKeyboardPolicy = 'manual'; } catch (e) { /* attribute */ } }
  }
  function watchInputMode() {
    var ta = inputBox();
    if (!ta) return false;
    if (!coarse.matches) return true;      // a computer: nothing to turn off
    if (ta.getAttribute('data-sbosk') === '1') return true;
    ta.setAttribute('data-sbosk', '1');
    var vk = vkApi();
    if (vk) {
      ta.setAttribute('virtualkeyboardpolicy', 'manual');
      try { ta.virtualKeyboardPolicy = 'manual'; } catch (e) { /* the attribute is enough */ }
      // the switch follows the real keyboard: closed with the back button of the phone, it goes out
      if (vk.addEventListener) vk.addEventListener('geometrychange', function () { var h = vkHeight(); if (h > 0) oskShow(true); else if (h === 0 && Date.now() - oskAt > 600) oskShow(false); });
      return true;
    }
    ta.setAttribute('inputmode', 'none');
    ta.addEventListener('blur', function () { if (oskOpen && Date.now() - oskAt > 300) closePhoneKeyboard(); });
    window.addEventListener('resize', function () {
      if (oskOpen && window.innerHeight >= oskHeight - 2 && Date.now() - oskAt > 1500) closePhoneKeyboard();      // the keyboard went away: the window is as tall as it was
    });
    return true;
  }

  // ---- coming back: no Enter to reconnect ---------------------------------------------------------------------------------------------
  // When the connection is lost for good (a phone that slept, a box that restarted) ttyd writes "Press ⏎ to Reconnect" over the terminal and waits for the Enter
  // key. The page presses it itself: at once, then again every 2 s, 4 s ... up to 10 s while the message stays (the box may still be coming up).
  var RECONNECT_TEXT = 'to Reconnect', reconnectTimer = 0, reconnectWait = 300;
  function reconnectNotice() {      // ttyd's message is a plain div (no class) added to the element of the terminal
    var t = window.term, kids = t && t.element ? t.element.children : [];
    for (var i = 0; i < kids.length; i++) if (!kids[i].className && (kids[i].textContent || '').indexOf(RECONNECT_TEXT) >= 0) return true;
    return false;
  }
  function pressEnter() {
    var t = window.term;
    var ta = t && (t.textarea || document.querySelector('.xterm-helper-textarea'));
    if (!ta) return;
    ta.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', code: 'Enter', keyCode: 13, which: 13, bubbles: true, cancelable: true }));
  }
  function checkReconnect() {
    if (!reconnectNotice()) { reconnectWait = 300; clearTimeout(reconnectTimer); reconnectTimer = 0; return; }
    if (reconnectTimer) return;
    reconnectTimer = setTimeout(function () {
      reconnectTimer = 0;
      if (!reconnectNotice()) { reconnectWait = 300; return; }
      pressEnter();
      reconnectWait = Math.min(10000, reconnectWait < 2000 ? 2000 : reconnectWait * 2);
      setTimeout(checkReconnect, reconnectWait);      // still there after this long: press again
    }, reconnectWait);
  }
  function watchReconnect() {
    var host = document.getElementById('terminal-container');
    if (!host || !window.MutationObserver) return false;
    new MutationObserver(checkReconnect).observe(host, { childList: true, subtree: true, characterData: true });
    document.addEventListener('visibilitychange', function () { if (!document.hidden) { reconnectWait = 300; checkReconnect(); } });
    checkReconnect();
    return true;
  }

  // ---- what the sysop is doing, in one line, beside the microphone ---------------------------------------------------------------------
  // tmux sends the title of the terminal when the option @sysop_line changes (the sysop sets it; tmux.conf has set-titles on): "sysop:<state>:<sentence>", and
  // "sysop:idle:" while a sysop is there with nothing to do. Where a sysop is there (a title of that shape was seen) and on a phone, the strip is COMPACT:
  //     [ ◆ Sysop ▴ ]  what it is doing, in two lines at most  [ ⌨ ] [ mic ]
  // The Sysop button is the one way to open and close the operator panel (Ctrl+A S): a light for the state, an arrow that says which way it goes, filled while the panel
  // is open. The key buttons are ONE slim row (Esc Tab ^C and the arrows) that is above the bar whenever the panel is open, and for as long as the ⌨ button says
  // when it is closed. What needs a yes or a no is not here: the sysop opens its own small approval panel for that. A finished goal (done, failed, stopped) stays
  // 10 s on the line, and the sysop itself says idle after that. Without a sysop, or on a computer, the strip is the one with all the keys.
  var SYSOP_TITLE = /^sysop:(idle|working|sending|allow\?|queued|done|failed|stopped):([\s\S]*)$/, TOAST_HOLD = 10000;
  var toastEl = null, pillEl = null, keyBtn = null, toastState = '', toastText = '', toastTimer = 0, sysopSeen = false, keysShown = false;
  function phone() { return coarse.matches || window.innerWidth <= PHONE_WIDTH; }
  function buildToast() {
    pillEl = el('button', 'sb-btn sb-sysop');
    pillEl.type = 'button';
    pillEl.setAttribute('aria-label', 'Open the sysop panel');
    pillEl.setAttribute('aria-pressed', 'false');
    pillEl.appendChild(el('i', 'sb-dot'));
    pillEl.appendChild(el('b')).textContent = 'Sysop';
    pillEl.appendChild(el('u', 'sb-arrow'));
    keepFocus(pillEl);
    pillEl.addEventListener('click', function () { typeKeys({ seq: ['C-a', 'S'] }); });
    toastEl = el('div', 'sb-toast');
    toastEl.setAttribute('role', 'status');
    toastEl.appendChild(el('span'));
    keyBtn = el('button', 'sb-btn sb-keytoggle');
    keyBtn.type = 'button';
    keyBtn.textContent = '⌨';
    keyBtn.setAttribute('aria-label', 'Show the key buttons');
    keyBtn.setAttribute('aria-pressed', 'false');
    keepFocus(keyBtn);
    keyBtn.addEventListener('click', function () { if (keyBtn.getAttribute('data-locked') === '1') return; keysShown = !keysShown; showToast(); });
    strip.insertBefore(keyBtn, strip.firstChild);
    strip.insertBefore(toastEl, strip.firstChild);
    strip.insertBefore(pillEl, strip.firstChild);
  }
  function showToast() {
    if (!strip) return;
    if (!toastEl) buildToast();
    var up = false;
    try { up = sysopState().up; } catch (e) { /* the screen cannot be read yet */ }
    var compact = sysopSeen && phone();
    var shape = compact ? (keysShown || up ? 'keys' : '1') : '0';
    if (strip.getAttribute('data-compact') !== shape) { strip.setAttribute('data-compact', shape); refit(); }      // the strip changed height: the terminal is fitted again
    pillEl.hidden = keyBtn.hidden = toastEl.hidden = !compact;
    if (!compact) return;
    var idle = !toastState || toastState === 'idle';
    pillEl.setAttribute('data-state', idle ? 'idle' : toastState);
    pillEl.setAttribute('data-on', up ? '1' : '0');
    pillEl.setAttribute('aria-pressed', up ? 'true' : 'false');
    pillEl.setAttribute('aria-label', up ? 'Close the sysop panel' : 'Open the sysop panel');
    keyBtn.setAttribute('aria-pressed', keysShown || up ? 'true' : 'false');
    keyBtn.setAttribute('data-locked', up ? '1' : '0');      // the panel is open: the keys are there and this button has nothing to say
    var text = idle ? (up ? '' : 'idle') : toastText;
    toastEl.setAttribute('data-state', idle ? 'idle' : toastState);
    toastEl.lastChild.textContent = text;
    toastEl.title = text;
  }
  function titleChanged(title) {
    var m = SYSOP_TITLE.exec(String(title || ''));
    clearTimeout(toastTimer);
    toastTimer = 0;
    sysopSeen = !!m;
    toastState = m ? m[1] : '';
    toastText = m ? m[2].replace(/\s+/g, ' ').trim().slice(0, 160) : '';
    if (m && /^(done|failed|stopped)$/.test(m[1])) toastTimer = setTimeout(function () { toastState = 'idle'; showToast(); }, TOAST_HOLD);
    showToast();
  }
  function watchTitle() {
    var t = window.term;
    if (!t || typeof t.onTitleChange !== 'function') return false;
    t.onTitleChange(titleChanged);
    setInterval(showToast, 500);      // the panel coming or going, a phone turning
    return true;
  }

  window.swarmboxStrip = { rewritePrefs: rewritePrefs, markBlockRows: markBlockRows, get fontSets() { return fontSets; }, get prefs() { return [prefsSeen, prefsRewritten]; }, claimSize: claimSize, fontFor: fontFor, setColumns: setColumns, add: add, remove: remove, note: note, titleChanged: titleChanged, checkReconnect: checkReconnect, openPhoneKeyboard: openPhoneKeyboard, refit: refit, parseKeys: parseKeys, keyBytes: keyBytes,
                           get element() { return strip; }, get visible() { return !!strip && !strip.hidden; } };

  // A page in another origin's frame never gets the strip: one click there would type a key (clickjacking). The server side says the same with
  // frame-ancestors (the voice front); this stays when ttyd runs alone.
  function framed() { try { return window.top !== window.self; } catch (e) { return true; } }
  if (framed()) ready();      // a framed page has no strip and no splash

  function start() {
    if (framed()) return;
    if (!document.body) { document.addEventListener('DOMContentLoaded', start); return; }
    build();
    (function waitDrag(n) { if (!dragScroll() && n > 0) setTimeout(function () { waitDrag(n - 1); }, 100); })(100);
    (function waitReconnect(n) { if (!watchReconnect() && n > 0) setTimeout(function () { waitReconnect(n - 1); }, 100); })(100);
    (function waitTitle(n) { if (!watchTitle() && n > 0) setTimeout(function () { waitTitle(n - 1); }, 100); })(100);
    (function waitBlocks(n) { if (!watchBlockRows() && n > 0) setTimeout(function () { waitBlocks(n - 1); }, 100); })(100);
    (function waitTerm(n) { if (!fitFont() && n > 0) setTimeout(function () { waitTerm(n - 1); }, 100); })(100);
    var later;
    function fitSoon() { fitFont(); clearTimeout(later); later = setTimeout(fitFont, 300); }      // again once the window has settled (a turning phone reports its size late)
    var claimLater;
    function claimSoon() { clearTimeout(claimLater); claimLater = setTimeout(function () { claimSize(true); }, 700); }      // after the refits have told tmux the new size
    setInterval(function () { if (document.hasFocus && document.hasFocus()) claimSize(false); }, 2000);      // while this page has the focus it keeps the size: nothing else takes it from it
    window.addEventListener('focus', function () { claimSize(false); });
    document.addEventListener('visibilitychange', function () { claimSize(false); });
    document.addEventListener('pointerdown', function () { claimSize(false); }, true);
    window.addEventListener('resize', claimSoon);
    (function waitModes(n) { if (!claimSize(true) && n > 0) setTimeout(function () { waitModes(n - 1); }, 300); })(40);
    window.addEventListener('resize', fitSoon);
    window.addEventListener('orientationchange', fitSoon);
    if (coarse.addEventListener) coarse.addEventListener('change', function () { fitFont(); update(); });
    if (window.visualViewport) {
      window.visualViewport.addEventListener('resize', viewport);
      window.visualViewport.addEventListener('scroll', viewport);
    }
    (function waitInput(n) { if (!watchInputMode() && n > 0) setTimeout(function () { waitInput(n - 1); }, 100); })(100);
    var tc = document.getElementById('terminal-container');
    if (tc && window.ResizeObserver) new ResizeObserver(refit).observe(tc);
  }
  start();
})();
