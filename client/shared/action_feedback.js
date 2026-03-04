/**
 * ActionFeedback — shared pending-action tracker.
 *
 * Tracks in-flight actions in a Map so that button renderers can show
 * an amber "in-progress" state that survives DOM re-renders.
 */

const _pending = new Map();   // key → { label, start, duration }

export function markPending(key, label, durationMs = 3000) {
  _pending.set(key, { label, start: performance.now(), duration: durationMs });
}

export function getPending(key) {
  const p = _pending.get(key);
  if (!p) return null;
  if (performance.now() - p.start > p.duration + 2000) {
    _pending.delete(key); return null;
  }
  return p;
}

export function clearPending(key) { _pending.delete(key); }

/** Apply pending state to a DOM button. Returns true if pending. */
export function applyPending(btn, key) {
  const p = getPending(key);
  if (!p) return false;
  btn.disabled = true;
  btn.textContent = p.label;
  btn.classList.add('btn--pending');
  if (p.duration > 0) {
    const elapsed = performance.now() - p.start;
    btn.style.setProperty('--action-duration', `${p.duration}ms`);
    btn.style.setProperty('--action-delay', `-${elapsed}ms`);
  }
  return true;
}
