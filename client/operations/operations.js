/**
 * Starbridge — Operations Station (v0.08)
 *
 * The crew's analyst and coordinator. Processes raw data from Science and
 * other stations into tactical intelligence, and pushes concrete, measurable
 * bonuses to Weapons, Helm, Flight Ops, and other stations.
 *
 * Replaces the old Tactical Officer station.
 */

import { on, onStatusChange, send, connect } from '../shared/connection.js';
import { setStatusDot, setAlertLevel } from '../shared/ui_components.js';
import { initRoleBar } from '../shared/role_bar.js';

// ---------------------------------------------------------------------------
// DOM references
// ---------------------------------------------------------------------------

const statusDotEl   = document.querySelector('[data-status-dot]');
const missionLabel  = document.querySelector('[data-mission-label]');
const standbyEl     = document.getElementById('ops-standby');
const mainEl        = document.getElementById('ops-main');
const feedListEl    = document.getElementById('ops-feed-list');
const hullStatusEl  = document.getElementById('ops-hull-status');
const shieldStatusEl = document.getElementById('ops-shield-status');
const speedStatusEl = document.getElementById('ops-speed-status');

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

let _gameActive = false;

// ---------------------------------------------------------------------------
// Initialisation
// ---------------------------------------------------------------------------

function init() {
  const _send = connect({
    role: 'operations',
    onStatusChange: (connected) => {
      setStatusDot(statusDotEl, connected ? 'connected' : 'disconnected');
    },
    onMessage: (msg) => {
      handleMessage(msg.type, msg.payload);
    },
  });

  initRoleBar(_send, 'operations');
}

// ---------------------------------------------------------------------------
// Message handlers
// ---------------------------------------------------------------------------

function handleMessage(type, payload) {
  switch (type) {
    case 'game.started':
      _gameActive = true;
      standbyEl.classList.add('ops-standby--hidden');
      mainEl.style.display = '';
      if (payload.mission_name) {
        missionLabel.textContent = payload.mission_name.toUpperCase();
      }
      break;

    case 'game.over':
      _gameActive = false;
      standbyEl.classList.remove('ops-standby--hidden');
      mainEl.style.display = 'none';
      break;

    case 'ship.state':
      if (!_gameActive) return;
      updateShipStatus(payload);
      break;

    case 'ship.alert_changed':
      setAlertLevel(payload.alert_level);
      break;

    case 'operations.state':
      // Full ops state — updated per tick (placeholder for A.2–A.5)
      break;

    case 'sensor.contacts':
      // Contact data for the tactical map (placeholder for A.2)
      break;
  }
}

// ---------------------------------------------------------------------------
// UI updates
// ---------------------------------------------------------------------------

function updateShipStatus(payload) {
  if (hullStatusEl) {
    hullStatusEl.textContent = `HULL ${Math.round(payload.hull || 0)}`;
  }
  if (shieldStatusEl) {
    const shields = payload.shields || {};
    const total = (shields.fore || 0) + (shields.aft || 0) +
                  (shields.port || 0) + (shields.starboard || 0);
    shieldStatusEl.textContent = `SHIELDS ${Math.round(total)}`;
  }
  if (speedStatusEl) {
    speedStatusEl.textContent = `SPD ${Math.round(payload.velocity || 0)}`;
  }
}

// ---------------------------------------------------------------------------
// Feed (placeholder — A.5.2 populates this)
// ---------------------------------------------------------------------------

/**
 * Add an event to the information feed.
 * @param {string} source - Station tag (e.g., 'SCIENCE', 'WEAPONS')
 * @param {string} text - Event description
 * @param {'info'|'warning'|'critical'} severity
 */
// eslint-disable-next-line no-unused-vars
function addFeedEvent(source, text, severity = 'info') {
  if (!feedListEl) return;
  const li = document.createElement('li');
  li.className = `ops-feed-item ops-feed-item--${severity}`;
  const time = new Date().toLocaleTimeString('en-GB', { hour12: false });
  li.textContent = `[${time}] [${source}] ${text}`;
  feedListEl.appendChild(li);

  // Cap at 50 items
  while (feedListEl.children.length > 50) {
    feedListEl.removeChild(feedListEl.firstChild);
  }

  // Auto-scroll
  feedListEl.scrollTop = feedListEl.scrollHeight;
}

// ---------------------------------------------------------------------------
// Entry point
// ---------------------------------------------------------------------------

document.addEventListener('DOMContentLoaded', init);
