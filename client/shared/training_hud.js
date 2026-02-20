/**
 * Training HUD — shared module for all stations.
 *
 * Registers a handler for the "training.hint" message and displays a
 * dismissible hint banner at the top of the station.  The banner auto-
 * dismisses after 12 seconds and the player can also dismiss it manually.
 *
 * Usage:
 *   import { initTrainingHud } from '../shared/training_hud.js';
 *   // Call once per station after the WebSocket connection is set up:
 *   initTrainingHud(connection);
 *
 * "connection" must expose an on(type, handler) method compatible with
 * the shared initConnection pattern used across all stations.
 */

const HINT_DURATION_MS = 12_000;

let _bannerEl = null;
let _dismissTimer = null;

/**
 * Create and inject the training hint banner element into the page.
 * Called once on first hint receipt.
 */
function _ensureBanner() {
  if (_bannerEl) return _bannerEl;

  const banner = document.createElement('div');
  banner.id = 'training-hint-banner';
  banner.style.cssText = [
    'position: fixed',
    'top: 0',
    'left: 0',
    'right: 0',
    'z-index: 9999',
    'background: rgba(0, 180, 120, 0.92)',
    'color: #000',
    'font-family: var(--font-mono, monospace)',
    'font-size: 0.82rem',
    'padding: 8px 48px 8px 16px',
    'display: none',
    'align-items: center',
    'gap: 12px',
    'border-bottom: 2px solid #00ff88',
    'box-shadow: 0 2px 12px rgba(0,255,136,0.3)',
  ].join('; ');

  const label = document.createElement('span');
  label.style.cssText = 'font-weight: bold; letter-spacing: 0.08em; flex-shrink: 0';
  label.textContent = '[ TRAINING ]';

  const text = document.createElement('span');
  text.id = 'training-hint-text';
  text.style.cssText = 'flex: 1';

  const close = document.createElement('button');
  close.textContent = '✕';
  close.title = 'Dismiss hint';
  close.style.cssText = [
    'position: absolute',
    'right: 8px',
    'top: 50%',
    'transform: translateY(-50%)',
    'background: transparent',
    'border: none',
    'color: #000',
    'cursor: pointer',
    'font-size: 1rem',
    'padding: 0 6px',
    'line-height: 1',
  ].join('; ');
  close.addEventListener('click', _dismiss);

  banner.appendChild(label);
  banner.appendChild(text);
  banner.appendChild(close);
  document.body.insertBefore(banner, document.body.firstChild);

  _bannerEl = banner;
  return banner;
}

function _showHint(text) {
  const banner = _ensureBanner();
  const textEl = document.getElementById('training-hint-text');
  if (textEl) textEl.textContent = text;

  banner.style.display = 'flex';

  // Clear any existing auto-dismiss timer.
  if (_dismissTimer !== null) {
    clearTimeout(_dismissTimer);
  }
  _dismissTimer = setTimeout(_dismiss, HINT_DURATION_MS);
}

function _dismiss() {
  if (_bannerEl) _bannerEl.style.display = 'none';
  if (_dismissTimer !== null) {
    clearTimeout(_dismissTimer);
    _dismissTimer = null;
  }
}

/**
 * Initialise the training HUD for a station.
 *
 * @param {object} connection - The station's WebSocket connection object,
 *   exposing an `on(type, handler)` method.
 */
export function initTrainingHud(connection) {
  connection.on('training.hint', (payload) => {
    if (payload && payload.text) {
      _showHint(payload.text);
    }
  });
}
