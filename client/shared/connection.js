/**
 * Starbridge — WebSocket Connection Manager
 *
 * Manages a single persistent connection to the server.
 * Provides on/send API and reconnects automatically with exponential backoff.
 *
 * Usage:
 *   import { on, onStatusChange, send, connect } from '../shared/connection.js';
 *   connect();
 *   on('lobby.state', (payload) => { ... });
 *   send('lobby.claim_role', { role: 'helm', player_name: 'Alice' });
 */

const BASE_BACKOFF_MS = 1000;
const MAX_BACKOFF_MS  = 30_000;

/** @type {WebSocket|null} */
let socket = null;
let reconnectAttempts = 0;

/** @type {Map<string, Array<function(object, object): void>>} */
const handlers = new Map();

/** @type {Array<function(string): void>} */
const statusHandlers = [];

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

/**
 * Register a handler for a specific message type.
 * Multiple handlers per type are supported.
 * @param {string} type
 * @param {function(object, object): void} callback - Called with (payload, fullMessage)
 */
export function on(type, callback) {
  if (!handlers.has(type)) handlers.set(type, []);
  handlers.get(type).push(callback);
}

/**
 * Register a handler for connection status changes.
 * @param {function(string): void} callback - Called with 'connected'|'reconnecting'|'disconnected'
 */
export function onStatusChange(callback) {
  statusHandlers.push(callback);
}

/**
 * Send a message to the server.
 * Silently drops the message if the socket is not open.
 * @param {string} type
 * @param {object} [payload={}]
 */
export function send(type, payload = {}) {
  if (!socket || socket.readyState !== WebSocket.OPEN) {
    console.warn(`[connection] Cannot send '${type}': socket not open`);
    return;
  }
  socket.send(JSON.stringify({
    type,
    payload,
    timestamp: Date.now() / 1000,
  }));
}

/**
 * Open the WebSocket connection. Call once on page load.
 * Subsequent calls (from reconnect timer) reuse the same logic.
 */
export function connect() {
  const url = `ws://${window.location.host}/ws`;
  socket = new WebSocket(url);

  socket.addEventListener('open', _onOpen);
  socket.addEventListener('message', _onMessage);
  socket.addEventListener('close', _onClose);
  socket.addEventListener('error', _onError);
}

// ---------------------------------------------------------------------------
// Private handlers
// ---------------------------------------------------------------------------

function _onOpen() {
  reconnectAttempts = 0;
  _setStatus('connected');
}

function _onMessage(event) {
  let msg;
  try {
    msg = JSON.parse(event.data);
  } catch (e) {
    console.error('[connection] Failed to parse message:', e);
    return;
  }
  const callbacks = handlers.get(msg.type);
  if (callbacks) {
    callbacks.forEach(cb => cb(msg.payload, msg));
  }
}

function _onClose() {
  _setStatus('reconnecting');
  _scheduleReconnect();
}

function _onError(e) {
  console.error('[connection] WebSocket error:', e);
}

function _setStatus(status) {
  statusHandlers.forEach(cb => cb(status));
}

function _scheduleReconnect() {
  const delay = Math.min(BASE_BACKOFF_MS * Math.pow(2, reconnectAttempts), MAX_BACKOFF_MS);
  reconnectAttempts++;
  console.log(`[connection] Reconnecting in ${delay}ms (attempt ${reconnectAttempts})...`);
  setTimeout(connect, delay);
}
