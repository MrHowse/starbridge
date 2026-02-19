/**
 * Starbridge — Lobby Client
 *
 * Handles role selection, player list, and game launch.
 * Communicates with the server via the shared connection module.
 */

import { on, onStatusChange, send, connect } from '../shared/connection.js';
import { setStatusDot, redirectToStation } from '../shared/ui_components.js';

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

/** @type {string|null} Server-assigned connection ID, received in lobby.welcome */
let myConnectionId = null;

/** @type {string|null} Role currently held by this client */
let myRole = null;

const ROLES = ['captain', 'helm', 'weapons', 'engineering', 'science', 'medical'];
const ROLE_LABELS = {
  captain:     'CAPTAIN',
  helm:        'HELM',
  weapons:     'WEAPONS',
  engineering: 'ENGINEERING',
  science:     'SCIENCE',
  medical:     'MEDICAL',
};

// ---------------------------------------------------------------------------
// DOM references
// ---------------------------------------------------------------------------

const statusDotEl    = document.querySelector('[data-status-dot]');
const statusLabelEl  = document.querySelector('[data-status-label]');
const callsignInput  = document.querySelector('[data-callsign-input]');
const rolesGridEl    = document.querySelector('[data-roles-grid]');
const launchPanelEl  = document.querySelector('[data-launch-panel]');
const launchStatusEl = document.querySelector('[data-launch-status]');
const launchBtnEl       = document.querySelector('[data-launch-btn]');
const missionSelectEl   = document.querySelector('[data-mission-select]');
const sessionLabelEl    = document.querySelector('[data-session-label]');

// ---------------------------------------------------------------------------
// Initialisation
// ---------------------------------------------------------------------------

function init() {
  buildRoleCards();

  onStatusChange((status) => {
    setStatusDot(statusDotEl, status);
    statusLabelEl.textContent = status.toUpperCase();
  });

  on('lobby.welcome', handleWelcome);
  on('lobby.state',   handleLobbyState);
  on('lobby.error',   handleLobbyError);
  on('game.started',  handleGameStarted);

  launchBtnEl.addEventListener('click', () => {
    const mission_id = missionSelectEl ? missionSelectEl.value : 'sandbox';
    send('lobby.start_game', { mission_id });
  });

  connect();
}

// ---------------------------------------------------------------------------
// Role card DOM construction
// ---------------------------------------------------------------------------

function buildRoleCards() {
  for (const role of ROLES) {
    const card = document.createElement('div');
    card.className = 'role-card panel';
    card.dataset.roleCard = role;

    card.innerHTML = `
      <div class="panel__header role-card__header">
        <span class="text-header">${ROLE_LABELS[role]}</span>
      </div>
      <div class="role-card__body">
        <span class="role-card__occupant text-data" data-occupant="${role}">VACANT</span>
        <div class="role-card__actions">
          <button class="btn btn--primary role-card__claim" data-claim="${role}">CLAIM</button>
          <button class="btn role-card__release" data-release="${role}">RELEASE</button>
        </div>
      </div>
    `;

    card.querySelector(`[data-claim="${role}"]`).addEventListener('click', () => claimRole(role));
    card.querySelector(`[data-release="${role}"]`).addEventListener('click', releaseRole);

    rolesGridEl.appendChild(card);
  }
}

// ---------------------------------------------------------------------------
// Actions
// ---------------------------------------------------------------------------

function claimRole(role) {
  const callsign = callsignInput.value.trim();
  if (!callsign || callsign.length > 20) {
    callsignInput.focus();
    callsignInput.classList.add('lobby-input--error');
    setTimeout(() => callsignInput.classList.remove('lobby-input--error'), 1500);
    return;
  }
  send('lobby.claim_role', { role, player_name: callsign });
}

function releaseRole() {
  send('lobby.release_role', {});
}

// ---------------------------------------------------------------------------
// Message handlers
// ---------------------------------------------------------------------------

/** @param {{ connection_id: string, is_host: boolean }} payload */
function handleWelcome(payload) {
  myConnectionId = payload.connection_id;
  updateLaunchPanel(payload.is_host);
}

/** @param {{ roles: Object, host: string, session_id: string }} payload */
function handleLobbyState(payload) {
  const { roles, host, session_id } = payload;

  sessionLabelEl.textContent = `SESSION ${session_id.slice(0, 8).toUpperCase()}`;

  const isHost = myConnectionId !== null && host === myConnectionId;
  updateLaunchPanel(isHost);

  // Determine which role belongs to this client by matching callsign.
  // This is intentionally simple for Phase 1 — works fine on a LAN where
  // callsign collisions are unlikely. Phase 2+ can use server-sent role info.
  const callsign = callsignInput.value.trim();
  myRole = null;

  for (const role of ROLES) {
    const playerName  = roles[role];
    const occupantEl  = document.querySelector(`[data-occupant="${role}"]`);
    const claimBtn    = document.querySelector(`[data-claim="${role}"]`);
    const releaseBtn  = document.querySelector(`[data-release="${role}"]`);
    const card        = document.querySelector(`[data-role-card="${role}"]`);

    if (playerName) {
      occupantEl.textContent = playerName;
      card.classList.add('role-card--occupied');
    } else {
      occupantEl.textContent = 'VACANT';
      card.classList.remove('role-card--occupied');
    }

    const isMine = callsign && playerName === callsign;
    if (isMine) myRole = role;

    card.classList.toggle('role-card--mine', Boolean(isMine));
    claimBtn.style.display  = (!playerName || isMine) ? '' : 'none';
    releaseBtn.style.display = isMine ? '' : 'none';
    claimBtn.disabled = Boolean(playerName && !isMine);
  }

  // Enable launch if host and at least one role is claimed
  const anyRoleClaimed = Object.values(roles).some(v => v !== null);
  launchBtnEl.disabled = !(isHost && anyRoleClaimed);
}

/** @param {{ message: string }} payload */
function handleLobbyError(payload) {
  // Brief visual flash on the input to signal rejection
  callsignInput.classList.add('lobby-input--error');
  setTimeout(() => callsignInput.classList.remove('lobby-input--error'), 1500);
  console.warn('[lobby] Error:', payload.message);
}

/** @param {{ mission_id: string, mission_name: string, briefing_text: string }} payload */
function handleGameStarted(payload) {
  console.log(`[lobby] Game started: ${payload.mission_name}`);
  // Persist callsign so station pages can re-claim the role on reconnect.
  const callsign = callsignInput.value.trim();
  if (callsign) sessionStorage.setItem('player_name', callsign);
  // Freeze all interactive controls before navigating away.
  document.querySelectorAll('.btn').forEach(btn => { btn.disabled = true; });
  launchStatusEl.textContent = `LAUNCHING — ${payload.mission_name.toUpperCase()}`;
  redirectToStation(myRole);
}

// ---------------------------------------------------------------------------
// UI helpers
// ---------------------------------------------------------------------------

/** @param {boolean} isHost */
function updateLaunchPanel(isHost) {
  launchPanelEl.style.display = isHost ? '' : 'none';
  launchStatusEl.textContent  = isHost ? 'YOU ARE HOST — SELECT MISSION AND LAUNCH' : '';
}

// ---------------------------------------------------------------------------
// Entry point
// ---------------------------------------------------------------------------

document.addEventListener('DOMContentLoaded', init);
