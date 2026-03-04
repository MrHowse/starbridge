/**
 * Render Scheduler — throttle + interaction guard for DOM-heavy stations.
 *
 * Prevents click-eating caused by DOM destruction between mousedown/mouseup
 * and reduces visual flicker from high-frequency server state updates.
 */

// ---------------------------------------------------------------------------
// createRenderScheduler — leading + trailing throttle
// ---------------------------------------------------------------------------

/**
 * Returns a `schedule()` function that coalesces calls to `renderFn`.
 *
 * Behaviour:
 *   - First call in a burst fires immediately (leading edge).
 *   - Subsequent calls within `intervalMs` are coalesced; the final state
 *     always renders after the interval expires (trailing edge).
 *
 * @param {Function} renderFn  — the render function to throttle
 * @param {number}   intervalMs — minimum interval between renders (default 333 → 3/sec)
 * @returns {Function} schedule — call this instead of renderFn directly
 */
export function createRenderScheduler(renderFn, intervalMs = 333) {
  let lastFired = 0;
  let timerId = null;

  return function schedule() {
    const now = Date.now();
    const elapsed = now - lastFired;

    if (elapsed >= intervalMs) {
      // Leading edge — fire immediately
      lastFired = now;
      if (timerId) { clearTimeout(timerId); timerId = null; }
      renderFn();
    } else {
      // Trailing edge — coalesce; schedule for remaining time
      if (timerId) clearTimeout(timerId);
      timerId = setTimeout(() => {
        timerId = null;
        lastFired = Date.now();
        renderFn();
      }, intervalMs - elapsed);
    }
  };
}

// ---------------------------------------------------------------------------
// guardInteraction — defer render while mousedown is active
// ---------------------------------------------------------------------------

/**
 * Wraps `renderFn` so that renders are deferred while a mousedown is held
 * inside `container`. On mouseup the deferred render fires after a
 * microtask so the click event completes first.
 *
 * @param {Function}    renderFn  — the render function to guard
 * @param {HTMLElement}  container — interactive container element
 * @returns {Function}  guarded   — drop-in replacement for renderFn
 */
export function guardInteraction(renderFn, container) {
  if (!container) return renderFn;  // no container → passthrough

  let mouseHeld = false;
  let deferred = false;

  container.addEventListener('mousedown', () => {
    mouseHeld = true;
    deferred = false;
  }, true);  // capture phase

  const release = () => {
    if (!mouseHeld) return;
    mouseHeld = false;
    if (deferred) {
      deferred = false;
      // Fire after microtask so the click event completes first
      setTimeout(renderFn, 0);
    }
  };

  window.addEventListener('mouseup', release);
  window.addEventListener('pointercancel', release);

  return function guarded() {
    if (mouseHeld) {
      deferred = true;
      return;
    }
    renderFn();
  };
}
