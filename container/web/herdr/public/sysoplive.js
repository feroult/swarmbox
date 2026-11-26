/* The running goal of the Sysop, live (docs/sysop-brain-design.md 4.5): a reducer over the goal's events (the `sysop_events` the gateway
 * relays from goals/<id>/events.jsonl, in seq order) and what the panel draws from it. Pure: no DOM, so tests run it in Node.
 *
 * goal()                    a fresh state
 * apply(g, ev)              one event (an event at or below the last seq is ignored: a replay and a push may overlap)
 * pace(g, hidden)           one animation frame of the steady reveal: a fifth of what is left of each block, at least 3 characters
 *                           (about 0.3 s for a 1 KB burst); everything at once when the page is hidden. -> {changed, more}
 * showAll(g)                reveal everything (a replay: what already happened is shown at once)
 * line(g, fallback)         the live line: thinking, the action under way or waiting for you, a note or reply being written
 * parts(g, fallback)        {acts: [{ok, state, label, fn}], notes: [{text, streaming}], reply: {text, streaming} | null, line}
 */
(function (root) {
  'use strict';

  function goal() {
    return { seq: 0, blocks: new Map(), order: [], actions: new Map(), actOrder: [], thinking: false, callId: '', state: 'running' };
  }
  function block(g, id, kind) {
    let b = g.blocks.get(id);
    if (!b) {
      b = { kind, text: '', shown: 0, final: false };
      g.blocks.set(id, b);
      g.order.push(id);
    }
    return b;
  }
  function action(g, id, fn) {
    let a = g.actions.get(id);
    if (!a) {
      a = { fn, state: 'chosen', label: '', live: '', args: null, summary: '' };
      g.actions.set(id, a);
      g.actOrder.push(id);
    }
    return a;
  }
  const isReply = (fn) => fn === 'say' || fn === 'done';

  function apply(g, ev) {
    if (!ev || !Number.isInteger(ev.seq) || ev.seq <= g.seq) return false;
    g.seq = ev.seq;
    switch (ev.type) {
      case 'text.delta': block(g, ev.block, 'text').text += String(ev.text || ''); g.thinking = false; break;
      case 'text': block(g, ev.block, 'text').text = String(ev.text || ''); break;
      case 'say.delta': block(g, ev.block, 'say').text += String(ev.text || ''); g.thinking = false; break;
      case 'reply.delta': block(g, ev.block, 'reply').text += String(ev.text || ''); g.thinking = false; break;
      case 'thinking': g.thinking = ev.state === 'started'; break;
      case 'action.start':
        g.thinking = false;
        if (isReply(ev.fn)) block(g, ev.block, ev.fn === 'say' ? 'say' : 'reply');
        else { const a = action(g, ev.block, ev.fn); a.live = ev.live || a.live; }
        break;
      case 'action.args':
        if (!isReply(ev.fn)) { const a = action(g, ev.block, ev.fn); a.args = ev.args; a.label = ev.label || a.label; a.live = ev.live || a.live; }
        break;
      case 'call':
        g.callId = String(ev.id || '');
        if (!isReply(ev.fn)) {
          const a = action(g, g.callId, ev.fn);
          a.state = 'running';
          a.label = a.label || ev.label || ev.fn;
          a.live = ev.live || a.live;
        }
        break;
      case 'approval': {
        const a = g.actions.get(String(ev.id || ''));
        if (a) a.state = ev.state === 'waiting' ? 'waiting' : (ev.state === 'approved' || ev.state === 'allowed' ? 'running' : 'refused');
        break;
      }
      case 'say': {
        const b = g.blocks.get(g.callId) || block(g, `say:${ev.seq}`, 'say');
        b.kind = 'say';
        b.text = String(ev.text || '');
        b.final = true;
        break;
      }
      case 'done': {
        const b = g.blocks.get(g.callId) || block(g, `reply:${ev.seq}`, 'reply');
        b.kind = 'reply';
        b.text = String(ev.summary || '');
        b.final = true;
        break;
      }
      case 'call.end': {
        const a = g.actions.get(String(ev.id || ''));
        if (a) { if (a.state !== 'refused') a.state = ev.ok ? 'ok' : 'err'; a.summary = String(ev.summary || ''); }
        const b = g.blocks.get(String(ev.id || ''));
        if (b) b.final = true;
        break;
      }
      case 'state': g.state = String(ev.state || ''); break;
      default: break;
    }
    return true;
  }

  function pace(g, hidden) {
    let changed = false;
    let more = false;
    for (const b of g.blocks.values()) {
      if (b.shown < b.text.length) {
        b.shown = hidden ? b.text.length : Math.min(b.text.length, b.shown + Math.max(3, Math.ceil((b.text.length - b.shown) / 5)));
        changed = true;
        if (b.shown < b.text.length) more = true;
      } else if (b.shown > b.text.length) {
        b.shown = b.text.length;
        changed = true;
      }
    }
    return { changed, more };
  }

  function showAll(g) {
    for (const b of g.blocks.values()) b.shown = b.text.length;
  }

  function line(g, fallback) {
    // the summary of done is in: what follows (the CLI's extra turn, the end of the process) is the goal finishing
    if (g.order.some((id) => { const b = g.blocks.get(id); return b.kind === 'reply' && b.final; })) return 'Finishing…';
    if (g.thinking) return 'Thinking…';
    if (g.actOrder.length) {
      const a = g.actions.get(g.actOrder[g.actOrder.length - 1]);
      if (a.state === 'waiting') return `Waiting for you · ${a.live || a.label || a.fn}`;
      if (a.state === 'chosen' || a.state === 'running') return a.live || a.label || a.fn;
    }
    const writing = g.order.map((id) => g.blocks.get(id)).reverse().find((b) => !b.final && b.text);
    if (writing) return writing.kind === 'say' ? 'Writing a note…' : 'Writing…';
    // between an answered call and the model's next block the model is at work: not the label of the call that ended
    if (g.actOrder.length || g.order.length) return 'Thinking…';
    return fallback || 'Working…';
  }

  function parts(g, fallback) {
    const acts = g.actOrder.map((id) => {
      const a = g.actions.get(id);
      return { ok: a.state !== 'err' && a.state !== 'refused', state: a.state, label: a.label || a.live || a.fn, fn: a.fn };
    });
    const notes = [];
    let reply = null;
    let replyIsDone = false;
    for (const id of g.order) {
      const b = g.blocks.get(id);
      if (!b.text) continue;
      const shown = b.text.slice(0, Math.max(0, Math.min(b.text.length, b.shown)));
      const part = { text: shown, streaming: !b.final || shown.length < b.text.length };
      if (b.kind === 'say') notes.push(part);
      else if (b.kind === 'reply') { reply = part; replyIsDone = true; }
      else if (!replyIsDone) reply = part;      // the text a CLI writes after done (its extra turn) never covers the summary of done
    }
    return { acts, notes, reply, line: line(g, fallback) };
  }

  const api = { goal, apply, pace, showAll, line, parts };
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.SbSysopLive = api;
})(typeof window !== 'undefined' ? window : globalThis);
