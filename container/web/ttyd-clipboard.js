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
  var strip, keysEl, slot, noteEl, noteTimer = 0, byId = {}, count = 0;
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
    var b = el('button', 'sb-btn sb-key');
    b.type = 'button';
    b.textContent = def.label;
    b.title = def.keys;
    if (!/[A-Za-z0-9]/.test(def.label)) b.setAttribute('aria-label', def.keys);
    keepFocus(b);
    var rep = def.seq.length === 1 && REPEAT[def.seq[0]], delay = 0, tick = 0, fired = false, down = false;
    function stop() { clearTimeout(delay); clearInterval(tick); }
    b.addEventListener('pointerdown', function (e) {
      if (e.button > 0) return;
      e.preventDefault();
      down = true; fired = false;
      try { b.setPointerCapture(e.pointerId); } catch (x) { /* not for this pointer */ }
      if (rep) delay = setTimeout(function () { fired = true; typeKeys(def); tick = setInterval(function () { typeKeys(def); }, 70); }, 420);
    });
    // a tap is typed on release, so a drag along a scrolling row (a phone in landscape) types nothing
    b.addEventListener('pointerup', function (e) {
      stop();
      if (down && !fired) typeKeys(def);
      down = false;
      e.preventDefault();
    });
    b.addEventListener('pointercancel', function () { stop(); down = false; });
    b.addEventListener('click', function (e) { if (e.detail === 0) typeKeys(def); }); // Enter or Space on the focused button
    return b;
  }

  function build() {
    strip = el('div');
    strip.id = 'swarmbox-strip';
    strip.setAttribute('role', 'toolbar');
    strip.setAttribute('aria-label', 'Terminal controls');
    strip.hidden = true;
    keysEl = el('div', 'sb-keys');
    keys.forEach(function (d) { keysEl.appendChild(keyButton(d)); });
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
  }

  var refitQueued = false;
  function refit() {
    if (refitQueued) return;
    refitQueued = true;
    requestAnimationFrame(function () { refitQueued = false; window.dispatchEvent(new Event('resize')); });
  }

  function update() {
    if (!strip) return;
    var keysOn = mode === 'on' || custom || coarse.matches;
    keysEl.hidden = !(keysOn && keys.length > 0);
    var show = mode !== 'off' && (!keysEl.hidden || slot.children.length > 0 || mode === 'on');
    var was = !strip.hidden;
    strip.hidden = !show;
    document.documentElement.classList.toggle('swarmbox-strip-on', show);
    if (show !== was) refit();
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

  window.swarmboxStrip = { add: add, remove: remove, note: note, refit: refit, parseKeys: parseKeys, keyBytes: keyBytes,
                           get element() { return strip; }, get visible() { return !!strip && !strip.hidden; } };

  // A page in another origin's frame never gets the strip: one click there would type a key (clickjacking). The server side says the same with
  // frame-ancestors (the voice front); this stays when ttyd runs alone.
  function framed() { try { return window.top !== window.self; } catch (e) { return true; } }

  function start() {
    if (framed()) return;
    if (!document.body) { document.addEventListener('DOMContentLoaded', start); return; }
    build();
    if (coarse.addEventListener) coarse.addEventListener('change', update);
    if (window.visualViewport) {
      window.visualViewport.addEventListener('resize', viewport);
      window.visualViewport.addEventListener('scroll', viewport);
    }
    var tc = document.getElementById('terminal-container');
    if (tc && window.ResizeObserver) new ResizeObserver(refit).observe(tc);
  }
  start();
})();
