/**
 * Starbridge — Shared Puzzle Renderer
 *
 * Manages the puzzle overlay lifecycle on any station page.
 * Import and call initPuzzleRenderer(sendFn) once in the station's init().
 *
 * Handles:
 *   puzzle.started       — create overlay, dynamically load puzzle type module
 *   puzzle.result        — show success/failure, remove overlay after 2s
 *   puzzle.assist_applied — forward to active puzzle module
 *
 * The puzzle type module (e.g. sequence_match.js) must export:
 *   init(container, puzzleData)  — render puzzle UI into container div
 *   applyAssist(assistData)      — update UI with assist data
 *   getSubmission()              — return the player's current answer dict
 *   destroy()                   — clean up (called before overlay removed)
 */

import { on } from './connection.js';

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

let _send = null;
let _activePuzzle = null;  // { puzzleId, module, overlayEl, timerFill, timeLimit, startTime }

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

/**
 * Initialise the puzzle renderer for a station.
 * Call once in the station's init() before connect().
 * @param {Function} sendFn — the station's send() function from connection.js
 */
export function initPuzzleRenderer(sendFn) {
  _send = sendFn;
  on('puzzle.started',        handlePuzzleStarted);
  on('puzzle.result',         handlePuzzleResult);
  on('puzzle.assist_applied', handleAssistApplied);
}

// ---------------------------------------------------------------------------
// Message handlers
// ---------------------------------------------------------------------------

async function handlePuzzleStarted(payload) {
  // Dismiss any existing puzzle overlay (shouldn't happen, but be safe).
  if (_activePuzzle) {
    _closeOverlay(false);
  }

  const { puzzle_id, label, type, time_limit, data } = payload;

  // Dynamically load the puzzle type module.
  let mod;
  try {
    mod = await import(`./puzzle_types/${type}.js`);
  } catch (err) {
    console.error('[puzzle_renderer] Failed to load puzzle type:', type, err);
    return;
  }

  // Build the overlay DOM.
  const overlayEl = _buildOverlay(label, time_limit, mod, puzzle_id);
  const stationEl = document.querySelector('.station-container');
  if (!stationEl) {
    console.error('[puzzle_renderer] .station-container not found');
    return;
  }
  stationEl.appendChild(overlayEl);

  // Initialise the puzzle type in its content div.
  const contentEl = overlayEl.querySelector('.puzzle-content');
  mod.init(contentEl, data);

  // Store active puzzle state.
  _activePuzzle = {
    puzzleId: puzzle_id,
    module: mod,
    overlayEl,
    timerFill: overlayEl.querySelector('.puzzle-timer-bar__fill'),
    timeLimit: time_limit,
    startTime: performance.now(),
    successMessage: data.success_message || 'COMPLETE',
  };

  // Start the client-side timer animation loop.
  _tickTimer();
}

function handlePuzzleResult(payload) {
  if (!_activePuzzle || _activePuzzle.puzzleId !== payload.puzzle_id) return;

  const success = payload.success;
  const resultEl = _activePuzzle.overlayEl.querySelector('.puzzle-result-msg');

  // Show result message (success text is puzzle-type-specific, set from data).
  if (resultEl) {
    resultEl.textContent = success
      ? (_activePuzzle.successMessage || 'COMPLETE')
      : (payload.reason === 'timeout' ? 'TIME EXPIRED' : 'INCORRECT');
    resultEl.className = `puzzle-result-msg text-header ${
      success ? 'puzzle-result-msg--success' : 'puzzle-result-msg--failure'
    }`;
    resultEl.style.display = 'block';
  }

  // Freeze the timer fill at its current position (don't remove overlay yet).
  if (_activePuzzle.timerFill) {
    _activePuzzle.timerFill.style.transition = 'none';
  }

  // Remove overlay after 2 seconds.
  setTimeout(() => _closeOverlay(true), 2000);
}

function handleAssistApplied(payload) {
  if (!_activePuzzle || _activePuzzle.puzzleId !== payload.puzzle_id) return;
  _activePuzzle.module.applyAssist(payload.data);
}

// ---------------------------------------------------------------------------
// Overlay construction
// ---------------------------------------------------------------------------

function _buildOverlay(label, timeLimit, mod, puzzleId) {
  const div = document.createElement('div');
  div.className = 'puzzle-overlay';

  div.innerHTML = `
    <div class="puzzle-box panel">
      <div class="panel__header puzzle-box__header">
        <span class="text-label">${label.toUpperCase().replace(/_/g, ' ')}</span>
        <span class="text-data text-dim puzzle-time-display">0:${String(Math.round(timeLimit)).padStart(2, '0')}</span>
      </div>
      <div class="puzzle-timer-bar">
        <div class="puzzle-timer-bar__fill" style="width:100%"></div>
      </div>
      <div class="puzzle-content"></div>
      <div class="puzzle-result-msg" style="display:none"></div>
      <div class="puzzle-footer">
        <button class="fire-btn puzzle-submit-btn" style="flex:1">SUBMIT</button>
        <button class="fire-btn fire-btn--small puzzle-assist-btn">REVEAL HINT</button>
      </div>
    </div>
  `;

  // Wire submit button.
  div.querySelector('.puzzle-submit-btn').addEventListener('click', () => {
    if (!_activePuzzle) return;
    const submission = _activePuzzle.module.getSubmission();
    _send('puzzle.submit', { puzzle_id: puzzleId, submission });
  });

  // Wire assist button.
  div.querySelector('.puzzle-assist-btn').addEventListener('click', () => {
    if (!_activePuzzle) return;
    _send('puzzle.request_assist', {
      puzzle_id: puzzleId,
      assist_type: 'reveal_start',
      data: { count: 1 },
    });
  });

  return div;
}

// ---------------------------------------------------------------------------
// Timer animation
// ---------------------------------------------------------------------------

function _tickTimer() {
  if (!_activePuzzle) return;

  const { timerFill, timeLimit, startTime, overlayEl } = _activePuzzle;
  const elapsed = (performance.now() - startTime) / 1000;
  const pct = Math.max(0, (1 - elapsed / timeLimit) * 100);

  // Update fill width.
  if (timerFill) {
    timerFill.style.width = `${pct}%`;
    // Colour-shift as time runs out.
    timerFill.className = pct > 50
      ? 'puzzle-timer-bar__fill'
      : pct > 25
        ? 'puzzle-timer-bar__fill puzzle-timer-bar__fill--warn'
        : 'puzzle-timer-bar__fill puzzle-timer-bar__fill--danger';
  }

  // Update numeric display.
  const remaining = Math.max(0, timeLimit - elapsed);
  const mins = Math.floor(remaining / 60);
  const secs = Math.floor(remaining % 60);
  const timeEl = overlayEl.querySelector('.puzzle-time-display');
  if (timeEl) {
    timeEl.textContent = `${mins}:${String(secs).padStart(2, '0')}`;
  }

  if (pct > 0 && _activePuzzle) {
    requestAnimationFrame(_tickTimer);
  }
}

// ---------------------------------------------------------------------------
// Cleanup
// ---------------------------------------------------------------------------

function _closeOverlay(callDestroy) {
  if (!_activePuzzle) return;
  if (callDestroy && _activePuzzle.module) {
    _activePuzzle.module.destroy();
  }
  _activePuzzle.overlayEl.remove();
  _activePuzzle = null;
}
