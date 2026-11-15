// Voice control for the ttyd page (the `voice` tool). Injected into the page by swarmbox-web with page.css.
//
// The browser only captures the microphone. Push-to-talk: hold the button (mouse, touch, or Space/Enter on the focused button), release
// to send. It records PCM with getUserMedia + the Web Audio API and sends 16 kHz mono 16-bit WAV, which is what the recognizer reads
// (the box has no audio decoder, so MediaRecorder's webm/opus would not be understood).
//
//  - POST <base>audio (audio/wav) -> {ok, state: 'pending' | 'nothing_heard'}. That is all that comes back: the transcript, the plan, its
//    risk and the confirmation are shown and decided in the tmux panel, the same for every client. This page shows none of it.
//  - A small state light: idle, recording, sending, sent, error, nothing heard. Errors say a short sentence.
//  - Text from the service is shown with textContent. This file never uses innerHTML.
//  - The page stays unchanged when the service is absent: the button only appears if GET <base>health answers 200.
(function () {
  var cfg = window.__swarmboxVoice || {};
  var BASE = typeof cfg.base === 'string' ? cfg.base : '/voice/';
  var RATE = 16000;
  var MIN_SECONDS = 0.3;
  var MAX_SECONDS = 60;
  var SVGNS = 'http://www.w3.org/2000/svg';
  var LABEL = { recording: 'Listening', sending: 'Sending', sent: 'Sent', nothing: 'Nothing heard' };

  var root, mic, noteEl, levelBar;
  var state = 'idle'; // idle | starting | recording | sending | sent | error | nothing | unsupported
  var pressed = false;
  var rec = null;
  var timer = null;

  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined && text !== null) e.textContent = String(text);
    return e;
  }

  function str(v, max) {
    var s = typeof v === 'string' ? v : (v === undefined || v === null ? '' : String(v));
    return s.length > (max || 200) ? s.slice(0, max || 200) + '...' : s;
  }

  // ---- the state light ----------------------------------------------------------------------
  function show(s, text, ms) {
    clearTimeout(timer);
    state = s;
    root.setAttribute('data-state', s);
    mic.setAttribute('aria-pressed', s === 'recording' ? 'true' : 'false');
    var msg = text || LABEL[s] || '';
    noteEl.textContent = msg;
    noteEl.hidden = !msg;
    if (ms) timer = setTimeout(function () { if (state === s) show('idle'); }, ms);
  }

  function busy() { return state === 'starting' || state === 'recording' || state === 'sending'; }

  function refocusTerminal() {
    try { if (window.term && window.term.focus) window.term.focus(); } catch (e) { /* no terminal to focus */ }
  }

  // ---- service call -------------------------------------------------------------------------
  function send(wav) {
    var ctl = typeof AbortController === 'function' ? new AbortController() : null;
    var abort = setTimeout(function () { if (ctl) ctl.abort(); }, 120000);
    var opts = { method: 'POST', credentials: 'same-origin', cache: 'no-store', headers: { 'Content-Type': 'audio/wav' }, body: wav };
    if (ctl) opts.signal = ctl.signal;
    return fetch(BASE + 'audio', opts).then(function (r) {
      return r.text().then(function (t) {
        var data = null;
        try { data = t ? JSON.parse(t) : {}; } catch (e) { data = null; }
        if (!r.ok) throw new Error(data && (data.message || data.error) ? str(data.message || data.error) : 'The voice service answered ' + r.status + '.');
        if (!data || typeof data !== 'object') throw new Error('The voice service did not answer properly.');
        return data;
      });
    }).then(function (d) { clearTimeout(abort); return d; }, function (e) {
      clearTimeout(abort);
      if (e && e.name === 'AbortError') throw new Error('The voice service took too long.');
      throw e;
    });
  }

  // ---- recording ----------------------------------------------------------------------------
  function micSupported() {
    var md = navigator.mediaDevices;
    return !!(md && md.getUserMedia && (window.AudioContext || window.webkitAudioContext));
  }

  function unsupportedMessage() {
    if (window.isSecureContext === false) return 'The microphone needs https or localhost.';
    return 'This browser cannot record audio.';
  }

  function start() {
    if (busy()) return;
    if (!micSupported()) { show('error', unsupportedMessage(), 8000); return; }
    pressed = true;
    show('starting', 'Starting...');
    navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true } }).then(function (stream) {
      if (!pressed) { // released before the microphone was ready
        stopTracks(stream);
        show('idle');
        return;
      }
      begin(stream);
    }, function (err) {
      pressed = false;
      var n = err && err.name;
      if (n === 'NotAllowedError' || n === 'SecurityError') show('error', 'Microphone blocked. Allow it in the site settings.', 10000);
      else if (n === 'NotFoundError' || n === 'OverconstrainedError') show('error', 'No microphone found.', 8000);
      else if (n === 'NotReadableError') show('error', 'The microphone is busy.', 8000);
      else show('error', 'Could not start the microphone.', 8000);
    });
  }

  function stopTracks(stream) {
    try { stream.getTracks().forEach(function (t) { t.stop(); }); } catch (e) { /* already stopped */ }
  }

  function begin(stream) {
    var AC = window.AudioContext || window.webkitAudioContext;
    var ctx = new AC();
    var r = { stream: stream, ctx: ctx, chunks: [], samples: 0 };
    try {
      if (ctx.state === 'suspended') ctx.resume();
      r.src = ctx.createMediaStreamSource(stream);
      r.proc = ctx.createScriptProcessor(4096, 1, 1);
      r.proc.onaudioprocess = function (e) {
        var data = e.inputBuffer.getChannelData(0);
        r.chunks.push(new Float32Array(data));
        r.samples += data.length;
        var sum = 0;
        for (var i = 0; i < data.length; i += 8) sum += data[i] * data[i];
        levelBar.style.width = Math.min(100, Math.round(Math.sqrt(sum / (data.length / 8)) * 400)) + '%';
        if (r.samples / ctx.sampleRate >= MAX_SECONDS) finish();
      };
      r.src.connect(r.proc);
      r.proc.connect(ctx.destination); // the processor only runs while it is connected; it writes no output
    } catch (e) {
      stopTracks(stream);
      try { ctx.close(); } catch (x) { /* ignore */ }
      show('error', 'Could not record audio here.', 8000);
      return;
    }
    rec = r;
    show('recording');
  }

  function finish() {
    pressed = false;
    var r = rec;
    if (!r || state !== 'recording') return;
    rec = null;
    try { r.src.disconnect(); r.proc.disconnect(); } catch (e) { /* already disconnected */ }
    r.proc.onaudioprocess = null;
    stopTracks(r.stream);
    var rate = r.ctx.sampleRate;
    try { r.ctx.close(); } catch (e) { /* ignore */ }
    levelBar.style.width = '0';
    if (r.samples / rate < MIN_SECONDS) {
      show('error', 'Too short. Hold the button while you speak.', 3000);
      return;
    }
    var wav = encodeWav(downsample(r.chunks, r.samples, rate, RATE), RATE);
    show('sending');
    send(wav).then(function (d) {
      if (d.state === 'pending') show('sent', '', 2500);
      else if (d.state === 'nothing_heard') show('nothing', '', 4000);
      else show('error', 'The voice service did not understand.', 6000);
      refocusTerminal();
    }, function (e) {
      show('error', e.message || 'The voice service failed.', 8000);
    });
  }

  function downsample(chunks, total, from, to) {
    var all = new Float32Array(total);
    var off = 0;
    for (var i = 0; i < chunks.length; i++) { all.set(chunks[i], off); off += chunks[i].length; }
    if (from <= to) return all;
    var ratio = from / to;
    var n = Math.floor(total / ratio);
    var out = new Float32Array(n);
    for (var j = 0; j < n; j++) {
      var a = Math.floor(j * ratio), b = Math.min(total, Math.floor((j + 1) * ratio)), s = 0;
      for (var k = a; k < b; k++) s += all[k];
      out[j] = b > a ? s / (b - a) : 0;
    }
    return out;
  }

  function encodeWav(samples, rate) {
    var buf = new ArrayBuffer(44 + samples.length * 2);
    var v = new DataView(buf);
    function tag(o, s) { for (var i = 0; i < s.length; i++) v.setUint8(o + i, s.charCodeAt(i)); }
    tag(0, 'RIFF'); v.setUint32(4, 36 + samples.length * 2, true); tag(8, 'WAVE');
    tag(12, 'fmt '); v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, 1, true);
    v.setUint32(24, rate, true); v.setUint32(28, rate * 2, true); v.setUint16(32, 2, true); v.setUint16(34, 16, true);
    tag(36, 'data'); v.setUint32(40, samples.length * 2, true);
    for (var i = 0; i < samples.length; i++) {
      var x = Math.max(-1, Math.min(1, samples[i]));
      v.setInt16(44 + i * 2, x < 0 ? x * 0x8000 : x * 0x7fff, true);
    }
    return new Blob([buf], { type: 'audio/wav' });
  }

  // ---- the page -----------------------------------------------------------------------------
  function micIcon() {
    var svg = document.createElementNS(SVGNS, 'svg');
    svg.setAttribute('viewBox', '0 0 24 24');
    svg.setAttribute('aria-hidden', 'true');
    var p = document.createElementNS(SVGNS, 'path');
    p.setAttribute('d', 'M12 14a3 3 0 0 0 3-3V5a3 3 0 0 0-6 0v6a3 3 0 0 0 3 3zm5-3a5 5 0 0 1-10 0H5a7 7 0 0 0 6 6.92V21h2v-3.08A7 7 0 0 0 19 11h-2z');
    svg.appendChild(p);
    return svg;
  }

  function build() {
    root = el('div');
    root.id = 'swarmbox-voice';
    mic = el('button', 'sv-mic');
    mic.type = 'button';
    mic.id = 'swarmbox-voice-mic';
    mic.setAttribute('aria-label', 'Hold to talk');
    mic.title = 'Hold to talk';
    mic.appendChild(micIcon());
    mic.appendChild(el('i', 'sv-light'));
    noteEl = el('div', 'sv-note');
    noteEl.setAttribute('role', 'status');
    noteEl.setAttribute('aria-live', 'polite');
    noteEl.hidden = true;
    levelBar = el('i');
    var lv = el('span', 'sv-level');
    lv.appendChild(levelBar);
    mic.appendChild(lv);
    root.appendChild(noteEl);
    root.appendChild(mic);
    document.body.appendChild(root);
    show('idle');
    if (!micSupported()) root.setAttribute('data-support', 'no');

    // keep the terminal's focus: pressing the button must not blur it
    mic.addEventListener('pointerdown', function (e) {
      if (e.button !== undefined && e.button !== 0) return;
      e.preventDefault();
      try { mic.setPointerCapture(e.pointerId); } catch (x) { /* not supported for this pointer */ }
      start();
    });
    function release(e) { e.preventDefault(); pressed = false; if (state === 'recording') finish(); }
    mic.addEventListener('pointerup', release);
    mic.addEventListener('pointercancel', release);
    mic.addEventListener('lostpointercapture', function () { pressed = false; if (state === 'recording') finish(); });
    mic.addEventListener('contextmenu', function (e) { e.preventDefault(); });
    mic.addEventListener('keydown', function (e) {
      if ((e.key === ' ' || e.key === 'Enter') && !e.repeat) { e.preventDefault(); start(); }
    });
    mic.addEventListener('keyup', function (e) {
      if (e.key === ' ' || e.key === 'Enter') { e.preventDefault(); pressed = false; if (state === 'recording') finish(); }
    });
    mic.addEventListener('blur', function () { pressed = false; if (state === 'recording') finish(); });
  }

  function init() {
    fetch(BASE + 'health', { credentials: 'same-origin', cache: 'no-store' }).then(function (r) {
      if (r.ok && document.body) build();
    }, function () { /* no service: the page stays as it is */ });
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
