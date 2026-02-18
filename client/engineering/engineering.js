/**
 * Engineering Station — Phase 1 placeholder.
 * Connects to server, displays mission briefing on game.started.
 * Full implementation: Phase 3 (power allocation, damage control, repair).
 */

import { on, onStatusChange, connect } from '../shared/connection.js';
import { setStatusDot } from '../shared/ui_components.js';

const statusDotEl    = document.querySelector('[data-status-dot]');
const statusLabelEl  = document.querySelector('[data-status-label]');
const standbyEl      = document.querySelector('[data-standby]');
const briefingEl     = document.querySelector('[data-briefing]');
const missionNameEl  = document.querySelector('[data-mission-name]');
const briefingTextEl = document.querySelector('[data-briefing-text]');

function init() {
  onStatusChange((status) => {
    setStatusDot(statusDotEl, status);
    statusLabelEl.textContent = status.toUpperCase();
  });

  on('game.started', (payload) => {
    missionNameEl.textContent  = payload.mission_name;
    briefingTextEl.textContent = payload.briefing_text;
    standbyEl.style.display    = 'none';
    briefingEl.style.display   = '';
  });

  connect();
}

document.addEventListener('DOMContentLoaded', init);
