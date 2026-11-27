// Responsive mobile touch drag, iOS-like momentum coasting, and optical-zoom / pinch guards.

import { state, dom, actions, activeSession } from './state.js';

// Responsive mobile touch drag + iOS-like momentum scroll.
// Uses a sub-row pixel accumulator feeding relative term.scrollLines() (zero translate3d/onRender
// phase-mismatch jitter, zero bottom blank-gap flicker, and immune to ring-buffer baseY churn).
export const TOUCH_DRAG_PX = 4;
export const TOUCH_DRAG_GAIN = 1.8;
export const TOUCH_COAST_GAIN = 1.8;
export const TOUCH_FLICK_MIN = 0.08;   // px/ms
export const TOUCH_FRICTION = 0.968;   // per 16.67ms frame (silky iOS glide)
export const TOUCH_STOP_VEL = 0.02;    // px/ms
export const TOUCH_VEL_WINDOW = 70;    // ms of active drag samples used for flick speed
export const TOUCH_MAX_VEL = 18;       // px/ms cap for chained fast flicks

let touchId = null;
let touchStartY = 0;
let touchLastY = 0;
let touchLastX = 0;
let touchLastT = 0;
let touchMoved = false;
let touchStoppedCoast = false;
let touchVel = 0;
let touchCoastDir = 0;
let touchChainBoost = 1;
let touchChainT = 0;
let touchRaf = 0;
let touchAltAccum = 0;
let touchSamples = [];
let touchSettleRaf = 0;
let touchScrollBound = false;

function nowMs() {
  return (typeof window !== 'undefined' && window.performance) ? performance.now() : Date.now();
}

function sessionRowHeight(sess) {
  try {
    const h = sess.term._core?._renderService?.dimensions?.css?.cell?.height;
    if (h && h > 4) return h;
  } catch (_) {}
  return Math.max(10, (sess.term.options.fontSize || 12) * (sess.term.options.lineHeight || 1.15));
}

export function clearTouchOffset(sess) {
  if (!sess) return;
  sess.touchRowAccum = 0;
}

export function touchOffsetOnScroll() {}
export function touchOffsetOnRender() {}

// Lightweight mobile touch & optical-zoom diagnostic telemetry (fires only once per gesture / zoom settle).
let touchDbgGesture = null;
let touchDbgCoast = null;
let touchDbgSeq = 0;
let zoomCooldownUntil = 0;
let multiTouchActive = false;

export function isOpticalZoomed() {
  return Boolean(typeof window !== 'undefined' && window.visualViewport && Number(window.visualViewport.scale || 1) > 1.02);
}

export function isViewportPinchingOrBouncing() {
  if (typeof window === 'undefined' || !window.visualViewport) return false;
  const vv = window.visualViewport;
  const scale = Number(vv.scale || 1);
  if (scale > 1.02 || scale < 0.99) return true;
  const layoutW = document.documentElement.clientWidth || 0;
  if ((vv.offsetTop || 0) < -1 || (vv.offsetLeft || 0) < -1) return true;
  if (layoutW > 0 && vv.width > layoutW + 2) return true;
  return false;
}

export function isTouchActive() {
  return touchId !== null || Boolean(touchRaf);
}

export function isTouchPinchOrCooldown() {
  return isViewportPinchingOrBouncing() || multiTouchActive || Date.now() < zoomCooldownUntil;
}

export function setZoomCooldown(ms = 650) {
  zoomCooldownUntil = Date.now() + ms;
}

export function isZoomCooldownElapsed() {
  return Date.now() >= zoomCooldownUntil;
}

export function sessionMouseMode(sess) {
  try {
    const m = sess && sess.term && sess.term._core && sess.term._core.coreMouseService && sess.term._core.coreMouseService.activeProtocol;
    return m ? String(m) : 'NONE';
  } catch (_) {
    return 'UNKNOWN';
  }
}

const TOUCH_DEBUG_ENABLED = (() => {
  try {
    if (typeof window === 'undefined') return false;
    return new URLSearchParams(window.location.search).get('debug_touch') === '1'
      || localStorage.getItem('swarmbox-debug-touch') === '1';
  } catch (_) {
    return false;
  }
})();

export function logTouchDebug(kind, data) {
  if (!TOUCH_DEBUG_ENABLED) return;
  if (window.innerWidth > 960 && !(navigator.maxTouchPoints > 0)) return;
  touchDbgSeq += 1;
  const dockEl = document.querySelector('.mobile-dock');
  const vv = window.visualViewport;
  const payload = {
    seq: touchDbgSeq,
    kind,
    tab: state.activeId || '',
    vvScale: vv ? Number((vv.scale || 1).toFixed(3)) : 1,
    vvH: vv ? Math.round(vv.height) : window.innerHeight,
    vvW: vv ? Math.round(vv.width) : window.innerWidth,
    winH: window.innerHeight,
    layoutH: document.documentElement.clientHeight || 0,
    dockH: dockEl ? Math.round(dockEl.getBoundingClientRect().height) : 0,
    ...data,
  };
  try {
    fetch('/api/debug/touch', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
      keepalive: true,
    }).catch(() => {});
  } catch (_) {}
}

function applyTouchScrollPx(deltaPx) {
  const sess = activeSession();
  if (!sess || !deltaPx) return false;
  const buf = sess.term.buffer && sess.term.buffer.active;
  const mouseMode = sessionMouseMode(sess);
  const appWantsWheel = mouseMode !== 'NONE' && mouseMode !== 'UNKNOWN';

  if (buf && buf.type === 'normal' && buf.baseY > 0 && !appWantsWheel) {
    const rh = sessionRowHeight(sess);
    const prevVpY = buf.viewportY;
    // Boundary check before accumulating so coast terminates cleanly at top/bottom
    if ((deltaPx < 0 && prevVpY <= 0) || (deltaPx > 0 && prevVpY >= buf.baseY)) {
      sess.touchRowAccum = 0;
      return false;
    }
    sess.touchRowAccum = (sess.touchRowAccum || 0) + (deltaPx / rh);
    const lines = Math.trunc(sess.touchRowAccum);
    if (lines !== 0) {
      sess.touchRowAccum -= lines;
      sess.term.scrollLines(lines);
      if (typeof actions.syncJumpLive === 'function') actions.syncJumpLive();
    }
    return true;
  }

  // Alternate screen or mouse-tracked TUI (an agent in fullscreen, vim, less, htop):
  // dispatch line-mode WheelEvents with coords clamped inside .xterm-screen so xterm's
  // CoreMouseService always resolves valid (col, row) coordinates and delivers every tick.
  const rh = sessionRowHeight(sess);
  touchAltAccum += deltaPx / Math.max(8, rh * 0.55);
  const lines = Math.trunc(touchAltAccum);
  if (lines !== 0) {
    touchAltAccum -= lines;
    const screenEl = sess.paneEl.querySelector('.xterm-screen');
    const dir = Math.sign(lines);
    const count = Math.min(12, Math.abs(lines));
    if (touchDbgGesture) touchDbgGesture.wheelSent += count;
    if (touchDbgCoast) touchDbgCoast.wheelSent += count;
    if (screenEl && typeof WheelEvent === 'function') {
      const rect = screenEl.getBoundingClientRect();
      const cx = rect.width > 16
        ? Math.max(rect.left + 8, Math.min(rect.right - 8, touchLastX || (rect.left + rect.width * 0.5)))
        : (rect.left + rect.width * 0.5);
      const cy = rect.height > 16
        ? Math.max(rect.top + 8, Math.min(rect.bottom - 8, touchLastY || (rect.top + rect.height * 0.45)))
        : (rect.top + rect.height * 0.5);
      for (let i = 0; i < count; i++) {
        screenEl.dispatchEvent(new WheelEvent('wheel', {
          deltaY: dir * 3,
          deltaMode: 1,
          clientX: cx,
          clientY: cy,
          bubbles: true,
          cancelable: true,
        }));
      }
    } else {
      sess.term.scrollLines(lines);
    }
  }
  return true;
}

function settleTouchScroll() {
  const sess = activeSession();
  if (sess) {
    sess.touchRowAccum = 0;
    if (sess.pokeScrollbar) sess.pokeScrollbar();
  }
}

function flushCoastDebug(reason) {
  if (!touchDbgCoast) return;
  const sess = activeSession();
  const buf = sess && sess.term && sess.term.buffer && sess.term.buffer.active;
  const c = touchDbgCoast;
  touchDbgCoast = null;
  logTouchDebug('coast_end', {
    reason,
    frames: c.frames,
    totalPx: Math.round(c.totalPx),
    wheelSent: c.wheelSent,
    startVpY: c.startVpY,
    endVpY: buf ? buf.viewportY : -1,
    baseY: buf ? buf.baseY : -1,
    bufType: buf ? buf.type : 'none',
  });
}

export function stopTouchCoast(caller = 'unknown') {
  if (touchRaf) {
    cancelAnimationFrame(touchRaf);
    touchRaf = 0;
    flushCoastDebug(`interrupted:${caller}`);
  }
  if (touchSettleRaf) {
    cancelAnimationFrame(touchSettleRaf);
    touchSettleRaf = 0;
  }
  touchVel = 0;
  touchAltAccum = 0;
}

export function startTouchCoast() {
  if (touchRaf) return;
  const sess0 = activeSession();
  const buf0 = sess0 && sess0.term && sess0.term.buffer && sess0.term.buffer.active;
  touchDbgCoast = {
    frames: 0,
    totalPx: 0,
    wheelSent: 0,
    startVpY: buf0 ? buf0.viewportY : -1,
  };
  let prevT = nowMs();
  const step = () => {
    touchRaf = 0;
    if (touchId !== null) {
      flushCoastDebug('new_touch');
      return;
    }
    const t = nowMs();
    const dt = Math.min(48, Math.max(4, t - prevT));
    prevT = t;
    const deltaPx = touchVel * dt * TOUCH_COAST_GAIN;
    const progressed = applyTouchScrollPx(deltaPx);
    if (touchDbgCoast) {
      touchDbgCoast.frames += 1;
      touchDbgCoast.totalPx += deltaPx;
    }
    touchVel *= Math.pow(TOUCH_FRICTION, dt / 16.67);
    if (progressed && Math.abs(touchVel) >= TOUCH_STOP_VEL) {
      touchRaf = requestAnimationFrame(step);
    } else {
      const dir = Math.sign(touchVel);
      touchVel = 0;
      touchAltAccum = 0;
      flushCoastDebug(progressed ? 'stopped' : 'boundary');
      settleTouchScroll(dir);
    }
  };
  touchRaf = requestAnimationFrame(step);
}

function findTouchById(list, id) {
  for (let i = 0; i < list.length; i++) {
    if (list[i].identifier === id) return list[i];
  }
  return null;
}

// Speed (px/ms, positive = towards the bottom) over the last TOUCH_VEL_WINDOW ms of active drag,
// resisting stationary touchstart dwell and final thumb-lift micro-slowdown.
function touchFlickVelocity() {
  if (touchSamples.length < 2) return 0;
  const last = touchSamples[touchSamples.length - 1];
  let first = last;
  for (let i = touchSamples.length - 2; i >= 0; i--) {
    if (last.t - touchSamples[i].t > TOUCH_VEL_WINDOW) break;
    first = touchSamples[i];
  }
  const dt = last.t - first.t;
  const winVel = dt > 0 ? (first.y - last.y) / dt : 0;
  // Also inspect the sharpest recent segment in the same direction (in case thumb slowed on lift)
  let peakVel = winVel;
  const dir = Math.sign(winVel);
  for (let i = touchSamples.length - 1; i >= Math.max(1, touchSamples.length - 3); i--) {
    const a = touchSamples[i - 1];
    const b = touchSamples[i];
    const sdt = b.t - a.t;
    if (sdt >= 4 && sdt <= 65) {
      const sv = (a.y - b.y) / sdt;
      if ((dir === 0 || Math.sign(sv) === dir) && Math.abs(sv) > Math.abs(peakVel)) {
        peakVel = sv;
      }
    }
  }
  return Math.abs(peakVel) > Math.abs(winVel) ? (winVel * 0.45 + peakVel * 0.55) : winVel;
}

// Capture-phase touch interception on dom.termWrapEl:
// xterm.js registers its own bubble-phase touchstart/touchmove handlers on `.xterm` that call
// stopPropagation() (swallowing 1-finger momentum scrolls in the middle of scrollback) and
// preventDefault() without checking touches.length === 1 (killing iOS 2-finger pinch-zoom!).
// Intercepting in CAPTURE phase and calling stopPropagation() completely bypasses xterm's
// primitive touch handler so:
//   - 2-finger pinch-zoom & zoomed 1-finger pans go 100% natively to the browser compositor
//   - 1-finger scrolls run our sub-row GPU + iOS momentum engine everywhere in the buffer
//   - single taps still open the keyboard (except tapping to stop an active coast!)
export function attachTouchScroll() {
  if (touchScrollBound || typeof window === 'undefined' || !dom.termWrapEl) return;
  touchScrollBound = true;

  window.addEventListener('touchend', (e) => {
    if (e.touches.length === 0) multiTouchActive = false;
  }, { passive: true });
  window.addEventListener('touchcancel', () => {
    multiTouchActive = false;
  }, { passive: true });

  dom.termWrapEl.addEventListener('touchstart', (e) => {
    if (e.target && e.target.closest && e.target.closest('button, a, input, textarea')) return;
    // Block xterm's built-in touchstart/touchmove handler (which otherwise swallows scrolls and kills pinch).
    e.stopPropagation();
    const wasCoasting = Boolean(touchRaf);
    stopTouchCoast('touchstart');
    if (e.touches.length >= 2) {
      if (touchMoved) settleTouchScroll();
      touchId = null;
      touchMoved = false;
      touchStoppedCoast = false;
      multiTouchActive = true;
      zoomCooldownUntil = Date.now() + 650;
      touchDbgGesture = null;
      return;
    }
    // Fresh 1-finger touch: never allow a stale multiTouchActive flag from a Safari pinch to stick.
    multiTouchActive = false;
    touchStoppedCoast = wasCoasting;
    if (isOpticalZoomed() || isViewportPinchingOrBouncing()) {
      touchId = null;
      touchMoved = false;
      touchDbgGesture = null;
      return;
    }
    if (e.touches.length === 1) {
      const t = e.touches[0];
      const sess = activeSession();
      const buf = sess && sess.term && sess.term.buffer && sess.term.buffer.active;
      const curTab = state.terminals.find((x) => x.address === state.activeId);
      touchId = t.identifier;
      touchStartY = t.clientY;
      touchLastY = t.clientY;
      touchLastX = t.clientX;
      touchLastT = nowMs();
      touchMoved = false;
      touchVel = 0;
      touchAltAccum = 0;
      touchSamples = [{ t: touchLastT, y: t.clientY }];
      touchDbgGesture = {
        startT: touchLastT,
        startY: t.clientY,
        moves: 0,
        nonCancelable: 0,
        wheelSent: 0,
        bufType: buf ? buf.type : 'none',
        baseY: buf ? buf.baseY : -1,
        startVpY: buf ? buf.viewportY : -1,
        mouseMode: sessionMouseMode(sess),
        agent: (curTab && curTab.labels && curTab.labels['swarmbox.agent']) || (curTab && curTab.agent) || '',
      };
    } else {
      touchId = null;
      touchMoved = false;
    }
  }, { capture: true, passive: true });

  dom.termWrapEl.addEventListener('touchmove', (e) => {
    if (e.target && e.target.closest && e.target.closest('button, a, input, textarea')) return;
    // Always stop propagation so xterm's built-in handleTouchMove NEVER runs (neither on scroll nor on pinch!).
    e.stopPropagation();
    if (e.touches.length >= 2) {
      multiTouchActive = true;
      zoomCooldownUntil = Date.now() + 650;
      touchId = null;
      return;
    }
    if (multiTouchActive || isOpticalZoomed() || isViewportPinchingOrBouncing()) {
      touchId = null;
      return;
    }
    if (touchId === null || e.touches.length !== 1) {
      touchId = null;
      return;
    }
    const t = findTouchById(e.touches, touchId);
    if (!t) return;
    if (touchDbgGesture) {
      touchDbgGesture.moves += 1;
      if (!e.cancelable) touchDbgGesture.nonCancelable += 1;
    }
    // Wait until vertical motion exceeds TOUCH_DRAG_PX BEFORE calling preventDefault() so
    // finger-1 micro-jitter while finger-2 lands never aborts native iOS pinch-zoom!
    if (!touchMoved) {
      if (Math.abs(t.clientY - touchStartY) < TOUCH_DRAG_PX) return;
      touchMoved = true;
      touchSamples = [{ t: touchLastT, y: touchLastY }];
    }
    if (e.cancelable) e.preventDefault();
    const tt = nowMs();
    const dy = touchLastY - t.clientY;
    touchSamples.push({ t: tt, y: t.clientY });
    while (touchSamples.length > 2 && tt - touchSamples[0].t > TOUCH_VEL_WINDOW * 2) touchSamples.shift();
    applyTouchScrollPx(dy * TOUCH_DRAG_GAIN);
    touchLastY = t.clientY;
    touchLastX = t.clientX;
    touchLastT = tt;
  }, { capture: true, passive: false });

  dom.termWrapEl.addEventListener('touchcancel', () => {
    const g = touchDbgGesture;
    touchDbgGesture = null;
    multiTouchActive = false;
    touchId = null;
    touchMoved = false;
    touchStoppedCoast = false;
    stopTouchCoast('touchcancel');
    settleTouchScroll();
    if (g && g.moves > 0) {
      const sess = activeSession();
      const buf = sess && sess.term && sess.term.buffer && sess.term.buffer.active;
      logTouchDebug('scroll_cancel', {
        agent: g.agent,
        bufType: g.bufType,
        baseY: g.baseY,
        startVpY: g.startVpY,
        endVpY: buf ? buf.viewportY : -1,
        mouseMode: g.mouseMode,
        moves: g.moves,
        nonCancelable: g.nonCancelable,
        wheelSent: g.wheelSent,
        dt: Math.round(nowMs() - g.startT),
      });
    }
  }, { capture: true, passive: true });

  dom.termWrapEl.addEventListener('touchend', (e) => {
    if (e.target && e.target.closest && e.target.closest('button, a, input, textarea')) return;
    if (multiTouchActive) {
      e.stopPropagation();
      if (e.touches.length === 0) multiTouchActive = false;
      return;
    }
    const stoppedCoast = touchStoppedCoast;
    touchStoppedCoast = false;
    if ((touchMoved || stoppedCoast) && e.cancelable) {
      e.preventDefault();
      e.stopPropagation();
    }
    const moved = touchMoved;
    const now = nowMs();
    const rawVel = moved ? touchFlickVelocity() : 0;
    const flick = moved && Math.abs(rawVel) >= TOUCH_FLICK_MIN && (now - touchLastT) < 110;
    const g = touchDbgGesture;
    touchDbgGesture = null;
    touchId = null;
    touchMoved = false;
    let appliedVel = 0;
    if (flick) {
      const dir = Math.sign(rawVel);
      // Chained flicks in the same direction within 700ms build speed naturally (like iOS/Android)
      if (dir === touchCoastDir && (now - touchChainT) < 700) {
        touchChainBoost = Math.min(2.5, touchChainBoost + 0.45);
      } else {
        touchChainBoost = 1;
      }
      touchCoastDir = dir;
      touchChainT = now;
      const speed = Math.abs(rawVel);
      const accel = 1.2 + Math.min(2.4, Math.max(0, speed - 0.15) * 1.15);
      touchVel = Math.max(-TOUCH_MAX_VEL, Math.min(TOUCH_MAX_VEL, rawVel * accel * touchChainBoost));
      appliedVel = touchVel;
      startTouchCoast();
    } else {
      touchVel = 0;
      touchChainBoost = 1;
      if (moved) settleTouchScroll();
    }
    if (g && (moved || g.moves >= 1)) {
      const sess = activeSession();
      const buf = sess && sess.term && sess.term.buffer && sess.term.buffer.active;
      logTouchDebug('scroll_end', {
        agent: g.agent,
        bufType: g.bufType,
        baseY: g.baseY,
        startVpY: g.startVpY,
        endVpY: buf ? buf.viewportY : -1,
        mouseMode: g.mouseMode,
        dy: Math.round(g.startY - touchLastY),
        dt: Math.round(now - g.startT),
        moves: g.moves,
        nonCancelable: g.nonCancelable,
        rawVel: Number(rawVel.toFixed(3)),
        appliedVel: Number(appliedVel.toFixed(3)),
        flick,
        chainBoost: Number(touchChainBoost.toFixed(2)),
        wheelSent: g.wheelSent,
      });
    }
  }, { capture: true, passive: false });
}
