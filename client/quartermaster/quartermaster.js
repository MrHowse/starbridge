/**
 * Starbridge — Quartermaster Station
 *
 * Manages ship resources, vendor trades, salvage operations, and rationing.
 *
 * Server messages received:
 *   game.started         — reveal station UI
 *   ship.state           — resource levels, credits
 *   vendor.*             — vendor events
 *   negotiation.*        — negotiation events
 *   salvage.*            — salvage events
 *   rationing.*          — rationing events
 *   ship.alert_changed   — update alert colour
 *   ship.hull_hit        — hit-flash border
 *   game.over            — victory/defeat overlay
 *
 * Server messages sent:
 *   lobby.claim_role     { role: 'quartermaster', player_name }
 *   rationing.*          — ration level changes
 *   vendor.*             — trade actions
 *   salvage.*            — salvage actions
 *   negotiation.*        — negotiation actions
 */

import { initConnection } from '../shared/connection.js';
import { initRoleBar } from '../shared/role_bar.js';
import {
  setStatusDot, setAlertLevel, showGameOver,
} from '../shared/ui_components.js';

// ---------------------------------------------------------------------------
// DOM references
// ---------------------------------------------------------------------------

const statusDotEl   = document.getElementById('status-dot');
const creditsEl     = document.getElementById('credits-display');
const resourceList  = document.getElementById('resource-list');
const rationBtns    = document.getElementById('ration-btns');
const vendorList    = document.getElementById('vendor-list');
const salvageList   = document.getElementById('salvage-list');
const logEl         = document.getElementById('qm-log');
const stationEl     = document.querySelector('.station-container');

let _send = null;

// ---------------------------------------------------------------------------
// Resource display
// ---------------------------------------------------------------------------

const RESOURCE_LABELS = {
  fuel:          'FUEL',
  provisions:    'PROVISIONS',
  ammunition:    'AMMUNITION',
  medical:       'MEDICAL',
  repair_parts:  'REPAIR PARTS',
  dc_supplies:   'DC SUPPLIES',
  drone_parts:   'DRONE PARTS',
};

function renderResources(resources) {
  if (!resources || !resourceList) return;
  resourceList.innerHTML = '';
  for (const [key, label] of Object.entries(RESOURCE_LABELS)) {
    const val = resources[key];
    if (val === undefined) continue;
    const cap = resources[key + '_max'] || 100;
    const pct = cap > 0 ? (val / cap) * 100 : 0;
    const row = document.createElement('div');
    row.className = 'qm-resource-row';
    const valClass = pct < 15 ? 'qm-resource-row__value--critical'
                   : pct < 35 ? 'qm-resource-row__value--low'
                   : 'qm-resource-row__value';
    row.innerHTML = `<span class="qm-resource-row__name">${label}</span>`
                  + `<span class="${valClass}">${Math.round(val)} / ${Math.round(cap)}</span>`;
    resourceList.appendChild(row);
  }
}

// ---------------------------------------------------------------------------
// Ration controls
// ---------------------------------------------------------------------------

const RATION_LEVELS = ['emergency', 'reduced', 'normal', 'generous'];
let currentRation = 'normal';

function renderRationButtons() {
  if (!rationBtns) return;
  rationBtns.innerHTML = '';
  for (const level of RATION_LEVELS) {
    const btn = document.createElement('button');
    btn.className = 'qm-ration-btn' + (level === currentRation ? ' qm-ration-btn--active' : '');
    btn.textContent = level.toUpperCase();
    btn.addEventListener('click', () => {
      if (_send) _send('rationing.set_level', { level });
    });
    rationBtns.appendChild(btn);
  }
}

// ---------------------------------------------------------------------------
// Event log
// ---------------------------------------------------------------------------

function addLog(text) {
  if (!logEl) return;
  const entry = document.createElement('div');
  entry.className = 'qm-log__entry';
  entry.textContent = text;
  logEl.prepend(entry);
  // Keep log size manageable
  while (logEl.children.length > 50) logEl.lastChild.remove();
}

// ---------------------------------------------------------------------------
// Message handling
// ---------------------------------------------------------------------------

function handleMessage(msg) {
  switch (msg.type) {
    case 'game.started':
      addLog('Game started. Quartermaster station online.');
      break;

    case 'ship.state':
      if (msg.payload.resources) renderResources(msg.payload.resources);
      if (msg.payload.credits !== undefined && creditsEl) {
        creditsEl.textContent = `CREDITS: ${Math.round(msg.payload.credits)}`;
      }
      if (msg.payload.ration_level) {
        currentRation = msg.payload.ration_level;
        renderRationButtons();
      }
      break;

    case 'ship.alert_changed':
      setAlertLevel(msg.payload.level);
      break;

    case 'ship.hull_hit':
      if (stationEl) {
        stationEl.classList.add('hit');
        setTimeout(() => stationEl.classList.remove('hit'), 400);
      }
      break;

    case 'game.over':
      showGameOver(msg.payload);
      break;

    default:
      // Vendor, negotiation, salvage, rationing events → log
      if (msg.type.startsWith('vendor.') ||
          msg.type.startsWith('negotiation.') ||
          msg.type.startsWith('salvage.') ||
          msg.type.startsWith('rationing.')) {
        addLog(`[${msg.type}] ${JSON.stringify(msg.payload).slice(0, 80)}`);
      }
      break;
  }
}

// ---------------------------------------------------------------------------
// Initialisation
// ---------------------------------------------------------------------------

document.addEventListener('DOMContentLoaded', () => {
  const { send } = initConnection({
    role: 'quartermaster',
    onStatusChange: (connected) => {
      if (statusDotEl) setStatusDot(statusDotEl, connected ? 'connected' : 'disconnected');
    },
    onMessage: handleMessage,
  });

  _send = send;
  initRoleBar(send, 'quartermaster');
  renderRationButtons();
});
