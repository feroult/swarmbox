// Real Voice Addon — WhatsApp-style Tap-to-Record -> Live Waveform -> Send / Discard, plus browser SpeechRecognition fallback.

import { state, dom, actions } from './state.js';
import { showTermToast } from './ui-chrome.js';
import { showVoiceNote } from './sysop-chat.js';

const VOICE_RATE = 16000;
let wavRec = null;
let speechRec = null;
let recTimerHandle = null;
let recStartMs = 0;
let voiceInitialized = false;

const byId = (id) => (typeof document !== 'undefined' ? document.getElementById(id) : null);
const qAll = (sel) => (typeof document !== 'undefined' ? Array.from(document.querySelectorAll(sel)) : []);

const mobileVoiceTimerEl = byId('mobile-voice-timer');
const sheetVoiceTimerEl = byId('sheet-voice-timer');
const desktopVoiceTimerEl = byId('desktop-voice-timer');
const mobileVoiceBars = qAll('#mobile-voice-bars > i');
const sheetVoiceBars = qAll('#sheet-voice-bars > i');
const desktopVoiceBars = qAll('#desktop-voice-bars > i');
const btnMobileRecCancel = byId('btn-mobile-rec-cancel');
const btnMobileRecSend = byId('btn-mobile-rec-send');
const btnSheetRecCancel = byId('btn-sheet-rec-cancel');
const btnSheetRecSend = byId('btn-sheet-rec-send');
const btnDesktopRecCancel = byId('btn-desktop-rec-cancel');
const btnDesktopRecSend = byId('btn-desktop-rec-send');

export function formatRecTime(ms) {
  const totalSec = Math.max(0, Math.floor(ms / 1000));
  const m = Math.floor(totalSec / 60);
  const s = totalSec % 60;
  return `${m}:${s < 10 ? '0' : ''}${s}`;
}

export function updateVoiceTimers(text) {
  if (mobileVoiceTimerEl) mobileVoiceTimerEl.textContent = text;
  if (sheetVoiceTimerEl) sheetVoiceTimerEl.textContent = text;
  if (desktopVoiceTimerEl) desktopVoiceTimerEl.textContent = text;
}

export function updateVoiceBars(level) {
  const norm = Math.max(0, Math.min(1, level));
  const now = Date.now() / 135;
  const paint = (bars, maxH) => {
    const mid = (bars.length - 1) / 2;
    bars.forEach((bar, i) => {
      const u = (i - mid) / (mid + 0.6);
      const bell = Math.exp(-u * u * 1.6);
      const wave = 0.5 + 0.35 * Math.sin(now + i * 0.65) + 0.15 * Math.sin(now * 1.7 - i * 0.4);
      const h = Math.round(4 + (maxH - 4) * bell * Math.max(0.22, norm * 0.88 + 0.16) * wave);
      bar.style.height = `${h}px`;
    });
  };
  paint(mobileVoiceBars, 24);
  paint(sheetVoiceBars, 24);
  paint(desktopVoiceBars, 18);
}

export function resetVoiceBars() {
  for (const b of mobileVoiceBars) b.style.height = '5px';
  for (const b of sheetVoiceBars) b.style.height = '5px';
  for (const b of desktopVoiceBars) b.style.height = '5px';
}

export function showVoiceFeedback(msg, tone = '', ms = 3500) {
  showVoiceNote(msg, tone, ms);
  const sysopVisible = window.innerWidth <= 860
    ? dom.appEl.dataset.mobileSysop === '1'
    : dom.appEl.dataset.sysopOpen === '1';
  if (!sysopVisible && msg) {
    showTermToast(msg, tone === 'error' ? 'error' : (tone === 'ok' ? 'ok' : ''), ms || 3500);
  }
}

export function setVoiceState(nextState) {
  dom.appEl.dataset.voiceState = nextState;
  const isRec = nextState === 'recording';
  dom.btnMic.classList.toggle('recording', isRec);
  dom.btnMobileMic.classList.toggle('recording', isRec);
  if (dom.micLabelEl) dom.micLabelEl.textContent = isRec ? 'Listening' : 'Speak';
  if (!isRec) {
    clearInterval(recTimerHandle);
    recTimerHandle = null;
    resetVoiceBars();
  }
  requestAnimationFrame(() => {
    if (typeof actions.fitAndResize === 'function') actions.fitAndResize();
  });
}

export function downsample(chunks, total, from, to) {
  const all = new Float32Array(total);
  let off = 0;
  for (const c of chunks) { all.set(c, off); off += c.length; }
  if (from <= to) return all;
  const ratio = from / to;
  const n = Math.floor(total / ratio);
  const out = new Float32Array(n);
  for (let j = 0; j < n; j++) {
    const a = Math.floor(j * ratio);
    const b = Math.min(total, Math.floor((j + 1) * ratio));
    let s = 0;
    for (let k = a; k < b; k++) s += all[k];
    out[j] = b > a ? s / (b - a) : 0;
  }
  return out;
}

export function encodeWav(samples, rate) {
  const buf = new ArrayBuffer(44 + samples.length * 2);
  const v = new DataView(buf);
  const tag = (o, s) => { for (let i = 0; i < s.length; i++) v.setUint8(o + i, s.charCodeAt(i)); };
  tag(0, 'RIFF'); v.setUint32(4, 36 + samples.length * 2, true); tag(8, 'WAVE');
  tag(12, 'fmt '); v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, 1, true);
  v.setUint32(24, rate, true); v.setUint32(28, rate * 2, true); v.setUint16(32, 2, true); v.setUint16(34, 16, true);
  tag(36, 'data'); v.setUint32(40, samples.length * 2, true);
  for (let i = 0; i < samples.length; i++) {
    const x = Math.max(-1, Math.min(1, samples[i]));
    v.setInt16(44 + i * 2, x < 0 ? x * 0x8000 : x * 0x7fff, true);
  }
  return new Blob([buf], { type: 'audio/wav' });
}

export function releaseWavHandle(rec) {
  if (!rec) return;
  try { rec.src.disconnect(); rec.proc.disconnect(); } catch (_) {}
  rec.proc.onaudioprocess = null;
  try { rec.stream.getTracks().forEach((t) => t.stop()); } catch (_) {}
  try { rec.ctx.close(); } catch (_) {}
}

export async function startWavRecording() {
  if (wavRec || dom.appEl.dataset.voiceState === 'sending') return;
  const md = navigator.mediaDevices;
  const AC = window.AudioContext || window.webkitAudioContext;
  if (!md || !md.getUserMedia || !AC) {
    showVoiceFeedback(window.isSecureContext === false ? 'Microphone needs HTTPS or localhost.' : 'Browser cannot record audio.', 'error', 6000);
    return;
  }
  try {
    const stream = await md.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true } });
    const ctx = new AC();
    if (ctx.state === 'suspended') await ctx.resume();
    const src = ctx.createMediaStreamSource(stream);
    const proc = ctx.createScriptProcessor(4096, 1, 1);
    const rec = { stream, ctx, src, proc, chunks: [], samples: 0, lastPaint: 0 };
    proc.onaudioprocess = (e) => {
      const ch = e.inputBuffer.getChannelData(0);
      rec.chunks.push(new Float32Array(ch));
      rec.samples += ch.length;
      const now = performance.now();
      if (now - rec.lastPaint >= 55) {
        rec.lastPaint = now;
        let sumSq = 0;
        for (let i = 0; i < ch.length; i += 4) sumSq += ch[i] * ch[i];
        const rms = Math.sqrt(sumSq / Math.max(1, ch.length / 4));
        updateVoiceBars(Math.min(1, rms * 5.2));
      }
      if (rec.samples / ctx.sampleRate >= 60) finishWavRecording(true);
    };
    src.connect(proc);
    proc.connect(ctx.destination);
    wavRec = rec;
    recStartMs = Date.now();
    updateVoiceTimers('0:00');
    setVoiceState('recording');
    recTimerHandle = setInterval(() => {
      updateVoiceTimers(formatRecTime(Date.now() - recStartMs));
    }, 250);
  } catch (err) {
    setVoiceState('idle');
    showVoiceFeedback(`Microphone error: ${err.name || err.message}`, 'error', 6000);
  }
}

export async function finishWavRecording(shouldSend = true) {
  const rec = wavRec;
  if (!rec) return;
  wavRec = null;
  const rate = rec.ctx.sampleRate;
  releaseWavHandle(rec);
  if (!shouldSend) {
    setVoiceState('idle');
    showVoiceFeedback('Recording discarded.', '', 1800);
    return;
  }
  if (rec.samples / rate < 0.25) {
    setVoiceState('idle');
    showVoiceFeedback('Too short — tap Speak, talk, then tap Send.', 'warn', 3200);
    return;
  }
  setVoiceState('sending');
  if (typeof actions.showSysopReplyOnMobile === 'function') actions.showSysopReplyOnMobile();
  const wav = encodeWav(downsample(rec.chunks, rec.samples, rate, VOICE_RATE), VOICE_RATE);
  try {
    const r = await fetch('/voice/audio', {
      method: 'POST',
      credentials: 'same-origin',
      cache: 'no-store',
      headers: { 'Content-Type': 'audio/wav' },
      body: wav,
    });
    const d = await r.json().catch(() => ({}));
    setVoiceState('idle');
    if (d.ok === true && d.state === 'sent') showVoiceFeedback('Voice goal sent to Sysop.', 'ok', 2800);
    else if (d.state === 'nothing_heard') showVoiceFeedback('Nothing heard.', 'warn', 3500);
    else if (d.state === 'no_listener') showVoiceFeedback('Nobody is listening (is Sysop running?).', 'warn', 6000);
    else showVoiceFeedback(d.message || d.error || 'Voice service failed.', 'error', 6000);
  } catch (e) {
    setVoiceState('idle');
    showVoiceFeedback(e.message || 'Voice request failed.', 'error', 6000);
  }
}

export function startBrowserSpeech() {
  const SpeechRec = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SpeechRec) {
    showVoiceFeedback('Install the voice addon (`swarmbox addon install voice`) for local Whisper.', 'warn', 5500);
    if (window.innerWidth > 860 && dom.goalInputEl) dom.goalInputEl.focus();
    return;
  }
  if (speechRec) return;
  speechRec = new SpeechRec();
  speechRec.lang = navigator.language || 'en-US';
  speechRec.interimResults = false;
  speechRec._discard = false;
  recStartMs = Date.now();
  updateVoiceTimers('0:00');
  setVoiceState('recording');
  recTimerHandle = setInterval(() => {
    updateVoiceTimers(formatRecTime(Date.now() - recStartMs));
    updateVoiceBars(0.35 + Math.random() * 0.35);
  }, 180);
  speechRec.onresult = (ev) => {
    if (speechRec && speechRec._discard) return;
    const txt = ev.results && ev.results[0] && ev.results[0][0] ? ev.results[0][0].transcript : '';
    if (txt) {
      if (typeof actions.sendGoal === 'function') actions.sendGoal(txt);
      showVoiceFeedback('Voice goal sent to Sysop.', 'ok', 2600);
    }
  };
  speechRec.onend = () => { setVoiceState('idle'); speechRec = null; };
  speechRec.onerror = () => { setVoiceState('idle'); speechRec = null; showVoiceFeedback('Speech recognition unavailable.', 'warn', 4000); };
  speechRec.start();
}

export function finishBrowserSpeech(shouldSend = true) {
  if (!speechRec) return;
  speechRec._discard = !shouldSend;
  try {
    if (shouldSend) speechRec.stop();
    else speechRec.abort();
  } catch (_) {}
  if (!shouldSend) {
    speechRec = null;
    setVoiceState('idle');
    showVoiceFeedback('Recording discarded.', '', 1800);
  }
}

export function startVoiceCapture() {
  if (state.voiceAddonAvailable) startWavRecording();
  else startBrowserSpeech();
}

export function stopVoiceCapture(shouldSend) {
  if (wavRec) finishWavRecording(shouldSend);
  else if (speechRec) finishBrowserSpeech(shouldSend);
  else setVoiceState('idle');
}

export function probeVoiceHealth() {
  // Probe local swarmbox-voice service quietly (no ugly "off" label when absent)
  return fetch('/voice/health', { credentials: 'same-origin', cache: 'no-store' })
    .then((r) => {
      if (r.ok) {
        state.voiceAddonAvailable = true;
        if (dom.voiceHintEl) dom.voiceHintEl.textContent = 'tap · whisper';
      } else if (dom.voiceHintEl) {
        dom.voiceHintEl.textContent = '';
      }
    })
    .catch(() => { if (dom.voiceHintEl) dom.voiceHintEl.textContent = ''; });
}

export function initVoice() {
  if (voiceInitialized || typeof document === 'undefined') return;
  voiceInitialized = true;
  if (dom.btnMic) dom.btnMic.addEventListener('click', () => startVoiceCapture());
  if (dom.btnMobileMic) dom.btnMobileMic.addEventListener('click', () => startVoiceCapture());
  if (dom.btnSheetMic) dom.btnSheetMic.addEventListener('click', () => startVoiceCapture());
  if (btnMobileRecCancel) btnMobileRecCancel.addEventListener('click', () => stopVoiceCapture(false));
  if (btnMobileRecSend) btnMobileRecSend.addEventListener('click', () => stopVoiceCapture(true));
  if (btnSheetRecCancel) btnSheetRecCancel.addEventListener('click', () => stopVoiceCapture(false));
  if (btnSheetRecSend) btnSheetRecSend.addEventListener('click', () => stopVoiceCapture(true));
  if (btnDesktopRecCancel) btnDesktopRecCancel.addEventListener('click', () => stopVoiceCapture(false));
  if (btnDesktopRecSend) btnDesktopRecSend.addEventListener('click', () => stopVoiceCapture(true));
  probeVoiceHealth();
}
