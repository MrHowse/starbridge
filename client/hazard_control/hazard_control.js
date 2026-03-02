/**
 * Starbridge — Hazard Control Station
 *
 * Displays the ship interior as a room grid with severity-coded cards.
 * Allows the HazCon officer to dispatch/cancel Damage Control Teams (DCTs).
 *
 * Server messages received:
 *   game.started          — reveal station UI; store interior layout
 *   hazard_control.state  — rooms (non-normal only) + active DCTs
 *   ship.alert_changed    — update alert colour
 *   ship.hull_hit         — hit-flash border
 *   game.over             — victory/defeat overlay
 *
 * Server messages sent:
 *   lobby.claim_role            { role: 'hazard_control', player_name }
 *   hazard_control.dispatch_dct { room_id }
 *   hazard_control.cancel_dct   { room_id }
 */

import { initConnection } from '../shared/connection.js';
import { initRoleBar } from '../shared/role_bar.js';
import { initCrewRoster } from '../shared/crew_roster.js';
import {
  setStatusDot, setAlertLevel, showGameOver,
} from '../shared/ui_components.js';

import { SoundBank } from '../shared/audio.js';
import '../shared/audio_ambient.js';
import '../shared/audio_events.js';
import { wireButtonSounds } from '../shared/audio_ui.js';

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const HIT_FLASH_MS = 500;

// Deck sort order for rendering the grid top-to-bottom
const DECK_ORDER = ['bridge', 'sensors', 'weapons', 'shields', 'engineering', 'medical'];

// Human-readable deck labels
const DECK_LABELS = {
  bridge:      'Bridge',
  sensors:     'Sensors',
  weapons:     'Weapons',
  shields:     'Shields',
  engineering: 'Engineering',
  medical:     'Medical',
};

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

let _allRooms     = {};   // room_id → {id, name, deck, connections, ...}
let _dcState      = null; // {rooms: {room_id: {name,state,deck}}, active_dcts: {room_id: 0.0-1.0}}
let _selectedId   = null; // currently selected room_id
let _send         = null;

// ---------------------------------------------------------------------------
// DOM refs
// ---------------------------------------------------------------------------

const statusDotEl   = document.querySelector('[data-status-dot]');
const statusLabelEl = document.querySelector('[data-status-label]');
const standbyEl     = document.querySelector('[data-standby]');
const dcMainEl      = document.querySelector('[data-dc-main]');
const missionLabelEl = document.getElementById('mission-label');
const stationEl     = document.querySelector('.station-container');

const roomGridEl    = document.getElementById('dc-room-grid');
const selectedEl    = document.getElementById('dc-selected-room');
const activeDctsEl  = document.getElementById('dc-active-dcts');
const teamCountEl   = document.getElementById('dc-team-count');

// ---------------------------------------------------------------------------
// Rendering
// ---------------------------------------------------------------------------

function getRoomState(roomId) {
  if (!_dcState) return 'normal';
  return (_dcState.rooms[roomId] && _dcState.rooms[roomId].state) || 'normal';
}

function getDctProgress(roomId) {
  if (!_dcState || !_dcState.active_dcts[roomId]) return null;
  return _dcState.active_dcts[roomId];
}

function renderRoomGrid() {
  if (Object.keys(_allRooms).length === 0) {
    roomGridEl.innerHTML = '<p class="text-dim">Interior layout unavailable.</p>';
    return;
  }

  // Group by deck
  const byDeck = {};
  for (const [id, room] of Object.entries(_allRooms)) {
    const deck = room.deck || 'unknown';
    if (!byDeck[deck]) byDeck[deck] = [];
    byDeck[deck].push({ ...room, id });
  }

  roomGridEl.innerHTML = '';

  const deckOrder = DECK_ORDER.filter(d => byDeck[d]).concat(
    Object.keys(byDeck).filter(d => !DECK_ORDER.includes(d))
  );

  for (const deck of deckOrder) {
    const rooms = byDeck[deck];
    if (!rooms) continue;

    // Deck separator label
    const sep = document.createElement('div');
    sep.className = 'dc-deck-label text-label';
    sep.textContent = DECK_LABELS[deck] || deck.toUpperCase();
    roomGridEl.appendChild(sep);

    for (const room of rooms) {
      const state      = getRoomState(room.id);
      const progress   = getDctProgress(room.id);
      const isSelected = room.id === _selectedId;

      const card = document.createElement('div');
      let cardClass = `dc-room-card dc-room-card--${state}`;
      if (isSelected) cardClass += ' dc-room-card--selected';
      card.className   = cardClass;
      card.dataset.rid = room.id;

      const dctBadge = progress !== null
        ? `<span class="dc-room-status dc-status--dct">DCT ${Math.round(progress * 100)}%</span>`
        : `<span class="dc-room-status dc-status--${state}">${state.toUpperCase()}</span>`;

      card.innerHTML = `
        <span class="dc-room-name">${room.name || room.id}</span>
        ${dctBadge}
      `;

      card.addEventListener('click', () => selectRoom(room.id));
      roomGridEl.appendChild(card);
    }
  }
}

function renderSelectedRoom() {
  if (!_selectedId || !_allRooms[_selectedId]) {
    selectedEl.innerHTML = '<p class="text-dim">Select a room to dispatch a DCT.</p>';
    return;
  }

  const room     = _allRooms[_selectedId];
  const state    = getRoomState(_selectedId);
  const progress = getDctProgress(_selectedId);
  const canDispatch = state !== 'normal' && state !== 'decompressed' && progress === null;
  const canCancel   = progress !== null;

  selectedEl.innerHTML = `
    <h3>${room.name || _selectedId}</h3>
    <p class="dc-room-detail">Deck: ${DECK_LABELS[room.deck] || room.deck || '—'}</p>
    <p class="dc-room-detail">Status: <span class="dc-status--${state}" style="padding:1px 4px;border-radius:2px">${state.toUpperCase()}</span></p>
    ${progress !== null ? `<p class="dc-room-detail">Repair progress: ${Math.round(progress * 100)}%</p>` : ''}
    <button class="dc-dispatch-btn" id="dc-btn-dispatch" ${canDispatch ? '' : 'disabled'}>
      DISPATCH DCT
    </button>
    <button class="dc-cancel-btn" id="dc-btn-cancel" ${canCancel ? '' : 'disabled'}>
      CANCEL DCT
    </button>
  `;

  document.getElementById('dc-btn-dispatch')?.addEventListener('click', () => {
    if (!_send || !_selectedId) return;
    _send('hazard_control.dispatch_dct', { room_id: _selectedId });
  });

  document.getElementById('dc-btn-cancel')?.addEventListener('click', () => {
    if (!_send || !_selectedId) return;
    _send('hazard_control.cancel_dct', { room_id: _selectedId });
  });
}

function renderActiveDCTs() {
  if (!_dcState) return;
  const dcts     = _dcState.active_dcts || {};
  const rooms    = _dcState.rooms || {};
  const entries  = Object.entries(dcts);
  const active   = Object.keys(dcts).length;

  teamCountEl.textContent = `${active} ACTIVE`;

  if (entries.length === 0) {
    activeDctsEl.innerHTML = '<p class="text-dim">No teams deployed.</p>';
    return;
  }

  activeDctsEl.innerHTML = '';
  for (const [roomId, progress] of entries) {
    const roomInfo  = rooms[roomId] || _allRooms[roomId] || {};
    const pct       = Math.round(progress * 100);
    const entry = document.createElement('div');
    entry.className = 'dc-dct-entry';
    entry.innerHTML = `
      <div><span class="dc-dct-entry__room">${roomInfo.name || roomId}</span>
           <span class="text-dim" style="float:right">${(roomInfo.state || 'repairing').toUpperCase()}</span></div>
      <div class="dc-dct-progress">
        <div class="dc-dct-progress__fill" style="width:${pct}%"></div>
      </div>
    `;
    activeDctsEl.appendChild(entry);
  }
}

function render() {
  renderRoomGrid();
  renderSelectedRoom();
  renderActiveDCTs();
}

// ---------------------------------------------------------------------------
// Interaction
// ---------------------------------------------------------------------------

function selectRoom(roomId) {
  _selectedId = (_selectedId === roomId) ? null : roomId;
  render();
}

// ---------------------------------------------------------------------------
// Message handlers
// ---------------------------------------------------------------------------

function handleGameStarted(payload) {
  standbyEl.style.display = 'none';
  dcMainEl.style.display  = 'grid';
  if (payload.mission_name) missionLabelEl.textContent = payload.mission_name.toUpperCase();

  // Populate _allRooms from interior_layout
  if (payload.interior_layout) {
    _allRooms = payload.interior_layout;
  }

  SoundBank.setAmbient('life_support', { active: true });
  render();
}

function handleDcState(payload) {
  _dcState = payload;
  render();
}

function handleHullHit() {
  SoundBank.play('hull_hit');
  stationEl.classList.add('hit');
  setTimeout(() => stationEl.classList.remove('hit'), HIT_FLASH_MS);
}

function handleMessage(msg) {
  switch (msg.type) {
    case 'game.started':
      handleGameStarted(msg.payload);
      break;
    case 'hazard_control.state':
      handleDcState(msg.payload);
      break;
    case 'ship.alert_changed':
      setAlertLevel(msg.payload.level);
      SoundBank.setAmbient('alert_level', { level: msg.payload.level });
      break;
    case 'ship.hull_hit':
      handleHullHit();
      break;
    case 'game.over':
      SoundBank.play(msg.payload.result === 'victory' ? 'victory' : 'defeat');
      SoundBank.stopAmbient('life_support');
      SoundBank.stopAmbient('alert_level');
      standbyEl.style.display = 'flex';
      dcMainEl.style.display  = 'none';
      showGameOver(msg.payload.result, msg.payload.stats);
      break;
  }
}

// ---------------------------------------------------------------------------
// Initialisation
// ---------------------------------------------------------------------------

document.addEventListener('DOMContentLoaded', () => {
  const { send } = initConnection({
    role: 'hazard_control',
    onStatusChange: (connected) => {
      setStatusDot(statusDotEl, connected ? 'connected' : 'disconnected');
      statusLabelEl.textContent = connected ? 'CONNECTED' : 'DISCONNECTED';
    },
    onMessage: handleMessage,
  });

  _send = send;
  initRoleBar(send, 'hazard_control');
  initCrewRoster(send);
  SoundBank.init();
  wireButtonSounds(SoundBank);
});
