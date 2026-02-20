/**
 * station_base.js — Convenience wrapper for stations that use initSharedUI.
 *
 * Re-exports on() and send() from connection.js and provides initSharedUI()
 * which handles the connection lifecycle, status UI, role claiming, and
 * game.started / game.over callbacks.
 *
 * Usage:
 *   import { initSharedUI, on, send } from '../shared/station_base.js';
 *   initSharedUI({ role: 'flight_ops', onGameStarted(p) {...}, onGameOver() {...} });
 *   on('flight_ops.state', payload => { ... });
 */

export { on, send } from './connection.js';
import { on, onStatusChange, send, connect } from './connection.js';

/**
 * Initialise shared station lifecycle.
 *
 * @param {{
 *   role: string,
 *   onConnect?: function(): void,
 *   onDisconnect?: function(): void,
 *   onGameStarted?: function(object): void,
 *   onGameOver?: function(object): void,
 * }} config
 */
export function initSharedUI({
  role,
  onConnect,
  onDisconnect,
  onGameStarted,
  onGameOver,
} = {}) {
  // Status dot + label update.
  onStatusChange((status) => {
    const dot   = document.querySelector('[data-status-dot]');
    const label = document.querySelector('[data-status-label]');
    const connected = status === 'connected';
    if (dot) {
      dot.className = 'status-dot ' + (connected ? 'status-dot--connected' : 'status-dot--disconnected');
    }
    if (label) {
      label.textContent = status.toUpperCase();
    }
    if (connected && onConnect) onConnect();
    if (!connected && onDisconnect) onDisconnect();
  });

  // Claim role on connect.
  on('lobby.welcome', () => {
    const name = sessionStorage.getItem('player_name') || role.toUpperCase();
    send('lobby.claim_role', { role, player_name: name });
  });

  // Game lifecycle hooks.
  if (onGameStarted) on('game.started', onGameStarted);
  if (onGameOver)    on('game.over',    onGameOver);

  connect();
}
