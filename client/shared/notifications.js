/**
 * Starbridge — Cross-station Crew Notification System
 *
 * Provides a crew.notify sender and crew.notification receiver for all
 * stations. Injects its own DOM elements and CSS so no HTML changes are
 * needed per station.
 *
 * Usage:
 *   import { initNotifications } from '../shared/notifications.js';
 *   // Inside init(), after connect():
 *   initNotifications(send, 'helm');
 *
 * Automatically registers the crew.notification handler via connection.js.
 *
 * Creates (appended to document.body):
 *   - Toast container   — bottom-right, auto-dismiss after 4 s
 *   - Notification log  — floating panel, last 20 entries, toggled by LOG button
 *   - Send panel        — preset messages + custom text, toggled by COMMS button
 */

import { on } from './connection.js';

// ---------------------------------------------------------------------------
// Config
// ---------------------------------------------------------------------------

const MAX_LOG          = 20;
const TOAST_DURATION   = 4000;   // ms before toast starts fading
const TOAST_FADE       = 400;    // ms for CSS fade-out transition

const PRESETS = [
  'BRACE FOR IMPACT',
  'ALL STOP — STAND BY',
  'SHIELDS CRITICAL',
  'NEED ENGINEERING NOW',
  'WEAPONS: OPEN FIRE',
  'SCIENCE: SCAN TARGET',
  'MEDICAL: STAND BY',
];

// ---------------------------------------------------------------------------
// Module state
// ---------------------------------------------------------------------------

let _send     = null;
let _fromRole = 'crew';
let _log      = [];            // array of { message, from_role, time }

let _toastContainer = null;
let _logPanel       = null;
let _logList        = null;
let _sendPanel      = null;
let _initialised    = false;

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

/**
 * Initialise the notification system for a station.
 * Safe to call multiple times — subsequent calls are no-ops.
 *
 * @param {function} send       - WebSocket send helper from connection.js
 * @param {string}   fromRole   - This station's role label (e.g. 'helm')
 */
export function initNotifications(send, fromRole = 'crew') {
  _send     = send;
  _fromRole = fromRole;

  if (_initialised) return;
  _initialised = true;

  _injectCSS();
  _buildToastContainer();
  _buildLogPanel();
  _buildControlButtons();
  _buildSendPanel();

  on('crew.notification', _handleNotification);
  on('ship.reactor_shutdown', _handleReactorShutdown);
  on('resources.critical', _handleResourceCritical);
  on('ship.resupplied', (p) => {
    const detail = p.resource ? (p.resource.toUpperCase().replace(/_/g, ' ')) : 'supplies';
    _showAlertToast('RESUPPLY', `${detail} replenished`, 'positive', 5000);
  });
  on('crew.reassignment_complete', () => {
    _showAlertToast('CREW', 'Reassignment complete', 'positive', 3000);
  });
  on('hazard.status', _handleHazardStatus);
  on('station.reinforcement_call', () => {
    _showAlertToast('TACTICAL', 'Enemy station calling reinforcements!', 'warning', 5000);
  });
  on('station.component_destroyed', (p) => {
    const comp = p.component ? p.component.toUpperCase() : 'COMPONENT';
    _showAlertToast('TACTICAL', `Enemy station: ${comp} destroyed`, 'positive', 3000);
  });
  on('station.destroyed', () => {
    _showAlertToast('TACTICAL', 'ENEMY STATION DESTROYED', 'positive', 5000);
  });
  on('station.captured', () => {
    _showAlertToast('TACTICAL', 'Station captured!', 'positive', 5000);
  });
}

// ---------------------------------------------------------------------------
// Message handler
// ---------------------------------------------------------------------------

function _handleNotification(payload) {
  const { message, from_role } = payload;
  const entry = { message, from_role, time: Date.now() };

  _log.push(entry);
  if (_log.length > MAX_LOG) _log.shift();
  _refreshLogUI();
  _showToast(message, from_role);
}

// ---------------------------------------------------------------------------
// System alert handlers
// ---------------------------------------------------------------------------

function _handleReactorShutdown(payload) {
  const systems = (payload.emergency_systems || []).join(', ').toUpperCase() || 'NONE';
  _showAlertToast(
    'REACTOR SHUTDOWN',
    `All systems losing power. Emergency: ${systems}`,
    'critical',
    10000,
  );
}

function _handleResourceCritical(payload) {
  const res = (payload.resource || 'UNKNOWN').toUpperCase().replace(/_/g, ' ');
  const pct = payload.fraction != null ? Math.round(payload.fraction * 100) : '?';
  _showAlertToast('RESOURCE', `${res} CRITICAL (${pct}%)`, 'warning', 6000);
}

function _handleHazardStatus(payload) {
  const types = payload.active_types || [];
  if (!types.length) return;
  const list = types.map(t => t.toUpperCase().replace(/_/g, ' ')).join(', ');
  _showAlertToast('HAZARD', list, 'warning', 5000);
}

function _showAlertToast(label, message, severity, duration) {
  if (!_toastContainer) return;
  const cls = severity === 'critical' ? 'notify-toast--critical'
    : severity === 'positive' ? 'notify-toast--positive'
    : 'notify-toast--warning';
  const toast = document.createElement('div');
  toast.className = `notify-toast ${cls}`;
  toast.innerHTML =
    `<span class="notify-toast__role">[${_esc(label)}]</span>` +
    `<span class="notify-toast__msg">${_esc(message)}</span>`;
  _toastContainer.appendChild(toast);
  const dur = duration || TOAST_DURATION;
  setTimeout(() => {
    toast.classList.add('notify-toast--fade');
    setTimeout(() => toast.remove(), TOAST_FADE);
  }, dur - TOAST_FADE);
}

// ---------------------------------------------------------------------------
// Toast
// ---------------------------------------------------------------------------

function _showToast(message, fromRole) {
  if (!_toastContainer) return;

  const toast = document.createElement('div');
  toast.className = 'notify-toast';
  toast.innerHTML =
    `<span class="notify-toast__role">[${_esc(fromRole.toUpperCase())}]</span>` +
    `<span class="notify-toast__msg">${_esc(message)}</span>`;

  _toastContainer.appendChild(toast);

  // Start fade after TOAST_DURATION − TOAST_FADE ms, then remove.
  setTimeout(() => {
    toast.classList.add('notify-toast--fade');
    setTimeout(() => toast.remove(), TOAST_FADE);
  }, TOAST_DURATION - TOAST_FADE);
}

// ---------------------------------------------------------------------------
// Log panel
// ---------------------------------------------------------------------------

function _buildLogPanel() {
  _logPanel = document.createElement('div');
  _logPanel.className = 'notify-log-panel notify-hidden';
  _logPanel.innerHTML =
    `<div class="notify-log-panel__header">` +
      `<span class="notify-label">COMM LOG</span>` +
      `<button class="notify-close-btn">✕</button>` +
    `</div>` +
    `<div class="notify-log-list"></div>`;
  document.body.appendChild(_logPanel);

  _logList = _logPanel.querySelector('.notify-log-list');
  _logPanel.querySelector('.notify-close-btn').addEventListener('click', () => {
    _logPanel.classList.add('notify-hidden');
  });
}

function _refreshLogUI() {
  if (!_logList) return;
  _logList.innerHTML = '';
  for (const entry of [..._log].reverse()) {
    const timeStr = new Date(entry.time)
      .toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    const row = document.createElement('div');
    row.className = 'notify-log-row';
    row.innerHTML =
      `<span class="notify-log-row__time">${timeStr}</span>` +
      `<span class="notify-log-row__role">${_esc(entry.from_role.toUpperCase())}</span>` +
      `<span class="notify-log-row__msg">${_esc(entry.message)}</span>`;
    _logList.appendChild(row);
  }
}

// ---------------------------------------------------------------------------
// Control buttons (COMMS + LOG)
// ---------------------------------------------------------------------------

function _buildControlButtons() {
  // COMMS button — opens send panel
  const commsBtn = document.createElement('button');
  commsBtn.className = 'notify-comms-btn';
  commsBtn.textContent = 'COMMS';
  commsBtn.addEventListener('click', () => {
    _sendPanel.classList.toggle('notify-hidden');
    _logPanel.classList.add('notify-hidden');
  });
  document.body.appendChild(commsBtn);

  // LOG button — opens log panel
  const logBtn = document.createElement('button');
  logBtn.className = 'notify-log-btn';
  logBtn.textContent = 'LOG';
  logBtn.addEventListener('click', () => {
    _logPanel.classList.toggle('notify-hidden');
    _sendPanel.classList.add('notify-hidden');
  });
  document.body.appendChild(logBtn);
}

// ---------------------------------------------------------------------------
// Send panel
// ---------------------------------------------------------------------------

function _buildSendPanel() {
  _sendPanel = document.createElement('div');
  _sendPanel.className = 'notify-send-panel notify-hidden';

  const presetHtml = PRESETS
    .map(msg => `<button class="notify-preset-btn">${_esc(msg)}</button>`)
    .join('');

  _sendPanel.innerHTML =
    `<div class="notify-send-panel__header">` +
      `<span class="notify-label">CREW COMMS — ${_fromRole.toUpperCase()}</span>` +
      `<button class="notify-close-btn">✕</button>` +
    `</div>` +
    `<div class="notify-presets">${presetHtml}</div>` +
    `<div class="notify-custom">` +
      `<input class="notify-custom-input" type="text" maxlength="120" placeholder="Custom message…" />` +
      `<button class="notify-custom-send">SEND</button>` +
    `</div>`;

  document.body.appendChild(_sendPanel);

  _sendPanel.querySelector('.notify-close-btn').addEventListener('click', () => {
    _sendPanel.classList.add('notify-hidden');
  });

  _sendPanel.querySelectorAll('.notify-preset-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      _doSend(btn.textContent);
      _sendPanel.classList.add('notify-hidden');
    });
  });

  const input   = _sendPanel.querySelector('.notify-custom-input');
  const sendBtn = _sendPanel.querySelector('.notify-custom-send');

  sendBtn.addEventListener('click', () => {
    const msg = input.value.trim();
    if (msg) {
      _doSend(msg);
      input.value = '';
      _sendPanel.classList.add('notify-hidden');
    }
  });

  input.addEventListener('keydown', e => {
    if (e.key === 'Enter') sendBtn.click();
  });
}

// ---------------------------------------------------------------------------
// Toast container
// ---------------------------------------------------------------------------

function _buildToastContainer() {
  _toastContainer = document.createElement('div');
  _toastContainer.className = 'notify-toast-container';
  document.body.appendChild(_toastContainer);
}

// ---------------------------------------------------------------------------
// Internal helpers
// ---------------------------------------------------------------------------

function _doSend(message) {
  if (_send) _send('crew.notify', { message, from_role: _fromRole });
}

function _esc(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

// ---------------------------------------------------------------------------
// Injected CSS
// ---------------------------------------------------------------------------

function _injectCSS() {
  if (document.getElementById('notify-styles')) return;
  const style = document.createElement('style');
  style.id = 'notify-styles';
  style.textContent = `
/* ── Notification system ── */

.notify-hidden { display: none !important; }

/* Toast container — stacks in bottom-right corner */
.notify-toast-container {
  position: fixed;
  bottom: 2.5rem;
  right: 0.75rem;
  z-index: 800;
  display: flex;
  flex-direction: column-reverse;
  gap: 0.35rem;
  pointer-events: none;
}

.notify-toast {
  background: rgba(10, 10, 10, 0.92);
  border: 1px solid rgba(0, 255, 65, 0.5);
  padding: 0.4rem 0.7rem;
  font-family: "Share Tech Mono", monospace;
  font-size: 0.875rem;
  display: flex;
  gap: 0.5rem;
  align-items: baseline;
  max-width: 320px;
  opacity: 1;
  transition: opacity 0.4s ease;
  box-shadow: 0 0 8px rgba(0, 255, 65, 0.2);
}

.notify-toast--fade {
  opacity: 0;
}

.notify-toast--critical {
  border-color: rgba(255, 60, 60, 0.8);
  box-shadow: 0 0 12px rgba(255, 60, 60, 0.35);
  max-width: 100%;
}
.notify-toast--critical .notify-toast__role { color: #ff4444; }
.notify-toast--critical .notify-toast__msg  { color: #ffcccc; }

.notify-toast--warning {
  border-color: rgba(255, 180, 0, 0.7);
  box-shadow: 0 0 10px rgba(255, 180, 0, 0.25);
}
.notify-toast--warning .notify-toast__role { color: #ffb400; }
.notify-toast--warning .notify-toast__msg  { color: #ffe0a0; }

.notify-toast--positive {
  border-color: rgba(0, 200, 80, 0.7);
  box-shadow: 0 0 10px rgba(0, 200, 80, 0.25);
}
.notify-toast--positive .notify-toast__role { color: #00c850; }
.notify-toast--positive .notify-toast__msg  { color: #b0ffc0; }

.notify-toast__role {
  color: rgba(0, 255, 65, 0.7);
  flex-shrink: 0;
  font-size: 0.875rem;
  letter-spacing: 0.08em;
}

.notify-toast__msg {
  color: #e0ffe0;
  word-break: break-word;
}

/* COMMS + LOG floating buttons — bottom-right */
.notify-comms-btn,
.notify-log-btn {
  position: fixed;
  bottom: 0.4rem;
  z-index: 750;
  background: transparent;
  border: 1px solid rgba(0, 255, 65, 0.35);
  color: rgba(0, 255, 65, 0.6);
  font-family: "Share Tech Mono", monospace;
  font-size: 0.8rem;
  letter-spacing: 0.12em;
  padding: 0.2rem 0.55rem;
  cursor: pointer;
  transition: border-color 0.2s, color 0.2s;
}

.notify-comms-btn { right: 0.4rem; }
.notify-log-btn   { right: 4.4rem; }

.notify-comms-btn:hover,
.notify-log-btn:hover {
  border-color: rgba(0, 255, 65, 0.8);
  color: #00ff41;
}

/* Send panel */
.notify-send-panel {
  position: fixed;
  bottom: 2.0rem;
  right: 0.4rem;
  z-index: 760;
  width: 280px;
  background: rgba(10, 10, 10, 0.96);
  border: 1px solid rgba(0, 255, 65, 0.4);
  font-family: "Share Tech Mono", monospace;
  box-shadow: 0 0 12px rgba(0, 255, 65, 0.15);
}

.notify-send-panel__header,
.notify-log-panel__header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0.3rem 0.6rem;
  border-bottom: 1px solid rgba(0, 255, 65, 0.2);
}

.notify-label {
  font-size: 0.8rem;
  letter-spacing: 0.12em;
  color: rgba(0, 255, 65, 0.7);
  text-transform: uppercase;
}

.notify-close-btn {
  background: transparent;
  border: none;
  color: rgba(0, 255, 65, 0.5);
  cursor: pointer;
  font-family: inherit;
  font-size: 0.875rem;
  padding: 0 0.2rem;
}
.notify-close-btn:hover { color: #00ff41; }

.notify-presets {
  display: flex;
  flex-direction: column;
  gap: 0;
}

.notify-preset-btn {
  background: transparent;
  border: none;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
  color: rgba(255, 255, 255, 0.65);
  font-family: "Share Tech Mono", monospace;
  font-size: 0.875rem;
  letter-spacing: 0.06em;
  text-align: left;
  padding: 0.35rem 0.65rem;
  cursor: pointer;
  transition: background 0.15s, color 0.15s;
}
.notify-preset-btn:hover {
  background: rgba(0, 255, 65, 0.07);
  color: #00ff41;
}

.notify-custom {
  display: flex;
  gap: 0.3rem;
  padding: 0.4rem 0.5rem;
  border-top: 1px solid rgba(0, 255, 65, 0.15);
}

.notify-custom-input {
  flex: 1;
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid rgba(0, 255, 65, 0.25);
  color: #e0ffe0;
  font-family: "Share Tech Mono", monospace;
  font-size: 0.875rem;
  padding: 0.2rem 0.4rem;
  outline: none;
}
.notify-custom-input:focus {
  border-color: rgba(0, 255, 65, 0.6);
}

.notify-custom-send {
  background: transparent;
  border: 1px solid rgba(0, 255, 65, 0.35);
  color: rgba(0, 255, 65, 0.7);
  font-family: "Share Tech Mono", monospace;
  font-size: 0.8rem;
  letter-spacing: 0.08em;
  padding: 0.2rem 0.45rem;
  cursor: pointer;
  transition: border-color 0.2s, color 0.2s;
}
.notify-custom-send:hover {
  border-color: #00ff41;
  color: #00ff41;
}

/* Log panel */
.notify-log-panel {
  position: fixed;
  bottom: 2.0rem;
  right: 0.4rem;
  z-index: 760;
  width: 340px;
  max-height: 240px;
  background: rgba(10, 10, 10, 0.96);
  border: 1px solid rgba(0, 255, 65, 0.4);
  font-family: "Share Tech Mono", monospace;
  box-shadow: 0 0 12px rgba(0, 255, 65, 0.15);
  display: flex;
  flex-direction: column;
}

.notify-log-list {
  overflow-y: auto;
  flex: 1;
  scrollbar-width: thin;
  scrollbar-color: rgba(0, 255, 65, 0.3) transparent;
}

.notify-log-row {
  display: grid;
  grid-template-columns: auto auto 1fr;
  gap: 0.5rem;
  align-items: baseline;
  padding: 0.25rem 0.6rem;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
  font-size: 0.8rem;
}

.notify-log-row__time {
  color: rgba(0, 255, 65, 0.4);
  white-space: nowrap;
}

.notify-log-row__role {
  color: rgba(0, 255, 65, 0.7);
  white-space: nowrap;
  font-size: 0.8rem;
  letter-spacing: 0.06em;
}

.notify-log-row__msg {
  color: rgba(255, 255, 255, 0.7);
  word-break: break-word;
}
`;
  document.head.appendChild(style);
}
