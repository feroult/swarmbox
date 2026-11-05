// Clipboard bridge for the ttyd page (injected by swarmbox-web-terminal; see web-terminal.sh).
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
